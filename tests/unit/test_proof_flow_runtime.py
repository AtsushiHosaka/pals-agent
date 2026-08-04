from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from pals_agent.models import ProofDraft
from pals_agent.openmath import OpenMathStructuringError, canonicalize_retrieval_openmath_xml
from pals_agent.private_draft_candidates import (
    DraftCandidate,
    DraftCandidateLimitError,
    DraftCandidateResult,
    DraftEmbeddingFingerprint,
)
from pals_agent.proof_flow_reranker import DraftRerankerRequest
from pals_agent.proof_flow_runtime import ProofFlowRetrievalError, ProofFlowRuntime

_XML = canonicalize_retrieval_openmath_xml(
    '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMBIND>'
    '<OMS cd="quant1" name="forall"/><OMBVAR><OMV name="x"/></OMBVAR><OMA>'
    '<OMS cd="relation1" name="eq"/><OMV name="x"/><OMV name="x"/>'
    "</OMA></OMBIND></OMOBJ>"
)
_SOURCE_XML = (
    '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMBIND>'
    '<OMS cd="quant1" name="forall"/><OMBVAR><OMV name="x"/></OMBVAR><OMA>'
    '<OMS cd="relation1" name="eq"/><OMV name="x"/><OMV name="x"/>'
    "</OMA></OMBIND></OMOBJ>"
)
_FINGERPRINT = DraftEmbeddingFingerprint(
    provider="openai",
    model="text-embedding-3-small",
    endpoint="https://api.openai.com/v1",
    deployment="text-embedding-3-small",
    revision="2026-07-27",
    dimension=2,
)
_RUNTIME_PROVENANCE_SHA256 = "b" * 64


@dataclass
class FakeStructurer:
    calls: list[str]

    def structure(self, statement: str) -> str:
        self.calls.append(statement)
        return _SOURCE_XML


@dataclass
class FakeEmbeddingModel:
    calls: list[str]

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [1.0, 0.0]


@dataclass
class FakeCandidatePort:
    calls: list[tuple[list[float], DraftEmbeddingFingerprint]]

    def find_candidates(
        self,
        *,
        embedding: list[float],
        fingerprint: DraftEmbeddingFingerprint,
    ) -> DraftCandidateResult:
        self.calls.append((embedding, fingerprint))
        candidate = DraftCandidate(
            draft=ProofDraft(
                id="a",
                matched_prompt="For all x, x equals x.",
                openmath_xml=_XML,
                proof_strategy="Use reflexivity.",
                sketch_steps=("Apply reflexivity.",),
            ),
            cosine_distance=0.0,
        )
        return DraftCandidateResult(
            generation_id="11111111-1111-4111-8111-111111111111",
            manifest_sha256="sha256:" + "a" * 64,
            seed_count=1,
            runtime_provenance_sha256="b" * 64,
            fingerprint=_FINGERPRINT,
            candidates=(candidate,),
        )


@dataclass
class FakeReranker:
    ids: tuple[str, ...]
    calls: list[DraftRerankerRequest]

    def rerank(self, request: DraftRerankerRequest) -> tuple[str, ...]:
        self.calls.append(request)
        return self.ids


def test_pfi_runtime_runs_one_ordered_private_candidate_and_reranker_flow() -> None:
    structurer = FakeStructurer(calls=[])
    embeddings = FakeEmbeddingModel(calls=[])
    candidate_port = FakeCandidatePort(calls=[])
    reranker = FakeReranker(ids=("a",), calls=[])
    runtime = ProofFlowRuntime(
        structurer=structurer,
        embedding_model=embeddings,
        embedding_fingerprint=_FINGERPRINT,
        runtime_provenance_sha256=_RUNTIME_PROVENANCE_SHA256,
        candidate_client=candidate_port,
        reranker=reranker,
    )

    result = runtime.retrieve("For all real x, x equals x.")

    assert result.outcome == "match"
    assert [item.candidate.draft.id for item in result.contexts] == ["a"]
    payload = result.as_json()
    assert payload["outcome"] == "match"
    contexts = payload["contexts"]
    assert isinstance(contexts, list)
    assert contexts[0]["draft"]["id"] == "a"
    assert structurer.calls == ["For all real x, x equals x."]
    assert embeddings.calls == [_XML]
    assert candidate_port.calls == [([1.0, 0.0], _FINGERPRINT)]
    assert len(reranker.calls) == 1


