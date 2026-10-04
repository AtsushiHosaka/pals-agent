"""Carrier, finite-dimensional structure, symbol-role, and corpus contract checks."""

from __future__ import annotations

import copy
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError
from pals_agent.typed_linear_algebra_v2 import (
    CDBASE,
    MAX_BYTES,
)
from pals_agent.typed_linear_algebra_v2 import (
    canonicalize_typed_linear_algebra_v2_openmath_xml as canon,
)
from pals_agent.typed_linear_algebra_v2 import (
    validate_canonical_typed_linear_algebra_v2_openmath_xml as valid,
)

NS = "http://www.openmath.org/OpenMath"
STD = "http://www.openmath.org/cd"
ROOT = Path(__file__).resolve().parents[3]


def s(name, cd="la2", base=CDBASE):
    return f'<OMS cdbase="{base}" cd="{cd}" name="{name}"/>'


def v(name):
    return f'<OMV name="{name}"/>'


def app(name, *args):
    return "<OMA>" + s(name) + "".join(args) + "</OMA>"


def relation(name, a, b):
    return "<OMA>" + s(name, "relation1", STD) + a + b + "</OMA>"


def doc(declarations, body):
    bound = "".join(
        "<OMATTR><OMATP>" + s("type", "typed1") + ty + "</OMATP>" + v(n) + "</OMATTR>"
        for n, ty in declarations
    )
    return (
        f'<OMOBJ xmlns="{NS}" version="2.0"><OMBIND>'
        + s("forall", "typed1")
        + "<OMBVAR>"
        + bound
        + "</OMBVAR>"
        + body
        + "</OMBIND></OMOBJ>"
    )


def declarations():
    return [
        ("K", s("Field")),
        ("V", app("FiniteDimensionalSpace", v("K"))),
        ("W", app("FiniteDimensionalSpace", v("K"))),
        ("f", app("LinearMap", v("K"), v("V"), v("W"))),
    ]


def dimension_query():
    return doc(
        declarations(),
        relation(
            "leq",
            app("sub_dim", v("K"), v("W"), app("range", v("K"), v("V"), v("W"), v("f"))),
            app("dim", v("K"), v("V")),
        ),
    )


def test_canonical_round_trip_and_alpha_invariance():
    raw = dimension_query()
    canonical = canon(raw)
    assert valid(canonical) == canonical
    renamed = raw.replace('name="V"', 'name="Domain"').replace('name="f"', 'name="Map"')
    assert canon(renamed) == canonical
    with pytest.raises(MathXMLValidationError):
        valid(raw)


@pytest.mark.parametrize(
    "body",
    [
        app("dim", v("V"), v("K")),  # space is not a scalar field
        app("dim", v("K")),  # missing explicit structure argument
        app("dim", v("K"), v("V"), v("W")),  # extra structure argument
        app("det", v("K"), v("V"), v("f")),  # rectangular map has no determinant
        app("sub_dim", v("K"), v("V"), app("range", v("K"), v("V"), v("W"), v("f"))),
        app("kernel", v("K"), v("W"), v("V"), v("f")),  # reversed domain/codomain
        app("linear_comp", v("K"), v("V"), v("W"), v("V"), v("f"), v("f")),
        app("dim", v("K"), v("U")),  # undeclared carrier
        s("Field"),  # sort constructor is not a proposition
    ],
)
def test_rejects_structure_arity_and_carrier_mixing(body):
    with pytest.raises(MathXMLValidationError):
        canon(doc(declarations(), relation("eq", body, body)))


def test_rejects_different_scalar_fields():
    ds = declarations()[:3] + [("L", s("Field")), ("U", app("FiniteDimensionalSpace", v("L")))]
    ds += [("f", app("LinearMap", v("K"), v("V"), v("U")))]
    with pytest.raises(MathXMLValidationError):
        canon(doc(ds, relation("eq", v("f"), v("f"))))


@pytest.mark.parametrize(
    "sort",
    [
        s("FiniteDimensionalSpace"),
        app("FiniteDimensionalSpace", v("V")),
        app("FiniteDimensionalSpace", v("K"), v("K")),
        app("Module", v("K")),  # no implicit fallback to the old infinite module grammar
        app("VectorFamily", v("K"), v("V"), "<OMI>3</OMI>"),
    ],
)
def test_finite_dimensional_sort_and_bound_index_are_mandatory(sort):
    ds = [("K", s("Field")), ("V", app("FiniteDimensionalSpace", v("K"))), ("X", sort)]
    with pytest.raises(MathXMLValidationError):
        canon(doc(ds, relation("eq", v("X"), v("X"))))


def eigen_declarations():
    return declarations()[:3] + [
        ("n", s("Nat")),
        ("m", s("Nat")),
        ("f", app("LinearMap", v("K"), v("V"), v("V"))),
        ("a", app("ScalarFamily", v("K"), v("n"))),
        ("b", app("ScalarFamily", v("K"), v("m"))),
        ("xs", app("VectorFamily", v("K"), v("V"), v("n"))),
        ("ys", app("VectorFamily", v("K"), v("W"), v("n"))),
        ("c", app("Scalar", v("K"))),
    ]


