"""A stored universal Recipe answers an instance of itself without proof generation.

Scripted providers stand in for the paid judgments; the Lean wrapper, its digests, the displayed
text and every fail-closed branch are the production code under test. The API compiles the wrapper.
"""

import copy
import hashlib
import json
import time

import pytest

from pals_agent.recipe_instantiation import elaborate, render_answer
from pals_agent.token_meter import TokenMeter, token_meter_scope
from pals_agent.usage import usage_scope
from tests.unit.test_proof_reuse import READY, runtime
from tests.unit.test_proof_reuse_lean_flow import (
    BOUND_REQUEST,
    CLAIM_ID,
    INTENT,
    MATCH,
    RECIPE,
    REQUEST_ID,
    REVIEW,
    lookup,
)
from tests.unit.test_recipe_parallel_reviews import ParallelProvider, engine
from tests.unit.test_token_meter import OP, Ledger

POWER_SOURCE = (
    "import Mathlib\n\nexample : ∀ (n : ℕ), Continuous (fun x : ℝ => x ^ n) := by\n"
    "  intro n\n  induction n with\n"
    "  | zero => simpa using (continuous_const : Continuous (fun _ : ℝ => (1 : ℝ)))\n"
    "  | succ n ih => simpa only [pow_succ, Pi.mul_apply, id_eq] using ih.fun_mul continuous_id\n"
)
POWER_ANSWER = (
    "$n=0$では定数関数$1$なので連続である。$x^n$が連続だと仮定すると、恒等関数$x$も連続なので、"
    "積$x^{n+1}=x^n x$も連続になる。したがって数学的帰納法により、任意の自然数$n$について$x^n$は"
    "実数全体で連続である。"
)
SQUARE = "Continuous (fun x : ℝ => x ^ 2)"
POWER = dict(
    RECIPE,
    recipe_id="requested.natural_power_continuous",
    entry_sha256="8" * 64,
    statement="任意の自然数$n$について、実数上の関数$f(x)=x^n$が実数全体で連続であることを証明せよ。",
    conclusion="∀ (n : ℕ), Continuous (fun x : ℝ => x ^ n)",
    quantifiers=["For every natural number $n$."],
    answer=POWER_ANSWER,
    answer_sha256=hashlib.sha256(POWER_ANSWER.encode()).hexdigest(),
    target_source="∀ (n : ℕ), Continuous (fun x : ℝ => x ^ n)",
    lean_code=POWER_SOURCE,
    lean_sha256=hashlib.sha256(POWER_SOURCE.encode()).hexdigest(),
)
SCOPE_MISS = dict(MATCH, recipe_id=None, recipe_revision=None, objects=False, quantifiers=False)
EXACT_REJECT = dict(REVIEW, recipe_id=None, recipe_revision=None, approved=False)
DIMENSIONS = ("objects", "domain", "assumptions", "quantifiers", "conclusion", "method")
DECLINE = {"instance_recipe_id": None, "instance_recipe_revision": None, "bindings": [],
           "requested_proposition": "", "rationale": "Not an instance of a stored result."}


def proposal(recipe=POWER, proposition=SQUARE, bindings=()):
    return {
        "instance_recipe_id": recipe["recipe_id"], "instance_recipe_revision": 1,
        "bindings": list(bindings), "requested_proposition": proposition,
        "rationale": "The request is the stored theorem applied to particular arguments.",
    }


def review(recipe=POWER, **changes):
    return dict({
        "instance_approved": True, "instance_recipe_id": recipe["recipe_id"],
        "instance_recipe_revision": 1, "bindings": [],
        **{dimension: True for dimension in DIMENSIONS},
        "rationale": "The Lean statement is exactly the requested proposition.",
    }, **changes)


def run(responses, recipes=(POWER,), request=BOUND_REQUEST, ready=None):
    engine_, transport = runtime([ready or dict(READY, recipe_intent=INTENT), *responses])
    search, calls = lookup(list(recipes))
    return engine_.answer(request, recipe_search=search, claim_id=CLAIM_ID), transport, calls


def is_instance_call(body):
    properties = body.get("text", {}).get("format", {}).get("schema", {}).get("properties", {})
    return "bindings" in properties


