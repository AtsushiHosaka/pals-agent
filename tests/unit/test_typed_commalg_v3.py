"""Carrier separation and semantic-slot regressions for commalg-v3 authoring."""

from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError
from pals_agent.typed_commalg_v3 import (
    _REGISTRY,
    CDBASE,
    _validate_registry,
)
from pals_agent.typed_commalg_v3 import (
    canonicalize_typed_commalg_v3_openmath_xml as canonicalize,
)
from pals_agent.typed_commalg_v3 import (
    validate_canonical_typed_commalg_v3_openmath_xml as validate,
)

ROOT = Path(__file__).resolve().parents[3]
NS = "{http://www.openmath.org/OpenMath}"


def s(cd, name):
    base = "http://www.openmath.org/cd" if cd in {"relation1", "logic1"} else CDBASE
    return f'<OMS cdbase="{base}" cd="{cd}" name="{name}"/>'


def v(name):
    return f'<OMV name="{name}"/>'


def a(name, *args):
    return "<OMA>" + s("module3", name) + "".join(args) + "</OMA>"


def equal(x, y):
    return "<OMA>" + s("relation1", "eq") + x + y + "</OMA>"


def document(body, declarations=None):
    if declarations is None:
        declarations = [
            ("R", s("module3", "CommRing")),
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
        ("R", s("module3", "CommRing")),
        ("S", s("module3", "CommRing")),
        ("M", a("Module", v("S"))),
    ]
    with pytest.raises(MathXMLValidationError):
        canonicalize(document(a("finite", R, M), ds))


