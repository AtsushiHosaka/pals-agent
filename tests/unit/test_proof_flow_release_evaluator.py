from __future__ import annotations

import json
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from pals_agent.models import ProofDraft
from pals_agent.private_draft_candidates import (
    DraftCandidate,
    DraftCandidateResult,
    DraftEmbeddingFingerprint,
)
from pals_agent.proof_flow_evidence import DraftEvidence
from pals_agent.proof_flow_release_evaluator import (
    GovernedReleaseEvaluationCorpus,
    PFIReleaseAdmissionWitness,
    ProofFlowIndexReleaseEvaluator,
    ReleaseEvaluationError,
    load_governed_release_corpus,
)
from pals_agent.proof_flow_release_evidence import (
    DraftRerankerReleaseEvidenceWriter,
    ExternalReleaseEvidenceStore,
    ReleaseEvidenceRetention,
    ReleaseEvidenceStoreControls,
    ReleaseEvidenceWriteReceipt,
)
from pals_agent.proof_flow_reranker import (
    DraftRerankerRequest,
    DraftRerankerResponse,
    DraftRerankerUnavailableError,
    DraftRerankerUsage,
)
from pals_agent.proof_flow_runtime import PreparedDraftRetrieval, ProofFlowRuntime

_ROOT = Path(__file__).parents[3]
_CORPUS_PATH = _ROOT / "specs/proof-flow-index/evaluation-corpus.json"
_FINGERPRINT = DraftEmbeddingFingerprint(
    provider="openai",
    model="text-embedding-3-small",
    endpoint="https://api.openai.com/v1",
    deployment="text-embedding-3-small",
    revision="2026-07-27",
    dimension=2,
)
_ADMISSION = PFIReleaseAdmissionWitness(
    generation_id="11111111-1111-4111-8111-111111111111",
    manifest_sha256="sha256:" + "a" * 64,
    seed_count=31,
    runtime_provenance_sha256="b" * 64,
    fingerprint=_FINGERPRINT,
)
_USAGE = DraftRerankerUsage(
    input_tokens=10,
    cached_input_tokens=2,
    uncached_input_tokens=8,
    output_tokens=3,
    reasoning_output_tokens=1,
    nonreasoning_output_tokens=2,
    total_tokens=13,
)


class RecordingStore:
    def __init__(
        self,
        *,
        controls_valid: bool = True,
        omit_last_from_coverage: bool = False,
    ) -> None:
        self.controls_valid = controls_valid
        self.omit_last_from_coverage = omit_last_from_coverage
        self.records: list[tuple[bytes, ReleaseEvidenceRetention]] = []

    def inspect_active_controls(self) -> ReleaseEvidenceStoreControls:
        return ReleaseEvidenceStoreControls(
            encrypted_in_transit=self.controls_valid,
            encrypted_at_rest=True,
            readable_roles=frozenset(
                {"pals_release_operator", "pals_release_auditor"}
            ),
            retention_seconds=15_552_000,
            deletion_grace_seconds=86_400,
            scheduled_deletion_active=True,
            records_immutable_until_expiry=True,
            dataset_replication_disabled=True,
        )

    def has_overdue_retained_record(self) -> bool:
        return False

    def has_incomplete_corpus_run(
        self, *, governed_query_ids: frozenset[str]
    ) -> bool:
        by_observation: dict[str, set[str]] = {}
        for record, _ in self.records:
            payload = json.loads(record)
            by_observation.setdefault(payload["observed_at"], set()).add(
                payload["corpus_query_id"]
            )
        return any(
            frozenset(query_ids) != governed_query_ids
            for query_ids in by_observation.values()
        )

    def inspect_run_query_ids(self, *, observed_at: str) -> tuple[str, ...]:
        query_ids = tuple(
            json.loads(record)["corpus_query_id"]
            for record, _ in self.records
            if json.loads(record)["observed_at"] == observed_at
        )
        return query_ids[:-1] if self.omit_last_from_coverage else query_ids

    def write_encrypted_external(
        self, *, record_jcs: bytes, retention: ReleaseEvidenceRetention
    ) -> ReleaseEvidenceWriteReceipt:
        self.records.append((record_jcs, retention))
        return ReleaseEvidenceWriteReceipt(
            controls=self.inspect_active_controls(),
            retention=retention,
        )


