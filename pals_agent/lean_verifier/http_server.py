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
from pathlib import Path
from typing import Any, Final, Protocol, cast
from uuid import UUID

import rfc8785
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from pals_agent.models import VerificationResult

_REQUEST_SCHEMA_VERSION: Final = "pals.isolated-verifier-request.v1"
_READINESS_SCHEMA_VERSION: Final = "pals.isolated-verifier-readiness.v1"
_ATTESTATION_SCHEMA_VERSION: Final = "pals.verifier-attestation.v1"
_ERROR_SCHEMA_VERSION: Final = "pals.isolated-verifier-error.v1"
_ADMISSION_REQUEST_SCHEMA_VERSION: Final = "pals.recipe-admission-verifier-request.v1"
_ADMISSION_RESULT_SCHEMA_VERSION: Final = "pals.recipe-admission-verifier-result.v1"
_ADMISSION_COMMAND_SCHEMA_VERSION: Final = "pals.recipe-admission-compiler-command.v1"
_ADMISSION_RESULT_DETAIL_SCHEMA_VERSION: Final = "pals.recipe-admission-compiler-result.v1"
_TOOLCHAIN_FINGERPRINT_SCHEMA_VERSION: Final = "pals.lean-toolchain-fingerprint.v1"
_MATERIALIZER_VERSION: Final = "pals.recipe-materializer.v1"
_MAX_REQUEST_BYTES: Final = 4_194_304
_MAX_RESPONSE_BYTES: Final = 16_384
_VERIFIER_PORT: Final = 18_117
_PROOF_JOB_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_ADMISSION_SOURCE_BYTES: Final = 480_000


@dataclass(frozen=True, slots=True)
class RecipeAdmissionVerifierContext:
    """The pinned workspace identity and normalized command the admission receipt binds."""

    toolchain_fingerprint: dict[str, str]
    compiler_command: dict[str, object]

    def __post_init__(self) -> None:
        fingerprint = _validated_toolchain_fingerprint(self.toolchain_fingerprint)
        command = _validated_admission_compiler_command(self.compiler_command)
        object.__setattr__(self, "toolchain_fingerprint", fingerprint)
        object.__setattr__(self, "compiler_command", command)

    @property
    def toolchain_fingerprint_jcs(self) -> bytes:
        return _canonical_json(self.toolchain_fingerprint)

    @property
    def toolchain_fingerprint_sha256(self) -> str:
        return _sha256_bytes(self.toolchain_fingerprint_jcs)

    @property
    def compiler_command_sha256(self) -> str:
        return _sha256_bytes(_canonical_json(self.compiler_command))


