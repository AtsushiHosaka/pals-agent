"""Carrier separation and semantic-slot regressions for module-v2 authoring."""

from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError
from pals_agent.typed_commalg_modules_v2 import (
    _REGISTRY,
    CDBASE,
    _validate_registry,
)
from pals_agent.typed_commalg_modules_v2 import (
    canonicalize_typed_commalg_modules_v2_openmath_xml as canonicalize,
)
from pals_agent.typed_commalg_modules_v2 import (
    validate_canonical_typed_commalg_modules_v2_openmath_xml as validate,
)

ROOT = Path(__file__).resolve().parents[3]
NS = "{http://www.openmath.org/OpenMath}"


def s(cd, name):
    base = "http://www.openmath.org/cd" if cd in {"relation1", "logic1"} else CDBASE
    return f'<OMS cdbase="{base}" cd="{cd}" name="{name}"/>'


def v(name):
    return f'<OMV name="{name}"/>'


def a(name, *args):
    return "<OMA>" + s("module2", name) + "".join(args) + "</OMA>"


def equal(x, y):
    return "<OMA>" + s("relation1", "eq") + x + y + "</OMA>"


def document(body, declarations=None):
    if declarations is None:
        declarations = [
            ("R", s("module2", "CommRing")),
            ("M", a("Module", v("R"))),
            ("N", a("Module", v("R"))),
            ("U", a("Submodule", v("R"), v("M"))),
            ("V", a("Submodule", v("R"), v("M"))),
            ("f", a("LinearMap", v("R"), v("M"), v("N"))),
        ]
    ds = "".join(
        "<OMATTR><OMATP>" + s("typed1", "type") + sort + "</OMATP>" + v(name) + "</OMATTR>"
        for name, sort in declarations
    )
    return (
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMBIND>'
        + s("typed1", "forall")
        + "<OMBVAR>"
        + ds
        + "</OMBVAR>"
        + body
        + "</OMBIND></OMOBJ>"
    )


R, M, N, U, V, F = map(v, ["R", "M", "N", "U", "V", "f"])
Q = a("quotient", R, M, U)
PI = a("quotient_map", R, M, U)


def test_quotient_projection_kernel_carrier():
    xml = document(equal(a("kernel", R, M, Q, PI), U))
    assert validate(canonicalize(xml)) == canonicalize(xml)


@pytest.mark.parametrize(
    "body",
    [
        equal(a("kernel", R, M, a("quotient", R, M, V), PI), U),
        equal(a("kernel", R, N, Q, PI), U),
        equal(a("range", R, M, Q, PI), U),
        equal(a("quotient_map", R, M, U), a("quotient_map", R, M, V)),
        equal(a("submodule_top", R, a("quotient", R, N, U)), a("submodule_bot", R, N)),
        a("fg", R, Q, U),
        a("surjective", R, Q, M, PI),
        a("exact", R, M, N, M, F, F),
        a(
            "injective",
            R,
            a("tensor", R, M, M),
            a("tensor", R, N, M),
            a("tensor_map_left", R, M, M, N, F),
        ),
        a("finite", R, M, U),
        a("fg", R, M),
        a("finite", R, v("unbound")),
        a("finite", R, a("tensor", R, M, v("unbound"))),
        equal(a("ideal_smul", R, M, U, U), U),
        equal(a("maximal_ideal", R), a("ideal_bot", R)),
    ],
)
def test_rejects_carrier_arity_scope_and_locality_errors(body):
    with pytest.raises(MathXMLValidationError):
        canonicalize(document(body))


def test_distinct_ring_modules_never_coerce():
    ds = [
        ("R", s("module2", "CommRing")),
        ("S", s("module2", "CommRing")),
        ("M", a("Module", v("S"))),
    ]
    with pytest.raises(MathXMLValidationError):
        canonicalize(document(a("finite", R, M), ds))


def test_local_ring_explicitly_permits_maximal_ideal():
    ds = [("R", s("module2", "LocalRing"))]
    xml = document(equal(a("maximal_ideal", R), a("ideal_jacobson", R, a("ideal_bot", R))), ds)
    validate(canonicalize(xml))


