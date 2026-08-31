"""Fail-closed OpenMath validation for the isolated ``typed-probability-v1``.

The profile is intentionally a sibling of generic retrieval and ``typed-math-v1``.
It admits only the reviewed natural-binomial, constant-expectation, and explicit
Probability-to-Real binomial-PMF surface.  Conditional probability and variance
are deliberately absent: their legacy Lean evidence uses different conventions.
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

TYPED_PROBABILITY_OPENMATH_CDBASE = "urn:pals:openmath:typed-math:v1"
TYPED_PROBABILITY_PROFILE = "typed-probability-v1"

_ProbabilitySortName = Literal[
    "prop",
    "nat",
    "nat_literal",
    "real",
    "probability",
    "sample_space",
    "event",
    "probability_measure",
    "real_random_variable",
    "distribution_nat",
]
_Symbol = tuple[str, str, str]
_NAT_NAMES = frozenset({"nat", "nat_literal"})
_TYPED_BINDERS = frozenset({"forall", "exists"})
_LOGICAL_NARY = frozenset({"and", "or"})
_LOGICAL_BINARY = frozenset({"implies", "equivalent"})
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
_NAT_RE = re.compile(r"(?:0|[1-9][0-9]*)\Z")


@dataclass(frozen=True, slots=True)
class ProbabilitySort:
    """A profile-local sort, including dependent sample-space carriers."""

    name: _ProbabilitySortName
    carrier: str | None = None

    def render(self) -> str:
        if self.name == "event":
            return f"Event({self.carrier})"
        if self.name == "probability_measure":
            return f"ProbabilityMeasure({self.carrier})"
        if self.name == "real_random_variable":
            return f"RealRandomVariable({self.carrier})"
        return {
            "prop": "Prop",
            "nat": "Nat",
            "nat_literal": "Nat literal",
            "real": "Real",
            "probability": "Probability",
            "sample_space": "SampleSpace",
            "distribution_nat": "DistributionNat",
        }[self.name]


@dataclass(frozen=True, slots=True)
class _Inferred:
    sort: ProbabilitySort
    origin: _Symbol | None = None


_PROP = ProbabilitySort("prop")
_NAT = ProbabilitySort("nat")
_NAT_LITERAL = ProbabilitySort("nat_literal")
_REAL = ProbabilitySort("real")
_PROBABILITY = ProbabilitySort("probability")
_SAMPLE_SPACE = ProbabilitySort("sample_space")
_DISTRIBUTION_NAT = ProbabilitySort("distribution_nat")


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-probability-v1-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - package invariant
        raise RuntimeError("typed-probability-v1 symbol registry is unavailable.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "pals.typed-probability-registry.v1"
        or payload.get("profile_id") != TYPED_PROBABILITY_PROFILE
        or payload.get("cdbases")
        != {
            "standard": OPENMATH_STANDARD_CDBASE,
            "typed": TYPED_PROBABILITY_OPENMATH_CDBASE,
        }
    ):  # pragma: no cover - package invariant
        raise RuntimeError("typed-probability-v1 symbol registry header is invalid.")
    entries = payload.get("symbols")
    if not isinstance(entries, list):  # pragma: no cover - package invariant
        raise RuntimeError("typed-probability-v1 symbol registry has no symbols list.")
    symbols: set[_Symbol] = set()
    for entry in entries:
        if not isinstance(entry, dict):  # pragma: no cover - package invariant
            raise RuntimeError("typed-probability-v1 symbol registry entry is invalid.")
        identity = tuple(entry.get(key) for key in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError("typed-probability-v1 symbol registry identity is invalid.")
        symbols.add(cast(_Symbol, identity))
    if len(symbols) != len(entries):  # pragma: no cover - package invariant
        raise RuntimeError("typed-probability-v1 symbol registry contains duplicates.")
    return frozenset(symbols)


_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_probability_openmath_xml(xml: str) -> str:
    """Validate and canonicalize one closed typed-probability proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("OpenMath XML exceeds the typed-probability byte bound.")
    root = validate_openmath_xml(xml)
    validate_typed_probability_openmath_root(root)
    return _canonicalize_openmath_v4_root(root)


