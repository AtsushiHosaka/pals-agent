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
    engine, transport = runtime([READY, INTENT, MATCH, REVIEW])
    monkeypatch.setattr(type(engine.catalog), "retrieve", forbidden)
    result, calls = run(engine, [RECIPE])
    assert result.outcome == "answered"
    assert result.answer["text"] == RECIPE["answer"]
    assert result.answer["sources"] == []
    assert result.answer["evidence_kind"] == "lean_catalog"
    assert result.answer["lean"]["entry_sha256"] == RECIPE["entry_sha256"]
    assert calls == [(INTENT["query"], "ja")]
    assert len(transport.calls) == 4
    assert all(
        "answer" not in call["text"]["format"]["schema"]["properties"] for call in transport.calls
    )
    review_prompt = transport.calls[-1]["input"]
    assert "without relying on any prior assessor" in review_prompt
    assert "request.output_language selects the learner-facing prose language" in review_prompt
    assert "Reject learner-facing prose in a different language" in review_prompt
    data = json.loads(review_prompt.split("DATA:\n", 1)[1])
    assert data["lean_source"] == SOURCE and data["answer"] == ANSWER
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
    engine, transport = runtime([READY, INTENT])
    monkeypatch.setattr(
        type(engine.catalog), "retrieve", lambda *a, **kw: pytest.fail("Draft call")
    )
    result, _ = run(engine, [])
    assert result.outcome == "formal" and result.answer is None
    assert result.formal_plan == {"kind": "dsp", "statement": READY["statement"]}
    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    "dimension", ["objects", "domain", "assumptions", "quantifiers", "conclusion", "method"]
)
def test_each_scope_difference_including_specialization_requires_full_dsp(dimension):
    engine, transport = runtime([READY, INTENT, dict(MATCH, **{dimension: False})])
    result, _ = run(engine, [RECIPE])
    assert result.outcome == "formal" and result.formal_plan["kind"] == "dsp"
    assert len(transport.calls) == 3


def test_independent_rejection_cannot_publish_stored_answer():
    engine, transport = runtime([READY, INTENT, MATCH, dict(REVIEW, approved=False)])
    result, _ = run(engine, [RECIPE])
    assert result.outcome == "formal" and result.answer is None
    assert result.formal_plan["kind"] == "dsp" and len(transport.calls) == 4


def test_language_miss_is_never_translated():
    engine, transport = runtime([READY, INTENT])
    result, _ = run(engine, [dict(RECIPE, output_language="en")])
    assert result.outcome == "formal" and result.formal_plan["kind"] == "dsp"
    assert len(transport.calls) == 2


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
    engine, transport = runtime([READY, INTENT])
    result, _ = run(engine, [dict(RECIPE, **changes)])
    assert result.outcome == "failed" and result.error_code == "proof_reuse_recipe_invalid"
    assert result.answer is None and len(transport.calls) == 2


def test_provider_failure_during_independent_review_never_compiles_or_publishes():
    engine, transport = runtime([READY, INTENT, MATCH, 500])
    result, _ = run(engine, [RECIPE])
    assert result.outcome == "failed" and result.answer is None
    assert result.error_code == "proof_reuse_provider_unavailable" and len(transport.calls) == 4


def test_missing_premise_asks_before_recipe_or_draft_search():
    missing = dict(READY, action="needs_input", question={"text": "Domain?", "options": []})
    engine, _ = runtime([missing])
    result, calls = run(engine, [RECIPE])
    assert result.outcome == "needs_input" and calls == [] and engine.catalog.calls == []


def test_uncertainty_requires_dsp_without_paid_generation_escalation():
    uncertain = dict(MATCH, recipe_id=None, recipe_revision=None, domain=False)
    engine, transport = runtime([READY, INTENT, uncertain])
    result, _ = run(engine, [RECIPE])
    assert result.outcome == "formal" and len(transport.calls) == 3


def test_without_lean_flow_previous_answer_path_is_unchanged():
    engine, _ = runtime([READY, decision()])
    result = engine.answer(REQUEST)
    assert result.answer["evidence_kind"] == "llm_assessed" and result.formal_plan is None
