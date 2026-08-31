"""Fail-closed release evaluation for the governed Proof Flow Index corpus."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from uuid import UUID

from pals_agent.private_draft_candidates import (
    DraftCandidateResult,
    DraftEmbeddingFingerprint,
    validate_draft_embedding_fingerprint,
)
from pals_agent.proof_flow_release_evidence import (
    DraftRerankerReleaseEvidenceWriter,
    GovernedReleaseCorpus,
    ReleaseEvidenceError,
)
from pals_agent.proof_flow_reranker import (
    DraftRerankerInvalidError,
    DraftRerankerRequest,
    DraftRerankerResponse,
    DraftRerankerUnavailableError,
)
from pals_agent.proof_flow_runtime import (
    PreparedDraftRetrieval,
    ProofFlowRetrievalError,
    ProofFlowRuntime,
)

_CORPUS_SHA256 = "9f3cbf318ae5d6ba3accc635a65bb9df67ccf5f503f2fec6a6c22a6a93613e54"
_CATALOG_SHA256 = "2d09c217ecf6a65dc6563630f8e27cb824f3c7986a24a0d193102345d150b515"
_CANONICALIZER_VERSION = "openmath-cdbase-alpha-c14n-v4"
_RERANKER_IDENTITY = {
    "role": "draft",
    "provider": "openai",
    "model": "gpt-5.4-mini-2026-03-17",
    "provider_api": "openai.responses.v1",
    "contract_version": "pals.draft-relevance-reranker.v1",
    "prompt_sha256": "ee3210814e58edab5fa2a5878100b310d7811df23e3c5f2d09d93d8f3cc03d00",
    "real_execution_observed": False,
    "response_schema": {
        "selected_draft_ids": (
            "ordered unique array of zero through four supplied candidate IDs"
        )
    },
}
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "canonicalizer_version",
        "catalog_source",
        "candidate_profile_gate",
        "reranker",
        "metric_contract",
        "oracle_aggregate",
        "queries",
        "evidence_kind",
    }
)
_QUERY_KEYS = frozenset(
    {
        "query_id",
        "language",
        "natural_statement",
        "canonical_openmath",
        "candidate_ids_in_database_order",
        "relevant_draft_ids",
        "expected_selected_draft_ids",
        "expected_outcome",
        "hard_negative_ids",
        "false_positive_ids",
        "adjudication",
    }
)
_SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,255}$")
_MANIFEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ERROR_CODES = frozenset(
    {
        "corpus_invalid",
        "admission_incompatible",
        "runtime_incompatible",
        "reranker_unavailable",
        "reranker_invalid",
        "unexpected_selection",
        "metric_mismatch",
        "evidence_invalid",
    }
)


class ReleaseEvaluationError(RuntimeError):
    """One content-free release failure code."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("Release evaluation error code is not registered.")
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PFIReleaseAdmissionWitness:
    """The immutable API publication/admission tuple required before a paid call."""

    generation_id: str
    manifest_sha256: str
    seed_count: int
    runtime_provenance_sha256: str
    fingerprint: DraftEmbeddingFingerprint

    def __post_init__(self) -> None:
        try:
            generation = UUID(self.generation_id)
        except (AttributeError, TypeError, ValueError):
            raise ValueError("PFI release generation ID is invalid.") from None
        if (
            generation.version != 4
            or str(generation) != self.generation_id
            or not _MANIFEST.fullmatch(self.manifest_sha256)
            or type(self.seed_count) is not int
            or not 8 <= self.seed_count <= 4096
            or not _SHA256.fullmatch(self.runtime_provenance_sha256)
        ):
            raise ValueError("PFI release admission witness is invalid.")
        validate_draft_embedding_fingerprint(self.fingerprint)


@dataclass(frozen=True, slots=True)
class GovernedReleaseQuery:
    query_id: str
    language: Literal["en", "ja"]
    natural_statement: str
    canonical_openmath: str
    candidate_ids_in_database_order: tuple[str, ...]
    relevant_draft_ids: frozenset[str]
    expected_selected_draft_ids: tuple[str, ...]
    expected_outcome: Literal["match", "no_match"]


