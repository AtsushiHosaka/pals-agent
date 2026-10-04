"""Closed carrier-safe localization, chain condition, Hom and tensor language.

This profile is independent of all v1/v2 registries and validators.
Validation establishes syntax and dependent sorts, not mathematical truth.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Sized
from dataclasses import dataclass
from importlib import resources

from .openmath import (
    OPENMATH_NAMESPACE,
    MathXMLValidationError,
    _canonicalize_openmath_v4_root,
    _local_name,
    validate_openmath_xml,
)

PROFILE_ID = "typed-commalg-v3"
CDBASE = "urn:pals:openmath:typed-commalg:v3"
STANDARD = "http://www.openmath.org/cd"
CD = "module3"


@dataclass(frozen=True)
class Sort:
    kind: str
    ring: tuple[object, ...] = ()
    carrier: tuple[object, ...] = ()
    target: tuple[object, ...] = ()
    local: bool = False


PROP = Sort("prop")
_ATTRS = {
    "OMOBJ": {"version"},
    "OMS": {"cd", "cdbase", "name"},
    "OMV": {"name"},
    "OMA": set(),
    "OMBIND": set(),
    "OMBVAR": set(),
    "OMATTR": set(),
    "OMATP": set(),
}
_EXPECTED_GROUPS = {
    (CDBASE, "typed1"): "forall exists type",
    (CDBASE, CD): (
        "CommRing LocalRing Module Ideal Submodule LinearMap ideal_bot maximal_ideal "
        "ideal_jacobson ideal_le quotient submodule_carrier tensor submodule_bot "
        "submodule_top submodule_le submodule_sup submodule_inf finite fg flat module_zero "
        "ideal_smul quotient_map inclusion linear_id linear_zero kernel range injective "
        "surjective compose exact map comap tensor_map_left "
        "Submonoid noetherian artinian finite_length scalar_module product hom localized_module "
        "localization_map localized_map localized_submodule hom_precompose hom_postcompose "
        "tensor_lift tensor_curry bilinear_postcompose tensor_comm tensor_assoc"
    ),
    (STANDARD, "logic1"): "and or implies not",
    (STANDARD, "relation1"): "eq neq",
}
_EXPECTED_SYMBOLS = frozenset(
    (base, cd, name) for (base, cd), names in _EXPECTED_GROUPS.items() for name in names.split()
)


def _validate_registry(payload: object) -> frozenset[tuple[str, str, str]]:
    """The registry documents a fixed language; it cannot extend the parser."""
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "profile_id", "cdbases", "symbols"}
        or payload["schema_version"] != "pals.typed-commalg-v3-registry.v1"
        or payload["profile_id"] != PROFILE_ID
        or payload["cdbases"] != {"typed": CDBASE, "standard": STANDARD}
        or not isinstance(payload["symbols"], list)
    ):
        raise RuntimeError("Invalid commalg v3 registry header")
    symbols = []
    for s in payload["symbols"]:
        if (
            not isinstance(s, dict)
            or set(s) != {"cdbase", "cd", "name", "signature", "lean_meaning"}
            or any(not isinstance(v, str) or not v.strip() for v in s.values())
        ):
            raise RuntimeError("Invalid commalg v3 symbol metadata")
        symbols.append((s["cdbase"], s["cd"], s["name"]))
    if len(symbols) != len(_EXPECTED_SYMBOLS) or frozenset(symbols) != _EXPECTED_SYMBOLS:
        raise RuntimeError("Commalg v3 registry symbol drift")
    return frozenset(symbols)


_REGISTRY = json.loads(
    resources.files("pals_agent.content_dictionaries")
    .joinpath("typed-commalg-v3-registry.json")
    .read_text(encoding="utf-8")
)
_SYMBOLS = _validate_registry(_REGISTRY)


def _fail(message: str) -> None:
    raise MathXMLValidationError("typed-commalg-v3: " + message)


def _symbol(e: ET.Element) -> tuple[str, str, str]:
    if _local_name(e) != "OMS":
        _fail("operator must be OMS")
    result = (e.get("cdbase", ""), e.get("cd", ""), e.get("name", ""))
    if result not in _SYMBOLS:
        _fail("unregistered symbol or cdbase")
    return result


def _term(e: ET.Element) -> tuple[object, ...]:
    """Structural term identity; quotient/submodule carriers retain exact operands."""
    if _local_name(e) == "OMV":
        return ("var", e.get("name"))
    return (_local_name(e), tuple(sorted(e.attrib.items())), tuple(_term(c) for c in e))


def _arity(args: Sized, n: int) -> None:
    if len(args) != n:
        _fail(f"operator arity must be {n}, received {len(args)}")


def _same(actual: Sort, expected: Sort) -> None:
    if actual != expected:
        _fail(f"dependent sort mismatch: expected {expected}, received {actual}")


def _ring(s: Sort) -> tuple[object, ...]:
    if s.kind != "ring" or not s.ring:
        _fail("expected a bound commutative ring")
    return s.ring


def _module(s: Sort, ring: tuple[object, ...]) -> tuple[object, ...]:
    if s.kind != "module" or s.ring != ring or not s.carrier:
        _fail("module belongs to a different ring or is not a module")
    return s.carrier


def _sort(e: ET.Element, env: dict[str, Sort]) -> Sort:
    if _local_name(e) == "OMS":
        _, cd, name = _symbol(e)
        if cd == CD and name in {"CommRing", "LocalRing"}:
            return Sort("ring", local=name == "LocalRing")
        _fail("invalid atomic binder sort")
    if _local_name(e) != "OMA" or not len(e):
        _fail("invalid dependent binder sort")
    base, cd, name = _symbol(e[0])
    if (base, cd) != (CDBASE, CD):
        _fail("invalid dependent binder constructor")
    args = list(e)[1:]
    if name not in {"Module", "Ideal", "Submodule", "LinearMap", "Submonoid"}:
        _fail("unknown binder sort; quotient carriers are constructed terms")
    _arity(args, {"Module": 1, "Ideal": 1, "Submodule": 2, "LinearMap": 3, "Submonoid": 1}[name])
    sorts = [_infer(a, env) for a in args]
    r = _ring(sorts[0])
    if name == "Module":
        return Sort("module", r)
    if name == "Submonoid":
        return Sort("submonoid", r)
    if name == "Ideal":
        return Sort("ideal", r)
    m = _module(sorts[1], r)
    if name == "Submodule":
        return Sort("submodule", r, m)
    return Sort("map", r, m, _module(sorts[2], r))


def _infer(e: ET.Element, env: dict[str, Sort]) -> Sort:
    tag = _local_name(e)
    if tag == "OMV":
        if e.get("name") not in env:
            _fail("unbound variable")
        return env[e.attrib["name"]]
    if tag == "OMBIND":
        _arity(list(e), 3)
        if _symbol(e[0]) not in {(CDBASE, "typed1", "forall"), (CDBASE, "typed1", "exists")}:
            _fail("invalid quantifier")
        if _local_name(e[1]) != "OMBVAR" or not 1 <= len(e[1]) <= 256:
            _fail("binder requires 1..256 declarations")
        scope = dict(env)
        for decl in e[1]:
            if _local_name(decl) != "OMATTR" or len(decl) != 2:
                _fail("binder declaration must be OMATTR")
            pair, variable = decl
            if (
                _local_name(pair) != "OMATP"
                or len(pair) != 2
                or _symbol(pair[0]) != (CDBASE, "typed1", "type")
            ):
                _fail("binder needs one exact type annotation")
            if _local_name(variable) != "OMV" or not variable.get("name"):
                _fail("declaration variable required")
            name = variable.attrib["name"]
            if name in scope:
                _fail("shadowed or duplicate binder")
            s = _sort(pair[1], scope)
            if s.kind == "ring":
                s = Sort("ring", ("var", name), local=s.local)
            elif s.kind == "module":
                s = Sort("module", s.ring, ("var", name))
            scope[name] = s
        _same(_infer(e[2], scope), PROP)
        return PROP
    if tag != "OMA" or not len(e):
        _fail("expression must be a variable, quantified proposition or application")
    base, cd, name = _symbol(e[0])
    args = list(e)[1:]
    ss = [_infer(a, env) for a in args]
    if (base, cd) == (STANDARD, "relation1"):
        _arity(ss, 2)
        if ss[0].kind in {"ring", "module", "prop"}:
            _fail("equality is on mathematical values, not carrier declarations or propositions")
        _same(ss[1], ss[0])
        return PROP
    if (base, cd) == (STANDARD, "logic1"):
        if name in {"and", "or"}:
            if not 2 <= len(ss) <= 32:
                _fail("and/or arity outside 2..32")
        else:
            _arity(ss, 1 if name == "not" else 2)
        for s in ss:
            _same(s, PROP)
        return PROP
    if (base, cd) != (CDBASE, CD):
        _fail("not a commalg v3 operator")
    arities = {
        "noetherian": 2,
        "artinian": 2,
        "finite_length": 2,
        "scalar_module": 1,
        "product": 3,
        "hom": 3,
        "localized_module": 3,
        "localization_map": 3,
        "localized_map": 5,
        "localized_submodule": 4,
        "hom_precompose": 5,
        "hom_postcompose": 5,
        "tensor_lift": 5,
        "tensor_curry": 5,
        "bilinear_postcompose": 7,
        "tensor_comm": 3,
        "tensor_assoc": 4,
        "ideal_bot": 1,
        "maximal_ideal": 1,
        "ideal_jacobson": 2,
        "ideal_le": 3,
        "quotient": 3,
        "submodule_carrier": 3,
        "tensor": 3,
        "submodule_bot": 2,
        "submodule_top": 2,
        "submodule_le": 4,
        "submodule_sup": 4,
        "submodule_inf": 4,
        "finite": 2,
        "fg": 3,
        "flat": 2,
        "module_zero": 2,
        "ideal_smul": 4,
        "quotient_map": 3,
        "inclusion": 3,
        "linear_id": 2,
        "linear_zero": 3,
        "kernel": 4,
        "range": 4,
        "injective": 4,
        "surjective": 4,
        "compose": 6,
        "exact": 6,
        "map": 5,
        "comap": 5,
        "tensor_map_left": 5,
    }
    if name not in arities:
        _fail("sort symbol used as term or unknown operator")
    _arity(ss, arities[name])
    r = _ring(ss[0])
    if name in {"ideal_bot", "maximal_ideal"}:
        if name == "maximal_ideal" and not ss[0].local:
            _fail("maximal_ideal requires an explicitly bound LocalRing")
        return Sort("ideal", r)
    if name in {"ideal_jacobson", "ideal_le"}:
        for s in ss[1:]:
            _same(s, Sort("ideal", r))
        return PROP if name == "ideal_le" else Sort("ideal", r)
    if name == "scalar_module":
        return Sort("module", r, ("scalar", r))
    m = _module(ss[1], r)
    if name in {"localized_module", "localization_map", "localized_submodule"}:
        _same(ss[2], Sort("submonoid", r))
        lm = ("localized", r, m, _term(args[2]))
        if name == "localized_module":
            return Sort("module", r, lm)
        if name == "localization_map":
            return Sort("map", r, m, lm)
        _same(ss[3], Sort("submodule", r, m))
        return Sort("submodule", r, lm)
    sub = Sort("submodule", r, m)
    if name in {"quotient", "submodule_carrier", "quotient_map", "inclusion"}:
        _same(ss[2], sub)
        constructor = "quotient" if name in {"quotient", "quotient_map"} else "submodule_carrier"
        carrier = (constructor, r, m, _term(args[2]))
        if name in {"quotient", "submodule_carrier"}:
            return Sort("module", r, carrier)
        if name == "quotient_map":
            return Sort("map", r, m, carrier)
        return Sort("map", r, carrier, m)
    if name in {"finite", "flat", "module_zero", "noetherian", "artinian", "finite_length"}:
        return PROP
    if name == "fg":
        _same(ss[2], sub)
        return PROP
    if name == "ideal_smul":
        _same(ss[2], Sort("ideal", r))
        _same(ss[3], sub)
        return sub
    if name in {"submodule_bot", "submodule_top"}:
        return sub
    if name in {"submodule_le", "submodule_sup", "submodule_inf"}:
        _same(ss[2], sub)
        _same(ss[3], sub)
        return PROP if name == "submodule_le" else sub
    if name == "linear_id":
        return Sort("map", r, m, m)
    n = _module(ss[2], r)
    if name in {"tensor", "product", "hom"}:
        return Sort("module", r, (name, r, m, n))
    if name == "tensor_comm":
        return Sort("map", r, ("tensor", r, m, n), ("tensor", r, n, m))
    if name == "localized_map":
        _same(ss[3], Sort("submonoid", r))
        _same(ss[4], Sort("map", r, m, n))
        subset_term = _term(args[3])
        return Sort("map", r, ("localized", r, m, subset_term), ("localized", r, n, subset_term))
    if name in {
        "hom_precompose",
        "hom_postcompose",
        "tensor_lift",
        "tensor_curry",
        "tensor_assoc",
        "bilinear_postcompose",
    }:
        p = _module(ss[3], r)
        if name == "tensor_assoc":
            return Sort(
                "map",
                r,
                ("tensor", r, ("tensor", r, m, n), p),
                ("tensor", r, m, ("tensor", r, n, p)),
            )
        if name == "bilinear_postcompose":
            q = _module(ss[4], r)
            _same(ss[5], Sort("map", r, m, ("hom", r, n, p)))
            _same(ss[6], Sort("map", r, p, q))
            return Sort("map", r, m, ("hom", r, n, q))
        if name == "hom_precompose":
            _same(ss[4], Sort("map", r, m, n))
            return Sort("map", r, ("hom", r, n, p), ("hom", r, m, p))
        if name == "hom_postcompose":
            _same(ss[4], Sort("map", r, n, p))
            return Sort("map", r, ("hom", r, m, n), ("hom", r, m, p))
        if name == "tensor_lift":
            _same(ss[4], Sort("map", r, m, ("hom", r, n, p)))
            return Sort("map", r, ("tensor", r, m, n), p)
        _same(ss[4], Sort("map", r, ("tensor", r, m, n), p))
        return Sort("map", r, m, ("hom", r, n, p))
    if name == "linear_zero":
        return Sort("map", r, m, n)
    if name in {"compose", "exact"}:
        p = _module(ss[3], r)
        _same(ss[4], Sort("map", r, m, n))
        _same(ss[5], Sort("map", r, n, p))
        return PROP if name == "exact" else Sort("map", r, m, p)
    if name == "tensor_map_left":
        p = _module(ss[3], r)
        _same(ss[4], Sort("map", r, n, p))
        return Sort("map", r, ("tensor", r, m, n), ("tensor", r, m, p))
    _same(ss[3], Sort("map", r, m, n))
    if name in {"injective", "surjective"}:
        return PROP
    if name in {"kernel", "range"}:
        return Sort("submodule", r, m if name == "kernel" else n)
    _same(ss[4], Sort("submodule", r, m if name == "map" else n))
    return Sort("submodule", r, n if name == "map" else m)


def canonicalize_typed_commalg_v3_openmath_xml(xml: str) -> str:
    if len(xml.encode("utf-8")) > 65_536:
        _fail("XML exceeds 65536 bytes")
    root = validate_openmath_xml(xml)
    nodes = list(root.iter())
    if len(nodes) > 4096:
        _fail("XML exceeds 4096 nodes")
    parents = {c: p for p in nodes for c in p}
    for e in nodes:
        tag = _local_name(e)
        if e.tag != f"{{{OPENMATH_NAMESPACE}}}{tag}" or tag not in _ATTRS:
            _fail("foreign namespace or unsupported element")
        if set(e.attrib) != _ATTRS[tag]:
            _fail("unexpected or missing attributes")
        if (e.text and e.text.strip()) or (e.tail and e.tail.strip()):
            _fail("mixed/text content is not permitted")
        if any(len(v) > 20_000 for v in e.attrib.values()):
            _fail("attribute too long")
        if tag in {"OMS", "OMV"} and len(e):
            _fail("atomic element cannot contain children")
        if tag == "OMS":
            _symbol(e)
        expected_parent = {"OMBVAR": "OMBIND", "OMATTR": "OMBVAR", "OMATP": "OMATTR"}.get(tag)
        if expected_parent and (e not in parents or _local_name(parents[e]) != expected_parent):
            _fail("misplaced binder annotation")
        depth, current = 0, e
        while current in parents:
            current = parents[current]
            depth += 1
        if depth > 64:
            _fail("XML exceeds depth64")
    if _local_name(root) != "OMOBJ" or root.get("version") != "2.0" or len(root) != 1:
        _fail("expected OMOBJ version2.0 with one expression")
    if _local_name(root[0]) != "OMBIND":
        _fail("root proposition requires explicit quantification")
    _same(_infer(root[0], {}), PROP)
    result: str = _canonicalize_openmath_v4_root(root)
    return result


def validate_canonical_typed_commalg_v3_openmath_xml(xml: str) -> str:
    result = canonicalize_typed_commalg_v3_openmath_xml(xml)
    if result != xml:
        _fail("XML is not exact canonical bytes")
    return result