def pinned_recipe_admission_context(
    *,
    project_dir: Path,
    verifier_sha256: str,
) -> RecipeAdmissionVerifierContext:
    """Bind admissions to the immutable files used by the same pinned Lean workspace.

    The command is intentionally normalized: the private verifier writes the untrusted source to a
    random scratch directory, so a literal temporary path must not enter an immutable receipt.
    ``Main.lean`` denotes that fixed file name within the fresh verifier-owned scratch directory.
    """

    if _SHA256_RE.fullmatch(verifier_sha256) is None:
        raise ValueError("verifier SHA-256 must be a lowercase SHA-256")
    manifest = project_dir / "lake-manifest.json"
    toolchain = project_dir / "lean-toolchain"
    lakefile = project_dir / "lakefile.lean"
    if not manifest.is_file() or not toolchain.is_file() or not lakefile.is_file():
        raise ValueError("recipe admission requires a pinned Lean workspace")
    try:
        lean_version = toolchain.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("pinned Lean toolchain is not UTF-8") from error
    if not lean_version or lean_version.strip() != lean_version:
        raise ValueError("pinned Lean toolchain is not one exact nonblank value")
    manifest_sha256 = _sha256_bytes(manifest.read_bytes())
    toolchain_sha256 = _sha256_bytes(toolchain.read_bytes())
    return RecipeAdmissionVerifierContext(
        toolchain_fingerprint={
            "schema_version": _TOOLCHAIN_FINGERPRINT_SCHEMA_VERSION,
            "lean_version": lean_version,
            "lake_manifest_sha256": manifest_sha256,
            "verifier_sha256": verifier_sha256,
            "materializer_version": _MATERIALIZER_VERSION,
        },
        compiler_command={
            "schema_version": _ADMISSION_COMMAND_SCHEMA_VERSION,
            "argv": ["lake", "env", "lean", "--threads=1", "Main.lean"],
            "workspace_lake_manifest_sha256": manifest_sha256,
            "workspace_lean_toolchain_sha256": toolchain_sha256,
        },
    )


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
    recipe_admission_context: RecipeAdmissionVerifierContext
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
        if not isinstance(self.recipe_admission_context, RecipeAdmissionVerifierContext):
            raise ValueError("recipe admission context must bind a pinned verifier workspace")
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
        self.recipe_admission_context = settings.recipe_admission_context
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
        if self.path == "/v1/verify":
            self._verify_proof_job()
            return
        if self.path == "/v1/recipe-admissions/verify":
            self._verify_recipe_admission()
            return
        self.close_connection = True

    def _verify_proof_job(self) -> None:
        if not self._trusted_peer():
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
                    "lean_sha256": hashlib.sha256(request["lean_code"].encode("utf-8")).hexdigest(),
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
            self._error(
                422,
                failure_code,
                request["proof_job_id"],
                retryable=False,
                diagnostics=_repair_diagnostics(result, request["lean_code"]),
            )

    def _verify_recipe_admission(self) -> None:
        """Compile one closed Recipe source without importing proof-job/artifact semantics."""
        if not self._trusted_peer():
            self.close_connection = True
            return
        if not self._binding_headers_match():
            self._admission_error(
                409,
                "verifier_release_binding_mismatch",
                admission_id=None,
                retryable=False,
            )
            return
        admission_id, request = self._admission_request()
        if request is None:
            self._admission_error(
                400,
                "verifier_request_invalid",
                admission_id=admission_id,
                retryable=False,
            )
            return
        if not self.server.ready:
            self._admission_error(
                503,
                "verifier_not_ready",
                admission_id=admission_id,
                retryable=True,
            )
            return
        if not self.server.compile_slot.acquire(blocking=False):
            # The API admission transport has a closed retryable registry.  Keep the same code as
            # a not-ready verifier rather than leaking the proof-job endpoint's unrelated code.
            self._admission_error(
                503,
                "verifier_not_ready",
                admission_id=admission_id,
                retryable=True,
            )
            return
        try:
            result = self.server.verifier.verify(cast(str, request["materialized_source"]))
        except BaseException:
            self._admission_error(
                503,
                "verifier_not_ready",
                admission_id=admission_id,
                retryable=True,
            )
            return
        finally:
            self.server.compile_slot.release()

        if not result.success:
            failure_code = _failure_code(result)
            self._admission_error(
                504 if failure_code == "verifier_timeout" else 422,
                failure_code,
                admission_id=admission_id,
                retryable=failure_code == "verifier_timeout",
            )
            return
        context = self.server.recipe_admission_context
        self._write_canonical_json(
            200,
            {
                "schema_version": _ADMISSION_RESULT_SCHEMA_VERSION,
                "status": "verified",
                "admission_id": str(admission_id),
                "materialized_source_sha256": request["materialized_source_sha256"],
                "toolchain_fingerprint": context.toolchain_fingerprint,
                "toolchain_fingerprint_sha256": context.toolchain_fingerprint_sha256,
                "compiler_command_sha256": context.compiler_command_sha256,
                "compiler_result": _admission_compiler_result(result),
            },
        )

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
            or set(value) != {"lean_code", "proof_job_id", "result_artifact_uri", "schema_version"}
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

    def _admission_request(self) -> tuple[UUID | None, dict[str, object] | None]:
        """Return only an exact RFC 8785 Recipe-admission request.

        A valid correlation ID is retained for a failed request so the release caller can safely
        associate the closed failure with its own request.  Invalid or absent IDs intentionally
        become ``null`` in a transport-invalid response; such a response can never validate
        against a release command request.
        """
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
        admission_id = _candidate_admission_id(value)
        try:
            canonical_value = _canonical_json(value)
        except ValueError:
            return admission_id, None
        if not isinstance(value, dict) or canonical_value != raw:
            return admission_id, None
        if set(value) != {
            "schema_version",
            "admission_id",
            "materialized_source",
            "materialized_source_sha256",
            "expected_toolchain_fingerprint",
            "expected_toolchain_fingerprint_sha256",
        }:
            return admission_id, None
        source = value.get("materialized_source")
        source_sha256 = value.get("materialized_source_sha256")
        expected_fingerprint = value.get("expected_toolchain_fingerprint")
        expected_fingerprint_sha256 = value.get("expected_toolchain_fingerprint_sha256")
        if (
            value.get("schema_version") != _ADMISSION_REQUEST_SCHEMA_VERSION
            or admission_id is None
            or not isinstance(source, str)
            or not source
            or not isinstance(source_sha256, str)
            or _SHA256_RE.fullmatch(source_sha256) is None
            or not isinstance(expected_fingerprint, dict)
            or not isinstance(expected_fingerprint_sha256, str)
            or _SHA256_RE.fullmatch(expected_fingerprint_sha256) is None
        ):
            return admission_id, None
        try:
            source_bytes = source.encode("utf-8")
        except UnicodeEncodeError:
            return admission_id, None
        if (
            len(source_bytes) > _MAX_ADMISSION_SOURCE_BYTES
            or _sha256_bytes(source_bytes) != source_sha256
        ):
            return admission_id, None
        try:
            normalized_fingerprint = _validated_toolchain_fingerprint(expected_fingerprint)
            fingerprint_jcs = _canonical_json(normalized_fingerprint)
        except ValueError:
            return admission_id, None
        if (
            fingerprint_jcs != _canonical_json(expected_fingerprint)
            or _sha256_bytes(fingerprint_jcs) != expected_fingerprint_sha256
            or fingerprint_jcs != self.server.recipe_admission_context.toolchain_fingerprint_jcs
        ):
            return admission_id, None
        return admission_id, {
            "materialized_source": source,
            "materialized_source_sha256": source_sha256,
        }

    def _error(
        self,
        status: int,
        code: str,
        proof_job_id: str | None,
        *,
        retryable: bool,
        diagnostics: list[dict[str, object]] | None = None,
    ) -> None:
        self._write_json(
            status,
            {
                "error_code": code,
                "proof_job_id": proof_job_id,
                "retryable": retryable,
                "schema_version": _ERROR_SCHEMA_VERSION,
                **({"diagnostics": diagnostics} if diagnostics is not None else {}),
            },
        )

    def _admission_error(
        self,
        status: int,
        code: str,
        *,
        admission_id: UUID | None,
        retryable: bool,
    ) -> None:
        self._write_canonical_json(
            status,
            {
                "schema_version": _ADMISSION_RESULT_SCHEMA_VERSION,
                "status": "failed",
                "admission_id": None if admission_id is None else str(admission_id),
                "failure_code": code,
                "retryable": retryable,
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

    def _write_canonical_json(self, status: int, value: dict[str, object]) -> None:
        try:
            encoded = _canonical_json(value)
        except ValueError:
            self.close_connection = True
            return
        self._write_encoded_json(status, encoded)

    def _write_encoded_json(self, status: int, encoded: bytes) -> None:
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


def _candidate_admission_id(value: object) -> UUID | None:
    if not isinstance(value, dict) or not isinstance(value.get("admission_id"), str):
        return None
    text = value["admission_id"]
    try:
        admission_id = UUID(text)
    except ValueError:
        return None
    if admission_id.version != 4 or str(admission_id) != text:
        return None
    return admission_id


def _valid_proof_job_id(value: object) -> str | None:
    return value if isinstance(value, str) and _PROOF_JOB_ID_RE.fullmatch(value) else None


def _nonblank_string(value: object, *, maximum: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def _canonical_json(value: object) -> bytes:
    try:
        return rfc8785.dumps(cast(Any, value))
    except (TypeError, UnicodeError, ValueError) as error:
        raise ValueError("value is not RFC 8785 canonical JSON") from error


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validated_toolchain_fingerprint(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "lean_version",
        "lake_manifest_sha256",
        "verifier_sha256",
        "materializer_version",
    }:
        raise ValueError("toolchain fingerprint must be one closed v1 object")
    schema_version = value.get("schema_version")
    lean_version = value.get("lean_version")
    lake_manifest_sha256 = value.get("lake_manifest_sha256")
    verifier_sha256 = value.get("verifier_sha256")
    materializer_version = value.get("materializer_version")
    if (
        schema_version != _TOOLCHAIN_FINGERPRINT_SCHEMA_VERSION
        or not _bounded_text(lean_version, maximum=512)
        or not isinstance(lake_manifest_sha256, str)
        or _SHA256_RE.fullmatch(lake_manifest_sha256) is None
        or not isinstance(verifier_sha256, str)
        or _SHA256_RE.fullmatch(verifier_sha256) is None
        or materializer_version != _MATERIALIZER_VERSION
    ):
        raise ValueError("toolchain fingerprint has an invalid v1 field")
    return {
        "schema_version": cast(str, schema_version),
        "lean_version": cast(str, lean_version),
        "lake_manifest_sha256": lake_manifest_sha256,
        "verifier_sha256": verifier_sha256,
        "materializer_version": cast(str, materializer_version),
    }


def _validated_admission_compiler_command(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "argv",
        "workspace_lake_manifest_sha256",
        "workspace_lean_toolchain_sha256",
    }:
        raise ValueError("recipe admission compiler command must be one closed v1 object")
    argv = value.get("argv")
    manifest_sha256 = value.get("workspace_lake_manifest_sha256")
    toolchain_sha256 = value.get("workspace_lean_toolchain_sha256")
    if (
        value.get("schema_version") != _ADMISSION_COMMAND_SCHEMA_VERSION
        or argv != ["lake", "env", "lean", "--threads=1", "Main.lean"]
        or not isinstance(manifest_sha256, str)
        or _SHA256_RE.fullmatch(manifest_sha256) is None
        or not isinstance(toolchain_sha256, str)
        or _SHA256_RE.fullmatch(toolchain_sha256) is None
    ):
        raise ValueError("recipe admission compiler command is invalid")
    return {
        "schema_version": _ADMISSION_COMMAND_SCHEMA_VERSION,
        "argv": list(argv),
        "workspace_lake_manifest_sha256": manifest_sha256,
        "workspace_lean_toolchain_sha256": toolchain_sha256,
    }


def _bounded_text(value: object, *, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.strip() == value
        and len(value.encode("utf-8")) <= maximum
    )


def _admission_compiler_result(result: VerificationResult) -> dict[str, object]:
    """Keep the receipt bounded and deterministic while proving compiler acceptance.

    The raw streams may contain verifier-owned temporary paths and are intentionally not released as
    an admission DTO.  Their semantic result is represented by the closed diagnostic-code sequence.
    """

    codes = [diagnostic.code for diagnostic in result.diagnostics]
    if any(not _bounded_text(code, maximum=256) for code in codes):
        raise ValueError("verifier emitted an invalid diagnostic code")
    return {
        "schema_version": _ADMISSION_RESULT_DETAIL_SCHEMA_VERSION,
        "verification_succeeded": True,
        "diagnostic_codes": codes,
    }


def _canonical_uuid4(value: UUID) -> str | None:
    return str(value) if value.version == 4 and str(value) == str(value).lower() else None


def _failure_code(result: VerificationResult) -> str:
    if any(item.code in {"lean.timeout", "lean.verifier_timeout"} for item in result.diagnostics):
        return "verifier_timeout"
    return "verifier_compile_failed"


def _repair_diagnostics(result: VerificationResult, source: str) -> list[dict[str, object]]:
    """Export a closed repair vocabulary, never compiler text, paths or subprocess output."""
    diagnostics: list[dict[str, object]] = []
    patterns = (
        (
            "lean.already_declared",
            r"^['`‘]([A-Za-z_][A-Za-z0-9_'.]{0,127})['`’] has already been declared\.?$",
        ),
        (
            "lean.unknown_identifier",
            r"^[Uu]nknown (?:identifier|constant) ['`‘]([A-Za-z_][A-Za-z0-9_'.]{0,127})['`’]\.?$",
        ),
    )
    for item in result.diagnostics:
        if item.severity != "error":
            continue
        code, symbol = "lean.compile_error", None
        first_line = item.message.splitlines()[0] if item.message else ""
        for candidate_code, pattern in patterns:
            match = re.fullmatch(pattern, first_line)
            if match and match.group(1) in source:
                code, symbol = candidate_code, match.group(1)
                break
        if code == "lean.compile_error":
            for prefix, category in (
                ("unsolved goals", "lean.unsolved_goals"),
                ("type mismatch", "lean.type_mismatch"),
                ("application type mismatch", "lean.type_mismatch"),
                ("unexpected token", "lean.syntax_error"),
                ("tactic", "lean.tactic_failed"),
            ):
                if first_line.lower().startswith(prefix):
                    code = category
                    break
        diagnostics.append(
            {
                "code": code,
                "symbol": symbol,
                "line": item.line
                if type(item.line) is int and 1 <= item.line <= 1_000_000
                else None,
                "column": item.column
                if type(item.column) is int and 0 <= item.column <= 1_000_000
                else None,
            }
        )
        if len(diagnostics) == 8:
            break
    return diagnostics
