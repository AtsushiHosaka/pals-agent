"""Worker opt-in chooses token processing; genuine API claims/permits remain authority."""

import pytest

from pals_agent.factory import build_proof_request_processor
from pals_agent.settings import AgentSettings


@pytest.mark.parametrize("environment", [None, "local", "prod", "dev", "other"])
@pytest.mark.parametrize("flag", [None, "false", "true", "TRUE"])
def test_token_worker_mode_requires_existing_explicit_flag_and_supported_environment(
    monkeypatch,
    environment,
    flag,
):
    if environment is None:
        monkeypatch.delenv("PALS_ENV", raising=False)
    else:
        monkeypatch.setenv("PALS_ENV", environment)
    if flag is None:
        monkeypatch.delenv("PALS_TOKEN_ACCOUNTING_ENABLED", raising=False)
    else:
        monkeypatch.setenv("PALS_TOKEN_ACCOUNTING_ENABLED", flag)
    monkeypatch.setenv("PALS_OPENAI_API_KEY", "test-no-network-key")
    settings = AgentSettings.from_env()
    # Construction makes no provider request; API reference is never called by this contract.
    api = object()
    processor = build_proof_request_processor(settings, api)
    assert processor.api is api
    assert processor.token_accounting_enabled is (
        environment in {"local", "prod"} and flag == "true"
    )