@dataclass(frozen=True, slots=True)
class GovernedReleaseEvaluationCorpus:
    queries: tuple[GovernedReleaseQuery, ...]
    oracle_metrics: tuple[Fraction, Fraction, Fraction, Fraction, Fraction]

    @property
    def governed_ids(self) -> GovernedReleaseCorpus:
        return GovernedReleaseCorpus(
            query_ids=frozenset(query.query_id for query in self.queries),
            draft_ids=frozenset(
                identifier
                for query in self.queries
                for identifier in query.candidate_ids_in_database_order
            ),
        )


@dataclass(frozen=True, slots=True)
class ReleaseEvaluationResult:
    """Content-free aggregate result; query text and provider envelopes are never retained."""

    query_count: int
    match_count: int
    no_match_count: int
    metrics: tuple[Fraction, Fraction, Fraction, Fraction, Fraction]


class ReleaseReranker(Protocol):
    def rerank_response(self, request: DraftRerankerRequest) -> DraftRerankerResponse: ...


@dataclass(frozen=True, slots=True)
class ProofFlowIndexReleaseEvaluator:
    runtime: ProofFlowRuntime
    reranker: ReleaseReranker
    admission: PFIReleaseAdmissionWitness
    corpus: GovernedReleaseEvaluationCorpus
    evidence_writer: DraftRerankerReleaseEvidenceWriter
    monotonic_ns: Callable[[], int] = field(default=time.monotonic_ns, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.evidence_writer.corpus != self.corpus.governed_ids:
            raise ValueError("Release evaluator and evidence corpus do not match.")
        if self.runtime.embedding_fingerprint != self.admission.fingerprint:
            raise ValueError("Release evaluator fingerprint is not admitted.")
        if (
            self.runtime.runtime_provenance_sha256
            != self.admission.runtime_provenance_sha256
        ):
            raise ValueError("Release evaluator provenance is not admitted.")

    def evaluate(self, *, observed_at: str) -> ReleaseEvaluationResult:
        try:
            self.evidence_writer.preflight(observed_at=observed_at)
        except ReleaseEvidenceError:
            raise ReleaseEvaluationError("evidence_invalid") from None

        observed: list[tuple[GovernedReleaseQuery, tuple[str, ...]]] = []
        for query in self.corpus.queries:
            prepared = self._prepare_query(query)
            started_ns = self.monotonic_ns()
            try:
                response = self.reranker.rerank_response(prepared.reranker_request)
            except DraftRerankerUnavailableError:
                raise ReleaseEvaluationError("reranker_unavailable") from None
            except DraftRerankerInvalidError:
                raise ReleaseEvaluationError("reranker_invalid") from None
            finished_ns = self.monotonic_ns()
            if (
                type(started_ns) is not int
                or type(finished_ns) is not int
                or finished_ns < started_ns
            ):
                raise ReleaseEvaluationError("evidence_invalid")
            latency_ms = (finished_ns - started_ns) // 1_000_000
            selected_ids = response.selected_draft_ids
            try:
                result = self.runtime.finalize(prepared, selected_ids)
            except ProofFlowRetrievalError:
                raise ReleaseEvaluationError("reranker_invalid") from None
            if (
                selected_ids != query.expected_selected_draft_ids
                or result.outcome != query.expected_outcome
            ):
                raise ReleaseEvaluationError("unexpected_selection")
            try:
                self.evidence_writer.write(
                    corpus_query_id=query.query_id,
                    observed_at=observed_at,
                    selected_draft_ids=selected_ids,
                    latency_ms=latency_ms,
                    usage=response.usage,
                )
            except ReleaseEvidenceError:
                raise ReleaseEvaluationError("evidence_invalid") from None
            observed.append((query, selected_ids))

        metrics = _metrics(observed)
        if metrics != self.corpus.oracle_metrics:
            raise ReleaseEvaluationError("metric_mismatch")
        try:
            self.evidence_writer.verify_complete_run(observed_at=observed_at)
        except ReleaseEvidenceError:
            raise ReleaseEvaluationError("evidence_invalid") from None
        return ReleaseEvaluationResult(
            query_count=len(observed),
            match_count=sum(query.expected_outcome == "match" for query, _ in observed),
            no_match_count=sum(query.expected_outcome == "no_match" for query, _ in observed),
            metrics=metrics,
        )

    def _prepare_query(self, query: GovernedReleaseQuery) -> PreparedDraftRetrieval:
        try:
            prepared = self.runtime.prepare(query.natural_statement)
        except ProofFlowRetrievalError:
            raise ReleaseEvaluationError("runtime_incompatible") from None
        candidates = prepared.candidates
        if (
            prepared.query_openmath != query.canonical_openmath
            or _candidate_ids(candidates) != query.candidate_ids_in_database_order
            or not _matches_admission(candidates, self.admission)
        ):
            raise ReleaseEvaluationError("admission_incompatible")
        return prepared


def load_governed_release_corpus(path: Path) -> GovernedReleaseEvaluationCorpus:
    """Load only the byte-exact approved corpus and validate its executable invariants."""
    try:
        payload = path.read_bytes()
    except OSError:
        raise ReleaseEvaluationError("corpus_invalid") from None
    if hashlib.sha256(payload).hexdigest() != _CORPUS_SHA256:
        raise ReleaseEvaluationError("corpus_invalid")
    try:
        root = json.loads(payload, object_pairs_hook=_unique_object)
        if not isinstance(root, dict) or frozenset(root) != _TOP_LEVEL_KEYS:
            raise ValueError
        if (
            root["schema_version"] != "pals.pfi-evaluation-corpus.v1"
            or root["canonicalizer_version"] != _CANONICALIZER_VERSION
            or root["evidence_kind"]
            != "spec_owned_deterministic_oracle_not_observed_runtime_output"
            or root["reranker"] != _RERANKER_IDENTITY
        ):
            raise ValueError
        catalog_source = _exact_object(
            root["catalog_source"],
            {"path", "sha256", "observed_row_count", "production_catalog_claim"},
        )
        if catalog_source != {
            "path": "pals-agent/pals_agent/seed/dsp_drafts.json",
            "sha256": _CATALOG_SHA256,
            "observed_row_count": 31,
            "production_catalog_claim": False,
        }:
            raise ValueError
        queries = _queries(root["queries"])
        metrics = _oracle_metrics(root["oracle_aggregate"])
        metric_contract = _exact_object(
            root["metric_contract"],
            {
                "positive_query_denominator",
                "no_match_query_denominator",
                "hit_at_1",
                "recall_at_4",
                "mrr",
                "no_match_specificity",
                "false_positive_rate",
            },
        )
        if (
            metric_contract["positive_query_denominator"] != 5
            or metric_contract["no_match_query_denominator"] != 1
            or _metrics(
                [(query, query.expected_selected_draft_ids) for query in queries]
            )
            != metrics
        ):
            raise ValueError
        profile_gate = _exact_object(
            root["candidate_profile_gate"],
            {
                "profile",
                "all_candidates_profile_valid_and_closed",
                "snapshot_incompatible_draft_ids",
            },
        )
        incompatible = _string_tuple(profile_gate["snapshot_incompatible_draft_ids"])
        if (
            profile_gate["profile"] != "pals.pfi-four-sort-closed-retrieval.v1"
            or profile_gate["all_candidates_profile_valid_and_closed"] is not True
            or len(incompatible) != 9
            or len(incompatible) != len(set(incompatible))
            or any(
                identifier in incompatible
                for query in queries
                for identifier in query.candidate_ids_in_database_order
            )
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, UnicodeDecodeError):
        raise ReleaseEvaluationError("corpus_invalid") from None
    return GovernedReleaseEvaluationCorpus(queries=queries, oracle_metrics=metrics)


def _queries(value: object) -> tuple[GovernedReleaseQuery, ...]:
    if not isinstance(value, list) or len(value) != 6:
        raise ValueError
    queries: list[GovernedReleaseQuery] = []
    for raw_query in value:
        query = _exact_object(raw_query, _QUERY_KEYS)
        query_id = _safe_id(query["query_id"])
        language = query["language"]
        natural_statement = query["natural_statement"]
        canonical_openmath = query["canonical_openmath"]
        candidates = _string_tuple(query["candidate_ids_in_database_order"])
        relevant = frozenset(_string_tuple(query["relevant_draft_ids"]))
        selected = _string_tuple(query["expected_selected_draft_ids"])
        outcome = query["expected_outcome"]
        hard_negatives = _string_tuple(query["hard_negative_ids"])
        false_positives = _string_tuple(query["false_positive_ids"])
        if (
            language not in {"en", "ja"}
            or not isinstance(natural_statement, str)
            or not natural_statement
            or len(natural_statement.encode("utf-8")) > 16_384
            or not isinstance(canonical_openmath, str)
            or not canonical_openmath
            or len(candidates) != 8
            or len(candidates) != len(set(candidates))
            or not relevant <= frozenset(candidates)
            or len(selected) > 4
            or len(selected) != len(set(selected))
            or not set(selected) <= set(candidates)
            or outcome not in {"match", "no_match"}
            or (outcome == "match") != bool(selected)
            or (outcome == "match") != bool(relevant)
            or not set(hard_negatives) <= set(candidates)
            or not set(false_positives) <= set(candidates)
            or not isinstance(query["adjudication"], str)
            or not query["adjudication"]
        ):
            raise ValueError
        queries.append(
            GovernedReleaseQuery(
                query_id=query_id,
                language=cast(Literal["en", "ja"], language),
                natural_statement=natural_statement,
                canonical_openmath=canonical_openmath,
                candidate_ids_in_database_order=candidates,
                relevant_draft_ids=relevant,
                expected_selected_draft_ids=selected,
                expected_outcome=cast(Literal["match", "no_match"], outcome),
            )
        )
    if (
        len({query.query_id for query in queries}) != 6
        or sum(query.expected_outcome == "match" for query in queries) != 5
        or sum(query.expected_outcome == "no_match" for query in queries) != 1
    ):
        raise ValueError
    return tuple(queries)


def _oracle_metrics(
    value: object,
) -> tuple[Fraction, Fraction, Fraction, Fraction, Fraction]:
    root = _exact_object(
        value,
        {
            "hit_at_1",
            "recall_at_4",
            "mrr",
            "no_match_specificity",
            "false_positive_rate",
        },
    )
    raw = (
        root["hit_at_1"],
        root["recall_at_4"],
        root["mrr"],
        root["no_match_specificity"],
        root["false_positive_rate"],
    )
    if any(type(item) not in {int, float} for item in raw):
        raise ValueError
    return tuple(Fraction(str(item)) for item in raw)  # type: ignore[return-value]


def _metrics(
    observed: list[tuple[GovernedReleaseQuery, tuple[str, ...]]],
) -> tuple[Fraction, Fraction, Fraction, Fraction, Fraction]:
    positive = [
        (query, selected)
        for query, selected in observed
        if query.expected_outcome == "match"
    ]
    negative = [
        (query, selected)
        for query, selected in observed
        if query.expected_outcome == "no_match"
    ]
    if not positive or not negative:
        raise ValueError
    hit_at_1 = Fraction(
        sum(
            bool(selected) and selected[0] in query.relevant_draft_ids
            for query, selected in positive
        ),
        len(positive),
    )
    recall_at_4 = sum(
        (
            Fraction(
                len(set(selected) & query.relevant_draft_ids),
                len(query.relevant_draft_ids),
            )
            for query, selected in positive
        ),
        start=Fraction(0),
    ) / len(positive)
    mrr = sum(
        (
            next(
                (
                    Fraction(1, rank)
                    for rank, identifier in enumerate(selected, start=1)
                    if identifier in query.relevant_draft_ids
                ),
                Fraction(0),
            )
            for query, selected in positive
        ),
        start=Fraction(0),
    ) / len(positive)
    specificity = Fraction(sum(not selected for _, selected in negative), len(negative))
    selected_pairs = [
        (query, identifier)
        for query, selected in observed
        for identifier in selected
    ]
    false_positive_rate = (
        Fraction(
            sum(
                identifier not in query.relevant_draft_ids
                for query, identifier in selected_pairs
            ),
            len(selected_pairs),
        )
        if selected_pairs
        else Fraction(0)
    )
    return hit_at_1, recall_at_4, mrr, specificity, false_positive_rate


def _matches_admission(
    result: DraftCandidateResult,
    admission: PFIReleaseAdmissionWitness,
) -> bool:
    return (
        result.generation_id == admission.generation_id
        and result.manifest_sha256 == admission.manifest_sha256
        and result.seed_count == admission.seed_count
        and result.seed_count >= 8
        and result.runtime_provenance_sha256 == admission.runtime_provenance_sha256
        and result.fingerprint == admission.fingerprint
        and len(result.candidates) == 8
    )


def _candidate_ids(result: DraftCandidateResult) -> tuple[str, ...]:
    return tuple(candidate.draft.id for candidate in result.candidates)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _exact_object(value: object, keys: set[str] | frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or frozenset(value) != frozenset(keys):
        raise ValueError
    return cast(dict[str, Any], value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError
    values = tuple(value)
    if any(not _SAFE_ID.fullmatch(item) for item in values):
        raise ValueError
    return values


def _safe_id(value: object) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError
    return value
