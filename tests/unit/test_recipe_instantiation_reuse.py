"""A stored universal Recipe answers an instance of itself without proof generation.

Scripted providers stand in for the two paid judgments; the instantiation itself, its digests, the
displayed wrapper and every fail-closed branch are the production code under test.
"""

import copy
import hashlib
import json
import time

import pytest

from pals_agent.recipe_instantiation import instantiate, render_answer
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


def proposal(recipe=POWER, value="2", variable="n"):
    return {
        "instance_recipe_id": recipe["recipe_id"], "instance_recipe_revision": 1,
        "bindings": [{"variable": variable, "value": value}],
        "rationale": "The request is the stored theorem with n replaced by the literal.",
    }


def review(recipe=POWER, value="2", variable="n", **changes):
    return dict({
        "instance_approved": True, "instance_recipe_id": recipe["recipe_id"],
        "instance_recipe_revision": 1,
        "bindings": [{"variable": variable, "value": value}],
        **{dimension: True for dimension in DIMENSIONS},
        "rationale": "The derived instance is exactly the requested proposition.",
    }, **changes)


def run(responses, recipes=(POWER,), request=BOUND_REQUEST, ready=None):
    engine, transport = runtime([ready or dict(READY, recipe_intent=INTENT), *responses])
    search, calls = lookup(list(recipes))
    return engine.answer(request, recipe_search=search, claim_id=CLAIM_ID), transport, calls


def is_instance_call(body):
    properties = body.get("text", {}).get("format", {}).get("schema", {}).get("properties", {})
    return "bindings" in properties


