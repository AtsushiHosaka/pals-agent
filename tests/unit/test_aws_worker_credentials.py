"""Offline worker credential boundary tests using synthetic, nonworking records.

Only the stdlib adapter is imported. No SDK/profile invocation, real credentials,
worker execution, network, database or engine is used. The shell setup tests stop
before credential_process and run with a wholly synthetic environment.
"""

from __future__ import annotations

import configparser
import importlib.util
import json
import os
import re
import socket
import stat
import subprocess
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_MODULE = _ROOT / "pals_agent" / "aws_worker_credentials.py"
_LAUNCHER = _ROOT / "scripts" / "start-worker-with-credentials.sh"
_PROFILE = _ROOT / "scripts" / "aws-worker-profile.conf"
_NOW = datetime(2026, 10, 2, 0, 0, 0, tzinfo=UTC)
_ROLE = "arn:aws:iam::111111111111:role/synthetic/worker"
_SESSION = "pals-mini-worker"
_CHECK = (
    "/usr/local/bin/python -I -m pals_agent.aws_worker_credentials --check /run/credentials/worker"
)
_ERROR = "Worker AWS session is unavailable.\n"
_REAL_POPEN = subprocess.Popen


def _load_adapter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("worker_credential_boundary", _MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = _load_adapter()


def _deny_external(*args: Any, **kwargs: Any) -> NoReturn:
    raise AssertionError("This unit test must not execute external processes or network calls")


@pytest.fixture(autouse=True)
def _offline_boundary(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(socket, "create_connection", _deny_external)
    monkeypatch.setattr(socket.socket, "connect", _deny_external)
    monkeypatch.setattr(subprocess, "Popen", _deny_external)
    yield


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _synthetic_credentials(*, expires_at: datetime | None = None) -> dict[str, Any]:
    return {
        "Version": 1,
        "AccessKeyId": "ASIA0000000000000000",
        "SecretAccessKey": "SYNTHETIC-NONWORKING-SECRET-00000000000000",
        "SessionToken": "SYNTHETIC-NONWORKING-SESSION-TOKEN-00000000",
        "Expiration": _timestamp(expires_at or _NOW + timedelta(minutes=60)),
    }


def _synthetic_state(credentials: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "ready": True,
        "role_arn": _ROLE,
        "session_name": _SESSION,
        "checked_at": _timestamp(_NOW),
        "expires_at": credentials["Expiration"],
        "reason": None,
    }


def _write_private(path: Path, value: dict[str, Any] | bytes) -> None:
    data = json.dumps(value).encode() if isinstance(value, dict) else value
    path.write_bytes(data)
    path.chmod(0o600)


@pytest.fixture
def handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path.resolve() / "worker"
    directory.mkdir(mode=0o700)
    credentials = _synthetic_credentials()
    _write_private(directory / "credentials.json", credentials)
    _write_private(directory / "state.json", _synthetic_state(credentials))
    policy_directory = tmp_path.resolve() / "policy"
    policy_directory.mkdir(mode=0o700)
    policy_path = policy_directory / "worker-role.json"
    _write_private(policy_path, {"version": 1, "role_arn": _ROLE, "session_name": _SESSION})
    monkeypatch.setattr(adapter, "_DEFAULT_POLICY_PATH", policy_path)
    return directory


def test_reads_exact_worker_session_and_ready_marker(handoff: Path) -> None:
    assert adapter.read_credentials(handoff, now=_NOW) == _synthetic_credentials()
    assert set(json.loads((handoff / "state.json").read_bytes())) == {
        "version",
        "ready",
        "role_arn",
        "session_name",
        "checked_at",
        "expires_at",
        "reason",
    }


def test_expected_role_comes_from_independent_policy(handoff: Path) -> None:
    policy_path = Path(adapter._DEFAULT_POLICY_PATH)
    assert adapter.read_credentials(handoff, now=_NOW, policy_path=policy_path) == (
        _synthetic_credentials()
    )
    policy = json.loads(policy_path.read_bytes())
    policy["role_arn"] = _ROLE.replace("/worker", "/different-worker")
    _write_private(policy_path, policy)
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", True),
        ("version", 2),
        ("version", "1"),
        ("role_arn", None),
        ("role_arn", ""),
        ("role_arn", _ROLE.replace("111111111111", "000000000000")),
        ("role_arn", _ROLE.replace("111111111111", "11111111111")),
        ("role_arn", _ROLE.replace(":role/", ":user/")),
        ("role_arn", _ROLE + "/"),
        ("role_arn", _ROLE + "\n"),
        ("session_name", None),
        ("session_name", "pals-mini-api"),
        ("session_name", _SESSION + " "),
    ],
)
def test_rejects_invalid_independent_policy(handoff: Path, field: str, value: Any) -> None:
    policy_path = Path(adapter._DEFAULT_POLICY_PATH)
    policy = json.loads(policy_path.read_bytes())
    policy[field] = value
    _write_private(policy_path, policy)
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


