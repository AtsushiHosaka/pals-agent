from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from importlib import resources
from typing import Any, Protocol, cast

from pals_agent.models import ProofDraft
from pals_agent.openmath import (
    canonicalize_openmath_xml,
    validate_openmath_statement_semantics,
)

OPENMATH_EMBEDDING_CANONICALIZER_VERSION = "openmath-cdbase-alpha-c14n-v2"


class DraftCatalog(Protocol):
    def find_by_statement(self, statement: str) -> ProofDraft | None: ...

    def find_by_openmath(self, openmath_xml: str) -> ProofDraft | None: ...

    def find_by_id(self, draft_id: str) -> ProofDraft | None: ...


@dataclass(frozen=True, slots=True)
class DraftSearchResult:
    draft: ProofDraft
    query_openmath_xml: str
    vector_score: float
    structural_score: float
    final_score: float
    exact_equivalence: bool


@dataclass(frozen=True, slots=True)
class SeedDraftCatalog:
    """Packaged seed catalog used only by the signed-worker build input."""

    drafts: tuple[ProofDraft, ...] | None = None

    def all_drafts(self) -> tuple[ProofDraft, ...]:
        if self.drafts is not None:
            return self.drafts
        return load_seed_drafts()

    def find_by_statement(self, statement: str) -> ProofDraft | None:
        _ = statement
        return None

    def find_by_openmath(self, openmath_xml: str) -> ProofDraft | None:
        _ = openmath_xml
        return None

    def find_by_id(self, draft_id: str) -> ProofDraft | None:
        for draft in self.all_drafts():
            if draft.id == draft_id:
                return draft
        return None


def load_seed_drafts() -> tuple[ProofDraft, ...]:
    seed_path = resources.files("pals_agent.seed").joinpath("dsp_drafts.json")
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("DSP draft seed must be a JSON array")
    drafts = tuple(_draft_from_payload(item) for item in payload)
    validate_draft_collection(drafts)
    return drafts


def normalize_statement(statement: str) -> str:
    return " ".join(statement.strip().split())


def draft_embedding_text(draft: ProofDraft) -> str:
    return canonicalize_openmath_xml(draft.openmath_xml)


def openmath_query_embedding_text(openmath_xml: str) -> str:
    return canonicalize_openmath_xml(openmath_xml)


def draft_seed_manifest(drafts: tuple[ProofDraft, ...]) -> str:
    payload = [
        {
            "id": draft.id,
            "matched_prompt": draft.matched_prompt,
            "openmath_xml": draft_embedding_text(draft),
            "proof_strategy": draft.proof_strategy,
            "sketch_steps": list(draft.sketch_steps),
        }
        for draft in sorted(drafts, key=lambda item: item.id)
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def validate_draft_collection(drafts: tuple[ProofDraft, ...]) -> None:
    draft_ids = {draft.id for draft in drafts}
    if len(draft_ids) != len(drafts):
        raise ValueError("DSP draft ids must be unique")

    for draft in drafts:
        validate_draft_xml(draft)


def validate_draft_xml(draft: ProofDraft) -> None:
    validate_openmath_statement_semantics(draft.openmath_xml, draft.matched_prompt)


def _draft_from_payload(payload: object) -> ProofDraft:
    if not isinstance(payload, dict):
        raise ValueError("DSP draft item must be a JSON object")
    item = cast(dict[str, Any], payload)
    return ProofDraft(
        id=_required_str(item, "id"),
        matched_prompt=_required_str(item, "matched_prompt"),
        openmath_xml=_required_str(item, "openmath_xml"),
        proof_strategy=_required_str(item, "proof_strategy"),
        sketch_steps=tuple(_required_str_list(item, "sketch_steps")),
    )


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"DSP draft field `{key}` must be a non-empty string")
    return value


def _required_str_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"DSP draft field `{key}` must be a string array")
    return cast(list[str], value)
