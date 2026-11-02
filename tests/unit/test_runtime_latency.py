"""Pure delegates plus actual paid TokenMeter/orchestration with offline HTTP fixtures.

No real claim, payment, provider call, AWS call, runtime evidence or timing claim.
"""

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from pals_agent import runtime_latency as h
from pals_agent.api_client import PalsApiClient
from pals_agent.chat_runtime import ChatRuntime
from pals_agent.http_transport import HardDeadlineHttpTransport, HttpResponse
from pals_agent.lightweight_http_transport import LightweightHttpTransport
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_request_worker import ProofRequestProcessor
from pals_agent.proof_reuse import ProofReuseRuntime
from tests.unit.test_recipe_semantic import CatalogBoundary, Provider, inputs
from tests.unit.test_token_meter import OP


def test_real_original_paid_runtime_has_count_permit_generation_usage_receipt_and_settle():
    request, batch, verdict = inputs()
    calls = []
    lock = threading.Lock()
    payloads = []

    class Api:
        def request(self, **kwargs):
            url = kwargs["url"]
            payload = json.loads(kwargs["body"])
            with lock:
                calls.append(url)
            if url.endswith("/claims"):
                value = {
                    "status": "acquired",
                    "request": dict(request, status="assessing"),
                    "claim_id": batch["claim_id"],
                    "lean_flow": True,
                    "math_conventions": request["math_conventions"],
                    "billing_operation_id": OP,
                    "lease_expires_at": (datetime.now(UTC) + timedelta(seconds=240)).isoformat(),
                }
            elif url.endswith("/recipe-batch"):
                value = batch
            elif url.endswith("/recipe-search"):
                value = {"recipes": []}
            elif url.endswith("/token-permits"):
                value = {"permitted": True}
            elif url.endswith(("/token-receipts", "/usage")):
                value = {"recorded": True}
            elif url.endswith("/settlements"):
                payloads.append(payload)
                value = {"id": request["id"], "status": payload["outcome"]}
            else:
                raise AssertionError("unexpected fixture path")
            return HttpResponse(200, json.dumps(value).encode())

    provider = Provider(verdict)
    reports = []
    class LegacyPaidApiClient(PalsApiClient):
        # Exercise the unchanged pre-atomic capability and its original 13 spans.
        record_semantic_token_result = None

    api = LegacyPaidApiClient(
        "https://api.fixture.invalid",
        "private-api-fixture",
        transport=h.TimedTransport(Api(), "api", "https://api.fixture.invalid"),
    )
    client = OpenAIResponsesClient(
        api_key="private-provider-fixture",
        transport=h.TimedTransport(provider, "provider", "https://api.openai.com/v1"),
    )
    original = ProofRequestProcessor(
        api,
        ChatRuntime(client, ProofReuseRuntime(client, CatalogBoundary())),
        token_accounting_enabled=True,
    )
    seen_visibility = []
    result = h.TracedProcessor(original, reports.append).process(
        request["id"], batch["claim_id"], seen_visibility.append
    )
    assert result is True and seen_visibility == [270] and len(reports) == 1
    assert (
        payloads[0]["outcome"] == "answered"
        and payloads[0]["answer"]["text"] == batch["recipes"][0]["answer"]
    )
    assert len(payloads[0]["usage"]) == len(provider.calls) == 2
    report = reports[0]
    phases = report["phases"]
    for role in ("recipe_semantic_assessment", "token_answer_qa"):
        for phase in ("input_tokens", "permit", "generation", "usage", "receipt"):
            rows = [r for r in phases if r["phase"] == phase and r["role"] == role]
            assert len(rows) == 1 and rows[0]["calls"] == 1
            assert rows[0]["http_status_counts"] == [{"status": 200, "count": 1}]
        ordered = {r["phase"]: r for r in phases if r["role"] == role}
        assert (
            ordered["input_tokens"]["last_end_offset_ms"]
            <= ordered["permit"]["first_start_offset_ms"]
        )
        assert (
            ordered["permit"]["last_end_offset_ms"]
            <= ordered["generation"]["first_start_offset_ms"]
        )
        assert (
            ordered["generation"]["last_end_offset_ms"] <= ordered["usage"]["first_start_offset_ms"]
        )
        assert ordered["usage"]["last_end_offset_ms"] <= ordered["receipt"]["first_start_offset_ms"]
    assert {r["phase"] for r in phases} >= {"claim", "batch_load", "settle"}
    assert report["dropped_spans"] == 0 and report["all_recorded_spans_finished"] is True
    assert h._ACTIVE.get() is None
    text = json.dumps(report)
    for private in (
        request["id"],
        batch["claim_id"],
        request["statement"],
        "private-api-fixture",
        "private-provider-fixture",
        "Authorization",
        "https://",
        "resp_",
    ):
        assert private not in text