@pytest.mark.parametrize("change", ["extra", "missing", "duplicate"])
def test_policy_requires_closed_unique_members(handoff: Path, change: str) -> None:
    policy_path = Path(adapter._DEFAULT_POLICY_PATH)
    policy = json.loads(policy_path.read_bytes())
    if change == "extra":
        policy["unexpected"] = None
        _write_private(policy_path, policy)
    elif change == "missing":
        del policy["role_arn"]
        _write_private(policy_path, policy)
    else:
        data = json.dumps(policy)
        _write_private(policy_path, (data[:-1] + ',"version":1}').encode())
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


@pytest.mark.parametrize("data", [b"", b"not-json", b"[]", b" " * 16385, b"\xff"])
def test_policy_rejects_invalid_or_unbounded_records(handoff: Path, data: bytes) -> None:
    _write_private(Path(adapter._DEFAULT_POLICY_PATH), data)
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


@pytest.mark.parametrize("location", ["same", "ancestor", "descendant"])
def test_policy_and_credential_directories_must_be_disjoint(handoff: Path, location: str) -> None:
    if location == "same":
        directory = handoff
    elif location == "ancestor":
        directory = handoff.parent
    else:
        directory = handoff / "policy"
        directory.mkdir(mode=0o700)
    policy_path = directory / "worker-role.json"
    _write_private(policy_path, {"version": 1, "role_arn": _ROLE, "session_name": _SESSION})
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW, policy_path=policy_path)


@pytest.mark.parametrize("mode", [0o400, 0o640, 0o644, 0o660, 0o777])
def test_policy_requires_private_file_mode(handoff: Path, mode: int) -> None:
    Path(adapter._DEFAULT_POLICY_PATH).chmod(mode)
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


@pytest.mark.parametrize("mode", [0o500, 0o750, 0o755, 0o770, 0o777])
def test_policy_requires_private_directory_mode(handoff: Path, mode: int) -> None:
    Path(adapter._DEFAULT_POLICY_PATH).parent.chmod(mode)
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "fifo", "missing"])
def test_policy_rejects_unsafe_files(handoff: Path, kind: str) -> None:
    path = Path(adapter._DEFAULT_POLICY_PATH)
    saved = path.with_suffix(".fixture")
    path.replace(saved)
    if kind == "symlink":
        path.symlink_to(saved)
    elif kind == "hardlink":
        path.hardlink_to(saved)
    elif kind == "directory":
        path.mkdir(mode=0o600)
    elif kind == "fifo":
        os.mkfifo(path, mode=0o600)
    with pytest.raises((OSError, ValueError)):
        adapter.read_credentials(handoff, now=_NOW)


def test_policy_rejects_symlinked_directory_and_relative_path(handoff: Path) -> None:
    path = Path(adapter._DEFAULT_POLICY_PATH)
    alias = handoff.parent / "policy-alias"
    alias.symlink_to(path.parent, target_is_directory=True)
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW, policy_path=alias / path.name)
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW, policy_path=Path("worker-role.json"))


