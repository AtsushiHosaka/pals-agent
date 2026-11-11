"""Pure-Python parts of the general-Recipe lane (no Lean): ranking, template, back-check, flag."""

from pathlib import Path

import pytest

from pals_agent import general_recipe_lane as lane
from pals_agent.recipe_instantiation import InstantiationRejected

TESTDATA = Path(__file__).resolve().parents[2] / "testdata"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "general_recipes"


def pool() -> list[lane.PoolRecipe]:
    return lane.load_test_fixtures(FIXTURES) + lane.load_fixture_recipes(TESTDATA)


def test_flag_is_off_unless_explicitly_on():
    assert not lane.lane_enabled({})
    assert not lane.lane_enabled({"PALS_GENERAL_RECIPE_LANE": "off"})
    assert lane.lane_enabled({"PALS_GENERAL_RECIPE_LANE": "ON"})


def test_example_header_becomes_a_closed_proposition():
    assert lane.closed_proposition("example (n : ℕ) (h : 0 < n) : 0 < n ^ 2") == (
        "∀ (n : ℕ) (h : 0 < n), 0 < n ^ 2"
    )
    assert lane.closed_proposition("Continuous f") == "Continuous f"
    assert lane.closed_proposition("example : 1 + 1 = 2") == "1 + 1 = 2"


@pytest.mark.parametrize(
    "request_text, expected",
    [
        ("Continuous (fun x : ℝ => (x ^ 2 + 1) * Real.exp x + (x ^ 2 + 1))", "composed_continuity"),
        ("∀ x y : ZMod 7, x ^ 2 - y ^ 2 = (x + y) * (x - y)", "ring_difference_of_squares"),
        ("∀ n : ℕ, (3 : ℝ) ^ n ≤ 5 ^ n", "pow_monotone"),
        ("∀ A B : Set ℕ, A ⊆ {1, 2} → A ∩ B ⊆ {1, 2}", "set_inter_subset"),
    ],
)
def test_ranking_uses_lean_constants_not_wording_or_language(request_text, expected):
    ranked = lane.rank_candidates(request_text, pool())
    # A prefilter, not a judge: the right Recipe only has to be inside the compiled top-N.
    top = [r.recipe_id for _, r in ranked[: lane.DEFAULT_CANDIDATES]]
    assert any(i.endswith(expected) for i in top)


def test_ranking_has_no_language_filter_and_no_batch_limit():
    # A Japanese-authored card is a candidate for an English request and vice versa; all 11 + 4
    # recipes are scored (the production local retrieval caps at 32 and filters by language).
    ranked = lane.rank_candidates("Continuous (fun x : ℝ => x ^ 3)", pool())
    ids = {r.recipe_id for _, r in ranked}
    assert "continuity.power.natural.explicit-epsilon-delta" in ids
    many = [
        lane.PoolRecipe(f"r{i}", f"theorem t{i} (a : ℕ) : a = a := rfl", "∀ a : ℕ, a = a")
        for i in range(100)
    ]
    assert len(lane.rank_candidates("∀ a : ℕ, a = a", many)) == 100


def test_template_declares_exactly_the_requested_statement_and_is_one_unit():
    recipes = [r for r in pool() if "pow_monotone" in r.recipe_id or "ring_diff" in r.recipe_id]
    source, rejected = lane.build_source(recipes, "∀ n : ℕ, (3 : ℝ) ^ n ≤ 5 ^ n")
    assert not rejected and source.source.count("import Mathlib") == 1
    for attempt in source.attempts:
        assert (
            f"theorem {attempt.instance_name} : ∀ n : ℕ, (3 : ℝ) ^ n ≤ 5 ^ n := by" in source.source
        )


@pytest.mark.parametrize(
    "bad",
    [
        "True := by sorry",
        "1 = 1 := by simp\n#eval 0",
        "∀ n : ℕ, n = n -- c",
        "(fun x => by exact x)",
    ],
)
def test_requests_with_tactic_or_command_syntax_never_reach_lean(bad):
    with pytest.raises(InstantiationRejected):
        lane.build_source(pool()[:1], bad)


