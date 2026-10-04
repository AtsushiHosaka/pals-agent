"""Closed, carrier-checked finite-dimensional linear algebra OpenMath profile.

A FiniteDimensionalSpace(K) declaration includes AddCommGroup, Module K, and
FiniteDimensional K assumptions. This authoring profile does not register runtime
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

PROFILE_ID = "typed-linear-algebra-v2"
CDBASE = "urn:pals:openmath:typed-linear-algebra:v2"
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
_TYPE_NAMES = {
    "Field",
    "FiniteDimensionalSpace",
    "LinearMap",
    "Subspace",
    "Scalar",
    "Vector",
    "Nat",
    "VectorFamily",
    "ScalarFamily",
    "Basis",
}
_LA_ARITIES = {
    "dim": 2,
    "sub_dim": 3,
    "sub_top": 2,
    "sub_bot": 2,
    "sub_sup": 4,
    "sub_inf": 4,
    "sub_le": 4,
    "sub_lt": 4,
    "kernel": 4,
    "range": 4,
    "injective": 4,
    "surjective": 4,
    "linear_comp": 6,
    "linear_sub": 5,
    "linear_smul": 5,
    "linear_id": 2,
    "det": 3,
    "eigenspace": 4,
    "family_span": 4,
    "independent": 4,
    "basis_vectors": 4,
    "scalar_family_injective": 3,
    "eigenfamily": 6,
    "has_eigenbasis": 5,
    "scalar_zero": 1,
    "scalar_mul": 3,
    "scalar_pow": 3,
}
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
    raise MathXMLValidationError("typed-linear-algebra-v2: " + message)


def _symbol(node: ET.Element) -> tuple[str, str, str]:
    return (node.get("cdbase", ""), node.get("cd", ""), node.get("name", ""))


def _registry() -> frozenset[tuple[str, str, str]]:
    data = json.loads(
        resources.files("pals_agent.content_dictionaries")
        .joinpath("typed-linear-algebra-v2-registry.json")
        .read_text(encoding="utf-8")
    )
    expected = {(CDBASE, "typed1", x) for x in ("forall", "exists", "type")}
    expected |= {(CDBASE, "la2", x) for x in _TYPE_NAMES | set(_LA_ARITIES)}
    expected |= {(STANDARD, cd, name) for cd, name in _STANDARD_ARITIES}
    rows = data.get("symbols", [])
    actual = {(x["cdbase"], x["cd"], x["name"]) for x in rows}
    if (
        data.get("schema_version") != "pals.typed-linear-algebra-registry.v2"
        or data.get("profile_id") != PROFILE_ID
        or actual != expected
        or len(actual) != len(rows)
    ):
        raise RuntimeError("linear algebra v2 registry does not match the closed grammar")
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


def _carriers(args: list[ET.Element], env: dict[str, Sort], count: int) -> tuple[str, ...]:
    field = _bound(args[0], env, "field")
    spaces = tuple(_bound(a, env, "space") for a in args[1 : count + 1])
    for space in spaces:
        _same(env[space], Sort("space", field, space))
    return (field, *spaces)


def _sort(node: ET.Element, name: str, env: dict[str, Sort]) -> Sort:
    if _tag(node) == "OMS":
        if _symbol(node) == (CDBASE, "la2", "Field"):
            return Sort("field", name)
        if _symbol(node) == (CDBASE, "la2", "Nat"):
            return NAT
        _fail("invalid atomic declaration sort")
    if _tag(node) != "OMA":
        _fail("invalid declaration sort")
    base, cd, ty = _symbol(node[0])
    args = list(node)[1:]
    arity = {
        "FiniteDimensionalSpace": 1,
        "Scalar": 1,
        "Vector": 2,
        "Subspace": 2,
        "LinearMap": 3,
        "VectorFamily": 3,
        "ScalarFamily": 2,
        "Basis": 3,
    }
    if (base, cd) != (CDBASE, "la2") or ty not in arity or len(args) != arity[ty]:
        _fail("unknown declaration sort or invalid type arity")
    field = _bound(args[0], env, "field")
    if ty == "FiniteDimensionalSpace":
        return Sort("space", field, name)
    if ty == "Scalar":
        return Sort("scalar", field)
    if ty == "ScalarFamily":
        return Sort("scalar_family", field, index=_bound(args[1], env, "nat"))
    _, space = _carriers(args, env, 1)
    if ty in {"Vector", "Subspace"}:
        return Sort("vector" if ty == "Vector" else "subspace", field, space)
    if ty == "LinearMap":
        _, _, target = _carriers(args, env, 2)
        return Sort("linear", field, space, target)
    return Sort(
        "basis" if ty == "Basis" else "family", field, space, index=_bound(args[2], env, "nat")
    )


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
        if op in {"eq", "neq"}:
            _same(types[0], types[1])
            if types[0].kind in {"field", "space", "prop"}:
                _fail("carrier/proposition equality is outside this profile")
            return PROP
        for ty in types:
            _same(ty, NAT)
        return NAT if cd == "arith1" else PROP
    if (base, cd) != (CDBASE, "la2") or op not in _LA_ARITIES or len(args) != _LA_ARITIES[op]:
        _fail("unknown value operator or invalid arity")
    field = _bound(args[0], env, "field")
    scalar = Sort("scalar", field)

    def check(i: int, ty: Sort) -> None:
        _same(_infer(args[i], env), ty)

    if op == "scalar_zero":
        return scalar
    if op in {"scalar_mul", "scalar_pow"}:
        check(1, scalar)
        check(2, scalar if op == "scalar_mul" else NAT)
        return scalar
    if op == "scalar_family_injective":
        n = _bound(args[1], env, "nat")
        check(2, Sort("scalar_family", field, index=n))
        return PROP
    _, space = _carriers(args, env, 1)
    sub = Sort("subspace", field, space)
    endo = Sort("linear", field, space, space)
    if op in {"dim", "sub_top", "sub_bot", "linear_id"}:
        return {"dim": NAT, "sub_top": sub, "sub_bot": sub, "linear_id": endo}[op]
    if op == "sub_dim":
        check(2, sub)
        return NAT
    if op in {"sub_sup", "sub_inf", "sub_le", "sub_lt"}:
        check(2, sub)
        check(3, sub)
        return PROP if op in {"sub_le", "sub_lt"} else sub
    if op in {"det", "eigenspace"}:
        check(2, endo)
        if op == "eigenspace":
            check(3, scalar)
        return scalar if op == "det" else sub
    if op in {"family_span", "independent", "basis_vectors", "eigenfamily", "has_eigenbasis"}:
        n = _bound(args[2], env, "nat")
        family = Sort("family", field, space, index=n)
        if op in {"eigenfamily", "has_eigenbasis"}:
            check(3, endo)
            check(4, Sort("scalar_family", field, index=n))
            if op == "eigenfamily":
                check(5, family)
            return PROP
        check(3, Sort("basis", field, space, index=n) if op == "basis_vectors" else family)
        return {"family_span": sub, "independent": PROP, "basis_vectors": family}[op]
    _, _, target = _carriers(args, env, 2)
    linear = Sort("linear", field, space, target)
    if op in {"kernel", "range", "injective", "surjective"}:
        check(3, linear)
        return (
            PROP
            if op in {"injective", "surjective"}
            else Sort("subspace", field, space if op == "kernel" else target)
        )
    if op == "linear_sub":
        check(3, linear)
        check(4, linear)
        return linear
    if op == "linear_smul":
        check(3, scalar)
        check(4, linear)
        return linear
    if op == "linear_comp":
        _, _, _, final = _carriers(args, env, 3)
        check(4, linear)
        check(5, Sort("linear", field, target, final))
        return Sort("linear", field, space, final)
    _fail("unhandled operator")


def canonicalize_typed_linear_algebra_v2_openmath_xml(xml: str) -> str:
    """Validate the closed profile before applying alpha-aware canonicalization."""
    if not isinstance(xml, str) or len(xml.encode("utf-8")) > MAX_BYTES:
        _fail("XML byte bound exceeded")
    root = validate_openmath_xml(xml)
    _shape(root)
    _same(_infer(root[0], {}), PROP)
    return cast(str, _canonicalize_openmath_v4_root(root))


def validate_canonical_typed_linear_algebra_v2_openmath_xml(xml: str) -> str:
    """Accept only exact canonical profile bytes."""
    canonical = canonicalize_typed_linear_algebra_v2_openmath_xml(xml)
    if canonical != xml:
        _fail("input is not exact canonical XML")
    return canonical
