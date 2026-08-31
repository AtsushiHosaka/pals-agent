from __future__ import annotations

import pytest

from pals_agent.openmath import (
    OPENMATH_STANDARD_CDBASE,
    MathXMLValidationError,
    canonicalize_retrieval_openmath_xml,
)
from pals_agent.typed_math import (
    TYPED_MATH_OPENMATH_CDBASE,
    canonicalize_typed_math_openmath_xml,
    validate_canonical_typed_math_openmath_xml,
    validate_typed_math_openmath_xml,
)

OPENMATH = "http://www.openmath.org/OpenMath"


def _typed_oms(cd: str, name: str) -> str:
    return f'<OMS cdbase="{TYPED_MATH_OPENMATH_CDBASE}" cd="{cd}" name="{name}"/>'


def _type_group() -> str:
    return _typed_oms("algebra1", "Group")


def _type_comm_ring() -> str:
    return _typed_oms("algebra1", "CommRing")


def _type_elem(carrier: str) -> str:
    return f'<OMA>{_typed_oms("typed1", "Elem")}<OMV name="{carrier}"/></OMA>'


def _declaration(name: str, sort: str) -> str:
    return (
        f'<OMATTR><OMATP>{_typed_oms("typed1", "type")}{sort}</OMATP><OMV name="{name}"/></OMATTR>'
    )


def _app(cd: str, name: str, *arguments: str, typed: bool = False) -> str:
    head = _typed_oms(cd, name) if typed else f'<OMS cd="{cd}" name="{name}"/>'
    return f"<OMA>{head}{''.join(arguments)}</OMA>"


def _binding(declarations: str, body: str) -> str:
    return (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>'
        f"{_typed_oms('typed1', 'forall')}<OMBVAR>{declarations}</OMBVAR>{body}"
        "</OMBIND></OMOBJ>"
    )


def _group_inverse_product(group: str = "G", left: str = "a", right: str = "b") -> str:
    declarations = "".join(
        (
            _declaration(group, _type_group()),
            _declaration(left, _type_elem(group)),
            _declaration(right, _type_elem(group)),
        )
    )
    product = _app(
        "algebra1",
        "mul",
        f'<OMV name="{group}"/>',
        f'<OMV name="{left}"/>',
        f'<OMV name="{right}"/>',
        typed=True,
    )
    left_side = _app("algebra1", "inv", f'<OMV name="{group}"/>', product, typed=True)
    right_side = _app(
        "algebra1",
        "mul",
        f'<OMV name="{group}"/>',
        _app("algebra1", "inv", f'<OMV name="{group}"/>', f'<OMV name="{right}"/>', typed=True),
        _app("algebra1", "inv", f'<OMV name="{group}"/>', f'<OMV name="{left}"/>', typed=True),
        typed=True,
    )
    return _binding(declarations, _app("relation1", "eq", left_side, right_side))


def test_typed_math_accepts_group_and_ring_core() -> None:
    group = _group_inverse_product()
    ring_declarations = _declaration("R", _type_comm_ring()) + _declaration("x", _type_elem("R"))
    ring_zero = _app("algebra1", "ring_zero", '<OMV name="R"/>', typed=True)
    ring_body = _app(
        "relation1",
        "eq",
        _app(
            "algebra1",
            "ring_add",
            '<OMV name="R"/>',
            '<OMV name="x"/>',
            ring_zero,
            typed=True,
        ),
        '<OMV name="x"/>',
    )

    validate_typed_math_openmath_xml(group)
    validate_typed_math_openmath_xml(_binding(ring_declarations, ring_body))
    with pytest.raises(MathXMLValidationError, match="Retrieval OMBVAR requires"):
        canonicalize_retrieval_openmath_xml(group)


def test_typed_math_canonicalizes_alpha_equivalent_bound_sorts() -> None:
    first = canonicalize_typed_math_openmath_xml(_group_inverse_product("G", "a", "b"))
    second = canonicalize_typed_math_openmath_xml(_group_inverse_product("H", "x", "y"))

    assert first == second
    assert validate_canonical_typed_math_openmath_xml(first) == first


def test_typed_math_rejects_generic_only_profile_confusion() -> None:
    generic = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="relation1" name="eq"/><OMI>1</OMI><OMI>1</OMI>'
        "</OMA></OMOBJ>"
    )

    with pytest.raises(MathXMLValidationError, match="not a typed-math-v1"):
        validate_typed_math_openmath_xml(generic)


