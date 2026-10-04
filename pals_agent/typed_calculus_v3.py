"""Closed typed OpenMath calculus-v3 grammar with Nat powers and real calculus.

Isolated from all v1 and v2 profiles. The signature registry records exact semantics;
validation proves typing/closure, not truth or OpenMath-to-Lean translation.
"""

from __future__ import annotations

import json
import math
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

TYPED_CALCULUS_V3_OPENMATH_CDBASE = "urn:pals:openmath:typed-calculus:v3"
TYPED_CALCULUS_V3_PROFILE = "typed-calculus-v3"

_SortName = Literal[
    "prop", "nat_literal", "int_literal", "real", "real_function", "nat", "real_sequence"
]
_Symbol = tuple[str, str, str]
_DECIMAL_INTEGER_RE = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_LOGICAL_NARY = frozenset({"and", "or"})
_LOGICAL_BINARY = frozenset({"implies", "equivalent"})
_ORDER_RELATIONS = frozenset({"lt", "leq", "gt", "geq"})
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
            "nat": "Nat",
            "real_sequence": "RealSequence",
        }[self.name]


@dataclass(frozen=True, slots=True)
class _Inferred:
    sort: _Sort
    integer_literal: int | None = None


_PROP = _Sort("prop")
_NAT = _Sort("nat")
_NAT_LITERAL = _NAT
_INT_LITERAL = _Sort("int_literal")
_REAL = _Sort("real")
_REAL_FUNCTION = _Sort("real_function")
_REAL_SEQUENCE = _Sort("real_sequence")


