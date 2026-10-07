"""With the Lean flow released, requests are never answered without Lean (PFR-010-013)."""

import hashlib
import json

import pytest

from pals_agent.lean import LeanVerifier
from pals_agent.proof_reuse_usage import current_role
from tests.unit.test_proof_reuse import READY, REQUEST, decision
from tests.unit.test_proof_reuse import runtime as legacy_runtime

RECIPE = {
    "draft_id": "power",
    "recipe_id": "continuous_power",
    "recipe_revision": 1,
    "target_source": "∀ n : ℕ, Continuous fun x : ℝ => x ^ n",
    "lean_code": "theorem continuous_power : ∀ n : ℕ, Continuous fun x : ℝ => x ^ n := by\n"
    "  intro n; exact continuous_pow n",
    "lean_sha256": "c" * 64,
}

RECIPE["lean_sha256"] = hashlib.sha256(RECIPE["lean_code"].encode()).hexdigest()
CATALOG_REQUEST = dict(
    REQUEST, statement="Prove that every natural power is continuous on the reals."
)
CATALOG_READY = dict(READY, statement=CATALOG_REQUEST["statement"])
APPROVED = {"approved": True, "rationale": "Same quantified claim and faithful proof."}
GENERATED = {"answer": r"For $n \in \mathbb{N}$, the function $x \mapsto x^n$ on "
             r"$\mathbb{R}$ is continuous by continuity of the identity and finite products.",
             "next_input_suggestion": "Explain the product continuity step."}


def assessment(**changes):
    value = decision(**changes)
    return {key: item for key, item in value.items()
            if key not in {"answer", "next_input_suggestion"}}


