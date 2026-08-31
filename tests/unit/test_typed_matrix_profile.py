from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from pals_agent.openmath import MathXMLValidationError, canonicalize_retrieval_openmath_xml
from pals_agent.typed_math import validate_typed_math_openmath_xml
from pals_agent.typed_matrix_profile import (
    TYPED_MATRIX_PROFILE,
    canonicalize_typed_matrix_openmath_xml,
    validate_canonical_typed_matrix_openmath_xml,
    validate_typed_matrix_openmath_xml,
)

OPENMATH = "http://www.openmath.org/OpenMath"
TYPED = "urn:pals:openmath:typed-math:v1"
STANDARD = "http://www.openmath.org/cd"


def _typed_oms(cd: str, name: str) -> str:
    return f'<OMS cdbase="{TYPED}" cd="{cd}" name="{name}"/>'


def _standard_oms(cd: str, name: str) -> str:
    return f'<OMS cdbase="{STANDARD}" cd="{cd}" name="{name}"/>'


def _app(operator: str, *arguments: str) -> str:
    return f"<OMA>{operator}{''.join(arguments)}</OMA>"


def _matrix(name: str, *arguments: str) -> str:
    return _app(_typed_oms("matrix1", name), *arguments)


def _field_sort() -> str:
    return _typed_oms("algebra1", "Field")


def _element_sort(carrier: str) -> str:
    return _app(_typed_oms("typed1", "Elem"), f'<OMV name="{carrier}"/>')


def _matrix_sort(carrier: str, rows: int, columns: int) -> str:
    return _matrix(
        "Matrix",
        f'<OMV name="{carrier}"/>',
        f"<OMI>{rows}</OMI>",
        f"<OMI>{columns}</OMI>",
    )


def _vector_sort(carrier: str, rows: int) -> str:
    return _matrix("ColumnVector", f'<OMV name="{carrier}"/>', f"<OMI>{rows}</OMI>")


def _declaration(name: str, sort: str) -> str:
    return (
        f"<OMATTR><OMATP>{_typed_oms('typed1', 'type')}{sort}</OMATP>"
        f'<OMV name="{name}"/></OMATTR>'
    )


def _binding(declarations: str, body: str) -> str:
    return (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>'
        f"{_typed_oms('typed1', 'forall')}<OMBVAR>{declarations}</OMBVAR>{body}"
        "</OMBIND></OMOBJ>"
    )


def _eq(left: str, right: str) -> str:
    return _app(_standard_oms("relation1", "eq"), left, right)


def _field_nat(carrier: str, value: int) -> str:
    return _matrix("field_nat_cast", f'<OMV name="{carrier}"/>', f"<OMI>{value}</OMI>")


def _literal(carrier: str, rows: int, columns: int, entries: list[int]) -> str:
    return _matrix(
        "literal",
        f'<OMV name="{carrier}"/>',
        f"<OMI>{rows}</OMI>",
        f"<OMI>{columns}</OMI>",
        *[_field_nat(carrier, entry) for entry in entries],
    )


def _column_literal(carrier: str, rows: int, entries: list[int]) -> str:
    return _matrix(
        "column_literal",
        f'<OMV name="{carrier}"/>',
        f"<OMI>{rows}</OMI>",
        *[_field_nat(carrier, entry) for entry in entries],
    )


def _field_matrix_declarations(*declarations: str) -> str:
    return _declaration("K", _field_sort()) + "".join(declarations)


