from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final, Literal, Protocol, cast
from urllib.parse import quote

from pals_agent.evaluation import (
    EVALUATION_STAGES,
    EvaluationMetric,
    EvaluationRun,
    EvaluationStage,
    EvaluationStageResult,
)

SemanticStage = Literal[
    "retrieval",
    "draft",
    "sketch",
    "prove",
    "repair",
    "explanation",
]
SemanticEvaluationFailure = Literal["configuration", "parse", "transport"]
ClarificationEvidence = Mapping[str, Any] | Sequence[Mapping[str, Any]]

SEMANTIC_STAGES: Final[tuple[SemanticStage, ...]] = (
    "retrieval",
    "draft",
    "sketch",
    "prove",
    "repair",
    "explanation",
)
GENERAL_RUBRIC_REVISION: Final = "pals-stage-quality-v1"
EXPLANATION_RUBRIC_REVISION: Final = "lean-explanation-ja-v1"
_GENERAL_DIMENSIONS: Final = ("quality",)
_EXPLANATION_DIMENSIONS: Final = (
    "mathematical_fidelity",
    "concise_explanatory_structure",
    "pedagogical_clarity",
)
_CLARIFICATION_DIMENSION: Final = "clarification_directness"
_EXPLANATION_DIMENSION_FLOOR: Final = 0.70
_EXPLANATION_MEAN_FLOOR: Final = 0.80
_SEMANTIC_STAGE_NAMES: Final = frozenset(SEMANTIC_STAGES)
_EVALUATION_STAGE_NAMES: Final = frozenset(EVALUATION_STAGES)
_SEMANTIC_METRIC_NAMES: Final = frozenset(
    {"semantic_quality", "semantic_quality_pass"}
)
_MISSING: Final = object()


class TextGenerationClient(Protocol):
    def generate(self, *, model: str, prompt: str) -> str: ...


class SemanticEvaluationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        attempt_outputs: tuple[str, ...] = (),
        kind: SemanticEvaluationFailure = "configuration",
    ) -> None:
        super().__init__(message)
        self.attempt_outputs = attempt_outputs
        self.raw_attempts = attempt_outputs
        self.kind = kind


@dataclass(frozen=True, slots=True)
class _StageEvidence:
    stage: SemanticStage
    artifact_output: Any


@dataclass(frozen=True, slots=True)
class _Rubric:
    revision: str
    dimensions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _StageScore:
    stage: SemanticStage
    score: float
    passed: bool
    rubric_revision: str


