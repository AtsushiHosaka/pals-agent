"""Add the mounted private API CA without replacing existing public TLS trust."""

from __future__ import annotations

import atexit
import os
import re
import shutil
import ssl
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509

_MAX_API_CA_BYTES = 131_072
_MAX_ROOT_BUNDLE_BYTES = 8_388_608
_CERTIFICATE_BLOCK = re.compile(
    rb"-----BEGIN CERTIFICATE-----\r?\n[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----"
)


def configure_worker_api_trust(certificate_path: Path | None) -> Path | None:
    """Run before worker clients are built; unset configuration is an exact no-op."""
    if certificate_path is None:
        return None
    certificate = _read_api_ca(certificate_path)
    roots = _existing_root_bundles()
    directory = Path(tempfile.mkdtemp(prefix="pals-api-trust-", dir="/tmp"))
    bundle_path = directory / "ca-bundle.pem"
    try:
        descriptor = os.open(
            bundle_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600
        )
        with os.fdopen(descriptor, "wb") as bundle:
            for root in roots:
                bundle.write(root.rstrip() + b"\n")
            bundle.write(certificate.rstrip() + b"\n")
        # Validate the completed bundle before exposing it to clients or helpers.
        context = ssl.create_default_context(cafile=str(bundle_path))
        if not context.get_ca_certs():
            raise ValueError("Worker TLS root bundle contains no CA certificates")
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    atexit.register(shutil.rmtree, directory, ignore_errors=True)
    os.environ["SSL_CERT_FILE"] = str(bundle_path)
    return bundle_path


def _read_api_ca(path: Path) -> bytes:
    if not path.is_absolute():
        raise ValueError("API CA certificate path must be absolute")
    # Check every component, including directories: a final-file O_NOFOLLOW alone
    # would still permit a symlink in a parent directory.
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if stat.S_ISLNK(current.lstat().st_mode):
            raise ValueError("API CA certificate path must not contain symlinks")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as certificate_file:
        metadata = os.fstat(certificate_file.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o400
            or not 0 < metadata.st_size <= _MAX_API_CA_BYTES
        ):
            raise ValueError(
                "API CA certificate must be worker-owned, mode 0400 and bounded"
            )
        certificate = certificate_file.read(_MAX_API_CA_BYTES + 1)
        if len(certificate) > _MAX_API_CA_BYTES:
            raise ValueError("API CA certificate exceeds the byte limit")
    blocks = _CERTIFICATE_BLOCK.findall(certificate)
    if not 1 <= len(blocks) <= 8 or _CERTIFICATE_BLOCK.sub(b"", certificate).strip():
        raise ValueError("API CA file must contain only PEM certificates")
    try:
        certificates = x509.load_pem_x509_certificates(certificate)
        now = datetime.now(UTC)
        for parsed in certificates:
            constraints = parsed.extensions.get_extension_for_class(
                x509.BasicConstraints
            ).value
            if not constraints.ca:
                raise ValueError("API trust certificate must be a CA")
            if not parsed.not_valid_before_utc <= now <= parsed.not_valid_after_utc:
                raise ValueError("API CA certificate is outside its validity period")
            try:
                usage = parsed.extensions.get_extension_for_class(x509.KeyUsage).value
            except x509.ExtensionNotFound:
                usage = None
            if usage is not None and not usage.key_cert_sign:
                raise ValueError(
                    "API CA certificate does not permit signing certificates"
                )
    except (x509.ExtensionNotFound, ValueError) as error:
        raise ValueError("API CA certificate is invalid") from error
    return certificate


def _existing_root_bundles() -> list[bytes]:
    paths = ssl.get_default_verify_paths()
    candidates = [paths.cafile, paths.openssl_cafile]
    try:
        import certifi
    except ImportError:
        pass
    else:
        candidates.append(certifi.where())
    roots: list[bytes] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        identity = str(path.resolve())
        if identity in seen or not path.is_file():
            continue
        seen.add(identity)
        with path.open("rb") as source:
            root = source.read(_MAX_ROOT_BUNDLE_BYTES + 1)
        if not 0 < len(root) <= _MAX_ROOT_BUNDLE_BYTES:
            raise ValueError(
                "Existing TLS root bundle is empty or exceeds its byte limit"
            )
        roots.append(root)
    if not roots:
        # Preserve native OS certificate stores even when they have no PEM path.
        certificates = ssl.create_default_context().get_ca_certs(binary_form=True)
        if not certificates:
            raise ValueError("Existing public TLS trust roots are unavailable")
        roots.append(
            b"".join(ssl.DER_cert_to_PEM_cert(cert).encode() for cert in certificates)
        )
    return roots
