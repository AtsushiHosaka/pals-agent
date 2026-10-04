"""Symbolic grammar conformance against unchanged production XML validators."""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError
from pals_agent.private_typed_candidates import profile_contract
from pals_agent.typed_algebra_guidance import profile_guidance

PROFILES = tuple(
    "typed-commutative-algebra" + suffix + "-v1"
    for suffix in (
        "",
        "-modules",
        "-localization",
        "-integral",
        "-decomposition",
        "-chain-dimension",
    )
)
NS = "http://www.openmath.org/OpenMath"


def symbolic_formula(profile, *, wrong_carrier=False, wrong_arity=False):
    base = "urn:pals:openmath:" + profile.removesuffix("-v1") + ":v1"

    def sym(cd, name, standard=False):
        return ET.Element(
            "OMS", cdbase="http://www.openmath.org/cd" if standard else base, cd=cd, name=name
        )

    def var(name):
        return ET.Element("OMV", name=name)

    def app(cd, name, *args, standard=False):
        node = ET.Element("OMA")
        node.extend([sym(cd, name, standard), *args])
        return node

    declarations = []

    def declare(name, sort):
        node = ET.Element("OMATTR")
        attrs = ET.SubElement(node, "OMATP")
        attrs.extend([sym("typed1", "type"), sort])
        node.append(var(name))
        declarations.append(node)

    suffix = profile.removeprefix("typed-commutative-algebra").removesuffix("-v1")
    cd = {
        "": "commalg1",
        "-modules": "module1",
        "-localization": "localization1",
        "-integral": "integral1",
        "-decomposition": "decomposition1",
        "-chain-dimension": "chain1",
    }[suffix]
    declare("R", sym(cd, "CommRing"))
    declare("T", sym(cd, "CommRing"))
    ring = var("T" if wrong_carrier else "R")
    if suffix == "-modules":
        for name in ("M", "N", "L"):
            declare(name, app(cd, "Module", var("R")))
        declare("f", app(cd, "LinearMap", var("R"), var("M"), var("N")))
        declare("g", app(cd, "LinearMap", var("R"), var("N"), var("L")))
        term = app(cd, "linear_comp", ring, var("M"), var("N"), var("L"), var("f"), var("g"))
    elif suffix == "-localization":
        declare("S", app(cd, "Submonoid", var("R")))
        declare("L", app(cd, "Localization", var("R"), var("S")))
        declare("x", app("typed1", "Elem", var("R")))
        declare("s", app(cd, "SubmonoidElem", var("R"), var("S")))
        term = app(cd, "loc_fraction", ring, var("S"), var("L"), var("x"), var("s"))
    elif suffix == "-integral":
        declare("E", app(cd, "Extension", var("R")))
        declare("x", app("typed1", "Elem", var("R")))
        term = app(cd, "extension_map", ring, var("E"), var("x"))
    elif suffix == "-decomposition":
        declare("I", app(cd, "Ideal", var("R")))
        declare("Qa", app(cd, "PrimaryIdeal", var("R")))
        declare("Qb", app(cd, "PrimaryIdeal", var("R")))
        term = app(cd, "primary_decomposition2", ring, var("I"), var("Qa"), var("Qb"))
    else:
        declare("I", app(cd, "Ideal", var("R")))
        term = (
            app(cd, "IdealFG", ring, var("I"))
            if suffix
            else app(cd, "ideal_le", ring, var("I"), var("I"))
        )
    if wrong_arity:
        term.remove(list(term)[-1])
    # Reflexivity is only an abstract syntax probe, not a catalog/example answer.
    body = app("relation1", "eq", term, ET.fromstring(ET.tostring(term)), standard=True)
    root = ET.Element("OMOBJ", xmlns=NS, version="2.0")
    bind = ET.SubElement(root, "OMBIND")
    bind.append(sym("typed1", "forall"))
    variables = ET.SubElement(bind, "OMBVAR")
    variables.extend(declarations)
    bind.append(body)
    return ET.tostring(root, encoding="unicode")


