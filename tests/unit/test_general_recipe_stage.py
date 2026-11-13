"""Request-path adapter of the general-Recipe lane: gating, misses, evidence (no Lean)."""

import time

import pytest

from pals_agent import general_recipe_lane as lane
from pals_agent import general_recipe_stage as stage
from pals_agent.proof_reuse import ProofReuseRuntime
from tests.unit.test_proof_reuse_lean_flow import BOUND_REQUEST, CLAIM_ID, lookup
from tests.unit.test_recipe_instantiation_reuse import POWER

REQUEST = dict(BOUND_REQUEST, statement="Prove that f(x)=x^3 is continuous on the real numbers.")


class Boom:
    """A lane object that must never be touched."""

    def run(self, *args, **kwargs):
        raise AssertionError("stage ran although it must be inert")


class Scripted:
    def __init__(self, result):
        self.result, self.calls = result, []

    def run(self, proposition, recipes, language, *, budget_s, bound=True, **kwargs):
        ids = [r["recipe_id"] for r in recipes]
        self.calls.append((proposition, ids, language, budget_s, bound))
        return self.result


def runtime(general_lane, instantiation=True):
    return ProofReuseRuntime(
        client=None, catalog=None, general_lane=general_lane,  # type: ignore[arg-type]
        instantiation_enabled=instantiation,
    )


def answered():
    return stage.StageResult(
        "answered", None, "ANSWER", {"recipe_id": POWER["recipe_id"], "recipe_revision": 1},
        POWER, "Continuous (fun x : ℝ => x ^ 3)", "a" * 64, {"lean": 4800.0}, "request_grammar", [],
    )


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("PALS_GENERAL_RECIPE_LANE", "on")


@pytest.fixture
def handoff(monkeypatch):
    """Capture what the lane hands to the (unchanged) instantiation route."""
    seen = []

    def fake(self, request, context, preflight, proposal, evidence, **kwargs):
        seen.append((proposal, evidence, kwargs))
        return "HANDED_OFF"

    monkeypatch.setattr(ProofReuseRuntime, "_recipe_instantiation", fake)
    return seen


def call(general_lane, request=REQUEST, recipes=(POWER,), instantiation=True, seconds=120):
    search, calls = lookup(list(recipes))
    now = time.monotonic()
    result = runtime(general_lane, instantiation).general_recipe_input(
        request, recipe_search=search, claim_id=CLAIM_ID, deadline=now + seconds, started=now,
    )
    return result, calls


def test_default_runtime_has_no_stage_and_does_nothing():
    assert ProofReuseRuntime(client=None, catalog=None).general_lane is None  # type: ignore[arg-type]
    result, calls = call(None)
    assert result is None and calls == []  # not even a Recipe search


def test_flag_off_or_instantiation_off_never_touches_the_stage(monkeypatch):
    monkeypatch.delenv("PALS_GENERAL_RECIPE_LANE", raising=False)
    result, calls = call(Boom())
    assert result is None and calls == []
    monkeypatch.setenv("PALS_GENERAL_RECIPE_LANE", "on")
    result, calls = call(Boom(), instantiation=False)
    assert result is None and calls == []
    assert stage.from_environment({}) is None
    assert stage.from_environment({"PALS_GENERAL_RECIPE_LANE": "on"}) is None  # no workspace


def test_a_lean_accepted_instance_is_proposed_to_the_unchanged_instantiation_route(on, handoff):
    scripted = Scripted(answered())
    result, calls = call(scripted)
    assert result == "HANDED_OFF" and len(calls) == 1
    proposal, evidence, kwargs = handoff[0]
    # the lane only proposes: no bindings are asserted, the independent review and the API decide
    assert proposal["proposed"]["requested_proposition"] == "Continuous (fun x : ℝ => x ^ 3)"
    assert proposal["proposed"]["bindings"] == []
    assert proposal["chosen"] is POWER or proposal["chosen"]["recipe_id"] == POWER["recipe_id"]
    assert evidence["phase"] == "general_recipe_instantiation"
    assert evidence["general_recipe_lane"]["model_calls"] == 0
    assert scripted.calls[0][0] == "Continuous (fun x : ℝ => x ^ 3)"
    assert scripted.calls[0][4] is False  # plain stage only: what the API re-derives
    assert kwargs["claim_id"] == CLAIM_ID


def test_a_miss_returns_none_so_the_request_continues(on, handoff):
    result, _ = call(Scripted(stage.StageResult("miss", "lean_rejected_all")))
    assert result is None and handoff == []


def test_request_the_grammar_does_not_cover_is_not_sent_to_lean(on, handoff):
    scripted = Scripted(answered())
    result, calls = call(scripted, dict(REQUEST, statement="Explain why the sky is blue."))
    assert result is None and scripted.calls == [] and calls == []


@pytest.mark.parametrize("extra", [{"chat_history": [{"role": "user"}]}, {"attachment_ids": ["x"]}])
def test_conversation_and_attachments_are_out_of_scope(on, handoff, extra):
    scripted = Scripted(answered())
    result, _ = call(scripted, dict(REQUEST, **extra))
    assert result is None and scripted.calls == []


def test_without_time_for_lean_and_the_review_it_returns_before_searching(on, handoff):
    scripted = Scripted(answered())
    result, calls = call(scripted, seconds=35)
    assert result is None and calls == [] and scripted.calls == []


