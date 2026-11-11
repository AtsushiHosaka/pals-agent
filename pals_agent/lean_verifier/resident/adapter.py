"""``ResidentWorker``: the ``automation_portfolio.WarmWorker`` interface on the resident Lean.

The stage-0 lanes talk to a "worker" with ``check`` / ``check_statement`` / ``alive`` /
``restart`` / ``close``.  ``WarmWorker`` is a long-lived process that elaborates every request in
the same process (state can leak, a runaway request takes the worker down, a fresh isolated worker
costs a whole Mathlib import).  This adapter answers the same calls from forked children of the
resident zygote instead: every ``check`` is a fresh isolated process that exists already warm.
So "a fresh, clean worker per request" costs milliseconds and "restart" is a no-op.
"""

from __future__ import annotations

import secrets
import shutil
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import mkdtemp

from pals_agent.lean_verifier.resident.manager import (
    ResidentBusy,
    ResidentLean,
    ResidentUnavailable,
)

HEADER = "import Mathlib\n"


class ResidentWorker:
    startup_s = 0.0  # the Mathlib import was paid once, by the zygote

    def __init__(self, resident: ResidentLean, *, scratch_dir: Path | None = None) -> None:
        self._resident = resident
        self._dir = Path(mkdtemp(prefix="pals-rw-", dir=scratch_dir))
        self._counter = 0

    def alive(self) -> bool:
        return self._resident.alive()

    def restart(self) -> None:  # nothing to restart: no state survives a request
        return None

    def prime_checker(self) -> None:
        return None

    def prewarm_search(self) -> float:
        return 0.0  # the zygote holds the ``exact?`` index when ``warm_exact`` is on

    def killed_reason(self) -> str | None:
        return None

    def check(self, source: str, *, timeout_s: float = 60.0) -> tuple[str, float]:
        """Elaborate ``source`` (commands, no header) in a fresh child; return its messages."""
        self._counter += 1
        path = self._dir / f"req{self._counter}-{secrets.token_hex(4)}.lean"
        path.write_text(HEADER + source, encoding="utf-8")
        started = time.monotonic()
        try:
            outcome = self._resident.compile(
                path, workdir=self._dir, olean=None, timeout_s=timeout_s
            )
        except (ResidentBusy, ResidentUnavailable) as error:
            raise RuntimeError(f"resident Lean unavailable: {error}") from error
        finally:
            path.unlink(missing_ok=True)
        if outcome.timed_out:
            raise TimeoutError("resident Lean timeout")
        if outcome.aborted or outcome.unsupported:
            raise RuntimeError("resident Lean child was interrupted")
        return outcome.stdout, time.monotonic() - started

    def check_race(
        self,
        sources: Sequence[str],
        accept: Callable[[int, str], bool],
        *,
        timeout_s: float = 60.0,
    ) -> dict[int, str]:
        """Run every source in its own child at once; return the finished outputs by index.

        As soon as ``accept(index, output)`` holds for one, the others are cancelled (their
        children are killed) and are missing from the result, which is what a caller reads as "not
        run".  Interrupted or timed-out children are missing too.
        """
        cancel = threading.Event()
        deadline = time.monotonic() + timeout_s
        results: dict[int, str] = {}
        lock = threading.Lock()

        def one(index: int) -> None:
            if cancel.is_set():
                return
            path = self._dir / f"race{index}-{secrets.token_hex(4)}.lean"
            path.write_text(HEADER + sources[index], encoding="utf-8")
            try:
                outcome = self._resident.compile(
                    path, workdir=self._dir, olean=None, cancel=cancel,
                    timeout_s=max(0.5, deadline - time.monotonic()),
                )
            except (ResidentBusy, ResidentUnavailable):
                return
            finally:
                path.unlink(missing_ok=True)
            if outcome.timed_out or outcome.aborted or outcome.unsupported:
                return
            with lock:
                results[index] = outcome.stdout
            if accept(index, outcome.stdout):
                cancel.set()

        slots = self._resident.config.max_children
        with ThreadPoolExecutor(max_workers=slots) as pool:
            list(pool.map(one, range(len(sources))))
        return dict(results)

    def check_statement(
        self, term: str, opens: str = "", *, mode: str = "CHECK", timeout_s: float = 30.0
    ) -> tuple[bool, str]:
        if mode != "CHECK":
            return False, "unsupported mode"
        try:
            return self._resident.check_statement(
                term, opens, workdir=self._dir, timeout_s=timeout_s
            )
        except ResidentBusy as error:
            raise RuntimeError(str(error)) from error
        except ResidentUnavailable as error:
            raise RuntimeError(str(error)) from error

    def close(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)
