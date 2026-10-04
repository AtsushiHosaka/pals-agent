"""Real provider/client code with isolated HTTP responses, never paid model calls."""

import hashlib
import json
import time

import pytest

from pals_agent.api_client import PalsApiClient, PalsApiError
from pals_agent.http_transport import HttpDeadlineExceeded, HttpResponse
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_reuse_catalog import BoundedEmbeddingModel
from pals_agent.token_meter import TokenMeter, TokenMeterError, token_meter_scope
from pals_agent.usage import usage_scope

OP = "33333333-3333-4333-8333-333333333333"
REQUEST = "11111111-1111-4111-8111-111111111111"
CLAIM = "22222222-2222-4222-8222-222222222222"


class Ledger:
    def __init__(self, events, *, permit_error=False, receipt_error=False):
        self.events = events
        self.permits = []
        self.receipts = []
        self.permit_error = permit_error
        self.receipt_error = receipt_error

    def permit_token_call(self, payload, *, timeout_seconds):
        self.events.append("permit")
        self.permits.append(payload)
        if self.permit_error:
            if isinstance(self.permit_error, Exception):
                raise self.permit_error
            raise PalsApiError("response lost")

    def record_token_receipt(self, payload, *, timeout_seconds):
        self.events.append("receipt")
        self.receipts.append(payload)
        if self.receipt_error:
            if isinstance(self.receipt_error, Exception):
                raise self.receipt_error
            raise PalsApiError("response lost")


class Provider:
    def __init__(self, events, *, count=None, usage=None, fault=None):
        self.events = events
        self.calls = []
        self.count = count or {"object": "response.input_tokens", "input_tokens": 23}
        self.usage = (
            usage
            if usage is not None
            else {
                "input_tokens": 23,
                "output_tokens": 15,
                "input_tokens_details": {"cached_tokens": 7},
                "output_tokens_details": {"reasoning_tokens": 11},
            }
        )
        self.fault = fault

    def request(self, **kwargs):
        self.calls.append(kwargs)
        is_count = kwargs["url"].endswith("/input_tokens")
        self.events.append("count" if is_count else "generate")
        if is_count:
            return HttpResponse(200, json.dumps(self.count).encode())
        if self.fault == "timeout":
            raise HttpDeadlineExceeded("test timeout")
        if self.fault == "http":
            return HttpResponse(429, b'{"error":{"code":"insufficient_quota"}}')
        request = json.loads(kwargs["body"])
        body = {"model": request["model"], "usage": self.usage, "output_text": "answer"}
        if self.fault == "missing_usage":
            del body["usage"]
        return HttpResponse(200, json.dumps(body).encode())


def setup_meter(**provider_kwargs):
    events = []
    api = Ledger(events)
    provider = Provider(events, **provider_kwargs)
    meter = TokenMeter(api, OP, REQUEST, CLAIM, time.monotonic() + 180)
    client = OpenAIResponsesClient(api_key="test", transport=provider, max_output_tokens=40)
    return events, api, provider, meter, client


def generate(client):
    return client.generate(model="gpt-6-luna", prompt="数学の命題", timeout_seconds=20)


def test_count_then_permit_then_provider_then_receipt_preserves_cost_telemetry():
    events, api, provider, meter, client = setup_meter()
    costs = []
    with usage_scope(costs.append), token_meter_scope(meter):
        assert generate(client) == "answer"
    assert events == ["count", "permit", "generate", "receipt"]
    counted = json.loads(provider.calls[0]["body"])
    generated = json.loads(provider.calls[1]["body"])
    assert counted == {key: generated[key] for key in ("model", "input", "reasoning")}
    assert api.permits[0]["payload_sha256"] == hashlib.sha256(provider.calls[1]["body"]).hexdigest()
    assert api.permits[0]["input_token_bound"] == 23
    assert api.permits[0]["output_token_bound"] == 40
    assert api.receipts[0]["status"] == "success"
    assert api.receipts[0]["cached_input_tokens"] == 7
    assert api.receipts[0]["reasoning_output_tokens"] == 11
    assert costs[0]["call_id"] == api.permits[0]["call_id"] == api.receipts[0]["call_id"]
    assert meter.completed_calls == {api.receipts[0]["call_id"]: "proof_reuse_judge"}


