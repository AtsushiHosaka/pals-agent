"""Finite, independently API-validated input profile for an already sealed Recipe.

This registry is not a natural-language parser or an LLM correspondence verdict.
Only the two reviewed UTF-8 statements below are admitted, without normalization.
Every other input retains the existing premise/independent-review pipeline.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

import rfc8785

from pals_agent.chat_images import current_chat_images
from pals_agent.math_conventions import known_readings, parse_claim

SCHEMA = "pals.recipe-exact-input-correspondence.v1"
PROFILE_ID = "natural-power-continuous-real-nat-zero-ja-v1"
STATEMENTS = frozenset(
    {
        "任意の自然数$n$について、実数上の関数$f(x)=x^n$が実数全体で連続であることを証明せよ。$n=0$も含める。",
        (
            "任意の自然数 n（0も含む）について、実数上の関数 f(x)=x^n が実数全体で連続であることを"
            "日本語で証明してください。n=0 の場合も説明してください。"
        ),
    }
)
QUERY = "natural power continuous natural numbers zero real"
PINS: dict[str, Any] = {
    "recipe_id": "requested.natural_power_continuous",
    "recipe_revision": 1,
    "entry_sha256": "89ae94a8fbb18de130615a1bcbc280ce9fb37cd83bbc5df30a094693f0384272",
    "lean_sha256": "2b74ac794880060a9d722414f4abe32689f8023eb173b41d029bd09d14521205",
    "answer_sha256": "962ee7d4e14cb783a0aa5b07c403c3a7c4c38aac9cf401a4eb9c0bce50a7bacd",
    "compiler_receipt_sha256": "0c649f5447d671e02ba819bd7769170aa25dff97fb53f549ec503b1b23ef3a4b",
    "toolchain_sha256": "837542e379e87b592c2e5b87d4c0359c0290abb003a307e35ba1eb9adaa3b156",
    "target_source": "∀ (n : ℕ), Continuous (fun x : ℝ => x ^ n)",
    "output_language": "ja",
    "proof_method_tag": None,
}
TARGET_SHA = hashlib.sha256(PINS["target_source"].encode()).hexdigest()
PROFILE_DESCRIPTOR: dict[str, Any] = {
    "schema_version": "pals.recipe-exact-input-profile.v1",
    "profile_id": PROFILE_ID,
    "normalization": "none",
    "statements": sorted(STATEMENTS),
    "output_language": "ja",
    **{key: PINS[key] for key in ("recipe_id", "recipe_revision", "entry_sha256")},
    "target_sha256": TARGET_SHA,
    **{
        key: PINS[key]
        for key in (
            "lean_sha256",
            "answer_sha256",
            "compiler_receipt_sha256",
            "toolchain_sha256",
        )
    },
    "required_conventions": {"natural_zero": "include", "zero_pow_zero": "include"},
    "request_revision": 1,
    "retry_count": 0,
    "history_policy": "absent",
    "material_policy": "absent",
    "attachment_policy": "absent",
    "provider_calls": 0,
}
PROFILE_SHA256 = hashlib.sha256(rfc8785.dumps(PROFILE_DESCRIPTOR)).hexdigest()
APPLIED = [
    {"id": "natural_zero", "choice": "include"},
    {"id": "zero_pow_zero", "choice": "include"},
]
_FORBIDDEN_EVIDENCE = frozenset({"chat_route", "recipe_correspondence", "answer_qa", "token_qa"})


def eligible(request: dict[str, Any]) -> bool:
    """No trimming, Unicode/TeX normalization, history omission or assumed readings."""
    if (
        not isinstance(request.get("statement"), str)
        or request["statement"] not in STATEMENTS
        or request.get("output_language") != "ja"
        or request.get("context_turns") != []
        or type(request.get("revision")) is not int
        or request["revision"] != 1
        or type(request.get("retry_count", 0)) is not int
        or request.get("retry_count", 0) != 0
        or request.get("formal_job_id") is not None
        or any(
            request.get(key, []) != []
            for key in (
                "chat_history",
                "conversation_history",
                "attachment_ids",
                "chat_images",
                "attachments",
            )
        )
        or "material_context" in request
        or request.get("project_id") is not None
        or current_chat_images()
    ):
        return False
    conventions = parse_claim(request.get("math_conventions"))
    if conventions is None:
        return False
    known = known_readings(conventions)
    return all(known.get(item["id"]) == item["choice"] for item in APPLIED)


def candidate_matches(candidate: dict[str, Any]) -> bool:
    return all(candidate.get(key) == value for key, value in PINS.items())


def correspondence(request: dict[str, Any], claim_id: str) -> dict[str, Any]:
    if not eligible(request):
        raise ValueError("exact_recipe_input_ineligible")
    request_id, revision = request.get("id"), request.get("revision")
    if (
        not isinstance(request_id, str)
        or str(UUID(request_id)) != request_id
        or UUID(request_id).version != 4
        or not isinstance(claim_id, str)
        or str(UUID(claim_id)) != claim_id
        or UUID(claim_id).version != 4
        or type(revision) is not int
        or revision != 1
    ):
        raise ValueError("exact_recipe_claim_invalid")
    return {
        "schema_version": SCHEMA,
        "profile_id": PROFILE_ID,
        "profile_sha256": PROFILE_SHA256,
        "request_id": request_id,
        "claim_id": claim_id,
        "request_revision": revision,
        "request_context_sha256": hashlib.sha256(
            rfc8785.dumps(
                {
                    "statement": request["statement"],
                    "context_turns": [],
                    "output_language": "ja",
                }
            )
        ).hexdigest(),
        **{
            key: PINS[key]
            for key in (
                "entry_sha256",
                "lean_sha256",
                "answer_sha256",
                "toolchain_sha256",
            )
        },
        "statement_sha256": hashlib.sha256(request["statement"].encode()).hexdigest(),
    }


def result_is_bound(
    request: dict[str, Any],
    claim_id: str,
    answer: Any,
    evidence: Any,
) -> bool:
    """Permit the zero-call billing path only for this complete local result binding.

    The API independently rederives the input profile and locked catalog/receipt
    eligibility. This local check never substitutes for that settlement authority.
    """
    try:
        return not (
            not isinstance(answer, dict)
            or not isinstance(evidence, dict)
            or _FORBIDDEN_EVIDENCE & evidence.keys()
            or evidence.get("applied_conventions") != APPLIED
            or evidence.get("recipe_exact_input_correspondence")
            != correspondence(
                request,
                claim_id,
            )
            or answer.get("evidence_kind") != "lean_catalog"
            or answer.get("sources") != []
            or not isinstance(answer.get("text"), str)
            or hashlib.sha256(answer["text"].encode()).hexdigest() != PINS["answer_sha256"]
            or answer.get("lean")
            != {
                "source": "catalog",
                **{
                    key: PINS[key]
                    for key in (
                        "recipe_id",
                        "recipe_revision",
                        "entry_sha256",
                        "answer_sha256",
                        "lean_sha256",
                        "compiler_receipt_sha256",
                        "toolchain_sha256",
                    )
                },
            }
        )
    except (ValueError, TypeError, KeyError):
        return False
