"""Local containment for the Lean processes of the portfolio lanes (second layer after the grammar).

Lean elaboration of untrusted text can execute code in ways a validator may miss.  This module
bounds what such code could do, as far as a developer machine allows:

  * a scrubbed environment (no secrets, PATH = the toolchain's bin dir + /usr/bin:/bin, HOME and
    TMPDIR inside the scratch dir);
  * the working directory is an empty scratch directory;
  * rlimits: no core dumps, bounded file size, open files, address space (and CPU for one-shot
    runs); the process runs in its own session so the whole group is killed on timeout;
  * on macOS, ``sandbox-exec``: no network, no exec except the Lean binary (``lean --run``
    re-invokes ``lean``),
    writes only inside the scratch directory, and reads of the user's home, /tmp and /var/folders
    denied except the toolchain, the Lake packages (``LEAN_PATH``) and the scratch directory.

This is NOT the production verifier's isolation (Landlock, seccomp, cgroups, mTLS, read-only
root; see ``docs/verification/warm-portfolio-worker-design-2026-11-11.md``).  Production use of
these lanes requires the real sandboxed verifier.  ``describe()`` says what was actually applied.
"""

from __future__ import annotations

import contextlib
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

SANDBOX_EXEC: Final = "/usr/bin/sandbox-exec"
MAX_FILE_BYTES: Final = 64 * 1024 * 1024
MAX_OPEN_FILES: Final = 1024
MAX_ADDRESS_SPACE: Final = 96 * 1024**3  # Lean maps Mathlib (tens of GB of virtual memory)


def enabled() -> bool:
    return os.environ.get("PALS_LEAN_SANDBOX", "").strip().lower() not in {"off", "0", "false"}


def available() -> bool:
    return enabled() and sys.platform == "darwin" and Path(SANDBOX_EXEC).exists()


def describe() -> str:
    parts = ["scrubbed-env", "scratch-cwd", "rlimits", "process-group-kill"]
    if available():
        parts.append("sandbox-exec(no-network,no-exec,scoped-read-write)")
    return "+".join(parts)


def _real(path: str | Path) -> str:
    return os.path.realpath(str(path))


def _sbpl_string(value: str) -> str:
    if any(ch in value for ch in '"\\\n'):
        raise ValueError("path not representable in a sandbox profile")
    return f'"{value}"'


@dataclass(frozen=True, slots=True)
class Isolation:
    """Paths the Lean process may read: the toolchain, the Lake packages, extra files."""

    lean_binary: str
    lean_path: str
    extra_read: tuple[str, ...] = ()

    def read_roots(self) -> list[str]:
        roots = {_real(Path(self.lean_binary).parent.parent)}
        for entry in self.lean_path.split(os.pathsep):
            if entry:
                roots.add(_real(entry))
        for extra in self.extra_read:
            roots.add(_real(extra))
        return sorted(roots)


def profile(isolation: Isolation, scratch: str) -> str:
    scratch_real = _real(scratch)
    reads = " ".join(f"(subpath {_sbpl_string(root)})" for root in isolation.read_roots())
    lean = _sbpl_string(_real(isolation.lean_binary))
    return (
        "(version 1)\n(allow default)\n"
        "(deny network*)\n"
        "(deny process-exec*)\n"
        f"(allow process-exec (literal {lean}))\n"
        "(deny file-write*)\n"
        f'(allow file-write* (subpath {_sbpl_string(scratch_real)}) (literal "/dev/null")'
        ' (regex #"^/dev/(tty|pty|ttys)[^/]*$"))\n'
        '(deny file-read* (subpath "/Users") (subpath "/private/tmp")'
        ' (subpath "/private/var/folders") (subpath "/private/var/root") (subpath "/Volumes"))\n'
        f"(allow file-read* (subpath {_sbpl_string(scratch_real)}) {reads})\n"
        "(allow file-read-metadata)\n"  # stat/realpath of parent directories, never contents
    )


def scrubbed_env(isolation: Isolation, scratch: str) -> dict[str, str]:
    return {
        "PATH": f"{Path(isolation.lean_binary).parent}:/usr/bin:/bin",
        "LEAN_PATH": isolation.lean_path,
        "HOME": scratch,
        "TMPDIR": scratch,
        "LANG": "C.UTF-8",
    }


def _rlimits(cpu_seconds: int | None) -> Callable[[], None]:
    def apply() -> None:
        def limit(which: int, value: int) -> None:
            # not every limit exists or can be lowered on every platform
            with contextlib.suppress(ValueError, OSError):
                resource.setrlimit(which, (value, value))

        limit(resource.RLIMIT_CORE, 0)
        limit(resource.RLIMIT_FSIZE, MAX_FILE_BYTES)
        limit(resource.RLIMIT_NOFILE, MAX_OPEN_FILES)
        limit(resource.RLIMIT_AS, MAX_ADDRESS_SPACE)
        if cpu_seconds is not None:
            limit(resource.RLIMIT_CPU, cpu_seconds)

    return apply


def command(cmd: list[str], isolation: Isolation, scratch: str) -> list[str]:
    """Wrap ``cmd`` in the sandbox profile when it is available."""
    if not available():
        return cmd
    return [SANDBOX_EXEC, "-p", profile(isolation, scratch), *cmd]


def popen_kwargs(
    isolation: Isolation, scratch: str, *, cpu_seconds: int | None = None
) -> dict[str, Any]:
    """Keyword arguments for ``subprocess.Popen``: env, cwd, rlimits, own session."""
    return {
        "env": scrubbed_env(isolation, scratch),
        "cwd": scratch,
        "preexec_fn": _rlimits(cpu_seconds),
        "start_new_session": True,
        "close_fds": True,
    }


def kill_group(proc: subprocess.Popen[Any]) -> None:
    """SIGKILL the whole process group (Lean may have children) and reap."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
    proc.wait()


def new_scratch(prefix: str = "pals-lean-") -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(prefix=prefix)


def which(name: str) -> str | None:
    return shutil.which(name)
