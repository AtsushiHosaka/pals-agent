"""Dependent ring/Spec carrier, variance and material-hypothesis regressions."""

from __future__ import annotations

import copy
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError
from pals_agent.typed_commalg_v4 import _REGISTRY, CDBASE, _validate_registry
from pals_agent.typed_commalg_v4 import canonicalize_typed_commalg_v4_openmath_xml as canonicalize
from pals_agent.typed_commalg_v4 import validate_canonical_typed_commalg_v4_openmath_xml as validate

ROOT = Path(__file__).resolve().parents[3]
NS = "{http://www.openmath.org/OpenMath}"


def sym(cd, name):
    base = CDBASE if cd not in {"relation1", "logic1"} else "http://www.openmath.org/cd"
    return f'<OMS cdbase="{base}" cd="{cd}" name="{name}"/>'


def v(name):
    return f'<OMV name="{name}"/>'


def op(name, *args):
    return "<OMA>" + sym("spectrum4", name) + "".join(args) + "</OMA>"


def eq(a, b):
    return "<OMA>" + sym("relation1", "eq") + a + b + "</OMA>"


R, S, IR, J, K, T, U, p, x, y, f, M, N = map(
    v, ["R", "S", "I", "J", "K", "T", "U", "p", "x", "y", "f", "M", "N"]
)


def ds():
    return [
        ("R", sym("spectrum4", "CommRing")),
        ("S", op("Algebra", R)),
        ("I", op("Ideal", R)),
        ("J", op("Ideal", R)),
        ("K", op("Ideal", S)),
        ("T", op("SpecSet", R)),
        ("U", op("SpecSet", S)),
        ("p", op("Prime", R)),
        ("x", op("Element", R)),
        ("y", op("Element", S)),
        ("f", op("RingHom", R, S)),
        ("M", op("Submonoid", R)),
        ("N", op("Submonoid", R)),
    ]


def doc(body, declarations=None):
    decls = ds() if declarations is None else declarations
    return (
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMBIND>'
        + sym("typed1", "forall")
        + "<OMBVAR>"
        + "".join(
            "<OMATTR><OMATP>" + sym("typed1", "type") + sort + "</OMATP>" + v(name) + "</OMATTR>"
            for name, sort in decls
        )
        + "</OMBVAR>"
        + body
        + "</OMBIND></OMOBJ>"
    )


def test_positive_dependent_operations():
    for body in [
        eq(op("zero_locus", R, IR), T),
        op("integral", R, S),
        op("continuous", S, R, op("spec_comap", R, S, f)),
        eq(op("comap_ideal", R, S, f, K), IR),
        eq(op("map_ideal", R, S, f, IR), K),
        eq(op("spec_preimage", R, S, f, T), U),
    ]:
        validate(canonicalize(doc(body)))


@pytest.mark.parametrize(
    "body",
    [
        eq(op("zero_locus", R, K), T),
        eq(op("zero_locus", S, IR), U),
        eq(op("zero_locus", R, IR), U),
        eq(op("vanishing_ideal", R, U), IR),
        eq(op("vanishing_ideal", R, T), K),
        eq(op("map_ideal", R, S, f, K), K),
        eq(op("comap_ideal", R, S, f, IR), IR),
        eq(op("spec_preimage", R, S, f, U), U),
        eq(op("spec_preimage", R, S, f, T), T),
        op("continuous", R, S, op("spec_comap", R, S, f)),
        op("spec_surjective", R, S, op("spec_comap", R, S, f)),
        op("ring_injective", S, R, f),
        op("ring_integral", S, R, f),
        op("integral", S, R),
        op("flat", S, R),
        eq(op("algebra_map", S, R), f),
        eq(op("algebra_map", R, S), op("localization_map", R, M)),
        eq(op("quotient_map", R, IR), op("quotient_map", R, J)),
        eq(op("localization_map", R, M), op("localization_map", R, N)),
        op("ring_injective", R, op("localization", R, N), op("localization_map", R, M)),
        op("ring_injective", R, op("quotient", R, J), op("quotient_map", R, IR)),
        op("domain", op("at_prime", R, IR)),
        op("domain", op("away", R, y)),
        op("domain", op("localization", S, M)),
        op("ideal_member", R, IR, x),
        op("ideal_member", R, x, K),
        op("nilpotent", R, IR),
        op("idempotent", R, y),
        op("dimension_le", op("dimension", R), x),
        op("dimension_le", op("height", R, K), op("dimension", S)),
        op("spec_t0", v("free")),
        op("noetherian", R, S),
        op("zero_locus", R),
        op("continuous", R, S, f),
    ],
)
def test_rejects_carrier_variance_arity_errors(body):
    with pytest.raises(MathXMLValidationError):
        canonicalize(doc(body))


@pytest.mark.parametrize(
    "sort",
    [
        op("localization", R, M),
        op("quotient", R, IR),
        op("RingHom", R, v("future")),
        op("Algebra", v("future")),
        op("Prime", IR),
    ],
)
def test_constructed_or_forward_binder_forgery(sort):
    with pytest.raises(MathXMLValidationError):
        canonicalize(doc(op("spec_t0", R), ds() + [("bad", sort)]))


