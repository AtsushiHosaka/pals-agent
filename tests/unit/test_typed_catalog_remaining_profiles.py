"""Existing sealed authoring evidence remains unadmitted through all loader adapters."""

import hashlib
import json
from pathlib import Path

import pytest
import rfc8785

from pals_agent.private_typed_candidates import profile_contract
from pals_agent.typed_local_catalog import (
    TypedLocalCatalogError,
    load_typed_local_catalog_manifest,
    validate_typed_local_catalog_manifest,
)
from pals_agent.typed_release import prepare_layout, profile_bindings

ROOT = Path(__file__).resolve().parents[3]
PROFILES = [("integral", 20), ("decomposition", 22), ("chain-dimension", 17)]


def manifest_path(name):
    return ROOT / f"docs/typed-commutative-algebra-{name}-v1-sealed-manifest.proposal.json"


@pytest.mark.parametrize("name,count", PROFILES)
def test_all_sealed_cards_load_without_promoting_authoring_status(name, count):
    path = manifest_path(name)
    manifest = load_typed_local_catalog_manifest(path, repository_root=ROOT)
    original = json.loads(path.read_bytes())
    assert len(manifest.cards) == count
    assert manifest.authoring_status == original["status"]
    assert "not_admitted" in manifest.authoring_status
    spec, binding = profile_contract(manifest.profile.profile_id)
    assert binding == profile_bindings(ROOT)[manifest.profile.profile_id]
    assert all(spec.validate_canonical(card.canonical_openmath_xml) for card in manifest.cards)
    # Deterministic vectors prove transport preparation only, never admission or quality.
    layout = json.loads(
        prepare_layout(
            path,
            repository_root=ROOT,
            author_id="test-author",
            embeddings={card.card_id: [1.0] * 384 for card in manifest.cards},
            coverage_families=["test-only"],
        )
    )
    assert len(layout["rows"]) == count
    assert layout["binding"] == binding
    assert not {"approved", "admitted", "review"} & layout.keys()


@pytest.mark.parametrize("name,count", PROFILES)
@pytest.mark.parametrize("mutation", ["status", "validator", "xml", "witness", "extra"])
def test_recomputed_digest_cannot_bypass_sealed_profile_validation(name, count, mutation):
    payload = json.loads(manifest_path(name).read_bytes())
    if mutation == "status":
        payload["status"] = "admitted"
    elif mutation == "validator":
        payload["profile"]["validator_sha256"] = "sha256:" + "0" * 64
    elif mutation == "xml":
        payload["cards"][0]["canonical_openmath_xml"] = "<OMOBJ/>"
    elif mutation == "witness":
        payload["cards"][0]["lean_witness"] = "by sorry"
    else:
        payload["cards"][0]["approved"] = True
    unsigned = {k: v for k, v in payload.items() if k != "manifest_payload_sha256"}
    payload["manifest_payload_sha256"] = (
        "sha256:" + hashlib.sha256(rfc8785.dumps(unsigned)).hexdigest()
    )
    with pytest.raises(TypedLocalCatalogError):
        validate_typed_local_catalog_manifest(payload, repository_root=ROOT)


def test_api_runtime_bindings_cover_exact_local_validator_bytes():
    trusted = json.loads((ROOT / "pals-api/app/domain/typed_catalog_bindings.json").read_bytes())
    assert trusted == profile_bindings(ROOT)
    assert len(trusted) == 16
