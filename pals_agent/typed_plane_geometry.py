"""Fail-closed OpenMath validation for ``typed-plane-geometry-v1``.

This native affine-plane profile is an opt-in sibling of generic retrieval and
the vector/complex profile.  It deliberately keeps ``P2`` and ``V2`` distinct
before any potential Lean lowering.
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

TYPED_PLANE_GEOMETRY_OPENMATH_CDBASE = "urn:pals:openmath:typed-plane-geometry:v1"
TYPED_PLANE_GEOMETRY_PROFILE = "typed-plane-geometry-v1"

_SortName = Literal["prop", "real", "vector2", "point2", "line2", "circle2"]
_Symbol = tuple[str, str, str]
_INTEGER_RE = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_PRIVATE_CD = "pals_plane_geometry"
_TYPED_BINDERS = frozenset({"forall", "exists"})
_SORT_NAMES = frozenset({"Real", "Vector2", "Point2", "Line2", "Circle2"})
_LOGICAL_NARY = frozenset({"and", "or"})
_LOGICAL_BINARY = frozenset({"implies", "equivalent"})
_RELATIONS = frozenset({"eq", "neq"})
_GEOMETRY_CONSTRUCTS = frozenset(
    {
        "vector2",
        "vector_add",
        "point2",
        "incident_point_line",
        "incident_point_circle",
        "parallel",
        "perpendicular",
        "distance_sq",
        "midpoint",
        "reflect",
        "non_collinear",
    }
)
_ALLOWED_ATTRIBUTES: dict[str, frozenset[str]] = {
    "OMOBJ": frozenset({"version"}),
    "OMS": frozenset({"cdbase", "cd", "name"}),
    "OMV": frozenset({"name"}),
    "OMI": frozenset(),
    "OMA": frozenset(),
    "OMBIND": frozenset(),
    "OMBVAR": frozenset(),
    "OMATTR": frozenset(),
    "OMATP": frozenset(),
}


@dataclass(frozen=True, slots=True)
class TypedPlaneGeometrySort:
    """One exact native-plane sort inferred by the isolated profile."""

    name: _SortName

    def render(self) -> str:
        return {
            "prop": "Prop",
            "real": "R",
            "vector2": "V2",
            "point2": "P2",
            "line2": "L2",
            "circle2": "Circle2",
        }[self.name]


_PROP = TypedPlaneGeometrySort("prop")
_REAL = TypedPlaneGeometrySort("real")
_VECTOR2 = TypedPlaneGeometrySort("vector2")
_POINT2 = TypedPlaneGeometrySort("point2")
_LINE2 = TypedPlaneGeometrySort("line2")
_CIRCLE2 = TypedPlaneGeometrySort("circle2")


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-plane-geometry-v1-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - package invariant
        raise RuntimeError("typed-plane-geometry-v1 symbol registry is unavailable.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "pals.typed-plane-geometry-registry.v1"
        or payload.get("profile_id") != TYPED_PLANE_GEOMETRY_PROFILE
        or payload.get("cdbases")
        != {"standard": OPENMATH_STANDARD_CDBASE, "typed": TYPED_PLANE_GEOMETRY_OPENMATH_CDBASE}
    ):  # pragma: no cover - package invariant
        raise RuntimeError("typed-plane-geometry-v1 registry header is invalid.")
    entries = payload.get("symbols")
    if not isinstance(entries, list):  # pragma: no cover - package invariant
        raise RuntimeError("typed-plane-geometry-v1 registry has no symbols list.")
    symbols: set[_Symbol] = set()
    for entry in entries:
        if not isinstance(entry, dict):  # pragma: no cover - package invariant
            raise RuntimeError("typed-plane-geometry-v1 registry entry is invalid.")
        identity = tuple(entry.get(field) for field in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError("typed-plane-geometry-v1 registry identity is invalid.")
        symbols.add(cast(_Symbol, identity))
    if len(symbols) != len(entries):  # pragma: no cover - package invariant
        raise RuntimeError("typed-plane-geometry-v1 registry contains duplicate symbols.")
    return frozenset(symbols)


_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_plane_geometry_openmath_xml(xml: str) -> str:
    """Validate and canonicalize one closed native-plane proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("OpenMath XML exceeds the typed-plane-geometry byte bound.")
    root = validate_openmath_xml(xml)
    validate_typed_plane_geometry_openmath_root(root)
    return _canonicalize_openmath_v4_root(root)


