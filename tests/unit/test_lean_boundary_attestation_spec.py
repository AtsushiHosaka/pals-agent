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
        pressure_events_readable=True,
        nofile_limited=True,
        credential_environment_names=(),
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"effective_uid": 0}, "non-root"),
        ({"pressure_events_readable": False}, "event counters"),
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
    ("memory_events", "pids_events", "expected"),
    [
        ("oom 1\noom_kill 0\n", "max 0\n", True),
        ("oom 1\noom_kill 0\n", None, False),
        (None, "max 0\n", False),
        ("oom 1\n", "max 0\n", False),
        ("oom_kill 0\n", "max many\n", False),
    ],
)
def test_pressure_event_counters_are_required(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    memory_events: str | None,
    pids_events: str | None,
    expected: bool,
) -> None:
    if memory_events is not None:
        (tmp_path / "memory.events").write_text(memory_events, encoding="ascii")
    if pids_events is not None:
        (tmp_path / "pids.events").write_text(pids_events, encoding="ascii")
    monkeypatch.setattr(boundary_module, "_cgroup_v2_root", lambda: tmp_path)
    assert boundary_module._pressure_events_readable() is expected


def test_pressure_event_counters_need_cgroup_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(boundary_module, "_cgroup_v2_root", lambda: None)
    assert boundary_module._pressure_events_readable() is False


@pytest.mark.parametrize(
    ("memory_max", "expected"),
    [
        (str(8 * _GIB), True),
        (str(8 * _GIB + 1), False),
        ("max", False),
    ],
)
def test_pae_017_outer_memory_attestation_is_bounded_at_eight_gib(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    memory_max: str,
    expected: bool,
) -> None:
    cgroup = tmp_path
    (cgroup / "memory.max").write_text(memory_max, encoding="ascii")
    monkeypatch.setattr(boundary_module, "_cgroup_v2_root", lambda: cgroup)

    assert boundary_module._MAX_MEMORY_BYTES == 8 * _GIB
    assert (
        boundary_module._integer_cgroup_limited(
            "memory.max",
            "memory.limit_in_bytes",
            maximum=boundary_module._MAX_MEMORY_BYTES,
            controllers=("memory",),
        )
        is expected
    )


@pytest.mark.parametrize(
    ("env", "cpu_max", "expected"),
    [
        (None, "400000 100000", False),
        ("2", "200000 100000", True),
        ("2", "400000 100000", False),
        ("4", "400000 100000", True),
        ("4", "400001 100000", False),
    ],
)
def test_cpu_ceiling_follows_the_reviewed_setting_and_defaults_to_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env: str | None, cpu_max: str, expected: bool
) -> None:
    (tmp_path / "cpu.max").write_text(cpu_max, encoding="ascii")
    monkeypatch.setattr(boundary_module, "_cgroup_v2_root", lambda: tmp_path)
    if env is None:
        monkeypatch.delenv("PALS_VERIFIER_CPUS", raising=False)
    else:
        monkeypatch.setenv("PALS_VERIFIER_CPUS", env)
    assert boundary_module._cpu_cgroup_limited() is expected


