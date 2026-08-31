from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from importlib import resources

import pytest
import rfc8785

from pals_agent.openmath import (
    OPENMATH_STANDARD_CDBASE,
    PALS_OPENMATH_CDBASE,
    LLMStatementOpenMathStructurer,
    MathXMLValidationError,
    OpenMathStructuringError,
    canonicalize_continuity_v1_openmath_xml,
    canonicalize_openmath_xml,
    continuity_v1_novelty_key,
    openmath_structural_similarity,
    validate_canonical_retrieval_openmath_xml,
    validate_openmath_statement_semantics,
    validate_openmath_xml,
)

OPENMATH = "http://www.openmath.org/OpenMath"
OPENMATH_CD = "http://www.openmath.org/OpenMathCD"


def test_pfi_ag_009_canonicalizes_only_synthetic_typed_xml_and_hashes_exact_preimage() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" '
        'name="forall_real_function"/><OMBVAR><OMV name="f"/></OMBVAR>'
        '<OMBIND><OMS cd="quant1" name="forall"/><OMBVAR><OMV name="a"/></OMBVAR>'
        f'<OMA><OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" '
        'name="continuous_at"/><OMV name="f"/><OMV name="a"/>'
        "</OMA></OMBIND></OMBIND></OMOBJ>"
    )
    coverage = {
        "context": "continuity_at",
        "operators": [],
        "prerequisites": [],
        "proof_schema": "basic",
        "representation": "variable_closure",
        "stratum": "core_law",
        "topic": "continuity_at",
    }

    canonical = canonicalize_continuity_v1_openmath_xml(xml)
    expected = (
        "sha256:"
        + hashlib.sha256(
            rfc8785.dumps(
                {
                    "coverage_signature": coverage,
                    "openmath_xml_sha256": "sha256:"
                    + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                }
            )
        ).hexdigest()
    )

    assert continuity_v1_novelty_key(coverage, canonical) == expected


def test_pfi_ag_009_c14n_v4_returns_parseable_bytes_and_rejects_raw_artifact() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" '
        'name="forall_real_function"/><OMBVAR><OMV name="f"/></OMBVAR>'
        '<OMBIND><OMS cd="quant1" name="forall"/><OMBVAR><OMV name="a"/></OMBVAR>'
        f'<OMA><OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" '
        'name="continuous_at"/><OMV name="f"/><OMV name="a"/>'
        "</OMA></OMBIND></OMBIND></OMOBJ>"
    )

    canonical = canonicalize_continuity_v1_openmath_xml(xml)
    raw_artifact = canonical.replace(" xmlns:n1=", ' xmlns:n0="" xmlns:n1=', 1)

    assert 'xmlns:n0=""' not in canonical
    assert ET.fromstring(canonical).tag == f"{{{OPENMATH}}}OMOBJ"
    with pytest.raises(MathXMLValidationError):
        validate_canonical_retrieval_openmath_xml(raw_artifact)


def test_packaged_pals1_content_dictionary_defines_supported_symbols() -> None:
    xml = (
        resources.files("pals_agent.content_dictionaries")
        .joinpath("pals1.ocd")
        .read_text(encoding="utf-8")
    )
    root = ET.fromstring(xml)
    definitions = root.findall(f"{{{OPENMATH_CD}}}CDDefinition")
    names = {definition.findtext(f"{{{OPENMATH_CD}}}Name") for definition in definitions}
    roles = {definition.findtext(f"{{{OPENMATH_CD}}}Role") for definition in definitions}

    assert root.tag == f"{{{OPENMATH_CD}}}CD"
    assert root.findtext(f"{{{OPENMATH_CD}}}CDName") == "pals1"
    assert root.findtext(f"{{{OPENMATH_CD}}}CDBase") == "urn:pals:openmath:cd:v1"
    assert root.findtext(f"{{{OPENMATH_CD}}}CDURL") == "urn:pals:openmath:cd:v1/pals1.ocd"
    assert root.findtext(f"{{{OPENMATH_CD}}}CDVersion") == "1"
    assert PALS_OPENMATH_CDBASE == "urn:pals:openmath:cd:v1"
    assert names == {
        "compact",
        "continuous_on",
        "dimension",
        "domain",
        "finite_dimensional",
        "linear_map",
        "nullity",
        "rank",
    }
    assert roles == {"application"}


def test_seed_pals1_symbols_emit_versioned_custom_cdbase() -> None:
    payload = json.loads(
        resources.files("pals_agent.seed").joinpath("dsp_drafts.json").read_text(encoding="utf-8")
    )
    symbols: list[ET.Element] = []
    for draft in payload:
        root = ET.fromstring(draft["openmath_xml"])
        symbols.extend(
            element for element in root.iter(f"{{{OPENMATH}}}OMS") if element.get("cd") == "pals1"
        )

    assert symbols
    assert all(element.get("cdbase") == PALS_OPENMATH_CDBASE for element in symbols)


class FakeTextClient:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[tuple[str, str]] = []

    def generate(self, *, model: str, prompt: str) -> str:
        self.calls.append((model, prompt))
        return self.output


class FailingTextClient:
    def generate(self, *, model: str, prompt: str) -> str:
        raise RuntimeError("provider unavailable")


class SequenceTextClient:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.prompts: list[str] = []
        self.models: list[str] = []

    def generate(self, *, model: str, prompt: str) -> str:
        self.models.append(model)
        self.prompts.append(prompt)
        return self.outputs[len(self.prompts) - 1]


def test_openmath_canonicalization_absorbs_prefix_whitespace_and_attribute_order() -> None:
    unprefixed = f"""
    <OMOBJ xmlns="{OPENMATH}" version="2.0">
      <OMA>
        <OMS name="eq" cd="relation1" />
        <OMV name="left" />
        <OMV name="right" />
      </OMA>
    </OMOBJ>
    """
    prefixed = (
        f'<om:OMOBJ version="2.0" xmlns:om="{OPENMATH}">'
        '<om:OMA><om:OMS cd="relation1" name="eq"></om:OMS>'
        '<om:OMV name="left"></om:OMV><om:OMV name="right"></om:OMV>'
        "</om:OMA></om:OMOBJ>"
    )

    assert canonicalize_openmath_xml(unprefixed) == canonicalize_openmath_xml(prefixed)


def test_standard_symbols_preserve_default_and_inherited_cdbase_semantics() -> None:
    implicit = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="relation1" name="eq"/><OMV name="x"/><OMV name="y"/>'
        "</OMA></OMOBJ>"
    )
    explicit = implicit.replace(
        '<OMS cd="relation1"',
        f'<OMS cdbase="{OPENMATH_STANDARD_CDBASE}" cd="relation1"',
    )
    inherited = implicit.replace(
        'version="2.0"',
        f'version="2.0" cdbase="{OPENMATH_STANDARD_CDBASE}"',
    )

    validate_openmath_statement_semantics(implicit, "x = y")
    validate_openmath_statement_semantics(explicit, "x = y")
    validate_openmath_statement_semantics(inherited, "x = y")
    assert openmath_structural_similarity(implicit, explicit) == pytest.approx(1.0)
    assert openmath_structural_similarity(implicit, inherited) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "cdbase_attribute",
    ["", ' cdbase="urn:example:wrong-openmath-base"'],
)
def test_pals1_symbols_reject_missing_or_wrong_cdbase(cdbase_attribute: str) -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS{cdbase_attribute} cd="pals1" name="linear_map"/>'
        '<OMV name="f"/></OMA></OMOBJ>'
    )

    with pytest.raises(MathXMLValidationError, match="must resolve `cdbase`"):
        validate_openmath_xml(xml)


def test_pals1_symbol_accepts_correct_inherited_cdbase() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0" cdbase="{PALS_OPENMATH_CDBASE}">'
        '<OMA><OMS cd="pals1" name="linear_map"/><OMV name="f"/></OMA></OMOBJ>'
    )

    validate_openmath_statement_semantics(xml, "f is a linear map")


def test_structural_similarity_uses_resolved_cdbase_in_symbol_identity() -> None:
    standard = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="relation1" name="eq"/><OMV name="x"/><OMV name="y"/>'
        "</OMA></OMOBJ>"
    )
    foreign = standard.replace(
        '<OMS cd="relation1"',
        '<OMS cdbase="urn:example:foreign-cd-base" cd="relation1"',
    )

    assert openmath_structural_similarity(standard, foreign) < 1.0


def test_structural_similarity_keeps_wrong_and_unknown_symbols_distinct() -> None:
    canonical = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/>'
        '<OMA><OMS cd="arith1" name="power"/><OMV name="y"/><OMV name="n"/></OMA>'
        "</OMA></OMOBJ>"
    )
    wrong_cd = canonical.replace('cd="arith1" name="power"', 'cd="fns1" name="power"')
    unknown_name = canonical.replace('name="power"', 'name="unknown_power"')

    assert canonicalize_openmath_xml(wrong_cd) != canonicalize_openmath_xml(canonical)
    assert canonicalize_openmath_xml(unknown_name) != canonicalize_openmath_xml(canonical)
    assert openmath_structural_similarity(canonical, canonical) == pytest.approx(1.0)
    assert openmath_structural_similarity(wrong_cd, canonical) < 1.0
    assert openmath_structural_similarity(unknown_name, canonical) < 1.0


def test_openmath_alpha_normalizes_bound_variables_in_declaration_order() -> None:
    first = _forall_equality("x", "y")
    second = _forall_equality("foo", "bar")

    canonical = canonicalize_openmath_xml(first)

    assert canonical == canonicalize_openmath_xml(second)
    assert 'name="v1"' in canonical
    assert 'name="v2"' in canonical
    assert 'name="x"' not in canonical
    assert 'name="y"' not in canonical


