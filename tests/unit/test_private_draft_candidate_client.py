from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from pals_agent.http_transport import HttpResponse, HttpTransportError
from pals_agent.private_draft_candidates import (
    DraftCandidateCompatibilityError,
    DraftCandidateLimitError,
    DraftCandidateUnavailableError,
    DraftEmbeddingFingerprint,
    PrivateDraftCandidateClient,
)

_FINGERPRINT = DraftEmbeddingFingerprint(
    provider="openai",
    model="text-embedding-3-small",
    endpoint="https://api.openai.com/v1",
    deployment="text-embedding-3-small",
    revision="2026-07-27",
    dimension=2,
)

_RESULT = {
    "schema_version": "pals.draft-candidate-result.v1",
    "generation_id": "11111111-1111-4111-8111-111111111111",
    "manifest_sha256": "sha256:" + "a" * 64,
    "seed_count": 1,
    "runtime_provenance_sha256": "b" * 64,
    "fingerprint": {
        **_FINGERPRINT.as_json(),
        "canonicalizer_version": "openmath-cdbase-alpha-c14n-v4",
    },
    "candidates": [
        {
            "draft": {
                "id": "continuous_square",
                "canonical_statement": "The square function is continuous.",
                "openmath_xml": (
                    '<n1:OMOBJ xmlns:n1="http://www.openmath.org/OpenMath" '
                    'version="2.0"><n1:OMA><n1:OMS cd="relation1" name="eq"></n1:OMS>'
                    "<n1:OMI>1</n1:OMI><n1:OMI>1</n1:OMI></n1:OMA></n1:OMOBJ>"
                ),
                "proof_strategy": "Use the epsilon-delta definition.",
                "sketch_steps": ["Choose a bound around the point."],
            },
            "cosine_distance": 0.0,
        }
    ],
}


