"""Manager for the resident Lean worker (``worker.lean.in`` + ``shim.c``).

One long-lived *zygote* process imports Mathlib once.  Each request is answered by a ``fork``ed
child of the zygote that shares the imported environment copy-on-write, so a check costs the
elaboration alone, not the process start and the Mathlib import (4-9 s warm, 35-48 s cold).

Why this is safe to put under a verdict
  * Isolation: the zygote never elaborates request text.  Each request lives and dies in its own
    process (own process group, CPU limit, on Linux a private-memory limit), so no request can
    change what another one sees.  There is no state to leak and nothing to clean between requests.
  * The audit stays the audit: ``audit`` runs the program of ``lean_audit.TRUSTED_AUDIT_SOURCE``
    (text-derived, see ``warm_audit_source``) in a fresh child of the same zygote, over the same
    ``.olean`` file protocol and with a nonce created after the candidate's child exited.
  * Failure is never a verdict: a dead child, a timeout, a dead zygote or a full pool are reported
    as ``timed_out``/``aborted``/``unsupported``/``ResidentBusy`` and the caller falls back to the
    cold path (or reports an interruption).  Only ``returncode`` and the text of a finished child
    ever reach a verdict.

Not done here (see docs/verification/resident-lean-2026-11-12.md): Landlock/seccomp for the zygote
(``launcher`` hook; ``lean_child.py`` can wrap it) and per-request narrowing of the write
permission to the request's own directory.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from pals_agent.lean_audit import TRUSTED_AUDIT_SOURCE

_HERE: Final = Path(__file__).resolve().parent
WORKER_TEMPLATE: Final = _HERE / "worker.lean.in"
SHIM_SOURCE: Final = _HERE / "shim.c"
STATEMENT_CHECK_SOURCE: Final = _HERE / "statement_check.lean.in"
MAX_RESTART_ATTEMPTS: Final = 5
UNSUPPORTED_CODES: Final = frozenset({65, 66})


class ResidentUnavailable(RuntimeError):
    """The worker is not running (starting, crashed or never started); use the cold path."""


class ResidentBusy(RuntimeError):
    """No slot became free within the queue limit; never wait unboundedly (503 semantics)."""


@dataclass(frozen=True, slots=True)
class CompileOutcome:
    returncode: int  # 0 accepted by the compiler, 1 errors; only meaningful if not interrupted
    stdout: str
    timed_out: bool = False
    aborted: bool = False  # child died or zygote lost: interruption, never a verdict
    unsupported: bool = False  # imports differ from the resident set: use the cold path
    output_limited: bool = False
    elapsed_s: float = 0.0


@dataclass(frozen=True, slots=True)
class AuditOutcome:
    returncode: int
    stdout: str
    timed_out: bool = False
    aborted: bool = False
    unsupported: bool = False
    output_limited: bool = False
    elapsed_s: float = 0.0


@dataclass(frozen=True, slots=True)
class ResidentConfig:
    lean_binary: str
    lean_path: str  # LEAN_PATH, resolved once outside any request
    build_dir: Path  # generated worker source and compiled shim go here (not request data)
    max_children: int = 4  # concurrent forked children
    queue_timeout_s: float = 2.0  # wait for a slot at most this long, then ResidentBusy
    child_memory_bytes: int = 6 << 30  # private memory a child may add (Linux, RLIMIT_DATA)
    child_cpu_seconds: int = 120
    startup_timeout_s: float = 180.0
    output_limit_bytes: int = 1 << 20
    c_compiler: str | None = None  # default: toolchain leanc, then cc/clang
    # Wraps the zygote command (e.g. lean_child.py for Landlock + seccomp). Gets (argv, scratch).
    launcher: Callable[[Sequence[str], Path], list[str]] | None = None
    extra_environment: dict[str, str] = field(default_factory=dict)
    # Build the `exact?` lemma index once in the zygote (12-15 s, extra memory) so every forked
    # child inherits it instead of building its own.
    warm_exact: bool = False


_AUDIT_HEADER = "unsafe def main (args : List String) : IO UInt32 := do\n"
_AUDIT_IMPORT = (
    "  enableInitializersExecution\n"
    "  let env ← importModules mod.imports {} 0 (loadExts := true)\n"
)


def warm_audit_source(source: str = TRUSTED_AUDIT_SOURCE) -> str:
    """``auditWarm``: the trusted audit with two anchored replacements and nothing else.

    1. the entry point becomes a function taking the already imported environment;
    2. the import is replaced by a check that the module's imports are the resident set (the
       resulting environment is the same value ``importModules`` would build);
    Every anchor must be present exactly once, so a change to the trusted audit cannot silently
    drift from this derivation.
    """
    for anchor in (_AUDIT_HEADER, _AUDIT_IMPORT):
        if source.count(anchor) != 1:
            raise ValueError("trusted audit source changed; update the warm derivation")
    marker = "unsafe def main"
    body = source[source.index(marker) :]
    body = body.replace(
        _AUDIT_HEADER,
        "unsafe def auditWarm (warmEnv : Environment) (warmImports : Array Import)"
        " (args : List String) : IO UInt32 := do\n",
    )
    body = body.replace(
        _AUDIT_IMPORT,
        "  unless mod.imports == warmImports do return 65\n"
        "  let env := warmEnv\n",
    )
    return body


def render_worker_source() -> str:
    template = WORKER_TEMPLATE.read_text(encoding="utf-8")
    return template.replace(
        "{{STATEMENT_CHECK}}", STATEMENT_CHECK_SOURCE.read_text(encoding="utf-8")
    ).replace("{{AUDIT_BODY}}", warm_audit_source())


@dataclass
class _Pending:
    kind: str
    forked: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    pid: int = 0
    code: int | None = None


class ResidentLean:
    def __init__(self, config: ResidentConfig) -> None:
        self.config = config
        self._lock = threading.Lock()  # guards _proc/_pending/_generation and stdin writes
        self._slots = threading.BoundedSemaphore(config.max_children)
        self._proc: subprocess.Popen[bytes] | None = None
        self._pending: dict[str, _Pending] = {}
        self._generation = 0
        self._ready = threading.Event()
        self._closed = False
        self.startup_s: float | None = None
        self.restarts = 0
        self._scratch: Path | None = None

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> float:
        """Build the shim, start the zygote and wait until Mathlib is imported."""
        started = time.monotonic()
        build = self.config.build_dir
        build.mkdir(parents=True, exist_ok=True)
        dylib = self._build_shim()
        worker = build / "worker.lean"
        text = render_worker_source()
        if not worker.exists() or worker.read_text(encoding="utf-8") != text:
            worker.write_text(text, encoding="utf-8")
        self._worker, self._dylib = worker, dylib
        self._spawn()
        if not self._ready.wait(self.config.startup_timeout_s):
            self.close()
            raise ResidentUnavailable("resident Lean did not become ready")
        self.startup_s = time.monotonic() - started
        return self.startup_s

    def _build_shim(self) -> Path:
        suffix = ".dylib" if sys.platform == "darwin" else ".so"
        out = self.config.build_dir / f"pals_resident_shim{suffix}"
        if out.exists() and out.stat().st_mtime >= SHIM_SOURCE.stat().st_mtime:
            return out
        include = Path(self.config.lean_binary).resolve().parent.parent / "include"
        candidates = [self.config.c_compiler] if self.config.c_compiler else []
        if sys.platform != "darwin":  # the toolchain's bundled clang has no macOS SDK
            candidates.append(str(Path(self.config.lean_binary).resolve().parent / "leanc"))
        candidates += [shutil.which("cc"), shutil.which("clang")]
        extra = ["-undefined", "dynamic_lookup"] if sys.platform == "darwin" else []
        last = ""
        for compiler in filter(None, candidates):
            tmp = out.with_suffix(out.suffix + f".{secrets.token_hex(4)}")
            result = subprocess.run(
                [compiler, "-shared", "-fPIC", "-O1", "-fvisibility=default", *extra,
                 f"-I{include}", "-o", str(tmp),
                 str(SHIM_SOURCE)],
                capture_output=True, text=True, timeout=120, check=False,
            )
            if result.returncode == 0:
                os.replace(tmp, out)
                return out
            last = result.stderr[-300:]
        raise ResidentUnavailable(f"could not build the resident shim: {last}")

    def _spawn(self) -> None:
        cfg = self.config
        if self._scratch is not None:
            shutil.rmtree(self._scratch, ignore_errors=True)
        self._scratch = Path(cfg.build_dir) / f"zygote-{secrets.token_hex(4)}"
        self._scratch.mkdir(mode=0o700)
        argv = [cfg.lean_binary, f"--load-dynlib={self._dylib}", "--run", str(self._worker)]
        if cfg.launcher is not None:
            argv = cfg.launcher(argv, self._scratch)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LEAN_PATH": cfg.lean_path,
            "HOME": str(self._scratch),
            "TMPDIR": str(self._scratch),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            **({"PALS_RESIDENT_WARM_EXACT": "1"} if cfg.warm_exact else {}),
            **cfg.extra_environment,
        }
        self._ready.clear()
        proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, cwd=str(self._scratch), start_new_session=True, bufsize=0,
        )
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._proc = proc
        threading.Thread(
            target=self._read_loop, args=(proc, generation), daemon=True, name="resident-reader"
        ).start()

    def _read_loop(self, proc: subprocess.Popen[bytes], generation: int) -> None:
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            parts = line.split(" ")
            if line == "PALS_READY":
                self._ready.set()
            elif parts[0] == "FORKED" and len(parts) == 3:
                pending = self._pending.get(parts[1])
                if pending is not None and parts[2].isdigit():
                    pending.pid = int(parts[2])
                    pending.forked.set()
            elif parts[0] == "DONE" and len(parts) == 3:
                pending = self._pending.get(parts[1])
                if pending is not None:
                    pending.code = int(parts[2]) if parts[2].lstrip("-").isdigit() else 70
                    pending.done.set()
            elif parts[0] == "PONG" and len(parts) == 2:
                pending = self._pending.get(parts[1])
                if pending is not None:
                    pending.code = 0
                    pending.forked.set()
                    pending.done.set()
        # EOF: the zygote is gone. In-flight requests become interruptions, then restart.
        with self._lock:
            if self._generation != generation:
                return
            self._proc = None
            self._ready.clear()
            lost = list(self._pending.values())
        for pending in lost:
            pending.forked.set()
            pending.done.set()
        if not self._closed:
            self.restarts += 1
            threading.Thread(target=self._restart, daemon=True, name="resident-restart").start()

    def _restart(self) -> None:
        """Replace a lost zygote: bounded tries with back-off; after that stay unavailable (callers
        use the cold path) instead of spinning on a broken installation."""
        delay = 0.2
        for _ in range(MAX_RESTART_ATTEMPTS):
            if self._closed:
                return
            try:
                self._spawn()
                self._ready.wait(self.config.startup_timeout_s)
                if self._ready.is_set():
                    return
            except OSError:
                pass
            time.sleep(delay)
            delay = min(delay * 2, 10.0)

    def alive(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None and self._ready.is_set()

    def close(self) -> None:
        self._closed = True
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is not None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)  # zygote and any children it started
            proc.wait()
        if self._scratch is not None:
            shutil.rmtree(self._scratch, ignore_errors=True)

    def __enter__(self) -> ResidentLean:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ requests

    def compile(
        self,
        source: Path,
        *,
        workdir: Path,
        olean: Path | None,
        timeout_s: float,
        cancel: threading.Event | None = None,
    ) -> CompileOutcome:
        """``lean [-o olean] source`` in a forked child; the header must be ``import Mathlib``."""
        started = time.monotonic()
        result = workdir / f"resident-{secrets.token_hex(8)}.out"
        code, status = self._run(
            "CHECK", [str(source), str(result), str(olean) if olean else "-"], timeout_s, cancel
        )
        return self._compile_outcome(code, status, result, started)

    def check_statement(
        self, term: str, opens: str = "", *, workdir: Path, timeout_s: float = 30.0
    ) -> tuple[bool, str]:
        """Parse-only allow-list check of one statement term in a fresh child (never elaborated).

        Returns ``(accepted, reason)``; an interruption raises ``ResidentUnavailable``.
        """
        if "\n" in term or "\n" in opens or " " in str(workdir):
            return False, "multi-line input"
        started = time.monotonic()
        request = workdir / f"resident-{secrets.token_hex(8)}.stmt"
        request.write_text(opens + "\n" + term + "\n", encoding="utf-8")
        result = workdir / f"resident-{secrets.token_hex(8)}.out"
        try:
            code, status = self._run("STMT", [str(request), str(result)], timeout_s)
        finally:
            request.unlink(missing_ok=True)
        outcome = self._compile_outcome(code, status, result, started)
        if outcome.aborted or outcome.timed_out:
            raise ResidentUnavailable("statement check interrupted")
        if "PALS_CHECK_OK" in outcome.stdout and "PALS_CHECK_REFUSED" not in outcome.stdout:
            return True, ""
        reason = next(
            (ln for ln in outcome.stdout.splitlines() if "PALS_CHECK_REFUSED" in ln), "no verdict"
        )
        return False, reason.replace("PALS_CHECK_REFUSED", "").strip()

    def audit(
        self, olean: Path, reference: Path, nonce: str, *, workdir: Path, timeout_s: float
    ) -> AuditOutcome:
        """The trusted audit over ``olean`` in a fresh forked child."""
        started = time.monotonic()
        result = workdir / f"resident-{secrets.token_hex(8)}.out"
        code, status = self._run(
            "AUDIT", [nonce, str(olean), str(reference), str(result)], timeout_s
        )
        outcome = self._compile_outcome(code, status, result, started)
        return AuditOutcome(
            outcome.returncode, outcome.stdout, outcome.timed_out, outcome.aborted,
            outcome.unsupported, outcome.output_limited, outcome.elapsed_s,
        )

    def _compile_outcome(
        self, code: int | None, status: str, result: Path, started: float
    ) -> CompileOutcome:
        elapsed = time.monotonic() - started
        if status != "done" or code is None:
            result.unlink(missing_ok=True)
            return CompileOutcome(
                -1, "", timed_out=status == "timeout", aborted=status != "timeout",
                elapsed_s=elapsed,
            )
        if code in UNSUPPORTED_CODES:
            result.unlink(missing_ok=True)
            return CompileOutcome(code, "", unsupported=True, elapsed_s=elapsed)
        text, limited = "", False
        try:
            if result.stat().st_size > self.config.output_limit_bytes:
                limited = True
            else:
                text = result.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return CompileOutcome(-1, "", aborted=True, elapsed_s=elapsed)
        finally:
            result.unlink(missing_ok=True)
        return CompileOutcome(code, text, output_limited=limited, elapsed_s=elapsed)

    def _run(
        self,
        kind: str,
        args: list[str],
        timeout_s: float,
        cancel: threading.Event | None = None,
    ) -> tuple[int | None, str]:
        """Fork one child and wait for it. Status: done | timeout | aborted."""
        if not self.alive():
            raise ResidentUnavailable("resident Lean is not running")
        if not self._slots.acquire(timeout=self.config.queue_timeout_s):
            raise ResidentBusy("no resident Lean slot is free")
        if cancel is not None and cancel.is_set():
            self._slots.release()
            return None, "aborted"
        request_id = secrets.token_hex(8)
        pending = _Pending(kind)
        deadline = time.monotonic() + timeout_s
        cfg = self.config
        try:
            with self._lock:
                proc = self._proc
                if proc is None or proc.stdin is None:
                    raise ResidentUnavailable("resident Lean is not running")
                self._pending[request_id] = pending
                line = " ".join(
                    [kind, request_id, *args, str(cfg.child_memory_bytes),
                     str(cfg.child_cpu_seconds)]
                )
                try:
                    proc.stdin.write(line.encode() + b"\n")
                except OSError:
                    self._pending.pop(request_id, None)
                    raise ResidentUnavailable("resident Lean pipe closed") from None
            if not pending.forked.wait(max(0.0, min(deadline - time.monotonic(), 10.0))):
                return None, "aborted"
            pid = pending.pid
            while True:
                if pending.done.wait(0.05):
                    break
                if cancel is not None and cancel.is_set():
                    self._kill_child(pid)
                    return None, "aborted"
                if time.monotonic() >= deadline:
                    self._kill_child(pid)
                    return None, "timeout"
                if pid and not _alive(pid):
                    # finished without DONE: give the pipe a moment, then call it an interruption
                    if pending.done.wait(0.3):
                        break
                    return None, "aborted"
            if pending.code is None:  # zygote lost while the child ran
                return None, "aborted"
            return pending.code, "done"
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
            self._slots.release()

    @staticmethod
    def _kill_child(pid: int) -> None:
        if pid <= 1:
            return
        for kill, argument in ((os.killpg, pid), (os.kill, pid)):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                kill(argument, signal.SIGKILL)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True

