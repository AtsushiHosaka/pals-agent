"""Fail-closed OpenMath validation for ``typed-finite-graph-v1``.

The finite-simple-graph vocabulary is deliberately a sibling profile.  It
never widens generic retrieval or ``typed-math-v1``: in particular public
``graph1`` constructors are not graph values for this validator.
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

TYPED_FINITE_GRAPH_OPENMATH_CDBASE = "urn:pals:openmath:typed-finite-graph:v1"
TYPED_FINITE_GRAPH_PROFILE = "typed-finite-graph-v1"

_SortName = Literal["prop", "nat", "fin_simple_graph", "vertex", "vertex_class", "trail"]
_Symbol = tuple[str, str, str]
_TYPED_BINDERS = frozenset({"forall", "exists"})
_LOGICAL_NARY = frozenset({"and", "or"})
_LOGICAL_BINARY = frozenset({"implies", "equivalent"})
_RELATIONS = frozenset({"eq", "neq"})
_GRAPH_NAT_UNARY = frozenset({"vertex_count", "edge_count", "degree_sum", "odd_degree_count"})
_GRAPH_PROP_UNARY = frozenset(
    {
        "connected",
        "nonisolated_connected",
        "acyclic",
        "tree",
        "bipartite",
        "has_euler_trail",
        "has_euler_circuit",
    }
)
_GRAPH_PROP_BINARY = frozenset({"is_euler_trail", "is_euler_circuit"})
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
class TypedFiniteGraphSort:
    """A finite-graph profile sort, including its graph-indexed carrier."""

    name: _SortName
    graph: str | None = None

    def render(self) -> str:
        if self.name == "fin_simple_graph":
            return "FinSimpleGraph"
        if self.name == "vertex":
            assert self.graph is not None
            return f"Vertex({self.graph})"
        if self.name == "vertex_class":
            assert self.graph is not None
            return f"VertexClass({self.graph})"
        if self.name == "trail":
            assert self.graph is not None
            return f"Trail({self.graph})"
        return {"prop": "Prop", "nat": "Nat"}[self.name]


_PROP = TypedFiniteGraphSort("prop")
_NAT = TypedFiniteGraphSort("nat")
_FIN_SIMPLE_GRAPH = TypedFiniteGraphSort("fin_simple_graph")


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-finite-graph-v1-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - package invariant
        raise RuntimeError("typed-finite-graph-v1 symbol registry is unavailable.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "pals.typed-finite-graph-registry.v1"
        or payload.get("profile_id") != TYPED_FINITE_GRAPH_PROFILE
        or payload.get("cdbases")
        != {"standard": OPENMATH_STANDARD_CDBASE, "typed": TYPED_FINITE_GRAPH_OPENMATH_CDBASE}
    ):  # pragma: no cover - package invariant
        raise RuntimeError("typed-finite-graph-v1 registry header is invalid.")
    entries = payload.get("symbols")
    if not isinstance(entries, list):  # pragma: no cover - package invariant
        raise RuntimeError("typed-finite-graph-v1 registry has no symbols list.")
    symbols: set[_Symbol] = set()
    for entry in entries:
        if not isinstance(entry, dict):  # pragma: no cover - package invariant
            raise RuntimeError("typed-finite-graph-v1 registry entry is invalid.")
        identity = tuple(entry.get(field) for field in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError("typed-finite-graph-v1 registry identity is invalid.")
        symbols.add(cast(_Symbol, identity))
    if len(symbols) != len(entries):  # pragma: no cover - package invariant
        raise RuntimeError("typed-finite-graph-v1 registry contains duplicate symbols.")
    return frozenset(symbols)


_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_finite_graph_openmath_xml(xml: str) -> str:
    """Validate and canonicalize one closed finite-graph proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("OpenMath XML exceeds the typed-finite-graph byte bound.")
    root = validate_openmath_xml(xml)
    validate_typed_finite_graph_openmath_root(root)
    return _canonicalize_openmath_v4_root(root)


