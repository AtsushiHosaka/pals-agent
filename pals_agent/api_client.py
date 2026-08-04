from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import quote

from pals_agent.http_transport import (
    HardDeadlineHttpError,
    HardDeadlineHttpTransport,
    HttpTransport,
)
from pals_agent.models import Diagnostic, ProofJobState

_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$", re.ASCII)
_VERIFICATION_CANDIDATE_SCHEMA_VERSION = "pals.proof-verification-candidate.v1"
_MANUAL_FIXTURE_URI_RE = re.compile(
    r"^s3://[A-Za-z0-9][A-Za-z0-9.-]{0,254}/manual-fixtures/([0-9a-f]{64})\.lean$",
    re.ASCII,
)
_MODEL_ARTIFACT_URI_RE = re.compile(
    r"^s3://[A-Za-z0-9][A-Za-z0-9.-]{0,254}/proof-jobs/"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}/result\.lean$",
    re.ASCII,
)

# Kept only for test-double compatibility while the public worker transport no longer accepts it.
type VerifierAttestation = dict[str, Any]


class PalsApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


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

    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        resource_id = _path_segment(proof_job_id)
        return self._request(
            "GET",
            f"/v1/internal/proof-jobs/{resource_id}/worker-input",
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

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
        uri_match = _MANUAL_FIXTURE_URI_RE.fullmatch(result_artifact_uri)
        lean_sha256 = hashlib.sha256(lean_code.encode("utf-8")).hexdigest()
        if uri_match is not None and uri_match.group(1) != lean_sha256:
            raise ValueError("verification candidate URI must bind the exact Lean digest")
        if uri_match is None and _MODEL_ARTIFACT_URI_RE.fullmatch(result_artifact_uri) is None:
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

    def upsert_proof_explanation(
        self,
        *,
        proof_job_id: str,
        state: str,
        claim_id: str,
        required_lease_ms: int | None = None,
        content: dict[str, Any] | None = None,
        diagnostics: list[Diagnostic] | None = None,
    ) -> dict[str, Any]:
        resource_id = _path_segment(proof_job_id)
        return self._request(
            "PUT",
            f"/v1/internal/proof-jobs/{resource_id}/explanation",
            _claim_update_payload(
                state=state,
                claim_id=claim_id,
                required_lease_ms=required_lease_ms,
                content=content,
                diagnostics=diagnostics,
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
        state: str,
        claim_id: str,
        required_lease_ms: int | None = None,
        content: dict[str, Any] | None = None,
        diagnostics: list[Diagnostic] | None = None,
    ) -> dict[str, Any]:
        resource_id = _path_segment(clarification_id)
        return self._request(
            "POST",
            f"/v1/internal/proof-clarifications/{resource_id}/worker-updates",
            _claim_update_payload(
                state=state,
                claim_id=claim_id,
                required_lease_ms=required_lease_ms,
                content=content,
                diagnostics=diagnostics,
            ),
            headers={"X-PALS-Worker-Secret": self.worker_secret},
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
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
                timeout_seconds=self.timeout_seconds,
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
    diagnostics: list[Diagnostic] | None,
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
        ):
            raise ValueError("generating requires only a valid required_lease_ms")
        payload["required_lease_ms"] = required_lease_ms
    elif state == "completed":
        if required_lease_ms is not None or not isinstance(content, dict):
            raise ValueError("completed requires content and forbids required_lease_ms")
        payload["content"] = content
    elif state == "failed":
        if required_lease_ms is not None or content is not None:
            raise ValueError("failed forbids content and required_lease_ms")
    else:
        raise ValueError("worker claim update state is invalid")

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
