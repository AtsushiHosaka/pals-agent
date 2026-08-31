"""Fail-closed OpenMath validation for ``typed-multivariable-calculus-v1``.

This opt-in sibling profile admits only bivariate real functions, first
coordinate partial derivatives, and differentiability facts that have direct
pinned-Lean witnesses.  It deliberately has no gradient, Hessian, extremum,
or multiple-integral vocabulary: accepting any of those would overstate the
currently sealed evidence.
"""

# ruff: noqa: E501

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

TYPED_MULTIVARIABLE_CALCULUS_OPENMATH_CDBASE = (
    "urn:pals:openmath:typed-multivariable-calculus:v1"
)
TYPED_MULTIVARIABLE_CALCULUS_PROFILE = "typed-multivariable-calculus-v1"

_SortName = Literal["prop", "nat_literal", "int_literal", "real", "real2", "real2_function"]
_Symbol = tuple[str, str, str]
_INTEGER_RE = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
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
class _Sort:
    name: _SortName

    def render(self) -> str:
        return {
            "prop": "Prop",
            "nat_literal": "Nat literal",
            "int_literal": "integer literal",
            "real": "Real",
            "real2": "Real2",
            "real2_function": "Real2Function",
        }[self.name]


@dataclass(frozen=True, slots=True)
class _Inferred:
    sort: _Sort
    integer_literal: int | None = None


_PROP = _Sort("prop")
_NAT_LITERAL = _Sort("nat_literal")
_INT_LITERAL = _Sort("int_literal")
_REAL = _Sort("real")
_REAL2 = _Sort("real2")
_REAL2_FUNCTION = _Sort("real2_function")
_QUANTIFIERS = frozenset({"forall", "exists"})
_LOGICAL_NARY = frozenset({"and", "or"})
_LOGICAL_BINARY = frozenset({"implies", "equivalent"})


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-multivariable-calculus-v1-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - package invariant
        raise RuntimeError("typed-multivariable-calculus-v1 symbol registry is unavailable.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "pals.typed-multivariable-calculus-registry.v1"
        or payload.get("profile_id") != TYPED_MULTIVARIABLE_CALCULUS_PROFILE
        or payload.get("cdbases")
        != {
            "standard": OPENMATH_STANDARD_CDBASE,
            "typed": TYPED_MULTIVARIABLE_CALCULUS_OPENMATH_CDBASE,
        }
    ):  # pragma: no cover - package invariant
        raise RuntimeError("typed-multivariable-calculus-v1 registry header is invalid.")
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):  # pragma: no cover - package invariant
        raise RuntimeError("typed-multivariable-calculus-v1 registry has no symbols list.")
    identities: set[_Symbol] = set()
    for entry in symbols:
        if not isinstance(entry, dict):  # pragma: no cover - package invariant
            raise RuntimeError("typed-multivariable-calculus-v1 registry entry is invalid.")
        identity = tuple(entry.get(field) for field in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError("typed-multivariable-calculus-v1 registry identity is invalid.")
        identities.add(cast(_Symbol, identity))
    if len(identities) != len(symbols):  # pragma: no cover - package invariant
        raise RuntimeError("typed-multivariable-calculus-v1 registry contains duplicates.")
    return frozenset(identities)


_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_multivariable_calculus_openmath_xml(xml: str) -> str:
    """Validate and canonicalize one closed profile proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError(
            "OpenMath XML exceeds the typed-multivariable-calculus byte bound."
        )
    root = validate_openmath_xml(xml)
    validate_typed_multivariable_calculus_openmath_root(root)
    return _canonicalize_openmath_v4_root(root)


def validate_canonical_typed_multivariable_calculus_openmath_xml(xml: str) -> str:
    """Accept only exact canonical bytes for this isolated profile."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError(
            "OpenMath XML is not exact typed-multivariable-calculus canonical bytes."
        )
    canonical = canonicalize_typed_multivariable_calculus_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError(
            "OpenMath XML is not exact typed-multivariable-calculus canonical bytes."
        )
    return canonical


def validate_typed_multivariable_calculus_openmath_xml(xml: str) -> None:
    """Validate one closed ``typed-multivariable-calculus-v1`` proposition."""
    validate_typed_multivariable_calculus_openmath_root(validate_openmath_xml(xml))