def validate_canonical_typed_finite_graph_openmath_xml(xml: str) -> str:
    """Accept only exact canonical bytes for this isolated profile."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError(
            "OpenMath XML is not exact typed-finite-graph canonical bytes."
        )
    canonical = canonicalize_typed_finite_graph_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError(
            "OpenMath XML is not exact typed-finite-graph canonical bytes."
        )
    return canonical


def validate_typed_finite_graph_openmath_xml(xml: str) -> None:
    """Validate one closed ``typed-finite-graph-v1`` proposition."""
    validate_typed_finite_graph_openmath_root(validate_openmath_xml(xml))


def validate_typed_finite_graph_openmath_root(root: ET.Element) -> None:
    """Validate an already XML-valid OpenMath root under this profile."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("OpenMath typed-finite-graph tree exceeds 4,096 nodes.")
    parents = _openmath_parents(root)
    _validate_tree_shape(root, nodes=nodes, parents=parents)
    if not _contains_profile_construct(root, parents=parents):
        raise MathXMLValidationError("OpenMath XML is not a typed-finite-graph-v1 proposition.")
    _validate_admitted_theorem_boundary(root, parents=parents)
    inferred = _infer_expression(list(root)[0], environment={}, parents=parents, path="root")
    if inferred != _PROP:
        raise MathXMLValidationError("typed-finite-graph-v1 root must have sort `Prop`.")


def _validate_tree_shape(
    root: ET.Element, *, nodes: list[ET.Element], parents: dict[ET.Element, ET.Element]
) -> None:
    for element in nodes:
        name = _local_name(element)
        if name not in _ALLOWED_ATTRIBUTES:
            raise MathXMLValidationError(
                f"OpenMath element `{name}` is outside typed-finite-graph-v1."
            )
        _validate_attributes(element, local_name=name)
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("OpenMath typed-finite-graph tree exceeds depth 64.")
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError("typed-finite-graph-v1 elements cannot have text tails.")
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError(
                "OpenMath typed-finite-graph text exceeds 20,000 code points."
            )
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError("typed-finite-graph attribute exceeds 20,000 code points.")
        if name == "OMATTR" and (
            _local_name(parents.get(element, ET.Element("invalid"))) != "OMBVAR"
            or not _is_declaration(element, parents=parents)
        ):
            raise MathXMLValidationError(
                "typed-finite-graph-v1 permits OMATTR only as one typed OMBVAR declaration."
            )
        if name == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                not _is_declaration(declaration, parents=parents) for declaration in declarations
            ):
                raise MathXMLValidationError(
                    "typed-finite-graph-v1 OMBVAR requires 1..256 typed OMV declarations."
                )
        if name == "OMBIND":
            binder, _variables, _body = list(element)
            if _operator_symbol(binder, parents=parents) not in {
                (TYPED_FINITE_GRAPH_OPENMATH_CDBASE, "pals_typed_graph", "forall"),
                (TYPED_FINITE_GRAPH_OPENMATH_CDBASE, "pals_typed_graph", "exists"),
            }:
                raise MathXMLValidationError(
                    "typed-finite-graph-v1 OMBIND must use pals_typed_graph:forall or exists."
                )
        if name == "OMA" and _local_name(list(element)[0]) != "OMS":
            raise MathXMLValidationError("typed-finite-graph-v1 OMA head must be an OMS.")
        if name == "OMS":
            _validate_symbol(element, parents=parents)


def _validate_attributes(element: ET.Element, *, local_name: str) -> None:
    actual = set(element.attrib)
    unexpected = actual - _ALLOWED_ATTRIBUTES[local_name]
    if unexpected:
        raise MathXMLValidationError(
            "typed-finite-graph-v1 "
            f"`{local_name}` does not permit attribute `{sorted(unexpected)[0]}`."
        )
    if local_name == "OMOBJ" and actual != {"version"}:
        raise MathXMLValidationError("typed-finite-graph-v1 OMOBJ requires only `version`.")
    if local_name == "OMS" and actual != {"cdbase", "cd", "name"}:
        raise MathXMLValidationError(
            "typed-finite-graph-v1 OMS requires direct `cdbase`, `cd`, and `name`."
        )
    if local_name == "OMV" and actual != {"name"}:
        raise MathXMLValidationError("typed-finite-graph-v1 OMV requires only `name`.")


