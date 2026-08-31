from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError, canonicalize_retrieval_openmath_xml
from pals_agent.typed_commutative_algebra_chain_dimension import (
    TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_OPENMATH_CDBASE,
    TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_PROFILE,
    canonicalize_typed_commutative_algebra_chain_dimension_openmath_xml,
    validate_canonical_typed_commutative_algebra_chain_dimension_openmath_xml,
    validate_typed_commutative_algebra_chain_dimension_openmath_xml,
)
from pals_agent.typed_commutative_algebra_chain_dimension_manifest import (
    TypedCommutativeAlgebraChainDimensionManifestError,
    load_typed_commutative_algebra_chain_dimension_manifest,
    validate_typed_commutative_algebra_chain_dimension_manifest,
)
from pals_agent.typed_math import validate_typed_math_openmath_xml

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "docs/typed-commutative-algebra-chain-dimension-v1-sealed-manifest.proposal.json"
WITNESS = ROOT / "docs/typed-commutative-algebra-chain-dimension-v1-authoring-witnesses.lean"
GENERATOR = (
    ROOT
    / "pals-scripts/generate-typed-commutative-algebra-chain-dimension-v1-authoring-manifest.py"
)
OPENMATH = "http://www.openmath.org/OpenMath"
STANDARD = "http://www.openmath.org/cd"
TYPED = TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_OPENMATH_CDBASE


def _manifest() -> dict[str, object]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _typed(name: str) -> str:
    return f'<OMS cdbase="{TYPED}" cd="chain1" name="{name}"/>'


def _type() -> str:
    return f'<OMS cdbase="{TYPED}" cd="typed1" name="type"/>'


def _forall() -> str:
    return f'<OMS cdbase="{TYPED}" cd="typed1" name="forall"/>'


def _app(operator: str, *arguments: str) -> str:
    return f"<OMA>{operator}{''.join(arguments)}</OMA>"


def _decl_ring(name: str) -> str:
    return f'<OMATTR><OMATP>{_type()}{_typed("CommRing")}</OMATP><OMV name="{name}"/></OMATTR>'


def _decl_ideal(name: str, ring: str) -> str:
    sort = _app(_typed("Ideal"), f'<OMV name="{ring}"/>')
    return f'<OMATTR><OMATP>{_type()}{sort}</OMATP><OMV name="{name}"/></OMATTR>'


def _binding(declarations: str, body: str) -> str:
    return (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>{_forall()}'
        f"<OMBVAR>{declarations}</OMBVAR>{body}</OMBIND></OMOBJ>"
    )


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


def test_chain_dimension_manifest_is_current_and_all_cards_are_bound_to_lean() -> None:
    payload = load_typed_commutative_algebra_chain_dimension_manifest(
        MANIFEST, repository_root=ROOT
    )
    assert payload["admitted_card_count"] == 17
    assert payload["excluded_card_count"] == 5
    cards = payload["cards"]
    assert isinstance(cards, list) and len(cards) == 17
    witness = WITNESS.read_text(encoding="utf-8")
    for card in cards:
        assert isinstance(card, dict)
        raw = card["openmath_xml"]
        assert isinstance(raw, str)
        canonical = canonicalize_typed_commutative_algebra_chain_dimension_openmath_xml(raw)
        assert (
            validate_canonical_typed_commutative_algebra_chain_dimension_openmath_xml(canonical)
            == canonical
        )
        assert card["canonical_openmath_xml"] == canonical
        assert 4 <= len(card["sketch_steps"]) <= 8
        assert (
            f"-- manifest card: {card['id']}\n{card['lean_target']} := {card['lean_witness']}"
            in witness
        )


def test_chain_dimension_manifest_is_deterministic_generator_output(tmp_path: Path) -> None:
    output = tmp_path / "chain-dimension.json"
    completed = subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(output), "--verify-lean"],
        cwd=ROOT / "pals-agent",
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert output.read_bytes() == MANIFEST.read_bytes()


def test_chain_dimension_rejects_cross_carrier_ideal_and_unbounded_dimension_symbol() -> None:
    declarations = _decl_ring("R") + _decl_ring("S") + _decl_ideal("I", "R") + _decl_ideal("J", "S")
    mixed = _binding(
        declarations,
        _app(_typed("IdealFG"), '<OMV name="R"/>', '<OMV name="J"/>'),
    )
    with pytest.raises(MathXMLValidationError, match="Ideal\\(R\\)"):
        validate_typed_commutative_algebra_chain_dimension_openmath_xml(mixed)

    unknown_dimension = _binding(_decl_ring("R"), _app(_typed("KrullDimension"), '<OMV name="R"/>'))
    with pytest.raises(MathXMLValidationError, match="outside typed chain/dimension"):
        validate_typed_commutative_algebra_chain_dimension_openmath_xml(unknown_dimension)


def test_chain_dimension_rejects_free_variables_and_typed_cdbase_inheritance() -> None:
    free = _binding(_decl_ring("R"), _app(_typed("NoetherianRing"), '<OMV name="S"/>'))
    with pytest.raises(MathXMLValidationError, match="free or undeclared"):
        validate_typed_commutative_algebra_chain_dimension_openmath_xml(free)

    raw = _manifest()["cards"]
    assert isinstance(raw, list) and isinstance(raw[0], dict)
    inherited = raw[0]["openmath_xml"]
    assert isinstance(inherited, str)
    inherited = inherited.replace(
        f'<OMS cdbase="{TYPED}" cd="chain1" name="NoetherianRing"/>',
        '<OMS cd="chain1" name="NoetherianRing"/>',
    ).replace(
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0">',
        f'<OMOBJ xmlns="{OPENMATH}" cdbase="{TYPED}" version="2.0">',
    )
    with pytest.raises(MathXMLValidationError):
        validate_typed_commutative_algebra_chain_dimension_openmath_xml(inherited)


def test_chain_dimension_isolated_from_generic_and_base_typed_math() -> None:
    cards = _manifest()["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    raw = cards[0]["openmath_xml"]
    assert isinstance(raw, str)
    with pytest.raises(MathXMLValidationError):
        canonicalize_retrieval_openmath_xml(raw)
    with pytest.raises(MathXMLValidationError):
        validate_typed_math_openmath_xml(raw)


def test_chain_dimension_manifest_rejects_resealed_staleness_and_bad_c14n() -> None:
    payload = copy.deepcopy(_manifest())
    profile = payload["profile"]
    assert isinstance(profile, dict)
    profile["registry_sha256"] = "sha256:" + "0" * 64
    _reseal(payload)
    with pytest.raises(
        TypedCommutativeAlgebraChainDimensionManifestError, match="registry artifact"
    ):
        validate_typed_commutative_algebra_chain_dimension_manifest(payload, repository_root=ROOT)

    tampered = copy.deepcopy(_manifest())
    cards = tampered["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["canonical_openmath_xml"] = "<OMOBJ/>"
    _reseal(tampered)
    with pytest.raises(TypedCommutativeAlgebraChainDimensionManifestError, match="canonical"):
        validate_typed_commutative_algebra_chain_dimension_manifest(tampered, repository_root=ROOT)


def test_chain_dimension_profile_identifier_is_fixed() -> None:
    assert TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_PROFILE == (
        "typed-commutative-algebra-chain-dimension-v1"
    )
    assert STANDARD == "http://www.openmath.org/cd"
