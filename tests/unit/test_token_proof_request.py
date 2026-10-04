"""Natural token requests traverse production orchestration and provider parsing.

HTTP/ledger doubles prove protocol behavior, not real model quality or PostgreSQL.
"""

import hashlib
import json

import pytest

from pals_agent.api_client import PalsApiError
from pals_agent.http_transport import HttpResponse
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_request_worker import ProofRequestProcessor
from pals_agent.proof_reuse import ProofReuseRuntime
from tests.unit.test_proof_request_worker import CLAIM_ID, REQUEST_ID, ApiBoundary
from tests.unit.test_proof_reuse import READY, CatalogBoundary, ProviderTransport, decision
from tests.unit.test_token_meter import OP, Ledger


class TokenApi(ApiBoundary, Ledger):
    def __init__(self, events, *, operation_id=OP, **kwargs):
        ApiBoundary.__init__(self)
        Ledger.__init__(self, events, **kwargs)
        self.operation_id = operation_id

    def acquire_proof_request_claim(self, **kwargs):
        return dict(
            super().acquire_proof_request_claim(**kwargs), billing_operation_id=self.operation_id
        )


class CountedProvider(ProviderTransport):
    def __init__(self, responses, events, *, missing_usage_on=None):
        super().__init__(responses)
        self.events = events
        self.counts = []
        self.missing_usage_on = missing_usage_on

    def request(self, **kwargs):
        if kwargs["url"].endswith("/input_tokens"):
            self.events.append("count")
            self.counts.append(json.loads(kwargs["body"]))
            return HttpResponse(200, b'{"object":"response.input_tokens","input_tokens":100}')
        self.events.append("generate")
        result = super().request(**kwargs)
        if len(self.calls) == self.missing_usage_on:
            body = json.loads(result.body)
            body.pop("usage", None)
            return HttpResponse(result.status_code, json.dumps(body).encode())
        return result


def run(responses, *, enabled=True, missing_usage_on=None, operation_id=OP, **api_options):
    events = []
    api = TokenApi(events, operation_id=operation_id, **api_options)
    provider = CountedProvider(responses, events, missing_usage_on=missing_usage_on)
    engine = ProofReuseRuntime(
        OpenAIResponsesClient(api_key="test", transport=provider), CatalogBoundary()
    )
    processed = ProofRequestProcessor(api, engine, token_accounting_enabled=enabled).process(
        REQUEST_ID, CLAIM_ID, lambda _: None
    )
    return processed, api, provider, events


def test_success_requires_fresh_independent_qa_bound_to_exact_visible_answer_and_receipt():
    processed, api, provider, events = run(
        [READY, decision(), {"approved": True, "rationale": "Full induction justifies n=2."}]
    )
    assert processed
    assert events == ["count", "permit", "generate", "receipt"] * 3
    payload = api.settlements[0]
    assert payload["outcome"] == "answered"
    assert len(payload["usage"]) == 3  # old provider-cost telemetry is retained
    qa = payload["private_evidence"]["token_qa"]
    assert qa == {
        "approved": True,
        "answer_sha256": hashlib.sha256(payload["answer"]["text"].encode()).hexdigest(),
        "call_id": api.receipts[-1]["call_id"],
    }
    assert api.permits[-1]["model_role"] == "token_answer_qa"
    assert [call["max_output_tokens"] for call in provider.calls] == [6000, 6000, 12000]
    assert [permit["output_token_bound"] for permit in api.permits] == [6000, 6000, 12000]
    assert api.permits[-1]["payload_sha256"] == hashlib.sha256(
        json.dumps(provider.calls[-1]).encode("utf-8")
    ).hexdigest()
    rationale_schema = provider.calls[-1]["text"]["format"]["schema"]["properties"]["rationale"]
    assert rationale_schema["pattern"] == r"^[^\u0000]{1,2000}$"
    assert api.permits[-1]["call_id"] != api.permits[-2]["call_id"]
    assert "previous_response_id" not in provider.calls[-1]
    qa_data = json.loads(provider.calls[-1]["input"].split("\nDATA:\n")[1])
    assert qa_data["answer"] == payload["answer"]["text"]
    assert qa_data["request"]["original_statement"] == READY["statement"]
    assert qa_data["cited_sources"][0]["draft_id"] == "power"
    assert "supporting_proof" not in qa_data  # cannot justify gaps outside the visible answer
    assert "Reject undelimited math or raw Unicode" in provider.calls[-1]["input"]
    assert "$x\\in\\sqrt{IJ}$" in provider.calls[-1]["input"]


def test_real_qa_rejection_is_failed_without_second_vote_or_answer_publication():
    processed, api, provider, _ = run(
        [READY, decision(), {"approved": False, "rationale": "The visible argument is circular."}]
    )
    assert processed and len(provider.calls) == 3
    result = api.settlements[0]
    assert result["outcome"] == "failed" and result["answer"] is None
    assert result["error_code"] == "proof_reuse_answer_review_failed"
    assert result["private_evidence"]["token_qa"]["approved"] is False


