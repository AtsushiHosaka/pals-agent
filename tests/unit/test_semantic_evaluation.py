import json
from typing import Any

import pytest

from pals_agent.evaluation import EvaluationRun, evaluate_artifact
from pals_agent.semantic_evaluation import (
    SemanticEvaluationError,
    SemanticStageJudge,
)


class FakeClient:
    def __init__(self, *responses: str | Exception) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate(self, *, model: str, prompt: str) -> str:
        assert model == "judge-model"
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("unexpected semantic judge call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _artifact() -> dict[str, Any]:
    return {
        "problem_id": "case-1",
        "retrieval": {
            "candidate_draft_id": "draft-1",
            "scores": {"final": 0.91},
            "raw_model_output": "RETRIEVAL_RAW_OUTPUT",
        },
        "model_attempt": {
            "lean_code": "theorem demo : True := by trivial",
            "raw_model_output": "PROVE_RAW_OUTPUT",
            "draft": {
                "text": "Use the trivial constructor.",
                "raw_model_output": "DRAFT_RAW_OUTPUT",
            },
            "sketch": {
                "lean_code": "theorem demo : True := by\n  trivial",
                "has_gaps": False,
                "raw_model_output": "SKETCH_RAW_OUTPUT",
            },
        },
        "model_attempt_verification": {"success": False, "diagnostics": []},
        "attempts": [
            {
                "attempt": 1,
                "generated": {"raw_model_output": "PROVE_RAW_OUTPUT"},
                "verification": {"success": False, "diagnostics": []},
            },
            {
                "attempt": 2,
                "generated": {"raw_model_output": "REPAIR_RAW_OUTPUT"},
                "verification": {"success": True, "diagnostics": []},
            },
        ],
        "repairs_used": 1,
        "max_repair_attempts": 12,
        "termination_reason": "verified",
        "generated": {"lean_code": "theorem demo : True := by trivial"},
        "verification": {"success": True, "diagnostics": []},
    }


def _explanation() -> dict[str, Any]:
    return {
        "overview": "The proof constructs True directly.",
        "sections": [
            {
                "id": "construct-true",
                "title": "Construct True",
                "summary": "The trivial tactic closes the goal.",
                "references": [
                    {
                        "start_line": 1,
                        "end_line": 1,
                        "excerpt": "theorem demo : True := by trivial",
                    }
                ],
            }
        ],
        "conclusion": "True is proved.",
        "raw_model_output": "EXPLANATION_RAW_OUTPUT",
    }


def _clarifications() -> list[dict[str, Any]]:
    return [
        {
            "section_id": "construct-true",
            "question": "Why does trivial work?",
            "answer": "True has an immediate constructor.",
            "key_points": ["The target is True."],
            "references": [
                {
                    "start_line": 1,
                    "end_line": 1,
                    "excerpt": "theorem demo : True := by trivial",
                }
            ],
            "raw_model_output": "CLARIFICATION_RAW_OUTPUT",
        }
    ]


def _run(
    artifact: dict[str, Any],
    *,
    explanation: dict[str, Any] | None = None,
    expect_clarification: bool = False,
) -> EvaluationRun:
    return evaluate_artifact(
        artifact,
        suite_revision="suite-1",
        run_id="run-1",
        case_id="case-1",
        model="proof-model",
        model_metadata={"provider": "proof-provider"},
        explanation=explanation,
        expect_clarification=expect_clarification,
        created_at="2026-07-13T12:00:00+09:00",
    )


def _scores(
    stages: tuple[str, ...],
    *,
    overrides: dict[str, float] | None = None,
) -> tuple[str, ...]:
    overrides = overrides or {}
    return tuple(
        json.dumps(
            {
                "rubric_revision": (
                    "lean-explanation-ja-v1"
                    if stage == "explanation"
                    else "pals-stage-quality-v1"
                ),
                "dimensions": (
                    {
                        "mathematical_fidelity": overrides.get(stage, 0.9),
                        "concise_explanatory_structure": overrides.get(stage, 0.9),
                        "pedagogical_clarity": overrides.get(stage, 0.9),
                    }
                    if stage == "explanation"
                    else {"quality": overrides.get(stage, 0.9)}
                ),
            }
        )
        for stage in stages
    )


def _judge(
    *responses: str | Exception,
    max_attempts: int = 2,
) -> tuple[SemanticStageJudge, FakeClient]:
    client = FakeClient(*responses)
    return (
        SemanticStageJudge(
            client=client,
            model="judge-model",
            provider="judge-provider",
            model_revision="judge-revision",
            max_attempts=max_attempts,
            pass_threshold=0.8,
        ),
        client,
    )


def test_pae_008_010_valid_scores_enrich_a_new_run_without_changing_stage_status() -> None:
    artifact = _artifact()
    explanation = _explanation()
    stages = ("retrieval", "draft", "sketch", "prove", "repair", "explanation")
    responses = _scores(
        stages,
        overrides={"draft": 0.8, "sketch": 0.79, "repair": 0.2},
    )
    judge, client = _judge(*responses)
    original = _run(artifact, explanation=explanation)
    original_json = original.to_json()
    original_statuses = tuple(stage.status for stage in original.stages)

    enriched = judge.evaluate(
        artifact_metadata=artifact,
        evaluation_run=original,
        explanation=explanation,
    )

    assert enriched is not original
    assert original.to_json() == original_json
    assert tuple(stage.status for stage in enriched.stages) == original_statuses
    assert len(client.prompts) == len(stages)
    for stage_name in stages:
        original_stage = original.stage(stage_name)  # type: ignore[arg-type]
        enriched_stage = enriched.stage(stage_name)  # type: ignore[arg-type]
        assert enriched_stage.metrics[: len(original_stage.metrics)] == original_stage.metrics
        quality = enriched_stage.metric("semantic_quality")
        quality_pass = enriched_stage.metric("semantic_quality_pass")
        assert quality.kind == "semantic"
        assert quality.status == "evaluated"
        expected_revision = (
            "lean-explanation-ja-v1"
            if stage_name == "explanation"
            else "pals-stage-quality-v1"
        )
        assert quality.source == (
            f"semantic_judge:judge-provider/judge-model@judge-revision:{expected_revision}"
        )
        assert quality.comment is None
        assert quality_pass.kind == "semantic"
        assert quality_pass.comment is None

    assert enriched.stage("draft").metric("semantic_quality_pass").value is True
    assert enriched.stage("sketch").metric("semantic_quality_pass").value is False
    assert enriched.stage("repair").metric("semantic_quality_pass").value is False
    assert enriched.stage("end_to_end") == original.stage("end_to_end")
    with pytest.raises(KeyError, match="semantic_quality"):
        original.stage("draft").metric("semantic_quality")


def test_pae_010_malformed_json_is_retried_once_then_validated() -> None:
    artifact = {"model_attempt": {"draft": {"text": "DRAFT_ONLY_RAW"}}}
    original = _run(artifact)
    judge, client = _judge("not-json", *_scores(("draft",)))

    enriched = judge.evaluate(artifact_metadata=artifact, evaluation_run=original)

    assert enriched.stage("draft").metric("semantic_quality").value == 0.9
    assert len(client.prompts) == 2
    assert "previous response failed schema validation" in client.prompts[1]
    assert "Return corrected strict JSON only" in client.prompts[1]


def test_pae_010_persistent_invalid_json_raises_with_all_raw_attempts() -> None:
    artifact = {"model_attempt": {"draft": {"text": "DRAFT_ONLY_RAW"}}}
    original = _run(artifact)
    original_json = original.to_json()
    judge, client = _judge("first invalid", "second invalid")

    with pytest.raises(SemanticEvaluationError) as error_info:
        judge.evaluate(artifact_metadata=artifact, evaluation_run=original)

    assert error_info.value.attempt_outputs == ("first invalid", "second invalid")
    assert original.to_json() == original_json
    assert len(client.prompts) == 2
    with pytest.raises(KeyError, match="semantic_quality"):
        original.stage("draft").metric("semantic_quality")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "rubric_revision": "pals-stage-quality-v1",
                "dimensions": {"quality": 1.01},
            },
            "between 0 and 1",
        ),
        (
            {
                "rubric_revision": "pals-stage-quality-v1",
                "dimensions": {"quality": 0.8, "extra": 0.7},
            },
            "configured rubric",
        ),
        (
            {
                "rubric_revision": "pals-stage-quality-v1",
                "dimensions": {},
            },
            "configured rubric",
        ),
        (
            {"rubric_revision": "wrong", "dimensions": {"quality": 0.8}},
            "revision",
        ),
    ],
)
def test_pae_010_rejects_invalid_score_sets(
    payload: dict[str, Any],
    message: str,
) -> None:
    artifact = {"model_attempt": {"draft": {"text": "DRAFT_ONLY_RAW"}}}
    raw = json.dumps(payload)
    judge, _client = _judge(raw, raw)

    with pytest.raises(SemanticEvaluationError, match=message) as error_info:
        judge.evaluate(artifact_metadata=artifact, evaluation_run=_run(artifact))

    assert error_info.value.attempt_outputs == (raw, raw)


