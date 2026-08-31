"""Tests for the isolated commutative-algebra localization authoring profile."""

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
from pals_agent.typed_commutative_algebra_localization import (
    TYPED_COMMUTATIVE_ALGEBRA_LOCALIZATION_OPENMATH_CDBASE,
    TYPED_COMMUTATIVE_ALGEBRA_LOCALIZATION_PROFILE,
    canonicalize_typed_commutative_algebra_localization_openmath_xml,
    validate_canonical_typed_commutative_algebra_localization_openmath_xml,
)
from pals_agent.typed_commutative_algebra_localization_manifest import (
    TypedCommutativeAlgebraLocalizationManifestError,
    load_typed_commutative_algebra_localization_manifest,
    validate_typed_commutative_algebra_localization_manifest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = (
    REPOSITORY_ROOT
    / "docs/typed-commutative-algebra-localization-v1-authoring-manifest.proposal.json"
)
GENERATOR = (
    REPOSITORY_ROOT
    / "pals-scripts/generate-typed-commutative-algebra-localization-v1-authoring-manifest.py"
)


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _reseal(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_payload_sha256")
    payload["manifest_payload_sha256"] = _sha256(rfc8785.dumps(cast(Any, unsigned)))


def _manifest_payload() -> dict[str, object]:
    return cast(dict[str, object], json.loads(MANIFEST.read_text(encoding="utf-8")))


def test_localization_manifest_revalidates_all_twenty_three_cards() -> None:
    payload = load_typed_commutative_algebra_localization_manifest(
        MANIFEST, repository_root=REPOSITORY_ROOT
    )
    assert payload["admitted_card_count"] == 23
    profile = cast(dict[str, object], payload["profile"])
    assert profile["id"] == TYPED_COMMUTATIVE_ALGEBRA_LOCALIZATION_PROFILE
    assert profile["typed_cdbase"] == TYPED_COMMUTATIVE_ALGEBRA_LOCALIZATION_OPENMATH_CDBASE
    cards = cast(list[dict[str, object]], payload["cards"])
    assert len({card["id"] for card in cards}) == 23
    assert all(4 <= len(cast(list[str], card["sketch_steps"])) <= 8 for card in cards)
    assert all(
        canonicalize_typed_commutative_algebra_localization_openmath_xml(
            cast(str, card["openmath_xml"])
        )
        == card["canonical_openmath_xml"]
        for card in cards
    )


def test_profile_rejects_carrier_mismatch_unknown_symbol_and_noncanonical_bytes() -> None:
    source = cast(
        str, cast(list[dict[str, object]], _manifest_payload()["cards"])[0]["openmath_xml"]
    )
    mismatch = source.replace(
        'name="Ideal"/><OMV name="R"/></OMA></OMATP><OMV name="J"/>',
        'name="Ideal"/><OMV name="L"/></OMA></OMATP><OMV name="J"/>',
        1,
    )
    with pytest.raises(MathXMLValidationError, match="Ideal\\(R\\)"):
        canonicalize_typed_commutative_algebra_localization_openmath_xml(mismatch)

    unknown = source.replace('name="extend"', 'name="quotient"', 1)
    with pytest.raises(MathXMLValidationError, match="outside typed localization"):
        canonicalize_typed_commutative_algebra_localization_openmath_xml(unknown)

    canonical = canonicalize_typed_commutative_algebra_localization_openmath_xml(source)
    with pytest.raises(MathXMLValidationError, match="not canonical"):
        validate_canonical_typed_commutative_algebra_localization_openmath_xml(canonical + "\n")


def test_manifest_rejects_resealed_c14n_registry_and_witness_staleness() -> None:
    canonical_tampered = copy.deepcopy(_manifest_payload())
    cards = cast(list[dict[str, object]], canonical_tampered["cards"])
    cards[0]["canonical_openmath_xml"] = "<OMOBJ/>"
    cards[0]["canonical_openmath_xml_sha256"] = _sha256(b"<OMOBJ/>")
    _reseal(canonical_tampered)
    with pytest.raises(
        TypedCommutativeAlgebraLocalizationManifestError,
        match="canonical OpenMath does not match source XML",
    ):
        validate_typed_commutative_algebra_localization_manifest(
            canonical_tampered, repository_root=REPOSITORY_ROOT
        )

    registry_tampered = copy.deepcopy(_manifest_payload())
    profile = cast(dict[str, object], registry_tampered["profile"])
    profile["registry_sha256"] = "sha256:" + "0" * 64
    _reseal(registry_tampered)
    with pytest.raises(TypedCommutativeAlgebraLocalizationManifestError, match="digest"):
        validate_typed_commutative_algebra_localization_manifest(
            registry_tampered, repository_root=REPOSITORY_ROOT
        )

    witness_tampered = copy.deepcopy(_manifest_payload())
    cards = cast(list[dict[str, object]], witness_tampered["cards"])
    cards[0]["lean_witness"] = "example : True := by trivial"
    cards[0]["lean_witness_sha256"] = _sha256(b"example : True := by trivial")
    _reseal(witness_tampered)
    with pytest.raises(TypedCommutativeAlgebraLocalizationManifestError, match="Lean evidence"):
        validate_typed_commutative_algebra_localization_manifest(
            witness_tampered, repository_root=REPOSITORY_ROOT
        )


def test_generator_reseals_c14n_and_runs_the_pinned_lean_witnesses(tmp_path: Path) -> None:
    output = tmp_path / "localization-manifest.json"
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(output), "--verify-lean"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    generated = load_typed_commutative_algebra_localization_manifest(
        output, repository_root=REPOSITORY_ROOT
    )
    checked_in = load_typed_commutative_algebra_localization_manifest(
        MANIFEST, repository_root=REPOSITORY_ROOT
    )
    assert generated["manifest_payload_sha256"] == checked_in["manifest_payload_sha256"]
