"""Independent worker caller regressions at isolated provider/ledger boundaries.

No database settlement or paid-provider runtime acceptance is asserted here.
"""

import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast

import pytest

from pals_agent.api_client import PalsApiError
from pals_agent.explanations import LeanGroundedOutputReviewer, LeanProofExplainer
from pals_agent.http_transport import HttpResponse
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_reuse_usage import current_role
from pals_agent.settings import AgentSettings
from pals_agent.token_meter import active_token_meter
from pals_agent.worker import SqsProofWorker
from tests.unit.test_worker_token_stages import (
    DELIVERY,
    JOB,
    OPERATION,
    StageApi,
    StageProvider,
    wire_diagnostics,
)

SUBJECT = "77777777-7777-4777-8777-777777777777"
INDEPENDENT_OPERATION = "88888888-8888-4888-8888-888888888888"


class IndependentApi(StageApi):
    def __init__(self, kind, *, operation_state="active", fault=None):
        super().__init__(fault)
        self.kind = kind
        self.source_job = super().get_proof_job(JOB)
        self.source_job["state"] = "verified"
        self.source_job["request_context"]["billing_context"]["operation_state"] = "consumed"
        self.admitted = deepcopy(self.source_job["request_context"]["billing_context"])
        self.admitted.update(
            operation_id=INDEPENDENT_OPERATION,
            operation_state=operation_state,
            subject={"kind": kind, "id": SUBJECT},
        )
        self.clarification_outputs = []

    def get_proof_job(self, proof_job_id):
        assert proof_job_id == JOB
        job = deepcopy(self.source_job)
        if self.kind == "explanation_retry":
            # API-owned read projection; the persisted originating job stays intact.
            job["request_context"]["billing_context"] = deepcopy(self.admitted)
        return job

    def get_proof_clarification(self, clarification_id):
        assert clarification_id == SUBJECT
        return {
            "dispatch_schema_version": "pals.proof-clarification-dispatch.v1",
            "id": SUBJECT,
            "state": "queued",
            "proof_job_id": JOB,
            "output_language": "en",
            "theorem_statement": self.source_job["theorem_statement"],
            "lean_code": self.source_job["lean_code"],
            "section_id": "truth",
            "selected_text": "",
            "after_clarification_id": None,
            "question": "Why does this establish the claim?",
            "billing_context": deepcopy(self.admitted),
            "summary": {
                "overview": "Truth holds directly.",
                "sections": [
                    {
                        "id": "truth",
                        "title": "Truth",
                        "summary": "The claim is true.",
                        "references": [{"start_line": 2, "end_line": 2, "excerpt": "  trivial"}],
                    }
                ],
                "conclusion": "This establishes the requested claim.",
                "model": "gpt-6.1-sol",
                "provider": "openai",
                "elapsed_ms": 1,
            },
        }

    def update_proof_clarification(self, **kwargs):
        assert kwargs["clarification_id"] == SUBJECT
        state = kwargs["state"]
        self.clarification_outputs.append(kwargs)
        self.events.append((state, "clarification"))
        if state == "completed":
            assert self.seals[-1]["scope"] == "clarification"
        return {
            "claim_status": "acquired" if state == "generating" else "terminal",
            "lease_remaining_ms": 3_600_000 if state == "generating" else None,
            "resource": {
                "id": SUBJECT,
                "proof_job_id": JOB,
                "section_id": "truth",
                "selected_text": "",
                "after_clarification_id": None,
                "question": "Why does this establish the claim?",
                "state": state,
                "content": kwargs.get("content"),
                "created_at": "2026-10-07T00:00:00Z",
                "updated_at": "2026-10-07T00:00:00Z",
                "diagnostics": wire_diagnostics(kwargs.get("diagnostics", [])),
            },
        }


class IndependentProvider(StageProvider):
    def __init__(self, api):
        super().__init__(api)
        self.http_calls = []

    def request(self, **kwargs):
        self.http_calls.append(kwargs)
        role = current_role()
        if kwargs["url"].endswith("/input_tokens") or role not in {"clarify", "clarify_qa"}:
            return super().request(**kwargs)
        payload = json.loads(kwargs["body"])
        self.calls.append((role, payload))
        self.api.events.append(("provider", role))
        answer = (
            {
                "section_id": "truth",
                "answer": "The proposition expresses truth itself, so it follows directly "
                "without any additional assumptions about the learner's objects.",
                "key_points": ["The proposition is true.", "No additional premise is needed."],
                "references": [{"start_line": 2, "end_line": 2, "excerpt": "  trivial"}],
            }
            if role == "clarify"
            else {"approved": True, "rationale": "Matches the verified source and requested step."}
        )
        return HttpResponse(
            200,
            json.dumps(
                {
                    "object": "response",
                    "id": f"resp_independent_{len(self.calls)}",
                    "status": "completed",
                    "model": payload["model"],
                    "service_tier": "default",
                    "output_text": json.dumps(answer),
                    "usage": {
                        "input_tokens": 23,
                        "output_tokens": 5,
                        "total_tokens": 28,
                        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                        "output_tokens_details": {"reasoning_tokens": 0},
                    },
                }
            ).encode(),
        )


