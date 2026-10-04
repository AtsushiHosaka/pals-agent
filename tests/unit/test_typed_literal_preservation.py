"""Real validated XML and non-corpus literals; no provider or database calls."""

from copy import deepcopy

import pytest

from pals_agent.typed_literal_preservation import (
    LiteralPreservationError,
    validate_literal_preservation,
)
from tests.unit.test_typed_profile_guidance import Grammar, n, v

PROFILE = "typed-math-matrix-v1"


def xml_for(*matrices, constructor=None):
    grammar = Grammar(PROFILE)
    expressions = []
    for matrix in matrices:
        rows, columns = len(matrix), len(matrix[0])
        entries = [
            grammar.app("field_nat_cast", v("K"), n(value)) for row in matrix for value in row
        ]
        literal = (
            grammar.app(constructor, v("K"), n(rows), n(columns))
            if constructor == "zero"
            else grammar.app("identity", v("K"), n(rows))
            if constructor == "identity"
            else grammar.app("literal", v("K"), n(rows), n(columns), *entries)
        )
        expressions.append(grammar.app("eq", literal, deepcopy(literal)))
    body = expressions[0] if len(expressions) == 1 else grammar.app("and", *expressions)
    document = grammar.document(grammar.bind([("K", grammar.symbol("Field"))], body))
    return grammar.spec.validate_canonical(grammar.spec.canonicalize(document))


def check(statement, xml):
    return validate_literal_preservation(PROFILE, statement, xml)


@pytest.mark.parametrize("constructor", ["zero", "identity"])
def test_zero_or_identity_cannot_replace_explicit_entries(constructor):
    with pytest.raises(LiteralPreservationError):
        check(
            "The matrix [[7, 8], [9, 10]] equals itself.",
            xml_for([[7, 8], [9, 10]], constructor=constructor),
        )


@pytest.mark.parametrize(
    "wrong",
    [
        [[7, 8], [9, 11]],  # Changed one value.
        [[8, 7], [9, 10]],  # Changed row-major order.
        [[7, 8, 9, 10]],  # Same values but changed shape.
    ],
)
def test_changed_value_order_or_shape_is_rejected(wrong):
    with pytest.raises(LiteralPreservationError):
        check("Use [[7,8],[9,10]].", xml_for(wrong))


def test_extra_or_missing_literal_is_rejected():
    a, b = [[11], [13]], [[17], [19]]
    with pytest.raises(LiteralPreservationError):
        check("Use [[11],[13]] and [[17],[19]].", xml_for(a))
    with pytest.raises(LiteralPreservationError):
        check("Use [[11],[13]].", xml_for(a, b))


def test_repeated_self_inverse_does_not_require_duplicate_source_mentions():
    # Multiplicity is deliberately not a semantic claim of this guard.
    a = [[0, 1], [1, 0]]
    assert check("[[0,1],[1,0]] is a two-sided inverse of itself.", xml_for(a, a)) is None
    assert check("[[0,1],[1,0]] and [[0,1],[1,0]].", xml_for(a)) is None


@pytest.mark.parametrize("rows, columns", [(1, 1), (1, 8), (8, 1), (3, 5), (8, 8)])
def test_rectangular_shapes_preserve_whitespace_and_explicit_positive_sign(rows, columns):
    matrix = [[11 + r * columns + c for c in range(columns)] for r in range(rows)]
    source = (
        "[\n" + ",\n".join("[ " + ", ".join(f"+{v}" for v in row) + " ]" for row in matrix) + "\n]"
    )
    assert check(source, xml_for(matrix)) is None


@pytest.mark.parametrize("source", ["[[-7,8]]", "[[-0,8]]", "[[7,-8]]"])
def test_negative_integer_is_never_absolute_valued_or_silently_coerced(source):
    with pytest.raises(LiteralPreservationError):
        check(source, xml_for([[7, 8]]))


@pytest.mark.parametrize(
    "source",
    [
        "[[7.5,8]]",
        "[[7/2,8]]",
        "[[1e3,8]]",
        "[[x,8]]",
        "[[７,8]]",
        "[[7,8], [9.5,10]]",
        "[[7,8]], plus [[1/2,3]]",
        "[[7,8], [9,10]",
    ],
)
def test_unsupported_source_is_not_partially_matched_and_claims_nothing(source):
    # XML is deliberately irrelevant: unsupported source returns without parsing it.
    assert check(source, "not XML") is None


@pytest.mark.parametrize(
    "source",
    [
        "[[1,2],[3]]",
        "[" + ",".join("[1]" for _ in range(9)) + "]",
        "[[" + ",".join("1" for _ in range(9)) + "]]",
        "[[" + "1" * 129 + "]]",
    ],
)
def test_recognized_integer_matrices_enforce_resource_shape_bounds(source):
    with pytest.raises(LiteralPreservationError):
        check(source, xml_for([[1]]))


def test_bound_value_is_exact_and_fullvalidator_remains_required():
    value = int("1" * 128)
    assert check(f"[[{value}]]", xml_for([[value]])) is None
    with pytest.raises(LiteralPreservationError):
        check("[[7]]", "<bad>")
    with pytest.raises(LiteralPreservationError):
        check("[[7]]", "<!DOCTYPE hidden><x/>")


def test_safe_exception_does_not_include_statement_or_xml():
    with pytest.raises(LiteralPreservationError) as caught:
        check("private secret [[7]]", xml_for([[8]]))
    assert str(caught.value) == "Explicit matrix literal values or dimensions were not preserved"


def test_other_profiles_and_no_explicit_matrix_are_unaffected():
    assert validate_literal_preservation("typed-math-v1", "[[-7]]", "not XML") is None
    assert check("The identity matrix has full rank.", "not XML") is None


def test_false_claim_is_not_repaired_by_guard():
    # Presence/value preservation never claims that an asserted proposition is true.
    a, wrong = [[7, 8]], [[99, 100]]
    assert check("Twice [[7,8]] equals [[99,100]].", xml_for(a, wrong)) is None
