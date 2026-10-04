"""Natural retrieval evidence has source identity and distance, not formal admission scores."""

from dataclasses import dataclass
from typing import Literal

from pals_agent.private_draft_candidates import DraftCandidate


@dataclass(frozen=True, slots=True)
class NaturalDraftContext:
    candidate: DraftCandidate


@dataclass(frozen=True, slots=True)
class NaturalDraftRetrievalResult:
    outcome: Literal["match", "no_match"]
    query_openmath: str
    contexts: tuple[NaturalDraftContext, ...]
    compatibility: dict[str, str | int]

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": "pals.natural-draft-retrieval.v1",
            "outcome": self.outcome,
            "query_openmath": self.query_openmath,
            "query_evidence_kind": "untrusted_retrieval_hint",
            "contexts": [
                {
                    "draft": {
                        "id": item.candidate.draft.id,
                        "canonical_statement": item.candidate.draft.matched_prompt,
                        "openmath_xml": item.candidate.draft.openmath_xml,
                        "proof_strategy": item.candidate.draft.proof_strategy,
                        "sketch_steps": list(item.candidate.draft.sketch_steps),
                    },
                    "cosine_distance": item.candidate.cosine_distance,
                }
                for item in self.contexts
            ],
            "compatibility": self.compatibility,
        }