def test_openmath_alpha_normalization_respects_shadowing_and_free_variables() -> None:
    xml = f"""
    <OMOBJ xmlns="{OPENMATH}" version="2.0">
      <OMA>
        <OMS cd="relation1" name="eq" />
        <OMV name="free" />
        <OMBIND>
          <OMS cd="fns1" name="lambda" />
          <OMBVAR><OMV name="x" /></OMBVAR>
          <OMA>
            <OMS cd="arith1" name="plus" />
            <OMV name="x" />
            <OMBIND>
              <OMS cd="fns1" name="lambda" />
              <OMBVAR><OMV name="x" /></OMBVAR>
              <OMV name="x" />
            </OMBIND>
            <OMV name="x" />
            <OMV name="free" />
          </OMA>
        </OMBIND>
      </OMA>
    </OMOBJ>
    """

    canonical = canonicalize_openmath_xml(xml)
    root = ET.fromstring(canonical)
    variables = [element.get("name") for element in root.iter(f"{{{OPENMATH}}}OMV")]

    assert variables == ["free", "v1", "v1", "v2", "v2", "v1", "free"]


@pytest.mark.parametrize(
    ("xml", "message"),
    [
        ("<OMOBJ>", "Malformed OpenMath XML"),
        (
            '<OMOBJ xmlns="urn:not-openmath" version="2.0"><OMV name="x"/></OMOBJ>',
            "OpenMath root",
        ),
        (
            f'<OMA xmlns="{OPENMATH}"><OMV name="x"/><OMV name="y"/></OMA>',
            "OpenMath root",
        ),
        (
            f'<OMOBJ xmlns="{OPENMATH}" version="1.0"><OMV name="x"/></OMOBJ>',
            "version",
        ),
    ],
)
def test_openmath_validation_rejects_malformed_namespace_root_and_version(
    xml: str,
    message: str,
) -> None:
    with pytest.raises(MathXMLValidationError, match=message):
        validate_openmath_xml(xml)


@pytest.mark.parametrize(
    "body",
    [
        "<OMB></OMB>",
        "<OMB>aGVs\n bG8=</OMB>",
        '<OMF dec="0"/>',
        '<OMF dec="-3.743e4"/>',
        '<OMF dec=".5"/>',
        '<OMF dec="-.5"/>',
        '<OMF dec="INF"/>',
        '<OMF dec="-INF"/>',
        '<OMF dec="NaN"/>',
        '<OMF hex="3DDB7CDFD9D7BDBB"/>',
    ],
)
def test_openmath_validation_accepts_openmath_omb_and_omf_lexical_forms(
    body: str,
) -> None:
    validate_openmath_xml(f'<OMOBJ xmlns="{OPENMATH}" version="2.0">{body}</OMOBJ>')


@pytest.mark.parametrize(
    "value",
    [
        "A",
        "AAAA=",
        "AA=A",
        "!!!!",
        "AB==",
        "aGVs\u00a0bG8=",
    ],
)
def test_openmath_validation_rejects_malformed_omb_base64(value: str) -> None:
    xml = f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMB>{value}</OMB></OMOBJ>'

    with pytest.raises(MathXMLValidationError, match="OMB contains"):
        validate_openmath_xml(xml)


@pytest.mark.parametrize(
    "value",
    ["", ".", "1.", "+1", "1e+2", "e3", "nan", "Infinity", "1_0", "--1"],
)
def test_openmath_validation_rejects_malformed_omf_decimal(value: str) -> None:
    xml = f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMF dec="{value}"/></OMOBJ>'

    with pytest.raises(MathXMLValidationError, match="invalid decimal float"):
        validate_openmath_xml(xml)


@pytest.mark.parametrize(
    "value",
    [
        "3DDB7CDFD9D7BDB",
        "3DDB7CDFD9D7BDBB0",
        "3ddb7cdfd9d7bdbb",
        "3DDB7CDFD9D7BDBG",
        " 3DDB7CDFD9D7BDBB",
    ],
)
def test_openmath_validation_rejects_malformed_omf_hex(value: str) -> None:
    xml = f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMF hex="{value}"/></OMOBJ>'

    with pytest.raises(MathXMLValidationError, match="invalid 64-bit hexadecimal float"):
        validate_openmath_xml(xml)


@pytest.mark.parametrize(
    "attributes",
    ["", 'dec="1" hex="3FF0000000000000"'],
)
def test_openmath_validation_requires_exactly_one_omf_representation(
    attributes: str,
) -> None:
    xml = f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMF {attributes}/></OMOBJ>'

    with pytest.raises(MathXMLValidationError, match="exactly one"):
        validate_openmath_xml(xml)


def test_llm_structurer_uses_configured_client_and_returns_canonical_openmath() -> None:
    client = FakeTextClient(f"```xml\n{_forall_equality('alpha', 'beta')}\n```")
    structurer = LLMStatementOpenMathStructurer(
        client=client,
        model="configured-model",
        provider="test-provider",
    )

    result = structurer.structure("  x = y を示せ  ")

    assert result == canonicalize_openmath_xml(_forall_equality("x", "y"))
    assert client.calls[0][0] == "configured-model"
    assert "x = y を示せ" in client.calls[0][1]
    assert "Preserve distinct free variables" in client.calls[0][1]


def test_llm_structurer_repairs_structural_then_semantic_validation_failures() -> None:
    structural_error_xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA><OMS cd="arith1" name="plus"/></OMA></OMOBJ>'
    )
    semantic_error_xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="relation1" name="eq"/><OMSTR>x</OMSTR><OMSTR>y</OMSTR>'
        "</OMA></OMOBJ>"
    )
    client = SequenceTextClient(
        [structural_error_xml, semantic_error_xml, _forall_equality("x", "y")]
    )
    structurer = LLMStatementOpenMathStructurer(
        client=client,
        model="configured-model",
        provider="test-provider",
    )

    result = structurer.structure("x = y を示せ")

    assert result == canonicalize_openmath_xml(_forall_equality("a", "b"))
    assert client.models == ["configured-model"] * 3
    assert "Positive example 1" in client.prompts[0]
    assert "Positive example 2" in client.prompts[0]
    assert "pals1:continuous_on(domain, function)" in client.prompts[0]
    assert "pals1:rank(map)" in client.prompts[0]
    assert "pals1:nullity(map)" in client.prompts[0]
    assert "pals1:dimension(space)" in client.prompts[0]
    assert "pals1:domain(map)" in client.prompts[0]
    assert "pals1:linear_map(map)" in client.prompts[0]
    assert f'cdbase="{PALS_OPENMATH_CDBASE}"' in client.prompts[0]
    assert OPENMATH_STANDARD_CDBASE in client.prompts[0]
    assert "x^2が連続であることを示せ" not in client.prompts[0]
    assert "rank A = n - Ker Aを示せ" not in client.prompts[0]
    assert "cpt集合の連続写像による像" not in client.prompts[0]
    assert "x = y を示せ" in client.prompts[1]
    assert structural_error_xml in client.prompts[1]
    assert "OMA must contain at least 2 child element(s)." in client.prompts[1]
    assert semantic_error_xml in client.prompts[2]
    assert "OMSTR is not allowed in structured statement OpenMath." in client.prompts[2]


def test_llm_structurer_repairs_missing_pals1_cdbase() -> None:
    missing_base = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="pals1" name="linear_map"/><OMV name="f"/></OMA></OMOBJ>'
    )
    repaired = missing_base.replace(
        '<OMS cd="pals1"',
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1"',
    )
    client = SequenceTextClient([missing_base, repaired])
    structurer = LLMStatementOpenMathStructurer(
        client=client,
        model="configured-model",
        provider="test-provider",
    )

    result = structurer.structure("f is a linear map")

    assert result == canonicalize_openmath_xml(repaired)
    assert "must resolve `cdbase`" in client.prompts[1]
    assert f'Set `cdbase="{PALS_OPENMATH_CDBASE}"`' in client.prompts[1]


def test_llm_structurer_adds_predicate_hint_when_candidate_is_only_a_term() -> None:
    term = '<OMA><OMS cd="arith1" name="power"/><OMV name="y"/><OMI>2</OMI></OMA>'
    term_xml = f'<OMOBJ xmlns="{OPENMATH}" version="2.0">{term}</OMOBJ>'
    function = (
        f'<OMBIND><OMS cd="fns1" name="lambda"/><OMBVAR><OMV name="y"/></OMBVAR>{term}</OMBIND>'
    )
    proposition_xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" name="continuous_on"/>'
        f'<OMS cd="setname1" name="R"/>{function}</OMA></OMOBJ>'
    )
    client = SequenceTextClient([term_xml, proposition_xml])
    structurer = LLMStatementOpenMathStructurer(
        client=client,
        model="configured-model",
        provider="test-provider",
    )

    result = structurer.structure("y^2が連続であることを示せ")

    assert result == canonicalize_openmath_xml(proposition_xml)
    assert len(client.prompts) == 2
    assert term_xml in client.prompts[1]
    assert "does not encode a predicate/proposition" in client.prompts[1]
    assert "pals1:continuous_on(domain, function)" in client.prompts[1]
    assert "faithful to the original statement" in client.prompts[1]
    assert "arith1:power" in client.prompts[1]
    assert "pals1:continuous_on" in client.prompts[1]


