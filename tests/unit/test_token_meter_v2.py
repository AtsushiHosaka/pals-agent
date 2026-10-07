"""Exercise the real client/meter contract at isolated HTTP and ledger boundaries."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
import rfc8785

from pals_agent.billing_meter import billing_stage
from pals_agent.http_transport import HttpResponse
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_reuse_usage import model_role
from pals_agent.provider_usage import POLICY_V2, PRICING_PROFILE, ROLE_POLICY_V2, TARIFF_SNAPSHOTS
from pals_agent.token_meter import (
    TokenMeter,
    TokenMeterError,
    active_token_meter,
    token_meter_scope,
)
from tests.unit.test_token_meter import CLAIM, OP, REQUEST, Ledger, Provider


class StageLedger(Ledger):
    def __init__(self, events, **kwargs):
        super().__init__(events, **kwargs)
        self.seals = []

    def seal_token_stage(self, payload, *, timeout_seconds):
        self.events.append("seal")
        self.seals.append(payload)


class ExactProvider(Provider):
    def request(self, **kwargs):
        response = super().request(**kwargs)
        if kwargs["url"].endswith("/input_tokens") or response.status_code != 200:
            return response
        body = json.loads(response.body)
        body.update(object="response", id="resp_isolated_test", service_tier="default")
        if "usage" in body:
            body["usage"]["total_tokens"] = 38
            body["usage"]["input_tokens_details"]["cache_write_tokens"] = 3
        return HttpResponse(200, json.dumps(body).encode())


def context(model="gpt-6-luna", operation=OP):
    return {
        "proof_request_id": REQUEST,
        "generation_model": model,
        "billing_context": {
            "operation_id": operation,
            "policy_version": POLICY_V2,
            "generation_model": model,
            "role_policy_version": ROLE_POLICY_V2,
            "pricing_profile": PRICING_PROFILE,
            "price_snapshot_ids": TARIFF_SNAPSHOTS,
        },
    }


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-6.1-sol", "gpt-5.6-terra"])
def test_actual_usage_and_stage_manifest_share_immutable_call_binding(model):
    events = []
    api, provider = StageLedger(events), ExactProvider(events)
    client = OpenAIResponsesClient(api_key="test", transport=provider, max_output_tokens=40)
    with billing_stage(
        api, context(model), scope="generation", job_id="job-1", claim_id=CLAIM
    ) as meter:
        with model_role("prove"):
            assert client.generate(model=model, prompt="x") == "answer"
        assert meter is not None
        meter.complete("llm")
        with pytest.raises(TokenMeterError):
            client.generate(model=model, prompt="x")
    assert events == ["count", "permit", "generate", "receipt", "seal"]
    permit, receipt, seal = api.permits[0], api.receipts[0], api.seals[0]
    assert permit["price_snapshot_id"] == TARIFF_SNAPSHOTS[model]
    assert receipt["schema_version"] == "pals.token-receipt.v2"
    assert receipt["cache_write_input_tokens"] == 3
    assert receipt["total_tokens"] == 38
    assert receipt["usage_kind"] == "responses"
    assert seal["call_ids"] == [receipt["call_id"]] == [permit["call_id"]]
    assert seal["completed_roles"] == ["prove"]
    for field in ("operation_id", "request_id", "claim_id", "scope", "job_id"):
        assert seal[field] == receipt[field] == permit[field]


def test_canonical_rerank_wire_bytes_are_metered_without_rewriting_payload():
    events = []
    api, provider = StageLedger(events), ExactProvider(events)
    meter = TokenMeter(api, OP, REQUEST, CLAIM, time.monotonic() + 60, policy_version=POLICY_V2)
    payload = {
        "model": "gpt-6-luna",
        "input": "日本語",
        "max_output_tokens": 40,
        "service_tier": "default",
        "stream": False,
    }
    wire = rfc8785.dumps(payload)
    with token_meter_scope(meter), model_role("rerank"):
        meter.request(
            transport=provider,
            endpoint="https://api.openai.com/v1/responses",
            headers={},
            payload=payload,
            data=wire,
            timeout_seconds=20,
            call_id="44444444-4444-4444-8444-444444444444",
        )
    assert provider.calls[1]["body"] == wire
    assert api.permits[0]["model_role"] == "rerank"


def test_unknown_receipt_has_no_fabricated_counts_and_cannot_seal():
    events = []
    api, provider = StageLedger(events), ExactProvider(events, fault="missing_usage")
    client = OpenAIResponsesClient(api_key="test", transport=provider, max_output_tokens=40)
    with billing_stage(api, context(), scope="generation", job_id="job-1", claim_id=CLAIM) as meter:
        with pytest.raises(TokenMeterError):
            client.generate(model="gpt-6-luna", prompt="x")
        assert meter is not None
        with pytest.raises(TokenMeterError):
            meter.complete("llm")
    assert api.receipts[0]["status"] == "unknown"
    assert not any(key.endswith("tokens") for key in api.receipts[0])
    assert not api.seals


def test_stage_transition_requires_sealed_previous_stage_and_restores_context():
    api = StageLedger([])
    with billing_stage(
        api, context(), scope="semantic_review", job_id="job-1", claim_id=CLAIM, task_id=REQUEST
    ) as review:
        with (
            pytest.raises(TokenMeterError),
            billing_stage(api, context(), scope="explanation", job_id="job-1", claim_id=CLAIM),
        ):
            pass
        assert review is not None
        review.complete("llm")
        with billing_stage(
            api, context(), scope="explanation", job_id="job-1", claim_id=CLAIM
        ) as explanation:
            assert active_token_meter() is explanation
        assert active_token_meter() is review
    assert active_token_meter() is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("pricing_profile", "other-region"),
        ("generation_model", "gpt-5.6-terra"),
        ("price_snapshot_ids", {}),
        ("role_policy_version", "unknown-policy"),
        ("operation_id", "not-a-uuid"),
    ],
)
def test_invalid_admission_fails_before_any_provider_or_ledger_call(field, value):
    admitted = context()
    admitted["billing_context"][field] = value
    api = StageLedger([])
    with (
        pytest.raises(TokenMeterError),
        billing_stage(api, admitted, scope="generation", job_id="job-1", claim_id=CLAIM),
    ):
        pass
    assert not api.events


def test_concurrent_admissions_keep_operation_and_role_separate():
    barrier = Barrier(2)

    def run(model, operation):
        with (
            billing_stage(
                StageLedger([]),
                context(model, operation),
                scope="generation",
                job_id="job-1",
                claim_id=CLAIM,
            ) as meter,
            model_role("prove"),
        ):
            barrier.wait(timeout=5)
            assert active_token_meter() is meter
            return meter.operation_id

    second = "55555555-5555-4555-8555-555555555555"
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(run, "gpt-6-luna", OP)
        two = pool.submit(run, "gpt-5.6-terra", second)
        assert [one.result(), two.result()] == [OP, second]
    assert active_token_meter() is None


@pytest.mark.parametrize("kind", ["clarification", "explanation_retry"])
def test_independent_subject_is_carried_without_reopening_original_request(kind):
    events = []
    api, provider = StageLedger(events), ExactProvider(events)
    admitted = context("gpt-6.1-sol")
    subject = {"kind": kind, "id": "66666666-6666-4666-8666-666666666666"}
    admitted["billing_context"]["subject"] = subject
    scope = "clarification" if kind == "clarification" else "explanation"
    role = "clarify" if kind == "clarification" else "explain"
    client = OpenAIResponsesClient(api_key="test", transport=provider, max_output_tokens=40)
    with (
        billing_stage(
            api,
            admitted,
            scope=scope,
            job_id="job-1",
            claim_id=CLAIM,
            task_id=subject["id"] if kind == "clarification" else None,
        ) as meter,
        model_role(role),
    ):
        assert meter is not None and meter.request_id is None
        assert client.generate(model="gpt-6.1-sol", prompt="x") == "answer"
        meter.complete("llm")
    for value in (*api.permits, *api.receipts, *api.seals):
        assert value["subject"] == subject
        assert "request_id" not in value
        assert value["scope"] == scope
        assert value["job_id"] == "job-1"


@pytest.mark.parametrize(
    "subject,scope,task",
    [
        ({"kind": "proof_request", "id": REQUEST}, "explanation", None),
        ({"kind": "explanation_retry", "id": REQUEST}, "generation", None),
        ({"kind": "clarification", "id": REQUEST}, "clarification", CLAIM),
        ({"kind": "clarification", "id": REQUEST, "extra": "x"}, "clarification", REQUEST),
    ],
)
def test_independent_subject_mismatch_is_rejected_before_provider(subject, scope, task):
    admitted = context()
    admitted["billing_context"]["subject"] = subject
    api = StageLedger([])
    with (
        pytest.raises(TokenMeterError),
        billing_stage(api, admitted, scope=scope, job_id="job-1", claim_id=CLAIM, task_id=task),
    ):
        pass
    assert not api.events
