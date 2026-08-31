from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal, cast
from uuid import uuid4

EvaluationStage = Literal[
    "retrieval",
    "draft",
    "sketch",
    "prove",
    "repair",
    "end_to_end",
    "explanation",
]
EvaluationStatus = Literal["passed", "failed", "not_evaluated"]
MetricStatus = Literal["evaluated", "not_evaluated"]
MetricKind = Literal["deterministic", "semantic"]
MetricValue = str | int | float | bool | None
ModelMetadataValue = str | int | float | bool | None

EVALUATION_SCHEMA_VERSION: Final = 2
EVALUATION_STAGES: Final[tuple[EvaluationStage, ...]] = (
    "retrieval",
    "draft",
    "sketch",
    "prove",
    "repair",
    "end_to_end",
    "explanation",
)

_EVALUATION_STATUSES: Final = frozenset({"passed", "failed", "not_evaluated"})
_METRIC_STATUSES: Final = frozenset({"evaluated", "not_evaluated"})
_METRIC_KINDS: Final = frozenset({"deterministic", "semantic"})
_TERMINATION_REASONS: Final = frozenset(
    {
        "verified",
        "repair_budget_exhausted",
        "non_repairable_failure",
        "repair_generator_unavailable",
        "repair_route_selection_failed",
        "artifact_store_failure",
    }
)
_TERMINATION_SOURCES: Final = {
    "verified": "verification_success",
    "repair_budget_exhausted": "repair_budget",
    "non_repairable_failure": "verifier_configuration",
    "repair_generator_unavailable": "repair_generator",
    "repair_route_selection_failed": "repair_route_selector",
    "artifact_store_failure": "artifact_store",
}
_MANDATORY_REPAIR_KEYS: Final = (
    "attempts",
    "repairs_used",
    "max_repair_attempts",
    "termination_reason",
    "termination_event",
    "generated",
    "verification",
)
_REPAIR_ROUTES: Final = frozenset({"draft", "sketch", "prove"})
_ATTEMPT_PHASES: Final = frozenset({"preflight", "compile"})
_CHECKPOINT_STATUSES: Final = frozenset({"published", "failed"})
_DIAGNOSTIC_SEVERITIES: Final = frozenset({"info", "warning", "error"})
_MAX_SAFE_INTEGER: Final = 2**53
_AMBIGUOUS_RECOVERY_SUFFIX: Final = ".recovery-ambiguous"
_SEMANTIC_COMMENTS_MIGRATION: Final = "semantic-comments-v2"
_MIGRATION_FENCE_SUFFIX: Final = ".migration-semantic-comments-v2-ambiguous"
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_MISSING: Final = object()


class EvaluationHistoryError(RuntimeError):
    """Base error for durable evaluation-history operations."""


class EvaluationHistoryTornTailError(EvaluationHistoryError):
    """Raised when a JSONL history ends with an unterminated record."""


class EvaluationHistoryRecoveryError(EvaluationHistoryError):
    """Raised when a torn history cannot be recovered before truncation."""


class EvaluationHistoryRecoveryAmbiguousError(EvaluationHistoryRecoveryError):
    """Raised when durability cannot be confirmed after history truncation."""


class EvaluationHistoryMigrationError(EvaluationHistoryError):
    """Raised when an explicit history migration fails before replacement."""


class EvaluationHistoryMigrationAmbiguousError(EvaluationHistoryMigrationError):
    """Raised when migration replacement durability cannot be confirmed."""


@dataclass(frozen=True, slots=True)
class EvaluationMetric:
    name: str
    value: MetricValue
    status: MetricStatus
    source: str
    kind: MetricKind = "deterministic"
    comment: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("metric name must be non-empty")
        if not self.source.strip():
            raise ValueError("metric source must be non-empty")
        if self.status not in _METRIC_STATUSES:
            raise ValueError(f"unsupported metric status: {self.status}")
        if self.kind not in _METRIC_KINDS:
            raise ValueError(f"unsupported metric kind: {self.kind}")
        if self.status == "not_evaluated" and self.value is not None:
            raise ValueError("not_evaluated metrics must have a None value")
        if self.status == "evaluated" and self.value is None:
            raise ValueError("evaluated metrics must have a value")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("metric values must be finite")
        if self.kind == "semantic" and self.comment is not None:
            raise ValueError("semantic metric comments must be None")
        if self.comment is not None and not self.comment.strip():
            raise ValueError("metric comment must be non-empty when provided")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "status": self.status,
            "source": self.source,
            "kind": self.kind,
            "comment": self.comment,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvaluationMetric:
        raw_status = _required_text(payload, "status")
        if raw_status not in _METRIC_STATUSES:
            raise ValueError(f"unsupported metric status: {raw_status}")
        raw_kind = _required_text(payload, "kind")
        if raw_kind not in _METRIC_KINDS:
            raise ValueError(f"unsupported metric kind: {raw_kind}")
        value = payload.get("value")
        if not _is_metric_value(value):
            raise TypeError("metric value must be a JSON scalar")
        return cls(
            name=_required_text(payload, "name"),
            value=cast(MetricValue, value),
            status=cast(MetricStatus, raw_status),
            source=_required_text(payload, "source"),
            kind=cast(MetricKind, raw_kind),
            comment=_optional_text(payload, "comment"),
        )