def test_llm_structurer_repairs_expanded_proof_method_to_continuity_claim() -> None:
    reciprocal_function = (
        '<OMBIND><OMS cd="fns1" name="lambda"/><OMBVAR><OMV name="x"/></OMBVAR>'
        '<OMA><OMS cd="arith1" name="divide"/><OMI>1</OMI><OMV name="x"/></OMA>'
        "</OMBIND>"
    )
    expanded_definition = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>'
        '<OMS cd="quant1" name="exists"/><OMBVAR><OMV name="delta"/></OMBVAR>'
        '<OMA><OMS cd="logic1" name="and"/><OMA><OMS cd="relation1" name="gt"/>'
        '<OMV name="delta"/><OMI>0</OMI></OMA><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        f'<OMS cd="setname1" name="R"/>{reciprocal_function}</OMA></OMA>'
        "</OMBIND></OMOBJ>"
    )
    reciprocal = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        f'<OMS cd="setname1" name="R"/>{reciprocal_function}</OMA></OMOBJ>'
    )
    client = SequenceTextClient([expanded_definition, reciprocal])
    structurer = LLMStatementOpenMathStructurer(
        client=client,
        model="configured-model",
        provider="test-provider",
    )

    result = structurer.structure("1/x が連続であることをイプシロンデルタで示せ")

    assert result == canonicalize_openmath_xml(reciprocal)
    assert len(client.prompts) == 2
    assert "Preserve the theorem's abstraction level" in client.prompts[0]
    assert expanded_definition in client.prompts[1]
    assert "epsilon-delta proof method" in client.prompts[1]
    assert "do not expand it into quantifiers" in client.prompts[1]


@pytest.mark.parametrize(
    ("cd", "name", "expected_arity"),
    [
        ("relation1", "eq", 2),
        ("logic1", "not", 1),
        ("logic1", "implies", 2),
        ("arith1", "minus", 2),
        ("arith1", "power", 2),
        ("pals1", "compact", 1),
        ("pals1", "continuous_on", 2),
        ("pals1", "dimension", 1),
        ("pals1", "domain", 1),
        ("pals1", "finite_dimensional", 1),
        ("pals1", "linear_map", 1),
        ("pals1", "nullity", 1),
        ("pals1", "rank", 1),
        ("set1", "in", 2),
        ("set1", "map", 2),
        ("set1", "size", 1),
    ],
)
def test_semantic_validation_enforces_known_symbol_arities(
    cd: str,
    name: str,
    expected_arity: int,
) -> None:
    received_arity = 1 if expected_arity == 2 else 2
    arguments = "".join(f'<OMV name="argument{index}"/>' for index in range(received_arity))
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f"{_profile_oms(cd, name)}{arguments}</OMA></OMOBJ>"
    )

    with pytest.raises(
        MathXMLValidationError,
        match=rf"`{cd}:{name}` requires exactly {expected_arity}",
    ):
        validate_openmath_statement_semantics(xml, "generic mathematical statement")


@pytest.mark.parametrize(
    ("cd", "name"),
    [
        ("logic1", "and"),
        ("arith1", "plus"),
        ("set1", "union"),
    ],
)
def test_semantic_validation_enforces_supported_nary_minimum(
    cd: str,
    name: str,
) -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cd="{cd}" name="{name}"/><OMV name="only"/></OMA></OMOBJ>'
    )

    with pytest.raises(
        MathXMLValidationError,
        match=rf"`{cd}:{name}` requires at least 2",
    ):
        validate_openmath_statement_semantics(xml, "generic mathematical statement")


def test_semantic_validation_accepts_supported_nary_logic_and_arithmetic() -> None:
    equality = (
        '<OMA><OMS cd="relation1" name="eq"/>'
        '<OMA><OMS cd="arith1" name="plus"/>'
        '<OMV name="x"/><OMV name="y"/><OMV name="z"/></OMA>'
        '<OMV name="w"/></OMA>'
    )
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="logic1" name="and"/>'
        f"{equality}{equality}{equality}</OMA></OMOBJ>"
    )

    validate_openmath_statement_semantics(xml, "generic mathematical statement")


def test_semantic_validation_accepts_standard_trigonometric_and_calculus_terms() -> None:
    trig = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>'
        '<OMS cd="quant1" name="forall"/><OMBVAR><OMV name="x"/></OMBVAR>'
        '<OMA><OMS cd="logic1" name="implies"/>'
        '<OMA><OMS cd="set1" name="in"/><OMV name="x"/>'
        '<OMS cd="setname1" name="R"/></OMA>'
        '<OMA><OMS cd="relation1" name="eq"/>'
        '<OMA><OMS cd="arith1" name="plus"/>'
        '<OMA><OMS cd="arith1" name="power"/><OMA><OMS cd="transc1" name="sin"/>'
        '<OMV name="x"/></OMA><OMI>2</OMI></OMA>'
        '<OMA><OMS cd="arith1" name="power"/><OMA><OMS cd="transc1" name="cos"/>'
        '<OMV name="x"/></OMA><OMI>2</OMI></OMA></OMA><OMI>1</OMI></OMA></OMA>'
        '</OMBIND></OMOBJ>'
    )
    derivative = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>'
        '<OMS cd="quant1" name="forall"/><OMBVAR><OMV name="x"/></OMBVAR>'
        '<OMA><OMS cd="logic1" name="implies"/>'
        '<OMA><OMS cd="set1" name="in"/><OMV name="x"/>'
        '<OMS cd="setname1" name="R"/></OMA>'
        '<OMA><OMS cd="relation1" name="eq"/>'
        f'<OMA><OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="apply"/>'
        '<OMA><OMS cd="calculus1" name="diff"/><OMBIND>'
        '<OMS cd="fns1" name="lambda"/><OMBVAR><OMV name="t"/></OMBVAR>'
        '<OMA><OMS cd="arith1" name="power"/><OMV name="t"/><OMI>2</OMI></OMA>'
        '</OMBIND></OMA><OMV name="x"/></OMA>'
        '<OMA><OMS cd="arith1" name="times"/><OMI>2</OMI><OMV name="x"/></OMA>'
        '</OMA></OMA></OMBIND></OMOBJ>'
    )
    definite_integral = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="relation1" name="eq"/><OMA><OMS cd="calculus1" name="defint"/>'
        '<OMA><OMS cd="interval1" name="oriented_interval"/><OMI>0</OMI>'
        '<OMI>1</OMI></OMA><OMBIND><OMS cd="fns1" name="lambda"/>'
        '<OMBVAR><OMV name="t"/></OMBVAR><OMV name="t"/></OMBIND></OMA>'
        '<OMA><OMS cd="arith1" name="divide"/><OMI>1</OMI><OMI>2</OMI></OMA>'
        '</OMA></OMOBJ>'
    )

    validate_openmath_statement_semantics(
        trig,
        "For every real x, sin(x)^2 + cos(x)^2 = 1.",
    )
    validate_openmath_statement_semantics(
        derivative,
        "For every real x, the derivative of x^2 is 2*x.",
    )
    validate_openmath_statement_semantics(
        definite_integral,
        "The definite integral of x from 0 to 1 is 1/2.",
    )


def test_semantic_validation_requires_functional_calculus_arguments() -> None:
    invalid_derivative = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="relation1" name="eq"/><OMA><OMS cd="calculus1" name="diff"/>'
        '<OMV name="f"/></OMA><OMV name="g"/></OMA></OMOBJ>'
    )
    invalid_integral = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="relation1" name="eq"/><OMA><OMS cd="calculus1" name="defint"/>'
        '<OMA><OMS cd="interval1" name="oriented_interval"/><OMI>0</OMI>'
        '<OMI>1</OMI></OMA><OMV name="f"/></OMA><OMI>0</OMI></OMA></OMOBJ>'
    )

    with pytest.raises(MathXMLValidationError, match="calculus1:diff.*unary"):
        validate_openmath_statement_semantics(
            invalid_derivative,
            "generic mathematical statement",
        )
    with pytest.raises(MathXMLValidationError, match="calculus1:defint.*unary"):
        validate_openmath_statement_semantics(
            invalid_integral,
            "generic mathematical statement",
        )


@pytest.mark.parametrize(
    ("xml", "role"),
    [
        (
            f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
            '<OMS cd="quant1" name="forall"/><OMV name="x"/></OMA></OMOBJ>',
            "binder",
        ),
        (
            f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
            '<OMS cd="logic1" name="true"/><OMV name="x"/></OMA></OMOBJ>',
            "constant",
        ),
        (
            f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>'
            '<OMS cd="relation1" name="eq"/><OMBVAR><OMV name="x"/></OMBVAR>'
            '<OMA><OMS cd="relation1" name="eq"/><OMV name="x"/>'
            '<OMV name="x"/></OMA></OMBIND></OMOBJ>',
            "application",
        ),
    ],
)
def test_semantic_validation_enforces_openmath_symbol_roles(
    xml: str,
    role: str,
) -> None:
    with pytest.raises(MathXMLValidationError, match=rf"OpenMath role `{role}`"):
        validate_openmath_statement_semantics(xml, "generic mathematical statement")


def test_semantic_validation_does_not_treat_binder_symbol_as_proposition_value() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="logic1" name="not"/><OMS cd="quant1" name="forall"/>'
        "</OMA></OMOBJ>"
    )

    with pytest.raises(MathXMLValidationError, match="must be a predicate/proposition"):
        validate_openmath_statement_semantics(xml, "generic mathematical statement")


def test_semantic_validation_rejects_raw_term_as_continuous_function() -> None:
    power = '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMI>2</OMI></OMA>'
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" name="continuous_on"/>'
        f'<OMA><OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" name="domain"/>{power}</OMA>{power}'
        "</OMA></OMOBJ>"
    )

    with pytest.raises(MathXMLValidationError, match="function argument.*fns1:lambda"):
        validate_openmath_statement_semantics(xml, "x^2 is continuous")


@pytest.mark.parametrize(
    "function",
    [
        '<OMV name="f"/>',
        (
            '<OMBIND><OMS cd="fns1" name="lambda"/>'
            '<OMBVAR><OMV name="x"/></OMBVAR><OMA>'
            '<OMS cd="arith1" name="plus"/><OMV name="x"/><OMI>1</OMI>'
            "</OMA></OMBIND>"
        ),
    ],
)
def test_semantic_validation_accepts_supported_continuous_function_forms(
    function: str,
) -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" name="continuous_on"/>'
        f'<OMS cd="setname1" name="R"/>{function}</OMA></OMOBJ>'
    )

    validate_openmath_statement_semantics(xml, "the function is continuous on R")


