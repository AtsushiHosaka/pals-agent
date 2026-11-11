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
STABLE_SECONDS: Final = 30.0
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
    # Private memory a child may add (Linux, RLIMIT_DATA).  Measured on the verifier image: a
    # typical child adds 6-220 MB; `exact?` run cold in a child adds 2.0 GB (and 20 s), so 3 GiB
    # bounds the worst honest case.  Four children at the limit would need 12 GiB: size the
    # container for the typical case (zygote + children x ~0.2 GB) and let this limit stop the
    # rest.  See docs/verification/resident-lean-2026-11-12.md for the measurement.
    child_memory_bytes: int = 3 << 30
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
    # Run children confined (Linux): no fork/exec/socket/signal syscalls, writes only under the
    # request's own directory, reads only under `read_roots` and that directory.  Needed before
    # the resident worker may serve untrusted source; the tests turn it on.
    confine: bool = False
    read_roots: tuple[str, ...] = ()
    project_dir: Path | None = None  # the verifier binds to this (see LeanVerifier)
    request_root: Path | None = None  # the tree the request directories live under
    # Linux only: let an UNCONFINED resident exist.  The default refuses to construct one,
    # because its children would run untrusted tactics without Landlock/seccomp.  For development
    # and for tests that do not exercise confinement.
    allow_unconfined: bool = False
    prebuilt_shim: Path | None = None
    allow_shim_compile: bool = True
    fsize_bytes: int = 16 << 20  # RLIMIT_FSIZE of a child, like the cold path's 16 MiB


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
    abandoned: bool = False


