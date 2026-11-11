from __future__ import annotations

import ctypes
import math
import os
import re
import secrets
import selectors
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from pals_agent.lean_audit import (
    TRUSTED_AUDIT_SOURCE,
    AuditReport,
    audit_diagnostics,
    audit_failure,
    parse_audit_report,
    statement_mismatch,
)
from pals_agent.lean_environment import (
    LakeEnvironmentCache,
    VerificationTiming,
    environment_identity,
    materialize_lake_environment,
    parse_lake_environment,
)
from pals_agent.lean_import_plan import APPLIED, ImportPlanning, retried_status
from pals_agent.lean_profiles import LibraryProfile
from pals_agent.lean_source_policy import (
    declared_theorem_names,
    find_source_violation,
    statement_reference,
    strip_lean_comments_and_strings,
    with_auditable_examples,
)
from pals_agent.models import Diagnostic, VerificationResult

_PLACEHOLDER_RE = re.compile(
    r"(^|[^A-Za-z0-9_])(sorryAx|sorry|admit)([^A-Za-z0-9_]|$)"
)
_SORRY_REPORT_RE = re.compile(
    r"\bdeclaration\s+uses\s+[`'\"\u2018\u2019\u201c\u201d]?sorry[`'\"\u2018\u2019\u201c\u201d]?",
    re.IGNORECASE,
)
_TRUSTED_DECLARATION_RE = re.compile(
    r"(^|[^A-Za-z0-9_])(axiom|constant|opaque|unsafe)([^A-Za-z0-9_]|$)"
)
_DIAGNOSTIC_RE = re.compile(
    r"^(?P<file>.*?):(?P<line>\d+):(?P<column>\d+): "
    r"(?P<severity>error|warning)(?:\((?P<diagnostic_code>[^)]+)\))?: "
    r"(?P<message>.*)$"
)
_MIB = 1024 * 1024
_GIB = 1024 * _MIB
_ADDRESS_SPACE_LIMIT_BYTES = 16 * _GIB
_FILE_SIZE_LIMIT_BYTES = 16 * _MIB
# RLIMIT_NPROC counts every process of the UID on the host, and all containers there share one UID,
# so a low value makes Lean fail on the other containers' threads. The per-container bound is the
# 64-process cgroup limit that the verifier boundary attests; this only stops a runaway elsewhere.
_PROCESS_LIMIT = 4096
_OPEN_FILE_LIMIT = 1024
_OUTPUT_LIMIT_BYTES = _MIB
_DEFAULT_CHILD_PATH = "/opt/elan/bin:/usr/local/bin:/usr/bin:/bin"
_DEFAULT_ELAN_HOME = "/opt/elan"
_SUPERVISOR_SCRIPT = Path(__file__).with_name("lean_supervisor.py")
_SUPERVISOR_GRACE_SECONDS = 5.0
_DRAIN_GRACE_SECONDS = 0.2
_SUPERVISOR_STATUS_RE = re.compile(rb"(-?\d{1,4}) ([01])\n")
_CGROUP_MEMORY_EVENTS = Path("/sys/fs/cgroup/memory.events")
_CGROUP_PIDS_EVENTS = Path("/sys/fs/cgroup/pids.events")
COMPILE_INTERRUPTED = "lean.compile_interrupted"
COMPILE_DEADLINE_INTERRUPTED = "lean.compile_deadline_interrupted"
_ACTIVE_SUPERVISORS: set[int] = set()
_ACTIVE_SUPERVISORS_LOCK = threading.Lock()
_REAP_ORPHANS = False


class LeanCompileInterrupted(Exception):
    """The compile was killed from outside its proof, so its outcome says nothing about it."""


class LeanCompileDeadlineInterrupted(LeanCompileInterrupted):
    """The deadline passed under cgroup pressure, so a retry may cost another full compile."""


