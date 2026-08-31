import copy
import inspect
from collections.abc import Callable
from typing import Any

import pytest

from pals_agent.evaluation import (
    EVALUATION_STAGES,
    EvaluationStageResult,
    evaluate_artifact,
)

LEAN_CODE = """import Mathlib
theorem demo : True := by
  trivial"""
BROKEN_LEAN_CODE = LEAN_CODE.replace("trivial", "missing")


def _diagnostic(code: str = "lean.error") -> dict[str, Any]:
    return {
        "severity": "error",
        "code": code,
        "message": "Unknown identifier",
    }


def _attempt(
    number: int,
    *,
    success: bool,
    lean_code: str,
    route: str | None = None,
    checkpoint_status: str = "published",
) -> dict[str, Any]:
    diagnostics = [] if success else [_diagnostic()]
    value: dict[str, Any] = {
        "attempt": number,
        "phase": "compile",
        "generated": {"lean_code": lean_code},
        "verification": {
            "success": success,
            "diagnostics": diagnostics,
        },
        "diagnostics": diagnostics,
        "checkpoint_status": checkpoint_status,
    }
    if route is not None:
        value["repair_route"] = {"route": route}
    return value


def _verified_artifact() -> dict[str, Any]:
    return {
        "retrieval": {
            "candidate_draft_id": "draft-1",
            "exact_equivalence": True,
            "scores": {"final": 0.75},
        },
        "model_attempt": {
            "lean_code": BROKEN_LEAN_CODE,
            "draft": {"text": "Use the constructor for True."},
            "sketch": {"lean_code": BROKEN_LEAN_CODE, "has_gaps": True},
        },
        "model_attempt_verification": {
            "success": False,
            "diagnostics": [_diagnostic()],
        },
        "attempts": [
            _attempt(1, success=False, lean_code=BROKEN_LEAN_CODE),
            _attempt(2, success=True, lean_code=LEAN_CODE, route="prove"),
        ],
        "repairs_used": 1,
        "max_repair_attempts": 12,
        "termination_reason": "verified",
        "termination_event": {
            "reason": "verified",
            "attempt": 2,
            "source": "verification_success",
        },
        "generated": {"lean_code": LEAN_CODE},
        "verification": {"success": True, "diagnostics": []},
    }


def _explanation() -> dict[str, Any]:
    return {
        "overview": "検証済みの Lean 証明の流れを簡潔に説明します。",
        "sections": [
            {
                "id": "finish-proof",
                "title": "証明を完了する",
                "summary": "trivial が True の標準的な証明を構成します。",
                "references": [
                    {
                        "start_line": 3,
                        "end_line": 3,
                        "excerpt": "  trivial",
                    }
                ],
            }
        ],
        "conclusion": "したがって、対象の命題 True が厳密に証明されました。",
    }


def _clarification() -> dict[str, Any]:
    return {
        "section_id": "finish-proof",
        "question": "trivial はなぜこのゴールを閉じられるのですか。",
        "answer": (
            "現在のゴールは True なので、trivial はその標準的なコンストラクタを"
            "適用し、追加の仮定や未解決ゴールを残さずに証明を完了します。"
        ),
        "key_points": [
            "ゴールは True です。",
            "標準コンストラクタで証明が閉じます。",
        ],
        "references": [
            {"start_line": 3, "end_line": 3, "excerpt": "  trivial"}
        ],
    }


def _evaluate(
    artifact: dict[str, Any],
    *,
    explanation: Any = None,
    clarifications: Any = None,
    expect_clarification: Any = False,
) -> tuple[EvaluationStageResult, ...]:
    kwargs: dict[str, Any] = {
        "suite_revision": "suite-v2",
        "run_id": "run-1",
        "case_id": "case-1",
        "model": "proof-model",
        "explanation": explanation,
        "clarifications": clarifications,
        "created_at": "2026-07-14T00:00:00+09:00",
    }
    if "expect_clarification" in inspect.signature(evaluate_artifact).parameters:
        kwargs["expect_clarification"] = expect_clarification
    return evaluate_artifact(artifact, **kwargs).stages


def _stage(
    artifact: dict[str, Any],
    name: str,
    **kwargs: Any,
) -> EvaluationStageResult:
    stages = _evaluate(artifact, **kwargs)
    return next(stage for stage in stages if stage.stage == name)


def test_pae_007_emits_exact_canonical_stage_order() -> None:
    stages = _evaluate({})

    assert tuple(stage.stage for stage in stages) == EVALUATION_STAGES


