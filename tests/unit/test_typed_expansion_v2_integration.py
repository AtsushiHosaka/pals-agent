"""Real authored v2 batches integrate without advertising an unshipped runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pals_agent import typed_expansion_profiles
from pals_agent.profile_routing import SUPPORTED_TYPED_PROFILES
from pals_agent.typed_catalog_expansion import AUTHORING_STATUS
from pals_agent.typed_expansion_profiles import expansion_profile_specs
from pals_agent.typed_local_catalog import load_typed_local_catalog_manifest

ROOT = Path(__file__).resolve().parents[3]
BATCHES = {
    "typed-calculus-v2": "calculus-v2-batch.json",
    "typed-linear-algebra-v2": "linear-algebra-v2-batch.json",
    "typed-commalg-modules-v2": "commalg-modules-v2-batch.json",
}


@pytest.mark.parametrize("profile,filename", BATCHES.items())
def test_actual_v2_cards_use_pinned_profile_and_remain_authoring(profile, filename):
    manifest = load_typed_local_catalog_manifest(ROOT / "docs" / filename, repository_root=ROOT)
    raw = json.loads((ROOT / "docs" / filename).read_text())
    assert manifest.profile.profile_id == profile
    assert manifest.authoring_status == AUTHORING_STATUS
    assert len(manifest.cards) == len(raw["cards"])
    assert manifest.profile.validator_module_sha256 == raw["evidence"]["validator_sha256"]
    assert manifest.profile.registry_sha256 == raw["evidence"]["registry_sha256"]
    assert profile not in SUPPORTED_TYPED_PROFILES


def test_separate_profiles_reject_each_others_actual_propositions():
    specs = expansion_profile_specs()
    for profile, filename in BATCHES.items():
        row = json.loads((ROOT / "docs" / filename).read_text())["cards"][0]
        for other, spec in specs.items():
            if other != profile:
                with pytest.raises(ValueError):
                    spec.canonicalize(row["openmath_xml"])


def test_loading_one_authoring_profile_does_not_import_other_profile_modules(monkeypatch):
    imported: list[str] = []
    original = typed_expansion_profiles.import_module

    def capture(name: str):
        imported.append(name)
        return original(name)

    monkeypatch.setattr(typed_expansion_profiles, "import_module", capture)
    spec = typed_expansion_profiles.expansion_profile_spec("typed-calculus-v2")
    assert spec is not None
    assert imported == ["pals_agent.typed_calculus_v2"]


def test_inventory_contains_each_loadable_authoring_batch():
    sources = json.loads(
        (ROOT / "specs/draft-catalog-expansion/inventory-sources.v1.json").read_text()
    )["sources"]
    for profile, filename in BATCHES.items():
        entry = next(s for s in sources if s["path"] == "docs/" + filename)
        assert entry["profile_id"] == profile
        assert entry["loader_supported"] is True
        assert entry["status_ceiling"] == "profile_valid"


def test_v2_cards_have_no_id_or_canonical_collision_with_existing_catalog():
    sources = json.loads(
        (ROOT / "specs/draft-catalog-expansion/inventory-sources.v1.json").read_text()
    )["sources"]
    ids: set[str] = set()
    xmls: set[str] = set()
    for source in sources:
        if source["kind"] != "typed_authoring" or source["profile_id"] in BATCHES:
            continue
        manifest = load_typed_local_catalog_manifest(ROOT / source["path"], repository_root=ROOT)
        ids.update(card.card_id for card in manifest.cards)
        xmls.update(card.canonical_openmath_xml for card in manifest.cards)
    for filename in BATCHES.values():
        manifest = load_typed_local_catalog_manifest(ROOT / "docs" / filename, repository_root=ROOT)
        for card in manifest.cards:
            assert card.card_id not in ids, card.card_id
            assert card.canonical_openmath_xml not in xmls, card.card_id
            ids.add(card.card_id)
            xmls.add(card.canonical_openmath_xml)
