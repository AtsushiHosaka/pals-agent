"""Claim-fenced SQS processing for natural proofs; no Lean dependencies."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from pals_agent.api_client import PalsApiError
from pals_agent.material_context import MaterialContext, MaterialContextError
from pals_agent.math_conventions import parse_claim as parse_conventions
from pals_agent.proof_reuse import MAX_SECONDS, ProofReuseError, ProofReuseResult, ProofReuseRuntime
from pals_agent.proof_reuse_usage import current_role
from pals_agent.token_meter import (
    TokenBudgetExceededError,
    TokenMeter,
    TokenMeterApi,
    TokenMeterError,
    token_meter_scope,
)
from pals_agent.usage import usage_scope

_logger = logging.getLogger(__name__)
_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,79}$", re.ASCII)
_SETTLED_STATUSES = frozenset({"answered", "needs_input", "verifying", "failed"})
_ASSESSMENT_PHASES = frozenset({
    "premise_resolution", "catalog_retrieval", "primary_assessment",
    "uncertainty_escalation", "independent_answer_qa", "recipe_request_structure",
    "recipe_search", "recipe_scope_assessment", "recipe_independent_correspondence",
})
_RESULT_ERROR_CODES = frozenset({
    "proof_reuse_answer_review_failed", "proof_reuse_catalog_invalid", "proof_reuse_deadline",
    "proof_reuse_input_invalid", "proof_reuse_invalid_instantiation",
    "proof_reuse_invalid_response", "proof_reuse_invalid_source",
    "proof_reuse_provider_unavailable", "proof_reuse_query_invalid",
    "proof_reuse_recipe_invalid", "proof_reuse_recipe_unavailable",
    "proof_reuse_token_accounting_failed", "proof_reuse_unsupported",
    "material_citation_invalid", "material_citation_missing", "material_context_invalid",
    "material_context_too_large", "material_context_unavailable", "material_proposition_invalid",
    "material_proposition_unconfirmed", "token_budget_exceeded", "token_usage_unknown",
    "proof_request_delivery_exhausted", "lean_flow_unavailable", "lean_verification_required",
    "lean_verification_failed", "lean_explanation_failed",
})


def _diagnostic_label(value: Any, allowed: frozenset[str]) -> str | None:
    # A syntactically valid identifier can still contain private data. Never echo
    # unknown labels from provider evidence or API responses into logs.
    if value is None:
        return None
    return value if isinstance(value, str) and value in allowed else "unrecognized"


def _review_verdict(evidence: dict[str, Any]) -> bool | None:
    review = evidence.get("token_qa", evidence.get("answer_qa"))
    verdict = review.get("approved") if isinstance(review, dict) else None
    return verdict if type(verdict) is bool else None


class ProofRequestApi(TokenMeterApi, Protocol):
    def record_proof_request_usage(
        self, *, request_id: str, claim_id: str, usage: dict[str, Any]
    ) -> None: ...

    def acquire_proof_request_claim(
        self, *, request_id: str, claim_id: str, lease_ms: int
    ) -> dict[str, Any]: ...

    def settle_proof_request(
        self, *, request_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...

    def get_proof_request_materials(
        self, *, request_id: str, claim_id: str
    ) -> dict[str, Any]: ...

    def lookup_proof_request_recipes(
        self, *, request_id: str, claim_id: str, sources: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...

    def search_proof_request_recipes(
        self, *, request_id: str, claim_id: str, query: str, output_language: str, limit: int = 8
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class ProofRequestProcessor:
    api: ProofRequestApi
    runtime: ProofReuseRuntime
    token_accounting_enabled: bool = False

    def process(
        self, request_id: str, claim_id: str, extend_visibility: Callable[[int], None]
    ) -> bool:
        if str(UUID(request_id)) != request_id or str(UUID(claim_id)) != claim_id:
            return False
        # A lease must never outlive the visibility protecting this delivery.
        extend_visibility(270)
        claim = self.api.acquire_proof_request_claim(
            request_id=request_id,
            claim_id=claim_id,
            lease_ms=240000,
        )
        keys = {"status", "request", "claim_id", "lease_expires_at"}
        if not keys <= set(claim) or set(claim) - keys - {
            "billing_operation_id", "complimentary_token_operation", "material_context_available",
            "lean_flow", "math_conventions"
        }:
            return False
        conventions = None
        if "math_conventions" in claim:
            conventions = parse_conventions(claim["math_conventions"])
            if conventions is None:
                return False
        if any(
            key in claim and type(claim[key]) is not bool
            for key in ("material_context_available", "lean_flow", "complimentary_token_operation")
        ):
            return False
        complimentary_token_operation = claim.get("complimentary_token_operation") is True
        if complimentary_token_operation and "billing_operation_id" not in claim:
            return False
        if claim["status"] == "terminal":
            return True
        if claim["status"] != "acquired" or claim["claim_id"] != claim_id:
            return False
        request = claim["request"]
        if not isinstance(request, dict) or request.get("id") != request_id:
            return False
        if conventions is not None:
            request = dict(request, math_conventions=conventions)
        revision = request.get("revision")
        if type(revision) is not int or revision < 0 or request.get("status") != "assessing":
            return False
        try:
            expiry = datetime.fromisoformat(claim["lease_expires_at"].replace("Z", "+00:00"))
            if expiry.tzinfo is None or (expiry - datetime.now(UTC)).total_seconds() < 230:
                return False
        except (ValueError, TypeError, AttributeError):
            return False
        usage: list[dict[str, Any]] = []

        def record(item: dict[str, Any]) -> None:
            record = {
                "call_id": item["call_id"],
                "model_role": current_role(),
                "provider": item["provider"],
                "model": item["model"],
                "input_tokens": item["input_tokens"],
                "output_tokens": item["output_tokens"],
                "cached_input_tokens": item["cached_input_tokens"],
                "reasoning_tokens": item["reasoning_output_tokens"],
                "price_snapshot_id": item.get("price_snapshot_id"),
                "provider_request_id": item.get("provider_request_id"),
            }
            usage.append(record)
            # The settlement repeats these IDs so temporary metering failures can be
            # recovered without double charging. Already-incurred usage survives failures.
            with suppress(PalsApiError):
                self.api.record_proof_request_usage(
                    request_id=request_id,
                    claim_id=claim_id,
                    usage=record,
                )

        started = time.monotonic()
        # Only a released Lean flow may route requests to catalog reuse or linked Lean jobs.
        def search_recipes(query: str, language: str) -> list[dict[str, Any]]:
            try:
                return self.api.search_proof_request_recipes(
                    request_id=request_id, claim_id=claim_id, query=query,
                    output_language=language, limit=8,
                )
            except PalsApiError as error:
                raise ProofReuseError("proof_reuse_recipe_unavailable") from error

        recipe_options: dict[str, Any] = (
            {"recipe_search": search_recipes, "claim_id": claim_id}
            if claim.get("lean_flow") else {}
        )
        try:
            if claim.get("material_context_available"):
                try:
                    payload = self.api.get_proof_request_materials(
                        request_id=request_id, claim_id=claim_id,
                    )
                except PalsApiError as error:
                    raise MaterialContextError("material_context_unavailable") from error
                material_context = MaterialContext.parse(
                    payload, project_id=request.get("project_id")
                )
                request = dict(request, material_context=material_context.as_data())
            with usage_scope(record):
                if "billing_operation_id" in claim:
                    # This API claim marker describes an already-admitted QA operation.
                    # Each provider call still needs an owner/operation/live-claim permit.
                    if not (self.token_accounting_enabled or complimentary_token_operation):
                        raise TokenMeterError("token_accounting_disabled")
                    operation_id = claim["billing_operation_id"]
                    if not isinstance(operation_id, str) or str(UUID(operation_id)) != operation_id:
                        raise TokenMeterError("token_binding_invalid")
                    if not all(callable(getattr(self.api, name, None)) for name in (
                        "permit_token_call", "record_token_receipt"
                    )):
                        raise TokenMeterError("token_accounting_unavailable")
                    meter = TokenMeter(self.api, operation_id, request_id, claim_id,
                                       started + MAX_SECONDS)
                    with token_meter_scope(meter):
                        result = self.runtime.answer(request, **recipe_options)
                    if meter.failed:
                        raise TokenMeterError("token_meter_failed")
                    if result.outcome == "answered" and (
                        not isinstance(result.private_evidence.get("token_qa"), dict)
                        or result.private_evidence["token_qa"].get("approved") is not True
                    ):
                        raise TokenMeterError("token_qa_missing")
                else:
                    result = self.runtime.answer(request, **recipe_options)
        except MaterialContextError as error:
            result = ProofReuseResult(
                "failed", None, None, error.code,
                {"schema_version": "pals.proof-reuse-assessment.v1"},
            )
        except (TokenMeterError, ValueError) as error:
            result = ProofReuseResult(
                "failed", None, None,
                "token_budget_exceeded" if isinstance(error, TokenBudgetExceededError)
                else "proof_reuse_token_accounting_failed",
                {"schema_version": "pals.proof-reuse-assessment.v1"},
            )
        payload = {
            "claim_id": claim_id,
            "expected_revision": revision,
            "outcome": result.outcome,
            "question": result.question,
            "answer": result.answer,
            "error_code": result.error_code,
            **({"formal_plan": result.formal_plan} if result.formal_plan is not None else {}),
            # MCV-005: readings the assessment applied; the API re-checks each one.
            **(
                {"conventions": result.private_evidence["applied_conventions"]}
                if result.outcome in {"answered", "formal"}
                and result.private_evidence.get("applied_conventions")
                else {}
            ),
            "private_evidence": dict(
                result.private_evidence,
                worker_elapsed_ms=round((time.monotonic() - started) * 1000),
            ),
            "usage": usage,
        }
        try:
            settled = self.api.settle_proof_request(request_id=request_id, payload=payload)
        except PalsApiError as error:
            # Never log the exception message or raw API validation body: they may
            # contain learner text, model output or credentials.
            code = error.error_code
            safe_code = code if isinstance(code, str) and _SAFE_ERROR_CODE.fullmatch(code) else None
            _logger.warning(
                "proof_request_settlement_failed request_id=%s claim_id=%s "
                "status_code=%s error_code=%s validation_errors=%s",
                request_id, claim_id, error.status_code, safe_code, error.validation_errors,
            )
            # Do not generate again in this delivery after an uncertain commit. Redelivery
            # must acquire a fresh API claim, which observes an already-terminal result.
            return False
        expected = "verifying" if result.outcome == "formal" else result.outcome
        accepted = settled.get("id") == request_id and settled.get("status") in (
            expected,
            # The API refuses Lean outcomes it cannot run and records an explicit failure.
            "failed",
        )
        status = settled.get("status")
        if accepted and isinstance(status, str) and status in _SETTLED_STATUSES:
            # This is the committed assessment result, including ordinary failed
            # jobs. A formal result is a handoff, not a Lean verification receipt.
            log = _logger.warning if status == "failed" else _logger.info
            log(
                "proof_request_settled request_id=%s claim_id=%s status=%s "
                "assessment_phase=%s error_code=%s review_approved=%s",
                request_id, claim_id, status,
                _diagnostic_label(result.private_evidence.get("phase"), _ASSESSMENT_PHASES),
                _diagnostic_label(
                    settled.get("error_code", result.error_code), _RESULT_ERROR_CODES,
                ),
                _review_verdict(result.private_evidence),
            )
        return accepted