def test_semantic_validation_matches_bare_continuity_target_variable() -> None:
    correct = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="f"/></OMA></OMOBJ>'
    )
    validate_openmath_statement_semantics(correct, "fが連続であることを示せ")

    wrong = correct.replace('<OMV name="f"/>', '<OMV name="g"/>')
    with pytest.raises(MathXMLValidationError, match="target function variable"):
        validate_openmath_statement_semantics(wrong, "fが連続であることを示せ")
    validate_openmath_statement_semantics(
        correct,
        "実数上で f は連続であることを示せ",
    )
    with pytest.raises(MathXMLValidationError, match="target function variable"):
        validate_openmath_statement_semantics(
            wrong,
            "実数上で f は連続であることを示せ",
        )

    function_g = correct.replace('<OMV name="f"/>', '<OMV name="g"/>')
    validate_openmath_statement_semantics(
        function_g,
        "関数gは連続であることを示せ",
    )
    validate_openmath_statement_semantics(
        function_g,
        "写像gが連続であることを示せ",
    )
    with pytest.raises(MathXMLValidationError, match="target function variable"):
        validate_openmath_statement_semantics(
            correct,
            "関数gは連続であることを示せ",
        )


def test_semantic_validation_matches_commandless_english_conditional_target() -> None:
    correct = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="logic1" name="implies"/><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="f"/></OMA><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="g"/></OMA></OMA></OMOBJ>'
    )
    statement = "If f is continuous, then g is continuous."
    validate_openmath_statement_semantics(correct, statement)

    wrong = correct.replace('<OMV name="g"/>', '<OMV name="h"/>')
    with pytest.raises(MathXMLValidationError, match="target function variable"):
        validate_openmath_statement_semantics(wrong, statement)
    validate_openmath_statement_semantics(
        correct,
        "fが連続ならgが連続であることを示せ",
    )
    validate_openmath_statement_semantics(
        correct,
        "fが連続であるときgが連続であることを示せ",
    )
    with pytest.raises(MathXMLValidationError, match="target function variable"):
        validate_openmath_statement_semantics(
            wrong,
            "fが連続ならgが連続であることを示せ",
        )


def test_semantic_validation_rejects_wrong_explicit_continuity_operator() -> None:
    xml = _continuous_expression_xml('<OMA><OMS cd="arith1" name="abs"/><OMV name="x"/></OMA>')

    with pytest.raises(
        MathXMLValidationError,
        match="arithmetic structure|omits operator.*arith1:power",
    ):
        validate_openmath_statement_semantics(xml, "x^2 が連続であることを示せ")


def test_semantic_validation_rejects_wrong_continuity_polarity() -> None:
    xml = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMI>2</OMI></OMA>'
    )

    with pytest.raises(MathXMLValidationError, match="negated continuity proposition"):
        validate_openmath_statement_semantics(xml, "x^2 が不連続であることを示せ")


def test_semantic_validation_treats_implication_antecedent_as_negative() -> None:
    square = ET.tostring(
        ET.fromstring(
            _continuous_expression_xml(
                '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMI>2</OMI></OMA>'
            )
        )[0],
        encoding="unicode",
    )
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="logic1" name="implies"/>'
        f'{square}<OMS cd="logic1" name="true"/></OMA></OMOBJ>'
    )

    with pytest.raises(MathXMLValidationError, match="positive continuity proposition"):
        validate_openmath_statement_semantics(xml, "x^2 が連続であることを示せ")


@pytest.mark.parametrize(
    ("antecedent", "statement"),
    [
        (
            '<OMA><OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" '
            'name="continuous_on"/><OMS cd="setname1" name="R"/>'
            '<OMV name="h"/></OMA>',
            "Show that if f is continuous, x^2 is continuous.",
        ),
        (
            '<OMA><OMS cd="logic1" name="not"/><OMA>'
            '<OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" '
            'name="continuous_on"/><OMS cd="setname1" name="R"/>'
            '<OMV name="f"/></OMA></OMA>',
            "Show that if f is continuous, x^2 is continuous.",
        ),
        (
            '<OMA><OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" '
            'name="continuous_on"/><OMS cd="setname1" name="R"/>'
            '<OMV name="f"/></OMA>',
            "Show that if f is continuous and g is continuous, x^2 is continuous.",
        ),
    ],
)
def test_semantic_validation_rejects_mismatched_continuity_premise_atoms(
    antecedent: str,
    statement: str,
) -> None:
    square = ET.tostring(
        ET.fromstring(
            _continuous_expression_xml(
                '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMI>2</OMI></OMA>'
            )
        )[0],
        encoding="unicode",
    )
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cd="logic1" name="implies"/>{antecedent}{square}</OMA></OMOBJ>'
    )

    with pytest.raises(MathXMLValidationError, match="positive continuity proposition"):
        validate_openmath_statement_semantics(xml, statement)


def test_semantic_validation_uses_goal_polarity_not_premise_polarity() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="logic1" name="implies"/><OMA><OMS cd="logic1" name="not"/>'
        f'<OMA><OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="f"/></OMA></OMA><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="g"/></OMA></OMA></OMOBJ>'
    )

    validate_openmath_statement_semantics(
        xml,
        "不連続関数 f を仮定し、gが連続であることを示せ",
    )


def test_semantic_validation_recognizes_continuous_suru_goal() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="relation1" name="eq"/><OMV name="x"/><OMV name="x"/>'
        "</OMA></OMOBJ>"
    )

    with pytest.raises(MathXMLValidationError, match="does not use `pals1:continuous_on`"):
        validate_openmath_statement_semantics(xml, "x^2 が連続することを示せ")


def test_semantic_validation_recognizes_negated_assumption_instruction_as_goal() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="relation1" name="eq"/><OMV name="f"/><OMV name="f"/>'
        "</OMA></OMOBJ>"
    )

    with pytest.raises(MathXMLValidationError, match="does not use `pals1:continuous_on`"):
        validate_openmath_statement_semantics(
            xml,
            "fが連続であることを仮定せずに示せ",
        )
    continuous = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="f"/></OMA></OMOBJ>'
    )
    validate_openmath_statement_semantics(
        continuous,
        "fが連続であることを仮定せずに示せ",
    )


def test_semantic_validation_rejects_missing_direct_nonzero_domain() -> None:
    xml = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="divide"/><OMI>1</OMI><OMV name="x"/></OMA>'
    )

    with pytest.raises(MathXMLValidationError, match="positive continuity proposition"):
        validate_openmath_statement_semantics(
            xml,
            "0でない点xにおいて1/xの連続性を示せ",
        )


def test_semantic_validation_rejects_restricted_domain_for_real_continuity_goal() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMA><OMS cd="set1" name="set"/><OMI>0</OMI></OMA>'
        '<OMBIND><OMS cd="fns1" name="lambda"/><OMBVAR><OMV name="x"/></OMBVAR>'
        '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMI>2</OMI>'
        "</OMA></OMBIND></OMA></OMOBJ>"
    )

    with pytest.raises(MathXMLValidationError, match="positive continuity proposition"):
        validate_openmath_statement_semantics(xml, "x^2が連続であることを示せ")


def test_semantic_validation_accepts_alpha_renamed_nonzero_domain_point() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMA><OMS cd="set1" name="setdiff"/><OMS cd="setname1" name="R"/>'
        '<OMA><OMS cd="set1" name="set"/><OMI>0</OMI></OMA></OMA>'
        '<OMBIND><OMS cd="fns1" name="lambda"/><OMBVAR><OMV name="y"/></OMBVAR>'
        '<OMA><OMS cd="arith1" name="divide"/><OMI>1</OMI><OMV name="y"/>'
        "</OMA></OMBIND></OMA></OMOBJ>"
    )

    validate_openmath_statement_semantics(
        xml,
        "0でない点xにおいて1/xの連続性を示せ",
    )


def test_semantic_validation_accepts_function_variable_on_nonzero_domain() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMA><OMS cd="set1" name="setdiff"/><OMS cd="setname1" name="R"/>'
        '<OMA><OMS cd="set1" name="set"/><OMI>0</OMI></OMA></OMA>'
        '<OMV name="f"/></OMA></OMOBJ>'
    )

    validate_openmath_statement_semantics(
        xml,
        "0でない点xにおいてfが連続であることを示せ",
    )
    with pytest.raises(MathXMLValidationError, match="target function variable"):
        validate_openmath_statement_semantics(
            xml.replace('<OMV name="f"/>', '<OMV name="g"/>'),
            "0でない点xにおいてfが連続であることを示せ",
        )


def test_semantic_validation_keeps_nonzero_parameter_out_of_domain_atoms() -> None:
    conclusion = (
        f'<OMA><OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMBIND><OMS cd="fns1" name="lambda"/>'
        '<OMBVAR><OMV name="x"/></OMBVAR><OMA><OMS cd="arith1" name="times"/>'
        '<OMV name="a"/><OMV name="x"/></OMA></OMBIND></OMA>'
    )
    implication = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="logic1" name="implies"/><OMA><OMS cd="relation1" name="neq"/>'
        f'<OMV name="a"/><OMI>0</OMI></OMA>{conclusion}</OMA></OMOBJ>'
    )
    statement = "a≠0のとき、x ↦ a*xが連続であることを示せ"

    validate_openmath_statement_semantics(implication, statement)

    restricted = implication.replace(
        '<OMS cd="setname1" name="R"/>',
        '<OMA><OMS cd="set1" name="setdiff"/><OMS cd="setname1" name="R"/>'
        '<OMA><OMS cd="set1" name="set"/><OMI>0</OMI></OMA></OMA>',
        1,
    )
    with pytest.raises(MathXMLValidationError, match="positive continuity proposition"):
        validate_openmath_statement_semantics(restricted, statement)


