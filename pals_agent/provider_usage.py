"""Exact, content-free Standard/global provider accounting contract.

Responses cache reads and writes are disjoint subsets of input. Reasoning is a
subset of output. Missing detail is unresolved usage, never an inferred zero.
"""

from __future__ import annotations

from typing import Any

POLICY_V2 = "utilization-tariff-v2-2026-10-07"
ROLE_POLICY_V2 = "pals.billing-role-policy.v2-2026-10-07"
PRICING_PROFILE = "openai-standard-global-2026-10-07"
TARIFF_SNAPSHOTS = {
    model: f"openai-{model}-standard-tariff-2026-10-07"
    for model in ("gpt-6-luna", "gpt-6.1-sol", "gpt-5.6-terra", "text-embedding-3-small")
}


def _count(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 9_007_199_254_740_991:
        raise ValueError("invalid provider token count")
    return value


def exact_usage(body: dict[str, Any], model: str, *, embedding: bool = False) -> dict[str, Any]:
    if model not in TARIFF_SNAPSHOTS or body.get("model") != model:
        raise ValueError("invalid provider model identity")
    usage = body.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("provider usage missing")
    if embedding:
        if model != "text-embedding-3-small":
            raise ValueError("unsupported embedding tariff")
        input_tokens = _count(usage.get("prompt_tokens"))
        output_tokens = cached = write = reasoning = 0
        total = _count(usage.get("total_tokens"))
        # The embeddings response has no response id or service tier. Record
        # its documented endpoint contract instead of fabricating Responses data.
    else:
        if body.get("object") != "response" or body.get("service_tier") != "default":
            raise ValueError("unsupported provider pricing profile")
        response_id = body.get("id")
        if (
            not isinstance(response_id, str)
            or not response_id.startswith("resp_")
            or not 6 <= len(response_id) <= 256
        ):
            raise ValueError("provider response identity missing")
        input_tokens = _count(usage.get("input_tokens"))
        output_tokens = _count(usage.get("output_tokens"))
        total = _count(usage.get("total_tokens"))
        inputs = usage.get("input_tokens_details")
        outputs = usage.get("output_tokens_details")
        if not isinstance(inputs, dict) or not isinstance(outputs, dict):
            raise ValueError("provider usage detail missing")
        cached = _count(inputs.get("cached_tokens"))
        write = _count(inputs.get("cache_write_tokens"))
        reasoning = _count(outputs.get("reasoning_tokens"))
        service_tier = body["service_tier"]
    if (
        cached + write > input_tokens
        or reasoning > output_tokens
        or total != input_tokens + output_tokens
    ):
        raise ValueError("provider usage totals inconsistent")
    result: dict[str, Any] = {
        "usage_kind": "embeddings" if embedding else "responses",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached,
        "cache_write_input_tokens": write,
        "reasoning_output_tokens": reasoning,
        "total_tokens": total,
        "returned_model": model,
        "pricing_profile": PRICING_PROFILE,
    }
    if not embedding:
        result.update(provider_response_id=response_id, service_tier=service_tier)
    return result
