from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import quote

import rfc8785

from pals_agent.http_transport import (
    HardDeadlineHttpError,
    HardDeadlineHttpTransport,
    HttpTransport,
)
from pals_agent.models import Diagnostic, ProofJobState

_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$", re.ASCII)
_VERIFICATION_CANDIDATE_SCHEMA_VERSION = "pals.proof-verification-candidate.v1"
_RECIPE_VERIFICATION_CANDIDATE_SCHEMA_VERSION = "pals.proof-verification-candidate.v2"
_SEMANTIC_REVIEW_SCHEMA_VERSION = "pals.proof-semantic-review.v2"
_RECIPE_SEMANTIC_REVIEW_SCHEMA_VERSION = "pals.proof-semantic-review.v3"
_OUTPUT_REVIEW_SCHEMA_VERSION = "pals.proof-output-review.v2"
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_MODEL_ARTIFACT_URI_RE = re.compile(
    r"^s3://[A-Za-z0-9][A-Za-z0-9.-]{0,254}/proof-jobs/"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}/result\.lean$",
    re.ASCII,
)

# Only fixed schema identifiers can enter operational validation diagnostics.
# Unknown dictionary keys may contain user/model text, so they are redacted.
_VALIDATION_LOCATION_FIELDS = frozenset({
    "body", "query", "path", "header", "response", "claim_id", "expected_revision",
    "outcome", "question", "answer", "text", "options", "evidence_kind", "sources",
    "draft_id", "revision", "statement", "error_code", "private_evidence", "usage",
    "call_id", "model_role", "provider", "model", "input_tokens", "output_tokens",
    "cached_input_tokens", "reasoning_tokens", "price_snapshot_id", "provider_request_id",
    "worker_elapsed_ms", "token_qa", "approved", "answer_sha256", "instantiation",
})
_VALIDATION_ERROR_TYPES = frozenset({
    "missing", "extra_forbidden", "value_error", "assertion_error", "literal_error",
    "string_type", "string_too_short", "string_too_long", "string_pattern_mismatch",
    "string_unicode", "int_type", "int_parsing", "int_from_float", "bool_type",
    "bool_parsing", "float_type", "float_parsing", "finite_number", "greater_than",
    "greater_than_equal", "less_than", "less_than_equal", "multiple_of", "list_type",
    "dict_type", "tuple_type", "set_type", "too_long", "too_short", "none_required",
    "uuid_type", "uuid_parsing", "uuid_version", "json_invalid", "json_type",
    "union_tag_invalid", "union_tag_not_found", "model_type", "model_attributes_type",
})


def _sanitize_validation_errors(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    errors: list[tuple[str, str]] = []
    for entry in value[:8]:
        if not isinstance(entry, dict):
            continue
        location = entry.get("loc")
        if not isinstance(location, (list, tuple)) or not location:
            continue
        parts = []
        for part in location[:12]:
            if isinstance(part, str) and part in _VALIDATION_LOCATION_FIELDS:
                parts.append(part)
            elif type(part) is int and 0 <= part <= 999:
                parts.append(str(part))
            else:
                parts.append("_redacted")
        if len(location) > 12:
            parts.append("_truncated")
        error_type = entry.get("type")
        kind = (error_type if isinstance(error_type, str) and
                error_type in _VALIDATION_ERROR_TYPES else "_redacted")
        errors.append((".".join(parts), kind))
    return tuple(errors)


def _extract_api_validation_errors(body: str) -> object:
    if len(body) > 65536 or len(body.encode("utf-8")) > 65536:
        return None
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, RecursionError):
        return None
    return payload.get("detail") if isinstance(payload, dict) else None


# Kept only for test-double compatibility while the public worker transport no longer accepts it.
type VerifierAttestation = dict[str, Any]


class PalsApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        validation_errors: object = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.validation_errors = _sanitize_validation_errors(validation_errors)


class ProofJobNotFoundError(PalsApiError):
    pass