def test_missing_policy_cannot_use_ready_state_or_ambient_role(
    handoff: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _freeze_reader(monkeypatch)
    monkeypatch.setenv("AWS_ROLE_ARN", _ROLE)
    Path(adapter._DEFAULT_POLICY_PATH).unlink()
    for arguments in ([str(handoff)], ["--check", str(handoff)]):
        assert adapter.main(arguments) == 1
        assert capsys.readouterr() == ("", _ERROR)


def test_public_adapter_has_no_embedded_account_role() -> None:
    assert Path("/run/credentials-policy/worker-role.json") == _load_adapter()._DEFAULT_POLICY_PATH
    assert re.search(r"arn:(?:aws|aws-us-gov|aws-cn):iam::[0-9]{12}:", _MODULE.read_text()) is None


@pytest.mark.parametrize("field", ["SecretAccessKey", "SessionToken"])
@pytest.mark.parametrize("token", ["short", "A" * 8193, "X" * 16 + "\n", "X" * 16 + "é"])
def test_rejects_invalid_session_fields(handoff: Path, field: str, token: str) -> None:
    credentials = _synthetic_credentials()
    credentials[field] = token
    _write_private(handoff / "credentials.json", credentials)
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Version", True),
        ("Version", 2),
        ("Version", "1"),
        ("AccessKeyId", "AKIA0000000000000000"),
        ("AccessKeyId", "ASIA000000000000000"),
        ("AccessKeyId", None),
        ("Expiration", None),
        ("Expiration", "2026-10-02T01:00:00"),
        ("Expiration", "2026-10-02T01:00:00+09:00"),
        ("Expiration", "2026-02-30T01:00:00+00:00"),
    ],
)
def test_rejects_invalid_credential_schema(handoff: Path, field: str, value: Any) -> None:
    credentials = _synthetic_credentials()
    credentials[field] = value
    _write_private(handoff / "credentials.json", credentials)
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(seconds=-1), timedelta(minutes=66)])
def test_rejects_expired_or_long_lived_credentials(handoff: Path, offset: timedelta) -> None:
    credentials = _synthetic_credentials(expires_at=_NOW + offset)
    _write_private(handoff / "credentials.json", credentials)
    _write_private(handoff / "state.json", _synthetic_state(credentials))
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


def test_rejects_naive_current_time(handoff: Path) -> None:
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW.replace(tzinfo=None))


@pytest.mark.parametrize("name", ["credentials.json", "state.json"])
@pytest.mark.parametrize("data", [b"", b"not-json", b"[]", b" " * 16385, b"\xff"])
def test_rejects_unbounded_or_invalid_records(handoff: Path, name: str, data: bytes) -> None:
    _write_private(handoff / name, data)
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


@pytest.mark.parametrize("name", ["credentials.json", "state.json"])
@pytest.mark.parametrize("change", ["extra", "missing", "duplicate"])
def test_requires_exact_unique_json_members(handoff: Path, name: str, change: str) -> None:
    path = handoff / name
    value = json.loads(path.read_bytes())
    first = next(iter(value))
    if change == "extra":
        value["unexpected"] = None
        _write_private(path, value)
    elif change == "missing":
        del value[first]
        _write_private(path, value)
    else:
        data = json.dumps(value)
        duplicate = json.dumps({first: value[first]})[1:]
        _write_private(path, (data[:-1] + "," + duplicate).encode())
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", True),
        ("version", 2),
        ("ready", False),
        ("ready", 1),
        ("reason", "authentication-or-renewal-failed"),
        ("role_arn", _ROLE.replace("/worker", "/api")),
        ("role_arn", _ROLE.replace("111111111111", "000000000000")),
        ("session_name", "pals-mini-api"),
        ("expires_at", None),
        ("expires_at", "2026-10-02T00:59:59+00:00"),
        ("checked_at", None),
        ("checked_at", "2026-10-02T00:00:00Z"),
        ("checked_at", "2026-10-02T00:00:00"),
        ("checked_at", "2026-10-02T00:00:00.001+00:00"),
        ("checked_at", "2026-02-30T00:00:00+00:00"),
        ("checked_at", "2026-10-02T00:00:01+00:00"),
        ("checked_at", "2026-10-01T23:24:59+00:00"),
        ("checked_at", "2026-10-01T23:54:59+00:00"),
    ],
)
def test_rejects_failed_stale_or_mismatched_broker_state(
    handoff: Path, field: str, value: Any
) -> None:
    state = _synthetic_state(_synthetic_credentials())
    state[field] = value
    _write_private(handoff / "state.json", state)
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


def test_accepts_broker_age_and_lifetime_limits(handoff: Path) -> None:
    credentials = _synthetic_credentials(expires_at=_NOW + timedelta(minutes=30))
    state = _synthetic_state(credentials)
    state["checked_at"] = _timestamp(_NOW - timedelta(minutes=35))
    _write_private(handoff / "credentials.json", credentials)
    _write_private(handoff / "state.json", state)
    assert adapter.read_credentials(handoff, now=_NOW) == credentials


@pytest.mark.parametrize("mode", [0o400, 0o640, 0o644, 0o660, 0o777])
@pytest.mark.parametrize("name", ["credentials.json", "state.json"])
def test_requires_exact_private_file_modes(handoff: Path, name: str, mode: int) -> None:
    (handoff / name).chmod(mode)
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


