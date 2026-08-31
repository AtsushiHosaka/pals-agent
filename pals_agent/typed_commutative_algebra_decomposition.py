"""Fail-closed OpenMath validation for primary-decomposition core evidence.

``typed-commutative-algebra-decomposition-v1`` is intentionally a new
profile.  It represents an explicit commutative-ring carrier, ideals,
primary ideals, prime ideals, two- and three-component decompositions, and
minimal-prime witnesses.  It does *not* model modules, associated primes,
arbitrary finite families, Noetherian existence theorems, quotients, or
localizations.
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

TYPED_COMMUTATIVE_ALGEBRA_DECOMPOSITION_OPENMATH_CDBASE = (
    "urn:pals:openmath:typed-commutative-algebra-decomposition:v1"
)
TYPED_COMMUTATIVE_ALGEBRA_DECOMPOSITION_PROFILE = "typed-commutative-algebra-decomposition-v1"

_SortName = Literal["prop", "comm_ring", "ideal", "primary_ideal", "prime_ideal"]
_Symbol = tuple[str, str, str]
_TYPED = TYPED_COMMUTATIVE_ALGEBRA_DECOMPOSITION_OPENMATH_CDBASE
_BINDERS = frozenset({"forall", "exists"})
_LOGICAL_BINARY = frozenset({"and", "or", "implies"})
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
class DecompositionSort:
    """One profile sort with an exact, bound commutative-ring carrier."""

    name: _SortName
    carrier: str | None = None

    def render(self) -> str:
        if self.name == "prop":
            return "Prop"
        if self.name == "comm_ring":
            return "CommRing"
        if self.name == "ideal":
            return f"Ideal({self.carrier or '?'})"
        if self.name == "primary_ideal":
            return f"PrimaryIdeal({self.carrier or '?'})"
        return f"PrimeIdeal({self.carrier or '?'})"


_PROP = DecompositionSort("prop")


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-commutative-algebra-decomposition-v1-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - packaging invariant
        raise RuntimeError("typed primary-decomposition registry is unavailable") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version")
        != "pals.typed-commutative-algebra-decomposition-registry.v1"
        or payload.get("profile_id") != TYPED_COMMUTATIVE_ALGEBRA_DECOMPOSITION_PROFILE
        or payload.get("cdbases") != {"standard": OPENMATH_STANDARD_CDBASE, "typed": _TYPED}
        or not isinstance(payload.get("symbols"), list)
    ):  # pragma: no cover - packaging invariant
        raise RuntimeError("typed primary-decomposition registry header is invalid")
    entries: set[_Symbol] = set()
    for raw_entry in payload["symbols"]:
        if not isinstance(raw_entry, dict):  # pragma: no cover - packaging invariant
            raise RuntimeError("typed primary-decomposition registry entry is invalid")
        identity = tuple(raw_entry.get(key) for key in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError("typed primary-decomposition registry identity is invalid")
        entries.add(cast(_Symbol, identity))
    if len(entries) != len(payload["symbols"]):  # pragma: no cover - packaging invariant
        raise RuntimeError("typed primary-decomposition registry contains duplicates")
    return frozenset(entries)


_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_commutative_algebra_decomposition_openmath_xml(xml: str) -> str:
    """Validate and return exact v4 C14N bytes for a closed proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("typed primary-decomposition XML exceeds 65,536 bytes")
    root = validate_openmath_xml(xml)
    validate_typed_commutative_algebra_decomposition_openmath_root(root)
    return _canonicalize_openmath_v4_root(root)


def validate_canonical_typed_commutative_algebra_decomposition_openmath_xml(xml: str) -> str:
    """Reject semantically valid profile XML whose bytes are not exact C14N."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError("typed primary-decomposition XML is not canonical")
    canonical = canonicalize_typed_commutative_algebra_decomposition_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError("typed primary-decomposition XML is not canonical")
    return canonical


def validate_typed_commutative_algebra_decomposition_openmath_xml(xml: str) -> None:
    """Validate a closed v1 primary-decomposition proposition."""
    validate_typed_commutative_algebra_decomposition_openmath_root(validate_openmath_xml(xml))


def validate_typed_commutative_algebra_decomposition_openmath_root(root: ET.Element) -> None:
    """Validate one already OpenMath-core-valid profile expression."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("typed primary-decomposition tree exceeds 4,096 nodes")
    parents = _openmath_parents(root)
    _validate_tree_shape(nodes, parents=parents)
    if len(list(root)) != 1:
        raise MathXMLValidationError("typed primary-decomposition OMOBJ needs one expression")
    if not _contains_profile_construct(root, parents=parents):
        raise MathXMLValidationError(
            "OpenMath XML is not a typed primary-decomposition proposition"
        )
    inferred = _infer_expression(list(root)[0], environment={}, parents=parents, path="root")
    _require_sort("typed primary-decomposition root", inferred, _PROP, path="root")


