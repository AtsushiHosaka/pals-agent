"""Finite profile misses never acquire the sealed-answer bypass authority."""

import copy
import hashlib
import importlib.util
import json
import time
from pathlib import Path

import pytest

from pals_agent.chat_runtime import ChatRuntime
from pals_agent.proof_reuse import ProofReuseError
from pals_agent.recipe_exact_input import (
    APPLIED,
    PINS,
    PROFILE_ID,
    STATEMENTS,
    eligible,
    result_is_bound,
)
from tests.unit.test_proof_reuse import runtime
from tests.unit.test_proof_reuse_lean_flow import BOUND_REQUEST, CLAIM_ID


def request(statement=None, **overrides):
    return {
        **BOUND_REQUEST,
        "revision": 1,
        "statement": statement or sorted(STATEMENTS)[0],
        "math_conventions": {"policy": "default", "choices": {}},
        **overrides,
    }


def recipe():
    base = Path(__file__).parents[2] / "testdata/requested-math-seeds-v1"
    spec = importlib.util.spec_from_file_location(
        "exact_input_publication", base / "publication.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = json.loads(
        (base / "publication/requested.natural_power_continuous.json").read_bytes()
    )
    case = next(
        item
        for item in json.loads((base / "corpus.json").read_bytes())["cases"]
        if item["id"] == PINS["recipe_id"]
    )
    return {
        **PINS,
        "statement": case["statement"],
        "domain": case["family_id"],
        "assumptions": case["assumptions"],
        "quantifiers": case["quantifiers"],
        "conclusion": manifest["target_source"],
        "proof_method_tag": None,
        "answer": case["answer"],
        "lean_code": module.materialize(manifest).decode(),
    }


@pytest.mark.parametrize("statement", sorted(STATEMENTS))
def test_exact_two_reviewed_forms_use_actual_stored_bytes_and_no_provider(statement):
    proof, provider = runtime([])
    r = request(statement)
    sealed = recipe()
    result = proof.answer(r, recipe_search=lambda *_: [sealed], claim_id=CLAIM_ID)
    assert result.outcome == "answered" and provider.calls == []
    assert result.answer["text"] == sealed["answer"]
    assert result.private_evidence["recipe_exact_input_correspondence"]["profile_id"] == PROFILE_ID
    assert result.private_evidence["applied_conventions"] == APPLIED
    assert result_is_bound(r, CLAIM_ID, result.answer, result.private_evidence)
    for forbidden in ("recipe_correspondence", "answer_qa", "token_qa", "chat_route"):
        assert forbidden not in result.private_evidence
    # The exact registered source is public, not a newly fabricated theorem.
    assert hashlib.sha256(sealed["lean_code"].encode()).hexdigest() == PINS["lean_sha256"]


def test_chat_bypass_occurs_before_intent_model_and_keeps_catalog_gate():
    proof, provider = runtime([])
    result = ChatRuntime(proof.client, proof).answer(
        request(),
        recipe_search=lambda *_: [recipe()],
        claim_id=CLAIM_ID,
    )
    assert result.outcome == "answered" and provider.calls == []
    assert result.private_evidence["phase"] == "recipe_exact_input"


@pytest.mark.parametrize(
    "alter",
    [
        lambda s: " " + s,
        lambda s: s + "\n",
        lambda s: s + "一様連続も示せ。",
        lambda s: s.replace("自然数", "整数"),
        lambda s: s.replace("実数", "複素数"),
        lambda s: s.replace("x^n", "x^x"),
        lambda s: s.replace("x^n", "n^x"),
        lambda s: s.replace("連続", "一様連続"),
        lambda s: s + "ε-δ法のみで証明せよ。",
        lambda s: "「" + s + "」という文の意味を説明してください。",
        lambda s: s.replace("$", ""),
        lambda s: s.replace("証明せよ", "説明してください"),
    ],
)
def test_no_normalization_or_changed_goal_scope_is_admitted(alter):
    assert not eligible(request(alter(next(s for s in STATEMENTS if "$" in s))))


@pytest.mark.parametrize(
    "override",
    [
        {"output_language": "en"},
        {"context_turns": [{}]},
        {"revision": 2},
        {"revision": True},
        {"retry_count": 1},
        {"retry_count": False},
        {"formal_job_id": "00000000-0000-4000-8000-000000000009"},
        {"chat_history": [{}]},
        {"conversation_history": [{}]},
        {"attachment_ids": ["doc"]},
        {"chat_images": [{}]},
        {"material_context": None},
        {"project_id": "project"},
        {"math_conventions": {"policy": "ask", "choices": {}}},
        {"math_conventions": {"policy": "default", "choices": {"natural_zero": "exclude"}}},
        {"math_conventions": {"policy": "default", "choices": {"zero_pow_zero": "exclude"}}},
    ],
)
def test_context_or_unknown_excluded_convention_keeps_existing_pipeline(override):
    assert not eligible(request(**override))


def test_explicit_authenticated_readings_are_accepted_only_when_both_known():
    assert eligible(
        request(
            math_conventions={
                "policy": "ask",
                "choices": {
                    "natural_zero": "include",
                    "zero_pow_zero": "include",
                },
            }
        )
    )
    assert not eligible(
        request(
            math_conventions={
                "policy": "ask",
                "choices": {
                    "natural_zero": "include",
                },
            }
        )
    )