def test_eigenfamily_roles_and_nonzero_semantic_contract():
    ds = eigen_declarations()
    good = app("eigenfamily", v("K"), v("V"), v("n"), v("f"), v("a"), v("xs"))
    assert valid(canon(doc(ds, good)))
    for bad in [
        app("eigenfamily", v("K"), v("V"), v("n"), v("f"), v("xs"), v("a")),
        app("eigenfamily", v("K"), v("V"), v("n"), v("f"), v("b"), v("xs")),
        app("eigenfamily", v("K"), v("V"), v("n"), v("f"), v("a"), v("ys")),
        app("eigenfamily", v("K"), v("V"), v("n"), v("f"), v("a")),
        app("eigenspace", v("K"), v("V"), v("c"), v("f")),
    ]:
        with pytest.raises(MathXMLValidationError):
            canon(doc(ds, bad))
    # The corpus binds the semantic predicate to HasEigenvector (not merely membership).
    batch = json.loads((ROOT / "docs/linear-algebra-v2-batch.json").read_text())
    for c in batch["cards"]:
        if 'name="eigenfamily"' in c["openmath_xml"]:
            assert "HasEigenvector" in c["lean_target"]
            assert "非零" in c["canonical_statement"]


def test_scalar_power_exponent_is_natural_and_base_is_scalar():
    ds = eigen_declarations()
    good = app("scalar_pow", v("K"), v("c"), app("dim", v("K"), v("V")))
    assert valid(canon(doc(ds, relation("eq", good, good))))
    for bad in [
        app("scalar_pow", v("K"), v("n"), v("c")),
        app("scalar_pow", v("K"), v("c"), v("c")),
    ]:
        with pytest.raises(MathXMLValidationError):
            canon(doc(ds, relation("eq", bad, bad)))


def test_composition_order_is_first_domain_map_then_second_map():
    ds = declarations() + [("g", app("LinearMap", v("K"), v("W"), v("V")))]
    good = app("linear_comp", v("K"), v("V"), v("W"), v("V"), v("f"), v("g"))
    assert valid(canon(doc(ds, relation("eq", good, good))))
    bad = app("linear_comp", v("K"), v("V"), v("W"), v("V"), v("g"), v("f"))
    with pytest.raises(MathXMLValidationError):
        canon(doc(ds, relation("eq", bad, bad)))


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.replace(CDBASE, CDBASE + "-other"),
        lambda x: x.replace('name="dim"', 'name="rank_nullity_theorem"'),
        lambda x: x.replace('version="2.0"', 'version="2.0" metadata="untrusted"'),
        lambda x: x.replace("<OMBVAR>", '<OMBVAR extra="x">'),
        lambda x: x.replace('name="f"', 'name="free"', 0) + "garbage",
        lambda x: x.replace(NS, "urn:not-openmath"),
        lambda x: x.replace('name="W"', 'name="V"'),
        lambda x: x.replace("<OMA>", "<OMA>unexpected", 1),
    ],
)
def test_rejects_nonprofile_symbols_attributes_namespace_shadowing_and_text(change):
    with pytest.raises(MathXMLValidationError):
        canon(change(dimension_query()))


def test_no_untyped_or_extra_payload_inside_quantifier():
    raw = dimension_query()
    with pytest.raises(MathXMLValidationError):
        canon(raw.replace("</OMBVAR>", '<OMV name="untyped"/></OMBVAR>'))
    with pytest.raises(MathXMLValidationError):
        canon(raw.replace("</OMOBJ>", "<OMI>1</OMI></OMOBJ>"))


def test_byte_and_depth_bounds():
    with pytest.raises(MathXMLValidationError):
        canon(" " * (MAX_BYTES + 1))
    body = relation("eq", app("dim", v("K"), v("V")), "<OMI>0</OMI>")
    for _ in range(70):
        body = "<OMA>" + s("not", "logic1", STD) + body + "</OMA>"
    with pytest.raises(MathXMLValidationError):
        canon(doc(declarations(), body))


def test_node_bound():
    leaf = relation("eq", app("dim", v("K"), v("V")), "<OMI>0</OMI>")
    root = ET.fromstring(doc(declarations(), leaf))
    # Direct shape test keeps the independent node bound observable despite the byte cap.
    body = root[0][2]
    for _ in range(9):
        node = ET.Element("{" + NS + "}OMA")
        node.append(ET.Element("{" + NS + "}OMS", {"cdbase": STD, "cd": "logic1", "name": "and"}))
        node.extend([copy.deepcopy(body), copy.deepcopy(body)])
        body = node
    root[0].remove(root[0][2])
    root[0].append(body)
    from pals_agent.typed_linear_algebra_v2 import _shape

    with pytest.raises(MathXMLValidationError, match="bound"):
        _shape(root)


def test_current_corpus_canonical_evidence_and_finite_assumptions():
    batch = json.loads((ROOT / "docs/linear-algebra-v2-batch.json").read_text())
    cards = batch["cards"]
    assert len(cards) == 27
    assert len({c["openmath_xml"] for c in cards}) == 27
    for c in cards:
        assert valid(c["openmath_xml"]) == c["openmath_xml"]
        assert "[Field K]" in c["lean_target"]
        assert "[FiniteDimensional K V]" in c["lean_target"]
        if "[Module K W]" in c["lean_target"]:
            assert "[FiniteDimensional K W]" in c["lean_target"]
        assert 4 <= len(c["sketch_steps"]) <= 10
        assert not any(x in c["lean_witness"] for x in ("sorry", "admit", "axiom"))
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
    witness = ROOT / batch["evidence"]["witness_path"]
    assert witness.read_text() == source
    assert (
        batch["evidence"]["witness_sha256"]
        == "sha256:" + hashlib.sha256(witness.read_bytes()).hexdigest()
    )
