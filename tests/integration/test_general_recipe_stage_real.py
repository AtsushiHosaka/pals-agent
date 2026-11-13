"""The request-path stage with the REAL pinned Lean + Mathlib, zero model calls.

Skipped without a Lake workspace with built Mathlib (PALS_LEAN_WORKSPACE or ./lean-workspace).
"""

import hashlib
import os
import shutil
from pathlib import Path

import pytest

from pals_agent import general_recipe_lane as lane
from pals_agent import general_recipe_stage as stage

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = Path(os.environ.get("PALS_LEAN_WORKSPACE", ROOT / "lean-workspace"))
LAKE = shutil.which("lake") or str(Path.home() / ".elan/bin/lake")
pytestmark = pytest.mark.skipif(
    not (WORKSPACE / ".lake/packages/mathlib").exists() or not Path(LAKE).exists(),
    reason="a Lake workspace with built Mathlib (pinned v4.32.0-rc1) is required",
)


@pytest.fixture(scope="module")
def general() -> stage.GeneralRecipeStage:
    return stage.GeneralRecipeStage(lane.LeanRunner.from_workspace(WORKSPACE, lake=LAKE))


def candidates() -> list[dict]:
    out = []
    for recipe in lane.load_fixture_recipes(ROOT / "testdata"):
        out.append(
            {
                "recipe_id": recipe.recipe_id,
                "recipe_revision": 1,
                "entry_sha256": hashlib.sha256(recipe.recipe_id.encode()).hexdigest(),
                "lean_code": recipe.lean_code,
                "lean_sha256": recipe.lean_sha256,
                "target_source": recipe.target_source,
                "answer": recipe.answer,
                "answer_sha256": hashlib.sha256((recipe.answer or "").encode()).hexdigest(),
                "output_language": "ja",
            }
        )
    return out


def test_cube_continuity_is_answered_from_the_general_power_recipe(general):
    result = general.run(
        "Continuous (fun x : ℝ => x ^ 3)", candidates(), "ja", budget_s=60.0
    )
    assert result.outcome == "answered", (result.code, result.tried)
    assert result.recipe["recipe_id"] and result.answer_text
    evidence = result.evidence()
    assert evidence["model_calls"] == 0 and evidence["back_checks"]["general_theorem_used"]
    assert evidence["timings_ms"]["lean"] > 0


@pytest.mark.parametrize(
    "proposition",
    [
        "Continuous (fun x : ℝ => x ^ 2 + 1)",  # not a specialisation of any stored Recipe
        "(2 : ℝ) + 2 = 4",  # provable without any Recipe: must not be credited to one
    ],
)
def test_non_instances_fall_through(general, proposition):
    result = general.run(proposition, candidates(), "ja", budget_s=60.0)
    assert result.outcome == "miss", result.tried


def test_the_api_wrapper_proves_a_hypothesis_instance_the_lane_accepts(general):
    """The fixed wrapper the API re-derives (recipe_instantiation.elaborate) closes the premises of
    a general theorem with its fixed side-goal closers, so a lane-accepted instance re-derives."""
    from pals_agent.recipe_instantiation import elaborate

    source = (ROOT / "tests/fixtures/general_recipes/pow_monotone.lean").read_text()
    proposition = "∀ n : ℕ, (3 : ℝ) ^ n ≤ 5 ^ n"
    instance = elaborate(source, proposition)
    code, output, _ = general.runner.run(instance.source)
    assert code == 0 and ": error" not in output, output[-600:]
    plain = general.run(
        proposition,
        [
            {
                "recipe_id": "pow", "recipe_revision": 1, "entry_sha256": "1" * 64,
                "lean_code": source, "lean_sha256": "2" * 64, "answer_sha256": "3" * 64,
                "target_source": "∀ (a b : ℝ), 0 ≤ a → a ≤ b → ∀ n : ℕ, a ^ n ≤ b ^ n",
                "answer": "A", "output_language": "ja",
            }
        ],
        "ja", budget_s=60.0, bound=False,
    )
    assert plain.outcome == "answered", (plain.code, plain.tried)