def test_delegate_arguments_response_and_error_are_never_modified():
    calls = []
    response = SimpleNamespace(status_code=201)
    headers = {"Authorization": "private"}
    body = b"private body"

    class Delegate:
        def request(self, **kwargs):
            calls.append(kwargs)
            return response

    timed = h.TimedTransport(Delegate(), "api", "https://api.fixture.invalid")
    assert (
        timed.request(
            method="POST",
            url="https://api.fixture.invalid/path",
            headers=headers,
            body=body,
            timeout_seconds=3.25,
        )
        is response
    )
    assert (
        calls[0]["headers"] is headers
        and calls[0]["body"] is body
        and calls[0]["timeout_seconds"] == 3.25
    )
    assert h._ACTIVE.get() is None


def test_transport_exception_and_logging_failure_preserve_original_processor_exception():
    failure = RuntimeError("sensitive fixture failure")
    reports = []

    class Delegate:
        def request(self, **kwargs):
            raise failure

    timed = h.TimedTransport(Delegate(), "provider", "https://api.openai.com")

    class Process:
        def process(self, *args):
            return timed.request(
                method="POST",
                url="https://api.openai.com/v1/responses",
                headers={},
                body=b"not logged",
                timeout_seconds=1,
            )

    with pytest.raises(RuntimeError) as error:
        h.TracedProcessor(Process(), reports.append).process("request", "claim", lambda _: None)
    assert error.value is failure and h._ACTIVE.get() is None
    assert reports[0]["phases"][0]["transport_failures"] == 1
    assert "sensitive" not in json.dumps(reports)

    def broken_logger(report):
        raise ValueError("log sink unavailable")

    with pytest.raises(RuntimeError) as again:
        h.TracedProcessor(Process(), broken_logger).process("request", "claim", lambda _: None)
    assert again.value is failure