def validate_canonical_typed_plane_geometry_openmath_xml(xml: str) -> str:
    """Accept only exact canonical bytes for this isolated profile."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError(
            "OpenMath XML is not exact typed-plane-geometry canonical bytes."
        )
    canonical = canonicalize_typed_plane_geometry_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError(
            "OpenMath XML is not exact typed-plane-geometry canonical bytes."
        )
    return canonical


def validate_typed_plane_geometry_openmath_xml(xml: str) -> None:
    """Validate one closed ``typed-plane-geometry-v1`` proposition."""
    validate_typed_plane_geometry_openmath_root(validate_openmath_xml(xml))


def validate_typed_plane_geometry_openmath_root(root: ET.Element) -> None:
    """Validate an already core-validated OpenMath root under this profile."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("OpenMath typed-plane-geometry tree exceeds 4,096 nodes.")
    parents = _openmath_parents(root)
    _validate_tree_shape(nodes, parents=parents)
    if not _contains_profile_construct(root, parents=parents):
        raise MathXMLValidationError("OpenMath XML is not a typed-plane-geometry-v1 proposition.")
    inferred = _infer_expression(list(root)[0], environment={}, parents=parents, path="root")
    if inferred != _PROP:
        raise MathXMLValidationError("typed-plane-geometry-v1 root must have sort `Prop`.")


def _validate_tree_shape(nodes: list[ET.Element], *, parents: dict[ET.Element, ET.Element]) -> None:
    for element in nodes:
        local_name = _local_name(element)
        if local_name not in _ALLOWED_ATTRIBUTES:
            raise MathXMLValidationError(
                f"OpenMath element `{local_name}` is outside typed-plane-geometry-v1."
            )
        _validate_attributes(element, local_name=local_name)
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("OpenMath typed-plane-geometry tree exceeds depth 64.")
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError(
                "OpenMath typed-plane-geometry text exceeds 20,000 code points."
            )
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError("typed-plane-geometry-v1 elements cannot have text tails.")
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError(
                "typed-plane-geometry attribute exceeds 20,000 code points."
            )
        if local_name == "OMATTR" and (
            _local_name(parents.get(element, ET.Element("invalid"))) != "OMBVAR"
            or not _is_declaration(element, parents=parents)
        ):
            raise MathXMLValidationError(
                "typed-plane-geometry-v1 permits OMATTR only as one typed OMBVAR declaration."
            )
        if local_name == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                not _is_declaration(declaration, parents=parents) for declaration in declarations
            ):
                raise MathXMLValidationError(
                    "typed-plane-geometry-v1 OMBVAR requires 1..256 typed OMV declarations."
                )
        if local_name == "OMBIND":
            binder, _variables, _body = list(element)
            symbol = _operator_symbol(binder, parents=parents)
            if (
                symbol not in {
                    (TYPED_PLANE_GEOMETRY_OPENMATH_CDBASE, _PRIVATE_CD, "forall"),
                    (TYPED_PLANE_GEOMETRY_OPENMATH_CDBASE, _PRIVATE_CD, "exists"),
                }
                or binder.get("cdbase") != TYPED_PLANE_GEOMETRY_OPENMATH_CDBASE
            ):
                raise MathXMLValidationError(
                    "typed-plane-geometry-v1 OMBIND must use a direct pals_plane_geometry binder."
                )
        if local_name == "OMA" and _local_name(list(element)[0]) != "OMS":
            raise MathXMLValidationError("typed-plane-geometry-v1 OMA head must be an OMS.")
        if local_name == "OMS":
            _validate_symbol(element, parents=parents)


def _validate_attributes(element: ET.Element, *, local_name: str) -> None:
    actual = set(element.attrib)
    unexpected = actual - _ALLOWED_ATTRIBUTES[local_name]
    if unexpected:
        raise MathXMLValidationError(
            "typed-plane-geometry-v1 "
            f"`{local_name}` does not permit attribute `{sorted(unexpected)[0]}`."
        )
    if local_name == "OMOBJ" and actual != {"version"}:
        raise MathXMLValidationError("typed-plane-geometry-v1 OMOBJ requires only `version`.")
    if local_name == "OMS" and actual != {"cdbase", "cd", "name"}:
        raise MathXMLValidationError(
            "typed-plane-geometry-v1 OMS requires direct `cdbase`, `cd`, and `name`."
        )
    if local_name == "OMV" and actual != {"name"}:
        raise MathXMLValidationError("typed-plane-geometry-v1 OMV requires only `name`.")


