from __future__ import annotations

import hashlib
import http.client
import json
import socket
import ssl
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic, sleep
from typing import Any, cast
from uuid import UUID

import pytest
import rfc8785
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from pals_agent.lean_verifier.http_server import (
    IsolatedVerifierHttpSettings,
    RecipeAdmissionVerifierContext,
    VerifierDeploymentBinding,
    create_server,
    pinned_recipe_admission_context,
)
from pals_agent.models import Diagnostic, VerificationResult

_RELEASE_ID = UUID("018a3b10-514d-4d6d-845e-3f322b74bca0")
_DEPLOYMENT_SHA = "a" * 64
_ADMISSION_ID = UUID("e406e9fa-fd9f-4856-b5c4-18e9b3102128")


def _admission_context(library_profile: str | None = None) -> RecipeAdmissionVerifierContext:
    return RecipeAdmissionVerifierContext(
        toolchain_fingerprint={
            "schema_version": "pals.lean-toolchain-fingerprint.v1",
            "lean_version": "leanprover/lean4:v4.32.0-rc1",
            "lake_manifest_sha256": "d" * 64,
            "verifier_sha256": "c" * 64,
            "materializer_version": "pals.recipe-materializer.v1",
            **({} if library_profile is None else {"library_profile": library_profile}),
        },
        compiler_command={
            "schema_version": "pals.recipe-admission-compiler-command.v1",
            "argv": ["lake", "env", "lean", "--threads=1", "Main.lean"],
            "workspace_lake_manifest_sha256": "d" * 64,
            "workspace_lean_toolchain_sha256": "e" * 64,
        },
    )


class StubVerifier:
    def __init__(self, result: VerificationResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def verify(self, lean_code: str) -> VerificationResult:
        self.calls.append(lean_code)
        return self.result


class BlockingVerifier(StubVerifier):
    def __init__(self) -> None:
        super().__init__(_success())
        self.started = Event()
        self.release = Event()

    def verify(self, lean_code: str) -> VerificationResult:
        self.calls.append(lean_code)
        self.started.set()
        assert self.release.wait(timeout=3)
        return self.result


@pytest.fixture
def tls_contexts() -> Iterator[tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str]]:
    with tempfile.TemporaryDirectory(prefix="pals-mtls-") as directory:
        root = Path(directory)
        _create_certificates(root)
        server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server.minimum_version = ssl.TLSVersion.TLSv1_3
        server.verify_mode = ssl.CERT_REQUIRED
        server.load_verify_locations(cafile=root / "ca.pem")
        server.load_cert_chain(root / "server.pem", root / "server.key")

        client = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=root / "ca.pem")
        client.minimum_version = ssl.TLSVersion.TLSv1_3
        client.load_cert_chain(root / "client.pem", root / "client.key")

        untrusted_client = ssl.create_default_context(
            ssl.Purpose.SERVER_AUTH,
            cafile=root / "ca.pem",
        )
        untrusted_client.minimum_version = ssl.TLSVersion.TLSv1_3
        yield (
            server,
            client,
            untrusted_client,
            _spki_sha256((root / "client.der").read_bytes()),
        )


