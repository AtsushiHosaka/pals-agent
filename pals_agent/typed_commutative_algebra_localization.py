"""Fail-closed OpenMath validation for the localization core of commutative algebra.

This profile is intentionally separate from ``typed-commutative-algebra-v1``.
It models exactly one explicit commutative ring, submonoid, and localization
carrier per proposition; generic OpenMath, quotient rings, and module
localizations are outside its language.
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

TYPED_COMMUTATIVE_ALGEBRA_LOCALIZATION_OPENMATH_CDBASE = (
    "urn:pals:openmath:typed-commutative-algebra-localization:v1"
)
TYPED_COMMUTATIVE_ALGEBRA_LOCALIZATION_PROFILE = "typed-commutative-algebra-localization-v1"

_Kind = Literal[
    "prop",
    "ring",
    "submonoid",
    "submonoid_element",
    "localized_ring",
    "ideal",
    "element",
]
_Symbol = tuple[str, str, str]
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
_BINDERS = frozenset({"forall", "exists"})
_TYPED = TYPED_COMMUTATIVE_ALGEBRA_LOCALIZATION_OPENMATH_CDBASE


@dataclass(frozen=True, slots=True)
class LocalizationSort:
    """A dependent sort with explicit source ring and submonoid names."""

    kind: _Kind
    carrier: str | None = None
    ring: str | None = None
    submonoid: str | None = None

    def render(self) -> str:
        if self.kind == "prop":
            return "Prop"
        if self.kind == "ring":
            return "CommRing"
        if self.kind == "submonoid":
            return f"Submonoid({self.ring or '?'})"
        if self.kind == "submonoid_element":
            return f"SubmonoidElem({self.ring or '?'},{self.submonoid or '?'})"
        if self.kind == "localized_ring":
            return f"Localization({self.ring or '?'},{self.submonoid or '?'})"
        if self.kind == "ideal":
            return f"Ideal({self.carrier or '?'})"
        return f"Elem({self.carrier or '?'})"


_PROP = LocalizationSort("prop")


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-commutative-algebra-localization-v1-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - packaging invariant
        raise RuntimeError(
            "typed commutative-algebra localization registry is unavailable"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version")
        != "pals.typed-commutative-algebra-localization-registry.v1"
        or payload.get("profile_id") != TYPED_COMMUTATIVE_ALGEBRA_LOCALIZATION_PROFILE
        or payload.get("cdbases") != {"standard": OPENMATH_STANDARD_CDBASE, "typed": _TYPED}
        or not isinstance(payload.get("symbols"), list)
    ):  # pragma: no cover - packaging invariant
        raise RuntimeError("typed commutative-algebra localization registry header is invalid")
    entries: set[_Symbol] = set()
    for raw_entry in payload["symbols"]:
        if not isinstance(raw_entry, dict):  # pragma: no cover - packaging invariant
            raise RuntimeError("typed commutative-algebra localization registry entry is invalid")
        identity = tuple(raw_entry.get(key) for key in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError(
                "typed commutative-algebra localization registry identity is invalid"
            )
        entries.add(cast(_Symbol, identity))
    if len(entries) != len(payload["symbols"]):  # pragma: no cover - packaging invariant
        raise RuntimeError("typed commutative-algebra localization registry contains duplicates")
    return frozenset(entries)


_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_commutative_algebra_localization_openmath_xml(xml: str) -> str:
    """Validate and return exact C14N-v4 bytes for one closed proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError(
            "typed commutative-algebra localization XML exceeds 65,536 bytes"
        )
    root = validate_openmath_xml(xml)
    validate_typed_commutative_algebra_localization_openmath_root(root)
    return _canonicalize_openmath_v4_root(root)


