"""Closed arbitrary-field, arbitrary-dimension matrix authoring profile.

Field declares a Lean Field. Matrix(K,m,n) is Matrix (Fin m) (Fin n) K.
Every dimension is a bound natural; zero dimensions are allowed.
This authoring profile does not register runtime
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

PROFILE_ID = "typed-linear-algebra-v4"
CDBASE = "urn:pals:openmath:typed-linear-algebra:v4"
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
_TYPE_SIGNATURES = {
    "Scalar": (("Field",), "Scalar@0"),
    "Matrix": (("Field", "IndexSize", "IndexSize"), "Mat@0,1,2"),
    "Vector": (("Field", "IndexSize"), "Vec@0,1"),
    "Polynomial": (("Field",), "Poly@0"),
}
_TYPE_NAMES = {"Field", "Nat"} | set(_TYPE_SIGNATURES)
_SIGNATURES: dict[str, tuple[tuple[str, ...], str]] = {
    "scalar_nat": (("Field", "Nat"), "Scalar@0"),
    "scalar_neg": (("Field", "Scalar@0"), "Scalar@0"),
    "scalar_inv": (("Field", "Scalar@0"), "Scalar@0"),
    "scalar_mul": (("Field", "Scalar@0", "Scalar@0"), "Scalar@0"),
    "scalar_pow": (("Field", "Scalar@0", "Nat"), "Scalar@0"),
    "zero": (("Field", "IndexSize", "IndexSize"), "Mat@0,1,2"),
    "identity": (("Field", "IndexSize"), "Mat@0,1,1"),
    "add": (("Field", "IndexSize", "IndexSize", "Mat@0,1,2", "Mat@0,1,2"), "Mat@0,1,2"),
    "smul": (("Field", "IndexSize", "IndexSize", "Scalar@0", "Mat@0,1,2"), "Mat@0,1,2"),
    "mul": (
        ("Field", "IndexSize", "IndexSize", "IndexSize", "Mat@0,1,2", "Mat@0,2,3"),
        "Mat@0,1,3",
    ),
    "transpose": (("Field", "IndexSize", "IndexSize", "Mat@0,1,2"), "Mat@0,2,1"),
    "pow": (("Field", "IndexSize", "Mat@0,1,1", "Nat"), "Mat@0,1,1"),
    "inv": (("Field", "IndexSize", "Mat@0,1,1"), "Mat@0,1,1"),
    "adjugate": (("Field", "IndexSize", "Mat@0,1,1"), "Mat@0,1,1"),
    "det": (("Field", "IndexSize", "Mat@0,1,1"), "Scalar@0"),
    "trace": (("Field", "IndexSize", "Mat@0,1,1"), "Scalar@0"),
    "rank": (("Field", "IndexSize", "IndexSize", "Mat@0,1,2"), "Nat"),
    "is_unit": (("Field", "IndexSize", "Mat@0,1,1"), "Prop"),
    "nilpotent": (("Field", "IndexSize", "Mat@0,1,1"), "Prop"),
    "upper_triangular": (("Field", "IndexSize", "Mat@0,1,1"), "Prop"),
    "diagonal": (("Field", "IndexSize", "Vec@0,1"), "Mat@0,1,1"),
    "diag_entries": (("Field", "IndexSize", "Mat@0,1,1"), "Vec@0,1"),
    "vec_product": (("Field", "IndexSize", "Vec@0,1"), "Scalar@0"),
    "count_nonzero": (("Field", "IndexSize", "Vec@0,1"), "Nat"),
    "mul_vec": (("Field", "IndexSize", "IndexSize", "Mat@0,1,2", "Vec@0,2"), "Vec@0,1"),
    "vec_smul": (("Field", "IndexSize", "Scalar@0", "Vec@0,1"), "Vec@0,1"),
    "cramer": (("Field", "IndexSize", "Mat@0,1,1", "Vec@0,1"), "Vec@0,1"),
    "charpoly": (("Field", "IndexSize", "Mat@0,1,1"), "Poly@0"),
    "poly_X": (("Field",), "Poly@0"),
    "poly_pow": (("Field", "Poly@0", "Nat"), "Poly@0"),
    "poly_coeff": (("Field", "Poly@0", "Nat"), "Scalar@0"),
    "poly_next_coeff": (("Field", "Poly@0"), "Scalar@0"),
    "poly_degree": (("Field", "Poly@0"), "Nat"),
    "poly_monic": (("Field", "Poly@0"), "Prop"),
    "poly_eval": (("Field", "Poly@0", "Scalar@0"), "Scalar@0"),
    "matrix_eval": (("Field", "IndexSize", "Mat@0,1,1", "Poly@0"), "Mat@0,1,1"),
    "linear_factor_product": (("Field", "IndexSize", "Vec@0,1"), "Poly@0"),
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
    raise MathXMLValidationError("typed-linear-algebra-v4: " + message)


def _symbol(node: ET.Element) -> tuple[str, str, str]:
    return (node.get("cdbase", ""), node.get("cd", ""), node.get("name", ""))


def _registry() -> frozenset[tuple[str, str, str]]:
    data = json.loads(
        resources.files("pals_agent.content_dictionaries")
        .joinpath("typed-linear-algebra-v4-registry.json")
        .read_text(encoding="utf-8")
    )
    expected = {(CDBASE, "typed1", x) for x in ("forall", "exists", "type")}
    expected |= {(CDBASE, "la4", x) for x in _TYPE_NAMES | set(_LA_ARITIES)}
    expected |= {(STANDARD, cd, name) for cd, name in _STANDARD_ARITIES}
    rows = data.get("symbols", [])
    actual = {(x["cdbase"], x["cd"], x["name"]) for x in rows}
    if (
        data.get("schema_version") != "pals.typed-linear-algebra-registry.v4"
        or data.get("profile_id") != PROFILE_ID
        or actual != expected
        or len(actual) != len(rows)
    ):
        raise RuntimeError("linear algebra v4 registry does not match the closed grammar")
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
            or _symbol(node[0]) not in {(CDBASE, "typed1", "forall"), (CDBASE, "typed1", "exists")}
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
            or _symbol(node[0]) != (CDBASE, "typed1", "type")
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
        if _symbol(node) == (CDBASE, "la4", "Field"):
            return Sort("field", field=name)
        if _symbol(node) == (CDBASE, "la4", "Nat"):
            return NAT
        _fail("invalid atomic declaration sort")
    if _tag(node) != "OMA":
        _fail("invalid declaration sort")
    base, cd, ty = _symbol(node[0])
    args = list(node)[1:]
    if (base, cd) != (CDBASE, "la4") or ty not in _TYPE_SIGNATURES:
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
            return {"Nat": NAT, "Prop": PROP}[kind]
        positions = [int(x) for x in refs.split(",")]
        field = _bound(args[positions[0]], env, "field")
        dims = [_bound(args[i], env, "nat") for i in positions[1:]]
        return Sort(
            {"Scalar": "scalar", "Mat": "matrix", "Vec": "vector", "Poly": "polynomial"}[kind],
            field=field,
            domain=dims[0] if dims else "",
            codomain=dims[1] if len(dims) > 1 else "",
        )

    for arg, spec in zip(args, signature, strict=True):
        if spec == "Field":
            _bound(arg, env, "field")
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
            if types[0].kind in {"field", "prop"}:
                _fail("carrier/proposition equality is outside this profile")
            return PROP
        if types[0] != NAT and not (cd == "arith1" and types[0].kind == "scalar"):
            _fail("orders require naturals; addition requires matching naturals or scalars")
        return types[0] if cd == "arith1" else PROP
    if (base, cd) != (CDBASE, "la4") or op not in _SIGNATURES:
        _fail("unknown value operator")
    signature, result = _SIGNATURES[op]
    return _apply_signature(args, signature, result, env)


def canonicalize_typed_linear_algebra_v4_openmath_xml(xml: str) -> str:
    """Validate closed dependent types before alpha-aware canonicalization."""
    if not isinstance(xml, str) or len(xml.encode("utf-8")) > MAX_BYTES:
        _fail("XML byte bound exceeded")
    root = validate_openmath_xml(xml)
    _shape(root)
    _same(_infer(root[0], {}), PROP)
    return cast(str, _canonicalize_openmath_v4_root(root))


def validate_canonical_typed_linear_algebra_v4_openmath_xml(xml: str) -> str:
    """Accept exact canonical bytes only."""
    canonical = canonicalize_typed_linear_algebra_v4_openmath_xml(xml)
    if canonical != xml:
        _fail("input is not exact canonical XML")
    return canonical
