"""Fail-closed, claim-bound metering for the opt-in natural-answer operation.

This is deliberately separate from best-effort provider cost telemetry. A missing
permit or receipt poisons the operation; it can never be converted into success.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

import rfc8785

from pals_agent.api_client import PalsApiError
from pals_agent.http_transport import HttpResponse, HttpTransport
from pals_agent.proof_reuse_usage import current_role
from pals_agent.provider_usage import POLICY_V2, TARIFF_SNAPSHOTS, exact_usage
from pals_agent.usage import PRICE_SNAPSHOTS, report_usage


class TokenMeterError(RuntimeError):
    """A closed operational failure, with no provider body or credentials."""


class TokenBudgetExceededError(TokenMeterError):
    """Only an explicit authenticated permit denial, not uncertain metering."""


class TokenMeterApi(Protocol):
    def permit_token_call(self, payload: dict[str, Any], *, timeout_seconds: float) -> None: ...

    def record_token_receipt(self, payload: dict[str, Any], *, timeout_seconds: float) -> None: ...

    def seal_token_stage(self, payload: dict[str, Any], *, timeout_seconds: float) -> None: ...


_active: ContextVar[TokenMeter | None] = ContextVar("pals_token_meter", default=None)


def active_token_meter() -> TokenMeter | None:
    return _active.get()


@contextmanager
def token_meter_scope(meter: TokenMeter) -> Iterator[None]:
    active = _active.get()
    if active is not None and not active.sealed:
        raise TokenMeterError("token_meter_nested")
    token = _active.set(meter)
    try:
        yield
    finally:
        _active.reset(token)


def _integer(value: object, *, maximum: int = 9_007_199_254_740_991) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise TokenMeterError("token_usage_invalid")
    return value


def _object(body: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise TokenMeterError("token_response_invalid")
            result[key] = value
        return result

    value = json.loads(body, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise TokenMeterError("token_response_invalid")
    return value


def _supported_input(value: Any, *, embedding: bool) -> bool:
    if isinstance(value, str):
        return True
    if embedding or not isinstance(value, list) or len(value) != 1:
        return False
    message = value[0]
    if (
        not isinstance(message, dict)
        or set(message) != {"role", "content"}
        or message["role"] != "user"
        or not isinstance(message["content"], list)
        or not 2 <= len(message["content"]) <= 331
    ):
        return False
    parts = message["content"]
    if (
        not isinstance(parts[0], dict)
        or set(parts[0]) != {"type", "text"}
        or parts[0]["type"] != "input_text"
        or not isinstance(parts[0]["text"], str)
    ):
        return False
    from pals_agent.chat_images import validate_image_data_url

    total_bytes = 0
    for item in parts[1:]:
        if (
            not isinstance(item, dict)
            or set(item) != {"type", "image_url", "detail"}
            or item["type"] != "input_image"
            or item["detail"] != "high"
        ):
            return False
        try:
            total_bytes += len(validate_image_data_url(item["image_url"]))
            if total_bytes > 20_000_000:
                return False
        except (ValueError, TypeError):
            return False
    return True


@dataclass
class TokenMeter:
    api: TokenMeterApi
    operation_id: str
    request_id: str | None
    claim_id: str
    deadline: float
    policy_version: str = "utilization-v1-2026-09-30"
    scope: str = "request"
    job_id: str | None = None
    task_id: str | None = None
    subject: dict[str, str] | None = None
    failed: bool = False
    completed_calls: dict[str, str] = field(default_factory=dict)
    last_call_id: str | None = None
    sealed: bool = False

    def __post_init__(self) -> None:
        for value in (self.operation_id, self.claim_id):
            if str(UUID(value)) != value:
                raise TokenMeterError("token_binding_invalid")
        if self.policy_version not in {"utilization-v1-2026-09-30", POLICY_V2}:
            raise TokenMeterError("token_policy_unsupported")
        if self.scope not in {
            "request",
            "generation",
            "explanation",
            "clarification",
            "semantic_review",
        }:
            raise TokenMeterError("token_scope_invalid")
        if self.scope != "request" and (not isinstance(self.job_id, str) or not self.job_id):
            raise TokenMeterError("token_binding_invalid")
        if self.subject is None:
            if (
                not isinstance(self.request_id, str)
                or str(UUID(self.request_id)) != self.request_id
            ):
                raise TokenMeterError("token_binding_invalid")
        elif (
            self.policy_version != POLICY_V2
            or self.request_id is not None
            or set(self.subject) != {"kind", "id"}
            or not isinstance(self.subject.get("id"), str)
            or self.subject.get("kind") not in {"clarification", "explanation_retry"}
            or self.scope != (
                "clarification" if self.subject["kind"] == "clarification" else "explanation"
            )
            or self.scope == "clarification" and self.task_id != self.subject["id"]
        ):
            raise TokenMeterError("token_binding_invalid")
        if self.subject is not None:
            parsed = UUID(self.subject["id"])
            if str(parsed) != self.subject["id"] or parsed.version != 4:
                raise TokenMeterError("token_binding_invalid")

    def _remaining(self, deadline: float) -> float:
        remaining = min(deadline, self.deadline) - time.monotonic()
        if remaining <= 0 or self.failed or self.sealed:
            raise TokenMeterError("token_meter_deadline")
        return remaining

    def complete(self, path: str) -> None:
        if self.policy_version != POLICY_V2:
            return
        payload: dict[str, Any] = {
            "schema_version": "pals.token-stage-seal.v2",
            "operation_id": self.operation_id,
            "claim_id": self.claim_id,
            "scope": self.scope,
            "call_ids": sorted(self.completed_calls),
            "completed_roles": sorted(set(self.completed_calls.values())),
            "outcome": "completed",
            "path": path,
        }
        if self.request_id is not None:
            payload["request_id"] = self.request_id
        if self.subject is not None:
            payload["subject"] = dict(self.subject)
        if self.job_id is not None:
            payload["job_id"] = self.job_id
        if self.task_id is not None:
            payload["task_id"] = self.task_id
        try:
            self.api.seal_token_stage(payload, timeout_seconds=self._remaining(self.deadline))
        except Exception:
            self.failed = True
            raise TokenMeterError("token_stage_seal_failed") from None
        self.sealed = True

    def request(
        self,
        *,
        transport: HttpTransport,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        data: bytes,
        timeout_seconds: float,
        call_id: str,
        embedding: bool = False,
    ) -> HttpResponse:
        """Count -> permit -> one provider request -> durable usage acknowledgement.

        Count uses the full Responses input including schema/formatting. Embedding
        reserves its documented maximum single-input size, not a character guess.
        Neither counting nor receipt latency grants additional generation time.
        """
        deadline = min(self.deadline, time.monotonic() + timeout_seconds)
        binding: dict[str, Any] = dict(
            operation_id=self.operation_id,
            claim_id=self.claim_id,
            call_id=call_id,
        )
        if self.request_id is not None:
            binding["request_id"] = self.request_id
        versioned_binding = dict(binding)
        if self.policy_version == POLICY_V2:
            versioned_binding.update(scope=self.scope)
            if self.subject is not None:
                versioned_binding["subject"] = dict(self.subject)
            if self.job_id is not None:
                versioned_binding["job_id"] = self.job_id
            if self.task_id is not None:
                versioned_binding["task_id"] = self.task_id
        permitted = False
        receipt_attempted = False
        try:
            self._remaining(deadline)
            model = payload.get("model")
            snapshots = TARIFF_SNAPSHOTS if self.policy_version == POLICY_V2 else PRICE_SNAPSHOTS
            snapshot = snapshots.get(model) if isinstance(model, str) else None
            if (
                snapshot is None
                or not isinstance(model, str)
                or not _supported_input(payload.get("input"), embedding=embedding)
            ):
                # Only explicit text or bounded inline derivatives may be counted.
                raise TokenMeterError("token_input_unsupported")
            if data not in (json.dumps(payload).encode("utf-8"), rfc8785.dumps(payload)):
                raise TokenMeterError("token_payload_changed")
            if self.policy_version == POLICY_V2 and endpoint not in {
                "https://api.openai.com/v1/embeddings",
                "https://api.openai.com/v1/responses",
            }:
                raise TokenMeterError("token_pricing_profile_unsupported")
            if embedding:
                if (
                    model != "text-embedding-3-small"
                    or set(payload) != {"model", "input", "dimensions"}
                    or not payload["input"]
                ):
                    raise TokenMeterError("token_input_unsupported")
                input_bound, output_bound = 8192, 0
            else:
                if not {"model", "input", "max_output_tokens"} <= set(payload) or set(payload) - {
                    "model",
                    "input",
                    "max_output_tokens",
                    "text",
                    "service_tier",
                    "reasoning",
                    "store",
                    "stream",
                }:
                    raise TokenMeterError("token_input_unsupported")
                if "store" in payload and payload["store"] is not False:
                    raise TokenMeterError("token_input_unsupported")
                if "stream" in payload and payload["stream"] is not False:
                    raise TokenMeterError("token_input_unsupported")
                if self.policy_version == POLICY_V2 and payload.get("service_tier") != "default":
                    raise TokenMeterError("token_pricing_profile_unsupported")
                output_bound = _integer(payload["max_output_tokens"])
                if output_bound == 0:
                    raise TokenMeterError("token_input_unsupported")
                # Forward every supported input/configuration field; only output
                # limits and service tier are absent from the official count schema.
                count_payload = {
                    key: payload[key]
                    for key in ("model", "input", "text", "reasoning")
                    if key in payload
                }
                count_response = transport.request(
                    method="POST",
                    url=endpoint + "/input_tokens",
                    headers=headers,
                    body=json.dumps(count_payload).encode("utf-8"),
                    timeout_seconds=self._remaining(deadline),
                )
                counted = _object(count_response.body)
                if (
                    count_response.status_code != 200
                    or set(counted) != {"object", "input_tokens"}
                    or counted["object"] != "response.input_tokens"
                ):
                    raise TokenMeterError("token_count_unavailable")
                input_bound = _integer(counted["input_tokens"])
            try:
                self.api.permit_token_call(
                    dict(
                        versioned_binding,
                        **(
                            {"schema_version": "pals.token-permit.v2"}
                            if self.policy_version == POLICY_V2
                            else {}
                        ),
                        model=model,
                        model_role=current_role(),
                        price_snapshot_id=snapshot,
                        input_token_bound=input_bound,
                        output_token_bound=output_bound,
                        payload_sha256=hashlib.sha256(data).hexdigest(),
                    ),
                    timeout_seconds=self._remaining(deadline),
                )
            except PalsApiError as error:
                if error.status_code == 402 and error.error_code == "token_budget_exceeded":
                    raise TokenBudgetExceededError("token_budget_exceeded") from None
                raise
            permitted = True
            response = transport.request(
                method="POST",
                url=endpoint,
                headers=headers,
                body=data,
                timeout_seconds=self._remaining(deadline),
            )
            body = _object(response.body)
            if not 200 <= response.status_code < 300 or body.get("model") != model:
                raise TokenMeterError("token_provider_unavailable")
            usage = body.get("usage")
            telemetry_usage = (
                {"input_tokens": usage.get("prompt_tokens"), "output_tokens": 0}
                if embedding and isinstance(usage, dict)
                else usage
            )
            # Keep provider cost evidence even when customer accounting subsequently
            # fails (including usage above a permit or a lost receipt acknowledgement).
            report_usage(call_id, model, telemetry_usage)
            if not isinstance(usage, dict):
                raise TokenMeterError("token_usage_missing")
            actual_input = _integer(usage.get("prompt_tokens" if embedding else "input_tokens"))
            actual_output = 0 if embedding else _integer(usage.get("output_tokens"))
            actual = (
                exact_usage(body, model, embedding=embedding)
                if self.policy_version == POLICY_V2
                else None
            )
            cached = (
                actual["cached_input_tokens"]
                if actual
                else _integer(usage.get("input_tokens_details", {}).get("cached_tokens", 0))
            )
            reasoning = (
                actual["reasoning_output_tokens"]
                if actual
                else _integer(usage.get("output_tokens_details", {}).get("reasoning_tokens", 0))
            )
            if (
                actual_input > input_bound
                or actual_output > output_bound
                or cached > actual_input
                or reasoning > actual_output
            ):
                raise TokenMeterError("token_usage_exceeds_permit")
            receipt_attempted = True
            self.api.record_token_receipt(
                dict(
                    versioned_binding,
                    **({"schema_version": "pals.token-receipt.v2"} if actual else {}),
                    status="success",
                    **(
                        actual
                        if actual
                        else dict(
                            input_tokens=actual_input,
                            output_tokens=actual_output,
                            cached_input_tokens=cached,
                            reasoning_output_tokens=reasoning,
                        )
                    ),
                ),
                timeout_seconds=self._remaining(deadline),
            )
            self.completed_calls[call_id] = current_role()
            self.last_call_id = call_id
            return response
        except Exception as error:
            # A lost success acknowledgement is NOT rewritten as unknown. The API
            # may have committed it; final failure releases the operation regardless.
            if permitted and not receipt_attempted:
                # An unresolved permit is itself a server-side success barrier.
                with suppress(Exception):
                    self.api.record_token_receipt(
                        dict(
                            versioned_binding,
                            status="unknown",
                            **(
                                {"schema_version": "pals.token-receipt.v2"}
                                if self.policy_version == POLICY_V2
                                else dict(
                                    input_tokens=0,
                                    output_tokens=0,
                                    cached_input_tokens=0,
                                    reasoning_output_tokens=0,
                                )
                            ),
                        ),
                        timeout_seconds=max(0.001, min(5.0, self.deadline - time.monotonic())),
                    )
            self.failed = True
            if isinstance(error, TokenBudgetExceededError):
                raise TokenBudgetExceededError("token_budget_exceeded") from None
            raise TokenMeterError("proof_reuse_token_accounting_failed") from None
