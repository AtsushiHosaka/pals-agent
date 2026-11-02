from __future__ import annotations

import base64
import json
import ssl
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from pals_agent import lightweight_http_transport as owner
from pals_agent.http_transport import (
    HardDeadlineHttpTransport,
    HttpDeadlineExceeded,
    HttpResponseTooLarge,
    HttpTransportError,
)


class Handler(BaseHTTPRequestHandler):
    followed: ClassVar[int] = 0

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/slow":
            time.sleep(0.5)
        if self.path == "/followed":
            type(self).followed += 1
        response = b"x" * 65 if self.path == "/oversize" else b"ok"
        self.send_response(302 if self.path == "/redirect" else 200)
        if self.path == "/redirect":
            self.send_header("Location", "/followed")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(response)

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        response = str(len(body)).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: object) -> None:
        pass


class Server(ThreadingHTTPServer):
    daemon_threads = True


@contextmanager
def server(context: ssl.SSLContext | None = None) -> Iterator[str]:
    instance = Server(("127.0.0.1", 0), Handler)
    if context is not None:
        instance.socket = context.wrap_socket(instance.socket, server_side=True)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield ("https://localhost:" if context is not None else "http://127.0.0.1:") + str(
            instance.server_port
        )
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=2)


def request(url: str, **kwargs: object) -> bytes:
    return (
        owner.LightweightHttpTransport(**kwargs)
        .request(  # type: ignore[arg-type]
            method="GET",
            url=url,
            headers={},
            body=None,
            timeout_seconds=3,
        )
        .body
    )


@pytest.fixture
def tls(tmp_path: Path) -> tuple[ssl.SSLContext, Path]:
    ca_key = ec.generate_private_key(ec.SECP256R1())
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "local test CA")])
    now = datetime.now(UTC)
    ca = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(minutes=10))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
        .sign(ca_key, hashes.SHA256())
    )
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(minutes=10))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), False)
        .sign(ca_key, hashes.SHA256())
    )
    ca_path, cert_path, key_path = (tmp_path / name for name in ("ca.pem", "leaf.pem", "key.pem"))
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.maximum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(cert_path, key_path)
    return context, ca_path


