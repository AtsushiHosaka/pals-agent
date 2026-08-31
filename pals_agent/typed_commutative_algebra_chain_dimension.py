"""Fail-closed validation for the bounded CA-6 chain/dimension profile.

The profile has an intentionally small semantic surface: it represents typed
ring and ideal carriers plus the Noetherian/Artinian/finite-generation and
Krull-dimension-at-most-zero predicates.  It is not a generic dimension or
chain language.
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

TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_OPENMATH_CDBASE = (
    "urn:pals:openmath:typed-commutative-algebra-chain-dimension:v1"
)
TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_PROFILE = "typed-commutative-algebra-chain-dimension-v1"

_SortName = Literal["prop", "comm_ring", "ideal"]
_Symbol = tuple[str, str, str]
_PROP: ChainDimensionSort
_BINDERS = frozenset({"forall", "exists"})
_LOGICAL_BINARY = frozenset({"and", "implies"})
_ALLOWED_ATTRIBUTES: dict[str, frozenset[str]] = {
    "OMOBJ": frozenset({"version"}),
    "OMS": frozenset({"cdbase", "cd", "name"}),
    "OMV": frozenset({"name"}),
    "OMA": frozenset(),
    "OMBIND": frozenset(),
    "OMBVAR": frozenset(),
    "OMATTR": frozenset(),
    "OMATP": frozenset(),
}


@dataclass(frozen=True, slots=True)
class ChainDimensionSort:
    """A sort whose ideal carrier is named rather than inferred by coercion."""

    name: _SortName
    carrier: str | None = None

    def render(self) -> str:
        if self.name == "prop":
            return "Prop"
        if self.name == "comm_ring":
            return "CommRing"
        return f"Ideal({self.carrier or '?'})"


_PROP = ChainDimensionSort("prop")


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-commutative-algebra-chain-dimension-v1-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - package invariant
        raise RuntimeError("typed chain/dimension registry is unavailable") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version")
        != "pals.typed-commutative-algebra-chain-dimension-registry.v1"
        or payload.get("profile_id") != TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_PROFILE
        or payload.get("cdbases")
        != {
            "standard": OPENMATH_STANDARD_CDBASE,
            "typed": TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_OPENMATH_CDBASE,
        }
        or not isinstance(payload.get("symbols"), list)
    ):  # pragma: no cover - package invariant
        raise RuntimeError("typed chain/dimension registry header is invalid")
    symbols: set[_Symbol] = set()
    for entry in payload["symbols"]:
        if not isinstance(entry, dict):  # pragma: no cover - package invariant
            raise RuntimeError("typed chain/dimension registry entry is invalid")
        identity = tuple(entry.get(key) for key in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError("typed chain/dimension registry identity is invalid")
        symbols.add(cast(_Symbol, identity))
    if len(symbols) != len(payload["symbols"]):  # pragma: no cover - package invariant
        raise RuntimeError("typed chain/dimension registry contains duplicate symbols")
    return frozenset(symbols)


_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_commutative_algebra_chain_dimension_openmath_xml(xml: str) -> str:
    """Validate and exact-canonicalize one closed CA-6 proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("OpenMath XML exceeds the typed chain/dimension byte bound.")
    root = validate_openmath_xml(xml)
    validate_typed_commutative_algebra_chain_dimension_openmath_root(root)
    return _canonicalize_openmath_v4_root(root)


def validate_canonical_typed_commutative_algebra_chain_dimension_openmath_xml(xml: str) -> str:
    """Accept only exact v4 canonical bytes for this isolated profile."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError("OpenMath XML is not exact chain/dimension canonical bytes.")
    canonical = canonicalize_typed_commutative_algebra_chain_dimension_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError("OpenMath XML is not exact chain/dimension canonical bytes.")
    return canonical


def validate_typed_commutative_algebra_chain_dimension_openmath_xml(xml: str) -> None:
    """Validate a closed profile proposition without canonicalizing it."""
    validate_typed_commutative_algebra_chain_dimension_openmath_root(validate_openmath_xml(xml))


def validate_typed_commutative_algebra_chain_dimension_openmath_root(root: ET.Element) -> None:
    """Validate one already core-valid OpenMath root fail-closed."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("OpenMath typed chain/dimension tree exceeds 4,096 nodes.")
    parents = _openmath_parents(root)
    _validate_tree_shape(nodes, parents=parents)
    if len(list(root)) != 1:
        raise MathXMLValidationError("typed chain/dimension OMOBJ must contain one expression.")
    if not _contains_profile_construct(root, parents=parents):
        raise MathXMLValidationError("OpenMath XML is not a typed chain/dimension proposition.")
    _require_sort(
        "typed chain/dimension root",
        _infer_expression(list(root)[0], environment={}, parents=parents, path="root"),
        _PROP,
        path="root",
    )


