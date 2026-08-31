"""Fail-closed OpenMath validation for the isolated ``typed-ode-v1`` profile.

The profile describes only concrete, globally defined ``Real -> Real`` solution
certificates.  It deliberately does not extend generic retrieval, typed-math,
or typed-real-analysis.  A v1 certificate contains one explicit initial value
and one all-real first- or second-order ODE equality for the *same* lambda.
Existence, uniqueness, local domains, function variables, and unlisted
initial-value forms are intentionally outside this profile.
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

TYPED_ODE_OPENMATH_CDBASE = "urn:pals:openmath:typed-ode:v1"
TYPED_ODE_PROFILE = "typed-ode-v1"

_SortName = Literal["prop", "nat_literal", "int_literal", "real", "real_function"]
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
            "real_function": "RealFunction",
        }[self.name]


@dataclass(frozen=True, slots=True)
class _Inferred:
    sort: _Sort
    integer_literal: int | None = None


_PROP = _Sort("prop")
_NAT_LITERAL = _Sort("nat_literal")
_INT_LITERAL = _Sort("int_literal")
_REAL = _Sort("real")
_REAL_FUNCTION = _Sort("real_function")


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-ode-v1-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - package invariant
        raise RuntimeError("typed-ode-v1 symbol registry is unavailable.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "pals.typed-ode-registry.v1"
        or payload.get("profile_id") != TYPED_ODE_PROFILE
        or payload.get("cdbases")
        != {"standard": OPENMATH_STANDARD_CDBASE, "typed": TYPED_ODE_OPENMATH_CDBASE}
    ):  # pragma: no cover - package invariant
        raise RuntimeError("typed-ode-v1 symbol registry header is invalid.")
    entries = payload.get("symbols")
    if not isinstance(entries, list):  # pragma: no cover - package invariant
        raise RuntimeError("typed-ode-v1 symbol registry has no symbols list.")
    symbols: set[_Symbol] = set()
    for entry in entries:
        if not isinstance(entry, dict):  # pragma: no cover - package invariant
            raise RuntimeError("typed-ode-v1 symbol registry entry is invalid.")
        identity = tuple(entry.get(key) for key in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError("typed-ode-v1 symbol registry identity is invalid.")
        symbols.add(cast(_Symbol, identity))
    if len(symbols) != len(entries):  # pragma: no cover - package invariant
        raise RuntimeError("typed-ode-v1 symbol registry contains duplicates.")
    return frozenset(symbols)


_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_ode_openmath_xml(xml: str) -> str:
    """Validate and canonicalize one closed typed ODE v1 certificate."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("OpenMath XML exceeds the typed-ode byte bound.")
    root = validate_openmath_xml(xml)
    validate_typed_ode_openmath_root(root)
    return _canonicalize_openmath_v4_root(root)


