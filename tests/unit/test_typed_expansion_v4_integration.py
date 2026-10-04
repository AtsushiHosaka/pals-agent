"""Real v4 authoring manifests stay pinned and outside unshipped routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pals_agent.profile_routing import SUPPORTED_TYPED_PROFILES
from pals_agent.typed_catalog_expansion import AUTHORING_STATUS
from pals_agent.typed_expansion_profiles import expansion_profile_specs
from pals_agent.typed_local_catalog import load_typed_local_catalog_manifest

ROOT = Path(__file__).resolve().parents[3]
BATCHES = {
    "typed-calculus-v4": "calculus-v4-batch.json",
    "typed-linear-algebra-v4": "linear-algebra-v4-batch.json",
    "typed-commalg-v4": "commalg-v4-batch.json",
}


@pytest.mark.parametrize("profile,filename", BATCHES.items())
def test_v4_manifest_pins_its_profile_and_remains_local_authoring(profile, filename):
    path = ROOT / "docs" / filename
    raw = json.loads(path.read_text())
    manifest = load_typed_local_catalog_manifest(path, repository_root=ROOT)
    assert manifest.profile.profile_id == profile
    assert manifest.authoring_status == AUTHORING_STATUS
    assert len(manifest.cards) == len(raw["cards"])
    assert manifest.profile.validator_module_sha256 == raw["evidence"]["validator_sha256"]
    assert manifest.profile.registry_sha256 == raw["evidence"]["registry_sha256"]
    assert profile not in SUPPORTED_TYPED_PROFILES


def test_v4_profiles_reject_each_others_actual_proposition():
    specs = expansion_profile_specs()
    for profile, filename in BATCHES.items():
        xml = json.loads((ROOT / "docs" / filename).read_text())["cards"][0]["openmath_xml"]
        for other in BATCHES:
            if other != profile:
                with pytest.raises(ValueError):
                    specs[other].canonicalize(xml)


def test_v4_inventory_is_closed_and_loadable():
    sources = json.loads(
        (ROOT / "specs/draft-catalog-expansion/inventory-sources.v1.json").read_text()
    )["sources"]
    for profile, filename in BATCHES.items():
        entry = next(s for s in sources if s["path"] == "docs/" + filename)
        assert entry["profile_id"] == profile
        assert entry["loader_supported"] is True
        assert entry["status_ceiling"] == "profile_valid"


def test_v4_id_and_canonical_xml_differ_from_all_existing_typed_cards():
    sources = json.loads(
        (ROOT / "specs/draft-catalog-expansion/inventory-sources.v1.json").read_text()
    )["sources"]
    old_ids: set[str] = set()
    old_xmls: set[str] = set()
    for source in sources:
        if source["kind"] != "typed_authoring" or source["profile_id"] in BATCHES:
            continue
        manifest = load_typed_local_catalog_manifest(ROOT / source["path"], repository_root=ROOT)
        old_ids.update(card.card_id for card in manifest.cards)
        old_xmls.update(card.canonical_openmath_xml for card in manifest.cards)
    for filename in BATCHES.values():
        manifest = load_typed_local_catalog_manifest(ROOT / "docs" / filename, repository_root=ROOT)
        for card in manifest.cards:
            assert card.card_id not in old_ids, card.card_id
            assert card.canonical_openmath_xml not in old_xmls, card.card_id
            old_ids.add(card.card_id)
            old_xmls.add(card.canonical_openmath_xml)