@dataclass(frozen=True, slots=True)
class SemanticStageJudge:
    client: TextGenerationClient | None
    model: str | None
    provider: str | None
    model_revision: str | None = None
    max_attempts: int = 2
    pass_threshold: float = 0.8

    def __post_init__(self) -> None:
        identity = (self.client, self.model, self.provider, self.model_revision)
        if any(value is None for value in identity) and not all(
            value is None for value in identity
        ):
            raise ValueError("semantic judge configuration must be all-or-none")
        if self.model is not None and not self.model.strip():
            raise ValueError("semantic judge model must be non-empty")
        if self.provider is not None and not self.provider.strip():
            raise ValueError("semantic judge provider must be non-empty")
        if self.model_revision is not None and not self.model_revision.strip():
            raise ValueError("semantic judge model revision must be non-empty")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if not _is_bounded_score(self.pass_threshold):
            raise ValueError("pass_threshold must be a finite number between 0 and 1")
        object.__setattr__(self, "pass_threshold", float(self.pass_threshold))

    @classmethod
    def unconfigured(cls) -> SemanticStageJudge:
        return cls(client=None, model=None, provider=None, model_revision=None)

    @property
    def configured(self) -> bool:
        return all(
            value is not None
            for value in (
                self.client,
                self.model,
                self.provider,
                self.model_revision,
            )
        )

    def evaluate(
        self,
        *,
        artifact_metadata: Mapping[str, Any],
        evaluation_run: EvaluationRun,
        explanation: Mapping[str, Any] | None = None,
        clarifications: ClarificationEvidence | None = None,
        expect_clarification: bool | None = None,
        expected_evidence: Mapping[str, Any] | None = None,
        rubric: Mapping[str, Any] | None = None,
    ) -> EvaluationRun:
        if not self.configured:
            raise SemanticEvaluationError("semantic evaluator is not configured")
        if expect_clarification is not None and type(expect_clarification) is not bool:
            raise SemanticEvaluationError(
                "clarification expectation must be an explicit boolean"
            )
        evidence = _available_stage_evidence(
            artifact_metadata,
            explanation,
            clarifications,
        )
        if not evidence:
            return replace(evaluation_run)

        required_stages = tuple(item.stage for item in evidence)
        _reject_existing_semantic_metrics(evaluation_run, required_stages)
        expected = _evaluation_only_mapping(expected_evidence, required_stages)
        evaluation_rubric = _evaluation_only_mapping(rubric, required_stages)

        scores: list[_StageScore] = []
        for item in evidence:
            stage_rubric = _rubric_for_stage(
                item.stage,
                expect_clarification=expect_clarification is True,
            )
            prompt = _semantic_evaluation_prompt(
                evidence=item,
                evaluation_run=evaluation_run,
                expected_evidence=expected,
                evaluation_rubric=evaluation_rubric,
                output_rubric=stage_rubric,
            )
            dimensions = self._generate_validated(prompt=prompt, rubric=stage_rubric)
            score = sum(dimensions.values()) / len(dimensions)
            passed = (
                _explanation_score_passes(dimensions)
                if item.stage == "explanation"
                else score >= self.pass_threshold
            )
            scores.append(
                _StageScore(
                    stage=item.stage,
                    score=score,
                    passed=passed,
                    rubric_revision=stage_rubric.revision,
                )
            )

        return _merge_semantic_scores(
            evaluation_run,
            scores=tuple(scores),
            provider=cast(str, self.provider).strip(),
            model=cast(str, self.model).strip(),
            model_revision=cast(str, self.model_revision).strip(),
        )

    def evaluate_or_mark_unavailable(
        self,
        *,
        artifact_metadata: Mapping[str, Any],
        evaluation_run: EvaluationRun,
        explanation: Mapping[str, Any] | None = None,
        clarifications: ClarificationEvidence | None = None,
        expect_clarification: bool | None = None,
        expected_evidence: Mapping[str, Any] | None = None,
        rubric: Mapping[str, Any] | None = None,
    ) -> EvaluationRun:
        try:
            evidence = _available_stage_evidence(
                artifact_metadata,
                explanation,
                clarifications,
            )
            if not evidence:
                return replace(evaluation_run)
            return self.evaluate(
                artifact_metadata=artifact_metadata,
                evaluation_run=evaluation_run,
                explanation=explanation,
                clarifications=clarifications,
                expect_clarification=expect_clarification,
                expected_evidence=expected_evidence,
                rubric=rubric,
            )
        except SemanticEvaluationError:
            stages = tuple(item.stage for item in evidence) if "evidence" in locals() else ()
            if not stages:
                return replace(evaluation_run)
            return _merge_unavailable_semantic_metrics(
                evaluation_run,
                stages=stages,
                provider=self.provider.strip() if self.provider is not None else None,
                model=self.model.strip() if self.model is not None else None,
                model_revision=(
                    self.model_revision.strip()
                    if self.model_revision is not None
                    else None
                ),
                expect_clarification=expect_clarification is True,
            )

    def _generate_validated(
        self,
        *,
        prompt: str,
        rubric: _Rubric,
    ) -> dict[str, float]:
        outputs: list[str] = []
        validation_error = ""
        current_prompt = prompt
        client = self.client
        model = self.model
        if client is None or model is None:
            raise SemanticEvaluationError("semantic evaluator is not configured")
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = client.generate(model=model, prompt=current_prompt)
            except Exception as exc:
                raise SemanticEvaluationError(
                    f"Semantic judge transport failed on attempt {attempt}",
                    attempt_outputs=tuple(outputs),
                    kind="transport",
                ) from exc

            raw_output = response if isinstance(response, str) else repr(response)
            outputs.append(raw_output)
            try:
                if not isinstance(response, str):
                    raise TypeError("semantic judge response must be text")
                return _parse_dimensions(response, rubric)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                validation_error = str(exc)
                if attempt < self.max_attempts:
                    current_prompt = (
                        f"{prompt}\n\nThe previous response failed schema validation: "
                        f"{validation_error}\nReturn corrected strict JSON only."
                    )

        raise SemanticEvaluationError(
            "Semantic judge returned invalid JSON after "
            f"{self.max_attempts} attempts: {validation_error}",
            attempt_outputs=tuple(outputs),
            kind="parse",
        )


