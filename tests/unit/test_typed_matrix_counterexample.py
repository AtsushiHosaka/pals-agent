"""Exact counterexamples on independent closed matrix expressions, never model calls."""

from copy import deepcopy

import pytest

from pals_agent import typed_matrix_counterexample as counterexample
from tests.unit.test_typed_profile_guidance import Grammar, n, v

PROFILE = "typed-math-matrix-v1"


class Terms:
    def __init__(self):
        self.g = Grammar(PROFILE)

    def cast(self, value):
        return self.g.app("field_nat_cast", v("K"), n(value))

    def matrix(self, rows):
        return self.g.app(
            "literal",
            v("K"),
            n(len(rows)),
            n(len(rows[0])),
            *(self.cast(value) for row in rows for value in row),
        )

    def identity(self, size=2):
        return self.g.app("identity", v("K"), n(size))

    def zero(self, rows=2, columns=2):
        return self.g.app("zero", v("K"), n(rows), n(columns))

    def canonical(self, body, *, binder="forall", declarations=None):
        root = self.g.bind(declarations or [("K", self.g.symbol("Field"))], body, name=binder)
        return self.g.spec.validate_canonical(self.g.spec.canonicalize(self.g.document(root)))

    def check(self, body, **kwargs):
        return counterexample.has_rational_counterexample(PROFILE, self.canonical(body, **kwargs))


@pytest.mark.parametrize("operation", ["add", "mul", "scale", "transpose", "neg"])
def test_correct_and_incorrect_closed_arithmetic(operation):
    t = Terms()
    a, b = t.matrix([[2, 5], [7, 11]]), t.matrix([[3, 1], [4, 2]])
    if operation == "add":
        expression, expected = t.g.app("add", a, b), t.matrix([[5, 6], [11, 13]])
    elif operation == "mul":
        expression, expected = t.g.app("mul", a, b), t.matrix([[26, 12], [65, 29]])
    elif operation == "scale":
        expression, expected = t.g.app("scale", t.cast(7), a), t.matrix([[14, 35], [49, 77]])
    elif operation == "transpose":
        expression, expected = t.g.app("transpose", a), t.matrix([[2, 7], [5, 11]])
    else:
        expression = t.g.app("add", a, t.g.app("neg", deepcopy(a)))
        expected = t.zero()
    assert not t.check(t.g.app("eq", deepcopy(expression), expected))
    assert t.check(t.g.app("eq", expression, t.matrix([[13, 17], [19, 23]])))


def test_rectangular_product_and_natural_rank_are_exact():
    t = Terms()
    a = t.matrix([[2, 3, 5], [7, 11, 13]])
    b = t.matrix([[1], [2], [3]])
    assert not t.check(t.g.app("eq", t.g.app("mul", a, b), t.matrix([[23], [68]])))
    assert not t.check(t.g.app("eq", t.g.app("rank", t.matrix([[2, 3], [1, 2]])), n(2)))
    assert t.check(t.g.app("eq", t.g.app("rank", t.matrix([[2, 3], [1, 2]])), n(1)))
    assert not t.check(t.g.app("eq", t.g.app("rank", t.matrix([[2, 3], [4, 6]])), n(1)))
    assert not t.check(t.g.app("eq", t.g.app("rank", t.zero(3, 5)), n(0)))


def test_determinant_fraction_pivot_row_swap_and_negative_result():
    t = Terms()
    # Eliminating the second row requires factor 1/2, not truncating integer division.
    assert not t.check(t.g.app("eq", t.g.app("determinant", t.matrix([[2, 3], [1, 2]])), t.cast(1)))
    a = t.matrix([[0, 3], [2, 5]])
    minus_six = t.g.app("determinant", t.g.app("neg", t.g.app("scale", t.cast(6), t.identity(1))))
    assert not t.check(t.g.app("eq", t.g.app("determinant", deepcopy(a)), minus_six))
    assert t.check(t.g.app("eq", t.g.app("determinant", a), t.cast(6)))
    assert not t.check(t.g.app("eq", t.g.app("determinant", t.matrix([[2, 3], [4, 6]])), t.cast(0)))


