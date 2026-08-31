"""Fail-closed OpenMath validation for ``typed-commutative-algebra-v1``.

This is an isolated profile for a small, carrier-safe ideal-lattice core over
commutative rings.  It intentionally has no quotient, localization, module,
or spectrum symbols: their maps and dependent carriers are not representable
soundly by this v1 language.
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

TYPED_COMMUTATIVE_ALGEBRA_OPENMATH_CDBASE = "urn:pals:openmath:typed-commutative-algebra:v1"
TYPED_COMMUTATIVE_ALGEBRA_PROFILE = "typed-commutative-algebra-v1"

_SortName = Literal["prop", "comm_ring", "ideal", "element"]
_Symbol = tuple[str, str, str]
_TYPED_BINDERS = frozenset({"forall", "exists"})
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
class CommutativeAlgebraSort:
    """A profile sort; dependent sorts retain their exact bound carrier name."""

    name: _SortName
    carrier: str | None = None

    def render(self) -> str:
        if self.name == "prop":
            return "Prop"
        if self.name == "comm_ring":
            return "CommRing"
        if self.name == "ideal":
            return f"Ideal({self.carrier or '?'})"
        return f"Elem({self.carrier or '?'})"


_PROP = CommutativeAlgebraSort("prop")
_COMM_RING = CommutativeAlgebraSort("comm_ring")


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-commutative-algebra-v1-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - package invariant
        raise RuntimeError("typed-commutative-algebra-v1 symbol registry is unavailable.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "pals.typed-commutative-algebra-registry.v1"
        or payload.get("profile_id") != TYPED_COMMUTATIVE_ALGEBRA_PROFILE
        or payload.get("cdbases")
        != {
            "standard": OPENMATH_STANDARD_CDBASE,
            "typed": TYPED_COMMUTATIVE_ALGEBRA_OPENMATH_CDBASE,
        }
        or not isinstance(payload.get("symbols"), list)
    ):  # pragma: no cover - package invariant
        raise RuntimeError("typed-commutative-algebra-v1 symbol registry header is invalid.")
    symbols: set[_Symbol] = set()
    for entry in payload["symbols"]:
        if not isinstance(entry, dict):  # pragma: no cover - package invariant
            raise RuntimeError("typed-commutative-algebra-v1 symbol registry entry is invalid.")
        identity = tuple(entry.get(key) for key in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError("typed-commutative-algebra-v1 symbol registry identity is invalid.")
        symbols.add(cast(_Symbol, identity))
    if len(symbols) != len(payload["symbols"]):  # pragma: no cover - package invariant
        raise RuntimeError("typed-commutative-algebra-v1 symbol registry contains duplicates.")
    return frozenset(symbols)


_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_commutative_algebra_openmath_xml(xml: str) -> str:
    """Validate and canonicalize one closed commutative-algebra proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError(
            "OpenMath XML exceeds the typed commutative-algebra byte bound."
        )
    root = validate_openmath_xml(xml)
    validate_typed_commutative_algebra_openmath_root(root)
    return _canonicalize_openmath_v4_root(root)


def validate_canonical_typed_commutative_algebra_openmath_xml(xml: str) -> str:
    """Accept only exact canonical bytes for the isolated profile."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError(
            "OpenMath XML is not exact typed commutative-algebra canonical bytes."
        )
    canonical = canonicalize_typed_commutative_algebra_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError(
            "OpenMath XML is not exact typed commutative-algebra canonical bytes."
        )
    return canonical


def validate_typed_commutative_algebra_openmath_xml(xml: str) -> None:
    """Validate a closed ``typed-commutative-algebra-v1`` proposition."""
    validate_typed_commutative_algebra_openmath_root(validate_openmath_xml(xml))


def validate_typed_commutative_algebra_openmath_root(root: ET.Element) -> None:
    """Validate an already OpenMath-core-valid root for this profile."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("OpenMath typed commutative-algebra tree exceeds 4,096 nodes.")
    parents = _openmath_parents(root)
    _validate_tree_shape(nodes, parents=parents)
    if not _contains_profile_construct(root, parents=parents):
        raise MathXMLValidationError(
            "OpenMath XML is not a typed-commutative-algebra-v1 proposition."
        )
    if len(list(root)) != 1:
        raise MathXMLValidationError(
            "typed-commutative-algebra-v1 OMOBJ must contain one expression."
        )
    inferred = _infer_expression(list(root)[0], environment={}, parents=parents, path="root")
    if inferred != _PROP:
        raise MathXMLValidationError("typed-commutative-algebra-v1 root must have sort `Prop`.")


