"""Closed planar carriers, exact evidence, orientation and hypothesis slot regression."""

from __future__ import annotations

import copy
import hashlib
import json
import runpy
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import pals_agent.typed_vector_calculus_v6 as module
from pals_agent.openmath import MathXMLValidationError
from pals_agent.typed_vector_calculus_v6 import (
    canonicalize_typed_vector_calculus_v6_openmath_xml as canon,
)
from pals_agent.typed_vector_calculus_v6 import (
    validate_canonical_typed_vector_calculus_v6_openmath_xml as valid,
)

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "docs/vector-calculus-v6-batch.json"
DATA = json.loads(PATH.read_text())
CARDS = {c["id"]: c for c in DATA["cards"]}
NS = {"om": "http://www.openmath.org/OpenMath"}
BASE = module.CDBASE


def symbol(name, cd="vector6"):
    base = BASE if cd in {"vector6", "typed6"} else module.STANDARD
    return f'<OMS cdbase="{base}" cd="{cd}" name="{name}"/>'


def var(name):
    return f'<OMV name="{name}"/>'


def app(name, *args):
    return "<OMA>" + symbol(name) + "".join(args) + "</OMA>"


def raw(body):
    ds = [
        ("f", "ScalarFunction"),
        ("A", "DualField"),
        ("z", "Point"),
        ("r", "Real"),
        ("s", "Set"),
        ("L", "Dual"),
    ]
    return (
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMBIND>'
        + symbol("forall", "typed6")
        + "<OMBVAR>"
        + "".join(
            "<OMATTR><OMATP>"
            + symbol("type", "typed6")
            + symbol(t)
            + "</OMATP>"
            + var(n)
            + "</OMATTR>"
            for n, t in ds
        )
        + "</OMBVAR>"
        + body
        + "</OMBIND></OMOBJ>"
    )


def apps(key, name):
    return [
        n
        for n in ET.fromstring(CARDS["vector_v6_" + key]["openmath_xml"]).findall(".//om:OMA", NS)
        if n[0].attrib.get("name") == name
    ]


@pytest.mark.parametrize("card", DATA["cards"], ids=lambda c: c["id"])
def test_all_cards_canonical(card):
    assert valid(card["openmath_xml"]) == card["openmath_xml"]
    assert 4 <= len(card["sketch_steps"]) <= 10
    assert card["lean_target"].startswith("example ")
    assert card["lean_witness"].startswith("by\n")


@pytest.mark.parametrize(
    "body",
    [
        app("has_fderiv", var("f"), var("L"), var("z")),
        app("has_fderiv", var("f"), var("z"), var("A")),
        app("has_fderiv", var("f"), var("z")),
        app("apply", var("f"), var("r")),
        app("continuous_on", var("f"), var("z")),
        app("boundary_flux", var("f"), var("f"), var("z"), var("r")),
        app("set_integral", var("f"), var("z")),
        app("interval_integral", var("f"), var("r"), var("r")),
        app("member", var("unbound"), var("s")),
        app("has_fderiv", var("f"), var("z"), symbol("ScalarFunction")),
    ],
)
def test_type_arity_closure_rejections(body):
    with pytest.raises(MathXMLValidationError):
        canon(raw(body))


def test_valid_actual_derivative_slot_order_and_zero_constant():
    x = raw(app("has_fderiv", var("f"), var("z"), symbol("zero_dual")))
    assert valid(canon(x)) == canon(x)


@pytest.mark.parametrize(
    "mutation", ["base", "namespace", "attribute", "shadow", "binder", "bytes", "depth"]
)
def test_strict_syntax_limits(mutation):
    x = raw(app("has_fderiv", var("f"), var("z"), var("L")))
    if mutation == "base":
        x = x.replace(BASE, BASE + "/forged")
    elif mutation == "namespace":
        x = x.replace("http://www.openmath.org/OpenMath", "http://www.openmath.org/OpenMath/forged")
    elif mutation == "attribute":
        x = x.replace('<OMV name="f"', '<OMV forged="yes" name="f"', 1)
    elif mutation == "shadow":
        x = x.replace('name="A"', 'name="f"')
    elif mutation == "binder":
        x = x.replace('name="forall"', 'name="type"', 1)
    elif mutation == "bytes":
        x += " " * (module.MAX_BYTES + 1)
    else:
        body = app("has_fderiv", var("f"), var("z"), var("L"))
        for _ in range(module.MAX_DEPTH):
            body = "<OMA>" + symbol("not", "logic1") + body + "</OMA>"
        x = raw(body)
    with pytest.raises(MathXMLValidationError):
        canon(x)