def test_semantic_validation_rejects_nonzero_domain_with_wrong_base_set() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMA><OMS cd="set1" name="setdiff"/><OMA><OMS cd="set1" name="set"/>'
        '<OMI>1</OMI></OMA><OMA><OMS cd="set1" name="set"/><OMI>0</OMI>'
        '</OMA></OMA><OMBIND><OMS cd="fns1" name="lambda"/>'
        '<OMBVAR><OMV name="x"/></OMBVAR><OMA><OMS cd="arith1" name="divide"/>'
        '<OMI>1</OMI><OMV name="x"/></OMA></OMBIND></OMA></OMOBJ>'
    )

    with pytest.raises(MathXMLValidationError, match="positive continuity proposition"):
        validate_openmath_statement_semantics(
            xml,
            "0でない点xにおいて1/xの連続性を示せ",
        )


def test_semantic_validation_requires_nonzero_constraint_in_conclusion_domain() -> None:
    reciprocal = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="divide"/><OMI>1</OMI><OMV name="y"/></OMA>'
    )
    target = ET.tostring(ET.fromstring(reciprocal)[0], encoding="unicode")
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="logic1" name="implies"/><OMA><OMS cd="relation1" name="neq"/>'
        f'<OMV name="x"/><OMI>0</OMI></OMA>{target}</OMA></OMOBJ>'
    )

    with pytest.raises(MathXMLValidationError, match="positive continuity proposition"):
        validate_openmath_statement_semantics(
            xml,
            "0でない点xにおいて1/xの連続性を示せ",
        )


def test_semantic_validation_accepts_exact_multi_variable_continuity_premises() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="logic1" name="implies"/><OMA><OMS cd="logic1" name="and"/>'
        f'<OMA><OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="f"/></OMA><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="g"/></OMA></OMA><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMBIND><OMS cd="fns1" name="lambda"/>'
        '<OMBVAR><OMV name="x"/></OMBVAR><OMA><OMS cd="arith1" name="plus"/>'
        '<OMA><OMV name="f"/><OMV name="x"/></OMA>'
        '<OMA><OMV name="g"/><OMV name="x"/></OMA></OMA></OMBIND></OMA></OMA></OMOBJ>'
    )

    validate_openmath_statement_semantics(
        xml,
        "Show that if f and g are continuous, the sum of f and g is continuous.",
    )


def test_semantic_validation_does_not_treat_continuous_map_as_continuity_goal() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="logic1" name="implies"/><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMV name="S"/><OMV name="f"/></OMA><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="compact"/>'
        '<OMA><OMS cd="set1" name="map"/><OMV name="f"/><OMV name="S"/>'
        "</OMA></OMA></OMA></OMOBJ>"
    )

    validate_openmath_statement_semantics(
        xml,
        "cpt集合の連続写像による像はcpt集合であることを示せ",
    )
    validate_openmath_statement_semantics(
        xml,
        "cpt集合の連続な写像による像はcpt集合であることを示せ",
    )
    validate_openmath_statement_semantics(
        xml,
        "fが連続であるとき、f(S)はコンパクトであることを示せ",
    )
    validate_openmath_statement_semantics(
        xml,
        "fが連続であれば、f(S)はコンパクトであることを示せ",
    )
    validate_openmath_statement_semantics(
        xml,
        "fが連続であることを仮定し、f(S)はコンパクトであることを示せ",
    )
    validate_openmath_statement_semantics(
        xml,
        "Show that if f is continuous, the image f(S) is compact.",
    )
    validate_openmath_statement_semantics(
        xml,
        "fが連続であることをまず仮定し、f(S)はコンパクトであることを示せ",
    )
    validate_openmath_statement_semantics(
        xml,
        "Show that, assuming f is continuous, the image f(S) is compact.",
    )
    validate_openmath_statement_semantics(
        xml,
        "Prove under the assumption that f is continuous the image f(S) is compact.",
    )
    validate_openmath_statement_semantics(
        xml,
        "Show that, given the continuity of f, the image f(S) is compact.",
    )
    validate_openmath_statement_semantics(
        xml,
        "Show that, assuming continuity of f, the image f(S) is compact.",
    )
    validate_openmath_statement_semantics(
        xml,
        "Prove under the assumption of continuity of f the image f(S) is compact.",
    )

    two_premise_xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="logic1" name="implies"/><OMA><OMS cd="logic1" name="and"/>'
        f'<OMA><OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMV name="S"/><OMV name="f"/></OMA><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMV name="S"/><OMV name="g"/></OMA></OMA><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="compact"/>'
        '<OMA><OMS cd="set1" name="map"/><OMV name="f"/><OMV name="S"/>'
        "</OMA></OMA></OMA></OMOBJ>"
    )
    validate_openmath_statement_semantics(
        two_premise_xml,
        "Show that, given f is continuous and g is continuous, the image f(S) is compact.",
    )


@pytest.mark.parametrize(
    "wrapper",
    [
        '<OMA><OMS cd="logic1" name="or"/>{target}<OMS cd="logic1" name="true"/></OMA>',
        '<OMA><OMS cd="logic1" name="implies"/><OMS cd="logic1" name="false"/>{target}</OMA>',
        (
            '<OMA><OMS cd="logic1" name="implies"/><OMA>'
            '<OMS cd="logic1" name="not"/><OMS cd="logic1" name="true"/>'
            "</OMA>{target}</OMA>"
        ),
        (
            '<OMA><OMS cd="logic1" name="implies"/><OMA>'
            '<OMS cd="relation1" name="neq"/><OMI>0</OMI><OMI>0</OMI>'
            "</OMA>{target}</OMA>"
        ),
        (
            '<OMA><OMS cd="logic1" name="implies"/><OMA>'
            '<OMS cd="logic1" name="xor"/><OMS cd="logic1" name="true"/>'
            '<OMS cd="logic1" name="true"/></OMA>{target}</OMA>'
        ),
        (
            '<OMA><OMS cd="logic1" name="implies"/><OMA>'
            '<OMS cd="relation1" name="lt"/><OMA><OMS cd="arith1" name="plus"/>'
            "<OMI>1</OMI><OMI>1</OMI></OMA><OMI>1</OMI></OMA>{target}</OMA>"
        ),
        (
            '<OMA><OMS cd="logic1" name="implies"/><OMA>'
            '<OMS cd="relation1" name="neq"/><OMI>x0</OMI><OMI>x0</OMI>'
            "</OMA>{target}</OMA>"
        ),
        (
            '<OMA><OMS cd="logic1" name="implies"/><OMBIND>'
            '<OMS cd="quant1" name="exists"/><OMBVAR><OMV name="z"/></OMBVAR>'
            '<OMS cd="logic1" name="false"/></OMBIND>{target}</OMA>'
        ),
    ],
)
def test_semantic_validation_rejects_tautology_wrapped_continuity_goal(
    wrapper: str,
) -> None:
    square = ET.tostring(
        ET.fromstring(
            _continuous_expression_xml(
                '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMI>2</OMI></OMA>'
            )
        )[0],
        encoding="unicode",
    )
    xml = f'<OMOBJ xmlns="{OPENMATH}" version="2.0">{wrapper.format(target=square)}</OMOBJ>'

    with pytest.raises(MathXMLValidationError, match="positive continuity proposition"):
        validate_openmath_statement_semantics(xml, "x^2 が連続であることを示せ")


def test_semantic_validation_does_not_combine_different_continuity_targets() -> None:
    absolute_value = ET.tostring(
        ET.fromstring(
            _continuous_expression_xml('<OMA><OMS cd="arith1" name="abs"/><OMV name="x"/></OMA>')
        )[0],
        encoding="unicode",
    )
    square = ET.tostring(
        ET.fromstring(
            _continuous_expression_xml(
                '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMI>2</OMI></OMA>'
            )
        )[0],
        encoding="unicode",
    )
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="logic1" name="and"/>'
        f'{absolute_value}<OMA><OMS cd="logic1" name="not"/>{square}</OMA>'
        "</OMA></OMOBJ>"
    )

    with pytest.raises(MathXMLValidationError, match="positive continuity proposition"):
        validate_openmath_statement_semantics(xml, "x^2 が連続であることを示せ")


def test_semantic_validation_rejects_target_operator_only_in_invalid_domain() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMA><OMS cd="set1" name="suchthat"/><OMS cd="setname1" name="R"/>'
        '<OMBIND><OMS cd="fns1" name="lambda"/><OMBVAR><OMV name="x"/></OMBVAR>'
        '<OMA><OMS cd="relation1" name="gt"/><OMA><OMS cd="arith1" name="power"/>'
        '<OMV name="x"/><OMI>2</OMI></OMA><OMI>0</OMI></OMA></OMBIND></OMA>'
        '<OMBIND><OMS cd="fns1" name="lambda"/><OMBVAR><OMV name="x"/></OMBVAR>'
        '<OMA><OMS cd="arith1" name="abs"/><OMV name="x"/></OMA></OMBIND>'
        "</OMA></OMOBJ>"
    )

    with pytest.raises(MathXMLValidationError, match="positive continuity proposition"):
        validate_openmath_statement_semantics(xml, "x^2 が連続であることを示せ")


def test_semantic_validation_accepts_sentence_final_continuity_goal() -> None:
    square = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMI>2</OMI></OMA>'
    )

    validate_openmath_statement_semantics(square, "x^2 は連続。")


def test_semantic_validation_accepts_hex_openmath_power_exponent() -> None:
    square = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMI>x2</OMI></OMA>'
    )

    validate_openmath_statement_semantics(square, "x^2 が連続であることを示せ")


