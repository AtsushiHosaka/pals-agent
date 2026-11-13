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
    assert evidence["seconds"]["lean"] > 0


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