@dataclass(frozen=True, slots=True)
class EvaluationStageResult:
    stage: EvaluationStage
    status: EvaluationStatus
    metrics: tuple[EvaluationMetric, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", tuple(self.metrics))
        if self.stage not in EVALUATION_STAGES:
            raise ValueError(f"unsupported evaluation stage: {self.stage}")
        if self.status not in _EVALUATION_STATUSES:
            raise ValueError(f"unsupported evaluation status: {self.status}")
        names = [metric.name for metric in self.metrics]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate metric name in {self.stage}")

    def metric(self, name: str) -> EvaluationMetric:
        for metric in self.metrics:
            if metric.name == name:
                return metric
        raise KeyError(f"unknown {self.stage} metric: {name}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "metrics": [metric.to_dict() for metric in self.metrics],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvaluationStageResult:
        raw_stage = _required_text(payload, "stage")
        if raw_stage not in EVALUATION_STAGES:
            raise ValueError(f"unsupported evaluation stage: {raw_stage}")
        raw_status = _required_text(payload, "status")
        if raw_status not in _EVALUATION_STATUSES:
            raise ValueError(f"unsupported evaluation status: {raw_status}")
        raw_metrics = payload.get("metrics")
        if not isinstance(raw_metrics, list):
            raise TypeError("stage metrics must be an array")
        metrics = tuple(
            EvaluationMetric.from_dict(_required_mapping(item, "metric")) for item in raw_metrics
        )
        return cls(
            stage=raw_stage,
            status=cast(EvaluationStatus, raw_status),
            metrics=metrics,
        )


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    suite_revision: str
    run_id: str
    case_id: str
    model: str
    stages: tuple[EvaluationStageResult, ...]
    model_metadata: tuple[tuple[str, ModelMetadataValue], ...] = ()
    created_at: str = ""
    schema_version: int = EVALUATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.suite_revision.strip():
            raise ValueError("suite_revision must be non-empty")
        if not self.run_id.strip():
            raise ValueError("run_id must be non-empty")
        if not self.case_id.strip():
            raise ValueError("case_id must be non-empty")
        if not self.model.strip():
            raise ValueError("model must be non-empty")
        if self.schema_version != EVALUATION_SCHEMA_VERSION:
            raise ValueError(f"unsupported evaluation schema version: {self.schema_version}")

        stages = tuple(self.stages)
        object.__setattr__(self, "stages", stages)
        if tuple(stage.stage for stage in stages) != EVALUATION_STAGES:
            raise ValueError("evaluation runs must contain every stage in canonical order")

        metadata = _normalize_model_metadata_items(self.model_metadata)
        object.__setattr__(self, "model_metadata", metadata)
        created_at = self.created_at or datetime.now(UTC).isoformat()
        _parse_iso_datetime(created_at)
        object.__setattr__(self, "created_at", created_at)

    def stage(self, name: EvaluationStage) -> EvaluationStageResult:
        for stage in self.stages:
            if stage.stage == name:
                return stage
        raise KeyError(f"unknown evaluation stage: {name}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "suite_revision": self.suite_revision,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "model": self.model,
            "model_metadata": dict(self.model_metadata),
            "created_at": self.created_at,
            "stages": [stage.to_dict() for stage in self.stages],
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvaluationRun:
        schema_version = payload.get("schema_version")
        if type(schema_version) is not int:
            raise TypeError("schema_version must be an integer")
        raw_metadata = payload.get("model_metadata")
        if not isinstance(raw_metadata, Mapping):
            raise TypeError("model_metadata must be an object")
        model_metadata = _model_metadata_from_mapping(raw_metadata)
        raw_stages = payload.get("stages")
        if not isinstance(raw_stages, list):
            raise TypeError("stages must be an array")
        stages = tuple(
            EvaluationStageResult.from_dict(_required_mapping(item, "stage")) for item in raw_stages
        )
        return cls(
            schema_version=schema_version,
            suite_revision=_required_text(payload, "suite_revision"),
            run_id=_required_text(payload, "run_id"),
            case_id=_required_text(payload, "case_id"),
            model=_required_text(payload, "model"),
            model_metadata=model_metadata,
            stages=stages,
            created_at=_required_text(payload, "created_at"),
        )

    @classmethod
    def from_json(cls, payload: str) -> EvaluationRun:
        value = json.loads(payload)
        if not isinstance(value, Mapping):
            raise TypeError("evaluation JSON must contain an object")
        return cls.from_dict(value)


@dataclass(frozen=True, slots=True)
class JsonlEvaluationStore:
    path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))

    def append(self, run: EvaluationRun) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = f"{run.to_json()}\n".encode()
        with _history_lock(self.path, exclusive=True):
            _raise_if_history_fenced(self.path)
            descriptor = os.open(
                self.path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                _write_all(descriptor, encoded)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def load_history(self) -> tuple[EvaluationRun, ...]:
        if not self.path.parent.exists():
            return ()
        with _history_lock(self.path, exclusive=False):
            _raise_if_history_fenced(self.path)
            try:
                descriptor = os.open(self.path, os.O_RDONLY)
            except FileNotFoundError:
                return ()
            try:
                snapshot = _read_bounded_snapshot(descriptor)
            finally:
                os.close(descriptor)
        return _parse_history_snapshot(snapshot, self.path)

    def load(self) -> tuple[EvaluationRun, ...]:
        return self.load_history()


def recover_torn_history(path: Path) -> Path:
    """Quarantine one unterminated JSONL suffix and truncate only after it is durable."""

    history_path = Path(path)
    if not history_path.parent.exists():
        raise EvaluationHistoryRecoveryError(
            f"cannot open evaluation history for recovery: {history_path}"
        )
    with _history_lock(history_path, exclusive=True):
        if _migration_fence(history_path).exists():
            raise EvaluationHistoryMigrationAmbiguousError(
                f"evaluation history migration requires operator confirmation: {history_path}"
            )
        try:
            descriptor = os.open(history_path, os.O_RDWR)
        except OSError as exc:
            raise EvaluationHistoryRecoveryError(
                f"cannot open evaluation history for recovery: {history_path}"
            ) from exc
        try:
            snapshot = _read_bounded_snapshot(descriptor)
            marker = _ambiguous_recovery_marker(history_path)
            if not snapshot or snapshot.endswith(b"\n"):
                resumed = _resume_completed_recovery(
                    history_path=history_path,
                    snapshot=snapshot,
                    marker=marker,
                )
                if resumed is not None:
                    return resumed
                raise EvaluationHistoryRecoveryError(
                    f"evaluation history does not contain a torn tail: {history_path}"
                )

            final_lf = snapshot.rfind(b"\n")
            prefix = snapshot[: final_lf + 1] if final_lf >= 0 else b""
            suffix = snapshot[final_lf + 1 :]
            if not suffix:
                raise EvaluationHistoryRecoveryError(
                    f"evaluation history torn suffix is empty: {history_path}"
                )
            try:
                _parse_history_snapshot(prefix, history_path)
            except (EvaluationHistoryError, UnicodeError, ValueError) as exc:
                raise EvaluationHistoryRecoveryError(
                    f"evaluation history prefix is invalid: {history_path}"
                ) from exc

            full_digest = hashlib.sha256(suffix).hexdigest()
            fragment_path = history_path.with_name(
                f"{history_path.name}.torn-{full_digest[:16]}.fragment"
            )
            marker_payload = _recovery_marker_payload(
                prefix_length=len(prefix),
                suffix_sha256=full_digest,
                fragment_name=fragment_path.name,
            )
            if marker.exists():
                if marker.read_bytes() != marker_payload or fragment_path.read_bytes() != suffix:
                    raise EvaluationHistoryRecoveryAmbiguousError(
                        f"evaluation history recovery fence does not match: {history_path}"
                    )
            else:
                _write_durable_create_only(fragment_path, suffix)
                try:
                    _write_durable_create_only(marker, marker_payload)
                except BaseException:
                    raise EvaluationHistoryRecoveryError(
                        f"evaluation history recovery fence could not be created: {history_path}"
                    ) from None

            os.ftruncate(descriptor, len(prefix))
            try:
                os.fsync(descriptor)
            except OSError as exc:
                raise EvaluationHistoryRecoveryAmbiguousError(
                    f"evaluation history truncation durability is ambiguous: {history_path}"
                ) from exc
            try:
                _remove_fence_durable(marker)
            except OSError as exc:
                raise EvaluationHistoryRecoveryAmbiguousError(
                    f"evaluation history recovery fence cleanup is ambiguous: {history_path}"
                ) from exc
            return fragment_path
        except EvaluationHistoryRecoveryError:
            raise
        except (OSError, UnicodeError, ValueError) as exc:
            raise EvaluationHistoryRecoveryError(
                f"evaluation history recovery failed before truncation: {history_path}"
            ) from exc
        finally:
            os.close(descriptor)


def migrate_evaluation_history(
    *,
    path: Path,
    migration: str,
    expected_sha256: str,
) -> dict[str, str | int]:
    history_path = Path(path)
    if migration != _SEMANTIC_COMMENTS_MIGRATION:
        raise EvaluationHistoryMigrationError(
            f"unsupported evaluation history migration: {migration}"
        )
    if _SHA256_RE.fullmatch(expected_sha256) is None:
        raise EvaluationHistoryMigrationError(
            "expected evaluation history SHA-256 must be 64 lowercase hexadecimal characters"
        )
    if not history_path.parent.exists():
        raise EvaluationHistoryMigrationError(
            f"evaluation history does not exist: {history_path}"
        )

    with _history_lock(history_path, exclusive=True):
        _raise_if_history_fenced(history_path)
        try:
            descriptor = os.open(history_path, os.O_RDONLY)
        except OSError as exc:
            raise EvaluationHistoryMigrationError(
                f"evaluation history cannot be opened: {history_path}"
            ) from exc
        try:
            source = _read_bounded_snapshot(descriptor)
        finally:
            os.close(descriptor)

        source_digest = hashlib.sha256(source).hexdigest()
        if source_digest != expected_sha256:
            raise EvaluationHistoryMigrationError(
                "evaluation history source digest does not match expected SHA-256"
            )
        records, change_count, result = _transform_semantic_comments_v2(
            source,
            history_path,
        )
        result_digest = hashlib.sha256(result).hexdigest()
        backup_path = history_path.with_name(
            f"{history_path.name}.pre-{migration}.{source_digest}.backup"
        )
        _ensure_exact_backup(backup_path, source, source_digest)

        fence = _migration_fence(history_path)
        fence_payload = (
            json.dumps(
                {
                    "migration": migration,
                    "source_sha256": source_digest,
                    "result_sha256": result_digest,
                    "backup_name": backup_path.name,
                    "record_count": len(records),
                    "change_count": change_count,
                },
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("ascii")
        temp_path = history_path.with_name(
            f".{history_path.name}.migration-{os.getpid()}-{uuid4().hex}.tmp"
        )
        fence_created = False
        replace_started = False
        temp_created = False
        try:
            _write_durable_create_only(fence, fence_payload)
            fence_created = True
            temp_descriptor = os.open(
                temp_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            temp_created = True
            try:
                _write_all(temp_descriptor, result)
                os.fsync(temp_descriptor)
            finally:
                os.close(temp_descriptor)
            replace_started = True
            os.replace(temp_path, history_path)
            temp_created = False
            _fsync_directory(history_path.parent)
            _validate_migrated_history(
                history_path,
                expected_digest=result_digest,
                expected_count=len(records),
            )
            _remove_fence_durable(fence)
            fence_created = False
        except EvaluationHistoryMigrationAmbiguousError:
            raise
        except Exception as exc:
            if temp_created:
                _remove_incomplete_fragment(temp_path)
            if replace_started:
                raise EvaluationHistoryMigrationAmbiguousError(
                    f"evaluation history migration durability is ambiguous: {history_path}"
                ) from exc
            if fence_created:
                try:
                    _remove_fence_durable(fence)
                    fence_created = False
                except OSError as cleanup_exc:
                    raise EvaluationHistoryMigrationAmbiguousError(
                        f"evaluation history migration fence cleanup is ambiguous: {history_path}"
                    ) from cleanup_exc
            raise EvaluationHistoryMigrationError(
                f"evaluation history migration failed before replacement: {history_path}"
            ) from exc

        return {
            "migration": migration,
            "record_count": len(records),
            "change_count": change_count,
            "source_sha256": source_digest,
            "result_sha256": result_digest,
            "backup_path": str(backup_path),
        }


def evaluate_artifact(
    artifact_metadata: Mapping[str, Any],
    *,
    suite_revision: str,
    run_id: str,
    case_id: str | None = None,
    model: str,
    model_metadata: Mapping[str, ModelMetadataValue] | None = None,
    explanation: Any = None,
    clarifications: Any = _MISSING,
    expect_clarification: Any = _MISSING,
    created_at: str | None = None,
) -> EvaluationRun:
    """Evaluate one persisted pipeline artifact without invoking external services."""

    stages = (
        _evaluate_retrieval(artifact_metadata),
        _evaluate_draft(artifact_metadata),
        _evaluate_sketch(artifact_metadata),
        _evaluate_prove(artifact_metadata),
        _evaluate_repair(artifact_metadata),
        _evaluate_end_to_end(artifact_metadata),
        _evaluate_explanation(
            artifact_metadata,
            explanation,
            clarifications,
            expect_clarification,
        ),
    )
    return EvaluationRun(
        suite_revision=suite_revision,
        run_id=run_id,
        case_id=case_id or _artifact_case_id(artifact_metadata, run_id),
        model=model,
        model_metadata=_model_metadata_from_mapping(model_metadata or {}),
        stages=stages,
        created_at=created_at or datetime.now(UTC).isoformat(),
    )


def summarize_evaluation_runs(
    runs: tuple[EvaluationRun, ...],
    *,
    case_id: str | None = None,
    suite_revision: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Aggregate comparable stage pass rates without treating missing data as failure."""

    selected = tuple(
        run
        for run in runs
        if (case_id is None or run.case_id == case_id)
        and (suite_revision is None or run.suite_revision == suite_revision)
        and (model is None or run.model == model)
    )
    stage_summaries: dict[str, dict[str, Any]] = {}
    for stage_name in EVALUATION_STAGES:
        results = [run.stage(stage_name) for run in selected]
        evaluated = [result for result in results if result.status != "not_evaluated"]
        passed = sum(result.status == "passed" for result in evaluated)
        failed = sum(result.status == "failed" for result in evaluated)
        metric_values: dict[str, list[float]] = {}
        for result in results:
            for metric in result.metrics:
                if (
                    metric.status == "evaluated"
                    and isinstance(metric.value, (int, float))
                    and not isinstance(metric.value, bool)
                ):
                    numeric = _summary_number(metric.value)
                    if numeric is not None:
                        metric_values.setdefault(metric.name, []).append(numeric)
        stage_summaries[stage_name] = {
            "evaluated": len(evaluated),
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / len(evaluated) if evaluated else None,
            "metric_averages": {
                name: sum(values) / len(values)
                for name, values in sorted(metric_values.items())
            },
        }
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "run_count": len(selected),
        "suite_revisions": sorted({run.suite_revision for run in selected}),
        "models": sorted({run.model for run in selected}),
        "cases": sorted({run.case_id for run in selected}),
        "stages": stage_summaries,
    }


def compare_evaluation_runs(
    baseline_runs: tuple[EvaluationRun, ...],
    candidate_runs: tuple[EvaluationRun, ...],
) -> dict[str, Any]:
    """Compare like-for-like cases and report case drift separately."""

    _validate_comparison_operand("baseline", baseline_runs)
    _validate_comparison_operand("candidate", candidate_runs)
    baseline_revision = baseline_runs[0].suite_revision
    candidate_revision = candidate_runs[0].suite_revision
    if baseline_revision != candidate_revision:
        raise ValueError("baseline and candidate must use the same suite revision")

    baseline_cases = {run.case_id for run in baseline_runs}
    candidate_cases = {run.case_id for run in candidate_runs}
    shared_cases = baseline_cases & candidate_cases
    baseline_summary = summarize_evaluation_runs(
        tuple(run for run in baseline_runs if run.case_id in shared_cases)
    )
    candidate_summary = summarize_evaluation_runs(
        tuple(run for run in candidate_runs if run.case_id in shared_cases)
    )

    stages: dict[str, dict[str, Any]] = {}
    for stage_name in EVALUATION_STAGES:
        baseline_stage = baseline_summary["stages"][stage_name]
        candidate_stage = candidate_summary["stages"][stage_name]
        baseline_pass_rate = baseline_stage["pass_rate"]
        candidate_pass_rate = candidate_stage["pass_rate"]
        baseline_metrics = baseline_stage["metric_averages"]
        candidate_metrics = candidate_stage["metric_averages"]
        metric_comparisons: dict[str, dict[str, float | None]] = {}
        for metric_name in sorted(set(baseline_metrics) | set(candidate_metrics)):
            baseline_value = baseline_metrics.get(metric_name)
            candidate_value = candidate_metrics.get(metric_name)
            metric_comparisons[metric_name] = {
                "baseline": baseline_value,
                "candidate": candidate_value,
                "delta": _numeric_delta(baseline_value, candidate_value),
            }
        stages[stage_name] = {
            "baseline_evaluated": baseline_stage["evaluated"],
            "candidate_evaluated": candidate_stage["evaluated"],
            "baseline_pass_rate": baseline_pass_rate,
            "candidate_pass_rate": candidate_pass_rate,
            "pass_rate_delta": _numeric_delta(
                baseline_pass_rate,
                candidate_pass_rate,
            ),
            "metric_averages": metric_comparisons,
        }

    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "baseline_run_ids": sorted({run.run_id for run in baseline_runs}),
        "candidate_run_ids": sorted({run.run_id for run in candidate_runs}),
        "shared_cases": sorted(shared_cases),
        "baseline_only_cases": sorted(baseline_cases - candidate_cases),
        "candidate_only_cases": sorted(candidate_cases - baseline_cases),
        "stages": stages,
    }


def _validate_comparison_operand(
    label: str,
    runs: tuple[EvaluationRun, ...],
) -> None:
    if not runs:
        raise ValueError(f"{label} evaluation runs must be non-empty")
    revisions = {run.suite_revision for run in runs}
    if len(revisions) != 1:
        raise ValueError(f"{label} must contain exactly one suite revision")
    case_ids = [run.case_id for run in runs]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError(f"{label} must contain at most one run per case")


def _summary_number(value: int | float) -> float | None:
    try:
        converted = float(value)
    except OverflowError:
        return None
    return converted if math.isfinite(converted) else None


def _numeric_delta(
    baseline: float | None,
    candidate: float | None,
) -> float | None:
    if baseline is None or candidate is None:
        return None
    return candidate - baseline


def _evaluate_retrieval(artifact: Mapping[str, Any]) -> EvaluationStageResult:
    if "retrieval" not in artifact:
        candidate_present: bool | None = None
        exact_match: bool | None = None
        top_score_present: bool | None = None
        top_score: float | None = None
    else:
        retrieval = _as_mapping(artifact.get("retrieval"))
        candidate_id = retrieval.get("candidate_draft_id") if retrieval is not None else None
        candidate_present = bool(candidate_id.strip()) if isinstance(candidate_id, str) else False
        if retrieval is not None and "exact_equivalence" in retrieval:
            exact_match = _as_bool(retrieval.get("exact_equivalence"))
            if exact_match is None:
                exact_match = False
        else:
            exact_match = None
        scores = _as_mapping(retrieval.get("scores")) if retrieval is not None else None
        raw_score = scores.get("final") if scores is not None else None
        candidate_score = _finite_number(raw_score)
        top_score = (
            candidate_score
            if candidate_score is not None and -1.0 <= candidate_score <= 1.0
            else None
        )
        top_score_present = top_score is not None

    return EvaluationStageResult(
        stage="retrieval",
        status=_required_boolean_status(candidate_present, top_score_present),
        metrics=(
            _metric(
                "candidate_present",
                candidate_present,
                "artifact.retrieval.candidate_draft_id",
            ),
            _metric(
                "exact_equivalence",
                exact_match,
                "artifact.retrieval.exact_equivalence",
            ),
            _metric(
                "top_score_present",
                top_score_present,
                "artifact.retrieval.scores.final",
            ),
            _metric("top_score", top_score, "artifact.retrieval.scores.final"),
        ),
    )


def _evaluate_draft(artifact: Mapping[str, Any]) -> EvaluationStageResult:
    model_attempt = _as_mapping(artifact.get("model_attempt"))
    if model_attempt is None or "draft" not in model_attempt:
        output_present: bool | None = None
        output_nonempty: bool | None = None
    else:
        draft = _as_mapping(model_attempt.get("draft"))
        output_present = draft is not None
        text = draft.get("text", _MISSING) if draft is not None else _MISSING
        output_nonempty = bool(text.strip()) if isinstance(text, str) else False

    return EvaluationStageResult(
        stage="draft",
        status=_required_boolean_status(output_present, output_nonempty),
        metrics=(
            _metric("output_present", output_present, "artifact.model_attempt.draft"),
            _metric(
                "output_nonempty",
                output_nonempty,
                "artifact.model_attempt.draft.text",
            ),
        ),
    )


def _evaluate_sketch(artifact: Mapping[str, Any]) -> EvaluationStageResult:
    model_attempt = _as_mapping(artifact.get("model_attempt"))
    if model_attempt is None or "sketch" not in model_attempt:
        code_present: bool | None = None
        code_nonempty: bool | None = None
        has_gaps: bool | None = None
    else:
        sketch = _as_mapping(model_attempt.get("sketch"))
        if sketch is None:
            code_present = False
            code_nonempty = False
            has_gaps = False
        else:
            code = sketch.get("lean_code", _MISSING)
            code_present = isinstance(code, str)
            code_nonempty = bool(code.strip()) if isinstance(code, str) else False
            has_gaps = _as_bool(sketch.get("has_gaps"))
            if has_gaps is None:
                has_gaps = False

    return EvaluationStageResult(
        stage="sketch",
        status=_required_boolean_status(code_present, code_nonempty),
        metrics=(
            _metric(
                "code_present",
                code_present,
                "artifact.model_attempt.sketch.lean_code",
            ),
            _metric(
                "code_nonempty",
                code_nonempty,
                "artifact.model_attempt.sketch.lean_code",
            ),
            _metric("has_gaps", has_gaps, "artifact.model_attempt.sketch.has_gaps"),
        ),
    )


def _evaluate_prove(artifact: Mapping[str, Any]) -> EvaluationStageResult:
    if "model_attempt" not in artifact:
        code_extracted: bool | None = None
        compile_success: bool | None = None
    else:
        model_attempt = _as_mapping(artifact.get("model_attempt"))
        code = model_attempt.get("lean_code") if model_attempt is not None else None
        code_extracted = bool(code.strip()) if isinstance(code, str) else False
        verification = _as_mapping(artifact.get("model_attempt_verification"))
        compile_success = (
            verification is not None and verification.get("success") is True
        )
    return EvaluationStageResult(
        stage="prove",
        status=_required_boolean_status(code_extracted, compile_success),
        metrics=(
            _metric(
                "code_extracted",
                code_extracted,
                "artifact.model_attempt.lean_code",
            ),
            _metric(
                "compile_success",
                compile_success,
                "artifact.model_attempt_verification.success",
            ),
        ),
    )


def _evaluate_repair(artifact: Mapping[str, Any]) -> EvaluationStageResult:
    if any(key not in artifact for key in _MANDATORY_REPAIR_KEYS):
        return _repair_stage_result(
            status="not_evaluated",
            repair_attempts=None,
            recorded_repairs=None,
            max_repair_attempts=None,
            attempt_count_consistent=None,
            error_reduction=None,
            converged=None,
            termination_reason=None,
            termination_reason_consistent=None,
        )

    raw_attempts = artifact.get("attempts")
    attempts = raw_attempts if isinstance(raw_attempts, list) else None
    repair_attempts = (
        len(attempts) - 1
        if attempts is not None and 1 <= len(attempts) <= _MAX_SAFE_INTEGER
        else None
    )
    recorded_repairs = _bounded_nonnegative_int(artifact.get("repairs_used"))
    max_repair_attempts = _repair_budget(artifact.get("max_repair_attempts"))
    raw_termination_reason = artifact.get("termination_reason")
    termination_reason = (
        raw_termination_reason if isinstance(raw_termination_reason, str) else None
    )

    attempt_mappings = (
        tuple(_as_mapping(item) for item in attempts) if attempts is not None else ()
    )
    final_attempt = attempt_mappings[-1] if attempt_mappings else None
    final_verification = (
        _as_mapping(final_attempt.get("verification"))
        if final_attempt is not None
        else None
    )
    final_success = (
        _as_bool(final_verification.get("success"))
        if final_verification is not None
        else None
    )
    converged = final_success

    attempt_count_consistent = _repair_attempts_consistent(
        attempts=attempt_mappings,
        repair_attempts=repair_attempts,
        recorded_repairs=recorded_repairs,
        max_repair_attempts=max_repair_attempts,
        termination_reason=termination_reason,
    )
    termination_reason_consistent = _repair_termination_consistent(
        artifact=artifact,
        attempts=attempt_mappings,
        repair_attempts=repair_attempts,
        recorded_repairs=recorded_repairs,
        max_repair_attempts=max_repair_attempts,
        termination_reason=termination_reason,
        final_success=final_success,
    )

    error_reduction: int | None = None
    if repair_attempts is not None and repair_attempts >= 1 and attempt_mappings:
        first_errors = _attempt_error_count(attempt_mappings[0])
        last_errors = _attempt_error_count(attempt_mappings[-1])
        if first_errors is not None and last_errors is not None:
            error_reduction = first_errors - last_errors

    status: EvaluationStatus = (
        "passed"
        if converged is True
        and attempt_count_consistent is True
        and termination_reason_consistent is True
        else "failed"
    )
    return _repair_stage_result(
        status=status,
        repair_attempts=repair_attempts,
        recorded_repairs=recorded_repairs,
        max_repair_attempts=max_repair_attempts,
        attempt_count_consistent=attempt_count_consistent,
        error_reduction=error_reduction,
        converged=converged,
        termination_reason=termination_reason,
        termination_reason_consistent=termination_reason_consistent,
    )


def _repair_stage_result(
    *,
    status: EvaluationStatus,
    repair_attempts: int | None,
    recorded_repairs: int | None,
    max_repair_attempts: int | None,
    attempt_count_consistent: bool | None,
    error_reduction: int | None,
    converged: bool | None,
    termination_reason: str | None,
    termination_reason_consistent: bool | None,
) -> EvaluationStageResult:
    return EvaluationStageResult(
        stage="repair",
        status=status,
        metrics=(
            _metric("attempts", repair_attempts, "artifact.attempts"),
            _metric("repairs_used", recorded_repairs, "artifact.repairs_used"),
            _metric(
                "max_repair_attempts",
                max_repair_attempts,
                "artifact.max_repair_attempts",
            ),
            _metric(
                "attempt_count_consistent",
                attempt_count_consistent,
                "artifact.repairs_used+artifact.attempts",
            ),
            _metric(
                "error_reduction",
                error_reduction,
                "artifact.attempts[].verification.diagnostics",
            ),
            _metric(
                "converged",
                converged,
                "artifact.attempts[-1].verification.success",
            ),
            _metric(
                "termination_reason",
                termination_reason,
                "artifact.termination_reason",
            ),
            _metric(
                "termination_reason_consistent",
                termination_reason_consistent,
                "artifact.termination_reason+artifact.attempts[-1].verification.success",
            ),
        ),
    )


def _repair_attempts_consistent(
    *,
    attempts: tuple[Mapping[str, Any] | None, ...],
    repair_attempts: int | None,
    recorded_repairs: int | None,
    max_repair_attempts: int | None,
    termination_reason: str | None,
) -> bool:
    if (
        repair_attempts is None
        or recorded_repairs is None
        or max_repair_attempts is None
        or not attempts
        or any(attempt is None for attempt in attempts)
        or recorded_repairs != repair_attempts
        or recorded_repairs > max_repair_attempts
    ):
        return False

    artifact_store_failure = termination_reason == "artifact_store_failure"
    for index, maybe_attempt in enumerate(attempts, start=1):
        if maybe_attempt is None:
            return False
        attempt = maybe_attempt
        if attempt.get("attempt") != index or isinstance(attempt.get("attempt"), bool):
            return False
        if attempt.get("phase") not in _ATTEMPT_PHASES:
            return False
        generated = _as_mapping(attempt.get("generated"))
        verification = _as_mapping(attempt.get("verification"))
        if generated is None or not isinstance(generated.get("lean_code"), str):
            return False
        if verification is None or _as_bool(verification.get("success")) is None:
            return False
        if not _typed_diagnostics(attempt.get("diagnostics")):
            return False
        if "diagnostics" in verification and not _typed_diagnostics(
            verification.get("diagnostics")
        ):
            return False

        checkpoint_status = attempt.get("checkpoint_status")
        if checkpoint_status not in _CHECKPOINT_STATUSES:
            return False
        final_failed_checkpoint = (
            artifact_store_failure
            and index == len(attempts)
            and checkpoint_status == "failed"
        )
        if not final_failed_checkpoint and checkpoint_status != "published":
            return False

        if index == 1 or final_failed_checkpoint:
            if "repair_route" in attempt:
                return False
        else:
            route = _as_mapping(attempt.get("repair_route"))
            if route is None or route.get("route") not in _REPAIR_ROUTES:
                return False
    return True


def _repair_termination_consistent(
    *,
    artifact: Mapping[str, Any],
    attempts: tuple[Mapping[str, Any] | None, ...],
    repair_attempts: int | None,
    recorded_repairs: int | None,
    max_repair_attempts: int | None,
    termination_reason: str | None,
    final_success: bool | None,
) -> bool:
    if (
        termination_reason not in _TERMINATION_REASONS
        or not attempts
        or any(attempt is None for attempt in attempts)
        or repair_attempts is None
        or recorded_repairs is None
        or max_repair_attempts is None
        or final_success is None
    ):
        return False
    concrete_attempts = cast(tuple[Mapping[str, Any], ...], attempts)
    if any(
        _as_mapping(attempt.get("verification")) is None
        or _as_bool(cast(Mapping[str, Any], attempt["verification"]).get("success"))
        is not False
        for attempt in concrete_attempts[:-1]
    ):
        return False

    top_generated = _as_mapping(artifact.get("generated"))
    top_verification = _as_mapping(artifact.get("verification"))
    final_generated = _as_mapping(concrete_attempts[-1].get("generated"))
    top_success = (
        _as_bool(top_verification.get("success"))
        if top_verification is not None
        else None
    )
    if (
        top_generated is None
        or top_verification is None
        or final_generated is None
        or not isinstance(top_generated.get("lean_code"), str)
        or not isinstance(final_generated.get("lean_code"), str)
        or top_generated.get("lean_code") != final_generated.get("lean_code")
        or top_success is None
        or top_success != final_success
    ):
        return False

    event = _as_mapping(artifact.get("termination_event"))
    if (
        event is None
        or set(event) != {"reason", "attempt", "source"}
        or event.get("reason") != termination_reason
        or event.get("attempt") != len(concrete_attempts)
        or isinstance(event.get("attempt"), bool)
        or event.get("source") != _TERMINATION_SOURCES[termination_reason]
    ):
        return False

    if termination_reason == "verified":
        return final_success is True
    if final_success is not False:
        return False
    if termination_reason == "repair_budget_exhausted":
        return recorded_repairs == max_repair_attempts
    if recorded_repairs >= max_repair_attempts:
        return False
    if termination_reason == "artifact_store_failure":
        return (
            concrete_attempts[-1].get("checkpoint_status") == "failed"
            and "repair_route" not in concrete_attempts[-1]
            and all(
                attempt.get("checkpoint_status") == "published"
                for attempt in concrete_attempts[:-1]
            )
        )
    return concrete_attempts[-1].get("checkpoint_status") == "published"


def _evaluate_end_to_end(artifact: Mapping[str, Any]) -> EvaluationStageResult:
    if "generated" not in artifact and "verification" not in artifact:
        verified: bool | None = None
        final_code_present: bool | None = None
    else:
        verification = _as_mapping(artifact.get("verification"))
        verified = verification is not None and verification.get("success") is True
        generated = _as_mapping(artifact.get("generated"))
        code = generated.get("lean_code") if generated is not None else None
        final_code_present = bool(code.strip()) if isinstance(code, str) else False

    return EvaluationStageResult(
        stage="end_to_end",
        status=_required_boolean_status(verified, final_code_present),
        metrics=(
            _metric("verified", verified, "artifact.verification.success"),
            _metric(
                "final_code_present",
                final_code_present,
                "artifact.generated.lean_code",
            ),
        ),
    )


def _evaluate_explanation(
    artifact: Mapping[str, Any],
    explanation: Any,
    clarifications: Any,
    expect_clarification: Any,
) -> EvaluationStageResult:
    verification = _as_mapping(artifact.get("verification"))
    if verification is None or verification.get("success") is not True:
        return _explanation_stage_result(
            status="not_evaluated",
            payload_present=None,
            shape_valid=None,
            reference_count=None,
            valid_reference_count=None,
            references_valid=None,
            reference_coverage=None,
            clarification_count=None,
            clarifications_complete=None,
            clarification_references_valid=None,
            clarification_section_overlap=None,
        )

    explanation_mapping = _as_mapping(explanation)
    payload_present = explanation_mapping is not None
    shape_valid = (
        _explanation_shape_valid(explanation_mapping)
        if explanation_mapping is not None
        else False
    )
    generated = _as_mapping(artifact.get("generated"))
    code = generated.get("lean_code") if generated is not None else None
    if explanation_mapping is None or not isinstance(code, str) or not code.strip():
        reference_count = 0
        valid_reference_count = 0
        references_valid = False
        reference_coverage = 0.0
    else:
        (
            reference_count,
            valid_reference_count,
            references_valid,
            reference_coverage,
        ) = _explanation_reference_metrics(explanation_mapping, code)

    core_status = _required_boolean_status(
        payload_present,
        shape_valid,
        references_valid,
    )
    if expect_clarification is False:
        clarification_count: int | None = None
        clarifications_complete: bool | None = None
        clarification_references_valid: bool | None = None
        clarification_section_overlap: bool | None = None
        status = core_status
    elif expect_clarification is True:
        if explanation_mapping is None or not isinstance(code, str) or not code.strip():
            clarification_count = 0
            clarifications_complete = False
            clarification_references_valid = False
            clarification_section_overlap = False
        else:
            (
                clarification_count,
                clarifications_complete,
                clarification_references_valid,
                clarification_section_overlap,
            ) = _clarification_metrics(explanation_mapping, clarifications, code)
        status = _required_boolean_status(
            payload_present,
            shape_valid,
            references_valid,
            clarifications_complete,
            clarification_references_valid,
            clarification_section_overlap,
        )
    else:
        clarification_count = None
        clarifications_complete = None
        clarification_references_valid = None
        clarification_section_overlap = None
        status = "failed" if core_status == "failed" else "not_evaluated"

    return _explanation_stage_result(
        status=status,
        payload_present=payload_present,
        shape_valid=shape_valid,
        reference_count=reference_count,
        valid_reference_count=valid_reference_count,
        references_valid=references_valid,
        reference_coverage=reference_coverage,
        clarification_count=clarification_count,
        clarifications_complete=clarifications_complete,
        clarification_references_valid=clarification_references_valid,
        clarification_section_overlap=clarification_section_overlap,
    )


def _explanation_stage_result(
    *,
    status: EvaluationStatus,
    payload_present: bool | None,
    shape_valid: bool | None,
    reference_count: int | None,
    valid_reference_count: int | None,
    references_valid: bool | None,
    reference_coverage: float | None,
    clarification_count: int | None,
    clarifications_complete: bool | None,
    clarification_references_valid: bool | None,
    clarification_section_overlap: bool | None,
) -> EvaluationStageResult:
    return EvaluationStageResult(
        stage="explanation",
        status=status,
        metrics=(
            _metric("payload_present", payload_present, "explanation"),
            _metric("shape_valid", shape_valid, "explanation"),
            _metric(
                "reference_count",
                reference_count,
                "explanation.sections[].references",
            ),
            _metric(
                "valid_reference_count",
                valid_reference_count,
                "explanation.sections[].references+artifact.generated.lean_code",
            ),
            _metric(
                "references_valid",
                references_valid,
                "explanation.sections[].references+artifact.generated.lean_code",
            ),
            _metric(
                "reference_coverage",
                reference_coverage,
                "explanation.sections[].references+artifact.generated.lean_code",
            ),
            _metric(
                "clarification_count",
                clarification_count,
                "clarifications",
            ),
            _metric(
                "clarifications_complete",
                clarifications_complete,
                "clarifications[].section_id+question+answer+key_points",
            ),
            _metric(
                "clarification_references_valid",
                clarification_references_valid,
                "clarifications[].references+artifact.generated.lean_code",
            ),
            _metric(
                "clarification_section_overlap",
                clarification_section_overlap,
                "clarifications[].references+explanation.sections[].references",
            ),
        ),
    )


def _explanation_reference_metrics(
    explanation: Mapping[str, Any],
    lean_code: str,
) -> tuple[int, int, bool, float]:
    raw_sections = explanation.get("sections")
    lines = lean_code.splitlines()
    nonempty_lines = {index for index, line in enumerate(lines, start=1) if line.strip()}
    if not isinstance(raw_sections, list):
        return 0, 0, False, 0.0

    structure_valid = True
    reference_count = 0
    valid_reference_count = 0
    covered_lines: set[int] = set()
    for raw_section in raw_sections:
        section = _as_mapping(raw_section)
        if section is None:
            structure_valid = False
            continue
        raw_references = section.get("references")
        if not isinstance(raw_references, list):
            structure_valid = False
            continue
        reference_count += len(raw_references)
        for raw_reference in raw_references:
            reference = _as_mapping(raw_reference)
            valid_lines = (
                _valid_reference_lines(reference, lines) if reference is not None else None
            )
            if valid_lines is None:
                structure_valid = False
                continue
            valid_reference_count += 1
            covered_lines.update(valid_lines & nonempty_lines)

    references_valid = (
        structure_valid and reference_count > 0 and valid_reference_count == reference_count
    )
    coverage = len(covered_lines) / len(nonempty_lines) if nonempty_lines else 0.0
    return reference_count, valid_reference_count, references_valid, coverage


def _explanation_shape_valid(explanation: Mapping[str, Any]) -> bool:
    overview = explanation.get("overview")
    conclusion = explanation.get("conclusion")
    raw_sections = explanation.get("sections")
    if (
        not _bounded_text(overview, minimum=1, maximum=600)
        or not _bounded_text(conclusion, minimum=1, maximum=600)
        or not isinstance(raw_sections, list)
        or not 1 <= len(raw_sections) <= 20
    ):
        return False

    section_ids: set[str] = set()
    for raw_section in raw_sections:
        section = _as_mapping(raw_section)
        if section is None:
            return False
        section_id = section.get("id")
        if (
            not isinstance(section_id, str)
            or not _trim_unicode_whitespace(section_id)
            or section_id in section_ids
            or not _bounded_text(section.get("title"), minimum=1, maximum=80)
            or not _bounded_text(section.get("summary"), minimum=1, maximum=800)
        ):
            return False
        section_ids.add(section_id)
        references = section.get("references")
        if not isinstance(references, list) or not 1 <= len(references) <= 20:
            return False
        if any(not _reference_shape_valid(reference) for reference in references):
            return False
    return True


def _reference_shape_valid(value: Any) -> bool:
    reference = _as_mapping(value)
    if reference is None:
        return False
    start_line = reference.get("start_line")
    end_line = reference.get("end_line")
    excerpt = reference.get("excerpt")
    return (
        type(start_line) is int
        and type(end_line) is int
        and start_line >= 1
        and end_line >= start_line
        and isinstance(excerpt, str)
        and bool(_trim_unicode_whitespace(excerpt))
    )


def _valid_reference_lines(
    reference: Mapping[str, Any],
    lean_lines: list[str],
) -> set[int] | None:
    start_line = reference.get("start_line")
    end_line = reference.get("end_line")
    excerpt = reference.get("excerpt")
    if type(start_line) is not int or type(end_line) is not int:
        return None
    if not isinstance(excerpt, str):
        return None
    if start_line < 1 or end_line < start_line or end_line > len(lean_lines):
        return None
    actual_excerpt = "\n".join(lean_lines[start_line - 1 : end_line])
    if excerpt != actual_excerpt:
        return None
    return set(range(start_line, end_line + 1))


def _clarification_metrics(
    explanation: Mapping[str, Any],
    clarifications: Any,
    lean_code: str,
) -> tuple[int, bool, bool, bool]:
    if (
        not isinstance(clarifications, Sequence)
        or isinstance(clarifications, (str, bytes, bytearray, Mapping))
    ):
        return 0, False, False, False
    count = len(clarifications)
    if count == 0 or count > _MAX_SAFE_INTEGER:
        return 0, False, False, False

    lean_lines = lean_code.splitlines()
    sections = _explanation_sections(explanation, lean_lines)
    structures_complete = sections is not None
    references_valid = True
    section_overlap = sections is not None

    for raw_clarification in clarifications:
        clarification = _as_mapping(raw_clarification)
        if clarification is None:
            structures_complete = False
            references_valid = False
            section_overlap = False
            continue
        section_id = clarification.get("section_id")
        question = clarification.get("question")
        answer = clarification.get("answer")
        key_points = clarification.get("key_points")
        raw_references = clarification.get("references")
        selected = (
            sections.get(section_id)
            if sections is not None and isinstance(section_id, str)
            else None
        )
        selected_summary = selected[1] if selected is not None else None
        if (
            not isinstance(section_id, str)
            or not _trim_unicode_whitespace(section_id)
            or not isinstance(question, str)
            or not _trim_unicode_whitespace(question)
            or not _bounded_text(answer, minimum=40, maximum=4000)
            or not isinstance(key_points, list)
            or not 2 <= len(key_points) <= 10
            or not all(_bounded_text(point, minimum=1, maximum=500) for point in key_points)
            or not isinstance(raw_references, list)
            or not 1 <= len(raw_references) <= 20
            or selected_summary is None
            or not isinstance(answer, str)
            or _normalize_unicode_whitespace(answer)
            == _normalize_unicode_whitespace(selected_summary)
            or len(_normalize_unicode_whitespace(answer))
            <= len(_normalize_unicode_whitespace(selected_summary))
        ):
            structures_complete = False

        selected_lines = (
            selected[0]
            if selected is not None
            else None
        )
        if selected_lines is None:
            structures_complete = False
            section_overlap = False

        valid_reference_lines: list[set[int]] = []
        if isinstance(raw_references, list):
            for raw_reference in raw_references:
                reference = _as_mapping(raw_reference)
                lines = (
                    _valid_reference_lines(reference, lean_lines)
                    if reference is not None
                    else None
                )
                if lines is None:
                    references_valid = False
                    continue
                valid_reference_lines.append(lines)
        else:
            references_valid = False

        if not valid_reference_lines:
            references_valid = False
            section_overlap = False
        elif selected_lines is None or not any(
            lines & selected_lines for lines in valid_reference_lines
        ):
            section_overlap = False

    return count, structures_complete, references_valid, section_overlap


def _explanation_sections(
    explanation: Mapping[str, Any],
    lean_lines: list[str],
) -> dict[str, tuple[set[int], str]] | None:
    raw_sections = explanation.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        return None

    result: dict[str, tuple[set[int], str]] = {}
    for raw_section in raw_sections:
        section = _as_mapping(raw_section)
        if section is None:
            return None
        section_id = section.get("id")
        summary = section.get("summary")
        raw_references = section.get("references")
        if (
            not isinstance(section_id, str)
            or not section_id.strip()
            or section_id in result
            or not isinstance(summary, str)
            or not isinstance(raw_references, list)
            or not raw_references
        ):
            return None
        lines: set[int] = set()
        for raw_reference in raw_references:
            reference = _as_mapping(raw_reference)
            valid_lines = (
                _valid_reference_lines(reference, lean_lines)
                if reference is not None
                else None
            )
            if valid_lines is None:
                return None
            lines.update(valid_lines)
        result[section_id] = (lines, summary)
    return result


def _attempt_error_count(attempt: Mapping[str, Any] | None) -> int | None:
    if attempt is None:
        return None
    verification = _as_mapping(attempt.get("verification"))
    if verification is not None and "diagnostics" in verification:
        diagnostics = verification.get("diagnostics")
    else:
        diagnostics = attempt.get("diagnostics", _MISSING)
    if not isinstance(diagnostics, list) or not _typed_diagnostics(diagnostics):
        return None

    return sum(
        1
        for raw_diagnostic in diagnostics
        if isinstance(raw_diagnostic, Mapping)
        and raw_diagnostic.get("severity") == "error"
    )


def _typed_diagnostics(value: Any) -> bool:
    if not isinstance(value, list) or len(value) > _MAX_SAFE_INTEGER:
        return False
    for raw_diagnostic in value:
        diagnostic = _as_mapping(raw_diagnostic)
        if diagnostic is None:
            return False
        severity = diagnostic.get("severity")
        message = diagnostic.get("message")
        code = diagnostic.get("code")
        line = diagnostic.get("line")
        column = diagnostic.get("column")
        if severity not in _DIAGNOSTIC_SEVERITIES or not isinstance(message, str):
            return False
        if code is not None and not isinstance(code, str):
            return False
        if line is not None and (type(line) is not int or line < 1):
            return False
        if column is not None and (type(column) is not int or column < 0):
            return False
    return True


def _bounded_text(value: Any, *, minimum: int, maximum: int) -> bool:
    if not isinstance(value, str):
        return False
    length = len(_trim_unicode_whitespace(value))
    return minimum <= length <= maximum


def _is_unicode_whitespace(character: str) -> bool:
    code_point = ord(character)
    return (
        0x0009 <= code_point <= 0x000D
        or code_point == 0x0020
        or code_point == 0x0085
        or code_point == 0x00A0
        or code_point == 0x1680
        or 0x2000 <= code_point <= 0x200A
        or code_point in {0x2028, 0x2029, 0x202F, 0x205F, 0x3000}
    )


def _trim_unicode_whitespace(value: str) -> str:
    start = 0
    end = len(value)
    while start < end and _is_unicode_whitespace(value[start]):
        start += 1
    while end > start and _is_unicode_whitespace(value[end - 1]):
        end -= 1
    return value[start:end]


def _normalize_unicode_whitespace(value: str) -> str:
    normalized: list[str] = []
    in_whitespace = False
    for character in value:
        if _is_unicode_whitespace(character):
            if normalized and not in_whitespace:
                normalized.append(" ")
            in_whitespace = True
            continue
        normalized.append(character)
        in_whitespace = False
    if normalized and normalized[-1] == " ":
        normalized.pop()
    return "".join(normalized)


def _metric(name: str, value: MetricValue, source: str) -> EvaluationMetric:
    return EvaluationMetric(
        name=name,
        value=value,
        status="evaluated" if value is not None else "not_evaluated",
        source=source,
    )


def _required_boolean_status(*values: bool | None) -> EvaluationStatus:
    if any(value is False for value in values):
        return "failed"
    if values and all(value is True for value in values):
        return "passed"
    return "not_evaluated"


def _model_metadata_from_mapping(
    metadata: Mapping[str, Any],
) -> tuple[tuple[str, ModelMetadataValue], ...]:
    items: list[tuple[str, ModelMetadataValue]] = []
    for key, value in metadata.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("model metadata keys must be non-empty strings")
        if not _is_model_metadata_value(value):
            raise TypeError(f"model metadata value for {key!r} must be a JSON scalar")
        items.append((key, cast(ModelMetadataValue, value)))
    return _normalize_model_metadata_items(tuple(items))


def _normalize_model_metadata_items(
    items: tuple[tuple[str, ModelMetadataValue], ...],
) -> tuple[tuple[str, ModelMetadataValue], ...]:
    normalized: list[tuple[str, ModelMetadataValue]] = []
    seen: set[str] = set()
    for key, value in items:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("model metadata keys must be non-empty strings")
        if key in seen:
            raise ValueError(f"duplicate model metadata key: {key}")
        if not _is_model_metadata_value(value):
            raise TypeError(f"model metadata value for {key!r} must be a JSON scalar")
        seen.add(key)
        normalized.append((key, value))
    return tuple(sorted(normalized, key=lambda item: item[0]))


def _required_mapping(value: Any, label: str) -> Mapping[str, Any]:
    mapping = _as_mapping(value)
    if mapping is None:
        raise TypeError(f"{label} must be an object")
    return mapping


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string when provided")
    return value


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _as_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None


def _nonnegative_int(value: Any) -> int | None:
    return _bounded_nonnegative_int(value)


def _bounded_nonnegative_int(value: Any) -> int | None:
    if type(value) is not int or value < 0 or value > _MAX_SAFE_INTEGER:
        return None
    parsed: int = value
    return parsed


def _repair_budget(value: Any) -> int | None:
    if type(value) is not int or not 1 <= value <= 64:
        return None
    parsed: int = value
    return parsed


def _is_metric_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _is_model_metadata_value(value: Any) -> bool:
    return _is_metric_value(value)


def _artifact_case_id(artifact: Mapping[str, Any], run_id: str) -> str:
    for key in ("problem_id", "proof_job_id", "draft_id"):
        value = artifact.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return run_id


def _parse_iso_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("created_at must be an ISO 8601 datetime") from exc
    if parsed.tzinfo is None:
        raise ValueError("created_at must include a timezone")
    return parsed


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("failed to append evaluation JSONL record")
        remaining = remaining[written:]


@contextmanager
def _history_lock(path: Path, *, exclusive: bool) -> Iterator[None]:
    lock_path = path.with_name(path.name + ".lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _raise_if_history_fenced(path: Path) -> None:
    if _ambiguous_recovery_marker(path).exists():
        raise EvaluationHistoryRecoveryAmbiguousError(
            f"evaluation history recovery requires operator confirmation: {path}"
        )
    if _migration_fence(path).exists():
        raise EvaluationHistoryMigrationAmbiguousError(
            f"evaluation history migration requires operator confirmation: {path}"
        )


def _migration_fence(path: Path) -> Path:
    return path.with_name(path.name + _MIGRATION_FENCE_SUFFIX)


def _transform_semantic_comments_v2(
    source: bytes,
    path: Path,
) -> tuple[list[dict[str, Any]], int, bytes]:
    if not source or not source.endswith(b"\n"):
        raise EvaluationHistoryMigrationError(
            f"evaluation history migration requires LF-terminated records: {path}"
        )
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvaluationHistoryMigrationError(
            f"evaluation history is not valid UTF-8: {path}"
        ) from exc

    records: list[dict[str, Any]] = []
    change_count = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise EvaluationHistoryMigrationError(
                f"invalid evaluation history at {path}:{line_number}: blank record"
            )
        try:
            value = json.loads(line, object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, ValueError) as exc:
            raise EvaluationHistoryMigrationError(
                f"invalid evaluation history JSON at {path}:{line_number}"
            ) from exc
        if not isinstance(value, dict) or value.get("schema_version") != 2:
            raise EvaluationHistoryMigrationError(
                f"migration requires schema_version=2 at {path}:{line_number}"
            )
        stages = value.get("stages")
        if isinstance(stages, list):
            for stage in stages:
                if not isinstance(stage, dict):
                    continue
                metrics = stage.get("metrics")
                if not isinstance(metrics, list):
                    continue
                for metric in metrics:
                    if (
                        isinstance(metric, dict)
                        and metric.get("kind") == "semantic"
                        and metric.get("comment") is not None
                    ):
                        metric["comment"] = None
                        change_count += 1
        try:
            EvaluationRun.from_dict(value)
        except (KeyError, TypeError, ValueError) as exc:
            raise EvaluationHistoryMigrationError(
                f"migration cannot repair unrelated schema error at {path}:{line_number}"
            ) from exc
        records.append(value)

    if change_count == 0:
        raise EvaluationHistoryMigrationError(
            "evaluation history contains no applicable semantic comments"
        )
    result = b"".join(
        (
            json.dumps(
                record,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        for record in records
    )
    return records, change_count, result


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _ensure_exact_backup(path: Path, source: bytes, source_digest: str) -> None:
    try:
        _write_durable_create_only(path, source)
        return
    except FileExistsError:
        pass
    except OSError as exc:
        raise EvaluationHistoryMigrationError(
            f"evaluation history backup cannot be created: {path}"
        ) from exc
    try:
        existing = path.read_bytes()
        mode = path.stat().st_mode & 0o777
    except OSError as exc:
        raise EvaluationHistoryMigrationError(
            f"evaluation history backup cannot be validated: {path}"
        ) from exc
    if (
        existing != source
        or hashlib.sha256(existing).hexdigest() != source_digest
        or mode != 0o600
    ):
        raise EvaluationHistoryMigrationError(
            f"evaluation history backup does not match source: {path}"
        )


def _validate_migrated_history(
    path: Path,
    *,
    expected_digest: str,
    expected_count: int,
) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        snapshot = _read_bounded_snapshot(descriptor)
    finally:
        os.close(descriptor)
    if hashlib.sha256(snapshot).hexdigest() != expected_digest:
        raise EvaluationHistoryMigrationAmbiguousError(
            f"migrated evaluation history digest mismatch: {path}"
        )
    if len(_parse_history_snapshot(snapshot, path)) != expected_count:
        raise EvaluationHistoryMigrationAmbiguousError(
            f"migrated evaluation history record count mismatch: {path}"
        )


def _recovery_marker_payload(
    *,
    prefix_length: int,
    suffix_sha256: str,
    fragment_name: str,
) -> bytes:
    return (
        json.dumps(
            {
                "prefix_length": prefix_length,
                "suffix_sha256": suffix_sha256,
                "fragment_name": fragment_name,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("ascii")


def _resume_completed_recovery(
    *,
    history_path: Path,
    snapshot: bytes,
    marker: Path,
) -> Path | None:
    if not marker.exists():
        return None
    try:
        evidence = json.loads(marker.read_text(encoding="ascii"))
        if not isinstance(evidence, dict) or set(evidence) != {
            "prefix_length",
            "suffix_sha256",
            "fragment_name",
        }:
            raise ValueError("invalid recovery evidence fields")
        prefix_length = evidence["prefix_length"]
        suffix_sha256 = evidence["suffix_sha256"]
        fragment_name = evidence["fragment_name"]
        if (
            type(prefix_length) is not int
            or prefix_length != len(snapshot)
            or not isinstance(suffix_sha256, str)
            or _SHA256_RE.fullmatch(suffix_sha256) is None
            or not isinstance(fragment_name, str)
            or Path(fragment_name).name != fragment_name
        ):
            raise ValueError("invalid recovery evidence values")
        fragment = history_path.with_name(fragment_name)
        if hashlib.sha256(fragment.read_bytes()).hexdigest() != suffix_sha256:
            raise ValueError("recovery fragment digest mismatch")
        _parse_history_snapshot(snapshot, history_path)
        _remove_fence_durable(marker)
        return fragment
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise EvaluationHistoryRecoveryAmbiguousError(
            f"evaluation history recovery fence does not match: {history_path}"
        ) from exc


def _remove_fence_durable(path: Path) -> None:
    payload = path.read_bytes()
    path.unlink()
    try:
        _fsync_directory(path.parent)
    except BaseException:
        _restore_visible_fence(path, payload)
        raise


def _restore_visible_fence(path: Path, payload: bytes) -> None:
    """Keep later readers closed even when fence-directory fsync is unavailable."""

    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return
    except OSError:
        return
    try:
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, payload)
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
    with suppress(OSError):
        _fsync_directory(path.parent)


def _read_bounded_snapshot(descriptor: int) -> bytes:
    size = os.fstat(descriptor).st_size
    if size < 0:
        raise OSError("evaluation history reported a negative size")
    os.lseek(descriptor, 0, os.SEEK_SET)
    remaining = size
    chunks: list[bytes] = []
    while remaining:
        chunk = os.read(descriptor, min(remaining, 1024 * 1024))
        if not chunk:
            raise OSError("evaluation history changed during locked snapshot read")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _parse_history_snapshot(
    snapshot: bytes,
    path: Path,
) -> tuple[EvaluationRun, ...]:
    if not snapshot:
        return ()
    if not snapshot.endswith(b"\n"):
        raise EvaluationHistoryTornTailError(
            f"evaluation history has an unterminated tail: {path}"
        )
    try:
        text = snapshot.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"evaluation history is not valid UTF-8: {path}") from exc

    history: list[EvaluationRun] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise ValueError(f"invalid evaluation history at {path}:{line_number}: blank record")
        try:
            history.append(EvaluationRun.from_json(line))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"invalid evaluation history at {path}:{line_number}: {exc}"
            ) from exc
    return tuple(history)


def _write_durable_create_only(path: Path, payload: bytes) -> None:
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        created = True
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        _fsync_directory(path.parent)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            _remove_incomplete_fragment(path)
        raise


def _remove_incomplete_fragment(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
        _fsync_directory(path.parent)
    except OSError:
        pass


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ambiguous_recovery_marker(path: Path) -> Path:
    return path.with_name(path.name + _AMBIGUOUS_RECOVERY_SUFFIX)


def _record_ambiguous_recovery(path: Path) -> None:
    marker = _ambiguous_recovery_marker(path)
    try:
        _write_durable_create_only(marker, b"operator-confirmation-required\n")
    except FileExistsError:
        return
    except OSError:
        return
