"""Fresh-exec lane workers with independent runtimes and graceful delivery drain.

This supervisor owns processes and readiness only. Claims, SQS visibility,
provider clients and mathematical/billing admission remain owned by each ordinary
worker. It never kills a child with a possibly active delivery. A child that already
died is replaced within a budget: its receipt returns through SQS and the API claim
fences a repeat, while draining would stop every healthy sibling in a container that
does not restart. An exhausted budget still drains and exits, so a persistent fault
cannot hide behind restarts.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path

MAX_PROOF_WORKERS = 8
_RESTART_BUDGET = 5
_RESTART_WINDOW_SECONDS = 600.0
_PROCESSES_ENV = "PALS_WORKER_PROCESSES"
_SUPERVISED_LANES = frozenset({"proof", "assessment"})


def worker_processes_from_env() -> int:
    """Omission keeps one process; anything unexpected refuses startup."""
    value = os.environ.get(_PROCESSES_ENV, "1")
    if not value.isascii() or not value.isdecimal() or str(int(value)) != value:
        raise ValueError(f"{_PROCESSES_ENV} must be a canonical integer")
    parsed = int(value)
    if not 1 <= parsed <= MAX_PROOF_WORKERS:
        raise ValueError(f"{_PROCESSES_ENV} is outside its bound")
    return parsed


def _marker_ready(marker: Path, pid: int) -> bool | None:
    try:
        fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError:
        return False
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or not 1 <= info.st_size <= 32):
            return False
        return stream.read(33) == str(pid).encode("ascii")


def run_lane_workers(*, lane: str, processes: int, ready_file: Path | None) -> int:
    """Exec a new interpreter per worker; never fork initialized agent state.

    A child names its count explicitly, so an inherited process-count environment value can
    never make it another supervisor.
    """
    if lane not in _SUPERVISED_LANES:
        raise ValueError("multiple worker processes require an explicit single lane")
    return _supervise(
        command=[
            sys.executable, "-m", "pals_agent.cli", "worker",
            "--lane", lane, "--processes", "1",
        ],
        processes=processes,
        ready_file=ready_file,
        restart_budget=_RESTART_BUDGET,
    )


def _supervise(
    *,
    command: list[str],
    processes: int,
    ready_file: Path | None,
    startup_seconds: float = 60.0,
    poll_seconds: float = 0.1,
    restart_budget: int = 0,
    restart_window_seconds: float = _RESTART_WINDOW_SECONDS,
) -> int:
    if type(processes) is not int or not 2 <= processes <= MAX_PROOF_WORKERS:
        raise ValueError("worker process count is outside its bound")
    if startup_seconds <= 0 or poll_seconds <= 0:
        raise ValueError("worker supervisor timing is invalid")
    stopping = False
    children: list[subprocess.Popen[bytes]] = []
    previous = {}

    def request_stop(signum: int, frame: object) -> None:
        nonlocal stopping
        stopping = True

    def clear_ready() -> None:
        if ready_file is not None:
            ready_file.unlink(missing_ok=True)

    def drain_children() -> None:
        # Each ordinary worker stops only at delivery boundaries. In particular,
        # a sibling failure cannot turn a live proof into a forced termination.
        for child in children:
            if child.poll() is None:
                with suppress(ProcessLookupError):
                    child.send_signal(signal.SIGTERM)
        for child in children:
            child.wait()

    clear_ready()
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, request_stop)
        parent = ready_file.parent if ready_file is not None else None
        with tempfile.TemporaryDirectory(prefix="pals-proof-workers-", dir=parent) as directory:
            root = Path(directory)
            markers = [root / f"{index}.ready" for index in range(processes)]
            try:
                for marker in markers:
                    if stopping:
                        return 0
                    children.append(
                        subprocess.Popen([*command, "--ready-file", str(marker)], close_fds=True)
                    )
                deadline = time.monotonic() + startup_seconds
                published = False
                restarts: list[float] = []
                restarted_until = [0.0] * processes
                while True:
                    exits = [child.poll() for child in children]
                    if stopping:
                        return 0
                    for index, code in enumerate(exits):
                        if code is None:
                            continue
                        # Even an unexpected zero exit means the configured lane
                        # no longer has its promised number of live workers.
                        now = time.monotonic()
                        restarts = [
                            at for at in restarts if now - at < restart_window_seconds
                        ]
                        if len(restarts) >= restart_budget:
                            return 1
                        restarts.append(now)
                        sys.stderr.write(
                            json.dumps({
                                "event": "worker_child_restarted",
                                "exit_code": code,
                                "restarts_in_window": len(restarts),
                            }) + "\n"
                        )
                        markers[index].unlink(missing_ok=True)
                        children[index] = subprocess.Popen(
                            [*command, "--ready-file", str(markers[index])], close_fds=True,
                        )
                        restarted_until[index] = now + startup_seconds
                    initialized = True
                    starting = False
                    for index, (child, marker) in enumerate(zip(children, markers, strict=True)):
                        valid = _marker_ready(marker, child.pid)
                        if valid is None:
                            initialized = False
                            starting |= time.monotonic() < restarted_until[index]
                        elif not valid:
                            return 1
                    if not initialized:
                        if starting:
                            # Readiness stays published: the other workers are consuming.
                            time.sleep(poll_seconds)
                            continue
                        if published or time.monotonic() >= deadline:
                            return 1
                    elif not published:
                        if stopping:
                            return 0
                        if any(child.poll() is not None for child in children):
                            return 1
                        if ready_file is not None:
                            # Preserve the existing PID marker format. The parent
                            # publishes it only while every child is ready/alive.
                            ready_file.write_text(str(os.getpid()), encoding="ascii")
                        published = True
                    time.sleep(poll_seconds)
            finally:
                try:
                    clear_ready()
                finally:
                    drain_children()
    finally:
        try:
            clear_ready()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