@pytest.mark.parametrize("qa", [429, "invalid JSON", {"approved": "yes", "rationale": "x"}])
def test_qa_unavailable_or_malformed_never_becomes_answered(qa):
    processed, api, provider, _ = run([READY, decision(), qa])
    assert processed and len(provider.calls) == 3
    assert api.settlements[0]["outcome"] == "failed"
    assert api.settlements[0]["answer"] is None
    assert "token_qa" not in api.settlements[0]["private_evidence"]


@pytest.mark.parametrize("call", [1, 2, 3])
def test_missing_usage_at_any_stage_stops_and_fails_without_more_paid_calls(call):
    processed, api, provider, _ = run(
        [READY, decision(), {"approved": True, "rationale": "Valid"}], missing_usage_on=call
    )
    assert processed and len(provider.calls) == call
    assert api.receipts[-1]["status"] == "unknown"
    assert api.settlements[0]["outcome"] == "failed"
    assert api.settlements[0]["error_code"] == "proof_reuse_token_accounting_failed"


@pytest.mark.parametrize("api_option", ["permit_error", "receipt_error"])
def test_uncertain_accounting_never_allows_success(api_option):
    processed, api, provider, _ = run([READY], **{api_option: True})
    assert processed and len(provider.calls) == (api_option == "receipt_error")
    assert api.settlements[0]["outcome"] == "failed"


@pytest.mark.parametrize("operation_id,enabled", [(OP, False), (None, True), ("bad", True)])
def test_disabled_or_bad_binding_never_sends_any_provider_request(operation_id, enabled):
    processed, api, provider, events = run([], enabled=enabled, operation_id=operation_id)
    assert processed and not provider.calls and not provider.counts and not events
    assert api.settlements[0]["outcome"] == "failed"


def test_mathematical_escalation_also_metered_then_independent_qa():
    processed, api, provider, _ = run(
        [
            READY,
            decision(action="uncertain", answer="", conclusion=""),
            decision(),
            {"approved": True, "rationale": "Checked independently."},
        ]
    )
    assert processed and api.settlements[0]["outcome"] == "answered"
    assert [p["model"] for p in api.permits] == [
        "gpt-6-luna",
        "gpt-6-luna",
        "gpt-5.6-terra",
        "gpt-6-luna",
    ]
    assert len(api.receipts) == len(provider.calls) == 4


@pytest.mark.parametrize(
    "environment,flag,enabled",
    [
        ("local", "true", True),
        ("local", "false", False),
        ("local", "TRUE", False),
        ("production", "true", False),
        ("dev", "true", False),
        ("", "", False),
    ],
)
def test_factory_token_capability_is_explicit_and_local_only(
    monkeypatch, environment, flag, enabled
):
    from pals_agent.factory import build_proof_request_processor
    from pals_agent.settings import AgentSettings

    monkeypatch.setenv("PALS_ENV", environment)
    monkeypatch.setenv("PALS_TOKEN_ACCOUNTING_ENABLED", flag)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    processor = build_proof_request_processor(AgentSettings.from_env(), TokenApi([]))
    assert processor.token_accounting_enabled is enabled


@pytest.mark.parametrize("status,code,expected", [
    (402, "token_budget_exceeded", "token_budget_exceeded"),
    (503, "token_budget_exceeded", "proof_reuse_token_accounting_failed"),
    (None, "token_budget_exceeded", "proof_reuse_token_accounting_failed"),
    (402, "quota_exhausted_tokens", "proof_reuse_token_accounting_failed"),
    (402, None, "proof_reuse_token_accounting_failed"),
])
def test_only_explicit_permit_budget_denial_reaches_settlement(status, code, expected):
    processed, api, provider, events = run(
        [], permit_error=PalsApiError("private body must not be echoed",
                                      status_code=status, error_code=code)
    )
    assert processed
    assert events == ["count", "permit"] and not provider.calls and not api.receipts
    settled = api.settlements[0]
    assert settled["outcome"] == "failed" and settled["answer"] is None
    assert settled["error_code"] == expected
    assert "private body" not in json.dumps(settled)


def test_same_error_from_receipt_is_accounting_uncertainty_not_budget_denial():
    processed, api, provider, _ = run(
        [READY], receipt_error=PalsApiError("private", status_code=402,
                                           error_code="token_budget_exceeded")
    )
    assert processed and len(provider.calls) == 1
    assert api.settlements[0]["error_code"] == "proof_reuse_token_accounting_failed"
    assert [r["status"] for r in api.receipts] == ["success"]


