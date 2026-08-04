from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import rfc8785

from pals_agent.proof_flow_seed import CanonicalizerChildProperty as ContainerElementTreeProperty
from pals_agent.proof_flow_seed import SeedBuildArtifact

__all__ = [
    "CommandResult",
    "ContainerElementTreeProperty",
    "DockerRunner",
    "SubprocessDocker",
    "WorkerImageBuildError",
    "build_worker_image",
    "probe_base_image_elementtree",
]

_BASE_IMAGE = "python:3.12.13-slim"
_BUILD_ROOT = Path("build/proof-flow-index")
_SEED_RELATIVE_PATH = Path("rootfs/opt/pals/draft-seed.json")
_LABELS_RELATIVE_PATH = Path("metadata/oci-labels.json")
_PROVENANCE_LABEL = "io.pals.draft-retrieval-provenance.v1"
_PROVENANCE_DIGEST_LABEL = "io.pals.draft-retrieval-provenance.sha256"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_IMAGE_TAG = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/:@-]{0,254}$")
_PROVENANCE_BUILD_ARGUMENTS = frozenset(
    ("PALS_PFI_BUILD_PROVENANCE_V1", "PALS_PFI_BUILD_PROVENANCE_SHA256")
)


class WorkerImageBuildError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class DockerRunner(Protocol):
    def run(self, command: tuple[str, ...], *, cwd: Path) -> CommandResult: ...


class SubprocessDocker:
    def run(self, command: tuple[str, ...], *, cwd: Path) -> CommandResult:
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return CommandResult(returncode=127, stdout="", stderr="")
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def probe_base_image_elementtree(
    docker: DockerRunner,
    *,
    cwd: Path,
) -> ContainerElementTreeProperty:
    script = (
        "import hashlib,json,stat,sysconfig;from pathlib import Path;"
        "source=Path(sysconfig.get_path('stdlib'))/'xml/etree/ElementTree.py';"
        "path=source.resolve(strict=True);mode=path.lstat().st_mode;"
        "valid=not source.is_symlink() and not path.is_symlink() and stat.S_ISREG(mode);"
        "valid or __import__('sys').exit(1);"
        "print(json.dumps({'path':path.as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()},"
        "sort_keys=True,separators=(',',':')))"
    )
    result = docker.run(
        ("docker", "run", "--rm", "--entrypoint", "python", _BASE_IMAGE, "-c", script),
        cwd=cwd,
    )
    _require_success(result, "container canonicalizer preflight failed")
    payload = _parse_json_object(result.stdout, "container canonicalizer preflight is invalid")
    if set(payload) != {"path", "sha256"}:
        raise WorkerImageBuildError("container canonicalizer preflight shape is invalid")
    if not isinstance(payload["path"], str) or not isinstance(payload["sha256"], str):
        raise WorkerImageBuildError("container canonicalizer preflight values are invalid")
    return ContainerElementTreeProperty(
        source_path=payload["path"],
        source_sha256=payload["sha256"],
    )


