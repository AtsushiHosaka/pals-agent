"""Independent countermodels: False means unknown/no Q countermodel, never a proof."""

from __future__ import annotations

import pytest

from pals_agent.typed_matrix_counterexample import has_rational_counterexample
from pals_agent.typed_matrix_profile import canonicalize_typed_matrix_openmath_xml

PROFILE = "typed-math-matrix-v1"
TYPED = "urn:pals:openmath:typed-math:v1"
STANDARD = "http://www.openmath.org/cd"


def sym(cd, name, base=TYPED):
    return f'<OMS cdbase="{base}" cd="{cd}" name="{name}"/>'


def app(op, *args):
    return "<OMA>" + op + "".join(args) + "</OMA>"


def mat(op, *args):
    return app(sym("matrix1", op), *args)


def nat(n):
    return f"<OMI>{n}</OMI>"


def cast(n):
    return mat("field_nat_cast", '<OMV name="K"/>', nat(n))


def literal(rows):
    return mat(
        "literal",
        '<OMV name="K"/>',
        nat(len(rows)),
        nat(len(rows[0])),
        *(cast(n) for row in rows for n in row),
    )


def relation(left, right, name="eq"):
    return app(sym("relation1", name, STANDARD), left, right)


def declaration(name="K", sort=None):
    return (
        "<OMATTR><OMATP>"
        + sym("typed1", "type")
        + (sort or sym("algebra1", "Field"))
        + f'</OMATP><OMV name="{name}"/></OMATTR>'
    )


def document(body, *, binder="forall", extra=""):
    xml = (
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMBIND>'
        + sym("typed1", binder)
        + "<OMBVAR>"
        + declaration()
        + extra
        + "</OMBVAR>"
        + body
        + "</OMBIND></OMOBJ>"
    )
    return canonicalize_typed_matrix_openmath_xml(xml)


@pytest.mark.parametrize(
    "left,right",
    [
        (mat("add", literal([[2, 3]]), literal([[5, 7]])), literal([[8, 10]])),
        (mat("mul", literal([[2, 3]]), literal([[5], [7]])), literal([[30]])),
        (mat("transpose", literal([[2, 3]])), literal([[2], [4]])),
        (mat("scale", cast(3), literal([[2, 3]])), literal([[6, 10]])),
        (mat("rank", literal([[2, 1], [4, 2]])), nat(2)),
    ],
)
def test_fresh_closed_literal_falsehoods_have_exact_q_countermodels(left, right):
    assert has_rational_counterexample(PROFILE, document(relation(left, right))) is True


def test_characteristic_two_does_not_invalidate_a_rational_countermodel():
    # 2=0 holds in characteristic two, but the query quantifies over every field.
    assert has_rational_counterexample(PROFILE, document(relation(cast(2), cast(0)))) is True


def test_true_over_q_is_not_a_claim_of_universal_truth():
    # rank([2])=1 is true over Q and false over F2. This guard must not suppress it
    # on the strength of a Q-only check, nor report it verified.
    result = has_rational_counterexample(
        PROFILE, document(relation(mat("rank", literal([[2]])), nat(1)))
    )
    assert result is False


@pytest.mark.parametrize("binder", ["exists"])
def test_nonuniversal_field_binder_is_outside_countermodel_contract(binder):
    assert (
        has_rational_counterexample(PROFILE, document(relation(cast(2), cast(0)), binder=binder))
        is False
    )


def test_implication_does_not_drop_its_assumptions():
    premise = relation(cast(2), cast(0))
    consequence = relation(cast(4), cast(0))
    # Valid in every field: the premise is false over Q, so evaluating only the
    # conclusion would produce an unsound suppression.
    xml = document(app(sym("logic1", "implies", STANDARD), premise, consequence))
    assert has_rational_counterexample(PROFILE, xml) is False


def test_extra_variables_and_extra_field_binders_are_unknown():
    falsehood = relation(cast(1), cast(0))
    for extra in (
        declaration("L"),
        declaration("x", app(sym("typed1", "Elem"), '<OMV name="K"/>')),
    ):
        assert has_rational_counterexample(PROFILE, document(falsehood, extra=extra)) is False


def test_two_sided_inverse_evaluates_the_supplied_matrices():
    swap = literal([[0, 1], [1, 0]])
    wrong = literal([[1, 1], [1, 0]])
    assert has_rational_counterexample(PROFILE, document(mat("is_inverse", swap, swap))) is False
    assert has_rational_counterexample(PROFILE, document(mat("is_inverse", swap, wrong))) is True


def test_elimination_uses_exact_fractional_pivots_and_no_float_rounding():
    # A pivot of 2 leads to 1/2 during elimination; both determinant and rank
    # must retain it exactly.
    matrix = literal([[2, 1], [1, 1]])
    assert (
        has_rational_counterexample(
            PROFILE, document(relation(mat("determinant", matrix), cast(1)))
        )
        is False
    )
    assert (
        has_rational_counterexample(
            PROFILE, document(relation(mat("determinant", matrix), cast(0)))
        )
        is True
    )
    assert (
        has_rational_counterexample(PROFILE, document(relation(mat("rank", matrix), nat(2))))
        is False
    )
    n = 2**53
    large = literal([[n, n - 1], [n + 1, n]])  # determinant exactly 1
    assert (
        has_rational_counterexample(PROFILE, document(relation(mat("determinant", large), cast(1))))
        is False
    )


def test_unsupported_profile_and_malformed_or_unbound_tree_never_claim_countermodel():
    xml = document(relation(cast(1), cast(0)))
    assert has_rational_counterexample("generic-v1", xml) is False
    for invalid in ("<broken>", "<OMOBJ/>", xml.replace("matrix1", "unsupported1")):
        assert has_rational_counterexample(PROFILE, invalid) is False


def test_large_integer_cancellation_really_finds_a_counterexample_not_unknown():
    n = 2**53
    matrix = literal([[n, n - 1], [n + 1, n]])
    # Float arithmetic can erase the unit determinant. Exact Q finds det != 0.
    assert (
        has_rational_counterexample(
            PROFILE, document(relation(mat("determinant", matrix), cast(0)))
        )
        is True
    )


def test_neq_and_pivot_swap_sign_are_preserved():
    swap = literal([[0, 1], [1, 0]])
    assert (
        has_rational_counterexample(PROFILE, document(relation(mat("determinant", swap), cast(1))))
        is True
    )
    assert (
        has_rational_counterexample(
            PROFILE, document(relation(mat("rank", swap), nat(2), name="neq"))
        )
        is True
    )


def test_size_and_numeric_limits_leave_the_claim_undetermined():
    xml = document(relation(cast(1), cast(0)))
    assert has_rational_counterexample(PROFILE, xml + " " * 65536) is False
    huge = xml.replace("<n1:OMI>1</n1:OMI>", "<n1:OMI>" + "9" * 1001 + "</n1:OMI>")
    assert huge != xml
    assert has_rational_counterexample(PROFILE, huge) is False
