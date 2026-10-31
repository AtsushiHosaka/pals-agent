"""Real OS-process lifecycle tests; no AWS, provider, API or Lean is invoked."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pals_agent import cli, worker_processes

CHILD = r'''
import json,os,signal,sys,time,uuid
from pathlib import Path
from types import SimpleNamespace
from pals_agent.worker import SqsProofWorker
root=Path(sys.argv[1]); mode=sys.argv[2]; marker=Path(sys.argv[-1])
claim=SqsProofWorker._fresh_claim_id(SimpleNamespace(uuid4_factory=uuid.uuid4))
record=root/(str(os.getpid())+'.json')
stop=False
def stopping(signum,frame):
 global stop
 stop=True
signal.signal(signal.SIGTERM,stopping); signal.signal(signal.SIGINT,stopping)
record.write_text(json.dumps({'pid':os.getpid(),'claim_id':claim,'drained':False}))
if mode!='no-marker': marker.write_text(str(os.getpid()) if mode!='bad-marker' else '1')
while not stop: time.sleep(.01)
time.sleep(.08)
record.write_text(json.dumps({'pid':os.getpid(),'claim_id':claim,'drained':True}))
marker.unlink(missing_ok=True)
'''


def launch(tmp_path: Path, mode: str = "normal") -> subprocess.Popen[bytes]:
    code = (
        "from pathlib import Path; from pals_agent.worker_processes import _supervise; "
        "raise SystemExit(_supervise(command="
        + repr([sys.executable, "-c", CHILD, str(tmp_path), mode])
        + ",processes=3,ready_file=Path("
        + repr(str(tmp_path / "ready"))
        + "),startup_seconds=5,poll_seconds=.01))"
    )
    return subprocess.Popen([sys.executable, "-c", code])


def wait_ready(process: subprocess.Popen[bytes], marker: Path) -> None:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if marker.exists():
            assert marker.read_text() == str(process.pid)
            return
        assert process.poll() is None
        time.sleep(.02)
    raise AssertionError("fixture readiness deadline exceeded")


def records(tmp_path: Path) -> list[dict]:
    return [json.loads(path.read_text()) for path in tmp_path.glob("*.json")]


def assert_drained_and_reaped(tmp_path: Path) -> None:
    actual = records(tmp_path)
    assert actual and all(item["drained"] is True for item in actual)
    for item in actual:
        with pytest.raises(ProcessLookupError):
            os.kill(item["pid"], 0)
    assert not (tmp_path / "ready").exists()
    assert not list(tmp_path.glob("pals-proof-workers-*"))


@pytest.mark.parametrize("stop_signal", [signal.SIGTERM, signal.SIGINT])
def test_real_children_have_independent_claims_and_gracefully_reap(tmp_path, stop_signal):
    process = launch(tmp_path)
    try:
        wait_ready(process, tmp_path / "ready")
        actual = records(tmp_path)
        assert len(actual) == len({x["pid"] for x in actual}) == 3
        assert len({x["claim_id"] for x in actual}) == 3
        process.send_signal(stop_signal)
        assert process.wait(timeout=8) == 0
        assert_drained_and_reaped(tmp_path)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=8)


def test_unexpected_zero_child_exit_is_failure_and_drains_siblings(tmp_path):
    process = launch(tmp_path)
    try:
        wait_ready(process, tmp_path / "ready")
        os.kill(records(tmp_path)[0]["pid"], signal.SIGTERM)
        assert process.wait(timeout=8) == 1
        assert_drained_and_reaped(tmp_path)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=8)


@pytest.mark.parametrize("mode", ["no-marker", "bad-marker"])
def test_startup_missing_or_invalid_marker_fails_closed_and_reaps(tmp_path, mode):
    process = launch(tmp_path, mode)
    try:
        assert process.wait(timeout=10) == 1
        assert_drained_and_reaped(tmp_path)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=8)


def test_partial_spawn_error_still_drains_and_reaps_real_child(tmp_path, monkeypatch):
    real = subprocess.Popen
    children = []

    def spawn(command, **kwargs):
        if children:
            # Let the fixture install its signal handler before the induced failure.
            deadline = time.monotonic() + 5
            while not records(tmp_path) and time.monotonic() < deadline:
                time.sleep(.01)
            raise OSError("fixture child creation failed")
        child = real(command, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(worker_processes.subprocess, "Popen", spawn)
    with pytest.raises(OSError, match="fixture child creation failed"):
        worker_processes._supervise(
            command=[sys.executable, "-c", CHILD, str(tmp_path), "normal"],
            processes=2, ready_file=tmp_path / "ready", poll_seconds=.01,
        )
    assert children[0].returncode == 0
    assert_drained_and_reaped(tmp_path)


def test_factory_uses_fresh_exec_and_does_not_pass_parent_runtime(monkeypatch, tmp_path):
    seen = {}

    def supervise(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(worker_processes, "_supervise", supervise)
    assert worker_processes.run_proof_workers(processes=3, ready_file=tmp_path / "ready") == 0
    assert seen == {
        "command": [sys.executable, "-m", "pals_agent.cli", "worker", "--lane", "proof"],
        "processes": 3, "ready_file": tmp_path / "ready",
    }


@pytest.mark.parametrize("count", [0, 1, 9, True, 2.0])
def test_process_count_is_closed(count):
    with pytest.raises(ValueError):
        worker_processes._supervise(command=[], processes=count, ready_file=None)


@pytest.mark.parametrize("lane", ["all", "assessment"])
def test_cli_refuses_nonproof_parallel_lanes(lane):
    with pytest.raises(SystemExit) as error:
        cli.main(["worker", "--lane", lane, "--processes", "2"])
    assert error.value.code == 2


def test_cli_selects_supervisor_before_constructing_any_worker(monkeypatch, tmp_path):
    seen = {}

    def supervise(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "run_proof_workers", supervise)
    monkeypatch.setattr(
        cli, "SqsProofWorker", lambda **kwargs: pytest.fail("parent runtime constructed")
    )
    assert cli.main(["worker", "--lane", "proof", "--processes", "2",
                     "--ready-file", str(tmp_path / "ready")]) == 0
    assert seen == {"processes": 2, "ready_file": tmp_path / "ready"}


@pytest.mark.parametrize("payload", [b"", b"wrong pid", b"\xff", b"1" * 33])
def test_malformed_marker_bytes_are_refused_without_decoding(tmp_path, payload):
    marker = tmp_path / "marker"
    marker.write_bytes(payload)
    assert worker_processes._marker_ready(marker, os.getpid()) is False


def test_marker_refuses_links_and_special_files(tmp_path):
    marker = tmp_path / "marker"
    original = tmp_path / "original"
    original.write_text(str(os.getpid()))
    marker.symlink_to(original)
    assert worker_processes._marker_ready(marker, os.getpid()) is False
    marker.unlink()
    os.link(original, marker)
    assert worker_processes._marker_ready(marker, os.getpid()) is False
    marker.unlink()
    os.mkfifo(marker)
    assert worker_processes._marker_ready(marker, os.getpid()) is False


def test_disappearing_child_readiness_fails_and_drains_real_children(tmp_path):
    process = launch(tmp_path)
    try:
        wait_ready(process, tmp_path / "ready")
        markers = list(tmp_path.glob("pals-proof-workers-*/*.ready"))
        assert len(markers) == 3
        markers[0].unlink()
        assert process.wait(timeout=8) == 1
        assert_drained_and_reaped(tmp_path)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=8)
