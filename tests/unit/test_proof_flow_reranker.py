from __future__ import annotations

import json
from typing import Any

import pytest

from pals_agent.http_transport import HttpResponse
from pals_agent.models import ProofDraft
from pals_agent.openmath import canonicalize_retrieval_openmath_xml
from pals_agent.private_draft_candidates import (
    DraftCandidate,
    DraftCandidateResult,
    DraftEmbeddingFingerprint,
)
from pals_agent.proof_flow_evidence import project_draft_evidence
from pals_agent.proof_flow_reranker import (
    DraftRerankerInvalidError,
    DraftRerankerRequest,
    DraftRerankerUnavailableError,
    OpenAIDraftReranker,
    build_draft_reranker_request,
)

_XML = canonicalize_retrieval_openmath_xml(
    '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMBIND>'
    '<OMS cd="quant1" name="forall"/><OMBVAR><OMV name="x"/></OMBVAR><OMA>'
    '<OMS cd="relation1" name="eq"/><OMV name="x"/><OMV name="x"/>'
    "</OMA></OMBIND></OMOBJ>"
)
_FINGERPRINT = DraftEmbeddingFingerprint(
    provider="openai",
    model="text-embedding-3-small",
    endpoint="https://api.openai.com/v1",
    deployment="text-embedding-3-small",
    revision="2026-07-27",
    dimension=2,
)


class RecordingTransport:
    def __init__(self, *, status: int = 200, body: bytes | None = None) -> None:
        self.status = status
        self.body = body or _provider_body(["a"])
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> HttpResponse:
        self.calls.append(kwargs)
        return HttpResponse(status_code=self.status, body=self.body)


def _provider_body(ids: list[str]) -> bytes:
    return json.dumps(
        {
            "object": "response",
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "model": "gpt-6-luna",
            "usage": {
                "input_tokens": 10,
                "input_tokens_details": {"cached_tokens": 2},
                "output_tokens": 3,
                "output_tokens_details": {"reasoning_tokens": 1},
                "total_tokens": 13,
            },
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "annotations": [],
                            "text": json.dumps({"selected_draft_ids": ids}),
                        }
                    ],
                }
            ],
        },
        separators=(",", ":"),
    ).encode()


def _request() -> DraftRerankerRequest:
    candidate = DraftCandidate(
        draft=ProofDraft(
            id="a",
            matched_prompt="For all x, x equals x.",
            openmath_xml=_XML,
            proof_strategy="Use reflexivity.",
            sketch_steps=("Apply reflexivity.",),
        ),
        cosine_distance=0.0,
    )
    result = DraftCandidateResult(
        generation_id="11111111-1111-4111-8111-111111111111",
        manifest_sha256="sha256:" + "a" * 64,
        seed_count=1,
        runtime_provenance_sha256="b" * 64,
        fingerprint=_FINGERPRINT,
        candidates=(candidate,),
    )
    return build_draft_reranker_request(
        natural_statement="For all real x, x equals x.",
        query_openmath=_XML,
        evidence=project_draft_evidence(query_openmath_xml=_XML, candidates=(candidate,)),
        candidates=result,
    )


