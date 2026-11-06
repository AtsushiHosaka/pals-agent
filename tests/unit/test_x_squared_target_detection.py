"""Which Lean statements and requests count as "the continuity of x²".

The epsilon-delta requirement (and the worker's pre-verification alignment check) follow the
verified Lean target; the wording of the request is a conservative fallback only.
"""

from __future__ import annotations

import pytest

from pals_agent.explanations import _is_x_squared_continuity, _requires_epsilon_delta
from pals_agent.lean_target import (
    extract_single_target_declaration,
    matches_x_squared_continuity,
    targets_another_property_of_a_function,
)
from pals_agent.worker import _verified_candidate_matches_statement


def theorem(proposition: str) -> str:
    return f"theorem t : {proposition} := by\n  sorry"


@pytest.mark.parametrize(
    "proposition",
    [
        "Continuous (fun x : ℝ => x ^ 2)",
        "Continuous fun x : ℝ => x ^ 2",
        "Continuous (fun (x : ℝ) => x ^ 2)",
        "Continuous (fun x : ℝ ↦ x ^ 2)",
        "Continuous (fun x : ℝ => (x ^ 2 : ℝ))",
        "Continuous (fun x : Real => x ^ 2)",
        "Continuous (fun (y : Real) => (y * y : ℝ))",
        "Continuous (fun x : ℝ => x * x)",
        "Continuous (fun x : ℝ => x ^ (2 : ℕ))",
        "Continuous (fun x : ℝ => x²)",
        "Continuous ((· ^ 2) : ℝ → ℝ)",
        "Continuous (· ^ 2 : ℝ → ℝ)",
        "Continuous (· * · : ℝ → ℝ)",
    ],
)
def test_the_square_function_is_recognised_in_its_usual_spellings(proposition: str) -> None:
    assert matches_x_squared_continuity(proposition)


@pytest.mark.parametrize(
    "proposition",
    [
        "Continuous (fun x : ℝ => x ^ 3)",
        "Continuous (fun x : ℝ => x ^ 2 + x)",
        "Continuous (fun x : ℝ => (x - 1) ^ 2)",
        "Continuous (fun x : ℝ => x ^ 2 ^ 2)",
        "Continuous (fun x : ℝ => x ^ 22)",
        "Continuous (fun x : ℝ => x ^ 2 * x)",
        "Continuous (fun x : ℝ => x * x * x)",
        "Continuous (fun x : ℝ => x * y)",
        "Continuous (fun x : ℝ => 2 ^ x)",
        "Continuous (fun x : ℝ => x ^ (2 : ℝ))",
        "Continuous (fun x : ℝ => Real.sqrt x ^ 2)",
        "Continuous (fun x : ℕ => x ^ 2)",
        "ContinuousAt (fun x : ℝ => x ^ 2) 0",
        "Continuous (fun x : ℝ => x ^ 2) ∧ Continuous (fun x : ℝ => x)",
        "Continuous (fun (x : ℝ) (y : ℝ) => x ^ 2)",
        # An untyped function elaborates over a default type, not necessarily ℝ.
        "Continuous (fun x => x ^ 2)",
        "Continuous (· ^ 2)",
    ],
)
def test_other_statements_are_not_the_square_function(proposition: str) -> None:
    assert not matches_x_squared_continuity(proposition)


@pytest.mark.parametrize(
    ("proposition", "expected"),
    [
        ("Continuous (deriv fun x : ℝ => x ^ 2)", True),
        ("Differentiable ℝ (fun x : ℝ => x ^ 2)", True),
        ("HasDerivAt (fun x : ℝ => x ^ 2) (2 * a) a", True),
        ("UniformContinuous (fun x : ℝ => x ^ 2)", True),
        ("Continuous (fun x : ℝ => x ^ 2)", False),
        ("ContinuousAt (fun x : ℝ => x ^ 2) 0", False),
    ],
)
def test_derivative_and_uniform_targets_are_another_property(
    proposition: str, expected: bool
) -> None:
    assert targets_another_property_of_a_function(proposition) is expected


# --- the epsilon-delta requirement follows the Lean target -------------------------------


@pytest.mark.parametrize(
    "request_text",
    [
        "Why is x^2 continuous?",
        "x のニ乗は連続ですか",
        "Show that the square function is continuous",
    ],
)
def test_a_readable_square_target_requires_epsilon_delta_in_any_language(
    request_text: str,
) -> None:
    assert _requires_epsilon_delta(request_text, theorem("Continuous (fun x : ℝ => x ^ 2)"))


@pytest.mark.parametrize(
    "lean",
    [
        theorem("Continuous (fun x : ℝ => x)"),
        theorem("Continuous (deriv fun x : ℝ => x ^ 2)"),
        theorem("UniformContinuous (fun x : ℝ => x ^ 2)"),
    ],
)
def test_a_readable_target_that_does_not_match_never_falls_back_to_the_wording(
    lean: str,
) -> None:
    assert extract_single_target_declaration(lean) is not None
    assert not _requires_epsilon_delta("x² の連続性を説明してください", lean)


HELPER_AND_THEOREM = (
    "lemma helper : True := trivial\n"
    "theorem t : Continuous (fun x : ℝ => x ^ 2) := by\n  continuity"
)


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        ("x² が連続であることを説明してください", True),
        ("x^2 は連続？", True),
        ("x^2 と x^3 の連続性", False),
        ("連続関数 x²+1 の連続性", False),
        ("x² の導関数は連続か", False),
        ("x^2 は一様連続でない", False),
        ("x^2 は連続で、x^2 は微分可能", False),
        ("x² が連続かつ有界であることと、sin x が連続であること", False),
        ("x^2 は連続？ 連続の定義も教えて", False),
        ("n + 0 = n を示せ", False),
    ],
)
def test_the_wording_fallback_is_conservative_when_the_target_is_not_one_declaration(
    request_text: str, expected: bool
) -> None:
    assert extract_single_target_declaration(HELPER_AND_THEOREM) is None
    assert _requires_epsilon_delta(request_text, HELPER_AND_THEOREM) is expected
    assert _is_x_squared_continuity(request_text) is expected


# --- the worker alignment check reads the Lean target, not only the request --------------

SQUARE = theorem("Continuous (fun x : ℝ => x ^ 2)")
IDENTITY = theorem("Continuous (fun x : ℝ => x)")
DERIVATIVE = theorem("Continuous (deriv fun x : ℝ => x ^ 2)")
UNIFORM = theorem("UniformContinuous (fun x : ℝ => x ^ 2)")


@pytest.mark.parametrize(
    ("request_text", "lean", "expected"),
    [
        ("x² の連続性を微分を使わずに示して", SQUARE, True),
        ("x² の連続性を微分を使わずに示して", IDENTITY, False),
        ("prove that x^2 is continuous without using derivatives", IDENTITY, True),  # no 連続
        ("x² が連続であることを示せ", IDENTITY, False),
        ("x² の導関数は連続か", DERIVATIVE, True),
        ("x² の導関数は連続か", IDENTITY, False),
        ("x^2 は一様連続でない", UNIFORM, True),
        ("x^2 は一様連続でない", IDENTITY, False),
        ("x² が連続であることを示せ", DERIVATIVE, False),
        ("x² が連続であることを示せ", UNIFORM, False),
        ("n + 0 = n を示せ", IDENTITY, True),
    ],
)
def test_alignment_follows_the_lean_target_not_the_wording(
    request_text: str, lean: str, expected: bool
) -> None:
    assert _verified_candidate_matches_statement(request_text, lean) is expected