def _validate_tree_shape(nodes: list[ET.Element], *, parents: dict[ET.Element, ET.Element]) -> None:
    for element in nodes:
        local = _local_name(element)
        if local not in _ALLOWED_ATTRIBUTES:
            raise MathXMLValidationError(
                f"OpenMath element `{local}` is outside typed-commutative-algebra-v1."
            )
        _validate_attributes(element, local=local)
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError(
                "OpenMath typed commutative-algebra tree exceeds depth 64."
            )
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError(
                "typed-commutative-algebra-v1 text exceeds 20,000 code points."
            )
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError(
                "typed-commutative-algebra-v1 elements cannot have text tails."
            )
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError(
                "typed-commutative-algebra-v1 attribute exceeds 20,000 code points."
            )
        if local == "OMATTR":
            parent = parents.get(element)
            if (
                parent is None
                or _local_name(parent) != "OMBVAR"
                or not _is_type_declaration(element, parents=parents)
            ):
                raise MathXMLValidationError(
                    "typed-commutative-algebra-v1 permits OMATTR only as a typed "
                    "OMBVAR declaration."
                )
        if local == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                not _is_type_declaration(item, parents=parents) for item in declarations
            ):
                raise MathXMLValidationError(
                    "typed-commutative-algebra-v1 OMBVAR requires 1..256 typed OMV declarations."
                )
        if local == "OMBIND":
            children = list(element)
            if len(children) != 3:
                raise MathXMLValidationError(
                    "typed-commutative-algebra-v1 OMBIND requires three children."
                )
            symbol = _operator_symbol(children[0], parents=parents)
            if (
                symbol is None
                or symbol[:2] != (TYPED_COMMUTATIVE_ALGEBRA_OPENMATH_CDBASE, "typed1")
                or symbol[2] not in _TYPED_BINDERS
                or children[0].get("cdbase") != TYPED_COMMUTATIVE_ALGEBRA_OPENMATH_CDBASE
            ):
                raise MathXMLValidationError(
                    "typed-commutative-algebra-v1 OMBIND must use typed1:forall or typed1:exists."
                )
        if local == "OMA":
            children = list(element)
            if not children or _local_name(children[0]) != "OMS":
                raise MathXMLValidationError(
                    "typed-commutative-algebra-v1 OMA head must be an OMS."
                )
        if local == "OMS":
            _validate_symbol(element, parents=parents)


def _validate_attributes(element: ET.Element, *, local: str) -> None:
    unexpected = set(element.attrib) - _ALLOWED_ATTRIBUTES[local]
    if unexpected:
        raise MathXMLValidationError(
            f"typed-commutative-algebra-v1 `{local}` does not permit attribute "
            f"`{sorted(unexpected)[0]}`."
        )
    if local == "OMOBJ" and set(element.attrib) != {"version"}:
        raise MathXMLValidationError("typed-commutative-algebra-v1 OMOBJ requires only `version`.")
    if local == "OMS" and not {"cd", "name"}.issubset(element.attrib):
        raise MathXMLValidationError("typed-commutative-algebra-v1 OMS requires `cd` and `name`.")
    if local == "OMV" and set(element.attrib) != {"name"}:
        raise MathXMLValidationError("typed-commutative-algebra-v1 OMV requires only `name`.")