def test_typed_math_rejects_carrier_mismatch() -> None:
    declarations = "".join(
        (
            _declaration("G", _type_group()),
            _declaration("H", _type_group()),
            _declaration("a", _type_elem("G")),
            _declaration("b", _type_elem("H")),
        )
    )
    product = _app(
        "algebra1",
        "mul",
        '<OMV name="G"/>',
        '<OMV name="a"/>',
        '<OMV name="b"/>',
        typed=True,
    )
    xml = _binding(declarations, _app("relation1", "eq", product, '<OMV name="a"/>'))

    with pytest.raises(MathXMLValidationError, match=r"Argument 3.*Elem\(G\).+Elem\(H\)"):
        validate_typed_math_openmath_xml(xml)


def test_typed_math_rejects_missing_or_misplaced_type_annotation() -> None:
    missing = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>{_typed_oms("typed1", "forall")} '
        '<OMBVAR><OMV name="x"/></OMBVAR><OMA><OMS cd="relation1" name="eq"/>'
        '<OMV name="x"/><OMV name="x"/></OMA></OMBIND></OMOBJ>'
    )
    misplaced = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMATTR><OMATP>{_typed_oms("typed1", "type")}'
        f'{_type_group()}</OMATP><OMV name="G"/></OMATTR></OMOBJ>'
    )

    with pytest.raises(MathXMLValidationError, match="OMBVAR requires"):
        validate_typed_math_openmath_xml(missing)
    with pytest.raises(MathXMLValidationError, match="only as one typed OMBVAR"):
        validate_typed_math_openmath_xml(misplaced)


def test_typed_math_rejects_generic_quantifiers_and_direct_ring_numerals() -> None:
    generic_quantifier = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND><OMS cd="quant1" name="forall"/>'
        '<OMBVAR><OMV name="x"/></OMBVAR><OMA><OMS cd="relation1" name="eq"/>'
        '<OMV name="x"/><OMV name="x"/></OMA></OMBIND></OMOBJ>'
    )
    declarations = _declaration("R", _type_comm_ring()) + _declaration("x", _type_elem("R"))
    direct_numeral = _binding(
        declarations,
        _app(
            "relation1",
            "eq",
            _app(
                "algebra1",
                "ring_add",
                '<OMV name="R"/>',
                '<OMV name="x"/>',
                "<OMI>2</OMI>",
                typed=True,
            ),
            '<OMV name="x"/>',
        ),
    )

    with pytest.raises(MathXMLValidationError, match="OMBIND must use typed1"):
        validate_typed_math_openmath_xml(generic_quantifier)
    with pytest.raises(MathXMLValidationError, match=r"Argument 3.*Elem\(R\).+Nat"):
        validate_typed_math_openmath_xml(direct_numeral)


def test_typed_math_rejects_forward_type_references_and_shadowing() -> None:
    forward_reference = _binding(
        _declaration("a", _type_elem("G")) + _declaration("G", _type_group()),
        _app("relation1", "eq", '<OMV name="a"/>', '<OMV name="a"/>'),
    )
    inner = (
        f"<OMBIND>{_typed_oms('typed1', 'exists')}<OMBVAR>"
        f"{_declaration('G', _type_group())}</OMBVAR>"
        '<OMA><OMS cd="relation1" name="eq"/><OMV name="G"/><OMV name="G"/></OMA>'
        "</OMBIND>"
    )
    shadowing = _binding(
        _declaration("G", _type_group()),
        inner,
    )

    with pytest.raises(MathXMLValidationError, match="invalid type annotation"):
        validate_typed_math_openmath_xml(forward_reference)
    with pytest.raises(MathXMLValidationError, match="redeclares bound variable `G`"):
        validate_typed_math_openmath_xml(shadowing)