@pytest.mark.parametrize("mode", [0o500, 0o750, 0o755, 0o770, 0o777])
def test_requires_exact_private_directory_mode(handoff: Path, mode: int) -> None:
    handoff.chmod(mode)
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


def test_rejects_writable_ancestor(handoff: Path) -> None:
    parent = handoff.parent
    previous = stat.S_IMODE(parent.stat().st_mode)
    try:
        parent.chmod(0o777)
        with pytest.raises(ValueError):
            adapter.read_credentials(handoff, now=_NOW)
    finally:
        parent.chmod(previous)


def test_rejects_relative_and_noncanonical_directories(handoff: Path) -> None:
    with pytest.raises(ValueError):
        adapter.read_credentials(Path("worker"), now=_NOW)
    alias = handoff.parent / "alias"
    alias.symlink_to(handoff, target_is_directory=True)
    with pytest.raises(ValueError):
        adapter.read_credentials(alias, now=_NOW)
    with pytest.raises(ValueError):
        adapter.read_credentials(alias / ".." / "worker", now=_NOW)


@pytest.mark.parametrize("name", ["credentials.json", "state.json"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "fifo", "missing"])
def test_rejects_unsafe_file_types_and_links(handoff: Path, name: str, kind: str) -> None:
    path = handoff / name
    saved = handoff.parent / (name + ".fixture")
    path.replace(saved)
    if kind == "symlink":
        path.symlink_to(saved)
    elif kind == "hardlink":
        path.hardlink_to(saved)
    elif kind == "directory":
        path.mkdir(mode=0o600)
    elif kind == "fifo":
        os.mkfifo(path, mode=0o600)
    with pytest.raises((OSError, ValueError)):
        adapter.read_credentials(handoff, now=_NOW)
    assert saved.is_file()


@pytest.mark.parametrize("file_type", [stat.S_IFDIR, stat.S_IFREG])
def test_rejects_foreign_ownership(
    handoff: Path, file_type: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_fstat = os.fstat

    def foreign_owner(descriptor: int) -> os.stat_result:
        metadata = original_fstat(descriptor)
        if stat.S_IFMT(metadata.st_mode) == file_type:
            fields = list(metadata)
            fields[4] = max(os.geteuid(), 1) + 10000
            return os.stat_result(fields)
        return metadata

    monkeypatch.setattr(os, "fstat", foreign_owner)
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


def test_atomic_rotation_refuses_mixed_generation_then_accepts_new_pair(handoff: Path) -> None:
    previous_inode = (handoff / "credentials.json").stat().st_ino
    credentials = _synthetic_credentials(expires_at=_NOW + timedelta(minutes=61))
    credentials["SessionToken"] = "SYNTHETIC-NONWORKING-ROTATED-SESSION-TOKEN"
    staged = handoff / "pending.fixture"
    _write_private(staged, credentials)
    staged.replace(handoff / "credentials.json")
    assert (handoff / "credentials.json").stat().st_ino != previous_inode
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)
    _write_private(staged, _synthetic_state(credentials))
    staged.replace(handoff / "state.json")
    assert adapter.read_credentials(handoff, now=_NOW) == credentials
    assert sorted(path.name for path in handoff.iterdir()) == ["credentials.json", "state.json"]


