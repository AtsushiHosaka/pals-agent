"""Closed grammar rejection and independent mathematical argument-role checks."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError
from pals_agent.typed_calculus_v2 import (
    canonicalize_typed_calculus_v2_openmath_xml as canonicalize,
)
from pals_agent.typed_calculus_v2 import (
    validate_canonical_typed_calculus_v2_openmath_xml as validate_canonical,
)

ROOT = Path(__file__).resolve().parents[3]
BASE = "urn:pals:openmath:typed-calculus:v2"


def s(cd, name):
    base = BASE if cd in {"typed2", "calculus2"} else "http://www.openmath.org/cd"
    return f'<OMS cdbase="{base}" cd="{cd}" name="{name}"/>'


def v(name):
    return f'<OMV name="{name}"/>'


def a(cd, name, *args):
    return "<OMA>" + s(cd, name) + "".join(args) + "</OMA>"


def decl(name, sort):
    cd = "calculus2" if sort == "RealFunction" else "typed2"
    return (
        "<OMATTR><OMATP>" + s("typed2", "type") + s(cd, sort) + "</OMATP>" + v(name) + "</OMATTR>"
    )


def forall(declarations, body):
    return (
        "<OMBIND>"
        + s("typed2", "forall")
        + "<OMBVAR>"
        + "".join(decl(*d) for d in declarations)
        + "</OMBVAR>"
        + body
        + "</OMBIND>"
    )


def xml(body):
    return '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0">' + body + "</OMOBJ>"


def power_proposition(exponent, extra=()):
    power = a("arith1", "power", v("x"), exponent)
    return xml(forall([("x", "Real"), *extra], a("relation1", "eq", power, power)))


def test_variable_natural_exponent_is_supported_and_canonical_is_idempotent():
    raw = power_proposition(v("n"), [("n", "Nat")])
    result = canonicalize(raw)
    assert result == canonicalize(result) == validate_canonical(result)


@pytest.mark.parametrize(
    "exponent,extra",
    [
        ("<OMI>-1</OMI>", ()),
        ("<OMI>1.5</OMI>", ()),
        (a("calculus2", "of_rat", "<OMI>1</OMI>", "<OMI>2</OMI>"), ()),
        (v("n"), [("n", "Real")]),
        (v("unbound"), ()),
    ],
)
def test_natural_power_rejects_negative_fractional_real_and_unbound_exponents(exponent, extra):
    with pytest.raises(MathXMLValidationError):
        canonicalize(power_proposition(exponent, extra))


@pytest.mark.parametrize(
    "body",
    [
        forall([("f", "Real"), ("x", "Real")], a("calculus2", "continuous_at", v("f"), v("x"))),
        forall(
            [("f", "RealFunction"), ("x", "Nat")], a("calculus2", "continuous_at", v("f"), v("x"))
        ),
        forall([("f", "RealFunction")], a("calculus2", "continuous", v("f"), v("f"))),
        forall(
            [("f", "RealFunction"), ("x", "Real")], a("calculus2", "has_deriv_at", v("f"), v("x"))
        ),
        forall(
            [("n", "Nat")],
            a(
                "relation1",
                "eq",
                a("calculus2", "of_int", v("n")),
                a("calculus2", "of_nat", v("n")),
            ),
        ),
        forall([("x", "Real"), ("x", "Real")], a("relation1", "eq", v("x"), v("x"))),
        forall([("x", "Real")], v("x")),
        forall([("x", "Real")], a("calculus2", "opaque_mean_value_theorem", v("x"))),
    ],
)
def test_wrong_carrier_arity_bound_variables_cast_and_unknown_operator_are_rejected(body):
    with pytest.raises(MathXMLValidationError):
        canonicalize(xml(body))


def test_v1_cdbase_and_noncanonical_bytes_are_rejected():
    raw = power_proposition(v("n"), [("n", "Nat")])
    with pytest.raises(MathXMLValidationError):
        canonicalize(raw.replace(BASE, "urn:pals:openmath:typed-math:v1"))
    with pytest.raises(MathXMLValidationError):
        validate_canonical(raw)


def test_tree_and_application_resource_bounds():
    real = a("calculus2", "of_int", "<OMI>1</OMI>")
    value = a("arith1", "plus", *([real] * 33))
    with pytest.raises(MathXMLValidationError):
        canonicalize(xml(forall([("x", "Real")], a("relation1", "eq", v("x"), value))))
    deep = v("x")
    for _ in range(70):
        deep = a("arith1", "unary_minus", deep)
    with pytest.raises(MathXMLValidationError):
        canonicalize(xml(forall([("x", "Real")], a("relation1", "eq", v("x"), deep))))
    with pytest.raises(MathXMLValidationError):
        canonicalize(" " * 65537)


def test_all_authored_cards_are_exact_canonical_closed_propositions():
    payload = json.loads((ROOT / "docs/calculus-v2-batch.json").read_text())
    assert len(payload["cards"]) >= 25
    seen = set()
    for card in payload["cards"]:
        canonical = validate_canonical(card["openmath_xml"])
        assert canonical not in seen
        seen.add(canonical)


def _tag(node):
    return node.tag.rsplit("}", 1)[-1]


def _decode(node, names):
    if _tag(node) == "OMV":
        return names[node.attrib["name"]]
    if _tag(node) == "OMI":
        return node.text.strip()
    if _tag(node) == "OMA":
        return node[0].attrib["name"] + "(" + ",".join(_decode(n, names) for n in node[1:]) + ")"
    if _tag(node) == "OMBIND" and node[0].attrib["name"] == "lambda":
        name = node[1][0][-1].attrib["name"]
        return "lambda(x," + _decode(node[2], {**names, name: "x"}) + ")"
    raise AssertionError(ET.tostring(node, encoding="unicode"))


# Expected formulas independently specify the mathematical function, point,
# and slope. All slots have the same Real sort, so typing alone is insufficient.
@pytest.mark.parametrize(
    "key,variables,last",
    [
        (
            "natural_power_derivative",
            "n a",
            ("lambda(x,power(x,n))", "a", "times(of_nat(n),power(a,nat_pred(n)))"),
        ),
        (
            "natural_power_chain",
            "f n a u",
            (
                "lambda(x,power(apply(f,x),n))",
                "a",
                "times(times(of_nat(n),power(apply(f,a),nat_pred(n))),u)",
            ),
        ),
        ("exp_chain", "f a u", ("lambda(x,exp(apply(f,x)))", "a", "times(exp(apply(f,a)),u)")),
        ("log_chain", "f a u", ("lambda(x,log(apply(f,x)))", "a", "divide(u,apply(f,a))")),
        ("sin_chain", "f a u", ("lambda(x,sin(apply(f,x)))", "a", "times(cos(apply(f,a)),u)")),
        (
            "cos_chain",
            "f a u",
            ("lambda(x,cos(apply(f,x)))", "a", "times(unary_minus(sin(apply(f,a))),u)"),
        ),
        (
            "sqrt_chain",
            "f a u",
            ("lambda(x,sqrt(apply(f,x)))", "a", "divide(u,times(of_int(2),sqrt(apply(f,a))))"),
        ),
        (
            "arctan_chain",
            "f a u",
            (
                "lambda(x,arctan(apply(f,x)))",
                "a",
                "times(divide(of_int(1),plus(of_int(1),power(apply(f,a),2))),u)",
            ),
        ),
        (
            "fundamental_theorem_variable_upper",
            "f a b",
            ("lambda(x,interval_integral(f,a,x))", "b", "apply(f,b)"),
        ),
    ],
)
def test_derivative_semantic_slots_match_exact_formula(key, variables, last):
    cards = json.loads((ROOT / "docs/calculus-v2-batch.json").read_text())["cards"]
    card = next(c for c in cards if c["id"] == "calculus_v2_" + key)
    root = ET.fromstring(card["openmath_xml"])
    bound = [d[-1].attrib["name"] for d in root[0][1]]
    names = dict(zip(bound, variables.split(), strict=True))
    derivatives = [
        node
        for node in root.iter()
        if _tag(node) == "OMA" and node[0].attrib.get("name") == "has_deriv_at"
    ]
    actual = tuple(_decode(arg, names) for arg in derivatives[-1][1:])
    assert actual == last
    assert actual != (last[0], last[2], last[1])
    if key.endswith("_chain"):
        assert tuple(_decode(arg, names) for arg in derivatives[0][1:]) == ("f", "a", "u")


def test_registry_pins_totalized_integral_and_natural_predecessor_semantics():
    data = json.loads(
        (
            ROOT / "pals-agent/pals_agent/content_dictionaries/typed-calculus-v2-registry.json"
        ).read_text()
    )
    semantics = {e["name"]: e.get("semantics", "") for e in data["symbols"]}
    assert "Totalized" in semantics["interval_integral"]
    assert "truncated at zero" in semantics["nat_pred"]
    assert "point precedes slope" in semantics["has_deriv_at"]
