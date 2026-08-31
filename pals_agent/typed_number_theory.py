"""Fail-closed OpenMath validation for ``typed-number-theory-v1``.

This profile deliberately separates elementary number theory from generic
retrieval and the group/ring profile.  In particular, it has distinct ``Nat``
and ``Int`` carriers, no implicit coercions, and no totalized interpretation
of a zero modulus.
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

TYPED_NUMBER_THEORY_OPENMATH_CDBASE = "urn:pals:openmath:typed-number-theory:v1"
TYPED_NUMBER_THEORY_PROFILE = "typed-number-theory-v1"

_SortName = Literal["prop", "nat", "int", "integer_literal"]
_Symbol = tuple[str, str, str]
_TYPED_BINDERS = frozenset({"forall", "exists"})
_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
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
class NumberTheorySort:
    """A non-coercible sort in the elementary number-theory profile."""

    name: _SortName

    def render(self) -> str:
        return {
            "prop": "Prop",
            "nat": "Nat",
            "int": "Int",
            "integer_literal": "untyped integer literal",
        }[self.name]


@dataclass(frozen=True, slots=True)
class _Inferred:
    sort: NumberTheorySort
    integer_literal: int | None = None


_PROP = NumberTheorySort("prop")
_NAT = NumberTheorySort("nat")
_INT = NumberTheorySort("int")
_INTEGER_LITERAL = NumberTheorySort("integer_literal")


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-number-theory-v1-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - package invariant
        raise RuntimeError("typed-number-theory-v1 symbol registry is unavailable.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "pals.typed-number-theory-registry.v1"
        or payload.get("profile_id") != TYPED_NUMBER_THEORY_PROFILE
        or payload.get("cdbases")
        != {
            "standard": OPENMATH_STANDARD_CDBASE,
            "typed": TYPED_NUMBER_THEORY_OPENMATH_CDBASE,
        }
        or not isinstance(payload.get("symbols"), list)
    ):  # pragma: no cover - package invariant
        raise RuntimeError("typed-number-theory-v1 symbol registry header is invalid.")
    symbols: set[_Symbol] = set()
    for entry in payload["symbols"]:
        if not isinstance(entry, dict):  # pragma: no cover - package invariant
            raise RuntimeError("typed-number-theory-v1 symbol registry entry is invalid.")
        identity = tuple(entry.get(key) for key in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError("typed-number-theory-v1 symbol registry identity is invalid.")
        symbols.add(cast(_Symbol, identity))
    if len(symbols) != len(payload["symbols"]):  # pragma: no cover - package invariant
        raise RuntimeError("typed-number-theory-v1 symbol registry contains duplicates.")
    return frozenset(symbols)


_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_number_theory_openmath_xml(xml: str) -> str:
    """Validate and canonicalize a closed number-theory proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("OpenMath XML exceeds the typed-number-theory byte bound.")
    root = validate_openmath_xml(xml)
    validate_typed_number_theory_openmath_root(root)
    return _canonicalize_openmath_v4_root(root)


def validate_canonical_typed_number_theory_openmath_xml(xml: str) -> str:
    """Accept only exact canonical bytes for the isolated profile."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError(
            "OpenMath XML is not exact typed-number-theory canonical bytes."
        )
    canonical = canonicalize_typed_number_theory_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError(
            "OpenMath XML is not exact typed-number-theory canonical bytes."
        )
    return canonical


def validate_typed_number_theory_openmath_xml(xml: str) -> None:
    """Validate a closed ``typed-number-theory-v1`` proposition."""
    validate_typed_number_theory_openmath_root(validate_openmath_xml(xml))


def validate_typed_number_theory_openmath_root(root: ET.Element) -> None:
    """Validate an already XML-valid OpenMath root under this profile."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("OpenMath typed-number-theory tree exceeds 4,096 nodes.")
    parents = _openmath_parents(root)
    _validate_tree_shape(nodes, parents=parents)
    if not _contains_profile_construct(root, parents=parents):
        raise MathXMLValidationError("OpenMath XML is not a typed-number-theory-v1 proposition.")
    inferred = _infer_expression(list(root)[0], environment={}, parents=parents, path="root")
    if inferred.sort != _PROP:
        raise MathXMLValidationError("typed-number-theory-v1 root must have sort `Prop`.")


