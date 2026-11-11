"""Tier 0 / Tier 1 runners and recording wrappers for the generation eval.

Nothing here edits ``generator.py``, ``worker.py`` or ``pipeline.py``: the wrappers sit in front of
the verifier and generator objects that ``ProofPipeline`` already accepts (the same pattern as
``tools/mathlib_index/hint_ab.py``). Per-stage times come from the ``elapsed_ms`` that
``GeneratedDraft/Sketch/Proof`` already carry; token counts from ``usage.usage_scope``.

Tier 0  replay stored Lean source through the real verifier (no model, no cost).
Tier 1  stored Draft -> fresh Sketch (model) -> ``verify_sketch`` (``sorry`` allowed).
Full    ``run_pipeline_once`` around a caller-built ``ProofPipeline`` (Tier 2/3; spends money).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from collections.abc import Callable, Iterable
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pals_agent.artifacts import safe_artifact_segment
from pals_agent.evals.records import ATTEMPT_SCHEMA, RUN_SCHEMA, JsonlSink

# List prices in USD per million tokens, copied from tools/mathlib_index/hint_ab.py. Cached input is
# not discounted, so cost is an UPPER estimate. gpt-6.1-terra's billed price is unconfirmed.
USD_PER_MTOK = {"gpt-6-luna": (0.10, 0.50), "gpt-6.1-terra": (1.25, 5.00)}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def estimate_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    price = USD_PER_MTOK.get(model)
    if price is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1e6


def interleaved_schedule(
    problem_ids: Iterable[str], arms: list[str], repeats: int, seed: int = 20261110
) -> list[tuple[str, str, int]]:
    """(problem, arm, repeat) order: arms of one problem run back-to-back, arm order is
    counterbalanced, and problems are reshuffled per repeat, so a slow hour hits both arms."""
    rng = random.Random(seed)
    ids = sorted(problem_ids)
    plan: list[tuple[str, str, int]] = []
    for repeat in range(1, repeats + 1):
        order = ids[:]
        rng.shuffle(order)
        for i, pid in enumerate(order):
            rotated = arms[(i + repeat) % len(arms) :] + arms[: (i + repeat) % len(arms)]
            plan.extend((pid, arm, repeat) for arm in rotated)
    return plan


@dataclass(slots=True)
class Scope:
    """Mutable identity of the run in flight; the wrappers read it for every row they write."""

    run_id: str
    sink: JsonlSink
    arm: str = ""
    problem_id: str = ""
    repeat: int = 1
    ordinal: int = 0
    usage: list[dict[str, Any]] = field(default_factory=list)
    # Summed elapsed_ms per stage for the run in flight (concurrent candidates add up).
    stage_ms: dict[str, int] = field(default_factory=dict)

    def reset(self, problem_id: str, arm: str, repeat: int) -> None:
        self.problem_id, self.arm, self.repeat, self.ordinal, self.usage = (
            problem_id,
            arm,
            repeat,
            0,
            [],
        )
        self.stage_ms = {}

    def attempt(self, stage: str, **kw: Any) -> dict[str, Any]:
        self.ordinal += 1
        row = {
            "schema": ATTEMPT_SCHEMA,
            "run_id": self.run_id,
            "problem_id": self.problem_id,
            "arm": self.arm,
            "repeat": self.repeat,
            "ordinal": self.ordinal,
            "stage": stage,
            "started_at": None,
            "ended_at": None,
            "elapsed_ms": None,
            "success": None,
            "error_codes": [],
            "model": None,
            "effort": None,
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
            "diagnostic_count": 0,
            "diagnostics": [],
            "lean_sha256": None,
            "lean_path": None,
        }
        row.update(kw)
        self.stage_ms[stage] = self.stage_ms.get(stage, 0) + int(row.get("elapsed_ms") or 0)
        self.sink.write(row)
        return row

    def on_usage(self, row: dict[str, Any]) -> None:
        self.usage.append(dict(row))

    def usage_totals(self, since: int = 0) -> dict[str, int]:
        rows = self.usage[since:]
        return {
            k: sum(int(r.get(k, 0) or 0) for r in rows)
            for k in ("input_tokens", "cached_input_tokens", "output_tokens")
        }


def _diagnostic_summary(result: Any) -> tuple[list[str], int, list[dict[str, Any]]]:
    diags = list(getattr(result, "diagnostics", []) or [])
    errors = [d for d in diags if getattr(d, "severity", "") == "error"]
    codes = sorted({str(d.code) for d in errors if getattr(d, "code", None)})
    brief = [
        {
            "code": getattr(d, "code", None),
            "severity": getattr(d, "severity", None),
            "line": getattr(d, "line", None),
            # A Lean message can quote the problem's own terms: keep only a digest of it.
            "message_sha256": hashlib.sha256(
                str(getattr(d, "message", "")).encode("utf-8")
            ).hexdigest(),
        }
        for d in errors[:5]
    ]
    return codes, len(errors), brief


@dataclass(slots=True)
class RecordingVerifier:
    """Wraps a verifier; one attempt row per check, Lean source saved for every failed check."""

    inner: Any
    scope: Scope
    stage_for_verify: str = "lean_check"

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def _record(self, stage: str, code: str, call: Callable[[str], Any]) -> Any:
        started, t0 = now_iso(), time.monotonic()
        result = call(code)
        elapsed = int((time.monotonic() - t0) * 1000)
        codes, count, brief = _diagnostic_summary(result)
        digest, path = (None, None)
        if not result.success:
            digest, path = self.scope.sink.save_lean(
                self.scope.run_id, self.scope.problem_id, self.scope.ordinal + 1, code
            )
        self.scope.attempt(
            stage,
            started_at=started,
            ended_at=now_iso(),
            elapsed_ms=elapsed,
            success=bool(result.success),
            error_codes=codes,
            diagnostic_count=count,
            diagnostics=brief,
            lean_sha256=digest,
            lean_path=path,
        )
        return result

    def verify(self, lean_code: str) -> Any:
        return self._record(self.stage_for_verify, lean_code, self.inner.verify)

    def verify_sketch(self, lean_code: str) -> Any:
        return self._record("sketch_check", lean_code, self.inner.verify_sketch)


_STAGE_METHODS = (
    "generate_draft",
    "generate_sketch",
    "generate_proof",
    "generate_direct_proof",
    "generate_patch",
)


@dataclass(slots=True)
class RecordingGenerator:
    """Wraps generate/repair; emits draft/sketch/prove rows from the elapsed_ms the generator
    already reports (start times are derived by laying the stages end to end)."""

    inner: Any
    scope: Scope

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def __getattribute__(self, name: str) -> Any:
        # Expose a stage method only when the wrapped generator has it: ProofPipeline decides
        # staged vs generate() by probing these names (pipeline._staged_generator).
        if name in _STAGE_METHODS and not callable(
            getattr(object.__getattribute__(self, "inner"), name, None)
        ):
            raise AttributeError(name)
        return object.__getattribute__(self, name)

    def _emit(
        self, stage: str, part: Any, start_ms: float, t_start: float, since: int | None = None
    ) -> None:
        if part is None:
            return
        ms = int(getattr(part, "elapsed_ms", 0) or 0)
        tokens = self.scope.usage_totals(since) if since is not None else {}
        self.scope.attempt(
            stage,
            started_at=datetime.fromtimestamp(t_start + start_ms / 1000, UTC).isoformat(
                timespec="milliseconds"
            ),
            ended_at=datetime.fromtimestamp(t_start + (start_ms + ms) / 1000, UTC).isoformat(
                timespec="milliseconds"
            ),
            elapsed_ms=ms,
            success=True,
            model=getattr(part, "model", None),
            effort=getattr(part, "reasoning_effort", None),
            **tokens,
        )

    # ProofPipeline drives a staged generator through these three methods instead of generate()
    # (pipeline._staged_generator), so without them Tier 2 records no Draft/Sketch/Prove rows.
    def _stage(self, stage: str, call: Callable[[], Any]) -> Any:
        t_start, since = time.time(), len(self.scope.usage)
        part = call()
        self._emit(stage, part, 0.0, t_start, since)
        return part

    def generate_draft(self, request: Any, feedback: Any = None) -> Any:
        return self._stage("draft", lambda: self.inner.generate_draft(request, feedback))

    def generate_sketch(self, request: Any, draft: Any, feedback: Any = None) -> Any:
        return self._stage("sketch", lambda: self.inner.generate_sketch(request, draft, feedback))

    def generate_proof(self, request: Any, draft: Any, sketch: Any, feedback: Any = None) -> Any:
        return self._stage(
            "prove", lambda: self.inner.generate_proof(request, draft, sketch, feedback)
        )

    def generate_direct_proof(self, request: Any, draft: Any) -> Any:
        return self._stage("prove_direct", lambda: self.inner.generate_direct_proof(request, draft))

    def generate_patch(self, request: Any, feedback: Any) -> Any:
        return self._stage("patch", lambda: self.inner.generate_patch(request, feedback))

    def generate(self, request: Any) -> Any:
        t_start = time.time()
        proof = self.inner.generate(request)
        offset = 0.0
        for stage, part in (("draft", proof.draft), ("sketch", proof.sketch), ("prove", proof)):
            self._emit(stage, part, offset, t_start)
            offset += float(getattr(part, "elapsed_ms", 0) or 0) if part is not None else 0.0
        return proof

    def repair(self, request: Any, feedback: Any) -> Any:
        started, t0 = now_iso(), time.monotonic()
        proof = self.inner.repair(request, feedback)
        self.scope.attempt(
            "repair",
            started_at=started,
            ended_at=now_iso(),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            success=True,
            model=getattr(proof, "model", None),
            effort=getattr(proof, "reasoning_effort", None),
        )
        return proof


def _usage_cost(usage: list[dict[str, Any]], default_model: str) -> float | None:
    """Price every usage row at its own model's rate (route/repair calls may use a cheaper model);
    rows without a model fall back to ``default_model``. None when any row's model is unpriced."""
    total = 0.0
    for row in usage:
        usd = estimate_usd(
            row.get("model") or default_model,
            int(row.get("input_tokens", 0) or 0),
            int(row.get("output_tokens", 0) or 0),
        )
        if usd is None:
            return None
        total += usd
    return total