def test_local_ring_explicitly_permits_maximal_ideal():
    ds = [("R", s("module3", "LocalRing"))]
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
        ("R", s("module3", "CommRing")),
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
        lambda x: x.replace('cd="module3" name="finite"', 'cd="module3" name="nakayama_theorem"'),
        lambda x: x.replace(CDBASE, CDBASE + "-forged"),
        lambda x: x.replace('name="finite"', 'name="finite" bogus="1"'),
        lambda x: x.replace('<OMV name="M"/>', '<OMV name="M"><OMV name="R"/></OMV>'),
        lambda x: x.replace("<OMBVAR>", '<OMBVAR extra="1">'),
        lambda x: x.replace('name="U"', 'name="M"'),
        lambda x: x.replace("</OMOBJ>", '<OMV name="R"/></OMOBJ>'),
        lambda x: x.replace("http://www.openmath.org/OpenMath", "urn:fake"),
        lambda x: x.replace(
            "<OMA>" + s("module3", "finite"), "<OMA>" + s("module3", "finite") + "text"
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
    payload = json.loads((ROOT / "docs/commalg-v3-batch.json").read_text())
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
    assert (ROOT / "docs/commalg-v3-batch.lean").read_text() == expected


def test_tensor_semantics_and_exact_order_are_pinned():
    entries = {s["name"]: s for s in _REGISTRY["symbols"]}
    assert "g.comp f" in entries["compose"]["lean_meaning"]
    assert "Function.Exact f g" in entries["exact"]["lean_meaning"]
    assert "f.lTensor X" in entries["tensor_map_left"]["lean_meaning"]
    assert "NOT finite cardinality" in entries["finite"]["lean_meaning"]
    assert "Subsingleton M" in entries["module_zero"]["lean_meaning"]


S, T, X = map(v, ["S", "T", "X"])


def localized(module, subset=S):
    return a("localized_module", R, module, subset)


def localized_map(fn=F, subset=S):
    return a("localized_map", R, M, N, subset, fn)


def hom(source, target):
    return a("hom", R, source, target)


def localization_document(body, extra=None):
    ds = [
        ("R", s("module3", "CommRing")),
        ("M", a("Module", R)),
        ("N", a("Module", R)),
        ("X", a("Module", R)),
        ("S", a("Submonoid", R)),
        ("T", a("Submonoid", R)),
        ("U", a("Submodule", R, M)),
        ("f", a("LinearMap", R, M, N)),
    ]
    return document(body, ds + (extra or []))


@pytest.mark.parametrize(
    "body",
    [
        a("injective", R, localized(M, T), localized(N), localized_map()),
        a("injective", R, localized(M), localized(N, T), localized_map()),
        a("injective", R, localized(N), localized(M), localized_map()),
        a("injective", R, localized(M), localized(N), localized_map(subset=U)),
        a("noetherian", R, a("localized_module", R, M, v("future"))),
        a("noetherian", R, a("localized_module", R, M, M)),
        a("noetherian", R, a("localized_module", R, S, M)),
        equal(a("localized_submodule", R, N, S, U), a("submodule_bot", R, localized(N))),
        equal(a("localized_submodule", R, M, S, U), a("submodule_bot", R, localized(M, T))),
        equal(a("localization_map", R, M, S), a("linear_id", R, M)),
        a("noetherian", R, a("hom", R, M)),
        a("finite_length", R, M, N),
        a("exact", R, M, localized(M), localized(N), a("localization_map", R, M, S), F),
        a("injective", R, hom(M, X), hom(N, X), a("hom_precompose", R, M, N, X, F)),
        a("injective", R, hom(X, N), hom(X, M), a("hom_postcompose", R, X, M, N, F)),
        a("injective", R, hom(M, X), hom(N, X), a("hom_postcompose", R, X, M, N, F)),
    ],
)
def test_new_dependent_carriers_and_variance_fail_closed(body):
    with pytest.raises(MathXMLValidationError):
        canonicalize(localization_document(body))


def test_localized_modules_do_not_coerce_multiplicative_subsets_between_rings():
    ds = [
        ("R", s("module3", "CommRing")),
        ("A", s("module3", "CommRing")),
        ("M", a("Module", R)),
        ("S", a("Submonoid", v("A"))),
    ]
    with pytest.raises(MathXMLValidationError):
        canonicalize(document(a("noetherian", R, localized(M)), ds))


def test_forged_localization_binder_sort():
    with pytest.raises(MathXMLValidationError):
        canonicalize(localization_document(a("noetherian", R, M), [("L", localized(M))]))


@pytest.mark.parametrize(
    "body",
    [
        a("injective", R, localized(M), localized(N), localized_map()),
        a("injective", R, hom(N, X), hom(M, X), a("hom_precompose", R, M, N, X, F)),
        a("injective", R, hom(X, M), hom(X, N), a("hom_postcompose", R, X, M, N, F)),
    ],
)
def test_new_operator_carriers_validate_in_correct_order(body):
    validate(canonicalize(localization_document(body)))


def test_tensor_lift_and_curry_enforce_bilinear_hom_order():
    tensor = a("tensor", R, M, N)
    lifted = a("tensor_lift", R, M, N, X, v("b"))
    ds = [("b", a("LinearMap", R, M, hom(N, X)))]
    good = equal(a("tensor_curry", R, M, N, X, lifted), v("b"))
    validate(canonicalize(localization_document(good, ds)))
    for bad in [
        a("injective", R, a("tensor", R, N, M), X, lifted),
        a("injective", R, tensor, X, a("tensor_lift", R, N, M, X, v("b"))),
        equal(a("tensor_curry", R, N, M, X, lifted), v("b")),
    ]:
        with pytest.raises(MathXMLValidationError):
            canonicalize(localization_document(bad, ds))


def test_new_card_assumptions_and_semantic_slots():
    payload = json.loads((ROOT / "docs/commalg-v3-batch.json").read_text())
    cards = {c["id"].removeprefix("commalg_v3_"): c for c in payload["cards"]}
    assert len(cards) == 31

    def names(key):
        return [e.get("name") for e in ET.fromstring(cards[key]["openmath_xml"]).iter(NS + "OMS")]

    assert names("tensor_right_exact").count("surjective") == 1
    assert "flat" not in names("tensor_right_exact")
    assert "surjective" not in names("localization_exact")
    assert names("noetherian_hom").count("finite") == 1
    assert names("noetherian_hom").count("noetherian") == 2
    assert "finite" not in names("finite_length_iff_chain_conditions")
    assert names("hom_contravariant_left_exact").count("surjective") == 1
    c = cards["localization_ideal_action"]
    root = ET.fromstring(c["openmath_xml"])
    actions = [e for e in root.iter(NS + "OMA") if e[0].get("name") == "ideal_smul"]
    assert len(actions) == 2
    assert actions[0][3].get("name") == actions[1][3].get("name")  # same original ideal
    assert actions[1][2][0].get("name") == "localized_module"
    entries = {e["name"]: e["lean_meaning"] for e in _REGISTRY["symbols"]}
    assert "h.comp f" in entries["hom_precompose"]
    assert "f.comp h" in entries["hom_postcompose"]
    assert "restricting scalars" in entries["localized_module"]
    assert "possibly containing 0" in entries["Submonoid"]