def _validate_symbol(element: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed-finite-graph-v1 OMS must identify a symbol.")
    if element.get("cdbase") != symbol[0]:
        raise MathXMLValidationError("typed-finite-graph-v1 OMS must directly declare its cdbase.")
    if symbol not in _SYMBOL_REGISTRY:
        cdbase, cd, name = symbol
        raise MathXMLValidationError(
            f"Symbol `{cd}:{name}` with cdbase `{cdbase}` is outside typed-finite-graph-v1."
        )


def _contains_profile_construct(root: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> bool:
    binder = False
    annotation = False
    graph_construct = False
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        symbol = _operator_symbol(element, parents=parents)
        if symbol is None or symbol[0:2] != (
            TYPED_FINITE_GRAPH_OPENMATH_CDBASE,
            "pals_typed_graph",
        ):
            continue
        binder = binder or symbol[2] in _TYPED_BINDERS
        annotation = annotation or symbol[2] == "type"
        graph_construct = graph_construct or symbol[2] not in _TYPED_BINDERS | {"type"}
    return binder and annotation and graph_construct


def _is_declaration(declaration: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> bool:
    if _local_name(declaration) != "OMATTR" or len(list(declaration)) != 2:
        return False
    attributes, variable = list(declaration)
    if _local_name(attributes) != "OMATP" or _local_name(variable) != "OMV":
        return False
    pairs = list(attributes)
    return (
        len(pairs) == 2
        and _local_name(pairs[0]) == "OMS"
        and _operator_symbol(pairs[0], parents=parents)
        == (TYPED_FINITE_GRAPH_OPENMATH_CDBASE, "pals_typed_graph", "type")
    )


def _validate_admitted_theorem_boundary(
    root: ET.Element, *, parents: dict[ET.Element, ET.Element]
) -> None:
    """Keep blocked Euler/bipartition converse families out of the v1 boundary."""
    symbols = {
        symbol
        for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS")
        if (symbol := _operator_symbol(element, parents=parents)) is not None
    }
    private = (TYPED_FINITE_GRAPH_OPENMATH_CDBASE, "pals_typed_graph")
    if private + ("has_euler_trail",) in symbols or private + ("has_euler_circuit",) in symbols:
        raise MathXMLValidationError(
            "typed-finite-graph-v1 does not admit Euler-existence theorem families."
        )
    if private + ("is_euler_trail",) in symbols and private + ("connected",) in symbols:
        raise MathXMLValidationError(
            "typed-finite-graph-v1 Euler conditions must use nonisolated_connected, not connected."
        )
    equivalence = (OPENMATH_STANDARD_CDBASE, "logic1", "equivalent")
    if equivalence in symbols and {
        private + ("bipartite",),
        private + ("proper_bipartition",),
    }.issubset(symbols):
        raise MathXMLValidationError(
            "typed-finite-graph-v1 does not admit full bipartition equivalence."
        )


def _infer_expression(
    expression: ET.Element,
    *,
    environment: dict[str, TypedFiniteGraphSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> TypedFiniteGraphSort:
    name = _local_name(expression)
    if name == "OMV":
        variable = expression.get("name")
        if variable is None or variable not in environment:
            raise MathXMLValidationError(
                "typed-finite-graph-v1 has a free or undeclared variable "
                f"`{variable or ''}` at {path}."
            )
        return environment[variable]
    if name == "OMI":
        if "".join((expression.text or "").split()).startswith("-"):
            raise MathXMLValidationError("typed-finite-graph-v1 Nat literals must be nonnegative.")
        return _NAT
    if name == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if name != "OMA":
        raise MathXMLValidationError(f"typed-finite-graph-v1 cannot infer `{name}` at {path}.")
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(f"typed-finite-graph-v1 has an invalid operator at {path}.")
    sorts = [
        _infer_expression(
            argument, environment=environment, parents=parents, path=f"{path}/{index}"
        )
        for index, argument in enumerate(arguments, start=1)
    ]
    return _infer_application(symbol, sorts, path=path)


def _infer_binding(
    binding: ET.Element,
    *,
    environment: dict[str, TypedFiniteGraphSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> TypedFiniteGraphSort:
    binder, variables, body = list(binding)
    symbol = _operator_symbol(binder, parents=parents)
    assert symbol is not None
    local_environment = dict(environment)
    declared: set[str] = set()
    for index, declaration in enumerate(list(variables), start=1):
        variable, sort = _parse_declaration(
            declaration, environment=local_environment, parents=parents, path=f"{path}/bind/{index}"
        )
        if variable in declared or variable in environment:
            raise MathXMLValidationError(
                f"typed-finite-graph-v1 redeclares bound variable `{variable}` at {path}."
            )
        declared.add(variable)
        local_environment[variable] = (
            TypedFiniteGraphSort("fin_simple_graph", variable)
            if sort == _FIN_SIMPLE_GRAPH
            else sort
        )
    body_sort = _infer_expression(
        body, environment=local_environment, parents=parents, path=f"{path}/body"
    )
    if body_sort != _PROP:
        raise MathXMLValidationError(
            f"The body of `{symbol[1]}:{symbol[2]}` must have sort `Prop`; "
            f"received `{body_sort.render()}`."
        )
    return _PROP


def _parse_declaration(
    declaration: ET.Element,
    *,
    environment: dict[str, TypedFiniteGraphSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> tuple[str, TypedFiniteGraphSort]:
    attributes, variable = list(declaration)
    _key, sort_expression = list(attributes)
    name = variable.get("name")
    if name is None or not name:
        raise MathXMLValidationError(f"typed-finite-graph-v1 bound OMV has no name at {path}.")
    return name, _parse_sort(sort_expression, environment=environment, parents=parents, path=path)


def _parse_sort(
    expression: ET.Element,
    *,
    environment: dict[str, TypedFiniteGraphSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> TypedFiniteGraphSort:
    if _local_name(expression) == "OMS" and _operator_symbol(expression, parents=parents) == (
        TYPED_FINITE_GRAPH_OPENMATH_CDBASE,
        "pals_typed_graph",
        "FinSimpleGraph",
    ):
        return _FIN_SIMPLE_GRAPH
    if _local_name(expression) == "OMA":
        operator, *arguments = list(expression)
        symbol = _operator_symbol(operator, parents=parents)
        if (
            symbol is not None
            and symbol[0:2] == (TYPED_FINITE_GRAPH_OPENMATH_CDBASE, "pals_typed_graph")
            and symbol[2] in {"Vertex", "VertexClass", "Trail"}
            and len(arguments) == 1
            and _local_name(arguments[0]) == "OMV"
        ):
            graph = arguments[0].get("name")
            graph_sort = environment.get(graph or "")
            if (
                graph_sort is not None
                and graph_sort.name == "fin_simple_graph"
                and graph_sort.graph
            ):
                mapping: dict[str, _SortName] = {
                    "Vertex": "vertex",
                    "VertexClass": "vertex_class",
                    "Trail": "trail",
                }
                return TypedFiniteGraphSort(mapping[symbol[2]], graph_sort.graph)
    raise MathXMLValidationError(
        "typed-finite-graph-v1 has an invalid type annotation at "
        f"{path}; expected a supported SortExpr."
    )


def _infer_application(
    symbol: _Symbol, arguments: list[TypedFiniteGraphSort], *, path: str
) -> TypedFiniteGraphSort:
    cdbase, cd, name = symbol
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "relation1") and name in _RELATIONS:
        _require_arity(symbol, arguments, 2)
        if arguments[0] != arguments[1]:
            _require_argument(symbol, arguments, 1, arguments[0], path=path)
        return _PROP
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "logic1"):
        if name in _LOGICAL_NARY:
            if len(arguments) < 2:
                _require_arity(symbol, arguments, 2, minimum=True)
            _require_all(symbol, arguments, _PROP, path=path)
            return _PROP
        if name in _LOGICAL_BINARY:
            _require_arity(symbol, arguments, 2)
            _require_all(symbol, arguments, _PROP, path=path)
            return _PROP
        if name == "not":
            _require_arity(symbol, arguments, 1)
            _require_argument(symbol, arguments, 0, _PROP, path=path)
            return _PROP
    if (cdbase, cd) != (TYPED_FINITE_GRAPH_OPENMATH_CDBASE, "pals_typed_graph"):
        raise MathXMLValidationError(
            f"Unsupported typed-finite-graph-v1 application `{cd}:{name}` at {path}."
        )
    if name in _GRAPH_NAT_UNARY:
        _require_arity(symbol, arguments, 1)
        _require_graph(symbol, arguments, 0, path=path)
        return _NAT
    if name in _GRAPH_PROP_UNARY:
        _require_arity(symbol, arguments, 1)
        _require_graph(symbol, arguments, 0, path=path)
        return _PROP
    if name in {"nat_add", "nat_mul"}:
        _require_arity(symbol, arguments, 2)
        _require_all(symbol, arguments, _NAT, path=path)
        return _NAT
    if name == "degree":
        _require_arity(symbol, arguments, 2)
        graph = _require_graph(symbol, arguments, 0, path=path)
        _require_argument(symbol, arguments, 1, TypedFiniteGraphSort("vertex", graph), path=path)
        return _NAT
    if name == "adjacent":
        _require_arity(symbol, arguments, 3)
        graph = _require_graph(symbol, arguments, 0, path=path)
        _require_argument(symbol, arguments, 1, TypedFiniteGraphSort("vertex", graph), path=path)
        _require_argument(symbol, arguments, 2, TypedFiniteGraphSort("vertex", graph), path=path)
        return _PROP
    if name == "proper_bipartition":
        _require_arity(symbol, arguments, 3)
        graph = _require_graph(symbol, arguments, 0, path=path)
        expected = TypedFiniteGraphSort("vertex_class", graph)
        _require_argument(symbol, arguments, 1, expected, path=path)
        _require_argument(symbol, arguments, 2, expected, path=path)
        return _PROP
    if name in _GRAPH_PROP_BINARY:
        _require_arity(symbol, arguments, 2)
        graph = _require_graph(symbol, arguments, 0, path=path)
        _require_argument(symbol, arguments, 1, TypedFiniteGraphSort("trail", graph), path=path)
        return _PROP
    raise MathXMLValidationError(
        f"Unsupported typed-finite-graph-v1 application `{cd}:{name}` at {path}."
    )


def _require_arity(
    symbol: _Symbol, arguments: list[TypedFiniteGraphSort], count: int, *, minimum: bool = False
) -> None:
    valid = len(arguments) >= count if minimum else len(arguments) == count
    if valid:
        return
    _, cd, name = symbol
    expectation = f"at least {count}" if minimum else str(count)
    raise MathXMLValidationError(
        f"`{cd}:{name}` requires {expectation} arguments; received {len(arguments)}."
    )


def _require_all(
    symbol: _Symbol,
    arguments: list[TypedFiniteGraphSort],
    expected: TypedFiniteGraphSort,
    *,
    path: str,
) -> None:
    for index in range(len(arguments)):
        _require_argument(symbol, arguments, index, expected, path=path)


def _require_argument(
    symbol: _Symbol,
    arguments: list[TypedFiniteGraphSort],
    index: int,
    expected: TypedFiniteGraphSort,
    *,
    path: str,
) -> None:
    actual = arguments[index]
    if actual == expected:
        return
    _, cd, name = symbol
    raise MathXMLValidationError(
        f"Argument {index + 1} of `{cd}:{name}` at {path} must have sort "
        f"`{expected.render()}`; received `{actual.render()}`."
    )


def _require_graph(
    symbol: _Symbol, arguments: list[TypedFiniteGraphSort], index: int, *, path: str
) -> str:
    graph = arguments[index]
    if graph.name == "fin_simple_graph" and graph.graph is not None:
        return graph.graph
    _require_argument(symbol, arguments, index, _FIN_SIMPLE_GRAPH, path=path)
    raise AssertionError("unreachable")