@pytest.mark.parametrize("status", [200, 201])
def test_pfi_ag_005_sends_one_pinned_strict_request_for_a_2xx_provider_response(
    status: int,
) -> None:
    request = _request()
    assert hasattr(request, "body_jcs")
    transport = RecordingTransport(status=status)

    ids = OpenAIDraftReranker(api_key="test-key", transport=transport).rerank(request)

    assert ids == ("a",)
    assert transport.calls == [
        {
            "method": "POST",
            "url": "https://api.openai.com/v1/responses",
            "headers": {
                "Authorization": "Bearer test-key",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            "body": request.body_jcs,
            "timeout_seconds": 90.0,
        }
    ]
    body = json.loads(request.body_jcs)
    assert body["model"] == "gpt-6-luna"
    assert body["reasoning"] == {"effort": "low"}
    assert body["service_tier"] == "default"
    assert body["text"]["format"]["schema"] == {
        "additionalProperties": False,
        "properties": {
            "selected_draft_ids": {
                "items": {"pattern": "^[a-z][a-z0-9_]{0,63}$", "type": "string"},
                "maxItems": 4,
                "type": "array",
            }
        },
        "required": ["selected_draft_ids"],
        "type": "object",
    }


def test_pfi_ag_005_accepts_valid_json_whitespace_in_the_provider_envelope_and_selection() -> None:
    envelope = json.loads(_provider_body(["a"]))
    output = envelope["output"]
    assert isinstance(output, list)
    message = output[0]
    assert isinstance(message, dict)
    content = message["content"]
    assert isinstance(content, list)
    text_item = content[0]
    assert isinstance(text_item, dict)
    text_item["text"] = " \n" + json.dumps({"selected_draft_ids": ["a"]}) + "\t"
    body = b" \n" + json.dumps(envelope, separators=(",", ":")).encode("utf-8")

    assert OpenAIDraftReranker(
        api_key="test-key", transport=RecordingTransport(body=body)
    ).rerank(_request()) == ("a",)


def test_pfi_ag_005_rejects_non_json_unicode_whitespace_before_a_provider_envelope() -> None:
    with pytest.raises(DraftRerankerInvalidError):
        OpenAIDraftReranker(
            api_key="test-key",
            transport=RecordingTransport(body=b"\xc2\xa0" + _provider_body(["a"])),
        ).rerank(_request())


@pytest.mark.parametrize("ids", [["unknown"], ["a", "a"]])
def test_pfi_ag_005_rejects_foreign_or_duplicate_provider_ids(ids: list[str]) -> None:
    with pytest.raises(DraftRerankerInvalidError):
        OpenAIDraftReranker(
            api_key="test-key", transport=RecordingTransport(body=_provider_body(ids))
        ).rerank(_request())


def test_pfi_ag_005_maps_non_200_to_unavailable() -> None:
    with pytest.raises(DraftRerankerUnavailableError):
        OpenAIDraftReranker(api_key="test-key", transport=RecordingTransport(status=429)).rerank(
            _request()
        )


def test_pfi_ag_007_rejects_missing_or_inconsistent_usage() -> None:
    missing_usage = json.loads(_provider_body(["a"]))
    del missing_usage["usage"]
    inconsistent_usage = json.loads(_provider_body(["a"]))
    inconsistent_usage["usage"]["total_tokens"] = 99

    for body in (missing_usage, inconsistent_usage):
        with pytest.raises(DraftRerankerInvalidError):
            OpenAIDraftReranker(
                api_key="test-key",
                transport=RecordingTransport(
                    body=json.dumps(body, separators=(",", ":")).encode()
                ),
            ).rerank(_request())


def test_provider_usage_extra_metadata_is_ignored_at_each_object_boundary() -> None:
    envelope = json.loads(_provider_body(['a']))
    usage = envelope['usage']
    usage['future_provider_metadata'] = {'private': 'not retained'}
    usage['input_tokens_details']['new_counter'] = {'not': 'a token count'}
    usage['output_tokens_details']['other_detail'] = [True, 'private']
    response = OpenAIDraftReranker(api_key='key', transport=RecordingTransport(
        body=json.dumps(envelope).encode(),
    )).rerank_response(_request())
    assert response.selected_draft_ids == ('a',)
    assert response.usage.input_tokens == 10
    assert response.usage.cached_input_tokens == 2
    assert response.usage.uncached_input_tokens == 8
    assert response.usage.output_tokens == 3
    assert response.usage.reasoning_output_tokens == 1
    assert response.usage.nonreasoning_output_tokens == 2
    assert response.usage.total_tokens == 13
    assert 'private' not in repr(response)


@pytest.mark.parametrize('path', [
    ('input_tokens',), ('output_tokens',), ('total_tokens',),
    ('input_tokens_details',), ('output_tokens_details',),
    ('input_tokens_details', 'cached_tokens'), ('output_tokens_details', 'reasoning_tokens'),
])
def test_provider_usage_still_requires_every_known_count(path) -> None:
    envelope = json.loads(_provider_body(['a']))
    target = envelope['usage']
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    with pytest.raises(DraftRerankerInvalidError) as caught:
        OpenAIDraftReranker(api_key='key', transport=RecordingTransport(
            body=json.dumps(envelope).encode(),
        )).rerank(_request())
    assert caught.value.private_evidence['parse_stage'] == 'usage'


@pytest.mark.parametrize('path,value', [
    (('input_tokens',), True), (('output_tokens',), -1),
    (('total_tokens',), 13.0), (('input_tokens_details', 'cached_tokens'), '2'),
    (('output_tokens_details', 'reasoning_tokens'), None),
    (('input_tokens',), 2**63), (('input_tokens_details', 'cached_tokens'), 11),
    (('output_tokens_details', 'reasoning_tokens'), 4), (('total_tokens',), 99),
])
def test_provider_usage_rejects_invalid_types_ranges_and_inconsistent_counts(path, value) -> None:
    envelope = json.loads(_provider_body(['a']))
    target = envelope['usage']
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(DraftRerankerInvalidError):
        OpenAIDraftReranker(api_key='key', transport=RecordingTransport(
            body=json.dumps(envelope).encode(),
        )).rerank(_request())


@pytest.mark.parametrize('before,after', [
    ('"input_tokens":10', '"input_tokens":10,"input_tokens":10'),
    ('"cached_tokens":2', '"cached_tokens":2,"cached_tokens":2'),
    ('"reasoning_tokens":1', '"reasoning_tokens":1,"reasoning_tokens":1'),
    ('"input_tokens":10', '"input_tokens":10,"new":1,"new":2'),
])
def test_provider_usage_rejects_duplicate_members_even_for_unknown_metadata(before, after) -> None:
    body = _provider_body(['a']).replace(before.encode(), after.encode())
    with pytest.raises(DraftRerankerInvalidError):
        OpenAIDraftReranker(
            api_key='key', transport=RecordingTransport(body=body)
        ).rerank(_request())