def build_worker_image(
    docker: DockerRunner,
    *,
    artifact: SeedBuildArtifact,
    context: Path,
    image_tag: str,
    canonicalizer_property: ContainerElementTreeProperty,
) -> None:
    if not _IMAGE_TAG.fullmatch(image_tag):
        raise WorkerImageBuildError("worker image tag is invalid")
    resolved_context = _validate_context(context)
    temporary_image_tag = f"pals-pfi-verify-{secrets.token_hex(12)}"
    temporary_image_created = False
    try:
        labels = _read_oci_labels(
            artifact,
            context=resolved_context,
            canonicalizer_property=canonicalizer_property,
        )
        expected_seed_sha256 = hashlib.sha256(artifact.seed_file.read_bytes()).hexdigest()
        build = docker.run(
            (
                "docker",
                "build",
                "-t",
                temporary_image_tag,
                "--build-arg",
                f"PALS_PFI_BUILD_PROVENANCE_V1={labels[_PROVENANCE_LABEL]}",
                "--build-arg",
                "PALS_PFI_BUILD_PROVENANCE_SHA256="
                + labels[_PROVENANCE_DIGEST_LABEL],
                ".",
            ),
            cwd=resolved_context,
        )
        _require_success(build, "worker image build failed")
        temporary_image_created = True

        inspect = docker.run(
            ("docker", "image", "inspect", temporary_image_tag),
            cwd=resolved_context,
        )
        _require_success(inspect, "worker image inspection failed")
        inspected = _parse_json_list(inspect.stdout, "worker image inspection is invalid")
        if len(inspected) != 1 or not isinstance(inspected[0], dict):
            raise WorkerImageBuildError("worker image inspection shape is invalid")
        config = inspected[0].get("Config")
        image_labels = config.get("Labels") if isinstance(config, dict) else None
        if not isinstance(image_labels, dict) or any(
            not isinstance(value, str) for value in image_labels.values()
        ):
            raise WorkerImageBuildError("worker image labels are invalid")
        if {
            key: image_labels.get(key)
            for key in (_PROVENANCE_LABEL, _PROVENANCE_DIGEST_LABEL)
        } != labels:
            raise WorkerImageBuildError("worker image provenance labels do not match the seed")
        image_environment = config.get("Env") if isinstance(config, dict) else None
        if not isinstance(image_environment, list) or any(
            not isinstance(value, str) for value in image_environment
        ):
            raise WorkerImageBuildError("worker image environment is invalid")
        if any(
            value.partition("=")[0] in _PROVENANCE_BUILD_ARGUMENTS
            for value in image_environment
        ):
            raise WorkerImageBuildError(
                "worker image provenance must not remain in the environment"
            )

        runtime = docker.run(
            (
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "python",
                temporary_image_tag,
                "-c",
                _RUNTIME_EVIDENCE_SCRIPT,
            ),
            cwd=resolved_context,
        )
        _require_success(runtime, "worker image runtime evidence failed")
        evidence = _parse_json_object(runtime.stdout, "worker image runtime evidence is invalid")
        expected_evidence = {
            "elementtree_source_path": canonicalizer_property.source_path,
            "elementtree_source_sha256": canonicalizer_property.source_sha256,
            "seed_file_sha256": expected_seed_sha256,
        }
        if evidence != expected_evidence:
            raise WorkerImageBuildError("worker image contents do not match the generated seed")
        tag = docker.run(
            ("docker", "image", "tag", temporary_image_tag, image_tag),
            cwd=resolved_context,
        )
        _require_success(tag, "worker image final tag publication failed")
    finally:
        try:
            if temporary_image_created:
                remove_image = docker.run(
                    ("docker", "image", "rm", temporary_image_tag),
                    cwd=resolved_context,
                )
                _require_success(remove_image, "worker image temporary cleanup failed")
        finally:
            _remove_build_artifact(artifact, context=resolved_context)


_RUNTIME_EVIDENCE_SCRIPT = (
    "import hashlib,json,stat,sysconfig;from pathlib import Path;"
    "source=Path(sysconfig.get_path('stdlib'))/'xml/etree/ElementTree.py';"
    "elementtree=source.resolve(strict=True);mode=elementtree.lstat().st_mode;"
    "valid=not source.is_symlink() and not elementtree.is_symlink() and stat.S_ISREG(mode);"
    "valid or __import__('sys').exit(1);"
    "seed=Path('/opt/pals/draft-seed.json');"
    "print(json.dumps({'elementtree_source_path':str(elementtree),"
    "'elementtree_source_sha256':hashlib.sha256(elementtree.read_bytes()).hexdigest(),"
    "'seed_file_sha256':hashlib.sha256(seed.read_bytes()).hexdigest()},"
    "sort_keys=True,separators=(',',':')))"
)


def _validate_context(context: Path) -> Path:
    try:
        resolved = context.resolve(strict=True)
    except OSError as exc:
        raise WorkerImageBuildError("worker image context is unreadable") from exc
    if context.is_symlink() or not resolved.is_dir():
        raise WorkerImageBuildError("worker image context is invalid")
    return resolved