def test_typed_math_rejects_inherited_typed_cdbase_and_negative_nat_cast() -> None:
    inherited = _group_inverse_product().replace(f' cdbase="{TYPED_MATH_OPENMATH_CDBASE}"', "")
    inherited = inherited.replace(
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0">',
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0" cdbase="{TYPED_MATH_OPENMATH_CDBASE}">',
    )
    inherited = inherited.replace(
        '<OMS cd="relation1"',
        '<OMS cdbase="http://www.openmath.org/cd" cd="relation1"',
    )
    declarations = _declaration("R", _type_comm_ring()) + _declaration("x", _type_elem("R"))
    negative_cast = _binding(
        declarations,
        _app(
            "relation1",
            "eq",
            _app(
                "typed1",
                "nat_cast",
                '<OMV name="R"/>',
                "<OMI>-2</OMI>",
                typed=True,
            ),
            '<OMV name="x"/>',
        ),
    )

    with pytest.raises(MathXMLValidationError, match="directly declare its typed cdbase"):
        validate_typed_math_openmath_xml(inherited)
    with pytest.raises(MathXMLValidationError, match="does not admit negative OMI"):
        validate_typed_math_openmath_xml(negative_cast)


def test_typed_math_rejects_unknown_annotations_free_variables_and_type_mismatches() -> None:
    unknown_symbol = _group_inverse_product().replace('name="inv"', 'name="unknown"', 1)
    multiple_type = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>{_typed_oms("typed1", "forall")} '
        f"<OMBVAR><OMATTR><OMATP>{_typed_oms('typed1', 'type')}{_type_group()}"
        f'{_typed_oms("typed1", "type")}{_type_group()}</OMATP><OMV name="G"/>'
        "</OMATTR></OMBVAR>"
        '<OMA><OMS cd="relation1" name="eq"/><OMV name="G"/><OMV name="G"/></OMA>'
        "</OMBIND></OMOBJ>"
    )
    unknown_type_key = multiple_type.replace('name="type"', 'name="unknown_type"', 1)
    declarations = "".join(
        (
            _declaration("G", _type_group()),
            _declaration("H", _type_group()),
            _declaration("a", _type_elem("G")),
            _declaration("b", _type_elem("H")),
        )
    )
    free_variable = _binding(
        _declaration("G", _type_group()),
        _app("relation1", "eq", '<OMV name="z"/>', '<OMV name="z"/>'),
    )
    mixed_equality = _binding(
        declarations,
        _app("relation1", "eq", '<OMV name="a"/>', '<OMV name="b"/>'),
    )
    wrong_inverse = _binding(
        declarations,
        _app(
            "relation1",
            "eq",
            _app("algebra1", "inv", '<OMV name="G"/>', '<OMV name="b"/>', typed=True),
            '<OMV name="a"/>',
        ),
    )
    inherited_standard = _group_inverse_product().replace(
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0">',
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0" cdbase="{OPENMATH_STANDARD_CDBASE}">',
    )

    with pytest.raises(MathXMLValidationError, match="outside typed-math-v1"):
        validate_typed_math_openmath_xml(unknown_symbol)
    with pytest.raises(MathXMLValidationError, match="OMBVAR requires"):
        validate_typed_math_openmath_xml(multiple_type)
    with pytest.raises(MathXMLValidationError, match="OMBVAR requires"):
        validate_typed_math_openmath_xml(unknown_type_key)
    with pytest.raises(MathXMLValidationError, match="free or undeclared variable `z`"):
        validate_typed_math_openmath_xml(free_variable)
    with pytest.raises(MathXMLValidationError, match=r"Elem\(G\).+Elem\(H\)"):
        validate_typed_math_openmath_xml(mixed_equality)
    with pytest.raises(MathXMLValidationError, match=r"Argument 2.*Elem\(G\).+Elem\(H\)"):
        validate_typed_math_openmath_xml(wrong_inverse)
    with pytest.raises(MathXMLValidationError, match="Standard typed-math-v1 OMS"):
        validate_typed_math_openmath_xml(inherited_standard)


def test_typed_math_preserves_pinned_generic_canonical_bytes() -> None:
    generic = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="relation1" name="eq"/><OMI>1</OMI><OMI>1</OMI>'
        "</OMA></OMOBJ>"
    )

    assert canonicalize_retrieval_openmath_xml(generic) == (
        '<n1:OMOBJ xmlns:n1="http://www.openmath.org/OpenMath" version="2.0"><n1:OMA>'
        '<n1:OMS cd="relation1" name="eq"></n1:OMS><n1:OMI>1</n1:OMI>'
        "<n1:OMI>1</n1:OMI></n1:OMA></n1:OMOBJ>"
    )
