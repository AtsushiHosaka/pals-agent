"""Paid semantic atomic-write orchestration against isolated network boundaries.

These tests do not claim actual provider calls, DB transactions or deployment.
"""

import copy
import json
import time
from datetime import UTC, datetime, timedelta
from threading import Lock

import pytest

from pals_agent import runtime_latency
from pals_agent.api_client import PalsApiClient, PalsApiError
from pals_agent.chat_runtime import ChatRuntime
from pals_agent.http_transport import HttpResponse
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_request_worker import ProofRequestProcessor
from pals_agent.proof_reuse import ProofReuseRuntime
from pals_agent.proof_reuse_usage import model_role
from pals_agent.recipe_semantic import SemanticReuseError, attempt
from pals_agent.token_meter import TokenMeter, TokenMeterError, token_meter_scope
from pals_agent.usage import usage_is_acknowledged, usage_scope
from tests.unit.test_proof_request_worker import ApiBoundary
from tests.unit.test_proof_reuse import CatalogBoundary
from tests.unit.test_recipe_semantic import Provider as SemanticProvider
from tests.unit.test_recipe_semantic import inputs
from tests.unit.test_token_meter import CLAIM, OP, REQUEST, Ledger, Provider


@pytest.fixture(autouse=True)
def judges_only(monkeypatch):
    """Call-count tests cover the judges; test_recipe_semantic_retrieval covers the vector."""
    monkeypatch.setattr("pals_agent.recipe_semantic.query_embedding", lambda *a, **k: None)


class AtomicLedger(Ledger):
    def __init__(self, events, *, lost_ack=False):
        super().__init__(events)
        self.atomic = []
        self.lost_ack = lost_ack

    def record_semantic_token_result(self, payload, *, timeout_seconds):
        self.events.append("atomic")
        self.atomic.append(copy.deepcopy(payload))
        if self.lost_ack:
            # Synthetic commit succeeded; only the HTTP acknowledgement was lost.
            raise PalsApiError("unit-only acknowledgement loss")


class IdentifiedProvider(Provider):
    def request(self, **kwargs):
        response = super().request(**kwargs)
        if kwargs["url"].endswith("/input_tokens"):
            return response
        body = json.loads(response.body)
        body["id"] = "resp_actual_boundary_1"
        return HttpResponse(response.status_code, json.dumps(body).encode())


def single_call(
    *,
    role="recipe_semantic_assessment",
    lost_ack=False,
    usage=None,
    alter=None,
    response_status=None,
):
    events = []
    ledger = AtomicLedger(events, lost_ack=lost_ack)
    provider = IdentifiedProvider(events, usage=usage)
    if alter is not None or response_status is not None:
        original = provider.request

        def changed(**kwargs):
            response = original(**kwargs)
            if kwargs["url"].endswith("/input_tokens"):
                return response
            body = json.loads(response.body)
            if alter is not None:
                alter(body)
            return HttpResponse(
                response.status_code if response_status is None else response_status,
                json.dumps(body).encode(),
            )

        provider.request = changed
    meter = TokenMeter(ledger, OP, REQUEST, CLAIM, time.monotonic() + 30)
    client = OpenAIResponsesClient(
        api_key="isolated-boundary", transport=provider, max_output_tokens=40
    )
    records = []
    acknowledged = []

    def record(value):
        records.append(value)
        acknowledged.append(usage_is_acknowledged(value["call_id"]))

    def invoke():
        with usage_scope(record), model_role(role), token_meter_scope(meter):
            return client.generate(model="gpt-6-luna", prompt="unit-only mathematical request")

    return events, ledger, provider, meter, records, acknowledged, invoke