@pytest.mark.parametrize(
    "sort",
    [
        a("QuotientModule", R, M, U),
        a("Submodule", R, a("quotient", R, N, U)),
        a("LinearMap", R, a("quotient", R, M, v("future")), N),
    ],
)
def test_forged_and_forward_dependent_sort_rejected(sort):
    ds = [
        ("R", s("module2", "CommRing")),
        ("M", a("Module", R)),
        ("N", a("Module", R)),
        ("U", a("Submodule", R, M)),
        ("f", sort),
    ]
    with pytest.raises(MathXMLValidationError):
        canonicalize(document(a("finite", R, M), ds))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x.replace('cd="module2" name="finite"', 'cd="module2" name="nakayama_theorem"'),
        lambda x: x.replace(CDBASE, CDBASE + "-forged"),
        lambda x: x.replace('name="finite"', 'name="finite" bogus="1"'),
        lambda x: x.replace('<OMV name="M"/>', '<OMV name="M"><OMV name="R"/></OMV>'),
        lambda x: x.replace("<OMBVAR>", '<OMBVAR extra="1">'),
        lambda x: x.replace('name="U"', 'name="M"'),
        lambda x: x.replace("</OMOBJ>", '<OMV name="R"/></OMOBJ>'),
        lambda x: x.replace("http://www.openmath.org/OpenMath", "urn:fake"),
        lambda x: x.replace(
            "<OMA>" + s("module2", "finite"), "<OMA>" + s("module2", "finite") + "text"
        ),
    ],
)
def test_rejects_forged_symbols_attributes_and_tree_shapes(mutation):
    with pytest.raises(MathXMLValidationError):
        canonicalize(mutation(document(a("finite", R, M))))


def test_only_exact_canonical_bytes_accepted():
    raw = document(a("finite", R, M))
    with pytest.raises(MathXMLValidationError):
        validate(raw)
    assert canonicalize(raw) == canonicalize(raw.replace('name="R"', 'name="S"'))


def test_resource_bounds():
    with pytest.raises(MathXMLValidationError):
        canonicalize(" " * 65537)
    body = a("finite", R, M)
    for _ in range(65):
        body = "<OMA>" + s("logic1", "not") + body + "</OMA>"
    with pytest.raises(MathXMLValidationError):
        canonicalize(document(body))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(schema_version="arbitrary"),
        lambda p: p.update(profile_id="typed-commutative-algebra-modules-v1"),
        lambda p: p.update(extra=True),
        lambda p: p["symbols"].append(
            {
                "cdbase": "http://www.openmath.org/cd",
                "cd": "relation1",
                "name": "leq",
                "signature": "a",
                "lean_meaning": "a",
            }
        ),
        lambda p: p["symbols"].pop(),
        lambda p: p["symbols"][0].update(name="invented"),
        lambda p: p["symbols"][0].update(lean_meaning=""),
    ],
)
def test_registry_cannot_extend_or_mutate_the_language(mutation):
    payload = copy.deepcopy(_REGISTRY)
    mutation(payload)
    with pytest.raises(RuntimeError):
        _validate_registry(payload)


def test_all_authored_cards_and_exact_lean_bundle():
    payload = json.loads((ROOT / "docs/commalg-modules-v2-batch.json").read_text())
    for card in payload["cards"]:
        validate(card["openmath_xml"])
    expected = (
        "import Mathlib\n\n"
        + "\n\n".join(
            "-- manifest card: "
            + c["id"]
            + "\n"
            + c["lean_target"]
            + " := "
            + c["lean_witness"].rstrip()
            for c in payload["cards"]
        )
        + "\n"
    )
    assert (ROOT / "docs/commalg-modules-v2-batch.lean").read_text() == expected


def test_nakayama_retains_finiteness_locality_and_ideal_action_order():
    payload = json.loads((ROOT / "docs/commalg-modules-v2-batch.json").read_text())
    c = next(
        c for c in payload["cards"] if c["id"] == "commalg_modules_v2_nakayama_local_finite_module"
    )
    root = ET.fromstring(c["openmath_xml"])
    symbols = [e.get("name") for e in root.iter(NS + "OMS")]
    assert symbols.count("LocalRing") == 1
    assert symbols.count("finite") == 1
    assert symbols.count("maximal_ideal") == 1
    assert "flat" not in symbols
    action = next(e for e in root.iter(NS + "OMA") if e[0].get("name") == "ideal_smul")
    assert action[1].get("name") == "v1"  # R
    assert action[2].get("name") == "v2"  # M
    assert action[3][0].get("name") == "maximal_ideal"  # ideal then submodule
    assert action[4][0].get("name") == "submodule_top"
    assert "[Module.Finite R M]" in c["lean_target"]
    assert "[IsLocalRing R]" in c["lean_target"]
    assert "Free" not in c["lean_target"] and "Noetherian" not in c["lean_target"]


def test_tensor_semantics_and_exact_order_are_pinned():
    entries = {s["name"]: s for s in _REGISTRY["symbols"]}
    assert "g.comp f" in entries["compose"]["lean_meaning"]
    assert "Function.Exact f g" in entries["exact"]["lean_meaning"]
    assert "f.lTensor X" in entries["tensor_map_left"]["lean_meaning"]
    assert "NOT finite cardinality" in entries["finite"]["lean_meaning"]
    assert "Subsingleton M" in entries["module_zero"]["lean_meaning"]
