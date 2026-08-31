from __future__ import annotations

import pytest

from pals_agent.openmath import MathXMLValidationError, canonicalize_retrieval_openmath_xml
from pals_agent.typed_geometry_complex import (
    TYPED_GEOMETRY_COMPLEX_OPENMATH_CDBASE,
    canonicalize_typed_geometry_complex_openmath_xml,
    validate_canonical_typed_geometry_complex_openmath_xml,
    validate_typed_geometry_complex_openmath_xml,
)
from pals_agent.typed_math import validate_typed_math_openmath_xml

OPENMATH = "http://www.openmath.org/OpenMath"
STANDARD = "http://www.openmath.org/cd"
TYPED = TYPED_GEOMETRY_COMPLEX_OPENMATH_CDBASE


def _typed(name: str) -> str:
    return f'<OMS cdbase="{TYPED}" cd="pals2" name="{name}"/>'


def _standard(cd: str, name: str) -> str:
    return f'<OMS cdbase="{STANDARD}" cd="{cd}" name="{name}"/>'


def _app(operator: str, *arguments: str) -> str:
    return f"<OMA>{operator}{''.join(arguments)}</OMA>"


def _eq(left: str, right: str) -> str:
    return _app(_standard("relation1", "eq"), left, right)


def _vector(first: str, second: str) -> str:
    return _app(_standard("linalg2", "vector"), first, second)


def _complex(real: str, imaginary: str) -> str:
    return _app(_standard("complex1", "complex_cartesian"), real, imaginary)


def _pals(name: str, *arguments: str) -> str:
    return _app(_typed(name), *arguments)


def _binding(binder: str, variables: str, body: str) -> str:
    return (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>{_typed(binder)}'
        f"<OMBVAR>{variables}</OMBVAR>{body}</OMBIND></OMOBJ>"
    )


def _obj(body: str) -> str:
    return f'<OMOBJ xmlns="{OPENMATH}" version="2.0">{body}</OMOBJ>'


def test_vector_and_complex_profile_accepts_exact_standard_and_private_signatures() -> None:
    dot = _obj(
        _eq(
            _app(
                _standard("linalg1", "scalarproduct"),
                _vector("<OMI>1</OMI>", "<OMI>2</OMI>"),
                _vector("<OMI>2</OMI>", "<OMI>-1</OMI>"),
            ),
            "<OMI>0</OMI>",
        )
    )
    norm_square = _obj(
        _eq(
            _pals("complex_norm_sq", _complex("<OMI>3</OMI>", "<OMI>4</OMI>")),
            "<OMI>25</OMI>",
        )
    )
    selector = _obj(
        _eq(
            _app(
                _standard("linalg1", "vector_selector"),
                "<OMI>2</OMI>",
                _vector("<OMI>1</OMI>", "<OMI>2</OMI>"),
            ),
            "<OMI>2</OMI>",
        )
    )
    conjugate = _obj(
        _eq(
            _app(_standard("complex1", "conjugate"), _complex("<OMI>3</OMI>", "<OMI>4</OMI>")),
            _complex("<OMI>3</OMI>", "<OMI>-4</OMI>"),
        )
    )
    quadrant_premises = _binding(
        "forall_complex",
        '<OMV name="z"/>',
        _app(
            _standard("logic1", "implies"),
            _app(
                _standard("logic1", "and"),
                _app(
                    _standard("relation1", "lt"),
                    _app(_standard("complex1", "real"), '<OMV name="z"/>'),
                    "<OMI>0</OMI>",
                ),
                _app(
                    _standard("relation1", "gt"),
                    _app(_standard("complex1", "imaginary"), '<OMV name="z"/>'),
                    "<OMI>0</OMI>",
                ),
            ),
            _app(
                _standard("relation1", "gt"),
                _app(_standard("complex1", "argument"), '<OMV name="z"/>'),
                "<OMI>0</OMI>",
            ),
        ),
    )

    for xml in (dot, norm_square, selector, conjugate, quadrant_premises):
        validate_typed_geometry_complex_openmath_xml(xml)
        canonical = canonicalize_typed_geometry_complex_openmath_xml(xml)
        assert validate_canonical_typed_geometry_complex_openmath_xml(canonical) == canonical


def test_profile_canonicalizes_alpha_equivalent_vector_and_complex_binders() -> None:
    first = _binding(
        "forall_real_vector2",
        '<OMV name="u"/>',
        _eq(
            _pals("vector_add", '<OMV name="u"/>', '<OMV name="u"/>'),
            _pals("vector_add", '<OMV name="u"/>', '<OMV name="u"/>'),
        ),
    )
    second = _binding(
        "forall_real_vector2",
        '<OMV name="v"/>',
        _eq(
            _pals("vector_add", '<OMV name="v"/>', '<OMV name="v"/>'),
            _pals("vector_add", '<OMV name="v"/>', '<OMV name="v"/>'),
        ),
    )

    assert canonicalize_typed_geometry_complex_openmath_xml(first) == (
        canonicalize_typed_geometry_complex_openmath_xml(second)
    )