def test_schema_is_counted_before_provider_not_just_visible_prompt():
    _, api, provider, meter, client = setup_meter()
    # Non-structured response intentionally fails downstream, but metering still records it.
    from pals_agent.openai import OpenAIError

    with token_meter_scope(meter), pytest.raises(OpenAIError):
        client.generate(model="gpt-6-luna", prompt="x", response_schema={"type": "object"})
    assert (
        json.loads(provider.calls[0]["body"])["text"]
        == json.loads(provider.calls[1]["body"])["text"]
    )
    assert api.receipts[0]["status"] == "success"


@pytest.mark.parametrize(
    "count",
    [
        {"object": "response.input_tokens", "input_tokens": True},
        {"object": "response.input_tokens", "input_tokens": -1},
        {"input_tokens": 23},
        {"object": "response.input_tokens", "input_tokens": 23, "x": 0},
    ],
)
def test_invalid_count_never_authorizes_or_generates(count):
    events, api, _, meter, client = setup_meter(count=count)
    with token_meter_scope(meter), pytest.raises(TokenMeterError):
        generate(client)
    assert events == ["count"] and not api.permits and not api.receipts


def test_uncertain_permit_never_generates_and_poison_is_sticky():
    events, api, _, meter, client = setup_meter()
    api.permit_error = True
    with token_meter_scope(meter):
        with pytest.raises(TokenMeterError):
            generate(client)
        api.permit_error = False
        with pytest.raises(TokenMeterError):
            generate(client)
    assert events == ["count", "permit"]


@pytest.mark.parametrize("fault", ["timeout", "http", "missing_usage"])
def test_incurred_but_unknown_usage_records_unknown_never_zero_success(fault):
    _, api, _, meter, client = setup_meter(fault=fault)
    with token_meter_scope(meter), pytest.raises(TokenMeterError):
        generate(client)
    assert api.receipts[0]["status"] == "unknown"
    assert not meter.completed_calls and meter.failed


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": 24, "output_tokens": 2},
        {"input_tokens": 23, "output_tokens": 41},
        {"input_tokens": 23, "output_tokens": True},
        {"input_tokens": 23, "output_tokens": 2, "input_tokens_details": {"cached_tokens": 24}},
        {"input_tokens": 23, "output_tokens": 2, "output_tokens_details": {"reasoning_tokens": 3}},
        {"input_tokens": 23, "output_tokens": 2, "input_tokens_details": None},
    ],
)
def test_invalid_or_above_permit_actual_usage_blocks_success(usage):
    _, api, _, meter, client = setup_meter(usage=usage)
    with token_meter_scope(meter), pytest.raises(TokenMeterError):
        generate(client)
    assert api.receipts[0]["status"] == "unknown" and meter.failed


def test_lost_success_receipt_ack_is_not_overwritten_or_retried():
    _, api, _, meter, client = setup_meter()
    api.receipt_error = True
    with token_meter_scope(meter), pytest.raises(TokenMeterError):
        generate(client)
    assert [r["status"] for r in api.receipts] == ["success"]
    assert meter.failed and not meter.completed_calls


