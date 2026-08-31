"""PFI-AG-008 formal-evidence gate for the 110-card continuity candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import rfc8785

from pals_agent.continuity_release_candidate import (
    ContinuityReleaseCandidateError,
    ContinuityReleaseCandidateProjector,
)
from pals_agent.proof_flow_seed import load_continuity_catalog

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "testdata" / "continuity-draft-seed-pilot" / "continuity-v1-catalog.json"
LOCAL_RECEIPTS = (
    ROOT / "testdata" / "continuity-draft-seed-pilot" / "continuity-v1-local-lean-receipts.json"
)


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _wrapper_source(card: dict[str, Any]) -> str:
    draft_id = card["draft_id"]
    return (
        f"import Pals.ContinuityV1.{draft_id}\n"
        f"example : {card['lean_target']} := Pals.ContinuityV1.{draft_id}\n"
    )


def _formal_evidence() -> tuple[tuple[bytes, ...], tuple[bytes, ...], tuple[bytes, ...]]:
    catalog = load_continuity_catalog(CATALOG)
    authorship: list[bytes] = []
    source_review: list[bytes] = []
    lean_receipts: list[bytes] = []
    for catalog_card in catalog.cards:
        card = dict(catalog_card.raw)
        text_hashes = {
            "canonical_statement_sha256": _sha256(
                card["canonical_statement"].encode("utf-8")
            ),
            "proof_strategy_sha256": _sha256(card["proof_strategy"].encode("utf-8")),
            "sketch_steps_sha256": _sha256(rfc8785.dumps(card["sketch_steps"])),
        }
        authorship.append(
            rfc8785.dumps(
                {
                    "schema_version": "pals.continuity-authorship-attestation.v1",
                    "draft_id": card["draft_id"],
                    **text_hashes,
                    "reviewer_role": "pals_curriculum_author",
                    "reviewed_at": "2026-08-05T00:00:00Z",
                    "result": "original",
                }
            )
        )
        source_review.append(
            rfc8785.dumps(
                {
                    "schema_version": "pals.continuity-source-review.v1",
                    "draft_id": card["draft_id"],
                    **text_hashes,
                    "reviewer_role": "pals_curriculum_reviewer",
                    "reviewed_at": "2026-08-05T00:00:00Z",
                    "result": "original",
                    "review_protocol": "manual_external_comparison_v1",
                }
            )
        )
        lean_receipts.append(
            rfc8785.dumps(
                {
                    "schema_version": "pals.continuity-lean-receipt.v1",
                    "draft_id": card["draft_id"],
                    "canonical_statement_sha256": text_hashes[
                        "canonical_statement_sha256"
                    ],
                    "openmath_xml_sha256": _sha256(card["openmath_xml"].encode("utf-8")),
                    "openmath_to_lean_profile": "pals.openmath-to-lean.continuity-v1",
                    "lean_declaration_name": f"Pals.ContinuityV1.{card['draft_id']}",
                    "lean_declaration_sha256": _sha256(card["lean_target"].encode("utf-8")),
                    "theorem_artifact_sha256": _sha256(
                        f"synthetic-artifact:{card['draft_id']}".encode()
                    ),
                    "wrapper_source_sha256": _sha256(
                        _wrapper_source(card).encode("utf-8")
                    ),
                    "toolchain_manifest_sha256": _sha256(b"synthetic-toolchain"),
                    "verified_at": "2026-08-05T00:00:00Z",
                    "result": "verified",
                }
            )
        )
    return tuple(authorship), tuple(source_review), tuple(lean_receipts)


def test_pfi_ag_008_projects_all_110_catalog_cards_without_rewriting_fields() -> None:
    authorship, source_review, lean_receipts = _formal_evidence()

    candidate = ContinuityReleaseCandidateProjector().project(
        catalog_path=CATALOG,
        authorship_attestations=authorship,
        source_review_attestations=source_review,
        lean_receipts=lean_receipts,
    )

    catalog = load_continuity_catalog(CATALOG)
    assert len(candidate.drafts) == 110
    assert [draft.id for draft in candidate.drafts] == [card.draft_id for card in catalog.cards]
    assert [draft.matched_prompt for draft in candidate.drafts] == [
        card.raw["canonical_statement"] for card in catalog.cards
    ]
    assert [draft.openmath_xml for draft in candidate.drafts] == [
        card.raw["openmath_xml"] for card in catalog.cards
    ]
    assert [draft.proof_strategy for draft in candidate.drafts] == [
        card.raw["proof_strategy"] for card in catalog.cards
    ]
    assert [draft.sketch_steps for draft in candidate.drafts] == [
        tuple(card.raw["sketch_steps"]) for card in catalog.cards
    ]
    assert len(candidate.evidence) == 110


@pytest.mark.parametrize(
    "field, value, expected_code",
    [
        ("reviewer_role", "wrong_role", "source_review_contract_invalid"),
        ("result", "not_original", "authorship_contract_invalid"),
        ("draft_id", "cv1_not_in_catalog", "evidence_id_set_mismatch"),
    ],
)
def test_pfi_ag_008_rejects_mutated_formal_evidence_before_candidate_output(
    field: str,
    value: str,
    expected_code: str,
) -> None:
    authorship, source_review, lean_receipts = _formal_evidence()
    if field == "reviewer_role":
        mutated = json.loads(source_review[0])
        mutated[field] = value
        source_review = (rfc8785.dumps(mutated), *source_review[1:])
    else:
        mutated = json.loads(authorship[0])
        mutated[field] = value
        authorship = (rfc8785.dumps(mutated), *authorship[1:])

    with pytest.raises(ContinuityReleaseCandidateError) as raised:
        ContinuityReleaseCandidateProjector().project(
            catalog_path=CATALOG,
            authorship_attestations=authorship,
            source_review_attestations=source_review,
            lean_receipts=lean_receipts,
        )

    assert raised.value.code == expected_code


def test_pfi_ag_008_rejects_the_local_receipt_collection_as_formal_evidence() -> None:
    authorship, source_review, lean_receipts = _formal_evidence()

    with pytest.raises(ContinuityReleaseCandidateError) as raised:
        ContinuityReleaseCandidateProjector().project(
            catalog_path=CATALOG,
            authorship_attestations=authorship,
            source_review_attestations=source_review,
            lean_receipts=(LOCAL_RECEIPTS.read_bytes(), *lean_receipts[1:]),
        )

    assert raised.value.code == "formal_lean_receipt_schema_invalid"


def test_pfi_ag_008_rejects_a_non_jcs_evidence_object() -> None:
    authorship, source_review, lean_receipts = _formal_evidence()

    with pytest.raises(ContinuityReleaseCandidateError) as raised:
        ContinuityReleaseCandidateProjector().project(
            catalog_path=CATALOG,
            authorship_attestations=(authorship[0] + b"\n", *authorship[1:]),
            source_review_attestations=source_review,
            lean_receipts=lean_receipts,
        )

    assert raised.value.code == "authorship_not_jcs"
