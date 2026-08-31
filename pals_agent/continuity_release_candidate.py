"""Fail-closed, in-memory PFI-AG-008 evidence binding for continuity-v1 cards.

This boundary deliberately cannot sign, embed, package, publish, or persist a candidate.  It
turns an already admitted catalog and externally supplied formal evidence into the five Draft
fields needed by the later signed-worker gate, and rejects every incomplete or local-only input.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rfc8785

from pals_agent.models import ProofDraft
from pals_agent.proof_flow_seed import ContinuityCatalogCard, load_continuity_catalog

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_AUTHORSHIP_SCHEMA = "pals.continuity-authorship-attestation.v1"
_SOURCE_REVIEW_SCHEMA = "pals.continuity-source-review.v1"
_FORMAL_LEAN_RECEIPT_SCHEMA = "pals.continuity-lean-receipt.v1"
_OPENMATH_TO_LEAN_PROFILE = "pals.openmath-to-lean.continuity-v1"
_AUTHORSHIP_FIELDS = frozenset(
    {
        "canonical_statement_sha256",
        "draft_id",
        "proof_strategy_sha256",
        "result",
        "reviewed_at",
        "reviewer_role",
        "schema_version",
        "sketch_steps_sha256",
    }
)
_SOURCE_REVIEW_FIELDS = _AUTHORSHIP_FIELDS | {"review_protocol"}
_FORMAL_LEAN_RECEIPT_FIELDS = frozenset(
    {
        "canonical_statement_sha256",
        "draft_id",
        "lean_declaration_name",
        "lean_declaration_sha256",
        "openmath_to_lean_profile",
        "openmath_xml_sha256",
        "result",
        "schema_version",
        "theorem_artifact_sha256",
        "toolchain_manifest_sha256",
        "verified_at",
        "wrapper_source_sha256",
    }
)


class ContinuityReleaseCandidateError(ValueError):
    """One exact PFI-AG-008 admission check rejected the candidate."""

    def __init__(self, code: str) -> None:
        super().__init__(f"continuity release candidate rejected: {code}")
        self.code = code


@dataclass(frozen=True, slots=True)
class ContinuityEvidenceBinding:
    """Only hashes of formal evidence survive the candidate boundary."""

    draft_id: str
    authorship_attestation_sha256: str
    source_review_attestation_sha256: str
    lean_receipt_sha256: str


@dataclass(frozen=True, slots=True)
class ContinuityReleaseCandidate:
    """In-memory only; this is neither a signed seed nor a publication artifact."""

    drafts: tuple[ProofDraft, ...]
    evidence: tuple[ContinuityEvidenceBinding, ...]


@dataclass(frozen=True, slots=True)
class ContinuityReleaseCandidateProjector:
    """Bind every approved catalog card to parent-exact formal evidence."""

    def project(
        self,
        *,
        catalog_path: Path,
        authorship_attestations: Sequence[bytes],
        source_review_attestations: Sequence[bytes],
        lean_receipts: Sequence[bytes],
    ) -> ContinuityReleaseCandidate:
        catalog = load_continuity_catalog(catalog_path)
        cards = tuple(catalog.cards)
        if len(cards) < 100:
            _reject("catalog_below_parent_volume_floor")

        authorship = _decode_evidence_set(
            authorship_attestations,
            kind="authorship",
            expected_fields=_AUTHORSHIP_FIELDS,
        )
        source_review = _decode_evidence_set(
            source_review_attestations,
            kind="source_review",
            expected_fields=_SOURCE_REVIEW_FIELDS,
        )
        formal_lean = _decode_evidence_set(
            lean_receipts,
            kind="formal_lean_receipt",
            expected_fields=_FORMAL_LEAN_RECEIPT_FIELDS,
        )

        expected_ids = tuple(card.draft_id for card in cards)
        expected_set = set(expected_ids)
        for values in (authorship, source_review, formal_lean):
            if set(values) != expected_set:
                _reject("evidence_id_set_mismatch")

        drafts: list[ProofDraft] = []
        bindings: list[ContinuityEvidenceBinding] = []
        for card in cards:
            authorship_record, authorship_bytes = authorship[card.draft_id]
            source_review_record, source_review_bytes = source_review[card.draft_id]
            formal_lean_record, formal_lean_bytes = formal_lean[card.draft_id]
            _validate_authorship(card, authorship_record)
            _validate_source_review(card, source_review_record)
            _validate_formal_lean_receipt(card, formal_lean_record)
            drafts.append(
                ProofDraft(
                    id=card.draft_id,
                    matched_prompt=card.raw["canonical_statement"],
                    openmath_xml=card.raw["openmath_xml"],
                    proof_strategy=card.raw["proof_strategy"],
                    sketch_steps=tuple(card.raw["sketch_steps"]),
                )
            )
            bindings.append(
                ContinuityEvidenceBinding(
                    draft_id=card.draft_id,
                    authorship_attestation_sha256=_sha256(authorship_bytes),
                    source_review_attestation_sha256=_sha256(source_review_bytes),
                    lean_receipt_sha256=_sha256(formal_lean_bytes),
                )
            )
        return ContinuityReleaseCandidate(drafts=tuple(drafts), evidence=tuple(bindings))


def _decode_evidence_set(
    values: Sequence[bytes],
    *,
    kind: str,
    expected_fields: frozenset[str],
) -> dict[str, tuple[Mapping[str, Any], bytes]]:
    decoded: dict[str, tuple[Mapping[str, Any], bytes]] = {}
    for raw in values:
        record = _decode_jcs_object(raw, kind=kind)
        if set(record) != expected_fields:
            _reject(f"{kind}_schema_invalid")
        draft_id = record.get("draft_id")
        if not isinstance(draft_id, str) or not draft_id:
            _reject(f"{kind}_schema_invalid")
        if draft_id in decoded:
            _reject(f"{kind}_duplicate_draft_id")
        decoded[draft_id] = (record, raw)
    return decoded


def _decode_jcs_object(raw: object, *, kind: str) -> Mapping[str, Any]:
    if not isinstance(raw, bytes) or not raw or b"\n" in raw or raw.startswith(b"\xef\xbb\xbf"):
        _reject(f"{kind}_not_jcs")
    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _reject(f"{kind}_not_jcs")
    if not isinstance(decoded, dict):
        _reject(f"{kind}_not_jcs")
    try:
        canonical = rfc8785.dumps(decoded)
    except (TypeError, ValueError):
        _reject(f"{kind}_not_jcs")
    if canonical != raw:
        _reject(f"{kind}_not_jcs")
    return decoded


def _no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _validate_authorship(card: ContinuityCatalogCard, record: Mapping[str, Any]) -> None:
    if (
        record["schema_version"] != _AUTHORSHIP_SCHEMA
        or record["reviewer_role"] != "pals_curriculum_author"
        or record["result"] != "original"
        or not _is_nonempty_string(record["reviewed_at"])
    ):
        _reject("authorship_contract_invalid")
    _validate_shared_text_hashes(card, record, kind="authorship")


def _validate_source_review(card: ContinuityCatalogCard, record: Mapping[str, Any]) -> None:
    if (
        record["schema_version"] != _SOURCE_REVIEW_SCHEMA
        or record["reviewer_role"] != "pals_curriculum_reviewer"
        or record["result"] != "original"
        or record["review_protocol"] != "manual_external_comparison_v1"
        or not _is_nonempty_string(record["reviewed_at"])
    ):
        _reject("source_review_contract_invalid")
    _validate_shared_text_hashes(card, record, kind="source_review")


def _validate_formal_lean_receipt(card: ContinuityCatalogCard, record: Mapping[str, Any]) -> None:
    if record["schema_version"] != _FORMAL_LEAN_RECEIPT_SCHEMA:
        _reject("formal_lean_receipt_schema_invalid")
    if (
        record["openmath_to_lean_profile"] != _OPENMATH_TO_LEAN_PROFILE
        or record["lean_declaration_name"] != f"Pals.ContinuityV1.{card.draft_id}"
        or record["result"] != "verified"
        or not _is_nonempty_string(record["verified_at"])
    ):
        _reject("formal_lean_receipt_contract_invalid")
    expected = {
        "canonical_statement_sha256": _sha256(
            card.raw["canonical_statement"].encode("utf-8")
        ),
        "openmath_xml_sha256": _sha256(card.raw["openmath_xml"].encode("utf-8")),
        "lean_declaration_sha256": _sha256(card.raw["lean_target"].encode("utf-8")),
        "wrapper_source_sha256": _sha256(_wrapper_source(card).encode("utf-8")),
    }
    if any(record[name] != value for name, value in expected.items()):
        _reject("formal_lean_receipt_hash_mismatch")
    for name in ("theorem_artifact_sha256", "toolchain_manifest_sha256"):
        if not _is_sha256(record[name]):
            _reject("formal_lean_receipt_hash_invalid")


def _validate_shared_text_hashes(
    card: ContinuityCatalogCard,
    record: Mapping[str, Any],
    *,
    kind: str,
) -> None:
    expected = {
        "canonical_statement_sha256": _sha256(
            card.raw["canonical_statement"].encode("utf-8")
        ),
        "proof_strategy_sha256": _sha256(card.raw["proof_strategy"].encode("utf-8")),
        "sketch_steps_sha256": _sha256(rfc8785.dumps(card.raw["sketch_steps"])),
    }
    if any(record[name] != value for name, value in expected.items()):
        _reject(f"{kind}_hash_mismatch")


def _wrapper_source(card: ContinuityCatalogCard) -> str:
    declaration = f"Pals.ContinuityV1.{card.draft_id}"
    return f"import {declaration}\nexample : {card.raw['lean_target']} := {declaration}\n"


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _reject(code: str) -> None:
    raise ContinuityReleaseCandidateError(code)