def _validate_tree_shape(nodes: list[ET.Element], *, parents: dict[ET.Element, ET.Element]) -> None:
    for element in nodes:
        local = _local_name(element)
        if local not in _ALLOWED_ATTRIBUTES:
            raise MathXMLValidationError(
                f"OpenMath element `{local}` is outside typed primary-decomposition"
            )
        _validate_attributes(element, local=local)
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("typed primary-decomposition tree exceeds depth 64")
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError(
                "typed primary-decomposition text exceeds 20,000 code points"
            )
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError(
                "typed primary-decomposition elements cannot have text tails"
            )
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError(
                "typed primary-decomposition attribute exceeds 20,000 code points"
            )
        if local == "OMATTR":
            parent = parents.get(element)
            if (
                parent is None
                or _local_name(parent) != "OMBVAR"
                or not _is_type_declaration(element, parents=parents)
            ):
                raise MathXMLValidationError(
                    "typed primary-decomposition permits OMATTR only as typed OMBVAR"
                )
        if local == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                not _is_type_declaration(item, parents=parents) for item in declarations
            ):
                raise MathXMLValidationError(
                    "typed primary-decomposition OMBVAR needs 1..256 typed declarations"
                )
        if local == "OMBIND":
            children = list(element)
            symbol = _operator_symbol(children[0], parents=parents) if len(children) == 3 else None
            if (
                symbol is None
                or symbol[:2] != (_TYPED, "typed1")
                or symbol[2] not in _BINDERS
                or children[0].get("cdbase") != _TYPED
            ):
                raise MathXMLValidationError(
                    "typed primary-decomposition OMBIND requires typed1:forall/exists"
                )
        if local == "OMA":
            children = list(element)
            if not children or _local_name(children[0]) != "OMS":
                raise MathXMLValidationError("typed primary-decomposition OMA head must be an OMS")
        if local == "OMS":
            _validate_symbol(element, parents=parents)


def _validate_attributes(element: ET.Element, *, local: str) -> None:
    unexpected = set(element.attrib) - _ALLOWED_ATTRIBUTES[local]
    if unexpected:
        raise MathXMLValidationError(
            f"typed primary-decomposition `{local}` forbids `{sorted(unexpected)[0]}`"
        )
    if local == "OMOBJ" and set(element.attrib) != {"version"}:
        raise MathXMLValidationError("typed primary-decomposition OMOBJ requires only version")
    if local == "OMS" and not {"cd", "name"}.issubset(element.attrib):
        raise MathXMLValidationError("typed primary-decomposition OMS requires cd and name")
    if local == "OMV" and set(element.attrib) != {"name"}:
        raise MathXMLValidationError("typed primary-decomposition OMV requires only name")