@pytest.mark.parametrize("role", ["recipe_semantic_assessment", "token_answer_qa"])
def test_count_permit_provider_then_one_atomic_write_and_one_local_report(role):
    events, api, provider, meter, records, ack, invoke = single_call(role=role)
    assert invoke() == "answer"
    assert events == ["count", "permit", "generate", "atomic"]
    assert len(api.atomic) == len(records) == 1 and api.receipts == [] and ack == [True]
    payload = api.atomic[0]
    assert set(payload) == {"usage", "receipt"}
    assert payload["usage"]["call_id"] == payload["receipt"]["call_id"] == records[0]["call_id"]
    assert (
        payload["usage"]["reasoning_tokens"] == payload["receipt"]["reasoning_output_tokens"] == 11
    )
    assert payload["receipt"]["operation_id"] == OP and payload["receipt"]["status"] == "success"
    assert payload["usage"]["provider_request_id"] == "resp_actual_boundary_1"
    assert meter.completed_calls == {records[0]["call_id"]: role}
    assert len(provider.calls) == 2 and not usage_is_acknowledged(records[0]["call_id"])


def test_lost_atomic_ack_never_overwrites_committed_success_or_repeats_provider():
    events, api, provider, meter, records, ack, invoke = single_call(lost_ack=True)
    with pytest.raises(TokenMeterError):
        invoke()
    assert meter.failed and not meter.completed_calls
    assert len(api.atomic) == len(records) == 1 and ack == [False]
    assert api.receipts == [] and events == ["count", "permit", "generate", "atomic"]
    with pytest.raises(TokenMeterError):
        invoke()
    assert len(provider.calls) == 2 and len(api.atomic) == 1


@pytest.mark.parametrize("mutation", ["wrong_model", "exceeds_permit", "missing_id"])
def test_pre_atomic_failures_keep_legacy_cost_and_unknown_permit(mutation):
    def alter(body):
        if mutation == "wrong_model":
            body["model"] = "gpt-6.1-sol"
        elif mutation == "exceeds_permit":
            body["usage"]["input_tokens"] = 24
        else:
            body.pop("id")

    _, api, _, meter, records, ack, invoke = single_call(alter=alter)
    with pytest.raises(TokenMeterError):
        invoke()
    assert meter.failed and not api.atomic and api.receipts[0]["status"] == "unknown"
    assert len(records) == 1 and ack == [False]


@pytest.mark.parametrize("role", ["chat_intent", "proof_reuse_judge", "formal_draft_sketch"])
def test_other_roles_keep_legacy_receipt_and_reporting(role):
    events, api, _, _, records, ack, invoke = single_call(role=role)
    assert invoke() == "answer"
    assert events == ["count", "permit", "generate", "receipt"] and not api.atomic
    assert len(records) == 1 and ack == [False]


def test_embedding_keeps_legacy_even_with_semantic_role_and_atomic_method():
    api = AtomicLedger([])

    class EmbeddingProvider:
        def request(self, **kwargs):
            return HttpResponse(
                200, b'{"model":"text-embedding-3-small","usage":{"prompt_tokens":23}}'
            )

    meter = TokenMeter(api, OP, REQUEST, CLAIM, time.monotonic() + 30)
    payload = {"model": "text-embedding-3-small", "input": "unit only", "dimensions": 1536}
    records = []
    with usage_scope(records.append), model_role("token_answer_qa"):
        meter.request(
            transport=EmbeddingProvider(),
            endpoint="https://api.invalid/embeddings",
            headers={},
            payload=payload,
            data=json.dumps(payload).encode(),
            timeout_seconds=20,
            call_id="44444444-4444-4444-8444-444444444444",
            embedding=True,
        )
    assert not api.atomic and api.receipts[0]["output_tokens"] == 0
    assert records[0]["model"] == "text-embedding-3-small"


class AtomicProcessorApi(ApiBoundary):
    def __init__(self, r, batch, *, lost_review_ack=False):
        super().__init__()
        self.r, self.batch, self.lost_review_ack = r, batch, lost_review_ack
        self.permits, self.receipts, self.atomic = [], [], []
        self.lock = Lock()

    def acquire_proof_request_claim(self, **kwargs):
        return {
            "status": "acquired",
            "request": dict(self.r, status="assessing"),
            "claim_id": self.batch["claim_id"],
            "lean_flow": True,
            "math_conventions": self.r["math_conventions"],
            "billing_operation_id": OP,
            "lease_expires_at": (datetime.now(UTC) + timedelta(seconds=240)).isoformat(),
        }

    def get_proof_request_recipe_window(self, **kwargs):
        return self.batch

    def permit_token_call(self, payload, **kwargs):
        with self.lock:
            self.permits.append(copy.deepcopy(payload))

    def record_token_receipt(self, payload, **kwargs):
        with self.lock:
            self.receipts.append(copy.deepcopy(payload))

    def record_semantic_token_result(self, payload, **kwargs):
        with self.lock:
            self.atomic.append(copy.deepcopy(payload))
        if self.lost_review_ack and payload["usage"]["model_role"] == "token_answer_qa":
            raise PalsApiError("unit-only commit acknowledgement lost")