def test_rotation_between_file_reads_fails_closed(
    handoff: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_read = adapter._read_private_file

    def read_then_rotate(descriptor: int, name: str) -> bytes:
        data: bytes = original_read(descriptor, name)
        if name == "credentials.json":
            credentials = _synthetic_credentials(expires_at=_NOW + timedelta(minutes=61))
            staged = handoff / "pending.fixture"
            _write_private(staged, credentials)
            staged.replace(handoff / "credentials.json")
            _write_private(staged, _synthetic_state(credentials))
            staged.replace(handoff / "state.json")
        return data

    monkeypatch.setattr(adapter, "_read_private_file", read_then_rotate)
    with pytest.raises(ValueError):
        adapter.read_credentials(handoff, now=_NOW)


def _freeze_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    original_read = adapter.read_credentials

    def frozen_reader(directory: Path) -> dict[str, Any]:
        value: dict[str, Any] = original_read(directory, now=_NOW)
        return value

    monkeypatch.setattr(adapter, "read_credentials", frozen_reader)


def test_check_is_silent_and_sdk_process_returns_only_v1_json(
    handoff: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _freeze_reader(monkeypatch)
    assert adapter.main(["--check", str(handoff)]) == 0
    assert capsys.readouterr() == ("", "")
    assert adapter.main([str(handoff)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == _synthetic_credentials()
    assert len(captured.out.splitlines()) == 1


@pytest.mark.parametrize("arguments", [[], ["--check"], ["a", "b"], ["--check", "a", "b"]])
def test_main_rejects_invalid_arguments_without_output(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert adapter.main(arguments) == 1
    assert capsys.readouterr() == ("", _ERROR)


def test_failed_precheck_and_process_never_fall_back_to_ambient_credentials(
    handoff: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _freeze_reader(monkeypatch)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "SYNTHETIC-AMBIENT-KEY")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "SYNTHETIC-AMBIENT-SECRET")
    monkeypatch.setenv("AWS_PROFILE", "SYNTHETIC-UNTRUSTED-PROFILE")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(handoff / "credentials.json"))
    (handoff / "state.json").unlink()
    for arguments in ([str(handoff)], ["--check", str(handoff)]):
        assert adapter.main(arguments) == 1
        assert capsys.readouterr() == ("", _ERROR)


def test_failures_are_redacted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_read(directory: Path) -> NoReturn:
        raise ValueError("SYNTHETIC-SECRET-MUST-NEVER-BE-LOGGED")

    monkeypatch.setattr(adapter, "read_credentials", fail_read)
    assert adapter.main(["/run/credentials/worker"]) == 1
    assert capsys.readouterr() == ("", _ERROR)


_AMBIENT_PROVIDERS = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN",
    "AWS_ACCESS_KEY",
    "AWS_SECRET_KEY",
    "AWS_CREDENTIAL_EXPIRATION",
    "AWS_DATA_PATH",
    "AWS_CREDENTIAL_FILE",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_ROLE_ARN",
    "AWS_ROLE_SESSION_NAME",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
    "AWS_ENDPOINT_URL",
    "AWS_ENDPOINT_URL_S3",
    "AWS_ENDPOINT_URL_SQS",
    "AWS_ENDPOINT_URL_STS",
}
_FIXED_ENVIRONMENT = {
    "PALS_ENV": "prod",
    "AWS_PROFILE": "pals-worker-runtime",
    "AWS_DEFAULT_PROFILE": "pals-worker-runtime",
    "PALS_AWS_REGION": "ap-northeast-1",
    "AWS_REGION": "ap-northeast-1",
    "AWS_DEFAULT_REGION": "ap-northeast-1",
    "AWS_CONFIG_FILE": "/app/scripts/aws-worker-profile.conf",
    "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
    "BOTO_CONFIG": "/dev/null",
    "AWS_EC2_METADATA_DISABLED": "true",
    "AWS_SDK_LOAD_CONFIG": "1",
    "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "true",
}


def test_launcher_precheck_precedes_fixed_worker_exec_and_profile_is_deployable() -> None:
    launcher = _LAUNCHER.read_text()
    assert launcher.startswith("#!/bin/sh\nset -eu\n")
    assert launcher.count(_CHECK) == 1
    assert launcher.index(_CHECK) < launcher.index('exec /usr/local/bin/pals-agent worker "$@"')
    assert launcher.split(_CHECK)[1].strip() == 'exec /usr/local/bin/pals-agent worker "$@"'
    assert "chmod" not in launcher and "sudo" not in launcher and "su " not in launcher
    profile = configparser.ConfigParser(interpolation=None)
    profile.read_string(_PROFILE.read_text())
    assert profile.sections() == ["profile pals-worker-runtime"]
    assert dict(profile["profile pals-worker-runtime"]) == {
        "region": "ap-northeast-1",
        "credential_process": (
            "/usr/local/bin/python -I -m pals_agent.aws_worker_credentials /run/credentials/worker"
        ),
    }


@pytest.fixture
def setup_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[str, dict[str, str]], subprocess.CompletedProcess[str]]:
    def run_setup(suffix: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        # Execute only the immutable launcher prefix, ending before the credential
        # precheck, plus shell builtin printf assertions. No profile or worker runs.
        setup, _, _ = _LAUNCHER.read_text().partition(_CHECK)
        assert _CHECK not in setup and "exec /usr/local/bin/" not in setup
        assert suffix.startswith("printf ")
        with monkeypatch.context() as controlled:
            controlled.setattr(subprocess, "Popen", _REAL_POPEN)
            return subprocess.run(
                ["/bin/sh", "-eu", "-c", setup + suffix],
                env=environment,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )

    return run_setup


def test_launcher_setup_scrubs_providers_and_fixes_profile_and_region(
    setup_shell: Callable[[str, dict[str, str]], subprocess.CompletedProcess[str]],
) -> None:
    environment = {name: "SYNTHETIC-AMBIENT-OVERRIDE" for name in _AMBIENT_PROVIDERS}
    environment.update({name: "SYNTHETIC-CONFIG-OVERRIDE" for name in _FIXED_ENVIRONMENT})
    environment["PALS_ENV"] = "prod"
    environment["PALS_PROOF_CAPABILITY"] = "natural-only"
    environment["PALS_TOKEN_ACCOUNTING_ENABLED"] = "true"
    names = sorted(_AMBIENT_PROVIDERS | set(_FIXED_ENVIRONMENT))
    suffix = "\n".join(f"printf '%s=%s\\n' {name} \"${{{name}-__unset__}}\"" for name in names)
    result = setup_shell(suffix, environment)
    assert result.returncode == 0 and result.stderr == ""
    actual = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert actual == {
        **dict.fromkeys(_AMBIENT_PROVIDERS, "__unset__"),
        **_FIXED_ENVIRONMENT,
    }


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"PALS_ENV": "local"},
        {"PALS_ENV": "dev"},
        {"PALS_ENV": " prod "},
        {"PALS_ENVIRONMENT": "local"},
        {"PALS_ENV": "local", "PALS_ENVIRONMENT": "prod"},
    ],
)
def test_launcher_refuses_missing_or_nonproduction_environment(
    environment: dict[str, str],
    setup_shell: Callable[[str, dict[str, str]], subprocess.CompletedProcess[str]],
) -> None:
    result = setup_shell("printf 'PRECHECK-MUST-NOT-RUN\\n'", environment)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "Worker AWS credential boundary requires the production environment.\n"


