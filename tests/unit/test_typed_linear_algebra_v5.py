"""Matrix dimensions, scalar fields, polynomial roles, bounds and evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError
from pals_agent.typed_linear_algebra_v5 import CDBASE, MAX_BYTES
from pals_agent.typed_linear_algebra_v5 import (
    canonicalize_typed_linear_algebra_v5_openmath_xml as canon,
)
from pals_agent.typed_linear_algebra_v5 import (
    validate_canonical_typed_linear_algebra_v5_openmath_xml as valid,
)

ROOT = Path(__file__).resolve().parents[3]
NS = "http://www.openmath.org/OpenMath"


def s(n, cd="la5", base=CDBASE):
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
        ("V", a("FiniteDimensionalSpace", v("K"))),
        ("W", a("FiniteDimensionalSpace", v("K"))),
        ("U", a("FiniteDimensionalSpace", v("L"))),
        ("m", s("Nat")),
        ("n", s("Nat")),
        ("p", s("Nat")),
        ("b", a("Basis", v("K"), v("V"), v("n"))),
        ("c", a("Basis", v("K"), v("W"), v("m"))),
        ("d", a("Basis", v("L"), v("U"), v("n"))),
        ("f", a("LinearMap", v("K"), v("V"), v("W"))),
        ("g", a("LinearMap", v("K"), v("V"), v("V"))),
        ("x", a("Vector", v("K"), v("V"))),
        ("y", a("Vector", v("K"), v("W"))),
        ("A", a("Matrix", v("K"), v("m"), v("n"))),
        ("C", a("Matrix", v("K"), v("n"), v("n"))),
        ("u", a("Coordinates", v("K"), v("n"))),
        ("w", a("Coordinates", v("K"), v("m"))),
        ("v", a("Family", v("K"), v("V"), v("n"))),
        ("phi", a("Functional", v("K"), v("V"))),
        ("psi", a("Functional", v("K"), v("W"))),
        ("t", a("Scalar", v("K"))),
        ("q", a("Polynomial", v("K"))),
        ("r", a("Polynomial", v("L"))),
        ("i", a("Index", v("n"))),
        ("j", a("Index", v("m"))),
    ]


def query():
    return doc(
        declarations(),
        rel(
            "eq",
            a("to_matrix", v("K"), v("V"), v("W"), v("n"), v("m"), v("b"), v("c"), v("f")),
            v("A"),
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
        a("coordinates", v("K"), v("V"), v("n"), v("b"), v("y")),
        a("coordinates", v("K"), v("V"), v("m"), v("b"), v("x")),
        a("coordinates", v("L"), v("V"), v("n"), v("b"), v("x")),
        a("coordinates", v("K"), v("V"), v("n"), v("b")),
        a("construct", v("K"), v("V"), v("W"), v("n"), v("b"), v("v")),
        a("family_images", v("K"), v("V"), v("W"), v("n"), v("g"), v("v")),
        a("to_matrix", v("K"), v("V"), v("W"), v("n"), v("m"), v("c"), v("b"), v("f")),
        a("to_matrix", v("K"), v("V"), v("W"), v("m"), v("n"), v("b"), v("c"), v("f")),
        a("transition", v("K"), v("V"), v("n"), v("m"), v("b"), v("c")),
        a("apply", v("K"), v("V"), v("W"), v("f"), v("y")),
        a("compose", v("K"), v("V"), v("W"), v("V"), v("f"), v("g")),
        a("diagonal_map", v("K"), v("V"), v("n"), v("b"), v("w")),
        a("eigenbasis", v("K"), v("V"), v("n"), v("f"), v("b"), v("u")),
        a("functional_values", v("K"), v("V"), v("n"), v("psi"), v("v")),
        a("functional_sum", v("K"), v("V"), v("n"), v("v"), v("u")),
        a("poly_aeval", v("K"), v("V"), v("g"), v("r")),
        a("poly_aeval", v("K"), v("V"), v("q"), v("g")),
        a("minpoly", v("K"), v("V"), v("f")),
        a("poly_eval", v("K"), v("q"), v("n")),
        a("matrix_vec", v("K"), v("m"), v("n"), v("A"), v("w")),
        a("matrix_det", v("K"), v("n"), v("A")),
        a("transvection", v("K"), v("n"), v("i"), v("j"), v("t")),
        a("transvection", v("K"), v("n"), v("i"), v("i"), v("n")),
        a("row_update", v("K"), v("m"), v("n"), v("A"), v("j"), v("w")),
        a("row", v("K"), v("m"), v("n"), v("A"), v("i")),
        a("coordinates", v("K"), v("V"), v("n"), v("b"), v("free")),
        a("matrix_identity", v("K"), "<OMI>2</OMI>"),
        s("Field"),
    ],
)
def test_rejects_mixed_fields_shapes_arity_and_roles(term):
    with pytest.raises(MathXMLValidationError):
        canon(doc(declarations(), rel("eq", term, term)))


@pytest.mark.parametrize(
    "badtype",
    [
        a("Matrix", v("K"), v("n")),
        a("Matrix", v("K"), v("n"), "<OMI>2</OMI>"),
        a("Vector", v("K"), v("W"), v("n")),
        a("Vector", v("K"), v("U")),
        a("Basis", v("K"), v("V"), v("t")),
        a("FiniteDimensionalSpace", v("n")),
        a("FiniteDimensionalSpace", v("K"), v("L")),
        a("Functional", v("L"), v("W")),
        a("Index", v("t")),
        s("CommRing"),
    ],
)
def test_closed_type_constructors(badtype):
    with pytest.raises(MathXMLValidationError):
        canon(doc(declarations() + [("bad", badtype)], rel("eq", v("bad"), v("bad"))))


@pytest.mark.parametrize(
    "change",
    [
        lambda q: q.replace(CDBASE, CDBASE + "wrong"),
        lambda q: q.replace(NS, "urn:wrong"),
        lambda q: q.replace('name="to_matrix"', 'name="some_theorem"'),
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
            / "pals-agent/pals_agent/content_dictionaries/typed-linear-algebra-v5-registry.json"
        ).read_text()
    )
    ops = {x["name"]: x for x in reg["symbols"]}
    assert ops["to_matrix"]["result"] == "Mat@0,4,3"
    assert (
        "converts coordinates in c into coordinates in b"
        in ops["transition"]["lean_interpretation"]
    )
    assert "nonzero" in ops["eigenbasis"]["lean_interpretation"]
    assert "x≠0" in ops["has_eigenvector"]["lean_interpretation"]
    assert ops["transvection"]["arguments"] == [
        "Field",
        "IndexSize",
        "Index@1",
        "Index@1",
        "Scalar@0",
    ]
    assert "not a set union" in ops["eigenspaces_sup"]["lean_interpretation"]


def test_manifest_evidence_and_all_negative_pairs():
    data = json.loads((ROOT / "docs/linear-algebra-v5-batch.json").read_text())
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
        ("validator", "pals-agent/pals_agent/typed_linear_algebra_v5.py"),
        (
            "registry",
            "pals-agent/pals_agent/content_dictionaries/typed-linear-algebra-v5-registry.json",
        ),
    ]:
        assert (
            e[key + "_sha256"] == "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        )
    for c in cards:
        assert valid(c["openmath_xml"]) == c["openmath_xml"]
        assert 4 <= len(c["sketch_steps"]) <= 10
        assert all(bad not in c["lean_witness"] for bad in ["sorry", "admit", "axiom"])
    negatives = json.loads((ROOT / "docs/linear-algebra-v5-negatives.json").read_text())["cases"]
    assert {c["id"] for c in cards} == {c["positive_card_id"] for c in negatives}


def test_node_and_binder_bounds_are_enforced_before_type_check():
    body = "<OMA>" + s("matrix_identity") + "<OMI>0</OMI>" * 4100 + "</OMA>"
    with pytest.raises(MathXMLValidationError, match="node or depth"):
        canon(doc([("K", s("Field"))], body))
    ds = [(f"n{i}", s("Nat")) for i in range(65)]
    with pytest.raises(MathXMLValidationError, match="binder declarations"):
        canon(doc(ds, rel("eq", v("n0"), v("n0"))))


def test_new_counterexample_family_signatures_reject_wrong_roles():
    for term in [
        a("matrix_single", v("K"), v("n"), v("m"), v("j"), v("i"), v("t")),
        a("matrix_single", v("L"), v("n"), v("m"), v("i"), v("j"), v("t")),
        a("scalar_zero", v("n")),
        a("matrix_zero", v("K"), v("n"), v("t")),
    ]:
        with pytest.raises(MathXMLValidationError):
            canon(doc(declarations(), rel("eq", term, term)))
