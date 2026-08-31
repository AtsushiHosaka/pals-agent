import json
import math
from typing import Any

import pytest

from pals_agent.evaluation import EvaluationRun, evaluate_artifact
from pals_agent.semantic_evaluation import SemanticEvaluationError, SemanticStageJudge

LEAN_CODE = "example : True := by\n  trivial"


class FakeClient:
    def __init__(
        self,
        *responses: str | Exception,
        expected_model: str = "judge-model",
    ) -> None:
        self.responses = list(responses)
        self.expected_model = expected_model
        self.prompts: list[str] = []

    def generate(self, *, model: str, prompt: str) -> str:
        assert model == self.expected_model
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _explanation() -> dict[str, Any]:
    return {
        "overview": "検証済みの証明を説明します。",
        "sections": [
            {
                "id": "finish",
                "title": "証明を閉じる",
                "summary": "trivial で True を証明します。",
                "references": [
                    {"start_line": 2, "end_line": 2, "excerpt": "  trivial"}
                ],
            }
        ],
        "conclusion": "したがって True が証明されました。",
    }


def _run(
    artifact: dict[str, Any],
    *,
    explanation: dict[str, Any] | None = None,
    expect_clarification: bool = False,
) -> EvaluationRun:
    return evaluate_artifact(
        artifact,
        suite_revision="suite-v2",
        run_id="run-1",
        case_id="case-1",
        model="proof-model",
        explanation=explanation,
        expect_clarification=expect_clarification,
        created_at="2026-07-14T00:00:00+09:00",
    )


def _judge(*responses: str | Exception) -> tuple[SemanticStageJudge, FakeClient]:
    client = FakeClient(*responses)
    return (
        SemanticStageJudge(
            client=client,
            model="judge-model",
            provider="judge-provider",
            model_revision="judge-revision",
            max_attempts=1,
        ),
        client,
    )


def _response(revision: str, dimensions: dict[str, float]) -> str:
    return json.dumps({"rubric_revision": revision, "dimensions": dimensions})


def test_pae_010_general_semantic_rubric_is_numeric_bounded_and_comment_free() -> None:
    artifact = {"model_attempt": {"draft": {"text": "draft evidence"}}}
    judge, client = _judge(_response("pals-stage-quality-v1", {"quality": 0.8}))
    original = _run(artifact)

    enriched = judge.evaluate(artifact_metadata=artifact, evaluation_run=original)

    quality = enriched.stage("draft").metric("semantic_quality")
    quality_pass = enriched.stage("draft").metric("semantic_quality_pass")
    assert quality.value == 0.8
    assert quality_pass.value is True
    assert quality.comment is None
    assert quality_pass.comment is None
    assert quality.source == (
        "semantic_judge:judge-provider/judge-model@judge-revision:"
        "pals-stage-quality-v1"
    )
    prompt = client.prompts[0].lower()
    assert "comment" not in prompt
    assert "rationale" not in prompt
    assert "rubric_revision" in prompt
    assert "dimensions" in prompt


@pytest.mark.parametrize(
    ("dimensions", "expected_pass"),
    [
        (
            {
                "mathematical_fidelity": 0.9,
                "concise_explanatory_structure": 0.8,
                "pedagogical_clarity": 0.7,
            },
            False,
        ),
        (
            {
                "mathematical_fidelity": 1.0,
                "concise_explanatory_structure": 0.95,
                "pedagogical_clarity": 0.69,
            },
            False,
        ),
        (
            {
                "mathematical_fidelity": 0.79,
                "concise_explanatory_structure": 0.79,
                "pedagogical_clarity": 0.79,
            },
            False,
        ),
    ],
)
def test_pae_002_010_explanation_rubric_uses_dimension_floor_and_mean_threshold(
    dimensions: dict[str, float],
    expected_pass: bool,
) -> None:
    artifact = {
        "generated": {"lean_code": LEAN_CODE},
        "verification": {"success": True},
    }
    explanation = _explanation()
    judge, _client = _judge(_response("lean-explanation-ja-v1", dimensions))

    enriched = judge.evaluate(
        artifact_metadata=artifact,
        evaluation_run=_run(artifact, explanation=explanation),
        explanation=explanation,
        expect_clarification=False,
    )

    assert enriched.stage("explanation").metric("semantic_quality").value == pytest.approx(
        sum(dimensions.values()) / 3
    )
    assert (
        enriched.stage("explanation").metric("semantic_quality_pass").value
        is expected_pass
    )


