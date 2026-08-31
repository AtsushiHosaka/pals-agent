"""Fail-closed OpenMath validation for the CA-5 integral/valuation core.

``typed-commutative-algebra-integral-v1`` deliberately represents only one
explicit ring extension and one explicit valuation subring at a time.  It is
not an extension of the generic or previous typed commutative-algebra profiles.
In particular, this module has no syntax for fraction fields, towers,
going-up/down, DVRs, or Dedekind domains.
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

TYPED_COMMUTATIVE_ALGEBRA_INTEGRAL_OPENMATH_CDBASE = (
    "urn:pals:openmath:typed-commutative-algebra-integral:v1"
)
TYPED_COMMUTATIVE_ALGEBRA_INTEGRAL_PROFILE = "typed-commutative-algebra-integral-v1"

_Kind = Literal[
    "prop",
    "comm_ring",
    "domain",
    "field",
    "extension",
    "valuation_ring",
    "element",
]
_Symbol = tuple[str, str, str]
_TYPED = TYPED_COMMUTATIVE_ALGEBRA_INTEGRAL_OPENMATH_CDBASE
_BINDERS = frozenset({"forall", "exists"})
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
class IntegralValuationSort:
    """A profile sort retaining explicit carriers and extension direction."""

    kind: _Kind
    carrier: str | None = None
    base: str | None = None
    ambient_field: str | None = None

    def render(self) -> str:
        if self.kind == "prop":
            return "Prop"
        if self.kind == "comm_ring":
            return "CommRing"
        if self.kind == "domain":
            return "Domain"
        if self.kind == "field":
            return "Field"
        if self.kind == "extension":
            return f"Extension({self.base or '?'})"
        if self.kind == "valuation_ring":
            return f"ValuationRing({self.ambient_field or '?'})"
        return f"Elem({self.carrier or '?'})"


_PROP = IntegralValuationSort("prop")


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-commutative-algebra-integral-v1-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - package invariant
        raise RuntimeError("typed integral/valuation registry is unavailable") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version")
        != "pals.typed-commutative-algebra-integral-registry.v1"
        or payload.get("profile_id") != TYPED_COMMUTATIVE_ALGEBRA_INTEGRAL_PROFILE
        or payload.get("cdbases")
        != {"standard": OPENMATH_STANDARD_CDBASE, "typed": _TYPED}
        or not isinstance(payload.get("symbols"), list)
    ):  # pragma: no cover - package invariant
        raise RuntimeError("typed integral/valuation registry header is invalid")
    entries: set[_Symbol] = set()
    for raw_entry in payload["symbols"]:
        if not isinstance(raw_entry, dict):  # pragma: no cover - package invariant
            raise RuntimeError("typed integral/valuation registry entry is invalid")
        identity = tuple(raw_entry.get(key) for key in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError("typed integral/valuation registry identity is invalid")
        entries.add(cast(_Symbol, identity))
    if len(entries) != len(payload["symbols"]):  # pragma: no cover - package invariant
        raise RuntimeError("typed integral/valuation registry contains duplicates")
    return frozenset(entries)


_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_commutative_algebra_integral_openmath_xml(xml: str) -> str:
    """Validate and return exact C14N-v4 bytes for a closed CA-5 proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("typed integral/valuation XML exceeds 65,536 bytes")
    root = validate_openmath_xml(xml)
    validate_typed_commutative_algebra_integral_openmath_root(root)
    return _canonicalize_openmath_v4_root(root)


