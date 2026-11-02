from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
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
        if "--run" in command:
            # The trusted audit that follows every accepted compile reuses the same boundary.
            nonce = command[command.index("--run") + 2]
            report = f"theorem target\nbound target\ncomplete {nonce}\n"
            return lean_module._ProcessResult(0, report, "", False, False)
        Path(command[command.index("-o") + 1]).write_bytes(b"olean")
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
    ).verify("theorem target : True := by trivial")

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
        "--nproc=256:256",
        "--nofile=1024:1024",
        "--core=0:0",
        "--",
    ]
    child_script = Path(command[10])
    assert child_script.name == "lean_child.py"
    assert child_script.parent.name == "pals_agent"
    assert child_script.is_file()
    assert command[-6] == str(probe)
    assert command[-5].startswith("--root=")
    assert command[-4] == "-o"
    assert Path(command[-3]).name == "Main.olean"
    assert command[-2] == "--threads=1"
    assert Path(command[-1]).name == "Main.lean"


def test_pae_017_combined_lean_output_is_hard_capped(tmp_path: Path) -> None:
    noisy = _write_shell_executable(
        tmp_path / "lean-noisy",
        "while :; do printf '%1024s\\n' x; done\n",
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
while :; do :; done &
child=$!
printf '%s\\n' "$child"
wait "$child"
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


def _run(command: list[str], *, timeout: float = 5) -> lean_module._ProcessResult:
    return lean_module._run_limited_process(
        command,
        cwd=None,
        environment={"PATH": "/usr/bin:/bin"},
        timeout_seconds=timeout,
        output_limit_bytes=65_536,
    )


def test_descendant_holding_stdout_cannot_outlive_a_finished_command() -> None:
    started = time.monotonic()
    result = _run(["/bin/sh", "-c", "echo done; sleep 30 & exit 0"], timeout=30)
    assert time.monotonic() - started < 5
    assert result.returncode == 0 and result.stdout == "done\n"
    assert result.timed_out is False


def test_deadline_applies_while_a_descendant_holds_the_pipes() -> None:
    started = time.monotonic()
    result = _run(["/bin/sh", "-c", "sleep 30 & sleep 30"], timeout=1)
    assert time.monotonic() - started < 5
    assert result.timed_out is True


def test_signal_death_is_an_interruption_and_never_a_verdict() -> None:
    with pytest.raises(lean_module.LeanCompileInterrupted):
        _run(["/bin/sh", "-c", "kill -9 $$"])
    with pytest.raises(lean_module.LeanCompileInterrupted):
        _run(["/bin/sh", "-c", "exit 137"])
    result = _run(["/bin/sh", "-c", "exit 1"])
    assert result.returncode == 1


def test_failure_during_an_oom_kill_is_an_interruption_and_success_stays_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counts = iter([0, 1, 0, 1])
    monkeypatch.setattr(lean_module, "_cgroup_pressure", lambda: next(counts))
    with pytest.raises(lean_module.LeanCompileInterrupted):
        _run(["/bin/sh", "-c", "exit 1"])
    assert _run(["/bin/sh", "-c", "exit 0"]).returncode == 0


def test_cgroup_pressure_counts_oom_kills_and_refused_forks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    memory = tmp_path / "memory.events"
    pids = tmp_path / "pids.events"
    monkeypatch.setattr(lean_module, "_CGROUP_MEMORY_EVENTS", memory)
    monkeypatch.setattr(lean_module, "_CGROUP_PIDS_EVENTS", pids)
    assert lean_module._cgroup_pressure() == 0
    memory.write_text("oom 9\noom_kill 2\n", encoding="ascii")
    pids.write_text("max 3\n", encoding="ascii")
    assert lean_module._cgroup_pressure() == 5


def test_exhausted_pids_at_start_are_an_interruption(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_pid(*_args: object, **_kwargs: object) -> None:
        raise BlockingIOError(errno.EAGAIN, "fork failed")

    monkeypatch.setattr(lean_module.subprocess, "Popen", no_pid)
    with pytest.raises(lean_module.LeanCompileInterrupted):
        _run(["/bin/sh", "-c", "exit 0"])


def test_dead_supervisor_is_an_interruption_and_its_pipes_are_not_waited_for(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    script = tmp_path / "dies.py"
    script.write_text("import os,signal\nos.kill(os.getpid(), signal.SIGKILL)\n")
    monkeypatch.setattr(lean_module, "_SUPERVISOR_SCRIPT", script)
    with pytest.raises(lean_module.LeanCompileInterrupted):
        _run(["/bin/sh", "-c", "exit 0"])


def test_interrupted_compile_returns_a_failed_result_without_touching_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    if sys.platform.startswith("linux"):
        pytest.skip("the Linux sandbox denies this shell; the real integration test covers it")
    probe = _write_shell_executable(tmp_path / "lean-probe", "kill -9 $$\n")
    result = LeanVerifier(lean_binary=str(probe), scratch_dir=tmp_path).verify(
        "example : True := by trivial"
    )
    assert result.success is False
    assert [item.code for item in result.diagnostics] == ["lean.compile_interrupted"]