class ResidentLean:
    def __init__(self, config: ResidentConfig) -> None:
        if sys.platform.startswith("linux") and not config.confine and not config.allow_unconfined:
            raise ValueError(
                "on Linux the resident Lean must be confined (confine=True); "
                "allow_unconfined=True is for development only"
            )
        self.config = config
        self._lock = threading.Lock()  # guards _proc/_pending/_children and stdin writes
        self._slots = threading.BoundedSemaphore(config.max_children)
        self._proc: subprocess.Popen[bytes] | None = None
        self._pending: dict[str, _Pending] = {}
        self._children: set[int] = set()  # pids (= process group ids) of running request children
        self._ready = threading.Event()
        self._first_ready = threading.Event()
        self._closed = False
        self._given_up = False
        self._supervisor: threading.Thread | None = None
        self._scratch: Path | None = None
        self.startup_s: float | None = None
        self.restarts = 0
        # how requests ended, for callers that must know the resident really served them
        self.stats = {"served": 0, "aborted": 0, "timed_out": 0, "unsupported": 0}

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> float:
        """Build the shim, start the supervisor and wait until Mathlib is imported once."""
        started = time.monotonic()
        build = self.config.build_dir
        build.mkdir(parents=True, exist_ok=True)
        if self.config.confine:
            ok, reason = confinement_available()
            if not ok:
                raise ResidentUnavailable(f"confinement is not available: {reason}")
        self._dylib = self._build_shim()
        worker = build / "worker.lean"
        text = render_worker_source()
        if not worker.exists() or worker.read_text(encoding="utf-8") != text:
            worker.write_text(text, encoding="utf-8")
        self._worker = worker
        self._supervisor = threading.Thread(
            target=self._supervise, daemon=True, name="resident-supervisor"
        )
        self._supervisor.start()
        deadline = time.monotonic() + self.config.startup_timeout_s * MAX_RESTART_ATTEMPTS
        while time.monotonic() < deadline:
            if self._first_ready.wait(0.2):
                if self.config.confine:
                    self._confinement_self_test()  # closes and raises if a child is not confined
                self.startup_s = time.monotonic() - started
                return self.startup_s
            if self._given_up:
                break
        self.close()
        raise ResidentUnavailable("resident Lean did not become ready")

    def _confinement_self_test(self) -> None:
        """Prove, with a real child, that confinement holds before anything is served.

        One request directory may be written, a second one (another request's) may not (Landlock,
        read from the file system), and a child may not start a process (seccomp, EPERM).
        """
        root = self.config.request_root
        assert root is not None
        own = root / f"pals-selftest-{secrets.token_hex(4)}"
        other = root / f"pals-selftest-{secrets.token_hex(4)}"
        own.mkdir(mode=0o700)
        other.mkdir(mode=0o700)
        try:
            source = own / "Main.lean"
            source.write_text(
                "import Mathlib\n"
                f'#eval show IO Unit from IO.FS.writeFile "{own}/ok" "x"\n'
                f'#eval show IO Unit from IO.FS.writeFile "{other}/no" "x"\n'
                # seccomp: starting a process (exec) must be refused with EPERM
                '#eval show IO Unit from do discard <| IO.Process.output {cmd := "/bin/true"}\n',
                encoding="utf-8",
            )
            outcome = self.compile(source, workdir=own, olean=None, timeout_s=60)
            confined = (
                not outcome.aborted
                and (own / "ok").is_file()
                and not (other / "no").exists()
                and "permission denied" in outcome.stdout  # Landlock
                and "not permitted" in outcome.stdout  # seccomp
            )
        finally:
            shutil.rmtree(own, ignore_errors=True)
            shutil.rmtree(other, ignore_errors=True)
        if not confined:
            self.close()
            raise ResidentUnavailable("the resident children are not confined")

    def _build_shim(self) -> Path:
        cfg = self.config
        if cfg.prebuilt_shim is not None:
            if not cfg.prebuilt_shim.is_file():
                raise ResidentUnavailable("the prebuilt resident shim is missing")
            return cfg.prebuilt_shim
        suffix = ".dylib" if sys.platform == "darwin" else ".so"
        out = cfg.build_dir / f"pals_resident_shim{suffix}"
        if out.exists() and out.stat().st_mtime >= SHIM_SOURCE.stat().st_mtime:
            return out
        if not cfg.allow_shim_compile:
            raise ResidentUnavailable("no prebuilt shim and compiling is not allowed")
        compile_shim(cfg.lean_binary, out, cfg.c_compiler)
        return out

    def _spawn_one(self) -> subprocess.Popen[bytes]:
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
            **({"PALS_RESIDENT_CONFINE": "1"} if cfg.confine else {}),
            **({"PALS_RESIDENT_READ_ROOTS": ":".join(cfg.read_roots)} if cfg.read_roots else {}),
            **(
                {"PALS_RESIDENT_REQUEST_ROOT": str(cfg.request_root.resolve())}
                if cfg.request_root is not None else {}
            ),
            **cfg.extra_environment,
        }
        return subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, cwd=str(self._scratch), start_new_session=True, bufsize=0,
            preexec_fn=_die_with_parent if sys.platform.startswith("linux") else None,
        )

    def _supervise(self) -> None:
        """The only owner of zygote lifetimes: one spawn at a time, bounded consecutive failures,
        back-off, and every failed or lost zygote is killed and reaped before the next one."""
        failures = 0
        while not self._closed:
            self._ready.clear()
            try:
                proc = self._spawn_one()
            except OSError:
                proc = None
            ready_at = None
            if proc is not None:
                with self._lock:
                    self._proc = proc
                reader = threading.Thread(
                    target=self._read_loop, args=(proc,), daemon=True, name="resident-reader"
                )
                reader.start()
                if self._ready.wait(self.config.startup_timeout_s):
                    ready_at = time.monotonic()
                    self._first_ready.set()
                    proc.wait()  # until it dies, or close() kills it
                self._lose(proc)
                reader.join(timeout=2.0)
            if self._closed:
                return
            self.restarts += 1
            stable = ready_at is not None and time.monotonic() - ready_at >= STABLE_SECONDS
            failures = 0 if stable else failures + 1
            if failures >= MAX_RESTART_ATTEMPTS:
                self._given_up = True  # a broken installation: stay unavailable, callers go cold
                return
            time.sleep(min(0.2 * 2**failures, 10.0))

    def _lose(self, proc: subprocess.Popen[bytes]) -> None:
        """The zygote is gone or must go: kill it and every child, fail what was in flight."""
        with self._lock:
            if self._proc is proc:
                self._proc = None
            self._ready.clear()
            children, self._children = set(self._children), set()
            lost = list(self._pending.values())
        _kill_group(proc.pid)
        for pid in children:
            _kill_group(pid)
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)
        for pending in lost:
            pending.forked.set()
            pending.done.set()

    def _read_loop(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            parts = raw.decode("utf-8", "replace").strip().split(" ")
            if parts == ["PALS_READY"]:
                self._ready.set()
            elif parts[0] == "FORKED" and len(parts) == 3 and parts[2].isdigit():
                pid = int(parts[2])
                with self._lock:
                    pending = self._pending.get(parts[1])
                    if pending is None or pending.abandoned or self._closed:
                        self._pending.pop(parts[1], None)
                        kill_now = True
                    else:
                        self._children.add(pid)
                        pending.pid = pid
                        kill_now = False
                if kill_now:  # a late acknowledgement for a request nobody waits for any more
                    _kill_group(pid)
                elif pending is not None:
                    pending.forked.set()
            elif parts[0] == "DONE" and len(parts) == 3:
                with self._lock:
                    pending = self._pending.get(parts[1])
                    if pending is not None:
                        self._children.discard(pending.pid)
                if pending is not None:
                    pending.code = int(parts[2]) if parts[2].lstrip("-").isdigit() else 70
                    pending.done.set()
            elif parts[0] == "PONG" and len(parts) == 2:
                pending = self._pending.get(parts[1])
                if pending is not None:
                    pending.code = 0
                    pending.forked.set()
                    pending.done.set()

    def alive(self) -> bool:
        with self._lock:
            proc = self._proc
            return (
                proc is not None and proc.poll() is None and self._ready.is_set()
                and not self._closed
            )

    def close(self) -> None:
        self._closed = True
        with self._lock:
            proc = self._proc
            children, self._children = set(self._children), set()
        for pid in children:
            _kill_group(pid)
        if proc is not None:
            _kill_group(proc.pid)  # wakes the supervisor
        if self._supervisor is not None and self._supervisor is not threading.current_thread():
            self._supervisor.join(timeout=10.0)
        if proc is not None:
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)
        if self._scratch is not None:
            shutil.rmtree(self._scratch, ignore_errors=True)

    def __enter__(self) -> ResidentLean:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ requests

    def _check_workdir(self, workdir: Path) -> None:
        """The request directory: no spaces (the protocol is line based), and with confinement
        inside ``request_root`` (the only tree the zygote may write)."""
        text = str(workdir)
        if not workdir.is_absolute() or " " in text or "\n" in text:
            raise ValueError("a request directory must be an absolute path without spaces")
        root = self.config.request_root
        if self.config.confine and (
            root is None or not workdir.resolve().is_relative_to(root.resolve())
        ):
            raise ValueError("a confined request directory must lie under the request root")

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
            "CHECK", [str(source), str(result), str(olean) if olean else "-"], timeout_s, cancel,
            workdir=workdir,
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
            code, status = self._run(
                "STMT", [str(request), str(result)], timeout_s, workdir=workdir
            )
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
            "AUDIT", [nonce, str(olean), str(reference), str(result)], timeout_s, workdir=workdir
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
        if status == "timeout":
            self.stats["timed_out"] += 1
        elif status != "done" or code is None:
            self.stats["aborted"] += 1
        elif code in UNSUPPORTED_CODES:
            self.stats["unsupported"] += 1
        else:
            self.stats["served"] += 1
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
        *,
        workdir: Path,
    ) -> tuple[int | None, str]:
        """Fork one child and wait for it. Status: done | timeout | aborted."""
        self._check_workdir(workdir)
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
        keep_pending = False
        try:
            with self._lock:
                proc = self._proc
                if proc is None or proc.stdin is None:
                    raise ResidentUnavailable("resident Lean is not running")
                self._pending[request_id] = pending
                line = " ".join(
                    [kind, request_id, *args, str(cfg.child_memory_bytes),
                     str(cfg.child_cpu_seconds), str(cfg.fsize_bytes), str(workdir)]
                )
                try:
                    proc.stdin.write(line.encode() + b"\n")
                except OSError:
                    self._pending.pop(request_id, None)
                    raise ResidentUnavailable("resident Lean pipe closed") from None
            if not pending.forked.wait(max(0.0, min(deadline - time.monotonic(), 10.0))):
                pending.abandoned = True  # a late FORKED for it is killed by the reader
                keep_pending = True
                return None, "aborted"
            pid = pending.pid
            while True:
                if pending.done.wait(0.05):
                    break
                if cancel is not None and cancel.is_set():
                    _kill_group(pid)
                    return None, "aborted"
                if time.monotonic() >= deadline:
                    _kill_group(pid)
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
                if not keep_pending:
                    self._pending.pop(request_id, None)
                self._children.discard(pending.pid)
            self._slots.release()


