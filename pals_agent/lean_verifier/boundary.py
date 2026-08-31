from __future__ import annotations

import os
import re
import resource
from dataclasses import dataclass
from pathlib import Path

_GIB = 1024 * 1024 * 1024
_MAX_CPU_COUNT = 2.0
_MAX_MEMORY_BYTES = 4 * _GIB
_MAX_PIDS = 64
_MAX_NOFILE = 1024
_CREDENTIAL_ENV_RE = re.compile(
    r"(?:^|_)(?:"
    r"AWS|AZURE|GCP|GOOGLE|CLOUD|DATABASE|DB|MODEL|OPENAI|OLLAMA|"
    r"ANTHROPIC|WORKER|TOKEN|PASSWORD|PASSWD|API_KEY|CREDENTIAL|SECRET|"
    r"ACCESS_KEY|PRIVATE_KEY"
    r")(?:$|_)",
    flags=re.ASCII,
)


class BoundaryAttestationError(RuntimeError):
    """The verifier runtime cannot prove a required outer isolation property."""


@dataclass(frozen=True, slots=True)
class RuntimeBoundaryEvidence:
    effective_uid: int
    inherited_capabilities: int
    permitted_capabilities: int
    effective_capabilities: int
    bounding_capabilities: int
    ambient_capabilities: int
    no_new_privs: bool
    network_interfaces: tuple[str, ...]
    root_read_only: bool
    project_read_only: bool
    scratch_tmpfs_bounded: bool
    socket_tmpfs_bounded: bool
    cpu_cgroup_limited: bool
    memory_cgroup_limited: bool
    pids_cgroup_limited: bool
    nofile_limited: bool
    credential_environment_names: tuple[str, ...]


def validate_runtime_boundary(evidence: RuntimeBoundaryEvidence) -> None:
    checks = (
        (evidence.effective_uid != 0, "verifier must run as a non-root user"),
        (
            all(
                capabilities == 0
                for capabilities in (
                    evidence.inherited_capabilities,
                    evidence.permitted_capabilities,
                    evidence.effective_capabilities,
                    evidence.bounding_capabilities,
                    evidence.ambient_capabilities,
                )
            ),
            "verifier must have no process capabilities",
        ),
        (evidence.no_new_privs, "verifier must have no_new_privs enabled"),
        (
            evidence.network_interfaces == ("lo",),
            "verifier network namespace must contain only loopback",
        ),
        (evidence.root_read_only, "verifier root filesystem must be read-only"),
        (
            evidence.project_read_only,
            "verifier project filesystem must be read-only",
        ),
        (
            evidence.scratch_tmpfs_bounded,
            "verifier scratch mount must be a bounded tmpfs",
        ),
        (
            evidence.socket_tmpfs_bounded,
            "verifier socket mount must be a bounded tmpfs",
        ),
        (evidence.cpu_cgroup_limited, "verifier CPU cgroup limit is missing"),
        (
            evidence.memory_cgroup_limited,
            "verifier memory cgroup limit is missing",
        ),
        (evidence.pids_cgroup_limited, "verifier PID cgroup limit is missing"),
        (evidence.nofile_limited, "verifier open-file limit is missing"),
        (
            not evidence.credential_environment_names,
            "verifier environment contains credential-like names",
        ),
    )
    for valid, message in checks:
        if not valid:
            raise BoundaryAttestationError(message)


def attest_runtime_boundary(
    *,
    project_dir: Path,
    scratch_dir: Path,
    socket_dir: Path,
    scratch_max_bytes: int,
    socket_max_bytes: int,
) -> RuntimeBoundaryEvidence:
    status = _proc_status()
    evidence = RuntimeBoundaryEvidence(
        effective_uid=os.geteuid(),
        inherited_capabilities=_hex_status_value(status, "CapInh"),
        permitted_capabilities=_hex_status_value(status, "CapPrm"),
        effective_capabilities=_hex_status_value(status, "CapEff"),
        bounding_capabilities=_hex_status_value(status, "CapBnd"),
        ambient_capabilities=_hex_status_value(status, "CapAmb"),
        no_new_privs=_decimal_status_value(status, "NoNewPrivs") == 1,
        network_interfaces=_network_interfaces(),
        root_read_only=_is_read_only(Path("/")),
        project_read_only=_is_read_only(project_dir),
        scratch_tmpfs_bounded=_is_bounded_tmpfs(
            scratch_dir,
            maximum_bytes=scratch_max_bytes,
        ),
        socket_tmpfs_bounded=_is_bounded_tmpfs(
            socket_dir,
            maximum_bytes=socket_max_bytes,
        ),
        cpu_cgroup_limited=_cpu_cgroup_limited(),
        memory_cgroup_limited=_integer_cgroup_limited(
            "memory.max",
            "memory.limit_in_bytes",
            maximum=_MAX_MEMORY_BYTES,
            controllers=("memory",),
        ),
        pids_cgroup_limited=_integer_cgroup_limited(
            "pids.max",
            "pids.max",
            maximum=_MAX_PIDS,
            controllers=("pids",),
        ),
        nofile_limited=_nofile_limited(),
        credential_environment_names=tuple(
            sorted(
                name
                for name, value in os.environ.items()
                if value and _CREDENTIAL_ENV_RE.search(name.upper()) is not None
            )
        ),
    )
    validate_runtime_boundary(evidence)
    return evidence


