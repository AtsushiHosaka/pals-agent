from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from pals_agent import artifacts
from pals_agent.artifacts import FileArtifactStore, S3ArtifactStore


def _checkpoint() -> dict[str, object]:
    return {
        "checkpoint_schema_version": 1,
        "run_id": "durable-run",
        "attempt": {"attempt": 1, "checkpoint_status": "published"},
    }


def test_pae_016_local_checkpoint_is_0600_and_fsyncs_cleanup_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Path] = []
    real_fsync_directory = artifacts._fsync_directory

    def recording_fsync_directory(path: Path) -> None:
        calls.append(path)
        real_fsync_directory(path)

    monkeypatch.setattr(artifacts, "_fsync_directory", recording_fsync_directory)
    store = FileArtifactStore(tmp_path)

    store.save_checkpoint(run_id="durable-run", attempt=1, metadata=_checkpoint())

    checkpoint = tmp_path / "durable-run" / "attempts" / "0001.json"
    assert stat.S_IMODE(checkpoint.stat().st_mode) == 0o600
    assert calls == [checkpoint.parent, checkpoint.parent]
    assert list(checkpoint.parent.glob(".*.tmp")) == []


def test_pae_016_directory_fsync_failure_is_ambiguous_and_still_fsyncs_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def failing_first_directory_fsync(path: Path) -> None:
        nonlocal calls
        _ = path
        calls += 1
        if calls == 1:
            raise OSError("directory fsync failed")

    monkeypatch.setattr(
        artifacts,
        "_fsync_directory",
        failing_first_directory_fsync,
    )
    store = FileArtifactStore(tmp_path)

    with pytest.raises(OSError, match="directory fsync failed"):
        store.save_checkpoint(
            run_id="durable-run",
            attempt=1,
            metadata=_checkpoint(),
        )

    assert calls == 2
    assert list((tmp_path / "durable-run" / "attempts").glob(".*.tmp")) == []


def test_pae_016_local_aggregate_is_create_only_and_durable(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path)
    original = {"termination_reason": "verified"}

    store.save(run_id="aggregate", lean_code="example : True := by trivial", metadata=original)

    with pytest.raises(FileExistsError):
        store.save(
            run_id="aggregate",
            lean_code="example : False := by sorry",
            metadata={"termination_reason": "fake"},
        )
    assert json.loads((tmp_path / "aggregate" / "result.json").read_text()) == original


class RecordingS3Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def put_object(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


def test_pae_016_s3_aggregate_uses_create_only_writes() -> None:
    client = RecordingS3Client()
    store = S3ArtifactStore(client=client, bucket="proof-artifacts")

    store.save(run_id="aggregate", lean_code="code", metadata={"ok": True})

    assert len(client.calls) == 2
    assert all(call["IfNoneMatch"] == "*" for call in client.calls)
