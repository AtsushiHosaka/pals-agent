from __future__ import annotations

import ssl
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from pals_agent.lean_verifier import boundary as boundary_module
from pals_agent.lean_verifier import http_runtime
from pals_agent.lean_verifier.http_runtime import (
    _ALLOWED_REFERENCE_ENVIRONMENT_NAMES,
    HttpVerifierRuntimeSettings,
    _secrets_client,
)
from pals_agent.lean_verifier.http_server import RecipeAdmissionVerifierContext


def test_runtime_requires_exact_immutable_transport_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_environment(monkeypatch)

    settings = HttpVerifierRuntimeSettings.from_env()

    assert settings.bind_host == "0.0.0.0"
    assert settings.project_dir.as_posix() == "/app/lean-workspace"
    assert settings.timeout_seconds == 300.0
    assert settings.binding.release_id == UUID("018a3b10-514d-4d6d-845e-3f322b74bca0")
    assert settings.tls.server_certificate.arn.endswith("verifier-server-certificate")
    assert settings.tls.server_private_key.version_id == "key-version-1"
    assert settings.tls.ca_certificate.version_id == "ca-version-1"
    assert settings.tls.reconciler_client_spiffe_uri == ("spiffe://pals/local/verified-reconciler")


def test_runtime_accepts_only_the_production_mounted_tls_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_environment(monkeypatch)
    monkeypatch.setenv("PALS_ENV", "prod")
    monkeypatch.setenv(
        "PALS_RECONCILER_CLIENT_SPIFFE_URI",
        "spiffe://pals/prod/verified-reconciler",
    )
    for name in tuple(_ALLOWED_REFERENCE_ENVIRONMENT_NAMES):
        if name.startswith("PALS_VERIFIER_") and "SECRET_" in name:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PALS_VERIFIER_TLS_DIRECTORY", "/run/pals-verifier-tls")

    settings = HttpVerifierRuntimeSettings.from_env()

    assert settings.tls_directory == Path("/run/pals-verifier-tls")
    assert settings.tls.server_certificate.arn == (
        "arn:pals:mounted-verifier-tls:server-certificate"
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PALS_LEAN_TIMEOUT_SECONDS", "299"),
        ("PALS_RECONCILER_CLIENT_SPIFFE_URI", "spiffe://pals/dev/verified-reconciler"),
        ("PALS_VERIFIER_SERVER_CERTIFICATE_SECRET_ARN", "server-certificate"),
        ("PALS_VERIFIER_CA_SPKI_SHA256", "A" * 64),
    ],
)
def test_runtime_rejects_nonadmitted_tls_configuration(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    _set_required_environment(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError):
        HttpVerifierRuntimeSettings.from_env()


def test_local_runtime_uses_fixed_localstack_signing_without_credential_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_environment(monkeypatch)
    settings = HttpVerifierRuntimeSettings.from_env()
    calls: list[tuple[str, dict[str, str]]] = []
    sentinel = object()

    def fake_client(service_name: str, **kwargs: str) -> object:
        calls.append((service_name, kwargs))
        return sentinel

    monkeypatch.setattr("pals_agent.lean_verifier.http_runtime.boto3.client", fake_client)

    assert _secrets_client(settings) is sentinel
    assert calls == [
        (
            "secretsmanager",
            {
                "region_name": "ap-northeast-1",
                "endpoint_url": "http://localstack:4566",
                "aws_access_key_id": "test",
                "aws_secret_access_key": "test",
            },
        )
    ]


def test_local_runtime_rejects_non_localstack_secrets_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_environment(monkeypatch)
    monkeypatch.setenv("PALS_AWS_ENDPOINT_URL", "http://untrusted:4566")

    with pytest.raises(ValueError, match="exact LocalStack Secrets endpoint"):
        _secrets_client(HttpVerifierRuntimeSettings.from_env())


def test_nonlocal_runtime_uses_ambient_task_role_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_environment(monkeypatch)
    monkeypatch.setenv("PALS_ENV", "dev")
    monkeypatch.setenv(
        "PALS_RECONCILER_CLIENT_SPIFFE_URI",
        "spiffe://pals/dev/verified-reconciler",
    )
    monkeypatch.delenv("PALS_AWS_ENDPOINT_URL")
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_client(service_name: str, **kwargs: str) -> object:
        calls.append((service_name, kwargs))
        return object()

    monkeypatch.setattr("pals_agent.lean_verifier.http_runtime.boto3.client", fake_client)

    _secrets_client(HttpVerifierRuntimeSettings.from_env())

    assert calls == [("secretsmanager", {"region_name": "ap-northeast-1"})]


def test_ecs_task_role_reference_environment_is_allowed_but_keys_are_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pals_agent.lean_verifier.boundary.os.environ",
        {
            "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/v2/credentials/task",
            "AWS_DEFAULT_REGION": "ap-northeast-1",
            "AWS_EXECUTION_ENV": "AWS_ECS_EC2",
            "AWS_REGION": "ap-northeast-1",
            "AWS_ACCESS_KEY_ID": "must-be-rejected",
        },
    )

    assert boundary_module._credential_environment_names(_ALLOWED_REFERENCE_ENVIRONMENT_NAMES) == (
        "AWS_ACCESS_KEY_ID",
    )