def test_semantic_validation_preserves_explicit_target_sum_and_literal() -> None:
    correct = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="plus"/><OMA>'
        '<OMS cd="arith1" name="power"/><OMV name="x"/><OMI>2</OMI>'
        "</OMA><OMI>1</OMI></OMA>"
    )
    statement = "x^2 + 1 が連続であることを示せ"
    validate_openmath_statement_semantics(correct, statement)

    missing_sum = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMI>2</OMI></OMA>'
    )
    with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
        validate_openmath_statement_semantics(missing_sum, statement)

    wrong_literal = correct.replace("<OMI>1</OMI>", "<OMI>0</OMI>")
    with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
        validate_openmath_statement_semantics(wrong_literal, statement)

    misplaced_literal = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="times"/><OMA>'
        '<OMS cd="arith1" name="plus"/><OMV name="x"/><OMI>2</OMI>'
        "</OMA><OMI>1</OMI></OMA>"
    )
    with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
        validate_openmath_statement_semantics(
            misplaced_literal,
            "x + 1 が実数上で連続であることを示せ",
        )

    reversed_structure = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="power"/><OMA>'
        '<OMS cd="arith1" name="plus"/><OMV name="x"/><OMI>1</OMI>'
        "</OMA><OMI>2</OMI></OMA>"
    )
    with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
        validate_openmath_statement_semantics(reversed_structure, statement)

    with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
        validate_openmath_statement_semantics(
            missing_sum,
            "x^2 - 1 が連続であることを示せ",
        )


def test_semantic_validation_excludes_proof_instruction_arithmetic_from_target() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="f"/></OMA></OMOBJ>'
    )

    validate_openmath_statement_semantics(
        xml,
        "1+1=2を用いて、fが連続であることを示せ",
    )
    validate_openmath_statement_semantics(
        xml,
        "1+1=2を用いてfが連続であることを示せ",
    )

    square = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMI>2</OMI></OMA>'
    )
    validate_openmath_statement_semantics(
        square,
        "Show that x^2 is continuous using the identity y^3 + y^2 + 1 = 0.",
    )
    validate_openmath_statement_semantics(
        square,
        "Using the identity y^3 + y^2 + 1 = 0, show that x^2 is continuous.",
    )
    validate_openmath_statement_semantics(
        square,
        "Show that x^2 is continuous using the identity y^n = y^n.",
    )
    validate_openmath_statement_semantics(
        square,
        "Using the identity y^n = y^n, show that x^2 is continuous.",
    )
    validate_openmath_statement_semantics(
        square,
        "Show that x^2 is continuous using y != 0.",
    )
    validate_openmath_statement_semantics(
        square,
        "Using y != 0, show that x^2 is continuous.",
    )
    validate_openmath_statement_semantics(
        square,
        "Using an expression with respect to y, show that x^2 is continuous.",
    )


def test_semantic_validation_preserves_target_variable_identity() -> None:
    correct = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="plus"/><OMV name="f"/><OMV name="g"/></OMA>'
    )
    duplicated = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="plus"/><OMV name="f"/><OMV name="f"/></OMA>'
    )

    validate_openmath_statement_semantics(correct, "f + g が連続であることを示せ")
    with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
        validate_openmath_statement_semantics(
            duplicated,
            "f + g が連続であることを示せ",
        )


def test_semantic_validation_normalizes_nary_associative_arithmetic() -> None:
    nary = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="plus"/><OMV name="x"/><OMI>1</OMI><OMI>2</OMI></OMA>'
    )

    validate_openmath_statement_semantics(
        nary,
        "x + 1 + 2 が連続であることを示せ",
    )


def test_semantic_validation_accepts_openmath_unary_minus_shape() -> None:
    unary_minus = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="unary_minus"/><OMV name="x"/></OMA>'
    )

    validate_openmath_statement_semantics(
        unary_minus,
        "-x が連続であることを示せ",
    )


def test_semantic_validation_preserves_explicit_function_callee() -> None:
    direct = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="f"/></OMA></OMOBJ>'
    )
    correct = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="plus"/><OMA><OMV name="f"/>'
        '<OMV name="x"/></OMA><OMI>1</OMI></OMA>'
    )
    wrong_callee = correct.replace('<OMV name="f"/>', '<OMV name="g"/>')
    statement = "f(x) + 1 が連続であることを示せ"

    validate_openmath_statement_semantics(
        direct,
        "f(x) が連続であることを示せ",
    )
    validate_openmath_statement_semantics(correct, statement)
    with pytest.raises(MathXMLValidationError, match="callee.*f"):
        validate_openmath_statement_semantics(wrong_callee, statement)


@pytest.mark.parametrize(
    "statement",
    [
        "For continuous f, show that f(x) + 1 is continuous.",
        "For f continuous, show that f(x) + 1 is continuous.",
        "Let f be continuous, show that f(x) + 1 is continuous.",
        "For f continuous. Show that f(x) + 1 is continuous.",
        "Let f be continuous. Show that f(x) + 1 is continuous.",
        "For f continuous. With respect to x, show that f(x) + 1 is continuous.",
        "For f continuous, using an identity, show that f(x) + 1 is continuous.",
    ],
)
def test_semantic_validation_requires_for_let_continuity_premise(
    statement: str,
) -> None:
    target = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="plus"/><OMA><OMV name="f"/>'
        '<OMV name="x"/></OMA><OMI>1</OMI></OMA>'
    )

    with pytest.raises(MathXMLValidationError, match="positive continuity proposition"):
        validate_openmath_statement_semantics(target, statement)


def test_semantic_validation_preserves_function_application_tree() -> None:
    composed = _continuous_expression_xml(
        '<OMA><OMV name="f"/><OMA><OMV name="g"/><OMV name="x"/></OMA></OMA>'
    )
    reversed_composition = _continuous_expression_xml(
        '<OMA><OMV name="g"/><OMA><OMV name="f"/><OMV name="x"/></OMA></OMA>'
    )
    duplicated = _continuous_expression_xml(
        '<OMA><OMV name="f"/><OMA><OMV name="f"/><OMV name="x"/></OMA></OMA>'
    )

    validate_openmath_statement_semantics(
        composed,
        "f(g(x)) が連続であることを示せ",
    )
    with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
        validate_openmath_statement_semantics(
            reversed_composition,
            "f(g(x)) が連続であることを示せ",
        )
    with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
        validate_openmath_statement_semantics(
            _continuous_expression_xml('<OMA><OMV name="f"/><OMV name="x"/></OMA>'),
            "f(f(x)) が連続であることを示せ",
        )
    validate_openmath_statement_semantics(
        duplicated,
        "f(f(x)) が連続であることを示せ",
    )


def test_semantic_validation_alpha_normalizes_lambda_point_name() -> None:
    renamed_square = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMI>2</OMI></OMA>'
    ).replace('name="x"', 'name="a"')
    renamed_composition = _continuous_expression_xml(
        '<OMA><OMV name="f"/><OMA><OMV name="g"/><OMV name="x"/></OMA></OMA>'
    ).replace('name="x"', 'name="a"')

    validate_openmath_statement_semantics(
        renamed_square,
        "x^2 が連続であることを示せ",
    )
    validate_openmath_statement_semantics(
        renamed_composition,
        "f(g(x)) が連続であることを示せ",
    )


def test_semantic_validation_preserves_declared_point_operand_order() -> None:
    correct = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="minus"/><OMV name="x"/><OMV name="y"/></OMA>'
    ).replace('name="x"', 'name="a"')
    reversed_operands = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="minus"/><OMV name="y"/><OMV name="x"/></OMA>'
    ).replace('name="x"', 'name="a"')
    statement = "xについてx-yが連続であることを示せ"

    validate_openmath_statement_semantics(correct, statement)
    with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
        validate_openmath_statement_semantics(reversed_operands, statement)

    for punctuated in (
        "xについて、x-yが連続であることを示せ",
        "With respect to x, show that x-y is continuous.",
        "Consider g with respect to y. With respect to x, show that x-y is continuous.",
        "With respect to x, using an identity, show that x-y is continuous.",
        "Show that x-y is continuous with respect to x.",
    ):
        validate_openmath_statement_semantics(correct, punctuated)
        with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
            validate_openmath_statement_semantics(reversed_operands, punctuated)


def test_semantic_validation_keeps_assumption_points_out_of_target_point_scope() -> None:
    def implication(body: str) -> str:
        return (
            f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
            '<OMS cd="logic1" name="implies"/><OMA>'
            f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
            '<OMS cd="setname1" name="R"/><OMV name="f"/></OMA><OMA>'
            f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
            '<OMS cd="setname1" name="R"/><OMBIND><OMS cd="fns1" name="lambda"/>'
            f'<OMBVAR><OMV name="a"/></OMBVAR>{body}</OMBIND></OMA></OMA></OMOBJ>'
        )

    correct = implication(
        '<OMA><OMS cd="arith1" name="minus"/><OMV name="a"/><OMV name="y"/></OMA>'
    )
    reversed_operands = implication(
        '<OMA><OMS cd="arith1" name="minus"/><OMV name="y"/><OMV name="a"/></OMA>'
    )
    for statement in (
        "Show that if f is continuous with respect to y then x-y is continuous with respect to x.",
        "With respect to x, show that if f is continuous, then x-y is continuous.",
        "If f is continuous with respect to y, then x-y is continuous with respect to x.",
        "For f continuous, with respect to x, show that x-y is continuous.",
    ):
        validate_openmath_statement_semantics(correct, statement)
        with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
            validate_openmath_statement_semantics(reversed_operands, statement)


def test_semantic_validation_preserves_multiple_comma_separated_assumptions() -> None:
    def continuity_atom(name: str) -> str:
        return (
            "<OMA>"
            f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
            f'<OMS cd="setname1" name="R"/><OMV name="{name}"/></OMA>'
        )

    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="logic1" name="implies"/><OMA><OMS cd="logic1" name="and"/>'
        f"{continuity_atom('f')}{continuity_atom('g')}</OMA><OMA>"
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMBIND><OMS cd="fns1" name="lambda"/>'
        '<OMBVAR><OMV name="a"/></OMBVAR><OMA><OMS cd="arith1" name="minus"/>'
        '<OMV name="a"/><OMV name="y"/></OMA></OMBIND></OMA></OMA></OMOBJ>'
    )
    for statement in (
        "If f is continuous, and g is continuous, then x-y is continuous with respect to x.",
        "Given f is continuous, and g is continuous, show that "
        "x-y is continuous with respect to x.",
    ):
        validate_openmath_statement_semantics(xml, statement)


