"""Closed grammar rejection and independent mathematical argument-role checks."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError
from pals_agent.typed_calculus_v5 import (
    canonicalize_typed_calculus_v5_openmath_xml as canonicalize,
)
from pals_agent.typed_calculus_v5 import (
    validate_canonical_typed_calculus_v5_openmath_xml as validate_canonical,
)

ROOT = Path(__file__).resolve().parents[3]
BASE = "urn:pals:openmath:typed-calculus:v5"


def s(cd, name):
    base = BASE if cd in {"typed5", "calculus5"} else "http://www.openmath.org/cd"
    return f'<OMS cdbase="{base}" cd="{cd}" name="{name}"/>'


def v(name):
    return f'<OMV name="{name}"/>'


def a(cd, name, *args):
    return "<OMA>" + s(cd, name) + "".join(args) + "</OMA>"


def decl(name, sort):
    cd = "calculus5" if sort == "RealFunction" else "typed5"
    return (
        "<OMATTR><OMATP>" + s("typed5", "type") + s(cd, sort) + "</OMATP>" + v(name) + "</OMATTR>"
    )


def forall(declarations, body):
    return (
        "<OMBIND>"
        + s("typed5", "forall")
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
        (a("calculus5", "of_rat", "<OMI>1</OMI>", "<OMI>2</OMI>"), ()),
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
        forall([("f", "Real"), ("x", "Real")], a("calculus5", "continuous_at", v("f"), v("x"))),
        forall(
            [("f", "RealFunction"), ("x", "Nat")], a("calculus5", "continuous_at", v("f"), v("x"))
        ),
        forall([("f", "RealFunction")], a("calculus5", "continuous", v("f"), v("f"))),
        forall(
            [("f", "RealFunction"), ("x", "Real")], a("calculus5", "has_deriv_at", v("f"), v("x"))
        ),
        forall(
            [("n", "Nat")],
            a(
                "relation1",
                "eq",
                a("calculus5", "of_int", v("n")),
                a("calculus5", "of_nat", v("n")),
            ),
        ),
        forall([("x", "Real"), ("x", "Real")], a("relation1", "eq", v("x"), v("x"))),
        forall([("x", "Real")], v("x")),
        forall([("x", "Real")], a("calculus5", "opaque_mean_value_theorem", v("x"))),
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
    real = a("calculus5", "of_int", "<OMI>1</OMI>")
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
    payload = json.loads((ROOT / "docs/calculus-v5-batch.json").read_text())
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


def payload():
    return json.loads((ROOT / "docs/calculus-v5-batch.json").read_text())


def expressions(key, variables, operator):
    card = next(c for c in payload()["cards"] if c["id"] == "calculus_v5_" + key)
    root = ET.fromstring(card["openmath_xml"])
    names = dict(zip([d[-1].attrib["name"] for d in root[0][1]], variables.split(), strict=True))
    return [
        _decode(node, names)
        for node in root.iter()
        if _tag(node) == "OMA" and node[0].attrib.get("name") == operator
        # Exclude nested bound points for tests focusing on top-level formulas.
    ]


@pytest.mark.parametrize(
    "operator,variables,args",
    [
        ("limit_punctured", [("f", "RealFunction"), ("a", "Real")], [v("a"), v("f"), v("a")]),
        ("limit_left", [("f", "RealFunction"), ("a", "Real")], [v("f"), v("a")]),
        ("limit_right", [("f", "RealFunction"), ("n", "Nat")], [v("f"), v("n"), v("n")]),
        ("limit_at_top", [("f", "RealFunction"), ("a", "Real")], [v("f"), v("a"), v("a")]),
        (
            "continuous_on_image",
            [("f", "RealFunction"), ("a", "Real")],
            [v("f"), v("a"), v("a"), v("a")],
        ),
        ("monotone", [("a", "Real")], [v("a")]),
        ("deriv", [("a", "Real")], [v("a")]),
    ],
)
def test_new_operators_reject_wrong_slots_and_arity(operator, variables, args):
    with pytest.raises(MathXMLValidationError):
        canonicalize(xml(forall(variables, a("calculus5", operator, *args))))


def test_inverse_derivative_preserves_function_point_slope_order():
    assert expressions("inverse_derivative", "f g a u", "has_deriv_at") == [
        "has_deriv_at(f,apply(g,a),u)",
        "has_deriv_at(g,a,divide(of_int(1),u))",
    ]
    assert expressions("fundamental_theorem_lower_endpoint", "f a b", "has_deriv_at") == [
        "has_deriv_at(lambda(x,interval_integral(f,x,b)),a,unary_minus(apply(f,a)))"
    ]
    assert expressions("moving_both_endpoints", "f g h a u v", "has_deriv_at") == [
        "has_deriv_at(g,a,u)",
        "has_deriv_at(h,a,v)",
        "has_deriv_at(lambda(x,interval_integral(f,apply(g,x),apply(h,x))),a,minus(times(apply(f,apply(h,a)),v),times(apply(f,apply(g,a)),u)))",
    ]


def test_limit_roles_sides_and_image_order():
    assert expressions("two_sided_limit_characterization", "f a u", "limit_punctured") == [
        "limit_punctured(f,a,u)"
    ]
    assert expressions("two_sided_limit_characterization", "f a u", "limit_left") == [
        "limit_left(f,a,u)"
    ]
    assert expressions("two_sided_limit_characterization", "f a u", "limit_right") == [
        "limit_right(f,a,u)"
    ]
    assert expressions("removable_singularity_extension", "f a u", "continuous_at") == [
        "continuous_at(update_value(f,a,u),a)"
    ]
    assert expressions("local_image_substitution", "f g h a b", "continuous_on_image") == [
        "continuous_on_image(g,f,a,b)"
    ]
    assert expressions("derivative_difference_quotient_limit", "f a u", "limit_punctured") == [
        "limit_punctured(lambda(x,divide(minus(apply(f,plus(a,x)),apply(f,a)),x)),of_int(0),u)"
    ]
    assert expressions("lhopital_zero_right", "f g h k a b u", "limit_right") == [
        "limit_right(f,a,of_int(0))",
        "limit_right(g,a,of_int(0))",
        "limit_right(lambda(x,divide(apply(h,x),apply(k,x))),a,u)",
        "limit_right(lambda(x,divide(apply(f,x),apply(g,x))),a,u)",
    ]


def test_new_registry_operator_semantics_and_complete_pins():
    import hashlib

    p = payload()
    regpath = ROOT / "pals-agent/pals_agent/content_dictionaries/typed-calculus-v5-registry.json"
    registry = json.loads(regpath.read_text())
    rows = {r["name"]: r for r in registry["symbols"]}
    assert "point precedes slope" in rows["has_deriv_at"]["semantics"]
    assert "Ioi" in rows["limit_right"]["semantics"]
    assert "Iio" in rows["limit_left"]["semantics"]
    assert "Function.update" in rows["update_value"]["semantics"]
    assert "Totalized" in rows["interval_integral"]["semantics"]
    assert all(r["signature"] and r["semantics"] for r in registry["symbols"])
    assert len(p["cards"]) >= 40
    for card in p["cards"]:
        assert 4 <= len(card["sketch_steps"]) <= 10
        assert validate_canonical(card["openmath_xml"]) == card["openmath_xml"]
    expected = (
        "import Mathlib\n\n"
        + "\n\n".join(
            "-- manifest card: "
            + c["id"]
            + "\n"
            + c["lean_target"]
            + " := "
            + c["lean_witness"].rstrip()
            for c in p["cards"]
        )
        + "\n"
    )
    assert (ROOT / p["evidence"]["witness_path"]).read_text() == expected
    for key, path in [
        ("witness", ROOT / p["evidence"]["witness_path"]),
        ("validator", ROOT / "pals-agent/pals_agent/typed_calculus_v5.py"),
        ("registry", regpath),
    ]:
        assert (
            p["evidence"][key + "_sha256"]
            == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        )


def test_negatives_cover_cards_and_prior_batches_not_repeated_verbatim():
    p = payload()
    n = json.loads((ROOT / "docs/calculus-v5-negatives.json").read_text())
    assert n["status"] == "authored_candidates_not_retrieval_tested"
    assert {i for case in n["cases"] for i in case["paired_card_ids"]} == {
        c["id"] for c in p["cards"]
    }
    for path in [
        "calculus-reuse-batch-20260930.json",
        "calculus-v2-batch.json",
        "calculus-v3-batch.json",
        "calculus-v4-batch.json",
    ]:
        old = json.loads((ROOT / "docs" / path).read_text())["cards"]
        assert {c["lean_target"] for c in old}.isdisjoint({c["lean_target"] for c in p["cards"]})
        assert {c["canonical_statement"] for c in old}.isdisjoint(
            {c["canonical_statement"] for c in p["cards"]}
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda q: q.replace("http://www.openmath.org/OpenMath", "urn:bad"),
        lambda q: q.replace('version="2.0"', 'version="2.0" href="evil"'),
        lambda q: q.replace("<OMBVAR>", '<OMBVAR extra="1">'),
        lambda q: q.replace("<OMA>", "<OMA>unexpected", 1),
        lambda q: q.replace(BASE, BASE + "-wrong"),
    ],
)
def test_namespace_attributes_and_mixed_text_are_rejected(mutate):
    raw = power_proposition(v("n"), [("n", "Nat")])
    with pytest.raises(MathXMLValidationError):
        canonicalize(mutate(raw))


def test_counterexample_cards_are_actual_negated_propositions_and_general_parameters():
    assert expressions("counterexample_limit_without_continuity", "a u v", "limit_punctured") == [
        "limit_punctured(update_value(lambda(x,u),a,v),a,u)"
    ]
    assert expressions("counterexample_limit_without_continuity", "a u v", "not") == [
        "not(continuous_at(update_value(lambda(x,u),a,v),a))"
    ]
    assert expressions("counterexample_continuous_not_differentiable", "a", "not") == [
        "not(differentiable_at(lambda(x,abs(minus(x,a))),a))"
    ]
    assert expressions("counterexample_zero_integral_cancellation", "a b", "neq") == [
        "neq(minus(a,divide(plus(a,b),of_int(2))),of_int(0))"
    ]