@pytest.mark.parametrize("mutation", ["header", "extra_symbol", "signature", "missing_semantics"])
def test_registry_drift_fails_closed(monkeypatch, mutation):
    data = json.loads(
        (
            ROOT
            / "pals-agent/pals_agent/content_dictionaries/typed-vector-calculus-v6-registry.json"
        ).read_text()
    )
    if mutation == "header":
        data["profile_id"] = "wrong"
    elif mutation == "extra_symbol":
        data["symbols"].append(
            {
                "cdbase": module.STANDARD,
                "cd": "logic1",
                "name": "forged",
                "arity": 2,
                "semantics": "forged",
            }
        )
    elif mutation == "signature":
        next(x for x in data["symbols"] if x["name"] == "curl")["arguments"] = [
            "ScalarFunction",
            "ScalarFunction",
        ]
    else:
        data["symbols"][0]["semantics"] = ""
    monkeypatch.setattr(module.json, "loads", lambda _: data)
    with pytest.raises(RuntimeError):
        module._registry()


def test_bundle_evidence_and_loader():
    from pals_agent.typed_catalog_expansion import validate_expansion_batch

    validate_expansion_batch(DATA, repository_root=ROOT)
    expected = (
        "import Mathlib\n\n"
        + "\n\n".join(
            "-- manifest card: "
            + c["id"]
            + "\n"
            + c["lean_target"]
            + " := "
            + c["lean_witness"].rstrip()
            for c in DATA["cards"]
        )
        + "\n"
    )
    assert (ROOT / DATA["evidence"]["witness_path"]).read_text() == expected
    for key, path in [
        ("witness_sha256", DATA["evidence"]["witness_path"]),
        ("validator_sha256", "pals-agent/pals_agent/typed_vector_calculus_v6.py"),
        (
            "registry_sha256",
            "pals-agent/pals_agent/content_dictionaries/typed-vector-calculus-v6-registry.json",
        ),
    ]:
        assert (
            DATA["evidence"][key]
            == "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        )


def test_generator_exact_cards():
    assert (
        runpy.run_path(str(ROOT / "pals-scripts/generate-vector-calculus-v6-batch.py"))["cards"]
        == DATA["cards"]
    )


def test_green_direction_countable_exception_and_actual_derivative_slots():
    key = "green_countable_exceptions"
    assert apps(key, "countable")
    assert len(apps(key, "set_difference")) == 2
    assert len(apps(key, "continuous_on")) == 2
    curl = apps(key, "curl")[0]
    assert [c.attrib["name"] for c in curl[1:]] == ["v3", "v4"]
    derivative = apps(key, "has_fderiv")[0]
    assert derivative[1].attrib["name"] == "v1"
    assert derivative[2].attrib["name"] == "v8"
    assert derivative[3][0].attrib["name"] == "field_apply"
    target = CARDS["vector_v6_" + key]["lean_target"]
    assert "B z (1,0) - A z (0,1)" in target
    assert "s.Countable" in target
    assert "MeasureTheory.IntegrableOn" in target


def test_closed_rectangle_continuity_not_only_interior():
    for key in ["gauss_rectangle", "green_countable_exceptions", "c1_gauss_hypotheses"]:
        assert all(
            n[-1][0].attrib["name"] == "closed_rectangle" for n in apps(key, "continuous_on")
        )


def test_affine_trace_and_signed_rectangle_convention():
    target = CARDS["vector_v6_affine_flux"]["lean_target"]
    assert "(α+δ)*(b.1-a.1)*(b.2-a.2)" in target
    assert "hab" not in target
    registry = json.loads(
        (
            ROOT
            / "pals-agent/pals_agent/content_dictionaries/typed-vector-calculus-v6-registry.json"
        ).read_text()
    )
    meanings = {x["name"]: x["semantics"] for x in registry["symbols"]}
    assert "top−bottom+right−left" in meanings["boundary_flux"]
    assert "counterclockwise" in meanings["boundary_circulation"]


def test_boundaries_counterexample_nonzero_width_height_and_amplitude():
    card = CARDS["vector_v6_missing_boundary_continuity"]
    assert len(apps("missing_boundary_continuity", "lt")) == 2
    assert "hc : c ≠ 0" in card["lean_target"]
    assert "HasFDerivAt f (0" in card["lean_target"]
    assert not apps("missing_boundary_continuity", "continuous_on")


def test_negative_pairs_and_explicit_bindings():
    negatives = json.loads((ROOT / "docs/vector-calculus-v6-negatives.json").read_text())
    assert sorted(i for c in negatives["cases"] for i in c["paired_card_ids"]) == sorted(CARDS)
    bindings = json.loads((ROOT / "docs/vector-calculus-v6-bindings.json").read_text())["bindings"]
    assert {b["draft_id"] for b in bindings} == set(CARDS)
    assert {b["primary_mode"] for b in bindings} == {
        "recognize",
        "compute_construct",
        "justify_prove",
        "counterexample_audit",
    }
    assert {b["difficulty"] for b in bindings} == {"introductory", "standard", "advanced"}


def test_tampered_witness_rejected_by_loader():
    from pals_agent.typed_catalog_expansion import validate_expansion_batch

    payload = copy.deepcopy(DATA)
    payload["cards"][1]["lean_target"] = payload["cards"][1]["lean_target"].replace(
        "B z (1,0) - A z (0,1)", "A z (0,1) - B z (1,0)"
    )
    with pytest.raises(ValueError):
        validate_expansion_batch(payload, repository_root=ROOT)