def _validate_tree_shape(
    nodes: list[ET.Element], *, parents: dict[ET.Element, ET.Element]
) -> None:
    for element in nodes:
        local = _local_name(element)
        if local not in _ALLOWED_ATTRIBUTES:
            raise MathXMLValidationError(
                f"OpenMath element `{local}` is outside typed-number-theory-v1."
            )
        _validate_attributes(element, local=local)
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("OpenMath typed-number-theory tree exceeds depth 64.")
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError(
                "OpenMath typed-number-theory text exceeds 20,000 code points."
            )
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError("typed-number-theory-v1 elements cannot have text tails.")
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError(
                "typed-number-theory-v1 attribute exceeds 20,000 code points."
            )
        if local == "OMATTR":
            parent = parents.get(element)
            if (
                parent is None
                or _local_name(parent) != "OMBVAR"
                or not _is_type_declaration(element, parents=parents)
            ):
                raise MathXMLValidationError(
                    "typed-number-theory-v1 permits OMATTR only as a typed OMBVAR declaration."
                )
        if local == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                not _is_type_declaration(item, parents=parents) for item in declarations
            ):
                raise MathXMLValidationError(
                    "typed-number-theory-v1 OMBVAR requires 1..256 typed OMV declarations."
                )
        if local == "OMBIND":
            children = list(element)
            if len(children) != 3:
                raise MathXMLValidationError(
                    "typed-number-theory-v1 OMBIND requires three children."
                )
            symbol = _operator_symbol(children[0], parents=parents)
            if (
                symbol is None
                or symbol[:2] != (TYPED_NUMBER_THEORY_OPENMATH_CDBASE, "typed1")
                or symbol[2] not in _TYPED_BINDERS
                or children[0].get("cdbase") != TYPED_NUMBER_THEORY_OPENMATH_CDBASE
            ):
                raise MathXMLValidationError(
                    "typed-number-theory-v1 OMBIND must use typed1:forall or typed1:exists."
                )
        if local == "OMA":
            children = list(element)
            if not children or _local_name(children[0]) != "OMS":
                raise MathXMLValidationError("typed-number-theory-v1 OMA head must be an OMS.")
        if local == "OMS":
            _validate_symbol(element, parents=parents)


def _validate_attributes(element: ET.Element, *, local: str) -> None:
    actual = set(element.attrib)
    unexpected = actual - _ALLOWED_ATTRIBUTES[local]
    if unexpected:
        raise MathXMLValidationError(
            f"typed-number-theory-v1 `{local}` does not permit attribute `{sorted(unexpected)[0]}`."
        )
    if local == "OMOBJ" and actual != {"version"}:
        raise MathXMLValidationError("typed-number-theory-v1 OMOBJ requires only `version`.")
    if local == "OMS" and not {"cd", "name"}.issubset(actual):
        raise MathXMLValidationError("typed-number-theory-v1 OMS requires `cd` and `name`.")
    if local == "OMV" and actual != {"name"}:
        raise MathXMLValidationError("typed-number-theory-v1 OMV requires only `name`.")


def _validate_symbol(element: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed-number-theory-v1 OMS must identify a symbol.")
    direct_cdbase = element.get("cdbase")
    if symbol[0] == TYPED_NUMBER_THEORY_OPENMATH_CDBASE:
        if direct_cdbase != symbol[0]:
            raise MathXMLValidationError(
                "typed-number-theory-v1 OMS must directly declare its typed cdbase."
            )
    elif symbol[0] == OPENMATH_STANDARD_CDBASE and direct_cdbase is None:
        ancestor = parents.get(element)
        while ancestor is not None:
            if "cdbase" in ancestor.attrib:
                raise MathXMLValidationError(
                    "Standard typed-number-theory-v1 OMS may omit cdbase only without "
                    "inherited cdbase."
                )
            ancestor = parents.get(ancestor)
    if symbol not in _SYMBOL_REGISTRY:
        _base, cd, name = symbol
        raise MathXMLValidationError(f"Symbol `{cd}:{name}` is outside typed-number-theory-v1.")


def _contains_profile_construct(
    root: ET.Element, *, parents: dict[ET.Element, ET.Element]
) -> bool:
    type_annotation = False
    binder = False
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        symbol = _operator_symbol(element, parents=parents)
        if symbol is None or symbol[0] != TYPED_NUMBER_THEORY_OPENMATH_CDBASE:
            continue
        type_annotation |= symbol[1:] == ("typed1", "type")
        binder |= symbol[1] == "typed1" and symbol[2] in _TYPED_BINDERS
    return type_annotation and binder


def _is_type_declaration(
    declaration: ET.Element, *, parents: dict[ET.Element, ET.Element]
) -> bool:
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
        == (TYPED_NUMBER_THEORY_OPENMATH_CDBASE, "typed1", "type")
    )


