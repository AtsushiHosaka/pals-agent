"""Authenticated API Recipe search transport and immutable byte boundaries."""

import hashlib
import json

import pytest

from pals_agent.api_client import PalsApiClient, PalsApiError
from pals_agent.http_transport import HttpResponse
from tests.unit.test_proof_reuse_lean_flow import CLAIM_ID, INTENT, RECIPE, REQUEST_ID


class Transport:
    def __init__(self, payload):
        self.payload, self.calls = payload, []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return HttpResponse(200, json.dumps(self.payload, ensure_ascii=False).encode())


def search(payload, **overrides):
    transport = Transport(payload)
    client = PalsApiClient("http://localhost:8000", "test-secret", transport=transport)
    result = client.search_proof_request_recipes(
        request_id=REQUEST_ID,
        claim_id=CLAIM_ID,
        **dict({"query": INTENT["query"], "output_language": "ja", "limit": 8}, **overrides),
    )
    return result, transport.calls


def test_search_calls_claim_bound_recipe_endpoint_without_draft_identifiers():
    result, calls = search({"recipes": [RECIPE]})
    assert result == [RECIPE]
    assert calls[0]["url"].endswith(f"/{REQUEST_ID}/recipe-search")
    assert calls[0]["headers"]["X-PALS-Worker-Secret"] == "test-secret"
    assert json.loads(calls[0]["body"]) == {
        "claim_id": CLAIM_ID,
        "query": INTENT["query"],
        "output_language": "ja",
        "limit": 8,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"recipes": [dict(RECIPE, answer="changed")]},
        {"recipes": [dict(RECIPE, lean_code="changed")]},
        {"recipes": [RECIPE, RECIPE]},
        {"recipes": [dict(RECIPE, recipe_revision=True)]},
        {"recipes": [], "unexpected": True},
        {"recipes": [dict(RECIPE, assumptions=[{}])]},
        {"recipes": [dict(RECIPE, toolchain_sha256="bad")]},
        {"recipes": "bad"},
    ],
)
def test_malformed_or_corrupt_search_response_is_never_a_cache_miss(payload):
    with pytest.raises(PalsApiError):
        search(payload)


@pytest.mark.parametrize(
    "changes",
    [{"limit": True}, {"limit": 9}, {"query": "私" * 3000}, {"output_language": "unsupported"}],
)
def test_query_bounds_are_checked_before_transport(changes):
    with pytest.raises(ValueError):
        search({"recipes": []}, **changes)


def test_valid_empty_or_other_language_response_is_a_miss():
    assert search({"recipes": []})[0] == []
    assert search({"recipes": [dict(RECIPE, output_language="en")]})[0] == []


def test_search_accepts_valid_envelope_above_legacy_one_mebibyte_limit():
    source = "-- " + "x" * 159_000
    candidates = [dict(
        RECIPE, recipe_id=f"large-{index}", lean_code=source,
        lean_sha256=hashlib.sha256(source.encode()).hexdigest(),
    ) for index in range(8)]
    assert len(json.dumps({"recipes": candidates}).encode()) > 1_048_576
    assert len(search({"recipes": candidates})[0]) == 8
    assert PalsApiClient("http://localhost", "secret").transport.max_response_bytes == 2_097_152


def test_search_rejects_envelope_over_two_mebibytes_even_with_custom_transport():
    source, answer = "x" * 199_000, "字" * 59_000
    candidates = [dict(
        RECIPE, recipe_id=f"oversized-{index}", lean_code=source, answer=answer,
        lean_sha256=hashlib.sha256(source.encode()).hexdigest(),
        answer_sha256=hashlib.sha256(answer.encode()).hexdigest(),
    ) for index in range(8)]
    with pytest.raises(PalsApiError, match="byte limit"):
        search({"recipes": candidates})


def test_target_utf8_limit_matches_existing_recipe_admission_contract():
    target = "界" * 21_845 + "x"
    assert len(target.encode()) == 65_536
    result, _ = search({"recipes": [dict(RECIPE, target_source=target)]})
    assert result[0]["target_source"] == target
    with pytest.raises(PalsApiError):
        search({"recipes": [dict(RECIPE, target_source=target + "x")]})