def test_pfi_runtime_prepares_without_reranking_and_finalizes_one_selection() -> None:
    reranker = FakeReranker(ids=("a",), calls=[])
    runtime = ProofFlowRuntime(
        structurer=FakeStructurer(calls=[]),
        embedding_model=FakeEmbeddingModel(calls=[]),
        embedding_fingerprint=_FINGERPRINT,
        runtime_provenance_sha256=_RUNTIME_PROVENANCE_SHA256,
        candidate_client=FakeCandidatePort(calls=[]),
        reranker=reranker,
    )

    prepared = runtime.prepare("For all real x, x equals x.")

    assert reranker.calls == []
    assert prepared.query_openmath == _XML
    assert [item.candidate.draft.id for item in prepared.evidence] == ["a"]
    result = runtime.finalize(prepared, ("a",))
    assert result.outcome == "match"
    assert [item.candidate.draft.id for item in result.contexts] == ["a"]


def test_pfi_runtime_returns_typed_no_match_without_a_catalog_fallback() -> None:
    runtime = ProofFlowRuntime(
        structurer=FakeStructurer(calls=[]),
        embedding_model=FakeEmbeddingModel(calls=[]),
        embedding_fingerprint=_FINGERPRINT,
        runtime_provenance_sha256=_RUNTIME_PROVENANCE_SHA256,
        candidate_client=FakeCandidatePort(calls=[]),
        reranker=FakeReranker(ids=(), calls=[]),
    )

    result = runtime.retrieve("For all real x, x equals x.")

    assert result.outcome == "no_match"
    assert result.contexts == ()


def test_pfi_runtime_rejects_non_utf8_natural_input_before_structuring() -> None:
    structurer = FakeStructurer(calls=[])
    embeddings = FakeEmbeddingModel(calls=[])
    candidates = FakeCandidatePort(calls=[])
    reranker = FakeReranker(ids=(), calls=[])
    runtime = ProofFlowRuntime(
        structurer=structurer,
        embedding_model=embeddings,
        embedding_fingerprint=_FINGERPRINT,
        runtime_provenance_sha256=_RUNTIME_PROVENANCE_SHA256,
        candidate_client=candidates,
        reranker=reranker,
    )

    with pytest.raises(ProofFlowRetrievalError, match="input_too_large"):
        runtime.retrieve("\ud800")

    assert structurer.calls == []
    assert embeddings.calls == []
    assert candidates.calls == []
    assert reranker.calls == []


def test_pfi_runtime_maps_private_candidate_unavailability_to_closed_error() -> None:
    class UnavailableCandidatePort:
        def find_candidates(
            self,
            *,
            embedding: list[float],
            fingerprint: DraftEmbeddingFingerprint,
        ) -> DraftCandidateResult:
            del embedding, fingerprint
            from pals_agent.private_draft_candidates import DraftCandidateUnavailableError

            raise DraftCandidateUnavailableError("unavailable")

    runtime = ProofFlowRuntime(
        structurer=FakeStructurer(calls=[]),
        embedding_model=FakeEmbeddingModel(calls=[]),
        embedding_fingerprint=_FINGERPRINT,
        runtime_provenance_sha256=_RUNTIME_PROVENANCE_SHA256,
        candidate_client=UnavailableCandidatePort(),
        reranker=FakeReranker(ids=(), calls=[]),
    )

    with pytest.raises(ProofFlowRetrievalError, match="retrieval_unavailable"):
        runtime.retrieve("For all real x, x equals x.")

    assert ProofFlowRetrievalError("retrieval_unavailable").as_json() == {
        "schema_version": "pals.draft-retrieval.v1",
        "outcome": "error",
        "error": {"code": "retrieval_unavailable"},
    }


def test_pfi_runtime_maps_candidate_limit_or_duplicate_ids_to_the_closed_limit_error() -> None:
    class CandidateLimitPort:
        def find_candidates(
            self,
            *,
            embedding: list[float],
            fingerprint: DraftEmbeddingFingerprint,
        ) -> DraftCandidateResult:
            del embedding, fingerprint
            raise DraftCandidateLimitError("too many or duplicate candidates")

    runtime = ProofFlowRuntime(
        structurer=FakeStructurer(calls=[]),
        embedding_model=FakeEmbeddingModel(calls=[]),
        embedding_fingerprint=_FINGERPRINT,
        runtime_provenance_sha256=_RUNTIME_PROVENANCE_SHA256,
        candidate_client=CandidateLimitPort(),
        reranker=FakeReranker(ids=(), calls=[]),
    )

    with pytest.raises(ProofFlowRetrievalError, match="candidate_limit_exceeded"):
        runtime.retrieve("For all real x, x equals x.")


@pytest.mark.parametrize("selected_ids", [("foreign",), ("a", "a"), ("a",) * 5])
def test_pfi_runtime_rejects_an_invalid_reranker_selection_at_the_final_boundary(
    selected_ids: tuple[str, ...],
) -> None:
    runtime = ProofFlowRuntime(
        structurer=FakeStructurer(calls=[]),
        embedding_model=FakeEmbeddingModel(calls=[]),
        embedding_fingerprint=_FINGERPRINT,
        runtime_provenance_sha256=_RUNTIME_PROVENANCE_SHA256,
        candidate_client=FakeCandidatePort(calls=[]),
        reranker=FakeReranker(ids=selected_ids, calls=[]),
    )

    with pytest.raises(ProofFlowRetrievalError, match="reranker_invalid"):
        runtime.retrieve("For all real x, x equals x.")


