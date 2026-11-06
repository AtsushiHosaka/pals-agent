#!/usr/bin/env python3
"""Run the independent explanation QA over a small labelled regression set.

The x² epsilon-delta requirement is enforced by the independent review (see
docs/verification/explanation-semantic-gate-2026-11-06.md), so its judgement quality has to be
measured on a real model. This script does that with the production call path:
`AgentSettings.from_env()` -> `build_proof_output_reviewer()` -> `review_explanation()`.

Default is a DRY RUN: every case is checked against the structural layer and its QA prompt is
built, but no model is called and no API key is needed. A live run needs ALL of:

    --execute  --budget-usd N  --input-usd-per-mtok P  --output-usd-per-mtok Q
    and PALS_OPENAI_API_KEY or OPENAI_API_KEY in the environment.

Prices are supplied by the operator because this repository holds no price table. The run is
refused when the worst-case cost of all cases exceeds the budget, and stops before any call
whose worst case would exceed what is left.

Exit status: 0 when every case got its expected decision, 1 on any mismatch or error, 2 when the
invocation is refused or the case file is invalid.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pals_agent.explanations import (  # noqa: E402
    ExplanationSection,
    LeanLineReference,
    ProofExplanation,
    ProofOutputReview,
    ProofOutputReviewError,
    _output_review_prompt,
    _parse_explanation,
)

DEFAULT_CASES = ROOT / "testdata" / "explanation-qa-v1" / "cases.json"
SCHEMA = "pals.explanation-qa-regression.v1"
GROUPS = ("valid_notation", "wrong", "summary_first")
EXPECTED = {"approve", "reject"}
# Deliberately pessimistic: roughly one token per two characters of mixed Japanese and TeX.
CHARS_PER_TOKEN = 2


class CaseFileError(ValueError):
    pass


class Refused(RuntimeError):
    pass


class Reviewer(Protocol):
    max_attempts: int

    def review_explanation(
        self,
        *,
        theorem_statement: str,
        lean_code: str,
        explanation: ProofExplanation,
        language: str,
        deadline: float | None = None,
        timeout_seconds: float | None = None,
    ) -> ProofOutputReview: ...


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    group: str
    expected: str
    language: str
    explanation: ProofExplanation


@dataclass(frozen=True, slots=True)
class CaseFile:
    theorem_statement: str
    lean_code: str
    cases: tuple[Case, ...]


def load_cases(path: Path) -> CaseFile:
    """Parse the file and require every case to pass the production structural layer."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["schema"] != SCHEMA:
            raise CaseFileError(f"schema must be {SCHEMA}")
        statement = str(document["theorem_statement"])
        lean_code = str(document["lean_code"])
        raw_cases = document["cases"]
        if not isinstance(raw_cases, list) or not raw_cases:
            raise CaseFileError("cases must be a non-empty list")
        cases: list[Case] = []
        seen: set[str] = set()
        for raw in raw_cases:
            case_id = str(raw["id"])
            if case_id in seen:
                raise CaseFileError(f"duplicate case id: {case_id}")
            seen.add(case_id)
            group, expected = str(raw["group"]), str(raw["expected"])
            if group not in GROUPS or expected not in EXPECTED:
                raise CaseFileError(f"{case_id}: unknown group or expected decision")
            if (group == "valid_notation") != (expected == "approve"):
                raise CaseFileError(f"{case_id}: only valid_notation cases are approved")
            language = str(raw.get("language", "ja"))
            payload = {k: raw[k] for k in ("overview", "sections", "conclusion")}
            try:
                overview, sections, conclusion = _parse_explanation(
                    payload, lean_code, language=language, require_linear_ending=True
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise CaseFileError(f"{case_id}: fails the structural layer: {exc}") from exc
            cases.append(
                Case(
                    id=case_id,
                    group=group,
                    expected=expected,
                    language=language,
                    explanation=ProofExplanation(
                        overview=overview,
                        sections=tuple(_section(s) for s in sections),
                        conclusion=conclusion,
                        model="regression-fixture",
                        provider="regression-fixture",
                        prompt="",
                        raw_model_output="",
                        elapsed_ms=0,
                    ),
                )
            )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CaseFileError(f"cannot read case file: {type(exc).__name__}: {exc}") from exc
    return CaseFile(statement, lean_code, tuple(cases))


def _section(section: ExplanationSection) -> ExplanationSection:
    return ExplanationSection(
        id=section.id,
        title=section.title,
        summary=section.summary,
        references=tuple(
            LeanLineReference(r.start_line, r.end_line, r.excerpt) for r in section.references
        ),
    )


def qa_prompt(case_file: CaseFile, case: Case) -> str:
    return _output_review_prompt(
        theorem_statement=case_file.theorem_statement,
        lean_code=case_file.lean_code,
        explanation=case.explanation,
        language=case.language,
    )


def estimated_input_tokens(prompt: str) -> int:
    return len(prompt) // CHARS_PER_TOKEN + 1


def worst_case_usd(
    prompt: str, *, max_output_tokens: int, attempts: int, input_price: float, output_price: float
) -> float:
    per_attempt = (
        estimated_input_tokens(prompt) * input_price + max_output_tokens * output_price
    ) / 1_000_000
    return per_attempt * attempts


def actual_usd(
    records: Sequence[Mapping[str, Any]], input_price: float, output_price: float
) -> float:
    return sum(
        (
            (int(r["input_tokens"]) * input_price + int(r["output_tokens"]) * output_price)
            / 1_000_000
        )
        for r in records
    )


def run(
    argv: Sequence[str],
    *,
    environ: Mapping[str, str] | None = None,
    reviewer_factory: Callable[[], Reviewer] | None = None,
    out: Callable[[str], None] = print,
) -> int:
    args = _parser().parse_args(argv)
    env = os.environ if environ is None else environ
    try:
        case_file = load_cases(args.cases)
    except CaseFileError as exc:
        out(f"invalid case file: {exc}")
        return 2
    cases = [c for c in case_file.cases if args.group in (None, c.group)]
    prompts = {c.id: qa_prompt(case_file, c) for c in cases}
    report: dict[str, Any] = {
        "mode": "execute" if args.execute else "dry-run",
        "cases": len(cases),
        "by_group": {g: sum(1 for c in cases if c.group == g) for g in GROUPS},
        "max_prompt_chars": max(len(p) for p in prompts.values()),
    }
    priced = args.input_usd_per_mtok is not None and args.output_usd_per_mtok is not None

    if not args.execute:
        if priced:
            report["worst_case_usd"] = _total_worst_case(args, prompts, attempts=2)
            if args.budget_usd is not None:
                report["within_budget"] = report["worst_case_usd"] <= args.budget_usd
        report["note"] = "dry run: structural layer passed for every case; no model was called"
        return _emit(args, report, out, 0)

    try:
        _check_live_preconditions(args, env, priced)
        reviewer = (reviewer_factory or _production_reviewer)()
        worst = _total_worst_case(args, prompts, attempts=reviewer.max_attempts)
        report["worst_case_usd"] = worst
        if worst > args.budget_usd:
            raise Refused(f"worst-case cost {worst:.4f} USD exceeds the budget {args.budget_usd}")
    except Refused as exc:
        out(f"refused: {exc}")
        return 2
    return _emit_live(args, case_file, cases, prompts, reviewer, report, out)


def _total_worst_case(
    args: argparse.Namespace, prompts: Mapping[str, str], *, attempts: int
) -> float:
    return sum(
        worst_case_usd(
            p,
            max_output_tokens=args.max_output_tokens,
            attempts=attempts,
            input_price=args.input_usd_per_mtok,
            output_price=args.output_usd_per_mtok,
        )
        for p in prompts.values()
    )


def _check_live_preconditions(
    args: argparse.Namespace, env: Mapping[str, str], priced: bool
) -> None:
    if not (env.get("PALS_OPENAI_API_KEY") or env.get("OPENAI_API_KEY")):
        raise Refused("PALS_OPENAI_API_KEY or OPENAI_API_KEY is required for --execute")
    if args.budget_usd is None or args.budget_usd <= 0:
        raise Refused("--budget-usd (> 0) is required for --execute")
    if not priced:
        raise Refused("--input-usd-per-mtok and --output-usd-per-mtok are required for --execute")


class RecordingClient:
    """Transparent wrapper that keeps the reviewer's raw answers for the report."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.outputs: list[str] = []

    def generate(self, *, model: str, prompt: str, timeout_seconds: float | None = None) -> str:
        if timeout_seconds is None:
            output: str = self.inner.generate(model=model, prompt=prompt)
        else:
            output = self.inner.generate(
                model=model, prompt=prompt, timeout_seconds=timeout_seconds
            )
        self.outputs.append(output)
        return output


def _production_reviewer() -> Reviewer:
    import dataclasses

    from pals_agent.factory import build_proof_output_reviewer
    from pals_agent.settings import AgentSettings

    reviewer = build_proof_output_reviewer(AgentSettings.from_env())
    return dataclasses.replace(reviewer, client=RecordingClient(reviewer.client))  # type: ignore[return-value]


def _emit_live(
    args: argparse.Namespace,
    case_file: CaseFile,
    cases: Sequence[Case],
    prompts: Mapping[str, str],
    reviewer: Reviewer,
    report: dict[str, Any],
    out: Callable[[str], None],
) -> int:
    from pals_agent.usage import capture_usage

    spent = 0.0
    results: list[dict[str, Any]] = []
    stopped_early = False
    for case in cases:
        next_worst = worst_case_usd(
            prompts[case.id],
            max_output_tokens=args.max_output_tokens,
            attempts=reviewer.max_attempts,
            input_price=args.input_usd_per_mtok,
            output_price=args.output_usd_per_mtok,
        )
        if spent + next_worst > args.budget_usd:
            stopped_early = True
            break
        decision = "error"
        detail: dict[str, Any] = {"category": None, "rationale": "", "reviewer_session_id": None}
        recorder = getattr(reviewer, "client", None)
        raw_outputs: list[str] | None = (
            recorder.outputs if isinstance(recorder, RecordingClient) else None
        )
        if raw_outputs is not None:
            raw_outputs.clear()
        with capture_usage() as records:
            try:
                review = reviewer.review_explanation(
                    theorem_statement=case_file.theorem_statement,
                    lean_code=case_file.lean_code,
                    explanation=case.explanation,
                    language=case.language,
                )
                decision = "approve"
                detail.update(
                    category="approved",
                    rationale=review.rationale,
                    reviewer_session_id=review.session_id,
                )
            except ProofOutputReviewError as exc:
                decision = "reject" if exc.category == "rejected" else "error"
                detail.update(
                    category=exc.category,
                    rationale=exc.rationale,
                    reviewer_session_id=exc.session_id,
                )
            except Exception as exc:  # noqa: BLE001 - report as an error, never as a decision
                decision = "error"
                detail.update(category=f"exception:{type(exc).__name__}")
        spent += actual_usd(records, args.input_usd_per_mtok, args.output_usd_per_mtok)
        results.append(
            {
                "id": case.id,
                "group": case.group,
                "expected": case.expected,
                "actual": decision,
                **detail,
                # The reviewer's structured JSON answers, one per attempt, exactly as returned.
                "raw_reviewer_outputs": list(raw_outputs) if raw_outputs is not None else [],
            }
        )
    report["results"] = results
    report["spent_usd"] = round(spent, 6)
    report["stopped_early_for_budget"] = stopped_early
    report["summary"] = summarize(results)
    ok = (
        not stopped_early
        and len(results) == len(cases)
        and all(r["actual"] == r["expected"] for r in results)
    )
    return _emit(args, report, out, 0 if ok else 1)


def summarize(results: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    by_group: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in results:
        by_group[r["group"]][r["actual"]] += 1
    wrong = [r for r in results if r["expected"] == "reject"]
    valid = [r for r in results if r["expected"] == "approve"]
    return {
        "by_group": {g: dict(v) for g, v in by_group.items()},
        "false_accepts": sum(r["actual"] == "approve" for r in wrong),
        "false_rejects": sum(r["actual"] == "reject" for r in valid),
        "errors": sum(r["actual"] == "error" for r in results),
        "mismatched_ids": [r["id"] for r in results if r["actual"] != r["expected"]],
    }


def _emit(
    args: argparse.Namespace, report: dict[str, Any], out: Callable[[str], None], code: int
) -> int:
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    out(text)
    if args.json_out is not None:
        args.json_out.write_text(text + "\n", encoding="utf-8")
    return code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--group", choices=GROUPS, default=None, help="run only one group")
    parser.add_argument("--execute", action="store_true", help="call the real model (see docs)")
    parser.add_argument("--budget-usd", type=float, default=None)
    parser.add_argument("--input-usd-per-mtok", type=float, default=None)
    parser.add_argument("--output-usd-per-mtok", type=float, default=None)
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=16384,
        help="per-call output bound for the worst-case estimate (production cap: 16384)",
    )
    parser.add_argument("--json-out", type=Path, default=None)
    return parser


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
