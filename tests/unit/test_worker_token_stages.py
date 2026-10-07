"""Real worker/model callers against isolated HTTP and billing ledger boundaries.

These are caller regressions, not provider or PostgreSQL acceptance evidence.
"""

import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest

from pals_agent.api_client import PalsApiError
from pals_agent.explanations import (
    LeanGroundedOutputReviewer,
    LeanProofExplainer,
    LeanProofSemanticReviewer,
)
from pals_agent.http_transport import HttpResponse
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_reuse_usage import current_role
from pals_agent.provider_usage import POLICY_V2, PRICING_PROFILE, TARIFF_SNAPSHOTS
from pals_agent.settings import AgentSettings
from pals_agent.token_meter import TokenMeterError, active_token_meter, token_meter_scope
from pals_agent.worker import SqsProofWorker
from tests.unit.test_worker import SemanticReviewApi

REQUEST = "44444444-4444-4444-8444-444444444444"
OPERATION = "55555555-5555-4555-8555-555555555555"
DELIVERY = "66666666-6666-4666-8666-666666666666"
JOB = "job-semantic"


class StageApi(SemanticReviewApi):
    def __init__(self, fault: tuple[str, str] | None = None):
        super().__init__()
        self.fault = fault
        self.events: list[tuple[str, str]] = []
        self.permits: list[dict[str, Any]] = []
        self.receipts: list[dict[str, Any]] = []
        self.seals: list[dict[str, Any]] = []
        self.outputs: list[dict[str, Any]] = []
        self.meters: dict[str, Any] = {}

    def get_proof_job(self, proof_job_id):
        job = super().get_proof_job(proof_job_id)
        job["output_language"] = "en"
        job["request_context"].update(
            proof_request_id=REQUEST,
            generation_model="gpt-6.1-sol",
            billing_context={
                "operation_id": OPERATION,
                "policy_version": POLICY_V2,
                "generation_model": "gpt-6.1-sol",
                "role_policy_version": "pals.billing-role-policy.v2-2026-10-07",
                "pricing_profile": PRICING_PROFILE,
                "price_snapshot_ids": TARIFF_SNAPSHOTS,
            },
        )
        return job

    def permit_token_call(self, payload, *, timeout_seconds):
        self.events.append(("permit", payload["scope"]))
        self.permits.append(payload)
        meter = active_token_meter()
        assert meter is not None
        self.meters[payload["scope"]] = meter

    def record_token_receipt(self, payload, *, timeout_seconds):
        self.events.append(("receipt", payload["scope"]))
        self.receipts.append(payload)
        if self.fault == ("receipt", payload["scope"]):
            raise PalsApiError("isolated receipt acknowledgement failure")

    def seal_token_stage(self, payload, *, timeout_seconds):
        self.events.append(("seal", payload["scope"]))
        if self.fault == ("seal", payload["scope"]):
            raise PalsApiError("isolated stage acknowledgement failure")
        receipts = [r for r in self.receipts if r["scope"] == payload["scope"]]
        assert all(r["status"] == "success" for r in receipts)
        assert set(payload["call_ids"]) == {r["call_id"] for r in receipts}
        self.seals.append(payload)

    def settle_proof_semantic_review(self, **kwargs):
        assert self.seals[-1]["scope"] == "semantic_review"
        self.events.append(("settle", "semantic_review"))
        result = super().settle_proof_semantic_review(**kwargs)
        self.state = result["state"]
        return result

    def upsert_proof_explanation(self, **kwargs):
        state = kwargs["state"]
        self.outputs.append(kwargs)
        self.events.append((state, "explanation"))
        if state == "completed":
            assert self.seals[-1]["scope"] == "explanation"
        return {
            "claim_status": "acquired" if state == "generating" else "terminal",
            "lease_remaining_ms": 3_600_000 if state == "generating" else None,
            "resource": {
                "proof_job_id": kwargs["proof_job_id"],
                "state": state,
                "content": kwargs.get("content"),
                "created_at": "2026-10-07T00:00:00Z",
                "updated_at": "2026-10-07T00:00:00Z",
                "diagnostics": kwargs.get("diagnostics", []),
            },
        }


class StageProvider:
    def __init__(self, api):
        self.api = api
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def request(self, **kwargs):
        payload = json.loads(kwargs["body"])
        if kwargs["url"].endswith("/input_tokens"):
            return HttpResponse(200, json.dumps({
                "object": "response.input_tokens", "input_tokens": 23,
            }).encode())
        role = current_role()
        self.calls.append((role, payload))
        self.api.events.append(("provider", role))
        if role == "explain":
            answer = {
                "overview": "Truth holds directly.",
                "sections": [{
                    "id": "truth", "title": "Truth", "summary": "The claim is true.",
                    "references": [{"start_line": 2, "end_line": 2, "excerpt": "  trivial"}],
                }],
                "conclusion": "This establishes the requested claim.",
            }
        else:
            assert role in {"proof_review", "explain_qa"}
            answer = {"approved": True, "rationale": "Matches the exact verified source."}
        body = {
            "object": "response", "id": f"resp_isolated_{len(self.calls)}",
            "status": "completed", "model": payload["model"], "service_tier": "default",
            "output_text": json.dumps(answer),
            "usage": {
                "input_tokens": 23, "output_tokens": 5, "total_tokens": 28,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }
        return HttpResponse(200, json.dumps(body).encode())


def setup_worker(fault=None):
    api = StageApi(fault)
    provider = StageProvider(api)

    def client():
        return OpenAIResponsesClient(api_key="isolated-test", transport=provider)

    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(explanation_model_timeout_seconds=17)),
        api_client=cast(Any, api), pipeline=None,
        explainer=LeanProofExplainer(client(), "gpt-6-luna", "openai", max_attempts=1),
        proof_reviewer=LeanProofSemanticReviewer(client(), "gpt-6-luna", "openai"),
        output_reviewer=LeanGroundedOutputReviewer(client(), "gpt-6-luna", "openai"),
    )
    return api, provider, worker, client


