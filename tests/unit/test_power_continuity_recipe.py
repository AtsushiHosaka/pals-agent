"""The general epsilon-delta Recipe for x^n: source shape, claimed estimates in exact arithmetic,
and the preference for it when a request asks about continuity. Real Lean compilation is the
opt-in test at the end (a pinned Lean on PATH and PALS_POWER_RECIPE_LEAN_PATH)."""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

import pytest

from pals_agent.lean_source_policy import find_source_violation
from pals_agent.lean_target import extract_single_target_declaration
from pals_agent.recipe_instantiation import elaborate, universal_parameters
from pals_agent.request_proposition import deterministic_instance_proposal
from tests.unit.test_recipe_instantiation_reuse import POWER

ROOT = Path(__file__).resolve().parents[2] / "testdata" / "power-continuity-recipe-v1"
CARD = json.loads((ROOT / "card.json").read_text(encoding="utf-8"))
SOURCE = (ROOT / CARD["source_path"]).read_text(encoding="utf-8")


def test_source_is_one_theorem_with_the_card_target_and_no_shortcut() -> None:
    assert find_source_violation(SOURCE) is None
    target = extract_single_target_declaration(SOURCE)
    assert target is not None and target.kind == "theorem"
    assert target.name == CARD["theorem_name"]
    assert target.proposition == CARD["target_source"]
    for shortcut in ("continuous_pow", "Continuous.pow", "continuous_id.pow", "fun_prop",
                     "continuity", "sorry", "axiom", "native_decide"):
        assert shortcut not in re.sub(r"--[^\n]*", "", SOURCE)
    assert "Metric.continuousAt_iff" in SOURCE


def test_the_card_target_has_one_natural_parameter_and_instantiates_at_two() -> None:
    parameters = universal_parameters(SOURCE)
    assert [(p.name, p.kind) for p in parameters] == [("n", "Nat")]
    instance = elaborate(SOURCE, "Continuous (fun x : ℝ => x ^ 2)", [])
    assert "exact power_continuous_explicit_epsilon_delta _" in instance.source


def test_manifest_matches_the_proof_file() -> None:
    manifest = json.loads(
        (ROOT / "publication" / f"{CARD['id']}.json").read_text(encoding="utf-8")
    )
    assert manifest["recipe_id"] == CARD["id"]
    assert manifest["target_source"] == CARD["target_source"]
    body = SOURCE.split(":= by\n", 1)[1].rstrip("\n")
    assert manifest["proof_body"] == "by\n" + body


def test_answer_has_the_required_form() -> None:
    answer = CARD["answer"]
    assert "\\min" in answer and "\\varepsilon" in answer and "\\delta" in answer
    assert "#" not in answer and "```" not in answer
    assert answer.count("$") % 2 == 0
    assert "Lean" not in answer and "Mathlib" not in answer
    assert CARD["proof_method_tag"] == "epsilon_delta"
    assert not any(n["statement"] == CARD["statement"] for n in CARD["hard_negatives"])


def _delta(n: int, a: Fraction, eps: Fraction) -> Fraction:
    c = n * (abs(a) + 1) ** (n - 1) + 1 if n else Fraction(1)
    return min(Fraction(1), eps / c)


def test_the_stated_delta_satisfies_the_epsilon_delta_claim_in_exact_arithmetic() -> None:
    rng = random.Random(7)
    checked = 0
    for _ in range(4000):
        n = rng.choice([0, 1, 2, 3, 4, 5, 8])
        a = Fraction(rng.randint(-60, 60), rng.randint(1, 9))
        eps = Fraction(rng.randint(1, 50), rng.randint(1, 50))
        delta = _delta(n, a, eps)
        assert delta > 0 and delta <= 1
        for t in (Fraction(-99, 100), Fraction(-1, 2), Fraction(0), Fraction(1, 3),
                  Fraction(99, 100)):
            x = a + t * delta
            assert abs(x**n - a**n) < eps
            checked += 1
    assert checked == 20000


def test_a_delta_without_the_minimum_with_one_would_fail() -> None:
    # The counterexample that justifies `min 1`: with delta = eps/C alone and a large eps, x leaves
    # the unit neighbourhood and the estimate is no longer valid.
    n, a, eps = 3, Fraction(1), Fraction(1000)
    c = n * (abs(a) + 1) ** (n - 1) + 1
    delta = eps / c
    x = a + delta * Fraction(99, 100)
    assert abs(x**n - a**n) >= eps


def test_n_equal_two_recovers_the_dedicated_delta_shape() -> None:
    a = Fraction(5, 3)
    assert 2 * (abs(a) + 1) ** 1 + 1 == 2 * abs(a) + 3


def test_continuity_requests_try_the_epsilon_delta_recipe_first() -> None:
    induction = dict(POWER, recipe_id="requested.natural_power_continuous",
                     proof_method_tag=None)
    delta = dict(POWER, recipe_id=CARD["id"], proof_method_tag="epsilon_delta")
    proposal = deterministic_instance_proposal("x² の連続性を説明して", [induction, delta])
    assert proposal is not None and proposal["instance_recipe_id"] == CARD["id"]
    only = deterministic_instance_proposal("x² の連続性を説明して", [induction])
    assert only is not None and only["instance_recipe_id"] == induction["recipe_id"]


@pytest.mark.skipif(
    shutil.which("lean") is None or not os.environ.get("PALS_POWER_RECIPE_LEAN_PATH"),
    reason="needs a pinned Lean and PALS_POWER_RECIPE_LEAN_PATH (LEAN_PATH of the pinned Mathlib)",
)
def test_real_lean_compiles_the_recipe_and_its_instances() -> None:
    env = dict(os.environ, LEAN_PATH=os.environ["PALS_POWER_RECIPE_LEAN_PATH"])
    sources = {
        "recipe": SOURCE,
        "n2": elaborate(SOURCE, "Continuous (fun x : ℝ => x ^ 2)", []).source,
        "n0": elaborate(SOURCE, "Continuous (fun x : ℝ => x ^ 0)", []).source,
    }
    with tempfile.TemporaryDirectory() as directory:
        for name, source in sources.items():
            path = Path(directory) / f"{name}.lean"
            path.write_text(source, encoding="utf-8")
            done = subprocess.run(["lean", str(path)], env=env, capture_output=True, text=True,
                                  timeout=900, check=False)
            assert done.returncode == 0, (name, done.stdout[-500:], done.stderr[-500:])
    wrong = elaborate(SOURCE, "Continuous (fun x : ℝ => x ^ 2 + 1)", []).source
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "wrong.lean"
        path.write_text(wrong, encoding="utf-8")
        done = subprocess.run(["lean", str(path)], env=env, capture_output=True, text=True,
                              timeout=900, check=False)
        assert done.returncode != 0
