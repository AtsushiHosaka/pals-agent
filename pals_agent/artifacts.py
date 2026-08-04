from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pals_agent.models import ProofArtifact

_SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ATTEMPT_CHECKPOINT_SCHEMA_VERSION = 1


class ArtifactPersistenceError(RuntimeError):
    """Raised when a terminal artifact cannot be durably persisted."""

    def __init__(self) -> None:
        super().__init__("pals.artifact_persistence_failed")


class ArtifactStore(Protocol):
    def save(self, *, run_id: str, lean_code: str, metadata: dict[str, Any]) -> ProofArtifact: ...

    def save_checkpoint(
        self,
        *,
        run_id: str,
        attempt: int,
        metadata: dict[str, Any],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class FileArtifactStore:
    root: Path

    def save(self, *, run_id: str, lean_code: str, metadata: dict[str, Any]) -> ProofArtifact:
        safe_run_id = safe_artifact_segment(run_id)
        root = self.root.resolve()
        run_dir = (root / safe_run_id).resolve()
        if not run_dir.is_relative_to(root):
            raise ValueError(f"Artifact run id escapes the artifact root: {run_id}")
        run_dir.mkdir(parents=True, exist_ok=True)
        lean_path = run_dir / "result.lean"
        metadata_path = run_dir / "result.json"
        _write_create_only_file(lean_path, lean_code.encode("utf-8"))
        _write_create_only_file(
            metadata_path,
            json.dumps(
                metadata,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8"),
        )
        _fsync_directory(run_dir)
        return ProofArtifact(
            uri=str(metadata_path),
            lean_uri=str(lean_path),
            metadata={"store": "file", "run_id": safe_run_id},
        )

    def save_checkpoint(
        self,
        *,
        run_id: str,
        attempt: int,
        metadata: dict[str, Any],
    ) -> None:
        safe_run_id = safe_artifact_segment(run_id)
        safe_attempt = _positive_attempt(attempt)
        _validate_checkpoint_metadata(metadata)
        root = self.root.resolve()
        attempts_dir = (root / safe_run_id / "attempts").resolve()
        if not attempts_dir.is_relative_to(root):
            raise ValueError(f"Artifact run id escapes the artifact root: {run_id}")
        attempts_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = attempts_dir / f"{safe_attempt:04d}.json"
        payload = json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")

        descriptor, temporary_name = tempfile.mkstemp(
            dir=attempts_dir,
            prefix=f".{safe_attempt:04d}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary_path, checkpoint_path)
            _fsync_directory(attempts_dir)
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            finally:
                _fsync_directory(attempts_dir)


@dataclass(frozen=True, slots=True)
class S3ArtifactStore:
    client: Any
    bucket: str
    prefix: str = "proof-jobs"

    def save(self, *, run_id: str, lean_code: str, metadata: dict[str, Any]) -> ProofArtifact:
        safe_run_id = safe_artifact_segment(run_id)
        base_key = f"{self.prefix.rstrip('/')}/{safe_run_id}"
        lean_key = f"{base_key}/result.lean"
        metadata_key = f"{base_key}/result.json"
        self.client.put_object(
            Bucket=self.bucket,
            Key=lean_key,
            Body=lean_code.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
            IfNoneMatch="*",
        )
        self.client.put_object(
            Bucket=self.bucket,
            Key=metadata_key,
            Body=json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
            IfNoneMatch="*",
        )
        return ProofArtifact(
            uri=f"s3://{self.bucket}/{metadata_key}",
            lean_uri=f"s3://{self.bucket}/{lean_key}",
            metadata={"store": "s3", "bucket": self.bucket, "run_id": safe_run_id},
        )

    def save_checkpoint(
        self,
        *,
        run_id: str,
        attempt: int,
        metadata: dict[str, Any],
    ) -> None:
        safe_run_id = safe_artifact_segment(run_id)
        safe_attempt = _positive_attempt(attempt)
        _validate_checkpoint_metadata(metadata)
        base_key = f"{self.prefix.rstrip('/')}/{safe_run_id}"
        checkpoint_key = f"{base_key}/attempts/{safe_attempt:04d}.json"
        self.client.put_object(
            Bucket=self.bucket,
            Key=checkpoint_key,
            Body=json.dumps(
                metadata,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
            IfNoneMatch="*",
        )


def safe_artifact_segment(run_id: str) -> str:
    if not _SAFE_RUN_ID_RE.fullmatch(run_id) or run_id in {".", ".."}:
        raise ValueError(f"Unsafe artifact run id: {run_id}")
    if "/" in run_id or "\\" in run_id:
        raise ValueError(f"Artifact run id must be a single path segment: {run_id}")
    return run_id


def _positive_attempt(attempt: int) -> int:
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("Artifact attempt must be a positive integer")
    return attempt


def _validate_checkpoint_metadata(metadata: dict[str, Any]) -> None:
    if metadata.get("checkpoint_schema_version") != ATTEMPT_CHECKPOINT_SCHEMA_VERSION:
        raise ValueError(
            "Attempt checkpoint metadata must use checkpoint_schema_version "
            f"{ATTEMPT_CHECKPOINT_SCHEMA_VERSION}"
        )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_create_only_file(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
