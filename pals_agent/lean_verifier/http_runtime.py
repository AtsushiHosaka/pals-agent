"""Production entrypoint for the Agent-owned private mTLS Lean verifier."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import boto3  # type: ignore[import-untyped]

from pals_agent.lean import LeanVerifier
from pals_agent.lean_verifier.boundary import attest_http_runtime_boundary
from pals_agent.lean_verifier.http_server import (
    IsolatedVerifierHttpSettings,
    VerifierDeploymentBinding,
    create_server,
)
from pals_agent.lean_verifier.tls_material import (
    Boto3SecretBinaryReader,
    SecretBinaryReference,
    TlsMaterialError,
    VerifierServerTlsConfiguration,
    build_verifier_server_tls_material,
)

_LOGGER: Final = logging.getLogger("pals_agent.lean_verifier.http_runtime")
_PORT: Final = 18_117
_MAX_TIMEOUT_SECONDS: Final = 300.0
_SCRATCH_DIRECTORY: Final = Path("/run/pals-verifier-requests")
_SCRATCH_MAX_BYTES: Final = 64 * 1024 * 1024
_LOCALSTACK_ACCESS_KEY_ID: Final = "test"
_LOCALSTACK_TEST_SECRET: Final = "test"
_LOCALSTACK_SECRETS_ENDPOINT: Final = "http://localstack:4566"
_ALLOWED_REFERENCE_ENVIRONMENT_NAMES: Final = frozenset(
    {
        "PALS_AWS_REGION",
        "PALS_AWS_ENDPOINT_URL",
        "PALS_VERIFIER_SERVER_CERTIFICATE_SECRET_ARN",
        "PALS_VERIFIER_SERVER_CERTIFICATE_SECRET_VERSION_ID",
        "PALS_VERIFIER_SERVER_PRIVATE_KEY_SECRET_ARN",
        "PALS_VERIFIER_SERVER_PRIVATE_KEY_SECRET_VERSION_ID",
        "PALS_VERIFIER_CA_CERTIFICATE_SECRET_ARN",
        "PALS_VERIFIER_CA_CERTIFICATE_SECRET_VERSION_ID",
    }
)


@dataclass(frozen=True, slots=True)
class HttpVerifierRuntimeSettings:
    bind_host: str
    project_dir: Path
    timeout_seconds: float
    aws_region: str
    aws_endpoint_url: str | None
    binding: VerifierDeploymentBinding
    tls: VerifierServerTlsConfiguration

    @classmethod
    def from_env(cls) -> HttpVerifierRuntimeSettings:
        timeout_seconds = _positive_float("PALS_LEAN_TIMEOUT_SECONDS", _MAX_TIMEOUT_SECONDS)
        if timeout_seconds != _MAX_TIMEOUT_SECONDS:
            raise ValueError("PALS_LEAN_TIMEOUT_SECONDS must equal 300")
        return cls(
            bind_host=_required("PALS_VERIFIER_BIND_HOST"),
            project_dir=Path(_required("PALS_LEAN_PROJECT_DIR")),
            timeout_seconds=timeout_seconds,
            aws_region=_required("PALS_AWS_REGION"),
            aws_endpoint_url=_optional("PALS_AWS_ENDPOINT_URL"),
            binding=VerifierDeploymentBinding(
                release_id=_uuid4(_required("PALS_RELEASE_ID")),
                deployment_binding_sha256=_required(
                    "PALS_VERIFIER_DEPLOYMENT_BINDING_SHA256"
                ),
                verifier_image_digest=_required("PALS_VERIFIER_IMAGE_DIGEST"),
                verifier_toolchain_sha256=_required("PALS_VERIFIER_TOOLCHAIN_SHA256"),
            ),
            tls=VerifierServerTlsConfiguration(
                server_certificate=_reference(
                    "PALS_VERIFIER_SERVER_CERTIFICATE_SECRET_ARN",
                    "PALS_VERIFIER_SERVER_CERTIFICATE_SECRET_VERSION_ID",
                ),
                server_private_key=_reference(
                    "PALS_VERIFIER_SERVER_PRIVATE_KEY_SECRET_ARN",
                    "PALS_VERIFIER_SERVER_PRIVATE_KEY_SECRET_VERSION_ID",
                ),
                ca_certificate=_reference(
                    "PALS_VERIFIER_CA_CERTIFICATE_SECRET_ARN",
                    "PALS_VERIFIER_CA_CERTIFICATE_SECRET_VERSION_ID",
                ),
                server_name=_required("PALS_VERIFIER_SERVER_NAME"),
                environment=_required("PALS_ENV"),
                ca_spki_sha256=_required("PALS_VERIFIER_CA_SPKI_SHA256"),
                reconciler_client_spki_sha256=_required(
                    "PALS_RECONCILER_CLIENT_SPKI_SHA256"
                ),
                reconciler_client_spiffe_uri=_required(
                    "PALS_RECONCILER_CLIENT_SPIFFE_URI"
                ),
            ),
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        settings = HttpVerifierRuntimeSettings.from_env()
        if not _SCRATCH_DIRECTORY.is_dir():
            raise ValueError("verifier request scratch tmpfs is unavailable")
        attest_http_runtime_boundary(
            project_dir=settings.project_dir,
            scratch_dir=_SCRATCH_DIRECTORY,
            scratch_max_bytes=_SCRATCH_MAX_BYTES,
            allowed_reference_environment_names=_ALLOWED_REFERENCE_ENVIRONMENT_NAMES,
        )
        secrets_client = _secrets_client(settings)
        material = build_verifier_server_tls_material(
            settings.tls,
            reader=Boto3SecretBinaryReader(secrets_client),
        )
        server = create_server(
            IsolatedVerifierHttpSettings(
                bind_host=settings.bind_host,
                binding=settings.binding,
                ssl_context=material.ssl_context,
                reconciler_client_spki_sha256=material.reconciler_client_spki_sha256,
                reconciler_client_spiffe_uri=material.reconciler_client_spiffe_uri,
            ),
            verifier=LeanVerifier(
                project_dir=settings.project_dir,
                timeout_seconds=settings.timeout_seconds,
                scratch_dir=_SCRATCH_DIRECTORY,
            ),
        )
    except (TlsMaterialError, OSError, ValueError) as exc:
        _LOGGER.error("verifier startup failed: %s", type(exc).__name__)
        raise SystemExit(2) from None

    _LOGGER.info(
        "isolated verifier ready: transport=mtls-http port=%d release_id=%s",
        _PORT,
        settings.binding.release_id,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _required(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value or value.strip() != value:
        raise ValueError(f"{name} must be nonblank")
    return value


def _optional(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    if not value or value.strip() != value:
        raise ValueError(f"{name} must be nonblank when configured")
    return value


def _positive_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a finite positive number") from exc
    if parsed <= 0 or not parsed < float("inf"):
        raise ValueError(f"{name} must be a finite positive number")
    return parsed


def _uuid4(value: str) -> UUID:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError("PALS_RELEASE_ID must be UUIDv4") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("PALS_RELEASE_ID must be canonical UUIDv4")
    return parsed


def _reference(arn_name: str, version_name: str) -> SecretBinaryReference:
    return SecretBinaryReference(
        arn=_required(arn_name),
        version_id=_required(version_name),
    )


def _secrets_client(settings: HttpVerifierRuntimeSettings) -> Any:
    """Construct the sole Secrets Manager client without credential environment input.

    LocalStack accepts the public ``test`` signing identity.  Keeping that local-only identity in
    the client construction prevents a credential-shaped environment variable from entering the
    verifier process, which the runtime boundary deliberately rejects.  Dev and production use
    the ambient task role credential provider chain instead.
    """

    kwargs: dict[str, str] = {"region_name": settings.aws_region}
    if settings.aws_endpoint_url is not None:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    if settings.tls.environment == "local":
        if settings.aws_endpoint_url != _LOCALSTACK_SECRETS_ENDPOINT:
            raise ValueError("local verifier must use the exact LocalStack Secrets endpoint")
        kwargs.update(
            aws_access_key_id=_LOCALSTACK_ACCESS_KEY_ID,
            aws_secret_access_key=_LOCALSTACK_TEST_SECRET,
        )
    return boto3.client("secretsmanager", **kwargs)


if __name__ == "__main__":
    main()