def test_real_private_ca_wrong_hostname_and_untrusted_ca(
    tls: tuple[ssl.SSLContext, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, ca_path = tls
    with server(context) as url:
        monkeypatch.setenv("SSL_CERT_FILE", str(ca_path))
        assert request(url) == b"ok"
        with pytest.raises(HttpTransportError):
            request(url.replace("localhost", "127.0.0.1"))
        monkeypatch.delenv("SSL_CERT_FILE")
        with pytest.raises(HttpTransportError):
            request(url)


def test_real_response_cap_exact_limit_and_redirect_denial() -> None:
    Handler.followed = 0
    with server() as url:
        assert request(url, max_response_bytes=2) == b"ok"
        with pytest.raises(HttpResponseTooLarge):
            request(url + "/oversize", max_response_bytes=64)
        response = owner.LightweightHttpTransport().request(
            method="GET",
            url=url + "/redirect",
            headers={},
            body=None,
            timeout_seconds=3,
        )
    assert response.status_code == 302 and ("Location", "/followed") in response.headers
    assert Handler.followed == 0


def test_real_total_deadline_reaps_the_fresh_child(monkeypatch: pytest.MonkeyPatch) -> None:
    original = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def launch(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        child = original(*args, **kwargs)  # type: ignore[call-overload]
        children.append(child)
        return child

    monkeypatch.setattr(owner.subprocess, "Popen", launch)
    with server() as url:
        started = time.monotonic()
        with pytest.raises(HttpDeadlineExceeded):
            owner.LightweightHttpTransport().request(
                method="GET",
                url=url + "/slow",
                headers={},
                body=None,
                timeout_seconds=0.15,
            )
        elapsed = time.monotonic() - started
    assert elapsed < 0.5 and len(children) == 1 and children[0].poll() is not None
    assert all(
        s is not None and s.closed
        for s in (
            children[0].stdin,
            children[0].stdout,
            children[0].stderr,
        )
    )


def test_two_thread_calls_have_independent_fresh_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    children: list[subprocess.Popen[bytes]] = []
    original = subprocess.Popen
    lock = threading.Lock()

    def launch(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        child = original(*args, **kwargs)  # type: ignore[call-overload]
        with lock:
            children.append(child)
        return child

    monkeypatch.setattr(owner.subprocess, "Popen", launch)
    with server() as url, ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(request, [url, url])) == [b"ok", b"ok"]
    assert len({child.pid for child in children}) == 2
    assert all(child.poll() == 0 for child in children)


def test_existing_large_image_and_attachment_budgets_are_supported() -> None:
    # Larger than the diagnostic's old 1 MiB IPC cap; no network is needed.
    body = b"x" * (4_000_000 * 7)
    packet = owner._packet("POST", "https://example.invalid", {}, body, 3.0, 56_000_000)
    request, maximum = owner._read_request(packet)
    assert request["body"] == body and maximum == 56_000_000
    assert (
        owner.LightweightHttpTransport(max_response_bytes=56_000_000).max_response_bytes == maximum
    )


@pytest.mark.parametrize(
    "raw",
    [
        b'{"outcome":"too_large","outcome":"response"}',
        b"[]",
        b'{"outcome":NaN}',
        b'{"outcome":"response","status":true,"body":"","headers":[]}',
        b'{"outcome":"response","status":200,"body":"b2t=","headers":[]}',
        b'{"outcome":"response","status":200,"body":"b2s=","headers":[[1,"x"]]}',
        b'{"outcome":"too_large","extra":1}',
    ],
)
def test_strict_response_json_base64_and_types(raw: bytes) -> None:
    with pytest.raises((ValueError, HttpTransportError)):
        owner._response(raw, 100)


@pytest.mark.parametrize("mutate", ["duplicate", "bool-cap", "unknown", "bad-base64", "nan"])
def test_strict_request_json_and_types(mutate: str) -> None:
    raw = owner._packet("POST", "https://example.invalid", {}, b"ok", 3.0, 100)
    value = json.loads(raw)
    if mutate == "duplicate":
        raw = raw.replace(b'"version":1', b'"version":1,"version":1')
    elif mutate == "bool-cap":
        value["max_response_bytes"] = True
        raw = json.dumps(value).encode()
    elif mutate == "unknown":
        value["request"]["extra"] = "private fixture"
        raw = json.dumps(value).encode()
    elif mutate == "bad-base64":
        value["request"]["body"] = "b2t="
        raw = json.dumps(value).encode()
    else:
        raw = raw.replace(b'"socket_timeout":3.0', b'"socket_timeout":NaN')
    with pytest.raises(ValueError):
        owner._read_request(raw)


def test_blocked_stdin_shares_deadline_and_output_caps() -> None:
    child = subprocess.Popen(
        [sys.executable, "-I", "-c", "import time;time.sleep(3)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        with pytest.raises(HttpDeadlineExceeded):
            owner._exchange(child, b"x" * (512 * 1024), time.monotonic() + 0.1, 100)
    finally:
        owner._reap(child)
    assert child.poll() is not None


def test_deadline_also_covers_exit_after_all_pipes_close() -> None:
    child = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            "import os,sys,time;sys.stdin.buffer.read();os.close(1);os.close(2);time.sleep(3)",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        with pytest.raises(HttpDeadlineExceeded):
            owner._exchange(child, b"{}", time.monotonic() + 0.1, 100)
    finally:
        owner._reap(child)
    assert child.poll() is not None


def test_response_budget_preserves_attachment_responses_above_default() -> None:
    body = b"x" * (2 * 1024 * 1024 + 1)
    raw = json.dumps(
        {
            "outcome": "response",
            "status": 200,
            "body": base64.b64encode(body).decode(),
            "headers": [],
        }
    ).encode()
    assert owner._response(raw, 56_000_000).body == body
    with pytest.raises(ValueError):
        owner._response(raw, 2 * 1024 * 1024)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_excessive_child_output_is_bounded_and_not_reported(stream: str) -> None:
    child = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys;sys." + stream + '.buffer.write(b"private_fixture"*10000)',
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        with pytest.raises(HttpTransportError) as caught:
            owner._exchange(child, b"{}", time.monotonic() + 2, 100)
        assert "private_fixture" not in str(caught.value)
    finally:
        owner._reap(child)


def test_static_bootstrap_clean_environment_and_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert owner._BOOTSTRAP == (
        "from pals_agent.lightweight_http_transport import _child_main; _child_main()"
    )
    assert isinstance(owner.fresh_process_http_transport(), HardDeadlineHttpTransport)
    monkeypatch.setattr(sys, "platform", "linux")
    assert isinstance(
        owner.fresh_process_http_transport(use_lightweight=True), owner.LightweightHttpTransport
    )
    monkeypatch.setattr(sys, "platform", "darwin")
    assert isinstance(
        owner.fresh_process_http_transport(use_lightweight=True), HardDeadlineHttpTransport
    )


def test_request_and_credentials_never_enter_child_argv_or_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = subprocess.Popen
    observed: list[tuple[object, object]] = []

    def launch(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        observed.append((args, kwargs))
        return original(*args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(owner.subprocess, "Popen", launch)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "private_fixture")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    with server() as url:
        response = owner.LightweightHttpTransport().request(
            method="POST",
            url=url,
            headers={"Authorization": "private_fixture"},
            body=b"private_fixture",
            timeout_seconds=3,
        )
    assert response.body == str(len(b"private_fixture")).encode()
    assert len(observed) == 1 and "private_fixture" not in repr(observed)
    assert "HTTP_PROXY" not in repr(observed) and "AWS_SECRET_ACCESS_KEY" not in repr(observed)
    assert observed[0][0][0][:4] == [sys.executable, "-I", "-B", "-c"]  # type: ignore[index]


def test_failure_never_retries_or_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    count = 0

    def failure(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        nonlocal count
        count += 1
        raise OSError("private_fixture")

    monkeypatch.setattr(owner.subprocess, "Popen", failure)
    with pytest.raises(HttpTransportError) as caught:
        request("https://example.invalid")
    assert count == 1 and "private_fixture" not in str(caught.value)


def test_isolation_ignores_cwd_and_pythonpath_package_shadowing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "pals_agent"
    package.mkdir()
    (package / "__init__.py").write_text("raise RuntimeError('untrusted shadow package')")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    with server() as url:
        assert request(url) == b"ok"


def test_header_protocol_budget_and_configured_caps() -> None:
    with pytest.raises(ValueError):
        owner._packet(
            "GET", "https://example.invalid", {"x": "a" * owner.MAX_HEADER_BYTES}, None, 3.0, 100
        )
    assert owner.LightweightHttpTransport().max_response_bytes == 1_048_576
    assert (
        owner.LightweightHttpTransport(max_response_bytes=2 * 1024 * 1024).max_response_bytes
        == 2 * 1024 * 1024
    )
    assert base64.b64encode(b"ok") == b"b2s="
