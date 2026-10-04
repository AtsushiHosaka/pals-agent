from __future__ import annotations

import hashlib
import json
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
import rfc8785

from pals_agent import explanations
from pals_agent.api_client import PalsApiError
from pals_agent.explanations import (
    ExplanationSection,
    LeanLineReference,
    ProofClarification,
    ProofExplanation,
    ProofOutputReview,
)
from pals_agent.settings import AgentSettings
from pals_agent.worker import SqsProofWorker, _parse_claim_envelope, parse_sqs_agent_message

CLAIM_IDS = (
    uuid.UUID("11111111-1111-4111-8111-111111111111"),
    uuid.UUID("22222222-2222-4222-8222-222222222222"),
    uuid.UUID("33333333-3333-4333-8333-333333333333"),
)
LEAN_CODE = "example : True := by\n  trivial"


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class UuidFactory:
    def __init__(self) -> None:
        self.values = list(CLAIM_IDS)

    def __call__(self) -> uuid.UUID:
        return self.values.pop(0)


class FakeSqs:
    def __init__(
        self,
        *bodies: str,
        clock: FakeClock | None = None,
        visibility_delay: float = 0.0,
        visibility_error: Exception | None = None,
    ) -> None:
        self.bodies = list(bodies)
        self.clock = clock
        self.visibility_delay = visibility_delay
        self.visibility_error = visibility_error
        self.visibility_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []

    def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        if not self.bodies:
            return {}
        body = self.bodies.pop(0)
        return {
            "Messages": [
                {
                    "Body": body,
                    "MessageId": f"message-{len(self.bodies)}",
                    "ReceiptHandle": f"PRIVATE-RECEIPT-{len(self.bodies)}",
                    "MessageAttributes": (
                        {}
                        if body.startswith("{")
                        else {
                            "proof_job_id": {
                                "DataType": "String",
                                "StringValue": body,
                            }
                        }
                    ),
                }
            ]
        }

    def change_message_visibility(self, **kwargs: Any) -> None:
        self.visibility_calls.append(kwargs)
        if self.clock is not None:
            self.clock.advance(self.visibility_delay)
        if self.visibility_error is not None:
            raise self.visibility_error

    def delete_message(self, **kwargs: Any) -> None:
        self.delete_calls.append(kwargs)


def _explanation() -> ProofExplanation:
    reference = LeanLineReference(2, 2, "  trivial")
    return ProofExplanation(
        overview="証明の概要です。",
        sections=(
            ExplanationSection(
                id="finish",
                title="証明を閉じる",
                summary="この命題は追加の仮定なしに成り立つことを確認します。",
                references=(reference,),
            ),
        ),
        conclusion="したがって True が証明されました。",
        model="explain-model",
        provider="test-provider",
        prompt="PRIVATE PROMPT",
        raw_model_output="PRIVATE RAW OUTPUT",
        elapsed_ms=2,
    )


class RecordingExplainer:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.explain_calls: list[dict[str, Any]] = []
        self.clarify_calls: list[dict[str, Any]] = []

    def explain(self, **kwargs: Any) -> ProofExplanation:
        self.explain_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return _explanation()

    def clarify(self, **kwargs: Any) -> ProofClarification:
        self.clarify_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return ProofClarification(
            section_id="finish",
            question="なぜこの命題は追加の仮定なしに成り立つのですか？",
            answer=(
                "詳しく見ると、この命題は前提を追加しなくても成り立つ形です。"
                "したがって、残っている目標がそのまま正しいことを確認できます。"
            ),
            key_points=("ゴールは True です。", "標準規則で閉じます。"),
            references=(LeanLineReference(2, 2, "  trivial"),),
            model="explain-model",
            provider="test-provider",
            prompt="PRIVATE PROMPT",
            raw_model_output="PRIVATE RAW OUTPUT",
            elapsed_ms=3,
        )


class RecordingOutputReviewer:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.explanation_calls: list[dict[str, Any]] = []
        self.clarification_calls: list[dict[str, Any]] = []

    def review_explanation(self, **kwargs: Any) -> ProofOutputReview:
        self.explanation_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return ProofOutputReview(
            kind="explanation",
            reviewer_provider="test-reviewer",
            reviewer_model="review-model",
            session_id="33333333-3333-4333-8333-333333333333",
            rationale="The explanation is grounded in the verified Lean source.",
        )

    def review_clarification(self, **kwargs: Any) -> ProofOutputReview:
        self.clarification_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return ProofOutputReview(
            kind="clarification",
            reviewer_provider="test-reviewer",
            reviewer_model="review-model",
            session_id="33333333-3333-4333-8333-333333333333",
            rationale="The clarification is grounded in the verified Lean source.",
        )


class PipelineThatMustNotRun:
    def run_statement(self, **kwargs: Any) -> Any:
        raise AssertionError(f"unexpected proof pipeline call: {kwargs}")