def test_pae_009_verified_flow_accepts_explicit_clarification_expectation() -> None:
    assert "expect_clarification" in inspect.signature(evaluate_artifact).parameters


@pytest.mark.parametrize(
    ("artifact", "expected_status", "expected"),
    [
        ({}, "not_evaluated", {"candidate_present": None, "top_score_present": None}),
        (
            {"retrieval": None},
            "failed",
            {"candidate_present": False, "top_score_present": False},
        ),
        (
            {"retrieval": {"candidate_draft_id": "draft", "scores": {"final": 2.0}}},
            "failed",
            {"candidate_present": True, "top_score_present": False, "top_score": None},
        ),
        (
            {
                "retrieval": {
                    "candidate_draft_id": "draft",
                    "exact_equivalence": "true",
                    "scores": {"final": -1.0},
                }
            },
            "passed",
            {
                "candidate_present": True,
                "exact_equivalence": False,
                "top_score_present": True,
                "top_score": -1.0,
            },
        ),
    ],
)
def test_pae_008_retrieval_absent_and_malformed_matrix(
    artifact: dict[str, Any],
    expected_status: str,
    expected: dict[str, Any],
) -> None:
    stage = _stage(artifact, "retrieval")

    assert stage.status == expected_status
    for name, value in expected.items():
        assert stage.metric(name).value == value