@dataclass
class PreparedRuntime:
    corpus: GovernedReleaseEvaluationCorpus
    prepared_calls: list[str]
    candidate_mutation: str | None = None

    embedding_fingerprint = _FINGERPRINT
    runtime_provenance_sha256 = "b" * 64

    def prepare(self, natural_statement: str) -> PreparedDraftRetrieval:
        self.prepared_calls.append(natural_statement)
        query = next(
            query
            for query in self.corpus.queries
            if query.natural_statement == natural_statement
        )
        candidates = tuple(
            DraftCandidate(
                draft=ProofDraft(
                    id=identifier,
                    matched_prompt=identifier,
                    openmath_xml=query.canonical_openmath,
                    proof_strategy="governed",
                    sketch_steps=("governed",),
                ),
                cosine_distance=float(position) / 100,
            )
            for position, identifier in enumerate(
                query.candidate_ids_in_database_order
            )
        )
        result = DraftCandidateResult(
            generation_id=_ADMISSION.generation_id,
            manifest_sha256=_ADMISSION.manifest_sha256,
            seed_count=_ADMISSION.seed_count,
            runtime_provenance_sha256=_ADMISSION.runtime_provenance_sha256,
            fingerprint=_FINGERPRINT,
            candidates=candidates,
        )
        query_openmath = query.canonical_openmath
        if self.candidate_mutation == "generation":
            result = replace(
                result,
                generation_id="22222222-2222-4222-8222-222222222222",
            )
        elif self.candidate_mutation == "order":
            result = replace(result, candidates=tuple(reversed(candidates)))
        elif self.candidate_mutation == "openmath":
            query_openmath += " "
        evidence = tuple(
            DraftEvidence(
                candidate=candidate,
                vector_score=1.0,
                structural_score=1.0,
                exact_equivalence=True,
            )
            for candidate in result.candidates
        )
        return PreparedDraftRetrieval(
            query_openmath=query_openmath,
            candidates=result,
            evidence=evidence,
            reranker_request=DraftRerankerRequest(
                subject_jcs=b"{}",
                body_jcs=b"{}",
                compatibility={"query_id": query.query_id},
            ),
        )

    def finalize(
        self, prepared: PreparedDraftRetrieval, selected_ids: object
    ) -> SimpleNamespace:
        allowed = {
            item.candidate.draft.id
            for item in prepared.evidence
        }
        if (
            not isinstance(selected_ids, tuple)
            or len(selected_ids) > 4
            or len(selected_ids) != len(set(selected_ids))
            or not set(selected_ids) <= allowed
        ):
            raise AssertionError("invalid test reranker selection")
        return SimpleNamespace(outcome="match" if selected_ids else "no_match")


@dataclass
class RecordingReranker:
    selections: dict[str, tuple[str, ...]]
    calls: list[str]
    fail_on_call: int | None = None

    def rerank_response(self, request: DraftRerankerRequest) -> DraftRerankerResponse:
        query_id = cast(str, request.compatibility["query_id"])
        self.calls.append(query_id)
        if self.fail_on_call == len(self.calls):
            raise DraftRerankerUnavailableError("provider detail")
        return DraftRerankerResponse(
            selected_draft_ids=self.selections[query_id],
            usage=_USAGE,
        )


def _evaluator(
    *,
    store: RecordingStore | None = None,
    candidate_mutation: str | None = None,
    selections: dict[str, tuple[str, ...]] | None = None,
    fail_on_call: int | None = None,
) -> tuple[ProofFlowIndexReleaseEvaluator, PreparedRuntime, RecordingReranker, RecordingStore]:
    corpus = load_governed_release_corpus(_CORPUS_PATH)
    runtime = PreparedRuntime(
        corpus=corpus,
        prepared_calls=[],
        candidate_mutation=candidate_mutation,
    )
    reranker = RecordingReranker(
        selections=selections
        or {
            query.query_id: query.expected_selected_draft_ids
            for query in corpus.queries
        },
        calls=[],
        fail_on_call=fail_on_call,
    )
    external_store = store or RecordingStore()
    writer = DraftRerankerReleaseEvidenceWriter(
        corpus=corpus.governed_ids,
        store=cast(ExternalReleaseEvidenceStore, external_store),
    )
    evaluator = ProofFlowIndexReleaseEvaluator(
        runtime=cast(ProofFlowRuntime, runtime),
        reranker=reranker,
        admission=_ADMISSION,
        corpus=corpus,
        evidence_writer=writer,
        monotonic_ns=iter(
            value
            for call in range(6)
            for value in (call * 2_000_000, call * 2_000_000 + 1_000_000)
        ).__next__,
    )
    return evaluator, runtime, reranker, external_store