@dataclass(frozen=True, slots=True)
class LeanVerifier:
    lean_binary: str = "lean"
    lake_binary: str = "lake"
    project_dir: Path | None = None
    timeout_seconds: float = 300.0
    output_limit_bytes: int = _OUTPUT_LIMIT_BYTES
    child_path: str = _DEFAULT_CHILD_PATH
    elan_home: str = _DEFAULT_ELAN_HOME
    scratch_dir: Path = Path("/tmp")
    lake_environment_cache: LakeEnvironmentCache | None = None
    timing_observer: Callable[[VerificationTiming], None] | None = None
    # Recipe admission receipts attest the literal `lake env lean --threads=1 Main.lean`, so that
    # exact command runs first and the audit artifact comes from a separate compile.
    literal_admission_command: bool = False
    # None keeps the unrestricted default profile; see ``pals_agent.lean_profiles``.
    library_profile: LibraryProfile | None = None
    # Opt-in (``None`` = off): verify over a proposed small import header and, when that fails the
    # way a missing import does, once more over the source as written. See ``lean_import_plan``.
    import_planning: ImportPlanning | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "scratch_dir", Path(self.scratch_dir))
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("Lean timeout must be a positive finite number")
        if type(self.output_limit_bytes) is not int or self.output_limit_bytes < 1:
            raise ValueError("Lean output limit must be a positive integer")
        if not self.child_path or not self.elan_home:
            raise ValueError("Lean child PATH and ELAN_HOME must not be empty")
        if not self.scratch_dir.is_absolute():
            raise ValueError("Lean scratch directory must be absolute")

    def verify(self, lean_code: str) -> VerificationResult:
        return self._timed_verify(lean_code, allow_sorry=False)

    def verify_sketch(self, lean_code: str) -> VerificationResult:
        return self._timed_verify(lean_code, allow_sorry=True)

    def _timed_verify(self, lean_code: str, *, allow_sorry: bool) -> VerificationResult:
        started = time.monotonic()
        try:
            if self.import_planning is None:
                return self._verify(lean_code, allow_sorry=allow_sorry)
            return self._verify_over_import_plan(
                self.import_planning, lean_code, allow_sorry=allow_sorry
            )
        except LeanCompileInterrupted as error:
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        code=(
                            COMPILE_DEADLINE_INTERRUPTED
                            if isinstance(error, LeanCompileDeadlineInterrupted)
                            else COMPILE_INTERRUPTED
                        ),
                        message=str(error),
                    )
                ],
                stdout="",
                stderr="",
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        finally:
            self._observe("total", started)

    def _verify_over_import_plan(
        self, planning: ImportPlanning, lean_code: str, *, allow_sorry: bool
    ) -> VerificationResult:
        planning_started = time.monotonic()
        planned = planning.prepare(lean_code, self.library_profile)
        if planned.source is None:
            self._observe_import_plan(planned.status, planning_started, None)
            return self._verify(lean_code, allow_sorry=allow_sorry)
        result = self._verify(lean_code, allow_sorry=allow_sorry, compile_source=planned.source)
        reason = planning.retry_reason(result)
        if reason is None:
            self._observe_import_plan(APPLIED, planning_started, planned.loaded_modules)
            return result
        self._observe_import_plan(
            retried_status(reason), planning_started, planned.loaded_modules
        )
        # One more verification, over every import the source wrote, within what is left of the
        # one deadline a request has.
        remaining = float(self.timeout_seconds) - (time.monotonic() - planning_started)
        if remaining <= 0:
            return result
        return self._verify(lean_code, allow_sorry=allow_sorry, timeout_seconds=remaining)

    def _observe_import_plan(self, status: str | None, started: float, modules: int | None) -> None:
        if self.timing_observer is not None and status is not None:
            self.timing_observer(VerificationTiming(
                stage="import_plan", elapsed_ms=(time.monotonic() - started) * 1000,
                import_plan=status, import_plan_modules=modules,
            ))

    def _observe(self, stage: str, started: float, status: str | None = None) -> None:
        if status is not None:
            from pals_agent import step_timing

            step_timing.record_step(
                "lean_env_cache", (time.monotonic() - started) * 1000, outcome=status,
            )
        if self.timing_observer is not None:
            self.timing_observer(VerificationTiming(
                stage=stage, elapsed_ms=(time.monotonic() - started) * 1000,
                cache_status=status,
            ))

    def _verify(
        self,
        lean_code: str,
        *,
        allow_sorry: bool,
        compile_source: str | None = None,
        timeout_seconds: float | None = None,
    ) -> VerificationResult:
        """Verify ``lean_code``; ``compile_source`` is the same source with another import header.

        Every policy check runs on the source as written and again on what is compiled, so a
        header rewritten by an import plan can never hide an import the profile forbids.
        """
        budget = float(self.timeout_seconds if timeout_seconds is None else timeout_seconds)
        source = lean_code if compile_source is None else compile_source
        checked_code = _strip_lean_comments_and_strings(lean_code)

        placeholder = _PLACEHOLDER_RE.search(checked_code)
        if placeholder and (not allow_sorry or placeholder.group(2) != "sorry"):
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        code="lean.disallowed_placeholder",
                        message=f"Generated Lean code contains `{placeholder.group(2)}`.",
                    )
                ],
                stdout="",
                stderr="",
                elapsed_ms=0,
            )

        trusted_declaration = _TRUSTED_DECLARATION_RE.search(checked_code)
        if trusted_declaration:
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        code="lean.disallowed_trusted_declaration",
                        message=(
                            "Generated Lean code contains trusted declaration "
                            f"`{trusted_declaration.group(2)}`."
                        ),
                    )
                ],
                stdout="",
                stderr="",
                elapsed_ms=0,
            )

        violation = None
        for checked in dict.fromkeys((lean_code, source)):
            violation = find_source_violation(checked)
            if violation is None and self.library_profile is not None:
                violation = self.library_profile.import_violation(checked)
            if violation is not None:
                break
        if violation is not None:
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(severity="error", code=violation.code, message=violation.message)
                ],
                stdout="",
                stderr="",
                elapsed_ms=0,
            )

        lean_binary = shutil.which(self.lean_binary)
        if lean_binary is None:
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        code="lean.not_found",
                        message="Lean binary was not found in the verifier boundary.",
                    )
                ],
                stdout="",
                stderr="",
                elapsed_ms=0,
            )
        if self.project_dir is not None and not self.project_dir.exists():
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        code="lean.project_not_found",
                        message=f"Lean project directory was not found: {self.project_dir}",
                    )
                ],
                stdout="",
                stderr="",
                elapsed_ms=0,
            )
        lake_binary = shutil.which(self.lake_binary) if self.project_dir is not None else None
        if self.project_dir is not None and lake_binary is None:
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        code="lake.not_found",
                        message="Lake binary was not found in the verifier boundary.",
                    )
                ],
                stdout="",
                stderr="",
                elapsed_ms=0,
            )

        if sys.platform.startswith("linux") and shutil.which("prlimit") is None:
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        code="lean.prlimit_not_found",
                        message="Lean resource limiter is unavailable.",
                    )
                ],
                stdout="",
                stderr="",
                elapsed_ms=0,
            )

        with TemporaryDirectory(prefix="pals-lean-", dir=self.scratch_dir) as tmpdir:
            temporary_dir = Path(tmpdir)
            home_dir = temporary_dir / "home"
            home_dir.mkdir(mode=0o700)
            lean_file = temporary_dir / "Main.lean"
            lean_file.write_text(source, encoding="utf-8")
            lean_file.chmod(0o400)
            # A sketch contains holes by construction and never becomes a verified result.
            audited = not allow_sorry
            # Receipts attest the literal command, and an `example` leaves no constant to audit.
            audit_source = with_auditable_examples(source)
            separate_audit_compile = (
                self.literal_admission_command or audit_source != source
            )
            olean_file = temporary_dir / "Main.olean"
            command, cwd = self._command_for(
                lean_file,
                lean_binary=lean_binary,
                lake_binary=lake_binary,
                olean_file=olean_file if audited and not separate_audit_compile else None,
            )
            child_environment = self._child_environment(temporary_dir, home_dir)

            started_at = time.monotonic()
            deadline = started_at + budget
            command, child_environment = self._reuse_environment(
                command, child_environment, lean_binary=lean_binary,
                lake_binary=lake_binary, temporary_dir=temporary_dir, deadline=deadline,
            )
            remaining = (
                budget if self.lake_environment_cache is None
                else deadline - time.monotonic()
            )
            compile_started = time.monotonic()
            if remaining <= 0:
                completed = _ProcessResult(-signal.SIGKILL, "", "", True, False)
            else:
                limited_command = _limited_command(
                    command, timeout_seconds=remaining, scratch_dir=temporary_dir,
                )
                completed = _run_limited_process(
                    limited_command,
                    cwd=cwd,
                    environment=child_environment,
                    timeout_seconds=remaining,
                    output_limit_bytes=self.output_limit_bytes,
                )
            self._observe("compile", compile_started)
            audit_result: list[Diagnostic] = []
            if audited and _compiler_accepted(completed):
                audit_started = time.monotonic()
                audit_result = self._run_trusted_audit(
                    source,
                    separate_compile_source=audit_source if separate_audit_compile else None,
                    olean_file=olean_file,
                    command=command,
                    cwd=cwd,
                    environment=child_environment,
                    lean_binary=lean_binary,
                    lake_binary=lake_binary,
                    temporary_dir=temporary_dir,
                    deadline=deadline,
                )
                self._observe("audit", audit_started)

        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        stderr = completed.stderr
        stdout = completed.stdout
        if completed.timed_out:
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        code="lean.timeout",
                        message=f"Lean timed out after {budget:.1f}s.",
                    )
                ],
                stdout=stdout,
                stderr=stderr,
                elapsed_ms=elapsed_ms,
            )
        if completed.output_limited:
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        code="lean.output_limit",
                        message="Lean exceeded the combined output limit.",
                    )
                ],
                stdout=stdout,
                stderr=stderr,
                elapsed_ms=elapsed_ms,
            )
        if completed.returncode == 125:
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        code="lean.sandbox_setup_failed",
                        message="Lean child isolation could not be established.",
                    )
                ],
                stdout="",
                stderr="",
                elapsed_ms=elapsed_ms,
            )
        compiler_output = f"{stdout}\n{stderr}"
        diagnostics = parse_lean_diagnostics(compiler_output)
        if allow_sorry:
            diagnostics = [
                diagnostic
                for diagnostic in diagnostics
                if diagnostic.code != "lean.declaration_uses_sorry"
            ]
        if not allow_sorry and _SORRY_REPORT_RE.search(compiler_output) and not any(
            diagnostic.code == "lean.declaration_uses_sorry" for diagnostic in diagnostics
        ):
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="lean.declaration_uses_sorry",
                    message="Lean reported that a declaration uses `sorry`.",
                )
            )
        success = completed.returncode == 0 and not any(
            diagnostic.severity == "error" for diagnostic in diagnostics
        )
        # An audit that only records (a recording profile's trust level) never fails the proof;
        # every other audit diagnostic is an error.
        audit_errors = [item for item in audit_result if item.severity == "error"]
        if success and audit_errors:
            success = False
            diagnostics.extend(audit_result)
        if success:
            diagnostics.append(
                Diagnostic(
                    severity="info",
                    code="lean.verified",
                    message="Lean accepted the generated code.",
                )
            )
            diagnostics.extend(audit_result)
        elif not diagnostics:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="lean.failed",
                    message=f"Lean exited with status {completed.returncode}.",
                )
            )

        return VerificationResult(
            success=success,
            diagnostics=diagnostics,
            stdout=stdout,
            stderr=stderr,
            elapsed_ms=elapsed_ms,
        )

    def _reuse_environment(
        self, command: list[str], base: dict[str, str], *, lean_binary: str,
        lake_binary: str | None, temporary_dir: Path, deadline: float,
    ) -> tuple[list[str], dict[str, str]]:
        delta, _ = self._lake_environment_delta(
            base, lean_binary=lean_binary, lake_binary=lake_binary,
            temporary_dir=temporary_dir, deadline=deadline,
        )
        if delta is None:
            # Optimization unavailable: execute the original bounded compiler path.
            # No result, environment or admission status is fabricated or cached.
            return command, base
        return command[command.index(lean_binary) :], materialize_lake_environment(base, delta)

    def _lake_environment_delta(
        self, base: dict[str, str], *, lean_binary: str, lake_binary: str | None,
        temporary_dir: Path, deadline: float,
    ) -> tuple[dict[str, str] | None, str]:
        """Return the reviewed Lake delta and ``miss``/``hit``, or ``None`` and ``fallback``."""
        cache = self.lake_environment_cache
        if cache is None or self.project_dir is None or lake_binary is None:
            return None, "disabled"
        project_dir = self.project_dir
        started = time.monotonic()
        status = "fallback"
        try:
            identity_started = time.monotonic()
            key = environment_identity(project_dir, lean_binary, lake_binary, base)
            self._observe("environment_identity", identity_started)

            def prepare() -> dict[str, str]:
                remaining = min(10.0, deadline - time.monotonic())
                if remaining <= 0:
                    raise TimeoutError("Lake preparation deadline expired")
                env_binary = shutil.which("env", path=self.child_path)
                if env_binary is None:
                    raise ValueError("environment reader unavailable")
                result = _run_limited_process(
                    _limited_command(
                        [lake_binary, "env", env_binary, "-0"],
                        timeout_seconds=remaining, scratch_dir=temporary_dir,
                    ),
                    cwd=project_dir, environment=base,
                    timeout_seconds=remaining,
                    output_limit_bytes=min(self.output_limit_bytes, 65_536),
                )
                if result.returncode or result.timed_out or result.output_limited or result.stderr:
                    raise ValueError("Lake preparation failed")
                delta = parse_lake_environment(result.stdout, base)
                if key != environment_identity(project_dir, lean_binary, lake_binary, base):
                    raise ValueError("Lake configuration changed during preparation")
                return delta

            delta, status = cache.get_or_prepare(
                key, prepare, timeout_seconds=max(0.0, deadline - time.monotonic()),
            )
            return delta, status
        except (OSError, ValueError, KeyError, TypeError, TimeoutError):
            return None, "fallback"
        finally:
            self._observe("environment_prepare", started, status)

    def warm_lake_environment(self) -> str:
        """Resolve Lake's environment once before serving; no source is compiled.

        Returns ``miss`` (resolved now), ``hit``, ``fallback`` (requests will run the original
        ``lake env lean`` command) or ``disabled``. A startup caller can therefore see that the
        reuse flag is ineffective, and the first request no longer pays for the preparation.
        """
        if self.lake_environment_cache is None or self.project_dir is None:
            return "disabled"
        lean_binary = shutil.which(self.lean_binary)
        lake_binary = shutil.which(self.lake_binary)
        if lean_binary is None or lake_binary is None or not self.project_dir.exists():
            return "fallback"
        deadline = time.monotonic() + float(self.timeout_seconds)
        with TemporaryDirectory(prefix="pals-lean-", dir=self.scratch_dir) as tmpdir:
            temporary_dir = Path(tmpdir)
            home_dir = temporary_dir / "home"
            home_dir.mkdir(mode=0o700)
            _, status = self._lake_environment_delta(
                self._child_environment(temporary_dir, home_dir),
                lean_binary=lean_binary, lake_binary=lake_binary,
                temporary_dir=temporary_dir, deadline=deadline,
            )
        return status

    def _child_environment(self, temporary_dir: Path, home_dir: Path) -> dict[str, str]:
        return {
            "PATH": self.child_path,
            "HOME": str(home_dir),
            "TMPDIR": str(temporary_dir),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "ELAN_HOME": self.elan_home,
        }

    def _command_for(
        self,
        lean_file: Path,
        *,
        lean_binary: str,
        lake_binary: str | None,
        olean_file: Path | None = None,
    ) -> tuple[list[str], Path | None]:
        # Lean derives the module name for `-o` from its root; the scratch file lies outside cwd.
        output = (
            [f"--root={lean_file.parent}", "-o", str(olean_file)] if olean_file is not None else []
        )
        if self.project_dir is not None:
            if lake_binary is None:
                raise AssertionError("validated Lake binary is required")
            return [
                lake_binary,
                "env",
                lean_binary,
                *output,
                "--threads=1",
                str(lean_file),
            ], self.project_dir
        return [lean_binary, *output, "--threads=1", str(lean_file)], None

    def _run_trusted_audit(
        self,
        lean_code: str,
        *,
        separate_compile_source: str | None,
        olean_file: Path,
        command: list[str],
        cwd: Path | None,
        environment: dict[str, str],
        lean_binary: str,
        lake_binary: str | None,
        temporary_dir: Path,
        deadline: float,
    ) -> list[Diagnostic]:
        """Check the compiled artifact in a process that runs no candidate code."""

        def run(arguments: list[str]) -> _ProcessResult | list[Diagnostic]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return [self._audit_timeout()]
            result = _run_limited_process(
                _limited_command(arguments, timeout_seconds=remaining, scratch_dir=temporary_dir),
                cwd=cwd,
                environment=environment,
                timeout_seconds=remaining,
                output_limit_bytes=self.output_limit_bytes,
            )
            if result.timed_out:
                return [self._audit_timeout()]
            if result.output_limited:
                return [
                    Diagnostic(
                        severity="error",
                        code="lean.output_limit",
                        message="Lean exceeded the combined output limit.",
                    )
                ]
            return result

        audit_dir = temporary_dir / f"audit-{secrets.token_hex(16)}"
        audit_dir.mkdir(mode=0o700)
        if separate_compile_source is not None:
            candidate = audit_dir / "Candidate.lean"
            candidate.write_text(separate_compile_source, encoding="utf-8")
            candidate.chmod(0o400)
            olean_file = audit_dir / "Candidate.olean"
            artifact_command, _ = self._command_for(
                candidate,
                lean_binary=lean_binary,
                lake_binary=lake_binary,
                olean_file=olean_file,
            )
            compiled = run(artifact_command)
            if isinstance(compiled, list):
                return compiled
            if not _compiler_accepted(compiled):
                return [audit_failure("Lean did not compile the audit artifact.")]
        if olean_file.is_symlink() or not olean_file.is_file():
            return [audit_failure("Lean exited without writing a compiled module.")]

        reference = statement_reference(separate_compile_source or lean_code)
        if reference is None or find_source_violation(reference) is not None:
            return [statement_mismatch("A statement could not be read from the written source.")]
        reference_file = audit_dir / "Statements.lean"
        reference_file.write_text(reference, encoding="utf-8")
        reference_file.chmod(0o400)

        nonce = secrets.token_hex(32)
        audit_file = audit_dir / "Audit.lean"
        audit_file.write_text(
            TRUSTED_AUDIT_SOURCE
            if self.library_profile is None
            else self.library_profile.audit_source,
            encoding="utf-8",
        )
        audit_file.chmod(0o400)
        lean_arguments = [
            lean_binary,
            "--threads=1",
            "--run",
            str(audit_file),
            nonce,
            str(olean_file),
            str(reference_file),
        ]
        audited = run(
            [lake_binary, "env", *lean_arguments]
            if lake_binary is not None and command[0] == lake_binary
            else lean_arguments
        )
        if isinstance(audited, list):
            return audited
        report = parse_audit_report(audited.stdout, nonce) if audited.returncode == 0 else None
        if report is None:
            return [audit_failure("Trusted Lean audit did not complete for this request.")]
        return self._audit_policy(report, lean_code)

    def _audit_policy(self, report: AuditReport, lean_code: str) -> list[Diagnostic]:
        """The audit policy under this verifier's profile (default profile: the audit's own)."""
        declared = declared_theorem_names(lean_code)
        profile = self.library_profile
        if profile is None:
            return audit_diagnostics(report, declared)
        return audit_diagnostics(
            report,
            declared,
            allowed_axioms=profile.axiom_allow_list,
            unreviewed_roots=profile.statement_recorded_roots or (),
            reviewed_roots=profile.reviewed_roots,
        )

    def _audit_timeout(self) -> Diagnostic:
        return Diagnostic(
            severity="error",
            code="lean.timeout",
            message=f"Lean timed out after {self.timeout_seconds:.1f}s.",
        )


