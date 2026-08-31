"""Fail-closed OpenMath validation for the isolated ``typed-math-v1`` profile.

This module deliberately does not extend the generic retrieval profile.  It is
an authoring boundary for carrier-sensitive mathematics; generic Drafts keep
using :mod:`pals_agent.openmath` unchanged.
"""

from __future__ import annotations

import json
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

TYPED_MATH_OPENMATH_CDBASE = "urn:pals:openmath:typed-math:v1"
TYPED_MATH_PROFILE = "typed-math-v1"

_TypedSortName = Literal[
    "prop",
    "nat",
    "group",
    "comm_ring",
    "integral_domain",
    "element",
]
_StructureSortName = Literal["group", "comm_ring", "integral_domain"]


@dataclass(frozen=True, slots=True)
class TypedSort:
    """One structural sort inferred by ``typed-math-v1``."""

    name: _TypedSortName
    carrier: str | None = None

    def render(self) -> str:
        if self.name == "element":
            assert self.carrier is not None
            return f"Elem({self.carrier})"
        return {
            "prop": "Prop",
            "nat": "Nat",
            "group": "Group",
            "comm_ring": "CommRing",
            "integral_domain": "IntegralDomain",
        }[self.name]


_PROP = TypedSort("prop")
_NAT = TypedSort("nat")
_GROUP = TypedSort("group")
_COMM_RING = TypedSort("comm_ring")
_INTEGRAL_DOMAIN = TypedSort("integral_domain")