def validate_typed_multivariable_calculus_openmath_root(root: ET.Element) -> None:
    """Validate an XML-valid root under this explicitly selected profile."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("OpenMath typed-multivariable-calculus tree exceeds 4,096 nodes.")
    if len(list(root)) != 1:
        raise MathXMLValidationError("typed-multivariable-calculus-v1 OMOBJ requires one expression.")
    parents = _openmath_parents(root)
    _validate_tree_shape(nodes, parents=parents)
    if not _contains_profile_construct(root, parents=parents):
        raise MathXMLValidationError(
            "OpenMath XML is not a typed-multivariable-calculus-v1 proposition."
        )
    inferred = _infer_expression(list(root)[0], environment={}, parents=parents, path="root")
    if inferred.sort != _PROP:
        raise MathXMLValidationError("typed-multivariable-calculus-v1 root must have sort `Prop`.")


def _validate_tree_shape(nodes: list[ET.Element], *, parents: dict[ET.Element, ET.Element]) -> None:
    for element in nodes:
        local = _local_name(element)
        if local not in _ALLOWED_ATTRIBUTES:
            raise MathXMLValidationError(
                f"OpenMath element `{local}` is outside typed-multivariable-calculus-v1."
            )
        _validate_attributes(element, local=local)
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("OpenMath typed-multivariable-calculus tree exceeds depth 64.")
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError("OpenMath typed-multivariable-calculus text exceeds 20,000 code points.")
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError("typed-multivariable-calculus-v1 elements cannot have text tails.")
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError(
                "typed-multivariable-calculus-v1 attribute exceeds 20,000 code points."
            )
        if local == "OMATTR":
            parent = parents.get(element)
            if (
                parent is None
                or _local_name(parent) != "OMBVAR"
                or not _is_type_declaration(element, parents=parents)
            ):
                raise MathXMLValidationError(
                    "typed-multivariable-calculus-v1 permits OMATTR only as one typed OMBVAR declaration."
                )
        if local == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                not _is_type_declaration(declaration, parents=parents)
                for declaration in declarations
            ):
                raise MathXMLValidationError(
                    "typed-multivariable-calculus-v1 OMBVAR requires 1..256 typed OMV declarations."
                )
        if local == "OMBIND":
            children = list(element)
            if len(children) != 3:
                raise MathXMLValidationError(
                    "typed-multivariable-calculus-v1 OMBIND requires three children."
                )
            symbol = _operator_symbol(children[0], parents=parents)
            if symbol is None or symbol not in _SYMBOL_REGISTRY:
                raise MathXMLValidationError(
                    "typed-multivariable-calculus-v1 OMBIND uses an unknown binder."
                )
            if children[0].get("cdbase") != TYPED_MULTIVARIABLE_CALCULUS_OPENMATH_CDBASE:
                raise MathXMLValidationError(
                    "typed-multivariable-calculus-v1 binders must directly declare the typed cdbase."
                )
            if symbol[1:] not in {
                ("typed1", "forall"),
                ("typed1", "exists"),
                ("multicalc1", "lambda2"),
            }:
                raise MathXMLValidationError(
                    "typed-multivariable-calculus-v1 OMBIND has an unsupported binder."
                )
        if local == "OMA":
            children = list(element)
            if not children or _local_name(children[0]) != "OMS":
                raise MathXMLValidationError(
                    "typed-multivariable-calculus-v1 OMA head must be an OMS."
                )
        if local == "OMS":
            _validate_symbol(element, parents=parents)


def _validate_attributes(element: ET.Element, *, local: str) -> None:
    actual = set(element.attrib)
    unexpected = actual - _ALLOWED_ATTRIBUTES[local]
    if unexpected:
        raise MathXMLValidationError(
            f"typed-multivariable-calculus-v1 `{local}` does not permit attribute `{sorted(unexpected)[0]}`."
        )
    if local == "OMOBJ" and actual != {"version"}:
        raise MathXMLValidationError("typed-multivariable-calculus-v1 OMOBJ requires only `version`.")
    if local == "OMS" and not {"cd", "name"}.issubset(actual):
        raise MathXMLValidationError("typed-multivariable-calculus-v1 OMS requires `cd` and `name`.")
    if local == "OMV" and actual != {"name"}:
        raise MathXMLValidationError("typed-multivariable-calculus-v1 OMV requires only `name`.")


def _validate_symbol(element: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed-multivariable-calculus-v1 OMS must identify a symbol.")
    direct_cdbase = element.get("cdbase")
    if symbol[0] == TYPED_MULTIVARIABLE_CALCULUS_OPENMATH_CDBASE:
        if direct_cdbase != symbol[0]:
            raise MathXMLValidationError(
                "typed-multivariable-calculus-v1 OMS must directly declare its typed cdbase."
            )
    elif symbol[0] == OPENMATH_STANDARD_CDBASE and direct_cdbase is None:
        ancestor = parents.get(element)
        while ancestor is not None:
            if "cdbase" in ancestor.attrib:
                raise MathXMLValidationError(
                    "Standard typed-multivariable-calculus-v1 OMS may omit cdbase only without inherited cdbase."
                )
            ancestor = parents.get(ancestor)
    if symbol not in _SYMBOL_REGISTRY:
        _base, cd, name = symbol
        raise MathXMLValidationError(
            f"Symbol `{cd}:{name}` is outside typed-multivariable-calculus-v1."
        )


def _contains_profile_construct(
    root: ET.Element, *, parents: dict[ET.Element, ET.Element]
) -> bool:
    type_annotation = False
    binder = False
    multivariable_construct = False
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        symbol = _operator_symbol(element, parents=parents)
        if symbol is None or symbol[0] != TYPED_MULTIVARIABLE_CALCULUS_OPENMATH_CDBASE:
            continue
        type_annotation |= symbol[1:] == ("typed1", "type")
        binder |= symbol[1:] in {("typed1", "forall"), ("typed1", "exists")}
        multivariable_construct |= symbol[1] == "multicalc1"
    return type_annotation and binder and multivariable_construct


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
        == (TYPED_MULTIVARIABLE_CALCULUS_OPENMATH_CDBASE, "typed1", "type")
    )


def _infer_expression(
    expression: ET.Element,
    *,
    environment: dict[str, _Sort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> _Inferred:
    local = _local_name(expression)
    if local == "OMV":
        name = expression.get("name")
        if name is None or name not in environment:
            raise MathXMLValidationError(
                "typed-multivariable-calculus-v1 has a free or undeclared variable "
                f"`{name or ''}` at {path}."
            )
        return _Inferred(environment[name])
    if local == "OMI":
        raw = "".join((expression.text or "").split())
        if not _INTEGER_RE.fullmatch(raw):
            raise MathXMLValidationError(
                "typed-multivariable-calculus-v1 admits only finite decimal OMI integer literals."
            )
        value = int(raw)
        return _Inferred(_NAT_LITERAL if value >= 0 else _INT_LITERAL, value)
    if local == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if local != "OMA":
        raise MathXMLValidationError(
            f"typed-multivariable-calculus-v1 cannot infer a sort for `{local}` at {path}."
        )
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(
            f"typed-multivariable-calculus-v1 OMA has an invalid operator at {path}."
        )
    inferred_arguments = [
        _infer_expression(argument, environment=environment, parents=parents, path=f"{path}/{index}")
        for index, argument in enumerate(arguments, start=1)
    ]
    return _infer_application(symbol, inferred_arguments, path=path)


def _infer_binding(
    binding: ET.Element,
    *,
    environment: dict[str, _Sort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> _Inferred:
    binder, variables, body = list(binding)
    symbol = _operator_symbol(binder, parents=parents)
    assert symbol is not None
    local_environment = dict(environment)
    declared: set[str] = set()
    sorts: list[_Sort] = []
    for index, declaration in enumerate(list(variables), start=1):
        name, sort = _parse_declaration(
            declaration, parents=parents, path=f"{path}/bind/{index}"
        )
        if name in declared or name in environment:
            raise MathXMLValidationError(
                f"typed-multivariable-calculus-v1 redeclares bound variable `{name}` at {path}."
            )
        declared.add(name)
        local_environment[name] = sort
        sorts.append(sort)
    body_sort = _infer_expression(body, environment=local_environment, parents=parents, path=f"{path}/body")
    if symbol[1:] in {("typed1", "forall"), ("typed1", "exists")}:
        _require_sort("typed binder body", body_sort, _PROP, path=path)
        return _Inferred(_PROP)
    if len(sorts) != 1 or sorts[0] != _REAL2:
        raise MathXMLValidationError(
            "typed-multivariable-calculus-v1 multicalc1:lambda2 binds one Real2 variable."
        )
    _require_sort("multicalc1:lambda2 body", body_sort, _REAL, path=path)
    return _Inferred(_REAL2_FUNCTION)


def _parse_declaration(
    declaration: ET.Element, *, parents: dict[ET.Element, ET.Element], path: str
) -> tuple[str, _Sort]:
    attributes, variable = list(declaration)
    _key, sort_expression = list(attributes)
    name = variable.get("name")
    if name is None or not name:
        raise MathXMLValidationError(
            f"typed-multivariable-calculus-v1 bound OMV is missing `name` at {path}."
        )
    symbol = _operator_symbol(sort_expression, parents=parents)
    sorts = {
        (TYPED_MULTIVARIABLE_CALCULUS_OPENMATH_CDBASE, "typed1", "Real"): _REAL,
        (TYPED_MULTIVARIABLE_CALCULUS_OPENMATH_CDBASE, "multicalc1", "Real2"): _REAL2,
        (TYPED_MULTIVARIABLE_CALCULUS_OPENMATH_CDBASE, "multicalc1", "Real2Function"): _REAL2_FUNCTION,
    }
    if symbol not in sorts:
        raise MathXMLValidationError(
            "typed-multivariable-calculus-v1 has an invalid type annotation at "
            f"{path}; expected Real, Real2, or Real2Function."
        )
    return name, sorts[symbol]


def _infer_application(symbol: _Symbol, arguments: list[_Inferred], *, path: str) -> _Inferred:
    cdbase, cd, name = symbol
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "relation1") and name in {"eq", "neq"}:
        _require_arity(symbol, arguments, exact=2)
        if arguments[0].sort != arguments[1].sort:
            raise MathXMLValidationError(
                f"Argument 2 of `{cd}:{name}` at {path} must have sort "
                f"`{arguments[0].sort.render()}`; received `{arguments[1].sort.render()}`."
            )
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
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "arith1"):
        if name in {"plus", "times"}:
            _require_arity(symbol, arguments, minimum=2)
            _require_all(symbol, arguments, _REAL, path=path)
            return _Inferred(_REAL)
        if name == "minus":
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _REAL, path=path)
            return _Inferred(_REAL)
        if name == "unary_minus":
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _REAL, path=path)
            return _Inferred(_REAL)
        if name == "power":
            _require_arity(symbol, arguments, exact=2)
            _require_argument(symbol, arguments, 0, _REAL, path=path)
            exponent = arguments[1]
            if (
                exponent.sort != _NAT_LITERAL
                or exponent.integer_literal is None
                or exponent.integer_literal > 64
            ):
                raise MathXMLValidationError(
                    f"Argument 2 of `arith1:power` at {path} must be a 0..64 Nat literal."
                )
            return _Inferred(_REAL)
    if (cdbase, cd) == (TYPED_MULTIVARIABLE_CALCULUS_OPENMATH_CDBASE, "multicalc1"):
        if name == "of_int":
            _require_arity(symbol, arguments, exact=1)
            if arguments[0].sort not in {_NAT_LITERAL, _INT_LITERAL}:
                raise MathXMLValidationError(
                    f"Argument 1 of `multicalc1:of_int` at {path} must be an integer literal."
                )
            return _Inferred(_REAL)
        if name == "pair":
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _REAL, path=path)
            return _Inferred(_REAL2)
        if name in {"fst", "snd"}:
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _REAL2, path=path)
            return _Inferred(_REAL)
        if name == "apply":
            _require_arity(symbol, arguments, exact=2)
            _require_argument(symbol, arguments, 0, _REAL2_FUNCTION, path=path)
            _require_argument(symbol, arguments, 1, _REAL2, path=path)
            return _Inferred(_REAL)
        if name in {"partial_x_at", "partial_y_at"}:
            _require_arity(symbol, arguments, exact=3)
            _require_argument(symbol, arguments, 0, _REAL2_FUNCTION, path=path)
            _require_argument(symbol, arguments, 1, _REAL2, path=path)
            _require_argument(symbol, arguments, 2, _REAL, path=path)
            return _Inferred(_PROP)
        if name == "differentiable_at":
            _require_arity(symbol, arguments, exact=2)
            _require_argument(symbol, arguments, 0, _REAL2_FUNCTION, path=path)
            _require_argument(symbol, arguments, 1, _REAL2, path=path)
            return _Inferred(_PROP)
    raise MathXMLValidationError(
        f"Unsupported typed-multivariable-calculus-v1 application `{cd}:{name}` at {path}."
    )


def _require_arity(
    symbol: _Symbol,
    arguments: list[_Inferred],
    *,
    exact: int | None = None,
    minimum: int | None = None,
) -> None:
    if (exact is None or len(arguments) == exact) and (minimum is None or len(arguments) >= minimum):
        return
    _base, cd, name = symbol
    expected = str(exact) if exact is not None else f"at least {minimum}"
    raise MathXMLValidationError(
        f"`{cd}:{name}` requires {expected} arguments; received {len(arguments)}."
    )


def _require_all(symbol: _Symbol, arguments: list[_Inferred], expected: _Sort, *, path: str) -> None:
    for index in range(len(arguments)):
        _require_argument(symbol, arguments, index, expected, path=path)


def _require_argument(
    symbol: _Symbol, arguments: list[_Inferred], index: int, expected: _Sort, *, path: str
) -> None:
    _require_sort(
        f"Argument {index + 1} of `{symbol[1]}:{symbol[2]}`", arguments[index], expected, path=path
    )


def _require_sort(label: str, actual: _Inferred, expected: _Sort, *, path: str) -> None:
    if actual.sort == expected:
        return
    raise MathXMLValidationError(
        f"{label} at {path} must have sort `{expected.render()}`; "
        f"received `{actual.sort.render()}`."
    )
