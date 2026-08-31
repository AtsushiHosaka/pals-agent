import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from pals_agent.evaluation import (
    EVALUATION_STAGES,
    EvaluationRun,
    JsonlEvaluationStore,
    compare_evaluation_runs,
    evaluate_artifact,
    summarize_evaluation_runs,
)

LEAN_CODE = """import Mathlib

theorem add_zero_nat (n : Nat) : n + 0 = n := by
  simpa using Nat.add_zero n"""


def _error(code: str) -> dict[str, str]:
    return {"severity": "error", "code": code, "message": code}


def _successful_artifact() -> dict[str, Any]:
    first_code = LEAN_CODE.replace("Nat.add_zero n", "missing_lemma n")
    return {
        "retrieval": {
            "candidate_draft_id": "continuous_add_zero",
            "exact_equivalence": True,
            "scores": {"vector": 0.9, "structural": 1.0, "final": 0.97},
        },
        "model_attempt": {
            "lean_code": first_code,
            "model": "prove-model",
            "provider": "openai",
            "draft": {"text": "Apply the natural-number addition identity."},
            "sketch": {
                "lean_code": first_code,
                "has_gaps": True,
            },
        },
        "model_attempt_verification": {
            "success": False,
            "diagnostics": [_error("lean.unknownIdentifier"), _error("lean.error")],
        },
        "generated": {
            "lean_code": LEAN_CODE,
            "model": "prove-model",
            "provider": "openai",
        },
        "verification": {"success": True, "diagnostics": []},
        "repairs_used": 1,
        "max_repair_attempts": 12,
        "termination_reason": "verified",
        "termination_event": {
            "reason": "verified",
            "attempt": 2,
            "source": "verification_success",
        },
        "attempts": [
            {
                "attempt": 1,
                "phase": "compile",
                "generated": {"lean_code": first_code},
                "verification": {
                    "success": False,
                    "diagnostics": [
                        _error("lean.unknownIdentifier"),
                        _error("lean.error"),
                    ],
                },
                "diagnostics": [
                    _error("lean.unknownIdentifier"),
                    _error("lean.error"),
                ],
                "checkpoint_status": "published",
            },
            {
                "attempt": 2,
                "phase": "compile",
                "generated": {"lean_code": LEAN_CODE},
                "verification": {"success": True, "diagnostics": []},
                "diagnostics": [],
                "checkpoint_status": "published",
                "repair_route": {"route": "prove"},
            },
        ],
    }


def _failed_artifact() -> dict[str, Any]:
    return {
        "retrieval": {
            "candidate_draft_id": None,
            "exact_equivalence": False,
            "scores": {"vector": 0.2, "structural": None, "final": None},
        },
        "model_attempt": {
            "lean_code": "",
            "draft": {"text": "   "},
            "sketch": {"lean_code": "", "has_gaps": False},
        },
        "model_attempt_verification": {
            "success": False,
            "diagnostics": [_error("pals.generation_empty")],
        },
        "generated": {"lean_code": ""},
        "verification": {
            "success": False,
            "diagnostics": [_error("lean.error"), _error("lean.typeMismatch")],
        },
        "repairs_used": 1,
        "max_repair_attempts": 1,
        "termination_reason": "repair_budget_exhausted",
        "termination_event": {
            "reason": "repair_budget_exhausted",
            "attempt": 2,
            "source": "repair_budget",
        },
        "attempts": [
            {
                "attempt": 1,
                "phase": "preflight",
                "generated": {"lean_code": ""},
                "verification": {
                    "success": False,
                    "diagnostics": [_error("pals.generation_empty")],
                },
                "diagnostics": [_error("pals.generation_empty")],
                "checkpoint_status": "published",
            },
            {
                "attempt": 2,
                "phase": "compile",
                "generated": {"lean_code": ""},
                "verification": {
                    "success": False,
                    "diagnostics": [_error("lean.error"), _error("lean.typeMismatch")],
                },
                "diagnostics": [_error("lean.error"), _error("lean.typeMismatch")],
                "checkpoint_status": "published",
                "repair_route": {"route": "prove"},
            },
        ],
    }


