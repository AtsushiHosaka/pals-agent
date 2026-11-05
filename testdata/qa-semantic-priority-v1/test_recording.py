"""Offline recording-boundary checks; no provider calls or model verdicts."""

import base64
import importlib.util
import json
from contextlib import suppress
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("benchmark.py")
spec = importlib.util.spec_from_file_location("qa_recording_boundary", SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def assert_raw(directory: Path, body: bytes) -> None:
    record = json.loads((directory / "provider-1-raw.json").read_bytes())
    assert record["http_status"] == 503
    assert record["elapsed_seconds"] == 0.125
    assert base64.b64decode(record["body_base64"]) == body
    assert (directory / "provider-1-raw.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("body", [b"not json", b"\xff\xfe"], ids=["non-json", "invalid-utf8"])
def test_decoder_failure_keeps_received_envelope(tmp_path: Path, body: bytes) -> None:
    benchmark.record_received_response(tmp_path, 1, 503, body, 0.125)
    assert_raw(tmp_path, body)
    assert json.loads((tmp_path / "provider-1.json").read_bytes())["response"] is None


@pytest.mark.parametrize("error", [ValueError, RecursionError])
def test_decoder_exception_keeps_received_envelope(tmp_path: Path, monkeypatch, error) -> None:
    def fail(_):
        raise error("explicit decoder failure")

    with monkeypatch.context() as patch:
        patch.setattr(benchmark.json, "loads", fail)
        benchmark.record_received_response(tmp_path, 1, 503, b"{}", 0.125)
    assert_raw(tmp_path, b"{}")


def test_deep_json_keeps_raw_even_if_parsed_serialization_fails(tmp_path: Path) -> None:
    body = b"[" * 2000 + b"0" + b"]" * 2000
    # Interpreter recursion limits may reject either decoding or encoding.
    # In both cases the same original envelope MUST already be durable.
    with suppress(RecursionError):
        benchmark.record_received_response(tmp_path, 1, 503, body, 0.125)
    assert_raw(tmp_path, body)


def test_parsed_artifact_write_failure_keeps_received_envelope(tmp_path: Path, monkeypatch) -> None:
    original_save = benchmark.save

    def fail_parsed(path, value):
        if path.name == "provider-1.json":
            raise OSError("explicit parsed artifact write failure")
        original_save(path, value)

    monkeypatch.setattr(benchmark, "save", fail_parsed)
    with pytest.raises(OSError, match="explicit parsed"):
        benchmark.record_received_response(tmp_path, 1, 503, b'{"ok":true}', 0.125)
    assert_raw(tmp_path, b'{"ok":true}')
    assert not (tmp_path / "provider-1.json").exists()


def test_parsed_artifact_conflict_does_not_overwrite_or_lose_raw(tmp_path: Path) -> None:
    parsed = tmp_path / "provider-1.json"
    parsed.write_bytes(b"existing owner artifact")
    with pytest.raises(FileExistsError):
        benchmark.record_received_response(tmp_path, 1, 503, b'{"ok":true}', 0.125)
    assert parsed.read_bytes() == b"existing owner artifact"
    assert_raw(tmp_path, b'{"ok":true}')


def test_valid_json_preserves_received_and_parsed_bytes(tmp_path: Path) -> None:
    body = b'{"ok": true}'
    benchmark.record_received_response(tmp_path, 1, 503, body, 0.125)
    assert_raw(tmp_path, body)
    parsed = json.loads((tmp_path / "provider-1.json").read_bytes())
    assert parsed["response"] == {"ok": True}
    assert parsed["raw_envelope_sha256"] == benchmark.digest(
        (tmp_path / "provider-1-raw.json").read_bytes()
    )