class RecordingTransport:
    def __init__(
        self,
        *,
        status_code: int = 200,
        body: bytes | None = None,
        headers: tuple[tuple[str, str], ...] = (("Content-Type", "application/json"),),
        error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.body = (
            json.dumps(_RESULT, separators=(",", ":")).encode("utf-8") if body is None else body
        )
        self.headers = headers
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> HttpResponse:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return HttpResponse(
            status_code=self.status_code,
            body=self.body,
            headers=self.headers,
        )


class TransportThatMustNotRun:
    def request(self, **kwargs: Any) -> HttpResponse:
        del kwargs
        pytest.fail("private candidate transport must not run")


def _reverse_candidate_order(value: dict[str, Any]) -> None:
    later = json.loads(json.dumps(value["candidates"][0]))
    later["draft"]["id"] = "z_later"
    value["candidates"] = [later, value["candidates"][0]]


def _client(transport: RecordingTransport | TransportThatMustNotRun) -> PrivateDraftCandidateClient:
    return PrivateDraftCandidateClient(
        base_url="https://api.pals.example",
        worker_secret="worker-secret",
        transport=transport,
    )


@pytest.mark.parametrize(
    "base_url",
    (
        "https://api.pals.example ",
        "https://api.pals.example\n",
        "https://api.pals.example:bad",
        "https://api.pals.example:65536",
    ),
)
def test_pfi_ag_003_rejects_a_noncanonical_private_api_origin(base_url: str) -> None:
    with pytest.raises(ValueError, match="absolute origin"):
        PrivateDraftCandidateClient(
            base_url=base_url,
            worker_secret="worker-secret",
            transport=TransportThatMustNotRun(),
        )


def test_pfi_ag_003_sends_one_exact_private_vector_only_request() -> None:
    transport = RecordingTransport()

    result = _client(transport).find_candidates(
        embedding=[1.0, 0.0],
        fingerprint=_FINGERPRINT,
    )

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.pals.example/v1/internal/proof-flow-index/candidates"
    assert call["headers"] == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-PALS-Worker-Secret": "worker-secret",
    }
    assert call["timeout_seconds"] == 10.0
    assert call["body"] is not None
    request = json.loads(call["body"].decode("utf-8"))
    assert request == {
        "schema_version": "pals.draft-candidate-query.v1",
        "embedding": [1.0, 0.0],
        "fingerprint": {
            **_FINGERPRINT.as_json(),
            "canonicalizer_version": "openmath-cdbase-alpha-c14n-v4",
        },
    }
    assert set(request) == {"schema_version", "embedding", "fingerprint"}
    assert result.candidates[0].draft.id == "continuous_square"
    assert result.candidates[0].cosine_distance == 0.0


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        pytest.param(
            json.dumps(_RESULT, separators=(",", ":")).encode("utf-8"),
            (("Content-Type", "application/problem+json"),),
            id="wrong-media-type",
        ),
        pytest.param(
            b"{" + b"x" * 262_145 + b"}",
            (("Content-Type", "application/json"),),
            id="oversized-success-body",
        ),
    ],
)
def test_pfi_ag_003_maps_a_nonconforming_success_response_to_compatibility(
    body: bytes,
    headers: tuple[tuple[str, str], ...],
) -> None:
    transport = RecordingTransport(body=body, headers=headers)

    with pytest.raises(DraftCandidateCompatibilityError):
        _client(transport).find_candidates(embedding=[1.0, 0.0], fingerprint=_FINGERPRINT)

    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    ("embedding", "fingerprint"),
    [
        ([0.0, 0.0], _FINGERPRINT),
        ([1.0], _FINGERPRINT),
        (
            [1.0, 0.0],
            DraftEmbeddingFingerprint(
                provider="openai",
                model="text-embedding-3-small",
                endpoint="https://api.openai.com/v1",
                deployment="text-embedding-3-small",
                revision="2026-07-27",
                dimension=2,
                canonicalizer_version="openmath-cdbase-alpha-c14n-v3",
            ),
        ),
    ],
)
def test_pfi_ag_003_rejects_invalid_input_before_private_request(
    embedding: list[float],
    fingerprint: DraftEmbeddingFingerprint,
) -> None:
    with pytest.raises(DraftCandidateCompatibilityError):
        _client(TransportThatMustNotRun()).find_candidates(
            embedding=embedding,
            fingerprint=fingerprint,
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"unexpected": True}),
        lambda value: value.__setitem__(
            "fingerprint", {**value["fingerprint"], "revision": "wrong"}
        ),
        lambda value: value["candidates"][0]["draft"].__setitem__(
            "openmath_xml",
            '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0">'
            '<OMA><OMS cd="relation1" name="eq"/><OMI>1</OMI><OMI>1</OMI></OMA>'
            "</OMOBJ>",
        ),
        lambda value: value.__setitem__("candidates", value["candidates"] * 2),
        _reverse_candidate_order,
    ],
)
def test_pfi_ag_004_rejects_nonconforming_candidate_response(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    value = json.loads(json.dumps(_RESULT))
    mutate(value)
    transport = RecordingTransport(body=json.dumps(value, separators=(",", ":")).encode("utf-8"))

    with pytest.raises(DraftCandidateCompatibilityError):
        _client(transport).find_candidates(embedding=[1.0, 0.0], fingerprint=_FINGERPRINT)

    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.__setitem__("candidates", value["candidates"] * 9),
        lambda value: value.__setitem__("candidates", value["candidates"] * 2),
    ],
)
def test_pfi_ag_004_classifies_candidate_limit_or_duplicate_ids_before_exposing_rows(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    value = json.loads(json.dumps(_RESULT))
    mutate(value)

    with pytest.raises(DraftCandidateLimitError):
        _client(
            RecordingTransport(body=json.dumps(value, separators=(",", ":")).encode("utf-8"))
        ).find_candidates(embedding=[1.0, 0.0], fingerprint=_FINGERPRINT)


def test_pfi_ag_004_does_not_classify_an_invalid_candidate_shape_as_a_limit_error() -> None:
    value = json.loads(json.dumps(_RESULT))
    value["candidates"] = {}

    with pytest.raises(DraftCandidateCompatibilityError) as error:
        _client(
            RecordingTransport(body=json.dumps(value, separators=(",", ":")).encode("utf-8"))
        ).find_candidates(embedding=[1.0, 0.0], fingerprint=_FINGERPRINT)

    assert type(error.value) is DraftCandidateCompatibilityError


def test_pfi_ag_004_rejects_candidates_that_exceed_the_active_seed_count() -> None:
    value = json.loads(json.dumps(_RESULT))
    value["seed_count"] = 0

    with pytest.raises(DraftCandidateCompatibilityError):
        _client(
            RecordingTransport(body=json.dumps(value, separators=(",", ":")).encode("utf-8"))
        ).find_candidates(embedding=[1.0, 0.0], fingerprint=_FINGERPRINT)


def test_pfi_ag_004_rejects_a_partial_result_for_the_active_seed_count() -> None:
    value = json.loads(json.dumps(_RESULT))
    value["seed_count"] = 2

    with pytest.raises(DraftCandidateCompatibilityError):
        _client(
            RecordingTransport(body=json.dumps(value, separators=(",", ":")).encode("utf-8"))
        ).find_candidates(embedding=[1.0, 0.0], fingerprint=_FINGERPRINT)


@pytest.mark.parametrize(
    ("status_code", "body", "expected"),
    [
        (
            409,
            b'{"error":{"code":"draft_catalog_incompatible"}}',
            DraftCandidateCompatibilityError,
        ),
        (
            503,
            b'{"error":{"code":"draft_retrieval_unavailable"}}',
            DraftCandidateUnavailableError,
        ),
        (500, b"{}", DraftCandidateCompatibilityError),
    ],
)
def test_pfi_ag_003_maps_only_closed_api_failures(
    status_code: int,
    body: bytes,
    expected: type[Exception],
) -> None:
    with pytest.raises(expected):
        _client(RecordingTransport(status_code=status_code, body=body)).find_candidates(
            embedding=[1.0, 0.0],
            fingerprint=_FINGERPRINT,
        )


@pytest.mark.parametrize(
    ("transport", "expected"),
    [
        (
            RecordingTransport(headers=(("Content-Type", "application/json; charset=utf-8"),)),
            DraftCandidateCompatibilityError,
        ),
        (RecordingTransport(headers=()), DraftCandidateCompatibilityError),
        (RecordingTransport(error=HttpTransportError("network")), DraftCandidateUnavailableError),
    ],
)
def test_pfi_ag_003_fails_closed_on_media_or_transport_with_the_first_applicable_token(
    transport: RecordingTransport,
    expected: type[Exception],
) -> None:
    with pytest.raises(expected):
        _client(transport).find_candidates(embedding=[1.0, 0.0], fingerprint=_FINGERPRINT)
