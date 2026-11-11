"""Offline card kits for the general (universally quantified) Recipe families: source shape, card
shape, byte-exact manifest, the claimed estimates in exact arithmetic, instantiation to concrete
requests, and a counterexample for each kit. Real Lean compilation is the opt-in test at the end
(PALS_GENERAL_RECIPE_LEAN=1, a pinned Lean 4.32.0-rc1 and a built Mathlib, one process at a time).

The precedent for this layout is ``test_power_continuity_recipe.py``. None of the kits is admitted,
reviewed, signed or published: the lifecycle flags of every card are asserted to say so."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import random
import re
import subprocess
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import rfc8785

from pals_agent.lean_source_policy import find_source_violation
from pals_agent.lean_target import extract_single_target_declaration
from pals_agent.recipe_entry_review import validate_entry
from pals_agent.recipe_instantiation import elaborate, universal_parameters
from pals_agent.request_proposition import bind_recipe, deterministic_instance_proposal
from tests.unit.test_recipe_elaboration_lean import PINNED, mathlib_environment
from tests.unit.test_recipe_instantiation_reuse import POWER

TESTDATA = Path(__file__).resolve().parents[2] / "testdata"
STANDARD_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
# Library shortcuts that would turn an epsilon-delta card into a one-liner.
EPSILON_DELTA_SHORTCUTS = (
    "continuous_const",
    "continuous_id",
    "Continuous.mul",
    "Continuous.add",
    "continuous_mul",
    "uniformContinuous_const",
    "UniformContinuous.mul",
    "LipschitzWith",
    "fun_prop",
    "continuity",
    "Continuous.const_smul",
)
GENERAL_SHORTCUTS = (
    "sorry",
    "axiom",
    "native_decide",
    "fun_prop",
    "Odd.strictMono_pow",
    "differentiable_pow",
    "Differentiable.pow",
    "differentiableAt_pow",
)


@dataclass(frozen=True)
class Kit:
    directory: str
    recipe_id: str
    theorem: str
    target: str
    parameters: tuple[tuple[str, str], ...]
    tag: str
    must_use: tuple[str, ...]  # Mathlib names the proof is expected to be built from
    instances: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]  # (request, hints)
    wrong_target: str  # a false statement of the same shape: the stored proof must not prove it
    wrong_request: str  # a proposition that is not an instance (or is false)
    epsilon_delta: bool


KITS = (
    Kit(
        directory="power-differentiability-recipe-v1",
        recipe_id="differentiability.power.natural.induction-product-rule",
        theorem="power_differentiable_induction_product_rule",
        target="∀ (n : ℕ), Differentiable ℝ (fun x : ℝ => x ^ n)",
        parameters=(("n", "Nat"),),
        tag="induction_product_rule",
        must_use=("ih.mul", "differentiable_id"),
        instances=(
            ("Differentiable ℝ (fun x : ℝ => x ^ 2)", ()),
            ("Differentiable ℝ (fun x : ℝ => x ^ 0)", ()),
        ),
        wrong_target="∀ (n : ℕ), Differentiable ℝ (fun x : ℝ => |x ^ n|)",
        wrong_request="Differentiable ℝ (fun x : ℝ => |x|)",
        epsilon_delta=False,
    ),
    Kit(
        directory="linear-continuity-recipe-v1",
        recipe_id="continuity.linear.real.explicit-epsilon-delta",
        theorem="linear_continuous_explicit_epsilon_delta",
        target="∀ (c : ℝ), Continuous (fun x : ℝ => c * x)",
        parameters=(("c", "Real"),),
        tag="epsilon_delta",
        must_use=("Metric.continuousAt_iff",),
        instances=(
            ("Continuous (fun x : ℝ => 3 * x)", ()),
            ("Continuous (fun x : ℝ => 0 * x)", ()),
        ),
        wrong_target="∀ (c : ℝ), Continuous (fun x : ℝ => c * (⌊x⌋ : ℝ))",
        wrong_request="Continuous (fun x : ℝ => 3 * x ^ 2)",
        epsilon_delta=True,
    ),
    Kit(
        directory="linear-differentiability-recipe-v1",
        recipe_id="differentiability.linear.real.difference-quotient",
        theorem="linear_differentiable_difference_quotient",
        target="∀ (c : ℝ), Differentiable ℝ (fun x : ℝ => c * x)",
        parameters=(("c", "Real"),),
        tag="difference_quotient",
        must_use=("hasDerivAt_iff_isLittleO", "Asymptotics.isLittleO_zero"),
        instances=(
            ("Differentiable ℝ (fun x : ℝ => 3 * x)", ()),
            ("Differentiable ℝ (fun x : ℝ => 0 * x)", ()),
        ),
        wrong_target="∀ (c : ℝ), Differentiable ℝ (fun x : ℝ => c * |x|)",
        wrong_request="Differentiable ℝ (fun x : ℝ => 3 * |x|)",
        epsilon_delta=False,
    ),
    Kit(
        directory="linear-uniform-continuity-recipe-v1",
        recipe_id="uniform-continuity.linear.real.explicit-epsilon-delta",
        theorem="linear_uniformly_continuous_explicit_epsilon_delta",
        target="∀ (c : ℝ), UniformContinuous (fun x : ℝ => c * x)",
        parameters=(("c", "Real"),),
        tag="epsilon_delta",
        must_use=("Metric.uniformContinuous_iff",),
        instances=(
            ("UniformContinuous (fun x : ℝ => 3 * x)", ()),
            ("UniformContinuous (fun x : ℝ => 0 * x)", ()),
        ),
        wrong_target="∀ (c : ℝ), UniformContinuous (fun x : ℝ => c * x ^ 2)",
        wrong_request="UniformContinuous (fun x : ℝ => 3 * x ^ 2)",
        epsilon_delta=True,
    ),
    Kit(
        directory="affine-continuity-recipe-v1",
        recipe_id="continuity.affine.real.explicit-epsilon-delta",
        theorem="affine_continuous_explicit_epsilon_delta",
        target="∀ (a b : ℝ), Continuous (fun x : ℝ => a * x + b)",
        parameters=(("a", "Real"), ("b", "Real")),
        tag="epsilon_delta",
        must_use=("Metric.continuousAt_iff",),
        instances=(
            ("Continuous (fun x : ℝ => 2 * x + 1)", ()),
            ("Continuous (fun x : ℝ => 0 * x + 5)", ()),
        ),
        wrong_target="∀ (a b : ℝ), Continuous (fun x : ℝ => a * (⌊x⌋ : ℝ) + b)",
        wrong_request="Continuous (fun x : ℝ => 2 * x ^ 2 + 1)",
        epsilon_delta=True,
    ),
    Kit(
        directory="affine-differentiability-recipe-v1",
        recipe_id="differentiability.affine.real.difference-quotient",
        theorem="affine_differentiable_difference_quotient",
        target="∀ (a b : ℝ), Differentiable ℝ (fun x : ℝ => a * x + b)",
        parameters=(("a", "Real"), ("b", "Real")),
        tag="difference_quotient",
        must_use=("hasDerivAt_iff_isLittleO", "Asymptotics.isLittleO_zero"),
        instances=(
            ("Differentiable ℝ (fun x : ℝ => 2 * x + 1)", ()),
            ("Differentiable ℝ (fun x : ℝ => 0 * x + 5)", ()),
        ),
        wrong_target="∀ (a b : ℝ), Differentiable ℝ (fun x : ℝ => a * |x| + b)",
        wrong_request="Differentiable ℝ (fun x : ℝ => 2 * |x| + 1)",
        epsilon_delta=False,
    ),
    Kit(
        directory="affine-uniform-continuity-recipe-v1",
        recipe_id="uniform-continuity.affine.real.explicit-epsilon-delta",
        theorem="affine_uniformly_continuous_explicit_epsilon_delta",
        target="∀ (a b : ℝ), UniformContinuous (fun x : ℝ => a * x + b)",
        parameters=(("a", "Real"), ("b", "Real")),
        tag="epsilon_delta",
        must_use=("Metric.uniformContinuous_iff",),
        instances=(
            ("UniformContinuous (fun x : ℝ => 2 * x + 1)", ()),
            ("UniformContinuous (fun x : ℝ => 0 * x + 5)", ()),
        ),
        wrong_target="∀ (a b : ℝ), UniformContinuous (fun x : ℝ => a * x ^ 2 + b)",
        wrong_request="UniformContinuous (fun x : ℝ => 2 * x ^ 2 + 1)",
        epsilon_delta=True,
    ),
    Kit(
        directory="odd-power-strict-mono-recipe-v1",
        recipe_id="monotonicity.power.odd.sign-cases",
        theorem="odd_power_strictly_increasing_sign_cases",
        target="∀ (n : ℕ), StrictMono (fun x : ℝ => x ^ (2 * n + 1))",
        parameters=(("n", "Nat"),),
        tag="sign_cases",
        must_use=("pow_lt_pow_left₀", "hm.neg_pow", "hm.pow_neg"),
        instances=(
            ("StrictMono (fun x : ℝ => x ^ 3)", (("n", "1"),)),
            ("StrictMono (fun x : ℝ => x ^ 1)", (("n", "0"),)),
        ),
        wrong_target="∀ (n : ℕ), StrictMono (fun x : ℝ => x ^ (2 * n))",
        wrong_request="StrictMono (fun x : ℝ => x ^ 2)",
        epsilon_delta=False,
    ),
)
IDS = [kit.directory for kit in KITS]


def _load(kit: Kit) -> tuple[Path, dict[str, Any], str, ModuleType]:
    root = TESTDATA / kit.directory
    card = json.loads((root / "card.json").read_text(encoding="utf-8"))
    source = (root / card["source_path"]).read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        f"publication_{kit.directory.replace('-', '_')}", root / "publication.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return root, card, source, module


@pytest.fixture(params=KITS, ids=IDS)
def kit(request: pytest.FixtureRequest) -> Kit:
    return request.param  # type: ignore[no-any-return]


def test_every_kit_directory_is_covered() -> None:
    """A new `*-recipe-v1` kit with the general-recipe card schema must be added to this file."""
    found = {
        path.parent.name
        for path in TESTDATA.glob("*-recipe-v1/card.json")
        if json.loads(path.read_text(encoding="utf-8")).get("schema_version")
        == "pals.general-recipe-card.v1"
    }
    assert found == set(IDS)
    assert len({kit.recipe_id for kit in KITS}) == len(KITS)
    assert len({kit.theorem for kit in KITS}) == len(KITS)


def test_source_is_one_theorem_with_the_card_target_and_no_shortcut(kit: Kit) -> None:
    _, card, source, _ = _load(kit)
    assert find_source_violation(source) is None
    target = extract_single_target_declaration(source)
    assert target is not None and target.kind == "theorem"
    assert target.name == card["theorem_name"] == kit.theorem
    assert target.proposition == card["target_source"] == kit.target
    code = re.sub(r"--[^\n]*", "", source)
    assert source.count("theorem ") == 1 and source.startswith("import Mathlib\n")
    for shortcut in GENERAL_SHORTCUTS + (EPSILON_DELTA_SHORTCUTS if kit.epsilon_delta else ()):
        assert shortcut not in code, shortcut
    for name in kit.must_use:
        assert name in code, name


def test_the_card_target_has_leading_explicit_binders_and_instantiates(kit: Kit) -> None:
    _, _, source, _ = _load(kit)
    parameters = universal_parameters(source)
    assert tuple((p.name, p.kind) for p in parameters) == kit.parameters
    for request, hints in kit.instances:
        instance = elaborate(source, request, list(hints))
        assert f"exact {kit.theorem}" in instance.source


def test_the_instantiation_route_does_not_bind_the_wrong_request(kit: Kit) -> None:
    # A request that is not an instance of the universal target must not bind syntactically.
    assert bind_recipe(kit.target, kit.wrong_request) is None


def test_manifest_matches_the_proof_file_and_is_byte_exact(kit: Kit) -> None:
    root, card, source, publication = _load(kit)
    committed = (root / "publication" / f"{card['id']}.json").read_bytes()
    manifest = json.loads(committed)
    assert manifest["recipe_id"] == card["id"] == kit.recipe_id
    assert manifest["target_source"] == card["target_source"]
    body = source.split(":= by\n", 1)[1].rstrip("\n")
    assert manifest["proof_body"] == "by\n" + body
    assert committed == rfc8785.dumps(publication.authoring_manifest(card))
    materialized = publication.materialize(manifest).decode()
    assert materialized == f"import Mathlib\n\nexample : {kit.target} := by\n{body}\n"


def test_a_synthetic_receipt_yields_an_entry_the_review_gate_accepts(kit: Kit) -> None:
    """Pure binding check with a fake receipt: nothing here is an admission or a signature."""
    root, card, _, publication = _load(kit)
    manifest = publication.authoring_manifest(card)
    source = publication.materialize(manifest)
    receipt: dict[str, Any] = {
        "schema_version": "pals.recipe-admission-compiler-receipt.v1",
        "materialized_source_sha256": hashlib.sha256(source).hexdigest(),
        "toolchain_fingerprint_sha256": hashlib.sha256(
            rfc8785.dumps(manifest["toolchain"]["fingerprint"])
        ).hexdigest(),
        "compiler_command_sha256": "0" * 64,
        "compiler_result": {
            "schema_version": "pals.recipe-admission-compiler-result.v1",
            "verification_succeeded": True,
            "diagnostic_codes": [],
        },
    }
    entry = publication.search_candidate(card, manifest, receipt)
    validate_entry(entry, source.decode())
    assert entry["proof_method_tag"] == kit.tag and entry["output_language"] == "ja"
    assert len(entry["search_text"]) < 20_000
    receipt["compiler_result"]["verification_succeeded"] = False
    with pytest.raises(ValueError):
        publication.search_candidate(card, manifest, receipt)


def test_card_shape_lifecycle_and_negatives(kit: Kit) -> None:
    _, card, _, _ = _load(kit)
    assert card["schema_version"] == "pals.general-recipe-card.v1"
    assert card["id"] == kit.recipe_id and re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", card["id"])
    assert card["proof_method_tag"] == kit.tag
    assert re.fullmatch(r"[a-z][a-z0-9_]{0,127}", card["proof_method_tag"])
    assert card["lifecycle"] == {
        "authored": True,
        "independently_reviewed": False,
        "admitted": False,
        "retrievable": False,
        "runtime_verified": False,
        "deployed": False,
    }
    assert card["status"] == "authored_awaiting_execution"
    for field in ("assumptions", "quantifiers", "proof_outline"):
        assert card[field] and all(isinstance(item, str) and item for item in card[field])
    for language in ("ja", "en"):
        assert len(card["question_variants"][language]) >= 4
        assert len(card["aliases"][language]) >= 8
    negatives = card["hard_negatives"]
    assert len(negatives) >= 8 and len({n["id"] for n in negatives}) == len(negatives)
    assert not any(n["statement"] == card["statement"] for n in negatives)
    assert all(set(n) == {"id", "dimension", "statement", "reason"} for n in negatives)
    assert len({n["statement"] for n in negatives}) == len(negatives)
    assert card["provenance"]["mathlib_revision"] == "8b62164d808cd0f23b7d8cc28190a6c1a1bb483a"


def test_answer_has_the_required_form(kit: Kit) -> None:
    _, card, _, _ = _load(kit)
    answer = card["answer"]
    assert 300 < len(answer) < 2500
    assert "#" not in answer and "```" not in answer
    assert answer.count("$") % 2 == 0
    for word in ("Lean", "Mathlib", "sorry", "tactic", "linarith", "simp"):
        assert word not in answer, word
    assert answer.endswith("\n") and answer.count("\n\n") >= 2
    assert re.search(r"[ぁ-ん]", answer)  # a Japanese explanation, not a restatement of code
    if kit.epsilon_delta:
        assert "\\varepsilon" in answer and "\\delta" in answer
        assert "\\delta=\\dfrac{\\varepsilon}{|" in answer and "|+1}" in answer
    else:
        assert kit.tag in ("induction_product_rule", "difference_quotient", "sign_cases")
    for variant in card["question_variants"]["ja"]:
        assert re.search(r"[ぁ-んァ-ヶ一-龥]", variant)


def _check_epsilon_delta(
    coefficient: Fraction, intercept: Fraction, point: Fraction, epsilon: Fraction
) -> int:
    """The answer's delta works for the pointwise and the uniform claim alike: the inequality only
    involves the two points x0 and y with |x0 - y| < delta, and delta never mentions either."""
    delta = epsilon / (abs(coefficient) + 1)
    assert delta > 0
    checked = 0
    for t in (Fraction(-99, 100), Fraction(-1, 2), Fraction(0), Fraction(1, 3), Fraction(99, 100)):
        y = point + t * delta
        assert abs(y - point) < delta
        assert abs((coefficient * y + intercept) - (coefficient * point + intercept)) < epsilon
        checked += 1
    return checked


@pytest.mark.parametrize("name", [k.directory for k in KITS if k.epsilon_delta])
def test_the_stated_delta_satisfies_the_epsilon_delta_claim_in_exact_arithmetic(name: str) -> None:
    rng = random.Random(11)
    affine = name.startswith("affine")
    checked = 0
    for _ in range(3000):
        coefficient = Fraction(
            rng.choice([0, 0, 1, -1, 2, 3, -7, 50, 1000]) + rng.randint(-9, 9), rng.randint(1, 9)
        )
        intercept = Fraction(rng.randint(-40, 40), rng.randint(1, 9)) if affine else Fraction(0)
        point = Fraction(rng.randint(-60, 60), rng.randint(1, 9))
        epsilon = Fraction(rng.randint(1, 50), rng.randint(1, 50))
        checked += _check_epsilon_delta(coefficient, intercept, point, epsilon)
    assert checked == 15000


def test_the_plus_one_in_the_denominator_is_needed_and_the_slope_matters() -> None:
    # delta = epsilon / |c| is undefined for the zero function, which the statement includes.
    with pytest.raises(ZeroDivisionError):
        Fraction(1, 2) / abs(Fraction(0))
    # A delta that ignores the coefficient fails as soon as |c| > 1.
    c, a, epsilon = Fraction(10), Fraction(1), Fraction(1, 5)
    x = a + epsilon * Fraction(99, 100)  # |x - a| < delta = epsilon would be accepted
    assert abs(c * x - c * a) >= epsilon
    # Uniform continuity of x^2 is false, which is why there is no such kit:
    # a delta fixed in advance fails far from the origin.
    delta = Fraction(1, 10**6)
    far = Fraction(10**9)
    assert abs((far + delta / 2) ** 2 - far**2) >= 1


@pytest.mark.parametrize(
    "name", ["linear-differentiability-recipe-v1", "affine-differentiability-recipe-v1"]
)
def test_the_difference_quotient_is_the_constant_slope_and_the_remainder_vanishes(
    name: str,
) -> None:
    rng = random.Random(5)
    affine = name.startswith("affine")
    for _ in range(2000):
        slope = Fraction(rng.randint(-30, 30), rng.randint(1, 9))
        intercept = Fraction(rng.randint(-30, 30), rng.randint(1, 9)) if affine else Fraction(0)
        point = Fraction(rng.randint(-60, 60), rng.randint(1, 9))
        x = point + Fraction(rng.choice([-1, 1]) * rng.randint(1, 100), rng.randint(1, 10**6))
        assert x != point
        f = slope * x + intercept
        g = slope * point + intercept
        assert (f - g) / (x - point) == slope
        assert f - g - (x - point) * slope == 0
    # The absolute value is the contrasting example: its quotient at 0 is not constant.
    h = Fraction(1, 7)
    assert (abs(h) - abs(Fraction(0))) / h != (abs(-h) - abs(Fraction(0))) / -h


def test_power_differentiability_induction_step_and_derivative_note() -> None:
    rng = random.Random(3)
    for _ in range(500):
        k = rng.randint(0, 8)
        x = Fraction(rng.randint(-20, 20), rng.randint(1, 7))
        assert x ** (k + 1) == (x**k) * x  # the factorisation used in the induction step
    # The closing remark of the answer: the derivative of x^n is n a^(n-1) for n >= 1.
    h = Fraction(1, 10**6)
    for n in range(1, 8):
        for a in (Fraction(-3), Fraction(-1, 2), Fraction(2), Fraction(5, 3)):
            quotient = ((a + h) ** n - a**n) / h
            assert abs(quotient - n * a ** (n - 1)) < Fraction(1, 100)


def test_odd_powers_are_strictly_increasing_by_the_three_cases_and_even_powers_are_not() -> None:
    rng = random.Random(9)
    for _ in range(4000):
        n = rng.randint(0, 6)
        m = 2 * n + 1
        x = Fraction(rng.randint(-40, 40), rng.randint(1, 9))
        y = x + Fraction(rng.randint(1, 40), rng.randint(1, 9))
        assert x < y and x**m < y**m
        if x >= 0:  # case 1: the factorisation of y^m - x^m
            assert y**m - x**m == (y - x) * sum(y ** (m - 1 - i) * x**i for i in range(m))
            assert sum(y ** (m - 1 - i) * x**i for i in range(m)) > 0
        elif y <= 0:  # case 2: reflection and (-t)^m = -t^m
            assert (-y) ** m < (-x) ** m and (-y) ** m == -(y**m) and (-x) ** m == -(x**m)
        else:  # case 3: x < 0 < y
            assert x**m < 0 < y**m
    # Counterexamples: the claim fails for every even exponent, and for x^0.
    assert (-2) ** 2 > (-1) ** 2 and Fraction(-2) < Fraction(-1)
    assert Fraction(1) ** 0 == Fraction(2) ** 0


def test_continuity_requests_still_prefer_the_power_epsilon_delta_recipe() -> None:
    """The new kits sit next to the stored power Recipes without hijacking `x² の連続性`."""
    induction = dict(POWER, recipe_id="requested.natural_power_continuous", proof_method_tag=None)
    delta = dict(
        POWER,
        recipe_id="continuity.power.natural.explicit-epsilon-delta",
        proof_method_tag="epsilon_delta",
    )
    newcomers = [
        dict(POWER, recipe_id=k.recipe_id, proof_method_tag=k.tag, target_source=k.target)
        for k in KITS
    ]
    proposal = deterministic_instance_proposal(
        "x² の連続性を説明して", newcomers + [induction, delta]
    )
    assert proposal is not None and proposal["instance_recipe_id"] == delta["recipe_id"]


def _lean_available() -> bool:
    return (
        os.environ.get("PALS_GENERAL_RECIPE_LEAN") == "1"
        and PINNED.exists()
        and mathlib_environment() is not None
    )


def _compile(source: str, directory: Path, name: str) -> tuple[int, str, float]:
    path = directory / f"{name}.lean"
    path.write_text(source, encoding="utf-8")
    started = time.monotonic()
    done = subprocess.run(
        [str(PINNED), str(path)],
        env=mathlib_environment(),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    return done.returncode, done.stdout + done.stderr, time.monotonic() - started


@pytest.mark.skipif(
    not _lean_available(),
    reason=(
        "opt-in: PALS_GENERAL_RECIPE_LEAN=1 with the pinned Lean 4.32.0-rc1 and a built Mathlib"
    ),
)
def test_real_lean_compiles_each_recipe_with_standard_axioms_its_instances_and_rejects_wrong_ones(
    kit: Kit, tmp_path: Path
) -> None:
    _, card, source, _ = _load(kit)
    code, output, elapsed = _compile(
        source + f"\n#print axioms {kit.theorem}\n", tmp_path, "recipe"
    )
    assert code == 0 and "error" not in output, output[-800:]
    observed = re.findall(r"depends on axioms: \[([^]]*)\]", output)
    assert len(observed) == 1
    assert {part.strip() for part in observed[0].split(",")} <= STANDARD_AXIOMS
    assert "sorry" not in output
    print(f"{kit.directory}: recipe + axioms {elapsed:.1f}s")
    for index, (request, hints) in enumerate(kit.instances):
        instance = elaborate(source, request, list(hints)).source
        code, output, _ = _compile(instance, tmp_path, f"instance{index}")
        assert code == 0 and "error" not in output, (request, output[-800:])
    # A false statement of the same shape is not proved by the stored proof body.
    wrong = source.replace(kit.target, kit.wrong_target, 1)
    assert wrong != source
    code, output, _ = _compile(wrong, tmp_path, "wrong_target")
    assert code != 0 and "error" in output
    # A proposition that is not an instance (or is false) fails to specialise.
    instance = elaborate(source, kit.wrong_request, []).source
    code, output, _ = _compile(instance, tmp_path, "wrong_request")
    assert code != 0 and "error" in output