def _valid_explanation() -> dict[str, Any]:
    return {
        "overview": "検証済みの Lean コードに沿って証明を説明します。",
        "sections": [
            {
                "id": "imports",
                "title": "ライブラリを読み込む",
                "summary": "Mathlib を読み込み、必要な定理を利用可能にします。",
                "references": [
                    {"start_line": 1, "end_line": 1, "excerpt": "import Mathlib"}
                ],
            },
            {
                "id": "statement",
                "title": "定理を証明する",
                "summary": "Nat.add_zero を使って加法のゴールを閉じます。",
                "references": [
                    {
                        "start_line": 3,
                        "end_line": 4,
                        "excerpt": (
                            "theorem add_zero_nat (n : Nat) : n + 0 = n := by\n"
                            "  simpa using Nat.add_zero n"
                        ),
                    },
                ],
            }
        ],
        "conclusion": "したがって、自然数にゼロを足した結果が元の数であると示されます。",
    }


def _valid_clarifications() -> list[dict[str, Any]]:
    return [
        {
            "section_id": "statement",
            "question": "simpa は何をしているの？",
            "answer": (
                "既存定理 Nat.add_zero を現在のゴールと同じ形へ簡約し、"
                "余分な未解決ゴールを残さずに等式の証明を完了します。"
            ),
            "key_points": ["Nat.add_zero を使う", "ゴールと型を揃える"],
            "references": [
                {
                    "start_line": 4,
                    "end_line": 4,
                    "excerpt": "  simpa using Nat.add_zero n",
                }
            ],
        }
    ]


def _evaluate(
    artifact: dict[str, Any],
    *,
    run_id: str = "run-1",
    explanation: dict[str, Any] | None = None,
    clarifications: list[dict[str, Any]] | None = None,
    expect_clarification: bool | None = None,
) -> EvaluationRun:
    return evaluate_artifact(
        artifact,
        suite_revision="suite-2026-07-13",
        run_id=run_id,
        case_id="add-zero",
        model="prove-model",
        model_metadata={"provider": "openai", "temperature": 0.0},
        explanation=explanation,
        clarifications=clarifications,
        expect_clarification=(
            clarifications is not None
            if expect_clarification is None
            else expect_clarification
        ),
        created_at="2026-07-13T12:00:00+09:00",
    )


def test_successful_repaired_artifact_has_bounded_deterministic_stage_metrics() -> None:
    run = _evaluate(_successful_artifact(), explanation=_valid_explanation())

    assert run.suite_revision == "suite-2026-07-13"
    assert run.run_id == "run-1"
    assert run.case_id == "add-zero"
    assert run.created_at == "2026-07-13T12:00:00+09:00"
    assert run.model == "prove-model"
    assert run.model_metadata == (("provider", "openai"), ("temperature", 0.0))
    assert tuple(stage.stage for stage in run.stages) == EVALUATION_STAGES

    retrieval = run.stage("retrieval")
    assert retrieval.status == "passed"
    assert retrieval.metric("candidate_present").value is True
    assert retrieval.metric("exact_equivalence").value is True
    assert retrieval.metric("top_score_present").value is True
    assert retrieval.metric("top_score").value == 0.97

    assert run.stage("draft").status == "passed"
    assert run.stage("draft").metric("output_nonempty").value is True

    sketch = run.stage("sketch")
    assert sketch.status == "passed"
    assert sketch.metric("code_nonempty").value is True
    assert sketch.metric("has_gaps").value is True

    prove = run.stage("prove")
    assert prove.status == "failed"
    assert prove.metric("code_extracted").value is True
    assert prove.metric("compile_success").value is False

    repair = run.stage("repair")
    assert repair.status == "passed"
    assert repair.metric("attempts").value == 1
    assert repair.metric("repairs_used").value == 1
    assert repair.metric("attempt_count_consistent").value is True
    assert repair.metric("error_reduction").value == 2
    assert repair.metric("converged").value is True
    assert repair.metric("termination_reason").value == "verified"
    assert repair.metric("termination_reason_consistent").value is True

    end_to_end = run.stage("end_to_end")
    assert end_to_end.status == "passed"
    assert end_to_end.metric("verified").value is True

    explanation = run.stage("explanation")
    assert explanation.status == "passed"
    assert explanation.metric("references_valid").value is True
    assert explanation.metric("reference_coverage").value == 1.0
    assert all(
        metric.kind == "deterministic" and metric.source
        for stage in run.stages
        for metric in stage.metrics
    )

    with pytest.raises(FrozenInstanceError):
        run.run_id = "changed"  # type: ignore[misc]