def test_profile_rejects_scalar_vector_complex_confusion_and_bad_vector_shapes() -> None:
    scalar_product_scalar = _obj(
        _eq(
            _app(
                _standard("linalg1", "scalarproduct"),
                _vector("<OMI>1</OMI>", "<OMI>2</OMI>"),
                "<OMI>3</OMI>",
            ),
            "<OMI>0</OMI>",
        )
    )
    wrong_dimension = _obj(
        _eq(
            _app(
                _standard("linalg1", "scalarproduct"),
                _vector("<OMI>1</OMI>", "<OMI>2</OMI>"),
                _app(
                    _standard("linalg2", "vector"),
                    "<OMI>3</OMI>",
                    "<OMI>4</OMI>",
                    "<OMI>5</OMI>",
                ),
            ),
            "<OMI>0</OMI>",
        )
    )
    bad_selector_zero = _obj(
        _eq(
            _app(
                _standard("linalg1", "vector_selector"),
                "<OMI>0</OMI>",
                _vector("<OMI>1</OMI>", "<OMI>2</OMI>"),
            ),
            "<OMI>1</OMI>",
        )
    )
    bad_selector_three = bad_selector_zero.replace("<OMI>0</OMI>", "<OMI>3</OMI>", 1)
    conjugate_real = _obj(
        _eq(_app(_standard("complex1", "conjugate"), "<OMI>3</OMI>"), "<OMI>3</OMI>")
    )
    complex_vector = _obj(
        _eq(
            _pals(
                "complex_mul",
                _complex("<OMI>1</OMI>", "<OMI>2</OMI>"),
                _vector("<OMI>1</OMI>", "<OMI>2</OMI>"),
            ),
            _complex("<OMI>0</OMI>", "<OMI>0</OMI>"),
        )
    )
    argument_complex = _obj(
        _eq(
            _pals(
                "complex_mul",
                _app(_standard("complex1", "argument"), _complex("<OMI>1</OMI>", "<OMI>2</OMI>")),
                _complex("<OMI>1</OMI>", "<OMI>0</OMI>"),
            ),
            _complex("<OMI>0</OMI>", "<OMI>0</OMI>"),
        )
    )

    with pytest.raises(MathXMLValidationError, match="V2.*R"):
        validate_typed_geometry_complex_openmath_xml(scalar_product_scalar)
    with pytest.raises(MathXMLValidationError, match="linalg2:vector.*requires 2"):
        validate_typed_geometry_complex_openmath_xml(wrong_dimension)
    for xml in (bad_selector_zero, bad_selector_three):
        with pytest.raises(MathXMLValidationError, match="literal 1 or 2"):
            validate_typed_geometry_complex_openmath_xml(xml)
    with pytest.raises(MathXMLValidationError, match="C.*R"):
        validate_typed_geometry_complex_openmath_xml(conjugate_real)
    with pytest.raises(MathXMLValidationError, match="C.*V2"):
        validate_typed_geometry_complex_openmath_xml(complex_vector)
    with pytest.raises(MathXMLValidationError, match="C.*R"):
        validate_typed_geometry_complex_openmath_xml(argument_complex)


def test_profile_hard_rejects_cdbase_inheritance_unknown_attributes_and_phase_b_geometry() -> None:
    valid = _obj(
        _eq(
            _pals(
                "vector_add",
                _vector("<OMI>1</OMI>", "<OMI>2</OMI>"),
                _vector("<OMI>3</OMI>", "<OMI>4</OMI>"),
            ),
            _vector("<OMI>4</OMI>", "<OMI>6</OMI>"),
        )
    )
    inherited = valid.replace(f' cdbase="{STANDARD}"', "")
    inherited = inherited.replace(
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0">',
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0" cdbase="{STANDARD}">',
    )
    unknown_attribute = valid.replace("<OMI>1</OMI>", '<OMI proof="forged">1</OMI>', 1)
    phase_b = _binding(
        "forall_real_vector2",
        '<OMV name="u"/>',
        _app(
            _standard("relation1", "eq"),
            _app(
                f'<OMS cdbase="{TYPED}" cd="pals2" name="point2"/>',
                "<OMI>0</OMI>",
                "<OMI>0</OMI>",
            ),
            _app(
                f'<OMS cdbase="{TYPED}" cd="pals2" name="point2"/>',
                "<OMI>0</OMI>",
                "<OMI>0</OMI>",
            ),
        ),
    )
    native_geometry = _obj(
        _eq(
            f'<OMS cdbase="{STANDARD}" cd="geometry1" name="line"/>',
            f'<OMS cdbase="{STANDARD}" cd="geometry1" name="line"/>',
        )
    )

    with pytest.raises(MathXMLValidationError, match="OMOBJ.*attribute `cdbase`"):
        validate_typed_geometry_complex_openmath_xml(inherited)
    with pytest.raises(MathXMLValidationError, match="OMI.*attribute `proof`"):
        validate_typed_geometry_complex_openmath_xml(unknown_attribute)
    with pytest.raises(MathXMLValidationError, match="point2.*outside typed-geometry-complex-v1"):
        validate_typed_geometry_complex_openmath_xml(phase_b)
    with pytest.raises(
        MathXMLValidationError,
        match="geometry1:line.*outside typed-geometry-complex-v1",
    ):
        validate_typed_geometry_complex_openmath_xml(native_geometry)


def test_profile_does_not_widen_generic_or_base_typed_math() -> None:
    raw = _obj(
        _eq(
            _pals("complex_norm_sq", _complex("<OMI>3</OMI>", "<OMI>4</OMI>")),
            "<OMI>25</OMI>",
        )
    )

    with pytest.raises(MathXMLValidationError):
        canonicalize_retrieval_openmath_xml(raw)
    with pytest.raises(MathXMLValidationError, match="outside typed-math-v1"):
        validate_typed_math_openmath_xml(raw)