def validate_canonical_typed_commutative_algebra_integral_openmath_xml(xml: str) -> str:
    """Accept only exact canonical bytes for this isolated profile."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError("typed integral/valuation XML is not canonical")
    canonical = canonicalize_typed_commutative_algebra_integral_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError("typed integral/valuation XML is not canonical")
    return canonical


def validate_typed_commutative_algebra_integral_openmath_xml(xml: str) -> None:
    """Validate a closed integral-dependence or valuation proposition."""
    validate_typed_commutative_algebra_integral_openmath_root(validate_openmath_xml(xml))


def validate_typed_commutative_algebra_integral_openmath_root(root: ET.Element) -> None:
    """Validate an OpenMath-core-valid root for the isolated CA-5 profile."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("typed integral/valuation tree exceeds 4,096 nodes")
    parents = _openmath_parents(root)
    _validate_tree_shape(nodes, parents=parents)
    if not _contains_profile_construct(root, parents=parents):
        raise MathXMLValidationError("OpenMath XML is not a typed integral/valuation proposition")
    if len(list(root)) != 1:
        raise MathXMLValidationError("typed integral/valuation OMOBJ needs one expression")
    inferred = _infer_expression(list(root)[0], environment={}, parents=parents, path="root")
    if inferred != _PROP:
        raise MathXMLValidationError("typed integral/valuation root must have sort `Prop`")


def _validate_tree_shape(nodes: list[ET.Element], *, parents: dict[ET.Element, ET.Element]) -> None:
    for element in nodes:
        local = _local_name(element)
        if local not in _ALLOWED_ATTRIBUTES:
            raise MathXMLValidationError(
                f"OpenMath element `{local}` is outside typed integral/valuation"
            )
        _validate_attributes(element, local=local)
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("typed integral/valuation tree exceeds depth 64")
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError("typed integral/valuation text exceeds 20,000 code points")
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError("typed integral/valuation elements cannot have text tails")
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError(
                "typed integral/valuation attribute exceeds 20,000 code points"
            )
        if local == "OMATTR":
            parent = parents.get(element)
            if (
                parent is None
                or _local_name(parent) != "OMBVAR"
                or not _is_type_declaration(element, parents=parents)
            ):
                raise MathXMLValidationError(
                    "typed integral/valuation permits OMATTR only as a typed OMBVAR declaration"
                )
        if local == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                not _is_type_declaration(item, parents=parents) for item in declarations
            ):
                raise MathXMLValidationError(
                    "typed integral/valuation OMBVAR requires 1..256 typed OMV declarations"
                )
        if local == "OMBIND":
            children = list(element)
            if len(children) != 3:
                raise MathXMLValidationError("typed integral/valuation OMBIND needs three children")
            symbol = _operator_symbol(children[0], parents=parents)
            if (
                symbol is None
                or symbol[:2] != (_TYPED, "typed1")
                or symbol[2] not in _BINDERS
                or children[0].get("cdbase") != _TYPED
            ):
                raise MathXMLValidationError(
                    "typed integral/valuation OMBIND requires typed1:forall/exists"
                )
        if local == "OMA":
            children = list(element)
            if not children or _local_name(children[0]) != "OMS":
                raise MathXMLValidationError("typed integral/valuation OMA head must be an OMS")
        if local == "OMS":
            _validate_symbol(element, parents=parents)


def _validate_attributes(element: ET.Element, *, local: str) -> None:
    unexpected = set(element.attrib) - _ALLOWED_ATTRIBUTES[local]
    if unexpected:
        raise MathXMLValidationError(
            f"typed integral/valuation `{local}` does not permit `{sorted(unexpected)[0]}`"
        )
    if local == "OMOBJ" and set(element.attrib) != {"version"}:
        raise MathXMLValidationError("typed integral/valuation OMOBJ requires only `version`")
    if local == "OMS" and not {"cd", "name"}.issubset(element.attrib):
        raise MathXMLValidationError("typed integral/valuation OMS requires `cd` and `name`")
    if local == "OMV" and set(element.attrib) != {"name"}:
        raise MathXMLValidationError("typed integral/valuation OMV requires only `name`")


