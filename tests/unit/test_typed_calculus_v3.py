"""Closed sequence/Taylor typing and independently specified semantic slot checks."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError
from pals_agent.typed_calculus_v3 import canonicalize_typed_calculus_v3_openmath_xml as canonicalize
from pals_agent.typed_calculus_v3 import (
    validate_canonical_typed_calculus_v3_openmath_xml as validate,
)

ROOT = Path(__file__).resolve().parents[3]
BASE = "urn:pals:openmath:typed-calculus:v3"


def sym(cd, name):
    base = BASE if cd in {"typed3", "calculus3"} else "http://www.openmath.org/cd"
    return f'<OMS cdbase="{base}" cd="{cd}" name="{name}"/>'


def var(n):
    return f'<OMV name="{n}"/>'


def app(name, *xs):
    return "<OMA>" + sym("calculus3", name) + "".join(xs) + "</OMA>"


def eq(a, b):
    return "<OMA>" + sym("relation1", "eq") + a + b + "</OMA>"


def binder(kind, vs, body):
    ds = "".join(
        "<OMATTR><OMATP>"
        + sym("typed3", "type")
        + sym("calculus3" if typ in {"RealFunction", "RealSequence"} else "typed3", typ)
        + "</OMATP>"
        + var(n)
        + "</OMATTR>"
        for n, typ in vs
    )
    return (
        "<OMBIND>"
        + sym("calculus3" if kind in {"lambda", "sequence_lambda"} else "typed3", kind)
        + "<OMBVAR>"
        + ds
        + "</OMBVAR>"
        + body
        + "</OMBIND>"
    )


def doc(body, vs=(("u", "RealSequence"), ("f", "RealFunction"), ("n", "Nat"), ("x", "Real"))):
    return (
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0">'
        + binder("forall", vs, body)
        + "</OMOBJ>"
    )


def real(n):
    return app("of_int", f"<OMI>{n}</OMI>")


@pytest.mark.parametrize(
    "bad",
    [
        app("sequence_apply", var("f"), var("n")),
        app("sequence_apply", var("u"), var("x")),
        app("sequence_apply", var("u"), "<OMI>-1</OMI>"),
        app("partial_sum", var("u"), app("of_rat", "<OMI>1</OMI>", "<OMI>2</OMI>")),
        app("summable", var("f")),
        app("has_sum", var("u"), var("n")),
        app("sequence_limit", var("u")),
        app("cont_diff_on", var("x"), var("f"), var("x"), var("x")),
        app("taylor_on", var("n"), var("u"), var("x"), var("x"), var("x"), var("x")),
        app("taylor_on", var("n"), var("f"), var("x"), var("x"), var("x")),
        app("iterated_deriv_on", "<OMI>-1</OMI>", var("f"), var("x"), var("x")),
        app("nat_factorial", var("x")),
        app("summable", var("not_bound")),
        binder("sequence_lambda", [("j", "Real")], var("j")),
        binder("sequence_lambda", [("j", "Nat")], var("j")),
        binder("lambda", [("j", "Nat")], real(1)),
        app("opaque_taylor_theorem", var("f")),
    ],
)
def test_wrong_sorts_arity_scope_and_opaque_symbols_rejected(bad):
    with pytest.raises(MathXMLValidationError):
        canonicalize(doc(eq(bad, bad)))


def test_sequence_lambda_and_variable_nat_operations_are_supported():
    seq = binder("sequence_lambda", [("j", "Nat")], app("of_nat", app("nat_factorial", var("j"))))
    raw = doc(app("has_sum", seq, real(1)))
    # Typing accepts even a false assertion: this is not a truth checker.
    assert validate(canonicalize(raw)) == canonicalize(raw)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.replace(BASE, "urn:pals:openmath:typed-calculus:v2"),
        lambda s: s.replace("http://www.openmath.org/OpenMath", "urn:wrong"),
        lambda s: s.replace('name="summable"', 'name="summable" extra="1"'),
        lambda s: s.replace('name="n"', 'name="x"'),
    ],
)
def test_namespace_attributes_and_redeclared_binders_rejected(mutate):
    with pytest.raises(MathXMLValidationError):
        canonicalize(mutate(doc(app("summable", var("u")))))


def test_size_depth_and_exact_canonical_guards():
    with pytest.raises(MathXMLValidationError):
        canonicalize(" " * 65537)
    raw = doc(app("summable", var("u")))
    with pytest.raises(MathXMLValidationError):
        validate(raw)
    body = app("summable", var("u"))
    for _ in range(65):
        body = "<OMA>" + sym("logic1", "not") + body + "</OMA>"
    with pytest.raises(MathXMLValidationError):
        canonicalize(doc(body))


def cards():
    return json.loads((ROOT / "docs/calculus-v3-batch.json").read_text())["cards"]


def test_entire_compiled_batch_is_canonical_unique_and_has_complete_steps():
    cs = cards()
    assert len(cs) >= 30
    assert len({c["openmath_xml"] for c in cs}) == len(cs)
    for c in cs:
        validate(c["openmath_xml"])
        assert 4 <= len(c["sketch_steps"]) <= 10
    source = (
        "import Mathlib\n\n"
        + "\n\n".join(
            "-- manifest card: "
            + c["id"]
            + "\n"
            + c["lean_target"]
            + " := "
            + c["lean_witness"].rstrip()
            for c in cs
        )
        + "\n"
    )
    assert source == (ROOT / "docs/calculus-v3-batch.lean").read_text()


def tag(e):
    return e.tag.rsplit("}", 1)[-1]


def render(e, names):
    if tag(e) == "OMV":
        return names[e.attrib["name"]]
    if tag(e) == "OMI":
        return e.text.strip()
    if tag(e) == "OMA":
        return e[0].attrib["name"] + "(" + ",".join(render(x, names) for x in e[1:]) + ")"
    if tag(e) == "OMBIND" and e[0].attrib["name"] in {"lambda", "sequence_lambda"}:
        kind = e[0].attrib["name"]
        alias = "i" if kind == "sequence_lambda" else "y"
        return (
            kind
            + "("
            + alias
            + ","
            + render(e[2], {**names, e[1][0][-1].attrib["name"]: alias})
            + ")"
        )
    raise AssertionError(ET.tostring(e, encoding="unicode"))


def applications(key, variables, operator):
    c = next(c for c in cards() if c["id"] == "calculus_v3_" + key)
    root = ET.fromstring(c["openmath_xml"])
    names = dict(zip([d[-1].attrib["name"] for d in root[0][1]], variables.split(), strict=True))
    return [
        render(e, names)
        for e in root.iter()
        if tag(e) == "OMA" and e[0].attrib.get("name") == operator
    ]


def test_partial_sums_and_exponential_series_are_not_sequence_term_limits():
    assert applications("partial_sums_limit", "u a", "sequence_limit") == [
        "sequence_limit(sequence_lambda(i,partial_sum(u,i)),a)"
    ]
    assert applications("exponential_power_series", "a", "has_sum") == [
        "has_sum(sequence_lambda(i,divide(power(a,i),of_nat(nat_factorial(i)))),exp(a))"
    ]
    assert applications("summable_terms_zero", "u", "sequence_limit") == [
        "sequence_limit(u,of_int(0))"
    ]
    assert not applications("summable_terms_zero", "u", "has_sum")


def test_taylor_degree_center_domain_and_derivative_slots_are_exact():
    assert applications("taylor_polynomial_derivative", "f n a b c x", "has_deriv_at") == [
        "has_deriv_at(lambda(y,taylor_on(nat_succ(n),f,a,b,c,y)),x,taylor_on(n,iterated_deriv_on(1,f,a,b),a,b,c,x))"
    ]
    assert applications("taylor_finite_expansion", "f n a b c x", "partial_sum") == [
        "partial_sum(sequence_lambda(i,times(divide(power(minus(x,c),i),of_nat(nat_factorial(i))),apply(iterated_deriv_on(i,f,a,b),c))),nat_succ(n))"
    ]
    assert applications("taylor_integral_remainder", "f n a b", "cont_diff_on") == [
        "cont_diff_on(nat_succ(n),f,a,b)"
    ]
    assert applications("taylor_integral_remainder", "f n a b", "interval_integral") == [
        "interval_integral(lambda(y,times(divide(power(minus(b,y),n),of_nat(nat_factorial(n))),apply(iterated_deriv_on(nat_succ(n),f,a,b),y))),a,b)"
    ]


def test_registry_distinguishes_unconditional_sum_and_ordered_convergence():
    d = json.loads(
        (
            ROOT / "pals-agent/pals_agent/content_dictionaries/typed-calculus-v3-registry.json"
        ).read_text()
    )
    entries = {e["name"]: e for e in d["symbols"]}
    assert all(e.get("signature") and e.get("semantics") for e in d["symbols"])
    assert "UNCONDITIONAL" in entries["has_sum"]["semantics"]
    assert "Conditional ordered convergence" in entries["summable"]["semantics"]
    assert "totalized as zero" in entries["tsum"]["semantics"]
    assert "0 through n-1" in entries["partial_sum"]["semantics"]
    assert "a,b fix the differentiation domain" in entries["taylor_on"]["semantics"]


def test_lagrange_uses_strict_endpoints_and_global_successor_derivative():
    key = "taylor_lagrange_remainder"
    assert applications(key, "f n a b", "cont_diff_on") == ["cont_diff_on(nat_succ(n),f,a,b)"]
    assert applications(key, "f n a b", "iterated_deriv") == ["iterated_deriv(nat_succ(n),f)"]
    assert not applications(key, "f n a b", "iterated_deriv_on")
    c = next(c for c in cards() if c["id"] == "calculus_v3_" + key)
    root = ET.fromstring(c["openmath_xml"])
    names = dict(zip([d[-1].attrib["name"] for d in root[0][1]], ["f", "n", "a", "b"], strict=True))
    existential = next(
        e for e in root.iter() if tag(e) == "OMBIND" and e[0].attrib["name"] == "exists"
    )
    names[existential[1][0][-1].attrib["name"]] = "c"
    strict = [
        render(e, names) for e in root.iter() if tag(e) == "OMA" and e[0].attrib.get("name") == "lt"
    ]
    assert strict == ["lt(a,b)", "lt(a,c)", "lt(c,b)"]


def test_zero_natural_degree_and_empty_partial_sum_are_well_typed():
    zero = "<OMI>0</OMI>"
    taylor = app("taylor_on", zero, var("f"), var("x"), var("x"), var("x"), var("x"))
    assert validate(canonicalize(doc(eq(taylor, taylor))))
    partial = app("partial_sum", var("u"), zero)
    assert validate(canonicalize(doc(eq(partial, partial))))


def test_hard_negatives_cover_the_entire_batch_without_claiming_retrieval_pass():
    d = json.loads((ROOT / "docs/calculus-v3-negatives.json").read_text())
    assert d["status"] == "authored_candidates_not_retrieval_tested"
    assert {i for c in d["cases"] for i in c["paired_card_ids"]} == {c["id"] for c in cards()}
    assert all(c["candidate_question"] and c["mathematical_reason"] for c in d["cases"])