@pytest.mark.parametrize("value", ["1", "5", "02", "two", "", "2.5", " 4"])
def test_invalid_cpu_setting_is_refused(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("PALS_VERIFIER_CPUS", value)
    with pytest.raises(boundary_module.BoundaryAttestationError):
        boundary_module._max_cpu_count()


@pytest.mark.parametrize(
    ("env", "expected_gib"), [(None, 8), ("8", 8), ("4", 4), ("16", 16), ("24", 24)]
)
def test_memory_ceiling_follows_the_reviewed_setting_and_defaults_to_eight_gib(
    monkeypatch: pytest.MonkeyPatch, env: str | None, expected_gib: int
) -> None:
    if env is None:
        monkeypatch.delenv("PALS_VERIFIER_MEMORY_GIB", raising=False)
    else:
        monkeypatch.setenv("PALS_VERIFIER_MEMORY_GIB", env)
    assert boundary_module._max_memory_bytes() == expected_gib * _GIB


@pytest.mark.parametrize("value", ["0", "3", "25", "08", "eight", "", "8.5"])
def test_invalid_memory_setting_is_refused(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("PALS_VERIFIER_MEMORY_GIB", value)
    with pytest.raises(boundary_module.BoundaryAttestationError):
        boundary_module._max_memory_bytes()


def _stub_boundary_environment(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path, *, cpu_max: str, memory_max: str
) -> None:
    for name, content in (("cpu.max", cpu_max), ("memory.max", memory_max), ("pids.max", "64")):
        (cgroup / name).write_text(content, encoding="ascii")
    monkeypatch.setattr(boundary_module, "_cgroup_v2_root", lambda: cgroup)
    monkeypatch.setattr(boundary_module.os, "geteuid", lambda: 65532)
    monkeypatch.setattr(boundary_module, "_proc_status", lambda: "")
    monkeypatch.setattr(boundary_module, "_hex_status_value", lambda *_: 0)
    monkeypatch.setattr(boundary_module, "_decimal_status_value", lambda *_: 1)
    monkeypatch.setattr(boundary_module, "_network_interfaces", lambda: ("lo",))
    monkeypatch.setattr(boundary_module, "_is_read_only", lambda _path: True)
    monkeypatch.setattr(boundary_module, "_is_bounded_tmpfs", lambda *_a, **_k: True)
    monkeypatch.setattr(boundary_module, "_pressure_events_readable", lambda: True)
    monkeypatch.setattr(boundary_module, "_nofile_limited", lambda: True)
    # A closed environment: the developer's own credentials must not trip the credential check.
    monkeypatch.setattr(boundary_module.os, "environ", {})


def _attest(entry_point: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    if entry_point == "http":
        monkeypatch.setattr(boundary_module, "_network_interfaces", lambda: ("eth0", "lo"))
    if entry_point == "unix":
        return boundary_module.attest_runtime_boundary(
            project_dir=tmp_path,
            scratch_dir=tmp_path,
            socket_dir=tmp_path,
            scratch_max_bytes=1,
            socket_max_bytes=1,
        )
    return boundary_module.attest_http_runtime_boundary(
        project_dir=tmp_path,
        scratch_dir=tmp_path,
        scratch_max_bytes=1,
        allowed_reference_environment_names=frozenset(),
    )


@pytest.mark.parametrize("entry_point", ["unix", "http"])
@pytest.mark.parametrize(
    ("env_cpus", "env_gib", "cpu_max", "memory_max", "accepted"),
    [
        (None, None, "200000 100000", str(8 * _GIB), True),
        (None, None, "400000 100000", str(8 * _GIB), False),
        (None, None, "200000 100000", str(16 * _GIB), False),
        ("4", "16", "400000 100000", str(16 * _GIB), True),
        ("4", "16", "400000 100000", str(16 * _GIB + 1), False),
        ("4", "16", "400001 100000", str(16 * _GIB), False),
    ],
)
def test_attestation_entry_points_honour_the_reviewed_ceilings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    entry_point: str,
    env_cpus: str | None,
    env_gib: str | None,
    cpu_max: str,
    memory_max: str,
    accepted: bool,
) -> None:
    cgroup = tmp_path / "cg"
    cgroup.mkdir()
    _stub_boundary_environment(monkeypatch, cgroup, cpu_max=cpu_max, memory_max=memory_max)
    if env_cpus is not None:
        monkeypatch.setenv("PALS_VERIFIER_CPUS", env_cpus)
    if env_gib is not None:
        monkeypatch.setenv("PALS_VERIFIER_MEMORY_GIB", env_gib)
    if accepted:
        evidence = _attest(entry_point, tmp_path, monkeypatch)
        assert evidence.cpu_cgroup_limited and evidence.memory_cgroup_limited
    else:
        with pytest.raises(BoundaryAttestationError, match="CPU|memory"):
            _attest(entry_point, tmp_path, monkeypatch)


@pytest.mark.parametrize(
    ("env", "quota", "expected"),
    [
        (None, 200000, True),
        (None, 200001, False),
        ("4", 400000, True),
        ("4", 400001, False),
    ],
)
def test_cgroup_v1_cpu_path_honours_the_reviewed_ceiling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env: str | None, quota: int, expected: bool
) -> None:
    (tmp_path / "cpu.cfs_quota_us").write_text(str(quota), encoding="ascii")
    (tmp_path / "cpu.cfs_period_us").write_text("100000", encoding="ascii")
    monkeypatch.setattr(boundary_module, "_cgroup_v2_root", lambda: None)
    monkeypatch.setattr(boundary_module, "_cgroup_v1_controller_root", lambda _names: tmp_path)
    if env is None:
        monkeypatch.delenv("PALS_VERIFIER_CPUS", raising=False)
    else:
        monkeypatch.setenv("PALS_VERIFIER_CPUS", env)
    assert boundary_module._cpu_cgroup_limited() is expected
