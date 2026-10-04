"""Closed real inner-product grammar: dependent roles, bounds and evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError
from pals_agent.typed_linear_algebra_v3 import CDBASE, MAX_BYTES
from pals_agent.typed_linear_algebra_v3 import (
    canonicalize_typed_linear_algebra_v3_openmath_xml as canon,
)
from pals_agent.typed_linear_algebra_v3 import (
    validate_canonical_typed_linear_algebra_v3_openmath_xml as valid,
)

ROOT = Path(__file__).resolve().parents[3]
NS = "http://www.openmath.org/OpenMath"


def s(n, cd="la3", base=CDBASE):
    return f'<OMS cdbase="{base}" cd="{cd}" name="{n}"/>'


def v(n):
    return f'<OMV name="{n}"/>'


def a(n, *args):
    return "<OMA>" + s(n) + "".join(args) + "</OMA>"


def eq(x, y):
    return "<OMA>" + s("eq", "relation1", "http://www.openmath.org/cd") + x + y + "</OMA>"


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
        ("V", s("RealInnerProductSpace")),
        ("W", s("RealInnerProductSpace")),
        ("n", s("Nat")),
        ("m", s("Nat")),
        ("x", a("Vector", v("V"))),
        ("y", a("Vector", v("W"))),
        ("S", a("Subspace", v("V"))),
        ("T", a("Subspace", v("W"))),
        ("b", a("OrthonormalBasis", v("V"), v("n"))),
        ("xs", a("VectorFamily", v("V"), v("n"))),
        ("ys", a("VectorFamily", v("V"), v("m"))),
        ("as", a("ScalarFamily", v("n"))),
        ("bs", a("ScalarFamily", v("m"))),
        ("f", a("End", v("V"))),
    ]


def query():
    return doc(declarations(), eq(a("projection", v("V"), v("S"), v("x")), v("x")))


def test_alpha_canonical_roundtrip():
    raw = query()
    c = canon(raw)
    assert valid(c) == c
    assert canon(raw.replace('name="V"', 'name="Space"')) == c
    with pytest.raises(MathXMLValidationError):
        valid(raw)


@pytest.mark.parametrize(
    "term",
    [
        a("projection", v("V"), v("T"), v("x")),
        a("projection", v("V"), v("S"), v("y")),
        a("projection", v("V"), v("x"), v("S")),
        a("projection", v("S"), v("S"), v("x")),
        a("projection", v("V"), v("S")),
        a("projection", v("V"), v("S"), v("x"), v("x")),
        a("inner", v("V"), v("x"), v("y")),
        a("inner", v("V"), v("x"), v("z")),
        a("coordinates", v("W"), v("n"), v("b"), v("y")),
        a("coordinates", v("V"), v("m"), v("b"), v("x")),
        a("sum_scaled", v("V"), v("n"), v("xs"), v("bs")),
        a("sum_scaled", v("V"), v("n"), v("ys"), v("as")),
        a("gram_schmidt", v("V"), "<OMI>3</OMI>", v("xs")),
        a("dot", v("n"), v("as"), v("xs")),
        a("real_square", v("n")),
        a("apply", v("W"), v("f"), v("y")),
        s("RealInnerProductSpace"),
    ],
)
def test_rejects_carrier_index_arity_and_role_mixing(term):
    with pytest.raises(MathXMLValidationError):
        canon(doc(declarations(), eq(term, term)))


def test_eigenfamily_nonzero_semantics_and_roles():
    good = a("eigenfamily", v("V"), v("n"), v("f"), v("as"), v("xs"))
    assert valid(canon(doc(declarations(), good)))
    for bad in [
        a("eigenfamily", v("V"), v("n"), v("f"), v("xs"), v("as")),
        a("eigenfamily", v("V"), v("n"), v("f"), v("bs"), v("xs")),
    ]:
        with pytest.raises(MathXMLValidationError):
            canon(doc(declarations(), bad))
    registry = json.loads(
        (
            ROOT
            / "pals-agent/pals_agent/content_dictionaries/typed-linear-algebra-v3-registry.json"
        ).read_text()
    )
    semantics = next(
        x["lean_interpretation"] for x in registry["symbols"] if x["name"] == "eigenfamily"
    )
    assert "HasEigenvector" in semantics and "≠0" in semantics


@pytest.mark.parametrize(
    "badtype",
    [
        s("InnerProductSpace"),
        a("Vector", v("n")),
        a("VectorFamily", v("V"), "<OMI>2</OMI>"),
        a("OrthonormalBasis", v("V")),
        a("End", v("V"), v("W")),
    ],
)
def test_type_constructors_are_closed(badtype):
    with pytest.raises(MathXMLValidationError):
        canon(doc(declarations() + [("z", badtype)], eq(v("z"), v("z"))))


@pytest.mark.parametrize(
    "change",
    [
        lambda q: q.replace(CDBASE, CDBASE + "-unknown"),
        lambda q: q.replace(NS, NS + "/"),
        lambda q: q.replace('name="projection"', 'name="spectral_theorem"'),
        lambda q: q.replace('version="2.0"', 'version="2.0" href="evil"'),
        lambda q: q.replace("<OMBVAR>", '<OMBVAR extra="1">'),
        lambda q: q.replace('name="W"', 'name="V"'),
        lambda q: q.replace("<OMA>", "<OMA>text", 1),
        lambda q: q.replace('<OMV name="x"/>', '<OMV name="free"/>', 1),
    ],
)
def test_rejects_untrusted_structure(change):
    with pytest.raises(MathXMLValidationError):
        canon(change(query()))


def test_bounds_and_depth():
    with pytest.raises(MathXMLValidationError):
        canon("x" * (MAX_BYTES + 1))
    body = eq(v("x"), v("x"))
    for _ in range(70):
        body = "<OMA>" + s("not", "logic1", "http://www.openmath.org/cd") + body + "</OMA>"
    with pytest.raises(MathXMLValidationError):
        canon(doc(declarations(), body))


def test_rejects_numeric_order_on_vectors():
    body = (
        "<OMA>" + s("leq", "relation1", "http://www.openmath.org/cd") + v("x") + v("x") + "</OMA>"
    )
    with pytest.raises(MathXMLValidationError):
        canon(doc(declarations(), body))


def test_manifest_exact_witness_and_hashes():
    data = json.loads((ROOT / "docs/linear-algebra-v3-batch.json").read_text())
    cards = data["cards"]
    e = data["evidence"]
    assert len(cards) >= 30 and len({c["id"] for c in cards}) == len(cards)
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
    assert (ROOT / e["witness_path"]).read_text() == expected
    for name, path in [
        ("witness", e["witness_path"]),
        ("validator", "pals-agent/pals_agent/typed_linear_algebra_v3.py"),
        (
            "registry",
            "pals-agent/pals_agent/content_dictionaries/typed-linear-algebra-v3-registry.json",
        ),
    ]:
        assert (
            e[name + "_sha256"]
            == "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        )
    for c in cards:
        assert valid(c["openmath_xml"]) == c["openmath_xml"]
        assert 4 <= len(c["sketch_steps"]) <= 10
        assert "sorry" not in c["lean_witness"] and "admit" not in c["lean_witness"]
    spectrum = next(c for c in cards if c["id"] == "la_v3_spectral_orthonormal_basis")
    assert "HasEigenvector" in spectrum["lean_target"] and "bᵢ≠0" in spectrum["canonical_statement"]
