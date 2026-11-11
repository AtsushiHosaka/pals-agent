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
}
ARM_FLAGS: dict[str, set[str]] = {
    "base": set(),
    "static": {"static"},
    "combined": {"static", "import", "cond"},
    "fields": {"fields"},
}
DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "testdata/generation-eval-v1/manifest.json"
_IMPORT_ERR = re.compile(
    r"unknown package|unknown module prefix|invalid 'import'|bad import|object file", re.I
)
_UNKNOWN_ID = re.compile(r"unknown (identifier|constant|namespace)|unknown identifier", re.I)


def set_arm(arm: str) -> dict[str, str]:
    on = ARM_FLAGS[arm]
    env = {name: ("true" if key in on else "false") for key, name in FLAG_NAMES.items()}
    os.environ.update(env)
    return env


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
    problems = select(json.loads(args.manifest.read_text()), args.ids, args.n)
    by_id = {p["id"]: p for p in problems}
    sink = JsonlSink(args.out / "records.jsonl", artifacts_dir=args.out / "artifacts")
    scope = Scope(run_id=args.out.name, sink=sink)
    pipeline = ProofPipeline(
        generator=RecordingGenerator(generator, scope),
        verifier=RecordingVerifier(verifier, scope),
        artifact_store=FileArtifactStore(args.out / "art"),
    )
    for pid, arm, rep in interleaved_schedule(
        list(by_id), args.arms.split(","), args.repeats, args.seed
    ):
        if meter.exhausted():
            print("budget reached; stopping", flush=True)
            break
        env = set_arm(arm)
        meter.arm = arm
        r = run_pipeline_once(
            by_id[pid],
            pipeline,
            scope,
            arm=arm,
            repeat=rep,
            model="gpt-6.1-terra",
            artifact_dir=args.out / "art",
            usage_scope_factory=lambda cb: usage_scope(lambda x: (cb(x), meter.add(x))),
            config={"flags": env},
        )
        print(
            f"{pid} {arm} r{rep} ok={r['success']} first={r['first_attempt_ok']} "
            f"repairs={r['repairs_used']} wall={r['wall_s']} run_usd={meter.run_usd:.4f} "
            f"err={r['error']}",
            flush=True,
        )


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
