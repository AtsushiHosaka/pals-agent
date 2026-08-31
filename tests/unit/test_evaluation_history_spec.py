import fcntl
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import pals_agent.evaluation as evaluation_module
from pals_agent.evaluation import (
    EVALUATION_STAGES,
    EvaluationMetric,
    EvaluationRun,
    EvaluationStageResult,
    EvaluationStatus,
    JsonlEvaluationStore,
    compare_evaluation_runs,
    summarize_evaluation_runs,
)


def _run(
    *,
    run_id: str,
    case_id: str,
    suite_revision: str = "suite-1",
    stage_status: EvaluationStatus = "passed",
    numeric_value: float = 1.0,
) -> EvaluationRun:
    stages = []
    for stage in EVALUATION_STAGES:
        metrics = (
            EvaluationMetric(
                name="numeric",
                value=numeric_value,
                status="evaluated",
                source="fixture",
            ),
            EvaluationMetric(
                name="boolean",
                value=True,
                status="evaluated",
                source="fixture",
            ),
        )
        stages.append(
            EvaluationStageResult(
                stage=stage,
                status=stage_status,
                metrics=metrics,
            )
        )
    return EvaluationRun(
        suite_revision=suite_revision,
        run_id=run_id,
        case_id=case_id,
        model="model-1",
        stages=tuple(stages),
        created_at="2026-07-14T00:00:00+09:00",
    )


def test_pae_012_summary_excludes_booleans_and_uses_exact_filters() -> None:
    runs = (
        _run(run_id="r1", case_id="a", numeric_value=0.25),
        _run(run_id="r2", case_id="b", numeric_value=0.75),
    )

    summary = summarize_evaluation_runs(
        runs,
        case_id="a",
        suite_revision="suite-1",
        model="model-1",
    )

    assert summary["run_count"] == 1
    assert summary["cases"] == ["a"]
    assert summary["stages"]["retrieval"]["metric_averages"] == {"numeric": 0.25}
    assert summarize_evaluation_runs(runs, case_id="A")["run_count"] == 0


