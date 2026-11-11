"""General Recipe -> instance with the REAL pinned Lean + Mathlib, zero model calls.

Needs the pinned toolchain and a Lake workspace with Mathlib built (PALS_LEAN_WORKSPACE or
./lean-workspace); skipped otherwise.  Each case is one Lean process (~4-6 s).
"""

import os
import shutil
from pathlib import Path

import pytest

from pals_agent import general_recipe_lane as lane

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = Path(os.environ.get("PALS_LEAN_WORKSPACE", ROOT / "lean-workspace"))
LAKE = shutil.which("lake") or str(Path.home() / ".elan/bin/lake")
pytestmark = pytest.mark.skipif(
    not (WORKSPACE / ".lake/packages/mathlib").exists() or not Path(LAKE).exists(),
    reason="a Lake workspace with built Mathlib (pinned v4.32.0-rc1) is required",
)
FIXTURES = ROOT / "tests/fixtures/general_recipes"


@pytest.fixture(scope="module")
def runner() -> lane.LeanRunner:
    return lane.LeanRunner.from_workspace(WORKSPACE, lake=LAKE)


@pytest.fixture(scope="module")
def pool() -> list[lane.PoolRecipe]:
    return lane.load_test_fixtures(FIXTURES) + lane.load_fixture_recipes(ROOT / "testdata")


# (family, request, the general Recipe that must produce it)
FAMILIES = [
    # continuity of a composed, parameterised function: HO unification f := x^2+1, g := exp
    (
        "composed-continuity",
        "Continuous (fun x : ℝ => (x ^ 2 + 1) * Real.exp x + (x ^ 2 + 1))",
        "testfixture.composed_continuity",
    ),
    # algebraic identity over a general commutative ring, specialised to a concrete ring
    (
        "ring-identity",
        "∀ x y : ZMod 7, x ^ 2 - y ^ 2 = (x + y) * (x - y)",
        "testfixture.ring_difference_of_squares",
    ),
    (
        "ring-identity-numerals",
        "(5 : ℤ) ^ 2 - 3 ^ 2 = (5 + 3) * (5 - 3)",
        "testfixture.ring_difference_of_squares",
    ),
    # order/analysis statement specialised from a general hypothesis; side goals closed by norm_num
    ("order-hypotheses", "∀ n : ℕ, (3 : ℝ) ^ n ≤ 5 ^ n", "testfixture.pow_monotone"),
    # sets with a hypothesis that must be discharged from the request itself
    (
        "set-hypothesis",
        "∀ A B : Set ℕ, A ⊆ {1, 2} → A ∩ B ⊆ {1, 2}",
        "testfixture.set_inter_subset",
    ),
]


@pytest.mark.parametrize(
    ("family", "request_text", "recipe_id"), FAMILIES, ids=[f[0] for f in FAMILIES]
)
def test_general_recipe_instantiated_by_lean_with_no_model_call(
    family, request_text, recipe_id, pool, runner
):
    result = lane.answer(request_text, pool, runner)
    assert result.outcome == "answered", result.tried
    assert result.recipe_id == recipe_id
    assert result.model_calls == 0
    assert result.proposition == lane.closed_proposition(request_text)
    assert result.timings_ms["lean"] < 15_000


def test_numeric_parameter_recipe_specialises_to_x_squared_without_the_concrete_card(pool, runner):
    general_only = [r for r in pool if r.recipe_id.startswith("continuity.power.natural")]
    result = lane.answer("Continuous (fun x : ℝ => x ^ 2)", general_only, runner)
    assert result.outcome == "answered" and result.recipe_id == general_only[0].recipe_id


@pytest.mark.parametrize(
    "wrong",
    [
        "Continuous (fun x : ℝ => x⁻¹)",  # false: never an instance of anything
        "∀ n : ℕ, (5 : ℝ) ^ n ≤ 3 ^ n",  # false direction: hypothesis 3 <= 5 turns into 5 <= 3
    ],
)
def test_a_statement_that_is_not_an_instance_is_never_answered(wrong, pool, runner):
    result = lane.answer(wrong, pool, runner)
    assert result.outcome == "miss", result.tried


def test_a_closer_cannot_stand_in_for_the_recipe(runner):
    # `2 < 3` is provable by norm_num alone; an unrelated Recipe must not be credited with it:
    # closers only discharge side goals left after the Recipe's conclusion unified.
    unrelated = [
        lane.PoolRecipe(
            "x", "import Mathlib\n\ntheorem unrelated (a : ℕ) : a = a := rfl", "∀ a : ℕ, a = a"
        )
    ]
    result = lane.answer("(2 : ℝ) < 3", unrelated, runner)
    assert result.outcome == "miss"


def test_recipe_containing_sorry_is_rejected(runner):
    bad = [
        lane.PoolRecipe(
            "bad",
            "import Mathlib\n\ntheorem bad_general (a b : ℕ) : a = b := by sorry",
            "∀ a b : ℕ, a = b",
        )
    ]
    result = lane.answer("(1 : ℕ) = 2", bad, runner)
    assert result.outcome == "miss"


@pytest.mark.parametrize(
    ("statement", "recipe_prefix"),
    [
        ("Continuous (fun x : ℝ => x * x)", "continuity.power"),  # x*x is not x ^ 2 syntactically
        ("Continuous (fun x : ℝ => x * x * x)", "continuity.power"),
        ("StrictMono (fun x : ℝ => x ^ 5)", "monotonicity.power.odd"),  # 5 = 2 * 2 + 1
        ("ContinuousAt (fun x : ℝ => x ^ 2) 1", "continuity.power"),  # pointwise corollary
        ("Differentiable ℝ (fun x : ℝ => x * x)", "differentiability.power"),
    ],
)
def test_non_syntactic_instances_use_the_recipe_with_bound_arguments(
    statement, recipe_prefix, pool, runner
):
    general_only = [
        r
        for r in pool
        if r.recipe_id.startswith(recipe_prefix)
        and not r.recipe_id.endswith("square.explicit-epsilon-delta")
    ]
    result = lane.answer(statement, general_only, runner)
    assert result.outcome == "answered", result.tried
    assert result.recipe_id.startswith(recipe_prefix)


def test_a_true_statement_outside_the_recipe_is_still_not_an_instance(pool, runner):
    only_power = [r for r in pool if r.recipe_id.startswith("continuity.power")]
    assert lane.answer("Continuous (fun x : ℝ => x ^ 2 + 1)", only_power, runner).outcome == "miss"
    assert lane.answer("Continuous (fun x : ℝ => |x|)", only_power, runner).outcome == "miss"