def test_count_permit_generation_share_one_deadline(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("pals_agent.token_meter.time.monotonic", lambda: clock[0])
    _, api, provider, meter, client = setup_meter()
    original = provider.request

    def slow_count(**kwargs):
        result = original(**kwargs)
        clock[0] += 12
        return result

    provider.request = slow_count
    with token_meter_scope(meter), pytest.raises(TokenMeterError):
        generate(client)
    assert provider.calls[0]["timeout_seconds"] == 20
    assert provider.calls[1]["timeout_seconds"] == 8
    assert not meter.completed_calls  # provider used the remaining time before receipt
    assert not api.receipts or api.receipts[-1]["status"] == "unknown"


def test_images_and_unknown_models_rejected_before_any_external_request():
    _, api, provider, meter, _ = setup_meter()
    payload = {"model": "gpt-6-luna", "input": [{"type": "input_image"}], "max_output_tokens": 40}
    with pytest.raises(TokenMeterError):
        meter.request(
            transport=provider,
            endpoint="https://api.test/responses",
            headers={},
            payload=payload,
            data=json.dumps(payload).encode(),
            timeout_seconds=10,
            call_id=CLAIM,
        )
    assert not provider.calls and not api.permits


def test_embedding_reserves_documented_single_input_maximum_and_actual_receipt():
    events = []
    api = Ledger(events)

    class EmbeddingTransport:
        def request(self, **kwargs):
            events.append("embed")
            return HttpResponse(
                200,
                json.dumps(
                    {
                        "model": "text-embedding-3-small",
                        "usage": {"prompt_tokens": 31, "total_tokens": 31},
                        "data": [{"embedding": [1.0, 2.0]}],
                    }
                ).encode(),
            )

    embedding = BoundedEmbeddingModel(
        api_key="test",
        model="text-embedding-3-small",
        revision="test",
        dimension=2,
        transport=EmbeddingTransport(),
    )
    meter = TokenMeter(api, OP, REQUEST, CLAIM, time.monotonic() + 180)
    costs = []
    with usage_scope(costs.append), token_meter_scope(meter):
        assert embedding.embed("x²") == [1.0, 2.0]
    assert events == ["permit", "embed", "receipt"]
    assert api.permits[0]["input_token_bound"] == 8192
    assert api.permits[0]["output_token_bound"] == 0
    assert api.permits[0]["model_role"] == "draft_embedding"
    assert api.receipts[0]["input_tokens"] == 31
    assert costs[0]["call_id"] == api.receipts[0]["call_id"]


@pytest.mark.parametrize("body", [{"permitted": 1}, {"permitted": True, "extra": 0}, {}])
def test_api_permit_ack_is_closed_boolean(body):
    class Transport:
        def request(self, **kwargs):
            assert kwargs["url"].endswith("/v1/internal/billing/token-permits")
            assert kwargs["headers"]["X-PALS-Worker-Secret"] == "worker"
            assert kwargs["timeout_seconds"] == 3
            return HttpResponse(200, json.dumps(body).encode())

    with pytest.raises(PalsApiError):
        PalsApiClient("https://api.test", "worker", transport=Transport()).permit_token_call(
            {}, timeout_seconds=3
        )


def test_base_embedding_path_cannot_bypass_active_meter(monkeypatch):
    from pals_agent.draft_embeddings import OpenAIEmbeddingModel

    events = []
    api = Ledger(events)

    def provider(**kwargs):
        events.append("embed")
        return HttpResponse(
            200,
            json.dumps(
                {
                    "model": "text-embedding-3-small",
                    "usage": {"prompt_tokens": 4},
                    "data": [{"embedding": [0.1]}],
                }
            ).encode(),
        )

    monkeypatch.setattr(
        "pals_agent.draft_embeddings.HardDeadlineHttpTransport",
        lambda: type("Transport", (), {"request": staticmethod(provider)})(),
    )
    monkeypatch.setattr(
        "pals_agent.draft_embeddings.urlopen", lambda *a, **kw: pytest.fail("unmetered urllib path")
    )
    model = OpenAIEmbeddingModel(api_key="test", revision="test", dimension=1)
    with token_meter_scope(TokenMeter(api, OP, REQUEST, CLAIM, time.monotonic() + 180)):
        assert model.embed("x") == [0.1]
    assert events == ["permit", "embed", "receipt"]


def test_unknown_model_has_no_count_or_generation():
    _, api, provider, meter, client = setup_meter()
    with token_meter_scope(meter), pytest.raises(TokenMeterError):
        client.generate(model="new-unpriced-model", prompt="x")
    assert not provider.calls and not api.permits