def _available_stage_evidence(
    artifact: Mapping[str, Any],
    explanation: Mapping[str, Any] | None,
    clarifications: ClarificationEvidence | None,
) -> tuple[_StageEvidence, ...]:
    available: dict[SemanticStage, Any] = {}
    clarification_evidence = _normalize_clarifications(clarifications)

    retrieval = artifact.get("retrieval", _MISSING)
    if retrieval is not _MISSING and retrieval is not None:
        available["retrieval"] = retrieval

    model_attempt = _as_mapping(artifact.get("model_attempt"))
    if model_attempt is not None:
        draft = model_attempt.get("draft", _MISSING)
        if draft is not _MISSING and draft is not None:
            available["draft"] = draft

        sketch = model_attempt.get("sketch", _MISSING)
        if sketch is not _MISSING and sketch is not None:
            available["sketch"] = sketch

        if "lean_code" in model_attempt:
            available["prove"] = {
                "output": {
                    key: value
                    for key, value in model_attempt.items()
                    if key not in {"draft", "sketch"}
                },
                "verification": artifact.get("model_attempt_verification"),
            }

    attempts = artifact.get("attempts")
    if isinstance(attempts, list) and len(attempts) > 1:
        available["repair"] = {
            "attempts": attempts,
            "repairs_used": artifact.get("repairs_used"),
            "max_repair_attempts": artifact.get("max_repair_attempts"),
            "termination_reason": artifact.get("termination_reason"),
            "termination_event": artifact.get("termination_event"),
        }

    verification = _as_mapping(artifact.get("verification"))
    verified = verification is not None and verification.get("success") is True
    if verified and (explanation is not None or clarification_evidence):
        available["explanation"] = {
            "explanation": explanation,
            "clarifications": [dict(item) for item in clarification_evidence],
        }

    return tuple(
        _StageEvidence(stage=stage, artifact_output=available[stage])
        for stage in SEMANTIC_STAGES
        if stage in available
    )


def _normalize_clarifications(
    clarifications: ClarificationEvidence | None,
) -> tuple[Mapping[str, Any], ...]:
    if clarifications is None:
        return ()
    if isinstance(clarifications, Mapping):
        return (clarifications,)
    normalized = tuple(clarifications)
    if any(not isinstance(item, Mapping) for item in normalized):
        raise SemanticEvaluationError("every clarification must be a mapping")
    return normalized


def _rubric_for_stage(
    stage: SemanticStage,
    *,
    expect_clarification: bool,
) -> _Rubric:
    if stage != "explanation":
        return _Rubric(GENERAL_RUBRIC_REVISION, _GENERAL_DIMENSIONS)
    dimensions: tuple[str, ...] = _EXPLANATION_DIMENSIONS
    if expect_clarification:
        dimensions = (*dimensions, _CLARIFICATION_DIMENSION)
    return _Rubric(EXPLANATION_RUBRIC_REVISION, dimensions)


