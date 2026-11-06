"""A proof job whose deliveries fail closed on its own data must reach a terminal state.

The queue's receive count is the only state that survives a worker restart, so the worker
reports it. The worker never takes a generation claim for this: it tells the API the count and
what it saw, and the API decides. A refusal therefore leaves nothing held, and a later delivery
asks again.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast

import pytest

from pals_agent.api_client import PalsApiError
from pals_agent.settings import AgentSettings
from pals_agent.worker import SqsProofWorker

CLAIM_ID = "11111111-1111-4111-8111-111111111111"
CANDIDATE_ID = "22222222-2222-4222-8222-222222222222"
SESSION_ID = "33333333-3333-4333-8333-333333333333"
REQUEST_ID = "44444444-4444-4444-8444-444444444444"
LEAN_CODE = "theorem sample : True := by\n  trivial"
ARTIFACT = "s3://pals-artifacts/proof-jobs/job-1/result.lean"

def semantic_review_job(**changes: Any) -> dict[str, Any]:
    job: dict[str, Any] = {
        "id": "job-1",
        "job_id": "job-1",
        "state": "semantic_review",
        "chat_id": "chat-1",
        "output_language": "en",
        "theorem_statement": "theorem sample : True := by trivial",
        "request_context": {"formal_statement": "True"},
        "lean_code": LEAN_CODE,
        "result_artifact_uri": ARTIFACT,
        "status_context": {
            "target_declaration": {"kind": "theorem", "name": "sample", "proposition": "True"}
        },
        "diagnostics": [],
        "verification_candidate_id": CANDIDATE_ID,
        "verification_candidate_state": "semantic_review",
        "generation_session_id": SESSION_ID,
    }
    job.update(changes)
    return job


def compile_failed_job(**changes: Any) -> dict[str, Any]:
    """The API kept a failed candidate but stored no complete repair seed."""

    job: dict[str, Any] = {
        "id": "job-1",
        "job_id": "job-1",
        "state": "compiling",
        "chat_id": "chat-1",
        "output_language": "en",
        "theorem_statement": "theorem sample : True := by trivial",
        "request_context": {},
        "lean_code": LEAN_CODE,
        "result_artifact_uri": ARTIFACT,
        "status_context": {"stage": "compiling"},
        "verification_candidate_id": CANDIDATE_ID,
        "verification_candidate_state": "verification_failed",
        "diagnostics": [
            {"severity": "error", "message": "Lean verification failed.",
             "code": "verifier_compile_failed"}
        ],
        "generation_session_id": None,
    }
    job.update(changes)
    return job


class Api:
    def __init__(self, job: dict[str, Any], *, binding: Any = "match") -> None:
        self.job = job
        self.binding = binding
        self.terminalizations: list[dict[str, Any]] = []
        self.terminalize_errors: list[Exception] = []
        self.response: Any = {"outcome": "terminalized"}

    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        return deepcopy(self.job)

    def get_proof_job_chat_input(self, proof_job_id: str) -> dict[str, Any]:
        return {}

    def get_verification_candidate_binding(self, **kwargs: Any) -> dict[str, Any]:
        if isinstance(self.binding, Exception):
            raise self.binding
        lean_sha = (
            "0" * 64
            if self.binding == "mismatch"
            else hashlib.sha256(LEAN_CODE.encode()).hexdigest()
        )
        result = {
            "schema_version": "pals.verification-candidate-binding.v1",
            **kwargs,
            "mutation_claim_id": SESSION_ID,
            "lean_sha256": lean_sha,
            "result_artifact_uri": ARTIFACT,
            "source_binding_sha256": None,
            "candidate_status": "semantic_review",
        }
        if self.binding == "unknown_shape":
            result["new_field_from_a_newer_api"] = 1
        if self.binding == "unknown_status":
            result["candidate_status"] = "quarantined"
        return result

    def retry_verification_candidate_reconciliation(self, **kwargs: Any) -> dict[str, Any]:
        raise PalsApiError("reconciliation unavailable")

    def terminalize_stalled_proof_job(
        self, *, proof_job_id: str, receive_count: int, observed: dict[str, Any]
    ) -> dict[str, Any]:
        self.terminalizations.append(
            {"proof_job_id": proof_job_id, "receive_count": receive_count, "observed": observed}
        )
        if self.terminalize_errors:
            raise self.terminalize_errors.pop(0)
        return cast(dict[str, Any], self.response)

    # A worker must never take a claim or write the job itself to end it.
    def acquire_proof_generation_claim(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("terminalization must not take a generation claim")

    def update_proof_job(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("terminalization must not write the job itself")


class Reviewer:
    def review_proof(self, **_kwargs: Any) -> Any:
        raise AssertionError("a structurally invalid delivery must never reach the reviewer")


def worker(api: Api, **settings: Any) -> SqsProofWorker:
    return SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(
            explanation_model_timeout_seconds=30, max_repair_attempts=12, **settings
        )),
        api_client=cast(Any, api),
        pipeline=None,
        explainer=None,
        proof_reviewer=cast(Any, Reviewer()),
    )


def process(w: SqsProofWorker, attempt: int | None, *, visibility: Any = None) -> bool:
    return w.process_proof_job(
        "job-1",
        claim_id=CLAIM_ID,
        extend_visibility=visibility if visibility is not None else (lambda _seconds: None),
        delivery_attempt=attempt,
    )


# What the job's own stored data makes impossible for every worker version.
STRUCTURAL = {
    "compile_failure_without_any_repair_seed_fields": lambda: compile_failed_job(),
    "compile_failure_with_wrong_stage": lambda: compile_failed_job(
        status_context={"stage": "failed"}),
    "compile_failure_with_non_integer_budget": lambda: compile_failed_job(
        status_context={"stage": "compiling", "attempt_evidence": {}, "repairs_used": "0",
                        "max_repair_attempts": 12, "verification_elapsed_ms": 1}),
    "semantic_blank_lean_code": lambda: semantic_review_job(lean_code="  "),
    "semantic_missing_candidate_id": lambda: semantic_review_job(verification_candidate_id=None),
    "semantic_missing_generation_session": lambda: semantic_review_job(
        generation_session_id=None),
    "semantic_no_stored_target": lambda: semantic_review_job(status_context={}),
    "semantic_missing_artifact": lambda: semantic_review_job(result_artifact_uri=None),
    "linked_request_id_not_text": lambda: compile_failed_job(
        state="queued", verification_candidate_id=None, verification_candidate_state=None,
        diagnostics=[], request_context={"proof_request_id": 7}),
}


@pytest.mark.parametrize("name", STRUCTURAL)
@pytest.mark.parametrize("attempt", [None, 1, 2])
def test_structural_failure_before_the_third_delivery_is_left_for_redelivery(
    name: str, attempt: int | None
) -> None:
    api = Api(STRUCTURAL[name]())

    assert process(worker(api), attempt) is False
    assert api.terminalizations == []


@pytest.mark.parametrize("name", STRUCTURAL)
@pytest.mark.parametrize("attempt", [3, 4, 5])
def test_structural_failure_on_a_late_delivery_asks_the_api_without_a_claim(
    name: str, attempt: int
) -> None:
    api = Api(STRUCTURAL[name]())

    assert process(worker(api), attempt) is True

    (call,) = api.terminalizations
    assert call["proof_job_id"] == "job-1" and call["receive_count"] == attempt
    job = api.job
    assert call["observed"] == {
        "state": job["state"],
        "verification_candidate_id": job["verification_candidate_id"],
        "verification_candidate_state": job["verification_candidate_state"],
        "lean_sha256": hashlib.sha256(job["lean_code"].encode()).hexdigest(),
    }


def test_the_request_names_the_job_by_scalars_and_never_by_content() -> None:
    api = Api(compile_failed_job())

    process(worker(api), 3)

    (call,) = api.terminalizations
    assert set(call) == {"proof_job_id", "receive_count", "observed"}
    assert set(call["observed"]) == {
        "state", "verification_candidate_id", "verification_candidate_state", "lean_sha256",
    }
    assert LEAN_CODE not in str(call) and "theorem" not in str(call)


def test_an_already_finished_job_is_acknowledged() -> None:
    api = Api(compile_failed_job())
    api.response = {"outcome": "already_terminal"}

    assert process(worker(api), 3) is True


@pytest.mark.parametrize(
    "error",
    [
        PalsApiError("refused", status_code=409, error_code="proof_job_not_terminalizable"),
        PalsApiError("an API that does not have the route yet", status_code=404),
        PalsApiError("api down", status_code=503),
        RuntimeError("transport"),
    ],
)
def test_a_refusal_or_outage_leaves_the_delivery_for_the_next_one_with_nothing_held(
    error: Exception,
) -> None:
    api = Api(compile_failed_job())
    api.terminalize_errors = [error]

    first = process(worker(api), 3)
    second = process(worker(api), 4)  # the next delivery asks again and succeeds

    assert (first, second) == (False, True)
    assert [call["receive_count"] for call in api.terminalizations] == [3, 4]


@pytest.mark.parametrize("response", [{}, {"outcome": "refused"}, {"outcome": 1}])
def test_an_unrecognized_answer_is_not_an_acknowledgement(response: Any) -> None:
    api = Api(compile_failed_job())
    api.response = response

    assert process(worker(api), 3) is False


# Reasons that depend on this worker's version or configuration, or that may be transient.
NOT_STRUCTURAL = {
    "seed_present_but_unreadable_by_this_version": lambda: compile_failed_job(
        status_context={"stage": "compiling", "attempt_evidence": {"attempt": 1},
                        "repairs_used": 0, "max_repair_attempts": 12,
                        "verification_elapsed_ms": 5}),
    "semantic_candidate_id_in_an_unknown_format": lambda: semantic_review_job(
        verification_candidate_id="not-a-uuid4"),
    "semantic_generation_session_in_an_unknown_format": lambda: semantic_review_job(
        generation_session_id="nope"),
    "semantic_target_that_this_parser_extracts_differently": lambda: semantic_review_job(
        status_context={"target_declaration": {
            "kind": "theorem", "name": "other", "proposition": "False"}}),
    "linked_request_id_in_an_unknown_format": lambda: compile_failed_job(
        state="queued", verification_candidate_id=None, verification_candidate_state=None,
        diagnostics=[], request_context={"proof_request_id": "not-a-uuid"}),
    "model_this_worker_does_not_know": lambda: compile_failed_job(
        state="queued", verification_candidate_id=None, verification_candidate_state=None,
        diagnostics=[], request_context={"generation_model": "gpt-7-from-the-future"}),
    "verified_job": lambda: semantic_review_job(state="verified", lean_code=""),
    "pending_api_compile": lambda: compile_failed_job(
        verification_candidate_state="compiling",
        diagnostics=[{"severity": "info", "message": "Verification is pending.",
                      "code": "pals.verification_pending"}]),
}


@pytest.mark.parametrize("name", NOT_STRUCTURAL)
def test_what_a_newer_worker_or_a_retry_could_handle_is_never_terminalized(name: str) -> None:
    api = Api(NOT_STRUCTURAL[name]())

    assert process(worker(api), 5) is False
    assert api.terminalizations == []


def test_chat_input_this_version_rejects_is_not_a_verdict_about_the_job() -> None:
    job = compile_failed_job(
        state="queued", verification_candidate_id=None, verification_candidate_state=None,
        diagnostics=[],
        request_context={"chat_route": {"schema_version": "pals.chat-route.v9"},
                         "generation_model": "gpt-6-luna"},
    )
    api = Api(job)

    assert process(worker(api), 5) is False
    assert api.terminalizations == []


def test_a_binding_that_names_other_evidence_is_terminalized() -> None:
    api = Api(semantic_review_job(), binding="mismatch")

    assert process(worker(api), 3) is True
    assert len(api.terminalizations) == 1


@pytest.mark.parametrize(
    "binding", [PalsApiError("api down"), "unknown_shape", "unknown_status"]
)
def test_a_binding_the_api_cannot_provide_or_in_an_unknown_shape_is_not_a_job_defect(
    binding: Any,
) -> None:
    api = Api(semantic_review_job(), binding=binding)

    assert process(worker(api), 5) is False
    assert api.terminalizations == []


def test_local_review_configuration_is_not_a_job_defect() -> None:
    api = Api(semantic_review_job())
    w = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(
            explanation_model_timeout_seconds=0, max_repair_attempts=12)),
        api_client=cast(Any, api), pipeline=None, explainer=None,
        proof_reviewer=cast(Any, Reviewer()),
    )

    assert process(w, 5) is False
    assert api.terminalizations == []


def test_visibility_that_cannot_be_extended_is_not_a_job_defect() -> None:
    api = Api(semantic_review_job())

    def denied(_seconds: int) -> None:
        raise RuntimeError("sqs unavailable")

    assert process(worker(api), 5, visibility=denied) is False
    assert api.terminalizations == []


@pytest.mark.parametrize("state", ["failed", "canceled"])
def test_a_terminal_job_is_acknowledged_without_asking_the_api(state: str) -> None:
    api = Api(compile_failed_job(state=state))

    assert process(worker(api), 5) is True
    assert api.terminalizations == []


def test_the_worker_has_no_terminalization_path_that_takes_a_claim() -> None:
    import inspect

    from pals_agent import worker as module

    source = inspect.getsource(module.SqsProofWorker._terminalize_no_progress)
    assert "acquire_proof_generation_claim" not in source
    assert "update_proof_job" not in source


def test_run_once_passes_the_queue_receive_count_to_the_proof_job(monkeypatch: Any) -> None:
    from pals_agent import worker as worker_module

    seen: list[int | None] = []

    class Queue:
        deleted: list[Any] = []

        def receive_message(self, **_kwargs: Any) -> dict[str, Any]:
            return {"Messages": [{
                "MessageId": "m", "ReceiptHandle": "r", "Body": "job-1",
                "MessageAttributes": {"task": {"StringValue": "job-1"}},
                "Attributes": {"SentTimestamp": "1", "ApproximateReceiveCount": "4"},
            }]}

        def change_message_visibility(self, **_kwargs: Any) -> None: ...

        def delete_message(self, **kwargs: Any) -> None:
            self.deleted.append(kwargs)

    queue = Queue()
    monkeypatch.setattr(worker_module.boto3, "client", lambda *a, **kw: queue)
    monkeypatch.setattr(
        worker_module,
        "parse_sqs_agent_message",
        lambda _message: (worker_module.AgentTask(kind="proof", id="job-1"), "r"),
    )

    class Recorder(SqsProofWorker):
        def process_proof_job(self, proof_job_id: str, **kwargs: Any) -> bool:
            seen.append(kwargs.get("delivery_attempt"))
            return True

    w = Recorder(
        settings=cast(AgentSettings, SimpleNamespace(
            proof_jobs_queue_url="q", proof_requests_queue_url=None, aws_endpoint_url=None,
            aws_region="ap-northeast-1")),
        api_client=None, pipeline=None, explainer=None,
    )

    assert w.run_once() is True
    assert seen == [4]
    assert queue.deleted == [{"QueueUrl": "q", "ReceiptHandle": "r"}]


def test_the_client_posts_only_the_documented_body_and_no_claim() -> None:
    from pals_agent.api_client import PalsApiClient

    sent: list[dict[str, Any]] = []

    class Transport:
        def request(self, **kwargs: Any) -> Any:
            sent.append(kwargs)
            return SimpleNamespace(status_code=200, body=b'{"outcome":"terminalized"}')

    client = PalsApiClient(
        base_url="http://api.invalid", worker_secret="s", transport=cast(Any, Transport())
    )

    result = client.terminalize_stalled_proof_job(
        proof_job_id="job-1", receive_count=3,
        observed={"state": "compiling", "verification_candidate_id": None,
                  "verification_candidate_state": None, "lean_sha256": None},
    )

    assert result == {"outcome": "terminalized"}
    (request,) = sent
    assert request["method"] == "POST"
    assert request["url"].endswith("/v1/internal/proof-jobs/job-1/no-progress-terminalizations")
    import json

    assert set(json.loads(request["body"])) == {"receive_count", "observed"}
    assert request["headers"]["X-PALS-Worker-Secret"] == "s"