def setup(kind, *, operation_state="active", fault=None):
    api = IndependentApi(kind, operation_state=operation_state, fault=fault)
    provider = IndependentProvider(api)

    def client():
        return OpenAIResponsesClient(api_key="isolated-test", transport=provider)

    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(explanation_model_timeout_seconds=17)),
        api_client=cast(Any, api),
        pipeline=None,
        explainer=LeanProofExplainer(client(), "gpt-6-luna", "openai", max_attempts=1),
        output_reviewer=LeanGroundedOutputReviewer(client(), "gpt-6-luna", "openai"),
    )
    return api, provider, worker


def process(worker, kind):
    if kind == "clarification":
        return worker.process_clarification(
            SUBJECT,
            claim_id=DELIVERY,
            extend_visibility=lambda _: None,
        )
    return worker.process_explanation_retry(
        JOB,
        retry_id=SUBJECT,
        claim_id=DELIVERY,
        extend_visibility=lambda _: None,
    )


@pytest.mark.parametrize("kind", ["clarification", "explanation_retry"])
def test_independent_worker_uses_new_subject_operation_and_inherits_selected_model(kind):
    api, provider, worker = setup(kind)
    original = deepcopy(api.source_job)
    assert process(worker, kind)
    scope = "clarification" if kind == "clarification" else "explanation"
    generation_role = "clarify" if kind == "clarification" else "explain"
    assert [(r, p["model"]) for r, p in provider.calls] == [
        (generation_role, "gpt-6.1-sol"),
        (generation_role + "_qa", "gpt-6-luna"),
    ]
    assert len(api.seals) == 1
    seal = api.seals[0]
    assert seal["completed_roles"] == sorted([generation_role, generation_role + "_qa"])
    assert len(set(seal["call_ids"])) == 2
    for binding in [*api.permits, *api.receipts, seal]:
        assert binding["subject"] == {"kind": kind, "id": SUBJECT}
        assert binding["operation_id"] == INDEPENDENT_OPERATION != OPERATION
        assert binding["job_id"] == JOB
        assert binding["claim_id"] == DELIVERY
        assert binding["scope"] == scope
        assert "request_id" not in binding
        if kind == "clarification":
            assert binding["task_id"] == SUBJECT
        else:
            assert "task_id" not in binding
    assert set(seal["call_ids"]) == {r["call_id"] for r in api.receipts}
    outputs = api.clarification_outputs if kind == "clarification" else api.outputs
    assert outputs[-1]["state"] == "completed"
    assert outputs[-1]["content"]["model"] == "gpt-6.1-sol"
    assert outputs[-1]["review_evidence"]["reviewer"]["model"] == "gpt-6-luna"
    if kind == "explanation_retry":
        assert outputs[0]["retry_id"] == SUBJECT
    assert api.events.index(("seal", scope)) < api.events.index(("completed", scope))
    assert api.source_job == original
    assert api.source_job["request_context"]["billing_context"]["operation_state"] == "consumed"
    assert active_token_meter() is None


@pytest.mark.parametrize("kind", ["clarification", "explanation_retry"])
@pytest.mark.parametrize("fault_type", ["receipt", "seal"])
def test_independent_failed_receipt_or_seal_cannot_write_completed_output(kind, fault_type):
    scope = "clarification" if kind == "clarification" else "explanation"
    api, _, worker = setup(kind, fault=(fault_type, scope))
    original = deepcopy(api.source_job)
    process(worker, kind)
    outputs = api.clarification_outputs if kind == "clarification" else api.outputs
    assert not any(output["state"] == "completed" for output in outputs)
    assert outputs[-1]["state"] == "failed"
    assert api.meters[scope].failed
    assert api.source_job == original
    assert active_token_meter() is None


