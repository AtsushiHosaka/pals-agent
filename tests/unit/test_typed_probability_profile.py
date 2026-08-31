from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError, canonicalize_retrieval_openmath_xml
from pals_agent.typed_math import validate_typed_math_openmath_xml
from pals_agent.typed_probability_profile import (
    TYPED_PROBABILITY_OPENMATH_CDBASE,
    TYPED_PROBABILITY_PROFILE,
    canonicalize_typed_probability_openmath_xml,
    validate_canonical_typed_probability_openmath_xml,
    validate_typed_probability_openmath_xml,
)

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "docs/typed-probability-v1-authoring-manifest.proposal.json"
WITNESS = ROOT / "docs/typed-probability-v1-authoring-witnesses.lean"
REGISTRY = ROOT / "pals-agent/pals_agent/content_dictionaries/typed-probability-v1-registry.json"
DESIGN = ROOT / "docs/probability-typed-profile-v1-design.md"
GENERATOR = ROOT / "pals-scripts/generate-typed-probability-v1-authoring-manifest.py"
OPENMATH = "http://www.openmath.org/OpenMath"
STANDARD = "http://www.openmath.org/cd"
TYPED = TYPED_PROBABILITY_OPENMATH_CDBASE


def _manifest() -> dict[str, object]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _typed(cd: str, name: str) -> str:
    return f'<OMS cdbase="{TYPED}" cd="{cd}" name="{name}"/>'


def _standard(cd: str, name: str) -> str:
    return f'<OMS cdbase="{STANDARD}" cd="{cd}" name="{name}"/>'


def _app(operator: str, *arguments: str) -> str:
    return f"<OMA>{operator}{''.join(arguments)}</OMA>"


def _papp(name: str, *arguments: str) -> str:
    return _app(_typed("probability1", name), *arguments)


def _decl(name: str, sort: str) -> str:
    return f"<OMATTR><OMATP>{_typed('typed1', 'type')}{sort}</OMATP><OMV name=\"{name}\"/></OMATTR>"


def _sort(name: str, carrier: str | None = None) -> str:
    if carrier is None:
        return _typed("probability1", name)
    return _papp(name, f'<OMV name="{carrier}"/>')


def _binding(declarations: str, body: str) -> str:
    return (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>{_typed("typed1", "forall")}'
        f"<OMBVAR>{declarations}</OMBVAR>{body}</OMBIND></OMOBJ>"
    )


def _eq(left: str, right: str) -> str:
    return _app(_standard("relation1", "eq"), left, right)


def _real_of_int(value: int) -> str:
    return _papp("real_of_int", f"<OMI>{value}</OMI>")


def test_typed_probability_accepts_and_canonicalizes_each_reviewed_card() -> None:
    cards = _manifest()["cards"]
    assert isinstance(cards, list) and len(cards) == 10
    for card in cards:
        assert isinstance(card, dict)
        raw = card["openmath_xml"]
        assert isinstance(raw, str)
        validate_typed_probability_openmath_xml(raw)
        canonical = canonicalize_typed_probability_openmath_xml(raw)
        assert validate_canonical_typed_probability_openmath_xml(canonical) == canonical