def validate_canonical_typed_ode_openmath_xml(xml: str) -> str:
    """Accept only exact canonical bytes for this isolated profile."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError("OpenMath XML is not exact typed-ode canonical bytes.")
    canonical = canonicalize_typed_ode_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError("OpenMath XML is not exact typed-ode canonical bytes.")
    return canonical


def validate_typed_ode_openmath_xml(xml: str) -> None:
    """Validate one closed ``typed-ode-v1`` solution certificate."""
    root = validate_openmath_xml(xml)
    validate_typed_ode_openmath_root(root)


def validate_typed_ode_openmath_root(root: ET.Element) -> None:
    """Validate an already XML-valid OpenMath root under the ODE profile."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("OpenMath typed-ode tree exceeds 4,096 nodes.")
    parents = _openmath_parents(root)
    _validate_tree_shape(root, nodes=nodes, parents=parents)
    expression = list(root)[0]
    inferred = _infer_expression(expression, environment={}, parents=parents, path="root")
    if inferred.sort != _PROP:
        raise MathXMLValidationError("typed-ode-v1 root must have sort `Prop`.")
    _validate_solution_certificate(expression, parents=parents)


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
                f"OpenMath element `{local_name}` is outside typed-ode-v1."
            )
        _validate_attributes(element, local_name=local_name)
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("OpenMath typed-ode tree exceeds depth 64.")
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError("OpenMath typed-ode text exceeds 20,000 code points.")
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError("typed-ode-v1 elements cannot have text tails.")
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError("typed-ode-v1 attribute exceeds 20,000 code points.")
        if local_name == "OMATTR":
            parent = parents.get(element)
            if (
                parent is None
                or _local_name(parent) != "OMBVAR"
                or not _is_type_declaration(element, parents=parents)
            ):
                raise MathXMLValidationError(
                    "typed-ode-v1 permits OMATTR only as one typed OMBVAR declaration."
                )
        if local_name == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                not _is_type_declaration(declaration, parents=parents)
                for declaration in declarations
            ):
                raise MathXMLValidationError(
                    "typed-ode-v1 OMBVAR requires 1..256 typed OMV declarations."
                )
        if local_name == "OMBIND":
            binder, variables, _body = list(element)
            symbol = _operator_symbol(binder, parents=parents)
            if symbol is None or symbol not in _SYMBOL_REGISTRY:
                raise MathXMLValidationError("typed-ode-v1 OMBIND uses an unknown binder.")
            if binder.get("cdbase") != TYPED_ODE_OPENMATH_CDBASE:
                raise MathXMLValidationError(
                    "typed-ode-v1 binders must directly declare the typed cdbase."
                )
            if symbol[1:] not in {("typed1", "forall"), ("ode1", "lambda")}:
                raise MathXMLValidationError("typed-ode-v1 OMBIND has an unsupported binder.")
            if symbol[1:] == ("ode1", "lambda") and len(list(variables)) != 1:
                raise MathXMLValidationError(
                    "typed-ode-v1 ode1:lambda binds exactly one Real variable."
                )
        if local_name == "OMA" and _local_name(list(element)[0]) != "OMS":
            raise MathXMLValidationError("typed-ode-v1 OMA head must be an OMS.")
        if local_name == "OMS":
            _validate_symbol(element, parents=parents)


def _validate_attributes(element: ET.Element, *, local_name: str) -> None:
    actual = set(element.attrib)
    unexpected = actual - _ALLOWED_ATTRIBUTES[local_name]
    if unexpected:
        raise MathXMLValidationError(
            f"typed-ode-v1 `{local_name}` does not permit attribute `{sorted(unexpected)[0]}`."
        )
    if local_name == "OMOBJ" and actual != {"version"}:
        raise MathXMLValidationError("typed-ode-v1 OMOBJ requires only `version`.")
    if local_name == "OMS" and not {"cd", "name"}.issubset(actual):
        raise MathXMLValidationError("typed-ode-v1 OMS requires `cd` and `name`.")
    if local_name == "OMV" and actual != {"name"}:
        raise MathXMLValidationError("typed-ode-v1 OMV requires only `name`.")


def _validate_symbol(element: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed-ode-v1 OMS must identify a symbol.")
    direct_cdbase = element.get("cdbase")
    if symbol[0] == TYPED_ODE_OPENMATH_CDBASE:
        if direct_cdbase != TYPED_ODE_OPENMATH_CDBASE:
            raise MathXMLValidationError("typed-ode-v1 OMS must directly declare its typed cdbase.")
    elif symbol[0] == OPENMATH_STANDARD_CDBASE and direct_cdbase is None:
        ancestor = parents.get(element)
        while ancestor is not None:
            if "cdbase" in ancestor.attrib:
                raise MathXMLValidationError(
                    "Standard typed-ode-v1 OMS may omit cdbase only without inherited cdbase."
                )
            ancestor = parents.get(ancestor)
    if symbol not in _SYMBOL_REGISTRY:
        _cdbase, cd, name = symbol
        raise MathXMLValidationError(f"Symbol `{cd}:{name}` is outside typed-ode-v1.")


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
        == (TYPED_ODE_OPENMATH_CDBASE, "typed1", "type")
    )