def test_unrelated_algebra_structures_do_not_coerce():
    decls = [
        ("R", sym("spectrum4", "CommRing")),
        ("A", sym("spectrum4", "CommRing")),
        ("S", op("Algebra", v("A"))),
    ]
    with pytest.raises(MathXMLValidationError):
        canonicalize(doc(op("integral", R, S), decls))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda x: x.replace(CDBASE, CDBASE + "forged"),
        lambda x: x.replace("http://www.openmath.org/OpenMath", "urn:fake"),
        lambda x: x.replace("<OMBVAR>", '<OMBVAR extra="1">'),
        lambda x: x.replace('name="I"', 'name="R"'),
        lambda x: x.replace('name="spec_t0"', 'name="spec_t0" bogus="1"'),
        lambda x: x.replace('name="spec_t0"', 'name="invented_theorem"'),
        lambda x: x.replace('<OMV name="I"/>', '<OMV name="I"><OMV name="R"/></OMV>'),
        lambda x: x.replace("</OMOBJ>", '<OMV name="R"/></OMOBJ>'),
    ],
)
def test_rejects_namespace_registry_and_tree_forgery(mutate):
    with pytest.raises(MathXMLValidationError):
        canonicalize(mutate(doc(op("spec_t0", R))))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(profile_id="v999"),
        lambda p: p.update(schema_version="v999"),
        lambda p: p.update(extra=True),
        lambda p: p["symbols"].append(
            dict(
                cdbase="http://www.openmath.org/cd",
                cd="logic1",
                name="invented",
                signature="Prop",
                lean_meaning="unsound",
            )
        ),
        lambda p: p["symbols"].pop(),
        lambda p: p["symbols"][0].update(lean_meaning=""),
    ],
)
def test_registry_drift_rejected(mutate):
    payload = copy.deepcopy(_REGISTRY)
    mutate(payload)
    with pytest.raises(RuntimeError):
        _validate_registry(payload)


def test_bounds_canonicalization_and_alpha_equivalence():
    raw = doc(op("spec_t0", R))
    with pytest.raises(MathXMLValidationError):
        validate(raw)
    assert canonicalize(raw) == canonicalize(raw.replace('name="R"', 'name="A"'))
    with pytest.raises(MathXMLValidationError):
        canonicalize(" " * 65537)
    body = op("spec_t0", R)
    for _ in range(65):
        body = "<OMA>" + sym("logic1", "not") + body + "</OMA>"
    with pytest.raises(MathXMLValidationError):
        canonicalize(doc(body))


def test_all_cards_bundle_and_final_hashes():
    payload = json.loads((ROOT / "docs/commalg-v4-batch.json").read_text())
    cards = payload["cards"]
    e = payload["evidence"]
    assert len(cards) == 33
    for c in cards:
        validate(c["openmath_xml"])
    source = (
        "import Mathlib\n\n"
        + "\n\n".join(
            "-- manifest card: "
            + c["id"]
            + "\n"
            + c["lean_target"]
            + " := "
            + c["lean_witness"].rstrip()
            for c in cards
        )
        + "\n"
    )
    assert (ROOT / e["witness_path"]).read_text() == source
    paths = {
        "witness_sha256": e["witness_path"],
        "validator_sha256": "pals-agent/pals_agent/typed_commalg_v4.py",
        "registry_sha256": (
            "pals-agent/pals_agent/content_dictionaries/typed-commalg-v4-registry.json"
        ),
    }
    for key, path in paths.items():
        assert e[key] == "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def test_material_extension_hypotheses_and_variance():
    cards = {
        c["id"].removeprefix("commalg_v4_"): c
        for c in json.loads((ROOT / "docs/commalg-v4-batch.json").read_text())["cards"]
    }

    def names(key):
        return [e.get("name") for e in ET.fromstring(cards[key]["openmath_xml"]).iter(NS + "OMS")]

    normal = names("going_down_normal_domain")
    assert normal.count("domain") == 2
    assert all(normal.count(n) == 1 for n in ["integral", "integrally_closed", "ring_injective"])
    flat = names("going_down_flat")
    assert flat.count("flat") == 1
    assert all(n not in flat for n in ["integral", "domain", "ring_injective", "integrally_closed"])
    assert "ring_injective" in names("integral_lying_over")
    assert "ring_kernel" in names("integral_extension_proper")
    assert "ring_injective" not in names("integral_going_up")
    assert "noetherian" in names("dimension_polynomial_noetherian")
    c = ET.fromstring(cards["spectrum_comap_continuous"]["openmath_xml"])
    cont = next(e for e in c.iter(NS + "OMA") if e[0].get("name") == "continuous")
    pullback = cont[3]
    assert cont[1].get("name") == pullback[2].get("name")
    assert cont[2].get("name") == pullback[1].get("name")
    meanings = {x["name"]: x["lean_meaning"] for x in _REGISTRY["symbols"]}
    assert "WithBot" in meanings["dimension"]
    assert (
        "IsIrreducible" in meanings["is_irreducible"]
        and "nonemptiness" in meanings["is_irreducible"]
    )
    assert "Algebra R S" in meanings["Algebra"]