def process(*, lost_review_ack=False):
    r, batch, verdict = inputs()
    api = AtomicProcessorApi(r, batch, lost_review_ack=lost_review_ack)
    provider = SemanticProvider(verdict)
    client = OpenAIResponsesClient(api_key="isolated-boundary", transport=provider)
    runtime = ChatRuntime(client, ProofReuseRuntime(client, CatalogBoundary()))
    assert ProofRequestProcessor(api, runtime, token_accounting_enabled=True).process(
        r["id"],
        batch["claim_id"],
        lambda _: None,
    )
    return api, provider


def test_processor_skips_only_acknowledged_usage_http_and_keeps_settlement_usage():
    api, provider = process()
    assert len(provider.calls) == len(api.permits) == len(api.atomic) == 2
    assert not api.usage and not api.receipts
    payload = api.settlements[0]
    assert payload["outcome"] == "answered" and len(payload["usage"]) == 2
    assert {r["call_id"] for r in payload["usage"]} == {p["usage"]["call_id"] for p in api.atomic}
    assert all("acknowledged" not in str(u) for u in payload["usage"])
    assert len({p["usage"]["provider_request_id"] for p in api.atomic}) == 2


def test_processor_commit_ack_loss_still_joins_peer_retains_costs_and_never_answers():
    api, provider = process(lost_review_ack=True)
    payload = api.settlements[0]
    assert payload["outcome"] == "failed" and len(provider.calls) == 2
    assert len(payload["usage"]) == 2 and len(api.usage) >= 1
    committed = {p["receipt"]["call_id"] for p in api.atomic}
    assert all(p["call_id"] not in committed for p in api.receipts)
    assert len(committed) == len(api.atomic)


def test_independent_parser_failure_still_joins_successful_atomic_peer():
    r, batch, verdict = inputs()
    provider = SemanticProvider(verdict, malformed=True)
    ledger = AtomicLedger([])
    meter = TokenMeter(ledger, OP, r["id"], batch["claim_id"], time.monotonic() + 30)
    records = []
    with usage_scope(records.append), token_meter_scope(meter), pytest.raises(SemanticReuseError):
        attempt(
            OpenAIResponsesClient(api_key="isolated-boundary", transport=provider),
            r,
            batch["claim_id"],
            lambda _vector: batch,
            deadline=time.monotonic() + 30,
        )
    assert (
        provider.returned.is_set()
        and len(provider.calls) == len(ledger.atomic) == len(records) == 2
    )
    assert not ledger.receipts


@pytest.mark.parametrize(
    "reply",
    [
        {"usage_recorded": True, "receipt_recorded": False},
        {"usage_recorded": 1, "receipt_recorded": True},
        {"recorded": True},
        {"usage_recorded": True, "receipt_recorded": True, "extra": 1},
    ],
)
def test_atomic_client_requires_both_exact_success_acknowledgements(reply):
    class Transport:
        def request(self, **kwargs):
            assert kwargs["url"].endswith("/v1/internal/billing/semantic-call-results")
            assert kwargs["headers"]["X-PALS-Worker-Secret"] == "unit-only"
            return HttpResponse(200, json.dumps(reply).encode())

    api = PalsApiClient("https://api.invalid", "unit-only", transport=Transport())
    with pytest.raises(PalsApiError):
        api.record_semantic_token_result({"usage": {}, "receipt": {}}, timeout_seconds=2)