def test_two_sided_inverse_uses_both_products_and_preserves_witness():
    t = Terms()
    a = t.matrix([[1, 3], [0, 1]])
    inverse = t.g.app("add", t.g.app("scale", t.cast(2), t.identity()), t.g.app("neg", deepcopy(a)))
    assert not t.check(t.g.app("is_inverse", deepcopy(a), inverse))
    assert t.check(t.g.app("is_inverse", a, t.identity()))


def test_true_over_q_is_not_certified_over_other_fields():
    t = Terms()
    # This is true over Q but false in characteristic two. False means NO CLAIM.
    assert not t.check(t.g.app("eq", t.g.app("rank", t.matrix([[2]])), n(1)))
    assert t.check(t.g.app("neq", t.identity(), t.identity()))
    assert not t.check(t.g.app("neq", t.identity(), t.zero()))


@pytest.mark.parametrize(
    "unsupported", ["exists", "assumption", "extra_field", "element", "nested", "proposition_eq"]
)
def test_no_refutation_for_out_of_scope_quantifiers_or_hypotheses(unsupported):
    t = Terms()
    false = t.g.app("eq", t.identity(), t.zero())
    if unsupported == "exists":
        assert not t.check(false, binder="exists")
    elif unsupported == "assumption":
        assert not t.check(t.g.app("implies", deepcopy(false), false))
    elif unsupported == "extra_field":
        assert not t.check(
            false, declarations=[("K", t.g.symbol("Field")), ("L", t.g.symbol("Field"))]
        )
    elif unsupported == "element":
        assert not t.check(
            false, declarations=[("K", t.g.symbol("Field")), ("x", t.g.app("Elem", v("K")))]
        )
    elif unsupported == "nested":
        assert not t.check(t.g.bind([("L", t.g.symbol("Field"))], false))
    else:
        predicate = t.g.app("is_inverse", t.identity(), t.identity())
        assert not t.check(t.g.app("eq", predicate, deepcopy(predicate)))


def test_carrier_and_full_symbol_identity_are_checked_independently():
    t = Terms()
    valid = t.canonical(t.g.app("eq", t.identity(), t.zero()))
    assert counterexample.has_rational_counterexample(PROFILE, valid)
    assert not counterexample.has_rational_counterexample(
        PROFILE, valid.replace('name="v1"', 'name="unbound"', 1)
    )
    assert not counterexample.has_rational_counterexample(
        PROFILE, valid.replace('cd="matrix1"', 'cd="foreign"')
    )
    assert not counterexample.has_rational_counterexample(
        PROFILE, valid.replace('name="forall"', 'name="exists"')
    )
    assert not counterexample.has_rational_counterexample("typed-math-v1", valid)
    # A fixed carrier/free field has no universal Field declaration.
    assert not counterexample.has_rational_counterexample(
        PROFILE, t.g.document(t.g.app("eq", t.identity(), t.zero()))
    )


@pytest.mark.parametrize("limit", ["_MAX_BYTES", "_MAX_NODES", "_MAX_DEPTH", "_MAX_OPERATIONS"])
def test_budget_exhaustion_never_becomes_counterexample(monkeypatch, limit):
    t = Terms()
    valid = t.canonical(t.g.app("eq", t.identity(), t.zero()))
    monkeypatch.setattr(counterexample, limit, 1)
    assert not counterexample.has_rational_counterexample(PROFILE, valid)


def test_arithmetic_bit_bound_and_input_digit_bound_are_unknown(monkeypatch):
    t = Terms()
    expression = t.g.app("mul", t.matrix([[200]]), t.matrix([[200]]))
    valid = t.canonical(t.g.app("eq", expression, t.matrix([[1]])))
    monkeypatch.setattr(counterexample, "_MAX_BITS", 8)
    assert not counterexample.has_rational_counterexample(PROFILE, valid)
    monkeypatch.setattr(counterexample, "_MAX_BITS", 4096)
    oversized = t.canonical(t.g.app("eq", t.matrix([[int("1" * 1001)]]), t.matrix([[1]])))
    assert not counterexample.has_rational_counterexample(PROFILE, oversized)


@pytest.mark.parametrize("raw", ["not xml", "<!DOCTYPE x><x/>", "\ud800", "<OMOBJ/>"])
def test_invalid_input_makes_no_refutation_claim(raw):
    assert not counterexample.has_rational_counterexample(PROFILE, raw)