def _matrix_profile_manifest() -> dict[str, object]:
    path = (
        Path(__file__).resolve().parents[3]
        / "docs/typed-math-matrix-v1-authoring-manifest.proposal.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def test_matrix_profile_constant_and_manifest_cards_canonicalize_exactly() -> None:
    manifest = _matrix_profile_manifest()

    profile = manifest["profile"]
    assert isinstance(profile, dict)
    assert profile["id"] == TYPED_MATRIX_PROFILE
    content_dictionary_bundle = profile["content_dictionary_bundle"]
    assert isinstance(content_dictionary_bundle, dict)
    registry_relative_path = (
        "pals-agent/pals_agent/content_dictionaries/typed-math-matrix-v1-registry.json"
    )
    registry_path = (
        Path(__file__).resolve().parents[2]
        / "pals_agent/content_dictionaries/typed-math-matrix-v1-registry.json"
    )
    assert content_dictionary_bundle == {
        "relative_path": registry_relative_path,
        "sha256": "sha256:" + hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        "digest_input": "exact UTF-8 bytes of the named registry/CD bundle",
    }
    signature_contract = profile["signature_contract"]
    assert isinstance(signature_contract, dict)
    symbols = signature_contract["symbols"]
    assert isinstance(symbols, dict)
    assert set(symbols) == {
        "matrix1:field_nat_cast",
        "matrix1:literal",
        "matrix1:column_literal",
        "matrix1:zero",
        "matrix1:identity",
        "matrix1:add",
        "matrix1:neg",
        "matrix1:scale",
        "matrix1:mul",
        "matrix1:transpose",
        "matrix1:determinant",
        "matrix1:rank",
        "matrix1:is_inverse",
        "matrix1:mul_vec",
    }
    cards = manifest["admitted_candidate_cards"]
    assert isinstance(cards, list)
    assert len(cards) == 6
    for card in cards:
        assert isinstance(card, dict)
        canonical = canonicalize_typed_matrix_openmath_xml(card["openmath_xml"])
        assert canonical == card["canonical_openmath_xml"]
        assert "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest() == card[
            "canonical_openmath_xml_sha256"
        ]
        assert validate_canonical_typed_matrix_openmath_xml(canonical) == canonical


def test_matrix_profile_accepts_matrix_and_vector_shape_operations() -> None:
    declarations = _field_matrix_declarations(
        _declaration("A", _matrix_sort("K", 2, 3)),
        _declaration("B", _matrix_sort("K", 3, 2)),
        _declaration("v", _vector_sort("K", 3)),
    )
    product = _matrix("mul", '<OMV name="A"/>', '<OMV name="B"/>')
    matrix_zero = _matrix("zero", '<OMV name="K"/>', "<OMI>2</OMI>", "<OMI>2</OMI>")
    vector_product = _matrix("mul_vec", '<OMV name="A"/>', '<OMV name="v"/>')
    vector_literal = _column_literal("K", 2, [0, 0])
    matrix_literal = _literal("K", 2, 2, [0, 0, 0, 0])
    expressions = (
        _eq(product, matrix_zero),
        _eq(vector_product, vector_literal),
        _eq(_matrix("neg", matrix_literal), matrix_literal),
        _eq(
            _matrix(
                "determinant",
                _matrix("identity", '<OMV name="K"/>', "<OMI>2</OMI>"),
            ),
            _field_nat("K", 1),
        ),
        _matrix(
            "is_inverse",
            _matrix("identity", '<OMV name="K"/>', "<OMI>2</OMI>"),
            _matrix("identity", '<OMV name="K"/>', "<OMI>2</OMI>"),
        ),
    )

    for expression in expressions:
        validate_typed_matrix_openmath_xml(_binding(declarations, expression))


def test_matrix_profile_rejects_profile_confusion_and_inherited_typed_cdbase() -> None:
    cards = _matrix_profile_manifest()["admitted_candidate_cards"]
    assert isinstance(cards, list) and cards
    assert isinstance(cards[0], dict)
    matrix_xml = cards[0]["openmath_xml"]
    assert isinstance(matrix_xml, str)
    no_matrix = _binding(
        _declaration("K", _field_sort()),
        _eq('<OMV name="K"/>', '<OMV name="K"/>'),
    )
    inherited = matrix_xml.replace(f' cdbase="{TYPED}"', "")
    inherited = inherited.replace(
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0">',
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0" cdbase="{TYPED}">',
    )
    inherited = inherited.replace(
        '<OMS cdbase="http://www.openmath.org/cd" cd="relation1"',
        '<OMS cdbase="http://www.openmath.org/cd" cd="relation1"',
    )

    with pytest.raises(MathXMLValidationError, match="not a typed-math-matrix-v1"):
        validate_typed_matrix_openmath_xml(no_matrix)
    with pytest.raises(MathXMLValidationError, match="outside typed-math-v1"):
        validate_typed_math_openmath_xml(matrix_xml)
    with pytest.raises(MathXMLValidationError, match="Retrieval OMBVAR requires"):
        canonicalize_retrieval_openmath_xml(matrix_xml)
    with pytest.raises(MathXMLValidationError, match="directly declare its typed cdbase"):
        validate_typed_matrix_openmath_xml(inherited)