def _validate_symbol(element: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed-commutative-algebra-v1 OMS must identify a symbol.")
    direct_cdbase = element.get("cdbase")
    if symbol[0] == TYPED_COMMUTATIVE_ALGEBRA_OPENMATH_CDBASE:
        if direct_cdbase != symbol[0]:
            raise MathXMLValidationError(
                "typed-commutative-algebra-v1 OMS must directly declare its typed cdbase."
            )
    elif symbol[0] == OPENMATH_STANDARD_CDBASE and direct_cdbase is None:
        ancestor = parents.get(element)
        while ancestor is not None:
            if "cdbase" in ancestor.attrib:
                raise MathXMLValidationError(
                    "Standard typed-commutative-algebra-v1 OMS may omit cdbase only without "
                    "inherited cdbase."
                )
            ancestor = parents.get(ancestor)
    if symbol not in _SYMBOL_REGISTRY:
        _base, cd, name = symbol
        raise MathXMLValidationError(
            f"Symbol `{cd}:{name}` is outside typed-commutative-algebra-v1."
        )


def _contains_profile_construct(root: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> bool:
    type_annotation = False
    binder = False
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        symbol = _operator_symbol(element, parents=parents)
        if symbol is None or symbol[0] != TYPED_COMMUTATIVE_ALGEBRA_OPENMATH_CDBASE:
            continue
        type_annotation |= symbol[1:] == ("typed1", "type")
        binder |= symbol[1:] in {("typed1", "forall"), ("typed1", "exists")}
    return type_annotation and binder


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
        == (TYPED_COMMUTATIVE_ALGEBRA_OPENMATH_CDBASE, "typed1", "type")
    )


def _infer_expression(
    expression: ET.Element,
    *,
    environment: dict[str, CommutativeAlgebraSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> CommutativeAlgebraSort:
    local = _local_name(expression)
    if local == "OMV":
        name = expression.get("name")
        if name is None or name not in environment:
            raise MathXMLValidationError(
                "typed-commutative-algebra-v1 has a free or undeclared variable "
                f"`{name or ''}` at {path}."
            )
        declared = environment[name]
        if declared.name == "comm_ring":
            return CommutativeAlgebraSort("comm_ring", name)
        return declared
    if local == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if local != "OMA":
        raise MathXMLValidationError(
            f"typed-commutative-algebra-v1 cannot infer a sort for `{local}` at {path}."
        )
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(
            f"typed-commutative-algebra-v1 OMA has an invalid operator at {path}."
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
    environment: dict[str, CommutativeAlgebraSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> CommutativeAlgebraSort:
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
                f"typed-commutative-algebra-v1 redeclares bound variable `{name}` at {path}."
            )
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
    environment: dict[str, CommutativeAlgebraSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> tuple[str, CommutativeAlgebraSort]:
    attributes, variable = list(declaration)
    _key, sort_expression = list(attributes)
    name = variable.get("name")
    if name is None or not name:
        raise MathXMLValidationError(
            f"typed-commutative-algebra-v1 bound OMV is missing `name` at {path}."
        )
    sort = _parse_sort(sort_expression, environment=environment, parents=parents, path=path)
    return name, sort


def _parse_sort(
    expression: ET.Element,
    *,
    environment: dict[str, CommutativeAlgebraSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> CommutativeAlgebraSort:
    if _local_name(expression) == "OMS" and _operator_symbol(expression, parents=parents) == (
        TYPED_COMMUTATIVE_ALGEBRA_OPENMATH_CDBASE,
        "commalg1",
        "CommRing",
    ):
        return _COMM_RING
    if _local_name(expression) == "OMA":
        operator, *arguments = list(expression)
        symbol = _operator_symbol(operator, parents=parents)
        if (
            symbol
            in {
                (TYPED_COMMUTATIVE_ALGEBRA_OPENMATH_CDBASE, "commalg1", "Ideal"),
                (TYPED_COMMUTATIVE_ALGEBRA_OPENMATH_CDBASE, "typed1", "Elem"),
            }
            and len(arguments) == 1
            and _local_name(arguments[0]) == "OMV"
        ):
            carrier = arguments[0].get("name")
            if (
                environment.get(carrier or "") is not None
                and environment[carrier or ""].name == "comm_ring"
            ):
                assert carrier is not None
                name: _SortName = "ideal" if symbol[2] == "Ideal" else "element"
                return CommutativeAlgebraSort(name, carrier)
    raise MathXMLValidationError(
        "typed-commutative-algebra-v1 has an invalid type annotation at "
        f"{path}; expected CommRing, Ideal(R), or Elem(R)."
    )


def _infer_application(
    symbol: _Symbol, arguments: list[CommutativeAlgebraSort], *, path: str
) -> CommutativeAlgebraSort:
    cdbase, cd, name = symbol
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "relation1") and name in {"eq", "neq"}:
        _require_arity(symbol, arguments, exact=2)
        if arguments[0] != arguments[1]:
            raise MathXMLValidationError(
                f"Argument 2 of `{cd}:{name}` at {path} must have sort "
                f"`{arguments[0].render()}`; received `{arguments[1].render()}`."
            )
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
    if (cdbase, cd) != (TYPED_COMMUTATIVE_ALGEBRA_OPENMATH_CDBASE, "commalg1"):
        raise MathXMLValidationError(
            f"Unsupported typed-commutative-algebra-v1 application `{cd}:{name}` at {path}."
        )
    if name in {"ideal_bot", "ideal_top"}:
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=1)
        return CommutativeAlgebraSort("ideal", carrier)
    if name in {"ideal_sum", "ideal_inf", "ideal_product"}:
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=3)
        _require_ideal_arguments(symbol, arguments, carrier=carrier, start=1, path=path)
        return CommutativeAlgebraSort("ideal", carrier)
    if name == "ideal_radical":
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=2)
        _require_ideal_arguments(symbol, arguments, carrier=carrier, start=1, path=path)
        return CommutativeAlgebraSort("ideal", carrier)
    if name == "ideal_le":
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=3)
        _require_ideal_arguments(symbol, arguments, carrier=carrier, start=1, path=path)
        return _PROP
    if name in {"is_prime_ideal", "is_maximal_ideal"}:
        carrier = _require_comm_ring(symbol, arguments, path=path, exact=2)
        _require_ideal_arguments(symbol, arguments, carrier=carrier, start=1, path=path)
        return _PROP
    raise MathXMLValidationError(
        f"Unsupported typed-commutative-algebra-v1 application `{cd}:{name}` at {path}."
    )


def _require_comm_ring(
    symbol: _Symbol,
    arguments: list[CommutativeAlgebraSort],
    *,
    path: str,
    exact: int,
) -> str:
    _require_arity(symbol, arguments, exact=exact)
    structure = arguments[0]
    carrier = structure.carrier
    if structure.name != "comm_ring" or carrier is None:
        _raise_expected(symbol, 0, structure, "CommRing", path=path)
    assert carrier is not None
    return carrier


def _require_ideal_arguments(
    symbol: _Symbol,
    arguments: list[CommutativeAlgebraSort],
    *,
    carrier: str,
    start: int,
    path: str,
) -> None:
    expected = CommutativeAlgebraSort("ideal", carrier)
    for index in range(start, len(arguments)):
        _require_argument(symbol, arguments, index, expected, path=path)


def _require_arity(
    symbol: _Symbol,
    arguments: list[CommutativeAlgebraSort],
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
        f"`{cd}:{name}` requires {expectation} arguments; received {len(arguments)}."
    )


def _require_all(
    symbol: _Symbol,
    arguments: list[CommutativeAlgebraSort],
    expected: CommutativeAlgebraSort,
    *,
    path: str,
) -> None:
    for index in range(len(arguments)):
        _require_argument(symbol, arguments, index, expected, path=path)


def _require_argument(
    symbol: _Symbol,
    arguments: list[CommutativeAlgebraSort],
    index: int,
    expected: CommutativeAlgebraSort,
    *,
    path: str,
) -> None:
    actual = arguments[index]
    if actual == expected:
        return
    _raise_expected(symbol, index, actual, expected.render(), path=path)


def _raise_expected(
    symbol: _Symbol,
    index: int,
    actual: CommutativeAlgebraSort,
    expected: str,
    *,
    path: str,
) -> None:
    _base, cd, name = symbol
    raise MathXMLValidationError(
        f"Argument {index + 1} of `{cd}:{name}` at {path} must have sort `{expected}`; "
        f"received `{actual.render()}`."
    )


def _require_sort(
    label: str,
    actual: CommutativeAlgebraSort,
    expected: CommutativeAlgebraSort,
    *,
    path: str,
) -> None:
    if actual == expected:
        return
    raise MathXMLValidationError(
        f"{label} at {path} must have sort `{expected.render()}`; received `{actual.render()}`."
    )
