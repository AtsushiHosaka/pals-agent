import json

import pytest

from pals_agent.proof_flow_reranker import DraftRerankerInvalidError, OpenAIDraftReranker
from pals_agent.reranker_diagnostics import response_diagnostics, sanitize_reranker_diagnostics
from pals_agent.typed_runtime_failures import TypedRetrievalFailure
from tests.unit.test_proof_flow_reranker import RecordingTransport, _provider_body, _request
from tests.unit.test_typed_runtime_diagnostics import PROFILE, runtime


@pytest.mark.parametrize(
    "change,stage",
    [
        ({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}, "status"),
        ({"model": "private model string"}, "model"),
        ({"usage": None}, "usage"),
        (
            {
                "output": [
                    {"type": "reasoning", "summary": [{"text": "secret reasoning"}]},
                    {"type": "message"},
                ]
            },
            "output",
        ),
        ({"output": [{"type": "reasoning", "content": "secret"}]}, "message"),
        (
            {
                "output": [
                    {"type": "message", "role": "assistant", "status": "completed", "content": []}
                ]
            },
            "content",
        ),
    ],
)
def test_failure_metadata_identifies_closed_stage_without_accepting_invalid_responses(
    change, stage
):
    envelope = json.loads(_provider_body(["a"]))
    envelope.update(change)
    envelope["secret"] = "secret credential"
    transport = RecordingTransport(body=json.dumps(envelope).encode())
    with pytest.raises(DraftRerankerInvalidError) as caught:
        OpenAIDraftReranker(api_key="secret credential", transport=transport).rerank(_request())
    evidence = caught.value.private_evidence
    assert evidence["parse_stage"] == stage
    assert "secret" not in json.dumps(evidence) and "private model" not in json.dumps(evidence)
    assert len(transport.calls) == 1
    assert json.loads(transport.calls[0]["body"])["max_output_tokens"] == 512
    if stage == "status":
        assert evidence["response_status"] == "incomplete"
        assert evidence["incomplete_reason"] == "max_output_tokens"
    if stage == "output":
        assert evidence["output_item_types"] == ["reasoning", "message"]
        assert evidence["output_item_count"] == 2
        assert evidence["reasoning_output_tokens"] == 1


@pytest.mark.parametrize(
    "body,stage", [(b"not json secret", "json"), (_provider_body(["foreign"]), "selection_ids")]
)
def test_invalid_json_and_foreign_ids_remain_rejected_with_safe_stages(body, stage):
    with pytest.raises(DraftRerankerInvalidError) as caught:
        OpenAIDraftReranker(api_key="key", transport=RecordingTransport(body=body)).rerank(
            _request()
        )
    assert caught.value.private_evidence["parse_stage"] == stage
    assert "secret" not in json.dumps(caught.value.private_evidence)


def test_unknown_metadata_is_closed_bounded_and_rechecked_at_typed_serialization():
    dirty = {
        "parse_stage": "secret",
        "response_status": "private text",
        "incomplete_reason": {"secret": 1},
        "output_item_types": ["secret"] * 100,
        "output_item_count": 100,
        "input_tokens": True,
        "output_tokens": -1,
        "total_tokens": 10**50,
        "text": "secret",
    }
    safe = sanitize_reranker_diagnostics(dirty)
    assert safe == {
        "response_status": "unknown",
        "incomplete_reason": "unknown",
        "output_item_count": 100,
        "output_item_types": ["unknown"] * 16,
    }
    assert TypedRetrievalFailure(
        "typed_reranking_invalid", reranker_diagnostics=dirty
    ).private_evidence == {"code": "typed_reranking_invalid", "reranker": safe}
    assert response_diagnostics(b"null", "json") == {"parse_stage": "json"}


def test_actual_parser_metadata_survives_typed_runtime_without_provider_prose():
    envelope = json.loads(_provider_body(["a"]))
    envelope.update(
        status="incomplete", incomplete_details={"reason": "max_output_tokens", "text": "secret"}
    )
    r = runtime()
    r.reranker.rerank.side_effect = lambda request: OpenAIDraftReranker(
        api_key="key", transport=RecordingTransport(body=json.dumps(envelope).encode())
    ).rerank(request)
    with pytest.raises(TypedRetrievalFailure) as caught:
        r.retrieve_for_profile(PROFILE, "Matrix statement")
    assert caught.value.private_evidence["reranker"]["parse_stage"] == "status"
    assert caught.value.private_evidence["reranker"]["incomplete_reason"] == "max_output_tokens"
    assert "secret" not in json.dumps(caught.value.private_evidence)
