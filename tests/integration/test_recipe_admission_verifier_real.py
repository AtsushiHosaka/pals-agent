from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import ssl
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
from typing import Any, cast
from uuid import UUID

import rfc8785
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from pals_agent.lean import LeanVerifier
from pals_agent.lean_verifier.http_server import (
    IsolatedVerifierHttpSettings,
    RecipeAdmissionVerifierContext,
    VerifierDeploymentBinding,
    create_server,
    pinned_recipe_admission_context,
)

_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE = _ROOT / "lean-workspace"
_RELEASE_ID = UUID("018a3b10-514d-4d6d-845e-3f322b74bca0")
_ADMISSION_ID = UUID("e406e9fa-fd9f-4856-b5c4-18e9b3102128")
_DEPLOYMENT_SHA = "a" * 64
_VERIFIER_SHA = "f" * 64


def test_pinned_recipe_admission_endpoint_compiles_over_mtls(tmp_path: Path) -> None:
    """Exercise the actual verifier owner, not a direct/mocked LeanVerifier call."""
    source = "import Mathlib\n\nexample : True := by\n  trivial\n"
    with _running_pinned_verifier(tmp_path) as (client_context, admission_context):
        response = _request(
            client_context,
            _admission_request(source, admission_context.toolchain_fingerprint),
        )

    assert response == (
        200,
        {
            "schema_version": "pals.recipe-admission-verifier-result.v1",
            "status": "verified",
            "admission_id": str(_ADMISSION_ID),
            "materialized_source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "toolchain_fingerprint": admission_context.toolchain_fingerprint,
            "toolchain_fingerprint_sha256": admission_context.toolchain_fingerprint_sha256,
            "compiler_command_sha256": admission_context.compiler_command_sha256,
            "compiler_result": {
                "schema_version": "pals.recipe-admission-compiler-result.v1",
                "verification_succeeded": True,
                "diagnostic_codes": ["lean.verified"],
            },
        },
    )


@contextmanager
def _running_pinned_verifier(
    tmp_path: Path,
) -> Iterator[tuple[ssl.SSLContext, RecipeAdmissionVerifierContext]]:
    elan_home = Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan")))
    lean = elan_home / "bin" / "lean"
    lake = elan_home / "bin" / "lake"
    assert lean.is_file(), f"pinned local Lean launcher is missing: {lean}"
    assert lake.is_file(), f"pinned local Lake launcher is missing: {lake}"
    with tempfile.TemporaryDirectory(prefix="pals-admission-mtls-", dir="/private/tmp") as raw_root:
        root = Path(raw_root)
        _create_certificates(root)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.minimum_version = ssl.TLSVersion.TLSv1_3
        server_context.verify_mode = ssl.CERT_REQUIRED
        server_context.load_verify_locations(cafile=root / "ca.pem")
        server_context.load_cert_chain(root / "server.pem", root / "server.key")
        client_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=root / "ca.pem")
        client_context.minimum_version = ssl.TLSVersion.TLSv1_3
        client_context.load_cert_chain(root / "client.pem", root / "client.key")
        admission_context = pinned_recipe_admission_context(
            project_dir=_WORKSPACE,
            verifier_sha256=_VERIFIER_SHA,
        )
        server = create_server(
            IsolatedVerifierHttpSettings(
                bind_host="127.0.0.1",
                binding=VerifierDeploymentBinding(
                    release_id=_RELEASE_ID,
                    deployment_binding_sha256=_DEPLOYMENT_SHA,
                    verifier_image_digest="sha256:" + "b" * 64,
                    verifier_toolchain_sha256=_VERIFIER_SHA,
                ),
                ssl_context=server_context,
                reconciler_client_spki_sha256=_spki_sha256((root / "client.der").read_bytes()),
                reconciler_client_spiffe_uri="spiffe://pals/local/verified-reconciler",
                recipe_admission_context=admission_context,
            ),
            verifier=LeanVerifier(
                lean_binary=str(lean),
                lake_binary=str(lake),
                project_dir=_WORKSPACE,
                scratch_dir=tmp_path,
                child_path=f"{elan_home / 'bin'}:/usr/bin:/bin",
                elan_home=str(elan_home),
            ),
        )
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield client_context, admission_context
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            assert not thread.is_alive()


def _admission_request(source: str, fingerprint: dict[str, str]) -> bytes:
    body = rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": "pals.recipe-admission-verifier-request.v1",
                "admission_id": str(_ADMISSION_ID),
                "materialized_source": source,
                "materialized_source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "expected_toolchain_fingerprint": fingerprint,
                "expected_toolchain_fingerprint_sha256": hashlib.sha256(
                    rfc8785.dumps(cast(Any, fingerprint))
                ).hexdigest(),
            },
        )
    )
    return (
        b"POST /v1/recipe-admissions/verify HTTP/1.1\r\n"
        + _headers()
        + b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        + body
    )


def _headers() -> bytes:
    return (
        "Host: verifier.internal\r\n"
        f"Pals-Release-Id: {_RELEASE_ID}\r\n"
        f"Pals-Deployment-Binding-Sha256: {_DEPLOYMENT_SHA}\r\n"
    ).encode("ascii")


def _request(context: ssl.SSLContext, raw_request: bytes) -> tuple[int, dict[str, object]]:
    with (
        socket.create_connection(("127.0.0.1", 18117), timeout=5) as raw,
        context.wrap_socket(raw, server_hostname="verifier.internal") as connection,
    ):
        connection.sendall(raw_request)
        response = http.client.HTTPResponse(connection)
        response.begin()
        assert response.getheader("Content-Type") == "application/json"
        assert response.getheader("Pals-Release-Id") == str(_RELEASE_ID)
        assert response.getheader("Pals-Deployment-Binding-Sha256") == _DEPLOYMENT_SHA
        content = response.read()
        assert response.getheader("Content-Length") == str(len(content))
    payload = json.loads(content)
    assert isinstance(payload, dict)
    assert rfc8785.dumps(cast(Any, payload)) == content
    return response.status, payload


def _spki_sha256(certificate_der: bytes) -> str:
    certificate = x509.load_der_x509_certificate(certificate_der)
    return hashlib.sha256(
        certificate.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).hexdigest()


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
