from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from pals_agent.draft_embeddings import EmbeddingError
from pals_agent.openmath import (
    MathXMLValidationError,
    OpenMathStructuringError,
    canonicalize_retrieval_openmath_xml,
)
from pals_agent.private_draft_candidates import (
    CANONICALIZER_VERSION,
    DraftCandidateCompatibilityError,
    DraftCandidateLimitError,
    DraftCandidateResult,
    DraftCandidateUnavailableError,
    DraftEmbeddingFingerprint,
    PrivateDraftCandidateClient,
    normalize_draft_embedding,
    validate_draft_embedding_fingerprint,
)
from pals_agent.proof_flow_evidence import DraftEvidence, project_draft_evidence
from pals_agent.proof_flow_reranker import (
    DraftRerankerInvalidError,
    DraftRerankerRequest,
    DraftRerankerUnavailableError,
    OpenAIDraftReranker,
    build_draft_reranker_request,
)

_ERROR_CODES = frozenset(
    {
        "input_too_large",
        "xml_invalid",
        "resource_limit_exceeded",
        "openmath_profile_invalid",
        "openmath_semantic_invalid",
        "canonicalizer_provenance_mismatch",
        "fingerprint_mismatch",
        "catalog_manifest_mismatch",
        "embedding_invalid",
        "candidate_limit_exceeded",
        "score_invalid",
        "reranker_invalid",
        "reranker_unavailable",
        "catalog_migration_incompatible",
        "retrieval_unavailable",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class StatementStructurer(Protocol):
    def structure(self, statement: str) -> str: ...


class ProofFlowRetrievalError(RuntimeError):
    """One closed PFI failure token suitable for worker status handling."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("Proof Flow retrieval error code is not registered.")
        super().__init__(code)
        self.code = code

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": "pals.draft-retrieval.v1",
            "outcome": "error",
            "error": {"code": self.code},
        }


class QueryEmbeddingModel(Protocol):
    def embed(self, text: str) -> list[float]: ...


class CandidatePort(Protocol):
    def find_candidates(
        self,
        *,
        embedding: list[float],
        fingerprint: DraftEmbeddingFingerprint,
    ) -> DraftCandidateResult: ...


class DraftReranker(Protocol):
    def rerank(self, request: DraftRerankerRequest) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class DraftRetrievalResult:
    """One validated PFI match/no-match result; natural input never leaves this object."""

    outcome: Literal["match", "no_match"]
    query_openmath: str
    contexts: tuple[DraftEvidence, ...]
    compatibility: dict[str, str | int]

    def __post_init__(self) -> None:
        if self.outcome == "match" and not self.contexts:
            raise ValueError("A Draft retrieval match requires a selected context")
        if self.outcome == "no_match" and self.contexts:
            raise ValueError("A Draft retrieval no-match cannot include contexts")

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": "pals.draft-retrieval.v1",
            "outcome": self.outcome,
            "query_openmath": self.query_openmath,
            "contexts": [
                {
                    "draft": {
                        "id": item.candidate.draft.id,
                        "canonical_statement": item.candidate.draft.matched_prompt,
                        "openmath_xml": item.candidate.draft.openmath_xml,
                        "proof_strategy": item.candidate.draft.proof_strategy,
                        "sketch_steps": list(item.candidate.draft.sketch_steps),
                    },
                    "evidence": {
                        "cosine_distance": item.candidate.cosine_distance,
                        "vector": item.vector_score,
                        "structural": item.structural_score,
                        "exact_equivalence": item.exact_equivalence,
                    },
                }
                for item in self.contexts
            ],
            "compatibility": self.compatibility,
        }


@dataclass(frozen=True, slots=True)
class PreparedDraftRetrieval:
    """Validated retrieval inputs immediately before the single reranker call."""

    query_openmath: str
    candidates: DraftCandidateResult
    evidence: tuple[DraftEvidence, ...]
    reranker_request: DraftRerankerRequest


@dataclass(frozen=True, slots=True)
class ProofFlowRuntime:
    """The ordered Agent-only PFI retrieval path with no catalog or database capability."""

    structurer: StatementStructurer
    embedding_model: QueryEmbeddingModel
    embedding_fingerprint: DraftEmbeddingFingerprint
    runtime_provenance_sha256: str
    candidate_client: CandidatePort
    reranker: DraftReranker

    def __post_init__(self) -> None:
        if not isinstance(self.runtime_provenance_sha256, str) or not _SHA256.fullmatch(
            self.runtime_provenance_sha256
        ):
            raise ValueError("PFI runtime provenance digest is invalid")

    def prepare(self, natural_statement: str) -> PreparedDraftRetrieval:
        """Run the shared deterministic path without invoking the semantic reranker."""
        from pals_agent.input_fence import check_input_snapshot

        check_input_snapshot()
        if not isinstance(natural_statement, str) or not natural_statement.strip():
            raise ProofFlowRetrievalError("input_too_large")
        try:
            natural_statement_bytes = natural_statement.encode("utf-8")
        except UnicodeEncodeError:
            raise ProofFlowRetrievalError("input_too_large") from None
        if len(natural_statement_bytes) > 16_384:
            raise ProofFlowRetrievalError("input_too_large")
        try:
            query_openmath = canonicalize_retrieval_openmath_xml(
                self.structurer.structure(natural_statement)
            )
        except OpenMathStructuringError:
            raise ProofFlowRetrievalError("openmath_profile_invalid") from None
        except MathXMLValidationError:
            raise ProofFlowRetrievalError("openmath_profile_invalid") from None
        if self.embedding_fingerprint.canonicalizer_version != CANONICALIZER_VERSION:
            raise ProofFlowRetrievalError("canonicalizer_provenance_mismatch")
        try:
            fingerprint = validate_draft_embedding_fingerprint(self.embedding_fingerprint)
        except ValueError:
            raise ProofFlowRetrievalError("fingerprint_mismatch") from None
        try:
            embedding = normalize_draft_embedding(
                self.embedding_model.embed(query_openmath),
                fingerprint=fingerprint,
            )
        except (EmbeddingError, TypeError, ValueError, OverflowError, struct.error):
            raise ProofFlowRetrievalError("embedding_invalid") from None
        try:
            candidates = self.candidate_client.find_candidates(
                embedding=embedding,
                fingerprint=fingerprint,
            )
        except DraftCandidateLimitError:
            raise ProofFlowRetrievalError("candidate_limit_exceeded") from None
        except DraftCandidateCompatibilityError:
            raise ProofFlowRetrievalError("catalog_migration_incompatible") from None
        except DraftCandidateUnavailableError:
            raise ProofFlowRetrievalError("retrieval_unavailable") from None
        if candidates.runtime_provenance_sha256 != self.runtime_provenance_sha256:
            raise ProofFlowRetrievalError("catalog_manifest_mismatch")
        try:
            evidence = project_draft_evidence(
                query_openmath_xml=query_openmath,
                candidates=candidates.candidates,
            )
        except ValueError:
            raise ProofFlowRetrievalError("score_invalid") from None
        try:
            reranker_request = build_draft_reranker_request(
                natural_statement=natural_statement,
                query_openmath=query_openmath,
                evidence=evidence,
                candidates=candidates,
            )
        except DraftRerankerInvalidError:
            raise ProofFlowRetrievalError("reranker_invalid") from None
        return PreparedDraftRetrieval(
            query_openmath=query_openmath,
            candidates=candidates,
            evidence=evidence,
            reranker_request=reranker_request,
        )

    def finalize(
        self,
        prepared: PreparedDraftRetrieval,
        selected_ids: object,
    ) -> DraftRetrievalResult:
        """Validate one reranker selection and construct the closed runtime result."""
        if not isinstance(prepared, PreparedDraftRetrieval) or not _is_valid_selection(
            selected_ids, prepared.evidence
        ):
            raise ProofFlowRetrievalError("reranker_invalid")
        validated_ids = cast(tuple[str, ...], selected_ids)
        by_id = {item.candidate.draft.id: item for item in prepared.evidence}
        selected = tuple(by_id[draft_id] for draft_id in validated_ids)
        return DraftRetrievalResult(
            outcome="match" if selected else "no_match",
            query_openmath=prepared.query_openmath,
            contexts=selected,
            compatibility=prepared.reranker_request.compatibility,
        )

    def retrieve(self, natural_statement: str) -> DraftRetrievalResult:
        prepared = self.prepare(natural_statement)
        try:
            selected_ids = self.reranker.rerank(prepared.reranker_request)
        except DraftRerankerUnavailableError:
            raise ProofFlowRetrievalError("reranker_unavailable") from None
        except DraftRerankerInvalidError:
            raise ProofFlowRetrievalError("reranker_invalid") from None
        return self.finalize(prepared, selected_ids)


def build_private_proof_flow_runtime(
    *,
    structurer: StatementStructurer,
    embedding_model: QueryEmbeddingModel,
    embedding_fingerprint: DraftEmbeddingFingerprint,
    runtime_provenance_sha256: str,
    api_base_url: str,
    worker_secret: str,
    openai_api_key: str,
) -> ProofFlowRuntime:
    """Construct the production PFI boundaries without exposing a catalog adapter."""
    return ProofFlowRuntime(
        structurer=structurer,
        embedding_model=embedding_model,
        embedding_fingerprint=embedding_fingerprint,
        runtime_provenance_sha256=runtime_provenance_sha256,
        candidate_client=PrivateDraftCandidateClient(
            base_url=api_base_url,
            worker_secret=worker_secret,
        ),
        reranker=OpenAIDraftReranker(api_key=openai_api_key),
    )


def _is_valid_selection(
    selected_ids: object,
    evidence: tuple[DraftEvidence, ...],
) -> bool:
    if (
        not isinstance(selected_ids, tuple)
        or len(selected_ids) > 4
        or not all(isinstance(identifier, str) for identifier in selected_ids)
        or len(selected_ids) != len(set(selected_ids))
    ):
        return False
    allowed_ids = {item.candidate.draft.id for item in evidence}
    return all(identifier in allowed_ids for identifier in selected_ids)