def _validate_symbol(element: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed-plane-geometry-v1 OMS must identify a symbol.")
    if element.get("cdbase") != symbol[0]:
        raise MathXMLValidationError(
            "typed-plane-geometry-v1 OMS must directly declare its cdbase."
        )
    if symbol not in _SYMBOL_REGISTRY:
        cdbase, cd, name = symbol
        raise MathXMLValidationError(
            f"Symbol `{cd}:{name}` with cdbase `{cdbase}` is outside typed-plane-geometry-v1."
        )


def _contains_profile_construct(root: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> bool:
    binder = False
    annotation = False
    geometry_construct = False
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        symbol = _operator_symbol(element, parents=parents)
        if symbol is None or symbol[:2] != (TYPED_PLANE_GEOMETRY_OPENMATH_CDBASE, _PRIVATE_CD):
            continue
        binder = binder or symbol[2] in _TYPED_BINDERS
        annotation = annotation or symbol[2] == "type"
        geometry_construct = geometry_construct or symbol[2] in _GEOMETRY_CONSTRUCTS
    return binder and annotation and geometry_construct


def _is_declaration(declaration: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> bool:
    if _local_name(declaration) != "OMATTR" or len(list(declaration)) != 2:
        return False
    attributes, variable = list(declaration)
    if _local_name(attributes) != "OMATP" or _local_name(variable) != "OMV":
        return False
    pairs = list(attributes)
    return (
        len(pairs) == 2
        and _local_name(pairs[0]) == "OMS"
        and _operator_symbol(pairs[0], parents=parents)
        == (TYPED_PLANE_GEOMETRY_OPENMATH_CDBASE, _PRIVATE_CD, "type")
    )


def _infer_expression(
    expression: ET.Element,
    *,
    environment: dict[str, TypedPlaneGeometrySort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> TypedPlaneGeometrySort:
    local_name = _local_name(expression)
    if local_name == "OMV":
        name = expression.get("name")
        if name is None or name not in environment:
            raise MathXMLValidationError(
                "typed-plane-geometry-v1 has a free or undeclared variable "
                f"`{name or ''}` at {path}."
            )
        return environment[name]
    if local_name == "OMI":
        value = "".join((expression.text or "").split())
        if not _INTEGER_RE.fullmatch(value):
            raise MathXMLValidationError(
                "typed-plane-geometry-v1 OMI must be one exact decimal integer literal."
            )
        return _REAL
    if local_name == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if local_name != "OMA":
        raise MathXMLValidationError(
            f"typed-plane-geometry-v1 cannot infer a sort for `{local_name}` at {path}."
        )
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(
            f"typed-plane-geometry-v1 OMA has an invalid operator at {path}."
        )
    inferred = [
        _infer_expression(
            argument,
            environment=environment,
            parents=parents,
            path=f"{path}/{index}",
        )
        for index, argument in enumerate(arguments, start=1)
    ]
    return _infer_application(symbol, inferred, path=path)


def _infer_binding(
    binding: ET.Element,
    *,
    environment: dict[str, TypedPlaneGeometrySort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> TypedPlaneGeometrySort:
    binder, variables, body = list(binding)
    symbol = _operator_symbol(binder, parents=parents)
    assert symbol is not None
    local_environment = dict(environment)
    declared: set[str] = set()
    for index, declaration in enumerate(list(variables), start=1):
        variable, sort = _parse_declaration(
            declaration, parents=parents, path=f"{path}/bind/{index}"
        )
        if variable in declared or variable in environment:
            raise MathXMLValidationError(
                f"typed-plane-geometry-v1 redeclares bound variable `{variable}` at {path}."
            )
        declared.add(variable)
        local_environment[variable] = sort
    body_sort = _infer_expression(
        body,
        environment=local_environment,
        parents=parents,
        path=f"{path}/body",
    )
    if body_sort != _PROP:
        raise MathXMLValidationError(
            f"The body of `{symbol[1]}:{symbol[2]}` must have sort `Prop`; "
            f"received `{body_sort.render()}`."
        )
    return _PROP


def _parse_declaration(
    declaration: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> tuple[str, TypedPlaneGeometrySort]:
    attributes, variable = list(declaration)
    _key, sort_expression = list(attributes)
    name = variable.get("name")
    if name is None or not name:
        raise MathXMLValidationError(
            f"typed-plane-geometry-v1 bound OMV has no name at {path}."
        )
    return name, _parse_sort(sort_expression, parents=parents, path=path)


def _parse_sort(
    expression: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> TypedPlaneGeometrySort:
    if _local_name(expression) == "OMS":
        symbol = _operator_symbol(expression, parents=parents)
        sorts = {
            (TYPED_PLANE_GEOMETRY_OPENMATH_CDBASE, _PRIVATE_CD, "Real"): _REAL,
            (TYPED_PLANE_GEOMETRY_OPENMATH_CDBASE, _PRIVATE_CD, "Vector2"): _VECTOR2,
            (TYPED_PLANE_GEOMETRY_OPENMATH_CDBASE, _PRIVATE_CD, "Point2"): _POINT2,
            (TYPED_PLANE_GEOMETRY_OPENMATH_CDBASE, _PRIVATE_CD, "Line2"): _LINE2,
            (TYPED_PLANE_GEOMETRY_OPENMATH_CDBASE, _PRIVATE_CD, "Circle2"): _CIRCLE2,
        }
        if symbol in sorts:
            return sorts[symbol]
    raise MathXMLValidationError(
        "typed-plane-geometry-v1 has an invalid type annotation at "
        f"{path}; expected an exact plane sort."
    )


def _infer_application(
    symbol: _Symbol, arguments: list[TypedPlaneGeometrySort], *, path: str
) -> TypedPlaneGeometrySort:
    cdbase, cd, name = symbol
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "relation1") and name in _RELATIONS:
        _require_arity(symbol, arguments, exact=2)
        if arguments[0] != arguments[1]:
            _require_argument(symbol, arguments, 1, arguments[0], path=path)
        return _PROP
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "logic1"):
        if name in _LOGICAL_NARY:
            _require_arity(symbol, arguments, minimum=2)
            _require_all(symbol, arguments, _PROP, path=path)
            return _PROP
        if name in _LOGICAL_BINARY:
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _PROP, path=path)
            return _PROP
        if name == "not":
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _PROP, path=path)
            return _PROP
    if (cdbase, cd) != (TYPED_PLANE_GEOMETRY_OPENMATH_CDBASE, _PRIVATE_CD):
        raise MathXMLValidationError(
            f"Unsupported typed-plane-geometry-v1 application `{cd}:{name}` at {path}."
        )
    if name in {"point2", "vector2"}:
        _require_arity(symbol, arguments, exact=2)
        _require_all(symbol, arguments, _REAL, path=path)
        return _POINT2 if name == "point2" else _VECTOR2
    if name == "vector_add":
        _require_arity(symbol, arguments, exact=2)
        _require_all(symbol, arguments, _VECTOR2, path=path)
        return _VECTOR2
    if name == "incident_point_line":
        _require_arity(symbol, arguments, exact=2)
        _require_argument(symbol, arguments, 0, _POINT2, path=path)
        _require_argument(symbol, arguments, 1, _LINE2, path=path)
        return _PROP
    if name == "incident_point_circle":
        _require_arity(symbol, arguments, exact=2)
        _require_argument(symbol, arguments, 0, _POINT2, path=path)
        _require_argument(symbol, arguments, 1, _CIRCLE2, path=path)
        return _PROP
    if name in {"parallel", "perpendicular"}:
        _require_arity(symbol, arguments, exact=2)
        _require_all(symbol, arguments, _LINE2, path=path)
        return _PROP
    if name == "distance_sq":
        _require_arity(symbol, arguments, exact=2)
        _require_all(symbol, arguments, _POINT2, path=path)
        return _REAL
    if name == "midpoint":
        _require_arity(symbol, arguments, exact=2)
        _require_all(symbol, arguments, _POINT2, path=path)
        return _POINT2
    if name == "reflect":
        _require_arity(symbol, arguments, exact=2)
        _require_argument(symbol, arguments, 0, _POINT2, path=path)
        _require_argument(symbol, arguments, 1, _LINE2, path=path)
        return _POINT2
    if name == "non_collinear":
        _require_arity(symbol, arguments, exact=3)
        _require_all(symbol, arguments, _POINT2, path=path)
        return _PROP
    raise MathXMLValidationError(
        f"Unsupported typed-plane-geometry-v1 application `{cd}:{name}` at {path}."
    )


def _require_arity(
    symbol: _Symbol,
    arguments: list[TypedPlaneGeometrySort],
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
    arguments: list[TypedPlaneGeometrySort],
    expected: TypedPlaneGeometrySort,
    *,
    path: str,
) -> None:
    for index in range(len(arguments)):
        _require_argument(symbol, arguments, index, expected, path=path)


def _require_argument(
    symbol: _Symbol,
    arguments: list[TypedPlaneGeometrySort],
    index: int,
    expected: TypedPlaneGeometrySort,
    *,
    path: str,
) -> None:
    actual = arguments[index]
    if actual == expected:
        return
    _, cd, name = symbol
    raise MathXMLValidationError(
        f"Argument {index + 1} of `{cd}:{name}` at {path} must have sort "
        f"`{expected.render()}`; received `{actual.render()}`."
    )