def test_matrix_profile_rejects_shape_mismatches_and_invalid_dimensions() -> None:
    declarations = _field_matrix_declarations(
        _declaration("A", _matrix_sort("K", 2, 3)),
        _declaration("B", _matrix_sort("K", 3, 2)),
        _declaration("C", _matrix_sort("K", 2, 2)),
        _declaration("v", _vector_sort("K", 3)),
        _declaration("w", _vector_sort("K", 2)),
    )
    bad_add = _binding(
        declarations,
        _eq(_matrix("add", '<OMV name="A"/>', '<OMV name="B"/>'), '<OMV name="A"/>'),
    )
    bad_mul = _binding(
        declarations,
        _eq(_matrix("mul", '<OMV name="A"/>', '<OMV name="C"/>'), '<OMV name="A"/>'),
    )
    bad_mul_vec = _binding(
        declarations,
        _eq(
            _matrix("mul_vec", '<OMV name="A"/>', '<OMV name="w"/>'),
            '<OMV name="w"/>',
        ),
    )
    bad_transpose = _binding(
        declarations,
        _eq(_matrix("transpose", '<OMV name="A"/>'), '<OMV name="A"/>'),
    )
    bad_rank = _binding(
        declarations,
        _eq(_matrix("rank", '<OMV name="A"/>'), _field_nat("K", 2)),
    )
    bad_dimension = _binding(
        _field_matrix_declarations(_declaration("A", _matrix_sort("K", 2, 3))),
        _eq(
            _matrix("zero", '<OMV name="K"/>', "<OMI>0</OMI>", "<OMI>2</OMI>"),
            '<OMV name="A"/>',
        ),
    )

    with pytest.raises(
        MathXMLValidationError,
        match=r"Argument 2.*Matrix\(K,2,3\).+Matrix\(K,3,2\)",
    ):
        validate_typed_matrix_openmath_xml(bad_add)
    with pytest.raises(
        MathXMLValidationError,
        match=r"Argument 2.*Matrix\(K,3,2\).+Matrix\(K,2,2\)",
    ):
        validate_typed_matrix_openmath_xml(bad_mul)
    with pytest.raises(
        MathXMLValidationError,
        match=r"Argument 2.*ColumnVector\(K,3\).+ColumnVector\(K,2\)",
    ):
        validate_typed_matrix_openmath_xml(bad_mul_vec)
    with pytest.raises(MathXMLValidationError, match=r"Matrix\(K,3,2\).+Matrix\(K,2,3\)"):
        validate_typed_matrix_openmath_xml(bad_transpose)
    with pytest.raises(MathXMLValidationError, match=r"Nat.+Elem\(K\)"):
        validate_typed_matrix_openmath_xml(bad_rank)
    with pytest.raises(MathXMLValidationError, match="dimensions must be direct OMI values 1..8"):
        validate_typed_matrix_openmath_xml(bad_dimension)


