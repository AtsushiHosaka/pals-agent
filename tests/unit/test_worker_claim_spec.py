from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest

from pals_agent import explanations
from pals_agent.api_client import PalsApiError
from pals_agent.explanations import (
    ExplanationSection,
    LeanLineReference,
    ProofClarification,
    ProofExplanation,
)
from pals_agent.settings import AgentSettings
from pals_agent.worker import SqsProofWorker, parse_sqs_agent_message

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
    ) -> None:
        self.claim_response = claim_response
        self.clock = clock
        self.claim_delay = claim_delay
        self.terminal_response = terminal_response
        self.completed_error = completed_error
        self.proof_job_response = proof_job_response
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
                        "references": [
                            {"start_line": 2, "end_line": 2, "excerpt": "  trivial"}
                        ],
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
                    "references": [
                        {"start_line": 2, "end_line": 2, "excerpt": "  trivial"}
                    ],
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
            "references": [
                {"start_line": 2, "end_line": 2, "excerpt": "  trivial"}
            ],
            "model": "explain-model",
            "provider": "test-provider",
            "elapsed_ms": 3,
        }
    return {
        "id": clarification_id,
        "proof_job_id": proof_job_id,
        "section_id": "finish",
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
        _clarification_resource(
            clarification_id=resource_id or "clarification-1", state="failed"
        )
        if resource_kind == "clarification"
        else _explanation_resource(proof_job_id=resource_id or "proof-1", state="failed")
    )
    return {
        "claim_status": "terminal",
        "lease_remaining_ms": None,
        "resource": resource,
    }


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
) -> SqsProofWorker:
    return SqsProofWorker(
        settings=_settings(timeout),
        api_client=api,
        pipeline=PipelineThatMustNotRun(),
        explainer=explainer,
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
    [(1, 33_000, 63), (90, 300_000, 330), (300, 930_000, 960)],
)
def test_pae_015_acquired_claim_uses_exact_lease_and_visibility_formulas(
    monkeypatch: pytest.MonkeyPatch,
    timeout: int,
    required_lease_ms: int,
    visibility_seconds: int,
) -> None:
    clock = FakeClock()
    sqs = FakeSqs("proof-1", clock=clock)
    api = ClaimApi(claim_response=_envelope("acquired", 1_000_000))
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
    assert explainer.explain_calls[0]["deadline"] == 100.0 + 3 * timeout
    assert len(sqs.delete_calls) == 1


@pytest.mark.parametrize(("lease_ms", "allowed"), [(36_000, True), (35_999, False)])
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
        pipeline_factory=unavailable_proof_pipeline,
        monotonic=clock,
        uuid4_factory=UuidFactory(),
    )

    assert worker.run_once() is True
    assert factory_calls == []
    assert len(explainer.clarify_calls) == 1
    assert len(sqs.delete_calls) == 1


def test_exp_010_clarification_passes_parent_target_to_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    clarification_id = "8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"
    parent_id = "58cd9b1d-5ef0-4dc2-b47b-93e91d5dca67"
    sqs = FakeSqs(
        f'{{"kind":"clarification","id":"{clarification_id}"}}'
    )
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
        return response

    cast(Any, api).get_proof_clarification = parent_targeted_input
    explainer = RecordingExplainer()
    _install_sqs(monkeypatch, sqs)

    assert _worker(api, explainer, clock).run_once() is True
    assert explainer.clarify_calls[0]["selected_text"] == "前の回答で説明されたこの部分"
    assert explainer.clarify_calls[0]["after_clarification_id"] == parent_id


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
    api = ClaimApi(
        claim_response=_envelope("terminal", None, resource_id="proof-2")
    )
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
    api = ClaimApi(
        claim_response=_envelope("not_ready", None, resource_kind="clarification")
    )
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
    resource_id = (
        "8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"
        if "clarification" in body
        else None
    )
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
    resource_id = (
        "8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"
        if "clarification" in body
        else None
    )
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
