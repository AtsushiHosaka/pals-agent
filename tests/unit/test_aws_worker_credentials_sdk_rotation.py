"""Preserve real local SDK refresh checks; no AWS authorization is claimed."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import botocore.session
import pytest
from botocore.exceptions import CredentialRetrievalError

from pals_agent import aws_worker_credentials as adapter
from pals_agent.aws_worker_credentials import main, read_credentials

_ROLE = "arn:aws:iam::111111111111:role/synthetic/worker"


@pytest.fixture
def policy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path.resolve() / "policy"
    directory.mkdir(mode=0o700)
    path = directory / "worker-role.json"
    path.write_text(
        json.dumps({"version": 1, "role_arn": _ROLE, "session_name": "pals-mini-worker"})
    )
    path.chmod(0o600)
    monkeypatch.setattr(adapter, "_DEFAULT_POLICY_PATH", path)
    return path


def process_command(directory: Path, policy_path: Path) -> list[str]:
    # A separate process cannot inherit the parent's monkeypatch. Set the
    # synthetic mount path before forwarding the unchanged adapter arguments.
    bootstrap = (
        "import sys; from pathlib import Path; "
        "from pals_agent import aws_worker_credentials as adapter; "
        "adapter._DEFAULT_POLICY_PATH = Path(sys.argv.pop(1)); "
        "raise SystemExit(adapter.main())"
    )
    return [sys.executable, "-c", bootstrap, str(policy_path), str(directory)]


def record(*, key: str = "ASIA" + "A" * 16, minutes: int = 55) -> dict[str, object]:
    return {
        "Version": 1,
        "AccessKeyId": key,
        "SecretAccessKey": "synthetic-local-process-test-value-only",
        "SessionToken": "synthetic-local-session-token-only",
        "Expiration": (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat(
            timespec="seconds"
        ),
    }


def write_record(directory: Path, value: dict[str, object]) -> None:
    directory.mkdir(mode=0o700, exist_ok=True)
    credentials = directory / "credentials.json"
    temporary = directory / "credentials.new"
    temporary.write_text(json.dumps(value))
    temporary.chmod(0o600)
    temporary.replace(credentials)
    marker = directory / "state.json"
    temporary = directory / "state.new"
    temporary.write_text(
        json.dumps(
            {
                "version": 1,
                "ready": True,
                "role_arn": _ROLE,
                "session_name": "pals-mini-worker",
                "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "expires_at": value["Expiration"],
                "reason": None,
            }
        )
    )
    temporary.chmod(0o600)
    temporary.replace(marker)


def test_botocore_process_refresh_observes_atomic_file_replacement(
    tmp_path, monkeypatch, policy_path: Path
):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-shared-credentials"))
    directory = tmp_path.resolve() / "worker"
    write_record(directory, record(minutes=5))
    config = tmp_path / "config"
    command = shlex.join(process_command(directory, policy_path))
    config.write_text("[profile pals-worker]\ncredential_process = " + command + "\n")
    session = botocore.session.Session(profile="pals-worker")
    session.set_config_variable("config_file", str(config))
    credentials = session.get_credentials()
    assert credentials is not None and credentials.method == "custom-process"
    assert credentials.get_frozen_credentials().access_key == "ASIA" + "A" * 16
    write_record(directory, record(key="ASIA" + "B" * 16, minutes=5))
    assert credentials.get_frozen_credentials().access_key == "ASIA" + "B" * 16
    write_record(directory, record(minutes=-1))
    with pytest.raises(CredentialRetrievalError):
        credentials.get_frozen_credentials()
    (directory / "credentials.json").unlink()
    with pytest.raises(CredentialRetrievalError):
        credentials.get_frozen_credentials()


@pytest.mark.parametrize(
    "change",
    [
        {"Expiration": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
        {"Expiration": (datetime.now(UTC) + timedelta(hours=2)).isoformat()},
        {"Version": True},
        {"SessionToken": ""},
        {"extra": "forbidden"},
    ],
)
def test_invalid_or_expired_records_fail_closed_without_output(
    tmp_path, capsys, change, policy_path: Path
):
    directory = tmp_path.resolve() / "worker"
    write_record(directory, {**record(), **change})
    assert main([str(directory)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Worker AWS session is unavailable.\n"


def test_missing_symlink_and_writable_records_are_rejected(tmp_path, policy_path: Path):
    directory = tmp_path.resolve() / "worker"
    with pytest.raises(FileNotFoundError):
        read_credentials(directory)
    write_record(directory, record())
    credentials = directory / "credentials.json"
    credentials.chmod(0o666)
    with pytest.raises(ValueError):
        read_credentials(directory)
    credentials.chmod(0o600)
    link = directory.with_name("linked-worker")
    link.symlink_to(directory)
    with pytest.raises(ValueError):
        read_credentials(link)


def test_real_process_missing_file_has_empty_stdout_and_closed_error(tmp_path, policy_path: Path):
    result = subprocess.run(
        process_command(tmp_path.resolve() / "absent", policy_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1 and result.stdout == ""
    assert result.stderr == "Worker AWS session is unavailable.\n"
