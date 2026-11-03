"""PFR: Recipe search precedes DSP; only exact sealed bytes bypass compilation."""

import copy
import hashlib
import json

import pytest
import rfc8785

from pals_agent.lean import LeanVerifier
from tests.unit.test_proof_reuse import READY, REQUEST, decision, runtime

REQUEST_ID = "00000000-0000-4000-8000-000000000001"
CLAIM_ID = "00000000-0000-4000-8000-000000000002"
BOUND_REQUEST = dict(REQUEST, id=REQUEST_ID, revision=3)
INTENT = {
    "query": "Continuity of x squared on the real numbers",
    "domain": "Real numbers",
    "assumptions": [],
    "quantifiers": ["All real x"],
    "conclusion": "The function x maps to x squared is continuous",
    "proof_method_tag": None,
}
READY_INTENT = dict(READY, recipe_intent=INTENT)
SOURCE = (
    "import Mathlib\ntheorem square_continuous : Continuous (fun x : ℝ => x ^ 2) := by\n"
    "  fun_prop\n"
)
ANSWER = (
    "関数 $f:\\mathbb{R}\\to\\mathbb{R}$ を $f(x)=x^2$ と定める。"
    "連続関数 $x$ の積なので連続である。"
)
RECIPE = {
    "recipe_id": "square_continuous",
    "recipe_revision": 1,
    "entry_sha256": "e" * 64,
    "statement": "x squared is continuous",
    "domain": "Real numbers",
    "assumptions": [],
    "quantifiers": ["All real x"],
    "conclusion": INTENT["conclusion"],
    "proof_method_tag": None,
    "answer": ANSWER,
    "answer_sha256": hashlib.sha256(ANSWER.encode()).hexdigest(),
    "output_language": "ja",
    "target_source": "Continuous (fun x : ℝ => x ^ 2)",
    "lean_code": SOURCE,
    "lean_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
    "compiler_receipt_sha256": "c" * 64,
    "toolchain_sha256": "t".replace("t", "a") * 64,
}
MATCH = {
    "recipe_id": RECIPE["recipe_id"],
    "recipe_revision": 1,
    **{
        field: True
        for field in ("objects", "domain", "assumptions", "quantifiers", "conclusion", "method")
    },
    "rationale": "Same mathematical scope modulo wording and bound variable names.",
}
REVIEW = {
    "recipe_id": RECIPE["recipe_id"], "recipe_revision": 1,
    "approved": True,
    "rationale": "The actual Lean and stored answer match the original request.",
}


def lookup(recipes):
    calls = []

    def search(query, language):
        calls.append((query, language))
        return copy.deepcopy(recipes)

    return search, calls


def run(engine, recipes, request=BOUND_REQUEST):
    search, calls = lookup(recipes)
    return engine.answer(request, recipe_search=search, claim_id=CLAIM_ID), calls


def test_recipe_hit_returns_stored_answer_without_draft_generation_or_compilation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Recipe hit must not retrieve Drafts or compile")

    monkeypatch.setattr(LeanVerifier, "verify", forbidden)
    engine, transport = runtime([READY_INTENT, MATCH, REVIEW])
    monkeypatch.setattr(type(engine.catalog), "retrieve", forbidden)
    result, calls = run(engine, [RECIPE])
    assert result.outcome == "answered"
    assert result.answer["text"] == RECIPE["answer"]
    assert result.answer["sources"] == []
    assert result.answer["evidence_kind"] == "lean_catalog"
    assert result.answer["lean"]["entry_sha256"] == RECIPE["entry_sha256"]
    assert calls == [(INTENT["query"], "ja")]
    assert len(transport.calls) == 3
    assert all(
        "answer" not in call["text"]["format"]["schema"]["properties"] for call in transport.calls
    )
    review_prompt = next(call["input"] for call in transport.calls
                         if "approved" in call["text"]["format"]["schema"]["properties"])
    assert "without relying on any prior assessor" in review_prompt
    assert "request.output_language selects the learner-facing prose language" in review_prompt
    assert "Reject learner-facing prose in a different language" in review_prompt
    data = json.loads(review_prompt.split("DATA:\n", 1)[1])
    assert data["candidates"][0]["lean_code"] == SOURCE
    assert data["candidates"][0]["answer"] == ANSWER
    assert data["request"]["original_statement"] == REQUEST["statement"]
    assert data["request"]["output_language"] == "ja"
    assert "recipe_scope_assessment" not in data
    receipt = result.private_evidence["recipe_correspondence"]
    assert receipt["assessment_session_id"] != receipt["reviewer_session_id"]
    assert (receipt["request_id"], receipt["claim_id"], receipt["request_revision"]) == (
        REQUEST_ID,
        CLAIM_ID,
        3,
    )
    assert receipt["request_context_sha256"] == hashlib.sha256(rfc8785.dumps(REQUEST)).hexdigest()


