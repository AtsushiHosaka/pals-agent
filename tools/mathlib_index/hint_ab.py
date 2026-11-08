"""A/B experiment: do unverified Mathlib index candidates reduce repairs and time?

Runs the real generate/Lean-verify/repair loop locally. The hinted arm only appends candidate names
to Sketch and Prove prompts; Lean still verifies every candidate and the verifier is unchanged.
Nothing here changes production prompts. Requires `OPENAI_API_KEY`; each run spends model tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pals_agent import step_timing
from pals_agent.artifacts import FileArtifactStore, safe_artifact_segment
from pals_agent.generator import HybridLeanGenerator
from pals_agent.lean import LeanVerifier
from pals_agent.openai import OpenAIError, OpenAIResponsesClient
from pals_agent.pipeline import ProofPipeline, _validate_formal_harness
from pals_agent.sketch_repair import repair_sketch
from pals_agent.usage import usage_scope
from tools.mathlib_index.build_index import name_tokens
from tools.mathlib_index.exemplars import (
    Target,
    load_catalog,
    render_exemplars,
    select_exemplars,
)
from tools.mathlib_index.search import (
    MathlibIndex,
    lean_query_terms,
    natural_query_terms,
)
from tools.mathlib_index.sketch_failures import classify_check, summarize

HINT_HEADER = """
Unverified Mathlib candidates from a name and statement index of the pinned environment.
They were not checked against this goal and may not apply. Treat them only as suggestions:
ignore any that do not fit. Lean verification decides, and a suggestion is never evidence.
"""
# List prices per million tokens; input is not discounted, so spend is an upper estimate.
USD_PER_MTOK = {"gpt-6-luna": (0.10, 0.50), "gpt-6.1-terra": (1.25, 5.00)}
_FENCED_LEAN = r"```lean\n(.*?)```"
_FAILED_CODE = re.compile(r"Failed Lean code:\n" + _FENCED_LEAN, re.DOTALL)
_SKETCH_CODE = re.compile(r"Lean Sketch to complete:\n" + _FENCED_LEAN, re.DOTALL)
_DRAFT_TEXT = re.compile(r"<draft>\n(.*?)</draft>", re.DOTALL)
_UNKNOWN = re.compile(r"Identifiers unresolved in the failed import environment:\n((?:- `.*`\n)+)")
_HINTED_STAGES = (
    "Translate the informal Draft into a Lean 4/mathlib formal Sketch.",
    "Complete a Lean 4/mathlib proof from the supplied Draft and formal Sketch.",
)


def _type_line(entry: dict[str, Any], limit: int = 220) -> str:
    statement = " ".join(str(entry["type"]).split())
    if len(statement) > limit:
        statement = statement[:limit] + " …"
    return f"- `{entry['name']}` : {statement}"


TARGET_TAIL = (Path(__file__).parent / "target_tail.lean.txt").read_text(encoding="utf-8")


def elaborated_constants(
    code: str, *, lean: str, timeout: float = 180.0
) -> tuple[list[str], list[str]]:
    """Read statement constants from Lean; generated code with a broken proof still yields them."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Target.lean"
        path.write_text(code + "\n" + TARGET_TAIL, encoding="utf-8")
        try:
            output = subprocess.run(
                [lean, str(path)],
                env=dict(os.environ),
                capture_output=True,
                text=True,
                timeout=timeout,
            ).stdout
        except subprocess.TimeoutExpired:
            return [], []
    conclusion: list[str] = []
    hypotheses: list[str] = []
    for line in output.splitlines():
        if line.startswith("PALS_TARGET "):
            target = json.loads(line.removeprefix("PALS_TARGET "))
            conclusion.extend(target["conclusion_constants"])
            hypotheses.extend(target["hypothesis_constants"])
    return conclusion, hypotheses