def test_pfi_runtime_maps_structuring_failure_to_a_closed_error() -> None:
    class FailingStructurer:
        def structure(self, statement: str) -> str:
            del statement
            raise OpenMathStructuringError("provider detail must not reach the PFI DTO")

    runtime = ProofFlowRuntime(
        structurer=FailingStructurer(),
        embedding_model=FakeEmbeddingModel(calls=[]),
        embedding_fingerprint=_FINGERPRINT,
        runtime_provenance_sha256=_RUNTIME_PROVENANCE_SHA256,
        candidate_client=FakeCandidatePort(calls=[]),
        reranker=FakeReranker(ids=(), calls=[]),
    )

    with pytest.raises(ProofFlowRetrievalError, match="openmath_profile_invalid"):
        runtime.retrieve("For all real x, x equals x.")


def test_pfi_runtime_rejects_c14n_v3_before_embedding_or_api() -> None:
    structurer = FakeStructurer(calls=[])
    embeddings = FakeEmbeddingModel(calls=[])
    candidates = FakeCandidatePort(calls=[])
    reranker = FakeReranker(ids=(), calls=[])
    runtime = ProofFlowRuntime(
        structurer=structurer,
        embedding_model=embeddings,
        embedding_fingerprint=replace(
            _FINGERPRINT, canonicalizer_version="openmath-cdbase-alpha-c14n-v3"
        ),
        runtime_provenance_sha256=_RUNTIME_PROVENANCE_SHA256,
        candidate_client=candidates,
        reranker=reranker,
    )

    with pytest.raises(ProofFlowRetrievalError, match="canonicalizer_provenance_mismatch"):
        runtime.retrieve("For all real x, x equals x.")

    assert structurer.calls == ["For all real x, x equals x."]
    assert embeddings.calls == []
    assert candidates.calls == []
    assert reranker.calls == []


def test_pfi_runtime_rejects_an_invalid_embedding_before_private_api_or_reranker() -> None:
    @dataclass
    class ZeroEmbeddingModel:
        calls: list[str]

        def embed(self, text: str) -> list[float]:
            self.calls.append(text)
            return [0.0, -0.0]

    embeddings = ZeroEmbeddingModel(calls=[])
    candidates = FakeCandidatePort(calls=[])
    reranker = FakeReranker(ids=(), calls=[])
    runtime = ProofFlowRuntime(
        structurer=FakeStructurer(calls=[]),
        embedding_model=embeddings,
        embedding_fingerprint=_FINGERPRINT,
        runtime_provenance_sha256=_RUNTIME_PROVENANCE_SHA256,
        candidate_client=candidates,
        reranker=reranker,
    )

    with pytest.raises(ProofFlowRetrievalError, match="embedding_invalid"):
        runtime.retrieve("For all real x, x equals x.")

    assert embeddings.calls == [_XML]
    assert candidates.calls == []
    assert reranker.calls == []


def test_pfi_runtime_rejects_unmatched_api_runtime_provenance_before_reranker() -> None:
    class WrongProvenanceCandidatePort:
        def __init__(self) -> None:
            self.calls: list[tuple[list[float], DraftEmbeddingFingerprint]] = []

        def find_candidates(
            self,
            *,
            embedding: list[float],
            fingerprint: DraftEmbeddingFingerprint,
        ) -> DraftCandidateResult:
            result = FakeCandidatePort(calls=self.calls).find_candidates(
                embedding=embedding,
                fingerprint=fingerprint,
            )
            return replace(result, runtime_provenance_sha256="c" * 64)

    candidates = WrongProvenanceCandidatePort()
    reranker = FakeReranker(ids=("a",), calls=[])
    runtime = ProofFlowRuntime(
        structurer=FakeStructurer(calls=[]),
        embedding_model=FakeEmbeddingModel(calls=[]),
        embedding_fingerprint=_FINGERPRINT,
        runtime_provenance_sha256=_RUNTIME_PROVENANCE_SHA256,
        candidate_client=candidates,
        reranker=reranker,
    )

    with pytest.raises(ProofFlowRetrievalError, match="catalog_manifest_mismatch"):
        runtime.retrieve("For all real x, x equals x.")

    assert len(candidates.calls) == 1
    assert reranker.calls == []


def test_pfi_runtime_rejects_unregistered_error_codes() -> None:
    with pytest.raises(ValueError, match="not registered"):
        ProofFlowRetrievalError("provider_error")