def validate_canonical_typed_probability_openmath_xml(xml: str) -> str:
    """Accept only exact canonical bytes for the isolated probability profile."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError("OpenMath XML is not exact typed-probability canonical bytes.")
    canonical = canonicalize_typed_probability_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError("OpenMath XML is not exact typed-probability canonical bytes.")
    return canonical


def validate_typed_probability_openmath_xml(xml: str) -> None:
    """Validate one closed ``typed-probability-v1`` proposition."""
    root = validate_openmath_xml(xml)
    validate_typed_probability_openmath_root(root)


def validate_typed_probability_openmath_root(root: ET.Element) -> None:
    """Validate an already XML-valid OpenMath root under this profile."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("OpenMath typed-probability tree exceeds 4,096 nodes.")
    parents = _openmath_parents(root)
    _validate_tree_shape(root, nodes=nodes, parents=parents)
    if not _contains_profile_construct(root, parents=parents):
        raise MathXMLValidationError("OpenMath XML is not a typed-probability-v1 proposition.")
    inferred = _infer_expression(list(root)[0], environment={}, parents=parents, path="root")
    if inferred.sort != _PROP:
        raise MathXMLValidationError("typed-probability-v1 root must have sort `Prop`.")
    _enforce_single_sample_space(root, parents=parents)


def _validate_tree_shape(
    root: ET.Element,
    *,
    nodes: list[ET.Element],
    parents: dict[ET.Element, ET.Element],
) -> None:
    allowed = set(_ALLOWED_ATTRIBUTES)
    for element in nodes:
        local_name = _local_name(element)
        if local_name not in allowed:
            raise MathXMLValidationError(
                f"OpenMath element `{local_name}` is outside typed-probability-v1."
            )
        _validate_attributes(element, local_name=local_name)
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("OpenMath typed-probability tree exceeds depth 64.")
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError(
                "OpenMath typed-probability text exceeds 20,000 code points."
            )
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError("typed-probability-v1 elements cannot have text tails.")
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError(
                "typed-probability-v1 attribute exceeds 20,000 code points."
            )
        if local_name == "OMATTR":
            parent = parents.get(element)
            if (
                parent is None
                or _local_name(parent) != "OMBVAR"
                or not _is_type_declaration(element, parents=parents)
            ):
                raise MathXMLValidationError(
                    "typed-probability-v1 permits OMATTR only as one typed OMBVAR declaration."
                )
        if local_name == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                not _is_type_declaration(declaration, parents=parents)
                for declaration in declarations
            ):
                raise MathXMLValidationError(
                    "typed-probability-v1 OMBVAR requires 1..256 typed OMV declarations."
                )
        if local_name == "OMBIND":
            binder, _variables, _body = list(element)
            symbol = _operator_symbol(binder, parents=parents)
            if (
                symbol is None
                or symbol[:2] != (TYPED_PROBABILITY_OPENMATH_CDBASE, "typed1")
                or symbol[2] not in _TYPED_BINDERS
                or binder.get("cdbase") != TYPED_PROBABILITY_OPENMATH_CDBASE
            ):
                raise MathXMLValidationError(
                    "typed-probability-v1 OMBIND must use typed1:forall or typed1:exists."
                )
        if local_name == "OMA" and _local_name(list(element)[0]) != "OMS":
            raise MathXMLValidationError("typed-probability-v1 OMA head must be an OMS.")
        if local_name == "OMS":
            _validate_symbol(element, parents=parents)


def _validate_attributes(element: ET.Element, *, local_name: str) -> None:
    actual = set(element.attrib)
    unexpected = actual - _ALLOWED_ATTRIBUTES[local_name]
    if unexpected:
        raise MathXMLValidationError(
            "typed-probability-v1 "
            f"`{local_name}` does not permit attribute `{sorted(unexpected)[0]}`."
        )
    if local_name == "OMOBJ" and actual != {"version"}:
        raise MathXMLValidationError("typed-probability-v1 OMOBJ requires only `version`.")
    if local_name == "OMS" and not {"cd", "name"}.issubset(actual):
        raise MathXMLValidationError("typed-probability-v1 OMS requires `cd` and `name`.")
    if local_name == "OMV" and actual != {"name"}:
        raise MathXMLValidationError("typed-probability-v1 OMV requires only `name`.")


