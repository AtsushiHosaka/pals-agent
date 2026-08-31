"""Fail-closed OpenMath validation for ``typed-geometry-complex-v1``.

The vector/complex-plane profile is an opt-in sibling of generic retrieval and
of every other typed profile.  It gives the selected standard ``linalg`` and
``complex`` symbols exact ``R``, ``V2``, and ``C`` signatures; it does not make
those CDs generic Draft vocabulary, and it deliberately has no affine-point
or native-geometry surface.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from importlib import resources
from typing import Literal, cast

from .openmath import (
    OPENMATH_NAMESPACE,
    OPENMATH_STANDARD_CDBASE,
    MathXMLValidationError,
    _canonicalize_openmath_v4_root,
    _element_depth,
    _local_name,
    _openmath_parents,
    _operator_symbol,
    validate_openmath_xml,
)

TYPED_GEOMETRY_COMPLEX_OPENMATH_CDBASE = "urn:pals:openmath:cd:v2"
TYPED_GEOMETRY_COMPLEX_PROFILE = "typed-geometry-complex-v1"

_SortName = Literal["prop", "real", "vector2", "complex"]
_Symbol = tuple[str, str, str]
_INTEGER_RE = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_PRIVATE_BINDERS = frozenset(
    {"forall_real_vector2", "exists_real_vector2", "forall_complex", "exists_complex"}
)
_LOGICAL_NARY = frozenset({"and", "or"})
_LOGICAL_BINARY = frozenset({"implies", "equivalent"})
_ORDER_RELATIONS = frozenset({"lt", "leq", "gt", "geq"})
_REAL_ARITHMETIC = frozenset({"plus", "times", "minus", "divide", "abs", "unary_minus"})
_ALLOWED_ATTRIBUTES: dict[str, frozenset[str]] = {
    "OMOBJ": frozenset({"version"}),
    "OMS": frozenset({"cdbase", "cd", "name"}),
    "OMV": frozenset({"name"}),
    "OMI": frozenset(),
    "OMA": frozenset(),
    "OMBIND": frozenset(),
    "OMBVAR": frozenset(),
}


@dataclass(frozen=True, slots=True)
class TypedGeometryComplexSort:
    """One exact sort in the planar-vector/complex sibling profile."""

    name: _SortName

    def render(self) -> str:
        return {"prop": "Prop", "real": "R", "vector2": "V2", "complex": "C"}[self.name]


@dataclass(frozen=True, slots=True)
class _Inferred:
    sort: TypedGeometryComplexSort
    integer_literal: int | None = None


_PROP = TypedGeometryComplexSort("prop")
_REAL = TypedGeometryComplexSort("real")
_VECTOR2 = TypedGeometryComplexSort("vector2")
_COMPLEX = TypedGeometryComplexSort("complex")


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-geometry-complex-v1-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - package invariant
        raise RuntimeError("typed-geometry-complex-v1 symbol registry is unavailable.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "pals.typed-geometry-complex-registry.v1"
        or payload.get("profile_id") != TYPED_GEOMETRY_COMPLEX_PROFILE
        or payload.get("cdbases")
        != {
            "standard": OPENMATH_STANDARD_CDBASE,
            "typed": TYPED_GEOMETRY_COMPLEX_OPENMATH_CDBASE,
        }
    ):  # pragma: no cover - package invariant
        raise RuntimeError("typed-geometry-complex-v1 registry header is invalid.")
    entries = payload.get("symbols")
    if not isinstance(entries, list):  # pragma: no cover - package invariant
        raise RuntimeError("typed-geometry-complex-v1 registry has no symbols list.")
    symbols: set[_Symbol] = set()
    for entry in entries:
        if not isinstance(entry, dict):  # pragma: no cover - package invariant
            raise RuntimeError("typed-geometry-complex-v1 registry entry is invalid.")
        identity = tuple(entry.get(field) for field in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError("typed-geometry-complex-v1 registry identity is invalid.")
        symbols.add(cast(_Symbol, identity))
    if len(symbols) != len(entries):  # pragma: no cover - package invariant
        raise RuntimeError("typed-geometry-complex-v1 registry contains duplicate symbols.")
    return frozenset(symbols)


_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_geometry_complex_openmath_xml(xml: str) -> str:
    """Validate and canonicalize one closed vector/complex proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("OpenMath XML exceeds the typed-geometry-complex byte bound.")
    root = validate_openmath_xml(xml)
    validate_typed_geometry_complex_openmath_root(root)
    return _canonicalize_openmath_v4_root(root)


