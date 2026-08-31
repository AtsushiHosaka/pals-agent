"""Memory-only verifier TLS material loading from immutable Secrets Manager versions."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import os
import ssl
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, padding, rsa

_SHA256_HEX_LENGTH: Final = 64
_SPIFFE_PREFIX: Final = "spiffe://pals/"


class TlsMaterialError(RuntimeError):
    """The verifier must not start when its admitted transport material is invalid."""


@dataclass(frozen=True, slots=True)
class SecretBinaryReference:
    arn: str
    version_id: str

    def __post_init__(self) -> None:
        if not self.arn.startswith("arn:") or any(character.isspace() for character in self.arn):
            raise ValueError("secret ARN must be a nonblank full ARN")
        if not self.version_id or any(character.isspace() for character in self.version_id):
            raise ValueError("secret version ID must be nonblank and whitespace-free")


class SecretBinaryReader(Protocol):
    def get(self, reference: SecretBinaryReference) -> bytes: ...


@dataclass(frozen=True, slots=True)
class Boto3SecretBinaryReader:
    """Reads exactly one immutable SecretBinary version; aliases and SecretString are rejected."""

    client: Any

    def get(self, reference: SecretBinaryReference) -> bytes:
        try:
            response = self.client.get_secret_value(
                SecretId=reference.arn,
                VersionId=reference.version_id,
            )
        except Exception as exc:
            raise TlsMaterialError("verifier transport secret retrieval failed") from exc
        value = response.get("SecretBinary") if isinstance(response, dict) else None
        if (
            not isinstance(response, dict)
            or response.get("ARN") != reference.arn
            or response.get("VersionId") != reference.version_id
            or response.get("SecretString") is not None
            or not isinstance(value, bytes)
            or not value
        ):
            raise TlsMaterialError("verifier transport secret response was invalid")
        return value


@dataclass(frozen=True, slots=True)
class MountedFileSecretBinaryReader:
    """Read exact rootless-container TLS mounts without following links."""

    files: Mapping[SecretBinaryReference, Path]

    def get(self, reference: SecretBinaryReference) -> bytes:
        path = self.files.get(reference)
        if path is None or not path.is_absolute():
            raise TlsMaterialError("verifier transport file reference was not admitted")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise TlsMaterialError("verifier transport file could not be opened") from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != stat.S_IRUSR
                or not 1 <= metadata.st_size <= 65_536
            ):
                raise TlsMaterialError("verifier transport file metadata was invalid")
            chunks: list[bytes] = []
            remaining = metadata.st_size
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    raise TlsMaterialError("verifier transport file was truncated")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise TlsMaterialError("verifier transport file changed while reading")
            return b"".join(chunks)
        finally:
            os.close(descriptor)


@dataclass(frozen=True, slots=True)
class VerifierServerTlsConfiguration:
    server_certificate: SecretBinaryReference
    server_private_key: SecretBinaryReference
    ca_certificate: SecretBinaryReference
    server_name: str
    environment: str
    ca_spki_sha256: str
    reconciler_client_spki_sha256: str
    reconciler_client_spiffe_uri: str

    def __post_init__(self) -> None:
        if not _is_private_dns_name(self.server_name):
            raise ValueError("verifier server name must be a private DNS name")
        if self.environment not in {"local", "dev", "prod"}:
            raise ValueError("verifier environment must be local, dev, or prod")
        for value in (self.ca_spki_sha256, self.reconciler_client_spki_sha256):
            if not _is_sha256(value):
                raise ValueError("transport SPKI digests must be lowercase SHA-256")
        if self.reconciler_client_spiffe_uri != (
            f"{_SPIFFE_PREFIX}{self.environment}/verified-reconciler"
        ):
            raise ValueError("reconciler client identity must be the admitted SPIFFE URI")


@dataclass(frozen=True, slots=True)
class VerifierServerTlsMaterial:
    """Validated memory-only material with no surviving private-key bytes."""

    ssl_context: ssl.SSLContext
    reconciler_client_spki_sha256: str
    reconciler_client_spiffe_uri: str


def build_verifier_server_tls_material(
    configuration: VerifierServerTlsConfiguration,
    *,
    reader: SecretBinaryReader,
) -> VerifierServerTlsMaterial:
    """Fetch, validate, and consume the exact three server-side SecretBinary versions.

    Python's SSL API accepts certificate/key filenames, not bytes.  Linux ``memfd`` supplies an
    anonymous in-memory file descriptor solely while ``load_cert_chain`` constructs the context;
    it is overwritten and closed before this function returns.  There is intentionally no disk or
    platform fallback.
    """

    certificate = bytearray(reader.get(configuration.server_certificate))
    private_key = bytearray(reader.get(configuration.server_private_key))
    ca_certificate = bytearray(reader.get(configuration.ca_certificate))
    try:
        parsed_certificate = _parse_certificate(certificate, label="server certificate")
        parsed_private_key = _parse_private_key(private_key)
        parsed_ca = _parse_certificate(ca_certificate, label="CA certificate")
        _validate_ca(parsed_ca, configuration.ca_spki_sha256)
        _validate_server_certificate(
            parsed_certificate,
            parsed_private_key,
            parsed_ca,
            server_name=configuration.server_name,
        )
        ssl_context = _build_ssl_context(
            certificate=certificate,
            private_key=private_key,
            ca_certificate=ca_certificate,
        )
    finally:
        _zero(certificate)
        _zero(private_key)
        _zero(ca_certificate)
    return VerifierServerTlsMaterial(
        ssl_context=ssl_context,
        reconciler_client_spki_sha256=configuration.reconciler_client_spki_sha256,
        reconciler_client_spiffe_uri=configuration.reconciler_client_spiffe_uri,
    )


def _parse_certificate(value: bytearray, *, label: str) -> x509.Certificate:
    pem = bytes(value)
    der = _canonical_pem_der(pem, label="CERTIFICATE")
    try:
        certificate = x509.load_der_x509_certificate(der)
    except ValueError as exc:
        raise TlsMaterialError(f"{label} was not a valid X.509 certificate") from exc
    if certificate.public_bytes(serialization.Encoding.DER) != der:
        raise TlsMaterialError(f"{label} PEM was not canonical")
    _validate_current(certificate, label=label)
    return certificate


def _parse_private_key(value: bytearray) -> Any:
    pem = bytes(value)
    der = _canonical_pem_der(pem, label="PRIVATE KEY")
    try:
        key = serialization.load_pem_private_key(pem, password=None)
    except ValueError as exc:
        raise TlsMaterialError("verifier private key was not an unencrypted PKCS#8 key") from exc
    if (
        key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        != der
    ):
        raise TlsMaterialError("verifier private key must use canonical PKCS#8")
    return key


def _canonical_pem_der(value: bytes, *, label: str) -> bytes:
    try:
        text = value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise TlsMaterialError("verifier transport PEM must be ASCII") from exc
    prefix = f"-----BEGIN {label}-----\n"
    suffix = f"-----END {label}-----\n"
    if not text.startswith(prefix) or not text.endswith(suffix):
        raise TlsMaterialError("verifier transport PEM delimiters were invalid")
    encoded = text[len(prefix) : -len(suffix)].replace("\n", "")
    if not encoded:
        raise TlsMaterialError("verifier transport PEM was empty")
    try:
        der = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise TlsMaterialError("verifier transport PEM base64 was invalid") from exc
    canonical = _pem(label, der)
    if canonical != value:
        raise TlsMaterialError("verifier transport PEM was not canonical")
    return der


def _pem(label: str, der: bytes) -> bytes:
    encoded = base64.b64encode(der).decode("ascii")
    lines = [encoded[index : index + 64] for index in range(0, len(encoded), 64)]
    return (f"-----BEGIN {label}-----\n" + "\n".join(lines) + f"\n-----END {label}-----\n").encode(
        "ascii"
    )


def _validate_ca(certificate: x509.Certificate, expected_spki_sha256: str) -> None:
    try:
        constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints).value
        usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
    except x509.ExtensionNotFound as exc:
        raise TlsMaterialError("verifier CA extensions were incomplete") from exc
    if not constraints.ca or not usage.key_cert_sign or not usage.crl_sign:
        raise TlsMaterialError("verifier CA certificate was not a signing CA")
    if _spki_sha256(certificate) != expected_spki_sha256:
        raise TlsMaterialError("verifier CA SPKI did not match the admitted binding")
    _verify_certificate_signature(certificate, certificate)


def _validate_server_certificate(
    certificate: x509.Certificate,
    private_key: Any,
    ca: x509.Certificate,
    *,
    server_name: str,
) -> None:
    try:
        constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints).value
        names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound as exc:
        raise TlsMaterialError("verifier server certificate extensions were incomplete") from exc
    if constraints.ca or names.get_values_for_type(x509.DNSName) != [server_name]:
        raise TlsMaterialError("verifier server certificate SAN did not match its endpoint")
    if names.get_values_for_type(x509.UniformResourceIdentifier):
        raise TlsMaterialError("verifier server certificate had an unexpected URI SAN")
    public_bytes = certificate.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if public_bytes != key_bytes:
        raise TlsMaterialError("verifier server certificate and private key did not match")
    if certificate.issuer != ca.subject:
        raise TlsMaterialError("verifier server certificate was not directly issued by its CA")
    _verify_certificate_signature(certificate, ca)


def _validate_current(certificate: x509.Certificate, *, label: str) -> None:
    now = datetime.now(UTC)
    if not certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc:
        raise TlsMaterialError(f"{label} was expired or not yet valid")


def _verify_certificate_signature(
    certificate: x509.Certificate,
    issuer: x509.Certificate,
) -> None:
    public_key = issuer.public_key()
    algorithm = certificate.signature_hash_algorithm
    try:
        if isinstance(public_key, rsa.RSAPublicKey):
            if algorithm is None:
                raise TlsMaterialError("RSA certificate signature omitted its hash")
            public_key.verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                padding.PKCS1v15(),
                algorithm,
            )
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            if algorithm is None:
                raise TlsMaterialError("EC certificate signature omitted its hash")
            public_key.verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                ec.ECDSA(algorithm),
            )
        elif isinstance(public_key, (ed25519.Ed25519PublicKey, ed448.Ed448PublicKey)):
            public_key.verify(certificate.signature, certificate.tbs_certificate_bytes)
        elif isinstance(public_key, dsa.DSAPublicKey):
            if algorithm is None:
                raise TlsMaterialError("DSA certificate signature omitted its hash")
            public_key.verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                algorithm,
            )
        else:
            raise TlsMaterialError("verifier certificate used an unsupported public key")
    except Exception as exc:
        raise TlsMaterialError("verifier certificate signature was invalid") from exc


def _build_ssl_context(
    *,
    certificate: bytearray,
    private_key: bytearray,
    ca_certificate: bytearray,
) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.verify_mode = ssl.CERT_REQUIRED
    try:
        context.load_verify_locations(cadata=bytes(ca_certificate).decode("ascii"))
        with (
            _anonymous_pem_path("pals-verifier-cert", certificate) as certificate_path,
            _anonymous_pem_path("pals-verifier-key", private_key) as private_key_path,
        ):
            context.load_cert_chain(certificate_path, private_key_path)
    except (OSError, ValueError, ssl.SSLError) as exc:
        raise TlsMaterialError("verifier TLS context could not be constructed") from exc
    return context


@contextmanager
def _anonymous_pem_path(label: str, value: bytearray) -> Iterator[str]:
    creator = getattr(os, "memfd_create", None)
    if creator is None:
        raise TlsMaterialError("verifier requires Linux memfd TLS loading")
    descriptor = creator(label, 0)
    fcntl.fcntl(descriptor, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
    try:
        _write_all(descriptor, value)
        yield f"/proc/self/fd/{descriptor}"
    finally:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            _write_all(descriptor, bytearray(len(value)))
        finally:
            os.close(descriptor)


def _write_all(descriptor: int, value: bytearray) -> None:
    remaining = memoryview(value)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("failed to write verifier TLS material")
        remaining = remaining[written:]


def _zero(value: bytearray) -> None:
    value[:] = b"\x00" * len(value)


def _spki_sha256(certificate: x509.Certificate) -> str:
    return hashlib.sha256(
        certificate.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).hexdigest()


def _is_sha256(value: str) -> bool:
    return (
        len(value) == _SHA256_HEX_LENGTH
        and value.isascii()
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_private_dns_name(value: str) -> bool:
    return (
        bool(value)
        and value.isascii()
        and "." in value
        and value == value.lower()
        and all(
            label
            and len(label) <= 63
            and label[0].isalnum()
            and label[-1].isalnum()
            and all(character.isalnum() or character == "-" for character in label)
            for label in value.split(".")
        )
    )
