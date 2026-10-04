"""Verify the actual SDK chooses the fixed process without reading credentials."""

import os
from pathlib import Path
from typing import Any

import botocore.session
import pytest


def test_real_sdk_profile_selects_worker_process_before_other_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(os, "environ", {"AWS_EC2_METADATA_DISABLED": "true"})
    session = botocore.session.Session(profile="pals-worker-runtime")
    session.set_config_variable("config_file", str(root / "scripts/aws-worker-profile.conf"))
    session.set_config_variable("credentials_file", "/dev/null")
    observed: list[list[str]] = []

    class ProcessBoundaryReached(RuntimeError):
        pass

    def stop_before_process(arguments: list[str], **_kwargs: Any) -> Any:
        observed.append(arguments)
        raise ProcessBoundaryReached

    provider = next(
        item
        for item in session.get_component("credential_provider").providers
        if item.METHOD == "custom-process"
    )
    monkeypatch.setattr(provider, "_popen", stop_before_process)
    with pytest.raises(ProcessBoundaryReached):
        session.get_credentials()

    assert observed == [
        [
            "/usr/local/bin/python",
            "-I",
            "-m",
            "pals_agent.aws_worker_credentials",
            "/run/credentials/worker",
        ]
    ]
    assert session.get_config_variable("region") == "ap-northeast-1"
