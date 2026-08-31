from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError, canonicalize_retrieval_openmath_xml
from pals_agent.typed_commutative_algebra import (
    TYPED_COMMUTATIVE_ALGEBRA_OPENMATH_CDBASE,
    TYPED_COMMUTATIVE_ALGEBRA_PROFILE,
    canonicalize_typed_commutative_algebra_openmath_xml,
    validate_canonical_typed_commutative_algebra_openmath_xml,
    validate_typed_commutative_algebra_openmath_xml,
)
from pals_agent.typed_commutative_algebra_manifest import (
    TypedCommutativeAlgebraManifestError,
    load_typed_commutative_algebra_manifest,
    validate_typed_commutative_algebra_manifest,
)
from pals_agent.typed_math import validate_typed_math_openmath_xml

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "docs/typed-commutative-algebra-v1-authoring-manifest.proposal.json"
WITNESS = ROOT / "docs/typed-commutative-algebra-v1-authoring-witnesses.lean"
REGISTRY = (
    ROOT / "pals-agent/pals_agent/content_dictionaries/typed-commutative-algebra-v1-registry.json"
)
GENERATOR = ROOT / "pals-scripts/generate-typed-commutative-algebra-v1-authoring-manifest.py"
OPENMATH = "http://www.openmath.org/OpenMath"
STANDARD = "http://www.openmath.org/cd"
TYPED = TYPED_COMMUTATIVE_ALGEBRA_OPENMATH_CDBASE


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


def _decl(name: str, sort: str) -> str:
    sorts = {
        "CommRing": _typed("commalg1", "CommRing"),
        "Ideal R": _app(_typed("commalg1", "Ideal"), '<OMV name="R"/>'),
        "Ideal S": _app(_typed("commalg1", "Ideal"), '<OMV name="S"/>'),
    }
    return (
        f"<OMATTR><OMATP>{_typed('typed1', 'type')}{sorts[sort]}"
        f'</OMATP><OMV name="{name}"/></OMATTR>'
    )


def _binding(declarations: str, body: str) -> str:
    return (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>{_typed("typed1", "forall")}'
        f"<OMBVAR>{declarations}</OMBVAR>{body}</OMBIND></OMOBJ>"
    )


def _ideal(name: str, *arguments: str) -> str:
    return _app(_typed("commalg1", name), *arguments)


def _le(carrier: str, left: str, right: str) -> str:
    return _ideal("ideal_le", f'<OMV name="{carrier}"/>', left, right)


def _reseal(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_payload_sha256")
    payload["manifest_payload_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
    )


def test_commutative_algebra_manifest_is_current_and_all_cards_use_actual_validator() -> None:
    payload = load_typed_commutative_algebra_manifest(MANIFEST, repository_root=ROOT)
    assert payload["schema_version"] == "pals.typed-commutative-algebra-v1-sealed-manifest.v1"
    assert payload["status"] == "sealed_local_authoring_revision_not_admitted"
    assert payload["admitted_card_count"] == 13
    assert payload["excluded_card_count"] == 4
    profile = payload["profile"]
    assert isinstance(profile, dict)
    assert profile["id"] == TYPED_COMMUTATIVE_ALGEBRA_PROFILE
    assert (
        profile["registry_sha256"] == "sha256:" + hashlib.sha256(REGISTRY.read_bytes()).hexdigest()
    )
    cards = payload["cards"]
    assert isinstance(cards, list) and len(cards) == 13
    for card in cards:
        assert isinstance(card, dict)
        raw = card["openmath_xml"]
        assert isinstance(raw, str)
        canonical = canonicalize_typed_commutative_algebra_openmath_xml(raw)
        assert validate_canonical_typed_commutative_algebra_openmath_xml(canonical) == canonical
        assert card["canonical_openmath_xml"] == canonical
        assert 4 <= len(card["sketch_steps"]) <= 8
        marker = f"-- manifest card: {card['id']}\n{card['lean_target']} := {card['lean_witness']}"
        assert marker in WITNESS.read_text(encoding="utf-8")


def test_commutative_algebra_manifest_is_deterministic_generator_output(tmp_path: Path) -> None:
    output = tmp_path / "typed-commutative-algebra.json"
    completed = subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(output), "--verify-lean"],
        cwd=ROOT / "pals-agent",
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert output.read_bytes() == MANIFEST.read_bytes()


def test_commutative_algebra_rejects_mixed_ideal_carriers_and_deferred_symbols() -> None:
    declarations = _decl("R", "CommRing") + _decl("S", "CommRing")
    declarations += _decl("I", "Ideal R") + _decl("J", "Ideal S")
    mixed = _binding(declarations, _le("R", '<OMV name="I"/>', '<OMV name="J"/>'))
    with pytest.raises(MathXMLValidationError, match="Ideal\\(R\\)"):
        validate_typed_commutative_algebra_openmath_xml(mixed)

    unknown_quotient = _binding(
        _decl("R", "CommRing") + _decl("I", "Ideal R"),
        _ideal("quotient_map", '<OMV name="R"/>', '<OMV name="I"/>'),
    )
    with pytest.raises(MathXMLValidationError, match="outside typed-commutative-algebra-v1"):
        validate_typed_commutative_algebra_openmath_xml(unknown_quotient)


def test_commutative_algebra_rejects_untyped_literals_and_cdbase_inheritance() -> None:
    bare_literal = _binding(_decl("R", "CommRing"), "<OMI>0</OMI>")
    with pytest.raises(MathXMLValidationError, match="outside typed-commutative-algebra-v1"):
        validate_typed_commutative_algebra_openmath_xml(bare_literal)

    inherited = _binding(
        _decl("R", "CommRing") + _decl("I", "Ideal R"),
        _le("R", '<OMV name="I"/>', '<OMV name="I"/>'),
    ).replace(
        f'<OMS cdbase="{STANDARD}" cd="relation1" name="eq"/>',
        '<OMS cd="relation1" name="eq"/>',
    )
    assert "relation1" not in inherited
    inherited = inherited.replace(
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0">',
        f'<OMOBJ xmlns="{OPENMATH}" cdbase="{TYPED}" version="2.0">',
    )
    with pytest.raises(MathXMLValidationError, match="does not permit attribute `cdbase`"):
        validate_typed_commutative_algebra_openmath_xml(inherited)


def test_commutative_algebra_does_not_widen_generic_or_base_typed_math() -> None:
    cards = _manifest()["cards"]
    assert isinstance(cards, list) and cards
    raw = cards[-1]["openmath_xml"]
    assert isinstance(raw, str)
    with pytest.raises(MathXMLValidationError):
        canonicalize_retrieval_openmath_xml(raw)
    with pytest.raises(MathXMLValidationError):
        validate_typed_math_openmath_xml(raw)


def test_commutative_algebra_manifest_rejects_resealed_staleness_and_bad_c14n() -> None:
    payload = copy.deepcopy(_manifest())
    profile = payload["profile"]
    assert isinstance(profile, dict)
    profile["registry_sha256"] = "sha256:" + "0" * 64
    _reseal(payload)
    with pytest.raises(TypedCommutativeAlgebraManifestError, match="stale or mismatched"):
        validate_typed_commutative_algebra_manifest(payload, repository_root=ROOT)

    xml_tampered = copy.deepcopy(_manifest())
    cards = xml_tampered["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["canonical_openmath_xml"] = "<OMOBJ/>"
    _reseal(xml_tampered)
    with pytest.raises(TypedCommutativeAlgebraManifestError, match="canonical OpenMath"):
        validate_typed_commutative_algebra_manifest(xml_tampered, repository_root=ROOT)
