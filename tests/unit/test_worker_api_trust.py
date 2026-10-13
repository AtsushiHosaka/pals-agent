from __future__ import annotations

import multiprocessing
import os
import ssl
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from pals_agent import cli
from pals_agent.http_transport import HardDeadlineHttpTransport, HttpTransportError
from pals_agent.settings import AgentSettings
from pals_agent.worker_api_trust import configure_worker_api_trust


@pytest.fixture
def certificate_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    directory = tmp_path.resolve()
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PALS test API CA")])
    now = datetime.now(UTC)
    ca = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False
        )
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_path, leaf_path, key_path = (
        directory / name for name in ("ca.pem", "leaf.pem", "key.pem")
    )
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    ca_path.chmod(0o400)
    leaf_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    return ca_path, leaf_path, key_path


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def _tls_server(leaf: Path, key: Path) -> Iterator[tuple[str, str]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(leaf, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        yield f"https://localhost:{port}/health", f"https://127.0.0.1:{port}/health"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(url: str, method: str = "spawn") -> bytes:
    return (
        HardDeadlineHttpTransport(process_start_method=method)
        .request(
            method="GET",
            url=url,
            headers={},
            body=None,
            timeout_seconds=5,
        )
        .body
    )


def test_unset_ca_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", "existing.pem")
    assert configure_worker_api_trust(None) is None
    assert os.environ["SSL_CERT_FILE"] == "existing.pem"


def test_private_bundle_retains_public_roots_and_trusts_api_tls(
    certificate_files: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    existing = set(ssl.create_default_context().get_ca_certs(binary_form=True))
    ca, leaf, key = certificate_files
    bundle = configure_worker_api_trust(ca)
    assert bundle is not None and os.environ["SSL_CERT_FILE"] == str(bundle)
    assert stat.S_IMODE(bundle.stat().st_mode) == 0o600
    assert stat.S_IMODE(bundle.parent.stat().st_mode) == 0o700
    assert bundle.stat().st_uid == os.geteuid()
    assert existing <= set(ssl.create_default_context().get_ca_certs(binary_form=True))
    with _tls_server(leaf, key) as (correct, wrong_hostname):
        assert _request(correct) == b"ok"
        with urlopen(correct, timeout=3) as response:
            assert response.read() == b"ok"
        with pytest.raises(HttpTransportError):
            _request(wrong_hostname)


def test_httpx_observes_exported_trust(
    certificate_files: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    httpx = pytest.importorskip("httpx")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    ca, leaf, key = certificate_files
    configure_worker_api_trust(ca)
    with _tls_server(leaf, key) as (correct, wrong_hostname), httpx.Client() as client:
        assert client.get(correct).text == "ok"
        with pytest.raises(httpx.ConnectError):
            client.get(wrong_hostname)


def test_wrong_ca_is_rejected(
    certificate_files: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    _, leaf, key = certificate_files
    # The unchanged public bundle has no trust in this test's private CA.
    with _tls_server(leaf, key) as (correct, _), pytest.raises(HttpTransportError):
        _request(correct)


def test_forkserver_helpers_receive_updated_trust_explicitly(
    certificate_files: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if "forkserver" not in multiprocessing.get_all_start_methods():
        pytest.skip("forkserver is unavailable")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    process = multiprocessing.get_context("forkserver").Process(
        target=time.sleep, args=(0,)
    )
    process.start()
    process.join(timeout=3)
    assert process.exitcode == 0
    ca, leaf, key = certificate_files
    configure_worker_api_trust(ca)
    with _tls_server(leaf, key) as (correct, _):
        assert _request(correct, "forkserver") == b"ok"


@pytest.mark.parametrize("mode", [0o600, 0o444, 0o644, 0o777])
def test_mutable_or_overexposed_api_ca_is_rejected(
    certificate_files: tuple[Path, Path, Path],
    mode: int,
) -> None:
    ca, _, _ = certificate_files
    ca.chmod(mode)
    with pytest.raises(ValueError, match="worker-owned, mode 0400"):
        configure_worker_api_trust(ca)


def test_other_owner_is_rejected(
    certificate_files: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ca, _, _ = certificate_files
    monkeypatch.setattr(os, "geteuid", lambda: ca.stat().st_uid + 1)
    with pytest.raises(ValueError, match="worker-owned"):
        configure_worker_api_trust(ca)


def test_nonregular_certificate_path_does_not_block(tmp_path: Path) -> None:
    fifo = tmp_path.resolve() / "ca.pem"
    os.mkfifo(fifo, 0o400)
    started = time.monotonic()
    with pytest.raises(ValueError, match="worker-owned"):
        configure_worker_api_trust(fifo)
    assert time.monotonic() - started < 1


@pytest.mark.parametrize("parent_symlink", [False, True])
def test_api_ca_path_symlinks_are_rejected(
    certificate_files: tuple[Path, Path, Path],
    tmp_path: Path,
    parent_symlink: bool,
) -> None:
    ca, _, _ = certificate_files
    link = tmp_path.resolve() / "link"
    link.symlink_to(
        ca.parent if parent_symlink else ca, target_is_directory=parent_symlink
    )
    with pytest.raises(ValueError, match="symlinks"):
        configure_worker_api_trust(link / ca.name if parent_symlink else link)


@pytest.mark.parametrize("kind", ["leaf", "private-key", "garbage", "oversize"])
def test_api_trust_rejects_non_ca_or_unbounded_pem(
    certificate_files: tuple[Path, Path, Path],
    kind: str,
    tmp_path: Path,
) -> None:
    ca, leaf, key = certificate_files
    invalid = tmp_path.resolve() / "invalid.pem"
    content = {
        "leaf": leaf.read_bytes(),
        "private-key": key.read_bytes(),
        "garbage": ca.read_bytes() + b"extra",
        "oversize": b"a" * 131_073,
    }[kind]
    invalid.write_bytes(content)
    invalid.chmod(0o400)
    with pytest.raises(ValueError):
        configure_worker_api_trust(invalid)


def test_api_ca_environment_path_is_optional_and_absolute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PALS_API_CA_CERTIFICATE_PATH", raising=False)
    assert AgentSettings.from_env().api_ca_certificate_path is None
    monkeypatch.setenv(
        "PALS_API_CA_CERTIFICATE_PATH", "/run/pals-api-ca/ca-certificate.pem"
    )
    assert AgentSettings.from_env().api_ca_certificate_path == Path(
        "/run/pals-api-ca/ca-certificate.pem"
    )
    monkeypatch.setenv("PALS_API_CA_CERTIFICATE_PATH", "relative.pem")
    with pytest.raises(ValueError, match="absolute path"):
        AgentSettings.from_env()


@pytest.mark.parametrize("lane", ["proof", "assessment"])
def test_each_worker_lane_configures_trust_before_clients(
    monkeypatch: pytest.MonkeyPatch,
    lane: str,
) -> None:
    ca = Path("/run/pals-api-ca/ca-certificate.pem")
    configured: list[Path] = []
    settings = SimpleNamespace(
        api_ca_certificate_path=ca,
        proof_jobs_queue_url="proof",
        proof_requests_queue_url="assessment",
        worker_shared_secret="test",
        api_base_url="https://api.internal",
        proof_capability="full",
    )
    monkeypatch.setattr(cli.AgentSettings, "from_env", lambda: settings)
    monkeypatch.setattr(cli, "configure_worker_api_trust", configured.append)

    def api(**kwargs: object) -> object:
        assert configured == [ca]
        return object()

    monkeypatch.setattr(cli, "PalsApiClient", api)
    for name in (
        "build_proof_explainer",
        "build_proof_output_reviewer",
        "build_proof_semantic_reviewer",
        "build_recipe_attempt_planner",
        "build_proof_request_processor",
    ):
        monkeypatch.setattr(cli, name, lambda *args: object())
    monkeypatch.setattr(
        cli, "SqsProofWorker", lambda **kwargs: SimpleNamespace(run_once=lambda: True)
    )
    assert cli.main(["worker-once", "--lane", lane]) == 0
