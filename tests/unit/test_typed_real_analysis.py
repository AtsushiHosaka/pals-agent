from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError, canonicalize_retrieval_openmath_xml
from pals_agent.typed_math import validate_typed_math_openmath_xml
from pals_agent.typed_real_analysis import (
    TYPED_REAL_ANALYSIS_OPENMATH_CDBASE,
    canonicalize_typed_real_analysis_openmath_xml,
    validate_canonical_typed_real_analysis_openmath_xml,
    validate_typed_real_analysis_openmath_xml,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_BASE_MANIFEST = (
    _REPOSITORY_ROOT / "docs" / "typed-real-analysis-v1-authoring-manifest-proposal.json"
)
_BASE_DESIGN = _REPOSITORY_ROOT / "docs" / "typed-real-analysis-v1-design.md"
_BASE_WITNESS = _REPOSITORY_ROOT / "docs" / "typed-real-analysis-v1-authoring-witnesses.lean"
_EXPANSION_MANIFEST = (
    _REPOSITORY_ROOT / "docs" / "typed-real-analysis-v1-expansion-r2-sealed-manifest.proposal.json"
)
_EXPANSION_DESIGN = _REPOSITORY_ROOT / "docs" / "typed-real-analysis-v1-expansion-r2-design.md"
_EXPANSION_WITNESS = (
    _REPOSITORY_ROOT / "docs" / "typed-real-analysis-v1-expansion-r2-authoring-witnesses.lean"
)
_GENERATOR = (
    _REPOSITORY_ROOT
    / "pals-scripts"
    / "generate-typed-real-analysis-v1-authoring-manifest.py"
)


def _cards() -> dict[str, str]:
    payload = _manifest()
    return {card["id"]: card["openmath_xml"] for card in payload["cards"]}


def _manifest() -> dict[str, object]:
    return json.loads(_BASE_MANIFEST.read_text(encoding="utf-8"))


def _expansion_manifest() -> dict[str, object]:
    return json.loads(_EXPANSION_MANIFEST.read_text(encoding="utf-8"))


def _typed_oms(cd: str, name: str) -> str:
    return f'<OMS cdbase="{TYPED_REAL_ANALYSIS_OPENMATH_CDBASE}" cd="{cd}" name="{name}"/>'


def _declaration(name: str, sort: str) -> str:
    return (
        f"<OMATTR><OMATP>{_typed_oms('typed1', 'type')}{sort}</OMATP>"
        f'<OMV name="{name}"/></OMATTR>'
    )


def _binding(declarations: str, body: str) -> str:
    return (
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMBIND>'
        f"{_typed_oms('typed1', 'forall')}<OMBVAR>{declarations}</OMBVAR>{body}"
        "</OMBIND></OMOBJ>"
    )


def _app(cd: str, name: str, *arguments: str, typed: bool = False) -> str:
    head = _typed_oms(cd, name) if typed else f'<OMS cd="{cd}" name="{name}"/>'
    return f"<OMA>{head}{''.join(arguments)}</OMA>"


def _of_int(value: int) -> str:
    return _app("realanalysis1", "of_int", f"<OMI>{value}</OMI>", typed=True)


def _real_lambda(name: str, body: str) -> str:
    return (
        f"<OMBIND>{_typed_oms('realanalysis1', 'lambda')}<OMBVAR>"
        f"{_declaration(name, _typed_oms('typed1', 'Real'))}</OMBVAR>{body}</OMBIND>"
    )


def test_typed_real_analysis_accepts_and_canonicalizes_each_adopted_card() -> None:
    for payload in (_manifest(), _expansion_manifest()):
        cards = payload["cards"]
        assert isinstance(cards, list)
        for card in cards:
            assert isinstance(card, dict)
            raw_xml = card["openmath_xml"]
            validate_typed_real_analysis_openmath_xml(raw_xml)
            canonical = canonicalize_typed_real_analysis_openmath_xml(raw_xml)
            assert validate_canonical_typed_real_analysis_openmath_xml(canonical) == canonical


def test_typed_real_analysis_manifest_binds_actual_profile_canonicalization() -> None:
    payload = _manifest()
    registry_path = (
        _REPOSITORY_ROOT
        / "pals-agent"
        / "pals_agent"
        / "content_dictionaries"
        / "typed-real-analysis-v1-registry.json"
    )
    profile = payload["profile"]
    assert isinstance(profile, dict)
    assert payload["schema_version"] == "pals.typed-real-analysis-v1-sealed-manifest.v1"
    assert payload["status"] == "sealed_local_authoring_revision_not_admitted"
    assert payload["seal"] == {
        "scope": "local typed-real-analysis authoring evidence only",
        "admission": "not admitted to the generic DB, seed, embedding index, or PFI package",
        "revision": "typed-real-analysis-v1-local-r1",
    }
    assert profile["profile_design_path"] == "docs/typed-real-analysis-v1-design.md"
    assert profile["profile_design_sha256"] == (
        "sha256:" + hashlib.sha256(_BASE_DESIGN.read_bytes()).hexdigest()
    )
    assert profile["registry_path"] == (
        "pals_agent/content_dictionaries/typed-real-analysis-v1-registry.json"
    )
    assert profile["registry_digest"] == (
        "sha256:" + hashlib.sha256(registry_path.read_bytes()).hexdigest()
    )

    receipt = payload["lean_receipt"]
    assert isinstance(receipt, dict)
    assert receipt["witness_path"] == "docs/typed-real-analysis-v1-authoring-witnesses.lean"
    assert receipt["witness_file_sha256"] == (
        "sha256:" + hashlib.sha256(_BASE_WITNESS.read_bytes()).hexdigest()
    )
    witness_text = _BASE_WITNESS.read_text(encoding="utf-8")

    cards = payload["cards"]
    assert isinstance(cards, list) and len(cards) == 4
    witness_audit = payload["witness_audit"]
    assert isinstance(witness_audit, list)
    adopted_witnesses = {
        audit["witness_id"]: audit
        for audit in witness_audit
        if isinstance(audit, dict) and audit["disposition"] == "adopted"
    }
    assert len(adopted_witnesses) == 4
    canonical_statements: set[str] = set()
    for card in cards:
        assert isinstance(card, dict)
        canonical = canonicalize_typed_real_analysis_openmath_xml(card["openmath_xml"])
        assert canonical not in canonical_statements
        canonical_statements.add(canonical)
        assert card["canonical_openmath_xml"] == canonical
        assert card["openmath_xml_sha256"] == (
            "sha256:" + hashlib.sha256(card["openmath_xml"].encode("utf-8")).hexdigest()
        )
        assert card["canonical_openmath_xml_sha256"] == (
            "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        )
        assert card["canonical_statement_sha256"] == (
            "sha256:"
            + hashlib.sha256(card["canonical_statement"].encode("utf-8")).hexdigest()
        )
        assert card["lean_target_sha256"] == (
            "sha256:" + hashlib.sha256(card["lean_target"].encode("utf-8")).hexdigest()
        )
        assert card["lean_witness_sha256"] == (
            "sha256:" + hashlib.sha256(card["lean_witness"].encode("utf-8")).hexdigest()
        )
        assert card["source_witness_sha256"] == card["lean_witness_sha256"]
        assert card["profile_validation_status"] == "validated_local_typed_real_analysis_v1_sealed"
        assert isinstance(card["proof_strategy"], str) and card["proof_strategy"]
        assert isinstance(card["sketch_steps"], list) and 4 <= len(card["sketch_steps"]) <= 8
        assert all(isinstance(step, str) and step.strip() for step in card["sketch_steps"])
        witness_ids = card["source_witness_ids"]
        assert isinstance(witness_ids, list) and len(witness_ids) == 1
        audit = adopted_witnesses[witness_ids[0]]
        assert audit["card_id"] == card["id"]
        assert audit["source_sha256"] == card["source_witness_sha256"]
        assert f"-- manifest card: {card['id']}\n{card['lean_witness']}" in witness_text

    unsigned = dict(payload)
    digest = unsigned.pop("manifest_payload_sha256")
    serialized = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert digest == "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    assert digest == "sha256:eb7e2e6715678fd45efa30a01e583f4274969e90fca8b2164ad83154a25cb6a8"


def test_typed_real_analysis_expansion_manifest_is_disjoint_and_bound() -> None:
    payload = _expansion_manifest()
    registry_path = (
        _REPOSITORY_ROOT
        / "pals-agent"
        / "pals_agent"
        / "content_dictionaries"
        / "typed-real-analysis-v1-registry.json"
    )
    profile = payload["profile"]
    assert isinstance(profile, dict)
    assert payload["schema_version"] == "pals.typed-real-analysis-v1-expansion-sealed-manifest.v1"
    assert payload["status"] == "sealed_local_authoring_revision_not_admitted"
    assert payload["seal"] == {
        "scope": "local typed-real-analysis-v1 r2 expansion authoring evidence only",
        "admission": "not admitted to the generic DB, seed, embedding index, or PFI package",
        "revision": "typed-real-analysis-v1-expansion-r2",
    }
    assert profile["profile_design_path"] == "docs/typed-real-analysis-v1-expansion-r2-design.md"
    assert profile["profile_design_sha256"] == (
        "sha256:" + hashlib.sha256(_EXPANSION_DESIGN.read_bytes()).hexdigest()
    )
    assert profile["registry_digest"] == (
        "sha256:" + hashlib.sha256(registry_path.read_bytes()).hexdigest()
    )
    receipt = payload["lean_receipt"]
    assert isinstance(receipt, dict)
    assert receipt["witness_path"] == (
        "docs/typed-real-analysis-v1-expansion-r2-authoring-witnesses.lean"
    )
    assert receipt["witness_file_sha256"] == (
        "sha256:" + hashlib.sha256(_EXPANSION_WITNESS.read_bytes()).hexdigest()
    )
    cards = payload["cards"]
    assert isinstance(cards, list) and len(cards) == 15
    base_ids = set(_cards())
    expansion_ids: set[str] = set()
    canonical_xml: set[str] = set()
    witness_text = _EXPANSION_WITNESS.read_text(encoding="utf-8")
    for card in cards:
        assert isinstance(card, dict)
        assert card["id"] not in base_ids
        assert card["id"] not in expansion_ids
        expansion_ids.add(card["id"])
        canonical = canonicalize_typed_real_analysis_openmath_xml(card["openmath_xml"])
        assert canonical == card["canonical_openmath_xml"]
        assert canonical not in canonical_xml
        canonical_xml.add(canonical)
        assert 4 <= len(card["sketch_steps"]) <= 8
        assert card["proof_strategy"]
        assert f"-- manifest card: {card['id']}\n{card['lean_witness']}" in witness_text
    assert len(canonical_xml.intersection({
        card["canonical_openmath_xml"] for card in _manifest()["cards"]
    })) == 0
    unsigned = dict(payload)
    digest = unsigned.pop("manifest_payload_sha256")
    serialized = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert digest == "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def test_typed_real_analysis_manifests_are_current_generator_output(tmp_path: Path) -> None:
    base_output = tmp_path / "typed-real-analysis-base.json"
    expansion_output = tmp_path / "typed-real-analysis-expansion.json"
    completed = subprocess.run(
        [sys.executable, str(_GENERATOR), "--scope", "base", "--output", str(base_output)],
        cwd=_REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert base_output.read_bytes() == _BASE_MANIFEST.read_bytes()
    expanded = subprocess.run(
        [
            sys.executable,
            str(_GENERATOR),
            "--scope",
            "expansion",
            "--output",
            str(expansion_output),
        ],
        cwd=_REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert expanded.returncode == 0, expanded.stdout + expanded.stderr
    assert expansion_output.read_bytes() == _EXPANSION_MANIFEST.read_bytes()


def test_typed_real_analysis_alpha_normalizes_real_binders() -> None:
    raw = _cards()["real_analysis_has_deriv_square"]
    renamed = raw.replace('name="a"', 'name="b"').replace('name="x"', 'name="y"')

    assert canonicalize_typed_real_analysis_openmath_xml(raw) == (
        canonicalize_typed_real_analysis_openmath_xml(renamed)
    )


def test_typed_real_analysis_does_not_widen_generic_or_base_typed_math() -> None:
    raw = _cards()["real_analysis_has_deriv_square"]

    with pytest.raises(MathXMLValidationError):
        canonicalize_retrieval_openmath_xml(raw)
    with pytest.raises(MathXMLValidationError, match="outside typed-math-v1"):
        validate_typed_math_openmath_xml(raw)


def test_typed_real_analysis_rejects_function_scalar_and_proposition_mismatches() -> None:
    declarations = _declaration("a", _typed_oms("typed1", "Real"))
    derivative_with_scalar_function = _binding(
        declarations,
        _app(
            "realanalysis1",
            "has_deriv_at",
            '<OMV name="a"/>',
            '<OMV name="a"/>',
            _of_int(0),
            typed=True,
        ),
    )
    derivative_with_function_slope = _binding(
        declarations,
        _app(
            "realanalysis1",
            "has_deriv_at",
            _real_lambda("x", '<OMV name="x"/>'),
            '<OMV name="a"/>',
            _real_lambda("z", '<OMV name="z"/>'),
            typed=True,
        ),
    )
    integral_as_scalar = _binding(
        _declaration("f", _typed_oms("realanalysis1", "RealFunction"))
        + _declaration("a", _typed_oms("typed1", "Real")),
        _app(
            "relation1",
            "eq",
            _app(
                "realanalysis1",
                "interval_integrable",
                '<OMV name="f"/>',
                '<OMV name="a"/>',
                '<OMV name="a"/>',
                typed=True,
            ),
            _app("realanalysis1", "of_int", "<OMI>0</OMI>", typed=True),
        ),
    )

    with pytest.raises(MathXMLValidationError, match=r"Argument 1.*RealFunction.*Real"):
        validate_typed_real_analysis_openmath_xml(derivative_with_scalar_function)
    with pytest.raises(MathXMLValidationError, match=r"Argument 3.*Real.*RealFunction"):
        validate_typed_real_analysis_openmath_xml(derivative_with_function_slope)
    with pytest.raises(MathXMLValidationError, match=r"Prop.*Real"):
        validate_typed_real_analysis_openmath_xml(integral_as_scalar)


def test_typed_real_analysis_rejects_bare_and_noncanonical_literals() -> None:
    raw = _cards()["real_analysis_has_deriv_square"]
    bare_real_literal = raw.replace(
        '<OMA><OMS cdbase="urn:pals:openmath:typed-math:v1" '
        'cd="realanalysis1" name="of_int"/><OMI>2</OMI></OMA>',
        "<OMI>2</OMI>",
        1,
    )
    malformed_rational = _binding(
        _declaration("a", _typed_oms("typed1", "Real")),
        _app(
            "relation1",
            "eq",
            _app("realanalysis1", "of_rat", "<OMI>2</OMI>", "<OMI>4</OMI>", typed=True),
            '<OMV name="a"/>',
        ),
    )
    real_exponent = raw.replace(
        "<OMI>2</OMI></OMA></OMBIND><OMV name=\"a\"/>",
        '<OMA><OMS cdbase="urn:pals:openmath:typed-math:v1" '
        'cd="realanalysis1" name="of_int"/><OMI>2</OMI></OMA></OMA></OMBIND>'
        '<OMV name="a"/>',
        1,
    )

    with pytest.raises(MathXMLValidationError, match=r"arith1:times.*Real.*Nat literal"):
        validate_typed_real_analysis_openmath_xml(bare_real_literal)
    with pytest.raises(MathXMLValidationError, match="reduced numerator"):
        validate_typed_real_analysis_openmath_xml(malformed_rational)
    with pytest.raises(MathXMLValidationError, match="0..64 Nat literal"):
        validate_typed_real_analysis_openmath_xml(real_exponent)


@pytest.mark.parametrize(
    ("forbidden", "label"),
    [
        ("continuous_on_uIcc", "MVT prerequisite"),
        ("has_taylor_lagrange_remainder", "Taylor"),
        ("interval_integral", "integral value"),
        ("has_improper_integral_to_pos_inf", "improper integral"),
        ("unsigned_extension", "unsigned symbol"),
    ],
)
def test_typed_real_analysis_rejects_out_of_scope_symbols(forbidden: str, label: str) -> None:
    xml = (
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMA>'
        f'{_typed_oms("realanalysis1", forbidden)}'
        "<OMI>0</OMI>"
        "</OMA></OMOBJ>"
    )

    with pytest.raises(MathXMLValidationError, match="outside typed-real-analysis-v1") as error:
        validate_typed_real_analysis_openmath_xml(xml)
    assert label
    assert forbidden in str(error.value)


def test_typed_real_analysis_rejects_inherited_typed_cdbase_and_invalid_lambda_sort() -> None:
    raw = _cards()["real_analysis_interval_integrable_square_zero_one"]
    inherited = raw.replace(f' cdbase="{TYPED_REAL_ANALYSIS_OPENMATH_CDBASE}"', "")
    inherited = inherited.replace(
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0">',
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0" '
        f'cdbase="{TYPED_REAL_ANALYSIS_OPENMATH_CDBASE}">',
    )
    inherited = inherited.replace(
        '<OMS cd="arith1"',
        '<OMS cdbase="http://www.openmath.org/cd" cd="arith1"',
    )
    function_lambda = raw.replace(
        'cd="typed1" name="Real"/>', 'cd="realanalysis1" name="RealFunction"/>', 1
    )

    with pytest.raises(MathXMLValidationError, match=r"OMOBJ.*attribute `cdbase`"):
        validate_typed_real_analysis_openmath_xml(inherited)
    with pytest.raises(MathXMLValidationError, match="lambda binds one variable of sort `Real`"):
        validate_typed_real_analysis_openmath_xml(function_lambda)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda xml: xml.replace('version="2.0"', 'version="2.0" injected="x"', 1),
        lambda xml: xml.replace('cd="typed1"', 'cd="typed1" injected="x"', 1),
        lambda xml: xml.replace('name="a"', 'name="a" injected="x"', 1),
        lambda xml: xml.replace("<OMI>2</OMI>", '<OMI injected="x">2</OMI>', 1),
        lambda xml: xml.replace("<OMA>", '<OMA injected="x">', 1),
        lambda xml: xml.replace("<OMBIND>", '<OMBIND injected="x">', 1),
        lambda xml: xml.replace("<OMBVAR>", '<OMBVAR injected="x">', 1),
        lambda xml: xml.replace("<OMATTR>", '<OMATTR injected="x">', 1),
        lambda xml: xml.replace("<OMATP>", '<OMATP injected="x">', 1),
    ],
)
def test_typed_real_analysis_rejects_unknown_xml_attributes(mutator: Callable[[str], str]) -> None:
    raw = _cards()["real_analysis_has_deriv_square"]

    with pytest.raises(MathXMLValidationError, match=r"does not permit attribute `injected`"):
        validate_typed_real_analysis_openmath_xml(mutator(raw))