def test_typed_probability_sealed_manifest_binds_profile_and_evidence() -> None:
    payload = _manifest()
    assert payload["schema_version"] == "pals.typed-probability-v1.sealed-manifest.v1"
    assert payload["status"] == "sealed_local_authoring_revision_not_admitted"
    assert payload["admitted_card_count"] == 10
    assert payload["excluded_card_count"] == 7
    assert payload["seal"] == {
        "scope": "local typed-probability authoring evidence only",
        "admission": "not admitted to the generic DB, seed, embedding index, or PFI package",
        "revision": "typed-probability-v1-local-r1",
    }
    profile = payload["profile"]
    assert isinstance(profile, dict)
    assert profile["id"] == TYPED_PROBABILITY_PROFILE
    assert profile["design_sha256"] == "sha256:" + hashlib.sha256(DESIGN.read_bytes()).hexdigest()
    assert profile["probability1_cd_bundle_sha256"] == (
        "sha256:" + hashlib.sha256(REGISTRY.read_bytes()).hexdigest()
    )
    receipt = payload["lean_receipt"]
    assert isinstance(receipt, dict)
    witness = WITNESS.read_text(encoding="utf-8")
    assert receipt["witness_file_sha256"] == (
        "sha256:" + hashlib.sha256(witness.encode()).hexdigest()
    )
    assert receipt["toolchain"] == "leanprover/lean4:v4.32.0-rc1"

    cards = payload["cards"]
    assert isinstance(cards, list)
    for card in cards:
        assert isinstance(card, dict)
        raw = card["openmath_xml"]
        assert isinstance(raw, str)
        canonical = canonicalize_typed_probability_openmath_xml(raw)
        assert card["source_candidate_id"] == card["id"]
        assert card["openmath_profile"] == TYPED_PROBABILITY_PROFILE
        assert card["canonical_openmath_xml"] == canonical
        assert card["canonical_openmath_xml_sha256"] == (
            "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
        )
        assert card["openmath_xml_sha256"] == "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
        assert card["canonical_statement_sha256"] == (
            "sha256:" + hashlib.sha256(card["canonical_statement"].encode()).hexdigest()
        )
        assert card["lean_target_sha256"] == (
            "sha256:" + hashlib.sha256(card["lean_target"].encode()).hexdigest()
        )
        assert card["lean_witness_sha256"] == (
            "sha256:" + hashlib.sha256(card["lean_witness"].encode()).hexdigest()
        )
        steps = card["sketch_steps"]
        assert isinstance(steps, list) and 4 <= len(steps) <= 8
        assert all(isinstance(step, str) and step.strip() for step in steps)
        assert isinstance(card["proof_strategy"], str) and card["proof_strategy"]
        marker = f"-- manifest card: {card['id']}\n{card['lean_target']} := {card['lean_witness']}"
        assert marker in witness
        assert card["compiler_receipt_status"] == "verified"
        assert card["profile_validation_status"] == "validated_local_typed_probability_v1_sealed"

    excluded = payload["excluded_cards"]
    assert isinstance(excluded, list) and len(excluded) == 7
    assert {card["id"] for card in excluded} == {
        "prob_conditional_definition",
        "prob_conditional_self",
        "prob_conditional_multiplication_rule",
        "prob_bayes_formula",
        "prob_variance_nonnegative",
        "prob_variance_scaling",
        "prob_variance_translation",
    }
    assert all(
        card["typed_profile_disposition"] == "explicitly_rejected_or_deferred"
        for card in excluded
    )

    unsigned = dict(payload)
    digest = unsigned.pop("manifest_payload_sha256")
    serialized = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert digest == "sha256:" + hashlib.sha256(serialized.encode()).hexdigest()


def test_typed_probability_manifest_is_current_generator_output(tmp_path: Path) -> None:
    output = tmp_path / "typed-probability.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "pals-agent")
    completed = subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(output)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert output.read_bytes() == MANIFEST.read_bytes()


def test_typed_probability_alpha_normalizes_bound_variables() -> None:
    cards = _manifest()["cards"]
    assert isinstance(cards, list)
    first = next(card for card in cards if card["id"] == "prob_binomial_pmf")
    assert isinstance(first, dict)
    raw = first["openmath_xml"]
    assert isinstance(raw, str)
    renamed = raw.replace('name="n"', 'name="a"').replace('name="k"', 'name="b"').replace(
        'name="p"', 'name="q"'
    )
    assert canonicalize_typed_probability_openmath_xml(raw) == (
        canonicalize_typed_probability_openmath_xml(renamed)
    )


def test_typed_probability_does_not_widen_generic_or_base_typed_math() -> None:
    cards = _manifest()["cards"]
    assert isinstance(cards, list) and cards
    raw = cards[0]["openmath_xml"]
    assert isinstance(raw, str)
    with pytest.raises(MathXMLValidationError):
        canonicalize_retrieval_openmath_xml(raw)
    with pytest.raises(MathXMLValidationError, match="outside typed-math-v1"):
        validate_typed_math_openmath_xml(raw)