def validate_canonical_typed_geometry_complex_openmath_xml(xml: str) -> str:
    """Accept only exact canonical bytes for this isolated sibling profile."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError(
            "OpenMath XML is not exact typed-geometry-complex canonical bytes."
        )
    canonical = canonicalize_typed_geometry_complex_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError(
            "OpenMath XML is not exact typed-geometry-complex canonical bytes."
        )
    return canonical


def validate_typed_geometry_complex_openmath_xml(xml: str) -> None:
    """Validate one closed ``typed-geometry-complex-v1`` proposition."""
    validate_typed_geometry_complex_openmath_root(validate_openmath_xml(xml))


def validate_typed_geometry_complex_openmath_root(root: ET.Element) -> None:
    """Validate an already XML-valid OpenMath root in this profile."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("OpenMath typed-geometry-complex tree exceeds 4,096 nodes.")
    parents = _openmath_parents(root)
    _validate_tree_shape(root, nodes=nodes, parents=parents)
    if not _contains_profile_construct(root, parents=parents):
        raise MathXMLValidationError("OpenMath XML is not a typed-geometry-complex-v1 proposition.")
    inferred = _infer_expression(list(root)[0], environment={}, parents=parents, path="root")
    if inferred.sort != _PROP:
        raise MathXMLValidationError("typed-geometry-complex-v1 root must have sort `Prop`.")


def _validate_tree_shape(
    root: ET.Element,
    *,
    nodes: list[ET.Element],
    parents: dict[ET.Element, ET.Element],
) -> None:
    for element in nodes:
        local_name = _local_name(element)
        if local_name not in _ALLOWED_ATTRIBUTES:
            raise MathXMLValidationError(
                f"OpenMath element `{local_name}` is outside typed-geometry-complex-v1."
            )
        _validate_attributes(element, local_name=local_name)
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("OpenMath typed-geometry-complex tree exceeds depth 64.")
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError(
                "OpenMath typed-geometry-complex text exceeds 20,000 code points."
            )
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError(
                "typed-geometry-complex-v1 elements cannot have text tails."
            )
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError(
                "typed-geometry-complex-v1 attribute exceeds 20,000 code points."
            )
        if local_name == "OMBVAR":
            variables = list(element)
            if not 1 <= len(variables) <= 256 or any(
                _local_name(variable) != "OMV" or set(variable.attrib) != {"name"}
                for variable in variables
            ):
                raise MathXMLValidationError(
                    "typed-geometry-complex-v1 OMBVAR requires 1..256 bare OMV declarations."
                )
        if local_name == "OMBIND":
            binder, _variables, _body = list(element)
            symbol = _operator_symbol(binder, parents=parents)
            if (
                symbol is None
                or symbol[:2] != (TYPED_GEOMETRY_COMPLEX_OPENMATH_CDBASE, "pals2")
                or symbol[2] not in _PRIVATE_BINDERS
                or binder.get("cdbase") != TYPED_GEOMETRY_COMPLEX_OPENMATH_CDBASE
            ):
                raise MathXMLValidationError(
                    "typed-geometry-complex-v1 OMBIND must use a direct pals2 typed binder."
                )
        if local_name == "OMA" and _local_name(list(element)[0]) != "OMS":
            raise MathXMLValidationError("typed-geometry-complex-v1 OMA head must be an OMS.")
        if local_name == "OMS":
            _validate_symbol(element, parents=parents)


def _validate_attributes(element: ET.Element, *, local_name: str) -> None:
    actual = set(element.attrib)
    unexpected = actual - _ALLOWED_ATTRIBUTES[local_name]
    if unexpected:
        raise MathXMLValidationError(
            "typed-geometry-complex-v1 "
            f"`{local_name}` does not permit attribute `{sorted(unexpected)[0]}`."
        )
    if local_name == "OMOBJ" and actual != {"version"}:
        raise MathXMLValidationError("typed-geometry-complex-v1 OMOBJ requires only `version`.")
    if local_name == "OMS" and actual != {"cdbase", "cd", "name"}:
        raise MathXMLValidationError(
            "typed-geometry-complex-v1 OMS requires direct `cdbase`, `cd`, and `name`."
        )
    if local_name == "OMV" and actual != {"name"}:
        raise MathXMLValidationError("typed-geometry-complex-v1 OMV requires only `name`.")