def test_recipe_with_leading_commands_is_not_combinable():
    recipe = lane.PoolRecipe(
        "x", "import Mathlib\nopen Real\ntheorem t (a : ℕ) : a = a := rfl", "∀ a : ℕ, a = a"
    )
    _, rejected = lane.build_source([recipe], "∀ a : ℕ, a = a")
    assert rejected and rejected[0]["recipe"] == "x"


def _unit(recipe_name="pow_monotone"):
    recipe = next(r for r in pool() if recipe_name in r.recipe_id)
    source, _ = lane.build_source([recipe], "∀ n : ℕ, (3 : ℝ) ^ n ≤ 5 ^ n")
    return source, source.attempts[0]


def _output(
    attempt, *, axioms="propext, Classical.choice, Quot.sound", term=True, recipe_axioms=None
):
    g, i = attempt.general_name, attempt.instance_name
    text = f"'{g}' depends on axioms: [{recipe_axioms or axioms}]\n"
    text += f"'{i}' depends on axioms: [{axioms}]\n" if axioms is not None else ""
    text += f"theorem {i} : T :=\n  fun n => {g if term else 'simp_lemma'} _ _ _ n\n"
    return text


def test_backcheck_accepts_only_a_clean_instance_that_uses_the_general_theorem():
    source, attempt = _unit()
    assert lane.back_check(source, attempt, _output(attempt)) is None
    assert lane.back_check(source, attempt, _output(attempt, axioms=None)) == "lean_rejected"
    assert lane.back_check(source, attempt, _output(attempt, axioms="sorryAx")) == "lean_rejected"
    assert lane.back_check(source, attempt, _output(attempt, axioms="propext, myAxiom")) == (
        "nonstandard_axiom"
    )
    assert lane.back_check(source, attempt, _output(attempt, term=False)) == (
        "does_not_use_general_theorem"
    )
    assert lane.back_check(source, attempt, _output(attempt, recipe_axioms="sorryAx")) == (
        "recipe_not_clean"
    )


def test_backcheck_rejects_a_statement_that_is_not_the_derived_one():
    source, attempt = _unit()
    tampered = lane.LaneSource(
        source.source.replace("5 ^ n", "6 ^ n"),
        source.proposition,
        source.attempts,
        source.source_sha256,
    )
    assert lane.back_check(tampered, attempt, _output(attempt)) == "statement_mismatch"


def test_answer_with_a_fake_runner_makes_no_model_call_and_reports_timings():
    class Fake(lane.LeanRunner):
        def run(self, source):
            import re

            names = re.findall(r"theorem (pals_recipe_instance_\d+) :", source)
            general = re.findall(r"(?m)^theorem (pow_le_pow_general)", source)
            out = ""
            for name in names:
                out += (
                    f"'{name}' depends on axioms: [propext]\ntheorem {name} : T := {general[0]}\n"
                )
            out += "'pow_le_pow_general' depends on axioms: [propext]\n"
            return 0, out, 0.01

    result = lane.answer("∀ n : ℕ, (3 : ℝ) ^ n ≤ 5 ^ n", pool(), Fake("lean", ""))
    assert result.model_calls == 0
    assert set(result.timings_ms) >= {"match", "build", "lean", "total"}
    assert result.outcome in {"answered", "miss"}


def test_a_logged_error_vetoes_a_declaration_even_when_axioms_look_clean():
    # a deterministic timeout logs an error but can leave `'x' does not depend on any axioms`
    output = (
        "'g' depends on axioms: [propext]\n"
        "/tmp/I.lean:9:0: error: (deterministic) timeout at `whnf`, maximum number of heartbeats\n"
        "'inst_a' does not depend on any axioms\n"
        "'inst_b' depends on axioms: [propext]\n"
    )
    assert lane.errored_declarations(output) == {"inst_a"}