@pytest.mark.parametrize("profile", PROFILES)
def test_guidance_profiles_cover_registered_symbols_without_catalog_answers(profile):
    guidance = profile_guidance(profile)
    registry = (
        Path(__file__).parents[2] / "pals_agent/content_dictionaries" / f"{profile}-registry.json"
    )
    value = json.loads(registry.read_text())
    assert value["cdbases"]["typed"] in guidance
    for symbol in value["symbols"]:
        assert re.search(r"\b" + re.escape(symbol["name"]) + r"\b", guidance), symbol
    assert "<OMOBJ" not in guidance  # No complete expected-answer XML in production hints.


@pytest.mark.parametrize("profile", PROFILES)
def test_documented_dependent_carriers_and_arities_match_actual_validators(profile):
    spec, _ = profile_contract(profile)
    canonical = spec.canonicalize(symbolic_formula(profile))
    assert spec.validate_canonical(canonical) == canonical
    with pytest.raises(MathXMLValidationError):
        spec.canonicalize(symbolic_formula(profile, wrong_carrier=True))
    with pytest.raises(MathXMLValidationError):
        spec.canonicalize(symbolic_formula(profile, wrong_arity=True))


@pytest.mark.parametrize(
    "profile", ["generic-v1", "typed-math-matrix-v1", "", PROFILES[0] + "-extra"]
)
def test_other_profiles_have_no_algebra_guidance_fallback(profile):
    with pytest.raises(ValueError, match="Unsupported algebra"):
        profile_guidance(profile)


@pytest.mark.parametrize(
    "suffix,mutation",
    [
        ("-modules", "reverse_composition"),
        ("-localization", "arbitrary_denominator"),
        ("-decomposition", "implicit_primary_cast"),
        ("-chain-dimension", "predicate_as_type"),
        ("-integral", "extension_over_extension"),
    ],
)
def test_documented_noncoercions_and_operator_order_are_real_validator_boundaries(suffix, mutation):
    profile = "typed-commutative-algebra" + suffix + "-v1"
    spec, _ = profile_contract(profile)
    root = ET.fromstring(symbolic_formula(profile))
    tags = {name: f"{{{NS}}}{name}" for name in ("OMS", "OMV", "OMA", "OMBVAR", "OMATTR", "OMATP")}
    if mutation == "reverse_composition":
        for symbol in root.iter(tags["OMS"]):
            if symbol.get("name") == "linear_comp":
                parent = next(node for node in root.iter(tags["OMA"]) if list(node)[0] is symbol)
                first, second = list(parent)[-2:]
                parent.remove(first)
                parent.remove(second)
                parent.extend([second, first])
    elif mutation == "extension_over_extension":
        variables = next(root.iter(tags["OMBVAR"]))
        declaration = ET.fromstring(ET.tostring(list(variables)[2]))
        # E2:Extension(E) is disallowed even though E is ring-like for arithmetic.
        list(declaration)[1].set("name", "E2")
        list(list(declaration)[0])[1].find(tags["OMV"]).set("name", "E")
        variables.append(declaration)
    else:
        old, cd, new = {
            "arbitrary_denominator": ("SubmonoidElem", "typed1", "Elem"),
            "implicit_primary_cast": ("PrimaryIdeal", "decomposition1", "Ideal"),
            "predicate_as_type": ("CommRing", "chain1", "Field"),
        }[mutation]
        for symbol in root.iter(tags["OMS"]):
            if symbol.get("name") == old:
                symbol.set("cd", cd)
                symbol.set("name", new)
                if mutation == "arbitrary_denominator":
                    parent = next(
                        node for node in root.iter(tags["OMA"]) if list(node)[0] is symbol
                    )
                    parent.remove(list(parent)[-1])
    with pytest.raises(MathXMLValidationError):
        spec.canonicalize(ET.tostring(root, encoding="unicode"))
