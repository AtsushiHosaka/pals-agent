"""Closed planar Green/Gauss authoring grammar; all points are real ordered pairs.

No runtime routing or publication capability is registered.
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

PROFILE_ID = "typed-vector-calculus-v6"
CDBASE = "urn:pals:openmath:typed-vector-calculus:v6"
STANDARD = "http://www.openmath.org/cd"
MAX_BYTES = 65_536
MAX_NODES = 4096
MAX_DEPTH = 64


@dataclass(frozen=True)
class Sort:
    kind: str


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
_TYPE_SIGNATURES: dict[str, tuple[tuple[str, ...], str]] = {}
_TYPE_NAMES = {"Set", "RealFunction", "Dual", "ScalarFunction", "Nat", "DualField", "Real", "Point"}
_SIGNATURES: dict[str, tuple[tuple[str, ...], str]] = {
    "real_nat": (("Nat",), "Real"),
    "real_add": (("Real", "Real"), "Real"),
    "real_sub": (("Real", "Real"), "Real"),
    "real_mul": (("Real", "Real"), "Real"),
    "point": (("Real", "Real"), "Point"),
    "fst": (("Point",), "Real"),
    "snd": (("Point",), "Real"),
    "zero_dual": ((), "Dual"),
    "zero_function": ((), "ScalarFunction"),
    "apply": (("ScalarFunction", "Point"), "Real"),
    "dual_apply": (("Dual", "Point"), "Real"),
    "field_apply": (("DualField", "Point"), "Dual"),
    "fderiv_field": (("ScalarFunction",), "DualField"),
    "divergence": (("DualField", "DualField"), "ScalarFunction"),
    "curl": (("DualField", "DualField"), "ScalarFunction"),
    "closed_rectangle": (("Point", "Point"), "Set"),
    "open_rectangle": (("Point", "Point"), "Set"),
    "set_difference": (("Set", "Set"), "Set"),
    "member": (("Point", "Set"), "Prop"),
    "countable": (("Set",), "Prop"),
    "has_fderiv": (("ScalarFunction", "Point", "Dual"), "Prop"),
    "continuous_on": (("ScalarFunction", "Set"), "Prop"),
    "cont_diff_one": (("ScalarFunction",), "Prop"),
    "integrable_on": (("ScalarFunction", "Set"), "Prop"),
    "set_integral": (("ScalarFunction", "Set"), "Real"),
    "horizontal_slice": (("ScalarFunction", "Real"), "RealFunction"),
    "vertical_slice": (("ScalarFunction", "Real"), "RealFunction"),
    "interval_integral": (("RealFunction", "Real", "Real"), "Real"),
    "affine": (("Real", "Real", "Real"), "ScalarFunction"),
    "boundary_flux": (("ScalarFunction", "ScalarFunction", "Point", "Point"), "Real"),
    "boundary_circulation": (("ScalarFunction", "ScalarFunction", "Point", "Point"), "Real"),
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
    raise MathXMLValidationError("typed-vector-calculus-v6: " + message)


def _symbol(node: ET.Element) -> tuple[str, str, str]:
    return (node.get("cdbase", ""), node.get("cd", ""), node.get("name", ""))


def _registry() -> frozenset[tuple[str, str, str]]:
    data = json.loads(
        resources.files("pals_agent.content_dictionaries")
        .joinpath("typed-vector-calculus-v6-registry.json")
        .read_text(encoding="utf-8")
    )
    expected = {(CDBASE, "typed6", x) for x in ("forall", "exists", "type")}
    expected |= {(CDBASE, "vector6", x) for x in _TYPE_NAMES | set(_LA_ARITIES)}
    expected |= {(STANDARD, cd, name) for cd, name in _STANDARD_ARITIES}
    if not isinstance(data, dict) or set(data) != {"schema_version", "profile_id", "symbols"}:
        raise RuntimeError("vector calculus v6 registry header is malformed")
    rows = data.get("symbols", [])
    if not isinstance(rows, list):
        raise RuntimeError("vector calculus v6 registry symbols are malformed")
    for entry in rows:
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(k), str) and entry[k]
            for k in ("cdbase", "cd", "name", "semantics")
        ):
            raise RuntimeError("vector calculus v6 registry entry lacks identity/semantics")
        signature = {**_TYPE_SIGNATURES, **_SIGNATURES}.get(entry["name"])
        if entry["cd"] == "vector6" and signature is not None:
            args, result = signature
            if entry.get("arguments") != list(args) or entry.get("result") != result:
                raise RuntimeError(
                    "vector calculus v6 registry signature differs from implementation"
                )
        if entry["cdbase"] == STANDARD and entry.get("arity") != _STANDARD_ARITIES.get(
            (entry["cd"], entry["name"])
        ):
            raise RuntimeError("vector calculus v6 standard signature differs from implementation")
    actual = {(x["cdbase"], x["cd"], x["name"]) for x in rows}
    if (
        data.get("schema_version") != "pals.typed-vector-calculus-registry.v6"
        or data.get("profile_id") != PROFILE_ID
        or actual != expected
        or len(actual) != len(rows)
    ):
        raise RuntimeError("vector calculus v6 registry does not match the closed grammar")
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
            or _symbol(node[0]) not in {(CDBASE, "typed6", "forall"), (CDBASE, "typed6", "exists")}
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
            or _symbol(node[0]) != (CDBASE, "typed6", "type")
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


def _sort(node: ET.Element, name: str, env: dict[str, Sort]) -> Sort:
    if (
        _tag(node) != "OMS"
        or _symbol(node)[:2] != (CDBASE, "vector6")
        or node.get("name") not in _TYPE_NAMES
    ):
        _fail("declaration requires a registered atomic sort")
    return Sort(node.get("name", "").lower())


def _apply_signature(
    args: list[ET.Element], signature: tuple[str, ...], result: str, env: dict[str, Sort]
) -> Sort:
    if len(args) != len(signature):
        _fail("operator arity mismatch")
    for arg, expected in zip(args, signature, strict=True):
        _same(_infer(arg, env), Sort(expected.lower()))
    return Sort(result.lower())


def _infer(node: ET.Element, env: dict[str, Sort]) -> Sort:
    tag = _tag(node)
    if tag == "OMV":
        name = node.get("name", "")
        if name not in env:
            _fail(f"unbound variable {name}")
        return env[name]
    if tag == "OMI":
        return NAT
    if tag == "OMS" and _symbol(node)[:2] == (CDBASE, "vector6"):
        constant_signature = _SIGNATURES.get(node.get("name", ""))
        if constant_signature is not None and not constant_signature[0]:
            return Sort(constant_signature[1].lower())
        _fail("only registered nullary values can occur as standalone symbols")
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
    if (base, cd) != (CDBASE, "vector6") or op not in _SIGNATURES:
        _fail("unknown value operator")
    signature, result = _SIGNATURES[op]
    return _apply_signature(args, signature, result, env)


def canonicalize_typed_vector_calculus_v6_openmath_xml(xml: str) -> str:
    """Validate fixed planar sorts before alpha-aware canonicalization."""
    if not isinstance(xml, str) or len(xml.encode("utf-8")) > MAX_BYTES:
        _fail("XML byte bound exceeded")
    root = validate_openmath_xml(xml)
    _shape(root)
    _same(_infer(root[0], {}), PROP)
    return cast(str, _canonicalize_openmath_v4_root(root))


def validate_canonical_typed_vector_calculus_v6_openmath_xml(xml: str) -> str:
    """Accept exact canonical bytes only."""
    canonical = canonicalize_typed_vector_calculus_v6_openmath_xml(xml)
    if canonical != xml:
        _fail("input is not exact canonical XML")
    return canonical
