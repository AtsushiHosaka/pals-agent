"""A generation claim answered with HTTP 5xx returns the receipt soon, within a bound (pals#451).

Without this, the claim lease's one-hour visibility hid the receipt for an hour after the API
returned a 500 for a job whose Lean check had finished.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from pals_agent.api_client import PalsApiError
from pals_agent.settings import AgentSettings
from pals_agent.worker import SqsProofWorker

CLAIM_ID = "11111111-1111-4111-8111-111111111111"


class Api:
    def __init__(self, error: Exception | None) -> None:
        self.error = error
        self.claims = 0

    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        return {
            "id": proof_job_id,
            "job_id": proof_job_id,
            "state": "queued",
            "chat_id": "chat-1",
            "output_language": "en",
            "theorem_statement": "theorem t : True := by trivial",
            "request_context": {},
            "diagnostics": [],
        }

    def acquire_proof_generation_claim(self, **_kwargs: Any) -> dict[str, Any]:
        self.claims += 1
        assert self.error is not None
        raise self.error


def run(error: Exception | None, attempt: int | None) -> tuple[bool, list[int]]:
    seconds: list[int] = []
    worker = SqsProofWorker(
        settings=cast(
            AgentSettings,
            SimpleNamespace(explanation_model_timeout_seconds=30, max_repair_attempts=12),
        ),
        api_client=cast(Any, Api(error)),
        pipeline=None,
        explainer=None,
    )
    acknowledged = worker.process_proof_job(
        "job-1",
        claim_id=CLAIM_ID,
        extend_visibility=seconds.append,
        delivery_attempt=attempt,
    )
    return acknowledged, seconds


@pytest.mark.parametrize("status", [500, 502, 503])
def test_a_5xx_returns_the_receipt_after_a_short_visibility(status: int) -> None:
    acknowledged, seconds = run(PalsApiError("boom", status_code=status), 1)
    assert acknowledged is False  # never deleted
    assert seconds == [30]


def test_the_short_visibility_stops_after_the_receive_limit() -> None:
    assert run(PalsApiError("boom", status_code=500), 5)[1] == [30]
    assert run(PalsApiError("boom", status_code=500), 6) == (False, [])


def test_an_unknown_receive_count_keeps_the_previous_behaviour() -> None:
    assert run(PalsApiError("boom", status_code=500), None) == (False, [])


@pytest.mark.parametrize(
    "error",
    [
        PalsApiError("refused", status_code=409),
        PalsApiError("bad", status_code=422),
        PalsApiError("not found", status_code=404),
        PalsApiError("transport"),
        RuntimeError("transport"),
    ],
)
def test_other_failures_do_not_change_visibility(error: Exception) -> None:
    assert run(error, 1) == (False, [])