def test_square_continuity_is_answered_by_lean_unification_without_generation():
    result, transport, _ = run([proposal(), review()])
    assert result.outcome == "answered", result.private_evidence
    evidence = result.private_evidence
    assert evidence["lean_route"] == "catalog_reuse_instantiation"
    instance = elaborate(POWER_SOURCE, SQUARE)
    text = render_answer("ja", POWER["statement"], (), POWER_ANSWER)
    assert result.answer["text"] == text and text.count(POWER_ANSWER) == 1
    assert result.answer["evidence_kind"] == "lean_catalog" and result.answer["sources"] == []
    lean = result.answer["lean"]
    assert (lean["entry_sha256"], lean["lean_sha256"], lean["answer_sha256"]) == (
        POWER["entry_sha256"], POWER["lean_sha256"], POWER["answer_sha256"])
    assert lean["instantiation"] == {
        "schema_version": "pals.recipe-instantiation.v1", "bindings": [],
        "requested_proposition": SQUARE, "instance_source_sha256": instance.source_sha256,
    }
    receipt = evidence["recipe_instantiation_correspondence"]
    assert (receipt["request_id"], receipt["claim_id"], receipt["request_revision"]) == (
        REQUEST_ID, CLAIM_ID, 3)
    assert receipt["requested_proposition"] == SQUARE and receipt["bindings"] == []
    assert receipt["instance_proposition_sha256"] == instance.proposition_sha256
    assert receipt["instance_source_sha256"] == instance.source_sha256
    assert receipt["final_answer_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert receipt["proposer_session_id"] != receipt["reviewer_session_id"]
    assert evidence["answer_qa"] == {
        "approved": True, "answer_sha256": hashlib.sha256(text.encode()).hexdigest()}
    assert "recipe_correspondence" not in evidence
    # preflight, proposal, independent review: the 27 s exact-scope judgment never ran
    assert len(transport.calls) == 3
    assert "recipe_scope_assessment" not in evidence


def test_instance_review_sees_the_wrapper_lean_not_the_proposers_verdict():
    _, transport, _ = run([proposal(), review()])
    reviewer = [c for c in transport.calls if is_instance_call(c)][-1]
    data = json.loads(reviewer["input"].split("DATA:\n", 1)[1])
    instance = elaborate(POWER_SOURCE, SQUARE)
    assert data["instance"]["proposition"] == SQUARE
    assert data["instance"]["lean_source"] == instance.source
    assert "exact pals_recipe_general _" in instance.source
    assert "proposal" not in json.dumps(data["instance"]) and "rationale" not in data["instance"]
    assert data["final_answer"].count(POWER_ANSWER) == 1


def test_another_exponent_and_an_unverified_hint():
    cubed = "Continuous (fun x : ℝ => x ^ 3)"
    hint = [{"variable": "n", "value": "3"}]
    result, _, _ = run([proposal(proposition=cubed, bindings=hint), review()])
    assert result.outcome == "answered"
    assert result.answer["lean"]["instantiation"]["bindings"] == hint
    assert result.answer["lean"]["instantiation"]["requested_proposition"] == cubed
    assert "n=3" not in result.answer["text"]  # elaborator-chosen arguments are never asserted


ADD_SOURCE = "theorem add_comm_nat (a b : Nat) : a + b = b + a := Nat.add_comm a b\n"
ADD_ANSWER = "Addition of natural numbers is commutative: $a+b=b+a$ for all $a,b$."
ADD = dict(
    POWER, recipe_id="nat.add_comm", entry_sha256="9" * 64, output_language="en",
    statement="For all natural numbers $a,b$ we have $a+b=b+a$.",
    conclusion="a + b = b + a", target_source="a + b = b + a", answer=ADD_ANSWER,
    answer_sha256=hashlib.sha256(ADD_ANSWER.encode()).hexdigest(),
    lean_code=ADD_SOURCE, lean_sha256=hashlib.sha256(ADD_SOURCE.encode()).hexdigest(),
)


def test_a_different_universal_recipe_with_two_parameters_in_english():
    request = dict(BOUND_REQUEST, statement="Is 3 + 4 equal to 4 + 3?", output_language="en")
    ready = dict(READY, statement=request["statement"], recipe_intent=INTENT)
    result, _, _ = run([proposal(ADD, "3 + 4 = 4 + 3"), review(ADD)],
                       recipes=(ADD,), request=request, ready=ready)
    assert result.outcome == "answered", result.private_evidence
    assert result.answer["text"].startswith("The statement you asked about is a special case")
    assert result.answer["text"].count(ADD_ANSWER) == 1


def test_only_the_top_ranked_candidates_are_shown_to_the_proposer():
    recipes = [dict(ADD, recipe_id=f"nat.add_comm.{i}", entry_sha256=f"{i}" * 64)
               for i in range(1, 6)]
    for recipe in recipes:
        recipe["output_language"] = "ja"
    _, transport, _ = run([DECLINE, SCOPE_MISS, EXACT_REJECT], recipes=recipes)
    proposer = next(c for c in transport.calls if is_instance_call(c))
    data = json.loads(proposer["input"].split("DATA:\n", 1)[1])
    assert [c["recipe_id"] for c in data["candidates"]] == [r["recipe_id"] for r in recipes[:3]]


def test_candidates_without_a_universal_parameter_never_trigger_extra_calls():
    existential = dict(POWER, lean_code="theorem t : ∃ n : ℕ, n = n := ⟨0, rfl⟩\n")
    existential["lean_sha256"] = hashlib.sha256(existential["lean_code"].encode()).hexdigest()
    result, transport, _ = run([SCOPE_MISS, EXACT_REJECT], recipes=(existential,))
    assert result.outcome == "formal" and len(transport.calls) == 3
    assert result.private_evidence["lean_route"] == "dsp_scope_mismatch"
    assert not any(is_instance_call(call) for call in transport.calls)


def test_exact_agreement_for_a_non_universal_recipe_is_unchanged():
    result, transport, _ = run([MATCH, REVIEW], recipes=(RECIPE,))
    assert result.outcome == "answered"
    assert result.private_evidence["lean_route"] == "catalog_reuse"
    assert len(transport.calls) == 3


def test_declined_instance_falls_through_to_the_unchanged_exact_flow():
    exact = dict(MATCH, recipe_id=POWER["recipe_id"])
    reviewed = dict(REVIEW, recipe_id=POWER["recipe_id"])
    result, transport, _ = run([DECLINE, exact, reviewed])
    assert result.outcome == "answered"
    assert result.private_evidence["lean_route"] == "catalog_reuse"
    assert result.answer["text"] == POWER_ANSWER and "instantiation" not in result.answer["lean"]
    assert len(transport.calls) == 4


@pytest.mark.parametrize("bad", [
    pytest.param(dict(requested_proposition=""), id="empty-proposition"),
    pytest.param(dict(requested_proposition="Continuous (fun x : ℝ => x ^ 2) := by simp"),
                 id="proof-smuggled-into-statement"),
    pytest.param(dict(requested_proposition="(by simp : Continuous (fun x : ℝ => x ^ 2))"),
                 id="tactic-block-rewrites-the-goal"),
    pytest.param(dict(requested_proposition="show True from trivial"), id="show-from"),
    pytest.param(dict(requested_proposition="Continuous (fun x : ℝ => x ^ 2\n"), id="newline"),
    pytest.param(dict(requested_proposition=SQUARE, bindings=[
        {"variable": "n", "value": "1/2"}]), id="rational-hint"),
    pytest.param(dict(bindings=[{"variable": "n", "value": "-1"}]), id="negative-natural-hint"),
    pytest.param(dict(bindings=[{"variable": "x", "value": "2"}]), id="hint-not-a-parameter"),
    pytest.param(dict(bindings=[{"variable": "n", "value": "k+1"}]), id="symbolic-hint"),
])
def test_unsafe_proposals_never_reach_lean_and_fall_back_to_exact_flow_then_dsp(bad):
    result, transport, _ = run([dict(proposal(), **bad), SCOPE_MISS, EXACT_REJECT])
    assert result.outcome == "formal" and result.formal_plan["kind"] == "dsp"
    assert result.private_evidence["lean_route"] == "dsp_scope_mismatch"
    assert result.answer is None and len(transport.calls) == 4
    assert result.private_evidence["recipe_instantiation"]["decision"] in {
        "rejected_by_grammar", "not_proposed"}
    assert "recipe_instantiation_correspondence" not in result.private_evidence


def test_unknown_recipe_from_proposer_is_an_invalid_response_failure():
    result, _, _ = run([dict(proposal(), instance_recipe_id="invented")])
    assert result.outcome == "failed" and result.error_code == "proof_reuse_invalid_response"


@pytest.mark.parametrize("change", [
    {"instance_approved": False},
    {"objects": False}, {"domain": False}, {"assumptions": False},
    {"quantifiers": False}, {"conclusion": False}, {"method": False},
    {"instance_recipe_id": None, "instance_recipe_revision": None},
    {"instance_recipe_id": "other"},
])
def test_reviewer_must_independently_approve_this_lean_statement(change):
    result, transport, _ = run([proposal(), review(**change), SCOPE_MISS, EXACT_REJECT])
    assert result.outcome == "formal" and result.answer is None
    assert result.private_evidence["lean_route"] == "dsp_scope_mismatch"
    assert result.private_evidence["recipe_instantiation"]["class"] == "inst_review_rejected"
    assert "recipe_instantiation_correspondence" not in result.private_evidence


def test_wrong_formalization_of_a_different_statement_is_rejected_by_the_reviewer():
    # The request is about x squared; the proposer formalized x cubed.
    cubed = proposal(proposition="Continuous (fun x : ℝ => x ^ 3)")
    result, transport, _ = run([cubed, review(instance_approved=False, conclusion=False),
                                SCOPE_MISS, EXACT_REJECT])
    assert result.outcome == "formal" and result.answer is None
    reviewer = [c for c in transport.calls if is_instance_call(c)][-1]
    assert "x ^ 3" in reviewer["input"]


def test_recipe_with_only_a_hypothesis_still_reaches_lean_for_the_api_to_decide():
    source = "theorem t (n : ℕ) (h : 0 < n) : 0 < n + 1 := Nat.succ_pos n\n"
    recipe = dict(POWER, lean_code=source, lean_sha256=hashlib.sha256(source.encode()).hexdigest())
    result, _, _ = run([proposal(recipe, "0 < 2 + 1"), review(recipe)], recipes=(recipe,))
    # Lean (not this module) rejects an unprovable premise; here the wrapper is well formed and
    # carries only the closed tactic vocabulary, so approval still requires the API compile.
    assert result.outcome == "answered"
    assert "(by decide)" in elaborate(source, "0 < 2 + 1").source


def test_provider_failure_in_the_instance_stage_fails_closed():
    result, _, _ = run([proposal(), 500])
    assert result.outcome == "failed" and result.answer is None
    assert result.error_code == "proof_reuse_provider_unavailable"


@pytest.mark.parametrize("change", [
    {"instance_approved": "yes"}, {"rationale": ""}, {"objects": "true"},
    {"instance_recipe_revision": True},
])
def test_malformed_reviewer_json_is_an_invalid_response(change):
    result, _, _ = run([proposal(), review(**change)])
    assert result.outcome == "failed" and result.error_code == "proof_reuse_invalid_response"


def test_expired_deadline_never_reaches_the_instance_stage():
    engine_, transport = runtime([dict(READY, recipe_intent=INTENT)])
    search, _ = lookup([POWER])
    result = engine_.answer(BOUND_REQUEST, recipe_search=search, claim_id=CLAIM_ID,
                            deadline=time.monotonic() - 1)
    assert result.outcome == "failed" and result.answer is None
    assert not any(is_instance_call(call) for call in transport.calls)


def test_metered_reuse_binds_exactly_one_new_qa_call_to_the_displayed_text():
    provider = ParallelProvider([dict(READY, recipe_intent=INTENT), proposal(), review()])
    ledger = Ledger([])
    meter = TokenMeter(ledger, OP, REQUEST_ID, CLAIM_ID, time.monotonic() + 30)
    usage = []
    search, _ = lookup([POWER])
    with token_meter_scope(meter), usage_scope(usage.append):
        result = engine(provider).answer(BOUND_REQUEST, recipe_search=search, claim_id=CLAIM_ID)
    assert result.outcome == "answered" and not meter.failed
    qa = result.private_evidence["token_qa"]
    digest = hashlib.sha256(result.answer["text"].encode()).hexdigest()
    assert qa["answer_sha256"] == digest and qa["approved"]
    roles = meter.snapshot_completed_calls()
    assert roles[qa["call_id"]] == "token_answer_qa"
    assert len(ledger.permits) == len(ledger.receipts) == len(usage) == 3
    assert {p["call_id"] for p in ledger.permits} == {r["call_id"] for r in ledger.receipts}


def test_stored_recipe_bytes_are_never_mutated_by_the_stage():
    recipes = [copy.deepcopy(POWER)]
    result, _, _ = run([proposal(), review()], recipes=recipes)
    assert result.outcome == "answered" and recipes == [POWER]