def _validate_tree_shape(nodes: list[ET.Element], *, parents: dict[ET.Element, ET.Element]) -> None:
    for element in nodes:
        local = _local_name(element)
        if local not in _ALLOWED_ATTRIBUTES:
            raise MathXMLValidationError(
                f"OpenMath element `{local}` is outside typed chain/dimension."
            )
        unexpected = set(element.attrib) - _ALLOWED_ATTRIBUTES[local]
        if unexpected:
            raise MathXMLValidationError(
                f"typed chain/dimension `{local}` does not permit `{sorted(unexpected)[0]}`."
            )
        if local == "OMOBJ" and set(element.attrib) != {"version"}:
            raise MathXMLValidationError("typed chain/dimension OMOBJ requires only `version`.")
        if local == "OMS" and not {"cd", "name"}.issubset(element.attrib):
            raise MathXMLValidationError("typed chain/dimension OMS requires `cd` and `name`.")
        if local == "OMV" and set(element.attrib) != {"name"}:
            raise MathXMLValidationError("typed chain/dimension OMV requires only `name`.")
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("OpenMath typed chain/dimension tree exceeds depth 64.")
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError("typed chain/dimension elements cannot have text tails.")
        if local == "OMATTR" and (
            _local_name(parents.get(element, ET.Element("invalid"))) != "OMBVAR"
            or not _is_type_declaration(element, parents=parents)
        ):
            raise MathXMLValidationError(
                "typed chain/dimension permits OMATTR only as a typed OMBVAR declaration."
            )
        if local == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                not _is_type_declaration(item, parents=parents) for item in declarations
            ):
                raise MathXMLValidationError(
                    "typed chain/dimension OMBVAR requires 1..256 typed OMV declarations."
                )
        if local == "OMBIND":
            children = list(element)
            symbol = _operator_symbol(children[0], parents=parents) if len(children) == 3 else None
            if (
                symbol is None
                or symbol[:2]
                != (TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_OPENMATH_CDBASE, "typed1")
                or symbol[2] not in _BINDERS
                or children[0].get("cdbase")
                != TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_OPENMATH_CDBASE
            ):
                raise MathXMLValidationError(
                    "typed chain/dimension OMBIND must use typed1:forall or typed1:exists."
                )
        if local == "OMA":
            children = list(element)
            if not children or _local_name(children[0]) != "OMS":
                raise MathXMLValidationError("typed chain/dimension OMA head must be an OMS.")
        if local == "OMS":
            _validate_symbol(element, parents=parents)


