from __future__ import annotations

import pytest

from pals_agent.lean_verifier.tls_material import (
    Boto3SecretBinaryReader,
    SecretBinaryReference,
    TlsMaterialError,
    VerifierServerTlsConfiguration,
)


class FakeSecretsClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, str]] = []

    def get_secret_value(self, **kwargs: str) -> object:
        self.calls.append(kwargs)
        return self.response


def test_secret_reader_uses_exact_arn_and_immutable_version() -> None:
    reference = _reference("server-cert", "version-1")
    client = FakeSecretsClient(
        {
            "ARN": reference.arn,
            "VersionId": reference.version_id,
            "SecretBinary": b"certificate-bytes",
        }
    )

    result = Boto3SecretBinaryReader(client).get(reference)

    assert result == b"certificate-bytes"
    assert client.calls == [
        {"SecretId": reference.arn, "VersionId": reference.version_id}
    ]


@pytest.mark.parametrize(
    "response",
    [
        {},
        {
            "ARN": "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:other",
            "VersionId": "version-1",
            "SecretBinary": b"certificate-bytes",
        },
        {
            "ARN": "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:server-cert",
            "VersionId": "version-2",
            "SecretBinary": b"certificate-bytes",
        },
        {
            "ARN": "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:server-cert",
            "VersionId": "version-1",
            "SecretString": "not-permitted",
            "SecretBinary": b"certificate-bytes",
        },
    ],
)
def test_secret_reader_rejects_aliases_and_nonbinary_material(response: object) -> None:
    reference = _reference("server-cert", "version-1")

    with pytest.raises(TlsMaterialError):
        Boto3SecretBinaryReader(FakeSecretsClient(response)).get(reference)


def test_tls_configuration_rejects_a_mismatched_reconciler_identity() -> None:
    with pytest.raises(ValueError):
        VerifierServerTlsConfiguration(
            server_certificate=_reference("server-cert", "cert-version"),
            server_private_key=_reference("server-key", "key-version"),
            ca_certificate=_reference("ca", "ca-version"),
            server_name="pals-lean-verifier.internal",
            environment="local",
            ca_spki_sha256="a" * 64,
            reconciler_client_spki_sha256="b" * 64,
            reconciler_client_spiffe_uri="spiffe://pals/dev/verified-reconciler",
        )


def _reference(name: str, version_id: str) -> SecretBinaryReference:
    return SecretBinaryReference(
        arn=f"arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:{name}",
        version_id=version_id,
    )