@dataclass(frozen=True, slots=True)
class _ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    output_limited: bool


def _compiler_accepted(completed: _ProcessResult) -> bool:
    return (
        completed.returncode == 0
        and not completed.timed_out
        and not completed.output_limited
        and not any(
            diagnostic.severity == "error"
            for diagnostic in parse_lean_diagnostics(f"{completed.stdout}\n{completed.stderr}")
        )
    )


def _limited_command(
    command: list[str],
    *,
    timeout_seconds: float,
    scratch_dir: Path,
) -> list[str]:
    cpu_seconds = math.ceil(timeout_seconds) + 1
    limits = (
        cpu_seconds,
        _ADDRESS_SPACE_LIMIT_BYTES,
        _FILE_SIZE_LIMIT_BYTES,
        _PROCESS_LIMIT,
        _OPEN_FILE_LIMIT,
        0,
    )
    launcher = [
        sys.executable,
        "-I",
        str(Path(__file__).with_name("lean_child.py")),
        str(scratch_dir),
        *(str(value) for value in limits),
        "--",
        *command,
    ]
    prlimit = shutil.which("prlimit")
    if prlimit is None:
        return launcher
    return [
        prlimit,
        f"--cpu={cpu_seconds}:{cpu_seconds}",
        f"--as={_ADDRESS_SPACE_LIMIT_BYTES}:{_ADDRESS_SPACE_LIMIT_BYTES}",
        f"--fsize={_FILE_SIZE_LIMIT_BYTES}:{_FILE_SIZE_LIMIT_BYTES}",
        f"--nproc={_PROCESS_LIMIT}:{_PROCESS_LIMIT}",
        f"--nofile={_OPEN_FILE_LIMIT}:{_OPEN_FILE_LIMIT}",
        "--core=0:0",
        "--",
        *launcher,
    ]


