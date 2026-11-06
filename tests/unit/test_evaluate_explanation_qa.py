"""Dry-run and stubbed-live tests for scripts/evaluate_explanation_qa.py (no model is called)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pals_agent.explanations import ProofExplanation, ProofOutputReview, ProofOutputReviewError
from pals_agent.usage import report_usage

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_explanation_qa.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("evaluate_explanation_qa", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["evaluate_explanation_qa"] = module
    spec.loader.exec_module(module)
    return module


qa = _load()
LIVE = [
    "--execute",
    "--budget-usd",
    "50",
    "--input-usd-per-mtok",
    "1",
    "--output-usd-per-mtok",
    "4",
]
KEY = {"OPENAI_API_KEY": "test-key-not-real"}


def _run(argv: list[str], **kwargs: Any) -> tuple[int, list[str]]:
    lines: list[str] = []
    code = qa.run(argv, out=lines.append, **kwargs)
    return code, lines


def _key(explanation: ProofExplanation) -> str:
    return "\n".join(
        [
            explanation.overview,
            *(sec.summary for sec in explanation.sections),
            explanation.conclusion,
        ]
    )


class StubReviewer:
    """Approves the cases expected to be approved; records spend through the usage scope."""

    max_attempts = 2

    def __init__(self, *, flip: set[str] = frozenset(), error: bool = False) -> None:  # type: ignore[assignment]
        case_file = qa.load_cases(qa.DEFAULT_CASES)
        self.expected = {_key(c.explanation): c for c in case_file.cases}
        self.flip = flip
        self.error = error
        self.calls = 0

    def review_explanation(self, *, explanation: ProofExplanation, **_: Any) -> ProofOutputReview:
        self.calls += 1
        report_usage(
            "11111111-1111-4111-8111-111111111111",
            "gpt-6-luna",
            {"input_tokens": 3000, "output_tokens": 500},
        )
        if self.error:
            raise ProofOutputReviewError("down", category="transport")
        case = self.expected[_key(explanation)]
        approve = (case.expected == "approve") != (case.id in self.flip)
        if not approve:
            raise ProofOutputReviewError(
                "no", category="rejected", rationale="delta fails", session_id="sess-no"
            )
        return ProofOutputReview("explanation", "p", "m", "sess-ok", "looks valid")


def test_case_file_has_the_required_shape_and_passes_the_structural_layer() -> None:
    case_file = qa.load_cases(qa.DEFAULT_CASES)
    groups = [c.group for c in case_file.cases]
    assert groups.count("valid_notation") == 10
    assert groups.count("wrong") == 10
    assert groups.count("summary_first") == 3
    assert {c.expected for c in case_file.cases if c.group == "valid_notation"} == {"approve"}
    assert {c.expected for c in case_file.cases if c.group != "valid_notation"} == {"reject"}
    for case in case_file.cases:
        assert "EPSILON-DELTA REQUIREMENT" in qa.qa_prompt(case_file, case)


def test_valid_cases_justify_every_step_so_a_rejection_cannot_blame_the_case() -> None:
    """v1.0 asserted positivity and |x| < |a| + 1 without reason; a strict reviewer may object."""
    for case in qa.load_cases(qa.DEFAULT_CASES).cases:
        if case.group != "valid_notation":
            continue
        text = " ".join(section.summary for section in case.explanation.sections)
        assert "triangle inequality" in text or "三角不等式" in text, case.id
        assert "positive" in text or "正" in text, case.id
        assert "|x-a|<\\delta" in text.replace("\\lvert ", "|").replace("\\rvert ", "|").replace(
            "\\vert ", "|"
        ).replace("|y-b|", "|x-a|"), case.id
        assert len(case.explanation.sections) == 2, case.id


def test_dry_run_is_the_default_needs_no_key_and_calls_no_model() -> None:
    def forbidden() -> Any:
        raise AssertionError("dry run must not build a reviewer")

    code, lines = _run([], environ={}, reviewer_factory=forbidden)
    report = json.loads(lines[0])
    assert code == 0
    assert report["mode"] == "dry-run"
    assert report["cases"] == 23
    assert report["by_group"] == {"valid_notation": 10, "wrong": 10, "summary_first": 3}
    assert "no model was called" in report["note"]


def test_dry_run_reports_worst_case_cost_when_prices_are_given() -> None:
    code, lines = _run(
        ["--input-usd-per-mtok", "1", "--output-usd-per-mtok", "4", "--budget-usd", "0.0001"]
    )
    report = json.loads(lines[0])
    assert code == 0
    assert report["worst_case_usd"] > 0
    assert report["within_budget"] is False


@pytest.mark.parametrize(
    ("argv", "environ", "needle"),
    [
        (LIVE, {}, "API_KEY"),
        (["--execute", "--input-usd-per-mtok", "1", "--output-usd-per-mtok", "4"], KEY, "budget"),
        (["--execute", "--budget-usd", "5"], KEY, "per-mtok"),
        (
            [
                "--execute",
                "--budget-usd",
                "0",
                "--input-usd-per-mtok",
                "1",
                "--output-usd-per-mtok",
                "4",
            ],
            KEY,
            "budget",
        ),
        (
            [
                "--execute",
                "--budget-usd",
                "0.001",
                "--input-usd-per-mtok",
                "1",
                "--output-usd-per-mtok",
                "4",
            ],
            KEY,
            "exceeds the budget",
        ),
    ],
)
def test_live_run_is_refused_without_key_budget_prices_or_headroom(
    argv: list[str], environ: dict[str, str], needle: str
) -> None:
    reviewer = StubReviewer()
    code, lines = _run(argv, environ=environ, reviewer_factory=lambda: reviewer)
    assert code == 2
    assert needle in lines[0]
    assert reviewer.calls == 0


def test_live_run_with_expected_decisions_exits_zero_and_accounts_cost() -> None:
    reviewer = StubReviewer()
    code, lines = _run(LIVE, environ=KEY, reviewer_factory=lambda: reviewer)
    report = json.loads(lines[0])
    assert code == 0
    assert reviewer.calls == 23
    assert report["summary"]["false_accepts"] == 0
    assert report["summary"]["false_rejects"] == 0
    assert report["spent_usd"] == pytest.approx(23 * (3000 * 1 + 500 * 4) / 1_000_000)


def test_report_carries_each_reviewers_reason_category_and_raw_output() -> None:
    code, lines = _run(LIVE, environ=KEY, reviewer_factory=lambda: StubReviewer())
    results = {r["id"]: r for r in json.loads(lines[0])["results"]}
    assert code == 0
    approved = results["valid-01-base"]
    assert (approved["category"], approved["rationale"]) == ("approved", "looks valid")
    assert approved["reviewer_session_id"] == "sess-ok"
    rejected = results["wrong-01-epsilon-plus-one"]
    assert (rejected["category"], rejected["rationale"]) == ("rejected", "delta fails")
    assert rejected["reviewer_session_id"] == "sess-no"
    assert all("raw_reviewer_outputs" in r for r in results.values())


def test_recording_client_keeps_raw_answers_and_forwards_the_timeout() -> None:
    class Inner:
        def __init__(self) -> None:
            self.calls: list[Any] = []

        def generate(self, *, model: str, prompt: str, timeout_seconds: float | None = None) -> str:
            self.calls.append((model, prompt, timeout_seconds))
            return '{"approved": false, "rationale": "r"}'

    inner = Inner()
    client = qa.RecordingClient(inner)
    client.generate(model="m", prompt="p")
    client.generate(model="m", prompt="q", timeout_seconds=3.0)
    assert client.outputs == ['{"approved": false, "rationale": "r"}'] * 2
    assert inner.calls == [("m", "p", None), ("m", "q", 3.0)]


def test_a_reviewer_with_a_recording_client_has_its_raw_outputs_in_the_report() -> None:
    class Recorded(StubReviewer):
        def __init__(self) -> None:
            super().__init__()
            self.client = qa.RecordingClient(None)

        def review_explanation(self, *, explanation: ProofExplanation, **kwargs: Any) -> Any:
            self.client.outputs.append('{"approved": true, "rationale": "raw"}')
            return super().review_explanation(explanation=explanation, **kwargs)

    code, lines = _run(LIVE, environ=KEY, reviewer_factory=lambda: Recorded())
    first = json.loads(lines[0])["results"][0]
    assert code == 0
    assert first["raw_reviewer_outputs"] == ['{"approved": true, "rationale": "raw"}']


def test_false_accept_and_false_reject_are_reported_and_fail_the_run() -> None:
    reviewer = StubReviewer(flip={"wrong-01-epsilon-plus-one", "valid-01-base"})
    code, lines = _run(LIVE, environ=KEY, reviewer_factory=lambda: reviewer)
    summary = json.loads(lines[0])["summary"]
    assert code == 1
    assert summary["false_accepts"] == 1
    assert summary["false_rejects"] == 1
    assert set(summary["mismatched_ids"]) == {"wrong-01-epsilon-plus-one", "valid-01-base"}


def test_review_infrastructure_errors_are_errors_not_decisions() -> None:
    code, lines = _run(LIVE, environ=KEY, reviewer_factory=lambda: StubReviewer(error=True))
    summary = json.loads(lines[0])["summary"]
    assert code == 1
    assert summary["errors"] == 23
    assert summary["false_accepts"] == 0


def test_run_stops_before_a_call_that_could_exceed_the_remaining_budget() -> None:
    class Expensive(StubReviewer):
        def review_explanation(self, *, explanation: ProofExplanation, **kwargs: Any) -> Any:
            report_usage(
                "11111111-1111-4111-8111-111111111111",
                "gpt-6-luna",
                {"input_tokens": 300_000, "output_tokens": 0},
            )
            return super().review_explanation(explanation=explanation, **kwargs)

    argv = [
        "--execute",
        "--budget-usd",
        "0.5",
        "--input-usd-per-mtok",
        "1",
        "--output-usd-per-mtok",
        "4",
        "--max-output-tokens",
        "100",
    ]
    reviewer = Expensive()
    code, lines = _run(argv, environ=KEY, reviewer_factory=lambda: reviewer)
    report = json.loads(lines[0])
    assert code == 1
    assert report["stopped_early_for_budget"] is True
    assert reviewer.calls == len(report["results"]) < 23
    # Each call spends about 0.3 USD; the guard refuses the call after the second.
    assert report["spent_usd"] < 0.5 + 0.35


def test_invalid_case_files_are_rejected_before_anything_runs(tmp_path: Path) -> None:
    document = json.loads(qa.DEFAULT_CASES.read_text(encoding="utf-8"))

    def write(mutate: Any) -> Path:
        copy = json.loads(json.dumps(document))
        mutate(copy)
        path = tmp_path / "cases.json"
        path.write_text(json.dumps(copy, ensure_ascii=False), encoding="utf-8")
        return path

    wrong_label = write(lambda d: d["cases"][10].update(expected="approve"))
    bad_reference = write(
        lambda d: d["cases"][0]["sections"][0]["references"][0].update(excerpt="invented")
    )
    for path in (wrong_label, bad_reference, tmp_path / "missing.json"):
        code, lines = _run(["--cases", str(path)])
        assert code == 2
        assert "invalid case file" in lines[0]


def test_json_out_is_written(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    code, lines = _run(["--json-out", str(target)])
    assert code == 0
    assert json.loads(target.read_text(encoding="utf-8")) == json.loads(lines[0])