def test_runtime_marks_ready_only_after_boundary_tls_and_server_setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_required_environment(monkeypatch)
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    ready_marker = scratch_dir / "verifier-ready"
    events: list[str] = []

    class Server:
        def serve_forever(self) -> None:
            assert ready_marker.is_file()
            events.append("served")

        def server_close(self) -> None:
            assert not ready_marker.exists()
            events.append("closed")

    tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls_context.minimum_version = ssl.TLSVersion.TLSv1_3
    tls_context.verify_mode = ssl.CERT_REQUIRED
    material = SimpleNamespace(
        ssl_context=tls_context,
        reconciler_client_spki_sha256="e" * 64,
        reconciler_client_spiffe_uri="spiffe://pals/local/verified-reconciler",
    )

    def attest(**_kwargs: object) -> None:
        assert not ready_marker.exists()
        events.append("attested")

    monkeypatch.setattr(http_runtime, "_SCRATCH_DIRECTORY", scratch_dir)
    monkeypatch.setattr(http_runtime, "_READY_MARKER", ready_marker)
    monkeypatch.setattr(
        http_runtime,
        "attest_http_runtime_boundary",
        attest,
    )
    monkeypatch.setattr(http_runtime, "_secrets_client", lambda _settings: object())
    monkeypatch.setattr(
        http_runtime,
        "build_verifier_server_tls_material",
        lambda *_args, **_kwargs: material,
    )
    monkeypatch.setattr(
        http_runtime,
        "pinned_recipe_admission_context",
        lambda **_kwargs: RecipeAdmissionVerifierContext(
            toolchain_fingerprint={
                "schema_version": "pals.lean-toolchain-fingerprint.v1",
                "lean_version": "leanprover/lean4:v4.32.0-rc1",
                "lake_manifest_sha256": "a" * 64,
                "verifier_sha256": "b" * 64,
                "materializer_version": "pals.recipe-materializer.v1",
            },
            compiler_command={
                "schema_version": "pals.recipe-admission-compiler-command.v1",
                "argv": ["lake", "env", "lean", "--threads=1", "Main.lean"],
                "workspace_lake_manifest_sha256": "a" * 64,
                "workspace_lean_toolchain_sha256": "c" * 64,
            },
        ),
    )
    monkeypatch.setattr(http_runtime, "LeanVerifier", lambda **_kwargs: object())
    monkeypatch.setattr(http_runtime, "create_server", lambda *_args, **_kwargs: Server())

    http_runtime.main()

    assert events == ["attested", "served", "closed"]
    assert not ready_marker.exists()


def test_runtime_never_marks_ready_when_boundary_attestation_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_required_environment(monkeypatch)
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    ready_marker = scratch_dir / "verifier-ready"
    monkeypatch.setattr(http_runtime, "_SCRATCH_DIRECTORY", scratch_dir)
    monkeypatch.setattr(http_runtime, "_READY_MARKER", ready_marker)
    monkeypatch.setattr(
        http_runtime,
        "attest_http_runtime_boundary",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("attestation failed")),
    )

    with pytest.raises(SystemExit, match="2"):
        http_runtime.main()

    assert not ready_marker.exists()


def _set_required_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    environment = {
        "PALS_VERIFIER_BIND_HOST": "0.0.0.0",
        "PALS_LEAN_PROJECT_DIR": "/app/lean-workspace",
        "PALS_AWS_REGION": "ap-northeast-1",
        "PALS_AWS_ENDPOINT_URL": "http://localstack:4566",
        "PALS_RELEASE_ID": "018a3b10-514d-4d6d-845e-3f322b74bca0",
        "PALS_VERIFIER_DEPLOYMENT_BINDING_SHA256": "a" * 64,
        "PALS_VERIFIER_IMAGE_DIGEST": "sha256:" + "b" * 64,
        "PALS_VERIFIER_TOOLCHAIN_SHA256": "c" * 64,
        "PALS_VERIFIER_SERVER_CERTIFICATE_SECRET_ARN": (
            "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:verifier-server-certificate"
        ),
        "PALS_VERIFIER_SERVER_CERTIFICATE_SECRET_VERSION_ID": "certificate-version-1",
        "PALS_VERIFIER_SERVER_PRIVATE_KEY_SECRET_ARN": (
            "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:verifier-server-private-key"
        ),
        "PALS_VERIFIER_SERVER_PRIVATE_KEY_SECRET_VERSION_ID": "key-version-1",
        "PALS_VERIFIER_CA_CERTIFICATE_SECRET_ARN": (
            "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:ca-certificate"
        ),
        "PALS_VERIFIER_CA_CERTIFICATE_SECRET_VERSION_ID": "ca-version-1",
        "PALS_VERIFIER_SERVER_NAME": "pals-lean-verifier.internal",
        "PALS_ENV": "local",
        "PALS_VERIFIER_CA_SPKI_SHA256": "d" * 64,
        "PALS_RECONCILER_CLIENT_SPKI_SHA256": "e" * 64,
        "PALS_RECONCILER_CLIENT_SPIFFE_URI": "spiffe://pals/local/verified-reconciler",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