@contextmanager
def _running_server(
    server_context: ssl.SSLContext,
    client_spki_sha256: str,
    verifier: StubVerifier,
    admission_verifier: StubVerifier | None = None,
    *,
    max_concurrent_compiles: int = 1,
    handshake_timeout_seconds: float = 5,
    http_timeout_seconds: float = 10,
    library_profile: str | None = None,
) -> Iterator[object]:
    settings = IsolatedVerifierHttpSettings(
        bind_host="127.0.0.1",
        binding=VerifierDeploymentBinding(
            release_id=_RELEASE_ID,
            deployment_binding_sha256=_DEPLOYMENT_SHA,
            verifier_image_digest="sha256:" + "b" * 64,
            verifier_toolchain_sha256="c" * 64,
        ),
        ssl_context=server_context,
        reconciler_client_spki_sha256=client_spki_sha256,
        reconciler_client_spiffe_uri="spiffe://pals/local/verified-reconciler",
        recipe_admission_context=_admission_context(library_profile),
        max_concurrent_compiles=max_concurrent_compiles,
        handshake_timeout_seconds=handshake_timeout_seconds,
        http_timeout_seconds=http_timeout_seconds,
    )
    server = create_server(settings, verifier=verifier, admission_verifier=admission_verifier)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def test_mtls_ready_and_successful_compile_produce_exact_bound_objects(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    verifier = StubVerifier(_success())
    with _running_server(server_context, client_spki_sha256, verifier):
        ready = _request(client_context, b"GET /ready HTTP/1.1\r\n" + _headers() + b"\r\n")
        proof = _request(client_context, _verify_request("example : True := by trivial"))

    assert ready == (
        200,
        {
            "deployment_binding_sha256": _DEPLOYMENT_SHA,
            "release_id": str(_RELEASE_ID),
            "schema_version": "pals.isolated-verifier-readiness.v1",
            "status": "ready",
            "verifier_image_digest": "sha256:" + "b" * 64,
            "verifier_toolchain_sha256": "c" * 64,
        },
    )
    assert proof == (
        200,
        {
            "lean_sha256": hashlib.sha256(b"example : True := by trivial").hexdigest(),
            "proof_job_id": "proof-1",
            "result_artifact_uri": "s3://bucket/manual-fixtures/" + "a" * 64 + ".lean",
            "schema_version": "pals.verifier-attestation.v1",
            "verification_succeeded": True,
        },
    )
    assert verifier.calls == ["example : True := by trivial"]


def test_pending_handshake_does_not_block_authenticated_requests(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    verifier = StubVerifier(_success())
    with _running_server(
        server_context, client_spki_sha256, verifier, handshake_timeout_seconds=0.5,
    ), socket.create_connection(("127.0.0.1", 18117), timeout=2) as silent:
        assert _request(client_context, b"GET /ready HTTP/1.1\r\n" + _headers() + b"\r\n")[0] == 200
        assert _request(client_context, _verify_request("transport fixture"))[0] == 200
        assert silent.recv(1) == b""
    assert verifier.calls == ["transport fixture"]


@pytest.mark.parametrize("part", ["headers", "body"])
def test_incomplete_authenticated_http_expires_without_compiling(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str], part: str,
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    verifier = StubVerifier(_success())
    partial = (
        b"GET /ready HTTP/1.1\r\n" if part == "headers" else
        b"POST /v1/verify HTTP/1.1\r\n" + _headers()
        + b"Content-Type: application/json\r\nContent-Length: 100\r\n\r\n{}"
    )
    with _running_server(
        server_context, client_spki_sha256, verifier, http_timeout_seconds=0.1,
    ), socket.create_connection(("127.0.0.1", 18117), timeout=2) as raw:
        with client_context.wrap_socket(raw, server_hostname="verifier.internal") as connection:
            connection.sendall(partial)
            assert connection.recv(1) == b""
        assert _request(client_context, b"GET /ready HTTP/1.1\r\n" + _headers() + b"\r\n")[0] == 200
    assert verifier.calls == []


def test_thread_start_failure_returns_admission_and_does_not_break_close(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_context, _, _, client_spki_sha256 = tls_contexts
    with _running_server(server_context, client_spki_sha256, StubVerifier(_success())) as server:
        def fail(_thread: Thread) -> None:
            raise RuntimeError("test thread capacity")

        with monkeypatch.context() as scoped, socket.socket() as connection:
            scoped.setattr(Thread, "start", fail)
            with pytest.raises(RuntimeError, match="test thread capacity"):
                server.process_request(connection, ("127.0.0.1", 1))
        assert not server._connection_threads
        slots = server._connection_slots
        assert all(slots.acquire(blocking=False) for _ in range(16))
        assert not slots.acquire(blocking=False)
        for _ in range(16):
            slots.release()


def test_connection_capacity_is_bounded_and_recovered(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    with _running_server(
        server_context, client_spki_sha256, StubVerifier(_success()),
        handshake_timeout_seconds=2,
    ) as server:
        with ExitStack() as peers:
            for _ in range(16):
                peers.enter_context(socket.create_connection(("127.0.0.1", 18117), timeout=2))
            deadline = monotonic() + 1
            while len(server._connection_threads) != 16 and monotonic() < deadline:
                sleep(0.01)
            assert len(server._connection_threads) == 16
            with socket.create_connection(("127.0.0.1", 18117), timeout=1) as excess:
                assert excess.recv(1) == b""
            assert len(server._connection_threads) == 16
        deadline = monotonic() + 1
        while server._connection_threads and monotonic() < deadline:
            sleep(0.01)
        assert not server._connection_threads
        assert _request(client_context, b"GET /ready HTTP/1.1\r\n" + _headers() + b"\r\n")[0] == 200


def test_authenticated_idle_keepalive_expires(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    with (
        _running_server(
            server_context, client_spki_sha256, StubVerifier(_success()), http_timeout_seconds=0.1,
        ),
        socket.create_connection(("127.0.0.1", 18117), timeout=2) as raw,
        client_context.wrap_socket(raw, server_hostname="verifier.internal") as connection,
    ):
        connection.sendall(b"GET /ready HTTP/1.1\r\n" + _headers() + b"\r\n")
        response = http.client.HTTPResponse(connection)
        response.begin()
        assert response.status == 200
        response.read()
        assert connection.recv(1) == b""


def test_http_receive_deadline_cannot_be_extended_by_trickling_bytes(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    with (
        _running_server(
            server_context, client_spki_sha256, StubVerifier(_success()), http_timeout_seconds=0.1,
        ),
        socket.create_connection(("127.0.0.1", 18117), timeout=2) as raw,
        client_context.wrap_socket(raw, server_hostname="verifier.internal") as connection,
    ):
        connection.sendall(
            b"POST /v1/verify HTTP/1.1\r\n" + _headers()
            + b"Content-Type: application/json\r\nContent-Length: 100\r\n\r\n"
        )
        started = monotonic()
        for _ in range(20):
            try:
                connection.sendall(b"x")
            except OSError:
                break
            sleep(0.03)
        assert monotonic() - started < 0.5


def test_receive_deadline_does_not_cancel_longer_compilation(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    class SlowVerifier(StubVerifier):
        def verify(self, lean_code: str) -> VerificationResult:
            sleep(0.2)
            return super().verify(lean_code)

    server_context, client_context, _, client_spki_sha256 = tls_contexts
    with _running_server(
        server_context, client_spki_sha256, SlowVerifier(_success()), http_timeout_seconds=0.05,
    ):
        assert _request(client_context, _verify_request("transport fixture"))[0] == 200


def test_invalid_binding_or_request_never_reaches_compiler(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    verifier = StubVerifier(_success())
    invalid_request = _verify_request("proof", schema_version="wrong")
    with _running_server(server_context, client_spki_sha256, verifier):
        binding_error = _request(
            client_context,
            b"POST /v1/verify HTTP/1.1\r\n"
            + _headers(release_id="wrong")
            + b"Content-Type: application/json\r\nContent-Length: 0\r\n\r\n",
        )
        request_error = _request(client_context, invalid_request)

    assert binding_error == (
        409,
        {
            "error_code": "verifier_release_binding_mismatch",
            "proof_job_id": None,
            "retryable": False,
            "schema_version": "pals.isolated-verifier-error.v1",
        },
    )
    assert request_error == (
        400,
        {
            "error_code": "verifier_request_invalid",
            "proof_job_id": "proof-1",
            "retryable": False,
            "schema_version": "pals.isolated-verifier-error.v1",
        },
    )
    assert verifier.calls == []


def test_server_requires_the_admitted_reconciler_certificate(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, _, untrusted_context, client_spki_sha256 = tls_contexts
    with (
        _running_server(
            server_context,
            client_spki_sha256,
            StubVerifier(_success()),
        ),
        socket.create_connection(("127.0.0.1", 18117), timeout=2) as raw,
        untrusted_context.wrap_socket(raw, server_hostname="verifier.internal") as connection,
    ):
        connection.sendall(b"GET /ready HTTP/1.1\r\n" + _headers() + b"\r\n")
        response = http.client.HTTPResponse(connection)
        with pytest.raises((ssl.SSLError, http.client.RemoteDisconnected)):
            response.begin()


def test_busy_and_compiler_failure_use_the_closed_error_registry(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    verifier = BlockingVerifier()
    with _running_server(server_context, client_spki_sha256, verifier):
        first = Thread(target=lambda: _request(client_context, _verify_request("first")))
        first.start()
        assert verifier.started.wait(timeout=2)
        busy = _request(client_context, _verify_request("second"))
        verifier.release.set()
        first.join(timeout=3)
        assert not first.is_alive()
        verifier.result = _failure()
        compile_failure = _request(client_context, _verify_request("third"))

    assert busy == (
        503,
        {
            "error_code": "verifier_unavailable",
            "proof_job_id": "proof-1",
            "retryable": True,
            "schema_version": "pals.isolated-verifier-error.v1",
        },
    )
    assert compile_failure == (
        422,
        {
            "error_code": "verifier_compile_failed",
            "proof_job_id": "proof-1",
            "retryable": False,
            "schema_version": "pals.isolated-verifier-error.v1",
            "diagnostics": [
                {"code": "lean.compile_error", "symbol": None, "line": None, "column": None}
            ],
        },
    )
    assert verifier.calls == ["first", "third"]


class _CountingVerifier(StubVerifier):
    """Hold every compile until the test observes the expected overlap."""

    def __init__(self, expected: int) -> None:
        super().__init__(_success())
        self.lock = Lock()
        self.running = 0
        self.peak = 0
        self.expected = expected
        self.overlapped = Event()
        self.release = Event()

    def verify(self, lean_code: str) -> VerificationResult:
        with self.lock:
            self.calls.append(lean_code)
            self.running += 1
            self.peak = max(self.peak, self.running)
            if self.running >= self.expected:
                self.overlapped.set()
        try:
            assert self.release.wait(timeout=5)
            return self.result
        finally:
            with self.lock:
                self.running -= 1


def test_configured_slots_run_concurrently_and_the_next_request_is_refused_retryably(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    verifier = _CountingVerifier(expected=2)
    responses: list[tuple[int, dict[str, object]]] = []
    with _running_server(
        server_context, client_spki_sha256, verifier, max_concurrent_compiles=2,
    ):
        threads = [
            Thread(
                target=lambda code=code: responses.append(
                    _request(client_context, _verify_request(code))
                )
            )
            for code in ("first", "second")
        ]
        for thread in threads:
            thread.start()
        assert verifier.overlapped.wait(timeout=3)
        refused = _request(client_context, _verify_request("third"))
        ready = _request(
            client_context,
            b"GET /ready HTTP/1.1\r\nHost: verifier.internal\r\n" + _headers() + b"\r\n",
        )
        verifier.release.set()
        for thread in threads:
            thread.join(timeout=3)
            assert not thread.is_alive()
        after = _request(client_context, _verify_request("fourth"))

    assert refused[0] == 503
    assert refused[1]["error_code"] == "verifier_unavailable"
    assert refused[1]["retryable"] is True
    # A compile in every slot must not make the readiness endpoint report anything else.
    assert ready[0] == 200
    assert [status for status, _ in responses] == [200, 200]
    assert after[0] == 200
    assert verifier.peak == 2
    assert sorted(verifier.calls) == ["first", "fourth", "second"]


def test_admission_and_proof_compiles_share_the_same_bound(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    verifier = _CountingVerifier(expected=2)
    with _running_server(
        server_context, client_spki_sha256, verifier, max_concurrent_compiles=2,
    ):
        threads = [
            Thread(target=lambda code=code: _request(client_context, _verify_request(code)))
            for code in ("first", "second")
        ]
        for thread in threads:
            thread.start()
        assert verifier.overlapped.wait(timeout=3)
        refused = _request(
            client_context,
            _recipe_admission_request("example : True := by trivial\n", _admission_context()),
        )
        verifier.release.set()
        for thread in threads:
            thread.join(timeout=3)
    assert refused[0] == 503
    assert refused[1]["failure_code"] == "verifier_not_ready"
    assert refused[1]["retryable"] is True


class _RaisingVerifier(StubVerifier):
    def verify(self, lean_code: str) -> VerificationResult:
        self.calls.append(lean_code)
        raise RuntimeError("cleanup failed")


@pytest.mark.parametrize(
    "result",
    [
        VerificationResult(
            success=False,
            diagnostics=[Diagnostic(severity="error", code="lean.timeout", message="timed out")],
            stdout="",
            stderr="",
            elapsed_ms=1,
        ),
        None,
    ],
    ids=["timeout", "error"],
)
def test_every_slot_is_released_after_a_timeout_or_compiler_error(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
    result: VerificationResult | None,
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    verifier = _RaisingVerifier(_success()) if result is None else StubVerifier(result)
    with _running_server(
        server_context, client_spki_sha256, verifier, max_concurrent_compiles=2,
    ) as server:
        for attempt in range(5):
            with suppress(http.client.HTTPException, OSError):
                _request(client_context, _verify_request(f"attempt-{attempt}"))
        slot = server.compile_slot  # type: ignore[attr-defined]
        assert slot.acquire(blocking=False)
        assert slot.acquire(blocking=False)
        assert not slot.acquire(blocking=False)
        slot.release()
        slot.release()
    assert len(verifier.calls) == 5


@pytest.mark.parametrize("value", [0, 3, -1, True, 2.0, "2"])
def test_concurrent_compile_setting_is_closed(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
    value: object,
) -> None:
    server_context, _, _, client_spki_sha256 = tls_contexts
    with pytest.raises(ValueError, match="concurrent compiles"):
        IsolatedVerifierHttpSettings(
            bind_host="127.0.0.1",
            binding=VerifierDeploymentBinding(
                release_id=_RELEASE_ID,
                deployment_binding_sha256=_DEPLOYMENT_SHA,
                verifier_image_digest="sha256:" + "b" * 64,
                verifier_toolchain_sha256="c" * 64,
            ),
            ssl_context=server_context,
            reconciler_client_spki_sha256=client_spki_sha256,
            reconciler_client_spiffe_uri="spiffe://pals/local/verified-reconciler",
            recipe_admission_context=_admission_context(),
            max_concurrent_compiles=value,  # type: ignore[arg-type]
        )


def _interrupted() -> VerificationResult:
    return VerificationResult(
        success=False,
        diagnostics=[
            Diagnostic(severity="error", code="lean.compile_interrupted", message="killed")
        ],
        stdout="",
        stderr="",
        elapsed_ms=1,
    )


@pytest.mark.parametrize("with_compiler_diagnostic", [False, True])
def test_sandbox_setup_failure_is_unavailable_and_never_proof_repair_feedback(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
    with_compiler_diagnostic: bool,
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    diagnostics = [
        Diagnostic(
            severity="error",
            code="lean.sandbox_setup_failed",
            message="Lean isolation failed at /private/verifier-host/diagnostic-secret.",
        )
    ]
    if with_compiler_diagnostic:
        diagnostics.append(
            Diagnostic(severity="error", code="lean.syntax_error", message="unexpected token")
        )
    verifier = StubVerifier(
        VerificationResult(
            success=False,
            diagnostics=diagnostics,
            stdout="private compiler output",
            stderr="private sandbox error",
            elapsed_ms=1,
        )
    )
    source = "example : True := by trivial\n"
    with _running_server(server_context, client_spki_sha256, verifier):
        proof = _request(client_context, _verify_request(source))
        admission = _request(
            client_context,
            _recipe_admission_request(source, _admission_context()),
            canonical=True,
        )

    assert proof == (
        503,
        {
            "error_code": "verifier_unavailable",
            "proof_job_id": "proof-1",
            "retryable": True,
            "schema_version": "pals.isolated-verifier-error.v1",
        },
    )
    assert admission == (
        503,
        {
            "schema_version": "pals.recipe-admission-verifier-result.v1",
            "status": "failed",
            "admission_id": str(_ADMISSION_ID),
            "failure_code": "verifier_not_ready",
            "retryable": True,
        },
    )
    assert verifier.calls == [source, source]


def test_interrupted_compile_is_a_retryable_infrastructure_failure_not_a_verdict(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    verifier = StubVerifier(_interrupted())
    with _running_server(server_context, client_spki_sha256, verifier):
        proof = _request(client_context, _verify_request("example : True := by trivial"))
        admission = _request(
            client_context,
            _recipe_admission_request("example : True := by trivial\n", _admission_context()),
        )
    assert proof == (
        503,
        {
            "error_code": "verifier_compile_interrupted",
            "proof_job_id": "proof-1",
            "retryable": True,
            "schema_version": "pals.isolated-verifier-error.v1",
        },
    )
    assert admission[0] == 503
    assert admission[1]["failure_code"] == "verifier_not_ready"
    assert admission[1]["retryable"] is True


def test_deadline_interruption_has_its_own_retryable_code(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    verifier = StubVerifier(
        VerificationResult(
            success=False,
            diagnostics=[
                Diagnostic(
                    severity="error", code="lean.compile_deadline_interrupted", message="late",
                )
            ],
            stdout="",
            stderr="",
            elapsed_ms=1,
        )
    )
    with _running_server(server_context, client_spki_sha256, verifier):
        proof = _request(client_context, _verify_request("example : True := by trivial"))
        admission = _request(
            client_context,
            _recipe_admission_request("example : True := by trivial\n", _admission_context()),
        )
    assert proof[0] == 503
    assert proof[1]["error_code"] == "verifier_compile_deadline_interrupted"
    assert proof[1]["retryable"] is True
    assert admission[0] == 503
    assert admission[1]["failure_code"] == "verifier_not_ready"


class _EventSink:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def send(self, line: str) -> None:
        self.lines.append(line)


def _diagnosed(code: str, message: str, elapsed_ms: int = 7) -> VerificationResult:
    return VerificationResult(
        success=False,
        diagnostics=[Diagnostic(severity="error", code=code, message=message)],
        stdout="",
        stderr="",
        elapsed_ms=elapsed_ms,
    )


def test_quality_events_are_off_by_default_and_never_carry_source_or_messages(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pals_agent import quality_events

    for name in (quality_events.ENABLED_ENV, quality_events.ENVIRONMENT_ENV, "PALS_ENV"):
        monkeypatch.delenv(name, raising=False)
    quality_events.reset_for_tests()
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    source = "theorem leaked_question_text : Why = Because := by sorry"
    message = "unknown identifier 'leaked_question_text' in /private/path/Main.lean"
    verifier = StubVerifier(_diagnosed("lean.unknown_identifier", message))
    sink = _EventSink()
    with quality_events.use_transport(sink), _running_server(
        server_context, client_spki_sha256, verifier,
    ):
        _request(client_context, _verify_request(source))
        assert sink.lines == []  # disabled by default
        monkeypatch.setenv(quality_events.ENABLED_ENV, "true")
        monkeypatch.setenv(quality_events.ENVIRONMENT_ENV, "probe")
        failed = _request(client_context, _verify_request(source))
        verifier.result = _success()
        passed = _request(client_context, _verify_request(source))
        verifier.result = _diagnosed("lean.timeout", "Lean timed out after 300.0s.", 300_000)
        timed_out = _request(client_context, _verify_request(source))
        verifier.result = _interrupted()
        interrupted = _request(client_context, _verify_request(source))
    assert [failed[0], passed[0], timed_out[0], interrupted[0]] == [422, 200, 504, 503]
    events = [json.loads(line) for line in sink.lines]
    assert [
        (event["outcome"], event.get("failure_code")) for event in events
    ] == [
        ("failure", "verifier.lean_compile_error"),
        ("success", None),
        ("failure", "infra.timeout"),
        ("failure", "infra.verifier_interrupted"),
    ]
    assert events[0]["diagnostic_code"] == "lean.unknown_identifier"
    assert events[0]["LeanAttempts"] == events[0]["LeanAttemptsFailed"] == 1
    assert events[2]["LeanVerifyDurationMs"] == 300_000
    blob = "\n".join(sink.lines)
    for private in ("leaked_question_text", "private/path", "theorem", "proof-1", "s3://"):
        assert private not in blob


def test_an_unexpected_compiler_exception_is_reported_as_unclassified_without_its_text(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pals_agent import quality_events

    class Exploding(StubVerifier):
        def verify(self, lean_code: str) -> VerificationResult:
            raise RuntimeError("secret compiler detail")

    monkeypatch.setenv(quality_events.ENABLED_ENV, "true")
    monkeypatch.setenv(quality_events.ENVIRONMENT_ENV, "probe")
    quality_events.reset_for_tests()
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    sink = _EventSink()
    with quality_events.use_transport(sink), _running_server(
        server_context, client_spki_sha256, Exploding(_success()),
    ), pytest.raises((http.client.RemoteDisconnected, ssl.SSLError, ConnectionError)):
        _request(client_context, _verify_request("example : True := by trivial"))
    (event,) = [json.loads(line) for line in sink.lines]
    assert (event["failure_code"], event["raw_code"]) == (
        "unclassified", "verifier_internal_error",
    )
    assert "secret compiler detail" not in sink.lines[0]


def test_recipe_admission_endpoint_uses_its_closed_canonical_contract(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    verifier = StubVerifier(_success())
    context = _admission_context()
    source = "import Mathlib\n\nexample : True := by trivial\n"
    with _running_server(server_context, client_spki_sha256, verifier):
        response = _request(
            client_context,
            _recipe_admission_request(source, context),
            canonical=True,
        )

    assert response == (
        200,
        {
            "schema_version": "pals.recipe-admission-verifier-result.v1",
            "status": "verified",
            "admission_id": str(_ADMISSION_ID),
            "materialized_source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "toolchain_fingerprint": context.toolchain_fingerprint,
            "toolchain_fingerprint_sha256": context.toolchain_fingerprint_sha256,
            "compiler_command_sha256": context.compiler_command_sha256,
            "compiler_result": {
                "schema_version": "pals.recipe-admission-compiler-result.v1",
                "verification_succeeded": True,
                "diagnostic_codes": [],
            },
        },
    )
    assert verifier.calls == [source]


def test_recipe_admission_uses_separate_bound_compiler(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    proof_verifier = StubVerifier(_success())
    admission_verifier = StubVerifier(_success())
    source = "import Mathlib\n\nexample : True := by trivial\n"
    with _running_server(
        server_context, client_spki_sha256, proof_verifier, admission_verifier,
    ):
        response = _request(
            client_context, _recipe_admission_request(source, _admission_context()),
            canonical=True,
        )
    assert response[0] == 200
    assert proof_verifier.calls == []
    assert admission_verifier.calls == [source]


def test_recipe_admission_rejects_noncanonical_or_tampered_bindings_before_compile(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    verifier = StubVerifier(_success())
    context = _admission_context()
    source = "import Mathlib\n\nexample : True := by trivial\n"
    bad_digest = _recipe_admission_request(
        source,
        context,
        materialized_source_sha256="0" * 64,
    )
    noncanonical = _recipe_admission_request(source, context, canonical=False)
    wrong_toolchain = _recipe_admission_request(
        source,
        context,
        expected_fingerprint_sha256="1" * 64,
    )
    with _running_server(server_context, client_spki_sha256, verifier):
        results = [
            _request(client_context, request, canonical=True)
            for request in (bad_digest, noncanonical, wrong_toolchain)
        ]

    assert results == [
        (
            400,
            {
                "schema_version": "pals.recipe-admission-verifier-result.v1",
                "status": "failed",
                "admission_id": str(_ADMISSION_ID),
                "failure_code": "verifier_request_invalid",
                "retryable": False,
            },
        ),
        (
            400,
            {
                "schema_version": "pals.recipe-admission-verifier-result.v1",
                "status": "failed",
                "admission_id": str(_ADMISSION_ID),
                "failure_code": "verifier_request_invalid",
                "retryable": False,
            },
        ),
        (
            400,
            {
                "schema_version": "pals.recipe-admission-verifier-result.v1",
                "status": "failed",
                "admission_id": str(_ADMISSION_ID),
                "failure_code": "verifier_request_invalid",
                "retryable": False,
            },
        ),
    ]
    assert verifier.calls == []


@pytest.mark.parametrize(
    ("server_profile", "request_profile"),
    [("stacks-4.35", None), (None, "stacks-4.35")],
)
def test_recipe_admission_never_crosses_library_profiles(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
    server_profile: str | None,
    request_profile: str | None,
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    verifier = StubVerifier(_success())
    source = "import Mathlib\n\nexample : True := by trivial\n"
    own = _admission_context(server_profile)
    foreign = _admission_context(request_profile)
    assert own.toolchain_fingerprint_sha256 != foreign.toolchain_fingerprint_sha256
    with _running_server(
        server_context, client_spki_sha256, verifier, library_profile=server_profile
    ):
        rejected = _request(
            client_context, _recipe_admission_request(source, foreign), canonical=True
        )
        accepted = _request(client_context, _recipe_admission_request(source, own), canonical=True)

    assert rejected[0] == 400
    assert rejected[1]["failure_code"] == "verifier_request_invalid"
    assert accepted[0] == 200
    assert accepted[1]["toolchain_fingerprint_sha256"] == own.toolchain_fingerprint_sha256
    assert verifier.calls == [source]


def test_recipe_admission_failure_never_returns_proof_job_or_artifact_fields(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    source = "import Mathlib\n\nexample : False := by\n  exact False.elim (by trivial)\n"
    with _running_server(server_context, client_spki_sha256, StubVerifier(_failure())):
        response = _request(
            client_context,
            _recipe_admission_request(source, _admission_context()),
            canonical=True,
        )

    assert response == (
        422,
        {
            "schema_version": "pals.recipe-admission-verifier-result.v1",
            "status": "failed",
            "admission_id": str(_ADMISSION_ID),
            "failure_code": "verifier_compile_failed",
            "retryable": False,
        },
    )


def test_recipe_admission_lean_timeout_maps_to_closed_retryable_504(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    source = "import Mathlib\n\nexample : True := by trivial\n"
    with _running_server(server_context, client_spki_sha256, StubVerifier(_timeout_failure())):
        response = _request(
            client_context,
            _recipe_admission_request(source, _admission_context()),
            canonical=True,
        )

    assert response == (
        504,
        {
            "schema_version": "pals.recipe-admission-verifier-result.v1",
            "status": "failed",
            "admission_id": str(_ADMISSION_ID),
            "failure_code": "verifier_timeout",
            "retryable": True,
        },
    )


def test_recipe_admission_busy_uses_its_closed_retryable_registry(
    tls_contexts: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
) -> None:
    server_context, client_context, _, client_spki_sha256 = tls_contexts
    verifier = BlockingVerifier()
    source = "import Mathlib\n\nexample : True := by trivial\n"
    request = _recipe_admission_request(source, _admission_context())
    with _running_server(server_context, client_spki_sha256, verifier):
        first = Thread(target=lambda: _request(client_context, request, canonical=True))
        first.start()
        assert verifier.started.wait(timeout=2)
        busy = _request(client_context, request, canonical=True)
        verifier.release.set()
        first.join(timeout=3)
        assert not first.is_alive()

    assert busy == (
        503,
        {
            "schema_version": "pals.recipe-admission-verifier-result.v1",
            "status": "failed",
            "admission_id": str(_ADMISSION_ID),
            "failure_code": "verifier_not_ready",
            "retryable": True,
        },
    )


def test_pinned_recipe_admission_context_binds_exact_workspace_bytes(tmp_path: Path) -> None:
    workspace = tmp_path / "lean-workspace"
    workspace.mkdir()
    (workspace / "lakefile.lean").write_text("import Lake\n", encoding="utf-8")
    manifest = workspace / "lake-manifest.json"
    manifest.write_bytes(b'{"version":"1.2.0"}\n')
    toolchain = workspace / "lean-toolchain"
    toolchain.write_bytes(b"leanprover/lean4:v4.32.0-rc1")

    context = pinned_recipe_admission_context(project_dir=workspace, verifier_sha256="f" * 64)

    assert context.toolchain_fingerprint == {
        "schema_version": "pals.lean-toolchain-fingerprint.v1",
        "lean_version": "leanprover/lean4:v4.32.0-rc1",
        "lake_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "verifier_sha256": "f" * 64,
        "materializer_version": "pals.recipe-materializer.v1",
    }
    assert (
        context.compiler_command["workspace_lean_toolchain_sha256"]
        == hashlib.sha256(toolchain.read_bytes()).hexdigest()
    )


def _create_certificates(root: Path) -> None:
    _openssl(
        root,
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "ca.key",
        "-out",
        "ca.pem",
        "-days",
        "1",
        "-subj",
        "/CN=pals-ca",
    )
    _openssl(
        root,
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "server.key",
        "-out",
        "server.csr",
        "-subj",
        "/CN=verifier.internal",
        "-addext",
        "subjectAltName=DNS:verifier.internal",
    )
    _openssl(
        root,
        "x509",
        "-req",
        "-in",
        "server.csr",
        "-CA",
        "ca.pem",
        "-CAkey",
        "ca.key",
        "-CAcreateserial",
        "-out",
        "server.pem",
        "-days",
        "1",
        "-copy_extensions",
        "copy",
    )
    _openssl(
        root,
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "client.key",
        "-out",
        "client.csr",
        "-subj",
        "/CN=pals-reconciler",
        "-addext",
        "subjectAltName=URI:spiffe://pals/local/verified-reconciler",
    )
    _openssl(
        root,
        "x509",
        "-req",
        "-in",
        "client.csr",
        "-CA",
        "ca.pem",
        "-CAkey",
        "ca.key",
        "-CAcreateserial",
        "-out",
        "client.pem",
        "-days",
        "1",
        "-copy_extensions",
        "copy",
    )
    _openssl(
        root,
        "x509",
        "-in",
        "client.pem",
        "-outform",
        "DER",
        "-out",
        "client.der",
    )


def _openssl(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["openssl", *arguments],
        cwd=root,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _headers(*, release_id: str | None = None) -> bytes:
    return (
        f"Host: verifier.internal\r\n"
        f"Pals-Release-Id: {release_id or _RELEASE_ID}\r\n"
        f"Pals-Deployment-Binding-Sha256: {_DEPLOYMENT_SHA}\r\n"
    ).encode("ascii")


def _verify_request(
    lean_code: str,
    *,
    schema_version: str = "pals.isolated-verifier-request.v1",
) -> bytes:
    body = json.dumps(
        {
            "lean_code": lean_code,
            "proof_job_id": "proof-1",
            "result_artifact_uri": "s3://bucket/manual-fixtures/" + "a" * 64 + ".lean",
            "schema_version": schema_version,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return (
        b"POST /v1/verify HTTP/1.1\r\n"
        + _headers()
        + b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        + body
    )


def _recipe_admission_request(
    source: str,
    context: RecipeAdmissionVerifierContext,
    *,
    materialized_source_sha256: str | None = None,
    expected_fingerprint_sha256: str | None = None,
    canonical: bool = True,
) -> bytes:
    payload = {
        "schema_version": "pals.recipe-admission-verifier-request.v1",
        "admission_id": str(_ADMISSION_ID),
        "materialized_source": source,
        "materialized_source_sha256": (
            materialized_source_sha256 or hashlib.sha256(source.encode()).hexdigest()
        ),
        "expected_toolchain_fingerprint": context.toolchain_fingerprint,
        "expected_toolchain_fingerprint_sha256": (
            expected_fingerprint_sha256 or context.toolchain_fingerprint_sha256
        ),
    }
    body = rfc8785.dumps(cast(Any, payload)) if canonical else json.dumps(payload).encode("utf-8")
    return (
        b"POST /v1/recipe-admissions/verify HTTP/1.1\r\n"
        + _headers()
        + b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        + body
    )


def _request(
    context: ssl.SSLContext,
    raw_request: bytes,
    *,
    canonical: bool = False,
) -> tuple[int, dict[str, object]]:
    with (
        socket.create_connection(("127.0.0.1", 18117), timeout=3) as raw,
        context.wrap_socket(raw, server_hostname="verifier.internal") as connection,
    ):
        connection.sendall(raw_request)
        response = http.client.HTTPResponse(connection)
        response.begin()
        assert response.getheader("Content-Type") == "application/json"
        assert response.getheader("Pals-Release-Id") == str(_RELEASE_ID)
        assert response.getheader("Pals-Deployment-Binding-Sha256") == _DEPLOYMENT_SHA
        assert response.getheader("Transfer-Encoding") is None
        content = response.read()
        assert response.getheader("Content-Length") == str(len(content))
    payload = json.loads(content)
    assert isinstance(payload, dict)
    if canonical:
        assert rfc8785.dumps(payload) == content
    return response.status, payload


def _success() -> VerificationResult:
    return VerificationResult(
        success=True,
        diagnostics=[],
        stdout="",
        stderr="",
        elapsed_ms=3,
    )


def _spki_sha256(certificate_der: bytes) -> str:
    certificate = x509.load_der_x509_certificate(certificate_der)
    return hashlib.sha256(
        certificate.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).hexdigest()


def _failure() -> VerificationResult:
    return VerificationResult(
        success=False,
        diagnostics=[
            Diagnostic(
                severity="error",
                code="lean.compile_failed",
                message="Lean rejected the candidate.",
            )
        ],
        stdout="",
        stderr="",
        elapsed_ms=3,
    )


def _timeout_failure() -> VerificationResult:
    return VerificationResult(
        success=False,
        diagnostics=[
            Diagnostic(
                severity="error",
                code="lean.timeout",
                message="Lean timed out after 300.0s.",
            )
        ],
        stdout="",
        stderr="",
        elapsed_ms=300_000,
    )


def test_repair_feedback_is_closed_bounded_and_never_copies_compiler_logs() -> None:
    from pals_agent.lean_verifier.http_server import _repair_diagnostics

    result = VerificationResult(
        success=False,
        stdout="SECRET STDOUT",
        stderr="SECRET STDERR",
        elapsed_ms=1,
        diagnostics=(
            Diagnostic(
                severity="error", message="'add_sq' has already been declared", line=3, column=8
            ),
            Diagnostic(severity="error", message="/private/secret.key: SECRET"),
            *(
                Diagnostic(severity="error", message="unknown identifier 'not_in_source'")
                for _ in range(20)
            ),
        ),
    )
    feedback = _repair_diagnostics(result, "theorem add_sq : True := by trivial")
    assert len(feedback) == 8
    assert feedback[0] == {
        "code": "lean.already_declared",
        "symbol": "add_sq",
        "line": 3,
        "column": 8,
    }
    assert feedback[1]["code"] == "lean.compile_error"
    assert "SECRET" not in str(feedback)
    assert "not_in_source" not in str(feedback)


def test_no_remaining_goals_has_specific_closed_feedback_without_compiler_text() -> None:
    from pals_agent.lean_verifier.http_server import _repair_diagnostics

    result = VerificationResult(
        success=False,
        stdout="PRIVATE compiler output",
        stderr="PRIVATE transport output",
        elapsed_ms=1,
        diagnostics=(
            Diagnostic("error", "No goals to be solved\nPRIVATE context", line=19, column=4),
            Diagnostic("error", "No goals to be solved: arbitrary text", line=20, column=4),
            Diagnostic("warning", "No goals to be solved", line=21, column=4),
        ),
    )

    source = (
        "theorem coprime_divisibility (a b c : ℕ) (hcoprime : Nat.gcd a b = 1) "
        "(hdiv : a ∣ b * c) : a ∣ c := by\n"
        "  exact (show Nat.Coprime a b from hcoprime).dvd_of_dvd_mul_left hdiv\n"
    )
    feedback = _repair_diagnostics(result, source)

    assert feedback == [
        {"code": "lean.no_goals", "symbol": None, "line": 19, "column": 4},
        {"code": "lean.compile_error", "symbol": None, "line": 20, "column": 4},
    ]
    assert "PRIVATE" not in str(feedback)
