import json
from unittest.mock import Mock

import pytest

from pals_agent.draft_embeddings import EmbeddingError
from pals_agent.openai import OpenAIError
from pals_agent.typed_runtime_failures import TypedRetrievalFailure
from tests.unit.test_typed_runtime_diagnostics import PROFILE, runtime

INVALID = '<OMOBJ xmlns="http://www.openmath.org/OpenMath"><OMI>1</OMOBJ>'


def test_valid_initial_structure_calls_model_once_without_repair():
    r = runtime()
    result = r.retrieve_for_profile(PROFILE, "Original theorem")
    r.client.generate.assert_called_once()
    assert 0 < r.client.generate.call_args.kwargs["timeout_seconds"] <= 90
    assert result.private_diagnostics["structuring_repair_used"] is False


def test_invalid_then_valid_preserves_original_request_and_private_first_failure():
    r = runtime()
    valid = r.client.generate.return_value
    r.client.generate.side_effect = [INVALID, valid]
    result = r.retrieve_for_profile(PROFILE, "Original theorem")
    calls = r.client.generate.call_args_list
    assert len(calls) == 2 and calls[1].kwargs["prompt"].startswith(calls[0].kwargs["prompt"])
    assert "untrusted diagnostic data" in calls[1].kwargs["prompt"]
    assert calls[1].kwargs["model"] == calls[0].kwargs["model"]
    assert calls[1].kwargs["timeout_seconds"] <= calls[0].kwargs["timeout_seconds"]
    assert result.private_diagnostics["first_failure"]["bounded_private_json"]["prefix"] == INVALID
    assert result.private_diagnostics["structuring_repair_used"] is True
    assert result.private_diagnostics["structuring_attempts"] == 2
    assert result.as_json()["private_diagnostics"] == result.private_diagnostics
    r.embeddings.embed.assert_called_once()
    r.candidates.find_candidates.assert_called_once()
    r.reranker.rerank.assert_called_once()


def test_two_invalid_results_stop_and_preserve_both_failures():
    r = runtime()
    r.client.generate.side_effect = [INVALID, "<invalid/>"]
    with pytest.raises(TypedRetrievalFailure) as caught:
        r.retrieve_for_profile(PROFILE, "Original theorem")
    assert caught.value.code == "typed_structuring_invalid"
    assert caught.value.private_evidence["bounded_private_json"]["prefix"] == "<invalid/>"
    assert (
        caught.value.private_evidence["first_failure"]["bounded_private_json"]["prefix"] == INVALID
    )
    assert caught.value.private_evidence["structuring_attempts"] == 2
    assert r.client.generate.call_count == 2
    r.embeddings.embed.assert_not_called()


def test_provider_unavailable_is_not_retried():
    r = runtime()
    r.client.generate.side_effect = OpenAIError("private provider message")
    with pytest.raises(TypedRetrievalFailure) as caught:
        r.retrieve_for_profile(PROFILE, "Original theorem")
    assert caught.value.code == "typed_structuring_unavailable"
    assert r.client.generate.call_count == 1
    assert "private provider" not in json.dumps(caught.value.private_evidence)


@pytest.mark.parametrize("ticks,expected_calls", [([0, 90], 0), ([0, 0, 90], 1)])
def test_exhausted_deadline_prevents_additional_model_call(monkeypatch, ticks, expected_calls):
    r = runtime()
    r.client.generate.return_value = INVALID
    monkeypatch.setattr("pals_agent.typed_runtime.monotonic", Mock(side_effect=ticks))
    with pytest.raises(TypedRetrievalFailure) as caught:
        r.retrieve_for_profile(PROFILE, "Original theorem")
    assert caught.value.code == "typed_structuring_unavailable"
    assert r.client.generate.call_count == expected_calls
    if expected_calls:
        assert caught.value.private_evidence["first_attempt_invalid"] is True
        assert caught.value.private_evidence["structuring_repair_used"] is False
    r.embeddings.embed.assert_not_called()


def test_repair_receives_only_remaining_total_deadline(monkeypatch):
    r = runtime()
    r.client.generate.side_effect = [INVALID, r.client.generate.return_value]
    monkeypatch.setattr("pals_agent.typed_runtime.monotonic", Mock(side_effect=[0, 1, 61, 62]))
    r.retrieve_for_profile(PROFILE, "Original theorem")
    assert [c.kwargs["timeout_seconds"] for c in r.client.generate.call_args_list] == [89, 29]


def test_downstream_failure_is_not_retried_and_preserves_repair_history():
    r = runtime()
    r.client.generate.side_effect = [INVALID, r.client.generate.return_value]
    r.embeddings.embed.side_effect = EmbeddingError("secret")
    with pytest.raises(TypedRetrievalFailure) as caught:
        r.retrieve_for_profile(PROFILE, "Original theorem")
    assert caught.value.code == "typed_embedding_unavailable"
    assert caught.value.private_evidence["structuring_attempts"] == 2
    assert (
        caught.value.private_evidence["first_failure"]["bounded_private_json"]["prefix"] == INVALID
    )
    assert r.embeddings.embed.call_count == 1
    r.candidates.find_candidates.assert_not_called()


def test_success_after_deadline_is_not_accepted(monkeypatch):
    r = runtime()
    monkeypatch.setattr("pals_agent.typed_runtime.monotonic", Mock(side_effect=[0, 0, 91]))
    with pytest.raises(TypedRetrievalFailure, match="typed_structuring_unavailable"):
        r.retrieve_for_profile(PROFILE, "Original theorem")
    assert r.client.generate.call_count == 1
    r.embeddings.embed.assert_not_called()


def test_repair_unavailable_does_not_retry_and_keeps_first_failure():
    r = runtime()
    r.client.generate.side_effect = [INVALID, OpenAIError("private transport data")]
    with pytest.raises(TypedRetrievalFailure) as caught:
        r.retrieve_for_profile(PROFILE, "Original theorem")
    assert r.client.generate.call_count == 2
    assert caught.value.code == "typed_structuring_unavailable"
    assert (
        caught.value.private_evidence["first_failure"]["bounded_private_json"]["prefix"] == INVALID
    )
    assert caught.value.private_evidence["structuring_repair_used"] is True
    assert "private transport data" not in json.dumps(caught.value.private_evidence)


def test_repaired_success_history_is_private_and_prior_xml_is_bounded():
    from pals_agent.worker import _status_retrieval

    r = runtime()
    huge = "<broken>" + "界" * 5000
    r.client.generate.side_effect = [huge, r.client.generate.return_value]
    result = r.retrieve_for_profile(PROFILE, "Original theorem")
    evidence = result.private_diagnostics["first_failure"]
    assert len(evidence["bounded_private_json"]["prefix"].encode()) <= 4096
    assert evidence["bounded_private_json"]["truncated"] is True
    assert huge not in r.client.generate.call_args.kwargs["prompt"]
    assert "first_failure" not in str(_status_retrieval({"proof_flow_result": result.as_json()}))