def test_failed_artifact_records_failures_and_unavailable_values_without_fake_passes() -> None:
    run = _evaluate(_failed_artifact())

    assert run.stage("retrieval").status == "failed"
    assert run.stage("retrieval").metric("candidate_present").value is False
    assert run.stage("retrieval").metric("exact_equivalence").value is False
    assert run.stage("retrieval").metric("top_score_present").value is False
    top_score = run.stage("retrieval").metric("top_score")
    assert top_score.value is None
    assert top_score.status == "not_evaluated"

    assert run.stage("draft").status == "failed"
    assert run.stage("draft").metric("output_nonempty").value is False
    assert run.stage("sketch").status == "failed"
    assert run.stage("sketch").metric("code_nonempty").value is False
    assert run.stage("prove").status == "failed"
    assert run.stage("prove").metric("code_extracted").value is False
    assert run.stage("prove").metric("compile_success").value is False

    repair = run.stage("repair")
    assert repair.status == "failed"
    assert repair.metric("attempts").value == 1
    assert repair.metric("repairs_used").value == 1
    assert repair.metric("attempt_count_consistent").value is True
    assert repair.metric("error_reduction").value == -1
    assert repair.metric("converged").value is False
    assert repair.metric("termination_reason").value == "repair_budget_exhausted"
    assert repair.metric("termination_reason_consistent").value is True
    assert run.stage("end_to_end").status == "failed"
    assert run.stage("explanation").status == "not_evaluated"


def test_missing_stage_data_is_not_evaluated_instead_of_becoming_false_or_zero() -> None:
    run = _evaluate({})

    assert all(stage.status == "not_evaluated" for stage in run.stages)
    assert all(
        metric.value is None and metric.status == "not_evaluated"
        for stage in run.stages
        for metric in stage.metrics
    )
    assert run.stage("repair").metric("attempts").value is None
    assert run.stage("end_to_end").metric("verified").value is None


def test_repair_evaluation_rejects_inconsistent_attempt_count_and_termination() -> None:
    artifact = _successful_artifact()
    artifact["repairs_used"] = 12
    artifact["termination_reason"] = "repair_budget_exhausted"

    repair = _evaluate(artifact).stage("repair")

    assert repair.status == "failed"
    assert repair.metric("attempt_count_consistent").value is False
    assert repair.metric("termination_reason_consistent").value is False


def test_semantic_retrieval_can_pass_without_exact_equivalence() -> None:
    artifact = _successful_artifact()
    artifact["retrieval"]["exact_equivalence"] = False

    retrieval = _evaluate(artifact).stage("retrieval")

    assert retrieval.status == "passed"
    assert retrieval.metric("candidate_present").value is True
    assert retrieval.metric("exact_equivalence").value is False


def test_invalid_explanation_references_fail_exact_validation_and_only_cover_valid_lines() -> None:
    explanation = _valid_explanation()
    explanation["sections"][0]["references"][0]["excerpt"] = "not the imported module"
    explanation["sections"][1]["references"][0]["end_line"] = 99

    stage = _evaluate(_successful_artifact(), explanation=explanation).stage("explanation")

    assert stage.status == "failed"
    assert stage.metric("reference_count").value == 2
    assert stage.metric("valid_reference_count").value == 0
    assert stage.metric("references_valid").value is False
    assert stage.metric("reference_coverage").value == 0.0


