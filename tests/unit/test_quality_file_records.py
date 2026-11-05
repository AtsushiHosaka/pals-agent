"""Real file/lock/subprocess checks; write failures are injected at the syscall boundary."""

from __future__ import annotations

import fcntl
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pals_agent import quality_events as qe


@pytest.fixture
def private_file(tmp_path: Path) -> Path:
    path = tmp_path.resolve() / "quality.ndjson"
    path.write_bytes(b'{"previous":true}\n')
    path.chmod(0o600)
    return path


@pytest.mark.parametrize("write_kind", ["zero", "short", "raise_before", "raise_after"])
def test_failed_write_preserves_prefix_and_next_json_record(private_file, monkeypatch, write_kind):
    prefix = private_file.read_bytes()
    real_write = os.write
    opened = []
    real_open = os.open

    def track_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        return fd

    def fail_write(fd, data):
        if write_kind == "raise_before":
            raise OSError("injected_write_failure")
        count = 0 if write_kind == "zero" else real_write(fd, data[:9])
        if write_kind == "raise_after":
            raise OSError("injected_write_failure_after_partial_append")
        return count

    sender = qe.FileTransport(str(private_file))
    with monkeypatch.context() as patch:
        patch.setattr(qe.os, "open", track_open)
        patch.setattr(qe.os, "write", fail_write)
        with pytest.raises(OSError):
            sender.send('{"incomplete":"probe"}')
    assert private_file.read_bytes() == prefix
    for descriptor in opened:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    sender.send('{"next":true}')
    assert [json.loads(line) for line in private_file.read_text().splitlines()] == [
        {"previous": True}, {"next": True},
    ]


def test_short_write_counts_only_one_drop_then_delivers_counter(private_file, monkeypatch):
    qe.reset_for_tests()
    monkeypatch.setenv(qe.ENABLED_ENV, "true")
    monkeypatch.setenv(qe.ENVIRONMENT_ENV, "probe")
    monkeypatch.setenv(qe.TRANSPORT_ENV, "file")
    monkeypatch.setenv(qe.FILE_ENV, str(private_file))
    real_write = os.write
    try:
        with monkeypatch.context() as patch:
            patch.setattr(qe.os, "write", lambda fd, data: real_write(fd, data[:9]))
            qe.record_worker_heartbeat()
        assert qe.dropped_count() == 1
        qe.record_worker_heartbeat()
        assert qe.dropped_count() == 0
        previous, heartbeat = map(json.loads, private_file.read_text().splitlines())
        assert previous == {"previous": True}
        assert heartbeat["event"] == "worker_heartbeat"
        assert heartbeat["WorkerHeartbeat"] == heartbeat["QualityEventsDropped"] == 1
    finally:
        qe.reset_for_tests()


def test_rotation_after_open_is_refused_before_appending(private_file, monkeypatch):
    prefix = private_file.read_bytes()
    old = private_file.with_suffix(".old")
    real_flock = fcntl.flock

    def rotate_before_lock(fd, operation):
        private_file.rename(old)
        private_file.touch(mode=0o600)
        real_flock(fd, operation)

    with monkeypatch.context() as patch:
        patch.setattr(qe.fcntl, "flock", rotate_before_lock)
        with pytest.raises(ValueError, match="quality_file_rotated"):
            qe.FileTransport(str(private_file)).send('{"probe":1}')
    assert old.read_bytes() == prefix and private_file.read_bytes() == b""
    qe.FileTransport(str(private_file)).send('{"new":true}')
    assert json.loads(private_file.read_text()) == {"new": True}


def test_permissions_are_rechecked_after_lock(private_file, monkeypatch):
    prefix = private_file.read_bytes()
    real_flock = fcntl.flock

    def change_mode_before_lock(fd, operation):
        private_file.chmod(0o644)
        real_flock(fd, operation)

    monkeypatch.setattr(qe.fcntl, "flock", change_mode_before_lock)
    with pytest.raises(ValueError, match="quality_file_not_private"):
        qe.FileTransport(str(private_file)).send('{"probe":1}')
    assert private_file.read_bytes() == prefix


@pytest.mark.parametrize("foreign_change", ["truncate", "extra_append"])
def test_uncooperative_change_is_not_truncated_by_rollback(
    private_file, monkeypatch, foreign_change,
):
    real_write = os.write

    def change_then_fail(fd, data):
        if foreign_change == "truncate":
            os.ftruncate(fd, 0)
            real_write(fd, b"x")
        else:
            real_write(fd, data + b"foreign bytes")
        raise OSError("injected_write_failure")

    with monkeypatch.context() as patch:
        patch.setattr(qe.os, "write", change_then_fail)
        with pytest.raises(OSError, match="quality_file_changed"):
            qe.FileTransport(str(private_file)).send('{"probe":1}')
    if foreign_change == "truncate":
        assert private_file.read_bytes() == b"x"
    else:
        assert private_file.read_bytes().endswith(b"foreign bytes")


def test_failed_rollback_is_reported_and_descriptor_released(private_file, monkeypatch):
    real_write = os.write

    def refuse_truncate(*args):
        raise OSError("injected_truncate_failure")

    with monkeypatch.context() as patch:
        patch.setattr(qe.os, "write", lambda fd, data: real_write(fd, data[:2]))
        patch.setattr(qe.os, "ftruncate", refuse_truncate)
        with pytest.raises(OSError, match="quality_rollback_failed"):
            qe.FileTransport(str(private_file)).send('{"probe":1}')
    # There is no false claim of recovery: this failure leaves a partial record.
    assert private_file.read_bytes().endswith(b'{"')
    with private_file.open("ab") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_other_process_lock_refuses_immediately_and_releases_after_exit(private_file):
    script = """
import fcntl, sys
with open(sys.argv[1], 'ab') as stream:
    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    print('locked', flush=True)
    sys.stdin.readline()
"""
    process = subprocess.Popen([sys.executable, "-c", script, str(private_file)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([process.stdout], [], [], 5)[0]
        assert process.stdout.readline() == "locked\n"
        start = time.monotonic()
        with pytest.raises(BlockingIOError):
            qe.FileTransport(str(private_file)).send('{"blocked":true}')
        assert time.monotonic() - start < 1
        output, errors = process.communicate("release\n", timeout=5)
        assert process.returncode == 0 and output == errors == ""
        qe.FileTransport(str(private_file)).send('{"released":true}')
        assert json.loads(private_file.read_text().splitlines()[-1]) == {"released": True}
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_four_real_subprocesses_keep_every_successful_record_intact(private_file):
    script = """
import json, sys, time
from pals_agent.quality_events import FileTransport
sender = FileTransport(sys.argv[1])
deadline = time.monotonic() + 10
for sequence in range(80):
    value = json.dumps({'producer': int(sys.argv[2]), 'sequence': sequence, 'padding': 'x' * 7000})
    while True:
        try:
            sender.send(value)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.001)
"""
    processes = []
    try:
        for producer in range(4):
            processes.append(subprocess.Popen(
                [sys.executable, "-c", script, str(private_file), str(producer)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ))
        for process in processes:
            output, errors = process.communicate(timeout=15)
            assert process.returncode == 0 and output == errors == ""
        records = [json.loads(line) for line in private_file.read_text().splitlines()]
        assert records[0] == {"previous": True}
        assert len(records) == 321
        assert {(record["producer"], record["sequence"]) for record in records[1:]} == {
            (producer, sequence) for producer in range(4) for sequence in range(80)
        }
        assert all(record["padding"] == "x" * 7000 for record in records[1:])
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
