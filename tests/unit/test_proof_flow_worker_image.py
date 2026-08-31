from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
import rfc8785

from pals_agent.proof_flow_image import (
    CommandResult,
    ContainerElementTreeProperty,
    WorkerImageBuildError,
    build_worker_image,
    probe_base_image_elementtree,
)
from pals_agent.proof_flow_seed import SeedBuildArtifact


class _Docker:
    def __init__(
        self,
        *,
        labels: dict[str, str],
        runtime: dict[str, str],
        build_returncode: int = 0,
        image_remove_returncode: int = 0,
        environment: list[str] | None = None,
    ) -> None:
        self._labels = labels
        self._runtime = runtime
        self._build_returncode = build_returncode
        self._image_remove_returncode = image_remove_returncode
        self._environment = environment or ["PYTHONDONTWRITEBYTECODE=1"]
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: tuple[str, ...], *, cwd: Path) -> CommandResult:
        del cwd
        self.commands.append(command)
        if command[:2] == ("docker", "build"):
            return CommandResult(
                returncode=self._build_returncode,
                stdout="built\n" if self._build_returncode == 0 else "",
                stderr="" if self._build_returncode == 0 else "failed",
            )
        if command[:3] == ("docker", "image", "inspect"):
            return CommandResult(
                returncode=0,
                stdout=json.dumps(
                    [{"Config": {"Env": self._environment, "Labels": self._labels}}]
                ),
                stderr="",
            )
        if command[:3] == ("docker", "image", "tag"):
            return CommandResult(returncode=0, stdout="", stderr="")
        if command[:3] == ("docker", "image", "rm"):
            return CommandResult(
                returncode=self._image_remove_returncode,
                stdout="" if self._image_remove_returncode else "removed\n",
                stderr="failed" if self._image_remove_returncode else "",
            )
        if command[:3] == ("docker", "run", "--rm"):
            return CommandResult(
                returncode=0,
                stdout=json.dumps(self._runtime),
                stderr="",
            )
        raise AssertionError(command)


def test_probe_base_image_reads_the_container_property_not_the_host(tmp_path: Path) -> None:
    expected = ContainerElementTreeProperty(
        source_path="/usr/local/lib/python3.12/xml/etree/ElementTree.py",
        source_sha256="a" * 64,
    )

    class _Probe:
        def run(self, command: tuple[str, ...], *, cwd: Path) -> CommandResult:
            assert cwd == tmp_path
            assert command[:7] == (
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "python",
                "python:3.12.13-slim",
                "-c",
            )
            return CommandResult(
                returncode=0,
                stdout=json.dumps(
                    {
                        "path": expected.source_path,
                        "sha256": expected.source_sha256,
                    }
                ),
                stderr="",
            )

    assert probe_base_image_elementtree(_Probe(), cwd=tmp_path) == expected


def test_build_worker_image_passes_verified_labels_and_checks_final_image(
    tmp_path: Path,
) -> None:
    context = tmp_path / "agent"
    property = ContainerElementTreeProperty(
        source_path="/usr/local/lib/python3.12/xml/etree/ElementTree.py",
        source_sha256="a" * 64,
    )
    artifact, labels = _artifact(context, property)
    docker = _Docker(
        labels=labels,
        runtime={
            "elementtree_source_path": property.source_path,
            "elementtree_source_sha256": property.source_sha256,
            "seed_file_sha256": hashlib.sha256(artifact.seed_file.read_bytes()).hexdigest(),
        },
    )

    build_worker_image(
        docker,
        artifact=artifact,
        context=context,
        image_tag="pals-agent-worker:test",
        canonicalizer_property=property,
    )

    temporary_tag = docker.commands[0][3]
    assert re.fullmatch(r"pals-pfi-verify-[0-9a-f]{24}", temporary_tag)
    assert docker.commands[0] == (
        "docker",
        "build",
        "-t",
        temporary_tag,
        "--build-arg",
        "PALS_PFI_BUILD_PROVENANCE_V1="
        + labels["io.pals.draft-retrieval-provenance.v1"],
        "--build-arg",
        "PALS_PFI_BUILD_PROVENANCE_SHA256="
        + labels["io.pals.draft-retrieval-provenance.sha256"],
        ".",
    )
    assert docker.commands[1] == ("docker", "image", "inspect", temporary_tag)
    assert docker.commands[2][:7] == (
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "python",
        temporary_tag,
        "-c",
    )
    assert docker.commands[3] == (
        "docker",
        "image",
        "tag",
        temporary_tag,
        "pals-agent-worker:test",
    )
    assert docker.commands[4] == ("docker", "image", "rm", temporary_tag)
    assert not artifact.root.exists()


