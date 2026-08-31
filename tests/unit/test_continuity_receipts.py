"""Receipt-set binding tests for local continuity-v1 Lean verification."""

from __future__ import annotations

import json
from pathlib import Path

from pals_agent.continuity_receipts import proof_body_for_card, receipt_bytes
from pals_agent.proof_flow_seed import load_continuity_catalog


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "testdata" / "continuity-draft-seed-pilot" / "continuity-v1-catalog.json"
RECEIPTS = ROOT / "testdata" / "continuity-draft-seed-pilot" / "continuity-v1-local-lean-receipts.json"


def test_local_receipts_bind_every_catalog_card_without_retaining_proof_source() -> None:
    catalog = load_continuity_catalog(CATALOG)
    payload = json.loads(RECEIPTS.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "pals.continuity-lean-receipts.local.v1"
    assert payload["verification_scope"] == "local_workspace_only"
    assert [receipt["draft_id"] for receipt in payload["receipts"]] == [
        card.draft_id for card in catalog.cards
    ]
    assert all(receipt["status"] == "verified" for receipt in payload["receipts"])
    assert all("proof_source" not in receipt for receipt in payload["receipts"])
    assert receipt_bytes(payload) == RECEIPTS.read_bytes()
    assert all(proof_body_for_card(card.draft_id).startswith("by\n") for card in catalog.cards)