@pytest.mark.parametrize("kind", ["clarification", "explanation_retry"])
@pytest.mark.parametrize("state", ["consumed", "released"])
def test_closed_independent_operation_claims_then_persists_failure_before_ack(kind, state):
    api, provider, worker = setup(kind, operation_state=state)
    original = deepcopy(api.source_job)
    assert process(worker, kind)
    assert not provider.http_calls
    assert not api.permits and not api.receipts and not api.seals
    outputs = api.clarification_outputs if kind == "clarification" else api.outputs
    assert [output["state"] for output in outputs] == ["generating", "failed"]
    assert all(output["claim_id"] == DELIVERY for output in outputs)
    assert outputs[0]["required_lease_ms"] > 0
    assert outputs[-1]["diagnostics"][0].code == (
        "pals.clarification_failed" if kind == "clarification" else "pals.explanation_failed"
    )
    assert "content" not in outputs[-1]
    if kind == "explanation_retry":
        assert outputs[0]["retry_id"] == SUBJECT
    assert api.source_job == original
    assert active_token_meter() is None


@pytest.mark.parametrize("kind", ["clarification", "explanation_retry"])
@pytest.mark.parametrize("state", ["consumed", "released"])
@pytest.mark.parametrize(
    "fault",
    [
        "busy",
        "acquire_error",
        "acquire_wrong_id",
        "failure_error",
        "failure_nonterminal",
        "failure_wrong_id",
        "failure_malformed",
    ],
)
def test_closed_independent_operation_keeps_redelivery_when_terminal_authority_is_missing(
    kind,
    state,
    fault,
    monkeypatch,
):
    api, provider, worker = setup(kind, operation_state=state)
    original = deepcopy(api.source_job)
    original_admission = deepcopy(api.admitted)
    method_name = (
        "update_proof_clarification" if kind == "clarification" else "upsert_proof_explanation"
    )
    update = getattr(api, method_name)
    attempts = []

    def uncertain_update(**kwargs):
        attempts.append(deepcopy(kwargs))
        acquiring = kwargs["state"] == "generating"
        if (fault == "acquire_error" and acquiring) or (fault == "failure_error" and not acquiring):
            raise PalsApiError("isolated authority rejection")
        response = update(**kwargs)
        if fault == "busy" and acquiring:
            response["claim_status"] = "busy"
        if (fault == "acquire_wrong_id" and acquiring) or (
            fault == "failure_wrong_id" and not acquiring
        ):
            field = "id" if kind == "clarification" else "proof_job_id"
            response["resource"][field] = "another-resource"
        if fault == "failure_nonterminal" and not acquiring:
            response["claim_status"] = "acquired"
            response["lease_remaining_ms"] = 3_600_000
            response["resource"]["state"] = "generating"
        if fault == "failure_malformed" and not acquiring:
            return {"claim_status": "terminal", "resource": response["resource"]}
        return response

    monkeypatch.setattr(api, method_name, uncertain_update)
    assert not process(worker, kind)
    assert attempts[0]["state"] == "generating"
    assert all(attempt["claim_id"] == DELIVERY for attempt in attempts)
    if kind == "explanation_retry":
        assert attempts[0]["retry_id"] == SUBJECT
    assert [attempt["state"] for attempt in attempts] == (
        ["generating"]
        if fault in {"busy", "acquire_error", "acquire_wrong_id"}
        else ["generating", "failed"]
    )
    assert not provider.http_calls
    assert not api.permits and not api.receipts and not api.seals
    assert api.source_job == original
    assert api.admitted == original_admission
    assert active_token_meter() is None


@pytest.mark.parametrize("kind", ["clarification", "explanation_retry"])
@pytest.mark.parametrize("state", ["consumed", "released"])
def test_closed_independent_operation_acknowledges_an_already_terminal_claim_without_rewrite(
    kind,
    state,
    monkeypatch,
):
    api, provider, worker = setup(kind, operation_state=state)
    original = deepcopy(api.source_job)
    method_name = (
        "update_proof_clarification" if kind == "clarification" else "upsert_proof_explanation"
    )
    update = getattr(api, method_name)

    def terminal_update(**kwargs):
        assert kwargs["state"] == "generating"
        response = update(**kwargs)
        response["claim_status"] = "terminal"
        response["lease_remaining_ms"] = None
        response["resource"]["state"] = "failed"
        return response

    monkeypatch.setattr(api, method_name, terminal_update)
    assert process(worker, kind)
    outputs = api.clarification_outputs if kind == "clarification" else api.outputs
    assert [output["state"] for output in outputs] == ["generating"]
    assert not provider.http_calls
    assert not api.permits and not api.receipts and not api.seals
    assert api.source_job == original
    assert active_token_meter() is None
