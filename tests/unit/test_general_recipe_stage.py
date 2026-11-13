"""Request-path adapter of the general-Recipe lane: gating, misses, evidence (no Lean)."""

import time

import pytest

from pals_agent import general_recipe_lane as lane
from pals_agent import general_recipe_stage as stage
from pals_agent.proof_reuse import ProofReuseRuntime
from tests.unit.test_proof_reuse_lean_flow import BOUND_REQUEST, RECIPE, lookup

REQUEST = dict(BOUND_REQUEST, statement="Prove that f(x)=x^3 is continuous on the real numbers.")


class Boom:
    """A lane object that must never be touched."""

    def run(self, *args, **kwargs):
        raise AssertionError("stage ran although it must be inert")


class Scripted:
    def __init__(self, result):
        self.result, self.calls = result, []

    def run(self, proposition, recipes, language, *, budget_s):
        self.calls.append((proposition, [r["recipe_id"] for r in recipes], language, budget_s))
        return self.result


def runtime(general_lane):
    return ProofReuseRuntime(client=None, catalog=None, general_lane=general_lane)  # type: ignore[arg-type]


def answered():
    return stage.StageResult(
        "answered", None, "ANSWER", {"recipe_id": RECIPE["recipe_id"], "recipe_revision": 1},
        "Continuous (fun x : ℝ => x ^ 3)", "a" * 64, {"lean": 4800.0}, [],
    )


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("PALS_GENERAL_RECIPE_LANE", "on")


def call(general_lane, request=REQUEST, recipes=(RECIPE,)):
    search, calls = lookup(list(recipes))
    result = runtime(general_lane).general_recipe_input(
        request, recipe_search=search, deadline=time.monotonic() + 120
    )
    return result, calls


def test_default_runtime_has_no_stage_and_does_nothing():
    assert ProofReuseRuntime(client=None, catalog=None).general_lane is None  # type: ignore[arg-type]
    result, calls = call(None)
    assert result is None and calls == []  # not even a Recipe search


def test_flag_off_never_touches_the_stage(monkeypatch):
    monkeypatch.delenv("PALS_GENERAL_RECIPE_LANE", raising=False)
    result, calls = call(Boom())
    assert result is None and calls == []
    assert stage.from_environment({}) is None
    assert stage.from_environment({"PALS_GENERAL_RECIPE_LANE": "on"}) is None  # no workspace


def test_answered_result_carries_binding_and_lean_evidence(on):
    scripted = Scripted(answered())
    result, calls = call(scripted)
    assert result.outcome == "answered" and result.answer["text"] == "ANSWER"
    assert result.answer["evidence_kind"] == stage.EVIDENCE_KIND
    evidence = result.private_evidence
    assert evidence["model_calls"] == 0 and evidence["lean_route"] == "general_recipe_lane"
    assert evidence["formal_statement"] == "Continuous (fun x : ℝ => x ^ 3)"
    assert evidence["back_checks"] == {
        "declared_statement_equals_request": True,
        "standard_axioms_only": True,
        "general_theorem_used": True,
    }
    assert scripted.calls[0][0] == "Continuous (fun x : ℝ => x ^ 3)"
    assert len(calls) == 1


def test_a_miss_returns_none_so_the_request_continues(on):
    result, _ = call(Scripted(stage.StageResult("miss", "lean_rejected_all")))
    assert result is None


def test_request_the_grammar_does_not_cover_is_not_sent_to_lean(on):
    scripted = Scripted(answered())
    result, calls = call(scripted, dict(REQUEST, statement="Explain why the sky is blue."))
    assert result is None and scripted.calls == [] and calls == []


@pytest.mark.parametrize("extra", [{"chat_history": [{"role": "user"}]}, {"attachment_ids": ["x"]}])
def test_conversation_and_attachments_are_out_of_scope(on, extra):
    scripted = Scripted(answered())
    result, _ = call(scripted, dict(REQUEST, **extra))
    assert result is None and scripted.calls == []


def test_stage_without_budget_or_recipes_is_a_miss():
    runner = lane.LeanRunner("/nonexistent/lean", "")
    general = stage.GeneralRecipeStage(runner)
    assert general.run("True", [RECIPE], "ja", budget_s=1.0).code == "budget_too_small"
    assert general.run("True", [], "ja", budget_s=30.0).code == "no_recipe"


def test_a_crashing_lane_is_a_miss_not_an_error(monkeypatch):
    def explode(*args, **kwargs):
        raise OSError("lean binary missing")

    monkeypatch.setattr(lane, "answer", explode)
    general = stage.GeneralRecipeStage(lane.LeanRunner("/nonexistent/lean", ""))
    result = general.run("Continuous f", [RECIPE], "ja", budget_s=30.0)
    assert result.outcome == "miss" and result.code == "lane_error:OSError"


@pytest.mark.parametrize(
    ("statement", "head"),
    [
        ("∀ n : ℕ, (3 : ℝ) ^ n ≤ 5 ^ n", "≤"),
        ("∀ (a b : ℝ), 0 ≤ a → a ≤ b → a ^ 2 ≤ b ^ 2", "≤"),
        ("Continuous (fun x : ℝ => x ^ 2 ≤ 1)", "Continuous"),
        ("(2 : ℝ) + 2 = 4", "="),
        ("∀ A B : Set ℕ, A ⊆ {1, 2} → A ∩ B ⊆ {1, 2}", "⊆"),
    ],
)
def test_conclusion_head(statement, head):
    assert lane.conclusion_head(statement) == head


def test_a_recipe_of_another_kind_is_not_credited_with_a_trivial_instance():
    differentiable = lane.PoolRecipe(
        "affine", "", "∀ a b : ℝ, Differentiable ℝ (fun x : ℝ => a * x + b)"
    )
    assert not lane.related("(2 : ℝ) + 2 = 4", differentiable)
    assert lane.related("Differentiable ℝ (fun x : ℝ => x * x)", differentiable)


def test_pointwise_corollary_of_a_global_recipe_is_related():
    continuous = lane.PoolRecipe("p", "", "∀ n : ℕ, Continuous (fun x : ℝ => x ^ n)")
    assert lane.related("ContinuousAt (fun x : ℝ => x ^ 2) 1", continuous)
    assert not lane.related("StrictMono (fun x : ℝ => x ^ 3)", continuous)