@pytest.mark.parametrize(
    ("baseline", "candidate", "message"),
    [
        ((), (_run(run_id="c", case_id="a"),), "non-empty"),
        ((_run(run_id="b", case_id="a"),), (), "non-empty"),
        (
            (
                _run(run_id="b1", case_id="a", suite_revision="suite-1"),
                _run(run_id="b2", case_id="b", suite_revision="suite-2"),
            ),
            (_run(run_id="c", case_id="a"),),
            "one suite revision",
        ),
        (
            (_run(run_id="b", case_id="a", suite_revision="suite-1"),),
            (_run(run_id="c", case_id="a", suite_revision="suite-2"),),
            "same suite revision",
        ),
        (
            (
                _run(run_id="b1", case_id="a"),
                _run(run_id="b2", case_id="a"),
            ),
            (_run(run_id="c", case_id="a"),),
            "one run per case",
        ),
    ],
)
def test_pae_012_comparison_rejects_ambiguous_pairing(
    baseline: tuple[EvaluationRun, ...],
    candidate: tuple[EvaluationRun, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        compare_evaluation_runs(baseline, candidate)


def test_pae_012_comparison_empty_intersection_is_valid_and_does_not_mutate_inputs() -> None:
    baseline = (_run(run_id="b", case_id="baseline-only"),)
    candidate = (_run(run_id="c", case_id="candidate-only"),)
    baseline_before = baseline[0].to_json()
    candidate_before = candidate[0].to_json()

    comparison = compare_evaluation_runs(baseline, candidate)

    assert comparison["shared_cases"] == []
    assert comparison["baseline_only_cases"] == ["baseline-only"]
    assert comparison["candidate_only_cases"] == ["candidate-only"]
    assert comparison["stages"]["retrieval"]["baseline_pass_rate"] is None
    assert comparison["stages"]["retrieval"]["candidate_pass_rate"] is None
    assert comparison["stages"]["retrieval"]["pass_rate_delta"] is None
    assert baseline[0].to_json() == baseline_before
    assert candidate[0].to_json() == candidate_before


def test_pae_011_reader_waits_for_writer_exclusive_lock_and_reads_one_snapshot(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.jsonl"
    lock_path = tmp_path / "history.jsonl.lock"
    first = _run(run_id="r1", case_id="a")
    second = _run(run_id="r2", case_id="b")
    path.write_bytes((first.to_json() + "\n").encode())
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(JsonlEvaluationStore(path).load_history)
            assert not future.done()
            history_descriptor = os.open(path, os.O_APPEND | os.O_WRONLY)
            try:
                os.write(history_descriptor, (second.to_json() + "\n").encode())
                os.fsync(history_descriptor)
            finally:
                os.close(history_descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            assert future.result(timeout=2) == (first, second)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def test_pae_011_recovery_marker_failure_precedes_ftruncate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery_error = getattr(evaluation_module, "EvaluationHistoryRecoveryError", None)
    assert isinstance(recovery_error, type)
    path = tmp_path / "history.jsonl"
    first = _run(run_id="r1", case_id="a")
    original = (first.to_json() + "\npartial").encode()
    path.write_bytes(original)
    real_write = evaluation_module._write_durable_create_only
    truncations: list[int] = []

    def fail_marker(marker_path: Path, payload: bytes) -> None:
        if marker_path.name.endswith(".recovery-ambiguous"):
            raise OSError("injected marker creation failure")
        real_write(marker_path, payload)

    def record_ftruncate(descriptor: int, length: int) -> None:
        _ = descriptor
        truncations.append(length)

    monkeypatch.setattr(evaluation_module, "_write_durable_create_only", fail_marker)
    monkeypatch.setattr(os, "ftruncate", record_ftruncate)

    with pytest.raises(recovery_error):
        evaluation_module.recover_torn_history(path)

    assert truncations == []
    assert path.read_bytes() == original


def test_pae_018_migration_fence_blocks_ordinary_load(
    tmp_path: Path,
) -> None:
    ambiguous_error = getattr(
        evaluation_module,
        "EvaluationHistoryMigrationAmbiguousError",
        None,
    )
    assert isinstance(ambiguous_error, type)
    path = tmp_path / "history.jsonl"
    first = _run(run_id="r1", case_id="a")
    path.write_bytes((first.to_json() + "\n").encode())
    fence = tmp_path / "history.jsonl.migration-semantic-comments-v2-ambiguous"
    fence.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ambiguous_error):
        JsonlEvaluationStore(path).load_history()


def test_pae_011_torn_tail_fails_closed_without_mutation(tmp_path: Path) -> None:
    error_type = getattr(evaluation_module, "EvaluationHistoryTornTailError", None)
    assert isinstance(error_type, type)
    path = tmp_path / "history.jsonl"
    first = _run(run_id="r1", case_id="a")
    torn = b'{"schema_version":2'
    original = (first.to_json() + "\n").encode() + torn
    path.write_bytes(original)

    with pytest.raises(error_type):
        JsonlEvaluationStore(path).load_history()

    assert path.read_bytes() == original


def test_pae_011_explicit_recovery_quarantines_exact_suffix_and_preserves_prefix(
    tmp_path: Path,
) -> None:
    recover = getattr(evaluation_module, "recover_torn_history", None)
    assert callable(recover)
    path = tmp_path / "history.jsonl"
    first = _run(run_id="r1", case_id="a")
    prefix = (first.to_json() + "\n").encode()
    suffix = '{"partial":"失敗"}'.encode()
    path.write_bytes(prefix + suffix)

    fragment = recover(path)

    digest = hashlib.sha256(suffix).hexdigest()[:16]
    assert fragment == tmp_path / f"history.jsonl.torn-{digest}.fragment"
    assert fragment.read_bytes() == suffix
    assert fragment.stat().st_mode & 0o777 == 0o600
    assert path.read_bytes() == prefix
    assert JsonlEvaluationStore(path).load_history() == (first,)


def test_pae_011_recovery_refuses_invalid_prefix_without_truncating(tmp_path: Path) -> None:
    recover = getattr(evaluation_module, "recover_torn_history", None)
    assert callable(recover)
    recovery_error = getattr(evaluation_module, "EvaluationHistoryRecoveryError", None)
    assert isinstance(recovery_error, type)
    path = tmp_path / "history.jsonl"
    original = b"not-json\npartial"
    path.write_bytes(original)

    with pytest.raises(recovery_error):
        recover(path)

    assert path.read_bytes() == original
    assert list(tmp_path.glob("*.fragment")) == []


def test_pae_011_pretruncate_quarantine_fsync_failure_preserves_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recover = getattr(evaluation_module, "recover_torn_history", None)
    assert callable(recover)
    recovery_error = getattr(evaluation_module, "EvaluationHistoryRecoveryError", None)
    assert isinstance(recovery_error, type)
    path = tmp_path / "history.jsonl"
    first = _run(run_id="r1", case_id="a")
    original = (first.to_json() + "\npartial").encode()
    path.write_bytes(original)
    real_fsync = os.fsync
    calls = 0

    def fail_first_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected quarantine fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_first_fsync)

    with pytest.raises(recovery_error):
        recover(path)

    assert path.read_bytes() == original


def test_pae_011_posttruncate_history_fsync_failure_is_ambiguous_and_blocks_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recover = getattr(evaluation_module, "recover_torn_history", None)
    assert callable(recover)
    ambiguous_error = getattr(
        evaluation_module,
        "EvaluationHistoryRecoveryAmbiguousError",
        None,
    )
    assert isinstance(ambiguous_error, type)
    path = tmp_path / "history.jsonl"
    first = _run(run_id="r1", case_id="a")
    path.write_bytes((first.to_json() + "\npartial").encode())
    real_fsync = os.fsync
    calls = 0

    def fail_history_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 5:
            raise OSError("injected history fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_history_fsync)

    with pytest.raises(ambiguous_error):
        recover(path)

    monkeypatch.setattr(os, "fsync", real_fsync)
    with pytest.raises(ambiguous_error):
        JsonlEvaluationStore(path).append(_run(run_id="r2", case_id="b"))


def test_pae_011_append_is_exactly_one_compact_json_object_plus_lf(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    run = _run(run_id="r1", case_id="a")

    JsonlEvaluationStore(path).append(run)

    raw = path.read_bytes()
    assert raw == run.to_json().encode() + b"\n"
    assert json.loads(raw) == run.to_dict()