def _run_row(
    scope: Scope,
    tier: int,
    *,
    success: bool,
    first_ok: bool,
    repairs: int,
    wall_s: float,
    model: str | None,
    split: str | None,
    config: dict[str, Any],
    started: str,
    termination: str | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    totals = scope.usage_totals()
    cost = _usage_cost(scope.usage, model) if model else 0.0
    row = {
        "schema": RUN_SCHEMA,
        "run_id": scope.run_id,
        "tier": tier,
        "problem_id": scope.problem_id,
        "arm": scope.arm,
        "repeat": scope.repeat,
        "split": split,
        "success": success,
        "first_attempt_ok": first_ok,
        "repairs_used": repairs,
        "wall_s": round(wall_s, 3),
        "cost_usd": cost,
        "model_calls": len(scope.usage),
        **totals,
        "termination_reason": termination,
        "config": config,
        "started_at": started,
        "ended_at": now_iso(),
        "error": error,
        "stage_ms": dict(scope.stage_ms),
        **(extra or {}),
    }
    scope.sink.write(row)
    return row


def run_tier0(
    replays: Iterable[dict[str, Any]],
    verifier: Any,
    scope: Scope,
    *,
    arm: str,
    repeat: int = 1,
    splits: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Each replay is ``{"problem_id", "lean_code"}``; the verifier is the code under test."""
    rec = RecordingVerifier(verifier, scope, stage_for_verify="replay_check")
    out = []
    for item in replays:
        scope.reset(item["problem_id"], arm, repeat)
        started, t0 = now_iso(), time.monotonic()
        error = None
        try:
            ok = bool(rec.verify(item["lean_code"]).success)
        except Exception as exc:  # a crashed verifier is a recorded failure, not a skipped row
            ok, error = False, type(exc).__name__
        out.append(
            _run_row(
                scope,
                0,
                success=ok,
                first_ok=ok,
                repairs=0,
                wall_s=time.monotonic() - t0,
                model=None,
                split=(splits or {}).get(item["problem_id"]),
                config=config or {},
                started=started,
                error=error,
            )
        )
    return out


def run_tier1(
    problems: Iterable[dict[str, Any]],
    drafts: dict[str, str],
    generator: Any,
    verifier: Any,
    prepare: Callable[..., Any],
    scope: Scope,
    *,
    arm: str,
    model: str,
    repeat: int = 1,
    config: dict[str, Any] | None = None,
    usage_scope_factory: Callable[[Callable[[dict[str, Any]], None]], Any] | None = None,
    make_draft: Callable[[str], Any] | None = None,
) -> list[dict[str, Any]]:
    """Cached Draft -> new Sketch -> sorry-tolerant compile. ``prepare`` is
    ``ProofPipeline.prepare_statement``; ``usage_scope_factory`` is
    ``pals_agent.usage.usage_scope``."""
    rec = RecordingVerifier(verifier, scope)
    out = []
    for p in problems:
        pid = p["id"]
        if pid not in drafts:
            continue
        scope.reset(pid, arm, repeat)
        started, t0 = now_iso(), time.monotonic()
        error, ok = None, False
        ctx = usage_scope_factory(scope.on_usage) if usage_scope_factory else nullcontext()
        try:
            with ctx:
                request = prepare(
                    statement=p["statement"], formal_statement=p.get("fixed_lean_statement")
                )
                draft = make_draft(drafts[pid]) if make_draft else drafts[pid]
                sk_start, since = now_iso(), len(scope.usage)
                s0 = time.monotonic()
                sketch = generator.generate_sketch(request, draft)
                tok = scope.usage_totals(since)
                scope.attempt(
                    "sketch",
                    started_at=sk_start,
                    ended_at=now_iso(),
                    elapsed_ms=int((time.monotonic() - s0) * 1000),
                    success=True,
                    model=sketch.model,
                    effort=sketch.reasoning_effort,
                    **tok,
                )
                ok = bool(rec.verify_sketch(sketch.lean_code).success)
        except Exception as exc:
            error = type(exc).__name__
        out.append(
            _run_row(
                scope,
                1,
                success=ok,
                first_ok=ok,
                repairs=0,
                wall_s=time.monotonic() - t0,
                model=model,
                split=p.get("split"),
                config=config or {},
                started=started,
                termination="sketch_checked" if error is None else "error",
                error=error,
            )
        )
    return out


def _load_1m() -> float | None:
    try:
        return round(os.getloadavg()[0], 2)
    except OSError:
        return None


def run_pipeline_once(
    problem: dict[str, Any],
    pipeline: Any,
    scope: Scope,
    *,
    arm: str,
    repeat: int,
    model: str,
    artifact_dir: Path,
    usage_scope_factory: Callable[..., Any],
    config: dict[str, Any] | None = None,
    post_run: Callable[[Any], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Tier 2/3: ``pipeline`` must already hold a RecordingVerifier/RecordingGenerator over
    ``scope``.
    First-attempt compile and repair count come from the pipeline's own result.json."""
    scope.reset(problem["id"], arm, repeat)
    run_id = f"{scope.run_id}-{arm}-{problem['id']}-{repeat}"
    started, t0 = now_iso(), time.monotonic()
    error, state = None, "error"
    load_start = _load_1m()
    pipeline_s: float | None = None
    answer_s: float | None = None
    extra: dict[str, Any] = {}
    try:
        with usage_scope_factory(scope.on_usage):
            result = pipeline.run_statement(
                statement=problem["statement"],
                formal_statement=problem.get("fixed_lean_statement"),
                proof_job_id=run_id,
                routine=problem.get("tier") == "easy",  # ignored unless PALS_T2_NO_DRAFT is on
            )
            pipeline_s = time.monotonic() - t0  # the clock stops before any bookkeeping below
            state = result.state
            if post_run is not None:
                extra = post_run(result)
                answer_s = time.monotonic() - t0
            # Candidates cancelled by a race (and discarded explanations) bill after the clock
            # stopped; wait for them so the usage and cost below include them.
            from pals_agent import t2_lane

            extra["undrained_background_calls"] = t2_lane.drain_background()
    except Exception as exc:
        error = type(exc).__name__
    meta: dict[str, Any] = {}
    seg = safe_artifact_segment(run_id)
    path = artifact_dir / seg / "result.json"
    if path.exists():
        meta = json.loads(path.read_text(encoding="utf-8"))
    attempts = meta.get("attempts", [])
    first_ok = bool(attempts and attempts[0].get("verification", {}).get("success"))
    return _run_row(
        scope,
        3,
        success=state == "verified",
        first_ok=first_ok,
        repairs=int(meta.get("repairs_used") or 0),
        wall_s=pipeline_s if pipeline_s is not None else time.monotonic() - t0,
        model=model,
        split=problem.get("split"),
        config=config or {},
        started=started,
        termination=meta.get("termination_reason"),
        error=error,
        extra={
            "answer_s": answer_s,
            "load_1m_start": load_start,
            "load_1m_end": _load_1m(),
            **extra,
        },
    )