def attest_http_runtime_boundary(
    *,
    project_dir: Path,
    scratch_dir: Path,
    scratch_max_bytes: int,
    allowed_reference_environment_names: frozenset[str],
) -> RuntimeBoundaryEvidence:
    """Attest the verifier's outer mTLS-server isolation without a Unix socket exception.

    The HTTP server must have a service interface in order to accept the reconciler, so unlike the
    retired Unix sidecar it cannot require a loopback-only namespace.  The actual mTLS peer
    authorization is checked by the server for every request; this startup check proves the rest of
    the process, filesystem, cgroup, and environment boundary before it binds a port.
    """

    status = _proc_status()
    evidence = RuntimeBoundaryEvidence(
        effective_uid=os.geteuid(),
        inherited_capabilities=_hex_status_value(status, "CapInh"),
        permitted_capabilities=_hex_status_value(status, "CapPrm"),
        effective_capabilities=_hex_status_value(status, "CapEff"),
        bounding_capabilities=_hex_status_value(status, "CapBnd"),
        ambient_capabilities=_hex_status_value(status, "CapAmb"),
        no_new_privs=_decimal_status_value(status, "NoNewPrivs") == 1,
        network_interfaces=_network_interfaces(),
        root_read_only=_is_read_only(Path("/")),
        project_read_only=_is_read_only(project_dir),
        scratch_tmpfs_bounded=_is_bounded_tmpfs(
            scratch_dir,
            maximum_bytes=scratch_max_bytes,
        ),
        socket_tmpfs_bounded=True,
        cpu_cgroup_limited=_cpu_cgroup_limited(),
        memory_cgroup_limited=_integer_cgroup_limited(
            "memory.max",
            "memory.limit_in_bytes",
            maximum=_MAX_MEMORY_BYTES,
            controllers=("memory",),
        ),
        pids_cgroup_limited=_integer_cgroup_limited(
            "pids.max",
            "pids.max",
            maximum=_MAX_PIDS,
            controllers=("pids",),
        ),
        nofile_limited=_nofile_limited(),
        credential_environment_names=_credential_environment_names(
            allowed_reference_environment_names
        ),
    )
    validate_http_runtime_boundary(evidence)
    return evidence


def validate_http_runtime_boundary(evidence: RuntimeBoundaryEvidence) -> None:
    checks = (
        (evidence.effective_uid != 0, "verifier must run as a non-root user"),
        (
            all(
                capabilities == 0
                for capabilities in (
                    evidence.inherited_capabilities,
                    evidence.permitted_capabilities,
                    evidence.effective_capabilities,
                    evidence.bounding_capabilities,
                    evidence.ambient_capabilities,
                )
            ),
            "verifier must have no process capabilities",
        ),
        (evidence.no_new_privs, "verifier must have no_new_privs enabled"),
        (
            any(interface != "lo" for interface in evidence.network_interfaces),
            "mTLS verifier must have a private service interface",
        ),
        (evidence.root_read_only, "verifier root filesystem must be read-only"),
        (
            evidence.project_read_only,
            "verifier project filesystem must be read-only",
        ),
        (
            evidence.scratch_tmpfs_bounded,
            "verifier scratch mount must be a bounded tmpfs",
        ),
        (evidence.cpu_cgroup_limited, "verifier CPU cgroup limit is missing"),
        (
            evidence.memory_cgroup_limited,
            "verifier memory cgroup limit is missing",
        ),
        (evidence.pids_cgroup_limited, "verifier PID cgroup limit is missing"),
        (evidence.nofile_limited, "verifier open-file limit is missing"),
        (
            not evidence.credential_environment_names,
            "verifier environment contains credential-like names",
        ),
    )
    for valid, message in checks:
        if not valid:
            raise BoundaryAttestationError(message)


