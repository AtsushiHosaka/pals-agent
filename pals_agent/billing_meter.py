"""Restore the admitted operation across asynchronous Lean worker deliveries."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from pals_agent.linked_chat import GENERATION_MODELS
from pals_agent.provider_usage import POLICY_V2, PRICING_PROFILE, ROLE_POLICY_V2, TARIFF_SNAPSHOTS
from pals_agent.token_meter import TokenMeter, TokenMeterApi, TokenMeterError, token_meter_scope


@contextmanager
def billing_stage(
    api: TokenMeterApi,
    context: dict[str, Any],
    *,
    scope: str,
    job_id: str,
    claim_id: str | None,
    task_id: str | None = None,
    timeout_seconds: float = 3600,
) -> Iterator[TokenMeter | None]:
    admitted = context.get("billing_context")
    if admitted is None:
        yield None
        return
    if not isinstance(admitted, dict):
        raise TokenMeterError("token_binding_invalid")
    if admitted.get("policy_version") == "utilization-v1-2026-09-30":
        yield None
        return
    request_id = context.get("proof_request_id")
    operation_id = admitted.get("operation_id")
    if (
        admitted.get("policy_version") != POLICY_V2
        or admitted.get("pricing_profile") != PRICING_PROFILE
        or admitted.get("generation_model") not in GENERATION_MODELS
        or admitted.get("generation_model") != context.get("generation_model")
        or admitted.get("role_policy_version") != ROLE_POLICY_V2
        or admitted.get("price_snapshot_ids") != TARIFF_SNAPSHOTS
        or not isinstance(request_id, str)
        or not isinstance(operation_id, str)
        or not isinstance(claim_id, str)
    ):
        raise TokenMeterError("token_binding_invalid")
    try:
        for value in (request_id, operation_id, claim_id):
            if str(UUID(value)) != value:
                raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise TokenMeterError("token_binding_invalid") from None
    meter = TokenMeter(
        api,
        operation_id,
        request_id,
        claim_id,
        time.monotonic() + timeout_seconds,
        policy_version=POLICY_V2,
        scope=scope,
        job_id=job_id,
        task_id=task_id,
    )
    with token_meter_scope(meter):
        yield meter