_EXPECTED_GROUPS = {
    ("urn:pals:openmath:typed-calculus:v3", "typed3"): "forall exists type Real Nat",
    (
        "urn:pals:openmath:typed-calculus:v3",
        "calculus3",
    ): (
        "RealFunction of_int of_rat lambda apply epsilon_delta_continuous_at continuous_at "
        "differentiable_at has_deriv_at interval_integrable nat_pred nat_succ of_nat exp log "
        "sin cos sqrt arctan continuous differentiable continuous_on_closed "
        "differentiable_on_open interval_integral RealSequence sequence_lambda nat_add "
        "nat_factorial sequence_apply sequence_limit has_sum summable partial_sum tsum rpow "
        "cont_diff_on iterated_deriv iterated_deriv_on taylor_on"
    ),
    ("http://www.openmath.org/cd", "relation1"): "eq neq lt leq gt geq",
    ("http://www.openmath.org/cd", "logic1"): "and or implies equivalent not",
    ("http://www.openmath.org/cd", "arith1"): "plus times minus divide abs unary_minus power",
}
_EXPECTED_SYMBOLS = frozenset(
    (base, cd, name) for (base, cd), names in _EXPECTED_GROUPS.items() for name in names.split()
)


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-calculus-v3-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - packaging invariant
        raise RuntimeError("typed-calculus-v3 symbol registry is unavailable.") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "profile_id", "cdbases", "symbols"}
        or payload.get("schema_version") != "pals.typed-calculus-registry.v3"
        or payload.get("profile_id") != TYPED_CALCULUS_V3_PROFILE
        or payload.get("cdbases")
        != {
            "standard": OPENMATH_STANDARD_CDBASE,
            "typed": TYPED_CALCULUS_V3_OPENMATH_CDBASE,
        }
    ):  # pragma: no cover - packaging invariant
        raise RuntimeError("typed-calculus-v3 symbol registry header is invalid.")
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):  # pragma: no cover - packaging invariant
        raise RuntimeError("typed-calculus-v3 symbol registry has no symbols list.")
    identities: set[_Symbol] = set()
    for entry in symbols:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"cdbase", "cd", "name", "signature", "semantics"}
            or any(not isinstance(value, str) or not value.strip() for value in entry.values())
        ):  # pragma: no cover - packaging invariant
            raise RuntimeError("typed-calculus-v3 symbol registry entry is invalid.")
        identity = tuple(entry.get(field) for field in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError("typed-calculus-v3 symbol registry identity is invalid.")
        identities.add(cast(_Symbol, identity))
    if (
        len(identities) != len(symbols) or frozenset(identities) != _EXPECTED_SYMBOLS
    ):  # pragma: no cover - packaging invariant
        raise RuntimeError("typed-calculus-v3 symbol registry contains duplicates.")
    return frozenset(identities)


_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_calculus_v3_openmath_xml(xml: str) -> str:
    """Validate and canonicalize one closed calculus v3 proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("OpenMath XML exceeds the typed-calculus-v3 byte bound.")
    root = validate_openmath_xml(xml)
    validate_typed_calculus_v3_openmath_root(root)
    return cast(str, _canonicalize_openmath_v4_root(root))


def validate_canonical_typed_calculus_v3_openmath_xml(xml: str) -> str:
    """Accept only exact canonical bytes for this isolated profile."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError("OpenMath XML is not exact typed-calculus-v3 canonical bytes.")
    canonical = canonicalize_typed_calculus_v3_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError("OpenMath XML is not exact typed-calculus-v3 canonical bytes.")
    return canonical


def validate_typed_calculus_v3_openmath_xml(xml: str) -> None:
    """Validate one closed ``typed-calculus-v3`` proposition."""
    canonicalize_typed_calculus_v3_openmath_xml(xml)


def validate_typed_calculus_v3_openmath_root(root: ET.Element) -> None:
    """Validate an already XML-valid OpenMath root for this profile."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("OpenMath typed-calculus-v3 tree exceeds 4,096 nodes.")
    parents = _openmath_parents(root)
    _validate_tree_shape(root, nodes=nodes, parents=parents)
    if not _contains_profile_construct(root, parents=parents):
        raise MathXMLValidationError("OpenMath XML is not a typed-calculus-v3 proposition.")
    inferred = _infer_expression(list(root)[0], environment={}, parents=parents, path="root")
    if inferred.sort != _PROP:
        raise MathXMLValidationError("typed-calculus-v3 root must have sort `Prop`.")


def _validate_tree_shape(
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
                f"OpenMath element `{local_name}` is outside typed-calculus-v3."
            )
        _validate_attributes(element, local_name=local_name)
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("OpenMath typed-calculus-v3 tree exceeds depth 64.")
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError(
                "OpenMath typed-calculus-v3 text exceeds 20,000 code points."
            )
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError("typed-calculus-v3 elements cannot have text tails.")
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError("typed-calculus-v3 attribute exceeds 20,000 code points.")
        if local_name == "OMATTR":
            parent = parents.get(element)
            if (
                parent is None
                or _local_name(parent) != "OMBVAR"
                or not _is_type_declaration(element, parents=parents)
            ):
                raise MathXMLValidationError(
                    "typed-calculus-v3 permits OMATTR only as one typed OMBVAR declaration."
                )
        if local_name == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                not _is_type_declaration(declaration, parents=parents)
                for declaration in declarations
            ):
                raise MathXMLValidationError(
                    "typed-calculus-v3 OMBVAR requires 1..256 typed OMV declarations."
                )
        if local_name == "OMBIND":
            binder, variables, _body = list(element)
            symbol = _operator_symbol(binder, parents=parents)
            if symbol is None or symbol not in _SYMBOL_REGISTRY:
                raise MathXMLValidationError("typed-calculus-v3 OMBIND uses an unknown binder.")
            if symbol[0] != TYPED_CALCULUS_V3_OPENMATH_CDBASE or binder.get("cdbase") != symbol[0]:
                raise MathXMLValidationError(
                    "typed-calculus-v3 binders must directly declare the typed cdbase."
                )
            is_quantifier = symbol[1:] == ("typed3", "forall") or symbol[1:] == ("typed3", "exists")
            is_lambda = symbol[1:] in {("calculus3", "lambda"), ("calculus3", "sequence_lambda")}
            if not (is_quantifier or is_lambda):
                raise MathXMLValidationError("typed-calculus-v3 OMBIND has an unsupported binder.")
            if is_lambda and len(list(variables)) != 1:
                raise MathXMLValidationError(
                    "typed-calculus-v3 calculus3:lambda binds exactly one Real variable."
                )
        if local_name == "OMA":
            children = list(element)
            if _local_name(children[0]) != "OMS":
                raise MathXMLValidationError("typed-calculus-v3 OMA head must be an OMS.")
        if local_name == "OMS":
            _validate_symbol(element, parents=parents)


def _validate_attributes(element: ET.Element, *, local_name: str) -> None:
    allowed = _ALLOWED_ATTRIBUTES[local_name]
    actual = set(element.attrib)
    unexpected = actual - allowed
    if unexpected:
        attribute = sorted(unexpected)[0]
        raise MathXMLValidationError(
            f"typed-calculus-v3 `{local_name}` does not permit attribute `{attribute}`."
        )
    if local_name == "OMOBJ" and actual != {"version"}:
        raise MathXMLValidationError("typed-calculus-v3 OMOBJ requires only `version`.")
    if local_name == "OMS" and not {"cd", "name"}.issubset(actual):
        raise MathXMLValidationError("typed-calculus-v3 OMS requires `cd` and `name`.")
    if local_name == "OMV" and actual != {"name"}:
        raise MathXMLValidationError("typed-calculus-v3 OMV requires only `name`.")


def _validate_symbol(element: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed-calculus-v3 OMS must identify a symbol.")
    direct_cdbase = element.get("cdbase")
    if symbol[0] == TYPED_CALCULUS_V3_OPENMATH_CDBASE:
        if direct_cdbase != symbol[0]:
            raise MathXMLValidationError(
                "typed-calculus-v3 OMS must directly declare its typed cdbase."
            )
    elif symbol[0] == OPENMATH_STANDARD_CDBASE and direct_cdbase is None:
        ancestor = parents.get(element)
        while ancestor is not None:
            if "cdbase" in ancestor.attrib:
                raise MathXMLValidationError(
                    "Standard typed-calculus-v3 OMS may omit cdbase only without inherited cdbase."
                )
            ancestor = parents.get(ancestor)
    if symbol not in _SYMBOL_REGISTRY:
        _cdbase, cd, name = symbol
        raise MathXMLValidationError(f"Symbol `{cd}:{name}` is outside typed-calculus-v3.")


def _contains_profile_construct(
    root: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> bool:
    has_type_annotation = False
    has_profile_binder = False
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        symbol = _operator_symbol(element, parents=parents)
        if symbol is None or symbol[0] != TYPED_CALCULUS_V3_OPENMATH_CDBASE:
            continue
        if symbol[1:] == ("typed3", "type"):
            has_type_annotation = True
        if symbol[1:] in {
            ("typed3", "forall"),
            ("typed3", "exists"),
            ("calculus3", "lambda"),
            ("calculus3", "sequence_lambda"),
        }:
            has_profile_binder = True
    return has_type_annotation and has_profile_binder


def _is_type_declaration(
    declaration: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
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
        == (TYPED_CALCULUS_V3_OPENMATH_CDBASE, "typed3", "type")
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
                f"typed-calculus-v3 has a free or undeclared variable `{name or ''}` at {path}."
            )
        return _Inferred(environment[name])
    if local_name == "OMI":
        value = "".join((expression.text or "").split())
        if not _DECIMAL_INTEGER_RE.fullmatch(value):
            raise MathXMLValidationError(
                "typed-calculus-v3 admits only finite decimal OMI integer literals."
            )
        try:
            parsed = int(value)
        except ValueError as exc:  # pragma: no cover - Python integer guard
            raise MathXMLValidationError(
                "typed-calculus-v3 OMI integer literal is too large."
            ) from exc
        return _Inferred(_NAT_LITERAL if parsed >= 0 else _INT_LITERAL, parsed)
    if local_name == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if local_name != "OMA":
        raise MathXMLValidationError(
            f"typed-calculus-v3 cannot infer a sort for `{local_name}` at {path}."
        )
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(f"typed-calculus-v3 OMA has an invalid operator at {path}.")
    inferred_arguments = [
        _infer_expression(
            argument, environment=environment, parents=parents, path=f"{path}/{index}"
        )
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
    declaration_sorts: list[_Sort] = []
    for index, declaration in enumerate(list(variables), start=1):
        name, sort = _parse_declaration(
            declaration, environment=local_environment, parents=parents, path=f"{path}/bind/{index}"
        )
        if name in declared or name in environment:
            raise MathXMLValidationError(
                f"typed-calculus-v3 redeclares bound variable `{name}` at {path}."
            )
        declared.add(name)
        local_environment[name] = sort
        declaration_sorts.append(sort)
    if symbol[1:] == ("calculus3", "lambda") and (
        len(declaration_sorts) != 1 or declaration_sorts[0] != _REAL
    ):
        raise MathXMLValidationError(
            "typed-calculus-v3 calculus3:lambda binds one variable of sort `Real`."
        )
    body_sort = _infer_expression(
        body, environment=local_environment, parents=parents, path=f"{path}/body"
    )
    if symbol[1:] in {("typed3", "forall"), ("typed3", "exists")}:
        _require_sort("typed binder body", body_sort, _PROP, path=path)
        return _Inferred(_PROP)
    if symbol[1:] == ("calculus3", "sequence_lambda"):
        if len(declaration_sorts) != 1 or declaration_sorts[0] != _NAT:
            raise MathXMLValidationError("sequence_lambda binds exactly one Nat")
        _require_sort("sequence_lambda body", body_sort, _REAL, path=path)
        return _Inferred(_REAL_SEQUENCE)
    assert symbol[1:] == ("calculus3", "lambda")
    _require_sort("calculus3:lambda body", body_sort, _REAL, path=path)
    return _Inferred(_REAL_FUNCTION)


def _parse_declaration(
    declaration: ET.Element,
    *,
    environment: dict[str, _Sort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> tuple[str, _Sort]:
    attributes, variable = list(declaration)
    _type_key, sort_expression = list(attributes)
    name = variable.get("name")
    if name is None or not name:
        raise MathXMLValidationError(f"typed-calculus-v3 bound OMV is missing `name` at {path}.")
    return name, _parse_sort(sort_expression, environment=environment, parents=parents, path=path)


def _parse_sort(
    expression: ET.Element,
    *,
    environment: dict[str, _Sort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> _Sort:
    del environment
    if _local_name(expression) == "OMS":
        symbol = _operator_symbol(expression, parents=parents)
        if symbol == (TYPED_CALCULUS_V3_OPENMATH_CDBASE, "calculus3", "RealSequence"):
            return _REAL_SEQUENCE
        if symbol == (TYPED_CALCULUS_V3_OPENMATH_CDBASE, "typed3", "Nat"):
            return _NAT
        if symbol == (TYPED_CALCULUS_V3_OPENMATH_CDBASE, "typed3", "Real"):
            return _REAL
        if symbol == (TYPED_CALCULUS_V3_OPENMATH_CDBASE, "calculus3", "RealFunction"):
            return _REAL_FUNCTION
    raise MathXMLValidationError(
        "typed-calculus-v3 has an invalid type annotation at "
        f"{path}; expected Real, Nat, or RealFunction."
    )


def _infer_application(symbol: _Symbol, arguments: list[_Inferred], *, path: str) -> _Inferred:
    if len(arguments) > 32:
        raise MathXMLValidationError("calculus-v3 applications are bounded to 32 arguments.")
    cdbase, cd, name = symbol
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "relation1"):
        if name in {"eq", "neq"}:
            _require_arity(symbol, arguments, exact=2)
            if arguments[0].sort != arguments[1].sort:
                raise MathXMLValidationError(
                    f"Argument 2 of `{cd}:{name}` at {path} must have sort "
                    f"`{arguments[0].sort.render()}`; received `{arguments[1].sort.render()}`."
                )
            return _Inferred(_PROP)
        if name in _ORDER_RELATIONS:
            _require_arity(symbol, arguments, exact=2)
            if arguments[0].sort not in {_REAL, _NAT}:
                raise MathXMLValidationError("Order requires Real or Nat operands")
            _require_argument(symbol, arguments, 1, arguments[0].sort, path=path)
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
        if name in {"minus", "divide"}:
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _REAL, path=path)
            return _Inferred(_REAL)
        if name in {"abs", "unary_minus"}:
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _REAL, path=path)
            return _Inferred(_REAL)
        if name == "power":
            _require_arity(symbol, arguments, exact=2)
            _require_argument(symbol, arguments, 0, _REAL, path=path)
            _require_argument(symbol, arguments, 1, _NAT, path=path)
            return _Inferred(_REAL)
    if (cdbase, cd) == (TYPED_CALCULUS_V3_OPENMATH_CDBASE, "calculus3"):
        signatures = {
            "nat_add": ((_NAT, _NAT), _NAT),
            "nat_factorial": ((_NAT,), _NAT),
            "sequence_apply": ((_REAL_SEQUENCE, _NAT), _REAL),
            "sequence_limit": ((_REAL_SEQUENCE, _REAL), _PROP),
            "has_sum": ((_REAL_SEQUENCE, _REAL), _PROP),
            "summable": ((_REAL_SEQUENCE,), _PROP),
            "partial_sum": ((_REAL_SEQUENCE, _NAT), _REAL),
            "tsum": ((_REAL_SEQUENCE,), _REAL),
            "rpow": ((_REAL, _REAL), _REAL),
            "cont_diff_on": ((_NAT, _REAL_FUNCTION, _REAL, _REAL), _PROP),
            "iterated_deriv": ((_NAT, _REAL_FUNCTION), _REAL_FUNCTION),
            "iterated_deriv_on": ((_NAT, _REAL_FUNCTION, _REAL, _REAL), _REAL_FUNCTION),
            "taylor_on": ((_NAT, _REAL_FUNCTION, _REAL, _REAL, _REAL, _REAL), _REAL),
        }
        if name in signatures:
            inputs, output = signatures[name]
            _require_arity(symbol, arguments, exact=len(inputs))
            for i, expected in enumerate(inputs):
                _require_argument(symbol, arguments, i, expected, path=path)
            return _Inferred(output)
        if name in {"nat_pred", "nat_succ"}:
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _NAT, path=path)
            return _Inferred(_NAT)
        if name == "of_nat":
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _NAT, path=path)
            return _Inferred(_REAL)
        if name in {"exp", "log", "sin", "cos", "sqrt", "arctan"}:
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _REAL, path=path)
            return _Inferred(_REAL)
        if name in {"continuous", "differentiable"}:
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _REAL_FUNCTION, path=path)
            return _Inferred(_PROP)
        if name in {"continuous_on_closed", "differentiable_on_open", "interval_integral"}:
            _require_arity(symbol, arguments, exact=3)
            _require_argument(symbol, arguments, 0, _REAL_FUNCTION, path=path)
            _require_argument(symbol, arguments, 1, _REAL, path=path)
            _require_argument(symbol, arguments, 2, _REAL, path=path)
            return _Inferred(_REAL if name == "interval_integral" else _PROP)
        if name == "of_int":
            _require_arity(symbol, arguments, exact=1)
            if arguments[0].integer_literal is None:
                raise MathXMLValidationError(
                    f"Argument 1 of `calculus3:of_int` at {path} must be an integer literal."
                )
            return _Inferred(_REAL)
        if name == "of_rat":
            _require_arity(symbol, arguments, exact=2)
            numerator, denominator = arguments
            if numerator.integer_literal is None or denominator.integer_literal is None:
                raise MathXMLValidationError(
                    f"`calculus3:of_rat` at {path} requires integer literal arguments."
                )
            if (
                denominator.integer_literal <= 0
                or math.gcd(numerator.integer_literal, denominator.integer_literal) != 1
            ):
                raise MathXMLValidationError(
                    f"`calculus3:of_rat` at {path} requires reduced numerator "
                    "and positive nonzero denominator."
                )
            return _Inferred(_REAL)
        if name == "apply":
            _require_arity(symbol, arguments, exact=2)
            _require_argument(symbol, arguments, 0, _REAL_FUNCTION, path=path)
            _require_argument(symbol, arguments, 1, _REAL, path=path)
            return _Inferred(_REAL)
        if name in {"epsilon_delta_continuous_at", "continuous_at", "differentiable_at"}:
            _require_arity(symbol, arguments, exact=2)
            _require_argument(symbol, arguments, 0, _REAL_FUNCTION, path=path)
            _require_argument(symbol, arguments, 1, _REAL, path=path)
            return _Inferred(_PROP)
        if name == "has_deriv_at":
            _require_arity(symbol, arguments, exact=3)
            _require_argument(symbol, arguments, 0, _REAL_FUNCTION, path=path)
            _require_argument(symbol, arguments, 1, _REAL, path=path)
            _require_argument(symbol, arguments, 2, _REAL, path=path)
            return _Inferred(_PROP)
        if name == "interval_integrable":
            _require_arity(symbol, arguments, exact=3)
            _require_argument(symbol, arguments, 0, _REAL_FUNCTION, path=path)
            _require_argument(symbol, arguments, 1, _REAL, path=path)
            _require_argument(symbol, arguments, 2, _REAL, path=path)
            return _Inferred(_PROP)
    raise MathXMLValidationError(
        f"Unsupported typed-calculus-v3 application `{cd}:{name}` at {path}."
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
    _cdbase, cd, name = symbol
    expectation = str(exact) if exact is not None else f"at least {minimum}"
    raise MathXMLValidationError(
        f"`{cd}:{name}` requires {expectation} arguments; received {len(arguments)}."
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