@pytest.mark.parametrize(
    "key",
    [
        "entry_sha256",
        "lean_sha256",
        "answer_sha256",
        "compiler_receipt_sha256",
        "toolchain_sha256",
        "target_source",
        "recipe_revision",
    ],
)
def test_changed_registry_entry_or_receipt_never_uses_fast_profile(key):
    proof, _ = runtime([])
    entry = recipe()
    entry[key] = 2 if key == "recipe_revision" else "0" * 64
    # Keep hashes consistent when testing changed source or answer identity.
    if key == "lean_sha256":
        entry["lean_code"] = "import Mathlib\n"
    if key == "answer_sha256":
        entry["answer"] = "別の解答"
    if key in {"lean_sha256", "answer_sha256"}:
        field = "lean_code" if key == "lean_sha256" else "answer"
        entry[key] = hashlib.sha256(entry[field].encode()).hexdigest()
    assert (
        proof.exact_recipe_input(request(), recipe_search=lambda *_: [entry], claim_id=CLAIM_ID)
        is None
    )


def test_corrupt_catalog_bytes_are_operational_failure_not_an_eligible_miss():
    proof, _ = runtime([])
    entry = recipe()
    entry["lean_code"] += "-- changed"
    with pytest.raises(ProofReuseError, match="proof_reuse_recipe_invalid"):
        proof.exact_recipe_input(request(), recipe_search=lambda *_: [entry], claim_id=CLAIM_ID)


@pytest.mark.parametrize("changed", ["claim", "request", "revision", "answer", "fake_qa"])
def test_zero_call_result_guard_rejects_rebound_or_fabricated_evidence(changed):
    proof, _ = runtime([])
    r = request()
    result = proof.exact_recipe_input(
        r,
        recipe_search=lambda *_: [recipe()],
        claim_id=CLAIM_ID,
    )
    answer = copy.deepcopy(result.answer)
    evidence = copy.deepcopy(result.private_evidence)
    claim = CLAIM_ID
    if changed == "claim":
        claim = "00000000-0000-4000-8000-000000000003"
    elif changed == "request":
        r["statement"] += " "
    elif changed == "revision":
        r["revision"] += 1
    elif changed == "answer":
        answer["text"] += "変更"
    else:
        evidence["token_qa"] = {"approved": True}
    assert not result_is_bound(r, claim, answer, evidence)


def test_expired_worker_deadline_cannot_publish_even_a_pinned_entry():
    proof, _ = runtime([])
    with pytest.raises(ProofReuseError, match="proof_reuse_deadline"):
        proof.exact_recipe_input(
            request(),
            recipe_search=lambda *_: [recipe()],
            claim_id=CLAIM_ID,
            deadline=time.monotonic() - 1,
        )


@pytest.mark.parametrize("contamination", [None, "forged_receipt", "provider_call"])
def test_claim_bound_token_operation_allows_only_exact_zero_provider_result(contamination):
    from pals_agent.proof_request_worker import ProofRequestProcessor
    from pals_agent.token_meter import active_token_meter
    from tests.unit.test_proof_request_worker import ApiBoundary
    from tests.unit.test_token_meter import OP

    r = request(id="11111111-1111-4111-8111-111111111111", status="assessing")

    class ExactApi(ApiBoundary):
        def acquire_proof_request_claim(self, **kwargs):
            return {
                **super().acquire_proof_request_claim(**kwargs),
                "request": r,
                "billing_operation_id": OP,
                "lean_flow": True,
                "math_conventions": r["math_conventions"],
            }

        def search_proof_request_recipes(self, **kwargs):
            assert kwargs["request_id"] == r["id"]
            return [recipe()]

        def permit_token_call(self, *args, **kwargs):
            pytest.fail("This exact profile must never request a provider permit")

        def record_token_receipt(self, *args, **kwargs):
            pytest.fail("No provider receipt may be fabricated")

    proof, provider = runtime([])

    class CheckedRuntime:
        def answer(self, actual, **kwargs):
            result = proof.answer(actual, **kwargs)
            if contamination == "forged_receipt":
                result.private_evidence["recipe_exact_input_correspondence"]["profile_sha256"] = (
                    "0" * 64
                )
            elif contamination == "provider_call":
                active_token_meter().completed_calls["unexpected"] = "proof_reuse_judge"
            return result

    api = ExactApi()
    assert ProofRequestProcessor(api, CheckedRuntime(), token_accounting_enabled=True).process(
        r["id"],
        CLAIM_ID,
        lambda _: None,
    )
    payload = api.settlements[0]
    assert provider.calls == [] and payload["usage"] == []
    if contamination:
        assert payload["outcome"] == "failed"
        assert payload["error_code"] == "proof_reuse_token_accounting_failed"
    else:
        assert payload["outcome"] == "answered"
        assert payload["conventions"] == APPLIED
        assert "token_qa" not in payload["private_evidence"]


def test_rejected_independent_review_keeps_only_bounded_private_diagnostic():
    from tests.unit.test_proof_reuse_lean_flow import MATCH, READY_INTENT, RECIPE

    proof, _ = runtime(
        [
            READY_INTENT,
            MATCH,
            {"approved": False, "rationale": "The answer omits a required boundary explanation."},
        ]
    )
    result = proof.answer(BOUND_REQUEST, recipe_search=lambda *_: [RECIPE], claim_id=CLAIM_ID)
    assert result.outcome == "formal"
    evidence = result.private_evidence["recipe_independent_review"]
    assert evidence["approved"] is False and evidence["rationale"]
    assert evidence["entry_sha256"] == RECIPE["entry_sha256"]
