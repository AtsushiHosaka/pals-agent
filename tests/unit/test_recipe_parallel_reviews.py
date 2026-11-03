"""Real judge/meter code with bounded isolated HTTP concurrency, no paid calls."""

import copy
import json
import time
from threading import Barrier, Event

import pytest

from pals_agent.chat_images import chat_image_scope, current_chat_images
from pals_agent.http_transport import HttpResponse
from pals_agent.linked_chat import (
    linked_chat_scope,
    selected_generation_model,
    selected_generation_reasoning_effort,
)
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_reuse import ProofReuseRuntime
from pals_agent.proof_reuse_usage import current_role
from pals_agent.token_meter import TokenMeter, TokenMeterError, token_meter_scope
from pals_agent.usage import usage_scope
from tests.unit.test_chat_runtime import IMAGE
from tests.unit.test_proof_reuse import READY, CatalogBoundary, ProviderTransport
from tests.unit.test_proof_reuse_lean_flow import (
    BOUND_REQUEST,
    CLAIM_ID,
    INTENT,
    MATCH,
    READY_INTENT,
    RECIPE,
    REQUEST_ID,
    REVIEW,
    lookup,
)
from tests.unit.test_token_meter import OP, Ledger


def kind(body):
    props = body.get("text", {}).get("format", {}).get("schema", {}).get("properties", {})
    if {"recipe_id", "approved"} <= props.keys():
        return "review"
    if {"recipe_id", "objects", "quantifiers", "method"} <= props.keys():
        return "scope"
    return None


class ParallelProvider(ProviderTransport):
    def __init__(self, responses, *, hold_scope=False, fail_scope=False, hold_review=False):
        super().__init__(responses)
        self.barrier = Barrier(2, timeout=4)
        self.hold_scope, self.fail_scope, self.hold_review = hold_scope, fail_scope, hold_review
        self.qa_completed, self.scope_failed = Event(), Event()
        self.review_returned = Event()
        self.contexts = {}

    def request(self, **kwargs):
        if kwargs["url"].endswith("/input_tokens"):
            return HttpResponse(
                200, b'{"object":"response.input_tokens","input_tokens":1000}'
            )
        body = json.loads(kwargs["body"])
        pair = kind(body)
        if pair is not None:
            self.contexts[pair] = (
                current_role(), selected_generation_model("unset"),
                selected_generation_reasoning_effort(None), current_chat_images(),
            )
            # A sequential implementation cannot cross this barrier.
            self.barrier.wait()
            if pair == "scope" and self.hold_scope:
                assert self.qa_completed.wait(4), "QA must finish before scope returns"
            if pair == "review" and self.hold_review:
                assert self.scope_failed.wait(4), "scope must fail before review returns"
        response = super().request(**kwargs)
        if pair == "scope" and self.fail_scope:
            return HttpResponse(500, b'{"error":{"code":"server_error"}}')
        if pair == "review":
            self.review_returned.set()
        return response


def engine(provider):
    return ProofReuseRuntime(
        OpenAIResponsesClient(api_key="test", transport=provider), CatalogBoundary()
    )


def answer(provider, recipes=None):
    search, _ = lookup(recipes or [RECIPE])
    return engine(provider).answer(BOUND_REQUEST, recipe_search=search, claim_id=CLAIM_ID)


def test_network_calls_overlap_and_keep_independent_inputs_and_context():
    provider = ParallelProvider([READY, INTENT, MATCH, REVIEW])
    costs = []
    image = IMAGE["image_data_url"]
    settings = {"generation_model": "gpt-6.1-sol", "generation_reasoning_effort": "high"}
    def reporter(usage):
        costs.append((current_role(), usage))

    with linked_chat_scope(settings), chat_image_scope((image,)), usage_scope(reporter):
        result = answer(provider)
    assert result.outcome == "answered"
    assert provider.contexts == {
        pair: (role, "gpt-6.1-sol", "high", (image,))
        for pair, role in (("scope", "proof_reuse_judge"), ("review", "proof_review"))
    }
    assert sorted(role for role, _ in costs) == [
        "proof_reuse_judge", "proof_reuse_judge", "proof_reuse_judge", "proof_review",
    ]
    prompts = {}
    for body in provider.calls:
        pair = kind(body)
        if pair:
            assert body["store"] is False
            assert body["model"] == "gpt-6-luna"
            text = body["input"][0]["content"][0]["text"]
            prompts[pair] = json.loads(text.split("DATA:\n", 1)[1])
    assert prompts["scope"]["candidates"] == prompts["review"]["candidates"]
    assert prompts["scope"]["request"] == prompts["review"]["request"]
    assert "assessment_session_id" not in prompts["review"]
    assert "intent" not in prompts["review"]
    assert result.private_evidence["recipe_review_execution"] == "parallel_independent_selection"


