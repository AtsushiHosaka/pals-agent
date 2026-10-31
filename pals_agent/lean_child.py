"""Apply per-compile limits and Linux restrictions immediately before Lean exec."""

from __future__ import annotations

import ctypes
import errno
import os
import resource
import shlex
import stat
import sys
import sysconfig
from pathlib import Path

_LANDLOCK_CREATE_RULESET = 444
_LANDLOCK_ADD_RULE = 445
_LANDLOCK_RESTRICT_SELF = 446
_LANDLOCK_CREATE_RULESET_VERSION = 1
_LANDLOCK_RULE_PATH_BENEATH = 1
_LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
_LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
_LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
_LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
_LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
_LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
_LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
_LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
_LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
_LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
_LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
_LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
_LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12
_LANDLOCK_ACCESS_FS_REFER = 1 << 13
_LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14
_LANDLOCK_BASE_ACCESS = (1 << 13) - 1
_LANDLOCK_READ_EXECUTE = (
    _LANDLOCK_ACCESS_FS_EXECUTE
    | _LANDLOCK_ACCESS_FS_READ_FILE
    | _LANDLOCK_ACCESS_FS_READ_DIR
)
_LANDLOCK_NULL_DEVICE = (
    _LANDLOCK_ACCESS_FS_READ_FILE | _LANDLOCK_ACCESS_FS_WRITE_FILE
)
_PR_SET_NO_NEW_PRIVS = 38
_SCMP_ACT_ALLOW = 0x7FFF0000
_SCMP_ACT_ERRNO = 0x00050000 | errno.EPERM
_BLOCKED_SOCKET_SYSCALLS = (
    b"socket",
    b"socketpair",
    b"connect",
    b"bind",
    b"listen",
    b"accept",
    b"accept4",
    b"sendto",
    b"sendmsg",
    b"sendmmsg",
    b"recvfrom",
    b"recvmsg",
    b"recvmmsg",
)
_LIMIT_NAMES = (
    resource.RLIMIT_CPU,
    resource.RLIMIT_AS,
    resource.RLIMIT_FSIZE,
    resource.RLIMIT_NPROC,
    resource.RLIMIT_NOFILE,
    resource.RLIMIT_CORE,
)


class _LandlockRulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _LandlockPathBeneathAttr(ctypes.Structure):
    _layout_ = "gcc-sysv"
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


def main() -> None:
    if len(sys.argv) < 10 or sys.argv[8] != "--":
        raise SystemExit(125)
    scratch_dir = Path(sys.argv[1])
    try:
        limits = [int(value, 10) for value in sys.argv[2:8]]
        _apply_rlimits(limits)
        if sys.platform.startswith("linux"):
            _apply_landlock(scratch_dir, sys.argv[9:])
            _apply_socket_seccomp()
        os.execv(sys.argv[9], sys.argv[9:])
    except (OSError, ValueError):
        raise SystemExit(125) from None


def _apply_rlimits(limits: list[int]) -> None:
    if len(limits) != len(_LIMIT_NAMES) or any(value < 0 for value in limits):
        raise ValueError("invalid child limits")
    for resource_name, value in zip(_LIMIT_NAMES, limits, strict=True):
        if sys.platform == "darwin" and resource_name in {
            resource.RLIMIT_AS,
            resource.RLIMIT_NPROC,
        }:
            # Darwin accounts these against shared mappings and the login user.
            # Linux production applies every limit through prlimit and here.
            continue
        resource.setrlimit(resource_name, (value, value))


