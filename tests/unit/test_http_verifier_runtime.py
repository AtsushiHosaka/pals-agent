from __future__ import annotations

from uuid import UUID

import pytest

from pals_agent.lean_verifier.http_runtime import HttpVerifierRuntimeSettings, _secrets_client


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
    assert settings.tls.reconciler_client_spiffe_uri == (
        "spiffe://pals/local/verified-reconciler"
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

    monkeypatch.setattr(
        "pals_agent.lean_verifier.http_runtime.boto3.client", fake_client
    )

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

    monkeypatch.setattr(
        "pals_agent.lean_verifier.http_runtime.boto3.client", fake_client
    )

    _secrets_client(HttpVerifierRuntimeSettings.from_env())

    assert calls == [("secretsmanager", {"region_name": "ap-northeast-1"})]


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
            "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:"
            "verifier-server-certificate"
        ),
        "PALS_VERIFIER_SERVER_CERTIFICATE_SECRET_VERSION_ID": "certificate-version-1",
        "PALS_VERIFIER_SERVER_PRIVATE_KEY_SECRET_ARN": (
            "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:"
            "verifier-server-private-key"
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
