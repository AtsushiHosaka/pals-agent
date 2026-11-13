"""Paid generation-eval runs: cache probe, Tier 1 (Draft cached, Sketch per arm), Tier 2 pipeline.

Needs OPENAI_API_KEY (and optionally PALS_OPENAI_BASE_URL) in the environment; never reads or
writes a key file. Every run takes --max-usd and stops before the next problem once the recorded
usage (estimated at list prices, cached input not discounted) reaches it. A shared spend ledger
(--spend-ledger, a JSONL outside git) lets several runs share one session cap (--total-cap).

    run_stages.py cache  --out DIR --ids a,b,c --arms base,static --max-usd 0.5 ...lean args
    run_stages.py tier1  --out DIR --ids ... --arms base,combined --max-usd 1 ...
    run_stages.py tier2  --out DIR --ids ... --arms base,combined --max-usd 1 ...

Arms are named flag bundles (ARM_FLAGS). Run it from a real file, not stdin: the OpenAI transport
uses multiprocessing spawn.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

FLAG_NAMES = {
    "static": "PALS_PROMPT_STATIC_PREFIX_ENABLED",
    "import": "PALS_PROMPT_FULL_MATHLIB_IMPORT_ENABLED",
    "cond": "PALS_PROMPT_CONDITIONAL_GUIDANCE_ENABLED",
    "fields": "PALS_DRAFT_STRUCTURED_FIELDS_ENABLED",
    # T2 lane (pals_agent/t2_lane.py)
    "nosketch": "PALS_T2_NO_SKETCH_ENABLED",
    "race": "PALS_T2_PARALLEL_CANDIDATES_ENABLED",
    "patch": "PALS_T2_PATCH_REPAIR_ENABLED",
    "pexpl": "PALS_T2_PARALLEL_EXPLANATION_ENABLED",
    "preview": "PALS_T2_PARALLEL_REVIEW_ENABLED",
    "nodraft": "PALS_T2_NO_DRAFT_ENABLED",
    "names": "PALS_T2_NAME_SAFETY_ENABLED",
    "hetero": "PALS_T2_HETERO_RACE_ENABLED",
    "hygiene": "PALS_T2_SOURCE_HYGIENE_ENABLED",
    "cheapfirst": "PALS_T2_CHEAP_FIRST_ENABLED",
}
ARM_FLAGS: dict[str, set[str]] = {
    "base": set(),
    "static": {"static"},
    "combined": {"static", "import", "cond"},
    "fields": {"fields"},
    "t2": {"nosketch", "race", "patch", "pexpl"},
    "nosketch": {"nosketch"},
    "race": {"race"},
    "patch": {"patch"},
    "pexpl": {"pexpl"},
    "nodraft": {"nodraft"},
    "nd_k2": {"nodraft", "race"},
    "nd_k2_names": {"nodraft", "race", "names"},
    # production shape (run_hetero_api_sim.py): fast + strong candidate, held alternate
    "hetero_par": {"nodraft", "race", "pexpl", "preview", "hetero"},
    # one candidate (run_hetero_api_sim.py --pin-effort) + patch repair + header fixes + names
    "single_fix": {"nodraft", "pexpl", "preview", "patch", "names", "hygiene"},
    # low first, a patch at the role's own effort on a compile failure (no race, no alternate)
    "cheap_first": {"nodraft", "pexpl", "preview", "patch", "names", "hygiene", "cheapfirst"},
    # hetero_par + patch repair after the alternate + deterministic header fixes + name guidance
    "hetero_fix": {"nodraft", "race", "pexpl", "preview", "hetero", "patch", "names", "hygiene"},
    # nd_k2 plus the explanation and the semantic review started when a candidate enters Lean
    "nd_k2_par": {"nodraft", "race", "pexpl", "preview"},
    # nd_k2 with the fixed-statement template and the layout splice (see ARM_PIPELINE)
    "nd_k2_tmpl": {"nodraft", "race"},
    # nd_k2 with one Lean slot per job (see ARM_ENV): the race is serial at the compiler
    "nd_k2_slot1": {"nodraft", "race"},
    "t2_norace": {"nosketch", "patch", "pexpl"},
    "t2_nopatch": {"nosketch", "race", "pexpl"},
    "t2_nonosketch": {"race", "patch", "pexpl"},
}
# Arms that also change how the generator/pipeline are built (not env flags).
ARM_PIPELINE: dict[str, dict[str, bool]] = {
    "nd_k2_tmpl": {"fixed_statement_template": True, "harness_splice": True},
}
DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "testdata/generation-eval-v1/manifest.json"
_IMPORT_ERR = re.compile(
    r"unknown package|unknown module prefix|invalid 'import'|bad import|object file", re.I
)
_UNKNOWN_ID = re.compile(r"unknown (identifier|constant|namespace)|unknown identifier", re.I)


# Extra environment of an arm (not a boolean flag).
ARM_ENV: dict[str, dict[str, str]] = {"nd_k2_slot1": {"PALS_T2_LEAN_SLOTS": "1"}}


def set_arm(arm: str) -> dict[str, str]:
    on = ARM_FLAGS[arm]
    env = {name: ("true" if key in on else "false") for key, name in FLAG_NAMES.items()}
    os.environ.update(env)
    os.environ.pop("PALS_T2_LEAN_SLOTS", None)
    extra = ARM_ENV.get(arm, {})
    os.environ.update(extra)
    return {**env, **extra}


def classify(result: Any) -> dict[str, Any]:
    errs = [d for d in result.diagnostics if getattr(d, "severity", "") == "error"]
    msgs = [str(getattr(d, "message", "")) for d in errs]
    return {
        "errors": len(errs),
        "unknown_identifier": sum(1 for m in msgs if _UNKNOWN_ID.search(m)),
        "import_error": sum(1 for m in msgs if _IMPORT_ERR.search(m)),
        "codes": sorted({str(d.code) for d in errs if getattr(d, "code", None)}),
        # Messages can quote problem terms: keep digests only.
        "first_message_sha256": [hashlib.sha256(m.encode("utf-8")).hexdigest() for m in msgs[:3]],
    }


class Meter:
    """Spend from recorded usage. Shared ledger => the session total is the sum of all runs."""

    def __init__(self, ledger: Path, run: str, max_usd: float, total_cap: float) -> None:
        self.ledger, self.run, self.max_usd, self.total_cap = ledger, run, max_usd, total_cap
        self.run_usd = 0.0
        self.arm_usd: dict[str, float] = {}
        self.arm = ""
        self.arm_cap: float | None = None

    def total(self) -> float:
        if not self.ledger.exists():
            return 0.0
        return sum(json.loads(x)["usd"] for x in self.ledger.read_text().splitlines() if x.strip())

    def add(self, row: dict[str, Any]) -> None:
        from pals_agent.evals.runner import estimate_usd

        usd = estimate_usd(row["model"], row["input_tokens"], row["output_tokens"]) or 0.0
        self.run_usd += usd
        self.arm_usd[self.arm] = self.arm_usd.get(self.arm, 0.0) + usd
        with self.ledger.open("a") as fh:
            fh.write(json.dumps({"run": self.run, "usd": usd, "model": row["model"]}) + "\n")

    def exhausted(self) -> bool:
        if self.arm_cap is not None and any(v >= self.arm_cap for v in self.arm_usd.values()):
            return True
        return self.run_usd >= self.max_usd or self.total() >= self.total_cap


def build(args: argparse.Namespace):
    from pals_agent.generator import HybridLeanGenerator
    from pals_agent.lean import LeanVerifier
    from pals_agent.openai import OpenAIResponsesClient

    # Release role bindings: Terra / medium for Draft, Sketch, Prove and Repair, as in production.
    client = OpenAIResponsesClient(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ.get("PALS_OPENAI_BASE_URL", "https://api.openai.com/v1"),
        timeout_seconds=args.model_timeout,
        max_output_tokens=args.max_output_tokens,
    )
    generator = HybridLeanGenerator(
        model="gpt-6.1-terra", provider="openai", client=client, use_release_role_bindings=True
    )
    verifier = LeanVerifier(
        lean_binary=args.lean,
        lake_binary=args.lake,
        project_dir=Path(args.project),
        child_path=f"{Path(args.lean).parent}:/usr/bin:/bin",
        elan_home=args.elan_home,
        scratch_dir=Path(args.scratch),
        timeout_seconds=args.lean_timeout,
    )
    return generator, verifier


def load_1m() -> float:
    return os.getloadavg()[0]


def wait_for_quiet_machine(args: argparse.Namespace, state: dict[str, Any]) -> bool:
    """Wait until the 1-minute load is <= --max-load, polling; give up after the first timeout.

    Returns True when the run proceeds under a load above the limit (the row is flagged)."""
    if args.max_load is None or state.get("gave_up"):
        return bool(state.get("gave_up"))
    deadline = time.monotonic() + args.load_wait_minutes * 60
    while load_1m() > args.max_load:
        if time.monotonic() >= deadline:
            state["gave_up"] = True
            print(f"load guard: load {load_1m():.1f} > {args.max_load}; going on", flush=True)
            return True
        time.sleep(15)
    return False


PROBE_CODE = (
    "import Mathlib\n\ntheorem pals_probe (a b : ℝ) : a ^ 2 + b ^ 2 ≥ 2 * a * b := by\n"
    "  nlinarith [sq_nonneg (a - b)]\n"
)


def probe_lean(verifier: Any, out: Path, label: str, repeats: int = 3) -> None:
    """Time a fixed small proof through the real verifier; the unloaded figure for normalising."""
    times = []
    for _ in range(repeats):
        t = time.monotonic()
        verifier.verify(PROBE_CODE)
        times.append(round(time.monotonic() - t, 2))
    row = {"label": label, "load_1m": round(load_1m(), 2), "seconds": times}
    with (out / "lean_probe.jsonl").open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    print("lean probe", row, flush=True)


def build_answer_stage(args: argparse.Namespace):
    """The release explainer and semantic reviewer (same models and efforts as production).

    Not measured here: the explanation output review, a second call after the explanation.
    """
    from pals_agent.explanations import LeanProofExplainer, LeanProofSemanticReviewer
    from pals_agent.model_roles import ModelRole, fixed_model_default
    from pals_agent.openai import OpenAIResponsesClient

    def client() -> OpenAIResponsesClient:
        return OpenAIResponsesClient(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("PALS_OPENAI_BASE_URL", "https://api.openai.com/v1"),
            timeout_seconds=args.model_timeout,
            max_output_tokens=6000,
        )

    explain = fixed_model_default(ModelRole.EXPLAIN)
    review = fixed_model_default(ModelRole.PROOF_REVIEW)
    explainer = LeanProofExplainer(
        client=client(), model=explain.model, provider=explain.provider, max_attempts=3
    )
    reviewer = LeanProofSemanticReviewer(
        client=client(), model=review.model, provider=review.provider, max_attempts=2
    )
    return explainer, reviewer


def answer_stage(result: Any, problem: dict, explainer: Any, reviewer: Any) -> dict[str, Any]:
    """After a verified proof: the semantic review and the explanation, timed.

    With an explanation already started beside verification (``result.speculative_explanation``)
    the review runs while it is in flight and only the remaining wait is paid; otherwise the
    explanation starts after the review, as it does in production today.
    """
    from pals_agent.explanations import ExplanationGenerationError
    from pals_agent.lean_target import extract_single_target_declaration

    if not result.verification.success:
        return {"answer_ok": False, "answer_note": "not_verified"}
    code, statement = result.generated.lean_code, result.prompt
    out: dict[str, Any] = {"answer_ok": True}
    target = extract_single_target_declaration(code)
    t = time.monotonic()
    approved = None
    review_handle = result.speculative_review
    if target is not None:
        try:
            review = None
            if review_handle is not None:
                review = review_handle.adopt(
                    theorem_statement=statement, lean_code=code, language="ja", wait_seconds=240
                )
            if review is None:
                review = reviewer.review_proof(
                    theorem_statement=statement,
                    formal_statement=problem.get("fixed_lean_statement"),
                    target_declaration=target,
                    lean_code=code,
                    timeout_seconds=120,
                )
            approved = review.decision == "approved"
        except Exception as exc:
            out["review_error"] = type(exc).__name__
    out["review_in_parallel"] = review_handle is not None
    out["review_s"] = round(time.monotonic() - t, 3)
    out["review_approved"] = approved
    t = time.monotonic()
    handle = result.speculative_explanation
    try:
        explanation = None
        if handle is not None:
            explanation = handle.adopt(
                theorem_statement=statement, lean_code=code, language="ja", wait_seconds=240
            )
        if explanation is None:
            explanation = explainer.explain(
                theorem_statement=statement,
                lean_code=code,
                verified=True,
                language="ja",
                deadline=time.monotonic() + 360,
                timeout_seconds=120,
            )
        out["explain_ok"] = True
    except ExplanationGenerationError as exc:
        out["explain_ok"] = False
        out["explain_error"] = type(exc).__name__
    out["explain_wait_s"] = round(time.monotonic() - t, 3)
    out["explained_in_parallel"] = handle is not None
    return out


def select(manifest: dict, ids: str | None, n: int | None) -> list[dict]:
    tuning = [p for p in manifest["problems"] if p["split"] == "tuning"]
    if ids:
        wanted = ids.split(",")
        by = {p["id"]: p for p in tuning}
        return [by[i] for i in wanted]  # KeyError on a held-out or unknown id is intended
    # Proportional-ish stratification over (field, tier): round-robin across strata, strata
    # ordered by size, members ordered by statement hash (stable, not by content).
    strata: dict[tuple[str, str], list[dict]] = {}
    for p in sorted(tuning, key=lambda p: p["statement_sha256"]):
        strata.setdefault((p["field"], p["tier"]), []).append(p)
    order = sorted(strata.values(), key=lambda g: -len(g))
    picked: list[dict] = []
    i = 0
    while len(picked) < (n or 0) and any(order):
        g = order[i % len(order)]
        if g:
            picked.append(g.pop(0))
        i += 1
    return picked


def cmd_cache(args: argparse.Namespace, meter: Meter) -> None:
    from pals_agent.artifacts import FileArtifactStore
    from pals_agent.pipeline import ProofPipeline
    from pals_agent.usage import usage_scope

    generator, verifier = build(args)
    pipeline = ProofPipeline(
        generator=generator, verifier=verifier, artifact_store=FileArtifactStore(args.out / "art")
    )
    problems = select(json.loads(args.manifest.read_text()), args.ids, args.n)
    out = (args.out / "cache.jsonl").open("a")
    seq = 0
    for p in problems:
        for arm in args.arms.split(","):
            for rep in (1, 2):  # back to back: the second call can hit the first's cache
                if meter.exhausted():
                    print("budget reached; stopping", flush=True)
                    return
                set_arm(arm)
                request = pipeline.prepare_statement(
                    statement=p["statement"], formal_statement=p.get("fixed_lean_statement")
                )
                usage: list[dict[str, Any]] = []
                with usage_scope(lambda r: (usage.append(dict(r)), meter.add(r))):  # noqa: B023
                    t0 = time.monotonic()
                    draft = generator.generate_draft(request, None)
                    t1 = time.monotonic()
                    sketch = generator.generate_sketch(request, draft, None) if draft.text else None
                    t2 = time.monotonic()
                seq += 1
                row = {
                    "seq": seq,
                    "problem_id": p["id"],
                    "arm": arm,
                    "rep": rep,
                    "ts": time.time(),
                    "draft_s": round(t1 - t0, 1),
                    "sketch_s": round(t2 - t1, 1),
                    "calls": [
                        {k: u[k] for k in ("input_tokens", "cached_input_tokens", "output_tokens")}
                        for u in usage
                    ],
                    "sketch_ok": bool(sketch and sketch.lean_code),
                    "run_usd": round(meter.run_usd, 4),
                }
                out.write(json.dumps(row) + "\n")
                out.flush()
                print(json.dumps(row), flush=True)


class ErrorLogVerifier:
    """Keeps every error message class of every Sketch check (RecordingVerifier keeps only 5)."""

    def __init__(self, inner: Any, path: Path, scope: Any) -> None:
        self.inner, self.path, self.scope = inner, path, scope

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def verify(self, code: str) -> Any:
        return self.inner.verify(code)

    def verify_sketch(self, code: str) -> Any:
        r = self.inner.verify_sketch(code)
        row = {
            "problem_id": self.scope.problem_id,
            "arm": self.scope.arm,
            "ok": bool(r.success),
            "elapsed_ms": getattr(r, "elapsed_ms", None),
            **classify(r),
            "header": code.strip().splitlines()[0] if code.strip() else "",
        }
        with self.path.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
        return r


def cmd_tier1(args: argparse.Namespace, meter: Meter) -> None:
    from pals_agent.artifacts import FileArtifactStore
    from pals_agent.evals.records import JsonlSink
    from pals_agent.evals.runner import Scope, interleaved_schedule, run_tier1
    from pals_agent.models import GeneratedDraft
    from pals_agent.pipeline import ProofPipeline
    from pals_agent.usage import usage_scope

    generator, verifier = build(args)
    manifest = json.loads(args.manifest.read_text())
    problems = select(manifest, args.ids, args.n)
    by_id = {p["id"]: p for p in problems}
    sink = JsonlSink(args.out / "records.jsonl", artifacts_dir=args.out / "artifacts")
    scope = Scope(run_id=args.out.name, sink=sink)
    pipeline = ProofPipeline(
        generator=generator,
        verifier=ErrorLogVerifier(verifier, args.out / "sketch_errors.jsonl", scope),
        artifact_store=FileArtifactStore(args.out / "art"),
    )
    # Shared Draft: generated once under the draft arm's flags, reused by every arm.
    drafts_path = args.out / "drafts.jsonl"
    drafts: dict[str, str] = {}
    if drafts_path.exists():
        for line in drafts_path.read_text().splitlines():
            d = json.loads(line)
            drafts[d["problem_id"]] = d["text"]
    set_arm(args.draft_arm)
    for p in problems:
        if p["id"] in drafts:
            continue
        if meter.exhausted():
            print("budget reached during drafts", flush=True)
            break
        request = pipeline.prepare_statement(
            statement=p["statement"], formal_statement=p.get("fixed_lean_statement")
        )
        usage: list[dict[str, Any]] = []
        with usage_scope(lambda r: (usage.append(dict(r)), meter.add(r))):  # noqa: B023
            draft = generator.generate_draft(request, None)
        if not draft.text:
            print(f"empty draft for {p['id']}", flush=True)
            continue
        drafts[p["id"]] = draft.text
        with drafts_path.open("a") as fh:
            fh.write(
                json.dumps(
                    {
                        "problem_id": p["id"],
                        "text": draft.text,
                        "usage": usage,
                        "elapsed_ms": draft.elapsed_ms,
                    }
                )
                + "\n"
            )
        print(f"draft {p['id']} run_usd={meter.run_usd:.4f}", flush=True)

    arms = args.arms.split(",")
    for pid, arm, rep in interleaved_schedule(
        [p["id"] for p in problems if p["id"] in drafts], arms, args.repeats, args.seed
    ):
        if meter.exhausted():
            print("budget reached; stopping", flush=True)
            break
        env = set_arm(arm)
        p = by_id[pid]
        rows = run_tier1(
            [p],
            drafts,
            pipeline.generator,
            pipeline.verifier,
            pipeline.prepare_statement,
            scope,
            arm=arm,
            model="gpt-6.1-terra",
            repeat=rep,
            config={"flags": env},
            usage_scope_factory=lambda cb: usage_scope(lambda r: (cb(r), meter.add(r))),  # noqa: B023
            make_draft=lambda text: GeneratedDraft(
                text=text, model="gpt-6.1-terra", raw_model_output=text
            ),
        )
        r = rows[0]
        print(
            f"{pid} {arm} r{rep} ok={r['success']} wall={r['wall_s']} err={r['error']} "
            f"run_usd={meter.run_usd:.4f}",
            flush=True,
        )


def cmd_fields(args: argparse.Namespace, meter: Meter) -> None:
    """Draft only, with PALS_DRAFT_STRUCTURED_FIELDS_ENABLED: how often the fields parse, and what
    FINAL_ANSWER says (compare to expected_answer by hand: it is a rationale, not a short answer)."""  # noqa: E501
    from pals_agent.artifacts import FileArtifactStore
    from pals_agent.pipeline import ProofPipeline
    from pals_agent.usage import usage_scope

    generator, verifier = build(args)
    pipeline = ProofPipeline(
        generator=generator, verifier=verifier, artifact_store=FileArtifactStore(args.out / "art")
    )
    set_arm("fields")
    for p in select(json.loads(args.manifest.read_text()), args.ids, args.n):
        if meter.exhausted():
            break
        request = pipeline.prepare_statement(
            statement=p["statement"], formal_statement=p.get("fixed_lean_statement")
        )
        with usage_scope(meter.add):
            d = generator.generate_draft(request, None)
        row = {
            "problem_id": p["id"],
            "parsed": d.fields is not None,
            "final_answer": d.fields.final_answer if d.fields else None,
            "hard_steps": list(d.fields.hard_steps) if d.fields else None,
            "tail": d.text[-300:],
            "elapsed_ms": d.elapsed_ms,
        }
        with (args.out / "fields.jsonl").open("a") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(json.dumps(row, ensure_ascii=False)[:400], flush=True)


def cmd_tier2(args: argparse.Namespace, meter: Meter) -> None:
    from pals_agent import t2_lane
    from pals_agent.artifacts import FileArtifactStore
    from pals_agent.evals.records import JsonlSink
    from pals_agent.evals.runner import (
        RecordingGenerator,
        RecordingVerifier,
        Scope,
        interleaved_schedule,
        run_pipeline_once,
    )
    from pals_agent.pipeline import ProofPipeline
    from pals_agent.usage import usage_scope

    generator, verifier = build(args)
    explainer, reviewer = build_answer_stage(args) if args.answer else (None, None)
    problems = select(json.loads(args.manifest.read_text()), args.ids, args.n)
    by_id = {p["id"]: p for p in problems}
    sink = JsonlSink(args.out / "records.jsonl", artifacts_dir=args.out / "artifacts")
    scope = Scope(run_id=args.out.name, sink=sink)
    import dataclasses

    recording_verifier = RecordingVerifier(verifier, scope)

    def pipeline_for(arm: str) -> ProofPipeline:
        options = ARM_PIPELINE.get(arm, {})
        gen = dataclasses.replace(
            generator, fixed_statement_template=options.get("fixed_statement_template", False)
        )
        return ProofPipeline(
            generator=RecordingGenerator(gen, scope),
            verifier=recording_verifier,
            artifact_store=FileArtifactStore(args.out / "art"),
            max_repair_attempts=args.max_repairs,
            explainer=explainer,
            reviewer=reviewer,
            harness_splice=options.get("harness_splice", False),
            # keep the wall clock honest; the runner drains the background after the answer stage
            accounting_wait_seconds=0.0,
        )

    pipelines = {arm: pipeline_for(arm) for arm in args.arms.split(",")}
    load_state: dict[str, Any] = {}
    wait_for_quiet_machine(args, load_state)
    probe_lean(verifier, args.out, "start")
    for pid, arm, rep in interleaved_schedule(
        list(by_id), args.arms.split(","), args.repeats, args.seed
    ):
        if meter.exhausted():
            print("budget reached; stopping", flush=True)
            break
        wait_for_quiet_machine(args, load_state)
        env = set_arm(arm)
        meter.arm = arm
        post = (
            (lambda res, p=by_id[pid]: answer_stage(res, p, explainer, reviewer))  # noqa: B023
            if args.answer
            else None
        )
        def count_discarded(row: dict[str, Any], arm: str = arm, pid: str = pid) -> None:
            """Work that was started and not used (a discarded explanation or review): spend."""
            from pals_agent.evals.runner import estimate_usd

            scope.on_usage(row)
            meter.add(row)
            usd = estimate_usd(row["model"], row["input_tokens"], row["output_tokens"]) or 0.0
            with (args.out / "discarded.jsonl").open("a") as fh:
                fh.write(json.dumps({"arm": arm, "problem_id": pid, "usd": usd}) + "\n")

        with t2_lane.discarded_usage_scope(count_discarded):
            r = run_pipeline_once(
                by_id[pid],
                pipelines[arm],
                scope,
                arm=arm,
                repeat=rep,
                model="gpt-6.1-terra",
                artifact_dir=args.out / "art",
                usage_scope_factory=lambda cb: usage_scope(lambda x: (cb(x), meter.add(x))),  # noqa: B023
                config={
                    "flags": env,
                    "max_repairs": args.max_repairs,
                    "load_guard_gave_up": bool(load_state.get("gave_up")),
                },
                post_run=post,
            )
        print(
            f"{pid} {arm} r{rep} ok={r['success']} first={r['first_attempt_ok']} "
            f"repairs={r['repairs_used']} wall={r['wall_s']} answer={r.get('answer_s')} "
            f"run_usd={meter.run_usd:.4f} err={r['error']}",
            flush=True,
        )
    probe_lean(verifier, args.out, "end")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("mode", choices=["cache", "tier1", "tier2", "fields"])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--ids")
    ap.add_argument("--n", type=int)
    ap.add_argument("--arms", required=True)
    ap.add_argument("--draft-arm", default="base")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--seed", type=int, default=20261110)
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--arm-cap", type=float, help="per-arm spend limit (tier2)")
    ap.add_argument("--total-cap", type=float, default=3.0)
    ap.add_argument("--spend-ledger", type=Path, required=True)
    ap.add_argument("--model-timeout", type=float, default=240.0)
    ap.add_argument("--max-output-tokens", type=int, default=12000)
    for name in ("lean", "lake", "project", "elan-home", "scratch"):
        ap.add_argument(f"--{name}", required=True)
    ap.add_argument("--lean-timeout", type=float, default=300.0)
    ap.add_argument("--max-repairs", type=int, default=3, help="repair cap (tier2)")
    ap.add_argument(
        "--max-load", type=float, default=None, help="tier2: wait for 1-min load <= this"
    )
    ap.add_argument("--load-wait-minutes", type=float, default=30.0)
    ap.add_argument(
        "--answer",
        action="store_true",
        help="tier2: after a verified proof also run the semantic review and the explanation",
    )
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    Path(args.scratch).mkdir(parents=True, exist_ok=True)
    meter = Meter(args.spend_ledger, args.out.name, args.max_usd, args.total_cap)
    meter.arm_cap = args.arm_cap
    {"cache": cmd_cache, "tier1": cmd_tier1, "tier2": cmd_tier2, "fields": cmd_fields}[args.mode](
        args, meter
    )
    print(f"DONE run_usd={meter.run_usd:.4f} session_total={meter.total():.4f}", flush=True)


if __name__ == "__main__":
    main()