def _semantic_evaluation_prompt(
    *,
    evidence: _StageEvidence,
    evaluation_run: EvaluationRun,
    expected_evidence: Mapping[str, Any] | None,
    evaluation_rubric: Mapping[str, Any] | None,
    output_rubric: _Rubric,
) -> str:
    run_payload = evaluation_run.to_dict()
    del run_payload["stages"]
    inputs = {
        "evaluation_run": run_payload,
        "stage": evidence.stage,
        "artifact_output": evidence.artifact_output,
        "deterministic_evaluation": _deterministic_prompt_payload(
            evaluation_run.stage(cast(EvaluationStage, evidence.stage))
        ),
    }
    output_shape = {
        "rubric_revision": output_rubric.revision,
        "dimensions": {name: 0.0 for name in output_rubric.dimensions},
    }
    return "\n".join(
        (
            "Act as a strict numeric quality judge for one recorded DSP stage.",
            "Use only visible evidence and do not reveal hidden chain-of-thought.",
            "The expected evidence and evaluation criteria are evaluation-only data.",
            "They are never generation input and never alter benchmark routing.",
            "Score every listed dimension from 0 through 1.",
            "Return exactly the JSON shape shown and no surrounding text.",
            "",
            "ARTIFACT AND DETERMINISTIC EVALUATION:",
            _prompt_json(inputs, "semantic evaluation inputs"),
            "",
            "EVALUATION-ONLY EXPECTED EVIDENCE:",
            _prompt_json(expected_evidence, "evaluation-only expected evidence"),
            "",
            "EVALUATION-ONLY CRITERIA:",
            _prompt_json(evaluation_rubric, "evaluation-only rubric"),
            "",
            "EXACT RESPONSE SHAPE:",
            _prompt_json(output_shape, "semantic response shape"),
        )
    )


