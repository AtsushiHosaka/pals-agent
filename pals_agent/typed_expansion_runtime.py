"""Explicit runtime transport for fourteen previously authoring-only profiles.

This module serializes closed expression trees. The original, unchanged profile
validator decides arity, sorts, carrier identities, binding order and closure.
A registry entry does not establish truth or publication authority.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from pals_agent import typed_local_catalog as local
from pals_agent.typed_expansion_profiles import expansion_profile_spec

SCHEMA_VERSION = "pals.typed-expansion-expression.v1"
EXPANSION_PROFILES = frozenset(
    {
        "typed-calculus-v2",
        "typed-calculus-v3",
        "typed-calculus-v4",
        "typed-calculus-v5",
        "typed-linear-algebra-v2",
        "typed-linear-algebra-v3",
        "typed-linear-algebra-v4",
        "typed-linear-algebra-v5",
        "typed-linear-algebra-v6",
        "typed-commalg-modules-v2",
        "typed-commalg-v3",
        "typed-commalg-v4",
        "typed-multivariable-v5",
        "typed-vector-calculus-v6",
    }
)
LEGACY_PROFILES = frozenset(
    {
        "typed-math-matrix-v1",
        "typed-math-v1",
        "typed-real-analysis-v1",
        "typed-multivariable-calculus-v1",
        "typed-ode-v1",
        "typed-finite-graph-v1",
        "typed-geometry-complex-v1",
        "typed-plane-geometry-v1",
        "typed-probability-v1",
        "typed-number-theory-v1",
        "typed-commutative-algebra-v1",
        "typed-commutative-algebra-modules-v1",
        "typed-commutative-algebra-localization-v1",
        "typed-commutative-algebra-integral-v1",
        "typed-commutative-algebra-decomposition-v1",
        "typed-commutative-algebra-chain-dimension-v1",
    }
)
_NAMESPACE = "http://www.openmath.org/OpenMath"
MAX_BYTES = 262_144
MAX_NODES = 4096
MAX_DEPTH = 64
MAX_TEXT = 20_000

_LINEAR_V2_GUIDANCE = """
Exact typed-linear-algebra-v2 declaration sorts (cd la2):
Field and Nat are atomic: use kind="symbol", never an application with [].
FiniteDimensionalSpace(K), Scalar(K), Vector(K,V), Subspace(K,V),
LinearMap(K,V,W), VectorFamily(K,V,n), ScalarFamily(K,n), Basis(K,V,n)
are dependent sorts: use kind="application" with the shown ordered arguments.
K is an earlier bound Field; V and W are earlier FiniteDimensionalSpace(K)
carriers. n is an earlier bound Nat when used as a family/basis index.
FiniteDimensionalSpace(K) already includes AddCommGroup, Module K and
FiniteDimensional K; do not add or omit assumptions elsewhere to change the target.
In the signatures below, every explicit carrier/index is REQUIRED, including
when Lean could infer it. Space variables and subspace values are distinct.
All listed value operators are cd la2 with the exact profile cdbase:
dim(K,V) -> Nat; sub_dim(K,V,S) -> Nat for S:Subspace(K,V).
sub_top(K,V), sub_bot(K,V) -> Subspace(K,V).
sub_sup(K,V,S,T), sub_inf(K,V,S,T) -> Subspace(K,V).
sub_le(K,V,S,T), sub_lt(K,V,S,T) -> Prop.
kernel(K,V,W,f) -> Subspace(K,V); range(K,V,W,f) -> Subspace(K,W),
where f:LinearMap(K,V,W). Neither kernel(f) nor range(f) is accepted.
The dimension of a subspace uses sub_dim with its AMBIENT space: for example,
sub_dim(K,W,range(K,V,W,f)); dim(K,range(...)) is invalid because range is
a subspace value, not a declared finite-dimensional carrier.
injective(K,V,W,f), surjective(K,V,W,f) -> Prop.
linear_comp(K,V,W,U,f,g) -> LinearMap(K,V,U), where f:V->W and g:W->U.
linear_sub(K,V,W,f,g), linear_smul(K,V,W,a,f) -> LinearMap(K,V,W), a:Scalar(K).
linear_id(K,V) -> LinearMap(K,V,V).
det(K,V,f) -> Scalar(K); eigenspace(K,V,f,a) -> Subspace(K,V),
where f:LinearMap(K,V,V) and a:Scalar(K).
family_span(K,V,n,v), independent(K,V,n,v) take v:VectorFamily(K,V,n)
and return Subspace(K,V), Prop respectively.
basis_vectors(K,V,n,b) -> VectorFamily(K,V,n), b:Basis(K,V,n).
scalar_family_injective(K,n,a) -> Prop, a:ScalarFamily(K,n).
eigenfamily(K,V,n,f,a,v) -> Prop; has_eigenbasis(K,V,n,f,a) -> Prop,
where f:LinearMap(K,V,V), a:ScalarFamily(K,n), v:VectorFamily(K,V,n).
scalar_zero(K), scalar_mul(K,a,b), scalar_pow(K,a,m) -> Scalar(K),
where a,b:Scalar(K), m:Nat. A bare nonnegative integer node has Nat sort,
never Scalar(K). No other scalar literal/cast constructor is available here.
Standard http://www.openmath.org/cd operators: logic1 and/or/implies each take
exactly two Props, not one; logic1 not takes one Prop. relation1 eq/neq take
two values of the same sort, excluding carrier/Prop equality. relation1 leq/lt
and arith1 plus take two Nats; plus returns Nat and the relations return Prop.
typed1 forall/exists are binder nodes with Prop bodies; typed1 type is only the
declaration type_key. No sort constructor is a term or a zero-argument value.
"""


def runtime_profile_specs() -> dict[str, local._ProfileSpec]:
    """Keep the existing sixteen profiles and explicitly add the reviewed fourteen."""
    specs = {
        value.profile_id: value
        for value in vars(local).values()
        if isinstance(value, local._ProfileSpec)
    }
    if set(specs) != LEGACY_PROFILES:
        raise ValueError("Legacy runtime profile population changed")
    for identifier in sorted(EXPANSION_PROFILES):
        spec = expansion_profile_spec(identifier)
        if spec is None or identifier in specs:
            raise ValueError("Runtime expansion profile unavailable or duplicated")
        specs[identifier] = spec
    return specs


def _spec(profile_id: str) -> local._ProfileSpec:
    if profile_id not in EXPANSION_PROFILES:
        raise ValueError("Expansion expression profile unsupported")
    spec = expansion_profile_spec(profile_id)
    if spec is None:
        raise ValueError("Expansion expression profile unavailable")
    return spec


def _symbols(profile_id: str) -> list[tuple[str, str, str]]:
    spec = _spec(profile_id)
    payload = json.loads(
        (Path(__file__).parent / "content_dictionaries" / Path(spec.registry_path).name).read_text()
    )
    identities = [tuple(row[k] for k in ("cdbase", "cd", "name")) for row in payload["symbols"]]
    if not identities or len(set(identities)) != len(identities):
        raise ValueError("Expansion registry identities invalid")
    return identities


def _closed(properties: dict[str, Any]) -> dict[str, Any]:
    return dict(
        type="object", properties=properties, required=list(properties), additionalProperties=False
    )


def response_schema(profile_id: str) -> dict[str, Any]:
    symbols = _symbols(profile_id)
    # Every identity is allowlisted as a whole tuple; cd/name cannot cross cdbases.
    operator_definition = {
        "anyOf": [
            _closed(
                {
                    k: {"type": "string", "enum": [v]}
                    for k, v in zip(("cdbase", "cd", "name"), symbol, strict=True)
                }
            )
            for symbol in symbols
        ]
    }
    operator = {"$ref": "#/$defs/operator"}
    node = {"$ref": "#/$defs/expression"}
    string = {"type": "string"}
    declaration = _closed({"name": string, "type_key": operator, "sort": node})
    variants = [
        _closed({"kind": {"type": "string", "enum": ["variable"]}, "name": string}),
        _closed({"kind": {"type": "string", "enum": ["integer"]}, "value": string}),
        _closed({"kind": {"type": "string", "enum": ["symbol"]}, "operator": operator}),
        _closed(
            {
                "kind": {"type": "string", "enum": ["application"]},
                "operator": operator,
                "arguments": {"type": "array", "items": node, "minItems": 0, "maxItems": 256},
            }
        ),
        _closed(
            {
                "kind": {"type": "string", "enum": ["binder"]},
                "operator": operator,
                "declarations": {
                    "type": "array",
                    "items": declaration,
                    "minItems": 1,
                    "maxItems": 256,
                },
                "body": node,
            }
        ),
    ]
    schema = _closed({"version": {"type": "string", "enum": ["2.0"]}, "body": node})
    schema["$defs"] = {"operator": operator_definition, "expression": {"anyOf": variants}}
    return schema


def guidance(profile_id: str) -> str:
    _spec(profile_id)
    common = (
        "Use the closed expansion expression schema, not XML. An application contains "
        "an exact registry operator and its ordered arguments array. A symbol has an "
        "operator; a variable has a name; an integer has its original decimal value. "
        "A binder has an operator, ordered declarations(name,type_key,sort), and body. "
        "A sort is an expression tree, including all explicit dependent carrier arguments. "
        "Atomic sorts are kind=symbol, NOT kind=application with an empty arguments array. "
        "A dependent sort is kind=application with every required carrier in signature order. "
        "Use an empty application only for a genuine listed nullary VALUE operator, never "
        "as a generic spelling of a sort. Bind carriers before their dependent variables; "
        "each declaration type_key is the selected registry's exact type symbol. "
        "Preserve carrier names, scope, quantifier order, premises and every literal. "
        "Use only the selected registry: no casts, dimensions, premises or missing terms "
        "may be inferred. The original profile validator checks the complete result."
    )
    return common + ("\n" + _LINEAR_V2_GUIDANCE if profile_id == "typed-linear-algebra-v2" else "")


def to_openmath_xml(raw: str, profile_id: str) -> str:
    spec = _spec(profile_id)
    allowed = set(_symbols(profile_id))
    if not isinstance(raw, str) or len(raw.encode()) > MAX_BYTES:
        raise ValueError("Expansion response byte bound exceeded")

    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Expansion duplicate JSON member")
            result[key] = value
        return result

    def constant(_value: str) -> None:
        raise ValueError("Expansion JSON constant invalid")

    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
    except RecursionError:
        raise ValueError("Expansion response depth exceeded") from None
    count = 0

    def fields(obj: Any, expected: set[str]) -> dict[str, Any]:
        if not isinstance(obj, dict) or set(obj) != expected:
            raise ValueError("Expansion expression fields invalid")
        return obj

    def text(value: Any) -> str:
        from pals_agent.typed_openmath_ast import _xml_text

        return _xml_text(value)

    def element(tag: str, attrs: dict[str, str] | None = None) -> ET.Element:
        nonlocal count
        count += 1
        if count > MAX_NODES:
            raise ValueError("Expansion tree node bound exceeded")
        return ET.Element("{" + _NAMESPACE + "}" + tag, attrs or {})

    def symbol(obj: Any) -> ET.Element:
        data = fields(obj, {"cdbase", "cd", "name"})
        attrs = {key: text(data[key]) for key in ("cdbase", "cd", "name")}
        if tuple(attrs.values()) not in allowed:
            raise ValueError("Expansion symbol outside selected registry")
        return element("OMS", attrs)

    def node(obj: Any, depth: int) -> ET.Element:
        if depth > MAX_DEPTH or not isinstance(obj, dict):
            raise ValueError("Expansion expression depth or type invalid")
        kind = obj.get("kind")
        if kind == "variable":
            fields(obj, {"kind", "name"})
            return element("OMV", {"name": text(obj["name"])})
        if kind == "integer":
            fields(obj, {"kind", "value"})
            result = element("OMI")
            result.text = text(obj["value"])
            return result
        if kind == "symbol":
            fields(obj, {"kind", "operator"})
            return symbol(obj["operator"])
        if kind == "application":
            fields(obj, {"kind", "operator", "arguments"})
            arguments = obj["arguments"]
            if not isinstance(arguments, list) or len(arguments) > 256:
                raise ValueError("Expansion application bound invalid")
            result = element("OMA")
            result.append(symbol(obj["operator"]))
            for argument in arguments:
                result.append(node(argument, depth + 1))
            return result
        if kind == "binder":
            fields(obj, {"kind", "operator", "declarations", "body"})
            declarations = obj["declarations"]
            if not isinstance(declarations, list) or not 1 <= len(declarations) <= 256:
                raise ValueError("Expansion declaration bound invalid")
            result = element("OMBIND")
            result.append(symbol(obj["operator"]))
            variables = element("OMBVAR")
            for declaration in declarations:
                data = fields(declaration, {"name", "type_key", "sort"})
                attributed = element("OMATTR")
                pair = element("OMATP")
                pair.append(symbol(data["type_key"]))
                pair.append(node(data["sort"], depth + 1))
                attributed.append(pair)
                attributed.append(element("OMV", {"name": text(data["name"])}))
                variables.append(attributed)
            result.append(variables)
            result.append(node(obj["body"], depth + 1))
            return result
        raise ValueError("Expansion node kind unsupported")

    fields(value, {"version", "body"})
    if value["version"] != "2.0":
        raise ValueError("Expansion OpenMath version invalid")
    root = element("OMOBJ", {"version": "2.0"})
    root.append(node(value["body"], 0))
    canonical = spec.canonicalize(ET.tostring(root, encoding="unicode"))
    spec.validate_canonical(canonical)
    return canonical


def from_openmath_xml(xml: str, profile_id: str) -> dict[str, Any]:
    """Lossless authoring/test conversion of already validated canonical source."""
    _spec(profile_id).validate_canonical(xml)
    root = ET.fromstring(xml)

    def symbol(e: ET.Element) -> dict[str, str]:
        return {key: e.attrib[key] for key in ("cdbase", "cd", "name")}

    def node(e: ET.Element) -> dict[str, Any]:
        tag = e.tag.rsplit("}", 1)[-1]
        if tag == "OMV":
            return dict(kind="variable", name=e.attrib["name"])
        if tag == "OMI":
            return dict(kind="integer", value=e.text)
        if tag == "OMS":
            return dict(kind="symbol", operator=symbol(e))
        if tag == "OMA":
            return dict(
                kind="application", operator=symbol(e[0]), arguments=[node(x) for x in list(e)[1:]]
            )
        if tag == "OMBIND":
            declarations = [
                dict(name=d[1].attrib["name"], type_key=symbol(d[0][0]), sort=node(d[0][1]))
                for d in e[1]
            ]
            return dict(
                kind="binder", operator=symbol(e[0]), declarations=declarations, body=node(e[2])
            )
        raise ValueError("Expansion canonical source node unsupported")

    return dict(version=root.attrib["version"], body=node(root[0]))