def validate_canonical_typed_commutative_algebra_localization_openmath_xml(xml: str) -> str:
    """Reject semantically valid but non-canonical profile XML."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError("typed commutative-algebra localization XML is not canonical")
    canonical = canonicalize_typed_commutative_algebra_localization_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError("typed commutative-algebra localization XML is not canonical")
    return canonical


def validate_typed_commutative_algebra_localization_openmath_xml(xml: str) -> None:
    """Validate a closed localization proposition without canonicalizing it."""
    validate_typed_commutative_algebra_localization_openmath_root(validate_openmath_xml(xml))


def validate_typed_commutative_algebra_localization_openmath_root(root: ET.Element) -> None:
    """Validate an OpenMath-core-valid root for this isolated profile."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError(
            "typed commutative-algebra localization tree exceeds 4,096 nodes"
        )
    parents = _openmath_parents(root)
    _validate_tree_shape(nodes, parents=parents)
    if not _contains_profile_construct(root, parents=parents):
        raise MathXMLValidationError("OpenMath XML is not a typed localization proposition")
    if len(list(root)) != 1:
        raise MathXMLValidationError("typed localization OMOBJ must contain one expression")
    inferred = _infer_expression(list(root)[0], environment={}, parents=parents, path="root")
    if inferred != _PROP:
        raise MathXMLValidationError("typed localization root must have sort `Prop`")


def _validate_tree_shape(nodes: list[ET.Element], *, parents: dict[ET.Element, ET.Element]) -> None:
    for element in nodes:
        local = _local_name(element)
        if local not in _ALLOWED_ATTRIBUTES:
            raise MathXMLValidationError(
                f"OpenMath element `{local}` is outside typed commutative-algebra localization"
            )
        _validate_attributes(element, local=local)
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("typed localization tree exceeds depth 64")
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError("typed localization text exceeds 20,000 code points")
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError("typed localization elements cannot have text tails")
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError("typed localization attribute exceeds 20,000 code points")
        if local == "OMATTR":
            parent = parents.get(element)
            if (
                parent is None
                or _local_name(parent) != "OMBVAR"
                or not _is_type_declaration(element, parents=parents)
            ):
                raise MathXMLValidationError(
                    "typed localization permits OMATTR only as a typed OMBVAR declaration"
                )
        if local == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                not _is_type_declaration(item, parents=parents) for item in declarations
            ):
                raise MathXMLValidationError(
                    "typed localization OMBVAR requires 1..256 typed OMV declarations"
                )
        if local == "OMBIND":
            children = list(element)
            if len(children) != 3:
                raise MathXMLValidationError("typed localization OMBIND requires three children")
            symbol = _operator_symbol(children[0], parents=parents)
            if (
                symbol is None
                or symbol[:2] != (_TYPED, "typed1")
                or symbol[2] not in _BINDERS
                or children[0].get("cdbase") != _TYPED
            ):
                raise MathXMLValidationError(
                    "typed localization OMBIND requires typed1:forall/exists"
                )
        if local == "OMA":
            children = list(element)
            if not children or _local_name(children[0]) != "OMS":
                raise MathXMLValidationError("typed localization OMA head must be an OMS")
        if local == "OMS":
            _validate_symbol(element, parents=parents)


def _validate_attributes(element: ET.Element, *, local: str) -> None:
    unexpected = set(element.attrib) - _ALLOWED_ATTRIBUTES[local]
    if unexpected:
        raise MathXMLValidationError(
            f"typed localization `{local}` does not permit `{sorted(unexpected)[0]}`"
        )
    if local == "OMOBJ" and set(element.attrib) != {"version"}:
        raise MathXMLValidationError("typed localization OMOBJ requires only `version`")
    if local == "OMS" and not {"cd", "name"}.issubset(element.attrib):
        raise MathXMLValidationError("typed localization OMS requires `cd` and `name`")
    if local == "OMV" and set(element.attrib) != {"name"}:
        raise MathXMLValidationError("typed localization OMV requires only `name`")


