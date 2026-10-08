"""Real worker/API client protocol; isolated HTTP responses, no provider or DB calls."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from pals_agent.api_client import PalsApiClient
from pals_agent.http_transport import HttpResponse
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_request_worker import ProofRequestProcessor
from pals_agent.proof_reuse import ProofReuseRuntime
from tests.unit.test_proof_request_worker import CLAIM_ID, REQUEST_ID, ApiBoundary
from tests.unit.test_proof_reuse import READY, CatalogBoundary, decision
from tests.unit.test_token_meter import OP
from tests.unit.test_token_proof_request import CountedProvider

ABSENT = object()


class ClaimTransport:
    def __init__(self, events, *, marker=ABSENT, operation=OP, claim_overrides=None,
                 deny_permit=False):
        self.events = events
        self.claim = ApiBoundary().acquire_proof_request_claim(claim_id=CLAIM_ID)
        if marker is not ABSENT:
            self.claim["complimentary_token_operation"] = marker
        if operation is not ABSENT:
            self.claim["billing_operation_id"] = operation
        self.claim.update(claim_overrides or {})
        self.deny_permit = deny_permit
        self.permits = []
        self.receipts = []
        self.settlements = []

    def request(self, **kwargs):
        assert kwargs["method"] == "POST"
        assert kwargs["headers"]["X-PALS-Worker-Secret"] == "test-worker-secret"
        body = json.loads(kwargs["body"])
        url = kwargs["url"]
        if url.endswith("/claims"):
            assert body == {"claim_id": CLAIM_ID, "lease_ms": 240000}
            response = self.claim
        elif url.endswith("/token-permits"):
            self.events.append("permit")
            self.permits.append(body)
            if self.deny_permit:
                return HttpResponse(409, b'{"detail":{"code":"token_claim_lost"}}')
            response = {"permitted": True}
        elif url.endswith("/token-receipts"):
            self.events.append("receipt")
            self.receipts.append(body)
            response = {"recorded": True}
        elif url.endswith("/usage"):
            response = {"recorded": True}
        elif url.endswith("/settlements"):
            self.settlements.append(body)
            response = {"id": REQUEST_ID, "status": body["outcome"]}
        else:
            pytest.fail(f"Unexpected API path: {url}")
        return HttpResponse(200, json.dumps(response).encode())


def run(*, responses=None, enabled=False, missing_usage_on=None, **claim_options):
    events = []
    transport = ClaimTransport(events, **claim_options)
    api = PalsApiClient("https://api.example.test", "test-worker-secret", transport=transport)
    provider = CountedProvider(responses or [], events, missing_usage_on=missing_usage_on)
    runtime = ProofReuseRuntime(
        OpenAIResponsesClient(api_key="test", transport=provider), CatalogBoundary()
    )
    processed = ProofRequestProcessor(api, runtime, token_accounting_enabled=enabled).process(
        REQUEST_ID, CLAIM_ID, lambda _: None
    )
    return processed, transport, provider, events


def test_acquired_qa_claim_works_with_global_flag_off_through_real_token_client():
    processed, transport, provider, events = run(
        marker=True, responses=[READY, decision(), {"approved": True, "rationale": "Verified"}]
    )
    assert processed
    assert events == ["count", "permit", "generate", "receipt"] * 3
    assert len(provider.calls) == len(transport.receipts) == 3
    assert transport.settlements[0]["outcome"] == "answered"
    assert transport.settlements[0]["private_evidence"]["token_qa"]["approved"] is True
    for payload in [*transport.permits, *transport.receipts]:
        assert payload["operation_id"] == OP
        assert payload["request_id"] == REQUEST_ID
        assert payload["claim_id"] == CLAIM_ID


@pytest.mark.parametrize("marker", [ABSENT, False])
def test_ordinary_token_claim_still_requires_global_flag(marker):
    processed, transport, provider, events = run(marker=marker)
    assert processed and not events and not provider.calls and not provider.counts
    assert transport.settlements[0]["error_code"] == "proof_reuse_token_accounting_failed"


@pytest.mark.parametrize("marker", [ABSENT, False])
def test_enabled_paid_token_claim_remains_compatible(marker):
    processed, transport, _, events = run(
        marker=marker, enabled=True,
        responses=[READY, decision(), {"approved": True, "rationale": "Verified"}],
    )
    assert processed and events == ["count", "permit", "generate", "receipt"] * 3
    assert transport.settlements[0]["outcome"] == "answered"


@pytest.mark.parametrize("marker", [None, 0, 1, "true", {}, []])
@pytest.mark.parametrize("enabled", [False, True])
def test_non_boolean_claim_marker_is_rejected_even_if_global_flag_is_on(marker, enabled):
    processed, transport, provider, events = run(marker=marker, enabled=enabled)
    assert not processed and not events and not provider.calls and not transport.settlements


def test_true_marker_without_operation_never_falls_back_to_legacy():
    processed, transport, provider, events = run(marker=True, operation=ABSENT)
    assert not processed and not events and not provider.calls and not transport.settlements


@pytest.mark.parametrize("operation", [None, "bad", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"])
def test_true_marker_still_requires_canonical_operation(operation):
    processed, transport, provider, events = run(marker=True, operation=operation)
    assert processed and not events and not provider.calls and not provider.counts
    assert transport.settlements[0]["outcome"] == "failed"


@pytest.mark.parametrize("overrides", [
    {"claim_id": OP},
    {"request": {"id": OP, "revision": 2, "status": "assessing"}},
    {"status": "busy"},
    {"lease_expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
])
def test_qa_marker_cannot_bypass_claim_identity_request_or_lease(overrides):
    processed, transport, provider, events = run(marker=True, claim_overrides=overrides)
    assert not processed and not events and not provider.calls and not transport.settlements


def test_request_content_cannot_activate_qa_token_exemption():
    request = ApiBoundary().acquire_proof_request_claim(claim_id=CLAIM_ID)["request"]
    request["complimentary_token_operation"] = True
    processed, transport, provider, events = run(claim_overrides={"request": request})
    assert processed and not events and not provider.calls
    assert transport.settlements[0]["outcome"] == "failed"


@pytest.mark.parametrize("marker", [ABSENT, False])
def test_legacy_claim_without_billing_binding_retains_legacy_behavior(marker):
    processed, transport, provider, events = run(
        marker=marker, operation=ABSENT,
        responses=[READY, decision(), {"approved": True, "rationale": "Verified"}],
    )
    assert processed and len(provider.calls) == 3
    assert events == ["generate"] * 3
    assert not transport.permits and not transport.receipts
    assert transport.settlements[0]["outcome"] == "answered"


def test_qa_exemption_requires_configured_token_permit_and_receipt_client():
    class NoTokenClient(ApiBoundary):
        def acquire_proof_request_claim(self, **kwargs):
            return dict(super().acquire_proof_request_claim(**kwargs),
                        complimentary_token_operation=True, billing_operation_id=OP)

    api = NoTokenClient()
    events = []
    provider = CountedProvider([], events)
    runtime = ProofReuseRuntime(
        OpenAIResponsesClient(api_key="test", transport=provider), CatalogBoundary()
    )
    assert ProofRequestProcessor(api, runtime).process(REQUEST_ID, CLAIM_ID, lambda _: None)
    assert not events and not provider.calls and not provider.counts
    assert api.settlements[0]["error_code"] == "proof_reuse_token_accounting_failed"


def test_qa_marker_never_bypasses_backend_permit_denial():
    processed, transport, provider, events = run(marker=True, deny_permit=True)
    assert processed and events == ["count", "permit"]
    assert not provider.calls and not transport.receipts
    assert transport.settlements[0]["outcome"] == "failed"


def test_qa_exemption_preserves_independent_answer_review():
    processed, transport, provider, events = run(
        marker=True,
        responses=[READY, decision(), {"approved": False, "rationale": "Invalid argument"}],
    )
    assert processed and len(provider.calls) == 3
    assert events == ["count", "permit", "generate", "receipt"] * 3
    assert transport.settlements[0]["answer"] is None
    assert transport.settlements[0]["error_code"] == "proof_reuse_answer_review_failed"


@pytest.mark.parametrize("call", [1, 2, 3])
def test_qa_exemption_unknown_usage_still_fails_closed(call):
    processed, transport, provider, _ = run(
        marker=True, responses=[READY, decision(), {"approved": True, "rationale": "Verified"}],
        missing_usage_on=call,
    )
    assert processed and len(provider.calls) == call
    assert transport.receipts[-1]["status"] == "unknown"
    assert transport.settlements[0]["answer"] is None
    assert transport.settlements[0]["error_code"] == "proof_reuse_token_accounting_failed"