def _readable_runtime_paths(command: list[str]) -> dict[Path, int]:
    """Derive access from trusted launcher configuration, never from proof text.

    Lake's workspace and Elan's installed toolchains are deployment-owned inputs.
    Production separately attests their read-only mounts. PATH is deliberately
    not an allowlist: it also contains daemon executables and unrelated files.
    """
    paths: dict[Path, int] = {}

    def allow(path: Path, access: int) -> Path:
        resolved = path.resolve(strict=True)
        if resolved == Path("/") or any(
            resolved.is_relative_to(root) for root in (Path("/proc"), Path("/run"))
        ):
            raise ValueError("invalid Lean runtime path")
        paths[resolved] = paths.get(resolved, 0) | access
        return resolved

    executables = [Path(command[0])]
    lake_environment = len(command) > 2 and command[1] == "env"
    if lake_environment:
        executables.append(Path(command[2]))
    toolchains: list[Path] = []
    for executable in executables:
        resolved = allow(executable, _LANDLOCK_ACCESS_FS_READ_FILE | _LANDLOCK_ACCESS_FS_EXECUTE)
        if not resolved.is_file():
            raise ValueError("invalid Lean executable")
        with resolved.open("rb") as source:
            header = source.readline(256)
        if header.startswith(b"#!"):
            interpreter = shlex.split(header[2:].decode("utf-8"))
            if not interpreter or not Path(interpreter[0]).is_absolute():
                raise ValueError("invalid Lean executable interpreter")
            allow(Path(interpreter[0]), _LANDLOCK_ACCESS_FS_READ_FILE | _LANDLOCK_ACCESS_FS_EXECUTE)
        native_toolchain = resolved.parent.parent
        if resolved.parent.name == "bin" and (native_toolchain / "lib/lean").is_dir():
            toolchains.append(allow(native_toolchain, _LANDLOCK_READ_EXECUTE))

    elan_home = Path(os.environ.get("ELAN_HOME", "/opt/elan"))
    # Standalone integrations may configure a native sysroot instead of Elan.
    if (elan_home / "bin/lean").is_file() and (elan_home / "lib/lean").is_dir():
        toolchains.append(allow(elan_home, _LANDLOCK_READ_EXECUTE))
    installed = elan_home / "toolchains"
    if installed.is_dir():
        # Elan proxies dispatch to the pinned installed toolchain. Do not expose
        # the rest of ELAN_HOME (or the daemon's HOME) to compiled Lean code.
        for name in ("lean", "lake"):
            proxy = elan_home / "bin" / name
            if proxy.is_file():
                allow(proxy, _LANDLOCK_ACCESS_FS_READ_FILE | _LANDLOCK_ACCESS_FS_EXECUTE)
        allow(installed, _LANDLOCK_ACCESS_FS_READ_DIR)
        for toolchain in installed.iterdir():
            if (toolchain / "bin/lean").is_file() and (toolchain / "lib/lean").is_dir():
                # `elan toolchain link` may name an operator-provisioned sysroot
                # outside ELAN_HOME. Canonicalize that runtime, not its parent.
                toolchains.append(allow(toolchain, _LANDLOCK_READ_EXECUTE))
        for name in ("settings.toml", "known-projects"):
            settings = elan_home / name
            if settings.is_file():
                allow(settings, _LANDLOCK_ACCESS_FS_READ_FILE)
        for directory in (Path.cwd(), *Path.cwd().parents):
            pin = directory / "lean-toolchain"
            if pin.is_file():
                allow(pin, _LANDLOCK_ACCESS_FS_READ_FILE)
                break

    workspace: Path | None = None
    if lake_environment or os.environ.get("LEAN_PATH"):
        workspace = Path.cwd().resolve(strict=True)
        if not (workspace / "lean-toolchain").is_file() or not any(
            (workspace / name).is_file() for name in ("lakefile.lean", "lakefile.toml")
        ):
            raise ValueError("invalid Lean workspace")
        allow(workspace, _LANDLOCK_ACCESS_FS_READ_FILE | _LANDLOCK_ACCESS_FS_READ_DIR)
        # Lake checks the pinned package remotes even for `lake env`.
        git = Path("/usr/bin/git")
        if git.is_file():
            allow(git, _LANDLOCK_ACCESS_FS_READ_FILE | _LANDLOCK_ACCESS_FS_EXECUTE)
    for name in ("LEAN_PATH", "LEAN_SRC_PATH", "LD_LIBRARY_PATH"):
        for value in filter(None, os.environ.get(name, "").split(os.pathsep)):
            path = Path(value).resolve()
            import_roots = [*toolchains, *([workspace] if workspace else [])]
            if not any(path.is_relative_to(root) for root in import_roots):
                raise ValueError("Lean import path is outside its runtime")
            # Lake includes build output directories that need not exist yet.
            if path.exists():
                allow(path, _LANDLOCK_ACCESS_FS_READ_FILE | _LANDLOCK_ACCESS_FS_READ_DIR)

    multiarch = sysconfig.get_config_var("MULTIARCH")
    if not isinstance(multiarch, str) or not multiarch or Path(multiarch).name != multiarch:
        raise ValueError("unsupported Linux runtime library layout")
    for library_root in (Path("/lib") / multiarch, Path("/usr/lib") / multiarch):
        if library_root.is_dir():
            allow(library_root, _LANDLOCK_READ_EXECUTE)
    # The x86-64 loader alias can live outside its triplet library directory.
    loader = Path("/lib64/ld-linux-x86-64.so.2")
    if loader.is_file():
        allow(loader, _LANDLOCK_ACCESS_FS_READ_FILE | _LANDLOCK_ACCESS_FS_EXECUTE)
    cache = Path("/etc/ld.so.cache")
    if cache.is_file():
        allow(cache, _LANDLOCK_ACCESS_FS_READ_FILE)
    return paths


