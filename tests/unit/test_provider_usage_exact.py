"""Validate the provider boundary; these fixtures do not prove real-provider acceptance."""

from copy import deepcopy

import pytest

from pals_agent.provider_usage import exact_usage


def response(model="gpt-6-luna"):
    return {
        "object": "response", "model": model, "id": "resp_test_contract",
        "service_tier": "default",
        "usage": {
            "input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200,
            "input_tokens_details": {"cached_tokens": 300, "cache_write_tokens": 400},
            "output_tokens_details": {"reasoning_tokens": 150},
        },
    }


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-6.1-sol", "gpt-5.6-terra"])
def test_disjoint_cache_counts_and_reasoning_subset_are_retained(model):
    actual = exact_usage(response(model), model)
    assert actual["input_tokens"] == 1000
    assert actual["cached_input_tokens"] == 300
    assert actual["cache_write_input_tokens"] == 400
    assert actual["output_tokens"] == 200
    assert actual["reasoning_output_tokens"] == 150
    assert actual["provider_response_id"] == "resp_test_contract"


@pytest.mark.parametrize("section,key", [
    ("usage", "input_tokens"), ("usage", "output_tokens"), ("usage", "total_tokens"),
    ("input_tokens_details", "cached_tokens"),
    ("input_tokens_details", "cache_write_tokens"),
    ("output_tokens_details", "reasoning_tokens"),
])
@pytest.mark.parametrize("invalid", [None, True, "0", -1, 0.0, 9007199254740992])
def test_missing_or_invalid_counts_are_not_inferred(section, key, invalid):
    body = response()
    target = body["usage"] if section == "usage" else body["usage"][section]
    target[key] = invalid
    with pytest.raises(ValueError):
        exact_usage(body, "gpt-6-luna")
    del target[key]
    with pytest.raises(ValueError):
        exact_usage(body, "gpt-6-luna")


def test_inconsistent_overlapping_cache_and_total_counts_reject():
    original = response()
    for key, value in [("cache_write_tokens", 701), ("cached_tokens", 601)]:
        body = deepcopy(original)
        body["usage"]["input_tokens_details"][key] = value
        with pytest.raises(ValueError):
            exact_usage(body, "gpt-6-luna")
    body = deepcopy(original)
    body["usage"]["total_tokens"] += 1
    with pytest.raises(ValueError):
        exact_usage(body, "gpt-6-luna")


@pytest.mark.parametrize("key,value", [
    ("service_tier", "flex"), ("service_tier", None),
    ("model", "gpt-6-luna-unregistered-snapshot"), ("id", None),
])
def test_unknown_prices_or_provider_identity_reject(key, value):
    body = response()
    body[key] = value
    with pytest.raises(ValueError):
        exact_usage(body, "gpt-6-luna")


def test_embedding_uses_its_own_prompt_total_contract():
    body = {"model": "text-embedding-3-small", "usage": {"prompt_tokens": 23, "total_tokens": 23}}
    actual = exact_usage(body, body["model"], embedding=True)
    assert actual["input_tokens"] == actual["total_tokens"] == 23
    assert actual["cache_write_input_tokens"] == actual["cached_input_tokens"] == 0
    assert actual["output_tokens"] == 0
    assert actual["usage_kind"] == "embeddings"
    assert "provider_response_id" not in actual
    assert "service_tier" not in actual
    body["usage"]["total_tokens"] = 24
    with pytest.raises(ValueError):
        exact_usage(body, body["model"], embedding=True)