def _read_oci_labels(
    artifact: SeedBuildArtifact,
    *,
    context: Path,
    canonicalizer_property: ContainerElementTreeProperty,
) -> dict[str, str]:
    expected_root = context / _BUILD_ROOT
    expected_seed = expected_root / _SEED_RELATIVE_PATH
    expected_labels = expected_root / _LABELS_RELATIVE_PATH
    expected_manifest = expected_root / "metadata/seed-manifest.json"
    expected_fingerprint = expected_root / "metadata/fingerprint.json"
    expected_provenance = expected_root / "metadata/build-provenance.json"
    if (
        artifact.root != expected_root
        or artifact.seed_file != expected_seed
        or artifact.oci_labels_file != expected_labels
        or artifact.seed_manifest_file != expected_manifest
        or artifact.fingerprint_file != expected_fingerprint
        or artifact.build_provenance_file != expected_provenance
    ):
        raise WorkerImageBuildError("worker image seed artifact path is invalid")
    for path in (
        artifact.seed_file,
        artifact.seed_manifest_file,
        artifact.fingerprint_file,
        artifact.build_provenance_file,
        artifact.oci_labels_file,
    ):
        if path.is_symlink() or not path.is_file():
            raise WorkerImageBuildError("worker image seed artifact is unreadable")
    seed_bytes = artifact.seed_file.read_bytes()
    seed = _parse_jcs_object(seed_bytes, "worker image seed is invalid")
    if set(seed) != {"schema_version", "fingerprint", "rows"}:
        raise WorkerImageBuildError("worker image seed shape is invalid")
    if seed["schema_version"] != "pals.draft-catalog-seed.v1":
        raise WorkerImageBuildError("worker image seed schema is invalid")
    fingerprint = seed["fingerprint"]
    rows = seed["rows"]
    if not isinstance(fingerprint, dict) or not isinstance(rows, list):
        raise WorkerImageBuildError("worker image seed values are invalid")
    expected_fingerprint_keys = {
        "provider",
        "model",
        "endpoint",
        "deployment",
        "revision",
        "dimension",
        "canonicalizer_version",
    }
    if set(fingerprint) != expected_fingerprint_keys:
        raise WorkerImageBuildError("worker image fingerprint shape is invalid")
    if any(
        not isinstance(fingerprint[key], str) or not fingerprint[key].strip()
        for key in (
            "provider",
            "model",
            "endpoint",
            "deployment",
            "revision",
        )
    ):
        raise WorkerImageBuildError("worker image fingerprint strings are invalid")
    dimension = fingerprint["dimension"]
    if isinstance(dimension, bool) or not isinstance(dimension, int) or not 1 <= dimension <= 4096:
        raise WorkerImageBuildError("worker image fingerprint dimension is invalid")
    if fingerprint["canonicalizer_version"] != "openmath-cdbase-alpha-c14n-v3":
        raise WorkerImageBuildError("worker image fingerprint canonicalizer is invalid")
    projection: list[dict[str, object]] = []
    previous_identifier: bytes | None = None
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "canonical_statement",
            "embedding",
            "id",
            "openmath_xml",
            "proof_strategy",
            "sketch_steps",
        }:
            raise WorkerImageBuildError("worker image seed row is invalid")
        identifier = row["id"]
        if not isinstance(identifier, str) or not identifier:
            raise WorkerImageBuildError("worker image seed identifier is invalid")
        encoded_identifier = identifier.encode("utf-8")
        if previous_identifier is not None and encoded_identifier <= previous_identifier:
            raise WorkerImageBuildError("worker image seed rows are not ordered")
        previous_identifier = encoded_identifier
        projection.append({key: value for key, value in row.items() if key != "embedding"})
    manifest_bytes = artifact.seed_manifest_file.read_bytes()
    manifest = _parse_jcs_value(manifest_bytes, "worker image seed manifest is invalid")
    if manifest != projection or manifest_bytes != rfc8785.dumps(cast(Any, projection)):
        raise WorkerImageBuildError("worker image seed manifest does not match the seed")
    manifest_sha256 = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    if artifact.seed_manifest_sha256 != manifest_sha256:
        raise WorkerImageBuildError("worker image seed manifest digest is invalid")
    fingerprint_bytes = artifact.fingerprint_file.read_bytes()
    if fingerprint_bytes != rfc8785.dumps(fingerprint):
        raise WorkerImageBuildError("worker image fingerprint does not match the seed")

    payload = _parse_json_object(
        artifact.oci_labels_file.read_text(encoding="utf-8"),
        "worker image OCI labels are invalid",
    )
    if set(payload) != {_PROVENANCE_LABEL, _PROVENANCE_DIGEST_LABEL} or any(
        not isinstance(value, str) for value in payload.values()
    ):
        raise WorkerImageBuildError("worker image OCI labels shape is invalid")
    labels = {key: value for key, value in payload.items() if isinstance(value, str)}
    if not labels[_PROVENANCE_LABEL] or not _SHA256.fullmatch(
        labels[_PROVENANCE_DIGEST_LABEL]
    ):
        raise WorkerImageBuildError("worker image OCI labels values are invalid")
    if not _BASE64URL.fullmatch(labels[_PROVENANCE_LABEL]):
        raise WorkerImageBuildError("worker image provenance label encoding is invalid")
    try:
        padded = labels[_PROVENANCE_LABEL] + ("=" * (-len(labels[_PROVENANCE_LABEL]) % 4))
        provenance_bytes = base64.b64decode(padded, altchars=b"-_", validate=True)
    except ValueError as exc:
        raise WorkerImageBuildError("worker image provenance label encoding is invalid") from exc
    if hashlib.sha256(provenance_bytes).hexdigest() != labels[_PROVENANCE_DIGEST_LABEL]:
        raise WorkerImageBuildError("worker image provenance label digest is invalid")
    if provenance_bytes != artifact.build_provenance_file.read_bytes():
        raise WorkerImageBuildError("worker image provenance file does not match its label")
    provenance = _parse_jcs_object(
        provenance_bytes,
        "worker image provenance is invalid",
    )
    expected_provenance_keys = {
        "canonicalizer_version",
        "elementtree_source_path",
        "elementtree_source_sha256",
        "property_id",
        "python_version",
        "schema_version",
        "seed_count",
        "seed_file_sha256",
        "seed_manifest_sha256",
        "seed_path",
        "source_commit",
    }
    if set(provenance) != expected_provenance_keys:
        raise WorkerImageBuildError("worker image provenance shape is invalid")
    expected_values: dict[str, object] = {
        "canonicalizer_version": "openmath-cdbase-alpha-c14n-v3",
        "elementtree_source_path": canonicalizer_property.source_path,
        "elementtree_source_sha256": canonicalizer_property.source_sha256,
        "property_id": "PFI-BP-001",
        "python_version": "3.12.13",
        "schema_version": "pals.draft-retrieval-build-provenance.v1",
        "seed_count": len(rows),
        "seed_file_sha256": hashlib.sha256(seed_bytes).hexdigest(),
        "seed_manifest_sha256": manifest_sha256,
        "seed_path": "/opt/pals/draft-seed.json",
    }
    if any(provenance[key] != value for key, value in expected_values.items()):
        raise WorkerImageBuildError("worker image provenance does not match the seed")
    source_commit = provenance["source_commit"]
    if not isinstance(source_commit, str) or not _SOURCE_COMMIT.fullmatch(source_commit):
        raise WorkerImageBuildError("worker image provenance source commit is invalid")
    return labels


