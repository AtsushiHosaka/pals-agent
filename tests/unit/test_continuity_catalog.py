"""PFI-AG-008 continuity-v2 catalog admission tests."""

from __future__ import annotations

import json
from pathlib import Path

import rfc8785

from pals_agent import proof_flow_seed

CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "specs"
    / "continuity-draft-seed-pilot"
    / "continuity-v1-catalog.json"
)


def test_pfi_ag_008_loads_the_profile_complete_continuity_catalog() -> None:
    catalog = proof_flow_seed.load_continuity_catalog(CATALOG_PATH)

    assert catalog.schema_version == "pals.continuity-draft-catalog.v2"
    assert len(catalog.cards) == 110
    assert len(catalog.required_signatures) == 41
    assert len({card.draft_id for card in catalog.cards}) == len(catalog.cards)


def test_pfi_ag_008_rejects_a_profile_signature_omission(tmp_path: Path) -> None:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    required = payload["coverage_profile"]["required_signatures"]
    c0_signature = next(
        card["coverage"]
        for card in payload["cards"]
        if card["draft_id"] == "cv1_add_continuity_at"
    )
    required.remove(c0_signature)
    path = tmp_path / "catalog.json"
    path.write_bytes(rfc8785.dumps(payload))

    try:
        proof_flow_seed.load_continuity_catalog(path)
    except proof_flow_seed.ContinuityCatalogError as error:
        assert error.code == "coverage_profile_missing_c0"
    else:
        raise AssertionError("a C0 signature omission must be rejected before seed construction")


def test_pfi_ag_008_rejects_a_missing_c0_signature_even_when_cards_match(
    tmp_path: Path,
) -> None:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    missing = next(
        card["coverage"]
        for card in payload["cards"]
        if card["draft_id"] == "cv1_add_continuity_at"
    )
    payload["coverage_profile"]["required_signatures"].remove(missing)
    payload["cards"] = [card for card in payload["cards"] if card["coverage"] != missing]
    path = tmp_path / "catalog.json"
    path.write_bytes(rfc8785.dumps(payload))

    try:
        proof_flow_seed.load_continuity_catalog(path)
    except proof_flow_seed.ContinuityCatalogError as error:
        assert error.code == "coverage_profile_missing_c0"
    else:
        raise AssertionError("a profile that omits C0 must be rejected before seed construction")