def test_semantic_validation_uses_first_comma_as_commandless_condition_boundary() -> None:
    atom = (
        "<OMA>"
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="f"/></OMA>'
    )
    target = (
        "<OMA>"
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="g"/></OMA>'
    )
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cd="logic1" name="implies"/>{atom}{target}</OMA></OMOBJ>'
    )

    for statement in (
        "If f is continuous, g is continuous.",
        "Given f is continuous, g is continuous.",
    ):
        validate_openmath_statement_semantics(xml, statement)


def test_semantic_validation_keeps_target_before_trailing_japanese_proof_method() -> None:
    power = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>'
        '<OMS cd="quant1" name="forall"/><OMBVAR><OMV name="n"/></OMBVAR>'
        '<OMA><OMS cd="logic1" name="implies"/><OMA><OMS cd="set1" name="in"/>'
        '<OMV name="n"/><OMS cd="setname1" name="N"/></OMA><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMBIND><OMS cd="fns1" name="lambda"/>'
        '<OMBVAR><OMV name="x"/></OMBVAR><OMA><OMS cd="arith1" name="power"/>'
        '<OMV name="x"/><OMV name="n"/></OMA></OMBIND></OMA></OMA></OMBIND></OMOBJ>'
    )

    validate_openmath_statement_semantics(
        power,
        "任意の自然数nに対して、x^nが連続であることを数学的帰納法を用いて示せ",
    )


def test_semantic_validation_rejects_wrong_simple_function_application_arguments() -> None:
    free_argument = _continuous_expression_xml('<OMA><OMV name="f"/><OMV name="w"/></OMA>')
    duplicate_argument = _continuous_expression_xml(
        '<OMA><OMV name="f"/><OMV name="x"/><OMV name="x"/></OMA>'
    )

    for xml in (free_argument, duplicate_argument):
        with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
            validate_openmath_statement_semantics(
                xml,
                "f(x) が連続であることを示せ",
            )


def test_semantic_validation_preserves_arithmetic_inside_absolute_value() -> None:
    shifted_absolute = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="abs"/><OMA>'
        '<OMS cd="arith1" name="minus"/><OMV name="x"/><OMI>1</OMI>'
        "</OMA></OMA>"
    )
    wrong_shift = shifted_absolute.replace('name="minus"', 'name="plus"')

    validate_openmath_statement_semantics(
        shifted_absolute,
        "|x - 1| が連続であることを示せ",
    )
    with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
        validate_openmath_statement_semantics(
            wrong_shift,
            "|x - 1| が連続であることを示せ",
        )


def test_semantic_validation_preserves_implicit_product_variables() -> None:
    correct = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="times"/><OMV name="f"/><OMV name="g"/></OMA>'
    )
    duplicated = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="times"/><OMV name="f"/><OMV name="f"/></OMA>'
    )
    statement = "f と g の積 fg が連続であることを示せ"

    validate_openmath_statement_semantics(correct, statement)
    with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
        validate_openmath_statement_semantics(duplicated, statement)

    english_statement = "Show that the product of fg is continuous."
    validate_openmath_statement_semantics(correct, english_statement)
    with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
        validate_openmath_statement_semantics(duplicated, english_statement)

    product_plus_one = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="plus"/><OMA>'
        '<OMS cd="arith1" name="times"/><OMV name="f"/><OMV name="g"/>'
        "</OMA><OMI>1</OMI></OMA>"
    )
    duplicated_plus_one = product_plus_one.replace(
        '<OMV name="g"/>',
        '<OMV name="f"/>',
    )
    for compound_statement in (
        "f と g の積 fg + 1 が連続であることを示せ",
        "Show that the product of fg + 1 is continuous.",
    ):
        validate_openmath_statement_semantics(product_plus_one, compound_statement)
        with pytest.raises(MathXMLValidationError, match="arithmetic structure"):
            validate_openmath_statement_semantics(
                duplicated_plus_one,
                compound_statement,
            )

    leading_one = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="plus"/><OMI>1</OMI><OMA>'
        '<OMS cd="arith1" name="times"/><OMV name="f"/><OMV name="g"/>'
        "</OMA></OMA>"
    )
    for right_product in (
        "1 + f と g の積 fg が連続であることを示せ",
        "Show that 1 + the product of fg is continuous.",
    ):
        validate_openmath_statement_semantics(leading_one, right_product)


def test_semantic_validation_preserves_explicit_real_power_parameter_type() -> None:
    def power_with_parameter_domain(domain: str) -> str:
        return (
            f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>'
            '<OMS cd="quant1" name="forall"/><OMBVAR><OMV name="n"/></OMBVAR>'
            '<OMA><OMS cd="logic1" name="implies"/><OMA><OMS cd="set1" name="in"/>'
            f'<OMV name="n"/><OMS cd="setname1" name="{domain}"/></OMA><OMA>'
            f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
            '<OMS cd="setname1" name="R"/><OMBIND><OMS cd="fns1" name="lambda"/>'
            '<OMBVAR><OMV name="x"/></OMBVAR><OMA><OMS cd="arith1" name="power"/>'
            '<OMV name="x"/><OMV name="n"/></OMA></OMBIND></OMA></OMA></OMBIND></OMOBJ>'
        )

    statement = "任意の実数nに対してx^nが連続であることを示せ"
    validate_openmath_statement_semantics(power_with_parameter_domain("R"), statement)
    with pytest.raises(MathXMLValidationError, match="positive continuity proposition"):
        validate_openmath_statement_semantics(power_with_parameter_domain("N"), statement)
    membership_statement = "n ∈ ℝ に対して x^n が連続であることを示せ"
    validate_openmath_statement_semantics(
        power_with_parameter_domain("R"),
        membership_statement,
    )
    with pytest.raises(MathXMLValidationError, match="positive continuity proposition"):
        validate_openmath_statement_semantics(
            power_with_parameter_domain("N"),
            membership_statement,
        )


def test_semantic_validation_rejects_predicate_valued_continuity_function() -> None:
    xml = _continuous_expression_xml(
        '<OMA><OMS cd="relation1" name="eq"/><OMV name="x"/><OMI>0</OMI></OMA>'
    )

    with pytest.raises(MathXMLValidationError, match="term-valued OMBIND"):
        validate_openmath_statement_semantics(xml, "x = 0 が連続であることを示せ")


def test_semantic_validation_rejects_proof_exists_despite_incidental_exists_word() -> None:
    square = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMI>2</OMI></OMA>'
    )
    expression = ET.tostring(ET.fromstring(square)[0], encoding="unicode")
    expanded = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>'
        '<OMS cd="quant1" name="exists"/><OMBVAR><OMV name="delta"/></OMBVAR>'
        f"{expression}</OMBIND></OMOBJ>"
    )

    with pytest.raises(MathXMLValidationError, match="epsilon-delta proof method"):
        validate_openmath_statement_semantics(
            expanded,
            "δが存在することを使って、x^2の連続性をε-δで示せ",
        )


def test_semantic_validation_rejects_relative_proof_existence_phrase() -> None:
    square = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMI>2</OMI></OMA>'
    )
    expression = ET.tostring(ET.fromstring(square)[0], encoding="unicode")
    expanded = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>'
        '<OMS cd="quant1" name="exists"/><OMBVAR><OMV name="delta"/></OMBVAR>'
        f"{expression}</OMBIND></OMOBJ>"
    )

    with pytest.raises(MathXMLValidationError, match="epsilon-delta proof method"):
        validate_openmath_statement_semantics(
            expanded,
            "δが存在することを示すε-δ定義を用いて、x^2の連続性を示せ",
        )


def test_semantic_validation_does_not_treat_proof_method_epsilon_delta_as_variables() -> None:
    square = _continuous_expression_xml(
        '<OMA><OMS cd="arith1" name="power"/><OMV name="x"/><OMI>2</OMI></OMA>'
    )

    validate_openmath_statement_semantics(
        square,
        "x^2の連続性をε-δで示せ",
    )


@pytest.mark.parametrize(
    "statement",
    [
        "調和関数 f が連続であることを示せ",
        "調和が連続であることを示せ",
        "累積分布関数 f が連続であることを示せ",
        "累積が連続であることを示せ",
        "面積を表す関数 f が連続であることを示せ",
        "面積が連続であることを示せ",
    ],
)
def test_semantic_validation_does_not_match_operator_inside_japanese_word(
    statement: str,
) -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="f"/></OMA></OMOBJ>'
    )

    validate_openmath_statement_semantics(xml, statement)


@pytest.mark.parametrize(
    ("statement", "operator"),
    [
        ("連続関数 f と g の和が連続であることを示せ", "plus"),
        ("連続関数 f と g の積は連続であることを示せ", "times"),
    ],
)
def test_semantic_validation_requires_operator_for_explicit_japanese_target(
    statement: str,
    operator: str,
) -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="logic1" name="implies"/><OMA><OMS cd="logic1" name="and"/>'
        f'<OMA><OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="f"/></OMA><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="g"/></OMA></OMA><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMV name="f"/></OMA></OMA></OMOBJ>'
    )

    with pytest.raises(MathXMLValidationError, match=operator):
        validate_openmath_statement_semantics(xml, statement)


