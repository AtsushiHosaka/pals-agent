"""Regression tests for the authored 110-card continuity collection."""

from __future__ import annotations

import json
from pathlib import Path

from pals_agent.continuity_collection import (
    build_catalog,
    canonical_catalog_bytes,
    catalog_sha256,
    concrete_cards,
)
from pals_agent.proof_flow_seed import load_continuity_catalog


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "testdata" / "continuity-draft-seed-pilot" / "continuity-v1-base-37.json"
CATALOG = ROOT / "testdata" / "continuity-draft-seed-pilot" / "continuity-v1-catalog.json"


def test_collection_is_deterministically_derived_from_the_retained_base() -> None:
    payload, proof_bodies = build_catalog(json.loads(BASE.read_text(encoding="utf-8")))

    assert canonical_catalog_bytes(payload) == CATALOG.read_bytes()
    assert catalog_sha256(payload) == "29f8a35e628d5aef2b40a1bb71582e87b3e5dc001024f8f9c39e0a3906ac49a7"
    assert len(payload["cards"]) == 110
    assert len(proof_bodies) == 73


def test_concrete_collection_has_the_declared_topic_split_and_is_admitted() -> None:
    cards = concrete_cards()
    identifiers = [card["draft_id"] for card in cards]

    assert len(cards) == 73
    assert sum(identifier.startswith("cv1_global_") for identifier in identifiers) == 25
    assert sum(identifier.startswith("cv1_at_") for identifier in identifiers) == 25
    assert sum(identifier.startswith("cv1_limit_constant_") for identifier in identifiers) == 12
    assert sum(identifier.startswith("cv1_sequence_constant_") for identifier in identifiers) == 11
    assert len({card["openmath_xml"] for card in cards}) == 73
    assert len({card["novelty_key"] for card in cards}) == 73
    assert len(load_continuity_catalog(CATALOG).cards) == 110