def _validate_symbol(element: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed-probability-v1 OMS must identify a symbol.")
    direct_cdbase = element.get("cdbase")
    if symbol[0] == TYPED_PROBABILITY_OPENMATH_CDBASE:
        if direct_cdbase != symbol[0]:
            raise MathXMLValidationError(
                "typed-probability-v1 OMS must directly declare its typed cdbase."
            )
    elif symbol[0] == OPENMATH_STANDARD_CDBASE and direct_cdbase is None:
        ancestor = parents.get(element)
        while ancestor is not None:
            if "cdbase" in ancestor.attrib:
                raise MathXMLValidationError(
                    "Standard typed-probability-v1 OMS may omit cdbase only "
                    "without inherited cdbase."
                )
            ancestor = parents.get(ancestor)
    if symbol not in _SYMBOL_REGISTRY:
        _cdbase, cd, name = symbol
        raise MathXMLValidationError(f"Symbol `{cd}:{name}` is outside typed-probability-v1.")


def _contains_profile_construct(
    root: ET.Element, *, parents: dict[ET.Element, ET.Element]
) -> bool:
    has_binder = False
    has_type = False
    has_probability = False
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        symbol = _operator_symbol(element, parents=parents)
        if symbol is None:
            continue
        has_binder = has_binder or symbol == (
            TYPED_PROBABILITY_OPENMATH_CDBASE,
            "typed1",
            "forall",
        ) or symbol == (TYPED_PROBABILITY_OPENMATH_CDBASE, "typed1", "exists")
        has_type = has_type or symbol == (
            TYPED_PROBABILITY_OPENMATH_CDBASE,
            "typed1",
            "type",
        )
        has_probability = has_probability or symbol[:2] == (
            TYPED_PROBABILITY_OPENMATH_CDBASE,
            "probability1",
        )
    return has_binder and has_type and has_probability


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
        == (TYPED_PROBABILITY_OPENMATH_CDBASE, "typed1", "type")
    )