def _run_limited_process(
    command: list[str],
    *,
    cwd: Path | None,
    environment: dict[str, str],
    timeout_seconds: float,
    output_limit_bytes: int,
) -> _ProcessResult:
    _enable_child_subreaper()
    pressure_before = _cgroup_pressure()
    status_read, status_write = os.pipe()
    try:
        with _ACTIVE_SUPERVISORS_LOCK:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    str(_SUPERVISOR_SCRIPT),
                    str(status_write),
                    str(timeout_seconds),
                    "--",
                    *command,
                ],
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                close_fds=True,
                pass_fds=(status_write,),
            )
            _ACTIVE_SUPERVISORS.add(process.pid)
    except BlockingIOError as error:
        # The PID limit is exhausted, possibly by a sibling, so nothing compiled.
        os.close(status_read)
        raise LeanCompileInterrupted("Lean supervisor could not start") from error
    except BaseException:
        os.close(status_read)
        raise
    finally:
        os.close(status_write)
    if process.stdout is None or process.stderr is None:
        _kill_and_reap_process_group(process)
        os.close(status_read)
        raise RuntimeError("Lean process pipes were not created")

    stdout_descriptor = process.stdout.fileno()
    stderr_descriptor = process.stderr.fileno()
    streams = {
        stdout_descriptor: bytearray(),
        stderr_descriptor: bytearray(),
    }
    selector = selectors.DefaultSelector()
    for stream in (process.stdout, process.stderr):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)

    # The supervisor enforces the deadline. This only bounds a supervisor that cannot.
    backstop = time.monotonic() + timeout_seconds + _SUPERVISOR_GRACE_SECONDS
    drain_until: float | None = None
    output_limited = False
    try:
        while selector.get_map() or process.poll() is None:
            now = time.monotonic()
            if process.poll() is None:
                if now >= backstop:
                    _kill_process_group(process)
            elif drain_until is None:
                # Every descendant is gone once it exits, so this normally ends at EOF at once.
                # A pipe still open after this grace is never waited for.
                drain_until = now + _DRAIN_GRACE_SECONDS
            elif now >= drain_until:
                break
            for key, _ in selector.select(0.02):
                descriptor = key.fd
                try:
                    chunk = os.read(descriptor, 65_536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                used = sum(len(buffer) for buffer in streams.values())
                remaining = max(0, output_limit_bytes - used)
                streams[descriptor].extend(chunk[:remaining])
                if len(chunk) > remaining and not output_limited:
                    output_limited = True
                    process.terminate()
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
        _reap_process(process)
        with _ACTIVE_SUPERVISORS_LOCK:
            _ACTIVE_SUPERVISORS.discard(process.pid)
        status = _read_supervisor_status(status_read)

    if status is None:
        # The tree may have outlived its owner, and nothing observed how the command ended.
        _reap_orphans()
        raise LeanCompileInterrupted("Lean supervisor exited without a result")
    returncode, timed_out = status
    pressured = _cgroup_pressure() > pressure_before
    # Above 128 is how Lake and Elan report a child that a signal killed. A deadline missed while
    # the cgroup refused forks or killed tasks says nothing about the proof either.
    if not output_limited and timed_out and pressured:
        raise LeanCompileDeadlineInterrupted("Lean missed its deadline under cgroup pressure")
    if not output_limited and not timed_out and (
        returncode < 0 or returncode > 128 or (returncode != 0 and pressured)
    ):
        raise LeanCompileInterrupted(f"Lean was terminated with status {returncode}")
    return _ProcessResult(
        returncode=returncode,
        stdout=bytes(streams[stdout_descriptor]).decode("utf-8", errors="replace"),
        stderr=bytes(streams[stderr_descriptor]).decode("utf-8", errors="replace"),
        timed_out=timed_out,
        output_limited=output_limited,
    )


def _read_supervisor_status(descriptor: int) -> tuple[int, bool] | None:
    """Only a complete line from the supervisor's own pipe counts as how the command ended."""
    try:
        os.set_blocking(descriptor, False)
        raw = os.read(descriptor, 64)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    match = _SUPERVISOR_STATUS_RE.fullmatch(raw)
    if match is None:
        return None
    return int(match.group(1)), match.group(2) == b"1"


def _cgroup_pressure() -> int:
    """OOM kills and refused forks in this cgroup; either during a failure denies it a verdict."""
    return _cgroup_event(_CGROUP_MEMORY_EVENTS, "oom_kill") + _cgroup_event(
        _CGROUP_PIDS_EVENTS, "max",
    )


def _cgroup_event(path: Path, name: str) -> int:
    try:
        events = path.read_text(encoding="ascii")
    except OSError:
        return 0
    for line in events.splitlines():
        key, _, value = line.partition(" ")
        if key == name and value.isdecimal():
            return int(value)
    return 0


def enable_orphan_reaping() -> None:
    """Only for a process whose every other child is a supervisor, such as the verifier server."""
    global _REAP_ORPHANS
    _REAP_ORPHANS = True


def _reap_orphans() -> None:
    """Kill what a dead supervisor left behind; the subreaper made those direct children."""
    if not _REAP_ORPHANS or not _is_linux():
        return
    me = os.getpid()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        found = False
        with _ACTIVE_SUPERVISORS_LOCK:
            for entry in Path("/proc").iterdir():
                if not entry.name.isdecimal() or int(entry.name) in _ACTIVE_SUPERVISORS:
                    continue
                try:
                    fields = (entry / "stat").read_bytes().rpartition(b")")[2].split()
                    if len(fields) > 1 and int(fields[1]) == me:
                        found = True
                        os.kill(int(entry.name), signal.SIGKILL)
                        os.waitpid(int(entry.name), os.WNOHANG)
                except OSError:
                    continue
        if not found:
            return
        time.sleep(0.01)


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def _kill_and_reap_process_group(process: subprocess.Popen[bytes]) -> None:
    _kill_process_group(process)
    _reap_process(process)


def _reap_process(process: subprocess.Popen[bytes]) -> None:
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        process.wait(timeout=2)


_SUBREAPER_ENABLED = False


def _enable_child_subreaper() -> None:
    global _SUBREAPER_ENABLED
    if _SUBREAPER_ENABLED or not _is_linux():
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "failed to enable child subreaper")
    _SUBREAPER_ENABLED = True


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def parse_lean_diagnostics(stderr: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    current_match: re.Match[str] | None = None
    message_lines: list[str] = []

    def append_current() -> None:
        if current_match is None:
            return
        message = "\n".join(message_lines).strip()
        severity = current_match.group("severity")
        declaration_uses_sorry = _SORRY_REPORT_RE.search(message) is not None
        compiler_code = current_match.group("diagnostic_code")
        code = f"lean.{severity}"
        if compiler_code:
            code = (
                compiler_code
                if compiler_code.startswith(("lean.", "lake."))
                else f"lean.{compiler_code}"
            )
        diagnostics.append(
            Diagnostic(
                severity="error"
                if severity == "error" or declaration_uses_sorry
                else "warning",
                code="lean.declaration_uses_sorry" if declaration_uses_sorry else code,
                message=message,
                line=int(current_match.group("line")),
                column=int(current_match.group("column")),
            )
        )

    for line in stderr.splitlines():
        match = _DIAGNOSTIC_RE.match(line)
        if match is not None:
            append_current()
            current_match = match
            message_lines = [match.group("message")]
            continue
        if current_match is not None:
            message_lines.append(line)
    append_current()
    return diagnostics


_strip_lean_comments_and_strings = strip_lean_comments_and_strings


def _text_from_timeout_output(output: bytes | str | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output