def test_lean_budget_keeps_thirty_seconds_for_the_review(on, handoff):
    scripted = Scripted(answered())
    call(scripted, seconds=60)
    assert 10.0 <= scripted.calls[0][3] <= 30.0


def test_stage_without_budget_or_recipes_is_a_miss():
    runner = lane.LeanRunner("/nonexistent/lean", "")
    general = stage.GeneralRecipeStage(runner)
    assert general.run("True", [POWER], "ja", budget_s=1.0).code == "budget_too_small"
    assert general.run("True", [], "ja", budget_s=30.0).code == "no_recipe"


def test_a_crashing_lane_is_a_miss_not_an_error(monkeypatch):
    def explode(*args, **kwargs):
        raise OSError("lean binary missing")

    monkeypatch.setattr(lane, "answer", explode)
    general = stage.GeneralRecipeStage(lane.LeanRunner("/nonexistent/lean", ""))
    result = general.run("Continuous f", [POWER], "ja", budget_s=30.0)
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


@pytest.mark.parametrize(
    ("statement", "head"),
    [
        ("Continuous fun x : ℝ => x ^ 2", "Continuous"),  # `=>` is not a relation
        ("∀ x : ℝ, x = 0 ↔ x ^ 2 = 0", "↔"),
        ("0 ≤ a ∧ a ≤ b", "∧"),
        ("¬ (∀ i : ℕ, i = i)", "¬"),
        ("∃ x : ℝ, 0 ≤ x", "∃"),
        ("x ∉ S", "∉"),
    ],
)
def test_conclusion_head_top_level_connectives(statement, head):
    assert lane.conclusion_head(statement) == head


def test_related_is_not_fooled_by_connectives_or_prefix_names():
    forall = lane.PoolRecipe("r", "", "∀ x : ℝ, 0 ≤ x ^ 2")
    assert not lane.related("∃ x : ℝ, 0 ≤ x", forall)
    iff = lane.PoolRecipe("r", "", "∀ x : ℝ, x ^ 2 = 0 ↔ x = 0")
    assert not lane.related("(2 : ℝ) + 2 = 4", iff)
    open_set = lane.PoolRecipe("r", "", "∀ s : Set ℝ, IsOpen s")
    assert not lane.related("IsOpenMap f", open_set)
    continuous = lane.PoolRecipe("r", "", "∀ n : ℕ, Continuous (fun x : ℝ => x ^ n)")
    assert not lane.related("ContinuousOn (fun x : ℝ => x ^ 2) s", continuous)


def test_same_recipe_id_with_two_revisions_binds_the_revision_that_answered(monkeypatch):
    seen = {}

    def fake_answer(proposition, pool, runner, **kwargs):
        seen["ids"] = [r.recipe_id for r in pool]
        seen["deadline"] = kwargs["deadline"]
        return lane.LaneResult(
            "answered", None, "r@2", "catalog", proposition, "s" * 64, "REV2", 0, {}, []
        )

    monkeypatch.setattr(lane, "answer", fake_answer)
    base = {"lean_code": "x", "target_source": "t", "output_language": "ja"}
    recipes = [
        dict(base, recipe_id="r", recipe_revision=1, answer="REV1", entry_sha256="1" * 64),
        dict(base, recipe_id="r", recipe_revision=2, answer="REV2", entry_sha256="2" * 64),
    ]
    general = stage.GeneralRecipeStage(lane.LeanRunner("/nonexistent/lean", ""))
    result = general.run("P", recipes, "ja", budget_s=30.0)
    assert seen["ids"] == ["r@1", "r@2"] and seen["deadline"] > 0
    assert result.recipe["recipe_revision"] == 2 and result.recipe["entry_sha256"] == "2" * 64
    assert "timings_ms" in result.evidence() and "seconds" not in result.evidence()


def test_a_timeout_skips_the_second_stage_and_the_total_stays_inside_the_budget(monkeypatch):
    runs = []

    def fake_run(self, source):
        runs.append(self.timeout_seconds)
        return 124, "timeout", self.timeout_seconds

    monkeypatch.setattr(lane.LeanRunner, "run", fake_run)
    source = "import Mathlib\n\ntheorem g (n : ℕ) : Continuous (fun x : ℝ => x ^ n) := by sorry\n"
    pool = [lane.PoolRecipe("r@1", source, "∀ n : ℕ, Continuous (fun x : ℝ => x ^ n)", "A")]
    runner = lane.LeanRunner("/nonexistent/lean", "")
    result = lane.answer(
        "Continuous (fun x : ℝ => x ^ 3)", pool, runner, deadline=time.monotonic() + 20.0
    )
    assert result.outcome == "miss" and result.code == "lean_timeout"
    assert len(runs) == 1 and runs[0] <= 20.0


@pytest.mark.parametrize(
    ("statement", "head"),
    [
        ("∃ x : ℝ, 0 < x ∧ x < 1", "∃"),
        ("∃ x : ℕ, x > 0 → x ≥ 1", "∃"),
        ("∀ a : ℝ, 0 < a → ∃ n : ℕ, a < n", "∃"),
        ("∀ a : ℝ, 0 < a → ∀ n ≥ 1, 0 < a ^ n", "<"),
    ],
)
def test_conclusion_head_existence_and_nested_binders(statement, head):
    assert lane.conclusion_head(statement) == head