def test_build_worker_image_rejects_provenance_in_final_image_environment(
    tmp_path: Path,
) -> None:
    context = tmp_path / "agent"
    property = ContainerElementTreeProperty(
        source_path="/usr/local/lib/python3.12/xml/etree/ElementTree.py",
        source_sha256="a" * 64,
    )
    artifact, labels = _artifact(context, property)
    docker = _Docker(
        labels=labels,
        runtime={},
        environment=[
            "PYTHONDONTWRITEBYTECODE=1",
            "PALS_PFI_BUILD_PROVENANCE_V1="
            + labels["io.pals.draft-retrieval-provenance.v1"],
        ],
    )

    with pytest.raises(WorkerImageBuildError, match="must not remain in the environment"):
        build_worker_image(
            docker,
            artifact=artifact,
            context=context,
            image_tag="pals-agent-worker:release",
            canonicalizer_property=property,
        )

    assert not any(command[:3] == ("docker", "image", "tag") for command in docker.commands)
    assert any(command[:3] == ("docker", "image", "rm") for command in docker.commands)
    assert not artifact.root.exists()


@pytest.mark.parametrize(
    "mutation",
    (
        "provenance_digest",
        "provenance_elementtree",
        "manifest",
        "seed",
        "fingerprint",
        "c14n_v3_fingerprint",
    ),
)
def test_build_worker_image_rejects_any_seed_or_provenance_mismatch(
    tmp_path: Path,
    mutation: str,
) -> None:
    context = tmp_path / "agent"
    property = ContainerElementTreeProperty(
        source_path="/usr/local/lib/python3.12/xml/etree/ElementTree.py",
        source_sha256="a" * 64,
    )
    artifact, labels = _artifact(context, property)
    if mutation == "provenance_digest":
        labels["io.pals.draft-retrieval-provenance.sha256"] = "0" * 64
        artifact.oci_labels_file.write_bytes(rfc8785.dumps(labels))
    elif mutation == "provenance_elementtree":
        provenance = json.loads(artifact.build_provenance_file.read_bytes())
        provenance["elementtree_source_sha256"] = "0" * 64
        provenance_bytes = rfc8785.dumps(provenance)
        artifact.build_provenance_file.write_bytes(provenance_bytes)
        labels["io.pals.draft-retrieval-provenance.v1"] = (
            base64.urlsafe_b64encode(provenance_bytes).rstrip(b"=").decode("ascii")
        )
        labels["io.pals.draft-retrieval-provenance.sha256"] = hashlib.sha256(
            provenance_bytes
        ).hexdigest()
        artifact.oci_labels_file.write_bytes(rfc8785.dumps(labels))
    elif mutation == "manifest":
        artifact.seed_manifest_file.write_bytes(rfc8785.dumps([{"id": "wrong"}]))
    elif mutation == "seed":
        artifact.seed_file.write_bytes(artifact.seed_file.read_bytes() + b"\n")
    elif mutation == "fingerprint":
        fingerprint = json.loads(artifact.fingerprint_file.read_bytes())
        del fingerprint["revision"]
        fingerprint_bytes = rfc8785.dumps(fingerprint)
        artifact.fingerprint_file.write_bytes(fingerprint_bytes)
        seed = json.loads(artifact.seed_file.read_bytes())
        seed["fingerprint"] = fingerprint
        artifact.seed_file.write_bytes(rfc8785.dumps(seed))
    elif mutation == "c14n_v3_fingerprint":
        fingerprint = json.loads(artifact.fingerprint_file.read_bytes())
        fingerprint["canonicalizer_version"] = "openmath-cdbase-alpha-c14n-v3"
        fingerprint_bytes = rfc8785.dumps(fingerprint)
        artifact.fingerprint_file.write_bytes(fingerprint_bytes)
        seed = json.loads(artifact.seed_file.read_bytes())
        seed["fingerprint"] = fingerprint
        artifact.seed_file.write_bytes(rfc8785.dumps(seed))
        provenance = json.loads(artifact.build_provenance_file.read_bytes())
        provenance["canonicalizer_version"] = "openmath-cdbase-alpha-c14n-v3"
        provenance_bytes = rfc8785.dumps(provenance)
        artifact.build_provenance_file.write_bytes(provenance_bytes)
        labels["io.pals.draft-retrieval-provenance.v1"] = (
            base64.urlsafe_b64encode(provenance_bytes).rstrip(b"=").decode("ascii")
        )
        labels["io.pals.draft-retrieval-provenance.sha256"] = hashlib.sha256(
            provenance_bytes
        ).hexdigest()
        artifact.oci_labels_file.write_bytes(rfc8785.dumps(labels))
    else:
        raise AssertionError(mutation)

    with pytest.raises(WorkerImageBuildError):
        build_worker_image(
            _Docker(labels=labels, runtime={}),
            artifact=artifact,
            context=context,
            image_tag="pals-agent-worker:test",
            canonicalizer_property=property,
        )

    assert not artifact.root.exists()


def test_failed_worker_image_build_removes_its_generated_seed(tmp_path: Path) -> None:
    context = tmp_path / "agent"
    property = ContainerElementTreeProperty(
        source_path="/usr/local/lib/python3.12/xml/etree/ElementTree.py",
        source_sha256="a" * 64,
    )
    artifact, labels = _artifact(context, property)

    with pytest.raises(WorkerImageBuildError, match="worker image build failed"):
        build_worker_image(
            _Docker(labels=labels, runtime={}, build_returncode=1),
            artifact=artifact,
            context=context,
            image_tag="pals-agent-worker:test",
            canonicalizer_property=property,
        )

    assert not artifact.root.exists()