def _infer_expression(
    expression: ET.Element,
    *,
    environment: dict[str, NumberTheorySort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> _Inferred:
    local = _local_name(expression)
    if local == "OMV":
        name = expression.get("name")
        if name is None or name not in environment:
            raise MathXMLValidationError(
                "typed-number-theory-v1 has a free or undeclared variable "
                f"`{name or ''}` at {path}."
            )
        return _Inferred(environment[name])
    if local == "OMI":
        text = "".join((expression.text or "").split())
        if not _INTEGER.fullmatch(text):
            raise MathXMLValidationError(
                "typed-number-theory-v1 admits only finite decimal OMI integer literals."
            )
        return _Inferred(_INTEGER_LITERAL, int(text))
    if local == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if local != "OMA":
        raise MathXMLValidationError(
            f"typed-number-theory-v1 cannot infer a sort for `{local}` at {path}."
        )
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(
            f"typed-number-theory-v1 OMA has an invalid operator at {path}."
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
    environment: dict[str, NumberTheorySort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> _Inferred:
    _binder, variables, body = list(binding)
    local_environment = dict(environment)
    declared: set[str] = set()
    for index, declaration in enumerate(list(variables), start=1):
        name, sort = _parse_declaration(
            declaration, environment=local_environment, parents=parents, path=f"{path}/bind/{index}"
        )
        if name in declared or name in environment:
            raise MathXMLValidationError(
                f"typed-number-theory-v1 redeclares bound variable `{name}` at {path}."
            )
        declared.add(name)
        local_environment[name] = sort
    body_sort = _infer_expression(
        body,
        environment=local_environment,
        parents=parents,
        path=f"{path}/body",
    )
    _require_sort("typed binder body", body_sort, _PROP, path=path)
    return _Inferred(_PROP)


def _parse_declaration(
    declaration: ET.Element,
    *,
    environment: dict[str, NumberTheorySort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> tuple[str, NumberTheorySort]:
    attributes, variable = list(declaration)
    _type, sort_expression = list(attributes)
    name = variable.get("name")
    if name is None or not name:
        raise MathXMLValidationError(
            f"typed-number-theory-v1 bound OMV is missing `name` at {path}."
        )
    return name, _parse_sort(sort_expression, environment=environment, parents=parents, path=path)


def _parse_sort(
    expression: ET.Element,
    *,
    environment: dict[str, NumberTheorySort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> NumberTheorySort:
    del environment
    if _local_name(expression) == "OMS":
        symbol = _operator_symbol(expression, parents=parents)
        if symbol == (TYPED_NUMBER_THEORY_OPENMATH_CDBASE, "numbertheory1", "Nat"):
            return _NAT
        if symbol == (TYPED_NUMBER_THEORY_OPENMATH_CDBASE, "numbertheory1", "Int"):
            return _INT
    raise MathXMLValidationError(
        "typed-number-theory-v1 has an invalid type annotation at "
        f"{path}; expected Nat or Int."
    )


def _infer_application(symbol: _Symbol, arguments: list[_Inferred], *, path: str) -> _Inferred:
    base, cd, name = symbol
    if (base, cd) == (OPENMATH_STANDARD_CDBASE, "relation1") and name in {"eq", "neq"}:
        _require_arity(symbol, arguments, exact=2)
        if arguments[0].sort != arguments[1].sort:
            raise MathXMLValidationError(
                f"Argument 2 of `{cd}:{name}` at {path} must have sort "
                f"`{arguments[0].sort.render()}`; received `{arguments[1].sort.render()}`."
            )
        return _Inferred(_PROP)
    if (base, cd) == (OPENMATH_STANDARD_CDBASE, "logic1"):
        if name == "implies":
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _PROP, path=path)
            return _Inferred(_PROP)
        if name in {"and", "or"}:
            _require_arity(symbol, arguments, minimum=2)
            _require_all(symbol, arguments, _PROP, path=path)
            return _Inferred(_PROP)
        if name == "not":
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _PROP, path=path)
            return _Inferred(_PROP)
    if (base, cd) != (TYPED_NUMBER_THEORY_OPENMATH_CDBASE, "numbertheory1"):
        raise MathXMLValidationError(
            f"Unsupported typed-number-theory-v1 application `{cd}:{name}` at {path}."
        )
    if name in {"nat_literal", "int_literal"}:
        _require_arity(symbol, arguments, exact=1)
        _require_argument(symbol, arguments, 0, _INTEGER_LITERAL, path=path)
        value = arguments[0].integer_literal
        assert value is not None
        if name == "nat_literal":
            if value < 0:
                raise MathXMLValidationError(
                    "typed-number-theory-v1 Nat literals must be nonnegative."
                )
            return _Inferred(_NAT, value)
        return _Inferred(_INT, value)
    if name in {"nat_add", "nat_mul"}:
        _require_arity(symbol, arguments, exact=2)
        _require_all(symbol, arguments, _NAT, path=path)
        return _Inferred(_NAT)
    if name in {"int_add", "int_mul"}:
        _require_arity(symbol, arguments, exact=2)
        _require_all(symbol, arguments, _INT, path=path)
        return _Inferred(_INT)
    if name == "int_neg":
        _require_arity(symbol, arguments, exact=1)
        _require_argument(symbol, arguments, 0, _INT, path=path)
        return _Inferred(_INT)
    if name == "int_of_nat":
        _require_arity(symbol, arguments, exact=1)
        _require_argument(symbol, arguments, 0, _NAT, path=path)
        return _Inferred(_INT)
    if name in {"gcd", "lcm"}:
        _require_arity(symbol, arguments, exact=2)
        _require_all(symbol, arguments, _NAT, path=path)
        return _Inferred(_NAT)
    if name == "nat_mod":
        _require_arity(symbol, arguments, exact=2)
        _require_all(symbol, arguments, _NAT, path=path)
        _require_positive_modulus(symbol, arguments[1], path=path)
        return _Inferred(_NAT)
    if name == "congruent_nat":
        _require_arity(symbol, arguments, exact=3)
        _require_argument(symbol, arguments, 0, _NAT, path=path)
        _require_argument(symbol, arguments, 1, _NAT, path=path)
        _require_argument(symbol, arguments, 2, _NAT, path=path)
        _require_positive_modulus(symbol, arguments[2], path=path)
        return _Inferred(_PROP)
    if name == "divides_nat":
        _require_arity(symbol, arguments, exact=2)
        _require_all(symbol, arguments, _NAT, path=path)
        return _Inferred(_PROP)
    if name == "divides_int":
        _require_arity(symbol, arguments, exact=2)
        _require_all(symbol, arguments, _INT, path=path)
        return _Inferred(_PROP)
    if name == "is_prime":
        _require_arity(symbol, arguments, exact=1)
        _require_argument(symbol, arguments, 0, _NAT, path=path)
        return _Inferred(_PROP)
    raise MathXMLValidationError(
        f"Unsupported typed-number-theory-v1 application `{cd}:{name}` at {path}."
    )


def _require_positive_modulus(symbol: _Symbol, argument: _Inferred, *, path: str) -> None:
    if (
        argument.sort == _NAT
        and argument.integer_literal is not None
        and argument.integer_literal > 0
    ):
        return
    raise MathXMLValidationError(
        f"Argument of `{symbol[1]}:{symbol[2]}` at {path} must be a positive Nat literal "
        "modulus; symbolic and zero moduli are outside typed-number-theory-v1."
    )


def _require_arity(
    symbol: _Symbol,
    arguments: list[_Inferred],
    *,
    exact: int | None = None,
    minimum: int | None = None,
) -> None:
    if (exact is None or len(arguments) == exact) and (
        minimum is None or len(arguments) >= minimum
    ):
        return
    _base, cd, name = symbol
    expectation = str(exact) if exact is not None else f"at least {minimum}"
    raise MathXMLValidationError(
        f"`{cd}:{name}` requires {expectation} arguments; received {len(arguments)}."
    )


def _require_all(
    symbol: _Symbol, arguments: list[_Inferred], expected: NumberTheorySort, *, path: str
) -> None:
    for index in range(len(arguments)):
        _require_argument(symbol, arguments, index, expected, path=path)


def _require_argument(
    symbol: _Symbol,
    arguments: list[_Inferred],
    index: int,
    expected: NumberTheorySort,
    *,
    path: str,
) -> None:
    _require_sort(
        f"Argument {index + 1} of `{symbol[1]}:{symbol[2]}`",
        arguments[index],
        expected,
        path=path,
    )


def _require_sort(label: str, actual: _Inferred, expected: NumberTheorySort, *, path: str) -> None:
    if actual.sort == expected:
        return
    raise MathXMLValidationError(
        f"{label} at {path} must have sort `{expected.render()}`; "
        f"received `{actual.sort.render()}`."
    )
