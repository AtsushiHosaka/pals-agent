from __future__ import annotations

import resource
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from pals_agent.lean_verifier import boundary as boundary_module
from pals_agent.lean_verifier.boundary import (
    BoundaryAttestationError,
    RuntimeBoundaryEvidence,
    validate_http_runtime_boundary,
    validate_runtime_boundary,
)

_GIB = 1024 * 1024 * 1024


def _valid_evidence() -> RuntimeBoundaryEvidence:
    return RuntimeBoundaryEvidence(
        effective_uid=65532,
        inherited_capabilities=0,
        permitted_capabilities=0,
        effective_capabilities=0,
        bounding_capabilities=0,
        ambient_capabilities=0,
        no_new_privs=True,
        network_interfaces=("lo",),
        root_read_only=True,
        project_read_only=True,
        scratch_tmpfs_bounded=True,
        socket_tmpfs_bounded=True,
        cpu_cgroup_limited=True,
        memory_cgroup_limited=True,
        pids_cgroup_limited=True,
        nofile_limited=True,
        credential_environment_names=(),
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"effective_uid": 0}, "non-root"),
        ({"inherited_capabilities": 1}, "capabilities"),
        ({"permitted_capabilities": 1}, "capabilities"),
        ({"effective_capabilities": 1}, "capabilities"),
        ({"bounding_capabilities": 1}, "capabilities"),
        ({"ambient_capabilities": 1}, "capabilities"),
        ({"no_new_privs": False}, "no_new_privs"),
        ({"network_interfaces": ("eth0", "lo")}, "network"),
        ({"root_read_only": False}, "root filesystem"),
        ({"project_read_only": False}, "project filesystem"),
        ({"scratch_tmpfs_bounded": False}, "scratch"),
        ({"socket_tmpfs_bounded": False}, "socket"),
        ({"cpu_cgroup_limited": False}, "CPU"),
        ({"memory_cgroup_limited": False}, "memory"),
        ({"pids_cgroup_limited": False}, "PID"),
        ({"nofile_limited": False}, "open-file"),
        ({"credential_environment_names": ("AWS_SECRET_ACCESS_KEY",)}, "credential"),
    ],
)
def test_pae_017_each_missing_boundary_property_fails_startup(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(BoundaryAttestationError, match=message):
        validate_runtime_boundary(
            replace(_valid_evidence(), **cast(Any, changes))
        )


def test_pae_017_complete_boundary_evidence_is_accepted() -> None:
    validate_runtime_boundary(_valid_evidence())


def test_pae_036_http_boundary_requires_private_service_network_not_unix_loopback() -> None:
    evidence = replace(_valid_evidence(), network_interfaces=("eth0", "lo"))

    validate_http_runtime_boundary(evidence)

    with pytest.raises(BoundaryAttestationError, match="service interface"):
        validate_http_runtime_boundary(_valid_evidence())


def test_pae_036_http_boundary_rejects_credential_environment_names() -> None:
    evidence = replace(
        _valid_evidence(),
        network_interfaces=("eth0", "lo"),
        credential_environment_names=("AWS_SECRET_ACCESS_KEY",),
    )

    with pytest.raises(BoundaryAttestationError, match="credential"):
        validate_http_runtime_boundary(evidence)


@pytest.mark.parametrize(
    ("limits", "expected"),
    [
        ((1024, 1024), True),
        ((1025, 1025), False),
        ((resource.RLIM_INFINITY, resource.RLIM_INFINITY), False),
        ((0, 1024), False),
    ],
)
def test_pae_017_outer_nofile_attestation_is_bounded_at_1024(
    monkeypatch: pytest.MonkeyPatch,
    limits: tuple[int, int],
    expected: bool,
) -> None:
    monkeypatch.setattr(
        resource,
        "getrlimit",
        lambda _resource_name: limits,
    )

    assert boundary_module._nofile_limited() is expected


@pytest.mark.parametrize(
    ("cpu_max", "expected"),
    [
        ("200000 100000", True),
        ("200001 100000", False),
        ("max 100000", False),
    ],
)
def test_pae_017_outer_cpu_attestation_is_bounded_at_two_vcpus(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cpu_max: str,
    expected: bool,
) -> None:
    cgroup = tmp_path
    (cgroup / "cpu.max").write_text(cpu_max, encoding="ascii")
    monkeypatch.setattr(boundary_module, "_cgroup_v2_root", lambda: cgroup)

    assert boundary_module._MAX_CPU_COUNT == 2.0
    assert boundary_module._cpu_cgroup_limited() is expected


@pytest.mark.parametrize(
    ("memory_max", "expected"),
    [
        (str(4 * _GIB), True),
        (str(4 * _GIB + 1), False),
        ("max", False),
    ],
)
def test_pae_017_outer_memory_attestation_is_bounded_at_four_gib(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    memory_max: str,
    expected: bool,
) -> None:
    cgroup = tmp_path
    (cgroup / "memory.max").write_text(memory_max, encoding="ascii")
    monkeypatch.setattr(boundary_module, "_cgroup_v2_root", lambda: cgroup)

    assert boundary_module._MAX_MEMORY_BYTES == 4 * _GIB
    assert (
        boundary_module._integer_cgroup_limited(
            "memory.max",
            "memory.limit_in_bytes",
            maximum=boundary_module._MAX_MEMORY_BYTES,
            controllers=("memory",),
        )
        is expected
    )