def _validate_symbol(element: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed integral/valuation OMS must identify a symbol")
    direct_cdbase = element.get("cdbase")
    if symbol[0] == _TYPED:
        if direct_cdbase != _TYPED:
            raise MathXMLValidationError(
                "typed integral/valuation OMS must directly declare its typed cdbase"
            )
    elif symbol[0] == OPENMATH_STANDARD_CDBASE and direct_cdbase is None:
        ancestor = parents.get(element)
        while ancestor is not None:
            if "cdbase" in ancestor.attrib:
                raise MathXMLValidationError(
                    "standard typed integral/valuation OMS cannot inherit a cdbase"
                )
            ancestor = parents.get(ancestor)
    if symbol not in _SYMBOL_REGISTRY:
        _base, cd, name = symbol
        raise MathXMLValidationError(f"symbol `{cd}:{name}` is outside typed integral/valuation")


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
    environment: dict[str, IntegralValuationSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> IntegralValuationSort:
    local = _local_name(expression)
    if local == "OMV":
        name = expression.get("name")
        if name is None or name not in environment:
            raise MathXMLValidationError(
                f"typed integral/valuation has free variable `{name or ''}` at {path}"
            )
        return environment[name]
    if local == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if local != "OMA":
        raise MathXMLValidationError(
            f"typed integral/valuation cannot infer `{local}` at {path}"
        )
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(f"typed integral/valuation OMA has invalid operator at {path}")
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
    environment: dict[str, IntegralValuationSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> IntegralValuationSort:
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
            raise MathXMLValidationError(f"typed integral/valuation redeclares `{name}` at {path}")
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
    environment: dict[str, IntegralValuationSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> tuple[str, IntegralValuationSort]:
    attributes, variable = list(declaration)
    _key, sort_expression = list(attributes)
    name = variable.get("name")
    if name is None or not name:
        raise MathXMLValidationError(f"typed integral/valuation bound OMV lacks name at {path}")
    return name, _parse_sort(
        sort_expression, name=name, environment=environment, parents=parents, path=path
    )


def _parse_sort(
    expression: ET.Element,
    *,
    name: str,
    environment: dict[str, IntegralValuationSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> IntegralValuationSort:
    if _local_name(expression) == "OMS":
        symbol = _operator_symbol(expression, parents=parents)
        sorts: dict[_Symbol, _Kind] = {
            (_TYPED, "integral1", "CommRing"): "comm_ring",
            (_TYPED, "integral1", "Domain"): "domain",
            (_TYPED, "integral1", "Field"): "field",
        }
        kind = sorts.get(symbol) if symbol is not None else None
        if kind is not None:
            return IntegralValuationSort(kind, carrier=name)
    if _local_name(expression) != "OMA":
        raise MathXMLValidationError(f"typed integral/valuation invalid type annotation at {path}")
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    names = _sort_argument_names(arguments, path=path)
    if symbol == (_TYPED, "integral1", "Extension") and len(names) == 1:
        _require_base_ring_variable(environment, names[0], path=path)
        return IntegralValuationSort("extension", carrier=name, base=names[0])
    if symbol == (_TYPED, "integral1", "ValuationRing") and len(names) == 1:
        _require_field_variable(environment, names[0], path=path)
        return IntegralValuationSort("valuation_ring", carrier=name, ambient_field=names[0])
    if symbol == (_TYPED, "typed1", "Elem") and len(names) == 1:
        _require_element_carrier_variable(environment, names[0], path=path)
        return IntegralValuationSort("element", carrier=names[0])
    raise MathXMLValidationError(
        "typed integral/valuation type annotation must be CommRing, Domain, Field, "
        "Extension(R), ValuationRing(K), or Elem(A)"
    )


def _sort_argument_names(arguments: list[ET.Element], *, path: str) -> list[str]:
    names: list[str] = []
    for argument in arguments:
        if _local_name(argument) != "OMV" or not argument.get("name"):
            raise MathXMLValidationError(
                f"typed integral/valuation sort arguments must be OMV at {path}"
            )
        names.append(argument.get("name") or "")
    return names


def _infer_application(
    symbol: _Symbol, arguments: list[IntegralValuationSort], *, path: str
) -> IntegralValuationSort:
    cdbase, cd, name = symbol
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "relation1") and name in {"eq", "neq"}:
        _require_arity(symbol, arguments, exact=2)
        if arguments[0] != arguments[1]:
            _raise_expected(symbol, 1, arguments[1], arguments[0].render(), path=path)
        return _PROP
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "logic1"):
        if name in {"and", "or", "implies"}:
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _PROP, path=path)
            return _PROP
        if name == "not":
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _PROP, path=path)
            return _PROP
    if (cdbase, cd) != (_TYPED, "integral1"):
        raise MathXMLValidationError(
            f"unsupported typed integral/valuation application `{cd}:{name}`"
        )
    return _infer_integral_application(name, symbol, arguments, path=path)


def _infer_integral_application(
    name: str,
    symbol: _Symbol,
    arguments: list[IntegralValuationSort],
    *,
    path: str,
) -> IntegralValuationSort:
    if name in {"ring_zero", "ring_one"}:
        carrier = _require_ringlike(symbol, arguments, path=path, exact=1)
        return IntegralValuationSort("element", carrier=carrier)
    if name in {"ring_add", "ring_sub", "ring_mul"}:
        carrier = _require_ringlike(symbol, arguments, path=path, exact=3)
        _require_elements(symbol, arguments, carrier=carrier, start=1, path=path)
        return IntegralValuationSort("element", carrier=carrier)
    if name in {"ring_neg", "ring_square"}:
        carrier = _require_ringlike(symbol, arguments, path=path, exact=2)
        _require_elements(symbol, arguments, carrier=carrier, start=1, path=path)
        return IntegralValuationSort("element", carrier=carrier)
    if name == "extension_map":
        _require_arity(symbol, arguments, exact=3)
        base, target = _require_extension_prefix(symbol, arguments, path=path)
        _require_argument(
            symbol, arguments, 2, IntegralValuationSort("element", carrier=base), path=path
        )
        return IntegralValuationSort("element", carrier=target)
    if name in {"is_integral", "is_integral_extension"}:
        exact = 3 if name == "is_integral" else 2
        _require_arity(symbol, arguments, exact=exact)
        base, target = _require_extension_prefix(symbol, arguments, path=path)
        if name == "is_integral":
            _require_argument(
                symbol,
                arguments,
                2,
                IntegralValuationSort("element", carrier=target),
                path=path,
            )
        return _PROP
    if name == "field_inv":
        field = _require_field(symbol, arguments, path=path, exact=2)
        _require_elements(symbol, arguments, carrier=field, start=1, path=path)
        return IntegralValuationSort("element", carrier=field)
    if name == "valuation_mem":
        _require_arity(symbol, arguments, exact=3)
        field, valuation = _require_valuation_prefix(symbol, arguments, path=path)
        _require_argument(
            symbol, arguments, 2, IntegralValuationSort("element", carrier=field), path=path
        )
        assert valuation.ambient_field == field
        return _PROP
    if name == "valuation_integrally_closed":
        _require_arity(symbol, arguments, exact=2)
        _require_valuation_prefix(symbol, arguments, path=path)
        return _PROP
    raise MathXMLValidationError(f"unsupported integral1:{name}")


def _require_extension_prefix(
    symbol: _Symbol, arguments: list[IntegralValuationSort], *, path: str
) -> tuple[str, str]:
    base = _require_ringlike(symbol, arguments, path=path, exact=None, index=0)
    target = arguments[1]
    if target.kind != "extension" or target.base != base or target.carrier is None:
        _raise_expected(symbol, 1, target, f"Extension({base})", path=path)
    assert target.carrier is not None
    return base, target.carrier


def _require_valuation_prefix(
    symbol: _Symbol, arguments: list[IntegralValuationSort], *, path: str
) -> tuple[str, IntegralValuationSort]:
    field = _require_field(symbol, arguments, path=path, exact=None, index=0)
    valuation = arguments[1]
    if valuation.kind != "valuation_ring" or valuation.ambient_field != field:
        _raise_expected(symbol, 1, valuation, f"ValuationRing({field})", path=path)
    return field, valuation


def _require_ringlike(
    symbol: _Symbol,
    arguments: list[IntegralValuationSort],
    *,
    path: str,
    exact: int | None,
    index: int = 0,
) -> str:
    if exact is not None:
        _require_arity(symbol, arguments, exact=exact)
    sort = arguments[index]
    if sort.kind not in {"comm_ring", "domain", "field", "extension"} or sort.carrier is None:
        _raise_expected(symbol, index, sort, "CommRing, Domain, Field, or Extension(R)", path=path)
        raise AssertionError("unreachable after sort failure")
    return sort.carrier


def _require_field(
    symbol: _Symbol,
    arguments: list[IntegralValuationSort],
    *,
    path: str,
    exact: int | None,
    index: int = 0,
) -> str:
    if exact is not None:
        _require_arity(symbol, arguments, exact=exact)
    sort = arguments[index]
    if sort.kind != "field" or sort.carrier is None:
        _raise_expected(symbol, index, sort, "Field", path=path)
        raise AssertionError("unreachable after sort failure")
    return sort.carrier


def _require_ringlike_variable(
    environment: dict[str, IntegralValuationSort], name: str, *, path: str
) -> None:
    sort = environment.get(name)
    if sort is None or sort.kind not in {"comm_ring", "domain", "field", "extension"}:
        raise MathXMLValidationError(
            f"typed integral/valuation expected prior ring carrier `{name}` at {path}"
        )


def _require_base_ring_variable(
    environment: dict[str, IntegralValuationSort], name: str, *, path: str
) -> None:
    sort = environment.get(name)
    if sort is None or sort.kind not in {"comm_ring", "domain", "field"}:
        raise MathXMLValidationError(
            f"typed integral/valuation expected prior base CommRing, Domain, or Field `{name}` "
            f"at {path}"
        )


def _require_field_variable(
    environment: dict[str, IntegralValuationSort], name: str, *, path: str
) -> None:
    sort = environment.get(name)
    if sort is None or sort.kind != "field":
        raise MathXMLValidationError(
            f"typed integral/valuation expected prior Field `{name}` at {path}"
        )


def _require_element_carrier_variable(
    environment: dict[str, IntegralValuationSort], name: str, *, path: str
) -> None:
    _require_ringlike_variable(environment, name, path=path)


def _require_elements(
    symbol: _Symbol,
    arguments: list[IntegralValuationSort],
    *,
    carrier: str,
    start: int,
    path: str,
) -> None:
    for index in range(start, len(arguments)):
        _require_argument(
            symbol,
            arguments,
            index,
            IntegralValuationSort("element", carrier=carrier),
            path=path,
        )


def _require_arity(
    symbol: _Symbol, arguments: list[IntegralValuationSort], *, exact: int
) -> None:
    if len(arguments) == exact:
        return
    _base, cd, name = symbol
    raise MathXMLValidationError(
        f"`{cd}:{name}` requires {exact} arguments; received {len(arguments)}"
    )


def _require_all(
    symbol: _Symbol,
    arguments: list[IntegralValuationSort],
    expected: IntegralValuationSort,
    *,
    path: str,
) -> None:
    for index in range(len(arguments)):
        _require_argument(symbol, arguments, index, expected, path=path)


def _require_argument(
    symbol: _Symbol,
    arguments: list[IntegralValuationSort],
    index: int,
    expected: IntegralValuationSort,
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
    actual: IntegralValuationSort,
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
    label: str, actual: IntegralValuationSort, expected: IntegralValuationSort, *, path: str
) -> None:
    if actual == expected:
        return
    raise MathXMLValidationError(
        f"{label} at {path} must have sort `{expected.render()}`; received `{actual.render()}`"
    )
