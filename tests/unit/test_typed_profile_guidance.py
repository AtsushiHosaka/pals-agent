"""Grammar examples are independent of the admission corpus; no model calls."""

import json
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

import pytest

from pals_agent.private_typed_candidates import profile_contract
from pals_agent.typed_profile_guidance import _GUIDANCE, profile_guidance

NS = "http://www.openmath.org/OpenMath"


class Grammar:
    def __init__(self, profile):
        self.spec, _ = profile_contract(profile)
        root = Path(__file__).resolve().parents[2] / "pals_agent/content_dictionaries"
        registry = json.loads((root / Path(self.spec.registry_path).name).read_text())
        self.symbols = {x["name"]: x for x in registry["symbols"]}

    def symbol(self, name):
        return ET.Element("OMS", self.symbols[name])

    def app(self, name, *arguments):
        node = ET.Element("OMA")
        node.extend([self.symbol(name), *arguments])
        return node

    def bind(self, declarations, body, name="forall"):
        binder = ET.Element("OMBIND")
        variables = ET.Element("OMBVAR")
        for variable, sort in declarations:
            declaration = ET.Element("OMATTR")
            attributes = ET.Element("OMATP")
            attributes.extend([self.symbol("type"), sort])
            declaration.extend([attributes, v(variable)])
            variables.append(declaration)
        binder.extend([self.symbol(name), variables, body])
        return binder

    def document(self, node):
        root = ET.Element("OMOBJ", {"xmlns": NS, "version": "2.0"})
        root.append(node)
        return ET.tostring(root, encoding="unicode")


def v(name):
    return ET.Element("OMV", {"name": name})


def n(value):
    node = ET.Element("OMI")
    node.text = str(value)
    return node


def example(profile):
    g = Grammar(profile)
    a = g.app
    s = g.symbol
    b = g.bind
    if profile == "typed-math-matrix-v1":
        body = a("eq", a("transpose", a("transpose", v("A"))), v("A"))
        doc = b([("K", s("Field")), ("A", a("Matrix", v("K"), n(3), n(1)))], body)
    elif profile == "typed-math-v1":
        body = a("eq", a("mul", v("G"), v("x"), a("one", v("G"))), v("x"))
        doc = b([("G", s("Group")), ("x", a("Elem", v("G")))], body)
    elif profile == "typed-real-analysis-v1":
        body = a("continuous_at", v("f"), v("x"))
        doc = b([("f", s("RealFunction")), ("x", s("Real"))], body)
    elif profile == "typed-multivariable-calculus-v1":
        body = a("partial_x_at", v("f"), v("p"), a("of_int", n(0)))
        doc = b([("f", s("Real2Function")), ("p", s("Real2"))], body)
    elif profile == "typed-ode-v1":
        function = b([("u", s("Real"))], v("u"), "lambda")
        body = a("eq", a("deriv_at", deepcopy(function), v("t")), a("of_int", n(1)))
        doc = a(
            "and",
            a("initial_value", function, a("of_int", n(0)), a("of_int", n(0))),
            b([("t", s("Real"))], body),
        )
    elif profile == "typed-number-theory-v1":
        body = a("eq", a("gcd", v("k"), v("k")), v("k"))
        doc = b([("k", s("Nat"))], body)
    elif profile == "typed-finite-graph-v1":
        body = a("adjacent", v("G"), v("x"), v("x"))
        doc = b([("G", s("FinSimpleGraph")), ("x", a("Vertex", v("G")))], body)
    elif profile == "typed-geometry-complex-v1":
        body = a("eq", a("vector_add", v("u"), v("u")), v("u"))
        variables = ET.Element("OMBVAR")
        variables.append(v("u"))
        doc = ET.Element("OMBIND")
        doc.extend([s("forall_real_vector2"), variables, body])
    elif profile == "typed-plane-geometry-v1":
        body = a("incident_point_line", v("p"), v("l"))
        doc = b([("p", s("Point2")), ("l", s("Line2"))], body)
    elif profile == "typed-probability-v1":
        body = a("eq", a("probability", v("mu"), v("e")), v("p"))
        doc = b(
            [
                ("S", s("SampleSpace")),
                ("mu", a("ProbabilityMeasure", v("S"))),
                ("e", a("Event", v("S"))),
                ("p", s("Probability")),
            ],
            body,
        )
    else:
        raise AssertionError(profile)
    return g, doc, body


@pytest.mark.parametrize("profile", sorted(_GUIDANCE))
def test_independent_typed_grammar_example_and_wrong_arity(profile):
    grammar, document, body = example(profile)
    xml = grammar.document(document)
    canonical = grammar.spec.canonicalize(xml)
    assert grammar.spec.validate_canonical(canonical) == canonical
    body.remove(list(body)[-1])
    with pytest.raises(ValueError):
        grammar.spec.canonicalize(grammar.document(document))
    assert "XML serialization contract" in profile_guidance(profile)


@pytest.mark.parametrize("profile", sorted(_GUIDANCE))
def test_guidance_covers_registry_symbols_without_catalog_answers(profile):
    grammar = Grammar(profile)
    guidance = profile_guidance(profile)
    for name in grammar.symbols:
        assert name in guidance, (profile, name)
    assert "typed_matrix_v1_literal" not in guidance
    assert "[[1, 2], [3, 4]]" not in guidance


def test_matrix_literal_entries_need_casts_and_depend_on_exact_carrier():
    g = Grammar("typed-math-matrix-v1")
    a = g.app
    s = g.symbol
    b = g.bind
    entries = [a("field_nat_cast", v("K"), n(i)) for i in (5, 7, 11)]
    literal = a("literal", v("K"), n(3), n(1), *entries)
    doc = b([("K", s("Field"))], a("eq", literal, a("zero", v("K"), n(3), n(1))))
    g.spec.canonicalize(g.document(doc))
    literal.remove(entries[0])
    literal.insert(4, n(5))
    with pytest.raises(ValueError, match="Elem"):
        g.spec.canonicalize(g.document(doc))


def test_profile_guidance_rejects_unknown_profile():
    with pytest.raises(ValueError):
        profile_guidance("typed-unknown-v99")