def test_explanation_stage_measures_the_section_scoped_clarification_flow() -> None:
    stage = _evaluate(
        _successful_artifact(),
        explanation=_valid_explanation(),
        clarifications=_valid_clarifications(),
    ).stage("explanation")

    assert stage.status == "passed"
    assert stage.metric("clarification_count").value == 1
    assert stage.metric("clarifications_complete").value is True
    assert stage.metric("clarification_references_valid").value is True
    assert stage.metric("clarification_section_overlap").value is True


def test_clarification_outside_selected_section_fails_grounding() -> None:
    clarifications = _valid_clarifications()
    clarifications[0]["references"] = [
        {"start_line": 1, "end_line": 1, "excerpt": "import Mathlib"}
    ]

    stage = _evaluate(
        _successful_artifact(),
        explanation=_valid_explanation(),
        clarifications=clarifications,
    ).stage("explanation")

    assert stage.status == "failed"
    assert stage.metric("clarification_references_valid").value is True
    assert stage.metric("clarification_section_overlap").value is False


def test_reference_whitespace_is_part_of_exact_grounding() -> None:
    explanation = _valid_explanation()
    explanation["sections"][1]["references"][0]["excerpt"] = (
        "theorem add_zero_nat (n : Nat) : n + 0 = n := by\n"
        "simpa using Nat.add_zero n"
    )

    stage = _evaluate(_successful_artifact(), explanation=explanation).stage("explanation")

    assert stage.status == "failed"
    assert stage.metric("valid_reference_count").value == 1


def test_evaluation_json_and_jsonl_history_round_trip(tmp_path: Path) -> None:
    first = _evaluate(_successful_artifact(), explanation=_valid_explanation())
    second = _evaluate(_failed_artifact(), run_id="run-2")
    restored = EvaluationRun.from_json(first.to_json())

    assert restored == first
    assert json.loads(first.to_json())["schema_version"] == 2

    path = tmp_path / "nested" / "history.jsonl"
    store = JsonlEvaluationStore(path)
    store.append(first)
    store.append(second)

    assert path.parent.is_dir()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    assert store.load_history() == (first, second)
    assert store.load() == (first, second)

    summary = summarize_evaluation_runs(store.load_history())
    assert summary["run_count"] == 2
    assert summary["cases"] == ["add-zero"]
    assert summary["stages"]["end_to_end"] == {
        "evaluated": 2,
        "passed": 1,
        "failed": 1,
        "pass_rate": 0.5,
        "metric_averages": {},
    }


def test_run_comparison_reports_shared_case_deltas_without_hiding_case_drift() -> None:
    baseline = _evaluate(_failed_artifact(), run_id="baseline")
    candidate = _evaluate(
        _successful_artifact(),
        run_id="candidate",
        explanation=_valid_explanation(),
    )

    comparison = compare_evaluation_runs((baseline,), (candidate,))

    assert comparison["shared_cases"] == ["add-zero"]
    assert comparison["baseline_only_cases"] == []
    assert comparison["candidate_only_cases"] == []
    end_to_end = comparison["stages"]["end_to_end"]
    assert end_to_end["baseline_pass_rate"] == 0.0
    assert end_to_end["candidate_pass_rate"] == 1.0
    assert end_to_end["pass_rate_delta"] == 1.0
    repair_attempts = comparison["stages"]["repair"]["metric_averages"]["attempts"]
    assert repair_attempts == {"baseline": 1.0, "candidate": 1.0, "delta": 0.0}


def test_jsonl_history_reports_the_corrupt_line(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text('{"not": "an evaluation run"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"history\.jsonl:1"):
        JsonlEvaluationStore(path).load_history()


def test_evaluation_requires_timezone_aware_created_at() -> None:
    with pytest.raises(ValueError, match="timezone"):
        evaluate_artifact(
            _successful_artifact(),
            suite_revision="suite-1",
            run_id="run-1",
            case_id="case-1",
            model="model-1",
            created_at="2026-07-13T12:00:00",
        )
