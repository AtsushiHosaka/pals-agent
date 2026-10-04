"""Actual expansion artifacts and mutation rejection at the authoring boundary."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pals_agent.typed_catalog_expansion import AUTHORING_STATUS
from pals_agent.typed_local_catalog import (
    TypedLocalCatalogError,
    load_typed_local_catalog_manifest,
    validate_typed_local_catalog_manifest,
)

ROOT = Path(__file__).resolve().parents[3]
BATCHES = [
    ROOT / f"docs/{subject}-reuse-batch-20260930.json"
    for subject in ("calculus", "linear-algebra", "commalg")
]


@pytest.mark.parametrize("path", BATCHES, ids=lambda p: p.stem)
def test_real_batch_is_loadable_and_remains_authoring_only(path: Path) -> None:
    payload = json.loads(path.read_text())
    manifest = load_typed_local_catalog_manifest(path, repository_root=ROOT)
    assert manifest.authoring_status == AUTHORING_STATUS
    assert len(manifest.cards) == len(payload["cards"])
    assert len({c.canonical_openmath_xml for c in manifest.cards}) == len(manifest.cards)
    assert manifest.profile.profile_id == payload["profile_id"]
    assert all(c.manifest_digest == manifest.manifest_digest for c in manifest.cards)


@pytest.fixture
def batch() -> dict:
    return json.loads(BATCHES[0].read_text())


@pytest.mark.parametrize("field", ["validator_sha256", "registry_sha256", "witness_sha256"])
def test_tampered_evidence_is_rejected(batch: dict, field: str) -> None:
    batch["evidence"][field] = "sha256:" + "0" * 64
    with pytest.raises(TypedLocalCatalogError):
        validate_typed_local_catalog_manifest(batch, repository_root=ROOT)


@pytest.mark.parametrize("field", ["toolchain", "mathlib_revision"])
def test_wrong_lean_environment_is_rejected(batch: dict, field: str) -> None:
    batch["evidence"][field] = "different-environment"
    with pytest.raises(TypedLocalCatalogError, match="environment is stale"):
        validate_typed_local_catalog_manifest(batch, repository_root=ROOT)


def test_repeated_canonical_proposition_with_new_id_is_rejected(batch: dict) -> None:
    row = copy.deepcopy(batch["cards"][0])
    row["id"] += "_duplicate"
    batch["cards"].append(row)
    with pytest.raises(TypedLocalCatalogError, match="repeats"):
        validate_typed_local_catalog_manifest(batch, repository_root=ROOT)


def test_repeated_id_with_another_statement_is_rejected(batch: dict) -> None:
    batch["cards"][1]["id"] = batch["cards"][0]["id"]
    with pytest.raises(TypedLocalCatalogError, match="repeats"):
        validate_typed_local_catalog_manifest(batch, repository_root=ROOT)


@pytest.mark.parametrize("proof", ["by sorry", "by admit", "by exact True.intro"])
def test_unchecked_or_unbound_proof_is_rejected(batch: dict, proof: str) -> None:
    batch["cards"][0]["lean_witness"] = proof
    with pytest.raises(TypedLocalCatalogError):
        validate_typed_local_catalog_manifest(batch, repository_root=ROOT)


def test_unknown_profile_is_rejected(batch: dict) -> None:
    batch["profile_id"] = "unknown-v1"
    with pytest.raises(TypedLocalCatalogError, match="Unsupported"):
        validate_typed_local_catalog_manifest(batch, repository_root=ROOT)


def test_cross_profile_xml_is_rejected(batch: dict) -> None:
    other = json.loads(BATCHES[1].read_text())
    batch["cards"][0]["openmath_xml"] = other["cards"][0]["openmath_xml"]
    with pytest.raises(ValueError):
        validate_typed_local_catalog_manifest(batch, repository_root=ROOT)


def test_injected_admission_status_is_rejected(batch: dict) -> None:
    batch["status"] = "admitted"
    with pytest.raises(TypedLocalCatalogError, match="unexpected fields"):
        validate_typed_local_catalog_manifest(batch, repository_root=ROOT)


def test_witness_path_escape_is_rejected(batch: dict) -> None:
    batch["evidence"]["witness_path"] = "docs/../../outside.lean"
    with pytest.raises(TypedLocalCatalogError, match="escapes"):
        validate_typed_local_catalog_manifest(batch, repository_root=ROOT)


def test_new_cards_do_not_collide_with_existing_typed_inventory() -> None:
    sources = json.loads(
        (ROOT / "specs/draft-catalog-expansion/inventory-sources.v1.json").read_text()
    )["sources"]
    previous_ids = set()
    previous_xml = set()
    for source in sources:
        if source["kind"] != "typed_authoring" or "reuse-20260930" in source["id"]:
            continue
        manifest = load_typed_local_catalog_manifest(ROOT / source["path"], repository_root=ROOT)
        previous_ids.update(card.card_id for card in manifest.cards)
        previous_xml.update(card.canonical_openmath_xml for card in manifest.cards)
    for path in BATCHES:
        manifest = load_typed_local_catalog_manifest(path, repository_root=ROOT)
        for card in manifest.cards:
            assert card.card_id not in previous_ids, card.card_id
            assert card.canonical_openmath_xml not in previous_xml, card.card_id
            previous_ids.add(card.card_id)
            previous_xml.add(card.canonical_openmath_xml)
