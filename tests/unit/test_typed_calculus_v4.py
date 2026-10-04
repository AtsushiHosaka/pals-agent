"""Closed multivariable carriers and independently specified semantic alignment."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError
from pals_agent.typed_calculus_v4 import _SIGNATURES, _TYPE_SIGNATURES, CDBASE
from pals_agent.typed_calculus_v4 import canonicalize_typed_calculus_v4_openmath_xml as canon
from pals_agent.typed_calculus_v4 import validate_canonical_typed_calculus_v4_openmath_xml as valid

ROOT = Path(__file__).resolve().parents[3]


def s(n, cd="calculus4"):
    base = CDBASE if cd in ("typed4", "calculus4") else "http://www.openmath.org/cd"
    return f'<OMS cdbase="{base}" cd="{cd}" name="{n}"/>'


def v(n):
    return f'<OMV name="{n}"/>'


def a(n, *xs):
    return "<OMA>" + s(n) + "".join(xs) + "</OMA>"


def eq(x, y):
    return "<OMA>" + s("eq", "relation1") + x + y + "</OMA>"


def raw(body, extra=()):
    ds = [
        ("E", s("RealInnerProductSpace")),
        ("F", s("RealInnerProductSpace")),
        ("G", s("RealInnerProductSpace")),
        ("f", a("Function", v("E"), v("F"))),
        ("g", a("Function", v("F"), v("G"))),
        ("A", a("CLM", v("E"), v("F"))),
        ("B", a("CLM", v("F"), v("G"))),
        ("x", a("Vector", v("E"))),
        ("y", a("Vector", v("F"))),
        ("n", s("Nat")),
        ("t", s("Real")),
        ("p", a("ScalarFunction", v("E"))),
        ("D", a("DerivativeField", v("E"), v("F"))),
        ("H", a("Bilinear", v("E"), v("F"))),
        *extra,
    ]
    return (
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMBIND>'
        + s("forall", "typed4")
        + "<OMBVAR>"
        + "".join(
            "<OMATTR><OMATP>" + s("type", "typed4") + ty + "</OMATP>" + v(n) + "</OMATTR>"
            for n, ty in ds
        )
        + "</OMBVAR>"
        + body
        + "</OMBIND></OMOBJ>"
    )


@pytest.mark.parametrize(
    "term",
    [
        a("apply", v("E"), v("F"), v("f"), v("y")),
        a("apply", v("E"), v("G"), v("f"), v("x")),
        a("clm_apply", v("E"), v("F"), v("f"), v("x")),
        a("clm_compose", v("E"), v("F"), v("G"), v("A"), v("B")),
        a("compose", v("E"), v("F"), v("G"), v("f"), v("g")),
        a("adjoint_apply", v("E"), v("F"), v("A"), v("x")),
        a("has_gradient", v("E"), v("p"), v("x"), v("y")),
        a("has_fderiv", v("E"), v("F"), v("f"), v("A"), v("x")),
        a("has_fderiv", v("E"), v("F"), v("f"), v("x")),
        a("has_fderiv", v("E"), v("F"), v("f"), v("x"), v("A"), v("A")),
        a("has_second_deriv", v("E"), v("F"), v("A"), v("x"), v("H")),
        a("has_second_deriv", v("E"), v("G"), v("D"), v("x"), v("H")),
        a("bilinear_apply", v("E"), v("F"), v("H"), v("x"), v("y")),
        a("cont_diff", v("E"), v("F"), "<OMI>-1</OMI>", v("f")),
        a("cont_diff", v("E"), v("F"), v("t"), v("f")),
        a("cont_diff", v("E"), v("F"), '<OMF dec="0.5"/>', v("f")),
        a("norm", v("E"), v("free")),
        a("frechet_chain_theorem", v("f")),
        a("inner", v("E"), v("x"), v("y")),
        a("curve_apply", v("E"), v("f"), v("t")),
        a("real_nat", v("t")),
        a("field_apply", v("E"), v("F"), v("H"), v("x")),
    ],
)
def test_invalid_carriers_arity_sorts_and_free_variables(term):
    with pytest.raises(MathXMLValidationError):
        canon(raw(eq(term, term)))


def test_natural_smoothness_and_composite_carriers_roundtrip():
    q = raw(
        a("cont_diff", v("E"), v("G"), v("n"), a("compose", v("E"), v("F"), v("G"), v("g"), v("f")))
    )
    assert valid(canon(q)) == canon(q)
    assert canon(q.replace('name="E"', 'name="Domain"')) == canon(q)
    with pytest.raises(MathXMLValidationError):
        valid(q)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda q: q.replace(CDBASE, CDBASE + "x"),
        lambda q: q.replace("http://www.openmath.org/OpenMath", "urn:wrong"),
        lambda q: q.replace('version="2.0"', 'version="2.0" href="evil"'),
        lambda q: q.replace('name="F"', 'name="E"'),
        lambda q: q.replace("<OMBVAR>", '<OMBVAR extra="1">'),
        lambda q: q.replace("<OMA>", "<OMA>unexpected", 1),
    ],
)
def test_namespace_scope_and_structure(mutate):
    with pytest.raises(MathXMLValidationError):
        canon(mutate(raw(eq(v("x"), v("x")))))


def test_resource_bounds_and_nominal_type_declarations():
    with pytest.raises(MathXMLValidationError):
        canon(" " * 65537)
    with pytest.raises(MathXMLValidationError):
        canon(raw(eq(v("x"), v("x")), extra=[("x", a("Vector", v("E")))]))
    body = eq(v("x"), v("x"))
    for _ in range(66):
        body = "<OMA>" + s("not", "logic1") + body + "</OMA>"
    with pytest.raises(MathXMLValidationError):
        canon(raw(body))
    with pytest.raises(MathXMLValidationError):
        canon(raw(eq(v("x"), v("x")), extra=[("q", a("Function", v("E"), v("n")))]))


def payload():
    return json.loads((ROOT / "docs/calculus-v4-batch.json").read_text())


def tag(e):
    return e.tag.rsplit("}", 1)[-1]


def render(e, names):
    if tag(e) == "OMV":
        return names[e.attrib["name"]]
    if tag(e) == "OMI":
        return e.text.strip()
    if tag(e) == "OMA":
        return e[0].attrib["name"] + "(" + ",".join(render(c, names) for c in e[1:]) + ")"
    raise AssertionError(tag(e))


def expressions(key, variables, operator):
    card = next(c for c in payload()["cards"] if c["id"] == "calculus_v4_" + key)
    root = ET.fromstring(card["openmath_xml"])
    names = dict(zip([d[-1].attrib["name"] for d in root[0][1]], variables.split(), strict=True))
    return [
        render(e, names)
        for e in root.iter()
        if tag(e) == "OMA" and e[0].attrib.get("name") == operator
    ]


def test_gradient_and_chain_slots_have_independent_semantic_expectations():
    assert expressions("chain_rule", "E F G f A x g B", "has_fderiv") == [
        "has_fderiv(E,F,f,x,A)",
        "has_fderiv(F,G,g,apply(E,F,f,x),B)",
        "has_fderiv(E,G,compose(E,F,G,g,f),x,clm_compose(E,F,G,B,A))",
    ]
    assert expressions("gradient_adjoint_chain", "E F g f A x u", "has_gradient") == [
        "has_gradient(F,f,apply(E,F,g,x),u)",
        "has_gradient(E,scalar_compose(E,F,f,g),x,adjoint_apply(E,F,A,u))",
    ]
    assert expressions("gradient_along_curve", "E f c t u w", "has_real_deriv") == [
        "has_real_deriv(scalar_curve_compose(E,f,c),t,inner(E,w,u))"
    ]
    assert expressions("directional_from_frechet", "E F f A x u", "has_line_deriv") == [
        "has_line_deriv(E,F,f,x,u,clm_apply(E,F,A,u))"
    ]


def test_second_derivative_and_actual_directional_slope():
    assert expressions("second_derivative_symmetry", "E F f D H x u w", "has_second_deriv") == [
        "has_second_deriv(E,F,D,x,H)"
    ]
    assert expressions("second_derivative_symmetry", "E F f D H x u w", "bilinear_apply") == [
        "bilinear_apply(E,F,H,u,w)",
        "bilinear_apply(E,F,H,w,u)",
    ]
    assert expressions("gradient_direction_bound", "E f x u w", "scalar_line_deriv") == [
        "scalar_line_deriv(E,f,x,w)"
    ]


def test_registry_semantics_signatures_and_complete_evidence():
    p = payload()
    r = json.loads(
        (
            ROOT / "pals-agent/pals_agent/content_dictionaries/typed-calculus-v4-registry.json"
        ).read_text()
    )
    rows = {e["name"]: e for e in r["symbols"] if e["cd"] == "calculus4"}
    for n, (args, result) in {**_TYPE_SIGNATURES, **_SIGNATURES}.items():
        assert rows[n]["arguments"] == list(args) and rows[n]["result"] == result
    assert all(e["semantics"] for e in r["symbols"])
    assert "POINT,GRADIENT" in rows["has_gradient"]["semantics"]
    assert "totalized" in rows["scalar_line_deriv"]["semantics"]
    assert "∀ x" in rows["derivative_field"]["semantics"]
    cards = p["cards"]
    assert len(cards) >= 30
    assert len({c["openmath_xml"] for c in cards}) == len(cards)
    for c in cards:
        assert valid(c["openmath_xml"]) == c["openmath_xml"]
        assert 4 <= len(c["sketch_steps"]) <= 10
    expected = (
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
    assert (ROOT / p["evidence"]["witness_path"]).read_text() == expected
    for k, path in [
        ("witness", p["evidence"]["witness_path"]),
        ("validator", "pals-agent/pals_agent/typed_calculus_v4.py"),
        ("registry", "pals-agent/pals_agent/content_dictionaries/typed-calculus-v4-registry.json"),
    ]:
        assert (
            p["evidence"][k + "_sha256"]
            == "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        )


def test_negatives_cover_all_cards_and_no_old_card_is_repeated_verbatim():
    p = payload()
    neg = json.loads((ROOT / "docs/calculus-v4-negatives.json").read_text())
    assert neg["status"] == "authored_candidates_not_retrieval_tested"
    assert {i for c in neg["cases"] for i in c["paired_card_ids"]} == {c["id"] for c in p["cards"]}
    for path in [
        "docs/calculus-v3-batch.json",
        "docs/calculus-v2-batch.json",
        "docs/calculus-reuse-batch-20260930.json",
    ]:
        old = json.loads((ROOT / path).read_text())["cards"]
        assert {c["lean_target"] for c in p["cards"]}.isdisjoint({c["lean_target"] for c in old})
        assert {c["canonical_statement"] for c in p["cards"]}.isdisjoint(
            {c["canonical_statement"] for c in old}
        )
