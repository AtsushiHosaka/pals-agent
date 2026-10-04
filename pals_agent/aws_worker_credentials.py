"""Read one host-renewed Worker STS session for the SDK credential_process.

Mount the service directory read-only, not credentials.json itself: the broker
atomically replaces that file. No AWS call, disk cache or ambient fallback occurs.
Only the SDK-facing successful stdout contains credentials; errors are closed.
An independently mounted host policy fixes the expected role and session name.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_KEYS = {"Version", "AccessKeyId", "SecretAccessKey", "SessionToken", "Expiration"}
_EXPIRY = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z")
_STATE_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00\Z")
_ACCESS_KEY = re.compile(r"ASIA[A-Z0-9]{16}\Z")
_STATE_KEYS = {
    "version",
    "ready",
    "role_arn",
    "session_name",
    "checked_at",
    "expires_at",
    "reason",
}
_WORKER_SESSION_NAME = "pals-mini-worker"
_DEFAULT_POLICY_PATH = Path("/run/credentials-policy/worker-role.json")
_POLICY_KEYS = {"version", "role_arn", "session_name"}
_ROLE_ARN = re.compile(
    r"arn:(?:aws|aws-us-gov|aws-cn):iam::(?!0{12}:)[0-9]{12}:role/"
    r"(?:[A-Za-z0-9_+=,.@-]+/)*[A-Za-z0-9_+=,.@-]{1,64}\Z"
)
_MAX_BYTES = 16384
_ERROR = "Worker AWS session is unavailable."


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, item in pairs:
        if name in value:
            raise ValueError("Worker session record is invalid")
        value[name] = item
    return value


def _validate_record(data: bytes, *, now: datetime) -> dict[str, Any]:
    if not 1 <= len(data) <= _MAX_BYTES:
        raise ValueError("Worker session record is invalid")
    value = json.loads(data, object_pairs_hook=_unique_members)
    if (
        not isinstance(value, dict)
        or set(value) != _KEYS
        or type(value["Version"]) is not int
        or value["Version"] != 1
        or not isinstance(value["AccessKeyId"], str)
        or not _ACCESS_KEY.fullmatch(value["AccessKeyId"])
    ):
        raise ValueError("Worker session record is invalid")
    for field in ("SecretAccessKey", "SessionToken"):
        token = value[field]
        if (
            not isinstance(token, str)
            or not 16 <= len(token) <= 8192
            or any(ord(character) < 33 or ord(character) > 126 for character in token)
        ):
            raise ValueError("Worker session record is invalid")
    expiration = value["Expiration"]
    if not isinstance(expiration, str) or not _EXPIRY.fullmatch(expiration):
        raise ValueError("Worker session record is invalid")
    expires_at = datetime.fromisoformat(expiration.replace("Z", "+00:00"))
    if now.tzinfo is None or not now < expires_at <= now + timedelta(minutes=65):
        raise ValueError("Worker session record is invalid")
    return value


def _trusted_directory(directory: Path) -> int:
    if not directory.is_absolute() or directory.resolve(strict=True) != directory:
        raise ValueError("Worker session directory is invalid")
    for parent in directory.parents:
        metadata = parent.stat()
        sticky_root = metadata.st_uid == 0 and metadata.st_mode & stat.S_ISVTX
        if metadata.st_uid not in {0, os.geteuid()} or metadata.st_mode & 0o022 and not sticky_root:
            raise ValueError("Worker session directory is invalid")
    descriptor = os.open(directory, os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if (
            metadata.st_uid not in {0, os.geteuid()}
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or not stat.S_ISDIR(metadata.st_mode)
        ):
            raise ValueError("Worker session directory is invalid")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_private_file(directory_descriptor: int, name: str) -> bytes:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW,
        dir_fd=directory_descriptor,
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid not in {0, os.geteuid()}
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise ValueError("Worker session file is invalid")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(_MAX_BYTES + 1)
        if not 1 <= len(data) <= _MAX_BYTES:
            raise ValueError("Worker session file is invalid")
        return data
    finally:
        os.close(descriptor)


def _read_policy(path: Path, credential_directory: Path) -> dict[str, Any]:
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("Worker role policy path is invalid")
    policy_directory = path.parent
    if (
        policy_directory == credential_directory
        or policy_directory in credential_directory.parents
        or credential_directory in policy_directory.parents
    ):
        raise ValueError("Worker role policy must be independent of the credential directory")
    descriptor = _trusted_directory(policy_directory)
    try:
        value = json.loads(
            _read_private_file(descriptor, path.name), object_pairs_hook=_unique_members
        )
    finally:
        os.close(descriptor)
    if (
        not isinstance(value, dict)
        or set(value) != _POLICY_KEYS
        or type(value["version"]) is not int
        or value["version"] != 1
        or not isinstance(value["role_arn"], str)
        or len(value["role_arn"]) > 2048
        or not _ROLE_ARN.fullmatch(value["role_arn"])
        or value["session_name"] != _WORKER_SESSION_NAME
    ):
        raise ValueError("Worker role policy is invalid")
    return value


def _validate_ready_state(
    data: bytes, credentials: dict[str, Any], policy: dict[str, Any], *, now: datetime
) -> None:
    # This is an assertion by the trusted host broker, not an STS identity call.
    value = json.loads(data, object_pairs_hook=_unique_members)
    if (
        not isinstance(value, dict)
        or set(value) != _STATE_KEYS
        or type(value["version"]) is not int
        or value["version"] != 1
        or value["ready"] is not True
        or value["reason"] is not None
        or value["role_arn"] != policy["role_arn"]
        or value["session_name"] != policy["session_name"]
        or value["expires_at"] != credentials["Expiration"]
        or not isinstance(value["checked_at"], str)
        or not _STATE_TIMESTAMP.fullmatch(value["checked_at"])
        or not _STATE_TIMESTAMP.fullmatch(value["expires_at"])
    ):
        raise ValueError("Worker broker is not ready")
    checked_at = datetime.fromisoformat(value["checked_at"].replace("Z", "+00:00"))
    expires_at = datetime.fromisoformat(credentials["Expiration"].replace("Z", "+00:00"))
    earliest_check = now - timedelta(minutes=35)
    lifetime = expires_at - checked_at
    if not earliest_check <= checked_at <= now < expires_at or lifetime > timedelta(minutes=65):
        raise ValueError("Worker broker is not ready")


def read_credentials(
    directory: Path, *, now: datetime | None = None, policy_path: Path | None = None
) -> dict[str, Any]:
    """Read a complete session and matching ready marker through one trusted directory.

    The broker writes credentials before the matching marker. Mismatched expirations
    are refused until both files agree. A later broker failure cannot revoke an
    already-cached SDK session; this check applies at process invocation only.
    """
    now = now or datetime.now(UTC)
    directory_descriptor = _trusted_directory(directory)
    try:
        policy = _read_policy(
            policy_path if policy_path is not None else _DEFAULT_POLICY_PATH, directory
        )
        credentials = _validate_record(
            _read_private_file(directory_descriptor, "credentials.json"), now=now
        )
        _validate_ready_state(
            _read_private_file(directory_descriptor, "state.json"), credentials, policy, now=now
        )
        return credentials
    finally:
        os.close(directory_descriptor)


def main(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    check_only = len(arguments) == 2 and arguments[0] == "--check"
    try:
        if len(arguments) != 1 and not check_only:
            raise ValueError("Worker session arguments are invalid")
        value = read_credentials(Path(arguments[-1]))
    except (OSError, ValueError, TypeError, RecursionError):
        print(_ERROR, file=sys.stderr)
        return 1
    if not check_only:
        print(json.dumps(value, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
