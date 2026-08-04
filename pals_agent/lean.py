from __future__ import annotations

import ctypes
import math
import os
import re
import selectors
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

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
_INTERACTIVE_COMMAND_RE = re.compile(r"^\s*#\w+", re.MULTILINE)
_METAPROGRAMMING_RE = re.compile(
    r"(^|[^A-Za-z0-9_])"
    r"(run_cmd|elab|macro|macro_rules|syntax|declare_syntax_cat)"
    r"([^A-Za-z0-9_]|$)"
)
_SYNTAX_QUOTATION_RE = re.compile(r"`\(")
_DIAGNOSTIC_RE = re.compile(
    r"^(?P<file>.*?):(?P<line>\d+):(?P<column>\d+): "
    r"(?P<severity>error|warning)(?:\((?P<diagnostic_code>[^)]+)\))?: "
    r"(?P<message>.*)$"
)
_MIB = 1024 * 1024
_GIB = 1024 * _MIB
_ADDRESS_SPACE_LIMIT_BYTES = 16 * _GIB
_FILE_SIZE_LIMIT_BYTES = 16 * _MIB
_PROCESS_LIMIT = 64
_OPEN_FILE_LIMIT = 1024
_OUTPUT_LIMIT_BYTES = _MIB
_DEFAULT_CHILD_PATH = "/opt/elan/bin:/usr/local/bin:/usr/bin:/bin"
_DEFAULT_ELAN_HOME = "/opt/elan"


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
        return self._verify(lean_code, allow_sorry=False)

    def verify_sketch(self, lean_code: str) -> VerificationResult:
        return self._verify(lean_code, allow_sorry=True)

    def _verify(self, lean_code: str, *, allow_sorry: bool) -> VerificationResult:
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

        interactive_command = _INTERACTIVE_COMMAND_RE.search(checked_code)
        if interactive_command:
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        code="lean.disallowed_interactive_command",
                        message=(
                            "Generated Lean code contains an interactive command "
                            f"`{interactive_command.group(0).strip()}`."
                        ),
                    )
                ],
                stdout="",
                stderr="",
                elapsed_ms=0,
            )

        metaprogramming = _METAPROGRAMMING_RE.search(checked_code)
        if metaprogramming:
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        code="lean.disallowed_metaprogramming",
                        message=(
                            "Generated Lean code contains metaprogramming command "
                            f"`{metaprogramming.group(2)}`."
                        ),
                    )
                ],
                stdout="",
                stderr="",
                elapsed_ms=0,
            )

        if _SYNTAX_QUOTATION_RE.search(checked_code):
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        code="lean.disallowed_syntax_quotation",
                        message="Generated Lean code contains syntax quotation.",
                    )
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
            lean_file.write_text(lean_code, encoding="utf-8")
            lean_file.chmod(0o400)
            command, cwd = self._command_for(
                lean_file,
                lean_binary=lean_binary,
                lake_binary=lake_binary,
            )
            limited_command = _limited_command(
                command,
                timeout_seconds=float(self.timeout_seconds),
                scratch_dir=temporary_dir,
            )
            child_environment = {
                "PATH": self.child_path,
                "HOME": str(home_dir),
                "TMPDIR": str(temporary_dir),
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "ELAN_HOME": self.elan_home,
            }

            started_at = time.monotonic()
            completed = _run_limited_process(
                limited_command,
                cwd=cwd,
                environment=child_environment,
                timeout_seconds=float(self.timeout_seconds),
                output_limit_bytes=self.output_limit_bytes,
            )

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
                        message=f"Lean timed out after {self.timeout_seconds:.1f}s.",
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
        if success:
            diagnostics.append(
                Diagnostic(
                    severity="info",
                    code="lean.verified",
                    message="Lean accepted the generated code.",
                )
            )
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

    def _command_for(
        self,
        lean_file: Path,
        *,
        lean_binary: str,
        lake_binary: str | None,
    ) -> tuple[list[str], Path | None]:
        if self.project_dir is not None:
            if lake_binary is None:
                raise AssertionError("validated Lake binary is required")
            return [
                lake_binary,
                "env",
                lean_binary,
                "--threads=1",
                str(lean_file),
            ], self.project_dir
        return [lean_binary, "--threads=1", str(lean_file)], None


@dataclass(frozen=True, slots=True)
class _ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    output_limited: bool


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
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
    )
    if process.stdout is None or process.stderr is None:
        _kill_and_reap_process_group(process)
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

    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    output_limited = False
    try:
        while selector.get_map() or process.poll() is None:
            now = time.monotonic()
            if not timed_out and process.poll() is None and now >= deadline:
                timed_out = True
                _kill_process_group(process)
            wait_seconds = 0.02
            if process.poll() is None:
                wait_seconds = min(wait_seconds, max(0.0, deadline - now))
            for key, _ in selector.select(wait_seconds):
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
                    _kill_process_group(process)
            if process.poll() is not None and not selector.get_map():
                break
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
        _reap_process(process)

    return _ProcessResult(
        returncode=process.returncode if process.returncode is not None else -signal.SIGKILL,
        stdout=bytes(streams[stdout_descriptor]).decode("utf-8", errors="replace"),
        stderr=bytes(streams[stderr_descriptor]).decode("utf-8", errors="replace"),
        timed_out=timed_out,
        output_limited=output_limited,
    )


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
    if not _is_linux():
        return
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            reaped_pid, _ = os.waitpid(-process.pid, os.WNOHANG)
        except ChildProcessError:
            return
        if reaped_pid == 0:
            time.sleep(0.01)
        else:
            return


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


def _strip_lean_comments_and_strings(text: str) -> str:
    lines = []
    current: list[str] = []
    index = 0
    block_depth = 0
    in_string = False
    while index < len(text):
        current_pair = text[index : index + 2]
        char = text[index]

        if block_depth > 0:
            if current_pair == "/-":
                block_depth += 1
                index += 2
                continue
            if current_pair == "-/":
                block_depth -= 1
                index += 2
                continue
            if char == "\n":
                lines.append("".join(current))
                current = []
            index += 1
            continue

        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
            if char == "\n":
                lines.append("".join(current))
                current = []
            index += 1
            continue

        if current_pair == "/-":
            block_depth = 1
            index += 2
            continue

        if current_pair == "--":
            newline_index = text.find("\n", index)
            if newline_index == -1:
                break
            lines.append("".join(current))
            current = []
            index = newline_index + 1
            continue

        if char == '"':
            in_string = True
            current.append(" ")
            index += 1
            continue

        if char == "\n":
            lines.append("".join(current))
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    lines.append("".join(current))
    return "\n".join(lines)


def _text_from_timeout_output(output: bytes | str | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output