def _infer_expression(
    expression: ET.Element,
    *,
    environment: dict[str, _Sort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> _Inferred:
    local_name = _local_name(expression)
    if local_name == "OMV":
        name = expression.get("name")
        if name is None or name not in environment:
            raise MathXMLValidationError(
                f"typed-ode-v1 has a free or undeclared variable `{name or ''}` at {path}."
            )
        return _Inferred(environment[name])
    if local_name == "OMI":
        value = "".join((expression.text or "").split())
        if not _INTEGER_RE.fullmatch(value):
            raise MathXMLValidationError(
                "typed-ode-v1 admits only finite decimal OMI integer literals."
            )
        parsed = int(value)
        if len(value.removeprefix("-")) > 10:
            raise MathXMLValidationError("typed-ode-v1 OMI literal exceeds the v1 bound.")
        return _Inferred(_NAT_LITERAL if parsed >= 0 else _INT_LITERAL, parsed)
    if local_name == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if local_name != "OMA":
        raise MathXMLValidationError(
            f"typed-ode-v1 cannot infer a sort for `{local_name}` at {path}."
        )
    operator, *argument_nodes = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(f"typed-ode-v1 OMA has an invalid operator at {path}.")
    arguments = [
        _infer_expression(node, environment=environment, parents=parents, path=f"{path}/{index}")
        for index, node in enumerate(argument_nodes, start=1)
    ]
    return _infer_application(symbol, arguments, path=path)


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
    declaration_sorts: list[_Sort] = []
    for index, declaration in enumerate(list(variables), start=1):
        name, sort = _parse_declaration(
            declaration, environment=local_environment, parents=parents, path=f"{path}/bind/{index}"
        )
        if name in declared or name in environment:
            raise MathXMLValidationError(
                f"typed-ode-v1 redeclares bound variable `{name}` at {path}."
            )
        declared.add(name)
        local_environment[name] = sort
        declaration_sorts.append(sort)
    body_sort = _infer_expression(
        body, environment=local_environment, parents=parents, path=f"{path}/body"
    )
    if symbol[1:] == ("typed1", "forall"):
        _require_sort("typed binder body", body_sort, _PROP, path=path)
        return _Inferred(_PROP)
    if len(declaration_sorts) != 1 or declaration_sorts[0] != _REAL:
        raise MathXMLValidationError("typed-ode-v1 ode1:lambda binds one variable of sort `Real`.")
    _require_sort("ode1:lambda body", body_sort, _REAL, path=path)
    return _Inferred(_REAL_FUNCTION)


def _parse_declaration(
    declaration: ET.Element,
    *,
    environment: dict[str, _Sort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> tuple[str, _Sort]:
    del environment
    attributes, variable = list(declaration)
    _type_key, sort_expression = list(attributes)
    name = variable.get("name")
    if name is None or not name:
        raise MathXMLValidationError(f"typed-ode-v1 bound OMV is missing `name` at {path}.")
    if _local_name(sort_expression) == "OMS" and _operator_symbol(
        sort_expression, parents=parents
    ) == (TYPED_ODE_OPENMATH_CDBASE, "typed1", "Real"):
        return name, _REAL
    raise MathXMLValidationError(
        f"typed-ode-v1 has an invalid type annotation at {path}; expected Real."
    )


def _infer_application(symbol: _Symbol, arguments: list[_Inferred], *, path: str) -> _Inferred:
    cdbase, cd, name = symbol
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "relation1") and name == "eq":
        _require_arity(symbol, arguments, exact=2)
        if arguments[0].sort != arguments[1].sort:
            raise MathXMLValidationError(
                f"Argument 2 of `{cd}:{name}` at {path} must have sort "
                f"`{arguments[0].sort.render()}`; received `{arguments[1].sort.render()}`."
            )
        return _Inferred(_PROP)
    if (cdbase, cd, name) == (OPENMATH_STANDARD_CDBASE, "logic1", "and"):
        _require_arity(symbol, arguments, exact=2)
        _require_all(symbol, arguments, _PROP, path=path)
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
                or exponent.integer_literal > 8
            ):
                raise MathXMLValidationError(
                    f"Argument 2 of `arith1:power` at {path} must be a 0..8 Nat literal."
                )
            return _Inferred(_REAL)
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "transc1") and name in {"exp", "sin", "cos"}:
        _require_arity(symbol, arguments, exact=1)
        _require_argument(symbol, arguments, 0, _REAL, path=path)
        return _Inferred(_REAL)
    if (cdbase, cd) == (TYPED_ODE_OPENMATH_CDBASE, "ode1"):
        if name == "of_int":
            _require_arity(symbol, arguments, exact=1)
            if arguments[0].sort not in {_NAT_LITERAL, _INT_LITERAL}:
                raise MathXMLValidationError(
                    f"Argument 1 of `ode1:of_int` at {path} must be an integer literal."
                )
            return _Inferred(_REAL)
        if name == "apply":
            _require_arity(symbol, arguments, exact=2)
            _require_argument(symbol, arguments, 0, _REAL_FUNCTION, path=path)
            _require_argument(symbol, arguments, 1, _REAL, path=path)
            return _Inferred(_REAL)
        if name in {"deriv_at", "second_deriv_at"}:
            _require_arity(symbol, arguments, exact=2)
            _require_argument(symbol, arguments, 0, _REAL_FUNCTION, path=path)
            _require_argument(symbol, arguments, 1, _REAL, path=path)
            return _Inferred(_REAL)
        if name == "initial_value":
            _require_arity(symbol, arguments, exact=3)
            _require_argument(symbol, arguments, 0, _REAL_FUNCTION, path=path)
            _require_argument(symbol, arguments, 1, _REAL, path=path)
            _require_argument(symbol, arguments, 2, _REAL, path=path)
            return _Inferred(_PROP)
    raise MathXMLValidationError(f"Unsupported typed-ode-v1 application `{cd}:{name}` at {path}.")


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
    _cdbase, cd, name = symbol
    expected = str(exact) if exact is not None else f"at least {minimum}"
    raise MathXMLValidationError(
        f"`{cd}:{name}` requires {expected} arguments; received {len(arguments)}."
    )


def _require_all(
    symbol: _Symbol, arguments: list[_Inferred], expected: _Sort, *, path: str
) -> None:
    for index in range(len(arguments)):
        _require_argument(symbol, arguments, index, expected, path=path)


def _require_argument(
    symbol: _Symbol,
    arguments: list[_Inferred],
    index: int,
    expected: _Sort,
    *,
    path: str,
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


def _validate_solution_certificate(
    expression: ET.Element, *, parents: dict[ET.Element, ET.Element]
) -> None:
    """Require the narrow v1 form ``params -> initial_value(f) ∧ forall x, ODE(f, x)``."""
    outer_environment: dict[str, str] = {}
    current = expression
    ordinal = 0
    while _is_binder(current, parents=parents, cd="typed1", name="forall"):
        _binder, variables, body = list(current)
        for declaration in list(variables):
            name = _declaration_name(declaration)
            ordinal += 1
            outer_environment[name] = f"p{ordinal}"
        current = body
    if not _is_application(
        current,
        parents=parents,
        cdbase=OPENMATH_STANDARD_CDBASE,
        cd="logic1",
        name="and",
    ):
        raise MathXMLValidationError(
            "typed-ode-v1 requires an explicit initial value conjoined with a global ODE equality."
        )
    _head, initial, global_ode = list(current)
    initial_function = _initial_value_function(initial, parents=parents)
    time_name, ode_body = _global_real_line_body(global_ode, parents=parents)
    derivative_functions = _derivative_functions(ode_body, parents=parents)
    if len(derivative_functions) != 1:
        raise MathXMLValidationError(
            "typed-ode-v1 global ODE equality must contain exactly one supported derivative term."
        )
    derivative_function, derivative_point = derivative_functions[0]
    if _local_name(derivative_point) != "OMV" or derivative_point.get("name") != time_name:
        raise MathXMLValidationError(
            "typed-ode-v1 derivative must be evaluated at the all-real domain variable."
        )
    initial_fingerprint = _function_fingerprint(initial_function, environment=outer_environment)
    derivative_fingerprint = _function_fingerprint(
        derivative_function, environment=outer_environment
    )
    if initial_fingerprint != derivative_fingerprint:
        raise MathXMLValidationError(
            "typed-ode-v1 initial value and ODE equality must use the same Real -> Real lambda."
        )
    for applied_function, applied_point in _applied_functions(ode_body, parents=parents):
        applied_fingerprint = _function_fingerprint(
            applied_function, environment=outer_environment
        )
        if applied_fingerprint != initial_fingerprint:
            raise MathXMLValidationError(
                "typed-ode-v1 ODE equality must apply the same Real -> Real lambda "
                "as its initial value."
            )
        if _local_name(applied_point) != "OMV" or applied_point.get("name") != time_name:
            raise MathXMLValidationError(
                "typed-ode-v1 function application must use the all-real domain variable."
            )


def _initial_value_function(
    expression: ET.Element, *, parents: dict[ET.Element, ET.Element]
) -> ET.Element:
    if not _is_application(
        expression,
        parents=parents,
        cdbase=TYPED_ODE_OPENMATH_CDBASE,
        cd="ode1",
        name="initial_value",
    ):
        raise MathXMLValidationError(
            "typed-ode-v1 requires one explicit ode1:initial_value premise."
        )
    _head, function, initial_time, _initial_value = list(expression)
    if not _is_zero(initial_time, parents=parents):
        raise MathXMLValidationError("typed-ode-v1 v1 admits only the explicit initial time 0.")
    if not _is_binder(function, parents=parents, cd="ode1", name="lambda"):
        raise MathXMLValidationError(
            "typed-ode-v1 initial_value must certify a literal Real -> Real lambda."
        )
    return function


def _global_real_line_body(
    expression: ET.Element, *, parents: dict[ET.Element, ET.Element]
) -> tuple[str, ET.Element]:
    if not _is_binder(expression, parents=parents, cd="typed1", name="forall"):
        raise MathXMLValidationError("typed-ode-v1 requires a forall-Real global domain clause.")
    _binder, variables, body = list(expression)
    declarations = list(variables)
    if len(declarations) != 1:
        raise MathXMLValidationError("typed-ode-v1 global domain binds exactly one Real variable.")
    name = _declaration_name(declarations[0])
    if not _declaration_has_real_sort(declarations[0], parents=parents):
        raise MathXMLValidationError("typed-ode-v1 global domain must quantify a Real variable.")
    if not _is_application(
        body, parents=parents, cdbase=OPENMATH_STANDARD_CDBASE, cd="relation1", name="eq"
    ):
        raise MathXMLValidationError("typed-ode-v1 global domain body must be an ODE equality.")
    return name, body


def _derivative_functions(
    expression: ET.Element, *, parents: dict[ET.Element, ET.Element]
) -> list[tuple[ET.Element, ET.Element]]:
    found: list[tuple[ET.Element, ET.Element]] = []
    for node in expression.iter(f"{{{OPENMATH_NAMESPACE}}}OMA"):
        children = list(node)
        symbol = _operator_symbol(children[0], parents=parents)
        if symbol is None or symbol[:2] != (TYPED_ODE_OPENMATH_CDBASE, "ode1"):
            continue
        if symbol[2] in {"deriv_at", "second_deriv_at"}:
            _head, function, point = children
            if not _is_binder(function, parents=parents, cd="ode1", name="lambda"):
                raise MathXMLValidationError(
                    "typed-ode-v1 derivative requires a literal Real -> Real lambda."
                )
            found.append((function, point))
    return found


def _applied_functions(
    expression: ET.Element, *, parents: dict[ET.Element, ET.Element]
) -> list[tuple[ET.Element, ET.Element]]:
    found: list[tuple[ET.Element, ET.Element]] = []
    for node in expression.iter(f"{{{OPENMATH_NAMESPACE}}}OMA"):
        children = list(node)
        if _operator_symbol(children[0], parents=parents) != (
            TYPED_ODE_OPENMATH_CDBASE,
            "ode1",
            "apply",
        ):
            continue
        _head, function, point = children
        if not _is_binder(function, parents=parents, cd="ode1", name="lambda"):
            raise MathXMLValidationError(
                "typed-ode-v1 apply requires a literal Real -> Real lambda."
            )
        found.append((function, point))
    return found


def _is_binder(
    element: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
    cd: str,
    name: str,
) -> bool:
    if _local_name(element) != "OMBIND":
        return False
    binder, _variables, _body = list(element)
    return _operator_symbol(binder, parents=parents) == (TYPED_ODE_OPENMATH_CDBASE, cd, name)


def _is_application(
    element: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
    cdbase: str,
    cd: str,
    name: str,
) -> bool:
    if _local_name(element) != "OMA":
        return False
    head, *_arguments = list(element)
    return _operator_symbol(head, parents=parents) == (cdbase, cd, name)


def _is_zero(element: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> bool:
    if not _is_application(
        element, parents=parents, cdbase=TYPED_ODE_OPENMATH_CDBASE, cd="ode1", name="of_int"
    ):
        return False
    _head, literal = list(element)
    return _local_name(literal) == "OMI" and (literal.text or "").strip() == "0"


def _declaration_name(declaration: ET.Element) -> str:
    _attributes, variable = list(declaration)
    name = variable.get("name")
    assert name is not None  # guaranteed by inference before shape validation
    return name


def _declaration_has_real_sort(
    declaration: ET.Element, *, parents: dict[ET.Element, ET.Element]
) -> bool:
    attributes, _variable = list(declaration)
    _type_key, sort = list(attributes)
    return _operator_symbol(sort, parents=parents) == (TYPED_ODE_OPENMATH_CDBASE, "typed1", "Real")


def _function_fingerprint(
    function: ET.Element, *, environment: dict[str, str]
) -> tuple[object, ...]:
    """Render a lambda structurally while preserving outer parameter identity.

    The profile C14N alpha-normalizes binders later; this local fingerprint is
    only the pre-C14N link between the initial-value and ODE clauses.
    """

    counter = 0

    def render(node: ET.Element, bindings: dict[str, str]) -> tuple[object, ...]:
        nonlocal counter
        local = _local_name(node)
        if local == "OMS":
            return ("OMS", node.get("cdbase"), node.get("cd"), node.get("name"))
        if local == "OMI":
            return ("OMI", "".join((node.text or "").split()))
        if local == "OMV":
            name = node.get("name") or ""
            return ("OMV", bindings.get(name, environment.get(name, f"free:{name}")))
        if local == "OMA":
            return ("OMA", *(render(child, bindings) for child in list(node)))
        if local == "OMBIND":
            binder, variables, body = list(node)
            nested = dict(bindings)
            rendered_variables: list[tuple[object, ...]] = []
            for declaration in list(variables):
                counter += 1
                token = f"b{counter}"
                attributes, variable = list(declaration)
                _type_key, sort = list(attributes)
                name = variable.get("name") or ""
                nested[name] = token
                rendered_variables.append(("DECL", token, render(sort, bindings)))
            return (
                "OMBIND",
                render(binder, bindings),
                tuple(rendered_variables),
                render(body, nested),
            )
        raise AssertionError(f"unexpected validated OpenMath node {local}")

    return render(function, {})
