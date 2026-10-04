"""Closed carrier-safe prime spectra, integral extensions and dimension language.

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

PROFILE_ID = "typed-commalg-v4"
CDBASE = "urn:pals:openmath:typed-commalg:v4"
STANDARD = "http://www.openmath.org/cd"
CD = "spectrum4"


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
        "CommRing Algebra Ideal Element Prime SpecSet Submonoid RingHom nontrivial domain "
        "noetherian integrally_closed spec_t0 spec_nonempty ideal_bot ideal_top "
        "nilradical zero one empty univ ideal_radical is_prime is_maximal ideal_le "
        "ideal_lt ideal_sum ideal_product prime_ideal singleton vanishing_ideal "
        "zero_locus closure complement is_closed is_clopen is_compact is_irreducible "
        "set_union set_intersection set_subset basic_open principal nilpotent idempotent "
        "ideal_member algebra_map integral flat ring_injective ring_surjective "
        "ring_integral ring_kernel spec_comap spec_range map_ideal comap_ideal "
        "spec_preimage continuous embedding open_embedding closed_embedding homeomorphism "
        "closed_map spec_surjective polynomial quotient localization away at_prime "
        "quotient_map localization_map away_map dimension height dimension_successor "
        "dimension_le "
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
        or payload["schema_version"] != "pals.typed-commalg-v4-registry.v1"
        or payload["profile_id"] != PROFILE_ID
        or payload["cdbases"] != {"typed": CDBASE, "standard": STANDARD}
        or not isinstance(payload["symbols"], list)
    ):
        raise RuntimeError("Invalid commalg v4 registry header")
    symbols = []
    for s in payload["symbols"]:
        if (
            not isinstance(s, dict)
            or set(s) != {"cdbase", "cd", "name", "signature", "lean_meaning"}
            or any(not isinstance(v, str) or not v.strip() for v in s.values())
        ):
            raise RuntimeError("Invalid commalg v4 symbol metadata")
        symbols.append((s["cdbase"], s["cd"], s["name"]))
    if len(symbols) != len(_EXPECTED_SYMBOLS) or frozenset(symbols) != _EXPECTED_SYMBOLS:
        raise RuntimeError("Commalg v4 registry symbol drift")
    return frozenset(symbols)


_REGISTRY = json.loads(
    resources.files("pals_agent.content_dictionaries")
    .joinpath("typed-commalg-v4-registry.json")
    .read_text(encoding="utf-8")
)
_SYMBOLS = _validate_registry(_REGISTRY)


def _fail(message: str) -> None:
    raise MathXMLValidationError("typed-commalg-v4: " + message)


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


_ARITIES = {
    "nontrivial": 1,
    "domain": 1,
    "noetherian": 1,
    "integrally_closed": 1,
    "spec_t0": 1,
    "spec_nonempty": 1,
    "ideal_bot": 1,
    "ideal_top": 1,
    "nilradical": 1,
    "zero": 1,
    "one": 1,
    "empty": 1,
    "univ": 1,
    "ideal_radical": 2,
    "is_prime": 2,
    "is_maximal": 2,
    "ideal_le": 3,
    "ideal_lt": 3,
    "ideal_sum": 3,
    "ideal_product": 3,
    "prime_ideal": 2,
    "singleton": 2,
    "vanishing_ideal": 2,
    "zero_locus": 2,
    "closure": 2,
    "complement": 2,
    "is_closed": 2,
    "is_clopen": 2,
    "is_compact": 2,
    "is_irreducible": 2,
    "set_union": 3,
    "set_intersection": 3,
    "set_subset": 3,
    "basic_open": 2,
    "principal": 2,
    "nilpotent": 2,
    "idempotent": 2,
    "ideal_member": 3,
    "algebra_map": 2,
    "integral": 2,
    "flat": 2,
    "ring_injective": 3,
    "ring_surjective": 3,
    "ring_integral": 3,
    "ring_kernel": 3,
    "spec_comap": 3,
    "spec_range": 3,
    "map_ideal": 4,
    "comap_ideal": 4,
    "spec_preimage": 4,
    "continuous": 3,
    "embedding": 3,
    "open_embedding": 3,
    "closed_embedding": 3,
    "homeomorphism": 3,
    "closed_map": 3,
    "spec_surjective": 3,
    "polynomial": 1,
    "quotient": 2,
    "localization": 2,
    "away": 2,
    "at_prime": 2,
    "quotient_map": 2,
    "localization_map": 2,
    "away_map": 2,
    "dimension": 1,
    "height": 2,
    "dimension_successor": 1,
    "dimension_le": 2,
}


def _sort(e: ET.Element, env: dict[str, Sort]) -> Sort:
    if _local_name(e) == "OMS" and _symbol(e) == (CDBASE, CD, "CommRing"):
        return Sort("ring")
    if _local_name(e) != "OMA" or not len(e):
        _fail("invalid dependent declaration")
    base, cd, name = _symbol(e[0])
    args = list(e)[1:]
    if (base, cd) != (CDBASE, CD) or name not in {
        "Algebra",
        "Ideal",
        "Element",
        "Prime",
        "SpecSet",
        "Submonoid",
        "RingHom",
    }:
        _fail("unknown declaration sort")
    _arity(args, 2 if name == "RingHom" else 1)
    r = _ring(_infer(args[0], env))
    if name == "Algebra":
        return Sort("ring", target=r)
    if name == "RingHom":
        return Sort("ringmap", r, target=_ring(_infer(args[1], env)))
    return Sort(
        {
            "Ideal": "ideal",
            "Element": "element",
            "Prime": "prime",
            "SpecSet": "set",
            "Submonoid": "submonoid",
        }[name],
        r,
    )


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
            _fail("invalid declarations")
        scope = dict(env)
        for decl in e[1]:
            if _local_name(decl) != "OMATTR" or len(decl) != 2:
                _fail("invalid declaration")
            pair, variable = decl
            if (
                _local_name(pair) != "OMATP"
                or len(pair) != 2
                or _symbol(pair[0]) != (CDBASE, "typed1", "type")
            ):
                _fail("one exact type annotation required")
            if _local_name(variable) != "OMV" or not variable.get("name"):
                _fail("declaration variable required")
            name = variable.attrib["name"]
            if name in scope:
                _fail("shadowed or duplicate binder")
            s = _sort(pair[1], scope)
            if s.kind == "ring":
                s = Sort("ring", ("var", name), target=s.target)
            scope[name] = s
        _same(_infer(e[2], scope), PROP)
        return PROP
    if tag != "OMA" or not len(e):
        _fail("expected application or binder")
    base, cd, name = _symbol(e[0])
    args = list(e)[1:]
    ss = [_infer(a, env) for a in args]
    if (base, cd) == (STANDARD, "relation1"):
        _arity(ss, 2)
        if ss[0].kind in {"ring", "prop"}:
            _fail("cannot equate carrier declarations or propositions")
        _same(ss[1], ss[0])
        return PROP
    if (base, cd) == (STANDARD, "logic1"):
        if name in {"and", "or"}:
            if not 2 <= len(ss) <= 32:
                _fail("logical arity outside bounds")
        else:
            _arity(ss, 1 if name == "not" else 2)
        for s in ss:
            _same(s, PROP)
        return PROP
    if (base, cd) != (CDBASE, CD) or name not in _ARITIES:
        _fail("not a term operator")
    _arity(ss, _ARITIES[name])
    if name in {"dimension_successor", "dimension_le"}:
        for s in ss:
            _same(s, Sort("dimension"))
        return PROP if name == "dimension_le" else Sort("dimension")
    r = _ring(ss[0])
    if name in {
        "nontrivial",
        "domain",
        "noetherian",
        "integrally_closed",
        "spec_t0",
        "spec_nonempty",
    }:
        return PROP
    if name in {"ideal_bot", "ideal_top", "nilradical"}:
        return Sort("ideal", r)
    if name in {"zero", "one"}:
        return Sort("element", r)
    if name in {"empty", "univ"}:
        return Sort("set", r)
    if name == "dimension":
        return Sort("dimension")
    if name == "polynomial":
        return Sort("ring", ("polynomial", r))
    if name in {
        "quotient",
        "quotient_map",
        "localization",
        "localization_map",
        "away",
        "away_map",
        "at_prime",
    }:
        constructor = {
            "quotient_map": "quotient",
            "localization_map": "localization",
            "away_map": "away",
        }.get(name, name)
        kind = {
            "quotient": "ideal",
            "localization": "submonoid",
            "away": "element",
            "at_prime": "prime",
        }[constructor]
        _same(ss[1], Sort(kind, r))
        carrier = (constructor, r, _term(args[1]))
        return (
            Sort("ringmap", r, target=carrier) if name.endswith("_map") else Sort("ring", carrier)
        )
    if name in {"ideal_radical", "is_prime", "is_maximal", "height"}:
        _same(ss[1], Sort("ideal", r))
        return (
            Sort("ideal", r)
            if name == "ideal_radical"
            else Sort("dimension")
            if name == "height"
            else PROP
        )
    if name in {"ideal_le", "ideal_lt", "ideal_sum", "ideal_product"}:
        for s in ss[1:]:
            _same(s, Sort("ideal", r))
        return PROP if name in {"ideal_le", "ideal_lt"} else Sort("ideal", r)
    if name in {"prime_ideal", "singleton"}:
        _same(ss[1], Sort("prime", r))
        return Sort("ideal" if name == "prime_ideal" else "set", r)
    if name == "zero_locus":
        _same(ss[1], Sort("ideal", r))
        return Sort("set", r)
    if name in {
        "closure",
        "complement",
        "vanishing_ideal",
        "is_closed",
        "is_clopen",
        "is_compact",
        "is_irreducible",
    }:
        _same(ss[1], Sort("set", r))
        return (
            PROP
            if name.startswith("is_")
            else Sort("ideal" if name == "vanishing_ideal" else "set", r)
        )
    if name in {"set_union", "set_intersection", "set_subset"}:
        for s in ss[1:]:
            _same(s, Sort("set", r))
        return PROP if name == "set_subset" else Sort("set", r)
    if name in {"basic_open", "principal", "nilpotent", "idempotent", "ideal_member"}:
        _same(ss[1], Sort("element", r))
        if name == "ideal_member":
            _same(ss[2], Sort("ideal", r))
        return (
            Sort("set", r)
            if name == "basic_open"
            else Sort("ideal", r)
            if name == "principal"
            else PROP
        )
    t = _ring(ss[1])
    if name in {"algebra_map", "integral", "flat"}:
        if ss[1].target != r:
            _fail("algebra belongs to a different base ring")
        return Sort("ringmap", r, target=t) if name == "algebra_map" else PROP
    if name in {
        "continuous",
        "embedding",
        "open_embedding",
        "closed_embedding",
        "homeomorphism",
        "closed_map",
        "spec_surjective",
    }:
        _same(ss[2], Sort("specmap", r, target=t))
        return PROP
    _same(ss[2], Sort("ringmap", r, target=t))
    if name in {"ring_injective", "ring_surjective", "ring_integral"}:
        return PROP
    if name == "ring_kernel":
        return Sort("ideal", r)
    if name == "spec_comap":
        return Sort("specmap", t, target=r)
    if name == "spec_range":
        return Sort("set", r)
    if name in {"map_ideal", "comap_ideal"}:
        _same(ss[3], Sort("ideal", r if name == "map_ideal" else t))
        return Sort("ideal", t if name == "map_ideal" else r)
    if name == "spec_preimage":
        _same(ss[3], Sort("set", r))
        return Sort("set", t)
    _fail("unsupported operation")
    raise AssertionError("unreachable")


def canonicalize_typed_commalg_v4_openmath_xml(xml: str) -> str:
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


def validate_canonical_typed_commalg_v4_openmath_xml(xml: str) -> str:
    result = canonicalize_typed_commalg_v4_openmath_xml(xml)
    if result != xml:
        _fail("XML is not exact canonical bytes")
    return result
