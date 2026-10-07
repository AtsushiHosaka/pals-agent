"""Call scopes shared by request-linked Lean generation and explanation phases."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from pals_agent.input_fence import input_fence_scope
from pals_agent.proof_reuse_usage import model_role
from pals_agent.token_meter import TokenMeter, TokenMeterError, token_meter_scope

_job: ContextVar[dict[str, Any] | None] = ContextVar("pals_linked_job", default=None)


def metered_linked_job() -> bool:
    job = _job.get()
    return job is not None and job.get("billing_operation_id") is not None


@contextmanager
def linked_job_scope(job: dict[str, Any]) -> Iterator[None]:
    token = _job.set(job)
    try:
        yield
    finally:
        _job.reset(token)


@contextmanager
def linked_call_scope(
    api: Any, claim_id: str, deadline: float, *, role: str = "prove"
) -> Iterator[None]:
    job = _job.get()
    if job is None or "proof_request_id" not in job:
        yield
        return
    request_id = job["proof_request_id"]
    generation = job.get("input_generation")
    job_id = job.get("id")
    if (
        not isinstance(request_id, str) or not isinstance(job_id, str)
        or type(generation) is not int or generation < 1
    ):
        raise TokenMeterError("linked_request_binding_invalid")
    with model_role(role), input_fence_scope(lambda: api.check_proof_request_claim(
        request_id=request_id, claim_id=claim_id, input_generation=generation,
        proof_job_id=job_id,
    )):
        operation_id = job.get("billing_operation_id")
        if operation_id is None:
            yield
        else:
            meter = TokenMeter(
                api, operation_id, request_id, claim_id, deadline,
                binding_kind="lean", input_generation=generation, proof_job_id=job_id,
            )
            with token_meter_scope(meter):
                yield
            if meter.failed:
                raise TokenMeterError("linked_request_meter_failed")