@pytest.mark.parametrize(
    ("score", "expected_pass"),
    [
        (math.nextafter(0.80, 0.0), False),
        (0.80, True),
    ],
)
def test_pae_024_explanation_mean_threshold_has_no_tolerance(
    score: float,
    expected_pass: bool,
) -> None:
    artifact = {
        "generated": {"lean_code": LEAN_CODE},
        "verification": {"success": True},
    }
    dimensions = {
        "mathematical_fidelity": score,
        "concise_explanatory_structure": score,
        "pedagogical_clarity": score,
    }
    judge, _client = _judge(_response("lean-explanation-ja-v1", dimensions))

    enriched = judge.evaluate(
        artifact_metadata=artifact,
        evaluation_run=_run(artifact, explanation=_explanation()),
        explanation=_explanation(),
        expect_clarification=False,
    )

    assert (
        enriched.stage("explanation").metric("semantic_quality_pass").value
        is expected_pass
    )


def test_pae_004_010_expected_clarification_adds_only_fixed_directness_dimension() -> None:
    artifact = {
        "generated": {"lean_code": LEAN_CODE},
        "verification": {"success": True},
    }
    explanation = _explanation()
    dimensions = {
        "mathematical_fidelity": 0.9,
        "concise_explanatory_structure": 0.9,
        "pedagogical_clarity": 0.9,
        "clarification_directness": 0.9,
    }
    judge, client = _judge(_response("lean-explanation-ja-v1", dimensions))

    enriched = judge.evaluate(
        artifact_metadata=artifact,
        evaluation_run=_run(
            artifact,
            explanation=explanation,
            expect_clarification=True,
        ),
        explanation=explanation,
        clarifications=[{"answer": "評価対象の詳細回答"}],
        expect_clarification=True,
    )

    assert enriched.stage("explanation").metric("semantic_quality").value == 0.9
    assert "clarification_directness" in client.prompts[0]
    assert "expect_clarification" not in client.prompts[0]


@pytest.mark.parametrize(
    "payload",
    [
        {"rubric_revision": "wrong", "dimensions": {"quality": 0.8}},
        {
            "rubric_revision": "pals-stage-quality-v1",
            "dimensions": {"quality": 0.8},
            "comment": "forbidden",
        },
        {
            "rubric_revision": "pals-stage-quality-v1",
            "dimensions": {"quality": 0.8, "extra": 0.5},
        },
        {"rubric_revision": "pals-stage-quality-v1", "dimensions": {}},
        {"rubric_revision": "pals-stage-quality-v1", "dimensions": {"quality": 1.1}},
        {"rubric_revision": "pals-stage-quality-v1", "dimensions": {"quality": True}},
    ],
)
def test_pae_010_semantic_output_schema_is_exact(payload: dict[str, Any]) -> None:
    artifact = {"model_attempt": {"draft": {"text": "draft evidence"}}}
    raw = json.dumps(payload)
    judge, _client = _judge(raw)

    with pytest.raises(SemanticEvaluationError):
        judge.evaluate(artifact_metadata=artifact, evaluation_run=_run(artifact))


def test_pae_008_010_unavailable_semantic_metrics_remain_comment_free() -> None:
    artifact = {"model_attempt": {"draft": {"text": "draft evidence"}}}
    secret = "PRIVATE_JUDGE_FAILURE"
    judge, _client = _judge(RuntimeError(secret))
    original = _run(artifact)

    enriched = judge.evaluate_or_mark_unavailable(
        artifact_metadata=artifact,
        evaluation_run=original,
    )

    assert enriched.stage("draft").status == original.stage("draft").status
    for name in ("semantic_quality", "semantic_quality_pass"):
        metric = enriched.stage("draft").metric(name)
        assert metric.status == "not_evaluated"
        assert metric.value is None
        assert metric.comment is None
    assert secret not in enriched.to_json()


def test_pae_019_unconfigured_evaluator_is_zero_call_and_explicitly_unevaluated() -> None:
    artifact = {"model_attempt": {"draft": {"text": "draft evidence"}}}
    original = _run(artifact)
    judge = SemanticStageJudge.unconfigured()

    enriched = judge.evaluate_or_mark_unavailable(
        artifact_metadata=artifact,
        evaluation_run=original,
    )

    assert judge.configured is False
    for name in ("semantic_quality", "semantic_quality_pass"):
        metric = enriched.stage("draft").metric(name)
        assert metric.status == "not_evaluated"
        assert metric.value is None
        assert metric.comment is None
        assert metric.source == (
            "semantic_judge:unconfigured:pals-stage-quality-v1"
        )


def test_pae_019_metric_source_encodes_pinned_evaluator_identity() -> None:
    artifact = {"model_attempt": {"draft": {"text": "draft evidence"}}}
    client = FakeClient(
        _response("pals-stage-quality-v1", {"quality": 0.9}),
        expected_model="judge/model@blue",
    )
    judge = SemanticStageJudge(
        client=client,
        provider="openai",
        model="judge/model@blue",
        model_revision="release/2026+07",
        max_attempts=1,
    )

    enriched = judge.evaluate(
        artifact_metadata=artifact,
        evaluation_run=_run(artifact),
    )

    assert enriched.stage("draft").metric("semantic_quality").source == (
        "semantic_judge:openai/judge%2Fmodel%40blue@release%2F2026%2B07:"
        "pals-stage-quality-v1"
    )