def test_cap_is_telemetry_only_and_never_drops_or_retries_a_real_transport_call():
    calls = []
    reports = []

    class Delegate:
        def request(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(status_code=204)

    timed = h.TimedTransport(Delegate(), "api", "https://api.fixture.invalid")

    class Process:
        def process(self, *args):
            for _ in range(70):
                timed.request(
                    method="POST",
                    url="https://api.fixture.invalid/unrecognized",
                    headers={},
                    body=None,
                    timeout_seconds=1,
                )
            return True

    assert (
        h.TracedProcessor(Process(), reports.append).process("request", "claim", lambda _: None)
        is True
    )
    assert (
        len(calls) == 70
        and reports[0]["recorded_spans"] == 32
        and reports[0]["dropped_spans"] == 38
    )
    assert reports[0]["phases"][0]["phase"] == "api_other"


def test_trace_and_logger_failures_cannot_change_successful_ack(monkeypatch):
    sentinel = object()

    class Process:
        def process(self, *args):
            return sentinel

    def fail(*args):
        raise RuntimeError("telemetry unavailable")

    monkeypatch.setattr(h._Trace, "summary", fail)
    assert (
        h.TracedProcessor(Process(), fail).process("request", "claim", lambda _: None) is sentinel
    )
    assert h._ACTIVE.get() is None


@pytest.mark.parametrize(
    "service,url,expected",
    [
        ("provider", "https://api.openai.com/v1/responses/input_tokens", "input_tokens"),
        ("provider", "https://api.openai.com/v1/responses", "generation"),
        ("provider", "https://other.invalid/v1/responses", "other_origin"),
        ("api", "https://api.openai.com/v1/internal/proof-requests/other/usage", "api_other"),
        ("provider", "https://api.openai.com/v1/responses?secret=private", "provider_other"),
        (
            "api", "https://api.openai.com/v1/internal/billing/semantic-call-results",
            "semantic_result",
        ),
        (
            "api", "https://other.invalid/v1/internal/billing/semantic-call-results",
            "other_origin",
        ),
        (
            "api", "https://api.openai.com/v1/internal/billing/semantic-call-results?secret=x",
            "api_other",
        ),
        (
            "api", "https://api.openai.com/v1/internal/billing/semantic-call-results/",
            "api_other",
        ),
    ],
)
def test_classification_is_closed_and_never_emits_paths_or_arbitrary_values(service, url, expected):
    assert (
        h._phase(service, h._origin("https://api.openai.com"), "POST", url, "request") == expected
    )


def test_thin_integration_adapter_preserves_process_arguments_and_result():
    reports = []

    def callback(seconds):
        return None

    sentinel = object()

    class Process:
        def process(self, request_id, claim_id, extend_visibility):
            assert request_id == "actual-delivery-request" and claim_id == "original-claim"
            assert extend_visibility is callback
            return sentinel

    assert (
        h.process_with_latency(
            Process(), "actual-delivery-request", "original-claim", callback, emit=reports.append
        )
        is sentinel
    )
    assert len(reports) == 1


def test_telemetry_failure_is_explicit_in_capture_quality_without_affecting_real_call(monkeypatch):
    reports = []

    class Delegate:
        def request(self, **kwargs):
            return SimpleNamespace(status_code=200)

    timed = h.TimedTransport(Delegate(), "provider", "https://api.openai.com")

    class Process:
        def process(self, *args):
            return timed.request(
                method="POST",
                url="https://api.openai.com/v1/responses",
                headers={},
                body=None,
                timeout_seconds=1,
            )

    def fail(*args):
        raise ValueError("instrumentation only")

    monkeypatch.setattr(h._Trace, "begin", fail)
    result = h.TracedProcessor(Process(), reports.append).process(
        "request", "claim", lambda _: None
    )
    assert result.status_code == 200 and reports[0]["instrumentation_errors"] == 1
    assert reports[0]["complete_timing_capture"] is False


def test_unclassifiable_url_keeps_original_transport_startup_and_response_behavior():
    sentinel = SimpleNamespace(status_code=200)

    class Delegate:
        def request(self, **kwargs):
            assert kwargs["url"] == "local/path"
            return sentinel

    timed = h.TimedTransport(Delegate(), "api", "local")
    assert (
        timed.request(method="POST", url="local/path", headers={}, body=None, timeout_seconds=1)
        is sentinel
    )
    assert h._phase("api", h._origin("local"), "POST", "local/path", "request") == "other_origin"


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_factory_shares_same_timed_provider_client_and_preserves_delegate_limits(
    monkeypatch, platform,
):
    from pals_agent.factory import build_proof_request_processor
    from pals_agent.settings import AgentSettings

    monkeypatch.setenv("PALS_OPENAI_API_KEY", "offline-fixture-only")
    monkeypatch.setattr(sys, "platform", platform)
    settings = AgentSettings.from_env()
    api = object()
    processor = build_proof_request_processor(settings, api)
    assert processor.api is api
    assert processor.runtime.client is processor.runtime.proof_runtime.client
    assert processor.runtime.client.max_output_tokens == 6000
    transport = processor.runtime.client.transport
    assert isinstance(transport, h.TimedTransport) and transport.service == "provider"
    assert transport.delegate.max_response_bytes == 1048576
    expected = LightweightHttpTransport if platform == "linux" else HardDeadlineHttpTransport
    assert isinstance(transport.delegate, expected)
    if platform != "linux":
        assert transport.delegate.process_start_method == "spawn"


def test_stderr_reporter_leaves_stdout_and_existing_logging_configuration_untouched(capsys):
    import logging

    before = (logging.root.level, list(logging.root.handlers))

    class Process:
        def process(self, *args):
            return True

    assert (
        h.process_with_latency(Process(), "request", "claim", lambda _: None, emit=h.report_latency)
        is True
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    event = json.loads(captured.err)
    assert event["event"] == "proof_request_latency"
    assert "request" not in event["metrics"] and "claim" not in event["metrics"]
    assert (logging.root.level, list(logging.root.handlers)) == before


def test_broken_stderr_does_not_change_successful_task_result(monkeypatch):
    class Stream:
        def write(self, value):
            raise BrokenPipeError("fixture log sink unavailable")

    monkeypatch.setattr(h.sys, "stderr", Stream())

    class Process:
        def process(self, *args):
            return True

    assert (
        h.process_with_latency(Process(), "request", "claim", lambda _: None, emit=h.report_latency)
        is True
    )


@pytest.mark.parametrize("platform", ["linux", "darwin"])
@pytest.mark.parametrize("lane", ["proof", "assessment"])
def test_cli_constructs_one_api_client_after_trust_with_exact_original_transport_limits(
    monkeypatch, platform, lane,
):
    from pals_agent import cli
    from pals_agent.api_client import RECIPE_SEARCH_RESPONSE_BYTES

    events = []
    monkeypatch.setattr(sys, "platform", platform)
    settings = SimpleNamespace(
        api_base_url="https://api.fixture.invalid",
        api_ca_certificate_path=None,
        proof_jobs_queue_url="proof",
        proof_requests_queue_url="assessment",
        worker_shared_secret="offline-fixture",
        proof_capability="full",
    )
    monkeypatch.setattr(cli.AgentSettings, "from_env", lambda: settings)
    monkeypatch.setattr(cli, "configure_worker_api_trust", lambda path: events.append("trust"))

    def api(**kwargs):
        assert events == ["trust"]
        events.append("client")
        transport = kwargs["transport"]
        assert isinstance(transport, h.TimedTransport)
        assert transport.service == "api" and transport.base_url == settings.api_base_url
        assert transport.delegate.max_response_bytes == RECIPE_SEARCH_RESPONSE_BYTES == 2097152
        expected = LightweightHttpTransport if platform == "linux" else HardDeadlineHttpTransport
        assert isinstance(transport.delegate, expected)
        assert isinstance(kwargs["attachment_transport"], expected)
        assert kwargs["attachment_transport"].max_response_bytes == 56_000_000
        if platform != "linux":
            assert transport.delegate.process_start_method == "spawn"
            assert kwargs["attachment_transport"].process_start_method == "spawn"
        return object()

    monkeypatch.setattr(cli, "PalsApiClient", api)
    for name in (
        "build_proof_explainer",
        "build_proof_output_reviewer",
        "build_proof_semantic_reviewer",
        "build_recipe_attempt_planner",
        "build_proof_request_processor",
    ):
        monkeypatch.setattr(cli, name, lambda *args: None)
    monkeypatch.setattr(
        cli, "SqsProofWorker", lambda **kwargs: SimpleNamespace(run_once=lambda: True)
    )
    assert cli.main(["worker-once", "--lane", lane]) == 0
    assert events == ["trust", "client"]


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_separate_semantic_judge_uses_same_static_transport_without_global_default_changes(
    monkeypatch, platform,
):
    from pals_agent.factory import build_semantic_stage_judge
    from pals_agent.settings import AgentSettings

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("PALS_OPENAI_API_KEY", "offline-fixture-only")
    settings = replace(
        AgentSettings.from_env(), semantic_evaluator_provider="openai",
        semantic_evaluator_model="independent-fixture", semantic_evaluator_revision="fixture-v1",
        semantic_evaluator_base_url="https://provider.fixture.invalid/v1",
    )
    judge = build_semantic_stage_judge(settings)
    expected = LightweightHttpTransport if platform == "linux" else HardDeadlineHttpTransport
    assert isinstance(judge.client.transport, expected)
    assert judge.client.transport.max_response_bytes == 1048576
    assert isinstance(OpenAIResponsesClient(api_key="offline-fixture").transport,
                      HardDeadlineHttpTransport)
    assert isinstance(PalsApiClient("https://api.fixture.invalid", "fixture").transport,
                      HardDeadlineHttpTransport)


def test_request_correlation_exact_known_hash_and_no_raw_identifiers(capsys):
    request = "00000000-0000-4000-8000-000000000001"

    class Process:
        def process(self, request_id, claim_id, extend_visibility):
            assert request_id == request and claim_id == "private-claim"
            return True

    assert h.process_with_latency(Process(), request, "private-claim", lambda _: None,
                                  emit=h.report_latency) is True
    captured = capsys.readouterr()
    assert captured.out == ""
    report = json.loads(captured.err)["metrics"]
    assert report["request_correlation_sha256"] == (
        "11e594f481958c10e3015d0bf0447a22f068a8a647f475df15ce2c7ab4b8f3f1"
    )
    assert request not in captured.err and "private-claim" not in captured.err


@pytest.mark.parametrize("value", ["private free text", "opaque-invalid-request-id", "0"*32,
                                    "00000000-0000-1000-8000-000000000001"])
def test_correlation_only_fingerprints_canonical_request_uuid_without_gating_tasks(value):
    reports = []

    class Process:
        def process(self, *args):
            return True

    assert h.TracedProcessor(Process(), reports.append).process(value, "claim", lambda _: None)
    assert reports[0]["request_correlation_sha256"] is None
    assert value not in json.dumps(reports)


def test_concurrent_requests_keep_correlation_and_phase_aggregates_separate():
    identifiers = ("00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002")
    expected = {
        "11e594f481958c10e3015d0bf0447a22f068a8a647f475df15ce2c7ab4b8f3f1",
        "e79acd97ac88086665d85a762f43d533a45195b6bac5961a993e6ed362471439",
    }
    barrier = threading.Barrier(2)
    reports = []

    class Delegate:
        def request(self, **kwargs):
            return HttpResponse(200, b"ok")

    transport = h.TimedTransport(Delegate(), "api", "https://api.fixture.invalid")

    class Process:
        def process(self, request_id, *args):
            barrier.wait(timeout=2)
            return transport.request(method="POST", url=(
                "https://api.fixture.invalid/v1/internal/proof-requests/"+request_id+"/usage"
            ), headers={}, body=None, timeout_seconds=1).body

    def run(identifier):
        return h.TracedProcessor(Process(), reports.append).process(
            identifier, "claim", lambda _: None,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, identifiers)) == [b"ok", b"ok"]
    assert {r["request_correlation_sha256"] for r in reports} == expected
    assert all(r["recorded_spans"] == 1 and r["phases"][0]["phase"] == "usage"
               and r["phases"][0]["calls"] == 1 for r in reports)
    assert all(identifier not in json.dumps(reports) for identifier in identifiers)
    assert h._ACTIVE.get() is None


def test_semantic_result_phase_requires_same_api_origin_and_post():
    url = "https://api.fixture.invalid/v1/internal/billing/semantic-call-results"
    origin = h._origin("https://api.fixture.invalid")
    assert h._phase("api", origin, "POST", url, "request") == "semantic_result"
    assert h._phase("api", origin, "GET", url, "request") == "api_other"
    assert h._phase("provider", origin, "POST", url, "request") == "provider_other"