def test_matrix_profile_rejects_wrong_field_literal_counts_and_nonliteral_dimensions() -> None:
    declarations = (
        _declaration("K", _field_sort())
        + _declaration("L", _field_sort())
        + _declaration("a", _element_sort("L"))
        + _declaration("A", _matrix_sort("K", 2, 2))
    )
    wrong_field = _binding(
        declarations,
        _eq(_matrix("scale", '<OMV name="a"/>', '<OMV name="A"/>'), '<OMV name="A"/>'),
    )
    bare_entry = _binding(
        _field_matrix_declarations(),
        _eq(
            _matrix(
                "literal",
                '<OMV name="K"/>',
                "<OMI>1</OMI>",
                "<OMI>1</OMI>",
                "<OMI>2</OMI>",
            ),
            _matrix("zero", '<OMV name="K"/>', "<OMI>1</OMI>", "<OMI>1</OMI>"),
        ),
    )
    missing_entry = _binding(
        _field_matrix_declarations(),
        _eq(
            _matrix(
                "literal",
                '<OMV name="K"/>',
                "<OMI>2</OMI>",
                "<OMI>2</OMI>",
                _field_nat("K", 1),
            ),
            _matrix("zero", '<OMV name="K"/>', "<OMI>2</OMI>", "<OMI>2</OMI>"),
        ),
    )
    dimension_from_rank = _binding(
        _field_matrix_declarations(_declaration("A", _matrix_sort("K", 2, 2))),
        _eq(
            _matrix("identity", '<OMV name="K"/>', _matrix("rank", '<OMV name="A"/>')),
            '<OMV name="A"/>',
        ),
    )
    cast_from_rank = _binding(
        _field_matrix_declarations(_declaration("A", _matrix_sort("K", 2, 2))),
        _eq(
            _field_nat("K", 0).replace(
                "<OMI>0</OMI>",
                _matrix("rank", '<OMV name="A"/>'),
            ),
            _field_nat("K", 0),
        ),
    )

    with pytest.raises(MathXMLValidationError, match=r"Elem\(K\).+Elem\(L\)"):
        validate_typed_matrix_openmath_xml(wrong_field)
    with pytest.raises(MathXMLValidationError, match=r"Argument 4.*Elem\(K\).+Nat"):
        validate_typed_matrix_openmath_xml(bare_entry)
    with pytest.raises(MathXMLValidationError, match="requires exactly 4 entries"):
        validate_typed_matrix_openmath_xml(missing_entry)
    with pytest.raises(MathXMLValidationError, match="requires a direct OMI dimension"):
        validate_typed_matrix_openmath_xml(dimension_from_rank)
    with pytest.raises(MathXMLValidationError, match="must be a direct nonnegative OMI"):
        validate_typed_matrix_openmath_xml(cast_from_rank)


def test_matrix_profile_rejects_negative_field_terms_solve_and_invalid_determinant() -> None:
    declarations = _field_matrix_declarations(_declaration("A", _matrix_sort("K", 2, 3)))
    negative = _binding(
        _field_matrix_declarations(),
        _eq(_field_nat("K", -2), _field_nat("K", 0)),
    )
    determinant = _binding(
        declarations,
        _eq(_matrix("determinant", '<OMV name="A"/>'), _matrix("determinant", '<OMV name="A"/>')),
    )
    solve = _binding(
        _field_matrix_declarations(_declaration("A", _matrix_sort("K", 2, 2))),
        _eq(_matrix("solve", '<OMV name="A"/>'), '<OMV name="A"/>'),
    )
    field_neg = _binding(
        _field_matrix_declarations(),
        _eq(_matrix("field_neg", _field_nat("K", 2)), _field_nat("K", 0)),
    )
    ring_neg = _binding(
        _field_matrix_declarations(),
        _eq(
            _app(_typed_oms("algebra1", "ring_neg"), '<OMV name="K"/>', _field_nat("K", 2)),
            _field_nat("K", 0),
        ),
    )

    with pytest.raises(MathXMLValidationError, match="does not admit negative OMI"):
        validate_typed_matrix_openmath_xml(negative)
    with pytest.raises(MathXMLValidationError, match="determinant.*must be square"):
        validate_typed_matrix_openmath_xml(determinant)
    with pytest.raises(MathXMLValidationError, match="outside typed-math-matrix-v1"):
        validate_typed_matrix_openmath_xml(solve)
    with pytest.raises(MathXMLValidationError, match="outside typed-math-matrix-v1"):
        validate_typed_matrix_openmath_xml(field_neg)
    with pytest.raises(MathXMLValidationError, match="outside typed-math-matrix-v1"):
        validate_typed_matrix_openmath_xml(ring_neg)
