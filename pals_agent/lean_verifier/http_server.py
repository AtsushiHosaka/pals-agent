"""Private TLS 1.3 mTLS HTTP endpoint for the isolated Lean verifier.

The worker never imports this module.  It is the Agent-owned server half of PRX-003:
only an API reconciler presenting the admitted client certificate can request a compile, and a
successful response is constructed only after the injected compiler reports success.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import re
import ssl
import threading
from dataclasses import dataclass
from email.message import Message
from typing import Any, Final, Protocol
from uuid import UUID

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from pals_agent.models import VerificationResult

_REQUEST_SCHEMA_VERSION: Final = "pals.isolated-verifier-request.v1"
_READINESS_SCHEMA_VERSION: Final = "pals.isolated-verifier-readiness.v1"
_ATTESTATION_SCHEMA_VERSION: Final = "pals.verifier-attestation.v1"
_ERROR_SCHEMA_VERSION: Final = "pals.isolated-verifier-error.v1"
_MAX_REQUEST_BYTES: Final = 4_194_304
_MAX_RESPONSE_BYTES: Final = 16_384
_VERIFIER_PORT: Final = 18_117
_PROOF_JOB_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")


class LeanVerifierPort(Protocol):
    """The compiler boundary implemented by the verifier image only."""

    def verify(self, lean_code: str) -> VerificationResult:  # pragma: no cover - Protocol shape
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class VerifierDeploymentBinding:
    release_id: UUID
    deployment_binding_sha256: str
    verifier_image_digest: str
    verifier_toolchain_sha256: str

    def __post_init__(self) -> None:
        if _canonical_uuid4(self.release_id) is None:
            raise ValueError("release_id must be UUIDv4")
        for name, value in (
            ("deployment_binding_sha256", self.deployment_binding_sha256),
            ("verifier_toolchain_sha256", self.verifier_toolchain_sha256),
        ):
            if _SHA256_RE.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256")
        if _IMAGE_DIGEST_RE.fullmatch(self.verifier_image_digest) is None:
            raise ValueError("verifier_image_digest must be a sha256 image digest")


@dataclass(frozen=True, slots=True)
class IsolatedVerifierHttpSettings:
    """Already-admitted runtime values; secret retrieval is intentionally outside this server."""

    bind_host: str
    binding: VerifierDeploymentBinding
    ssl_context: ssl.SSLContext
    reconciler_client_spki_sha256: str
    reconciler_client_spiffe_uri: str
    port: int = _VERIFIER_PORT
    max_concurrent_compiles: int = 1

    def __post_init__(self) -> None:
        if not self.bind_host or self.bind_host.strip() != self.bind_host:
            raise ValueError("bind_host must be a nonblank private endpoint host")
        if self.port != _VERIFIER_PORT:
            raise ValueError("isolated verifier must bind port 18117")
        if self.max_concurrent_compiles != 1:
            raise ValueError("isolated verifier accepts exactly one concurrent compile")
        if _SHA256_RE.fullmatch(self.reconciler_client_spki_sha256) is None:
            raise ValueError("reconciler client SPKI must be a lowercase SHA-256")
        if not self.reconciler_client_spiffe_uri.startswith("spiffe://pals/"):
            raise ValueError("reconciler client identity must be an admitted SPIFFE URI")
        if (
            self.ssl_context.minimum_version < ssl.TLSVersion.TLSv1_3
            or self.ssl_context.verify_mode != ssl.CERT_REQUIRED
        ):
            raise ValueError("isolated verifier requires TLS 1.3 mTLS")


class ThreadingTlsVerifierServer(http.server.ThreadingHTTPServer):
    """A one-slot TLS server which rejects every caller except the reconciler certificate."""

    daemon_threads = False
    block_on_close = True
    allow_reuse_address = True

    def __init__(
        self,
        settings: IsolatedVerifierHttpSettings,
        verifier: LeanVerifierPort,
    ) -> None:
        self.settings = settings
        self.verifier = verifier
        self.compile_slot = threading.BoundedSemaphore(1)
        self.ready = True
        super().__init__((settings.bind_host, settings.port), _RequestHandler)

    def get_request(self) -> tuple[ssl.SSLSocket, tuple[str, int]]:
        connection, address = super().get_request()
        try:
            tls_connection = self.settings.ssl_context.wrap_socket(
                connection,
                server_side=True,
            )
        except BaseException:
            connection.close()
            raise
        return tls_connection, address


class _RequestHandler(http.server.BaseHTTPRequestHandler):
    server: ThreadingTlsVerifierServer
    protocol_version = "HTTP/1.1"
    server_version = ""
    sys_version = ""

    def log_message(self, _format: str, *args: object) -> None:
        """The verifier never writes request material to an access log."""

    def send_error(self, _code: int, _message: str | None = None, *_args: object) -> None:
        # Unsupported/invalid HTTP methods are an untrusted transport failure, not a new API.
        self.close_connection = True

    def do_GET(self) -> None:
        if self.path != "/ready" or not self._trusted_peer():
            self.close_connection = True
            return
        if not self._binding_headers_match():
            self._error(409, "verifier_release_binding_mismatch", None, retryable=False)
            return
        if not self.server.ready:
            self._error(503, "verifier_not_ready", None, retryable=True)
            return
        binding = self.server.settings.binding
        self._write_json(
            200,
            {
                "deployment_binding_sha256": binding.deployment_binding_sha256,
                "release_id": str(binding.release_id),
                "schema_version": _READINESS_SCHEMA_VERSION,
                "status": "ready",
                "verifier_image_digest": binding.verifier_image_digest,
                "verifier_toolchain_sha256": binding.verifier_toolchain_sha256,
            },
        )

    def do_POST(self) -> None:
        if self.path != "/v1/verify" or not self._trusted_peer():
            self.close_connection = True
            return
        if not self._binding_headers_match():
            self._error(409, "verifier_release_binding_mismatch", None, retryable=False)
            return
        proof_job_id, request = self._verification_request()
        if request is None:
            self._error(400, "verifier_request_invalid", proof_job_id, retryable=False)
            return
        if not self.server.ready:
            self._error(503, "verifier_not_ready", proof_job_id, retryable=True)
            return
        if not self.server.compile_slot.acquire(blocking=False):
            self._error(503, "verifier_unavailable", proof_job_id, retryable=True)
            return
        try:
            result = self.server.verifier.verify(request["lean_code"])
        except BaseException:
            # An unexpected compiler/cleanup failure is deliberately not translated into success.
            self.close_connection = True
            return
        finally:
            self.server.compile_slot.release()

        if result.success:
            self._write_json(
                200,
                {
                    "lean_sha256": hashlib.sha256(
                        request["lean_code"].encode("utf-8")
                    ).hexdigest(),
                    "proof_job_id": request["proof_job_id"],
                    "result_artifact_uri": request["result_artifact_uri"],
                    "schema_version": _ATTESTATION_SCHEMA_VERSION,
                    "verification_succeeded": True,
                },
            )
            return
        failure_code = _failure_code(result)
        if failure_code == "verifier_timeout":
            self._error(504, failure_code, request["proof_job_id"], retryable=True)
        else:
            self._error(422, failure_code, request["proof_job_id"], retryable=False)

    def _trusted_peer(self) -> bool:
        connection = self.connection
        if not isinstance(connection, ssl.SSLSocket) or connection.version() != "TLSv1.3":
            return False
        peer_der = connection.getpeercert(binary_form=True)
        if not isinstance(peer_der, bytes) or not peer_der:
            return False
        try:
            certificate = x509.load_der_x509_certificate(peer_der)
            client_spki_sha256 = hashlib.sha256(
                certificate.public_key().public_bytes(
                    serialization.Encoding.DER,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            ).hexdigest()
            identities = certificate.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value.get_values_for_type(x509.UniformResourceIdentifier)
        except (ValueError, x509.ExtensionNotFound):
            return False
        return (
            client_spki_sha256 == self.server.settings.reconciler_client_spki_sha256
            and identities == [self.server.settings.reconciler_client_spiffe_uri]
        )

    def _binding_headers_match(self) -> bool:
        binding = self.server.settings.binding
        return (
            _single_header(self.headers, "Pals-Release-Id") == str(binding.release_id)
            and _single_header(self.headers, "Pals-Deployment-Binding-Sha256")
            == binding.deployment_binding_sha256
        )

    def _verification_request(self) -> tuple[str | None, dict[str, str] | None]:
        if (
            _single_header(self.headers, "Content-Type") != "application/json"
            or self.headers.get_all("Transfer-Encoding") is not None
        ):
            return None, None
        length_text = _single_header(self.headers, "Content-Length")
        if (
            length_text is None
            or not length_text.isascii()
            or not length_text.isdecimal()
            or (len(length_text) > 1 and length_text.startswith("0"))
        ):
            return None, None
        length = int(length_text, 10)
        if not 1 <= length <= _MAX_REQUEST_BYTES:
            return None, None
        raw = self.rfile.read(length)
        if len(raw) != length:
            return None, None
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None, None
        proof_job_id = _candidate_proof_job_id(value)
        if (
            not isinstance(value, dict)
            or set(value)
            != {"lean_code", "proof_job_id", "result_artifact_uri", "schema_version"}
            or value.get("schema_version") != _REQUEST_SCHEMA_VERSION
            or _valid_proof_job_id(value.get("proof_job_id")) is None
            or not _nonblank_string(value.get("lean_code"), maximum=200_000)
            or not _nonblank_string(value.get("result_artifact_uri"), maximum=2_048)
        ):
            return proof_job_id, None
        return proof_job_id, {
            "lean_code": value["lean_code"],
            "proof_job_id": value["proof_job_id"],
            "result_artifact_uri": value["result_artifact_uri"],
        }

    def _error(
        self,
        status: int,
        code: str,
        proof_job_id: str | None,
        *,
        retryable: bool,
    ) -> None:
        self._write_json(
            status,
            {
                "error_code": code,
                "proof_job_id": proof_job_id,
                "retryable": retryable,
                "schema_version": _ERROR_SCHEMA_VERSION,
            },
        )

    def _write_json(self, status: int, value: dict[str, object]) -> None:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_RESPONSE_BYTES:
            self.close_connection = True
            return
        binding = self.server.settings.binding
        self.send_response_only(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Pals-Release-Id", str(binding.release_id))
        self.send_header(
            "Pals-Deployment-Binding-Sha256",
            binding.deployment_binding_sha256,
        )
        self.end_headers()
        self.wfile.write(encoded)


def create_server(
    settings: IsolatedVerifierHttpSettings,
    *,
    verifier: LeanVerifierPort,
) -> ThreadingTlsVerifierServer:
    return ThreadingTlsVerifierServer(settings, verifier)


def _single_header(headers: Message[str, str], name: str) -> str | None:
    values = headers.get_all(name)
    if values is None or len(values) != 1 or "," in values[0]:
        return None
    return values[0]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _candidate_proof_job_id(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    return _valid_proof_job_id(value.get("proof_job_id"))


def _valid_proof_job_id(value: object) -> str | None:
    return value if isinstance(value, str) and _PROOF_JOB_ID_RE.fullmatch(value) else None


def _nonblank_string(value: object, *, maximum: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def _canonical_uuid4(value: UUID) -> str | None:
    return str(value) if value.version == 4 and str(value) == str(value).lower() else None


def _failure_code(result: VerificationResult) -> str:
    if any(item.code == "lean.verifier_timeout" for item in result.diagnostics):
        return "verifier_timeout"
    return "verifier_compile_failed"
