"""Tests for the isolated CA-4 primary-decomposition authoring profile."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
import rfc8785

from pals_agent.openmath import MathXMLValidationError
from pals_agent.typed_commutative_algebra_decomposition import (
    TYPED_COMMUTATIVE_ALGEBRA_DECOMPOSITION_OPENMATH_CDBASE,
    TYPED_COMMUTATIVE_ALGEBRA_DECOMPOSITION_PROFILE,
    canonicalize_typed_commutative_algebra_decomposition_openmath_xml,
    validate_canonical_typed_commutative_algebra_decomposition_openmath_xml,
)
from pals_agent.typed_commutative_algebra_decomposition_manifest import (
    TypedCommutativeAlgebraDecompositionManifestError,
    load_typed_commutative_algebra_decomposition_manifest,
    validate_typed_commutative_algebra_decomposition_manifest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = (
    REPOSITORY_ROOT
    / "docs/typed-commutative-algebra-decomposition-v1-sealed-manifest.proposal.json"
)
GENERATOR = (
    REPOSITORY_ROOT
    / "pals-scripts/generate-typed-commutative-algebra-decomposition-v1-authoring-manifest.py"
)
TYPED = TYPED_COMMUTATIVE_ALGEBRA_DECOMPOSITION_OPENMATH_CDBASE


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _reseal(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_payload_sha256")
    payload["manifest_payload_sha256"] = _sha256(rfc8785.dumps(cast(Any, unsigned)))


def _manifest_payload() -> dict[str, object]:
    return cast(dict[str, object], json.loads(MANIFEST.read_text(encoding="utf-8")))


def _decl(name: str, sort: str) -> str:
    return (
        "<OMATTR><OMATP>"
        f'<OMS cdbase="{TYPED}" cd="typed1" name="type"/>{sort}'
        f'</OMATP><OMV name="{name}"/></OMATTR>'
    )


def _sort(name: str, carrier: str | None = None) -> str:
    symbol = f'<OMS cdbase="{TYPED}" cd="decomposition1" name="{name}"/>'
    return symbol if carrier is None else f'<OMA>{symbol}<OMV name="{carrier}"/></OMA>'


def _carrier_mismatch_xml() -> str:
    decomp = f'<OMS cdbase="{TYPED}" cd="decomposition1" name="primary_decomposition2"/>'
    declarations = "".join(
        [
            _decl("R", _sort("CommRing")),
            _decl("S", _sort("CommRing")),
            _decl("I", _sort("Ideal", "R")),
            _decl("Q1", _sort("PrimaryIdeal", "S")),
            _decl("Q2", _sort("PrimaryIdeal", "R")),
        ]
    )
    return (
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0">'
        f'<OMBIND><OMS cdbase="{TYPED}" cd="typed1" name="forall"/>'
        f"<OMBVAR>{declarations}</OMBVAR>"
        f'<OMA>{decomp}<OMV name="R"/><OMV name="I"/><OMV name="Q1"/><OMV name="Q2"/></OMA>'
        "</OMBIND></OMOBJ>"
    )


def test_manifest_revalidates_all_twenty_two_cards_and_hard_deferrals() -> None:
    payload = load_typed_commutative_algebra_decomposition_manifest(
        MANIFEST, repository_root=REPOSITORY_ROOT
    )
    assert payload["admitted_card_count"] == 22
    assert payload["hard_rejects"] == [
        "associated_primes_requires_module_and_annihilator",
        "noetherian_primary_decomposition_existence",
        "arbitrary_finite_family_decomposition",
        "quotient_or_localized_primary_component",
    ]
    profile = cast(dict[str, object], payload["profile"])
    assert profile["id"] == TYPED_COMMUTATIVE_ALGEBRA_DECOMPOSITION_PROFILE
    assert profile["typed_cdbase"] == TYPED
    cards = cast(list[dict[str, object]], payload["cards"])
    assert len({card["id"] for card in cards}) == 22
    assert all(4 <= len(cast(list[str], card["sketch_steps"])) <= 8 for card in cards)
    assert all(
        canonicalize_typed_commutative_algebra_decomposition_openmath_xml(
            cast(str, card["openmath_xml"])
        )
        == card["canonical_openmath_xml"]
        for card in cards
    )


def test_profile_rejects_carrier_mismatch_untyped_component_and_associated_prime_token() -> None:
    with pytest.raises(MathXMLValidationError, match="PrimaryIdeal\\(R\\)"):
        canonicalize_typed_commutative_algebra_decomposition_openmath_xml(_carrier_mismatch_xml())

    source = cast(
        str, cast(list[dict[str, object]], _manifest_payload()["cards"])[13]["openmath_xml"]
    )
    untyped_component = source.replace('name="PrimaryIdeal"', 'name="Ideal"', 1)
    with pytest.raises(MathXMLValidationError, match="PrimaryIdeal\\(R\\)"):
        canonicalize_typed_commutative_algebra_decomposition_openmath_xml(untyped_component)

    associated_prime = source.replace('name="primary_decomposition2"', 'name="associated_prime"')
    with pytest.raises(MathXMLValidationError, match="outside typed primary-decomposition"):
        canonicalize_typed_commutative_algebra_decomposition_openmath_xml(associated_prime)

    noetherian_existence = source.replace(
        'name="primary_decomposition2"', 'name="noetherian_primary_decomposition_exists"'
    )
    with pytest.raises(MathXMLValidationError, match="outside typed primary-decomposition"):
        canonicalize_typed_commutative_algebra_decomposition_openmath_xml(noetherian_existence)

    canonical = canonicalize_typed_commutative_algebra_decomposition_openmath_xml(source)
    with pytest.raises(MathXMLValidationError, match="not canonical"):
        validate_canonical_typed_commutative_algebra_decomposition_openmath_xml(canonical + "\n")


def test_manifest_rejects_resealed_c14n_registry_and_lean_evidence_staleness() -> None:
    c14n_tampered = copy.deepcopy(_manifest_payload())
    cards = cast(list[dict[str, object]], c14n_tampered["cards"])
    cards[0]["canonical_openmath_xml"] = "<OMOBJ/>"
    cards[0]["canonical_openmath_xml_sha256"] = _sha256(b"<OMOBJ/>")
    _reseal(c14n_tampered)
    with pytest.raises(
        TypedCommutativeAlgebraDecompositionManifestError,
        match="canonical OpenMath does not match source XML",
    ):
        validate_typed_commutative_algebra_decomposition_manifest(
            c14n_tampered, repository_root=REPOSITORY_ROOT
        )

    registry_tampered = copy.deepcopy(_manifest_payload())
    profile = cast(dict[str, object], registry_tampered["profile"])
    profile["registry_sha256"] = "sha256:" + "0" * 64
    _reseal(registry_tampered)
    with pytest.raises(TypedCommutativeAlgebraDecompositionManifestError, match="digest"):
        validate_typed_commutative_algebra_decomposition_manifest(
            registry_tampered, repository_root=REPOSITORY_ROOT
        )

    witness_tampered = copy.deepcopy(_manifest_payload())
    cards = cast(list[dict[str, object]], witness_tampered["cards"])
    cards[0]["lean_witness"] = "by\n  exact False.elim (by contradiction)"
    cards[0]["lean_witness_sha256"] = _sha256(b"by\n  exact False.elim (by contradiction)")
    _reseal(witness_tampered)
    with pytest.raises(
        TypedCommutativeAlgebraDecompositionManifestError,
        match="Lean evidence is not bound to its card",
    ):
        validate_typed_commutative_algebra_decomposition_manifest(
            witness_tampered, repository_root=REPOSITORY_ROOT
        )


def test_generator_reseals_c14n_and_runs_pinned_lean_bundle(tmp_path: Path) -> None:
    output = tmp_path / "decomposition-manifest.json"
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(output), "--verify-lean"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    generated = load_typed_commutative_algebra_decomposition_manifest(
        output, repository_root=REPOSITORY_ROOT
    )
    checked_in = load_typed_commutative_algebra_decomposition_manifest(
        MANIFEST, repository_root=REPOSITORY_ROOT
    )
    assert generated["manifest_payload_sha256"] == checked_in["manifest_payload_sha256"]