def runtime(responses):
    return legacy_runtime([
        {key: value for key, value in item.items()
         if key not in {"answer", "next_input_suggestion"}}
        if isinstance(item, dict) and "mode" in item else item
        for item in responses
    ])


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
    engine, transport = runtime([CATALOG_READY, assessment(mode="direct", substitutions=[]),
                                 APPROVED, GENERATED])
    recipe_lookup, calls = lookup([RECIPE])
    result = engine.answer(CATALOG_REQUEST, recipe_lookup)
    assert result.outcome == "answered"
    assert result.answer["evidence_kind"] == "lean_catalog"
    assert result.answer["lean"] == {
        "source": "catalog",
        "lean_sha256": RECIPE["lean_sha256"],
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
    assert plan["lean_sha256"] == RECIPE["lean_sha256"]
    assert plan["substitutions"][0]["variable"] == "n"
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
    engine, _ = legacy_runtime([READY, decision()])
    result = engine.answer(REQUEST)
    assert result.answer["evidence_kind"] == "llm_assessed" and result.formal_plan is None


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-6.1-sol", "gpt-5.6-terra"])
def test_catalog_answer_uses_selected_model_and_exact_source_between_fixed_reviews(model):
    engine, transport = runtime([
        CATALOG_READY, assessment(mode="direct", substitutions=[]), APPROVED, GENERATED,
    ])
    roles = []
    boundary = transport.request

    def observed(**kwargs):
        roles.append(current_role())
        return boundary(**kwargs)

    transport.request = observed
    result = engine.answer(dict(CATALOG_REQUEST, generation_model=model), lookup([RECIPE])[0])
    assert result.outcome == "answered"
    assert roles == ["proof_reuse_judge", "proof_reuse_judge", "catalog_correspondence",
                     "catalog_answer", "proof_review"]
    assert [call["model"] for call in transport.calls] == [
        "gpt-6-luna", "gpt-6-luna", "gpt-6-luna", model, "gpt-6-luna",
    ]
    assess_schema = transport.calls[1]["text"]["format"]["schema"]["properties"]
    assert "answer" not in assess_schema and "next_input_suggestion" not in assess_schema
    assert "answer" not in result.private_evidence["primary_assessment"]
    correspondence = json.loads(transport.calls[2]["input"].split("DATA:\n", 1)[1])
    generation = json.loads(transport.calls[3]["input"].split("DATA:\n", 1)[1])
    qa = json.loads(transport.calls[4]["input"].split("DATA:\n", 1)[1])
    assert correspondence["lean_source"] == generation["lean_source"] == qa["lean_source"]
    assert generation["lean_source"] == RECIPE["lean_code"]
    assert generation["lean_sha256"] == RECIPE["lean_sha256"]
    assert "candidates" not in generation
    assert qa["answer"] == result.answer["text"] == GENERATED["answer"]
    digest = hashlib.sha256(GENERATED["answer"].encode()).hexdigest()
    assert result.private_evidence["answer_qa"]["answer_sha256"] == digest
    assert result.private_evidence["catalog_answer"]["answer_sha256"] == digest
    assert result.answer["next_input_suggestion"] == GENERATED["next_input_suggestion"]


@pytest.mark.parametrize("rationale", [
    "The source has an additional positivity assumption absent from the request.",
    "The source proves the existential case, not the universal claim requested.",
    "The source uses the product rule although the request explicitly requires induction.",
])
def test_recipe_correspondence_rejection_runs_no_selected_generation(rationale):
    engine, transport = runtime([
        CATALOG_READY, assessment(mode="direct", substitutions=[]),
        {"approved": False, "rationale": rationale},
    ])
    result = engine.answer(
        dict(CATALOG_REQUEST, generation_model="gpt-6.1-sol"), lookup([RECIPE])[0]
    )
    assert result.outcome == "formal" and result.answer is None
    assert result.formal_plan == {"kind": "dsp", "statement": CATALOG_READY["statement"]}
    assert len(transport.calls) == 3
    assert all(call["model"] == "gpt-6-luna" for call in transport.calls)
    assert result.private_evidence["lean_route"] == "dsp_after_catalog_correspondence"


@pytest.mark.parametrize("change", [
    {"lean_code": RECIPE["lean_code"] + "\n-- changed"},
    {"lean_sha256": "c" * 64},
    {"draft_id": "another-draft"},
    {"target_source": ""},
])
def test_recipe_bytes_or_identity_mismatch_falls_through_before_generation(change):
    engine, transport = runtime([CATALOG_READY, assessment(mode="direct", substitutions=[])])
    result = engine.answer(CATALOG_REQUEST, lookup([dict(RECIPE, **change)])[0])
    assert result.outcome == "formal" and result.answer is None
    assert len(transport.calls) == 2
    assert result.private_evidence["lean_route"] == "dsp_after_recipe_integrity"


def test_rejected_selected_catalog_answer_is_not_published_and_routes_to_lean():
    engine, transport = runtime([
        CATALOG_READY, assessment(mode="direct", substitutions=[]), APPROVED,
        {"answer": "Every real function is continuous.", "next_input_suggestion": None},
        {"approved": False, "rationale": "The generated statement is false and changes the goal."},
    ])
    result = engine.answer(
        dict(CATALOG_REQUEST, generation_model="gpt-5.6-terra"), lookup([RECIPE])[0]
    )
    assert result.outcome == "formal" and result.answer is None
    assert result.private_evidence["lean_route"] == "dsp_after_catalog_review"
    assert transport.calls[-1]["model"] == "gpt-6-luna"


@pytest.mark.parametrize("failure", [429, 500, "not JSON"])
def test_selected_catalog_provider_failure_never_substitutes_another_model(failure):
    engine, transport = runtime([
        CATALOG_READY, assessment(mode="direct", substitutions=[]), APPROVED, failure,
    ])
    result = engine.answer(
        dict(CATALOG_REQUEST, generation_model="gpt-6.1-sol"), lookup([RECIPE])[0]
    )
    assert result.outcome == "failed" and result.answer is None
    assert len(transport.calls) == 4 and transport.calls[-1]["model"] == "gpt-6.1-sol"


def test_model_is_per_request_and_cannot_leak_into_fixed_assessment_or_next_request():
    first = [
        CATALOG_READY, assessment(mode="direct", substitutions=[]), APPROVED, GENERATED, APPROVED,
    ]
    engine, transport = runtime([*first, *first])
    selected = engine.answer(
        dict(CATALOG_REQUEST, generation_model="gpt-6.1-sol"), lookup([RECIPE])[0]
    )
    default = engine.answer(CATALOG_REQUEST, lookup([RECIPE])[0])
    assert selected.outcome == default.outcome == "answered"
    assert transport.calls[3]["model"] == "gpt-6.1-sol"
    assert all(call["model"] == "gpt-6-luna" for call in transport.calls[5:])


def test_unsupported_generation_model_is_rejected_without_a_provider_call():
    engine, transport = runtime([])
    result = engine.answer(dict(CATALOG_REQUEST, generation_model="unknown"), lookup([RECIPE])[0])
    assert result.outcome == "failed" and result.error_code == "proof_reuse_input_invalid"
    assert transport.calls == []


def test_missing_math_premise_asks_before_any_selected_generation_or_recipe_lookup():
    ready = dict(
        CATALOG_READY, action="needs_input", question={"text": "Which domain?", "options": []}
    )
    engine, transport = runtime([ready])
    reader, lookups = lookup([RECIPE])
    result = engine.answer(dict(CATALOG_REQUEST, generation_model="gpt-6.1-sol"), reader)
    assert result.outcome == "needs_input" and result.answer is None
    assert lookups == [] and len(transport.calls) == 1
    assert transport.calls[0]["model"] == "gpt-6-luna"


def test_fixed_uncertainty_escalation_does_not_override_selected_catalog_generator():
    engine, transport = runtime([
        CATALOG_READY, assessment(action="uncertain"),
        assessment(mode="direct", substitutions=[]), APPROVED, GENERATED,
    ])
    result = engine.answer(
        dict(CATALOG_REQUEST, generation_model="gpt-6.1-sol"), lookup([RECIPE])[0]
    )
    assert result.outcome == "answered"
    assert [call["model"] for call in transport.calls] == [
        "gpt-6-luna", "gpt-6-luna", "gpt-5.6-terra", "gpt-6-luna",
        "gpt-6.1-sol", "gpt-6-luna",
    ]
    assert "answer" not in result.private_evidence["escalated_assessment"]
