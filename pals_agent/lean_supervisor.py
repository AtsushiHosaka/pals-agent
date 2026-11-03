"""Own one compile's whole process tree; imports nothing from the agent and holds no secret.

This process stays outside the sandbox and runs as the Linux child subreaper for one command, so a
descendant that detaches with ``setsid`` or a double fork still ends up as its child. When the
command exits, reaches its deadline or the verifier asks, every descendant is killed and reaped, so
a compile cannot outlive its result, hold its output pipes open or keep PIDs from a sibling.

The result goes to the verifier over a pipe descendants never inherit. A supervisor that dies
writes nothing, and the verifier treats that as an interrupted compile, never as a verdict.
"""

from __future__ import annotations

import ctypes
import os
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path

_PR_SET_CHILD_SUBREAPER = 36
_POLL_SECONDS = 0.01
_SETUP_FAILED = 125


def main() -> None:
    if len(sys.argv) < 5 or sys.argv[3] != "--":
        raise SystemExit(_SETUP_FAILED)
    status_descriptor = int(sys.argv[1], 10)
    deadline = time.monotonic() + float(sys.argv[2])
    os.set_inheritable(status_descriptor, False)
    stopping = [False]
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stopping.__setitem__(0, True))
    if _is_linux():
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
            raise SystemExit(_SETUP_FAILED)
    child = os.fork()
    if child == 0:
        _exec_command(sys.argv[4:])
    # Set in both processes, so the group exists whichever side runs first.
    _set_group(child)
    returncode: int | None = None
    timed_out = False
    while returncode is None:
        returncode = _reap_until_child_exits(child)
        if returncode is None and stopping[0]:
            break
        if returncode is None and time.monotonic() >= deadline:
            timed_out = True
            break
        if returncode is None:
            time.sleep(_POLL_SECONDS)
    _kill_every_descendant(child)
    if returncode is None:
        returncode = -int(signal.SIGKILL)
    os.write(status_descriptor, f"{returncode} {int(timed_out)}\n".encode("ascii"))
    os.close(status_descriptor)


def _exec_command(command: list[str]) -> None:
    with suppress(OSError):
        _set_group(0)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        os.execv(command[0], command)
    os._exit(_SETUP_FAILED)


def _set_group(pid: int) -> None:
    try:
        os.setpgid(pid, 0 if pid == 0 else pid)
    except OSError:
        # The other process already set it, or the child has already exited.
        return


def _reap_until_child_exits(child: int) -> int | None:
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return -int(signal.SIGKILL)
        if pid == 0:
            return None
        if pid == child:
            return os.waitstatus_to_exitcode(status)


def _kill_every_descendant(child: int) -> None:
    """Killing direct children reparents their descendants here, so the loop converges on ECHILD."""
    with suppress(OSError):
        os.killpg(child, signal.SIGKILL)
    while True:
        for pid in _direct_children():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                continue
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            time.sleep(0.001)


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def _direct_children() -> list[int]:
    if not _is_linux():
        return []
    me = os.getpid()
    children = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            fields = (entry / "stat").read_bytes().rpartition(b")")[2].split()
        except OSError:
            continue
        if len(fields) > 1 and int(fields[1]) == me:
            children.append(int(entry.name))
    return children


if __name__ == "__main__":
    main()