def _validate_symbol(element: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed primary-decomposition OMS must identify a symbol")
    direct_cdbase = element.get("cdbase")
    if symbol[0] == _TYPED:
        if direct_cdbase != _TYPED:
            raise MathXMLValidationError(
                "typed primary-decomposition OMS must directly declare its cdbase"
            )
    elif symbol[0] == OPENMATH_STANDARD_CDBASE and direct_cdbase is None:
        ancestor = parents.get(element)
        while ancestor is not None:
            if "cdbase" in ancestor.attrib:
                raise MathXMLValidationError(
                    "standard primary-decomposition OMS cannot inherit a cdbase"
                )
            ancestor = parents.get(ancestor)
    if symbol not in _SYMBOL_REGISTRY:
        _base, cd, name = symbol
        raise MathXMLValidationError(f"symbol `{cd}:{name}` is outside typed primary-decomposition")


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
    environment: dict[str, DecompositionSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> DecompositionSort:
    local = _local_name(expression)
    if local == "OMV":
        name = expression.get("name")
        if name is None or name not in environment:
            raise MathXMLValidationError(
                f"typed primary-decomposition has free variable `{name or ''}` at {path}"
            )
        declared = environment[name]
        return DecompositionSort("comm_ring", name) if declared.name == "comm_ring" else declared
    if local == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if local != "OMA":
        raise MathXMLValidationError(
            f"typed primary-decomposition cannot infer `{local}` at {path}"
        )
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(
            f"typed primary-decomposition OMA has invalid operator at {path}"
        )
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
    environment: dict[str, DecompositionSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> DecompositionSort:
    _binder, variables, body = list(binding)
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
                f"typed primary-decomposition redeclares `{name}` at {path}"
            )
        declared.add(name)
        local_environment[name] = sort
    result = _infer_expression(
        body, environment=local_environment, parents=parents, path=f"{path}/body"
    )
    _require_sort("typed binder body", result, _PROP, path=path)
    return _PROP


def _parse_declaration(
    declaration: ET.Element,
    *,
    environment: dict[str, DecompositionSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> tuple[str, DecompositionSort]:
    attributes, variable = list(declaration)
    _key, sort_expression = list(attributes)
    name = variable.get("name")
    if name is None or not name:
        raise MathXMLValidationError(f"typed primary-decomposition bound OMV lacks name at {path}")
    return name, _parse_sort(sort_expression, environment=environment, parents=parents, path=path)


def _parse_sort(
    expression: ET.Element,
    *,
    environment: dict[str, DecompositionSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> DecompositionSort:
    if _local_name(expression) == "OMS" and _operator_symbol(expression, parents=parents) == (
        _TYPED,
        "decomposition1",
        "CommRing",
    ):
        return DecompositionSort("comm_ring")
    if _local_name(expression) == "OMA":
        operator, *arguments = list(expression)
        symbol = _operator_symbol(operator, parents=parents)
        if (
            symbol is not None
            and symbol[:2] == (_TYPED, "decomposition1")
            and symbol[2] in {"Ideal", "PrimaryIdeal", "PrimeIdeal"}
            and len(arguments) == 1
            and _local_name(arguments[0]) == "OMV"
        ):
            carrier = arguments[0].get("name")
            if (
                environment.get(carrier or "") is not None
                and environment[carrier or ""].name == "comm_ring"
            ):
                assert carrier is not None
                kind: _SortName
                if symbol[2] == "Ideal":
                    kind = "ideal"
                elif symbol[2] == "PrimaryIdeal":
                    kind = "primary_ideal"
                else:
                    kind = "prime_ideal"
                return DecompositionSort(kind, carrier)
    raise MathXMLValidationError(
        "typed primary-decomposition type annotation must be CommRing, Ideal(R), "
        "PrimaryIdeal(R), or PrimeIdeal(R) at "
        f"{path}"
    )


def _infer_application(
    symbol: _Symbol, arguments: list[DecompositionSort], *, path: str
) -> DecompositionSort:
    cdbase, cd, name = symbol
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "relation1") and name in {"eq", "neq"}:
        _require_arity(symbol, arguments, exact=2)
        if arguments[0] != arguments[1]:
            _raise_expected(symbol, 1, arguments[1], arguments[0].render(), path=path)
        return _PROP
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "logic1"):
        if name in _LOGICAL_BINARY:
            _require_arity(symbol, arguments, minimum=2, maximum=2 if name == "implies" else None)
            _require_all(symbol, arguments, _PROP, path=path)
            return _PROP
        if name == "not":
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _PROP, path=path)
            return _PROP
    if (cdbase, cd) != (_TYPED, "decomposition1"):
        raise MathXMLValidationError(f"unsupported typed primary-decomposition `{cd}:{name}`")
    if name == "primary_as_ideal":
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=2)
        _require_argument(
            symbol, arguments, 1, DecompositionSort("primary_ideal", carrier), path=path
        )
        return DecompositionSort("ideal", carrier)
    if name == "prime_as_ideal":
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=2)
        _require_argument(
            symbol, arguments, 1, DecompositionSort("prime_ideal", carrier), path=path
        )
        return DecompositionSort("ideal", carrier)
    if name == "primary_radical_prime":
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=2)
        _require_argument(
            symbol, arguments, 1, DecompositionSort("primary_ideal", carrier), path=path
        )
        return DecompositionSort("prime_ideal", carrier)
    if name == "ideal_radical":
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=2)
        _require_argument(symbol, arguments, 1, DecompositionSort("ideal", carrier), path=path)
        return DecompositionSort("ideal", carrier)
    if name == "ideal_top":
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=1)
        return DecompositionSort("ideal", carrier)
    if name == "ideal_inf2":
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=3)
        _require_ideals(symbol, arguments, carrier=carrier, start=1, path=path)
        return DecompositionSort("ideal", carrier)
    if name == "ideal_inf3":
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=4)
        _require_ideals(symbol, arguments, carrier=carrier, start=1, path=path)
        return DecompositionSort("ideal", carrier)
    if name in {"ideal_le", "is_primary_ideal", "is_prime_ideal", "is_radical_ideal"}:
        exact = 3 if name == "ideal_le" else 2
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=exact)
        _require_ideals(symbol, arguments, carrier=carrier, start=1, path=path)
        return _PROP
    if name in {"primary_decomposition2", "irredundant_decomposition2"}:
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=4)
        _require_argument(symbol, arguments, 1, DecompositionSort("ideal", carrier), path=path)
        _require_primary_arguments(symbol, arguments, carrier=carrier, start=2, path=path)
        return _PROP
    if name == "primary_decomposition3":
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=5)
        _require_argument(symbol, arguments, 1, DecompositionSort("ideal", carrier), path=path)
        _require_primary_arguments(symbol, arguments, carrier=carrier, start=2, path=path)
        return _PROP
    if name == "minimal_prime_over":
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=3)
        _require_argument(
            symbol, arguments, 1, DecompositionSort("prime_ideal", carrier), path=path
        )
        _require_argument(symbol, arguments, 2, DecompositionSort("ideal", carrier), path=path)
        return _PROP
    raise MathXMLValidationError(f"unsupported decomposition1:{name}")


