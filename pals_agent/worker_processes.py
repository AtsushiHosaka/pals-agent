"""Fresh-exec proof workers with independent runtimes and graceful delivery drain.

This supervisor owns processes and readiness only. Claims, SQS visibility,
provider clients and mathematical/billing admission remain owned by each ordinary
worker. It never restarts or kills a child with a possibly active delivery.
"""

from __future__ import annotations

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


def run_proof_workers(*, processes: int, ready_file: Path | None) -> int:
    """Exec a new interpreter per worker; never fork initialized agent state."""
    return _supervise(
        command=[sys.executable, "-m", "pals_agent.cli", "worker", "--lane", "proof"],
        processes=processes,
        ready_file=ready_file,
    )


def _supervise(
    *,
    command: list[str],
    processes: int,
    ready_file: Path | None,
    startup_seconds: float = 60.0,
    poll_seconds: float = 0.1,
) -> int:
    if type(processes) is not int or not 2 <= processes <= MAX_PROOF_WORKERS:
        raise ValueError("proof worker process count is outside its bound")
    if startup_seconds <= 0 or poll_seconds <= 0:
        raise ValueError("proof worker supervisor timing is invalid")
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
                while True:
                    exits = [child.poll() for child in children]
                    if stopping:
                        return 0
                    if any(code is not None for code in exits):
                        # Even an unexpected zero exit means the configured lane
                        # no longer has its promised number of live workers.
                        return 1
                    initialized = True
                    for child, marker in zip(children, markers, strict=True):
                        valid = _marker_ready(marker, child.pid)
                        if valid is None:
                            initialized = False
                        elif not valid:
                            return 1
                    if not initialized:
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
