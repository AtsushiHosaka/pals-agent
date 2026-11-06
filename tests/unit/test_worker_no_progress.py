"""A proof job whose deliveries fail closed on its own data must reach a terminal state.

The queue's receive count is the only state that survives a worker restart, so the decision
is made from it; a live generation claim or an API-owned compile always defers the decision.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast

import pytest

from pals_agent.api_client import PalsApiError
from pals_agent.models import Diagnostic, ProofJobState
from pals_agent.settings import AgentSettings
from pals_agent.worker import SqsProofWorker

CLAIM_ID = "11111111-1111-4111-8111-111111111111"
CANDIDATE_ID = "22222222-2222-4222-8222-222222222222"
SESSION_ID = "33333333-3333-4333-8333-333333333333"
REQUEST_ID = "44444444-4444-4444-8444-444444444444"
LEAN_CODE = "theorem sample : True := by\n  trivial"
ARTIFACT = "s3://pals-artifacts/proof-jobs/job-1/result.lean"

MESSAGES = {
    "en": "Proof verification could not continue and was stopped.",
    "ja": "検証を続けられなかったため、処理を終了しました。",
    "zh-Hans": "验证无法继续，已终止处理。",
    "zh-Hant": "驗證無法繼續，已終止處理。",
}


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
        self.reads = 0
        self.claims: list[str] = []
        self.updates: list[dict[str, Any]] = []
        self.claim_status = "acquired"
        self.claim_error: Exception | None = None
        self.update_failures = 0
        self.job_after_claim: dict[str, Any] | None = None
        self.reconciliation_retries = 0

    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        self.reads += 1
        return deepcopy(self.job)

    def get_proof_job_chat_input(self, proof_job_id: str) -> dict[str, Any]:
        return {}

    def get_verification_candidate_binding(self, **kwargs: Any) -> dict[str, Any]:
        if isinstance(self.binding, Exception):
            raise self.binding
        if self.binding == "mismatch":
            lean_sha = "0" * 64
        else:
            lean_sha = hashlib.sha256(LEAN_CODE.encode()).hexdigest()
        return {
            "schema_version": "pals.verification-candidate-binding.v1",
            **kwargs,
            "mutation_claim_id": SESSION_ID,
            "lean_sha256": lean_sha,
            "result_artifact_uri": ARTIFACT,
            "source_binding_sha256": None,
            "candidate_status": "semantic_review",
        }

    def retry_verification_candidate_reconciliation(self, **kwargs: Any) -> dict[str, Any]:
        self.reconciliation_retries += 1
        raise PalsApiError("reconciliation unavailable")

    def acquire_proof_generation_claim(self, *, proof_job_id: str, claim_id: str,
                                       required_lease_ms: int = 3_600_000) -> dict[str, Any]:
        self.claims.append(claim_id)
        if self.claim_error is not None:
            raise self.claim_error
        resource = deepcopy(self.job_after_claim or self.job)
        if self.claim_status == "terminal":
            resource["state"] = "failed"
        else:
            # The API reports the job's current claim as its generation session.
            resource["generation_session_id"] = claim_id
        return {
            "claim_status": self.claim_status,
            "lease_remaining_ms": None if self.claim_status == "terminal" else 3_600_000,
            "resource": resource,
        }

    def update_proof_job(
        self, *, proof_job_id: str, claim_id: str, state: ProofJobState,
        diagnostics: list[Diagnostic], result_artifact_uri: str | None,
        lean_code: str | None, context: dict[str, Any],
    ) -> dict[str, Any]:
        if self.update_failures:
            self.update_failures -= 1
            raise PalsApiError("temporarily unavailable")
        self.updates.append({
            "proof_job_id": proof_job_id, "claim_id": claim_id, "state": state,
            "diagnostics": diagnostics, "result_artifact_uri": result_artifact_uri,
            "lean_code": lean_code, "context": context,
        })
        return {"update_status": "terminal", "lease_remaining_ms": None}


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


STRUCTURAL = {
    "compile_failure_without_repair_seed": lambda: compile_failed_job(),
    "semantic_blank_lean_code": lambda: semantic_review_job(lean_code="  "),
    "semantic_bad_candidate_id": lambda: semantic_review_job(verification_candidate_id="nope"),
    "semantic_missing_generation_session": lambda: semantic_review_job(
        generation_session_id=None),
    "semantic_lean_without_target": lambda: semantic_review_job(
        lean_code="def x := 1", status_context={}),
    "semantic_missing_artifact": lambda: semantic_review_job(result_artifact_uri=None),
    "invalid_linked_request_id": lambda: compile_failed_job(
        state="queued", verification_candidate_id=None, verification_candidate_state=None,
        diagnostics=[], request_context={"proof_request_id": "not-a-uuid"}),
}


@pytest.mark.parametrize("name", STRUCTURAL)
@pytest.mark.parametrize("attempt", [None, 1, 2])
def test_structural_failure_before_the_third_delivery_is_left_for_redelivery(
    name: str, attempt: int | None
) -> None:
    api = Api(STRUCTURAL[name]())

    assert process(worker(api), attempt) is False
    assert api.claims == [] and api.updates == []


@pytest.mark.parametrize("name", STRUCTURAL)
@pytest.mark.parametrize("attempt", [3, 4, 5])
def test_structural_failure_on_a_late_delivery_fails_the_job_with_a_typed_diagnostic(
    name: str, attempt: int
) -> None:
    api = Api(STRUCTURAL[name]())

    assert process(worker(api), attempt) is True

    assert api.claims == [CLAIM_ID]
    (update,) = api.updates
    assert update["state"] == "failed"
    assert update["claim_id"] == CLAIM_ID
    assert [(d.severity, d.code, d.message) for d in update["diagnostics"]] == [
        ("error", "pals.proof_job_no_progress", MESSAGES["en"])
    ]
    assert update["context"]["stage"] == "failed"
    assert update["context"]["schema_version"] == "pals.proof-status-context.v1"
    assert update["context"]["termination_reason"] == "non_repairable_failure"
    # Evidence that was already stored must survive the terminal write.
    assert update["lean_code"] == api.job["lean_code"]
    assert update["result_artifact_uri"] == api.job["result_artifact_uri"]


@pytest.mark.parametrize("language", sorted(MESSAGES))
def test_failure_diagnostic_is_localized_to_the_job_language(language: str) -> None:
    api = Api(compile_failed_job(output_language=language))

    assert process(worker(api), 3) is True

    (diagnostic,) = api.updates[0]["diagnostics"]
    assert (diagnostic.code, diagnostic.message) == ("pals.proof_job_no_progress",
                                                     MESSAGES[language])


def test_a_live_generation_claim_defers_the_decision() -> None:
    api = Api(compile_failed_job())
    api.claim_status = "busy"

    assert process(worker(api), 5) is False
    assert api.updates == []


def test_a_job_that_became_terminal_is_acknowledged_without_a_write() -> None:
    api = Api(compile_failed_job())
    api.claim_status = "terminal"

    assert process(worker(api), 3) is True
    assert api.updates == []


@pytest.mark.parametrize(
    "error", [PalsApiError("api down"), RuntimeError("unexpected"), ValueError("malformed")]
)
def test_an_unavailable_claim_api_never_terminalizes(error: Exception) -> None:
    api = Api(compile_failed_job())
    api.claim_error = error

    assert process(worker(api), 5) is False
    assert api.updates == []


def test_a_job_that_changed_between_read_and_claim_is_not_failed() -> None:
    api = Api(compile_failed_job())
    api.job_after_claim = compile_failed_job(state="repairing", verification_candidate_state=None)

    assert process(worker(api), 4) is False
    assert api.updates == []


def test_a_job_that_changes_before_the_claim_is_not_claimed() -> None:
    api = Api(compile_failed_job())
    original = api.get_proof_job
    reads = []

    def read(proof_job_id: str) -> dict[str, Any]:
        reads.append(proof_job_id)
        if len(reads) > 1:
            api.job = compile_failed_job(state="repairing", verification_candidate_state=None)
        return original(proof_job_id)

    api.get_proof_job = read  # type: ignore[method-assign]

    assert process(worker(api), 4) is False
    assert api.claims == [] and api.updates == []


def test_a_transient_terminal_write_failure_is_retried_on_the_same_claim() -> None:
    api = Api(compile_failed_job())
    api.update_failures = 2

    assert process(worker(api), 3) is True
    assert api.claims == [CLAIM_ID] and len(api.updates) == 1


def test_a_persistent_terminal_write_failure_leaves_the_delivery_for_redelivery() -> None:
    api = Api(compile_failed_job())
    api.update_failures = 3

    assert process(worker(api), 3) is False
    assert api.updates == []


def test_a_semantic_review_binding_the_api_cannot_provide_is_not_a_job_defect() -> None:
    api = Api(semantic_review_job(), binding=PalsApiError("api down"))

    assert process(worker(api), 5) is False
    assert api.claims == [] and api.updates == []


def test_a_semantic_review_binding_that_does_not_match_the_job_is_terminalized() -> None:
    api = Api(semantic_review_job(), binding="mismatch")

    assert process(worker(api), 3) is True
    assert api.updates[0]["state"] == "failed"
    assert api.updates[0]["lean_code"] == LEAN_CODE


def test_local_review_configuration_is_not_a_job_defect() -> None:
    api = Api(semantic_review_job())
    w = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(
            explanation_model_timeout_seconds=0, max_repair_attempts=12)),
        api_client=cast(Any, api), pipeline=None, explainer=None,
        proof_reviewer=cast(Any, Reviewer()),
    )

    assert process(w, 5) is False
    assert api.claims == [] and api.updates == []


def test_visibility_that_cannot_be_extended_is_not_a_job_defect() -> None:
    api = Api(semantic_review_job())

    def denied(_seconds: int) -> None:
        raise RuntimeError("sqs unavailable")

    assert process(worker(api), 5, visibility=denied) is False
    assert api.claims == [] and api.updates == []


def test_a_pending_api_owned_compile_is_never_terminalized() -> None:
    api = Api(compile_failed_job(
        verification_candidate_state="compiling",
        diagnostics=[{"severity": "info", "message": "Verification is pending.",
                      "code": "pals.verification_pending"}],
    ))

    assert process(worker(api), 5) is False
    assert api.claims == [] and api.updates == []


def test_a_verified_job_is_never_failed() -> None:
    api = Api(semantic_review_job(state="verified", lean_code=""))

    assert process(worker(api), 5) is False
    assert api.claims == [] and api.updates == []


@pytest.mark.parametrize("state", ["failed", "canceled"])
def test_a_terminal_job_is_acknowledged_without_claim_or_write(state: str) -> None:
    api = Api(compile_failed_job(state=state))

    assert process(worker(api), 5) is True
    assert api.claims == [] and api.updates == []


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