def _prompt_json(value: Any, label: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise SemanticEvaluationError(f"{label} must be JSON serializable") from exc


def _evaluation_only_mapping(
    value: Mapping[str, Any] | None,
    required_stages: tuple[SemanticStage, ...],
) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise SemanticEvaluationError("evaluation-only context must be a mapping")
    required = frozenset(required_stages)
    return {
        key: item
        for key, item in value.items()
        if key not in _EVALUATION_STAGE_NAMES or key in required
    }


def _parse_dimensions(raw_output: str, rubric: _Rubric) -> dict[str, float]:
    payload = json.loads(raw_output)
    if not isinstance(payload, dict):
        raise TypeError("semantic judge JSON must be an object")
    if set(payload) != {"rubric_revision", "dimensions"}:
        raise ValueError(
            "semantic judge JSON must contain only rubric_revision and dimensions"
        )
    if payload["rubric_revision"] != rubric.revision:
        raise ValueError("semantic judge rubric revision does not match configuration")
    dimensions = payload["dimensions"]
    if not isinstance(dimensions, dict):
        raise TypeError("semantic judge dimensions must be an object")
    if set(dimensions) != set(rubric.dimensions):
        raise ValueError("semantic judge dimensions do not match the configured rubric")
    parsed: dict[str, float] = {}
    for name in rubric.dimensions:
        value = dimensions[name]
        if not _is_bounded_score(value):
            raise ValueError(f"semantic dimension {name} must be between 0 and 1")
        parsed[name] = float(value)
    return parsed


def _is_bounded_score(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and 0.0 <= float(value) <= 1.0
    )


def _deterministic_prompt_payload(result: EvaluationStageResult) -> dict[str, Any]:
    return {
        "stage": result.stage,
        "status": result.status,
        "metrics": [
            {
                "name": metric.name,
                "value": metric.value,
                "status": metric.status,
                "source": metric.source,
                "kind": metric.kind,
            }
            for metric in result.metrics
        ],
    }


def _explanation_score_passes(dimensions: Mapping[str, float]) -> bool:
    mean = sum(dimensions.values()) / len(dimensions)
    return (
        all(value >= _EXPLANATION_DIMENSION_FLOOR for value in dimensions.values())
        and mean >= _EXPLANATION_MEAN_FLOOR
    )


def _reject_existing_semantic_metrics(
    evaluation_run: EvaluationRun,
    stages: tuple[SemanticStage, ...],
) -> None:
    for stage in stages:
        result = evaluation_run.stage(cast(EvaluationStage, stage))
        conflicts = _SEMANTIC_METRIC_NAMES.intersection(
            metric.name for metric in result.metrics
        )
        if conflicts:
            raise SemanticEvaluationError(
                f"{stage} already contains semantic quality metrics"
            )


def _metric_source(
    provider: str | None,
    model: str | None,
    model_revision: str | None,
    rubric_revision: str,
) -> str:
    if provider is None and model is None and model_revision is None:
        return f"semantic_judge:unconfigured:{rubric_revision}"
    if provider is None or model is None or model_revision is None:
        raise ValueError("semantic evaluator identity must be all-or-none")
    encoded_model = quote(
        model,
        safe="-._~",
        encoding="ascii",
        errors="strict",
    )
    encoded_revision = quote(
        model_revision,
        safe="-._~",
        encoding="ascii",
        errors="strict",
    )
    return (
        f"semantic_judge:{provider}/{encoded_model}@{encoded_revision}:"
        f"{rubric_revision}"
    )


def _merge_semantic_scores(
    evaluation_run: EvaluationRun,
    *,
    scores: tuple[_StageScore, ...],
    provider: str,
    model: str,
    model_revision: str,
) -> EvaluationRun:
    scores_by_stage = {score.stage: score for score in scores}
    stages: list[EvaluationStageResult] = []
    for result in evaluation_run.stages:
        if result.stage not in _SEMANTIC_STAGE_NAMES:
            stages.append(result)
            continue
        score = scores_by_stage.get(result.stage)
        if score is None:
            stages.append(result)
            continue
        source = _metric_source(
            provider,
            model,
            model_revision,
            score.rubric_revision,
        )
        stages.append(
            replace(
                result,
                metrics=(
                    *result.metrics,
                    EvaluationMetric(
                        name="semantic_quality",
                        value=score.score,
                        status="evaluated",
                        source=source,
                        kind="semantic",
                    ),
                    EvaluationMetric(
                        name="semantic_quality_pass",
                        value=score.passed,
                        status="evaluated",
                        source=source,
                        kind="semantic",
                    ),
                ),
            )
        )
    return replace(evaluation_run, stages=tuple(stages))


def _merge_unavailable_semantic_metrics(
    evaluation_run: EvaluationRun,
    *,
    stages: tuple[SemanticStage, ...],
    provider: str | None,
    model: str | None,
    model_revision: str | None,
    expect_clarification: bool,
) -> EvaluationRun:
    available = frozenset(stages)
    merged_stages: list[EvaluationStageResult] = []
    for result in evaluation_run.stages:
        if result.stage not in available:
            merged_stages.append(result)
            continue
        rubric = _rubric_for_stage(
            result.stage,
            expect_clarification=expect_clarification,
        )
        source = _metric_source(
            provider,
            model,
            model_revision,
            rubric.revision,
        )
        merged_stages.append(
            replace(
                result,
                metrics=(
                    *result.metrics,
                    EvaluationMetric(
                        name="semantic_quality",
                        value=None,
                        status="not_evaluated",
                        source=source,
                        kind="semantic",
                    ),
                    EvaluationMetric(
                        name="semantic_quality_pass",
                        value=None,
                        status="not_evaluated",
                        source=source,
                        kind="semantic",
                    ),
                ),
            )
        )
    return replace(evaluation_run, stages=tuple(merged_stages))


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None