def test_square_continuity_is_answered_as_n_equals_two_of_the_stored_theorem():
    result, transport, _ = run([SCOPE_MISS, EXACT_REJECT, proposal(), review()])
    assert result.outcome == "answered", result.private_evidence
    evidence = result.private_evidence
    assert evidence["lean_route"] == "catalog_reuse_instantiation"
    instance = instantiate(POWER_SOURCE, [("n", "2")])
    text = render_answer("ja", POWER["statement"], instance.bindings, POWER_ANSWER)
    assert result.answer["text"] == text and POWER_ANSWER in text and "$n=2$" in text
    assert result.answer["evidence_kind"] == "lean_catalog" and result.answer["sources"] == []
    lean = result.answer["lean"]
    assert lean["entry_sha256"] == POWER["entry_sha256"]
    assert lean["lean_sha256"] == POWER["lean_sha256"]
    assert lean["answer_sha256"] == POWER["answer_sha256"]
    assert lean["instantiation"] == {
        "schema_version": "pals.recipe-instantiation.v1",
        "bindings": [{"variable": "n", "value": "2"}],
        "instance_source_sha256": instance.source_sha256,
    }
    receipt = evidence["recipe_instantiation_correspondence"]
    assert receipt["schema_version"] == "pals.recipe-instantiation-correspondence.v1"
    assert (receipt["request_id"], receipt["claim_id"], receipt["request_revision"]) == (
        REQUEST_ID, CLAIM_ID, 3)
    assert receipt["instance_proposition_sha256"] == instance.proposition_sha256
    assert receipt["instance_source_sha256"] == instance.source_sha256
    assert receipt["final_answer_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert receipt["answer_sha256"] == POWER["answer_sha256"]
    assert receipt["proposer_session_id"] != receipt["reviewer_session_id"]
    assert receipt["bindings"] == [{"variable": "n", "value": "2"}] and receipt["approved"] is True
    assert evidence["answer_qa"] == {
        "approved": True, "answer_sha256": hashlib.sha256(text.encode()).hexdigest()}
    assert "recipe_correspondence" not in evidence
    # preflight, exact scope, exact review, proposal, independent instance review: no generation
    assert len(transport.calls) == 5
    assert all("answer" not in call["text"]["format"]["schema"]["properties"]
               for call in transport.calls)


def test_instance_review_sees_the_derived_lean_not_the_proposers_verdict():
    _, transport, _ = run([SCOPE_MISS, EXACT_REJECT, proposal(), review()])
    reviewer = [c for c in transport.calls if is_instance_call(c)][-1]
    data = json.loads(reviewer["input"].split("DATA:\n", 1)[1])
    instance = instantiate(POWER_SOURCE, [("n", "2")])
    assert data["instance"]["proposition"] == instance.proposition
    assert data["instance"]["lean_source"] == instance.source
    assert data["final_answer"].count(POWER_ANSWER) == 1
    assert "rationale" not in json.dumps(data["instance"]) and "proposal" not in data
    assert "specializ" in reviewer["input"].lower()


def test_another_exponent_of_the_same_recipe():
    request = dict(BOUND_REQUEST, statement="x³ は連続ですか？")
    ready = dict(READY, statement=request["statement"], recipe_intent=INTENT)
    result, _, _ = run([SCOPE_MISS, EXACT_REJECT, proposal(value="3"), review(value="3")],
                       request=request, ready=ready)
    assert result.outcome == "answered"
    assert result.answer["lean"]["instantiation"]["bindings"] == [
        {"variable": "n", "value": "3"}]
    assert "$n=3$" in result.answer["text"]


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
    proposed = {
        "instance_recipe_id": "nat.add_comm", "instance_recipe_revision": 1,
        "bindings": [{"variable": "a", "value": "3"}, {"variable": "b", "value": "4"}],
        "rationale": "Instance a=3, b=4.",
    }
    confirmed = review(ADD, bindings=proposed["bindings"])
    result, _, _ = run([dict(SCOPE_MISS), EXACT_REJECT, proposed, confirmed],
                       recipes=(ADD,), request=request, ready=ready)
    assert result.outcome == "answered", result.private_evidence
    assert result.answer["text"].startswith("This is the special case $a=3$, $b=4$")
    assert result.answer["text"].count(ADD_ANSWER) == 1


def test_candidates_without_an_instantiable_prefix_never_trigger_extra_calls():
    existential = dict(POWER, lean_code="theorem t : ∃ n : ℕ, n = n := ⟨0, rfl⟩\n")
    existential["lean_sha256"] = hashlib.sha256(existential["lean_code"].encode()).hexdigest()
    result, transport, _ = run([SCOPE_MISS, EXACT_REJECT], recipes=(existential,))
    assert result.outcome == "formal" and len(transport.calls) == 3
    assert result.private_evidence["lean_route"] == "dsp_scope_mismatch"


def test_exact_assessment_agreement_path_never_runs_the_instance_stage():
    result, transport, _ = run([MATCH, REVIEW], recipes=(RECIPE,))
    assert result.outcome == "answered"
    assert result.private_evidence["lean_route"] == "catalog_reuse"
    assert len(transport.calls) == 3


def test_independent_exact_rejection_with_matching_scope_is_not_retried_as_instance():
    result, transport, _ = run([MATCH, dict(REVIEW, approved=False)], recipes=(RECIPE,))
    assert result.outcome == "formal" and len(transport.calls) == 3
    assert result.private_evidence["lean_route"] == "dsp_correspondence_rejected"


@pytest.mark.parametrize("bad", [
    pytest.param(dict(bindings=[{"variable": "n", "value": "1/2"}]), id="rational-exponent"),
    pytest.param(dict(bindings=[{"variable": "n", "value": "0.5"}]), id="real-exponent"),
    pytest.param(dict(bindings=[{"variable": "n", "value": "-1"}]), id="negative-natural"),
    pytest.param(dict(bindings=[{"variable": "x", "value": "2"}]), id="not-a-parameter"),
    pytest.param(dict(bindings=[{"variable": "n", "value": "k+1"}]), id="symbolic-term"),
    pytest.param(dict(bindings=[]), id="no-substitution"),
    pytest.param(dict(instance_recipe_id=None, instance_recipe_revision=None, bindings=[]),
                 id="proposer-declines"),
])
def test_proposals_outside_the_closed_grammar_fall_back_to_full_dsp(bad):
    result, transport, _ = run([SCOPE_MISS, EXACT_REJECT, dict(proposal(), **bad)])
    assert result.outcome == "formal" and result.formal_plan["kind"] == "dsp"
    assert result.private_evidence["lean_route"] == "dsp_scope_mismatch"
    assert result.answer is None and len(transport.calls) == 4
    assert "recipe_instantiation_correspondence" not in result.private_evidence
    assert result.private_evidence["recipe_instantiation"]["class"] in {
        "inst_no_unifier", "inst_type_mismatch", "inst_unsupported_shape",
        "inst_limit_exceeded"}


def test_unknown_recipe_from_proposer_is_an_invalid_response_failure():
    result, _, _ = run([SCOPE_MISS, EXACT_REJECT,
                        dict(proposal(), instance_recipe_id="invented")])
    assert result.outcome == "failed" and result.error_code == "proof_reuse_invalid_response"


@pytest.mark.parametrize("change", [
    {"instance_approved": False},
    {"objects": False}, {"domain": False}, {"assumptions": False},
    {"quantifiers": False}, {"conclusion": False}, {"method": False},
    {"instance_recipe_id": None, "instance_recipe_revision": None},
    {"bindings": [{"variable": "n", "value": "3"}]},
    {"bindings": []},
])
def test_reviewer_must_independently_approve_the_same_instance(change):
    result, transport, _ = run([SCOPE_MISS, EXACT_REJECT, proposal(), review(**change)])
    assert result.outcome == "formal" and len(transport.calls) == 5
    assert result.private_evidence["lean_route"] == "dsp_scope_mismatch"
    assert result.answer is None
    assert result.private_evidence["recipe_instantiation"]["decision"] == "rejected"
    assert result.private_evidence["recipe_instantiation"]["class"] == "inst_review_rejected"
    assert "recipe_instantiation_correspondence" not in result.private_evidence


def test_recipe_with_a_hypothesis_binder_is_never_specialised():
    source = "theorem t (n : ℕ) (h : 0 < n) : 0 < n + 1 := Nat.succ_pos n\n"
    recipe = dict(POWER, lean_code=source, lean_sha256=hashlib.sha256(source.encode()).hexdigest())
    result, transport, _ = run([SCOPE_MISS, EXACT_REJECT, proposal()], recipes=(recipe,))
    assert result.outcome == "formal" and len(transport.calls) == 4
    assert result.private_evidence["recipe_instantiation"]["decision"] == "rejected_by_grammar"
    assert result.private_evidence["recipe_instantiation"]["class"] == "inst_premise_unprovable"


def test_provider_failure_in_the_instance_stage_fails_closed():
    result, _, _ = run([SCOPE_MISS, EXACT_REJECT, proposal(), 500])
    assert result.outcome == "failed" and result.answer is None
    assert result.error_code == "proof_reuse_provider_unavailable"


@pytest.mark.parametrize("change", [
    {"instance_approved": "yes"}, {"rationale": ""}, {"objects": "true"},
    {"instance_recipe_revision": True},
])
def test_malformed_reviewer_json_is_an_invalid_response(change):
    result, _, _ = run([SCOPE_MISS, EXACT_REJECT, proposal(), review(**change)])
    assert result.outcome == "failed" and result.error_code == "proof_reuse_invalid_response"


def test_expired_deadline_never_reaches_the_instance_stage():
    engine, transport = runtime([dict(READY, recipe_intent=INTENT), SCOPE_MISS, EXACT_REJECT])
    search, _ = lookup([POWER])
    result = engine.answer(BOUND_REQUEST, recipe_search=search, claim_id=CLAIM_ID,
                           deadline=time.monotonic() - 1)
    assert result.outcome == "failed" and result.answer is None
    assert not any(is_instance_call(call) for call in transport.calls)


def test_metered_reuse_binds_exactly_one_new_qa_call_to_the_displayed_text():
    provider = ParallelProvider([
        dict(READY, recipe_intent=INTENT), SCOPE_MISS, EXACT_REJECT, proposal(), review()])
    ledger = Ledger([])
    meter = TokenMeter(ledger, OP, REQUEST_ID, CLAIM_ID, time.monotonic() + 30)
    usage = []
    search, _ = lookup([POWER])
    with token_meter_scope(meter), usage_scope(usage.append):
        result = engine(provider).answer(BOUND_REQUEST, recipe_search=search, claim_id=CLAIM_ID)
    assert result.outcome == "answered" and not meter.failed
    text = result.answer["text"]
    qa = result.private_evidence["token_qa"]
    assert qa["answer_sha256"] == hashlib.sha256(text.encode()).hexdigest() and qa["approved"]
    roles = meter.snapshot_completed_calls()
    assert roles[qa["call_id"]] == "token_answer_qa"
    # exact-scope QA (rejected) and the instance QA are different calls
    assert sum(1 for role in roles.values() if role == "token_answer_qa") == 2
    assert len(ledger.permits) == len(ledger.receipts) == len(usage) == 5
    assert {p["call_id"] for p in ledger.permits} == {r["call_id"] for r in ledger.receipts}


def test_stored_recipe_bytes_are_never_mutated_by_the_stage():
    recipes = [copy.deepcopy(POWER)]
    result, _, _ = run([SCOPE_MISS, EXACT_REJECT, proposal(), review()], recipes=recipes)
    assert result.outcome == "answered" and recipes == [POWER]


def test_wrong_substitution_from_the_proposer_is_not_approved_by_the_independent_review():
    # The proposer claims n=3 for a request about x squared; the reviewer sees x ^ 3 and refuses.
    result, transport, _ = run([
        SCOPE_MISS, EXACT_REJECT, proposal(value="3"),
        review(value="3", instance_approved=False, conclusion=False),
    ])
    assert result.outcome == "formal" and result.answer is None
    assert result.private_evidence["recipe_instantiation"]["class"] == "inst_review_rejected"
    reviewer = [c for c in transport.calls if is_instance_call(c)][-1]
    assert "x ^ 3" in reviewer["input"]
