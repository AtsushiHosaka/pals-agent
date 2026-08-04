from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

import pals_agent.evaluation as evaluation_module
from pals_agent.cli import main
from pals_agent.evaluation import (
    EVALUATION_STAGES,
    EvaluationMetric,
    EvaluationRun,
    EvaluationStageResult,
    JsonlEvaluationStore,
)


def _run(run_id: str) -> EvaluationRun:
    return EvaluationRun(
        suite_revision="migration-suite-v1",
        run_id=run_id,
        case_id=f"case-{run_id}",
        model="generation-model",
        stages=tuple(
            EvaluationStageResult(
                stage=stage,
                status="passed",
                metrics=(
                    EvaluationMetric(
                        name="deterministic_ok",
                        value=True,
                        status="evaluated",
                        source="fixture",
                    ),
                ),
            )
            for stage in EVALUATION_STAGES
        ),
        created_at="2026-07-14T00:00:00+09:00",
    )


def _legacy_five_line_history(path: Path) -> tuple[bytes, list[dict[str, Any]]]:
    records = [_run(f"run-{index}").to_dict() for index in range(1, 6)]
    metrics = records[4]["stages"]
    for index, stage in enumerate(metrics[:4], start=1):
        stage["metrics"][0] = {
            "name": f"semantic-{index}",
            "value": 0.75,
            "status": "evaluated",
            "source": "legacy-judge",
            "kind": "semantic",
            "comment": f"legacy comment {index}",
        }
    source = b"".join(
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
    path.write_bytes(source)
    return source, records


def test_pae_018_explicit_digest_migration_repairs_only_semantic_comments(
    tmp_path: Path,
) -> None:
    migrate = getattr(evaluation_module, "migrate_evaluation_history", None)
    assert callable(migrate)
    path = tmp_path / "history.jsonl"
    source, original_records = _legacy_five_line_history(path)
    source_digest = hashlib.sha256(source).hexdigest()

    with pytest.raises(ValueError, match="semantic metric comments must be None"):
        JsonlEvaluationStore(path).load_history()
    assert path.read_bytes() == source

    report = migrate(
        path=path,
        migration="semantic-comments-v2",
        expected_sha256=source_digest,
    )

    backup = tmp_path / f"history.jsonl.pre-semantic-comments-v2.{source_digest}.backup"
    assert backup.read_bytes() == source
    assert backup.stat().st_mode & 0o777 == 0o600
    migrated_records = [json.loads(line) for line in path.read_text().splitlines()]
    expected_records = json.loads(json.dumps(original_records))
    changed = 0
    for stage in expected_records[4]["stages"][:4]:
        stage["metrics"][0]["comment"] = None
        changed += 1
    assert migrated_records == expected_records
    assert changed == 4
    assert len(JsonlEvaluationStore(path).load_history()) == 5
    assert report == {
        "migration": "semantic-comments-v2",
        "record_count": 5,
        "change_count": 4,
        "source_sha256": source_digest,
        "result_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "backup_path": str(backup),
    }


def test_pae_018_wrong_digest_is_non_mutating_and_creates_no_backup(
    tmp_path: Path,
) -> None:
    migrate = getattr(evaluation_module, "migrate_evaluation_history", None)
    migration_error = getattr(evaluation_module, "EvaluationHistoryMigrationError", None)
    assert callable(migrate)
    assert isinstance(migration_error, type)
    path = tmp_path / "history.jsonl"
    source, _records = _legacy_five_line_history(path)

    with pytest.raises(migration_error):
        migrate(
            path=path,
            migration="semantic-comments-v2",
            expected_sha256="0" * 64,
        )

    assert path.read_bytes() == source
    assert list(tmp_path.glob("*.backup")) == []
    assert list(tmp_path.glob("*.migration-*-ambiguous")) == []


def test_pae_018_cli_requires_explicit_migration_and_prints_audit_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "history.jsonl"
    source, _records = _legacy_five_line_history(path)
    digest = hashlib.sha256(source).hexdigest()

    exit_code = main(
        [
            "evaluation-history-migrate",
            "--migration",
            "semantic-comments-v2",
            "--history",
            str(path),
            "--expected-sha256",
            digest,
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["migration"] == "semantic-comments-v2"
    assert output["record_count"] == 5
    assert output["change_count"] == 4
    assert "legacy comment" not in json.dumps(output)
    assert len(JsonlEvaluationStore(path).load_history()) == 5


def test_pae_018_fence_creation_failure_is_non_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "history.jsonl"
    source, _records = _legacy_five_line_history(path)
    digest = hashlib.sha256(source).hexdigest()
    real_write = evaluation_module._write_durable_create_only

    def fail_fence(target: Path, payload: bytes) -> None:
        if target.name.endswith(".migration-semantic-comments-v2-ambiguous"):
            raise OSError("injected migration fence failure")
        real_write(target, payload)

    monkeypatch.setattr(evaluation_module, "_write_durable_create_only", fail_fence)

    with pytest.raises(evaluation_module.EvaluationHistoryMigrationError) as raised:
        evaluation_module.migrate_evaluation_history(
            path=path,
            migration="semantic-comments-v2",
            expected_sha256=digest,
        )

    assert type(raised.value) is evaluation_module.EvaluationHistoryMigrationError
    assert path.read_bytes() == source
    assert not evaluation_module._migration_fence(path).exists()


def test_pae_018_backup_creation_failure_is_non_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "history.jsonl"
    source, _records = _legacy_five_line_history(path)
    digest = hashlib.sha256(source).hexdigest()

    def fail_backup(target: Path, payload: bytes) -> None:
        _ = payload
        if target.name.endswith(".backup"):
            raise OSError("injected migration backup failure")
        raise AssertionError(f"unexpected durable create: {target}")

    monkeypatch.setattr(evaluation_module, "_write_durable_create_only", fail_backup)

    with pytest.raises(evaluation_module.EvaluationHistoryMigrationError):
        evaluation_module.migrate_evaluation_history(
            path=path,
            migration="semantic-comments-v2",
            expected_sha256=digest,
        )

    assert path.read_bytes() == source
    assert list(tmp_path.glob("*.backup")) == []
    assert not evaluation_module._migration_fence(path).exists()


def test_pae_018_temp_file_fsync_failure_is_non_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "history.jsonl"
    source, _records = _legacy_five_line_history(path)
    digest = hashlib.sha256(source).hexdigest()
    real_open = os.open
    real_fsync = os.fsync
    opened: dict[int, Path] = {}

    def tracked_open(target: Any, flags: int, mode: int = 0o777) -> int:
        descriptor = real_open(target, flags, mode)
        opened[descriptor] = Path(target)
        return descriptor

    def fail_temp_fsync(descriptor: int) -> None:
        target = opened.get(descriptor)
        if target is not None and ".migration-" in target.name and target.suffix == ".tmp":
            raise OSError("injected migration temp fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "fsync", fail_temp_fsync)

    with pytest.raises(evaluation_module.EvaluationHistoryMigrationError) as raised:
        evaluation_module.migrate_evaluation_history(
            path=path,
            migration="semantic-comments-v2",
            expected_sha256=digest,
        )

    assert type(raised.value) is evaluation_module.EvaluationHistoryMigrationError
    assert path.read_bytes() == source
    assert not evaluation_module._migration_fence(path).exists()
    assert list(tmp_path.glob(".*.migration-*.tmp")) == []


def test_pae_018_replace_failure_is_ambiguous_and_leaves_blocking_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "history.jsonl"
    source, _records = _legacy_five_line_history(path)
    digest = hashlib.sha256(source).hexdigest()

    def fail_replace(source_path: Path, target_path: Path) -> None:
        _ = (source_path, target_path)
        raise OSError("injected atomic replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(evaluation_module.EvaluationHistoryMigrationAmbiguousError):
        evaluation_module.migrate_evaluation_history(
            path=path,
            migration="semantic-comments-v2",
            expected_sha256=digest,
        )

    assert path.read_bytes() == source
    assert evaluation_module._migration_fence(path).exists()
    with pytest.raises(evaluation_module.EvaluationHistoryMigrationAmbiguousError):
        JsonlEvaluationStore(path).load_history()


def test_pae_018_post_replace_directory_fsync_failure_leaves_blocking_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "history.jsonl"
    source, _records = _legacy_five_line_history(path)
    digest = hashlib.sha256(source).hexdigest()
    real_directory_fsync = evaluation_module._fsync_directory
    calls = 0

    def fail_post_replace(target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected post-replace directory fsync failure")
        real_directory_fsync(target)

    monkeypatch.setattr(evaluation_module, "_fsync_directory", fail_post_replace)

    with pytest.raises(evaluation_module.EvaluationHistoryMigrationAmbiguousError):
        evaluation_module.migrate_evaluation_history(
            path=path,
            migration="semantic-comments-v2",
            expected_sha256=digest,
        )

    assert path.read_bytes() != source
    assert evaluation_module._migration_fence(path).exists()
    with pytest.raises(evaluation_module.EvaluationHistoryMigrationAmbiguousError):
        JsonlEvaluationStore(path).load_history()


def test_pae_018_fence_cleanup_fsync_failure_restores_blocking_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "history.jsonl"
    source, _records = _legacy_five_line_history(path)
    digest = hashlib.sha256(source).hexdigest()
    real_directory_fsync = evaluation_module._fsync_directory
    calls = 0

    def fail_cleanup_and_restore(target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls >= 4:
            raise OSError("injected fence cleanup directory fsync failure")
        real_directory_fsync(target)

    monkeypatch.setattr(
        evaluation_module,
        "_fsync_directory",
        fail_cleanup_and_restore,
    )

    with pytest.raises(evaluation_module.EvaluationHistoryMigrationAmbiguousError):
        evaluation_module.migrate_evaluation_history(
            path=path,
            migration="semantic-comments-v2",
            expected_sha256=digest,
        )

    fence = evaluation_module._migration_fence(path)
    assert fence.exists()
    monkeypatch.setattr(evaluation_module, "_fsync_directory", real_directory_fsync)
    with pytest.raises(evaluation_module.EvaluationHistoryMigrationAmbiguousError):
        JsonlEvaluationStore(path).load_history()