@dataclass(slots=True)
class HintBuilder:
    index: MathlibIndex
    lean: str
    general_limit: int = 15
    unknown_limit: int = 3
    log: list[dict[str, Any]] = field(default_factory=list)
    _cache: dict[str, tuple[list[str], list[str]]] = field(default_factory=dict)

    def hints_for(self, prompt: str) -> str:
        if not prompt.startswith(_HINTED_STAGES):
            return ""
        started = time.monotonic()
        code_match = _FAILED_CODE.search(prompt) or _SKETCH_CODE.search(prompt)
        general: list[str] = []
        source = "none"
        if code_match:
            code = code_match.group(1)
            if code not in self._cache:
                self._cache[code] = elaborated_constants(code, lean=self.lean)
            conclusion, hypotheses = self._cache[code]
            if conclusion or hypotheses:
                source = "elaborated_symbols"
                general = [
                    candidate.name
                    for candidate in self.index.symbol_search(
                        conclusion, hypotheses, k=self.general_limit, scope="full"
                    )
                ]
            else:
                source = "lean_text"
                general = [
                    candidate.name
                    for candidate in self.index.text_search(
                        lean_query_terms(code), k=self.general_limit, scope="full"
                    )
                ]
        else:
            draft = _DRAFT_TEXT.search(prompt)
            if draft:
                source = "draft_text"
                general = [
                    candidate.name
                    for candidate in self.index.text_search(
                        natural_query_terms(draft.group(1)), k=self.general_limit, scope="core"
                    )
                ]
        unknown_names: list[str] = []
        unknown = _UNKNOWN.search(prompt)
        if unknown:
            for identifier in re.findall(r"`(.*?)`", unknown.group(1)):
                found = self.index.text_search(
                    name_tokens(identifier).split(), k=self.unknown_limit, scope="full"
                )
                unknown_names.extend(candidate.name for candidate in found)
        names = list(dict.fromkeys([*unknown_names, *general]))
        self.log.append(
            {
                "source": source,
                "general": general,
                "for_unknown": unknown_names,
                "seconds": round(time.monotonic() - started, 2),
            }
        )
        if not names:
            return ""
        lines = [_type_line(entry) for entry in self.index.describe(names)]
        return HINT_HEADER + "\n".join(lines) + "\n"


@dataclass(slots=True)
class HintingClient:
    inner: OpenAIResponsesClient
    builder: HintBuilder

    def generate(self, *, model: str, prompt: str) -> str:
        return self.inner.generate(model=model, prompt=prompt + self.builder.hints_for(prompt))


@dataclass(slots=True)
class ExemplarClient:
    """Appends the same catalog proof examples to every Sketch and Prove prompt of one card."""

    inner: Any
    text: str

    def generate(self, *, model: str, prompt: str) -> str:
        suffix = self.text if prompt.startswith(_HINTED_STAGES) else ""
        return str(self.inner.generate(model=model, prompt=prompt + suffix))


@dataclass(slots=True)
class SpendGuard:
    """Refuses further model calls once the estimated spend of this process reaches the limit."""

    limit_usd: float | None = None
    spent_usd: float = 0.0
    stopped: bool = False

    def add(self, row: dict[str, Any]) -> None:
        input_price, output_price = USD_PER_MTOK[row["model"]]
        self.spent_usd += (
            row["input_tokens"] * input_price + row["output_tokens"] * output_price
        ) / 1e6

    def check(self) -> None:
        if self.limit_usd is not None and self.spent_usd >= self.limit_usd:
            self.stopped = True
            raise OpenAIError(f"experiment budget of {self.limit_usd} USD reached")


@dataclass(slots=True)
class GuardedClient:
    inner: Any
    guard: SpendGuard

    def generate(self, *, model: str, prompt: str) -> str:
        self.guard.check()
        return str(self.inner.generate(model=model, prompt=prompt))


@dataclass(slots=True)
class SketchRecorder:
    """Wraps the verifier and records every Sketch check: outcome, time, error classes.

    Message text is kept only in the local raw dump (`raw_dir`), never in the result record.
    """

    inner: Any
    raw_dir: Path | None = None
    run_id: str = ""
    checks: list[dict[str, Any]] = field(default_factory=list)
    last_result: Any = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def verify_sketch(self, lean_code: str) -> Any:
        result = self.inner.verify_sketch(lean_code)
        self.last_result = result
        rows = classify_check(list(result.diagnostics), lean_code)
        self.checks.append(
            {
                "ordinal": len(self.checks) + 1,
                "success": bool(result.success),
                "lean_ms": result.elapsed_ms,
                **summarize(rows),
                "codes": sorted({str(r.code) for r in rows}),
                "regions": sorted({r.region for r in rows}),
            }
        )
        if self.raw_dir is not None:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            raw = {
                "code": lean_code,
                "diagnostics": [d.to_api() for d in result.diagnostics],
            }
            name = f"{safe_artifact_segment(self.run_id)}-{len(self.checks)}.json"
            (self.raw_dir / name).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        return result


