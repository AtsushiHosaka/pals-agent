"""Closed dependent dimensions, audit evidence and independently pinned semantic slots."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import pals_agent.typed_multivariable_v5 as module
from pals_agent.openmath import MathXMLValidationError
from pals_agent.typed_multivariable_v5 import (
    canonicalize_typed_multivariable_v5_openmath_xml as canon,
)
from pals_agent.typed_multivariable_v5 import (
    validate_canonical_typed_multivariable_v5_openmath_xml as valid,
)

ROOT = Path(__file__).resolve().parents[3]
BASE = module.CDBASE
PAYLOAD = json.loads((ROOT / "docs/multivariable-v5-batch.json").read_text())


def s(name, cd="multivar5"):
    base = BASE if cd in {"multivar5", "typed5"} else "http://www.openmath.org/cd"
    return f'<OMS cdbase="{base}" cd="{cd}" name="{name}"/>'


def v(name):
    return f'<OMV name="{name}"/>'


def a(name, *xs):
    return "<OMA>" + s(name) + "".join(xs) + "</OMA>"


def eq(x, y):
    return "<OMA>" + s("eq", "relation1") + x + y + "</OMA>"


def raw(body, extra=()):
    ds = [
        ("m", s("Nat")),
        ("n", s("Nat")),
        ("p", s("Nat")),
        ("k", s("Nat")),
        ("x", a("Vector", v("m"))),
        ("y", a("Vector", v("n"))),
        ("f", a("Function", v("m"), v("n"))),
        ("g", a("Function", v("n"), v("p"))),
        ("A", a("CLM", v("m"), v("n"))),
        ("B", a("Matrix", v("n"), v("m"))),
        ("i", a("Index", v("m"))),
        ("j", a("Index", v("n"))),
        ("t", s("Real")),
        ("q", a("ScalarFunction", v("m"))),
        ("D", a("DerivativeField", v("m"), v("m"))),
        ("s", a("Set", v("m"))),
        ("c", a("Curve", v("m"))),
        *extra,
    ]
    return (
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMBIND>'
        + s("forall", "typed5")
        + "<OMBVAR>"
        + "".join(
            "<OMATTR><OMATP>" + s("type", "typed5") + ty + "</OMATP>" + v(name) + "</OMATTR>"
            for name, ty in ds
        )
        + "</OMBVAR>"
        + body
        + "</OMBIND></OMOBJ>"
    )


@pytest.mark.parametrize("card", PAYLOAD["cards"], ids=lambda c: c["id"])
def test_all_authored_cards_are_canonical(card):
    assert valid(card["openmath_xml"]) == card["openmath_xml"]
    assert 4 <= len(card["sketch_steps"]) <= 10
    assert card["lean_target"].startswith("example ")
    assert card["lean_witness"].startswith("by")


@pytest.mark.parametrize(
    "term",
    [
        a("apply", v("m"), v("n"), v("f"), v("y")),
        a("apply", v("m"), v("p"), v("f"), v("x")),
        a("coordinate", v("m"), v("x"), v("j")),
        a("matrix_action", v("n"), v("m"), v("B"), v("y")),
        a("matrix_entry", v("n"), v("m"), v("B"), v("i"), v("j")),
        a("has_fderiv", v("m"), v("n"), v("f"), v("A"), v("x")),
        a("has_fderiv", v("m"), v("n"), v("f"), v("x")),
        a("has_fderiv", v("m"), v("n"), v("f"), v("x"), v("A"), v("A")),
        a("jacobian", v("m"), v("n"), v("f"), v("y")),
        a("compose", v("m"), v("n"), v("p"), v("f"), v("g")),
        a("jacobian_weighted", v("m"), v("f"), v("D"), v("q")),
        a("has_fderiv_within", v("m"), v("f"), v("x"), v("s"), v("A")),
        a("scalar_cont_diff", v("m"), v("t"), v("q")),
        a("scalar_cont_diff", v("m"), "<OMI>-1</OMI>", v("q")),
        a("coordinate", v("t"), v("x"), v("i")),
        a("coordinate", "<OMI>2</OMI>", v("x"), v("i")),
        a("apply", v("m"), v("n"), v("missing"), v("x")),
        a("fubini_theorem", v("f")),
        a("real_nat", v("t")),
        a("product_integrable", v("m"), v("n"), v("f")),
    ],
)
def test_invalid_dimensions_arity_scopes_and_opaque_predicates(term):
    with pytest.raises(MathXMLValidationError):
        canon(raw(eq(term, term)))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda q: q.replace(BASE, BASE + "x"),
        lambda q: q.replace("http://www.openmath.org/OpenMath", "urn:wrong"),
        lambda q: q.replace('version="2.0"', 'version="2.0" href="x"'),
        lambda q: q.replace('name="n"', 'name="m"'),
        lambda q: q.replace("<OMBVAR>", '<OMBVAR extra="1">'),
        lambda q: q.replace("<OMA>", "<OMA>text", 1),
    ],
)
def test_namespace_attributes_and_shadowing(mutate):
    with pytest.raises(MathXMLValidationError):
        canon(mutate(raw(eq(v("x"), v("x")))))


def test_dependent_types_must_use_prior_bound_naturals():
    for ty in [
        a("Vector", v("not_bound")),
        a("Vector", v("x")),
        a("Matrix", v("m")),
        a("Unknown", v("m")),
    ]:
        with pytest.raises(MathXMLValidationError):
            canon(raw(eq(v("x"), v("x")), extra=[("z", ty)]))
    assert valid(canon(raw(eq(v("x"), v("x")))))


def test_bounds_and_canonical_bytes():
    with pytest.raises(MathXMLValidationError):
        canon(" " * 65537)
    term = eq(v("x"), v("x"))
    for _ in range(65):
        term = "<OMA>" + s("not", "logic1") + term + "</OMA>"
    with pytest.raises(MathXMLValidationError):
        canon(raw(term))
    text = raw(eq(v("x"), v("x")))
    with pytest.raises(MathXMLValidationError):
        valid(text)
    assert canon(text) == canon(text.replace('name="m"', 'name="dimension"'))


def test_registry_rejects_additional_symbols_and_signature_drift(monkeypatch):
    original = json.loads(
        (
            ROOT / "pals-agent/pals_agent/content_dictionaries/typed-multivariable-v5-registry.json"
        ).read_text()
    )
    for kind in ["extra", "signature", "header"]:
        changed = json.loads(json.dumps(original))
        if kind == "extra":
            changed["symbols"].append(
                {
                    "cdbase": "http://www.openmath.org/cd",
                    "cd": "logic1",
                    "name": "invented",
                    "semantics": "unapproved",
                    "arity": 2,
                }
            )
        elif kind == "signature":
            entry = next(r for r in changed["symbols"] if r["name"] == "coordinate")
            entry["arguments"] = ["Real"]
        else:
            changed["profile_id"] = "other"
        with monkeypatch.context() as ctx:
            ctx.setattr(module.json, "loads", lambda _, payload=changed: payload)
            with pytest.raises(RuntimeError):
                canon(raw(eq(v("x"), v("x"))))


def expressions(key, variables, operator):
    card = next(c for c in PAYLOAD["cards"] if c["id"] == "mv_v5_" + key)
    root = ET.fromstring(card["openmath_xml"])
    names = dict(zip([d[-1].attrib["name"] for d in root[0][1]], variables.split(), strict=True))

    def render(node):
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "OMV":
            return names[node.attrib["name"]]
        if tag == "OMI":
            return node.text.strip()
        if tag == "OMA":
            return node[0].attrib["name"] + "(" + ",".join(render(c) for c in node[1:]) + ")"
        raise AssertionError(tag)

    return [
        render(e)
        for e in root.iter()
        if e.tag.endswith("}OMA") and e[0].attrib.get("name") == operator
    ]


def test_coordinate_derivative_point_slope_and_row_column_slots():
    assert expressions("coordinate_partial_from_total", "n f A x i", "has_deriv") == [
        "has_deriv(coordinate_slice(n,f,x,i),coordinate(n,x,i),dual_apply(n,A,basis_vector(n,i)))"
    ]
    assert expressions("jacobian_entries", "m n f x i j", "has_deriv") == [
        "has_deriv(coordinate_slice(m,component(m,n,f,j),x,i),coordinate(m,x,i),matrix_entry(n,m,jacobian(m,n,f,x),j,i))"
    ]
    target = next(c["lean_target"] for c in PAYLOAD["cards"] if c["id"] == "mv_v5_jacobian_entries")
    assert "toLinearMap j i) (x i)" in target


def test_jacobian_chain_order_is_p_by_n_times_n_by_m():
    assert expressions("jacobian_chain", "m n p f g x", "matrix_mul") == [
        "matrix_mul(p,n,m,jacobian(n,p,g,apply(m,n,f,x)),jacobian(m,n,f,x))"
    ]


def test_objective_constraint_and_derivative_field_order():
    assert expressions("lagrange_regular_constraint", "n f g A B x", "local_extr_fiber") == [
        "local_extr_fiber(n,g,f,x)"
    ]
    assert expressions(
        "lagrange_regular_constraint", "n f g A B x", "has_scalar_strict_fderiv"
    ) == ["has_scalar_strict_fderiv(n,f,x,A)", "has_scalar_strict_fderiv(n,g,x,B)"]
    assert expressions("jacobian_change_variables", "n f D s g", "jacobian_weighted") == [
        "jacobian_weighted(n,f,D,g)"
    ]


def test_integral_order_and_counterexample_hypotheses():
    assert expressions("fubini_order_exchange", "m n f", "integral") == [
        "integral(m,inner_integral_right(m,n,f))",
        "integral(n,inner_integral_left(m,n,f))",
    ]
    card = next(c for c in PAYLOAD["cards"] if c["id"] == "mv_v5_partials_without_continuity")
    assert "(ha : a ≠ 0)" in card["lean_target"]
    assert "¬ ContinuousAt f (0, 0)" in card["lean_target"]
    assert "axis_jump" in card["openmath_xml"]
    assert (
        expressions("partials_without_continuity", "m n i j a", "axis_jump")
        == ["axis_jump(m,n,i,j,a)"] * 3
    )


def test_exact_witness_and_pins():
    expected = (
        "import Mathlib\n\n"
        + "\n\n".join(
            "-- manifest card: "
            + c["id"]
            + "\n"
            + c["lean_target"]
            + " := "
            + c["lean_witness"].rstrip()
            for c in PAYLOAD["cards"]
        )
        + "\n"
    )
    assert (ROOT / PAYLOAD["evidence"]["witness_path"]).read_text() == expected
    paths = {
        "witness_sha256": PAYLOAD["evidence"]["witness_path"],
        "validator_sha256": "pals-agent/pals_agent/typed_multivariable_v5.py",
        "registry_sha256": (
            "pals-agent/pals_agent/content_dictionaries/typed-multivariable-v5-registry.json"
        ),
    }
    for key, path in paths.items():
        assert (
            PAYLOAD["evidence"][key]
            == "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        )


def test_negative_pairs_and_no_exact_prior_duplicates():
    negatives = json.loads((ROOT / "docs/multivariable-v5-negatives.json").read_text())
    assert negatives["status"] == "authored_candidates_not_retrieval_tested"
    ids = {c["id"] for c in PAYLOAD["cards"]}
    assert {i for n in negatives["cases"] for i in n["paired_card_ids"]} == ids
    assert len(negatives["cases"]) == len(ids) == 32
    previous = []
    for filename in [
        "calculus-reuse-batch-20260930.json",
        "calculus-v2-batch.json",
        "calculus-v3-batch.json",
        "calculus-v4-batch.json",
    ]:
        previous.extend(json.loads((ROOT / "docs" / filename).read_text())["cards"])
    for field in ["canonical_statement", "lean_target"]:
        assert not {c[field] for c in PAYLOAD["cards"]} & {c[field] for c in previous}


def test_path_integral_slots_and_essential_constraint_premise():
    assert expressions("potential_line_integral", "n f D c u a b", "interval_integral") == [
        "interval_integral(pullback_one_form(n,D,c,u),a,b)"
    ]
    assert expressions("lagrange_regular_constraint", "n f g A B x", "neq") == [
        "neq(A,dual_zero(n))"
    ]
    assert expressions("partials_without_continuity", "m n i j a", "neq") == ["neq(a,real_nat(0))"]
    target = next(
        c["lean_target"] for c in PAYLOAD["cards"] if c["id"] == "mv_v5_jacobian_change_variables"
    )
    assert "|(D x).det| * g (f x)" in target
