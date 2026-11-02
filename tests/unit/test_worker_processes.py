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


class _ChildStarted(Exception):
    """The ordinary single-worker path was reached without a nested supervisor."""


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
    for lane in ("proof", "assessment"):
        assert worker_processes.run_lane_workers(
            lane=lane, processes=3, ready_file=tmp_path / "ready",
        ) == 0
        # An explicit child count keeps an inherited environment value from nesting supervisors.
        assert seen == {
            "command": [sys.executable, "-m", "pals_agent.cli", "worker",
                        "--lane", lane, "--processes", "1"],
            "processes": 3, "ready_file": tmp_path / "ready",
            "restart_budget": worker_processes._RESTART_BUDGET,
        }
    with pytest.raises(ValueError):
        worker_processes.run_lane_workers(lane="all", processes=2, ready_file=None)


@pytest.mark.parametrize("count", [0, 1, 9, True, 2.0])
def test_process_count_is_closed(count):
    with pytest.raises(ValueError):
        worker_processes._supervise(command=[], processes=count, ready_file=None)


def test_cli_refuses_parallel_mixed_lane():
    with pytest.raises(SystemExit) as error:
        cli.main(["worker", "--lane", "all", "--processes", "2"])
    assert error.value.code == 2


@pytest.mark.parametrize("value", ["0", "9", "02", "two", "", " 2", "-1", "\u0662"])
def test_process_count_environment_is_closed(monkeypatch, value):
    monkeypatch.setenv("PALS_WORKER_PROCESSES", value)
    monkeypatch.setattr(cli, "run_lane_workers", lambda **kwargs: pytest.fail("supervised"))
    with pytest.raises(SystemExit) as error:
        cli.main(["worker", "--lane", "assessment"])
    assert error.value.code == 2


def test_process_count_environment_omission_keeps_one_worker(monkeypatch):
    monkeypatch.delenv("PALS_WORKER_PROCESSES", raising=False)
    assert worker_processes.worker_processes_from_env() == 1


@pytest.mark.parametrize(("lane", "argv", "environment", "expected"), [
    ("assessment", ["--processes", "4"], None, 4),
    ("assessment", [], "4", 4),
    ("proof", [], "2", 2),
    ("proof", ["--processes", "3"], "2", 3),
])
def test_cli_selects_lane_supervisor(monkeypatch, tmp_path, lane, argv, environment, expected):
    seen = {}

    def supervise(**kwargs):
        seen.update(kwargs)
        return 0

    if environment is None:
        monkeypatch.delenv("PALS_WORKER_PROCESSES", raising=False)
    else:
        monkeypatch.setenv("PALS_WORKER_PROCESSES", environment)
    monkeypatch.setattr(cli, "run_lane_workers", supervise)
    monkeypatch.setattr(
        cli, "SqsProofWorker", lambda **kwargs: pytest.fail("parent runtime constructed")
    )
    assert cli.main(["worker", "--lane", lane, *argv,
                     "--ready-file", str(tmp_path / "ready")]) == 0
    assert seen == {"lane": lane, "processes": expected, "ready_file": tmp_path / "ready"}


def test_supervised_child_with_inherited_environment_never_nests(monkeypatch):
    monkeypatch.setenv("PALS_WORKER_PROCESSES", "4")
    monkeypatch.setattr(cli, "run_lane_workers", lambda **kwargs: pytest.fail("nested"))
    monkeypatch.setattr(cli, "worker_queue_url", lambda *a: (_ for _ in ()).throw(_ChildStarted()))
    monkeypatch.setattr(cli, "configure_worker_api_trust", lambda *a: None)
    with pytest.raises(_ChildStarted):
        cli.main(["worker", "--lane", "assessment", "--processes", "1"])


def test_cli_selects_supervisor_before_constructing_any_worker(monkeypatch, tmp_path):
    seen = {}

    def supervise(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "run_lane_workers", supervise)
    monkeypatch.setattr(
        cli, "SqsProofWorker", lambda **kwargs: pytest.fail("parent runtime constructed")
    )
    assert cli.main(["worker", "--lane", "proof", "--processes", "2",
                     "--ready-file", str(tmp_path / "ready")]) == 0
    assert seen == {"lane": "proof", "processes": 2, "ready_file": tmp_path / "ready"}


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


DYING_CHILD = r"""
import os,sys,time
from pathlib import Path
root=Path(sys.argv[1]); dying=int(sys.argv[2]); marker=Path(sys.argv[-1])
births=len(list(root.glob('birth-*')))
(root/f'birth-{os.getpid()}').write_text('')
marker.write_text(str(os.getpid()))
if births<dying: os._exit(9)
time.sleep(60)
"""


def test_dead_child_is_replaced_without_stopping_healthy_siblings(tmp_path):
    code = (
        "from pathlib import Path; from pals_agent.worker_processes import _supervise; "
        "raise SystemExit(_supervise(command="
        + repr([sys.executable, "-c", DYING_CHILD, str(tmp_path), "2"])
        + ",processes=2,ready_file=Path(" + repr(str(tmp_path / "ready"))
        + "),startup_seconds=5,poll_seconds=.01,restart_budget=5))"
    )
    process = subprocess.Popen([sys.executable, "-c", code], stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and len(list(tmp_path.glob("birth-*"))) < 4:
            assert process.poll() is None
            time.sleep(.02)
        assert len(list(tmp_path.glob("birth-*"))) == 4
        time.sleep(.2)
        assert process.poll() is None
        assert (tmp_path / "ready").exists()
    finally:
        process.terminate()
        process.wait(timeout=10)
    assert process.stderr is not None
    assert b"worker_child_restarted" in process.stderr.read()


def test_exhausted_restart_budget_still_drains_and_exits(tmp_path):
    code = (
        "from pathlib import Path; from pals_agent.worker_processes import _supervise; "
        "raise SystemExit(_supervise(command="
        + repr([sys.executable, "-c", DYING_CHILD, str(tmp_path), "1000"])
        + ",processes=2,ready_file=Path(" + repr(str(tmp_path / "ready"))
        + "),startup_seconds=5,poll_seconds=.01,restart_budget=2))"
    )
    process = subprocess.Popen([sys.executable, "-c", code], stderr=subprocess.DEVNULL)
    assert process.wait(timeout=20) == 1
    assert 3 <= len(list(tmp_path.glob("birth-*"))) <= 5
    assert not (tmp_path / "ready").exists()


def test_child_reporting_an_sqs_outage_stops_the_lane_without_a_restart(tmp_path):
    outage = (
        "import sys,pathlib,os;"
        f"pathlib.Path({str(tmp_path)!r},f'birth-{{os.getpid()}}').write_text('');"
        "pathlib.Path(sys.argv[-1]).write_text(str(os.getpid()));"
        f"os._exit({worker_processes.LANE_UNAVAILABLE_EXIT})"
    )
    assert worker_processes._supervise(
        command=[sys.executable, "-c", outage], processes=2, ready_file=tmp_path / "ready",
        startup_seconds=5, poll_seconds=.01, restart_budget=5,
    ) == 1
    assert len(list(tmp_path.glob("birth-*"))) == 2
    assert not (tmp_path / "ready").exists()


def test_restart_budget_window_reaches_a_crash_every_twelve_minutes():
    assert worker_processes._RESTART_WINDOW_SECONDS / worker_processes._RESTART_BUDGET == 720
