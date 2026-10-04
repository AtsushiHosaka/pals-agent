"""Authenticated read-only candidates for LLM-assessed natural proofs.

This is deliberately a separate contract from published PFI and typed catalogs.
Rows are unverified sketches with content identity, not proof certificates.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

import rfc8785

from pals_agent.http_transport import (
    HardDeadlineHttpError,
    HardDeadlineHttpTransport,
    HttpTransport,
)
from pals_agent.models import ProofDraft
from pals_agent.natural_draft_evidence import NaturalDraftContext, NaturalDraftRetrievalResult
from pals_agent.openmath import canonicalize_openmath_xml, validate_canonical_retrieval_openmath_xml
from pals_agent.private_draft_candidates import DraftCandidate, _validate_api_base_url
from pals_agent.proof_reuse import ProofReuseError

EMBEDDING_BINDING: dict[str, str | int] = {
    "provider": "openai",
    "model": "text-embedding-3-small",
    "dimension": 384,
    "endpoint": "https://api.openai.com/v1",
    "deployment": "text-embedding-3-small",
    "revision": "openai-release-2024-01-25",
    "canonicalizer_version": "openmath-cdbase-alpha-c14n-v2",
}
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_PAYLOAD_FIELDS = {"id", "canonical_statement", "openmath_xml", "proof_strategy", "sketch_steps"}


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate member")
        result[key] = value
    return result


def _text(value: object, limit: int = 20000) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


@dataclass(frozen=True, slots=True)
class NaturalDraftCandidateClient:
    base_url: str
    worker_secret: str = field(repr=False)
    transport: HttpTransport = field(
        default_factory=lambda: HardDeadlineHttpTransport(max_response_bytes=262144),
        repr=False,
    )

    def __post_init__(self) -> None:
        _validate_api_base_url(self.base_url)
        if not self.worker_secret.strip() or any(c in self.worker_secret for c in "\r\n"):
            raise ValueError("Natural draft worker credential invalid")

    def retrieve(self, query: str, embedding: list[float]) -> NaturalDraftRetrievalResult:
        try:
            if len(query.encode()) > 65536 or canonicalize_openmath_xml(query) != query:
                raise ValueError("Query is not bounded canonical v2 search data")
            if (
                len(embedding) != 384
                or not any(embedding)
                or any(
                    type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e6
                    for value in embedding
                )
            ):
                raise ValueError("embedding invalid")
            response = self.transport.request(
                method="POST",
                url=self.base_url.rstrip("/") + "/v1/internal/proof-requests/draft-candidates",
                headers={
                    "X-PALS-Worker-Secret": self.worker_secret,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                body=rfc8785.dumps(
                    {"embedding": embedding, "embedding_binding": EMBEDDING_BINDING, "limit": 8}
                ),
                timeout_seconds=10.0,
            )
            if response.status_code != 200:
                raise ProofReuseError(
                    "proof_reuse_catalog_unavailable",
                    details={
                        "failure_code": "natural_catalog_http",
                        "status": str(response.status_code),
                    },
                )
            if len(response.body) > 262144:
                raise ValueError("catalog response too large")
            payload = json.loads(response.body, object_pairs_hook=_object)
            expected = {
                "schema_version",
                "evidence_kind",
                "catalog_revision_sha256",
                "actual_row_count",
                "embedding_binding",
                "candidates",
            }
            if not isinstance(payload, dict) or set(payload) != expected:
                raise ValueError("catalog response shape invalid")
            if (
                payload["schema_version"] != "pals.proof-request-draft-candidates.v1"
                or payload["evidence_kind"] != "unverified_sketches"
                or payload["embedding_binding"] != EMBEDDING_BINDING
                or type(payload["actual_row_count"]) is not int
                or not 1 <= payload["actual_row_count"] <= 4096
                or not isinstance(payload["catalog_revision_sha256"], str)
                or not _HEX64.fullmatch(payload["catalog_revision_sha256"])
            ):
                raise ValueError("catalog identity invalid")
            rows = payload["candidates"]
            if (
                not isinstance(rows, list)
                or len(rows) > 8
                or len(rows) > payload["actual_row_count"]
            ):
                raise ValueError("catalog candidate count invalid")
            candidates: list[DraftCandidate] = []
            revisions: dict[str, str] = {}
            for row in rows:
                if not isinstance(row, dict) or set(row) != _PAYLOAD_FIELDS | {
                    "payload_sha256",
                    "distance",
                }:
                    raise ValueError("catalog row shape invalid")
                if any(not _text(row[key]) for key in _PAYLOAD_FIELDS - {"sketch_steps"}):
                    raise ValueError("catalog text invalid")
                if not _ID.fullmatch(row["id"]) or row["id"] in revisions:
                    raise ValueError("catalog candidate identity invalid")
                steps = row["sketch_steps"]
                distance = row["distance"]
                if (
                    not isinstance(steps, list)
                    or len(steps) > 256
                    or any(not _text(step) for step in steps)
                    or type(distance) not in (int, float)
                    or not math.isfinite(distance)
                    or not -0.00001 <= distance <= 2.00001
                ):
                    raise ValueError("catalog row content invalid")
                exact_payload = {key: row[key] for key in _PAYLOAD_FIELDS}
                canonical_bytes = rfc8785.dumps(exact_payload)
                if len(canonical_bytes) > 65536:
                    raise ValueError("catalog source payload too large")
                digest = hashlib.sha256(canonical_bytes).hexdigest()
                if row["payload_sha256"] != digest:
                    raise ValueError("catalog source digest differs")
                validate_canonical_retrieval_openmath_xml(row["openmath_xml"])
                revisions[row["id"]] = digest
                candidates.append(
                    DraftCandidate(
                        ProofDraft(
                            row["id"],
                            row["canonical_statement"],
                            row["openmath_xml"],
                            row["proof_strategy"],
                            tuple(steps),
                        ),
                        float(distance),
                    )
                )
            evidence = tuple(NaturalDraftContext(candidate) for candidate in candidates)
            return NaturalDraftRetrievalResult(
                "match" if evidence else "no_match",
                query,
                evidence,
                {
                    "catalog_contract": "pals.proof-request-draft-candidates.v1",
                    "evidence_kind": "unverified_sketches",
                    "catalog_revision_sha256": payload["catalog_revision_sha256"],
                    "actual_row_count": payload["actual_row_count"],
                    "source_revisions_json": json.dumps(revisions, sort_keys=True),
                },
            )
        except ProofReuseError:
            raise
        except (HardDeadlineHttpError, ValueError, TypeError, KeyError, RecursionError) as error:
            raise ProofReuseError("proof_reuse_catalog_invalid") from error