def _validate_symbol(element: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed-geometry-complex-v1 OMS must identify a symbol.")
    if element.get("cdbase") != symbol[0]:
        raise MathXMLValidationError(
            "typed-geometry-complex-v1 OMS must directly declare its cdbase."
        )
    if symbol not in _SYMBOL_REGISTRY:
        cdbase, cd, name = symbol
        raise MathXMLValidationError(
            f"Symbol `{cd}:{name}` with cdbase `{cdbase}` is outside typed-geometry-complex-v1."
        )


def _contains_profile_construct(root: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> bool:
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        symbol = _operator_symbol(element, parents=parents)
        if symbol is None:
            continue
        if symbol[:2] == (TYPED_GEOMETRY_COMPLEX_OPENMATH_CDBASE, "pals2"):
            return True
        if symbol[:2] in {
            (OPENMATH_STANDARD_CDBASE, "linalg1"),
            (OPENMATH_STANDARD_CDBASE, "linalg2"),
            (OPENMATH_STANDARD_CDBASE, "complex1"),
            (OPENMATH_STANDARD_CDBASE, "nums1"),
        }:
            return True
    return False


def _infer_expression(
    expression: ET.Element,
    *,
    environment: dict[str, TypedGeometryComplexSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> _Inferred:
    local_name = _local_name(expression)
    if local_name == "OMV":
        name = expression.get("name")
        if name is None or name not in environment:
            raise MathXMLValidationError(
                "typed-geometry-complex-v1 has a free or undeclared variable "
                f"`{name or ''}` at {path}."
            )
        return _Inferred(environment[name])
    if local_name == "OMI":
        value = "".join((expression.text or "").split())
        if not _INTEGER_RE.fullmatch(value):
            raise MathXMLValidationError(
                "typed-geometry-complex-v1 OMI must be one exact decimal integer literal."
            )
        return _Inferred(_REAL, integer_literal=int(value))
    if local_name == "OMS":
        symbol = _operator_symbol(expression, parents=parents)
        if symbol == (OPENMATH_STANDARD_CDBASE, "nums1", "i"):
            return _Inferred(_COMPLEX)
        raise MathXMLValidationError(
            f"typed-geometry-complex-v1 cannot infer a sort for symbol at {path}."
        )
    if local_name == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if local_name != "OMA":
        raise MathXMLValidationError(
            f"typed-geometry-complex-v1 cannot infer a sort for `{local_name}` at {path}."
        )
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(
            f"typed-geometry-complex-v1 OMA has an invalid operator at {path}."
        )
    inferred_arguments = [
        _infer_expression(
            argument,
            environment=environment,
            parents=parents,
            path=f"{path}/{index}",
        )
        for index, argument in enumerate(arguments, start=1)
    ]
    return _infer_application(symbol, inferred_arguments, path=path)


def _infer_binding(
    binding: ET.Element,
    *,
    environment: dict[str, TypedGeometryComplexSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> _Inferred:
    binder, variables, body = list(binding)
    symbol = _operator_symbol(binder, parents=parents)
    assert symbol is not None
    local_environment = dict(environment)
    bound_sort = _VECTOR2 if symbol[2].endswith("vector2") else _COMPLEX
    declared: set[str] = set()
    for index, variable in enumerate(list(variables), start=1):
        name = variable.get("name")
        if name is None or not name:
            raise MathXMLValidationError(
                f"typed-geometry-complex-v1 bound OMV is missing `name` at {path}/bind/{index}."
            )
        if name in declared or name in environment:
            raise MathXMLValidationError(
                f"typed-geometry-complex-v1 redeclares bound variable `{name}` at {path}."
            )
        declared.add(name)
        local_environment[name] = bound_sort
    body_sort = _infer_expression(
        body,
        environment=local_environment,
        parents=parents,
        path=f"{path}/body",
    )
    if body_sort.sort != _PROP:
        raise MathXMLValidationError(
            f"The body of `pals2:{symbol[2]}` must have sort `Prop`; "
            f"received `{body_sort.sort.render()}`."
        )
    return _Inferred(_PROP)


def _infer_application(symbol: _Symbol, arguments: list[_Inferred], *, path: str) -> _Inferred:
    cdbase, cd, name = symbol
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "relation1"):
        if name in {"eq", "neq"}:
            _require_arity(symbol, arguments, exact=2)
            _require_same(symbol, arguments, 0, 1, path=path)
            return _Inferred(_PROP)
        if name in _ORDER_RELATIONS:
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _REAL, path=path)
            return _Inferred(_PROP)
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "logic1"):
        if name in _LOGICAL_NARY:
            _require_arity(symbol, arguments, minimum=2)
            _require_all(symbol, arguments, _PROP, path=path)
            return _Inferred(_PROP)
        if name in _LOGICAL_BINARY:
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _PROP, path=path)
            return _Inferred(_PROP)
        if name == "not":
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _PROP, path=path)
            return _Inferred(_PROP)
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "arith1") and name in _REAL_ARITHMETIC:
        _infer_real_arithmetic(symbol, arguments, path=path)
        return _Inferred(_REAL)
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "linalg2") and name == "vector":
        _require_arity(symbol, arguments, exact=2)
        _require_all(symbol, arguments, _REAL, path=path)
        return _Inferred(_VECTOR2)
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "linalg1"):
        if name == "vector_selector":
            _require_arity(symbol, arguments, exact=2)
            _require_argument(symbol, arguments, 0, _REAL, path=path)
            index = arguments[0].integer_literal
            if index not in {1, 2}:
                raise MathXMLValidationError(
                    "Argument 1 of `linalg1:vector_selector` must be the literal 1 or 2."
                )
            _require_argument(symbol, arguments, 1, _VECTOR2, path=path)
            return _Inferred(_REAL)
        if name == "scalarproduct":
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _VECTOR2, path=path)
            return _Inferred(_REAL)
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "complex1"):
        if name == "complex_cartesian":
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _REAL, path=path)
            return _Inferred(_COMPLEX)
        if name == "conjugate":
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _COMPLEX, path=path)
            return _Inferred(_COMPLEX)
        if name in {"real", "imaginary", "argument"}:
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _COMPLEX, path=path)
            return _Inferred(_REAL)
    if (cdbase, cd, name) == (OPENMATH_STANDARD_CDBASE, "nums1", "i"):
        _require_arity(symbol, arguments, exact=0)
        return _Inferred(_COMPLEX)
    if (cdbase, cd) == (TYPED_GEOMETRY_COMPLEX_OPENMATH_CDBASE, "pals2"):
        if name == "vector_add":
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _VECTOR2, path=path)
            return _Inferred(_VECTOR2)
        if name == "vector_scale":
            _require_arity(symbol, arguments, exact=2)
            _require_argument(symbol, arguments, 0, _REAL, path=path)
            _require_argument(symbol, arguments, 1, _VECTOR2, path=path)
            return _Inferred(_VECTOR2)
        if name == "determinant2":
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _VECTOR2, path=path)
            return _Inferred(_REAL)
        if name in {"complex_add", "complex_mul"}:
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _COMPLEX, path=path)
            return _Inferred(_COMPLEX)
        if name == "complex_norm_sq":
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _COMPLEX, path=path)
            return _Inferred(_REAL)
    raise MathXMLValidationError(
        f"Unsupported typed-geometry-complex-v1 application `{cd}:{name}` at {path}."
    )