def test_reverse_completion_binds_qa_to_qa_role_not_last_call(monkeypatch):
    provider = ParallelProvider([READY_INTENT, MATCH, REVIEW], hold_scope=True)
    original = TokenMeter.request

    def completed(self, **kwargs):
        response = original(self, **kwargs)
        if current_role() == "token_answer_qa":
            provider.qa_completed.set()
        return response

    monkeypatch.setattr(TokenMeter, "request", completed)
    ledger = Ledger([])
    meter = TokenMeter(ledger, OP, REQUEST_ID, CLAIM_ID, time.monotonic() + 30)
    usage = []
    with token_meter_scope(meter), usage_scope(usage.append):
        result = answer(provider)
    assert result.outcome == "answered" and not meter.failed
    qa_id = result.private_evidence["token_qa"]["call_id"]
    completed_roles = meter.snapshot_completed_calls()
    assert completed_roles[qa_id] == "token_answer_qa"
    assert qa_id != meter.last_call_id
    assert completed_roles[meter.last_call_id] == "proof_reuse_judge"
    assert len(ledger.permits) == len(ledger.receipts) == len(usage) == 3
    assert {p["call_id"] for p in ledger.permits} == {r["call_id"] for r in ledger.receipts}
    assert all(r["status"] == "success" for r in ledger.receipts)


def test_provider_failure_joins_other_call_and_attempts_every_permit_receipt(monkeypatch):
    provider = ParallelProvider(
        [READY_INTENT, MATCH, REVIEW], fail_scope=True, hold_review=True,
    )
    original = TokenMeter.request

    def failure(self, **kwargs):
        try:
            return original(self, **kwargs)
        except TokenMeterError:
            if current_role() == "proof_reuse_judge":
                provider.scope_failed.set()
            raise

    monkeypatch.setattr(TokenMeter, "request", failure)
    ledger = Ledger([])
    meter = TokenMeter(ledger, OP, REQUEST_ID, CLAIM_ID, time.monotonic() + 30)
    costs = []
    with token_meter_scope(meter), usage_scope(costs.append), pytest.raises(TokenMeterError):
        answer(provider)
    assert provider.review_returned.is_set(), "the surviving request must join before propagation"
    assert meter.failed
    assert len(ledger.permits) == len(ledger.receipts) == 3
    assert {p["call_id"] for p in ledger.permits} == {r["call_id"] for r in ledger.receipts}
    assert sorted(r["status"] for r in ledger.receipts) == ["success", "unknown", "unknown"]
    # The review actually incurred usage even though another permit poisoned settlement.
    assert len(costs) == 2
    assert len(meter.snapshot_completed_calls()) == 1


def test_independent_valid_but_different_selection_is_dsp_not_approval():
    other = dict(RECIPE, recipe_id="different_candidate", entry_sha256="d" * 64)
    provider = ParallelProvider([
        READY_INTENT, MATCH, dict(REVIEW, recipe_id="different_candidate"),
    ])
    result = answer(provider, [RECIPE, other])
    assert result.outcome == "formal" and result.answer is None
    assert result.private_evidence["lean_route"] == "dsp_correspondence_rejected"
    assert result.private_evidence["answer_qa"]["approved"] is False
    assert "recipe_correspondence" not in result.private_evidence


@pytest.mark.parametrize("changes", [
    {"recipe_id": "unknown"}, {"recipe_revision": 2},
    {"recipe_id": None, "recipe_revision": None},
    {"recipe_revision": True}, {"rationale": ""}, {"approved": "true"},
])
def test_unknown_or_malformed_independent_selection_fails_closed(changes):
    provider = ParallelProvider([READY_INTENT, MATCH, dict(REVIEW, **changes)])
    result = answer(provider)
    assert result.outcome == "failed" and result.answer is None
    assert result.error_code == "proof_reuse_invalid_response"
    assert provider.review_returned.is_set()


def test_candidate_batch_keeps_existing_bounded_admission():
    recipes = [dict(copy.deepcopy(RECIPE), recipe_id=f"candidate_{i}") for i in range(9)]
    provider = ParallelProvider([READY_INTENT])
    result = answer(provider, recipes)
    assert result.outcome == "failed" and result.error_code == "proof_reuse_recipe_invalid"
    assert not provider.contexts


@pytest.mark.parametrize("bad_citation", [False, True])
def test_parallel_review_keeps_bound_material_snapshot_and_validates_citations(bad_citation):
    from tests.unit.test_material_context import MATERIAL_ID, PAGE_TEXT, PROJECT_ID, snapshot

    citations = [{"material_id": MATERIAL_ID, "page": 3,
                  "excerpt": "fabricated citation" if bad_citation else PAGE_TEXT}]
    ready = dict(READY, confirmed_material_statement=True, material_proposition=None)
    provider = ParallelProvider([ready, INTENT, MATCH, dict(REVIEW, material_citations=citations)])
    request = dict(BOUND_REQUEST, project_id=PROJECT_ID, material_context=snapshot())
    search, _ = lookup([RECIPE])
    result = engine(provider).answer(request, recipe_search=search, claim_id=CLAIM_ID)
    if bad_citation:
        assert result.outcome == "failed" and result.answer is None
        assert "recipe_correspondence" not in result.private_evidence
    else:
        assert result.outcome == "answered"
        assert result.answer["material_sources"][0]["excerpt"] == PAGE_TEXT
    for body in provider.calls:
        if kind(body):
            assert snapshot()["snapshot_sha256"] in body["input"]
            assert PAGE_TEXT in body["input"]