@pytest.mark.parametrize("environment", [{"PALS_ENV": "prod"}, {"PALS_ENVIRONMENT": "prod"}])
def test_launcher_accepts_production_environment_precedence(
    environment: dict[str, str],
    setup_shell: Callable[[str, dict[str, str]], subprocess.CompletedProcess[str]],
) -> None:
    environment = {
        **environment,
        "PALS_PROOF_CAPABILITY": "natural-only",
        "PALS_TOKEN_ACCOUNTING_ENABLED": "true",
    }
    result = setup_shell("printf 'SETUP-ACCEPTED\\n'", environment)
    assert result.returncode == 0
    assert result.stdout == "SETUP-ACCEPTED\n" and result.stderr == ""


@pytest.mark.parametrize("name", ["PALS_LOCALSTACK_ENDPOINT_URL", "PALS_AWS_ENDPOINT_URL"])
def test_launcher_refuses_application_endpoint_override_before_precheck(
    name: str,
    setup_shell: Callable[[str, dict[str, str]], subprocess.CompletedProcess[str]],
) -> None:
    result = setup_shell(
        "printf 'PRECHECK-MUST-NOT-RUN\\n'",
        {
            "PALS_ENV": "prod",
            "PALS_PROOF_CAPABILITY": "natural-only",
            "PALS_TOKEN_ACCOUNTING_ENABLED": "true",
            name: "https://invalid.test",
        },
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "Worker AWS credential boundary requires the production AWS endpoint.\n"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PALS_PROOF_CAPABILITY", None),
        ("PALS_PROOF_CAPABILITY", "full"),
        ("PALS_PROOF_CAPABILITY", " natural-only "),
        ("PALS_TOKEN_ACCOUNTING_ENABLED", None),
        ("PALS_TOKEN_ACCOUNTING_ENABLED", "false"),
        ("PALS_TOKEN_ACCOUNTING_ENABLED", "1"),
        ("PALS_TOKEN_ACCOUNTING_ENABLED", "TRUE"),
    ],
)
def test_launcher_requires_natural_capability_and_accounting(
    name: str,
    value: str | None,
    setup_shell: Callable[[str, dict[str, str]], subprocess.CompletedProcess[str]],
) -> None:
    environment = {
        "PALS_ENV": "prod",
        "PALS_PROOF_CAPABILITY": "natural-only",
        "PALS_TOKEN_ACCOUNTING_ENABLED": "true",
    }
    if value is None:
        del environment[name]
    else:
        environment[name] = value
    result = setup_shell("printf 'PRECHECK-MUST-NOT-RUN\\n'", environment)
    assert result.returncode == 2 and result.stdout == ""
    assert result.stderr == (
        "Worker production boundary requires natural-only capability and token accounting.\n"
    )