def _kill_group(pid: int) -> None:
    """SIGKILL a request child's process group (its pid is its group id), then the pid itself."""
    if pid <= 1:
        return
    for kill in (os.killpg, os.kill):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            kill(pid, signal.SIGKILL)


def _die_with_parent() -> None:
    """Linux: the zygote gets SIGKILL when the manager's thread dies (no orphaned Mathlib)."""
    import ctypes

    ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG


def compile_shim(lean_binary: str, out: Path, c_compiler: str | None = None) -> None:
    """Build the C part of the worker (needs a C compiler and the toolchain's ``lean.h``).

    Run this at image build time and pass the result as ``ResidentConfig.prebuilt_shim``: the
    verifier then needs neither a compiler nor a writable directory at run time.
    """
    include = Path(lean_binary).resolve().parent.parent / "include"
    candidates = [c_compiler] if c_compiler else []
    if sys.platform != "darwin":  # the toolchain's bundled clang has no macOS SDK
        candidates.append(str(Path(lean_binary).resolve().parent / "leanc"))
    candidates += [shutil.which("cc"), shutil.which("clang")]
    extra = ["-undefined", "dynamic_lookup"] if sys.platform == "darwin" else []
    last = ""
    out.parent.mkdir(parents=True, exist_ok=True)
    for compiler in filter(None, candidates):
        tmp = out.with_suffix(out.suffix + f".{secrets.token_hex(4)}")
        result = subprocess.run(
            [compiler, "-shared", "-fPIC", "-O1", "-fvisibility=default", *extra,
             f"-I{include}", "-o", str(tmp), str(SHIM_SOURCE)],
            capture_output=True, text=True, timeout=120, check=False,
        )
        if result.returncode == 0:
            os.replace(tmp, out)
            return
        last = result.stderr[-300:]
    raise ResidentUnavailable(f"could not build the resident shim: {last}")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True



def default_read_roots(lean_binary: str, lean_path: str) -> tuple[str, ...]:
    """What a confined child may read: the toolchain, the import directories, system libraries."""
    toolchain = Path(lean_binary).resolve().parent.parent
    roots = [str(toolchain), *(p for p in lean_path.split(os.pathsep) if p)]
    roots += ["/lib", "/lib64", "/usr/lib", "/usr/lib64", "/etc/ld.so.cache"]
    roots += ["/proc", "/sys/devices"]
    return tuple(dict.fromkeys(roots))


def confinement_available() -> tuple[bool, str]:
    """Can this host confine children (Linux with Landlock and libseccomp)?  ``(ok, reason)``.

    A deployment keeps the resident flag off when this is false; ``ResidentLean.start`` also
    checks it, and then proves confinement with a real child (``_confinement_self_test``).
    """
    if not sys.platform.startswith("linux"):
        return False, "confinement needs Linux"
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    abi = libc.syscall(444, ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint(1))
    if abi < 1:
        return False, "Landlock is not available in this kernel or sandbox"
    try:
        ctypes.CDLL("libseccomp.so.2")
    except OSError:
        return False, "libseccomp.so.2 is not installed"
    return True, f"Landlock ABI {abi}, libseccomp present"
