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
from pals_agent.chat_images import chat_attachment_ids, parse_chat_images
from pals_agent.material_context import MaterialContext, MaterialContextError
from pals_agent.math_conventions import parse_claim as parse_conventions
from pals_agent.proof_reuse import MAX_SECONDS, ProofReuseResult, ProofReuseRuntime
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


class ChatAnswerRuntime(Protocol):
    def answer(
        self, request: dict[str, Any],
        recipe_lookup: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    ) -> ProofReuseResult: ...


class ProofRequestApi(TokenMeterApi, Protocol):
    def get_proof_request_attachments(
        self, *, request_id: str, claim_id: str
    ) -> dict[str, Any]: ...
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


@dataclass(frozen=True, slots=True)
class ProofRequestProcessor:
    api: ProofRequestApi
    runtime: ProofReuseRuntime | ChatAnswerRuntime
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
            "billing_operation_id", "material_context_available", "lean_flow", "math_conventions"
        }:
            return False
        conventions = None
        if "math_conventions" in claim:
            conventions = parse_conventions(claim["math_conventions"])
            if conventions is None:
                return False
        if any(
            key in claim and type(claim[key]) is not bool
            for key in ("material_context_available", "lean_flow")
        ):
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
        request = dict(request, worker_deadline=started + MAX_SECONDS)
        # Only a released Lean flow may route requests to catalog reuse or linked Lean jobs.
        recipe_lookup = (
            (lambda sources: self.api.lookup_proof_request_recipes(
                request_id=request_id, claim_id=claim_id, sources=sources
            ))
            if claim.get("lean_flow")
            else None
        )
        try:
            attachment_ids = chat_attachment_ids(request)
            if attachment_ids:
                try:
                    image_payload = self.api.get_proof_request_attachments(
                        request_id=request_id, claim_id=claim_id,
                    )
                    images = parse_chat_images(image_payload, attachment_ids)
                except (PalsApiError, ValueError, TypeError, KeyError) as error:
                    raise MaterialContextError("chat_attachments_unavailable") from error
                request = dict(request, chat_images=images)
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
                    if not self.token_accounting_enabled:
                        raise TokenMeterError("token_accounting_disabled")
                    operation_id = claim["billing_operation_id"]
                    if not isinstance(operation_id, str) or str(UUID(operation_id)) != operation_id:
                        raise TokenMeterError("token_binding_invalid")
                    meter = TokenMeter(self.api, operation_id, request_id, claim_id,
                                       started + MAX_SECONDS)
                    with token_meter_scope(meter):
                        result = self.runtime.answer(request, recipe_lookup)
                    if meter.failed:
                        raise TokenMeterError("token_meter_failed")
                    if result.outcome == "answered" and (
                        not isinstance(result.private_evidence.get("token_qa"), dict)
                        or result.private_evidence["token_qa"].get("approved") is not True
                    ):
                        raise TokenMeterError("token_qa_missing")
                else:
                    result = self.runtime.answer(request, recipe_lookup)
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
        return settled.get("id") == request_id and settled.get("status") in (
            expected,
            # The API refuses Lean outcomes it cannot run and records an explicit failure.
            "failed",
        )
