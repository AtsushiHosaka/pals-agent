"""With the Lean flow released, requests are never answered without Lean (PFR-010-013)."""

import json

from pals_agent.lean import LeanVerifier
from tests.unit.test_proof_reuse import READY, REQUEST, decision, runtime

RECIPE = {
    "draft_id": "power",
    "recipe_id": "continuous_power",
    "recipe_revision": 1,
    "target_source": "∀ n : ℕ, Continuous fun x : ℝ => x ^ n",
    "lean_code": "theorem continuous_power : ∀ n : ℕ, Continuous fun x : ℝ => x ^ n := by\n"
    "  intro n; exact continuous_pow n",
    "lean_sha256": "c" * 64,
}


def lookup(recipes):
    calls = []

    def recipe_lookup(sources):
        calls.append(sources)
        return list(recipes)

    return recipe_lookup, calls


def test_identical_draft_with_admitted_recipe_reuses_its_lean_without_compiling(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("catalog reuse must not compile")

    monkeypatch.setattr(LeanVerifier, "verify", forbidden)
    engine, transport = runtime([READY, decision(mode="direct", substitutions=[])])
    recipe_lookup, calls = lookup([RECIPE])
    result = engine.answer(REQUEST, recipe_lookup)
    assert result.outcome == "answered"
    assert result.answer["evidence_kind"] == "lean_catalog"
    assert result.answer["lean"] == {
        "source": "catalog",
        "lean_sha256": "c" * 64,
        "recipe_id": "continuous_power",
        "recipe_revision": 1,
    }
    assert [source["draft_id"] for source in calls[0]] == ["power"]
    review = transport.calls[-1]["input"]
    assert "lean_target states exactly the requested claim" in review
    assert RECIPE["target_source"] in json.loads(review.split("DATA:\n", 1)[1])["lean_target"]
    assert result.private_evidence["lean_route"] == "catalog_reuse"


def test_rejected_catalog_review_is_verified_with_dsp_instead_of_failing():
    engine, _ = runtime(
        [
            READY,
            decision(mode="direct", substitutions=[]),
            {"approved": False, "rationale": "The Lean target is a different claim."},
        ]
    )
    result = engine.answer(REQUEST, lookup([RECIPE])[0])
    assert result.outcome == "formal" and result.answer is None
    assert result.formal_plan == {"kind": "dsp", "statement": READY["statement"]}


def test_specialization_with_recipe_compiles_the_substituted_version():
    engine, transport = runtime([READY, decision()])
    result = engine.answer(REQUEST, lookup([RECIPE])[0])
    assert result.outcome == "formal"
    plan = result.formal_plan
    assert plan["kind"] == "instantiate" and plan["recipe_id"] == "continuous_power"
    assert plan["lean_sha256"] == "c" * 64 and plan["substitutions"][0]["variable"] == "n"
    # No answer review runs: nothing is shown until Lean has verified the request.
    assert len(transport.calls) == 2


def test_without_recipe_or_with_derivation_lean_generates_the_proof():
    for change, recipes in ((dict(mode="direct", substitutions=[]), []), ({}, [])):
        engine, _ = runtime([READY, decision(**change)])
        result = engine.answer(REQUEST, lookup(recipes)[0])
        assert (result.outcome, result.formal_plan["kind"]) == ("formal", "dsp")
    engine, _ = runtime(
        [READY, decision(mode="derive", source_ids=[], substitutions=[], supporting_proof="")]
    )
    recipe_lookup, calls = lookup([RECIPE])
    assert engine.answer(REQUEST, recipe_lookup).formal_plan["kind"] == "dsp"
    assert calls == []


def test_uncertainty_is_left_to_lean_and_missing_premises_are_still_asked():
    engine, _ = runtime([READY, decision(action="uncertain"), decision(action="uncertain")])
    assert engine.answer(REQUEST, lookup([])[0]).outcome == "formal"
    missing = dict(READY, action="needs_input", question={"text": "Domain?", "options": []})
    engine, _ = runtime([missing])
    assert engine.answer(REQUEST, lookup([RECIPE])[0]).outcome == "needs_input"


def test_without_the_lean_flow_the_previous_answer_path_is_unchanged():
    engine, _ = runtime([READY, decision()])
    result = engine.answer(REQUEST)
    assert result.answer["evidence_kind"] == "llm_assessed" and result.formal_plan is None