@dataclass(frozen=True, slots=True)
class PalsApiClient:
    base_url: str
    worker_secret: str
    timeout_seconds: float = 15.0
    transport: HttpTransport = field(
        default_factory=HardDeadlineHttpTransport,
        repr=False,
        compare=False,
    )

    def permit_token_call(self, payload: dict[str, Any], *, timeout_seconds: float) -> None:
        result = self._request(
            "POST", "/v1/internal/billing/token-permits", payload,
            headers={"X-PALS-Worker-Secret": self.worker_secret},
            timeout_seconds=timeout_seconds,
        )
        if set(result) != {"permitted"} or result["permitted"] is not True:
            raise PalsApiError("Token permit was malformed")

    def record_token_receipt(self, payload: dict[str, Any], *, timeout_seconds: float) -> None:
        result = self._request(
            "POST", "/v1/internal/billing/token-receipts", payload,
            headers={"X-PALS-Worker-Secret": self.worker_secret},
            timeout_seconds=timeout_seconds,
        )
        if set(result) != {"recorded"} or result["recorded"] is not True:
            raise PalsApiError("Token receipt was malformed")

    def acquire_proof_request_claim(
        self, *, request_id: str, claim_id: str, lease_ms: int = 240000
    ) -> dict[str, Any]:
        if lease_ms != 240000:
            raise ValueError("proof request lease must be 240000ms")
        return self._request(
            "POST", f"/v1/internal/proof-requests/{_canonical_claim_id(request_id)}/claims",
            {"claim_id": _canonical_claim_id(claim_id), "lease_ms": lease_ms},
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def get_proof_request_materials(
        self, *, request_id: str, claim_id: str
    ) -> dict[str, Any]:
        return self._request(
            "POST", f"/v1/internal/proof-requests/{_canonical_claim_id(request_id)}/materials",
            {"claim_id": _canonical_claim_id(claim_id)},
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def settle_proof_request(
        self, *, request_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "POST", f"/v1/internal/proof-requests/{_canonical_claim_id(request_id)}/settlements",
            payload, headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def record_proof_request_usage(
        self, *, request_id: str, claim_id: str, usage: dict[str, Any]
    ) -> None:
        result = self._request(
            "POST", f"/v1/internal/proof-requests/{_canonical_claim_id(request_id)}/usage",
            {"claim_id": _canonical_claim_id(claim_id), "usage": usage},
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )
        if result != {"recorded": True}:
            raise PalsApiError("Proof request usage receipt was malformed")

    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        resource_id = _path_segment(proof_job_id)
        return self._request(
            "GET",
            f"/v1/internal/proof-jobs/{resource_id}/worker-input",
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def record_usage(self, *, proof_job_id: str, claim_id: str, usage: dict[str, Any]) -> None:
        payload = dict(usage, generation_claim_id=_canonical_claim_id(claim_id))
        result = self._request(
            "POST", f"/v1/internal/proof-jobs/{_path_segment(proof_job_id)}/usage",
            payload, headers={"X-PALS-Worker-Secret": self.worker_secret},
        )
        if result != {"recorded": True}:
            raise PalsApiError("Usage receipt was malformed")

    def acquire_proof_generation_claim(
        self,
        *,
        proof_job_id: str,
        claim_id: str,
        required_lease_ms: int = 3_600_000,
    ) -> dict[str, Any]:
        resource_id = _path_segment(proof_job_id)
        if required_lease_ms != 3_600_000:
            raise ValueError("required_lease_ms must equal 3600000")
        return self._request(
            "POST",
            f"/v1/internal/proof-jobs/{resource_id}/generation-claims",
            {
                "claim_id": _canonical_claim_id(claim_id),
                "required_lease_ms": required_lease_ms,
            },
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def update_proof_job(
        self,
        *,
        proof_job_id: str,
        claim_id: str,
        state: ProofJobState,
        diagnostics: list[Diagnostic],
        result_artifact_uri: str | None,
        lean_code: str | None,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if state == "verified":
            raise ValueError(
                "workers must submit a verification candidate; they cannot update verified proofs"
            )
        resource_id = _path_segment(proof_job_id)
        payload: dict[str, Any] = {
            "state": state,
            "claim_id": _canonical_claim_id(claim_id),
            "diagnostics": [_diagnostic_payload(diagnostic) for diagnostic in diagnostics],
            "result_artifact_uri": result_artifact_uri,
            "lean_code": lean_code,
            "context": context,
        }
        return self._request(
            "POST",
            f"/v1/internal/proof-jobs/{resource_id}/worker-updates",
            payload,
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def submit_verification_candidate(
        self,
        *,
        proof_job_id: str,
        claim_id: str,
        candidate_id: str,
        lean_code: str,
        result_artifact_uri: str,
    ) -> dict[str, Any]:
        """Submit stored Lean for API-owned verifier reconciliation.

        The worker deliberately cannot attach an attestation or terminal state.  The API locks the
        candidate against its already-persisted provenance, then its isolated reconciler is the
        only component that can promote the proof to ``verified``.
        """
        resource_id = _path_segment(proof_job_id)
        canonical_candidate_id = _canonical_claim_id(candidate_id)
        if not isinstance(lean_code, str) or not lean_code.strip() or len(lean_code) > 200_000:
            raise ValueError("verification candidates require bounded nonblank Lean code")
        if not isinstance(result_artifact_uri, str):
            raise ValueError("verification candidates require a canonical Lean artifact URI")
        lean_sha256 = hashlib.sha256(lean_code.encode("utf-8")).hexdigest()
        if _MODEL_ARTIFACT_URI_RE.fullmatch(result_artifact_uri) is None:
            raise ValueError("verification candidates require a canonical Lean artifact URI")
        return self._request(
            "POST",
            f"/v1/internal/proof-jobs/{resource_id}/verification-candidates",
            {
                "schema_version": _VERIFICATION_CANDIDATE_SCHEMA_VERSION,
                "candidate_id": canonical_candidate_id,
                "claim_id": _canonical_claim_id(claim_id),
                "lean_code": lean_code,
                "lean_sha256": lean_sha256,
                "result_artifact_uri": result_artifact_uri,
            },
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def record_no_recipe_attempt(
        self, *, proof_job_id: str, mutation_claim_id: str, request_sha256: str
    ) -> dict[str, Any]:
        if (not isinstance(request_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", request_sha256) is None):
            raise ValueError("Recipe decision digest is invalid")
        response = self._request(
            "POST",
            f"/v1/internal/proof-jobs/{_path_segment(proof_job_id)}/recipe-selection-traces",
            {"schema_version": "pals.recipe-attempt-trace-request.v1",
             "mutation_claim_id": _canonical_claim_id(mutation_claim_id),
             "request_sha256": request_sha256},
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )
        if (
            set(response) != {"schema_version", "status"}
            or response.get("schema_version") != "pals.recipe-attempt-trace-response.v1"
            or response.get("status") not in {"linked", "already_linked"}
        ):
            raise ValueError("Recipe decision acknowledgement is invalid")
        return response

    def submit_recipe_verification_candidate(
        self,
        *,
        proof_job_id: str,
        mutation_claim_id: str,
        candidate_id: str,
        lean_code: str,
        result_artifact_uri: str,
        candidate_source: dict[str, Any],
    ) -> dict[str, Any]:
        """Submit exactly the selected Recipe bytes and its sealed v2 binding.

        Unlike the historic candidate method this accepts neither model provenance nor a repair
        route.  The API is still the authority for receipt/lifecycle admission and verifier
        settlement; this method only carries authenticated selection fields across that boundary.
        """

        resource_id = _path_segment(proof_job_id)
        canonical_candidate_id = _canonical_claim_id(candidate_id)
        canonical_mutation_claim_id = _canonical_claim_id(mutation_claim_id)
        if not isinstance(lean_code, str) or not lean_code.strip() or len(lean_code) > 200_000:
            raise ValueError("Recipe candidates require bounded nonblank Lean code")
        if not isinstance(result_artifact_uri, str) or not _recipe_artifact_uri_is_exact(
            result_artifact_uri=result_artifact_uri,
            proof_job_id=proof_job_id,
            candidate_id=canonical_candidate_id,
            lean_sha256=hashlib.sha256(lean_code.encode("utf-8")).hexdigest(),
        ):
            raise ValueError(
                "Recipe candidate URI must bind the exact job, candidate, and Lean bytes"
            )
        _validate_recipe_candidate_source(candidate_source, lean_code=lean_code)
        return self._request(
            "POST",
            f"/v1/internal/proof-jobs/{resource_id}/recipe-verification-candidates",
            {
                "schema_version": _RECIPE_VERIFICATION_CANDIDATE_SCHEMA_VERSION,
                "candidate_id": canonical_candidate_id,
                "mutation_claim_id": canonical_mutation_claim_id,
                "lean_code": lean_code,
                "lean_sha256": hashlib.sha256(lean_code.encode("utf-8")).hexdigest(),
                "result_artifact_uri": result_artifact_uri,
                "candidate_source": candidate_source,
            },
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def get_verification_candidate_binding(
        self, *, proof_job_id: str, candidate_id: str,
    ) -> dict[str, Any]:
        resource_id = _path_segment(proof_job_id)
        candidate = _canonical_claim_id(candidate_id)
        return self._request(
            "GET",
            f"/v1/internal/proof-jobs/{resource_id}/verification-candidates/{candidate}/binding",
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def retry_verification_candidate_reconciliation(
        self,
        *,
        proof_job_id: str,
        candidate_id: str,
    ) -> dict[str, Any]:
        """Re-notify the reconciler for an already-durable candidate after redelivery."""
        resource_id = _path_segment(proof_job_id)
        canonical_candidate_id = _canonical_claim_id(candidate_id)
        return self._request(
            "POST",
            "/v1/internal/proof-jobs/"
            f"{resource_id}/verification-candidates/{canonical_candidate_id}/reconciliation",
            {},
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def settle_proof_semantic_review(
        self,
        *,
        proof_job_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        resource_id = _path_segment(proof_job_id)
        _validate_semantic_review_evidence(evidence)
        return self._request(
            "POST",
            f"/v1/internal/proof-jobs/{resource_id}/semantic-reviews",
            evidence,
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def settle_proof_semantic_review_unavailable(
        self, *, proof_job_id: str, failure: dict[str, Any],
    ) -> dict[str, Any]:
        if failure.get("source_binding_sha256") is not None:
            raise PalsApiError("Recipe review requires the dedicated reviewer actor")
        return self._request(
            "POST",
            f"/v1/internal/proof-jobs/{_path_segment(proof_job_id)}/semantic-review-unavailable",
            failure, headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def settle_recipe_semantic_review(
        self, *, proof_job_id: str, evidence: dict[str, Any],
    ) -> dict[str, Any]:
        raise PalsApiError("Recipe review requires the dedicated reviewer actor")

    def upsert_proof_explanation(
        self,
        *,
        proof_job_id: str,
        state: str,
        claim_id: str,
        required_lease_ms: int | None = None,
        content: dict[str, Any] | None = None,
        review_evidence: dict[str, Any] | None = None,
        diagnostics: list[Diagnostic] | None = None,
        private_review_failures: list[dict[str, Any]] | None = None,
        retry_id: str | None = None,
    ) -> dict[str, Any]:
        resource_id = _path_segment(proof_job_id)
        if state == "completed":
            _validate_output_review_binding(
                evidence=review_evidence,
                kind="explanation",
                proof_job_id=proof_job_id,
                clarification_id=None,
                content=content,
            )
        return self._request(
            "PUT",
            f"/v1/internal/proof-jobs/{resource_id}/explanation",
            _claim_update_payload(
                state=state,
                claim_id=claim_id,
                required_lease_ms=required_lease_ms,
                content=content,
                review_evidence=review_evidence,
                diagnostics=diagnostics,
                private_review_failures=private_review_failures,
                retry_id=retry_id,
            ),
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def get_proof_clarification(self, clarification_id: str) -> dict[str, Any]:
        resource_id = _path_segment(clarification_id)
        return self._request(
            "GET",
            f"/v1/internal/proof-clarifications/{resource_id}/worker-input",
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def update_proof_clarification(
        self,
        *,
        clarification_id: str,
        proof_job_id: str | None = None,
        state: str,
        claim_id: str,
        required_lease_ms: int | None = None,
        content: dict[str, Any] | None = None,
        review_evidence: dict[str, Any] | None = None,
        diagnostics: list[Diagnostic] | None = None,
        private_review_failures: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        resource_id = _path_segment(clarification_id)
        if state == "completed":
            _validate_output_review_binding(
                evidence=review_evidence,
                kind="clarification",
                proof_job_id=proof_job_id,
                clarification_id=clarification_id,
                content=content,
            )
        return self._request(
            "POST",
            f"/v1/internal/proof-clarifications/{resource_id}/worker-updates",
            _claim_update_payload(
                state=state,
                claim_id=claim_id,
                required_lease_ms=required_lease_ms,
                content=content,
                review_evidence=review_evidence,
                diagnostics=diagnostics,
                private_review_failures=private_review_failures,
            ),
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        request_headers = {"Accept": "application/json", **(headers or {})}
        data = None
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")

        try:
            response = self.transport.request(
                method=method,
                url=self.base_url.rstrip("/") + path,
                headers=request_headers,
                body=data,
                timeout_seconds=(self.timeout_seconds if timeout_seconds is None
                                 else min(self.timeout_seconds, timeout_seconds)),
            )
        except HardDeadlineHttpError:
            raise PalsApiError("PALS API request failed") from None
        if not 200 <= response.status_code < 300:
            detail = response.body.decode("utf-8", errors="replace")
            error_code = _extract_api_error_code(detail)
            error = (
                ProofJobNotFoundError
                if response.status_code == 404 and error_code == "proof_job_not_found"
                else PalsApiError
            )
            raise error(
                f"PALS API returned HTTP {response.status_code}",
                status_code=response.status_code,
                error_code=error_code,
                validation_errors=_extract_api_validation_errors(detail),
            ) from None
        try:
            decoded = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise PalsApiError("PALS API request failed") from None
        if not isinstance(decoded, dict):
            raise PalsApiError("PALS API response was malformed")
        return cast(dict[str, Any], decoded)


def _claim_update_payload(
    *,
    state: str,
    claim_id: str,
    required_lease_ms: int | None,
    content: dict[str, Any] | None,
    review_evidence: dict[str, Any] | None,
    diagnostics: list[Diagnostic] | None,
    private_review_failures: list[dict[str, Any]] | None = None,
    retry_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "state": state,
        "claim_id": _canonical_claim_id(claim_id),
    }
    if state == "generating":
        if (
            type(required_lease_ms) is not int
            or not 1 <= required_lease_ms <= 3_600_000
            or content is not None
            or review_evidence is not None
        ):
            raise ValueError("generating requires only a valid required_lease_ms")
        payload["required_lease_ms"] = required_lease_ms
    elif state == "completed":
        if (
            required_lease_ms is not None
            or not isinstance(content, dict)
            or not isinstance(review_evidence, dict)
        ):
            raise ValueError("completed requires content and review evidence")
        payload["content"] = content
        payload["review_evidence"] = review_evidence
    elif state == "failed":
        if required_lease_ms is not None or content is not None or review_evidence is not None:
            raise ValueError("failed forbids content, review evidence, and required_lease_ms")
    else:
        raise ValueError("worker claim update state is invalid")

    if retry_id is not None:
        if state != "generating":
            raise ValueError("retry_id is valid only for acquisition")
        payload["retry_id"] = _canonical_claim_id(retry_id)
    if private_review_failures is not None:
        if state not in {"completed", "failed"} or not 1 <= len(private_review_failures) <= 2:
            raise ValueError(
                "private review failures require a terminal update and at most two items"
            )
        for failure in private_review_failures:
            if set(failure) != {"category", "rationale", "reviewer_session_id", "candidate_sha256"}:
                raise ValueError("invalid private review failure fields")
            if failure["category"] not in {"rejected", "transport", "schema"}:
                raise ValueError("invalid private review failure category")
            if not isinstance(failure["rationale"], str) or len(failure["rationale"]) > 2000:
                raise ValueError("invalid private review failure rationale")
            if failure["reviewer_session_id"] is not None:
                _canonical_claim_id(failure["reviewer_session_id"])
            if (
                not isinstance(failure["candidate_sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", failure["candidate_sha256"]) is None
            ):
                raise ValueError("invalid private review candidate hash")
        payload["private_review_failures"] = private_review_failures
    if diagnostics is not None:
        payload["diagnostics"] = [_diagnostic_payload(diagnostic) for diagnostic in diagnostics]
    return payload


def _diagnostic_payload(diagnostic: Diagnostic) -> dict[str, Any]:
    """Serialize the closed worker diagnostic wire shape, including null locations."""

    return {
        "severity": diagnostic.severity,
        "message": diagnostic.message,
        "code": diagnostic.code,
        "line": diagnostic.line,
        "column": diagnostic.column,
    }


def _validate_semantic_review_evidence(evidence: dict[str, Any]) -> None:
    required_keys = {
        "schema_version",
        "candidate_id",
        "generator_session_id",
        "lean_sha256",
        "target_declaration",
        "review_input_sha256",
        "reviewer",
        "decision",
        "rationale",
        "evidence_sha256",
    }
    if not isinstance(evidence, dict) or set(evidence) != required_keys:
        raise ValueError("proof semantic review evidence fields are invalid")
    if evidence.get("schema_version") != _SEMANTIC_REVIEW_SCHEMA_VERSION:
        raise ValueError("proof semantic review evidence schema is invalid")
    candidate_id = evidence.get("candidate_id")
    if not isinstance(candidate_id, str):
        raise ValueError("proof semantic review candidate id is invalid")
    try:
        _canonical_claim_id(candidate_id)
    except ValueError as exc:
        raise ValueError("proof semantic review candidate id is invalid") from exc
    generator_session_id = evidence.get("generator_session_id")
    if not isinstance(generator_session_id, str):
        raise ValueError("proof semantic review generator session is invalid")
    try:
        _canonical_claim_id(generator_session_id)
    except ValueError as exc:
        raise ValueError("proof semantic review generator session is invalid") from exc
    if not _is_sha256(evidence.get("lean_sha256")):
        raise ValueError("proof semantic review Lean digest is invalid")
    if not _is_target_declaration(evidence.get("target_declaration")):
        raise ValueError("proof semantic review target declaration is invalid")
    if not _is_sha256(evidence.get("review_input_sha256")):
        raise ValueError("proof semantic review input hash is invalid")
    if not _is_reviewer_identity(evidence.get("reviewer")):
        raise ValueError("proof semantic reviewer identity is invalid")
    reviewer = cast(dict[str, Any], evidence["reviewer"])
    if reviewer["session_id"] == generator_session_id:
        raise ValueError("proof semantic reviewer session must differ from generation")
    if evidence.get("decision") not in {"approved", "rejected"}:
        raise ValueError("proof semantic review decision is invalid")
    rationale = evidence.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 8_000:
        raise ValueError("proof semantic review rationale is invalid")
    if not _is_sha256(evidence.get("evidence_sha256")):
        raise ValueError("proof semantic review evidence hash is invalid")


def _validate_recipe_semantic_review_evidence(evidence: dict[str, Any]) -> None:
    """Validate the closed v3 worker object before it crosses the private boundary."""

    required_keys = {
        "schema_version",
        "candidate_id",
        "lean_sha256",
        "target_declaration",
        "review_input_sha256",
        "source_binding_sha256",
        "decision",
        "rationale",
    }
    if not isinstance(evidence, dict) or set(evidence) != required_keys:
        raise ValueError("Recipe semantic review evidence fields are invalid")
    if evidence.get("schema_version") != _RECIPE_SEMANTIC_REVIEW_SCHEMA_VERSION:
        raise ValueError("Recipe semantic review evidence schema is invalid")
    candidate_id = evidence.get("candidate_id")
    if not isinstance(candidate_id, str):
        raise ValueError("Recipe semantic review candidate id is invalid")
    try:
        _canonical_claim_id(candidate_id)
    except ValueError as exc:
        raise ValueError("Recipe semantic review candidate id is invalid") from exc
    if not _is_sha256(evidence.get("source_binding_sha256")):
        raise ValueError("Recipe semantic review source binding is invalid")
    if not _is_sha256(evidence.get("lean_sha256")):
        raise ValueError("Recipe semantic review Lean digest is invalid")
    if not _is_target_declaration(evidence.get("target_declaration")):
        raise ValueError("Recipe semantic review target declaration is invalid")
    if not _is_sha256(evidence.get("review_input_sha256")):
        raise ValueError("Recipe semantic review input hash is invalid")
    if evidence.get("decision") not in {"approved", "rejected"}:
        raise ValueError("Recipe semantic review decision is invalid")
    rationale = evidence.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 8_000:
        raise ValueError("Recipe semantic review rationale is invalid")


def _validate_recipe_candidate_source(candidate_source: dict[str, Any], *, lean_code: str) -> None:
    required_keys = {
        "schema_version",
        "candidate_source",
        "recipe_id",
        "recipe_revision",
        "alignment_id",
        "alignment_revision",
        "selection_payload_sha256",
        "selection_receipt_sha256",
        "materialized_source_sha256",
        "target_sha256",
        "toolchain_fingerprint_sha256",
        "compiler_receipt_sha256",
        "source_author_principal",
    }
    if not isinstance(candidate_source, dict) or set(candidate_source) != required_keys:
        raise ValueError("Recipe candidate source fields are invalid")
    if (
        candidate_source.get("schema_version") != "pals.candidate-source.v2"
        or candidate_source.get("candidate_source") != "recipe"
    ):
        raise ValueError("Recipe candidate source schema is invalid")
    for key in ("recipe_id", "source_author_principal"):
        value = candidate_source.get(key)
        if not isinstance(value, str) or not value or len(value) > 512:
            raise ValueError("Recipe candidate source text binding is invalid")
    if not str(candidate_source["source_author_principal"]).startswith("pals.principal.v1/"):
        raise ValueError("Recipe candidate author principal is invalid")
    recipe_revision = candidate_source.get("recipe_revision")
    if type(recipe_revision) is not int or recipe_revision < 1:
        raise ValueError("Recipe candidate Recipe revision is invalid")
    alignment_id = candidate_source.get("alignment_id")
    alignment_revision = candidate_source.get("alignment_revision")
    if (alignment_id is None) != (alignment_revision is None):
        raise ValueError("Recipe candidate alignment binding is incomplete")
    if alignment_id is not None and (
        not isinstance(alignment_id, str)
        or not alignment_id
        or type(alignment_revision) is not int
        or alignment_revision < 1
    ):
        raise ValueError("Recipe candidate alignment binding is invalid")
    for key in (
        "selection_payload_sha256",
        "selection_receipt_sha256",
        "materialized_source_sha256",
        "target_sha256",
        "toolchain_fingerprint_sha256",
        "compiler_receipt_sha256",
    ):
        if not _is_sha256(candidate_source.get(key)):
            raise ValueError("Recipe candidate source digest is invalid")
    if (
        candidate_source["materialized_source_sha256"]
        != hashlib.sha256(lean_code.encode("utf-8")).hexdigest()
    ):
        raise ValueError("Recipe candidate source must bind the exact Lean bytes")


def _recipe_artifact_uri_is_exact(
    *,
    result_artifact_uri: str,
    proof_job_id: str,
    candidate_id: str,
    lean_sha256: str,
) -> bool:
    match = re.fullmatch(
        r"s3://(?P<bucket>[A-Za-z0-9][A-Za-z0-9.-]{0,254})/proof-jobs/"
        r"(?P<job>[A-Za-z0-9][A-Za-z0-9._-]{0,127})/candidates/"
        r"(?P<candidate>[0-9a-f-]{36})/(?P<digest>[0-9a-f]{64})[.]lean",
        result_artifact_uri,
        flags=re.ASCII,
    )
    return bool(
        match is not None
        and match.group("job") == proof_job_id
        and match.group("candidate") == candidate_id
        and match.group("digest") == lean_sha256
    )


def _validate_output_review_binding(
    *,
    evidence: dict[str, Any] | None,
    kind: str,
    proof_job_id: str | None,
    clarification_id: str | None,
    content: dict[str, Any] | None,
) -> None:
    """Reject completed learner output unless the approval binds this exact payload."""

    if not isinstance(content, dict):
        raise ValueError("completed output requires content")
    if not isinstance(proof_job_id, str) or _RESOURCE_ID_RE.fullmatch(proof_job_id) is None:
        raise ValueError("completed output review requires a valid proof job id")
    _validate_output_review_evidence(evidence)
    assert evidence is not None
    if evidence["output_kind"] != kind:
        raise ValueError("output review kind does not match the completed resource")

    output: dict[str, Any] = {
        "output_kind": kind,
        "proof_job_id": proof_job_id,
        "content": content,
    }
    if kind == "clarification":
        if (
            not isinstance(clarification_id, str)
            or _RESOURCE_ID_RE.fullmatch(clarification_id) is None
        ):
            raise ValueError("clarification output review requires a valid clarification id")
        output["clarification_id"] = clarification_id
        output["parent_explanation_sha256"] = evidence["parent_explanation_sha256"]
        if evidence["schema_version"] == "pals.proof-output-review.v3":
            output["clarification_context_sha256"] = evidence["clarification_context_sha256"]
    elif clarification_id is not None:
        raise ValueError("explanation output reviews cannot bind a clarification id")
    if evidence["output_sha256"] != _canonical_json_sha256(output):
        raise ValueError("output review evidence does not bind the completed content")


def _validate_output_review_evidence(evidence: dict[str, Any] | None) -> None:
    required_keys = {
        "schema_version",
        "output_kind",
        "output_sha256",
        "lean_sha256",
        "parent_explanation_sha256",
        "generator_session_id",
        "reviewer",
        "decision",
        "rationale",
        "evidence_sha256",
    }
    if (
        isinstance(evidence, dict)
        and evidence.get("schema_version") == "pals.proof-output-review.v3"
    ):
        required_keys.add("clarification_context_sha256")
        if evidence.get("output_kind") != "clarification" or not _is_sha256(
            evidence.get("clarification_context_sha256")
        ):
            raise ValueError("clarification review context is invalid")
    if not isinstance(evidence, dict) or set(evidence) != required_keys:
        raise ValueError("output review evidence fields are invalid")
    if evidence.get("schema_version") not in {
        _OUTPUT_REVIEW_SCHEMA_VERSION, "pals.proof-output-review.v3"
    }:
        raise ValueError("output review evidence schema version is invalid")
    kind = evidence.get("output_kind")
    if kind not in {"explanation", "clarification"}:
        raise ValueError("output review evidence kind is invalid")
    if not _is_sha256(evidence.get("output_sha256")) or not _is_sha256(evidence.get("lean_sha256")):
        raise ValueError("output review evidence digest is invalid")
    parent_sha256 = evidence.get("parent_explanation_sha256")
    if (kind == "explanation" and parent_sha256 is not None) or (
        kind == "clarification" and not _is_sha256(parent_sha256)
    ):
        raise ValueError("output review evidence parent binding is invalid")
    if not _is_output_reviewer_identity(evidence.get("reviewer")):
        raise ValueError("output review evidence reviewer identity is invalid")
    generator_session_id = evidence.get("generator_session_id")
    if not isinstance(generator_session_id, str):
        raise ValueError("output review generation session is invalid")
    try:
        _canonical_claim_id(generator_session_id)
    except ValueError as exc:
        raise ValueError("output review generation session is invalid") from exc
    reviewer = cast(dict[str, Any], evidence["reviewer"])
    if reviewer["session_id"] == generator_session_id:
        raise ValueError("output reviewer session must differ from generation")
    rationale = evidence.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 8_000:
        raise ValueError("output review evidence rationale is invalid")
    if evidence.get("decision") != "approved" or not _is_sha256(evidence.get("evidence_sha256")):
        raise ValueError("output review evidence approval is invalid")
    unsigned_evidence = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence["evidence_sha256"] != _canonical_json_sha256(unsigned_evidence):
        raise ValueError("output review evidence digest does not match its payload")


def _is_output_reviewer_identity(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"provider", "model", "session_id"}:
        return False
    return all(
        _is_printable_ascii_identifier(value.get(key))
        for key in ("provider", "model", "session_id")
    )


def _is_printable_ascii_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= 200
        and value.isascii()
        and all("!" <= character <= "~" for character in value)
    )


def _canonical_json_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_HEX_RE.fullmatch(value) is not None


def _is_target_declaration(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"kind", "name", "proposition"}:
        return False
    name = value.get("name")
    return (
        value.get("kind") in {"theorem", "lemma", "example"}
        and (name is None or (isinstance(name, str) and bool(name.strip()) and len(name) <= 20_000))
        and isinstance(value.get("proposition"), str)
        and bool(value["proposition"].strip())
        and len(value["proposition"]) <= 200_000
    )


def _is_reviewer_identity(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"provider", "model", "session_id"}:
        return False
    provider = value.get("provider")
    model = value.get("model")
    session_id = value.get("session_id")
    return (
        _is_ascii_nonblank(provider, maximum=80)
        and _is_ascii_nonblank(model, maximum=200)
        and _is_ascii_nonblank(session_id, maximum=200)
    )


def _is_ascii_nonblank(value: object, *, maximum: int) -> bool:
    return (
        isinstance(value, str) and bool(value.strip()) and value.isascii() and len(value) <= maximum
    )


def _canonical_claim_id(claim_id: str) -> str:
    try:
        parsed_claim = uuid.UUID(claim_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("claim_id must be a canonical UUIDv4 string") from exc
    if parsed_claim.version != 4 or str(parsed_claim) != claim_id:
        raise ValueError("claim_id must be a canonical UUIDv4 string")
    return claim_id


def _extract_api_error_code(body: str) -> str | None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, str) else None


def _path_segment(resource_id: str) -> str:
    if not isinstance(resource_id, str) or _RESOURCE_ID_RE.fullmatch(resource_id) is None:
        raise ValueError("resource id must be one valid path segment")
    return quote(resource_id, safe="-._~", encoding="ascii", errors="strict")