def test_pfi_ag_007_loads_only_the_exact_approved_corpus(tmp_path: Path) -> None:
    corpus = load_governed_release_corpus(_CORPUS_PATH)

    assert len(corpus.queries) == 6
    assert corpus.oracle_metrics == (
        Fraction(1),
        Fraction(1),
        Fraction(1),
        Fraction(1),
        Fraction(0),
    )

    mutated = tmp_path / "evaluation-corpus.json"
    mutated.write_bytes(_CORPUS_PATH.read_bytes() + b"\n")
    with pytest.raises(ReleaseEvaluationError, match="corpus_invalid"):
        load_governed_release_corpus(mutated)


def test_pfi_ag_007_runs_all_queries_once_and_verifies_external_coverage() -> None:
    evaluator, runtime, reranker, store = _evaluator()

    result = evaluator.evaluate(observed_at="2026-07-27T00:00:00Z")

    assert result.query_count == 6
    assert result.match_count == 5
    assert result.no_match_count == 1
    assert result.metrics == (Fraction(1),) * 4 + (Fraction(0),)
    assert len(runtime.prepared_calls) == 6
    assert len(reranker.calls) == 6
    assert len(store.records) == 6
    for record, retention in store.records:
        payload = json.loads(record)
        assert set(payload) == {
            "schema_version",
            "corpus_query_id",
            "observed_at",
            "model",
            "schema_admitted",
            "outcome",
            "selected_draft_ids",
            "latency_ms",
            "usage",
            "pricing",
            "cost",
        }
        assert payload["latency_ms"] == 1
        assert retention.expires_at == "2027-01-23T00:00:00Z"


def test_pfi_ag_007_blocks_before_paid_call_when_store_controls_are_invalid() -> None:
    evaluator, runtime, reranker, store = _evaluator(
        store=RecordingStore(controls_valid=False)
    )

    with pytest.raises(ReleaseEvaluationError, match="evidence_invalid"):
        evaluator.evaluate(observed_at="2026-07-27T00:00:00Z")

    assert runtime.prepared_calls == []
    assert reranker.calls == []
    assert store.records == []


def test_pfi_ag_007_rejects_invalid_observation_time_before_paid_call() -> None:
    evaluator, runtime, reranker, store = _evaluator()

    with pytest.raises(ReleaseEvaluationError, match="evidence_invalid"):
        evaluator.evaluate(observed_at="2026-07-27T00:00:00+00:00")

    assert runtime.prepared_calls == []
    assert reranker.calls == []
    assert store.records == []


@pytest.mark.parametrize("mutation", ["generation", "order", "openmath"])
def test_pfi_ag_007_blocks_admission_drift_before_paid_call(mutation: str) -> None:
    evaluator, runtime, reranker, store = _evaluator(candidate_mutation=mutation)

    with pytest.raises(ReleaseEvaluationError, match="admission_incompatible"):
        evaluator.evaluate(observed_at="2026-07-27T00:00:00Z")

    assert len(runtime.prepared_calls) == 1
    assert reranker.calls == []
    assert store.records == []


def test_pfi_ag_007_stops_on_unexpected_ids_without_writing_evidence() -> None:
    corpus = load_governed_release_corpus(_CORPUS_PATH)
    selections = {
        query.query_id: query.expected_selected_draft_ids
        for query in corpus.queries
    }
    first = corpus.queries[0]
    selections[first.query_id] = (first.candidate_ids_in_database_order[0],)
    evaluator, _, reranker, store = _evaluator(selections=selections)

    with pytest.raises(ReleaseEvaluationError, match="unexpected_selection"):
        evaluator.evaluate(observed_at="2026-07-27T00:00:00Z")

    assert reranker.calls == [first.query_id]
    assert store.records == []


def test_pfi_ag_007_stops_without_retry_when_provider_is_unavailable() -> None:
    evaluator, _, reranker, store = _evaluator(fail_on_call=2)

    with pytest.raises(ReleaseEvaluationError, match="reranker_unavailable"):
        evaluator.evaluate(observed_at="2026-07-27T00:00:00Z")

    assert len(reranker.calls) == 2
    assert len(store.records) == 1

    next_evaluator, next_runtime, next_reranker, _ = _evaluator(store=store)
    with pytest.raises(ReleaseEvaluationError, match="evidence_invalid"):
        next_evaluator.evaluate(observed_at="2026-07-28T00:00:00Z")
    assert next_runtime.prepared_calls == []
    assert next_reranker.calls == []


def test_pfi_ag_007_rejects_partial_external_corpus_after_all_writes() -> None:
    evaluator, _, reranker, store = _evaluator(
        store=RecordingStore(omit_last_from_coverage=True)
    )

    with pytest.raises(ReleaseEvaluationError, match="evidence_invalid"):
        evaluator.evaluate(observed_at="2026-07-27T00:00:00Z")

    assert len(reranker.calls) == 6
    assert len(store.records) == 6
