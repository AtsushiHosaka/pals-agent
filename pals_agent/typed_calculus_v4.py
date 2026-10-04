"""Closed multivariable real calculus authoring profile.

RealInnerProductSpace includes NormedAddCommGroup, InnerProductSpace real,
and FiniteDimensional real assumptions. This authoring profile does not register runtime
structuring or publication support. No existing profile semantics are modified.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from importlib import resources
from typing import NoReturn, cast

from .openmath import (
    OPENMATH_NAMESPACE,
    MathXMLValidationError,
    _canonicalize_openmath_v4_root,
    validate_openmath_xml,
)

PROFILE_ID = "typed-calculus-v4"
CDBASE = "urn:pals:openmath:typed-calculus:v4"
STANDARD = "http://www.openmath.org/cd"
MAX_BYTES = 65_536
MAX_NODES = 4096
MAX_DEPTH = 64


@dataclass(frozen=True)
class Sort:
    kind: str
    field: str = ""
    domain: str = ""
    codomain: str = ""
    index: str = ""


PROP = Sort("prop")
NAT = Sort("nat")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ALLOWED_ATTRIBUTES = {
    "OMOBJ": {"version"},
    "OMS": {"cdbase", "cd", "name"},
    "OMV": {"name"},
    "OMI": set(),
    "OMA": set(),
    "OMBIND": set(),
    "OMBVAR": set(),
    "OMATTR": set(),
    "OMATP": set(),
}
REAL = Sort("real")
_TYPE_SIGNATURES = {
    "Vector": (("Space",), "Vector@0"),
    "Function": (("Space", "Space"), "Function@0,1"),
    "CLM": (("Space", "Space"), "CLM@0,1"),
    "ScalarFunction": (("Space",), "ScalarFunction@0"),
    "ScalarCLM": (("Space",), "ScalarCLM@0"),
    "Curve": (("Space",), "Curve@0"),
    "DerivativeField": (("Space", "Space"), "DerivativeField@0,1"),
    "Bilinear": (("Space", "Space"), "Bilinear@0,1"),
}
_TYPE_NAMES = {"RealInnerProductSpace", "Nat", "Real", "RealFunction"} | set(_TYPE_SIGNATURES)
_SIGNATURES: dict[str, tuple[tuple[str, ...], str]] = {
    "apply": (("Space", "Space", "Function@0,1", "Vector@0"), "Vector@1"),
    "scalar_apply": (("Space", "ScalarFunction@0", "Vector@0"), "Real"),
    "curve_apply": (("Space", "Curve@0", "Real"), "Vector@0"),
    "clm_apply": (("Space", "Space", "CLM@0,1", "Vector@0"), "Vector@1"),
    "scalar_clm_apply": (("Space", "ScalarCLM@0", "Vector@0"), "Real"),
    "bilinear_apply": (("Space", "Space", "Bilinear@0,1", "Vector@0", "Vector@0"), "Vector@1"),
    "field_apply": (("Space", "Space", "DerivativeField@0,1", "Vector@0"), "CLM@0,1"),
    "real_nat": (("Nat",), "Real"),
    "real_mul": (("Real", "Real"), "Real"),
    "real_abs": (("Real",), "Real"),
    "vector_zero": (("Space",), "Vector@0"),
    "vector_add": (("Space", "Vector@0", "Vector@0"), "Vector@0"),
    "vector_sub": (("Space", "Vector@0", "Vector@0"), "Vector@0"),
    "vector_scale": (("Space", "Real", "Vector@0"), "Vector@0"),
    "norm": (("Space", "Vector@0"), "Real"),
    "inner": (("Space", "Vector@0", "Vector@0"), "Real"),
    "clm_norm": (("Space", "Space", "CLM@0,1"), "Real"),
    "clm_zero": (("Space", "Space"), "CLM@0,1"),
    "scalar_clm_zero": (("Space",), "ScalarCLM@0"),
    "clm_add": (("Space", "Space", "CLM@0,1", "CLM@0,1"), "CLM@0,1"),
    "clm_sub": (("Space", "Space", "CLM@0,1", "CLM@0,1"), "CLM@0,1"),
    "clm_scale": (("Space", "Space", "Real", "CLM@0,1"), "CLM@0,1"),
    "clm_compose": (("Space", "Space", "Space", "CLM@1,2", "CLM@0,1"), "CLM@0,2"),
    "smul_right": (("Space", "Space", "ScalarCLM@0", "Vector@1"), "CLM@0,1"),
    "dual": (("Space", "Vector@0"), "ScalarCLM@0"),
    "adjoint_apply": (("Space", "Space", "CLM@0,1", "Vector@1"), "Vector@0"),
    "linear_function": (("Space", "Space", "CLM@0,1"), "Function@0,1"),
    "affine_function": (("Space", "Space", "CLM@0,1", "Vector@1"), "Function@0,1"),
    "compose": (("Space", "Space", "Space", "Function@1,2", "Function@0,1"), "Function@0,2"),
    "function_add": (("Space", "Space", "Function@0,1", "Function@0,1"), "Function@0,1"),
    "function_sub": (("Space", "Space", "Function@0,1", "Function@0,1"), "Function@0,1"),
    "function_scale": (("Space", "Space", "Real", "Function@0,1"), "Function@0,1"),
    "function_smul": (("Space", "Space", "ScalarFunction@0", "Function@0,1"), "Function@0,1"),
    "scalar_add": (("Space", "ScalarFunction@0", "ScalarFunction@0"), "ScalarFunction@0"),
    "scalar_scale": (("Space", "Real", "ScalarFunction@0"), "ScalarFunction@0"),
    "scalar_compose": (("Space", "Space", "ScalarFunction@1", "Function@0,1"), "ScalarFunction@0"),
    "inner_composition": (("Space", "Space", "Function@0,1", "Function@0,1"), "ScalarFunction@0"),
    "inner_derivative": (
        ("Space", "Space", "Vector@1", "Vector@1", "CLM@0,1", "CLM@0,1"),
        "ScalarCLM@0",
    ),
    "norm_square_composition": (("Space", "Space", "Function@0,1"), "ScalarFunction@0"),
    "norm_composition": (("Space", "Space", "Function@0,1"), "ScalarFunction@0"),
    "distance_composition": (
        ("Space", "Space", "Function@0,1", "Function@0,1"),
        "ScalarFunction@0",
    ),
    "norm_square_derivative": (("Space", "Space", "Vector@1", "CLM@0,1"), "ScalarCLM@0"),
    "inner_function": (("Space", "Vector@0"), "ScalarFunction@0"),
    "norm_square": (("Space",), "ScalarFunction@0"),
    "curve_compose": (("Space", "Space", "Function@0,1", "Curve@0"), "Curve@1"),
    "scalar_curve_compose": (("Space", "ScalarFunction@0", "Curve@0"), "RealFunction"),
    "has_fderiv": (("Space", "Space", "Function@0,1", "Vector@0", "CLM@0,1"), "Prop"),
    "has_scalar_fderiv": (("Space", "ScalarFunction@0", "Vector@0", "ScalarCLM@0"), "Prop"),
    "has_gradient": (("Space", "ScalarFunction@0", "Vector@0", "Vector@0"), "Prop"),
    "has_curve_deriv": (("Space", "Curve@0", "Real", "Vector@0"), "Prop"),
    "has_real_deriv": (("RealFunction", "Real", "Real"), "Prop"),
    "has_line_deriv": (
        ("Space", "Space", "Function@0,1", "Vector@0", "Vector@0", "Vector@1"),
        "Prop",
    ),
    "derivative_field": (("Space", "Space", "Function@0,1", "DerivativeField@0,1"), "Prop"),
    "has_second_deriv": (
        ("Space", "Space", "DerivativeField@0,1", "Vector@0", "Bilinear@0,1"),
        "Prop",
    ),
    "differentiable_at": (("Space", "Space", "Function@0,1", "Vector@0"), "Prop"),
    "scalar_differentiable_at": (("Space", "ScalarFunction@0", "Vector@0"), "Prop"),
    "continuous_at": (("Space", "Space", "Function@0,1", "Vector@0"), "Prop"),
    "scalar_continuous_at": (("Space", "ScalarFunction@0", "Vector@0"), "Prop"),
    "scalar_line_deriv": (("Space", "ScalarFunction@0", "Vector@0", "Vector@0"), "Real"),
    "fderiv": (("Space", "Space", "Function@0,1", "Vector@0"), "CLM@0,1"),
    "local_min": (("Space", "ScalarFunction@0", "Vector@0"), "Prop"),
    "local_extremum": (("Space", "ScalarFunction@0", "Vector@0"), "Prop"),
    "cont_diff": (("Space", "Space", "Nat", "Function@0,1"), "Prop"),
    "scalar_cont_diff": (("Space", "Nat", "ScalarFunction@0"), "Prop"),
}
_LA_ARITIES = {name: len(signature) for name, (signature, _) in _SIGNATURES.items()}
_STANDARD_ARITIES = {
    ("logic1", "and"): 2,
    ("logic1", "or"): 2,
    ("logic1", "implies"): 2,
    ("logic1", "not"): 1,
    ("relation1", "eq"): 2,
    ("relation1", "neq"): 2,
    ("relation1", "leq"): 2,
    ("relation1", "lt"): 2,
    ("arith1", "plus"): 2,
}


def _fail(message: str) -> NoReturn:
    raise MathXMLValidationError("typed-calculus-v4: " + message)


def _symbol(node: ET.Element) -> tuple[str, str, str]:
    return (node.get("cdbase", ""), node.get("cd", ""), node.get("name", ""))


def _registry() -> frozenset[tuple[str, str, str]]:
    data = json.loads(
        resources.files("pals_agent.content_dictionaries")
        .joinpath("typed-calculus-v4-registry.json")
        .read_text(encoding="utf-8")
    )
    expected = {(CDBASE, "typed4", x) for x in ("forall", "exists", "type")}
    expected |= {(CDBASE, "calculus4", x) for x in _TYPE_NAMES | set(_LA_ARITIES)}
    expected |= {(STANDARD, cd, name) for cd, name in _STANDARD_ARITIES}
    if not isinstance(data, dict) or set(data) != {"schema_version", "profile_id", "symbols"}:
        raise RuntimeError("calculus v4 registry header is malformed")
    rows = data.get("symbols", [])
    if not isinstance(rows, list):
        raise RuntimeError("calculus v4 registry symbols are malformed")
    for entry in rows:
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(k), str) and entry[k]
            for k in ("cdbase", "cd", "name", "semantics")
        ):
            raise RuntimeError("calculus v4 registry entry lacks identity/semantics")
        signature = {**_TYPE_SIGNATURES, **_SIGNATURES}.get(entry["name"])
        if entry["cd"] == "calculus4" and signature is not None:
            args, result = signature
            if entry.get("arguments") != list(args) or entry.get("result") != result:
                raise RuntimeError("calculus v4 registry signature differs from implementation")
        if entry["cdbase"] == STANDARD and entry.get("arity") != _STANDARD_ARITIES.get(
            (entry["cd"], entry["name"])
        ):
            raise RuntimeError("calculus v4 standard signature differs from implementation")
    actual = {(x["cdbase"], x["cd"], x["name"]) for x in rows}
    if (
        data.get("schema_version") != "pals.typed-calculus-registry.v4"
        or data.get("profile_id") != PROFILE_ID
        or actual != expected
        or len(actual) != len(rows)
    ):
        raise RuntimeError("calculus v4 registry does not match the closed grammar")
    return frozenset(actual)


def _tag(node: ET.Element) -> str:
    prefix = "{" + OPENMATH_NAMESPACE + "}"
    if not isinstance(node.tag, str) or not node.tag.startswith(prefix):
        _fail("every element must use the exact OpenMath namespace")
    return node.tag[len(prefix) :]


def _shape(root: ET.Element) -> None:
    symbols = _registry()
    count = 0

    def visit(node: ET.Element, parent: str | None, depth: int) -> None:
        nonlocal count
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            _fail("node or depth bound exceeded")
        tag = _tag(node)
        if tag not in _ALLOWED_ATTRIBUTES or set(node.attrib) != _ALLOWED_ATTRIBUTES[tag]:
            _fail(f"unknown element or attributes on {tag}")
        if any(len(v) > 256 for v in node.attrib.values()):
            _fail("attribute bound exceeded")
        if (node.text and node.text.strip() and tag != "OMI") or (node.tail and node.tail.strip()):
            _fail("unexpected text")
        if tag == "OMOBJ" and (
            parent is not None or node.get("version") != "2.0" or len(node) != 1
        ):
            _fail("OMOBJ requires one expression and version 2.0")
        if tag == "OMS" and (_symbol(node) not in symbols or len(node)):
            _fail("unknown symbol, cdbase, or symbol children")
        if tag == "OMV" and (not _NAME.fullmatch(node.get("name", "")) or len(node)):
            _fail("invalid variable")
        if tag == "OMI" and (len(node) or not re.fullmatch(r"0|[1-9][0-9]{0,8}", node.text or "")):
            _fail("OMI must be a canonical natural literal below one billion")
        if tag == "OMA" and (len(node) < 1 or _tag(node[0]) != "OMS"):
            _fail("application head must be a registered symbol")
        if tag == "OMBIND" and (
            len(node) != 3
            or _tag(node[0]) != "OMS"
            or _symbol(node[0]) not in {(CDBASE, "typed4", "forall"), (CDBASE, "typed4", "exists")}
            or _tag(node[1]) != "OMBVAR"
        ):
            _fail("invalid typed quantifier")
        if tag == "OMBVAR" and (
            parent != "OMBIND" or not 1 <= len(node) <= 64 or any(_tag(c) != "OMATTR" for c in node)
        ):
            _fail("invalid binder declarations")
        if tag == "OMATTR" and (
            parent != "OMBVAR"
            or len(node) != 2
            or _tag(node[0]) != "OMATP"
            or _tag(node[1]) != "OMV"
        ):
            _fail("type attributes are permitted only on bound declarations")
        if tag == "OMATP" and (
            parent != "OMATTR"
            or len(node) != 2
            or _tag(node[0]) != "OMS"
            or _symbol(node[0]) != (CDBASE, "typed4", "type")
        ):
            _fail("invalid type annotation")
        for child in node:
            visit(child, tag, depth + 1)

    visit(root, None, 1)
    if _tag(root) != "OMOBJ" or _tag(root[0]) != "OMBIND":
        _fail("root must be a closed typed quantification")


def _same(actual: Sort, expected: Sort) -> None:
    if actual != expected:
        _fail(f"carrier/type mismatch: expected {expected}, received {actual}")


def _bound(node: ET.Element, env: dict[str, Sort], kind: str) -> str:
    if _tag(node) != "OMV" or node.get("name") not in env:
        _fail("dependent carrier/index arguments must be previously bound variables")
    name = node.get("name", "")
    if env[name].kind != kind:
        _fail(f"expected a bound {kind} structure, received {env[name].kind}")
    return name


def _sort(node: ET.Element, name: str, env: dict[str, Sort]) -> Sort:
    if _tag(node) == "OMS":
        if _symbol(node) == (CDBASE, "calculus4", "RealInnerProductSpace"):
            return Sort("space", domain=name)
        if _symbol(node) == (CDBASE, "calculus4", "Nat"):
            return NAT
        if _symbol(node) == (CDBASE, "calculus4", "Real"):
            return REAL
        if _symbol(node) == (CDBASE, "calculus4", "RealFunction"):
            return Sort("real_function")
        _fail("invalid atomic declaration sort")
    if _tag(node) != "OMA":
        _fail("invalid declaration sort")
    base, cd, ty = _symbol(node[0])
    args = list(node)[1:]
    if (base, cd) != (CDBASE, "calculus4") or ty not in _TYPE_SIGNATURES:
        _fail("unknown declaration sort")
    signature, result = _TYPE_SIGNATURES[ty]
    return _apply_signature(args, signature, result, env)


def _apply_signature(
    args: list[ET.Element], signature: tuple[str, ...], result: str, env: dict[str, Sort]
) -> Sort:
    if len(args) != len(signature):
        _fail("operator arity mismatch")

    def resolve(spec: str) -> Sort:
        kind, _, refs = spec.partition("@")
        if not refs:
            return {"Nat": NAT, "Real": REAL, "Prop": PROP, "RealFunction": Sort("real_function")}[
                kind
            ]
        positions = [int(x) for x in refs.split(",")]
        space = _bound(args[positions[0]], env, "space")
        target = _bound(args[positions[1]], env, "space") if len(positions) == 2 else ""
        return Sort(kind.lower(), domain=space, codomain=target)

    for arg, spec in zip(args, signature, strict=True):
        if spec == "Space":
            _bound(arg, env, "space")
        elif spec == "IndexSize":
            _bound(arg, env, "nat")
        else:
            _same(_infer(arg, env), resolve(spec))
    return resolve(result)


def _infer(node: ET.Element, env: dict[str, Sort]) -> Sort:
    tag = _tag(node)
    if tag == "OMV":
        name = node.get("name", "")
        if name not in env:
            _fail(f"unbound variable {name}")
        return env[name]
    if tag == "OMI":
        return NAT
    if tag == "OMBIND":
        scope = dict(env)
        for decl in node[1]:
            name = decl[1].get("name", "")
            if name in scope:
                _fail("duplicate declaration or shadowed bound name")
            scope[name] = _sort(decl[0][1], name, scope)
        _same(_infer(node[2], scope), PROP)
        return PROP
    if tag != "OMA":
        _fail("sort/symbol cannot be used as a mathematical value")
    base, cd, op = _symbol(node[0])
    args = list(node)[1:]
    if base == STANDARD:
        if len(args) != _STANDARD_ARITIES.get((cd, op)):
            _fail("standard operator arity mismatch")
        types = [_infer(a, env) for a in args]
        if cd == "logic1":
            for ty in types:
                _same(ty, PROP)
            return PROP
        _same(types[0], types[1])
        if op in {"eq", "neq"}:
            if types[0].kind in {"space", "prop"}:
                _fail("carrier/proposition equality is outside this profile")
            return PROP
        if types[0] not in {NAT, REAL}:
            _fail("ordered and arithmetic operators require numeric values")
        return types[0] if cd == "arith1" else PROP
    if (base, cd) != (CDBASE, "calculus4") or op not in _SIGNATURES:
        _fail("unknown value operator")
    signature, result = _SIGNATURES[op]
    return _apply_signature(args, signature, result, env)


def canonicalize_typed_calculus_v4_openmath_xml(xml: str) -> str:
    """Validate closed dependent types before alpha-aware canonicalization."""
    if not isinstance(xml, str) or len(xml.encode("utf-8")) > MAX_BYTES:
        _fail("XML byte bound exceeded")
    root = validate_openmath_xml(xml)
    _shape(root)
    _same(_infer(root[0], {}), PROP)
    return cast(str, _canonicalize_openmath_v4_root(root))


def validate_canonical_typed_calculus_v4_openmath_xml(xml: str) -> str:
    """Accept exact canonical bytes only."""
    canonical = canonicalize_typed_calculus_v4_openmath_xml(xml)
    if canonical != xml:
        _fail("input is not exact canonical XML")
    return canonical
