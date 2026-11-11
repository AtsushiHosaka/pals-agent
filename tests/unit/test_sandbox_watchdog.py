"""Memory and CPU watchdog for the Lean processes (pure Python, runs in CI on macOS and Linux)."""

import subprocess
import sys
import time

import pytest

from pals_agent import sandbox


def _spawn(code: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", code], start_new_session=True)


def test_a_process_group_over_the_rss_limit_is_killed_and_the_reason_recorded():
    proc = _spawn(
        "import time\nx = bytearray(600 * 1024 * 1024)\n"
        "for i in range(0, len(x), 4096):\n    x[i] = 1\ntime.sleep(60)"
    )
    dog = sandbox.Watchdog(proc, rss_bytes=200 * 1024 * 1024, interval=0.1)
    started = time.monotonic()
    proc.wait(timeout=30)
    dog.stop()
    assert dog.reason == "rss" and time.monotonic() - started < 25
    assert proc.returncode != 0


def test_a_child_of_the_process_counts_toward_the_group_limit():
    code = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', \"x = bytearray(600*1024*1024)\\n"
        'for i in range(0, len(x), 4096): x[i] = 1\\nimport time; time.sleep(60)"])\n'
        "time.sleep(60)\n"
    )
    proc = _spawn(code)
    dog = sandbox.Watchdog(proc, rss_bytes=200 * 1024 * 1024, interval=0.1)
    proc.wait(timeout=30)
    dog.stop()
    assert dog.reason == "rss"


def test_a_cpu_spinning_group_is_killed_at_the_cpu_limit():
    proc = _spawn("while True: pass")
    dog = sandbox.Watchdog(proc, cpu_seconds=1.5, interval=0.1)
    proc.wait(timeout=30)
    dog.stop()
    assert dog.reason == "cpu"


def test_a_well_behaved_process_is_left_alone_and_the_defaults_are_bounded():
    proc = _spawn("import time; time.sleep(0.5)")
    dog = sandbox.Watchdog(proc, rss_bytes=sandbox.default_rss_bytes(), interval=0.1)
    assert proc.wait(timeout=10) == 0
    dog.stop()
    assert dog.reason is None
    assert 1 * 1024**3 <= sandbox.default_rss_bytes() <= 16 * 1024**3


def test_the_limits_are_configurable_by_the_environment(monkeypatch):
    monkeypatch.setenv("PALS_LEAN_RSS_LIMIT_MB", "512")
    assert sandbox.default_rss_bytes() == 512 * 1024 * 1024
    monkeypatch.setenv("PALS_LEAN_RSS_LIMIT_MB", "not-a-number")
    assert sandbox.default_rss_bytes() == sandbox.DEFAULT_RSS_BYTES
    monkeypatch.setenv("PALS_LEAN_WORKER_CPU_S", "123")
    assert sandbox.default_worker_cpu_seconds() == 123.0


def test_ps_output_parsing_handles_cputime_formats():
    assert sandbox._parse_cputime("0:01.50") == pytest.approx(1.5)
    assert sandbox._parse_cputime("1:02:03") == pytest.approx(3723.0)
    assert sandbox._parse_cputime("12:34.56") == pytest.approx(754.56)


# --- review 3, item 7 ----------------------------------------------------------------------------
import subprocess  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from pals_agent import automation_portfolio as ap  # noqa: E402


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("0:01.50", 1.5),
        ("12:34", 754.0),
        ("1:02:03", 3723.0),
        ("1-02:03:04", 86400 + 2 * 3600 + 3 * 60 + 4),
        ("1-02:03", 86400 + 2 * 3600 + 3 * 60),  # D-HH:MM (some ps builds)
        ("10-00:00:01", 864000 + 1),
        ("garbage", 0.0),
    ],
)
def test_ps_cputime_formats_including_days(text, seconds):
    assert sandbox._parse_cputime(text) == seconds


def test_a_worker_that_floods_its_output_is_killed_and_reaped(monkeypatch):
    """No PALS_DONE ever arrives: the per-request output bound kills the process group."""
    monkeypatch.setattr(ap, "MAX_OUTPUT_BYTES", 1024 * 1024)
    worker = object.__new__(ap.WarmWorker)
    proc = subprocess.Popen(
        ["/bin/sh", "-c", "yes xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        start_new_session=True,
    )
    worker.proc, worker._buf, worker._counter, worker._req_bytes = proc, b"", 0, 0
    worker._dog = SimpleNamespace(stop=lambda: None, reason=None)
    worker._lock = __import__("threading").RLock()
    with pytest.raises(RuntimeError, match="output"):
        worker._request("CHECK /x", ap.Path("/x"), timeout_s=30.0)
    assert proc.poll() is not None


def test_a_stream_that_floods_its_output_is_bounded():
    assert ap.MAX_OUTPUT_BYTES <= 16 * 1024 * 1024