_Symbol = tuple[str, str, str]
_TYPED_BINDERS = frozenset({"forall", "exists"})
_LOGICAL_APPLICATIONS = frozenset({"and", "or", "implies", "equivalent"})
_UNARY_LOGICAL_APPLICATIONS = frozenset({"not"})
_RELATION_APPLICATIONS = frozenset({"eq", "neq"})
_GROUP_STRUCTURE_SORTS: frozenset[_StructureSortName] = frozenset({"group"})
_RING_STRUCTURE_SORTS: frozenset[_StructureSortName] = frozenset({"comm_ring", "integral_domain"})


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-math-v1-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - packaging invariant
        raise RuntimeError("typed-math-v1 symbol registry is unavailable.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "pals.typed-math-registry.v1"
        or payload.get("profile_id") != TYPED_MATH_PROFILE
        or payload.get("cdbases")
        != {
            "standard": OPENMATH_STANDARD_CDBASE,
            "typed": TYPED_MATH_OPENMATH_CDBASE,
        }
    ):  # pragma: no cover - packaging invariant
        raise RuntimeError("typed-math-v1 symbol registry header is invalid.")
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):  # pragma: no cover - packaging invariant
        raise RuntimeError("typed-math-v1 symbol registry has no symbols list.")
    identities: set[_Symbol] = set()
    for entry in symbols:
        if not isinstance(entry, dict):  # pragma: no cover - packaging invariant
            raise RuntimeError("typed-math-v1 symbol registry entry is invalid.")
        identity = tuple(entry.get(field) for field in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError("typed-math-v1 symbol registry identity is invalid.")
        identities.add(cast(_Symbol, identity))
    if len(identities) != len(symbols):  # pragma: no cover - packaging invariant
        raise RuntimeError("typed-math-v1 symbol registry contains duplicates.")
    return frozenset(identities)


_TYPED_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_math_openmath_xml(xml: str) -> str:
    """Validate and canonicalize one closed ``typed-math-v1`` proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("OpenMath XML exceeds the typed-math byte bound.")
    root = validate_openmath_xml(xml)
    validate_typed_math_openmath_root(root)
    return _canonicalize_openmath_v4_root(root)


def validate_canonical_typed_math_openmath_xml(xml: str) -> str:
    """Accept only exact typed-math canonical bytes."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError("OpenMath XML is not exact typed-math canonical bytes.")
    canonical = canonicalize_typed_math_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError("OpenMath XML is not exact typed-math canonical bytes.")
    return canonical


def validate_typed_math_openmath_xml(xml: str) -> None:
    """Validate one closed ``typed-math-v1`` proposition without canonicalizing it."""
    root = validate_openmath_xml(xml)
    validate_typed_math_openmath_root(root)


def validate_typed_math_openmath_root(root: ET.Element) -> None:
    """Validate an already core-validated OpenMath root for this profile."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("OpenMath typed-math tree exceeds 4,096 nodes.")
    parents = _openmath_parents(root)
    _validate_typed_tree_shape(root, nodes=nodes, parents=parents)
    if not _contains_typed_construct(root, parents=parents):
        raise MathXMLValidationError("OpenMath XML is not a typed-math-v1 proposition.")
    expression = list(root)[0]
    inferred = _infer_expression(expression, environment={}, parents=parents, path="root")
    if inferred != _PROP:
        raise MathXMLValidationError("typed-math-v1 root must have sort `Prop`.")


def _validate_typed_tree_shape(
    root: ET.Element,
    *,
    nodes: list[ET.Element],
    parents: dict[ET.Element, ET.Element],
) -> None:
    allowed = {"OMOBJ", "OMS", "OMV", "OMI", "OMA", "OMBIND", "OMBVAR", "OMATTR", "OMATP"}
    for element in nodes:
        local_name = _local_name(element)
        if local_name not in allowed:
            raise MathXMLValidationError(
                f"OpenMath element `{local_name}` is outside typed-math-v1."
            )
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("OpenMath typed-math tree exceeds depth 64.")
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError("OpenMath typed-math text exceeds 20,000 code points.")
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError("OpenMath typed-math elements cannot have text tails.")
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError(
                "OpenMath typed-math attribute exceeds 20,000 code points."
            )

        if local_name == "OMATTR":
            parent = parents.get(element)
            if (
                parent is None
                or _local_name(parent) != "OMBVAR"
                or not _is_typed_declaration_annotation(element, parents=parents)
            ):
                raise MathXMLValidationError(
                    "typed-math-v1 permits OMATTR only as one typed OMBVAR declaration."
                )
        if local_name == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                not _is_typed_declaration_annotation(declaration, parents=parents)
                for declaration in declarations
            ):
                raise MathXMLValidationError(
                    "typed-math-v1 OMBVAR requires 1..256 typed OMV declarations."
                )
        if local_name == "OMBIND":
            binder, _variables, _body = list(element)
            symbol = _operator_symbol(binder, parents=parents)
            if (
                symbol is None
                or symbol
                != (
                    TYPED_MATH_OPENMATH_CDBASE,
                    "typed1",
                    symbol[2],
                )
                or symbol[2] not in _TYPED_BINDERS
            ):
                raise MathXMLValidationError(
                    "typed-math-v1 OMBIND must use typed1:forall or typed1:exists."
                )
        if local_name == "OMA":
            children = list(element)
            if _local_name(children[0]) != "OMS":
                raise MathXMLValidationError("typed-math-v1 OMA head must be an OMS.")

        if local_name == "OMS":
            _validate_typed_symbol(element, parents=parents)


def _validate_typed_symbol(
    element: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed-math-v1 OMS must identify a symbol.")
    direct_cdbase = element.get("cdbase")
    if symbol[0] == TYPED_MATH_OPENMATH_CDBASE and direct_cdbase != symbol[0]:
        raise MathXMLValidationError("typed-math-v1 OMS must directly declare its typed cdbase.")
    if symbol[0] == OPENMATH_STANDARD_CDBASE and direct_cdbase is None:
        ancestor = parents.get(element)
        while ancestor is not None:
            if "cdbase" in ancestor.attrib:
                raise MathXMLValidationError(
                    "Standard typed-math-v1 OMS may omit cdbase only without inherited cdbase."
                )
            ancestor = parents.get(ancestor)
    if symbol in _TYPED_SYMBOL_REGISTRY:
        return
    cdbase, cd, name = symbol
    raise MathXMLValidationError(
        f"Symbol `{cd}:{name}` with cdbase `{cdbase}` is outside typed-math-v1."
    )


def _contains_typed_construct(
    root: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> bool:
    has_typed_binder = False
    has_type_annotation = False
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        symbol = _operator_symbol(element, parents=parents)
        if symbol is None or symbol[0:2] != (TYPED_MATH_OPENMATH_CDBASE, "typed1"):
            continue
        if symbol[2] in _TYPED_BINDERS:
            has_typed_binder = True
        if symbol[2] == "type":
            has_type_annotation = True
    return has_typed_binder and has_type_annotation


def _is_typed_declaration_annotation(
    declaration: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> bool:
    if _local_name(declaration) != "OMATTR" or len(list(declaration)) != 2:
        return False
    attributes, variable = list(declaration)
    if _local_name(attributes) != "OMATP" or _local_name(variable) != "OMV":
        return False
    pairs = list(attributes)
    if len(pairs) != 2 or _local_name(pairs[0]) != "OMS":
        return False
    return _operator_symbol(pairs[0], parents=parents) == (
        TYPED_MATH_OPENMATH_CDBASE,
        "typed1",
        "type",
    )


def _infer_expression(
    expression: ET.Element,
    *,
    environment: dict[str, TypedSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> TypedSort:
    local_name = _local_name(expression)
    if local_name == "OMV":
        name = expression.get("name")
        if name is None or name not in environment:
            raise MathXMLValidationError(
                f"typed-math-v1 has a free or undeclared variable `{name or ''}` at {path}."
            )
        declared_sort = environment[name]
        if declared_sort.name in {"group", "comm_ring", "integral_domain"}:
            return TypedSort(declared_sort.name, name)
        return declared_sort
    if local_name == "OMI":
        value = "".join((expression.text or "").split())
        if value.startswith("-"):
            raise MathXMLValidationError(
                "typed-math-v1 group/ring core does not admit negative OMI literals."
            )
        return _NAT
    if local_name == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if local_name != "OMA":
        raise MathXMLValidationError(
            f"typed-math-v1 cannot infer a sort for `{local_name}` at {path}."
        )

    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(f"typed-math-v1 OMA has an invalid operator at {path}.")
    argument_sorts = [
        _infer_expression(
            argument, environment=environment, parents=parents, path=f"{path}/{index}"
        )
        for index, argument in enumerate(arguments, start=1)
    ]
    return _infer_application(symbol, argument_sorts, path=path)


def _infer_binding(
    binding: ET.Element,
    *,
    environment: dict[str, TypedSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> TypedSort:
    binder, variables, body = list(binding)
    symbol = _operator_symbol(binder, parents=parents)
    assert symbol is not None
    local_environment = dict(environment)
    declared: set[str] = set()
    for index, declaration in enumerate(list(variables), start=1):
        name, sort = _parse_declaration(
            declaration,
            environment=local_environment,
            parents=parents,
            path=f"{path}/bind/{index}",
        )
        if name in declared or name in environment:
            raise MathXMLValidationError(
                f"typed-math-v1 redeclares bound variable `{name}` at {path}."
            )
        declared.add(name)
        local_environment[name] = sort
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
    environment: dict[str, TypedSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> tuple[str, TypedSort]:
    attributes, variable = list(declaration)
    _key, sort_expression = list(attributes)
    name = variable.get("name")
    if name is None or not name:
        raise MathXMLValidationError(f"typed-math-v1 bound OMV is missing `name` at {path}.")
    return name, _parse_sort(sort_expression, environment=environment, parents=parents, path=path)


def _parse_sort(
    expression: ET.Element,
    *,
    environment: dict[str, TypedSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> TypedSort:
    if _local_name(expression) == "OMS":
        symbol = _operator_symbol(expression, parents=parents)
        mapping = {
            (TYPED_MATH_OPENMATH_CDBASE, "algebra1", "Group"): _GROUP,
            (TYPED_MATH_OPENMATH_CDBASE, "algebra1", "CommRing"): _COMM_RING,
            (TYPED_MATH_OPENMATH_CDBASE, "algebra1", "IntegralDomain"): _INTEGRAL_DOMAIN,
        }
        if symbol is not None:
            sort = mapping.get(symbol)
            if sort is not None:
                return sort
    if _local_name(expression) == "OMA":
        operator, *arguments = list(expression)
        if (
            _operator_symbol(operator, parents=parents)
            == (
                TYPED_MATH_OPENMATH_CDBASE,
                "typed1",
                "Elem",
            )
            and len(arguments) == 1
            and _local_name(arguments[0]) == "OMV"
        ):
            carrier = arguments[0].get("name")
            carrier_sort = environment.get(carrier or "")
            if carrier_sort is not None and carrier_sort.name in {
                "group",
                "comm_ring",
                "integral_domain",
            }:
                assert carrier is not None
                return TypedSort("element", carrier)
    raise MathXMLValidationError(
        f"typed-math-v1 has an invalid type annotation at {path}; expected a supported SortExpr."
    )


def _infer_application(
    symbol: _Symbol,
    arguments: list[TypedSort],
    *,
    path: str,
) -> TypedSort:
    cdbase, cd, name = symbol
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "relation1") and name in _RELATION_APPLICATIONS:
        _require_arity(symbol, arguments, exact=2)
        if arguments[0] != arguments[1]:
            raise MathXMLValidationError(
                f"Argument 2 of `{cd}:{name}` at {path} must have sort "
                f"`{arguments[0].render()}`; received `{arguments[1].render()}`."
            )
        return _PROP
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "logic1"):
        if name in _LOGICAL_APPLICATIONS:
            _require_arity(
                symbol,
                arguments,
                minimum=2,
                maximum=2 if name in {"implies", "equivalent"} else None,
            )
            _require_all(symbol, arguments, _PROP, path=path)
            return _PROP
        if name in _UNARY_LOGICAL_APPLICATIONS:
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _PROP, path=path)
            return _PROP
    if (cdbase, cd) == (TYPED_MATH_OPENMATH_CDBASE, "typed1") and name == "nat_cast":
        _require_arity(symbol, arguments, exact=2)
        _require_structure_argument(symbol, arguments, 0, path=path, allowed=_RING_STRUCTURE_SORTS)
        _require_argument(symbol, arguments, 1, _NAT, path=path)
        carrier = _require_carrier_name(arguments[0], symbol=symbol, index=0, path=path)
        return TypedSort("element", carrier)
    if (cdbase, cd) == (TYPED_MATH_OPENMATH_CDBASE, "algebra1"):
        if name == "mul":
            return _infer_group_operation(symbol, arguments, count=3, path=path)
        if name == "inv":
            return _infer_group_operation(symbol, arguments, count=2, path=path)
        if name == "one":
            _require_arity(symbol, arguments, exact=1)
            _require_structure_argument(
                symbol, arguments, 0, path=path, allowed=_GROUP_STRUCTURE_SORTS
            )
            return TypedSort(
                "element", _require_carrier_name(arguments[0], symbol=symbol, index=0, path=path)
            )
        if name in {"ring_add", "ring_mul"}:
            return _infer_ring_operation(symbol, arguments, count=3, path=path)
        if name in {"ring_neg"}:
            return _infer_ring_operation(symbol, arguments, count=2, path=path)
        if name in {"ring_zero", "ring_one"}:
            _require_arity(symbol, arguments, exact=1)
            _require_structure_argument(
                symbol, arguments, 0, path=path, allowed=_RING_STRUCTURE_SORTS
            )
            return TypedSort(
                "element", _require_carrier_name(arguments[0], symbol=symbol, index=0, path=path)
            )
    raise MathXMLValidationError(f"Unsupported typed-math-v1 application `{cd}:{name}` at {path}.")


def _infer_group_operation(
    symbol: _Symbol,
    arguments: list[TypedSort],
    *,
    count: int,
    path: str,
) -> TypedSort:
    _require_arity(symbol, arguments, exact=count)
    _require_structure_argument(symbol, arguments, 0, path=path, allowed=_GROUP_STRUCTURE_SORTS)
    carrier = _require_carrier_name(arguments[0], symbol=symbol, index=0, path=path)
    for index in range(1, count):
        _require_argument(symbol, arguments, index, TypedSort("element", carrier), path=path)
    return TypedSort("element", carrier)


def _infer_ring_operation(
    symbol: _Symbol,
    arguments: list[TypedSort],
    *,
    count: int,
    path: str,
) -> TypedSort:
    _require_arity(symbol, arguments, exact=count)
    _require_structure_argument(symbol, arguments, 0, path=path, allowed=_RING_STRUCTURE_SORTS)
    carrier = _require_carrier_name(arguments[0], symbol=symbol, index=0, path=path)
    for index in range(1, count):
        _require_argument(symbol, arguments, index, TypedSort("element", carrier), path=path)
    return TypedSort("element", carrier)


def _require_arity(
    symbol: _Symbol,
    arguments: list[TypedSort],
    *,
    exact: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> None:
    valid = (
        (exact is None or len(arguments) == exact)
        and (minimum is None or len(arguments) >= minimum)
        and (maximum is None or len(arguments) <= maximum)
    )
    if valid:
        return
    _, cd, name = symbol
    expectation = str(exact) if exact is not None else f"{minimum or 0}..{maximum or 'n'}"
    raise MathXMLValidationError(
        f"`{cd}:{name}` requires {expectation} arguments; received {len(arguments)}."
    )


def _require_all(
    symbol: _Symbol,
    arguments: list[TypedSort],
    expected: TypedSort,
    *,
    path: str,
) -> None:
    for index in range(len(arguments)):
        _require_argument(symbol, arguments, index, expected, path=path)


def _require_argument(
    symbol: _Symbol,
    arguments: list[TypedSort],
    index: int,
    expected: TypedSort,
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


def _require_structure_argument(
    symbol: _Symbol,
    arguments: list[TypedSort],
    index: int,
    *,
    path: str,
    allowed: frozenset[_StructureSortName],
) -> None:
    actual = arguments[index]
    if actual.name in allowed:
        return
    _, cd, name = symbol
    expected = " or ".join(
        sorted(
            {
                "group": "Group",
                "comm_ring": "CommRing",
                "integral_domain": "IntegralDomain",
            }[sort]
            for sort in allowed
        )
    )
    raise MathXMLValidationError(
        f"Argument {index + 1} of `{cd}:{name}` at {path} must have sort "
        f"`{expected}`; received `{actual.render()}`."
    )


def _require_carrier_name(
    structure: TypedSort,
    *,
    symbol: _Symbol,
    index: int,
    path: str,
) -> str:
    if structure.carrier is not None:
        return structure.carrier
    _, cd, name = symbol
    raise MathXMLValidationError(
        f"Argument {index + 1} of `{cd}:{name}` at {path} must be a bound structure variable."
    )