def test_pae_008_unavailable_stages_are_neither_sent_nor_given_fake_metrics() -> None:
    artifact = {"model_attempt": {"draft": {"text": "DRAFT_ONLY_RAW"}}}
    original = _run(artifact)
    judge, client = _judge(*_scores(("draft",)))

    enriched = judge.evaluate(
        artifact_metadata=artifact,
        evaluation_run=original,
        expected_evidence={
            "draft": "EXPECTED_DRAFT_EVIDENCE",
            "retrieval": "UNAVAILABLE_RETRIEVAL_EVIDENCE",
        },
    )

    assert "DRAFT_ONLY_RAW" in client.prompts[0]
    assert "EXPECTED_DRAFT_EVIDENCE" in client.prompts[0]
    assert "UNAVAILABLE_RETRIEVAL_EVIDENCE" not in client.prompts[0]
    assert enriched.stage("draft").metric("semantic_quality").value == 0.9
    for stage_name in ("retrieval", "sketch", "prove", "repair", "explanation"):
        with pytest.raises(KeyError, match="semantic_quality"):
            enriched.stage(stage_name).metric("semantic_quality")

    empty_artifact: dict[str, Any] = {}
    empty_run = _run(empty_artifact)
    no_stage_result = judge.evaluate(
        artifact_metadata=empty_artifact,
        evaluation_run=empty_run,
    )
    assert no_stage_result is not empty_run
    assert no_stage_result == empty_run
    assert len(client.prompts) == 1
    assert all(
        metric.kind != "semantic" for stage in no_stage_result.stages for metric in stage.metrics
    )


