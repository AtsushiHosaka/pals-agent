from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from pals_agent.openmath import (
    retrieval_openmath_structural_features,
    validate_canonical_retrieval_openmath_xml,
)
from pals_agent.private_draft_candidates import DraftCandidate


class DraftEvidenceError(ValueError):
    """Candidate evidence cannot be computed under the closed PFI contract."""


@dataclass(frozen=True, slots=True)
class DraftEvidence:
    candidate: DraftCandidate
    vector_score: float
    structural_score: float
    exact_equivalence: bool


def project_draft_evidence(
    *,
    query_openmath_xml: str,
    candidates: tuple[DraftCandidate, ...],
) -> tuple[DraftEvidence, ...]:
    """Attach deterministic evidence without selecting, filtering, or reordering rows."""
    query = validate_canonical_retrieval_openmath_xml(query_openmath_xml)
    query_features = retrieval_openmath_structural_features(query)
    projected: list[DraftEvidence] = []
    for candidate in candidates:
        distance = _distance(candidate.cosine_distance)
        candidate_xml = validate_canonical_retrieval_openmath_xml(
            candidate.draft.openmath_xml
        )
        candidate_features = retrieval_openmath_structural_features(candidate_xml)
        projected.append(
            DraftEvidence(
                candidate=candidate,
                vector_score=_clamp(1.0 - distance),
                structural_score=_structural_score(query_features, candidate_features),
                exact_equivalence=query == candidate_xml,
            )
        )
    return tuple(projected)


def _distance(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DraftEvidenceError("Candidate cosine distance is invalid.")
    distance = float(value)
    if not math.isfinite(distance):
        raise DraftEvidenceError("Candidate cosine distance is invalid.")
    return 0.0 if distance == 0.0 else distance


def _structural_score(query: Counter[str], candidate: Counter[str]) -> float:
    query_weight = sum(query.values())
    candidate_weight = sum(candidate.values())
    if query_weight == 0 or candidate_weight == 0:
        return 0.0
    overlap = sum((query & candidate).values())
    score = 0.85 * (overlap / query_weight) + 0.15 * (overlap / candidate_weight)
    if not math.isfinite(score):
        raise DraftEvidenceError("Candidate structural score is invalid.")
    return _clamp(score)


def _clamp(value: float) -> float:
    if not math.isfinite(value):
        raise DraftEvidenceError("Candidate evidence is invalid.")
    return min(1.0, max(0.0, value))
