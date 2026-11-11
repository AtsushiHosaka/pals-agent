"""Safe normalisations (pure Python): recover refused statements without loosening the grammar."""

import pytest

from pals_agent import statement_normalise as N
from pals_agent.statement_grammar import StatementRejected, validate_proposition


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("∀ (n : ℕ) (λ : Fin n → ℝ), λ 0 = λ 0", "∀ (n : ℕ) (lam : Fin n → ℝ), lam 0 = lam 0"),
        ("∀ x : ℝ, x = x", "∀ x : ℝ, x = x"),
    ],
)
def test_a_keyword_used_as_a_variable_is_renamed(text, expected):
    assert N.rename_reserved_variable(text) == expected
    validate_proposition(expected)


@pytest.mark.parametrize(
    "text",
    [
        "∀ f : ℕ → ℕ, f = λ x => x",  # a real lambda: renaming would change the meaning
        "∀ f : ℕ → ℕ, f = λ x ↦ x",
        "∀ (lam λ : ℕ), lam = λ",  # the new name is already in use
    ],
)
def test_renaming_is_refused_when_it_could_change_the_meaning(text):
    assert N.rename_reserved_variable(text) is None


def test_a_let_chain_is_hoisted_by_substitution_and_then_passes_the_grammar():
    text = "∀ (b : ℕ), let p := b + 1; let q := p * 2; p ≠ 0 ∧ q.succ ≠ 0 ∧ p.succ = q"
    hoisted = N.hoist_lets(text)
    assert (
        hoisted == "∀ (b : ℕ), (b + 1) ≠ 0 ∧ ((b + 1) * 2).succ ≠ 0 ∧ (b + 1).succ = ((b + 1) * 2)"
    )
    with pytest.raises(StatementRejected):
        validate_proposition(text)
    validate_proposition(hoisted)


@pytest.mark.parametrize(
    "text",
    [
        "∀ n : ℕ, let p := n + 1 p = p",  # no ';': not a recognised shape
        "∀ n : ℕ, let p := n + 1; ∀ p : ℕ, p = p",  # the name is rebound inside the body
        "∀ n : ℕ, let p := (n; p = p",
    ],
)
def test_unrecognised_or_capturing_shapes_are_not_hoisted(text):
    assert N.hoist_lets(text) is None


def test_the_equivalence_check_is_a_closed_iff_rfl():
    source = N.equivalence_source("let p := 1; p = 1", "(1) = 1")
    assert "theorem _pals_hoist : (let p := 1; p = 1) ↔ ((1) = 1) := Iff.rfl" in source
    assert "autoImplicit false" in source
