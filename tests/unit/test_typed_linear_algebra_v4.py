"""Matrix dimensions, scalar fields, polynomial roles, bounds and evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError
from pals_agent.typed_linear_algebra_v4 import CDBASE, MAX_BYTES
from pals_agent.typed_linear_algebra_v4 import (
    canonicalize_typed_linear_algebra_v4_openmath_xml as canon,
)
from pals_agent.typed_linear_algebra_v4 import (
    validate_canonical_typed_linear_algebra_v4_openmath_xml as valid,
)

ROOT = Path(__file__).resolve().parents[3]
NS = "http://www.openmath.org/OpenMath"


def s(n, cd="la4", base=CDBASE):
    return f'<OMS cdbase="{base}" cd="{cd}" name="{n}"/>'


def v(n):
    return f'<OMV name="{n}"/>'


def a(n, *args):
    return "<OMA>" + s(n) + "".join(args) + "</OMA>"


def rel(n, x, y):
    return "<OMA>" + s(n, "relation1", "http://www.openmath.org/cd") + x + y + "</OMA>"


def doc(ds, body):
    attrs = "".join(
        "<OMATTR><OMATP>" + s("type", "typed1") + t + "</OMATP>" + v(n) + "</OMATTR>" for n, t in ds
    )
    return (
        f'<OMOBJ xmlns="{NS}" version="2.0"><OMBIND>'
        + s("forall", "typed1")
        + "<OMBVAR>"
        + attrs
        + "</OMBVAR>"
        + body
        + "</OMBIND></OMOBJ>"
    )


def declarations():
    return [
        ("K", s("Field")),
        ("L", s("Field")),
        ("m", s("Nat")),
        ("n", s("Nat")),
        ("p", s("Nat")),
        ("A", a("Matrix", v("K"), v("m"), v("n"))),
        ("B", a("Matrix", v("K"), v("n"), v("p"))),
        ("C", a("Matrix", v("K"), v("n"), v("n"))),
        ("D", a("Matrix", v("L"), v("n"), v("n"))),
        ("x", a("Vector", v("K"), v("n"))),
        ("y", a("Vector", v("K"), v("m"))),
        ("t", a("Scalar", v("K"))),
        ("q", a("Polynomial", v("K"))),
        ("r", a("Polynomial", v("L"))),
    ]


def query():
    return doc(
        declarations(),
        rel(
            "eq",
            a("mul", v("K"), v("m"), v("n"), v("p"), v("A"), v("B")),
            a("zero", v("K"), v("m"), v("p")),
        ),
    )


def test_canonical_alpha_roundtrip():
    raw = query()
    c = canon(raw)
    assert valid(c) == c
    assert canon(raw.replace('name="n"', 'name="middle"')) == c
    with pytest.raises(MathXMLValidationError):
        valid(raw)


@pytest.mark.parametrize(
    "term",
    [
        a("mul", v("K"), v("m"), v("n"), v("p"), v("B"), v("A")),
        a("mul", v("K"), v("m"), v("n"), v("p"), v("A"), v("C")),
        a("mul", v("K"), v("n"), v("n"), v("n"), v("C"), v("D")),
        a("mul", v("K"), v("m"), v("n"), v("p"), v("A")),
        a("det", v("K"), v("n"), v("A")),
        a("det", v("K"), v("n"), v("D")),
        a("det", v("K"), v("n"), v("C"), v("C")),
        a("det", v("K"), v("n")),
        a("inv", v("K"), v("n"), v("A")),
        a("rank", v("K"), v("n"), v("m"), v("A")),
        a("matrix_eval", v("K"), v("n"), v("C"), v("r")),
        a("matrix_eval", v("K"), v("n"), v("q"), v("C")),
        a("matrix_eval", v("K"), v("n"), v("A"), v("q")),
        a("poly_eval", v("K"), v("q"), v("n")),
        a("poly_eval", v("K"), v("t"), v("q")),
        a("poly_coeff", v("K"), v("q"), v("t")),
        a("mul_vec", v("K"), v("m"), v("n"), v("A"), v("y")),
        a("cramer", v("K"), v("n"), v("C"), v("y")),
        a("scalar_pow", v("K"), v("t"), v("t")),
        a("charpoly", v("K"), v("n"), v("free")),
        a("zero", v("K"), "<OMI>2</OMI>", v("n")),
        a("identity", v("n"), v("n")),
        s("Field"),
    ],
)
def test_rejects_mixed_fields_shapes_arity_and_roles(term):
    with pytest.raises(MathXMLValidationError):
        canon(doc(declarations(), rel("eq", term, term)))


def test_expression_dimensions_are_not_bound_sizes():
    size = a("poly_degree", v("K"), v("q"))
    with pytest.raises(MathXMLValidationError):
        canon(doc(declarations(), rel("eq", a("zero", v("K"), size, v("n")), v("C"))))


@pytest.mark.parametrize(
    "badtype",
    [
        a("Matrix", v("K"), v("n")),
        a("Matrix", v("K"), v("n"), "<OMI>2</OMI>"),
        a("Vector", v("K"), v("t")),
        a("Scalar", v("n")),
        s("CommRing"),
        a("Polynomial", v("K"), v("n")),
    ],
)
def test_closed_type_constructors(badtype):
    with pytest.raises(MathXMLValidationError):
        canon(doc(declarations() + [("z", badtype)], rel("eq", v("z"), v("z"))))


@pytest.mark.parametrize(
    "change",
    [
        lambda q: q.replace(CDBASE, CDBASE + "wrong"),
        lambda q: q.replace(NS, "urn:wrong"),
        lambda q: q.replace('name="mul"', 'name="cayley_hamilton_theorem"'),
        lambda q: q.replace('version="2.0"', 'version="2.0" extra="yes"'),
        lambda q: q.replace("<OMBVAR>", '<OMBVAR extra="yes">'),
        lambda q: q.replace('name="L"', 'name="K"'),
        lambda q: q.replace("<OMA>", "<OMA>text", 1),
    ],
)
def test_rejects_untrusted_xml(change):
    with pytest.raises(MathXMLValidationError):
        canon(change(query()))


def test_order_is_not_invented_for_arbitrary_field():
    with pytest.raises(MathXMLValidationError):
        canon(doc(declarations(), rel("leq", v("t"), v("t"))))


def test_bounds():
    with pytest.raises(MathXMLValidationError):
        canon("x" * (MAX_BYTES + 1))
    body = rel("eq", v("C"), v("C"))
    for _ in range(70):
        body = "<OMA>" + s("not", "logic1", "http://www.openmath.org/cd") + body + "</OMA>"
    with pytest.raises(MathXMLValidationError):
        canon(doc(declarations(), body))


def test_registry_semantic_roles():
    reg = json.loads(
        (
            ROOT
            / "pals-agent/pals_agent/content_dictionaries/typed-linear-algebra-v4-registry.json"
        ).read_text()
    )
    ops = {x["name"]: x for x in reg["symbols"]}
    assert "zero for a singular" in ops["inv"]["lean_interpretation"]
    assert ops["matrix_eval"]["arguments"] == ["Field", "IndexSize", "Mat@0,1,1", "Poly@0"]
    assert "below" in ops["poly_next_coeff"]["lean_interpretation"]
    assert "updateCol A i y" in ops["cramer"]["lean_interpretation"]


def test_manifest_evidence_and_all_negative_pairs():
    data = json.loads((ROOT / "docs/linear-algebra-v4-batch.json").read_text())
    cards = data["cards"]
    e = data["evidence"]
    assert len(cards) >= 30
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
    for key, path in [
        ("witness", e["witness_path"]),
        ("validator", "pals-agent/pals_agent/typed_linear_algebra_v4.py"),
        (
            "registry",
            "pals-agent/pals_agent/content_dictionaries/typed-linear-algebra-v4-registry.json",
        ),
    ]:
        assert (
            e[key + "_sha256"] == "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        )
    for c in cards:
        assert valid(c["openmath_xml"]) == c["openmath_xml"]
        assert 4 <= len(c["sketch_steps"]) <= 10
        assert all(bad not in c["lean_witness"] for bad in ["sorry", "admit", "axiom"])
    negatives = json.loads((ROOT / "docs/linear-algebra-v4-negatives.json").read_text())["cases"]
    assert {c["id"] for c in cards} == {c["positive_card_id"] for c in negatives}