def test_worker_seals_semantic_review_then_uses_fresh_explanation_meter():
    api, provider, worker, client = setup_worker()
    assert worker.process_proof_job(JOB, claim_id=DELIVERY, extend_visibility=lambda _: None)
    assert [(role, p["model"]) for role, p in provider.calls] == [
        ("proof_review", "gpt-6-luna"),
        ("explain", "gpt-6.1-sol"),
        ("explain_qa", "gpt-6-luna"),
    ]
    assert [s["scope"] for s in api.seals] == ["semantic_review", "explanation"]
    semantic, explanation = api.seals
    assert semantic["claim_id"] == api.get_proof_job(JOB)["generation_session_id"]
    assert explanation["claim_id"] == DELIVERY
    assert semantic["task_id"] == api.get_proof_job(JOB)["verification_candidate_id"]
    assert "task_id" not in explanation
    assert semantic["completed_roles"] == ["proof_review"]
    assert explanation["completed_roles"] == ["explain", "explain_qa"]
    assert set(semantic["call_ids"]).isdisjoint(explanation["call_ids"])
    assert len({p["call_id"] for p in api.permits}) == 3
    for permit, receipt in zip(api.permits, api.receipts, strict=True):
        for field in ("operation_id", "request_id", "claim_id", "scope", "job_id", "call_id"):
            assert permit[field] == receipt[field]
        assert permit["operation_id"] == OPERATION
        assert permit["request_id"] == REQUEST
    assert api.events.index(("seal", "semantic_review")) < api.events.index(
        ("settle", "semantic_review")
    ) < api.events.index(("permit", "explanation"))
    assert api.events.index(("seal", "explanation")) < api.events.index(
        ("completed", "explanation")
    )
    assert api.outputs[-1]["content"]["model"] == "gpt-6.1-sol"
    assert api.outputs[-1]["review_evidence"]["reviewer"]["model"] == "gpt-6-luna"
    assert api.meters["semantic_review"] is not api.meters["explanation"]
    assert all(m.sealed for m in api.meters.values())
    assert active_token_meter() is None
    with token_meter_scope(api.meters["semantic_review"]), pytest.raises(TokenMeterError):
        client().generate(model="gpt-6-luna", prompt="cannot reuse sealed meter")
    assert len(provider.calls) == 3


@pytest.mark.parametrize("fault", [
    ("receipt", "semantic_review"), ("seal", "semantic_review"),
    ("receipt", "explanation"), ("seal", "explanation"),
])
def test_failed_receipt_or_seal_never_writes_completed_explanation(fault):
    api, _, worker, _ = setup_worker(fault)
    worker.process_proof_job(JOB, claim_id=DELIVERY, extend_visibility=lambda _: None)
    assert not any(output["state"] == "completed" for output in api.outputs)
    if fault[1] == "semantic_review":
        assert not api.evidence
        assert not api.outputs
    else:
        assert api.evidence
        assert api.outputs[-1]["state"] == "failed"
    assert api.meters[fault[1]].failed
    assert active_token_meter() is None


def test_recipe_actor_readback_uses_new_worker_explanation_stage():
    api, provider, worker, _ = setup_worker()
    original_get = api.get_proof_job

    def recipe_job(proof_job_id):
        job = original_get(proof_job_id)
        job["attempt_source"] = "recipe"
        return job

    api.get_proof_job = recipe_job

    class ActorBoundary:
        def request(self, **kwargs):
            # The dedicated actor owns semantic review; the root worker must not
            # wrap that HTTP dispatch in a second semantic billing meter.
            assert active_token_meter() is None
            assert kwargs["proof_job_id"] == JOB
            assert kwargs["candidate_id"] == original_get(JOB)["verification_candidate_id"]
            api.events.append(("actor_readback", "verified"))
            api.state = "verified"

    worker = replace(worker, recipe_review_dispatcher=ActorBoundary())
    assert worker.process_proof_job(JOB, claim_id=DELIVERY, extend_visibility=lambda _: None)
    assert [(role, p["model"]) for role, p in provider.calls] == [
        ("explain", "gpt-6.1-sol"), ("explain_qa", "gpt-6-luna"),
    ]
    assert len(api.seals) == 1
    seal = api.seals[0]
    assert seal["scope"] == "explanation"
    assert seal["claim_id"] == DELIVERY
    assert seal["completed_roles"] == ["explain", "explain_qa"]
    assert set(seal["call_ids"]) == {p["call_id"] for p in api.permits}
    assert len(seal["call_ids"]) == 2
    assert all(p["scope"] == "explanation" for p in api.permits)
    assert api.events.index(("actor_readback", "verified")) < api.events.index(
        ("permit", "explanation")
    )
    assert api.meters["explanation"].sealed
    assert api.outputs[-1]["state"] == "completed"
    assert active_token_meter() is None