def test_valid_search_miss_routes_to_dsp_without_presearching_draft(monkeypatch):
    engine, transport = runtime([READY_INTENT])
    monkeypatch.setattr(
        type(engine.catalog), "retrieve", lambda *a, **kw: pytest.fail("Draft call")
    )
    result, _ = run(engine, [])
    assert result.outcome == "formal" and result.answer is None
    assert result.formal_plan == {"kind": "dsp", "statement": READY["statement"]}
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "dimension", ["objects", "domain", "assumptions", "quantifiers", "conclusion", "method"]
)
def test_each_scope_difference_including_specialization_requires_full_dsp(dimension):
    engine, transport = runtime([READY_INTENT, dict(MATCH, **{dimension: False}), REVIEW])
    result, _ = run(engine, [RECIPE])
    assert result.outcome == "formal" and result.formal_plan["kind"] == "dsp"
    assert len(transport.calls) == 3


def test_independent_rejection_cannot_publish_stored_answer():
    engine, transport = runtime([READY_INTENT, MATCH, dict(REVIEW, approved=False)])
    result, _ = run(engine, [RECIPE])
    assert result.outcome == "formal" and result.answer is None
    assert result.formal_plan["kind"] == "dsp" and len(transport.calls) == 3


def test_language_miss_is_never_translated():
    engine, transport = runtime([READY_INTENT])
    result, _ = run(engine, [dict(RECIPE, output_language="en")])
    assert result.outcome == "formal" and result.formal_plan["kind"] == "dsp"
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"lean_code": SOURCE + "-- modified"},
        {"answer": ANSWER + "変更"},
        {"recipe_revision": True},
        {"compiler_receipt_sha256": "invalid"},
        {"extra": 0},
    ],
)
def test_corrupt_recipe_is_failure_never_dsp_miss(changes):
    engine, transport = runtime([READY_INTENT])
    result, _ = run(engine, [dict(RECIPE, **changes)])
    assert result.outcome == "failed" and result.error_code == "proof_reuse_recipe_invalid"
    assert result.answer is None and len(transport.calls) == 1


def test_provider_failure_during_independent_review_never_compiles_or_publishes():
    engine, transport = runtime([READY_INTENT, MATCH, 500])
    result, _ = run(engine, [RECIPE])
    assert result.outcome == "failed" and result.answer is None
    assert result.error_code == "proof_reuse_provider_unavailable" and len(transport.calls) == 3


def test_missing_premise_asks_before_recipe_or_draft_search():
    missing = dict(READY, action="needs_input", question={"text": "Domain?", "options": []})
    engine, _ = runtime([dict(missing, recipe_intent=None)])
    result, calls = run(engine, [RECIPE])
    assert result.outcome == "needs_input" and calls == [] and engine.catalog.calls == []


def test_uncertainty_requires_dsp_without_paid_generation_escalation():
    uncertain = dict(MATCH, recipe_id=None, recipe_revision=None, domain=False)
    engine, transport = runtime([READY_INTENT, uncertain, REVIEW])
    result, _ = run(engine, [RECIPE])
    assert result.outcome == "formal" and len(transport.calls) == 3


def test_without_lean_flow_previous_answer_path_is_unchanged():
    engine, _ = runtime([READY, decision()])
    result = engine.answer(REQUEST)
    assert result.answer["evidence_kind"] == "llm_assessed" and result.formal_plan is None


@pytest.mark.parametrize("intent", [
    {},
    dict(INTENT, query=""),
    dict(INTENT, assumptions=["a"] * 65),
    dict(INTENT, quantifiers=[True]),
    dict(INTENT, proof_method_tag=1),
    dict(INTENT, additional="untrusted"),
    [],
])
def test_malformed_combined_intent_never_searches_or_publishes(intent):
    engine, provider = runtime([dict(READY, recipe_intent=intent)])
    result, calls = run(engine, [RECIPE])
    assert result.outcome == "failed" and result.error_code == "proof_reuse_invalid_response"
    assert result.answer is None and calls == [] and len(provider.calls) == 1


