from __future__ import annotations

import hashlib
import http.client
import json
import socket
import ssl
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
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


def _admission_context() -> RecipeAdmissionVerifierContext:
    return RecipeAdmissionVerifierContext(
        toolchain_fingerprint={
            "schema_version": "pals.lean-toolchain-fingerprint.v1",
            "lean_version": "leanprover/lean4:v4.32.0-rc1",
            "lake_manifest_sha256": "d" * 64,
            "verifier_sha256": "c" * 64,
            "materializer_version": "pals.recipe-materializer.v1",
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
    with tempfile.TemporaryDirectory(prefix="pals-mtls-", dir="/private/tmp") as directory:
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
        recipe_admission_context=_admission_context(),
    )
    server = create_server(settings, verifier=verifier)
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
