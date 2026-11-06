"""Dry-run and stubbed-live tests for scripts/evaluate_explanation_qa.py (no model is called)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pals_agent.explanations import (
    EPSILON_DELTA_CHECK_IDS,
    ProofExplanation,
    ProofOutputReview,
    ProofOutputReviewError,
    ReviewCheck,
)
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


def _checks(failing: tuple[str, ...]) -> tuple[ReviewCheck, ...]:
    return tuple(
        ReviewCheck(
            id=i,
            status="missing" if i in failing else "ok",
            quote="",
            note="gap" if i in failing else "",
        )
        for i in EPSILON_DELTA_CHECK_IDS
    )


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

    def __init__(
        self,
        *,
        flip: set[str] = frozenset(),  # type: ignore[assignment]
        error: bool = False,
        contradicted: set[str] = frozenset(),  # type: ignore[assignment]
    ) -> None:
        self.contradicted = contradicted
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
                "no",
                category="rejected",
                rationale="delta fails",
                session_id="sess-no",
                samples=(_checks(case.expected_failed_checks),) * 2,
            )
        return ProofOutputReview(
            "explanation",
            "p",
            "m",
            "sess-ok",
            "looks valid",
            samples=(_checks(()),) * 2,
            approved_flag_contradicted_checks=case.id in self.contradicted,
        )


def test_case_file_has_the_required_shape_and_passes_the_structural_layer() -> None:
    case_file = qa.load_cases(qa.DEFAULT_CASES)
    groups = [c.group for c in case_file.cases]
    assert groups.count("valid_notation") == 20
    assert groups.count("wrong") == 22
    assert groups.count("summary_first") == 3
    assert {c.expected for c in case_file.cases if c.group == "valid_notation"} == {"approve"}
    assert {c.expected for c in case_file.cases if c.group != "valid_notation"} == {"reject"}
    for case in case_file.cases:
        assert "EPSILON-DELTA REQUIREMENT" in qa.qa_prompt(case_file, case)


def test_valid_cases_give_a_reason_for_positivity_and_the_sum_bound() -> None:
    """Each valid case states why delta > 0 and why |x+a| < 2|a|+1 (one phrase is enough)."""
    for case in qa.load_cases(qa.DEFAULT_CASES).cases:
        if case.group != "valid_notation":
            continue
        text = " ".join(section.summary for section in case.explanation.sections)
        assert any(
            phrase in text
            for phrase in ("triangle inequality", "三角不等式", "|2a+(x-a)|", "|a|+|x-a|")
        ), case.id
        assert any(phrase in text for phrase in ("positive", "正", "min")), case.id


def test_dry_run_is_the_default_needs_no_key_and_calls_no_model() -> None:
    def forbidden() -> Any:
        raise AssertionError("dry run must not build a reviewer")

    code, lines = _run([], environ={}, reviewer_factory=forbidden)
    report = json.loads(lines[0])
    assert code == 0
    assert report["mode"] == "dry-run"
    assert report["cases"] == 45
    assert report["by_group"] == {"valid_notation": 20, "wrong": 22, "summary_first": 3}
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
    assert reviewer.calls == 45
    assert report["summary"]["false_accepts"] == 0
    assert report["summary"]["false_rejects"] == 0
    assert report["spent_usd"] == pytest.approx(45 * (3000 * 1 + 500 * 4) / 1_000_000)


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


def test_report_lists_the_checks_and_whether_the_approved_flag_contradicted_them() -> None:
    reviewer = StubReviewer(contradicted={"valid-02-dfrac-vert-equality-end"})
    code, lines = _run(LIVE, environ=KEY, reviewer_factory=lambda: reviewer)
    report = json.loads(lines[0])
    results = {r["id"]: r for r in report["results"]}
    assert code == 0
    assert results["valid-02-dfrac-vert-equality-end"]["approved_flag_contradicted_checks"]
    assert not results["valid-01-base"]["approved_flag_contradicted_checks"]
    assert report["summary"]["approved_flag_contradictions"] == 1
    # Each independent review sample is kept; the two-sample review reports both.
    assert len(results["valid-01-base"]["samples"]) == 2
    assert [c["id"] for c in results["valid-01-base"]["samples"][0]] == list(
        EPSILON_DELTA_CHECK_IDS
    )
    rejected = results["wrong-01-epsilon-plus-one"]
    assert rejected["expected_failed_checks"] == ["final_inequality"]
    assert rejected["failed_checks"] == ["final_inequality"]
    assert report["summary"]["rejected_for_an_unexpected_check"] == []


def test_a_rejection_for_another_element_than_the_case_was_built_for_is_reported() -> None:
    class Elsewhere(StubReviewer):
        def review_explanation(self, *, explanation: ProofExplanation, **kwargs: Any) -> Any:
            case = self.expected[_key(explanation)]
            if case.id == "wrong-01-epsilon-plus-one":
                self.calls += 1
                raise ProofOutputReviewError(
                    "no", category="rejected", rationale="r", samples=(_checks(("conclusion",)),)
                )
            return super().review_explanation(explanation=explanation, **kwargs)

    _, lines = _run(LIVE, environ=KEY, reviewer_factory=lambda: Elsewhere())
    assert json.loads(lines[0])["summary"]["rejected_for_an_unexpected_check"] == [
        "wrong-01-epsilon-plus-one"
    ]


def test_repeats_run_every_case_n_times_and_report_agreement_per_case() -> None:
    reviewer = StubReviewer(flip={"valid-01-base"})
    argv = [*LIVE, "--repeats", "3"]
    code, lines = _run(argv, environ=KEY, reviewer_factory=lambda: reviewer)
    report = json.loads(lines[0])
    assert code == 1
    assert report["repeats"] == 3
    assert reviewer.calls == 135
    assert report["summary"]["runs"] == 135
    assert report["summary"]["false_rejects"] == 3
    assert report["summary"]["agreement_by_case"]["valid-01-base"] == {
        "runs": 3,
        "agree": 0,
        "rate": 0.0,
    }
    assert report["summary"]["agreement_by_case"]["valid-02-dfrac-vert-equality-end"]["rate"] == 1.0
    assert {r["repeat"] for r in report["results"]} == {1, 2, 3}


def test_repeats_scale_the_worst_case_estimate_and_must_be_positive() -> None:
    priced = ["--input-usd-per-mtok", "1", "--output-usd-per-mtok", "4"]
    _, once = _run(priced)
    _, thrice = _run([*priced, "--repeats", "3"])
    assert json.loads(thrice[0])["worst_case_usd"] == pytest.approx(
        3 * json.loads(once[0])["worst_case_usd"]
    )
    code, lines = _run(["--repeats", "0"])
    assert code == 2 and "repeats" in lines[0]


def test_every_rejected_case_names_the_checks_it_fails_and_presentation_cases_a_quote() -> None:
    for case in qa.load_cases(qa.DEFAULT_CASES).cases:
        if case.expected != "reject":
            continue
        assert case.expected_failed_checks, case.id
        assert set(case.expected_failed_checks) <= set(EPSILON_DELTA_CHECK_IDS)
        if case.group == "summary_first":
            assert case.expected_failed_checks == ("presentation",)
            proof = "".join(
                (
                    case.explanation.overview
                    + "".join(sec.summary for sec in case.explanation.sections)
                    + case.explanation.conclusion
                ).split()
            )
            assert "".join((case.defect_quote or "").split()) in proof, case.id
    covered = {i for c in qa.load_cases(qa.DEFAULT_CASES).cases for i in c.expected_failed_checks}
    assert covered == set(EPSILON_DELTA_CHECK_IDS)  # every element has a wrong case


def test_a_rejected_case_without_a_quotable_defect_is_an_invalid_case_file(
    tmp_path: Path,
) -> None:
    document = json.loads(qa.DEFAULT_CASES.read_text(encoding="utf-8"))
    target = next(c for c in document["cases"] if c["id"] == "wrong-03-delta-ignores-point")
    target["defect_quote"] = "this passage is not in the explanation"
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    code, lines = _run(["--cases", str(path)])
    assert code == 2
    assert "defect_quote" in lines[0]


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
    assert summary["errors"] == 45
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
        "2.0",
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
    assert reviewer.calls == len(report["results"]) < 45
    # Each call spends about 0.3 USD; the guard stops before the budget is overshot by much.
    assert report["spent_usd"] < 2.0 + 0.35


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