def test_pae_013_prompt_keeps_raw_outputs_separate_from_evaluation_only_oracles() -> None:
    artifact = _artifact()
    explanation = _explanation()
    stages = ("retrieval", "draft", "sketch", "prove", "repair", "explanation")
    judge, client = _judge(*_scores(stages))

    judge.evaluate(
        artifact_metadata=artifact,
        evaluation_run=_run(artifact, explanation=explanation),
        explanation=explanation,
        expected_evidence={
            "retrieval": "EXPECTED_RETRIEVAL_EVIDENCE",
            "prove": "EXPECTED_PROVE_EVIDENCE",
            "end_to_end": "UNJUDGED_EXPECTED_EVIDENCE",
        },
        rubric={
            "clarity": "GLOBAL_RUBRIC",
            "explanation": "EXPLANATION_ONLY_RUBRIC",
        },
    )

    prompt = "\n".join(client.prompts)
    for marker in (
        "RETRIEVAL_RAW_OUTPUT",
        "DRAFT_RAW_OUTPUT",
        "SKETCH_RAW_OUTPUT",
        "PROVE_RAW_OUTPUT",
        "REPAIR_RAW_OUTPUT",
        "EXPLANATION_RAW_OUTPUT",
    ):
        assert marker in prompt
    assert '"termination_reason":"verified"' in prompt
    assert '"repairs_used":1' in prompt
    assert "EXPECTED_RETRIEVAL_EVIDENCE" in prompt
    assert "EXPECTED_PROVE_EVIDENCE" in prompt
    assert "UNJUDGED_EXPECTED_EVIDENCE" not in prompt
    assert "GLOBAL_RUBRIC" in prompt
    assert "EXPLANATION_ONLY_RUBRIC" in prompt
    assert "evaluation-only" in prompt.lower()
    assert "generation input" in prompt.lower()
    assert "benchmark routing" in prompt.lower()
    assert "hidden chain-of-thought" in prompt.lower()


