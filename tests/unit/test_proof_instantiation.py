import xml.etree.ElementTree as ET

import pytest

from pals_agent.proof_instantiation import InstantiationError, instantiate_universal

NS = "http://www.openmath.org/OpenMath"


def document(body):
    return f'<OMOBJ xmlns="{NS}" version="2.0">{body}</OMOBJ>'


def membership(variable, domain="N"):
    return (
        f'<OMA><OMS cd="set1" name="in"/><OMV name="{variable}"/>'
        f'<OMS cd="setname1" name="{domain}"/></OMA>'
    )


def universal(body, *, variable="n", domain="N", binder="forall"):
    return document(
        f'<OMBIND><OMS cd="quant1" name="{binder}"/><OMBVAR>'
        f'<OMV name="{variable}"/></OMBVAR><OMA><OMS cd="logic1" name="implies"/>'
        f"{membership(variable, domain)}{body}</OMA></OMBIND>"
    )


def integer(value):
    return f'<OMI xmlns="{NS}">{value}</OMI>'


POWER = (
    '<OMBIND><OMS cd="fns1" name="lambda"/><OMBVAR><OMV name="x"/></OMBVAR>'
    '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMV name="n"/></OMA></OMBIND>'
)


def test_universal_natural_power_instantiates_two_and_preserves_premise():
    result = instantiate_universal(
        universal(POWER), [{"variable": "n", "term_openmath_xml": integer(2)}]
    )
    root = ET.fromstring(result.openmath_xml)
    assert [n.text for n in root.iter(f"{{{NS}}}OMI")] == ["2", "2"]
    assert not any(n.get("name") == "n" for n in root.iter(f"{{{NS}}}OMV"))
    assert any(n.get("name") == "implies" for n in root.iter())
    assert result.substitutions[0]["domain"] == "Nat"


@pytest.mark.parametrize(
    "source,value",
    [
        (universal(POWER), -1),
        (universal(POWER, binder="exists"), 2),
    ],
)
def test_rejects_wrong_domain_and_existential_witness(source, value):
    with pytest.raises(InstantiationError):
        instantiate_universal(source, [{"variable": "n", "term_openmath_xml": integer(value)}])


def test_capture_avoidance_renames_inner_x_and_keeps_substitution_x_free():
    target = universal('<OMV name="x"/>', variable="x")
    result = instantiate_universal(
        universal(POWER),
        [
            {
                "variable": "n",
                "term_openmath_xml": f'<OMV xmlns="{NS}" name="x"/>',
            }
        ],
        target=target,
    )
    root = ET.fromstring(result.openmath_xml)
    binding = next(root.iter(f"{{{NS}}}OMBIND"))
    assert binding[1][0].get("name") == "x_pals1"
    assert binding[2][1].get("name") == "x_pals1"
    assert binding[2][2].get("name") == "x"


def test_unknown_variable_type_does_not_guess_domain():
    with pytest.raises(InstantiationError, match="sort"):
        instantiate_universal(
            universal(POWER),
            [
                {
                    "variable": "n",
                    "term_openmath_xml": f'<OMV xmlns="{NS}" name="x"/>',
                }
            ],
        )


def test_disjunctive_or_negated_domain_is_not_a_guaranteed_premise():
    source = universal(POWER).replace(
        membership("n"), '<OMA><OMS cd="logic1" name="not"/>' + membership("n") + "</OMA>"
    )
    with pytest.raises(InstantiationError, match="sort unknown"):
        instantiate_universal(source, [{"variable": "n", "term_openmath_xml": integer(2)}])


def test_nested_shadow_cannot_change_outer_natural_parameter_to_real():
    nested = (
        '<OMBIND><OMS cd="quant1" name="exists"/><OMBVAR><OMV name="n"/></OMBVAR>'
        '<OMA><OMS cd="logic1" name="implies"/>'
        + membership("n", "R")
        + '<OMA><OMS cd="relation1" name="eq"/><OMV name="n"/><OMV name="n"/></OMA>'
        "</OMA></OMBIND>"
    )
    with pytest.raises(InstantiationError):
        instantiate_universal(
            universal(nested),
            [
                {
                    "variable": "n",
                    "term_openmath_xml": integer(-1),
                }
            ],
        )


def test_redundant_real_membership_cannot_widen_natural_domain():
    source = universal(POWER).replace(
        membership("n"),
        '<OMA><OMS cd="logic1" name="and"/>' + membership("n") + membership("n", "R") + "</OMA>",
    )
    with pytest.raises(InstantiationError):
        instantiate_universal(source, [{"variable": "n", "term_openmath_xml": integer(-1)}])


@pytest.mark.parametrize(
    "term",
    [
        '<!DOCTYPE a [<!ENTITY x "value">]><OMI>2</OMI>',
        "<OMI>2</OMI>",
        f'<OMI xmlns="{NS}">2.5</OMI>',
    ],
)
def test_malformed_or_untyped_terms_are_rejected(term):
    with pytest.raises(InstantiationError):
        instantiate_universal(universal(POWER), [{"variable": "n", "term_openmath_xml": term}])


def test_parameter_discovery_distinguishes_function_input_from_theorem_parameter():
    from pals_agent.proof_instantiation import universal_numeric_parameters

    concrete = document(POWER.replace('<OMV name="n"/>', '<OMI>2</OMI>'))
    assert universal_numeric_parameters(concrete) == ()
    assert universal_numeric_parameters(universal(POWER)) == ({"variable": "n", "domain": "Nat"},)
    assert universal_numeric_parameters(universal(POWER, binder="exists")) == ()
    unknown = document(
        '<OMBIND><OMS cd="quant1" name="forall"/><OMBVAR><OMV name="n"/></OMBVAR>'
        + POWER + '</OMBIND>'
    )
    assert universal_numeric_parameters(unknown) == ()


def test_parameter_discovery_does_not_offer_an_ambiguous_shadowed_name():
    from pals_agent.proof_instantiation import universal_numeric_parameters

    shadowed = universal(
        '<OMBIND><OMS cd="fns1" name="lambda"/><OMBVAR><OMV name="n"/></OMBVAR>'
        '<OMV name="n"/></OMBIND>'
    )
    assert universal_numeric_parameters(shadowed) == ()
