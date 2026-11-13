"""PALS_T2_FIRST_EFFORT and PALS_EXPLAIN_EFFORT: unset changes nothing; set changes one effort."""

from __future__ import annotations

import pytest

from pals_agent import factory, t2_lane
from pals_agent.openai import OpenAIResponsesClient


def test_first_effort_unset_is_the_existing_fast_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(t2_lane.FIRST_EFFORT_ENV, raising=False)
    assert t2_lane.first_effort() == t2_lane.HETERO_EFFORTS[0] == "low"


def test_first_effort_is_used_by_the_cheap_first_attempt_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(t2_lane.CHEAP_FIRST_ENV, "true")
    monkeypatch.setenv(t2_lane.FIRST_EFFORT_ENV, "none")
    with t2_lane.candidate_variant(0):
        assert t2_lane.variant_effort() == "none"
    monkeypatch.delenv(t2_lane.FIRST_EFFORT_ENV)
    with t2_lane.candidate_variant(0):
        assert t2_lane.variant_effort() == "low"
    monkeypatch.setenv(t2_lane.CHEAP_FIRST_ENV, "false")
    monkeypatch.setenv(t2_lane.FIRST_EFFORT_ENV, "none")
    with t2_lane.candidate_variant(0):
        assert t2_lane.variant_effort() is None  # the switch alone changes nothing


def test_a_malformed_first_effort_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(t2_lane.FIRST_EFFORT_ENV, "high")
    with pytest.raises(ValueError):
        t2_lane.validate_flags()


def _client() -> OpenAIResponsesClient:
    return OpenAIResponsesClient(api_key="k")


def test_explain_effort_unset_keeps_the_release_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "_release_openai_client", lambda settings: _client())
    monkeypatch.delenv("PALS_EXPLAIN_EFFORT", raising=False)
    assert factory.build_proof_explainer(None).client.reasoning_effort is None  # type: ignore[arg-type]


def test_explain_effort_none_and_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "_release_openai_client", lambda settings: _client())
    monkeypatch.setenv("PALS_EXPLAIN_EFFORT", "none")
    assert factory.build_proof_explainer(None).client.reasoning_effort == "none"  # type: ignore[arg-type]
    monkeypatch.setenv("PALS_EXPLAIN_EFFORT", "high")
    with pytest.raises(ValueError):
        factory.build_proof_explainer(None)  # type: ignore[arg-type]