def _parse_jcs_object(raw: bytes, message: str) -> dict[str, object]:
    value = _parse_jcs_value(raw, message)
    if not isinstance(value, dict):
        raise WorkerImageBuildError(message)
    return value


def _parse_jcs_value(raw: bytes, message: str) -> object:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerImageBuildError(message) from exc
    try:
        canonical = rfc8785.dumps(value)
    except (TypeError, ValueError) as exc:
        raise WorkerImageBuildError(message) from exc
    if canonical != raw:
        raise WorkerImageBuildError(message)
    return value


def _remove_build_artifact(artifact: SeedBuildArtifact, *, context: Path) -> None:
    expected_root = context / _BUILD_ROOT
    if artifact.root != expected_root or artifact.root.is_symlink() or not artifact.root.is_dir():
        raise WorkerImageBuildError("worker image seed cleanup target is invalid")
    try:
        shutil.rmtree(artifact.root)
    except OSError as exc:
        raise WorkerImageBuildError("worker image seed cleanup failed") from exc


def _require_success(result: CommandResult, message: str) -> None:
    if result.returncode != 0:
        raise WorkerImageBuildError(message)


def _parse_json_object(raw: str, message: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorkerImageBuildError(message) from exc
    if not isinstance(value, dict):
        raise WorkerImageBuildError(message)
    return value


def _parse_json_list(raw: str, message: str) -> list[object]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorkerImageBuildError(message) from exc
    if not isinstance(value, list):
        raise WorkerImageBuildError(message)
    return value