def _validated_scratch_directory(scratch_dir: Path) -> Path:
    resolved = scratch_dir.resolve(strict=True)
    if resolved == Path("/") or resolved.is_relative_to(Path("/proc")):
        raise ValueError("invalid Lean scratch directory")
    if resolved.is_relative_to(Path("/run")):
        # HTTP startup attests this exact bounded tmpfs. Grant only the current
        # TemporaryDirectory child, never its parent or the daemon's TLS mount.
        request_root = Path("/run/pals-verifier-requests")
        if (
            scratch_dir != resolved
            or resolved.parent != request_root
            or not resolved.name.startswith("pals-lean-")
            or resolved.name == "pals-lean-"
            or os.geteuid() == 0
        ):
            raise ValueError("invalid HTTP Lean scratch directory")
        for directory in (request_root, resolved):
            info = directory.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise ValueError("unprotected HTTP Lean scratch directory")
        mount_types = []
        for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) > 6 and fields[4] == str(request_root):
                separator = fields.index("-")
                mount_types.append(fields[separator + 1])
        filesystem = os.statvfs(request_root)
        size = filesystem.f_frsize * filesystem.f_blocks
        if mount_types != ["tmpfs"] or not 0 < size <= 64 * 1024 * 1024:
            raise ValueError("HTTP Lean scratch tmpfs boundary is unavailable")
    return resolved


def _apply_landlock(scratch_dir: Path, command: list[str]) -> None:
    runtime_paths = _readable_runtime_paths(command)
    scratch_dir = _validated_scratch_directory(scratch_dir)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    abi = libc.syscall(
        _LANDLOCK_CREATE_RULESET,
        ctypes.c_void_p(),
        ctypes.c_size_t(0),
        ctypes.c_uint(_LANDLOCK_CREATE_RULESET_VERSION),
    )
    if abi < 1:
        _raise_errno("Landlock ABI is unavailable")

    handled_access = _LANDLOCK_BASE_ACCESS
    if abi >= 2:
        handled_access |= _LANDLOCK_ACCESS_FS_REFER
    if abi >= 3:
        handled_access |= _LANDLOCK_ACCESS_FS_TRUNCATE
    ruleset_attr = _LandlockRulesetAttr(handled_access_fs=handled_access)
    ruleset_fd = libc.syscall(
        _LANDLOCK_CREATE_RULESET,
        ctypes.byref(ruleset_attr),
        ctypes.sizeof(ruleset_attr),
        ctypes.c_uint(0),
    )
    if ruleset_fd < 0:
        _raise_errno("Landlock ruleset creation failed")
    try:
        for path, access in runtime_paths.items():
            _add_landlock_path_rule(libc, ruleset_fd, path, access)
        _add_landlock_path_rule(
            libc,
            ruleset_fd,
            Path("/dev/null"),
            _LANDLOCK_NULL_DEVICE,
        )
        _add_landlock_path_rule(
            libc,
            ruleset_fd,
            Path("/dev/urandom"),
            _LANDLOCK_ACCESS_FS_READ_FILE,
        )
        _add_landlock_path_rule(
            libc,
            ruleset_fd,
            scratch_dir,
            handled_access,
        )
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            _raise_errno("no_new_privs setup failed")
        if libc.syscall(
            _LANDLOCK_RESTRICT_SELF,
            ruleset_fd,
            ctypes.c_uint(0),
        ) != 0:
            _raise_errno("Landlock activation failed")
    finally:
        os.close(ruleset_fd)


def _add_landlock_path_rule(
    libc: ctypes.CDLL,
    ruleset_fd: int,
    path: Path,
    allowed_access: int,
) -> None:
    o_path = getattr(os, "O_PATH", 0o10000000)
    path_fd = os.open(path, o_path | os.O_CLOEXEC)
    try:
        rule = _LandlockPathBeneathAttr(
            allowed_access=allowed_access,
            parent_fd=path_fd,
        )
        if libc.syscall(
            _LANDLOCK_ADD_RULE,
            ruleset_fd,
            _LANDLOCK_RULE_PATH_BENEATH,
            ctypes.byref(rule),
            ctypes.c_uint(0),
        ) != 0:
            _raise_errno("Landlock path rule failed")
    finally:
        os.close(path_fd)


def _apply_socket_seccomp() -> None:
    try:
        seccomp = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    except OSError as exc:
        raise OSError(errno.ENOSYS, "seccomp library is unavailable") from exc
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_syscall_resolve_name.restype = ctypes.c_int
    seccomp.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]

    context = seccomp.seccomp_init(_SCMP_ACT_ALLOW)
    if not context:
        raise OSError(errno.EPERM, "seccomp context creation failed")
    try:
        for syscall_name in _BLOCKED_SOCKET_SYSCALLS:
            syscall_number = seccomp.seccomp_syscall_resolve_name(syscall_name)
            if syscall_number < 0:
                continue
            if (
                seccomp.seccomp_rule_add(
                    context,
                    _SCMP_ACT_ERRNO,
                    syscall_number,
                    0,
                )
                != 0
            ):
                raise OSError(errno.EPERM, "seccomp rule installation failed")
        if seccomp.seccomp_load(context) != 0:
            raise OSError(errno.EPERM, "seccomp activation failed")
    finally:
        seccomp.seccomp_release(context)


def _raise_errno(message: str) -> None:
    error_number = ctypes.get_errno() or errno.EPERM
    raise OSError(error_number, message)


if __name__ == "__main__":
    main()