def _proc_status() -> dict[str, str]:
    try:
        lines = Path("/proc/self/status").read_text(encoding="ascii").splitlines()
    except OSError as exc:
        raise BoundaryAttestationError(
            "verifier cannot read Linux process isolation evidence"
        ) from exc
    return {
        name: value.strip()
        for line in lines
        if ":" in line
        for name, value in (line.split(":", 1),)
    }


def _credential_environment_names(
    allowed_reference_environment_names: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for name, value in os.environ.items()
            if value
            and name not in allowed_reference_environment_names
            and _CREDENTIAL_ENV_RE.search(name.upper()) is not None
        )
    )


def _hex_status_value(status: dict[str, str], name: str) -> int:
    try:
        return int(status[name], 16)
    except (KeyError, ValueError) as exc:
        raise BoundaryAttestationError(
            f"verifier cannot prove process {name} state"
        ) from exc


def _decimal_status_value(status: dict[str, str], name: str) -> int:
    try:
        return int(status[name], 10)
    except (KeyError, ValueError) as exc:
        raise BoundaryAttestationError(
            f"verifier cannot prove process {name} state"
        ) from exc


def _network_interfaces() -> tuple[str, ...]:
    try:
        return tuple(sorted(path.name for path in Path("/sys/class/net").iterdir()))
    except OSError as exc:
        raise BoundaryAttestationError(
            "verifier cannot inspect its network namespace"
        ) from exc


def _is_read_only(path: Path) -> bool:
    try:
        return bool(os.statvfs(path).f_flag & os.ST_RDONLY)
    except OSError:
        return False


def _is_bounded_tmpfs(path: Path, *, maximum_bytes: int) -> bool:
    if maximum_bytes <= 0:
        return False
    try:
        resolved = path.resolve(strict=True)
        mount_type = _mount_types()[resolved]
        filesystem = os.statvfs(resolved)
    except (KeyError, OSError):
        return False
    total_bytes = filesystem.f_frsize * filesystem.f_blocks
    return mount_type == "tmpfs" and 0 < total_bytes <= maximum_bytes


def _mount_types() -> dict[Path, str]:
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BoundaryAttestationError(
            "verifier cannot inspect filesystem mounts"
        ) from exc
    mounts: dict[Path, str] = {}
    for line in lines:
        fields = line.split()
        try:
            separator = fields.index("-")
            mount_point = Path(_unescape_mount_field(fields[4])).resolve()
            filesystem_type = fields[separator + 1]
        except (IndexError, ValueError, OSError):
            continue
        mounts[mount_point] = filesystem_type
    return mounts


def _unescape_mount_field(value: str) -> str:
    return (
        value.replace(r"\040", " ")
        .replace(r"\011", "\t")
        .replace(r"\012", "\n")
        .replace(r"\134", "\\")
    )


def _cgroup_v2_root() -> Path | None:
    root = Path("/sys/fs/cgroup")
    return root if (root / "cgroup.controllers").is_file() else None


def _cpu_cgroup_limited() -> bool:
    v2_root = _cgroup_v2_root()
    if v2_root is not None:
        try:
            quota_text, period_text = (v2_root / "cpu.max").read_text(
                encoding="ascii"
            ).split()
            if quota_text == "max":
                return False
            quota = int(quota_text, 10)
            period = int(period_text, 10)
            return quota > 0 and period > 0 and quota / period <= _MAX_CPU_COUNT
        except (OSError, ValueError):
            return False

    root = _cgroup_v1_controller_root(("cpu", "cpuacct"))
    if root is None:
        return False
    try:
        quota = int((root / "cpu.cfs_quota_us").read_text(encoding="ascii"), 10)
        period = int((root / "cpu.cfs_period_us").read_text(encoding="ascii"), 10)
    except (OSError, ValueError):
        return False
    return quota > 0 and period > 0 and quota / period <= _MAX_CPU_COUNT


def _integer_cgroup_limited(
    v2_name: str,
    v1_name: str,
    *,
    maximum: int,
    controllers: tuple[str, ...],
) -> bool:
    v2_root = _cgroup_v2_root()
    root = v2_root if v2_root is not None else _cgroup_v1_controller_root(controllers)
    if root is None:
        return False
    name = v2_name if v2_root is not None else v1_name
    try:
        value = (root / name).read_text(encoding="ascii").strip()
        return value != "max" and 0 < int(value, 10) <= maximum
    except (OSError, ValueError):
        return False


def _cgroup_v1_controller_root(controllers: tuple[str, ...]) -> Path | None:
    base = Path("/sys/fs/cgroup")
    for controller in controllers:
        candidate = base / controller
        if candidate.is_dir():
            return candidate
    return None


def _nofile_limited() -> bool:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    return 0 < soft <= _MAX_NOFILE and 0 < hard <= _MAX_NOFILE