def test_semantic_validation_rejects_redundant_outer_continuity_point() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>'
        '<OMS cd="quant1" name="forall"/><OMBVAR><OMV name="x"/></OMBVAR>'
        '<OMA><OMS cd="logic1" name="implies"/><OMA><OMS cd="relation1" name="neq"/>'
        '<OMV name="x"/><OMI>0</OMI></OMA><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMA><OMS cd="set1" name="suchthat"/><OMS cd="setname1" name="R"/>'
        '<OMBIND><OMS cd="fns1" name="lambda"/><OMBVAR><OMV name="z"/></OMBVAR>'
        '<OMA><OMS cd="relation1" name="neq"/><OMV name="z"/><OMI>0</OMI></OMA>'
        '</OMBIND></OMA><OMBIND><OMS cd="fns1" name="lambda"/>'
        '<OMBVAR><OMV name="x"/></OMBVAR><OMA><OMS cd="arith1" name="divide"/>'
        '<OMI>1</OMI><OMV name="x"/></OMA></OMBIND></OMA></OMA></OMBIND></OMOBJ>'
    )

    with pytest.raises(MathXMLValidationError, match="Leading universal variable"):
        validate_openmath_statement_semantics(
            xml,
            "0でない点xにおいて1/xの連続性をε-δで示せ",
        )


def test_semantic_validation_accepts_canonical_set_image() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" name="compact"/>'
        '<OMA><OMS cd="set1" name="map"/>'
        '<OMV name="f"/><OMV name="S"/></OMA></OMA></OMOBJ>'
    )

    validate_openmath_statement_semantics(xml, "the image of S under f is compact")


def test_llm_structurer_repairs_continuity_arity_and_function_shape() -> None:
    expression = '<OMA><OMS cd="arith1" name="plus"/><OMV name="x"/><OMI>1</OMI></OMA>'
    wrong_arity = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/></OMA></OMOBJ>'
    )
    raw_term_function = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" name="continuous_on"/>'
        f'<OMS cd="setname1" name="R"/>{expression}</OMA></OMOBJ>'
    )
    repaired = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/>'
        '<OMBIND><OMS cd="fns1" name="lambda"/><OMBVAR><OMV name="x"/></OMBVAR>'
        f"{expression}</OMBIND></OMA></OMOBJ>"
    )
    client = SequenceTextClient([wrong_arity, raw_term_function, repaired])
    structurer = LLMStatementOpenMathStructurer(
        client=client,
        model="configured-model",
        provider="test-provider",
    )

    result = structurer.structure("x+1が実数上で連続であることを示せ")

    assert result == canonicalize_openmath_xml(repaired)
    assert len(client.prompts) == 3
    assert "Canonical continuity shape example" in client.prompts[0]
    assert "set1:map(function, set)" in client.prompts[0]
    assert "Do not use\n  `fns1:image`" in client.prompts[0]
    assert wrong_arity in client.prompts[1]
    assert "requires exactly 2 argument(s); received 1" in client.prompts[1]
    assert "Use exactly `pals1:continuous_on(domain, function)`" in client.prompts[1]
    assert raw_term_function in client.prompts[2]
    assert "function argument of `pals1:continuous_on`" in client.prompts[2]
    assert "make the function argument an `fns1:lambda`" in client.prompts[2]


@pytest.mark.parametrize(
    ("cdbase", "cd", "name"),
    [
        (PALS_OPENMATH_CDBASE, "pals1", "rank_nullity_relation"),
        (OPENMATH_STANDARD_CDBASE, "logic1", "maybe"),
        (OPENMATH_STANDARD_CDBASE, "arith1", "average"),
        (OPENMATH_STANDARD_CDBASE, "set1", "supset"),
        ("https://example.test/openmath", "invented", "mystery"),
    ],
)
def test_semantic_validation_rejects_unknown_profile_symbols(
    cdbase: str,
    cd: str,
    name: str,
) -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cdbase="{cdbase}" cd="{cd}" name="{name}"/><OMV name="A"/>'
        "</OMA></OMOBJ>"
    )

    with pytest.raises(MathXMLValidationError, match="supported OpenMath symbol profile"):
        validate_openmath_statement_semantics(xml, "Aについて示せ")


def test_semantic_validation_rejects_known_name_from_wrong_cd() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="wrong_cd" name="rank"/><OMV name="A"/>'
        "</OMA></OMOBJ>"
    )

    with pytest.raises(MathXMLValidationError, match="supported OpenMath symbol profile"):
        validate_openmath_statement_semantics(xml, "Aのrankを示せ")


def test_semantic_validation_does_not_rescue_predicate_with_wrong_cd() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="fns1" name="is_continuous"/><OMV name="f"/>'
        "</OMA></OMOBJ>"
    )

    with pytest.raises(MathXMLValidationError, match="supported OpenMath symbol profile"):
        validate_openmath_statement_semantics(xml, "fが連続であることを示せ")


def test_statement_faithfulness_rejects_distinct_free_variable_collapse() -> None:
    xml = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="relation1" name="eq"/><OMV name="x"/><OMV name="x"/>'
        "</OMA></OMOBJ>"
    )

    with pytest.raises(MathXMLValidationError, match="collapses distinct variables"):
        validate_openmath_statement_semantics(xml, "x = y")


def test_statement_faithfulness_ignores_unused_bound_declarations() -> None:
    xml = f"""
    <OMOBJ xmlns="{OPENMATH}" version="2.0">
      <OMBIND>
        <OMS cd="quant1" name="forall" />
        <OMBVAR><OMV name="x" /><OMV name="y" /></OMBVAR>
        <OMA>
          <OMS cd="relation1" name="eq" />
          <OMV name="x" /><OMV name="x" />
        </OMA>
      </OMBIND>
    </OMOBJ>
    """

    with pytest.raises(MathXMLValidationError, match="collapses distinct variables"):
        validate_openmath_statement_semantics(xml, "x = y")


def test_statement_faithfulness_allows_repeated_single_variable_and_english_article() -> None:
    equality = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="relation1" name="eq"/><OMV name="z"/><OMV name="z"/>'
        "</OMA></OMOBJ>"
    )
    linear_map = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" name="linear_map"/>'
        '<OMV name="f"/></OMA></OMOBJ>'
    )

    validate_openmath_statement_semantics(equality, "x = x")
    validate_openmath_statement_semantics(linear_map, "f is a linear map")


def test_llm_structurer_repairs_distinct_variable_collapse_from_validation_error() -> None:
    collapsed = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="relation1" name="eq"/><OMV name="x"/><OMV name="x"/>'
        "</OMA></OMOBJ>"
    )
    repaired = (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        '<OMS cd="relation1" name="eq"/><OMV name="x"/><OMV name="y"/>'
        "</OMA></OMOBJ>"
    )
    client = SequenceTextClient([collapsed, repaired])
    structurer = LLMStatementOpenMathStructurer(
        client=client,
        model="configured-model",
        provider="test-provider",
    )

    assert structurer.structure("x = y") == canonicalize_openmath_xml(repaired)
    assert len(client.prompts) == 2
    assert collapsed in client.prompts[1]
    assert "collapses distinct variables" in client.prompts[1]
    assert "Preserve every distinct variable" in client.prompts[1]


@pytest.mark.parametrize(
    ("xml", "statement", "message"),
    [
        (
            f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
            '<OMS cd="relation1" name="eq"/><OMSTR>x</OMSTR><OMSTR>x</OMSTR>'
            "</OMA></OMOBJ>",
            "x = x",
            "OMSTR is not allowed",
        ),
        (
            f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMS cd="set1" name="emptyset"/></OMOBJ>',
            "空集合を考える",
            "empty-set placeholder",
        ),
        (
            f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
            '<OMS cd="arith1" name="power"/><OMV name="y"/><OMI>2</OMI>'
            "</OMA></OMOBJ>",
            "y^2",
            "does not encode a predicate/proposition",
        ),
        (
            f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
            '<OMS cd="relation1" name="eq"/><OMI>1</OMI><OMI>1</OMI>'
            "</OMA></OMOBJ>",
            "y^nを示せ",
            "omits variables present in the statement",
        ),
    ],
)
def test_statement_semantic_validation_rejects_nonsemantic_candidates(
    xml: str,
    statement: str,
    message: str,
) -> None:
    with pytest.raises(MathXMLValidationError, match=message):
        validate_openmath_statement_semantics(xml, statement)


def test_llm_structurer_has_no_invalid_xml_fallback() -> None:
    client = FakeTextClient("The statement probably means x = x.")
    structurer = LLMStatementOpenMathStructurer(
        client=client,
        model="configured-model",
        provider="test-provider",
    )

    with pytest.raises(OpenMathStructuringError, match="invalid OpenMath XML"):
        structurer.structure("x = x")

    assert len(client.calls) == 3
    assert all("x = x" in prompt for _model, prompt in client.calls)


def test_llm_structurer_surfaces_provider_failure() -> None:
    structurer = LLMStatementOpenMathStructurer(
        client=FailingTextClient(),
        model="configured-model",
        provider="test-provider",
    )

    with pytest.raises(OpenMathStructuringError, match="provider unavailable"):
        structurer.structure("x = x")


def _forall_equality(first: str, second: str) -> str:
    return f"""
    <OMOBJ xmlns="{OPENMATH}" version="2.0">
      <OMBIND>
        <OMS cd="quant1" name="forall" />
        <OMBVAR><OMV name="{first}" /><OMV name="{second}" /></OMBVAR>
        <OMA>
          <OMS cd="relation1" name="eq" />
          <OMV name="{first}" />
          <OMV name="{second}" />
        </OMA>
      </OMBIND>
    </OMOBJ>
    """


def _profile_oms(cd: str, name: str) -> str:
    cdbase = f' cdbase="{PALS_OPENMATH_CDBASE}"' if cd == "pals1" else ""
    return f'<OMS{cdbase} cd="{cd}" name="{name}"/>'


def _continuous_expression_xml(expression: str) -> str:
    return (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMA>'
        f'<OMS cdbase="{PALS_OPENMATH_CDBASE}" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/><OMBIND><OMS cd="fns1" name="lambda"/>'
        f'<OMBVAR><OMV name="x"/></OMBVAR>{expression}</OMBIND></OMA></OMOBJ>'
    )