def test_failed_final_image_check_never_publishes_the_requested_tag(tmp_path: Path) -> None:
    context = tmp_path / "agent"
    property = ContainerElementTreeProperty(
        source_path="/usr/local/lib/python3.12/xml/etree/ElementTree.py",
        source_sha256="a" * 64,
    )
    artifact, labels = _artifact(context, property)
    docker = _Docker(
        labels=labels,
        runtime={
            "elementtree_source_path": property.source_path,
            "elementtree_source_sha256": property.source_sha256,
            "seed_file_sha256": "0" * 64,
        },
    )

    with pytest.raises(WorkerImageBuildError, match="contents do not match"):
        build_worker_image(
            docker,
            artifact=artifact,
            context=context,
            image_tag="pals-agent-worker:release",
            canonicalizer_property=property,
        )

    assert not any(command[:3] == ("docker", "image", "tag") for command in docker.commands)
    assert any(command[:3] == ("docker", "image", "rm") for command in docker.commands)
    assert not artifact.root.exists()


def test_temporary_image_cleanup_failure_still_removes_seed_artifact(tmp_path: Path) -> None:
    context = tmp_path / "agent"
    property = ContainerElementTreeProperty(
        source_path="/usr/local/lib/python3.12/xml/etree/ElementTree.py",
        source_sha256="a" * 64,
    )
    artifact, labels = _artifact(context, property)
    docker = _Docker(
        labels=labels,
        runtime={
            "elementtree_source_path": property.source_path,
            "elementtree_source_sha256": property.source_sha256,
            "seed_file_sha256": hashlib.sha256(artifact.seed_file.read_bytes()).hexdigest(),
        },
        image_remove_returncode=1,
    )

    with pytest.raises(WorkerImageBuildError, match="temporary cleanup failed"):
        build_worker_image(
            docker,
            artifact=artifact,
            context=context,
            image_tag="pals-agent-worker:release",
            canonicalizer_property=property,
        )

    assert not artifact.root.exists()


def _artifact(
    context: Path,
    property: ContainerElementTreeProperty,
) -> tuple[SeedBuildArtifact, dict[str, str]]:
    root = context / "build/proof-flow-index"
    seed_file = root / "rootfs/opt/pals/draft-seed.json"
    metadata = root / "metadata"
    seed_file.parent.mkdir(parents=True)
    metadata.mkdir(parents=True)
    fingerprint: dict[str, Any] = {
        "provider": "test",
        "model": "test",
        "endpoint": "https://embedding.invalid/v1",
        "deployment": "test",
        "revision": "test",
        "dimension": 2,
        "canonicalizer_version": "openmath-cdbase-alpha-c14n-v4",
    }
    seed_bytes = rfc8785.dumps(
        {
            "schema_version": "pals.draft-catalog-seed.v1",
            "fingerprint": fingerprint,
            "rows": [],
        }
    )
    manifest_bytes = rfc8785.dumps([])
    provenance_bytes = rfc8785.dumps(
        {
            "canonicalizer_version": "openmath-cdbase-alpha-c14n-v4",
            "elementtree_source_path": property.source_path,
            "elementtree_source_sha256": property.source_sha256,
            "property_id": "PFI-BP-001",
            "python_version": "3.12.13",
            "schema_version": "pals.draft-retrieval-build-provenance.v1",
            "seed_count": 0,
            "seed_file_sha256": hashlib.sha256(seed_bytes).hexdigest(),
            "seed_manifest_sha256": "sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
            "seed_path": "/opt/pals/draft-seed.json",
            "source_commit": "1" * 40,
        }
    )
    labels = {
        "io.pals.draft-retrieval-provenance.v1": base64.urlsafe_b64encode(
            provenance_bytes
        )
        .rstrip(b"=")
        .decode("ascii"),
        "io.pals.draft-retrieval-provenance.sha256": hashlib.sha256(
            provenance_bytes
        ).hexdigest(),
    }
    seed_manifest = metadata / "seed-manifest.json"
    fingerprint_file = metadata / "fingerprint.json"
    provenance_file = metadata / "build-provenance.json"
    labels_file = metadata / "oci-labels.json"
    seed_file.write_bytes(seed_bytes)
    seed_manifest.write_bytes(manifest_bytes)
    fingerprint_file.write_bytes(rfc8785.dumps(fingerprint))
    provenance_file.write_bytes(provenance_bytes)
    labels_file.write_bytes(rfc8785.dumps(labels))
    return (
        SeedBuildArtifact(
            root=root,
            seed_file=seed_file,
            seed_manifest_file=seed_manifest,
            fingerprint_file=fingerprint_file,
            build_provenance_file=provenance_file,
            oci_labels_file=labels_file,
            seed_manifest_sha256="sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
            seed_count=0,
        ),
        labels,
    )
