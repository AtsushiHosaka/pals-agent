from __future__ import annotations

import errno
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from pals_agent import lean as lean_module
from pals_agent.lean import LeanVerifier

_MIB = 1024 * 1024
_GIB = 1024 * _MIB


def test_pae_017_lean_server_process_default_is_bounded_for_cold_mathlib() -> None:
    assert LeanVerifier().timeout_seconds == 300.0


def test_pae_017_lean_child_has_closed_environment_and_exact_rlimits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    probe = tmp_path / "lean-probe"
    captured: dict[str, object] = {}

    def find_binary(binary: str) -> str:
        return "/usr/bin/prlimit" if binary == "prlimit" else str(probe)

    def run_process(
        command: list[str],
        *,
        cwd: Path | None,
        environment: dict[str, str],
        timeout_seconds: float,
        output_limit_bytes: int,
    ) -> lean_module._ProcessResult:
        captured.update(
            command=command,
            cwd=cwd,
            environment=environment,
            timeout_seconds=timeout_seconds,
            output_limit_bytes=output_limit_bytes,
        )
        return lean_module._ProcessResult(
            returncode=0,
            stdout="",
            stderr="",
            timed_out=False,
            output_limited=False,
        )

    monkeypatch.setattr("pals_agent.lean.shutil.which", find_binary)
    monkeypatch.setattr(lean_module, "_run_limited_process", run_process)

    timeout_seconds = 1.2
    result = LeanVerifier(
        lean_binary=str(probe),
        timeout_seconds=timeout_seconds,
    ).verify("example : True := by trivial")

    assert result.success is True
    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert sorted(environment) == [
        "ELAN_HOME",
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "TMPDIR",
    ]
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:8] == [
        "/usr/bin/prlimit",
        "--cpu=3:3",
        f"--as={16 * _GIB}:{16 * _GIB}",
        f"--fsize={16 * _MIB}:{16 * _MIB}",
        "--nproc=64:64",
        "--nofile=1024:1024",
        "--core=0:0",
        "--",
    ]
    child_script = Path(command[10])
    assert child_script.name == "lean_child.py"
    assert child_script.parent.name == "pals_agent"
    assert child_script.is_file()
    assert command[-3] == str(probe)
    assert command[-2] == "--threads=1"
    assert Path(command[-1]).name == "Main.lean"


def test_pae_017_combined_lean_output_is_hard_capped(tmp_path: Path) -> None:
    noisy = _write_shell_executable(
        tmp_path / "lean-noisy",
        "/usr/bin/yes x | /usr/bin/head -c 1048577\n",
    )

    result = LeanVerifier(lean_binary=str(noisy)).verify(
        "example : True := by trivial"
    )

    assert result.success is False
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "lean.output_limit"
    ]
    assert len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8")) <= _MIB


def test_pae_017_timeout_kills_complete_process_group(tmp_path: Path) -> None:
    sleeper = _write_shell_executable(
        tmp_path / "lean-sleeper",
        """\
/bin/sleep 30 &
child=$!
printf '%s\\n' "$child"
/bin/sleep 30
""",
    )
    descendant_pid: int | None = None
    try:
        result = LeanVerifier(
            lean_binary=str(sleeper),
            timeout_seconds=1.0,
        ).verify("example : True := by trivial")
        descendant_pid = int(result.stdout.strip())

        assert result.success is False
        assert [diagnostic.code for diagnostic in result.diagnostics] == [
            "lean.timeout"
        ]
        deadline = time.monotonic() + 2
        while _pid_is_running(descendant_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert _pid_is_running(descendant_pid) is False
    finally:
        if descendant_pid is not None and _pid_exists(descendant_pid):
            os.kill(descendant_pid, signal.SIGKILL)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno == errno.EPERM
    return True


def _pid_is_running(pid: int) -> bool:
    if not _pid_exists(pid):
        return False
    completed = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        check=False,
        text=True,
    )
    state = completed.stdout.strip()
    return bool(state) and not state.startswith("Z")


def _write_shell_executable(path: Path, body: str) -> Path:
    path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path
