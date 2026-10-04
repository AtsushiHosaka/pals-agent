"""Closed coordinate calculus, multiple-integral and constraint authoring profile.

Dimensions are previously bound natural variables; dependent carriers are Fin n
real coordinate spaces with their standard topology, norm and Lebesgue volume.
No runtime routing or publication support is registered by this module.
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

PROFILE_ID = "typed-multivariable-v5"
CDBASE = "urn:pals:openmath:typed-multivariable:v5"
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
    "Index": (("Dim",), "Index@0"),
    "Vector": (("Dim",), "Vector@0"),
    "Function": (("Dim", "Dim"), "Function@0,1"),
    "CLM": (("Dim", "Dim"), "CLM@0,1"),
    "Matrix": (("Dim", "Dim"), "Matrix@0,1"),
    "ScalarFunction": (("Dim",), "ScalarFunction@0"),
    "ScalarCLM": (("Dim",), "ScalarCLM@0"),
    "Bilinear": (("Dim",), "Bilinear@0"),
    "ScalarDerivativeField": (("Dim",), "ScalarDerivativeField@0"),
    "DerivativeField": (("Dim", "Dim"), "DerivativeField@0,1"),
    "Set": (("Dim",), "Set@0"),
    "Curve": (("Dim",), "Curve@0"),
    "FunctionFamily": (("Dim", "Dim"), "FunctionFamily@0,1"),
    "DualFamily": (("Dim", "Dim"), "DualFamily@0,1"),
    "RealFunctionFamily": (("Dim",), "RealFunctionFamily@0"),
    "ProductScalarFunction": (("Dim", "Dim"), "ProductScalarFunction@0,1"),
    "ProductFunction": (("Dim", "Dim", "Dim"), "ProductFunction@0,1,2"),
    "ProductCLM": (("Dim", "Dim", "Dim"), "ProductCLM@0,1,2"),
    "LeftField": (("Dim", "Dim", "Dim"), "LeftField@0,1,2"),
    "RightField": (("Dim", "Dim", "Dim"), "RightField@0,1,2"),
}
_TYPE_NAMES = {"Nat", "Real", "RealFunction"} | set(_TYPE_SIGNATURES)
_SIGNATURES: dict[str, tuple[tuple[str, ...], str]] = {
    "real_nat": (("Nat",), "Real"),
    "real_add": (("Real", "Real"), "Real"),
    "real_sub": (("Real", "Real"), "Real"),
    "real_mul": (("Real", "Real"), "Real"),
    "apply": (("Dim", "Dim", "Function@0,1", "Vector@0"), "Vector@1"),
    "scalar_apply": (("Dim", "ScalarFunction@0", "Vector@0"), "Real"),
    "coordinate": (("Dim", "Vector@0", "Index@0"), "Real"),
    "basis_vector": (("Dim", "Index@0"), "Vector@0"),
    "zero": (("Dim",), "Vector@0"),
    "add": (("Dim", "Vector@0", "Vector@0"), "Vector@0"),
    "projection": (("Dim", "Index@0"), "ScalarFunction@0"),
    "projection_clm": (("Dim", "Index@0"), "ScalarCLM@0"),
    "update_curve": (("Dim", "Vector@0", "Index@0"), "Curve@0"),
    "coordinate_slice": (("Dim", "ScalarFunction@0", "Vector@0", "Index@0"), "RealFunction"),
    "component": (("Dim", "Dim", "Function@0,1", "Index@1"), "ScalarFunction@0"),
    "component_clm": (("Dim", "Dim", "CLM@0,1", "Index@1"), "ScalarCLM@0"),
    "has_fderiv": (("Dim", "Dim", "Function@0,1", "Vector@0", "CLM@0,1"), "Prop"),
    "has_scalar_fderiv": (("Dim", "ScalarFunction@0", "Vector@0", "ScalarCLM@0"), "Prop"),
    "has_scalar_strict_fderiv": (("Dim", "ScalarFunction@0", "Vector@0", "ScalarCLM@0"), "Prop"),
    "differentiable_at": (("Dim", "Dim", "Function@0,1", "Vector@0"), "Prop"),
    "scalar_differentiable_at": (("Dim", "ScalarFunction@0", "Vector@0"), "Prop"),
    "scalar_differentiable": (("Dim", "ScalarFunction@0"), "Prop"),
    "has_deriv": (("RealFunction", "Real", "Real"), "Prop"),
    "has_curve_deriv": (("Dim", "Curve@0", "Real", "Vector@0"), "Prop"),
    "clm_apply": (("Dim", "Dim", "CLM@0,1", "Vector@0"), "Vector@1"),
    "dual_apply": (("Dim", "ScalarCLM@0", "Vector@0"), "Real"),
    "dual_zero": (("Dim",), "ScalarCLM@0"),
    "dual_add": (("Dim", "ScalarCLM@0", "ScalarCLM@0"), "ScalarCLM@0"),
    "dual_scale": (("Dim", "Real", "ScalarCLM@0"), "ScalarCLM@0"),
    "compose": (("Dim", "Dim", "Dim", "Function@1,2", "Function@0,1"), "Function@0,2"),
    "jacobian": (("Dim", "Dim", "Function@0,1", "Vector@0"), "Matrix@1,0"),
    "matrix_entry": (("Dim", "Dim", "Matrix@0,1", "Index@0", "Index@1"), "Real"),
    "matrix_mul": (("Dim", "Dim", "Dim", "Matrix@0,1", "Matrix@1,2"), "Matrix@0,2"),
    "matrix_action": (("Dim", "Dim", "Matrix@0,1", "Vector@1"), "Vector@0"),
    "linearization_remainder": (("Dim", "Dim", "Function@0,1", "Vector@0"), "Function@0,1"),
    "little_o_displacement": (("Dim", "Dim", "Function@0,1", "Vector@0"), "Prop"),
    "scalar_cont_diff": (("Dim", "Nat", "ScalarFunction@0"), "Prop"),
    "field_cont_diff": (("Dim", "Nat", "ScalarDerivativeField@0"), "Prop"),
    "scalar_fderiv_field": (("Dim", "ScalarFunction@0"), "ScalarDerivativeField@0"),
    "bilinear_apply": (("Dim", "Bilinear@0", "Vector@0", "Vector@0"), "Real"),
    "quadratic": (("Dim", "Bilinear@0"), "ScalarFunction@0"),
    "quadratic_derivative": (("Dim", "Bilinear@0", "Vector@0"), "ScalarCLM@0"),
    "quadratic_field": (("Dim", "Bilinear@0"), "ScalarDerivativeField@0"),
    "symmetrize": (("Dim", "Bilinear@0"), "Bilinear@0"),
    "has_field_derivative": (("Dim", "ScalarDerivativeField@0", "Vector@0", "Bilinear@0"), "Prop"),
    "product_slice_left": (
        ("Dim", "Dim", "Dim", "ProductFunction@0,1,2", "Vector@1"),
        "Function@0,2",
    ),
    "product_slice_right": (
        ("Dim", "Dim", "Dim", "ProductFunction@0,1,2", "Vector@0"),
        "Function@1,2",
    ),
    "left_field_apply": (
        ("Dim", "Dim", "Dim", "LeftField@0,1,2", "Vector@0", "Vector@1"),
        "CLM@0,2",
    ),
    "right_field_apply": (
        ("Dim", "Dim", "Dim", "RightField@0,1,2", "Vector@0", "Vector@1"),
        "CLM@1,2",
    ),
    "continuous_left_field_at": (
        ("Dim", "Dim", "Dim", "LeftField@0,1,2", "Vector@0", "Vector@1"),
        "Prop",
    ),
    "continuous_right_field_at": (
        ("Dim", "Dim", "Dim", "RightField@0,1,2", "Vector@0", "Vector@1"),
        "Prop",
    ),
    "coprod": (("Dim", "Dim", "Dim", "CLM@0,2", "CLM@1,2"), "ProductCLM@0,1,2"),
    "has_product_strict_fderiv": (
        ("Dim", "Dim", "Dim", "ProductFunction@0,1,2", "Vector@0", "Vector@1", "ProductCLM@0,1,2"),
        "Prop",
    ),
    "local_extr_fiber": (("Dim", "ScalarFunction@0", "ScalarFunction@0", "Vector@0"), "Prop"),
    "family_at": (("Dim", "Dim", "FunctionFamily@0,1", "Index@0"), "ScalarFunction@1"),
    "dual_family_at": (("Dim", "Dim", "DualFamily@0,1", "Index@0"), "ScalarCLM@1"),
    "local_extr_fibers": (
        ("Dim", "Dim", "ScalarFunction@1", "FunctionFamily@0,1", "Vector@1"),
        "Prop",
    ),
    "weighted_dual_sum": (("Dim", "Dim", "Vector@0", "DualFamily@0,1"), "ScalarCLM@1"),
    "product_scalar_slice_left": (
        ("Dim", "Dim", "ProductScalarFunction@0,1", "Vector@1"),
        "ScalarFunction@0",
    ),
    "product_scalar_slice_right": (
        ("Dim", "Dim", "ProductScalarFunction@0,1", "Vector@0"),
        "ScalarFunction@1",
    ),
    "axis_jump": (("Dim", "Dim", "Index@0", "Index@1", "Real"), "ProductScalarFunction@0,1"),
    "product_continuous_at": (
        ("Dim", "Dim", "ProductScalarFunction@0,1", "Vector@0", "Vector@1"),
        "Prop",
    ),
    "integrable": (("Dim", "ScalarFunction@0"), "Prop"),
    "integral": (("Dim", "ScalarFunction@0"), "Real"),
    "product_integrable": (("Dim", "Dim", "ProductScalarFunction@0,1"), "Prop"),
    "product_integral": (("Dim", "Dim", "ProductScalarFunction@0,1"), "Real"),
    "product_separable": (
        ("Dim", "Dim", "ScalarFunction@0", "ScalarFunction@1"),
        "ProductScalarFunction@0,1",
    ),
    "inner_integral_right": (("Dim", "Dim", "ProductScalarFunction@0,1"), "ScalarFunction@0"),
    "inner_integral_left": (("Dim", "Dim", "ProductScalarFunction@0,1"), "ScalarFunction@1"),
    "ae_right_sections_integrable": (("Dim", "Dim", "ProductScalarFunction@0,1"), "Prop"),
    "product_ae_strongly_measurable": (("Dim", "Dim", "ProductScalarFunction@0,1"), "Prop"),
    "inner_abs_integral": (("Dim", "Dim", "ProductScalarFunction@0,1"), "ScalarFunction@0"),
    "product_integrable_on": (
        ("Dim", "Dim", "ProductScalarFunction@0,1", "Set@0", "Set@1"),
        "Prop",
    ),
    "product_set_integral": (("Dim", "Dim", "ProductScalarFunction@0,1", "Set@0", "Set@1"), "Real"),
    "inner_set_integral_right": (
        ("Dim", "Dim", "ProductScalarFunction@0,1", "Set@1"),
        "ScalarFunction@0",
    ),
    "set_integral": (("Dim", "ScalarFunction@0", "Set@0"), "Real"),
    "real_family_at": (("Dim", "RealFunctionFamily@0", "Index@0"), "RealFunction"),
    "real_integrable": (("RealFunction",), "Prop"),
    "separable_n_product": (("Dim", "RealFunctionFamily@0"), "ScalarFunction@0"),
    "product_real_integrals": (("Dim", "RealFunctionFamily@0"), "Real"),
    "measurable_set": (("Dim", "Set@0"), "Prop"),
    "injective_on": (("Dim", "Function@0,0", "Set@0"), "Prop"),
    "image": (("Dim", "Function@0,0", "Set@0"), "Set@0"),
    "field_apply": (("Dim", "Dim", "DerivativeField@0,1", "Vector@0"), "CLM@0,1"),
    "member": (("Dim", "Vector@0", "Set@0"), "Prop"),
    "has_fderiv_within": (("Dim", "Function@0,0", "Vector@0", "Set@0", "CLM@0,0"), "Prop"),
    "jacobian_weighted": (
        ("Dim", "Function@0,0", "DerivativeField@0,0", "ScalarFunction@0"),
        "ScalarFunction@0",
    ),
    "integrable_on": (("Dim", "ScalarFunction@0", "Set@0"), "Prop"),
    "curve_apply": (("Dim", "Curve@0", "Real"), "Vector@0"),
    "scalar_field_apply": (("Dim", "ScalarDerivativeField@0", "Vector@0"), "ScalarCLM@0"),
    "pullback_one_form": (("Dim", "ScalarDerivativeField@0", "Curve@0", "Curve@0"), "RealFunction"),
    "interval_integrable": (("RealFunction", "Real", "Real"), "Prop"),
    "interval_integral": (("RealFunction", "Real", "Real"), "Real"),
    "in_uIcc": (("Real", "Real", "Real"), "Prop"),
}
_LA_ARITIES = {name: len(signature) for name, (signature, _) in _SIGNATURES.items()}
_STANDARD_ARITIES = {
    ("logic1", "and"): 2,
    ("logic1", "or"): 2,
    ("logic1", "implies"): 2,
    ("logic1", "not"): 1,
    ("logic1", "equivalent"): 2,
    ("relation1", "eq"): 2,
    ("relation1", "neq"): 2,
    ("relation1", "leq"): 2,
    ("relation1", "lt"): 2,
    ("arith1", "plus"): 2,
}


def _fail(message: str) -> NoReturn:
    raise MathXMLValidationError("typed-multivariable-v5: " + message)


def _symbol(node: ET.Element) -> tuple[str, str, str]:
    return (node.get("cdbase", ""), node.get("cd", ""), node.get("name", ""))


def _registry() -> frozenset[tuple[str, str, str]]:
    data = json.loads(
        resources.files("pals_agent.content_dictionaries")
        .joinpath("typed-multivariable-v5-registry.json")
        .read_text(encoding="utf-8")
    )
    expected = {(CDBASE, "typed5", x) for x in ("forall", "exists", "type")}
    expected |= {(CDBASE, "multivar5", x) for x in _TYPE_NAMES | set(_LA_ARITIES)}
    expected |= {(STANDARD, cd, name) for cd, name in _STANDARD_ARITIES}
    if not isinstance(data, dict) or set(data) != {"schema_version", "profile_id", "symbols"}:
        raise RuntimeError("multivariable v5 registry header is malformed")
    rows = data.get("symbols", [])
    if not isinstance(rows, list):
        raise RuntimeError("multivariable v5 registry symbols are malformed")
    for entry in rows:
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(k), str) and entry[k]
            for k in ("cdbase", "cd", "name", "semantics")
        ):
            raise RuntimeError("multivariable v5 registry entry lacks identity/semantics")
        signature = {**_TYPE_SIGNATURES, **_SIGNATURES}.get(entry["name"])
        if entry["cd"] == "multivar5" and signature is not None:
            args, result = signature
            if entry.get("arguments") != list(args) or entry.get("result") != result:
                raise RuntimeError(
                    "multivariable v5 registry signature differs from implementation"
                )
        if entry["cdbase"] == STANDARD and entry.get("arity") != _STANDARD_ARITIES.get(
            (entry["cd"], entry["name"])
        ):
            raise RuntimeError("multivariable v5 standard signature differs from implementation")
    actual = {(x["cdbase"], x["cd"], x["name"]) for x in rows}
    if (
        data.get("schema_version") != "pals.typed-multivariable-registry.v5"
        or data.get("profile_id") != PROFILE_ID
        or actual != expected
        or len(actual) != len(rows)
    ):
        raise RuntimeError("multivariable v5 registry does not match the closed grammar")
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
            or _symbol(node[0]) not in {(CDBASE, "typed5", "forall"), (CDBASE, "typed5", "exists")}
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
            or _symbol(node[0]) != (CDBASE, "typed5", "type")
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
        if _symbol(node) == (CDBASE, "multivar5", "Nat"):
            return NAT
        if _symbol(node) == (CDBASE, "multivar5", "Real"):
            return REAL
        if _symbol(node) == (CDBASE, "multivar5", "RealFunction"):
            return Sort("real_function")
        _fail("invalid atomic declaration sort")
    if _tag(node) != "OMA":
        _fail("invalid declaration sort")
    base, cd, ty = _symbol(node[0])
    args = list(node)[1:]
    if (base, cd) != (CDBASE, "multivar5") or ty not in _TYPE_SIGNATURES:
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
        dimensions = [_bound(args[p], env, "nat") for p in positions]
        dimensions += [""] * (3 - len(dimensions))
        return Sort(kind.lower(), domain=dimensions[0], codomain=dimensions[1], index=dimensions[2])

    for arg, spec in zip(args, signature, strict=True):
        if spec == "Dim":
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
    if (base, cd) != (CDBASE, "multivar5") or op not in _SIGNATURES:
        _fail("unknown value operator")
    signature, result = _SIGNATURES[op]
    return _apply_signature(args, signature, result, env)


def canonicalize_typed_multivariable_v5_openmath_xml(xml: str) -> str:
    """Validate closed dependent types before alpha-aware canonicalization."""
    if not isinstance(xml, str) or len(xml.encode("utf-8")) > MAX_BYTES:
        _fail("XML byte bound exceeded")
    root = validate_openmath_xml(xml)
    _shape(root)
    _same(_infer(root[0], {}), PROP)
    return cast(str, _canonicalize_openmath_v4_root(root))


def validate_canonical_typed_multivariable_v5_openmath_xml(xml: str) -> str:
    """Accept exact canonical bytes only."""
    canonical = canonicalize_typed_multivariable_v5_openmath_xml(xml)
    if canonical != xml:
        _fail("input is not exact canonical XML")
    return canonical