def test_typed_probability_rejects_carrier_mismatch_and_multiple_sample_spaces() -> None:
    declarations = "".join(
        (
            _decl("Omega", _sort("SampleSpace")),
            _decl("Omega2", _sort("SampleSpace")),
            _decl("mu", _sort("ProbabilityMeasure", "Omega")),
            _decl("S", _sort("Event", "Omega2")),
        )
    )
    carrier_mismatch = _binding(
        declarations,
        _eq(_papp("probability", '<OMV name="mu"/>', '<OMV name="S"/>'), _real_of_int(0)),
    )
    with pytest.raises(MathXMLValidationError, match="Event\\(Omega\\)"):
        validate_typed_probability_openmath_xml(carrier_mismatch)

    multiple_spaces = _binding(
        _decl("Omega", _sort("SampleSpace")) + _decl("Omega2", _sort("SampleSpace")),
        _eq('<OMV name="Omega"/>', '<OMV name="Omega2"/>'),
    )
    with pytest.raises(MathXMLValidationError, match="exactly one SampleSpace"):
        validate_typed_probability_openmath_xml(multiple_spaces)


def test_typed_probability_rejects_cross_scalar_and_unreviewed_operations() -> None:
    p_real = _binding(
        _decl("n", _typed("typed1", "Nat")) + _decl("p", _typed("typed1", "Real")),
        _eq(
            _papp("binomial_distribution", '<OMV name="n"/>', '<OMV name="p"/>'),
            _papp("binomial_distribution", '<OMV name="n"/>', '<OMV name="p"/>'),
        ),
    )
    bare_real_literal = _binding(
        _decl("c", _typed("typed1", "Real")), _eq("<OMI>0</OMI>", '<OMV name="c"/>')
    )
    negative_natural = _binding(
        _decl("n", _typed("typed1", "Nat")),
        _eq(
            _papp("choose", '<OMV name="n"/>', "<OMI>-1</OMI>"),
            _papp("choose", '<OMV name="n"/>', "<OMI>0</OMI>"),
        ),
    )
    probability_in_real_mul = _binding(
        _decl("p", _sort("Probability")),
        _eq(_papp("real_mul", '<OMV name="p"/>', '<OMV name="p"/>'), _real_of_int(0)),
    )
    unreviewed_conditional = _binding(
        _decl("Omega", _sort("SampleSpace"))
        + _decl("mu", _sort("ProbabilityMeasure", "Omega"))
        + _decl("S", _sort("Event", "Omega")),
        _eq(
            _papp(
                "conditional_probability",
                '<OMV name="mu"/>',
                '<OMV name="S"/>',
                '<OMV name="S"/>',
            ),
            _papp(
                "conditional_probability",
                '<OMV name="mu"/>',
                '<OMV name="S"/>',
                '<OMV name="S"/>',
            ),
        ),
    )
    unreviewed_variance = _binding(
        _decl("Omega", _sort("SampleSpace"))
        + _decl("mu", _sort("ProbabilityMeasure", "Omega"))
        + _decl("X", _sort("RealRandomVariable", "Omega")),
        _eq(
            _papp("variance", '<OMV name="X"/>', '<OMV name="mu"/>'),
            _papp("variance", '<OMV name="X"/>', '<OMV name="mu"/>'),
        ),
    )
    for xml in (
        p_real,
        bare_real_literal,
        negative_natural,
        probability_in_real_mul,
        unreviewed_conditional,
        unreviewed_variance,
    ):
        with pytest.raises(MathXMLValidationError):
            validate_typed_probability_openmath_xml(xml)


def test_typed_probability_rejects_unreviewed_expectation_and_inherited_cdbase() -> None:
    general_expectation = _binding(
        _decl("Omega", _sort("SampleSpace"))
        + _decl("mu", _sort("ProbabilityMeasure", "Omega"))
        + _decl("X", _sort("RealRandomVariable", "Omega")),
        _eq(_papp("expectation", '<OMV name="X"/>', '<OMV name="mu"/>'), _real_of_int(0)),
    )
    with pytest.raises(MathXMLValidationError, match="constant_rv"):
        validate_typed_probability_openmath_xml(general_expectation)

    cards = _manifest()["cards"]
    assert isinstance(cards, list) and cards
    raw = cards[0]["openmath_xml"]
    assert isinstance(raw, str)
    inherited = raw.replace(f' cdbase="{TYPED}"', "")
    inherited = inherited.replace(
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0">',
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0" cdbase="{TYPED}">',
    )
    with pytest.raises(MathXMLValidationError):
        validate_typed_probability_openmath_xml(inherited)