def run_sketch_only(
    problem: dict[str, str],
    arm: str,
    args: argparse.Namespace,
    pipeline: ProofPipeline,
    generator: Any,
    recorder: SketchRecorder,
    usage: list[dict[str, Any]],
    on_usage: Any,
) -> dict[str, Any]:
    """Draft, Sketch and the Sketch Lean check of the first attempt; nothing after it."""
    started = time.monotonic()
    request = pipeline.prepare_statement(
        statement=problem["statement"], formal_statement=problem.get("formal_statement")
    )
    with usage_scope(on_usage):
        draft = generator.generate_draft(request, None)
        draft_seconds = time.monotonic() - started
        sketch = generator.generate_sketch(request, draft, None) if draft.text.strip() else None
    sketch_seconds = time.monotonic() - started - draft_seconds
    check = None
    harness_ok = None
    if sketch is not None and sketch.lean_code.strip():
        recorder.verify_sketch(sketch.lean_code)
        check = recorder.checks[-1]
        if request.formal_statement:
            harness_ok = not _validate_formal_harness(
                formal_statement=request.formal_statement, lean_code=sketch.lean_code
            )
    repair_record: dict[str, Any] | None = None
    if args.sketch_repair and check and not check["success"] and sketch is not None:
        first = recorder.last_result
        before = len(recorder.checks)
        repaired = repair_sketch(sketch.lean_code, first, recorder.verify_sketch)
        repair_record = {
            "repaired": repaired is not None,
            "steps": list(repaired.steps) if repaired else None,
            "rechecks": len(recorder.checks) - before,
            "lean_seconds": round(sum(c["lean_ms"] for c in recorder.checks[before:]) / 1000, 1),
        }
    if sketch is None or not sketch.lean_code.strip():
        outcome = "empty_sketch"
    elif check and not check["success"]:
        outcome = "lean_failed"
    elif harness_ok is False:
        outcome = "harness_mismatch"
    else:
        outcome = "passed"
    record = {
        "problem": problem["id"],
        "arm": arm,
        "mode": "sketch_only",
        "model": args.model,
        "effort": args.effort,
        "outcome": outcome,
        "sketch_has_gaps": bool(sketch and sketch.has_gaps),
        "harness_ok": harness_ok,
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "draft_seconds": round(draft_seconds, 1),
        "sketch_seconds": round(sketch_seconds, 1),
        "lean_seconds": round((check or {}).get("lean_ms", 0) / 1000, 1),
        "model_calls": len(usage),
        "input_tokens": sum(row["input_tokens"] for row in usage),
        "output_tokens": sum(row["output_tokens"] for row in usage),
        "sketch_checks": recorder.checks,
        "mechanical_repair": repair_record,
    }
    print(json.dumps(record, ensure_ascii=False), flush=True)
    return record