def _validate_symbol(element: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed chain/dimension OMS must identify a symbol.")
    direct_cdbase = element.get("cdbase")
    if symbol[0] == TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_OPENMATH_CDBASE:
        if direct_cdbase != symbol[0]:
            raise MathXMLValidationError(
                "typed chain/dimension OMS must directly declare typed cdbase."
            )
    elif symbol[0] == OPENMATH_STANDARD_CDBASE and direct_cdbase is None:
        ancestor = parents.get(element)
        while ancestor is not None:
            if "cdbase" in ancestor.attrib:
                raise MathXMLValidationError(
                    "Standard chain/dimension OMS may omit cdbase only without inheritance."
                )
            ancestor = parents.get(ancestor)
    if symbol not in _SYMBOL_REGISTRY:
        raise MathXMLValidationError(
            f"Symbol `{symbol[1]}:{symbol[2]}` is outside typed chain/dimension."
        )


def _contains_profile_construct(root: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> bool:
    typed_binder = False
    typed_annotation = False
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        symbol = _operator_symbol(element, parents=parents)
        if symbol is None or symbol[0] != TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_OPENMATH_CDBASE:
            continue
        typed_binder |= symbol[1:] in {("typed1", "forall"), ("typed1", "exists")}
        typed_annotation |= symbol[1:] == ("typed1", "type")
    return typed_binder and typed_annotation


def _is_type_declaration(declaration: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> bool:
    if _local_name(declaration) != "OMATTR" or len(list(declaration)) != 2:
        return False
    attributes, variable = list(declaration)
    if _local_name(attributes) != "OMATP" or _local_name(variable) != "OMV":
        return False
    pair = list(attributes)
    return (
        len(pair) == 2
        and _local_name(pair[0]) == "OMS"
        and _operator_symbol(pair[0], parents=parents)
        == (TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_OPENMATH_CDBASE, "typed1", "type")
    )


def _infer_expression(
    expression: ET.Element,
    *,
    environment: dict[str, ChainDimensionSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> ChainDimensionSort:
    local = _local_name(expression)
    if local == "OMV":
        name = expression.get("name")
        if name is None or name not in environment:
            raise MathXMLValidationError(
                f"typed chain/dimension has a free or undeclared variable `{name or ''}` at {path}."
            )
        declared = environment[name]
        return ChainDimensionSort("comm_ring", name) if declared.name == "comm_ring" else declared
    if local == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if local != "OMA":
        raise MathXMLValidationError(f"cannot infer a sort for `{local}` at {path}.")
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(f"typed chain/dimension OMA has invalid operator at {path}.")
    return _infer_application(
        symbol,
        [
            _infer_expression(
                argument, environment=environment, parents=parents, path=f"{path}/{i}"
            )
            for i, argument in enumerate(arguments, start=1)
        ],
        path=path,
    )


def _infer_binding(
    binding: ET.Element,
    *,
    environment: dict[str, ChainDimensionSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> ChainDimensionSort:
    _binder, variables, body = list(binding)
    local_environment = dict(environment)
    declared: set[str] = set()
    for index, declaration in enumerate(list(variables), start=1):
        name, sort = _parse_declaration(
            declaration, environment=local_environment, parents=parents, path=f"{path}/bind/{index}"
        )
        if name in declared or name in environment:
            raise MathXMLValidationError(f"typed chain/dimension redeclares `{name}` at {path}.")
        declared.add(name)
        local_environment[name] = sort
    _require_sort(
        "typed binder body",
        _infer_expression(
            body, environment=local_environment, parents=parents, path=f"{path}/body"
        ),
        _PROP,
        path=path,
    )
    return _PROP


def _parse_declaration(
    declaration: ET.Element,
    *,
    environment: dict[str, ChainDimensionSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> tuple[str, ChainDimensionSort]:
    attributes, variable = list(declaration)
    _type, sort_expression = list(attributes)
    name = variable.get("name")
    if name is None or not name:
        raise MathXMLValidationError(f"typed chain/dimension bound OMV misses name at {path}.")
    return name, _parse_sort(sort_expression, environment=environment, parents=parents, path=path)


def _parse_sort(
    expression: ET.Element,
    *,
    environment: dict[str, ChainDimensionSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> ChainDimensionSort:
    if _local_name(expression) == "OMS" and _operator_symbol(expression, parents=parents) == (
        TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_OPENMATH_CDBASE,
        "chain1",
        "CommRing",
    ):
        return ChainDimensionSort("comm_ring")
    if _local_name(expression) == "OMA":
        operator, *arguments = list(expression)
        if (
            _operator_symbol(operator, parents=parents)
            == (TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_OPENMATH_CDBASE, "chain1", "Ideal")
            and len(arguments) == 1
            and _local_name(arguments[0]) == "OMV"
        ):
            carrier = arguments[0].get("name")
            if (
                environment.get(carrier or "") is not None
                and environment[carrier or ""].name == "comm_ring"
            ):
                assert carrier is not None
                return ChainDimensionSort("ideal", carrier)
    raise MathXMLValidationError(
        f"invalid type annotation at {path}; expected CommRing or Ideal(R)."
    )


def _infer_application(
    symbol: _Symbol, arguments: list[ChainDimensionSort], *, path: str
) -> ChainDimensionSort:
    cdbase, cd, name = symbol
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "relation1") and name == "eq":
        _require_arity(symbol, arguments, 2)
        if arguments[0] != arguments[1]:
            _raise_expected(symbol, 1, arguments[1], arguments[0].render(), path=path)
        return _PROP
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "logic1"):
        if name in _LOGICAL_BINARY:
            _require_arity(symbol, arguments, 2)
            _require_all(symbol, arguments, _PROP, path=path)
            return _PROP
        if name == "not":
            _require_arity(symbol, arguments, 1)
            _require_argument(symbol, arguments, 0, _PROP, path=path)
            return _PROP
    if (cdbase, cd) != (TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_OPENMATH_CDBASE, "chain1"):
        raise MathXMLValidationError(
            f"unsupported chain/dimension application `{cd}:{name}` at {path}."
        )
    if name in {
        "NoetherianRing",
        "ArtinianRing",
        "KrullDimLEZero",
        "Field",
        "HilbertNoetherian",
        "IteratedHilbertNoetherian",
    }:
        _require_ring(symbol, arguments, exact=1, path=path)
        return _PROP
    if name in {"IdealFG", "PrimeIdeal", "MaximalIdeal"}:
        carrier = _require_ring(symbol, arguments, exact=2, path=path)
        _require_argument(symbol, arguments, 1, ChainDimensionSort("ideal", carrier), path=path)
        return _PROP
    if name in {"IdealSum", "IdealInf", "IdealProduct"}:
        carrier = _require_ring(symbol, arguments, exact=3, path=path)
        _require_ideal_tail(symbol, arguments, carrier=carrier, start=1, path=path)
        return ChainDimensionSort("ideal", carrier)
    if name == "IdealRadical":
        carrier = _require_ring(symbol, arguments, exact=2, path=path)
        _require_ideal_tail(symbol, arguments, carrier=carrier, start=1, path=path)
        return ChainDimensionSort("ideal", carrier)
    raise MathXMLValidationError(
        f"unsupported chain/dimension application `{cd}:{name}` at {path}."
    )


def _require_ring(
    symbol: _Symbol, arguments: list[ChainDimensionSort], *, exact: int, path: str
) -> str:
    _require_arity(symbol, arguments, exact)
    first = arguments[0]
    if first.name != "comm_ring" or first.carrier is None:
        _raise_expected(symbol, 0, first, "CommRing", path=path)
    assert first.carrier is not None
    return first.carrier


def _require_ideal_tail(
    symbol: _Symbol, arguments: list[ChainDimensionSort], *, carrier: str, start: int, path: str
) -> None:
    for index in range(start, len(arguments)):
        _require_argument(symbol, arguments, index, ChainDimensionSort("ideal", carrier), path=path)


def _require_arity(symbol: _Symbol, arguments: list[ChainDimensionSort], exact: int) -> None:
    if len(arguments) == exact:
        return
    raise MathXMLValidationError(
        f"`{symbol[1]}:{symbol[2]}` requires {exact} arguments; received {len(arguments)}."
    )


def _require_all(
    symbol: _Symbol, arguments: list[ChainDimensionSort], expected: ChainDimensionSort, *, path: str
) -> None:
    for index in range(len(arguments)):
        _require_argument(symbol, arguments, index, expected, path=path)


def _require_argument(
    symbol: _Symbol,
    arguments: list[ChainDimensionSort],
    index: int,
    expected: ChainDimensionSort,
    *,
    path: str,
) -> None:
    if arguments[index] != expected:
        _raise_expected(symbol, index, arguments[index], expected.render(), path=path)


def _raise_expected(
    symbol: _Symbol, index: int, actual: ChainDimensionSort, expected: str, *, path: str
) -> None:
    raise MathXMLValidationError(
        f"Argument {index + 1} of `{symbol[1]}:{symbol[2]}` at {path} must have sort "
        f"`{expected}`; received `{actual.render()}`."
    )


def _require_sort(
    label: str, actual: ChainDimensionSort, expected: ChainDimensionSort, *, path: str
) -> None:
    if actual != expected:
        raise MathXMLValidationError(
            f"{label} at {path} must have sort `{expected.render()}`; received `{actual.render()}`."
        )