def _infer_real_arithmetic(symbol: _Symbol, arguments: list[_Inferred], *, path: str) -> None:
    name = symbol[2]
    if name in {"plus", "times"}:
        _require_arity(symbol, arguments, minimum=2)
    else:
        _require_arity(symbol, arguments, exact=1 if name in {"abs", "unary_minus"} else 2)
    _require_all(symbol, arguments, _REAL, path=path)


def _require_arity(
    symbol: _Symbol,
    arguments: list[_Inferred],
    *,
    exact: int | None = None,
    minimum: int | None = None,
) -> None:
    valid = (exact is None or len(arguments) == exact) and (
        minimum is None or len(arguments) >= minimum
    )
    if valid:
        return
    _, cd, name = symbol
    expected = str(exact) if exact is not None else f"at least {minimum}"
    raise MathXMLValidationError(
        f"`{cd}:{name}` requires {expected} arguments; received {len(arguments)}."
    )


def _require_all(
    symbol: _Symbol,
    arguments: list[_Inferred],
    expected: TypedGeometryComplexSort,
    *,
    path: str,
) -> None:
    for index in range(len(arguments)):
        _require_argument(symbol, arguments, index, expected, path=path)


def _require_argument(
    symbol: _Symbol,
    arguments: list[_Inferred],
    index: int,
    expected: TypedGeometryComplexSort,
    *,
    path: str,
) -> None:
    actual = arguments[index].sort
    if actual == expected:
        return
    _, cd, name = symbol
    raise MathXMLValidationError(
        f"Argument {index + 1} of `{cd}:{name}` at {path} must have sort "
        f"`{expected.render()}`; received `{actual.render()}`."
    )


def _require_same(
    symbol: _Symbol,
    arguments: list[_Inferred],
    first: int,
    second: int,
    *,
    path: str,
) -> None:
    if arguments[first].sort == arguments[second].sort:
        return
    _, cd, name = symbol
    raise MathXMLValidationError(
        f"Argument {second + 1} of `{cd}:{name}` at {path} must have sort "
        f"`{arguments[first].sort.render()}`; received `{arguments[second].sort.render()}`."
    )
