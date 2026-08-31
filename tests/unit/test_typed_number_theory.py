from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError, canonicalize_retrieval_openmath_xml
from pals_agent.typed_math import validate_typed_math_openmath_xml
from pals_agent.typed_number_theory import (
    TYPED_NUMBER_THEORY_OPENMATH_CDBASE,
    TYPED_NUMBER_THEORY_PROFILE,
    canonicalize_typed_number_theory_openmath_xml,
    validate_canonical_typed_number_theory_openmath_xml,
    validate_typed_number_theory_openmath_xml,
)
from pals_agent.typed_number_theory_manifest import (
    TypedNumberTheoryManifestError,
    load_typed_number_theory_manifest,
    validate_typed_number_theory_manifest,
)

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "docs/typed-number-theory-v1-authoring-manifest.proposal.json"
WITNESS = ROOT / "docs/typed-number-theory-v1-authoring-witnesses.lean"
REGISTRY = ROOT / "pals-agent/pals_agent/content_dictionaries/typed-number-theory-v1-registry.json"
GENERATOR = ROOT / "pals-scripts/generate-typed-number-theory-v1-authoring-manifest.py"
OPENMATH = "http://www.openmath.org/OpenMath"
STANDARD = "http://www.openmath.org/cd"
TYPED = TYPED_NUMBER_THEORY_OPENMATH_CDBASE


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


def _nat(value: int) -> str:
    return _app(_typed("numbertheory1", "nat_literal"), f"<OMI>{value}</OMI>")


def _decl(name: str, sort: str) -> str:
    return (
        f"<OMATTR><OMATP>{_typed('typed1', 'type')}"
        f"{_typed('numbertheory1', sort)}</OMATP><OMV name=\"{name}\"/></OMATTR>"
    )


def _binding(declarations: str, body: str) -> str:
    return (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>{_typed("typed1", "forall")}'
        f"<OMBVAR>{declarations}</OMBVAR>{body}</OMBIND></OMOBJ>"
    )


def _eq(left: str, right: str) -> str:
    return _app(_standard("relation1", "eq"), left, right)


def _reseal(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_payload_sha256")
    payload["manifest_payload_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def test_number_theory_manifest_is_current_and_all_cards_use_actual_validator() -> None:
    payload = load_typed_number_theory_manifest(MANIFEST, repository_root=ROOT)
    assert payload["schema_version"] == "pals.typed-number-theory-v1-sealed-manifest.v1"
    assert payload["status"] == "sealed_local_authoring_revision_not_admitted"
    assert payload["admitted_card_count"] == 12
    assert payload["excluded_card_count"] == 4
    profile = payload["profile"]
    assert isinstance(profile, dict)
    assert profile["id"] == TYPED_NUMBER_THEORY_PROFILE
    assert profile["registry_sha256"] == (
        "sha256:" + hashlib.sha256(REGISTRY.read_bytes()).hexdigest()
    )
    cards = payload["cards"]
    assert isinstance(cards, list) and len(cards) == 12
    for card in cards:
        assert isinstance(card, dict)
        raw = card["openmath_xml"]
        assert isinstance(raw, str)
        canonical = canonicalize_typed_number_theory_openmath_xml(raw)
        assert validate_canonical_typed_number_theory_openmath_xml(canonical) == canonical
        assert card["canonical_openmath_xml"] == canonical
        assert 4 <= len(card["sketch_steps"]) <= 8
        marker = f"-- manifest card: {card['id']}\n{card['lean_target']} := {card['lean_witness']}"
        assert marker in WITNESS.read_text(encoding="utf-8")


def test_number_theory_manifest_is_deterministic_generator_output(tmp_path: Path) -> None:
    output = tmp_path / "typed-number-theory.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "pals-agent")
    completed = subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(output), "--verify-lean"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert output.read_bytes() == MANIFEST.read_bytes()


def test_number_theory_rejects_zero_or_symbolic_modulus_and_carrier_mixing() -> None:
    n = '<OMV name="n"/>'
    m = '<OMV name="m"/>'
    def nat_mod(left: str, right: str) -> str:
        return _app(_typed("numbertheory1", "nat_mod"), left, right)

    zero_modulus = _binding(_decl("n", "Nat"), _eq(nat_mod(n, _nat(0)), _nat(0)))
    with pytest.raises(MathXMLValidationError, match="positive Nat literal modulus"):
        validate_typed_number_theory_openmath_xml(zero_modulus)

    symbolic_modulus = _binding(
        _decl("n", "Nat") + _decl("m", "Nat"),
        _eq(nat_mod(n, m), _nat(0)),
    )
    with pytest.raises(MathXMLValidationError, match="positive Nat literal modulus"):
        validate_typed_number_theory_openmath_xml(symbolic_modulus)

    mixed_carrier = _binding(
        _decl("n", "Nat") + _decl("x", "Int"),
        _app(_typed("numbertheory1", "divides_int"), n, '<OMV name="x"/>'),
    )
    with pytest.raises(MathXMLValidationError, match="must have sort `Int`"):
        validate_typed_number_theory_openmath_xml(mixed_carrier)


def test_number_theory_rejects_negative_nat_untyped_literals_and_cdbase_inheritance() -> None:
    bad_nat = _binding(
        _decl("n", "Nat"),
        _eq(_app(_typed("numbertheory1", "nat_literal"), "<OMI>-1</OMI>"), _nat(0)),
    )
    with pytest.raises(MathXMLValidationError, match="Nat literals must be nonnegative"):
        validate_typed_number_theory_openmath_xml(bad_nat)

    bare_integer = _binding(_decl("n", "Nat"), _eq("<OMI>1</OMI>", _nat(1)))
    with pytest.raises(MathXMLValidationError, match="untyped integer literal"):
        validate_typed_number_theory_openmath_xml(bare_integer)

    inherited_cdbase = _binding(_decl("n", "Nat"), _eq('<OMV name="n"/>', _nat(1))).replace(
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0">',
        f'<OMOBJ xmlns="{OPENMATH}" cdbase="{TYPED}" version="2.0">',
    )
    with pytest.raises(MathXMLValidationError, match="does not permit attribute `cdbase`"):
        validate_typed_number_theory_openmath_xml(inherited_cdbase)


def test_number_theory_does_not_widen_generic_or_base_typed_math() -> None:
    cards = _manifest()["cards"]
    assert isinstance(cards, list) and cards
    raw = cards[-1]["openmath_xml"]
    assert isinstance(raw, str)
    with pytest.raises(MathXMLValidationError):
        canonicalize_retrieval_openmath_xml(raw)
    with pytest.raises(MathXMLValidationError):
        validate_typed_math_openmath_xml(raw)


def test_number_theory_manifest_rejects_resealed_staleness_and_bad_c14n() -> None:
    payload = copy.deepcopy(_manifest())
    profile = payload["profile"]
    assert isinstance(profile, dict)
    profile["registry_sha256"] = "sha256:" + "0" * 64
    _reseal(payload)
    with pytest.raises(TypedNumberTheoryManifestError, match="stale or mismatched"):
        validate_typed_number_theory_manifest(payload, repository_root=ROOT)

    xml_tampered = copy.deepcopy(_manifest())
    cards = xml_tampered["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["canonical_openmath_xml"] = "<OMOBJ/>"
    _reseal(xml_tampered)
    with pytest.raises(TypedNumberTheoryManifestError, match="canonical OpenMath"):
        validate_typed_number_theory_manifest(xml_tampered, repository_root=ROOT)