class ClaimApi:
    def __init__(
        self,
        *,
        claim_response: dict[str, Any] | Exception,
        clock: FakeClock | None = None,
        claim_delay: float = 0.0,
        terminal_response: dict[str, Any] | Exception | None = None,
        completed_error: Exception | None = None,
        proof_job_response: dict[str, Any] | None = None,
        output_language: str = "ja",
    ) -> None:
        self.claim_response = claim_response
        self.clock = clock
        self.claim_delay = claim_delay
        self.terminal_response = terminal_response
        self.completed_error = completed_error
        self.proof_job_response = proof_job_response
        self.output_language = output_language
        self.explanation_updates: list[dict[str, Any]] = []
        self.clarification_updates: list[dict[str, Any]] = []
        self.proof_job_reads: list[str] = []

    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        self.proof_job_reads.append(proof_job_id)
        if self.proof_job_response is not None:
            return self.proof_job_response
        return {
            "id": proof_job_id,
            "state": "verified",
            "theorem_statement": "True を証明せよ",
            "lean_code": LEAN_CODE,
            "output_language": self.output_language,
            "context": {},
        }

    def acquire_proof_generation_claim(
        self,
        *,
        proof_job_id: str,
        claim_id: str,
        required_lease_ms: int = 3_600_000,
    ) -> dict[str, Any]:
        raise AssertionError(
            f"unexpected proof generation claim: {proof_job_id} {claim_id} {required_lease_ms}"
        )

    def update_proof_job(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError(f"unexpected proof update: {kwargs}")

    def submit_verification_candidate(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError(f"unexpected verification candidate import: {kwargs}")

    def settle_proof_semantic_review(
        self,
        *,
        proof_job_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        _ = (proof_job_id, evidence)
        raise AssertionError("unexpected semantic review settlement")

    def upsert_proof_explanation(self, **kwargs: Any) -> dict[str, Any]:
        self.explanation_updates.append(kwargs)
        if kwargs["state"] == "generating":
            if self.clock is not None:
                self.clock.advance(self.claim_delay)
            if isinstance(self.claim_response, Exception):
                raise self.claim_response
            return self.claim_response
        if kwargs["state"] == "completed" and self.completed_error is not None:
            raise self.completed_error
        if isinstance(self.terminal_response, Exception):
            raise self.terminal_response
        return self.terminal_response or _envelope("terminal", None)

    def get_proof_clarification(self, clarification_id: str) -> dict[str, Any]:
        return {
            "dispatch_schema_version": "pals.proof-clarification-dispatch.v1",
            "id": clarification_id,
            "state": "queued",
            "proof_job_id": "proof-1",
            "output_language": self.output_language,
            "theorem_statement": "True を証明せよ",
            "lean_code": LEAN_CODE,
            "section_id": "finish",
            "selected_text": "この命題は追加の仮定なしに成り立つ",
            "after_clarification_id": None,
            "question": "なぜこの命題は追加の仮定なしに成り立つのですか？",
            "summary": {
                "overview": "証明の概要です。",
                "sections": [
                    {
                        "id": "finish",
                        "title": "証明を閉じる",
                        "summary": "この命題は追加の仮定なしに成り立つことを確認します。",
                        "references": [{"start_line": 2, "end_line": 2, "excerpt": "  trivial"}],
                    }
                ],
                "conclusion": "したがって True が証明されました。",
                "model": "explain-model",
                "provider": "test-provider",
                "elapsed_ms": 2,
            },
        }

    def update_proof_clarification(self, **kwargs: Any) -> dict[str, Any]:
        self.clarification_updates.append(kwargs)
        if kwargs["state"] == "generating":
            if self.clock is not None:
                self.clock.advance(self.claim_delay)
            if isinstance(self.claim_response, Exception):
                raise self.claim_response
            return self.claim_response
        if kwargs["state"] == "completed" and self.completed_error is not None:
            raise self.completed_error
        if isinstance(self.terminal_response, Exception):
            raise self.terminal_response
        return self.terminal_response or _envelope(
            "terminal",
            None,
            resource_kind="clarification",
        )


def _explanation_resource(
    *,
    proof_job_id: str = "proof-1",
    state: str = "generating",
) -> dict[str, Any]:
    content = None
    if state == "completed":
        content = {
            "overview": "証明の概要です。",
            "sections": [
                {
                    "id": "finish",
                    "title": "証明を閉じる",
                    "summary": "この命題は追加の仮定なしに成り立つことを確認します。",
                    "references": [{"start_line": 2, "end_line": 2, "excerpt": "  trivial"}],
                }
            ],
            "conclusion": "したがって True が証明されました。",
            "model": "explain-model",
            "provider": "test-provider",
            "elapsed_ms": 2,
        }
    return {
        "proof_job_id": proof_job_id,
        "state": state,
        "content": content,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "diagnostics": [],
    }


def _clarification_resource(
    *,
    clarification_id: str = "clarification-1",
    proof_job_id: str = "proof-1",
    state: str = "generating",
) -> dict[str, Any]:
    content = None
    if state == "completed":
        content = {
            "section_id": "finish",
            "question": "なぜこの命題は追加の仮定なしに成り立つのですか？",
            "answer": (
                "詳しく見ると、この命題は前提を追加しなくても成り立つ形です。"
                "したがって、残っている目標がそのまま正しいことを確認できます。"
            ),
            "key_points": ["ゴールは True です。", "標準規則で閉じます。"],
            "references": [{"start_line": 2, "end_line": 2, "excerpt": "  trivial"}],
            "model": "explain-model",
            "provider": "test-provider",
            "elapsed_ms": 3,
        }
    return {
        "id": clarification_id,
        "proof_job_id": proof_job_id,
        "section_id": "finish",
        "selected_text": "この命題は追加の仮定なしに成り立つ",
        "after_clarification_id": None,
        "question": "なぜこの命題は追加の仮定なしに成り立つのですか？",
        "state": state,
        "content": content,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "diagnostics": [],
    }


def _envelope(
    status: str,
    lease_remaining_ms: int | None,
    *,
    resource_kind: str = "explanation",
    resource_id: str | None = None,
) -> dict[str, Any]:
    state = {
        "acquired": "generating",
        "busy": "generating",
        "terminal": "completed",
        "not_ready": "queued",
        "lease_too_short": "queued",
    }[status]
    if status == "lease_too_short" and resource_kind == "explanation":
        resource = None
    elif resource_kind == "clarification":
        resource = _clarification_resource(
            clarification_id=resource_id or "clarification-1",
            state=state,
        )
    else:
        resource = _explanation_resource(
            proof_job_id=resource_id or "proof-1",
            state=state,
        )
    return {
        "claim_status": status,
        "lease_remaining_ms": lease_remaining_ms,
        "resource": resource,
    }


def _failed_terminal_envelope(
    *, resource_kind: str, resource_id: str | None = None
) -> dict[str, Any]:
    resource = (
        _clarification_resource(clarification_id=resource_id or "clarification-1", state="failed")
        if resource_kind == "clarification"
        else _explanation_resource(proof_job_id=resource_id or "proof-1", state="failed")
    )
    return {
        "claim_status": "terminal",
        "lease_remaining_ms": None,
        "resource": resource,
    }


def test_prx_042_accepts_the_current_api_proof_claim_resource_shape() -> None:
    resource = {
        "id": "proof-1",
        "job_id": "proof-1",
        "project_id": None,
        "chat_id": "chat-1",
        "output_language": "en",
        "theorem_statement": "Show that x squared is continuous.",
        "formal_statement": None,
        "state": "queued",
        "request_context": {},
        "status_context": None,
        "diagnostics": [],
        "result_artifact_uri": None,
        "lean_code": None,
        "verifier_attestation": None,
        "verification_candidate_id": None,
        "verification_candidate_state": None,
        "generation_session_id": "11111111-1111-4111-8111-111111111111",
    }

    envelope = _parse_claim_envelope(
        {
            "claim_status": "acquired",
            "lease_remaining_ms": 3_599_999,
            "resource": resource,
        },
        resource_kind="proof_job",
        resource_id="proof-1",
    )

    assert envelope.status == "acquired"
    assert envelope.lease_remaining_ms == 3_599_999

    resource["generation_session_id"] = "not-a-uuid"
    with pytest.raises(ValueError, match="proof generation session id"):
        _parse_claim_envelope(
            {
                "claim_status": "acquired",
                "lease_remaining_ms": 3_599_999,
                "resource": resource,
            },
            resource_kind="proof_job",
            resource_id="proof-1",
        )


def _settings(timeout: int = 90) -> AgentSettings:
    return cast(
        AgentSettings,
        SimpleNamespace(
            proof_jobs_queue_url="https://sqs.test/proof-jobs",
            aws_endpoint_url=None,
            aws_region="ap-northeast-1",
            worker_idle_sleep_seconds=0.0,
            explanation_model_timeout_seconds=timeout,
        ),
    )


def _worker(
    api: ClaimApi,
    explainer: RecordingExplainer,
    clock: FakeClock,
    *,
    timeout: int = 90,
    uuid_factory: UuidFactory | None = None,
    output_reviewer: RecordingOutputReviewer | None = None,
) -> SqsProofWorker:
    return SqsProofWorker(
        settings=_settings(timeout),
        api_client=api,
        pipeline=PipelineThatMustNotRun(),
        explainer=explainer,
        output_reviewer=output_reviewer or RecordingOutputReviewer(),
        monotonic=clock,
        uuid4_factory=uuid_factory or UuidFactory(),
    )


def _install_sqs(monkeypatch: pytest.MonkeyPatch, sqs: FakeSqs) -> None:
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *args, **kwargs: sqs)


@pytest.mark.parametrize(
    ("status", "lease", "expected_delete"),
    [
        ("busy", 600_000, False),
        ("terminal", None, True),
        ("lease_too_short", None, False),
    ],
)
def test_pae_015_claim_outcomes_gate_model_and_receipt(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    lease: int | None,
    expected_delete: bool,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs("proof-1")
    api = ClaimApi(claim_response=_envelope(status, lease))
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    assert _worker(api, explainer, clock).run_once() is True

    assert explainer.explain_calls == []
    assert bool(sqs.delete_calls) is expected_delete
    assert sqs.visibility_calls == []


def test_pae_015_each_receive_uses_a_fresh_uuid4_and_never_reuses_busy_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs("proof-1", "proof-1")
    api = ClaimApi(claim_response=_envelope("busy", 600_000))
    explainer = RecordingExplainer()
    factory = UuidFactory()
    worker = _worker(api, explainer, clock, uuid_factory=factory)
    _install_sqs(monkeypatch, sqs)

    worker.run_once()
    worker.run_once()

    claims = [update["claim_id"] for update in api.explanation_updates]
    assert claims == [str(CLAIM_IDS[0]), str(CLAIM_IDS[1])]
    assert len(set(claims)) == 2
    assert all(uuid.UUID(value).version == 4 for value in claims)
    assert explainer.explain_calls == []
    assert sqs.delete_calls == []


@pytest.mark.parametrize(
    ("timeout", "required_lease_ms", "visibility_seconds"),
    [(1, 35_000, 65), (90, 480_000, 510), (300, 1_530_000, 1_560)],
)
def test_pae_015_acquired_claim_uses_exact_lease_and_visibility_formulas(
    monkeypatch: pytest.MonkeyPatch,
    timeout: int,
    required_lease_ms: int,
    visibility_seconds: int,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs("proof-1", clock=clock)
    api = ClaimApi(claim_response=_envelope("acquired", 2_000_000))
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    _worker(api, explainer, clock, timeout=timeout).run_once()

    claim = api.explanation_updates[0]
    terminal = api.explanation_updates[1]
    assert claim == {
        "proof_job_id": "proof-1",
        "state": "generating",
        "claim_id": str(CLAIM_IDS[0]),
        "required_lease_ms": required_lease_ms,
    }
    assert sqs.visibility_calls[0]["VisibilityTimeout"] == visibility_seconds
    assert terminal["state"] == "completed"
    assert terminal["claim_id"] == claim["claim_id"]
    assert "required_lease_ms" not in terminal
    assert explainer.explain_calls[0]["timeout_seconds"] == timeout
    assert explainer.explain_calls[0]["deadline"] == 100.0 + 5 * timeout
    assert len(sqs.delete_calls) == 1


@pytest.mark.parametrize(("lease_ms", "allowed"), [(38_000, True), (37_999, False)])
def test_pae_015_final_margin_exactly_thirty_seconds_passes(
    monkeypatch: pytest.MonkeyPatch,
    lease_ms: int,
    allowed: bool,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs("proof-1", clock=clock, visibility_delay=2.0)
    api = ClaimApi(
        claim_response=_envelope("acquired", lease_ms),
        clock=clock,
        claim_delay=1.0,
    )
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    _worker(api, explainer, clock, timeout=1).run_once()

    assert bool(explainer.explain_calls) is allowed
    assert len(api.explanation_updates) == (2 if allowed else 1)
    assert bool(sqs.delete_calls) is allowed


def test_pae_015_claim_response_is_anchored_before_delayed_api_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs("proof-1", clock=clock)
    api = ClaimApi(
        claim_response=_envelope("acquired", 33_000),
        clock=clock,
        claim_delay=1.0,
    )
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    _worker(api, explainer, clock, timeout=1).run_once()

    assert explainer.explain_calls == []
    assert sqs.delete_calls == []


def test_pae_015_visibility_failure_performs_zero_model_calls_and_retains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs("proof-1", visibility_error=RuntimeError("PRIVATE RECEIPT"))
    api = ClaimApi(claim_response=_envelope("acquired", 600_000))
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    _worker(api, explainer, clock).run_once()

    assert explainer.explain_calls == []
    assert len(api.explanation_updates) == 1
    assert sqs.delete_calls == []


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"claim_status": "acquired", "lease_remaining_ms": True, "resource": {}},
        {"claim_status": "unknown", "lease_remaining_ms": None, "resource": {}},
        {
            "claim_status": "acquired",
            "lease_remaining_ms": 600_000,
            "resource": {},
            "extra": "forbidden",
        },
        RuntimeError("PRIVATE CLAIM TRANSPORT"),
    ],
)
def test_pae_015_malformed_or_ambiguous_claim_never_calls_model_or_deletes(
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, Any] | Exception,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs("proof-1")
    api = ClaimApi(claim_response=response)
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    _worker(api, explainer, clock).run_once()

    assert explainer.explain_calls == []
    assert sqs.visibility_calls == []
    assert sqs.delete_calls == []


def test_pae_015_clarification_not_ready_retains_without_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    body = '{"kind":"clarification","id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"}'
    sqs = FakeSqs(body)
    api = ClaimApi(
        claim_response=_envelope(
            "not_ready",
            None,
            resource_kind="clarification",
        )
    )
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    _worker(api, explainer, clock).run_once()

    assert explainer.clarify_calls == []
    assert sqs.visibility_calls == []
    assert sqs.delete_calls == []


def test_clarification_does_not_construct_proof_generation_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verified-proof clarification must run without the optional PFI runtime."""
    clock = FakeClock()
    body = '{"kind":"clarification","id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"}'
    sqs = FakeSqs(body)
    api = ClaimApi(
        claim_response=_envelope(
            "acquired",
            600_000,
            resource_kind="clarification",
            resource_id="8bf36a9a-5d98-4e19-8f70-7f07dfc881a1",
        ),
        terminal_response=_envelope(
            "terminal",
            None,
            resource_kind="clarification",
            resource_id="8bf36a9a-5d98-4e19-8f70-7f07dfc881a1",
        ),
    )
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)
    factory_calls: list[None] = []

    def unavailable_proof_pipeline() -> PipelineThatMustNotRun:
        factory_calls.append(None)
        raise AssertionError("clarification must not construct the proof pipeline")

    worker = SqsProofWorker(
        settings=_settings(),
        api_client=api,
        pipeline=None,
        explainer=explainer,
        output_reviewer=RecordingOutputReviewer(),
        pipeline_factory=unavailable_proof_pipeline,
        monotonic=clock,
        uuid4_factory=UuidFactory(),
    )

    assert worker.run_once() is True
    assert factory_calls == []
    assert len(explainer.clarify_calls) == 1
    assert len(sqs.delete_calls) == 1


@pytest.mark.parametrize(
    "context_case", ["valid", "missing", "different-parent", "selection-not-in-parent"]
)
def test_exp_010_clarification_passes_parent_target_to_generation(
    monkeypatch: pytest.MonkeyPatch,
    context_case: str,
) -> None:
    clock = FakeClock()
    clarification_id = "8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"
    parent_id = "58cd9b1d-5ef0-4dc2-b47b-93e91d5dca67"
    sqs = FakeSqs(f'{{"kind":"clarification","id":"{clarification_id}"}}')
    api = ClaimApi(
        claim_response=_envelope(
            "acquired",
            600_000,
            resource_kind="clarification",
            resource_id=clarification_id,
        ),
        terminal_response=_envelope(
            "terminal",
            None,
            resource_kind="clarification",
            resource_id=clarification_id,
        ),
    )
    original_worker_input = api.get_proof_clarification

    def parent_targeted_input(target_id: str) -> dict[str, Any]:
        response = original_worker_input(target_id)
        response["selected_text"] = "前の回答で説明されたこの部分"
        response["after_clarification_id"] = parent_id
        response["parent_clarification"] = {
            "id": parent_id,
            "question": "Earlier question",
            "answer": (
                "前の回答で説明されたこの部分。ここでは q を素数とし、"
                "a を整数として議論を進めます。"
            ),
            "key_points": ["q is prime", "a is an integer"],
        }
        if context_case == "missing":
            response.pop("parent_clarification")
        elif context_case == "different-parent":
            response["parent_clarification"]["id"] = "another-parent"
        elif context_case == "selection-not-in-parent":
            response["selected_text"] = "a passage from another answer"
        return response

    cast(Any, api).get_proof_clarification = parent_targeted_input
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    reviewer = RecordingOutputReviewer()
    assert _worker(api, explainer, clock, output_reviewer=reviewer).run_once() is True
    if context_case != "valid":
        assert explainer.clarify_calls == []
        assert reviewer.clarification_calls == []
        assert sqs.delete_calls == []
        return
    assert reviewer.clarification_calls[0]["selected_text"] == "前の回答で説明されたこの部分"
    assert (
        reviewer.clarification_calls[0]["parent_clarification"]
        == explainer.clarify_calls[0]["parent_clarification"]
    )
    assert reviewer.clarification_calls[0]["parent_clarification"]["question"] == "Earlier question"
    assert explainer.clarify_calls[0]["selected_text"] == "前の回答で説明されたこの部分"
    assert explainer.clarify_calls[0]["after_clarification_id"] == parent_id
    completed = api.clarification_updates[-1]
    evidence = completed["review_evidence"]
    context = {
        "section_id": explainer.clarify_calls[0]["section_id"],
        "question": explainer.clarify_calls[0]["question"],
        "selected_text": explainer.clarify_calls[0]["selected_text"],
        "after_clarification_id": parent_id,
        "parent_clarification": explainer.clarify_calls[0]["parent_clarification"],
    }
    assert evidence["schema_version"] == "pals.proof-output-review.v3"
    assert (
        evidence["clarification_context_sha256"]
        == hashlib.sha256(rfc8785.dumps(context)).hexdigest()
    )
    assert (
        evidence["clarification_context_sha256"]
        != hashlib.sha256(
            rfc8785.dumps({**context, "selected_text": "a different selected statement"})
        ).hexdigest()
    )


def test_pae_015_malformed_acquired_resource_never_authorizes_model_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs("proof-1")
    api = ClaimApi(
        claim_response={
            "claim_status": "acquired",
            "lease_remaining_ms": 600_000,
            "resource": {},
        }
    )
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    _worker(api, explainer, clock).run_once()

    assert explainer.explain_calls == []
    assert sqs.visibility_calls == []
    assert sqs.delete_calls == []


def test_pae_015_terminal_resource_for_another_proof_never_deletes_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs("proof-1")
    api = ClaimApi(claim_response=_envelope("terminal", None, resource_id="proof-2"))
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    _worker(api, explainer, clock).run_once()

    assert explainer.explain_calls == []
    assert sqs.delete_calls == []


def test_pae_004_clarification_rechecks_same_verified_proof_before_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    body = '{"kind":"clarification","id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"}'
    sqs = FakeSqs(body)
    api = ClaimApi(
        claim_response=_envelope(
            "acquired",
            600_000,
            resource_kind="clarification",
        ),
        proof_job_response={
            "id": "proof-1",
            "state": "verified",
            "theorem_statement": "True を証明せよ",
            "lean_code": "example : True := by\n  exact True.intro",
            "context": {},
        },
    )
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    _worker(api, explainer, clock).run_once()

    assert api.proof_job_reads == ["proof-1"]
    assert api.clarification_updates == []
    assert explainer.clarify_calls == []
    assert sqs.visibility_calls == []
    assert sqs.delete_calls == []


@pytest.mark.parametrize(
    "task_id",
    ["../proof", "proof/child", r"proof\\child", ".hidden", "proof?query", "proof#part"],
)
def test_pae_015_clarification_task_rejects_non_segment_ids(task_id: str) -> None:
    body = json.dumps({"kind": "clarification", "id": task_id})

    with pytest.raises(ValueError, match="clarification"):
        from pals_agent.worker import parse_agent_task

        parse_agent_task(body)


@pytest.mark.parametrize(
    "body",
    [
        "a" * 201,
        json.dumps({"kind": "clarification", "id": "a" * 201}),
    ],
)
def test_pae_015_queue_task_rejects_ids_longer_than_200_characters(body: str) -> None:
    from pals_agent.worker import parse_agent_task

    with pytest.raises(ValueError):
        parse_agent_task(body)


def test_pae_015_legacy_proof_task_accepts_exactly_200_ascii_characters() -> None:
    from pals_agent.worker import parse_agent_task

    task = parse_agent_task("a" * 200)

    assert task.kind == "proof"
    assert task.id == "a" * 200


def test_pae_038_clarification_task_rejects_noncanonical_200_character_id() -> None:
    from pals_agent.worker import parse_agent_task

    with pytest.raises(ValueError, match="clarification"):
        parse_agent_task(json.dumps({"kind": "clarification", "id": "a" * 200}))


def test_pae_038_sqs_envelope_requires_identity_and_empty_clarification_attributes() -> None:
    body = '{"kind":"clarification","id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"}'
    task, receipt_handle = parse_sqs_agent_message(
        {
            "Body": body,
            "MessageId": "message-1",
            "ReceiptHandle": "receipt-1",
            "MessageAttributes": {},
            "Attributes": {"ApproximateReceiveCount": "1"},
        }
    )

    assert task.id == "8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"
    assert receipt_handle == "receipt-1"

    for malformed in (
        {"Body": body, "ReceiptHandle": "receipt-1", "MessageAttributes": {}},
        {"Body": body, "MessageId": "message-1", "MessageAttributes": {}},
        {
            "Body": body,
            "MessageId": "message-1",
            "ReceiptHandle": "receipt-1",
            "MessageAttributes": {"unexpected": {}},
        },
        {
            "Body": body,
            "MessageId": "message-1",
            "ReceiptHandle": "receipt-1",
            "MessageAttributes": [],
        },
        {
            "Body": body,
            "MessageId": "message-1",
            "ReceiptHandle": "receipt-1",
            "MessageAttributes": {},
            "Attributes": [],
        },
    ):
        with pytest.raises(ValueError):
            parse_sqs_agent_message(malformed)


def test_pae_038_clarification_worker_does_not_call_api_for_invalid_sqs_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    body = '{"kind":"clarification","id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"}'
    sqs = FakeSqs(body)
    api = ClaimApi(claim_response=_envelope("not_ready", None, resource_kind="clarification"))
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    # An application attribute makes this otherwise exact clarification body poison.
    original_receive = sqs.receive_message

    def receive_with_unexpected_attribute(**kwargs: Any) -> dict[str, Any]:
        response = original_receive(**kwargs)
        response["Messages"][0]["MessageAttributes"] = {"proof_job_id": {}}
        return response

    sqs.receive_message = receive_with_unexpected_attribute  # type: ignore[method-assign]

    assert _worker(api, explainer, clock).run_once() is True
    assert api.clarification_updates == []
    assert explainer.clarify_calls == []
    assert sqs.delete_calls == []


def test_pae_038_clarification_worker_retains_wrong_api_marker_before_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    body = '{"kind":"clarification","id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"}'
    sqs = FakeSqs(body)
    api = ClaimApi(claim_response=_envelope("not_ready", None, resource_kind="clarification"))
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    original_worker_input = api.get_proof_clarification

    def worker_input_with_wrong_marker(clarification_id: str) -> dict[str, Any]:
        response = original_worker_input(clarification_id)
        response["dispatch_schema_version"] = "unexpected"
        return response

    api.get_proof_clarification = worker_input_with_wrong_marker  # type: ignore[method-assign]

    assert _worker(api, explainer, clock).run_once() is True
    assert api.clarification_updates == []
    assert explainer.clarify_calls == []
    assert sqs.delete_calls == []


def test_pae_015_deadline_failure_uses_fixed_claimed_terminal_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs("proof-1")
    api = ClaimApi(claim_response=_envelope("acquired", 600_000))
    deadline_error_type = explanations.ExplanationDeadlineExceeded
    explainer = RecordingExplainer(error=deadline_error_type("PRIVATE LATE OUTPUT"))
    _install_sqs(monkeypatch, sqs)

    _worker(api, explainer, clock).run_once()

    terminal = api.explanation_updates[-1]
    assert terminal["state"] == "failed"
    assert terminal["claim_id"] == str(CLAIM_IDS[0])
    assert terminal["diagnostics"][0].code == "pals.explanation_deadline_exceeded"
    assert "PRIVATE" not in terminal["diagnostics"][0].message
    assert len(sqs.delete_calls) == 1


def test_pae_015_terminal_write_failure_retains_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs("proof-1")
    api = ClaimApi(
        claim_response=_envelope("acquired", 600_000),
        terminal_response=RuntimeError("STALE CLAIM PRIVATE"),
    )
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    _worker(api, explainer, clock).run_once()

    assert len(explainer.explain_calls) == 1
    assert sqs.delete_calls == []


def test_core_006_summary_review_must_pass_before_completion_and_uses_verified_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs("proof-1")
    api = ClaimApi(claim_response=_envelope("acquired", 600_000))
    explainer = RecordingExplainer()
    reviewer = RecordingOutputReviewer()
    _install_sqs(monkeypatch, sqs)

    assert _worker(api, explainer, clock, output_reviewer=reviewer).run_once() is True

    assert [update["state"] for update in api.explanation_updates] == [
        "generating",
        "completed",
    ]
    assert len(reviewer.explanation_calls) == 1
    review_call = reviewer.explanation_calls[0]
    assert review_call["lean_code"] == LEAN_CODE
    assert review_call["explanation"].overview == "証明の概要です。"
    assert cast(object, reviewer) is not explainer
    completed = api.explanation_updates[-1]
    evidence = cast(dict[str, Any], completed["review_evidence"])
    expected_output = {
        "output_kind": "explanation",
        "proof_job_id": "proof-1",
        "content": completed["content"],
    }
    assert evidence["schema_version"] == "pals.proof-output-review.v2"
    assert evidence["output_kind"] == "explanation"
    assert evidence["generator_session_id"] == completed["claim_id"]
    assert evidence["output_sha256"] == hashlib.sha256(rfc8785.dumps(expected_output)).hexdigest()
    assert evidence["lean_sha256"] == hashlib.sha256(LEAN_CODE.encode("utf-8")).hexdigest()
    assert evidence["parent_explanation_sha256"] is None
    assert evidence["reviewer"] == {
        "provider": "test-reviewer",
        "model": "review-model",
        "session_id": "33333333-3333-4333-8333-333333333333",
    }
    assert evidence["decision"] == "approved"
    assert evidence["rationale"] == "The explanation is grounded in the verified Lean source."
    unsigned_evidence = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    assert (
        evidence["evidence_sha256"] == hashlib.sha256(rfc8785.dumps(unsigned_evidence)).hexdigest()
    )


@pytest.mark.parametrize(
    ("body", "updates_name", "review_method", "diagnostic_code"),
    [
        (
            "proof-1",
            "explanation_updates",
            "explanation_calls",
            "pals.explanation_review_failed",
        ),
        (
            '{"kind":"clarification","id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"}',
            "clarification_updates",
            "clarification_calls",
            "pals.clarification_review_failed",
        ),
    ],
)
def test_core_006_rejected_output_fails_only_that_output_before_completion(
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    updates_name: str,
    review_method: str,
    diagnostic_code: str,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs(body)
    api = ClaimApi(
        claim_response=_envelope(
            "acquired",
            600_000,
            resource_kind=("clarification" if "clarification" in body else "explanation"),
            resource_id=(
                "8bf36a9a-5d98-4e19-8f70-7f07dfc881a1" if "clarification" in body else None
            ),
        ),
        terminal_response=_envelope(
            "terminal",
            None,
            resource_kind=("clarification" if "clarification" in body else "explanation"),
            resource_id=(
                "8bf36a9a-5d98-4e19-8f70-7f07dfc881a1" if "clarification" in body else None
            ),
        ),
    )
    explainer = RecordingExplainer()
    reviewer = RecordingOutputReviewer(
        error=explanations.ProofOutputReviewError("PRIVATE REVIEW DETAIL")
    )
    _install_sqs(monkeypatch, sqs)

    assert _worker(api, explainer, clock, output_reviewer=reviewer).run_once() is True

    updates = cast(list[dict[str, Any]], getattr(api, updates_name))
    assert [update["state"] for update in updates] == ["generating", "failed"]
    assert updates[-1]["diagnostics"][0].code == diagnostic_code
    assert "review_evidence" not in updates[-1]
    assert "PRIVATE" not in updates[-1]["diagnostics"][0].message
    assert len(cast(list[dict[str, Any]], getattr(reviewer, review_method))) == 1
    assert api.proof_job_reads == ["proof-1"]
    assert len(sqs.delete_calls) == 1


def test_core_006_unavailable_reviewer_fails_only_the_localized_explanation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs("proof-1")
    api = ClaimApi(
        claim_response=_envelope("acquired", 600_000),
        output_language="zh-Hant",
    )
    _install_sqs(monkeypatch, sqs)
    worker = SqsProofWorker(
        settings=_settings(),
        api_client=api,
        pipeline=PipelineThatMustNotRun(),
        explainer=RecordingExplainer(),
        output_reviewer=None,
        monotonic=clock,
        uuid4_factory=UuidFactory(),
    )

    assert worker.run_once() is True

    assert [update["state"] for update in api.explanation_updates] == ["generating", "failed"]
    failed = api.explanation_updates[-1]
    assert failed["diagnostics"][0].code == "pals.explanation_review_failed"
    assert failed["diagnostics"][0].message == "說明審核失敗。"
    assert "review_evidence" not in failed
    assert api.proof_job_reads == ["proof-1"]
    assert len(sqs.delete_calls) == 1


@pytest.mark.parametrize(
    ("language", "expected_explanation", "expected_clarification"),
    [
        (
            "en",
            "Explanation review failed.",
            "Clarification review failed.",
        ),
        (
            "ja",
            "説明のレビューに失敗しました。",
            "追加回答のレビューに失敗しました。",
        ),
        (
            "zh-Hans",
            "说明审核失败。",
            "补充回答审核失败。",
        ),
        (
            "zh-Hant",
            "說明審核失敗。",
            "補充回答審核失敗。",
        ),
    ],
)
@pytest.mark.parametrize(
    ("body", "resource_kind", "updates_name", "expected_index"),
    [
        ("proof-1", "explanation", "explanation_updates", 1),
        (
            '{"kind":"clarification","id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"}',
            "clarification",
            "clarification_updates",
            2,
        ),
    ],
)
def test_core_004_localizes_explanation_and_clarification_failures_to_chat_language(
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    expected_explanation: str,
    expected_clarification: str,
    body: str,
    resource_kind: str,
    updates_name: str,
    expected_index: int,
) -> None:
    clock = FakeClock()
    resource_id = (
        "8bf36a9a-5d98-4e19-8f70-7f07dfc881a1" if resource_kind == "clarification" else None
    )
    api = ClaimApi(
        claim_response=_envelope(
            "acquired",
            600_000,
            resource_kind=resource_kind,
            resource_id=resource_id,
        ),
        terminal_response=_envelope(
            "terminal",
            None,
            resource_kind=resource_kind,
            resource_id=resource_id,
        ),
        output_language=language,
    )
    sqs = FakeSqs(body)
    reviewer = RecordingOutputReviewer(
        error=explanations.ProofOutputReviewError("PRIVATE REVIEW DETAIL")
    )
    _install_sqs(monkeypatch, sqs)

    assert (
        _worker(
            api,
            RecordingExplainer(),
            clock,
            output_reviewer=reviewer,
        ).run_once()
        is True
    )

    updates = cast(list[dict[str, Any]], getattr(api, updates_name))
    assert updates[-1]["state"] == "failed"
    assert updates[-1]["diagnostics"][0].message == (
        expected_explanation if expected_index == 1 else expected_clarification
    )
    assert "PRIVATE" not in updates[-1]["diagnostics"][0].message
    assert api.proof_job_reads == ["proof-1"]


@pytest.mark.parametrize(
    ("body", "error_code", "updates_name", "diagnostic_code"),
    [
        (
            "proof-1",
            "proof_explanation_reference_mismatch",
            "explanation_updates",
            "pals.explanation_reference_mismatch",
        ),
        (
            '{"kind":"clarification","id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"}',
            "proof_clarification_reference_mismatch",
            "clarification_updates",
            "pals.clarification_reference_mismatch",
        ),
    ],
)
def test_pae_015_reference_mismatch_terminalizes_once_with_the_current_claim(
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    error_code: str,
    updates_name: str,
    diagnostic_code: str,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs(body)
    resource_id = "8bf36a9a-5d98-4e19-8f70-7f07dfc881a1" if "clarification" in body else None
    api = ClaimApi(
        claim_response=_envelope(
            "acquired",
            600_000,
            resource_kind=("clarification" if "clarification" in body else "explanation"),
            resource_id=resource_id,
        ),
        completed_error=PalsApiError("private reference detail", error_code=error_code),
        terminal_response=_failed_terminal_envelope(
            resource_kind=("clarification" if "clarification" in body else "explanation"),
            resource_id=resource_id,
        ),
    )
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    assert _worker(api, explainer, clock).run_once() is True

    updates = cast(list[dict[str, Any]], getattr(api, updates_name))
    assert [update["state"] for update in updates] == [
        "generating",
        "completed",
        "failed",
    ]
    assert {update["claim_id"] for update in updates} == {str(CLAIM_IDS[0])}
    assert updates[-1]["diagnostics"][0].code == diagnostic_code
    assert "private reference detail" not in updates[-1]["diagnostics"][0].message
    assert len(explainer.explain_calls) == (1 if updates_name == "explanation_updates" else 0)
    assert len(explainer.clarify_calls) == (1 if updates_name == "clarification_updates" else 0)
    assert len(sqs.delete_calls) == 1


@pytest.mark.parametrize(
    ("body", "error_code", "updates_name", "terminal_response"),
    [
        (
            "proof-1",
            "proof_explanation_reference_mismatch",
            "explanation_updates",
            _envelope("terminal", None),
        ),
        (
            '{"kind":"clarification","id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"}',
            "proof_clarification_reference_mismatch",
            "clarification_updates",
            _envelope("terminal", None, resource_kind="clarification"),
        ),
        (
            "proof-1",
            "proof_explanation_reference_mismatch",
            "explanation_updates",
            {},
        ),
        (
            '{"kind":"clarification","id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"}',
            "proof_clarification_reference_mismatch",
            "clarification_updates",
            RuntimeError("private failed write"),
        ),
    ],
)
def test_pae_015_reference_mismatch_retains_nonfailed_or_ambiguous_terminal(
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    error_code: str,
    updates_name: str,
    terminal_response: dict[str, Any] | Exception,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs(body)
    resource_id = "8bf36a9a-5d98-4e19-8f70-7f07dfc881a1" if "clarification" in body else None
    api = ClaimApi(
        claim_response=_envelope(
            "acquired",
            600_000,
            resource_kind=("clarification" if "clarification" in body else "explanation"),
            resource_id=resource_id,
        ),
        completed_error=PalsApiError("private reference detail", error_code=error_code),
        terminal_response=terminal_response,
    )
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    assert _worker(api, explainer, clock).run_once() is True

    updates = cast(list[dict[str, Any]], getattr(api, updates_name))
    assert [update["state"] for update in updates] == [
        "generating",
        "completed",
        "failed",
    ]
    assert len(sqs.delete_calls) == 0


def test_pae_015_private_values_never_enter_content_diagnostics_or_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs("proof-1")
    api = ClaimApi(claim_response=_envelope("acquired", 600_000))
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    _worker(api, explainer, clock).run_once()

    serialized_terminal = repr(api.explanation_updates[-1].get("content")) + repr(
        api.explanation_updates[-1].get("diagnostics")
    )
    assert str(CLAIM_IDS[0]) not in serialized_terminal
    assert "PRIVATE-RECEIPT" not in serialized_terminal
    assert "PRIVATE PROMPT" not in serialized_terminal
    assert "PRIVATE RAW OUTPUT" not in serialized_terminal
    assert all(str(CLAIM_IDS[0]) not in repr(call) for call in explainer.explain_calls)


@pytest.mark.parametrize(
    "value",
    ["", "+1", "-1", "1.0", "1e1", " 1", "1 ", "0", "301", "９０"],
)
def test_pae_015_invalid_model_timeout_fails_settings_preflight(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("PALS_EXPLANATION_MODEL_TIMEOUT_SECONDS", value)

    with pytest.raises(ValueError, match="PALS_EXPLANATION_MODEL_TIMEOUT_SECONDS"):
        AgentSettings.from_env()


@pytest.mark.parametrize("value", ["1", "90", "300"])
def test_pae_015_model_timeout_accepts_exact_bounds(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("PALS_EXPLANATION_MODEL_TIMEOUT_SECONDS", value)

    assert AgentSettings.from_env().explanation_model_timeout_seconds == int(value)


@pytest.mark.parametrize("reference_error", [False, True])
def test_rejected_summary_generates_one_new_candidate_and_keeps_private_reason(
    monkeypatch: pytest.MonkeyPatch,
    reference_error: bool,
) -> None:
    from dataclasses import replace

    class CorrectingExplainer(RecordingExplainer):
        def explain(self, **kwargs: Any) -> ProofExplanation:
            original = super().explain(**kwargs)
            return (
                replace(original, overview="修正した導入です。")
                if kwargs.get("review_feedback")
                else original
            )

    class OnceRejectingReviewer(RecordingOutputReviewer):
        def review_explanation(self, **kwargs: Any) -> ProofOutputReview:
            if not self.explanation_calls:
                self.explanation_calls.append(kwargs)
                raise explanations.ProofOutputReviewError(
                    "rejected",
                    category="rejected",
                    rationale="PRIVATE: duplicated derivation",
                    session_id="44444444-4444-4444-8444-444444444444",
                )
            return super().review_explanation(**kwargs)

    clock = FakeClock()
    sqs = FakeSqs("proof-1")
    api = ClaimApi(
        claim_response=_envelope("acquired", 600_000),
        completed_error=(
            PalsApiError("private", error_code="proof_explanation_reference_mismatch")
            if reference_error
            else None
        ),
        terminal_response=(
            _failed_terminal_envelope(resource_kind="explanation") if reference_error else None
        ),
    )
    explainer = CorrectingExplainer()
    reviewer = OnceRejectingReviewer()
    _install_sqs(monkeypatch, sqs)
    assert _worker(api, explainer, clock, output_reviewer=reviewer).run_once()
    assert len(explainer.explain_calls) == len(reviewer.explanation_calls) == 2
    assert (
        explainer.explain_calls[1]["review_feedback"]["rationale"]
        == "PRIVATE: duplicated derivation"
    )
    assert explainer.explain_calls[0]["deadline"] == explainer.explain_calls[1]["deadline"]
    final = api.explanation_updates[-2] if reference_error else api.explanation_updates[-1]
    if reference_error:
        assert api.explanation_updates[-1]["state"] == "failed"
        assert (
            api.explanation_updates[-1]["private_review_failures"]
            == final["private_review_failures"]
        )
    assert final["state"] == "completed"
    assert final["content"]["overview"] == "修正した導入です。"
    assert final["private_review_failures"][0]["category"] == "rejected"
    assert "PRIVATE" not in str(final["content"])
    assert (
        final["private_review_failures"][0]["candidate_sha256"]
        != final["review_evidence"]["output_sha256"]
    )


def test_repeated_rejected_candidate_never_gets_another_vote() -> None:
    from pals_agent.worker import _generate_reviewed_candidate

    review_calls = []

    def reject(candidate: dict[str, Any]) -> ProofOutputReview:
        review_calls.append(candidate)
        raise explanations.ProofOutputReviewError(
            "rejected", category="rejected", rationale="invalid"
        )

    failures: list[dict[str, Any]] = []
    with pytest.raises(explanations.ProofOutputReviewError, match="repeated"):
        _generate_reviewed_candidate(
            generate=lambda _: {"answer": "same"},
            review=reject,
            content_of=lambda candidate: candidate,
            failures=failures,
        )
    assert len(review_calls) == 1
    assert len(failures) == 2
    assert failures[-1]["reviewer_session_id"] is None


@pytest.mark.parametrize("category", ["transport", "schema"])
def test_review_infrastructure_failure_does_not_regenerate(category: str) -> None:
    from pals_agent.worker import _generate_reviewed_candidate

    generated = []

    def generate(feedback: object) -> dict[str, str]:
        generated.append(feedback)
        return {"answer": "candidate"}

    def fail(_: object) -> ProofOutputReview:
        raise explanations.ProofOutputReviewError("unavailable", category=cast(Any, category))

    failures: list[dict[str, Any]] = []
    with pytest.raises(explanations.ProofOutputReviewError):
        _generate_reviewed_candidate(
            generate=generate,
            review=fail,
            content_of=lambda candidate: candidate,
            failures=failures,
        )
    assert len(generated) == 1
    assert failures[0]["category"] == category


def test_hidden_metadata_changes_do_not_allow_revote_of_same_visible_explanation() -> None:
    from pals_agent.worker import _generate_reviewed_candidate

    counter = 0

    def generate(_: object) -> dict[str, Any]:
        nonlocal counter
        counter += 1
        return {
            "overview": "x is real",
            "sections": [
                {
                    "id": str(counter),
                    "title": str(counter),
                    "summary": "proof text",
                    "references": [counter],
                }
            ],
            "conclusion": "done",
        }

    calls = []

    def review(candidate: object) -> ProofOutputReview:
        calls.append(candidate)
        raise explanations.ProofOutputReviewError(
            "bad", category="rejected", rationale="unsupported"
        )

    with pytest.raises(explanations.ProofOutputReviewError, match="repeated"):
        _generate_reviewed_candidate(
            generate=generate, review=review, content_of=lambda value: value, failures=[]
        )
    assert counter == 2 and len(calls) == 1


def test_explanation_retry_message_preserves_retry_binding_and_requires_closed_wire() -> None:
    from pals_agent.worker import parse_agent_task

    job = "11111111-1111-4111-8111-111111111111"
    retry = "22222222-2222-4222-8222-222222222222"
    body = f'{{"kind":"explanation","id":"{job}","retry_id":"{retry}"}}'
    task = parse_agent_task(body)
    assert task.kind == "explanation" and task.id == job and task.retry_id == retry
    for bad in [
        body.replace(retry, "invalid"),
        body[:-1] + ',"extra":true}',
        body.replace(",", ", "),
    ]:
        with pytest.raises(ValueError):
            parse_agent_task(bad)


def test_retry_dispatch_reads_verified_proof_and_claims_only_the_explanation() -> None:
    clock = FakeClock()
    api = ClaimApi(claim_response=_envelope("acquired", 600_000))
    explainer = RecordingExplainer()
    worker = _worker(api, explainer, clock)
    retry = "22222222-2222-4222-8222-222222222222"
    assert worker.process_explanation_retry(
        "proof-1",
        retry_id=retry,
        claim_id="11111111-1111-4111-8111-111111111111",
        extend_visibility=lambda _: None,
    )
    assert api.explanation_updates[0]["retry_id"] == retry
    assert api.explanation_updates[-1]["state"] == "completed"
    assert len(explainer.explain_calls) == 1