def _require_comm_ring(
    symbol: _Symbol, arguments: list[DecompositionSort], *, path: str, exact: int
) -> str:
    _require_arity(symbol, arguments, exact=exact)
    structure = arguments[0]
    if structure.name != "comm_ring" or structure.carrier is None:
        _raise_expected(symbol, 0, structure, "CommRing", path=path)
    assert structure.carrier is not None
    return structure.carrier


def _require_ideals(
    symbol: _Symbol,
    arguments: list[DecompositionSort],
    *,
    carrier: str,
    start: int,
    path: str,
) -> None:
    for index in range(start, len(arguments)):
        _require_argument(symbol, arguments, index, DecompositionSort("ideal", carrier), path=path)


def _require_primary_arguments(
    symbol: _Symbol,
    arguments: list[DecompositionSort],
    *,
    carrier: str,
    start: int,
    path: str,
) -> None:
    for index in range(start, len(arguments)):
        _require_argument(
            symbol, arguments, index, DecompositionSort("primary_ideal", carrier), path=path
        )


def _require_arity(
    symbol: _Symbol,
    arguments: list[DecompositionSort],
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
    _base, cd, name = symbol
    expectation = str(exact) if exact is not None else f"{minimum or 0}..{maximum or 'n'}"
    raise MathXMLValidationError(
        f"`{cd}:{name}` requires {expectation} arguments; received {len(arguments)}"
    )


def _require_all(
    symbol: _Symbol, arguments: list[DecompositionSort], expected: DecompositionSort, *, path: str
) -> None:
    for index in range(len(arguments)):
        _require_argument(symbol, arguments, index, expected, path=path)


def _require_argument(
    symbol: _Symbol,
    arguments: list[DecompositionSort],
    index: int,
    expected: DecompositionSort,
    *,
    path: str,
) -> None:
    actual = arguments[index]
    if actual != expected:
        _raise_expected(symbol, index, actual, expected.render(), path=path)


def _raise_expected(
    symbol: _Symbol, index: int, actual: DecompositionSort, expected: str, *, path: str
) -> None:
    _base, cd, name = symbol
    raise MathXMLValidationError(
        f"argument {index + 1} of `{cd}:{name}` at {path} must have sort `{expected}`; "
        f"received `{actual.render()}`"
    )


def _require_sort(
    label: str, actual: DecompositionSort, expected: DecompositionSort, *, path: str
) -> None:
    if actual != expected:
        raise MathXMLValidationError(
            f"{label} at {path} must have sort `{expected.render()}`; received `{actual.render()}`"
        )