def _validate_symbol(element: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed localization OMS must identify a symbol")
    direct_cdbase = element.get("cdbase")
    if symbol[0] == _TYPED:
        if direct_cdbase != _TYPED:
            raise MathXMLValidationError("typed localization OMS must directly declare its cdbase")
    elif symbol[0] == OPENMATH_STANDARD_CDBASE and direct_cdbase is None:
        ancestor = parents.get(element)
        while ancestor is not None:
            if "cdbase" in ancestor.attrib:
                raise MathXMLValidationError(
                    "standard typed localization OMS cannot inherit a cdbase"
                )
            ancestor = parents.get(ancestor)
    if symbol not in _SYMBOL_REGISTRY:
        _base, cd, name = symbol
        raise MathXMLValidationError(f"symbol `{cd}:{name}` is outside typed localization")


def _contains_profile_construct(root: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> bool:
    has_type = False
    has_binder = False
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        symbol = _operator_symbol(element, parents=parents)
        if symbol is None or symbol[0] != _TYPED:
            continue
        has_type |= symbol[1:] == ("typed1", "type")
        has_binder |= symbol[1:] in {("typed1", "forall"), ("typed1", "exists")}
    return has_type and has_binder


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
        and _operator_symbol(pair[0], parents=parents) == (_TYPED, "typed1", "type")
    )


def _infer_expression(
    expression: ET.Element,
    *,
    environment: dict[str, LocalizationSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> LocalizationSort:
    local = _local_name(expression)
    if local == "OMV":
        name = expression.get("name")
        if name is None or name not in environment:
            raise MathXMLValidationError(
                f"typed localization has free variable `{name or ''}` at {path}"
            )
        return environment[name]
    if local == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if local != "OMA":
        raise MathXMLValidationError(f"typed localization cannot infer `{local}` at {path}")
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(f"typed localization OMA has invalid operator at {path}")
    inferred = [
        _infer_expression(
            argument, environment=environment, parents=parents, path=f"{path}/{index}"
        )
        for index, argument in enumerate(arguments, start=1)
    ]
    return _infer_application(symbol, inferred, path=path)


def _infer_binding(
    binding: ET.Element,
    *,
    environment: dict[str, LocalizationSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> LocalizationSort:
    _binder, variables, body = list(binding)
    local_environment = dict(environment)
    declared: set[str] = set()
    for index, declaration in enumerate(list(variables), start=1):
        name, sort = _parse_declaration(
            declaration, environment=local_environment, parents=parents, path=f"{path}/bind/{index}"
        )
        if name in declared or name in environment:
            raise MathXMLValidationError(f"typed localization redeclares `{name}` at {path}")
        declared.add(name)
        local_environment[name] = sort
    body_sort = _infer_expression(
        body, environment=local_environment, parents=parents, path=f"{path}/body"
    )
    _require_sort("typed binder body", body_sort, _PROP, path=path)
    return _PROP


def _parse_declaration(
    declaration: ET.Element,
    *,
    environment: dict[str, LocalizationSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> tuple[str, LocalizationSort]:
    attributes, variable = list(declaration)
    _key, sort_expression = list(attributes)
    name = variable.get("name")
    if name is None or not name:
        raise MathXMLValidationError(f"typed localization bound OMV lacks name at {path}")
    sort = _parse_sort(
        sort_expression, name=name, environment=environment, parents=parents, path=path
    )
    return name, sort


def _parse_sort(
    expression: ET.Element,
    *,
    name: str,
    environment: dict[str, LocalizationSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> LocalizationSort:
    if _local_name(expression) == "OMS" and _operator_symbol(expression, parents=parents) == (
        _TYPED,
        "localization1",
        "CommRing",
    ):
        return LocalizationSort("ring", carrier=name)
    if _local_name(expression) != "OMA":
        raise MathXMLValidationError(f"typed localization invalid type annotation at {path}")
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    names = _sort_argument_names(arguments, path=path)
    if symbol == (_TYPED, "localization1", "Submonoid") and len(names) == 1:
        _require_base_ring_variable(environment, names[0], path=path)
        return LocalizationSort("submonoid", carrier=name, ring=names[0])
    if symbol == (_TYPED, "localization1", "SubmonoidElem") and len(names) == 2:
        _require_submonoid_variable(environment, names[1], ring=names[0], path=path)
        return LocalizationSort(
            "submonoid_element", carrier=name, ring=names[0], submonoid=names[1]
        )
    if symbol == (_TYPED, "localization1", "Localization") and len(names) == 2:
        _require_submonoid_variable(environment, names[1], ring=names[0], path=path)
        return LocalizationSort("localized_ring", carrier=name, ring=names[0], submonoid=names[1])
    if symbol in {(_TYPED, "typed1", "Elem"), (_TYPED, "commalg1", "Ideal")} and len(names) == 1:
        _require_ring_variable(environment, names[0], path=path)
        kind: _Kind = "element" if symbol[2] == "Elem" else "ideal"
        return LocalizationSort(kind, carrier=names[0])
    raise MathXMLValidationError(
        "typed localization type annotation must be CommRing, Submonoid(R), "
        "SubmonoidElem(R,M), Localization(R,M), Ideal(A), or Elem(A)"
    )


def _sort_argument_names(arguments: list[ET.Element], *, path: str) -> list[str]:
    names: list[str] = []
    for argument in arguments:
        if _local_name(argument) != "OMV" or not argument.get("name"):
            raise MathXMLValidationError(f"typed localization sort arguments must be OMV at {path}")
        names.append(argument.get("name") or "")
    return names


def _infer_application(
    symbol: _Symbol, arguments: list[LocalizationSort], *, path: str
) -> LocalizationSort:
    cdbase, cd, name = symbol
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "relation1") and name in {"eq", "neq"}:
        _require_arity(symbol, arguments, exact=2)
        if arguments[0] != arguments[1]:
            _raise_expected(symbol, 1, arguments[1], arguments[0].render(), path=path)
        return _PROP
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "logic1"):
        if name in {"and", "or", "equivalent"}:
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _PROP, path=path)
            return _PROP
        if name == "implies":
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _PROP, path=path)
            return _PROP
    if cdbase != _TYPED:
        raise MathXMLValidationError(f"unsupported typed localization application `{cd}:{name}`")
    if cd == "localization1":
        return _infer_localization_application(name, symbol, arguments, path=path)
    if cd == "commalg1":
        return _infer_ideal_application(name, symbol, arguments, path=path)
    raise MathXMLValidationError(f"unsupported typed localization application `{cd}:{name}`")


def _infer_localization_application(
    name: str, symbol: _Symbol, arguments: list[LocalizationSort], *, path: str
) -> LocalizationSort:
    if name in {"ring_zero", "ring_one"}:
        carrier = _require_ring(symbol, arguments, path=path, exact=1)
        return LocalizationSort("element", carrier=carrier)
    if name in {"ring_add", "ring_mul"}:
        carrier = _require_ring(symbol, arguments, path=path, exact=3)
        _require_elements(symbol, arguments, carrier=carrier, start=1, path=path)
        return LocalizationSort("element", carrier=carrier)
    if name == "is_unit":
        carrier = _require_ring(symbol, arguments, path=path, exact=2)
        _require_argument(
            symbol, arguments, 1, LocalizationSort("element", carrier=carrier), path=path
        )
        return _PROP
    if name == "submonoid_value":
        _require_arity(symbol, arguments, exact=3)
        base = _require_base_ring(symbol, arguments, index=0, path=path)
        _require_argument(
            symbol,
            arguments,
            1,
            LocalizationSort("submonoid", ring=base),
            path=path,
        )
        _require_argument(
            symbol,
            arguments,
            2,
            LocalizationSort(
                "submonoid_element",
                ring=base,
                submonoid=arguments[1].carrier,
            ),
            path=path,
        )
        return LocalizationSort("element", carrier=base)
    if name == "loc_map":
        _require_arity(symbol, arguments, exact=4)
        _require_localization_prefix(symbol, arguments, path=path)
        localized = arguments[2]
        assert localized.carrier is not None
        _require_argument(
            symbol,
            arguments,
            3,
            LocalizationSort("element", carrier=arguments[0].carrier),
            path=path,
        )
        return LocalizationSort("element", carrier=localized.carrier)
    if name == "loc_fraction":
        _require_arity(symbol, arguments, exact=5)
        _require_localization_prefix(symbol, arguments, path=path)
        localized = arguments[2]
        assert localized.carrier is not None
        _require_argument(
            symbol,
            arguments,
            3,
            LocalizationSort("element", carrier=arguments[0].carrier),
            path=path,
        )
        _require_argument(
            symbol,
            arguments,
            4,
            LocalizationSort(
                "submonoid_element",
                ring=arguments[0].carrier,
                submonoid=arguments[1].carrier,
            ),
            path=path,
        )
        return LocalizationSort("element", carrier=localized.carrier)
    raise MathXMLValidationError(f"unsupported localization1:{name}")


def _infer_ideal_application(
    name: str, symbol: _Symbol, arguments: list[LocalizationSort], *, path: str
) -> LocalizationSort:
    if name == "ideal_top":
        carrier = _require_ring(symbol, arguments, path=path, exact=1)
        return LocalizationSort("ideal", carrier=carrier)
    if name in {"ideal_inf", "ideal_sup"}:
        carrier = _require_ring(symbol, arguments, path=path, exact=3)
        _require_ideals(symbol, arguments, carrier=carrier, start=1, path=path)
        return LocalizationSort("ideal", carrier=carrier)
    if name == "ideal_radical":
        carrier = _require_ring(symbol, arguments, path=path, exact=2)
        _require_ideals(symbol, arguments, carrier=carrier, start=1, path=path)
        return LocalizationSort("ideal", carrier=carrier)
    if name == "ideal_le":
        carrier = _require_ring(symbol, arguments, path=path, exact=3)
        _require_ideals(symbol, arguments, carrier=carrier, start=1, path=path)
        return _PROP
    if name == "ideal_mem":
        carrier = _require_ring(symbol, arguments, path=path, exact=3)
        _require_argument(
            symbol, arguments, 1, LocalizationSort("ideal", carrier=carrier), path=path
        )
        _require_argument(
            symbol, arguments, 2, LocalizationSort("element", carrier=carrier), path=path
        )
        return _PROP
    if name == "is_prime_ideal":
        carrier = _require_ring(symbol, arguments, path=path, exact=2)
        _require_ideals(symbol, arguments, carrier=carrier, start=1, path=path)
        return _PROP
    if name == "ideal_disjoint_submonoid":
        _require_arity(symbol, arguments, exact=3)
        base = _require_base_ring(symbol, arguments, index=0, path=path)
        _require_argument(
            symbol,
            arguments,
            1,
            LocalizationSort("submonoid", ring=base),
            path=path,
        )
        _require_argument(symbol, arguments, 2, LocalizationSort("ideal", carrier=base), path=path)
        return _PROP
    if name in {"extend", "contract"}:
        _require_arity(symbol, arguments, exact=4)
        _require_localization_prefix(symbol, arguments, path=path)
        base = _require_base_ring(symbol, arguments, index=0, path=path)
        localized = arguments[2].carrier
        assert localized is not None
        expected = LocalizationSort("ideal", carrier=base if name == "extend" else localized)
        _require_argument(symbol, arguments, 3, expected, path=path)
        return LocalizationSort("ideal", carrier=localized if name == "extend" else base)
    raise MathXMLValidationError(f"unsupported commalg1:{name}")


def _require_localization_prefix(
    symbol: _Symbol, arguments: list[LocalizationSort], *, path: str
) -> None:
    base = _require_base_ring(symbol, arguments, index=0, path=path)
    submonoid = arguments[1]
    _require_argument(symbol, arguments, 1, LocalizationSort("submonoid", ring=base), path=path)
    localized = arguments[2]
    if (
        localized.kind != "localized_ring"
        or localized.ring != base
        or localized.submonoid != submonoid.carrier
    ):
        _raise_expected(
            symbol,
            2,
            localized,
            f"Localization({base},{submonoid.carrier or '?'})",
            path=path,
        )


def _require_base_ring(
    symbol: _Symbol, arguments: list[LocalizationSort], *, index: int, path: str
) -> str:
    sort = arguments[index]
    if sort.kind != "ring" or sort.carrier is None:
        _raise_expected(symbol, index, sort, "CommRing", path=path)
        raise AssertionError("unreachable after sort failure")
    return sort.carrier


def _require_ring(
    symbol: _Symbol, arguments: list[LocalizationSort], *, path: str, exact: int
) -> str:
    _require_arity(symbol, arguments, exact=exact)
    sort = arguments[0]
    if sort.kind not in {"ring", "localized_ring"} or sort.carrier is None:
        _raise_expected(symbol, 0, sort, "CommRing or Localization(R,M)", path=path)
        raise AssertionError("unreachable after sort failure")
    return sort.carrier


def _require_base_ring_variable(
    environment: dict[str, LocalizationSort], name: str, *, path: str
) -> None:
    sort = environment.get(name)
    if sort is None or sort.kind != "ring":
        raise MathXMLValidationError(
            f"typed localization expected prior CommRing `{name}` at {path}"
        )


def _require_ring_variable(
    environment: dict[str, LocalizationSort], name: str, *, path: str
) -> None:
    sort = environment.get(name)
    if sort is None or sort.kind not in {"ring", "localized_ring"}:
        raise MathXMLValidationError(
            f"typed localization expected prior CommRing or Localization `{name}` at {path}"
        )


def _require_submonoid_variable(
    environment: dict[str, LocalizationSort], name: str, *, ring: str, path: str
) -> None:
    _require_base_ring_variable(environment, ring, path=path)
    sort = environment.get(name)
    if sort is None or sort.kind != "submonoid" or sort.ring != ring:
        raise MathXMLValidationError(
            f"typed localization expected prior Submonoid({ring}) `{name}` at {path}"
        )


def _require_ideals(
    symbol: _Symbol,
    arguments: list[LocalizationSort],
    *,
    carrier: str,
    start: int,
    path: str,
) -> None:
    for index in range(start, len(arguments)):
        _require_argument(
            symbol, arguments, index, LocalizationSort("ideal", carrier=carrier), path=path
        )


def _require_elements(
    symbol: _Symbol,
    arguments: list[LocalizationSort],
    *,
    carrier: str,
    start: int,
    path: str,
) -> None:
    for index in range(start, len(arguments)):
        _require_argument(
            symbol, arguments, index, LocalizationSort("element", carrier=carrier), path=path
        )


def _require_arity(
    symbol: _Symbol,
    arguments: list[LocalizationSort],
    *,
    exact: int,
) -> None:
    if len(arguments) == exact:
        return
    _base, cd, name = symbol
    raise MathXMLValidationError(
        f"`{cd}:{name}` requires {exact} arguments; received {len(arguments)}"
    )


def _require_all(
    symbol: _Symbol,
    arguments: list[LocalizationSort],
    expected: LocalizationSort,
    *,
    path: str,
) -> None:
    for index in range(len(arguments)):
        _require_argument(symbol, arguments, index, expected, path=path)


def _require_argument(
    symbol: _Symbol,
    arguments: list[LocalizationSort],
    index: int,
    expected: LocalizationSort,
    *,
    path: str,
) -> None:
    actual = arguments[index]
    if _sort_matches(actual, expected):
        return
    _raise_expected(symbol, index, actual, expected.render(), path=path)


def _sort_matches(actual: LocalizationSort, expected: LocalizationSort) -> bool:
    if actual.kind != expected.kind:
        return False
    if expected.kind in {"ring", "localized_ring"}:
        return actual.carrier == expected.carrier
    return (
        (expected.carrier is None or actual.carrier == expected.carrier)
        and (expected.ring is None or actual.ring == expected.ring)
        and (expected.submonoid is None or actual.submonoid == expected.submonoid)
    )


def _raise_expected(
    symbol: _Symbol,
    index: int,
    actual: LocalizationSort,
    expected: str,
    *,
    path: str,
) -> None:
    _base, cd, name = symbol
    raise MathXMLValidationError(
        f"argument {index + 1} of `{cd}:{name}` at {path} must have sort `{expected}`; "
        f"received `{actual.render()}`"
    )


def _require_sort(
    label: str, actual: LocalizationSort, expected: LocalizationSort, *, path: str
) -> None:
    if actual == expected:
        return
    raise MathXMLValidationError(
        f"{label} at {path} must have sort `{expected.render()}`; received `{actual.render()}`"
    )