def test_acknowledgement_is_exact_call_scoped_and_reset_on_error():
    from pals_agent.usage import acknowledged_usage_scope

    call = "44444444-4444-4444-8444-444444444444"
    other = "55555555-5555-4555-8555-555555555555"
    assert not usage_is_acknowledged(None)
    with pytest.raises(RuntimeError), acknowledged_usage_scope(call):
        assert usage_is_acknowledged(call) and not usage_is_acknowledged(other)
        raise RuntimeError("unit-only local failure")
    assert not usage_is_acknowledged(call)
    with pytest.raises(ValueError), acknowledged_usage_scope("not-a-call"):
        pytest.fail("invalid acknowledgement scope must never enter")


def test_real_api_client_processor_uses_seven_worker_http_requests_not_nine():
    """Network-isolated protocol count only, not a measured latency improvement."""
    r, batch, verdict = inputs()
    api_calls = []

    class ApiTransport:
        def request(self, **kwargs):
            api_calls.append(kwargs)
            assert kwargs["headers"]["X-PALS-Worker-Secret"] == "unit-only"
            path = kwargs["url"].rsplit("/", 1)[-1]
            if path == "claims":
                value = {
                    "status": "acquired",
                    "request": dict(r, status="assessing"),
                    "claim_id": batch["claim_id"],
                    "lean_flow": True,
                    "math_conventions": r["math_conventions"],
                    "billing_operation_id": OP,
                    "lease_expires_at": (datetime.now(UTC) + timedelta(seconds=240)).isoformat(),
                }
            elif path == "recipe-window":
                value = batch
            elif path == "token-permits":
                value = {"permitted": True}
            elif path == "semantic-call-results":
                body = json.loads(kwargs["body"])
                assert set(body) == {"usage", "receipt"}
                assert body["usage"]["call_id"] == body["receipt"]["call_id"]
                value = {"usage_recorded": True, "receipt_recorded": True}
            elif path == "settlements":
                body = json.loads(kwargs["body"])
                assert body["outcome"] == "answered" and len(body["usage"]) == 2
                value = {"id": r["id"], "status": "answered"}
            else:
                pytest.fail("unexpected internal request: " + path)
            return HttpResponse(200, json.dumps(value).encode())

    api = PalsApiClient(
        "https://api.invalid",
        "unit-only",
        transport=runtime_latency.TimedTransport(ApiTransport(), "api", "https://api.invalid"),
    )
    provider = SemanticProvider(verdict)
    client = OpenAIResponsesClient(
        api_key="isolated-boundary",
        transport=runtime_latency.TimedTransport(provider, "provider", "https://api.openai.com"),
    )
    runtime = ChatRuntime(client, ProofReuseRuntime(client, CatalogBoundary()))
    reports = []
    processor = ProofRequestProcessor(api, runtime, token_accounting_enabled=True)
    assert runtime_latency.TracedProcessor(processor, reports.append).process(
        r["id"],
        batch["claim_id"],
        lambda _: None,
    )
    paths = [call["url"].rsplit("/", 1)[-1] for call in api_calls]
    assert len(paths) == 7 and len(provider.calls) == 2
    assert paths.count("token-permits") == paths.count("semantic-call-results") == 2
    assert "usage" not in paths and "token-receipts" not in paths
    report = reports[0]
    assert report["recorded_spans"] == 11 and report["complete_timing_capture"] is True
    for role in ("recipe_semantic_assessment", "token_answer_qa"):
        phases = [p for p in report["phases"] if p["role"] == role]
        assert {p["phase"] for p in phases} == {
            "input_tokens",
            "permit",
            "generation",
            "semantic_result",
        }
        assert all(p["calls"] == 1 and p["elapsed_total_ms"] >= 0 for p in phases)
    rendered = json.dumps(report)
    for private in (
        "https://",
        "unit-only",
        "isolated-boundary",
        r["statement"],
        r["id"],
        batch["claim_id"],
        "Authorization",
        "resp_",
        "provider_request_id",
    ):
        assert private not in rendered


@pytest.mark.parametrize("role", ["recipe_semantic_assessment", "proof_reuse_judge"])
def test_non2xx_usage_shaped_body_keeps_existing_unknown_without_reporting_success(role):
    _, api, _, meter, records, _, invoke = single_call(role=role, response_status=503)
    with pytest.raises(TokenMeterError):
        invoke()
    assert meter.failed and not meter.completed_calls and not records
    assert not api.atomic and api.receipts[0]["status"] == "unknown"