def test_pae_004_010_clarifications_are_judged_with_explanation_evidence() -> None:
    artifact = _artifact()
    explanation = _explanation()
    clarifications = _clarifications()
    clarifications_before = json.dumps(clarifications, sort_keys=True)
    stages = ("retrieval", "draft", "sketch", "prove", "repair", "explanation")
    responses = list(_scores(stages))
    responses[-1] = json.dumps(
        {
            "rubric_revision": "lean-explanation-ja-v1",
            "dimensions": {
                "mathematical_fidelity": 0.9,
                "concise_explanatory_structure": 0.9,
                "pedagogical_clarity": 0.9,
                "clarification_directness": 0.9,
            },
        }
    )
    judge, client = _judge(*responses)

    enriched = judge.evaluate(
        artifact_metadata=artifact,
        evaluation_run=_run(
            artifact,
            explanation=explanation,
            expect_clarification=True,
        ),
        explanation=explanation,
        clarifications=clarifications,
        expect_clarification=True,
    )

    prompt = client.prompts[-1]
    assert '"explanation":{' in prompt
    assert '"clarifications":[{' in prompt
    assert "EXPLANATION_RAW_OUTPUT" in prompt
    assert "CLARIFICATION_RAW_OUTPUT" in prompt
    assert json.dumps(clarifications, sort_keys=True) == clarifications_before
    assert enriched.stage("explanation").metric("semantic_quality").value == 0.9
    with pytest.raises(KeyError, match="semantic_quality"):
        enriched.stage("end_to_end").metric("semantic_quality")


def test_pae_008_010_safe_transport_failure_marks_all_available_stages_unavailable() -> None:
    artifact = _artifact()
    explanation = _explanation()
    clarifications = _clarifications()
    stages = ("retrieval", "draft", "sketch", "prove", "repair", "explanation")
    secret = "SECRET_TRANSPORT_TOKEN"
    original = _run(artifact, explanation=explanation)
    original_json = original.to_json()
    strict_judge, _strict_client = _judge(RuntimeError(secret))

    with pytest.raises(SemanticEvaluationError, match="transport"):
        strict_judge.evaluate(
            artifact_metadata=artifact,
            evaluation_run=original,
            explanation=explanation,
            clarifications=clarifications,
        )

    safe_judge, safe_client = _judge(RuntimeError(secret))
    result = safe_judge.evaluate_or_mark_unavailable(
        artifact_metadata=artifact,
        evaluation_run=original,
        explanation=explanation,
        clarifications=clarifications,
    )

    assert result is not original
    assert original.to_json() == original_json
    assert tuple(stage.status for stage in result.stages) == tuple(
        stage.status for stage in original.stages
    )
    assert len(safe_client.prompts) == 1
    for stage_name in stages:
        original_stage = original.stage(stage_name)  # type: ignore[arg-type]
        result_stage = result.stage(stage_name)  # type: ignore[arg-type]
        assert result_stage.metrics[: len(original_stage.metrics)] == original_stage.metrics
        for metric_name in ("semantic_quality", "semantic_quality_pass"):
            metric = result_stage.metric(metric_name)
            assert metric.kind == "semantic"
            assert metric.status == "not_evaluated"
            assert metric.value is None
            assert metric.comment is None

    assert result.stage("end_to_end") == original.stage("end_to_end")


def test_pae_008_010_safe_parse_failure_does_not_leak_raw_attempts() -> None:
    artifact = {"model_attempt": {"draft": {"text": "DRAFT_ONLY_RAW"}}}
    raw_attempts = ("SECRET_RAW_ATTEMPT_ONE", "SECRET_RAW_ATTEMPT_TWO")
    original = _run(artifact)
    original_json = original.to_json()
    judge, client = _judge(*raw_attempts)

    result = judge.evaluate_or_mark_unavailable(
        artifact_metadata=artifact,
        evaluation_run=original,
    )

    assert result is not original
    assert original.to_json() == original_json
    assert len(client.prompts) == 2
    assert (
        result.stage("draft").metrics[: len(original.stage("draft").metrics)]
        == original.stage("draft").metrics
    )
    for metric_name in ("semantic_quality", "semantic_quality_pass"):
        metric = result.stage("draft").metric(metric_name)
        assert metric.kind == "semantic"
        assert metric.status == "not_evaluated"
        assert metric.value is None
        assert metric.comment is None

    for stage_name in ("retrieval", "sketch", "prove", "repair", "explanation"):
        with pytest.raises(KeyError, match="semantic_quality"):
            result.stage(stage_name).metric("semantic_quality")