def test_incomplete_qa_with_valid_looking_verdict_cannot_publish_or_retry():
    class IncompleteQaProvider(CountedProvider):
        def request(self, **kwargs):
            result = super().request(**kwargs)
            if not kwargs["url"].endswith("/input_tokens") and len(self.calls) == 3:
                body = json.loads(result.body)
                body["status"] = "incomplete"
                body["incomplete_details"] = {"reason": "max_output_tokens"}
                body["usage"]["output_tokens"] = 12000
                return HttpResponse(200, json.dumps(body).encode())
            return result

    events = []
    api = TokenApi(events)
    provider = IncompleteQaProvider(
        [READY, decision(), {"approved": True, "rationale": "Looks valid but incomplete."}],
        events,
    )
    client = OpenAIResponsesClient(api_key="test", transport=provider)
    engine = ProofReuseRuntime(client, CatalogBoundary())
    assert ProofRequestProcessor(api, engine, token_accounting_enabled=True).process(
        REQUEST_ID, CLAIM_ID, lambda _: None
    )
    assert client.max_output_tokens == 6000
    assert len(provider.calls) == 3
    settled = api.settlements[0]
    assert settled["outcome"] == "failed" and settled["answer"] is None
    assert settled["error_code"] == "proof_reuse_provider_unavailable"
    failure = settled["private_evidence"]["provider_failure"]
    assert failure["incomplete_reason"] == "max_output_tokens"
    assert "token_qa" not in settled["private_evidence"]
    assert api.receipts[-1]["output_tokens"] == 12000


def test_qa_larger_output_bound_must_be_permitted_before_any_qa_generation():
    class QaBudgetDeniedApi(TokenApi):
        def permit_token_call(self, payload, *, timeout_seconds):
            super().permit_token_call(payload, timeout_seconds=timeout_seconds)
            if payload["model_role"] == "token_answer_qa":
                raise PalsApiError(
                    "test budget denied", status_code=402, error_code="token_budget_exceeded"
                )

    events = []
    api = QaBudgetDeniedApi(events)
    provider = CountedProvider([READY, decision()], events)
    engine = ProofReuseRuntime(
        OpenAIResponsesClient(api_key="test", transport=provider), CatalogBoundary()
    )
    assert ProofRequestProcessor(api, engine, token_accounting_enabled=True).process(
        REQUEST_ID, CLAIM_ID, lambda _: None
    )
    assert len(provider.calls) == 2 and len(api.permits) == 3
    assert api.permits[-1]["output_token_bound"] == 12000
    assert len(api.receipts) == 2
    assert api.settlements[0]["outcome"] == "failed"
    assert api.settlements[0]["error_code"] == "token_budget_exceeded"


@pytest.mark.parametrize("bad", ["\x00", "\ud800", "\udfff"])
@pytest.mark.parametrize("stage", ["preflight", "decision", "qa"])
def test_invalid_provider_unicode_is_failed_before_qa_binding_and_persists_safe_evidence(
    bad, stage,
):
    ready = dict(READY)
    assessed = decision()
    reviewed = {"approved": True, "rationale": "Valid full proof."}
    if stage == "preflight":
        ready["reason"] = "invalid" + bad
    elif stage == "decision":
        assessed["premises"] = [{"statement": "premise", "justification": "invalid" + bad}]
    else:
        reviewed["rationale"] = "invalid" + bad
    # Escape surrogate code points so the provider HTTP envelope remains valid.
    responses = [json.dumps(value, ensure_ascii=True) for value in (ready, assessed, reviewed)]
    processed, api, provider, _ = run(responses)
    assert processed
    assert len(provider.calls) == {"preflight": 1, "decision": 2, "qa": 3}[stage]
    settled = api.settlements[0]
    assert settled["outcome"] == "failed" and settled["answer"] is None
    assert settled["error_code"] == "proof_reuse_invalid_response"
    evidence = settled["private_evidence"]
    assert "token_qa" not in evidence
    assert "token_qa_rationale" not in evidence
    if stage == "preflight":
        assert "preflight" not in evidence
    if stage == "decision":
        assert "primary_assessment" not in evidence
    # Real PostgreSQL persistence is separately exercised by the API regression.
    encoded = json.dumps(settled, ensure_ascii=False)
    assert "\\u0000" not in encoded
    encoded.encode("utf-8", errors="strict")
    assert all(receipt["status"] == "success" for receipt in api.receipts)


def test_valid_unicode_and_whitespace_keep_exact_visible_answer_and_qa_hash():
    answer = "日本語\t$ x^2 $\n\n絵文字 😀 と補助平面 𝛼 を含む説明。"
    processed, api, provider, _ = run([
        READY, decision(answer=answer), {"approved": True, "rationale": "Complete."},
    ])
    assert processed and len(provider.calls) == 3
    settled = api.settlements[0]
    assert settled["outcome"] == "answered"
    assert settled["answer"]["text"] == answer
    assert settled["private_evidence"]["token_qa"]["answer_sha256"] == hashlib.sha256(
        answer.encode("utf-8")
    ).hexdigest()


def test_provider_schemas_exclude_nul_before_generation_without_changing_valid_tex():
    import re

    processed, _, provider, _ = run([
        READY, decision(), {"approved": True, "rationale": "Valid."},
    ])
    assert processed
    for call, field in zip(provider.calls, ("reason", "answer", "rationale"), strict=True):
        schema = call["text"]["format"]["schema"]["properties"][field]
        pattern = schema["pattern"]
        assert re.fullmatch(pattern, "日本語\n$ x^2 $\t😀")
        assert re.fullmatch(pattern, "invalid\x00text") is None