@pytest.mark.parametrize(
    ("stage_name", "artifact", "expected"),
    [
        (
            "draft",
            {"model_attempt": {"draft": None}},
            {"output_present": False, "output_nonempty": False},
        ),
        (
            "sketch",
            {"model_attempt": {"sketch": {"lean_code": ""}}},
            {"code_present": True, "code_nonempty": False, "has_gaps": False},
        ),
        (
            "prove",
            {"model_attempt": {}},
            {"code_extracted": False, "compile_success": False},
        ),
        (
            "prove",
            {"model_attempt": "wrong", "model_attempt_verification": {"success": True}},
            {"code_extracted": False, "compile_success": True},
        ),
        (
            "end_to_end",
            {"generated": None},
            {"verified": False, "final_code_present": False},
        ),
        (
            "end_to_end",
            {"verification": {"success": "true"}, "generated": {"lean_code": LEAN_CODE}},
            {"verified": False, "final_code_present": True},
        ),
    ],
)
def test_pae_008_present_stage_evidence_is_evaluated_false_when_malformed(
    stage_name: str,
    artifact: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    stage = _stage(artifact, stage_name)

    assert stage.status == "failed"
    for name, value in expected.items():
        metric = stage.metric(name)
        assert metric.status == "evaluated"
        assert metric.value == value


@pytest.mark.parametrize("verification", [None, False, "true", 1])
def test_pae_001_009_unverified_explanation_is_never_evaluated(
    verification: Any,
) -> None:
    artifact = _verified_artifact()
    if verification is None:
        artifact.pop("verification")
    else:
        artifact["verification"] = {"success": verification}

    stage = _stage(artifact, "explanation", explanation=_explanation())

    assert stage.status == "not_evaluated"
    assert all(metric.status == "not_evaluated" for metric in stage.metrics)
    assert all(metric.value is None for metric in stage.metrics)


def test_pae_008_009_verified_missing_explanation_is_an_evaluated_failure() -> None:
    stage = _stage(_verified_artifact(), "explanation", explanation=None)

    assert stage.status == "failed"
    assert stage.metric("payload_present").value is False
    assert stage.metric("shape_valid").value is False
    assert stage.metric("reference_count").value == 0
    assert stage.metric("valid_reference_count").value == 0
    assert stage.metric("references_valid").value is False
    assert stage.metric("reference_coverage").value == 0.0


def test_pae_002_009_verified_explanation_requires_shape_and_exact_references() -> None:
    stage = _stage(
        _verified_artifact(),
        "explanation",
        explanation=_explanation(),
        expect_clarification=False,
    )

    assert stage.status == "passed"
    assert stage.metric("payload_present").value is True
    assert stage.metric("shape_valid").value is True
    assert stage.metric("references_valid").value is True
    assert stage.metric("reference_count").value == 1
    assert stage.metric("valid_reference_count").value == 1
    assert stage.metric("reference_coverage").value == pytest.approx(1 / 3)
    for name in (
        "clarification_count",
        "clarifications_complete",
        "clarification_references_valid",
        "clarification_section_overlap",
    ):
        assert stage.metric(name).status == "not_evaluated"


def _replace_overview_with_english(value: dict[str, Any]) -> None:
    value["overview"] = "English only"


def _replace_title_with_overflow(value: dict[str, Any]) -> None:
    value["sections"][0]["title"] = "証" * 81


def _replace_summary_with_overflow(value: dict[str, Any]) -> None:
    value["sections"][0]["summary"] = "証" * 801


def _replace_sections_with_overflow(value: dict[str, Any]) -> None:
    value["sections"] = [copy.deepcopy(value["sections"][0]) for _ in range(21)]
    for index, section in enumerate(value["sections"]):
        section["id"] = f"section-{index}"


def _replace_references_with_overflow(value: dict[str, Any]) -> None:
    reference = value["sections"][0]["references"][0]
    value["sections"][0]["references"] = [copy.deepcopy(reference) for _ in range(21)]


@pytest.mark.parametrize(
    "mutate",
    [
        _replace_title_with_overflow,
        _replace_summary_with_overflow,
        _replace_sections_with_overflow,
        _replace_references_with_overflow,
    ],
)
def test_pae_002_shape_valid_enforces_text_and_cardinality_bounds(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    explanation = _explanation()
    mutate(explanation)

    stage = _stage(_verified_artifact(), "explanation", explanation=explanation)

    assert stage.status == "failed"
    assert stage.metric("payload_present").value is True
    assert stage.metric("shape_valid").value is False


def test_pae_002_shape_valid_accepts_english_learner_content() -> None:
    explanation = _explanation()
    _replace_overview_with_english(explanation)

    stage = _stage(_verified_artifact(), "explanation", explanation=explanation)

    assert stage.status == "passed"
    assert stage.metric("shape_valid").value is True


@pytest.mark.parametrize("clarifications", [None, [], {}, "wrong"])
def test_pae_004_009_expected_clarification_absence_or_wrong_shape_fails(
    clarifications: Any,
) -> None:
    stage = _stage(
        _verified_artifact(),
        "explanation",
        explanation=_explanation(),
        clarifications=clarifications,
        expect_clarification=True,
    )

    assert stage.status == "failed"
    assert stage.metric("clarification_count").value == 0
    assert stage.metric("clarifications_complete").value is False
    assert stage.metric("clarification_references_valid").value is False
    assert stage.metric("clarification_section_overlap").value is False


def test_pae_004_009_expected_clarification_enforces_detail_and_overlap() -> None:
    stage = _stage(
        _verified_artifact(),
        "explanation",
        explanation=_explanation(),
        clarifications=[_clarification()],
        expect_clarification=True,
    )

    assert stage.status == "passed"
    assert stage.metric("clarification_count").value == 1
    assert stage.metric("clarifications_complete").value is True
    assert stage.metric("clarification_references_valid").value is True
    assert stage.metric("clarification_section_overlap").value is True


@pytest.mark.parametrize(
    "mutate",
        [
            lambda value: value.update(answer="短い回答です。"),
            lambda value: value.update(key_points=["一つだけです。"]),
        lambda value: value.update(key_points=["点" * 501, "二つ目です。"]),
        lambda value: value.update(
            references=[{"start_line": 1, "end_line": 1, "excerpt": "import Mathlib"}]
        ),
    ],
)
def test_pae_004_clarification_shape_bounds_and_non_repetition_fail_closed(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    clarification = _clarification()
    mutate(clarification)

    stage = _stage(
        _verified_artifact(),
        "explanation",
        explanation=_explanation(),
        clarifications=[clarification],
        expect_clarification=True,
    )

    assert stage.status == "failed"


def test_pae_004_clarification_shape_accepts_english_answer() -> None:
    clarification = _clarification()
    clarification["answer"] = (
        "This answer explains how the cited Lean line closes the proof goal directly."
    )

    stage = _stage(
        _verified_artifact(),
        "explanation",
        explanation=_explanation(),
        clarifications=[clarification],
        expect_clarification=True,
    )

    assert stage.status == "passed"


def test_pae_009_missing_expect_clarification_cannot_upgrade_a_valid_explanation() -> None:
    stage = _stage(
        _verified_artifact(),
        "explanation",
        explanation=_explanation(),
        expect_clarification=None,
    )

    assert stage.status == "not_evaluated"
    assert stage.metric("payload_present").value is True
    assert stage.metric("shape_valid").value is True
    assert stage.metric("references_valid").value is True
    assert stage.metric("clarification_count").status == "not_evaluated"


_MANDATORY_REPAIR_KEYS = (
    "attempts",
    "repairs_used",
    "max_repair_attempts",
    "termination_reason",
    "termination_event",
    "generated",
    "verification",
)


@pytest.mark.parametrize("missing_key", _MANDATORY_REPAIR_KEYS)
def test_pae_008_016_absent_repair_provenance_is_not_evaluated(
    missing_key: str,
) -> None:
    artifact = _verified_artifact()
    artifact.pop(missing_key)

    stage = _stage(artifact, "repair")

    assert stage.status == "not_evaluated"
    assert all(metric.status == "not_evaluated" for metric in stage.metrics)
    assert all(metric.value is None for metric in stage.metrics)


@pytest.mark.parametrize("malformed_key", _MANDATORY_REPAIR_KEYS)
def test_pae_008_016_present_malformed_repair_provenance_fails(
    malformed_key: str,
) -> None:
    artifact = _verified_artifact()
    artifact[malformed_key] = None

    stage = _stage(artifact, "repair")

    assert stage.status == "failed"
    assert False in {
        stage.metric("attempt_count_consistent").value,
        stage.metric("termination_reason_consistent").value,
    }


def test_pae_016_complete_verified_repair_provenance_passes() -> None:
    stage = _stage(_verified_artifact(), "repair")

    assert stage.status == "passed"
    assert stage.metric("attempts").value == 1
    assert stage.metric("repairs_used").value == 1
    assert stage.metric("max_repair_attempts").value == 12
    assert stage.metric("attempt_count_consistent").value is True
    assert stage.metric("error_reduction").value == 1
    assert stage.metric("converged").value is True
    assert stage.metric("termination_reason").value == "verified"
    assert stage.metric("termination_reason_consistent").value is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["attempts"][1].update(attempt=3),
        lambda value: value["attempts"][0]["verification"].update(success=True),
        lambda value: value["attempts"][1].pop("repair_route"),
        lambda value: value["attempts"][0].update(checkpoint_status="failed"),
        lambda value: value["generated"].update(lean_code=BROKEN_LEAN_CODE),
        lambda value: value["verification"].update(success=False),
        lambda value: value["termination_event"].update(source="repair_budget"),
        lambda value: value.update(repairs_used=2),
        lambda value: value.update(max_repair_attempts=65),
    ],
)
def test_pae_016_repair_sequence_and_terminal_inconsistencies_fail(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    artifact = _verified_artifact()
    mutate(artifact)

    assert _stage(artifact, "repair").status == "failed"


@pytest.mark.parametrize(
    ("reason", "source", "checkpoint_status"),
    [
        ("non_repairable_failure", "verifier_configuration", "published"),
        ("repair_generator_unavailable", "repair_generator", "published"),
        ("repair_route_selection_failed", "repair_route_selector", "published"),
        ("artifact_store_failure", "artifact_store", "failed"),
    ],
)
def test_pae_016_consistent_nonconverged_terminal_reasons_fail_honestly(
    reason: str,
    source: str,
    checkpoint_status: str,
) -> None:
    artifact = _verified_artifact()
    artifact["attempts"] = [
        _attempt(
            1,
            success=False,
            lean_code=BROKEN_LEAN_CODE,
            checkpoint_status=checkpoint_status,
        )
    ]
    artifact["repairs_used"] = 0
    artifact["generated"] = {"lean_code": BROKEN_LEAN_CODE}
    artifact["verification"] = {"success": False, "diagnostics": [_diagnostic()]}
    artifact["termination_reason"] = reason
    artifact["termination_event"] = {"reason": reason, "attempt": 1, "source": source}

    stage = _stage(artifact, "repair")

    assert stage.status == "failed"
    assert stage.metric("attempt_count_consistent").value is True
    assert stage.metric("converged").value is False
    assert stage.metric("termination_reason_consistent").value is True


def test_pae_016_consistent_budget_exhaustion_fails_honestly() -> None:
    artifact = _verified_artifact()
    artifact["attempts"][1] = _attempt(
        2,
        success=False,
        lean_code=BROKEN_LEAN_CODE,
        route="prove",
    )
    artifact["repairs_used"] = 1
    artifact["max_repair_attempts"] = 1
    artifact["generated"] = {"lean_code": BROKEN_LEAN_CODE}
    artifact["verification"] = {"success": False, "diagnostics": [_diagnostic()]}
    artifact["termination_reason"] = "repair_budget_exhausted"
    artifact["termination_event"] = {
        "reason": "repair_budget_exhausted",
        "attempt": 2,
        "source": "repair_budget",
    }

    stage = _stage(artifact, "repair")

    assert stage.status == "failed"
    assert stage.metric("attempt_count_consistent").value is True
    assert stage.metric("termination_reason_consistent").value is True