def _infer_expression(
    expression: ET.Element,
    *,
    environment: dict[str, ProbabilitySort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> _Inferred:
    local_name = _local_name(expression)
    if local_name == "OMV":
        name = expression.get("name")
        if name is None or name not in environment:
            raise MathXMLValidationError(
                f"typed-probability-v1 has a free or undeclared variable `{name or ''}` at {path}."
            )
        return _Inferred(environment[name])
    if local_name == "OMI":
        value = "".join((expression.text or "").split())
        if not _NAT_RE.fullmatch(value):
            raise MathXMLValidationError(
                "typed-probability-v1 admits only nonnegative canonical Nat OMI literals."
            )
        if len(value) > 10:
            raise MathXMLValidationError("typed-probability-v1 OMI literal exceeds the v1 bound.")
        return _Inferred(_NAT_LITERAL)
    if local_name == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if local_name != "OMA":
        raise MathXMLValidationError(
            f"typed-probability-v1 cannot infer a sort for `{local_name}` at {path}."
        )
    operator, *argument_nodes = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(f"typed-probability-v1 OMA has an invalid operator at {path}.")
    arguments = [
        _infer_expression(node, environment=environment, parents=parents, path=f"{path}/{index}")
        for index, node in enumerate(argument_nodes, start=1)
    ]
    return _infer_application(symbol, arguments, argument_nodes=argument_nodes, path=path)


def _infer_binding(
    binding: ET.Element,
    *,
    environment: dict[str, ProbabilitySort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> _Inferred:
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
                f"typed-probability-v1 redeclares bound variable `{name}` at {path}."
            )
        declared.add(name)
        local_environment[name] = sort
    body_sort = _infer_expression(
        body, environment=local_environment, parents=parents, path=f"{path}/body"
    )
    _require_sort("typed binder body", body_sort, _PROP, path=path)
    return _Inferred(_PROP)


def _parse_declaration(
    declaration: ET.Element,
    *,
    environment: dict[str, ProbabilitySort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> tuple[str, ProbabilitySort]:
    attributes, variable = list(declaration)
    _key, sort_expression = list(attributes)
    name = variable.get("name")
    if name is None or not name:
        raise MathXMLValidationError(
            f"typed-probability-v1 bound OMV is missing `name` at {path}."
        )
    return name, _parse_sort(sort_expression, environment=environment, parents=parents, path=path)


def _parse_sort(
    expression: ET.Element,
    *,
    environment: dict[str, ProbabilitySort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> ProbabilitySort:
    if _local_name(expression) == "OMS":
        symbol = _operator_symbol(expression, parents=parents)
        mapping = {
            (TYPED_PROBABILITY_OPENMATH_CDBASE, "typed1", "Nat"): _NAT,
            (TYPED_PROBABILITY_OPENMATH_CDBASE, "typed1", "Real"): _REAL,
            (TYPED_PROBABILITY_OPENMATH_CDBASE, "probability1", "Probability"): _PROBABILITY,
            (TYPED_PROBABILITY_OPENMATH_CDBASE, "probability1", "SampleSpace"): _SAMPLE_SPACE,
            (TYPED_PROBABILITY_OPENMATH_CDBASE, "probability1", "DistributionNat"):
                _DISTRIBUTION_NAT,
        }
        if symbol is not None:
            sort = mapping.get(symbol)
            if sort is not None:
                return sort
    if _local_name(expression) == "OMA":
        operator, *arguments = list(expression)
        symbol = _operator_symbol(operator, parents=parents)
        dependent = {
            "Event": "event",
            "ProbabilityMeasure": "probability_measure",
            "RealRandomVariable": "real_random_variable",
        }
        if (
            symbol is not None
            and symbol[:2] == (TYPED_PROBABILITY_OPENMATH_CDBASE, "probability1")
            and symbol[2] in dependent
            and len(arguments) == 1
            and _local_name(arguments[0]) == "OMV"
        ):
            carrier = arguments[0].get("name")
            if carrier is not None and environment.get(carrier) == _SAMPLE_SPACE:
                return ProbabilitySort(cast(_ProbabilitySortName, dependent[symbol[2]]), carrier)
    raise MathXMLValidationError(
        f"typed-probability-v1 has an invalid type annotation at {path}; "
        "expected a supported SortExpr."
    )


def _enforce_single_sample_space(
    root: ET.Element, *, parents: dict[ET.Element, ET.Element]
) -> None:
    sample_space_declarations = 0
    for declaration in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMATTR"):
        if not _is_type_declaration(declaration, parents=parents):
            continue
        attributes, _variable = list(declaration)
        _type_key, sort = list(attributes)
        if _local_name(sort) != "OMS":
            continue
        if _operator_symbol(sort, parents=parents) == (
            TYPED_PROBABILITY_OPENMATH_CDBASE,
            "probability1",
            "SampleSpace",
        ):
            sample_space_declarations += 1
    if sample_space_declarations > 1:
        raise MathXMLValidationError(
            "typed-probability-v1 permits exactly one SampleSpace declaration per closed statement."
        )


def _infer_application(
    symbol: _Symbol,
    arguments: list[_Inferred],
    *,
    argument_nodes: list[ET.Element],
    path: str,
) -> _Inferred:
    cdbase, cd, name = symbol
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "relation1"):
        if name in {"eq", "neq"}:
            _require_arity(symbol, arguments, exact=2)
            if not _sorts_equal(arguments[0].sort, arguments[1].sort):
                raise MathXMLValidationError(
                    f"Argument 2 of `{cd}:{name}` at {path} must have sort "
                    f"`{arguments[0].sort.render()}`; received `{arguments[1].sort.render()}`."
                )
            return _Inferred(_PROP, symbol)
        if name == "leq":
            _require_arity(symbol, arguments, exact=2)
            _require_nat_argument(symbol, arguments, 0, path=path)
            _require_nat_argument(symbol, arguments, 1, path=path)
            return _Inferred(_PROP, symbol)
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "logic1"):
        if name in _LOGICAL_NARY:
            _require_arity(symbol, arguments, minimum=2)
            _require_all(symbol, arguments, _PROP, path=path)
            return _Inferred(_PROP, symbol)
        if name in _LOGICAL_BINARY:
            _require_arity(symbol, arguments, exact=2)
            _require_all(symbol, arguments, _PROP, path=path)
            return _Inferred(_PROP, symbol)
        if name == "not":
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _PROP, path=path)
            return _Inferred(_PROP, symbol)
    if (cdbase, cd) != (TYPED_PROBABILITY_OPENMATH_CDBASE, "probability1"):
        raise MathXMLValidationError(
            f"Unsupported typed-probability-v1 application `{cd}:{name}` at {path}."
        )
    if name in {"nat_add", "nat_sub", "nat_mul", "nat_div", "choose"}:
        _require_arity(symbol, arguments, exact=2)
        _require_nat_argument(symbol, arguments, 0, path=path)
        _require_nat_argument(symbol, arguments, 1, path=path)
        return _Inferred(_NAT, symbol)
    if name == "nat_to_real":
        _require_arity(symbol, arguments, exact=1)
        _require_nat_argument(symbol, arguments, 0, path=path)
        return _Inferred(_REAL, symbol)
    if name == "real_of_int":
        _require_arity(symbol, arguments, exact=1)
        _require_nat_argument(symbol, arguments, 0, path=path)
        if _local_name(argument_nodes[0]) != "OMI":
            raise MathXMLValidationError(
                f"Argument 1 of `probability1:real_of_int` at {path} must be a direct OMI literal."
            )
        return _Inferred(_REAL, symbol)
    if name == "prob_to_real":
        _require_arity(symbol, arguments, exact=1)
        _require_argument(symbol, arguments, 0, _PROBABILITY, path=path)
        return _Inferred(_REAL, symbol)
    if name in {"real_add", "real_mul"}:
        _require_arity(symbol, arguments, minimum=2)
        _require_all(symbol, arguments, _REAL, path=path)
        return _Inferred(_REAL, symbol)
    if name in {"real_sub", "real_div"}:
        _require_arity(symbol, arguments, exact=2)
        _require_all(symbol, arguments, _REAL, path=path)
        return _Inferred(_REAL, symbol)
    if name == "real_pow_nat":
        _require_arity(symbol, arguments, exact=2)
        _require_argument(symbol, arguments, 0, _REAL, path=path)
        _require_nat_argument(symbol, arguments, 1, path=path)
        return _Inferred(_REAL, symbol)
    if name == "event_intersection":
        _require_arity(symbol, arguments, exact=2)
        left = _require_dependent_argument(symbol, arguments, 0, "event", path=path)
        _require_argument(symbol, arguments, 1, left, path=path)
        return _Inferred(left, symbol)
    if name == "probability":
        _require_arity(symbol, arguments, exact=2)
        measure = _require_dependent_argument(
            symbol, arguments, 0, "probability_measure", path=path
        )
        assert measure.carrier is not None
        _require_argument(
            symbol, arguments, 1, ProbabilitySort("event", measure.carrier), path=path
        )
        return _Inferred(_PROBABILITY, symbol)
    if name == "constant_rv":
        _require_arity(symbol, arguments, exact=2)
        _require_argument(symbol, arguments, 0, _SAMPLE_SPACE, path=path)
        _require_argument(symbol, arguments, 1, _REAL, path=path)
        node = argument_nodes[0]
        if _local_name(node) != "OMV" or node.get("name") is None:
            raise MathXMLValidationError(
                f"Argument 1 of `probability1:constant_rv` at {path} must be "
                "a SampleSpace variable."
            )
        return _Inferred(ProbabilitySort("real_random_variable", node.get("name")), symbol)
    if name == "expectation":
        _require_arity(symbol, arguments, exact=2)
        rv = _require_dependent_argument(symbol, arguments, 0, "real_random_variable", path=path)
        assert rv.carrier is not None
        _require_argument(
            symbol, arguments, 1, ProbabilitySort("probability_measure", rv.carrier), path=path
        )
        if arguments[0].origin != (
            TYPED_PROBABILITY_OPENMATH_CDBASE,
            "probability1",
            "constant_rv",
        ):
            raise MathXMLValidationError(
                "typed-probability-v1 admits expectation only for constant_rv; "
                "general integrability evidence is deferred."
            )
        return _Inferred(_REAL, symbol)
    if name == "binomial_distribution":
        _require_arity(symbol, arguments, exact=2)
        _require_nat_argument(symbol, arguments, 0, path=path)
        _require_argument(symbol, arguments, 1, _PROBABILITY, path=path)
        return _Inferred(_DISTRIBUTION_NAT, symbol)
    if name == "pmf":
        _require_arity(symbol, arguments, exact=2)
        _require_argument(symbol, arguments, 0, _DISTRIBUTION_NAT, path=path)
        _require_nat_argument(symbol, arguments, 1, path=path)
        return _Inferred(_PROBABILITY, symbol)
    raise MathXMLValidationError(
        f"Unsupported typed-probability-v1 application `probability1:{name}` at {path}."
    )


def _sorts_equal(left: ProbabilitySort, right: ProbabilitySort) -> bool:
    return left == right or (left.name in _NAT_NAMES and right.name in _NAT_NAMES)


def _require_arity(
    symbol: _Symbol,
    arguments: list[_Inferred],
    *,
    exact: int | None = None,
    minimum: int | None = None,
) -> None:
    valid = (exact is None or len(arguments) == exact) and (
        minimum is None or len(arguments) >= minimum
    )
    if valid:
        return
    _cdbase, cd, name = symbol
    expectation = str(exact) if exact is not None else f"at least {minimum}"
    raise MathXMLValidationError(
        f"`{cd}:{name}` requires {expectation} arguments; received {len(arguments)}."
    )


def _require_all(
    symbol: _Symbol, arguments: list[_Inferred], expected: ProbabilitySort, *, path: str
) -> None:
    for index in range(len(arguments)):
        _require_argument(symbol, arguments, index, expected, path=path)


def _require_argument(
    symbol: _Symbol,
    arguments: list[_Inferred],
    index: int,
    expected: ProbabilitySort,
    *,
    path: str,
) -> _Inferred:
    actual = arguments[index]
    if _sorts_equal(actual.sort, expected):
        return actual
    _cdbase, cd, name = symbol
    raise MathXMLValidationError(
        f"Argument {index + 1} of `{cd}:{name}` at {path} must have sort "
        f"`{expected.render()}`; received `{actual.sort.render()}`."
    )


def _require_nat_argument(
    symbol: _Symbol, arguments: list[_Inferred], index: int, *, path: str
) -> _Inferred:
    actual = arguments[index]
    if actual.sort.name in _NAT_NAMES:
        return actual
    _cdbase, cd, name = symbol
    raise MathXMLValidationError(
        f"Argument {index + 1} of `{cd}:{name}` at {path} must have sort `Nat`; "
        f"received `{actual.sort.render()}`."
    )


def _require_dependent_argument(
    symbol: _Symbol,
    arguments: list[_Inferred],
    index: int,
    expected_name: Literal["event", "probability_measure", "real_random_variable"],
    *,
    path: str,
) -> ProbabilitySort:
    actual = arguments[index].sort
    if actual.name == expected_name and actual.carrier is not None:
        return actual
    _cdbase, cd, name = symbol
    rendered = {
        "event": "Event(Omega)",
        "probability_measure": "ProbabilityMeasure(Omega)",
        "real_random_variable": "RealRandomVariable(Omega)",
    }[expected_name]
    raise MathXMLValidationError(
        f"Argument {index + 1} of `{cd}:{name}` at {path} must have sort `{rendered}`; "
        f"received `{actual.render()}`."
    )


def _require_sort(
    label: str, actual: _Inferred, expected: ProbabilitySort, *, path: str
) -> None:
    if _sorts_equal(actual.sort, expected):
        return
    raise MathXMLValidationError(
        f"{label} at {path} must have sort `{expected.render()}`; "
        f"received `{actual.sort.render()}`."
    )