def test_combined_resolution_is_search_data_and_keeps_both_independent_reviews():
    engine, provider = runtime([READY_INTENT, MATCH, REVIEW])
    result, calls = run(engine, [RECIPE])
    assert result.outcome == "answered"
    assert len(provider.calls) == 3
    assert result.private_evidence["request_structure_source"] == "premise_resolution"
    assert result.private_evidence["request_structure"] == INTENT
    assert "premise_check" in provider.calls[0]["text"]["format"]["schema"]["properties"]
    assert "recipe_intent" in provider.calls[0]["text"]["format"]["schema"]["properties"]
    assessment = json.loads(next(call["input"] for call in provider.calls
        if "objects" in call["text"]["format"]["schema"]["properties"]).split("DATA:\n",1)[1])
    review = json.loads(next(call["input"] for call in provider.calls
        if "approved" in call["text"]["format"]["schema"]["properties"]).split("DATA:\n",1)[1])
    assert assessment["intent"] == INTENT
    candidate = assessment["candidates"][0]
    # Hashes are checked locally before assessment and bound again at settlement;
    # they add no mathematical content to the judge's prompt.
    assert set(candidate) == {
        "recipe_id", "recipe_revision", "statement", "domain", "assumptions", "quantifiers",
        "conclusion", "proof_method_tag", "output_language", "target_source", "lean_code", "answer",
    }
    assert candidate["lean_code"] == RECIPE["lean_code"]
    assert candidate["answer"] == RECIPE["answer"]
    assert result.private_evidence["recipe_candidates"][0]["entry_sha256"] == RECIPE["entry_sha256"]
    assert assessment["request"] == review["request"]
    assert assessment["assessment_session_id"] != review["reviewer_session_id"]
    assert "intent" not in review and "assessment" not in review
    assert calls == [(INTENT["query"], "ja")]


def test_null_combined_intent_uses_separate_extraction_without_skipping_review():
    engine, provider = runtime([dict(READY, recipe_intent=None), INTENT, MATCH, REVIEW])
    result, _ = run(engine, [RECIPE])
    assert result.outcome == "answered" and len(provider.calls) == 4
    assert result.private_evidence["request_structure_source"] == "separate_resolution"


def test_known_convention_changed_statement_discards_prepared_intent():
    from pals_agent.math_conventions import with_readings

    applied = [{"id": "natural_zero", "choice": "include"}]
    ready = dict(READY, recipe_intent=dict(INTENT, query="Stale convention-free query"),
                 premise_check=dict(READY["premise_check"], conventions=["natural_zero"]))
    resolved = with_readings(READY["statement"], applied)
    final_intent = dict(INTENT, query="Natural numbers including zero: continuity of powers")
    engine, provider = runtime([ready, final_intent])
    result, calls = run(engine, [], dict(BOUND_REQUEST, math_conventions={
        "policy": "ask", "choices": {"natural_zero": "include"},
    }))
    assert result.outcome == "formal" and result.formal_plan["statement"] == resolved
    assert calls == [(final_intent["query"], "ja")]
    assert len(provider.calls) == 2
    extraction = json.loads(provider.calls[1]["input"].split("DATA:\n", 1)[1])
    assert extraction["resolved_statement"] == resolved
    assert result.private_evidence["request_structure_source"] == "separate_resolution"


def test_unknown_convention_blocks_search_even_with_prepared_intent():
    ready = dict(READY_INTENT,
                 premise_check=dict(READY["premise_check"], conventions=["natural_zero"]))
    engine, provider = runtime([ready])
    result, calls = run(engine, [RECIPE], dict(BOUND_REQUEST, math_conventions={
        "policy": "ask", "choices": {},
    }))
    assert result.outcome == "needs_input" and result.answer is None
    assert calls == [] and len(provider.calls) == 1
    assert result.private_evidence["convention_question"] == "natural_zero"


@pytest.mark.parametrize("extra", [
    {"conversation_history": [{"statement": "Earlier theorem", "answer": "Earlier result"}]},
    {"chat_history": [{"role": "user", "text": "Earlier theorem",
                       "attachment_ids": [], "context_turns": []}]},
    {"context_turns": [{"question_id": "domain", "question": "Domain?", "answer": "R"}]},
])
def test_contextual_requests_keep_separate_resolution_and_intent_calls(extra):
    engine, provider = runtime([READY, INTENT])
    result, calls = run(engine, [], dict(BOUND_REQUEST, **extra))
    assert result.outcome == "formal" and calls == [(INTENT["query"], "ja")]
    assert len(provider.calls) == 2
    assert "recipe_intent" not in provider.calls[0]["text"]["format"]["schema"]["properties"]
    assert result.private_evidence["request_structure_source"] == "separate_resolution"