def run_one(
    problem: dict[str, str],
    *,
    arm: str,
    args: argparse.Namespace,
    index: MathlibIndex | None,
    guard: SpendGuard,
) -> dict[str, Any]:
    openai = OpenAIResponsesClient(
        api_key=os.environ["OPENAI_API_KEY"],
        max_output_tokens=args.max_output_tokens,
        reasoning_effort=args.effort,
    )
    builder = HintBuilder(index, lean=args.hint_lean) if index is not None else None
    client: Any = openai
    if arm == "hinted":
        if builder is None:
            raise ValueError("the hinted arm needs --index-dir")
        client = HintingClient(openai, builder)
    exemplar_ids: list[str] = []
    exemplar_chars = 0
    if arm == "exemplars":
        chosen = select_exemplars(
            Target(problem["id"], problem["statement"], problem.get("formal_statement") or ""),
            load_catalog(args.catalog_docs),
            k=args.exemplar_count,
        )
        exemplar_ids = [card.id for card in chosen]
        text = render_exemplars(chosen)
        exemplar_chars = len(text)
        client = ExemplarClient(openai, text)
    generator = HybridLeanGenerator(
        model=args.model,
        provider="openai",
        client=GuardedClient(client, guard),
        fixed_statement_template=args.statement_template,
    )
    run_id = f"{args.run_label}-{arm}-{problem['id']}"
    recorder = SketchRecorder(
        LeanVerifier(
            lean_binary=args.lean,
            lake_binary=args.lake,
            project_dir=args.lean_project,
            child_path=f"{Path(args.lean).parent}:/usr/bin:/bin",
            elan_home=str(args.elan_home),
            scratch_dir=args.scratch,
            timeout_seconds=args.lean_timeout,
        ),
        raw_dir=args.out / "raw",
        run_id=run_id,
    )
    pipeline = ProofPipeline(
        generator=generator,
        verifier=recorder,
        artifact_store=FileArtifactStore(args.out / "artifacts"),
        max_repair_attempts=args.max_repairs,
        harness_splice=args.harness_splice,
        deterministic_repair_route=args.deterministic_route,
        sketch_failure_proceeds_to_prove=args.sketch_continue,
        sketch_mechanical_repair=args.sketch_repair,
        sketch_parallel=args.sketch_parallel,
        stop_on_repeated_harness_mismatch=args.stop_harness_repeat,
    )
    usage: list[dict[str, Any]] = []

    def on_usage(row: dict[str, Any]) -> None:
        usage.append(row)
        guard.add(row)

    if args.stop_after_sketch:
        return run_sketch_only(problem, arm, args, pipeline, generator, recorder, usage, on_usage)
    started = time.monotonic()
    # One label per run label, problem and arm, so timing files from different experiments
    # cannot be mixed up. A name that is not token-safe falls back to the job digest.
    with (
        usage_scope(on_usage),
        step_timing.run_scope(
            run_id, label=f"{args.run_label}.{problem['id']}.{arm}"
        ) as timing_run,
    ):
        result = pipeline.run_statement(
            statement=problem["statement"],
            formal_statement=problem.get("formal_statement"),
            proof_job_id=run_id,
        )
    elapsed = time.monotonic() - started
    metadata_path = args.out / "artifacts" / safe_artifact_segment(run_id) / "result.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    attempts = metadata.get("attempts", [])
    record = {
        "problem": problem["id"],
        "history": problem["history"],
        "arm": arm,
        "model": args.model,
        "effort": args.effort,
        "max_repairs": args.max_repairs,
        "state": result.state,
        "repairs_used": metadata.get("repairs_used"),
        "termination_reason": metadata.get("termination_reason"),
        "elapsed_seconds": round(elapsed, 1),
        "lean_seconds": round(
            sum(a.get("verification", {}).get("elapsed_ms", 0) for a in attempts) / 1000, 1
        ),
        "harness_splice": args.harness_splice,
        "deterministic_route": args.deterministic_route,
        "sketch_continue": args.sketch_continue,
        "sketch_repair": args.sketch_repair,
        "sketch_parallel": args.sketch_parallel,
        "statement_template": args.statement_template,
        "stop_harness_repeat": args.stop_harness_repeat,
        "route_model_calls": sum(
            1
            for a in attempts
            if a.get("repair_route")
            and a["repair_route"].get("provider") != "pals-deterministic-policy"
        ),
        "routes": [a["repair_route"]["route"] for a in attempts if a.get("repair_route")],
        "model_calls": len(usage),
        "input_tokens": sum(row["input_tokens"] for row in usage),
        "cached_input_tokens": sum(row["cached_input_tokens"] for row in usage),
        "output_tokens": sum(row["output_tokens"] for row in usage),
        "diagnostic_codes": [
            sorted(
                {
                    str(d.get("code"))
                    for d in a.get("verification", {}).get("diagnostics", [])
                    if d.get("severity") == "error"
                }
            )
            for a in attempts
        ],
        "sketch_checks": recorder.checks,
        "exemplar_ids": exemplar_ids,
        "exemplar_chars": exemplar_chars,
        "hint_seconds": round(sum(r["seconds"] for r in builder.log), 1) if builder else 0.0,
        "hint_rounds": builder.log if builder else [],
        "budget_stopped": guard.stopped,
        # Joins this record to its pipeline_run in the PALS_STEP_TIMING_JSONL events.
        **({"step_timing_run": timing_run.name} if timing_run is not None else {}),
    }
    print(
        json.dumps({k: v for k, v in record.items() if k != "hint_rounds"}, ensure_ascii=False),
        flush=True,
    )
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problems", type=Path, required=True)
    parser.add_argument("--only", default="", help="Comma-separated problem ids")
    parser.add_argument("--arms", default="baseline,hinted", help="baseline, hinted, exemplars")
    parser.add_argument("--index-dir", type=Path, help="Required only for the hinted arm")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-label", required=True)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--effort", default="low")
    parser.add_argument("--max-repairs", type=int, default=6)
    parser.add_argument(
        "--harness-splice", action="store_true", help="Enable ProofPipeline.harness_splice"
    )
    parser.add_argument(
        "--deterministic-route",
        action="store_true",
        help="Enable ProofPipeline.deterministic_repair_route",
    )
    parser.add_argument(
        "--sketch-continue",
        action="store_true",
        help="Enable ProofPipeline.sketch_failure_proceeds_to_prove",
    )
    parser.add_argument(
        "--sketch-repair",
        action="store_true",
        help="Enable ProofPipeline.sketch_mechanical_repair (and record it in sketch-only mode)",
    )
    parser.add_argument(
        "--statement-template",
        action="store_true",
        help="HybridLeanGenerator.fixed_statement_template: the model writes only the proof body",
    )
    parser.add_argument(
        "--stop-harness-repeat",
        action="store_true",
        help="ProofPipeline.stop_on_repeated_harness_mismatch",
    )
    parser.add_argument(
        "--sketch-parallel",
        type=int,
        default=1,
        help="Ask for this many Sketches at once and keep the first that passes its Lean check",
    )
    parser.add_argument(
        "--stop-after-sketch",
        action="store_true",
        help="Run Draft and Sketch and the Sketch Lean check only (no Prove, no repair loop)",
    )
    parser.add_argument(
        "--catalog-docs",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "docs",
        help="Directory with *-batch.json/.lean catalog cards (arm exemplars)",
    )
    parser.add_argument("--exemplar-count", type=int, default=2)
    parser.add_argument("--max-output-tokens", type=int, default=12000)
    parser.add_argument("--lean", required=True, help="Verifier lean, usually the Elan proxy")
    parser.add_argument("--lake", required=True)
    parser.add_argument("--hint-lean", required=True, help="Lean with LEAN_PATH set for hints")
    parser.add_argument("--lean-project", type=Path, required=True)
    parser.add_argument("--elan-home", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--lean-timeout", type=float, default=180.0)
    parser.add_argument("--max-usd", type=float, help="Stop calling the model at this estimate")
    parser.add_argument(
        "--step-timing", action="store_true",
        help="Write per-step timing events to <out>/<run-label>.steps.jsonl",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.step_timing:
        os.environ[step_timing.ENV_JSONL] = str(args.out / f"{args.run_label}.steps.jsonl")
    problems = json.loads(args.problems.read_text(encoding="utf-8"))
    selected = set(filter(None, args.only.split(",")))
    results_path = args.out / f"{args.run_label}.jsonl"
    index = None
    if "hinted" in args.arms.split(","):
        if args.index_dir is None:
            parser.error("--index-dir is required for the hinted arm")
        index = MathlibIndex(args.index_dir / "index.sqlite")
        index.symbol_search(["Continuous"], [], k=1)  # Load postings outside the measured runs.
    guard = SpendGuard(limit_usd=args.max_usd)
    for problem in problems:
        if selected and problem["id"] not in selected:
            continue
        for arm in args.arms.split(","):
            if guard.stopped:
                return
            try:
                record = run_one(problem, arm=arm, args=args, index=index, guard=guard)
            except Exception as exc:  # A failed run must not lose completed paired results.
                record = {
                    "problem": problem["id"],
                    "arm": arm,
                    "error": type(exc).__name__,
                    "message": str(exc)[:500],
                }
                print(json.dumps(record, ensure_ascii=False), flush=True)
            with results_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
