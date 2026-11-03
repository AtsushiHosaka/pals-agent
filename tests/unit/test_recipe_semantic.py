"""Actual orchestration/client parsing against an isolated HTTP boundary, no paid calls."""

import copy
import hashlib
import json
import time
from threading import Barrier, Event

import pytest

from pals_agent.chat_runtime import ChatRuntime
from pals_agent.http_transport import HttpResponse
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_request_worker import ProofRequestProcessor
from pals_agent.proof_reuse import ProofReuseRuntime
from pals_agent.recipe_semantic import SemanticReuseError, attempt
from pals_agent.recipe_semantic_contract import (
    CONTENT_SCHEMA,
    SCHEMA_VERSION,
    STATED_READING_POLICY,
    digest,
    fresh_plain_request,
    prompts,
    read_batch,
)
from pals_agent.token_meter import TokenMeter, token_meter_scope
from pals_agent.usage import usage_scope
from tests.unit.test_proof_request_worker import ApiBoundary
from tests.unit.test_proof_reuse import CatalogBoundary
from tests.unit.test_recipe_exact_input import recipe, request
from tests.unit.test_token_meter import OP, Ledger


def inputs(statement="任意の非負整数 n に対して、実数上の x^n の連続性を証明してください。"):
    r = request(statement)
    r["generation_model"] = "gpt-6.1-sol"
    r["generation_reasoning_effort"] = "high"
    row = recipe()
    batch = {
        "schema_version": "pals.recipe-catalog-batch.v1",
        "request_id": r["id"],
        "claim_id": "00000000-0000-4000-8000-000000000002",
        "request_revision": 1,
        "request_context_sha256": digest(
            {
                k: r[k]
                for k in (
                    "statement",
                    "context_turns",
                    "output_language",
                )
            }
        ),
        "output_language": "ja",
        "toolchain_sha256": row["toolchain_sha256"],
        "complete": True,
        "truncated": False,
        "reason": None,
        "total_count": 1,
        "recipes": [row],
    }
    batch["batch_sha256"] = digest(
        {
            "schema_version": CONTENT_SCHEMA,
            **{k: batch[k] for k in ("output_language", "toolchain_sha256", "recipes")},
        }
    )
    verdict = {
        "schema_version": SCHEMA_VERSION,
        "action": "reuse",
        "tasks": [{"kind": "prove", "answer_relation": "proves_assertion"}],
        "recipe_id": row["recipe_id"],
        "recipe_revision": row["recipe_revision"],
        "request_scope": {
            "objects_and_types": ["n : Nat", "x : Real"],
            "domain": "Real",
            "assumptions": [],
            "quantifiers_and_dependencies": ["all n : Nat including zero"],
            "conclusion": row["target_source"],
            "required_method": None,
        },
        "source_target_sha256": hashlib.sha256(row["target_source"].encode()).hexdigest(),
        "checks": {
            k: True
            for k in (
                "objects",
                "domain",
                "assumptions",
                "quantifiers",
                "conclusion",
                "method",
            )
        },
        "answer_qa": True,
        "relevant_conventions": ["natural_zero", "zero_pow_zero"],
        "unresolved": [],
        "rationale": "Synthetic HTTP fixture, not live mathematical evidence.",
    }
    return r, batch, verdict


class Provider:
    def __init__(self, verdict, *, malformed=False, missing_id=False):
        self.verdict = verdict
        self.malformed = malformed
        self.missing_id = missing_id
        self.calls = []
        self.barrier = Barrier(2, timeout=4)
        self.returned = Event()

    def request(self, **kwargs):
        body = json.loads(kwargs["body"])
        if kwargs["url"].endswith("/input_tokens"):
            return HttpResponse(200, b'{"object":"response.input_tokens","input_tokens":1000}')
        self.calls.append(body)
        self.barrier.wait()
        review = "ROLE: Act as an adversarial" in body["input"]
        value = copy.deepcopy(self.verdict)
        if self.malformed and not review:
            value["checks"]["method"] = False
        result = {
            "object": "response",
            "status": "completed",
            "model": body["model"],
            "id": "resp_review_b" if review else "resp_assessment_a",
            "error": None,
            "incomplete_details": None,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 60,
                "input_tokens_details": {"cached_tokens": 7},
                "output_tokens_details": {"reasoning_tokens": 10},
            },
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": json.dumps(value)}],
                }
            ],
        }
        if self.missing_id:
            result.pop("id")
        self.returned.set()
        return HttpResponse(200, json.dumps(result).encode())


def test_real_two_call_path_matches_stored_source_and_complete_usage_without_intent(monkeypatch):
    r, batch, verdict = inputs()
    provider = Provider(verdict)
    client = OpenAIResponsesClient(api_key="isolated-test", transport=provider)
    proof = ProofReuseRuntime(client, CatalogBoundary())
    from pals_agent.lean import LeanVerifier

    monkeypatch.setattr(LeanVerifier, "verify", lambda *a, **k: pytest.fail("no new compilation"))
    records = []
    with usage_scope(records.append):
        result = ChatRuntime(client, proof).answer(
            r,
            recipe_batch=lambda: batch,
            claim_id=batch["claim_id"],
        )
    assert result.outcome == "answered"
    assert result.answer["text"] == batch["recipes"][0]["answer"]
    assert len(provider.calls) == len(records) == 2
    assert all(
        call["model"] == "gpt-6-luna"
        and call["reasoning"] == {"effort": "low"}
        and call["service_tier"] == "default"
        and call["store"] is False
        and call["max_output_tokens"] == 1536
        for call in provider.calls
    )
    receipt = result.private_evidence["recipe_semantic_correspondence"]
    assert (
        "answer_qa" not in result.private_evidence and "chat_route" not in result.private_evidence
    )
    assert "api_recipe_catalog_batch" not in result.private_evidence
    assert {receipt[p]["provider_request_id"] for p in ("assessment", "review")} == {
        record["provider_request_id"] for record in records
    }
    assert receipt["assessment"]["call_id"] != receipt["review"]["call_id"]
    assert result.private_evidence["token_qa"]["call_id"] == receipt["review"]["call_id"]


def test_paid_meter_calls_have_real_roles_ids_usage_and_success_receipts():
    r, batch, verdict = inputs()
    provider = Provider(verdict)
    ledger = Ledger([])
    meter = TokenMeter(ledger, OP, r["id"], batch["claim_id"], time.monotonic() + 30)
    records = []
    with usage_scope(records.append), token_meter_scope(meter):
        result = attempt(
            OpenAIResponsesClient(api_key="test", transport=provider),
            r,
            batch["claim_id"],
            lambda: batch,
            deadline=time.monotonic() + 30,
        )
    assert result.answer is not None and not meter.failed
    assert len(ledger.permits) == len(ledger.receipts) == len(records) == 2
    assert {v["model_role"] for v in ledger.permits} == {
        "recipe_semantic_assessment",
        "token_answer_qa",
    }
    assert {v["call_id"] for v in ledger.permits} == {v["call_id"] for v in records}
    assert all(v["reasoning_output_tokens"] == 10 for v in ledger.receipts)
    assert all(v["output_tokens"] == 60 for v in ledger.receipts)


def test_parser_failure_joins_peer_and_retains_every_spent_call():
    r, batch, verdict = inputs()
    provider = Provider(verdict, malformed=True)
    records = []
    with usage_scope(records.append), pytest.raises(SemanticReuseError):
        attempt(
            OpenAIResponsesClient(api_key="test", transport=provider),
            r,
            batch["claim_id"],
            lambda: batch,
            deadline=time.monotonic() + 30,
        )
    assert provider.returned.is_set() and len(records) == len(provider.calls) == 2
    assert all(record["provider_request_id"].startswith("resp_") for record in records)


def test_missing_actual_provider_id_cannot_fabricate_correspondence_but_usage_survives():
    from pals_agent.openai import OpenAIError

    r, batch, verdict = inputs()
    provider = Provider(verdict, missing_id=True)
    records = []
    with usage_scope(records.append), pytest.raises(OpenAIError):
        attempt(
            OpenAIResponsesClient(api_key="test", transport=provider),
            r,
            batch["claim_id"],
            lambda: batch,
            deadline=time.monotonic() + 30,
        )
    assert len(records) == 2 and all("provider_request_id" not in value for value in records)


@pytest.mark.parametrize(
    "change",
    [
        {"revision": 2},
        {"retry_count": 1},
        {"project_id": "project"},
        {"material_context": {}},
        {"chat_history": [{}]},
        {"attachment_ids": ["id"]},
        {"output_language": "en"},
        {"context_turns": [{}]},
    ],
)
def test_contextful_or_changed_requests_retain_ordinary_route_without_batch_read(change):
    r, _, _ = inputs()
    assert not fresh_plain_request(dict(r, **change))


def test_incomplete_batch_is_explicit_fallback_and_unowned_batch_is_failure():
    r, batch, _ = inputs()
    incomplete = dict(
        batch,
        complete=False,
        truncated=True,
        reason="count_limit",
        total_count=None,
        recipes=[],
        batch_sha256=None,
    )
    assert read_batch(r, batch["claim_id"], incomplete) is None
    with pytest.raises(ValueError, match="batch_claim_mismatch"):
        read_batch(r, "11111111-1111-4111-8111-111111111111", batch)


def test_processor_preserves_actual_provider_ids_and_current_claim_in_settlement():
    r, batch, verdict = inputs()

    class Api(ApiBoundary):
        def acquire_proof_request_claim(self, **kwargs):
            from datetime import UTC, datetime, timedelta

            return {
                "status": "acquired",
                "request": dict(r, status="assessing"),
                "claim_id": batch["claim_id"],
                "lean_flow": True,
                "math_conventions": r["math_conventions"],
                "lease_expires_at": (datetime.now(UTC) + timedelta(seconds=240)).isoformat(),
            }

        def get_proof_request_recipe_batch(self, **kwargs):
            assert kwargs["request_id"] == r["id"] and kwargs["claim_id"] == batch["claim_id"]
            return batch

        def search_proof_request_recipes(self, **kwargs):
            return []

    api = Api()
    provider = Provider(verdict)
    client = OpenAIResponsesClient(api_key="test", transport=provider)
    engine = ChatRuntime(client, ProofReuseRuntime(client, CatalogBoundary()))
    assert ProofRequestProcessor(api, engine).process(r["id"], batch["claim_id"], lambda _: None)
    payload = api.settlements[0]
    assert payload["outcome"] == "answered" and len(payload["usage"]) == 2
    assert {v["model_role"] for v in payload["usage"]} == {
        "recipe_semantic_assessment",
        "token_answer_qa",
    }
    assert all(v["provider_request_id"].startswith("resp_") for v in payload["usage"])
    assert "api_recipe_catalog_batch" not in payload["private_evidence"]


def test_inherited_linked_prompt_context_cannot_silently_change_measured_plain_input(monkeypatch):
    r, _, _ = inputs()
    monkeypatch.setattr("pals_agent.linked_chat.linked_chat_prompt", lambda _: "inherited source")
    assert not fresh_plain_request(r)


def test_legacy_proof_job_usage_writer_filters_only_new_optional_provider_metadata():
    from pals_agent.api_client import PalsApiClient

    class JobTransport:
        def request(self, **kwargs):
            self.payload = json.loads(kwargs["body"])
            return HttpResponse(200, b'{"recorded":true}')

    transport = JobTransport()
    api = PalsApiClient("https://api.invalid", "isolated", transport=transport)
    usage = {
        "call_id": "00000000-0000-4000-8000-000000000009",
        "model": "gpt-6-luna",
        "provider_request_id": "resp_actual_a",
        "unrecognized": "still-closed-at-api",
    }
    original = dict(usage)
    api.record_usage(
        proof_job_id="job", claim_id="00000000-0000-4000-8000-000000000002", usage=usage
    )
    assert usage == original
    assert transport.payload == {
        k: v
        for k, v in dict(
            usage,
            generation_claim_id="00000000-0000-4000-8000-000000000002",
        ).items()
        if k != "provider_request_id"
    }


@pytest.mark.parametrize("paid", [False, True])
def test_wrong_known_model_fails_closed_and_keeps_actual_provider_costs(paid):
    from pals_agent.openai import OpenAIError
    from pals_agent.token_meter import TokenMeterError

    r, batch, verdict = inputs()

    class WrongProvider(Provider):
        def request(self, **kwargs):
            response = super().request(**kwargs)
            if kwargs["url"].endswith("/input_tokens"):
                return response
            body = json.loads(response.body)
            body["model"] = "gpt-6.1-sol"
            return HttpResponse(200, json.dumps(body).encode())

    provider = WrongProvider(verdict)
    records = []
    client = OpenAIResponsesClient(api_key="test", transport=provider)
    if paid:
        ledger = Ledger([])
        meter = TokenMeter(ledger, OP, r["id"], batch["claim_id"], time.monotonic() + 30)
        with usage_scope(records.append), token_meter_scope(meter), pytest.raises(TokenMeterError):
            attempt(client, r, batch["claim_id"], lambda: batch, deadline=time.monotonic() + 30)
        assert meter.failed and len(ledger.permits) == len(ledger.receipts) == 2
        assert all(v["status"] == "unknown" for v in ledger.receipts)
    else:
        with usage_scope(records.append), pytest.raises(OpenAIError):
            attempt(client, r, batch["claim_id"], lambda: batch, deadline=time.monotonic() + 30)
    assert len(records) == 2 and all(v["model"] == "gpt-6.1-sol" for v in records)


def test_independent_nonacceptance_stays_diagnostic_and_retains_costs():
    r, batch, verdict = inputs()
    provider = Provider(verdict)
    original = provider.request

    def rejecting(**kwargs):
        response = original(**kwargs)
        body = json.loads(response.body)
        if body.get("id") == "resp_review_b":
            value = json.loads(body["output"][0]["content"][0]["text"])
            value.update(
                action="miss",
                recipe_id=None,
                recipe_revision=None,
                source_target_sha256=None,
                answer_qa=False,
            )
            body["output"][0]["content"][0]["text"] = json.dumps(value)
        return HttpResponse(200, json.dumps(body).encode())

    provider.request = rejecting
    records = []
    with usage_scope(records.append):
        result = attempt(
            OpenAIResponsesClient(api_key="test", transport=provider),
            r,
            batch["claim_id"],
            lambda: batch,
            deadline=time.monotonic() + 30,
        )
    assert result.answer is None and len(records) == 2
    assert set(result.evidence) == {"recipe_semantic_attempt"}
    assert result.evidence["recipe_semantic_attempt"]["review"]["result"]["action"] == "miss"


def test_shared_actual_provider_id_cannot_be_recast_as_two_independent_reviews():
    r, batch, verdict = inputs()
    provider = Provider(verdict)
    original = provider.request

    def duplicate(**kwargs):
        response = original(**kwargs)
        body = json.loads(response.body)
        body["id"] = "resp_same_call"
        return HttpResponse(200, json.dumps(body).encode())

    provider.request = duplicate
    records = []
    with usage_scope(records.append), pytest.raises(SemanticReuseError):
        attempt(
            OpenAIResponsesClient(api_key="test", transport=provider),
            r,
            batch["claim_id"],
            lambda: batch,
            deadline=time.monotonic() + 30,
        )
    assert len(records) == 2


@pytest.mark.parametrize("mutation", ["entry_hash", "source", "answer", "batch", "context"])
def test_complete_batch_tampering_fails_before_any_model_call(mutation):
    r, batch, verdict = inputs()
    if mutation == "entry_hash":
        batch["recipes"][0]["entry_sha256"] = "not-a-hash"
    elif mutation == "source":
        batch["recipes"][0]["lean_code"] += "-- changed"
    elif mutation == "answer":
        batch["recipes"][0]["answer"] += " changed"
    elif mutation == "batch":
        batch["batch_sha256"] = "0" * 64
    else:
        batch["request_context_sha256"] = "0" * 64
    provider = Provider(verdict)
    with pytest.raises(SemanticReuseError, match="proof_reuse_recipe_invalid"):
        attempt(
            OpenAIResponsesClient(api_key="test", transport=provider),
            r,
            batch["claim_id"],
            lambda: batch,
            deadline=time.monotonic() + 30,
        )
    assert not provider.calls


def test_recipe_batch_client_uses_current_claim_and_bounded_authenticated_endpoint():
    from pals_agent.api_client import PalsApiClient

    r, batch, _ = inputs()

    class BatchTransport:
        def request(self, **kwargs):
            self.requested = kwargs
            return HttpResponse(200, json.dumps(batch).encode())

    transport = BatchTransport()
    client = PalsApiClient("https://api.invalid", "isolated", transport=transport)
    assert (
        client.get_proof_request_recipe_batch(
            request_id=r["id"],
            claim_id=batch["claim_id"],
            output_language="ja",
        )
        == batch
    )
    sent = transport.requested
    assert sent["method"] == "POST" and sent["url"].endswith(f"/{r['id']}/recipe-batch")
    assert json.loads(sent["body"]) == {"claim_id": batch["claim_id"], "output_language": "ja"}
    assert sent["headers"]["X-PALS-Worker-Secret"] == "isolated"


def test_runtime_schema_and_compound_task_policy_have_explicit_golden_bytes():
    """Explicit compound-task delta from v12; static schema remains v6.

    New golden bytes identify the changed prompt, not a new provider measurement,
    catalog admission or production latency result.
    """
    import rfc8785

    from pals_agent import recipe_semantic_contract as contract

    assert hashlib.sha256(contract.BASE.encode()).hexdigest() == (
        "6ece96d39ce5526c14dbeb8ca6e20ed1e7a22bbe5d3c925fcc3348ffe3c3517a"
    )
    assert hashlib.sha256(rfc8785.dumps(contract.SCHEMA)).hexdigest() == (
        "800d484003ee988403d102d99d4dc071dfc572c3dfa9e756932accde775ab2df"
    )
    assert hashlib.sha256(rfc8785.dumps(contract.ROLE)).hexdigest() == (
        "fb12bab6629ca2942585e3ee56da413fe4d5f24d5091c88216af1df2122aeea7"
    )
    # N=1 uses the explicitly truthful full-shown policy extension.
    r, batch, _ = inputs()
    result = contract.prompts(
        r,
        batch,
        {"natural_zero": "include", "zero_pow_zero": "include"},
        assessment_session="00000000-0000-4000-8000-000000000001",
        review_session="00000000-0000-4000-8000-000000000002",
        retrieved_entry_sha256s=[batch["recipes"][0]["entry_sha256"]],
    )
    assert {role: hashlib.sha256(value.encode()).hexdigest() for role, value in result.items()} == {
        "assessment": "d956ec60496799999345f6155b5b724c51d8ad53d28090d16bddfa619439327b",
        "review": "554439c60e639b5a0b1be47f3c0d57ad925bd84b514c9cf5203fa2d6ded215dd",
    }


def run_attempt(r, batch, verdict):
    records = []
    with usage_scope(records.append):
        result = attempt(
            OpenAIResponsesClient(api_key="test", transport=Provider(verdict)),
            r,
            batch["claim_id"],
            lambda: batch,
            deadline=time.monotonic() + 30,
        )
    assert len(records) == 2
    return result


@pytest.mark.parametrize(
    "choices",
    [{}, {"natural_zero": "include"}],
    ids=["no_reading", "one_of_two_readings"],
)
def test_reuse_citing_a_reading_the_request_lacks_is_nonacceptance_not_failure(choices):
    # A signed-in learner's unset setting omits the reading, whereas a guest has every default.
    r, batch, verdict = inputs()
    r["math_conventions"] = {"policy": "ask", "choices": choices}
    result = run_attempt(r, batch, verdict)
    assert result.answer is None
    assert set(result.evidence) == {"recipe_semantic_attempt"}


def test_reuse_with_every_reading_known_still_publishes_under_ask_policy():
    r, batch, verdict = inputs()
    choices = {"natural_zero": "include", "zero_pow_zero": "include"}
    r["math_conventions"] = {"policy": "ask", "choices": choices}
    result = run_attempt(r, batch, verdict)
    assert result.answer is not None
    assert result.evidence["applied_conventions"] == [
        {"id": "natural_zero", "choice": "include"},
        {"id": "zero_pow_zero", "choice": "include"},
    ]


def test_runtime_continues_past_a_reuse_citing_an_unknown_reading():
    r, batch, verdict = inputs()
    r["math_conventions"] = {"policy": "ask", "choices": {}}
    client = OpenAIResponsesClient(api_key="test", transport=Provider(verdict))
    semantic = ProofReuseRuntime(client, CatalogBoundary()).semantic_recipe_input(
        r,
        recipe_batch=lambda: batch,
        claim_id=batch["claim_id"],
        deadline=time.monotonic() + 30,
    )
    assert semantic is not None and semantic.answer is None


@pytest.mark.parametrize("policy", ["ask", "default"])
@pytest.mark.parametrize(
    "change",
    [
        {"answer_qa": False},
        {"unresolved": ["unsettled premise"]},
        {"tasks": []},
        {"relevant_conventions": ["zero_pow_zero", "zero_pow_zero"]},
        {"relevant_conventions": ["zero_pow_zero=include"]},
        {"relevant_conventions": ["not_a_catalog_id"]},
        {"recipe_id": "requested.not_in_catalog"},
        {"source_target_sha256": "0" * 64},
        {"checks": {"objects": False}},
    ],
    ids=[
        "answer_qa_false",
        "unresolved",
        "no_tasks",
        "duplicate_convention",
        "id_joined_with_reading",
        "id_outside_catalog",
        "recipe_outside_catalog",
        "target_changed",
        "failed_check",
    ],
)
def test_genuinely_invalid_reuse_output_still_fails_closed(policy, change):
    r, batch, verdict = inputs()
    r["math_conventions"] = {"policy": policy, "choices": {}}
    if "checks" in change:
        verdict["checks"].update(change["checks"])
    else:
        verdict.update(change)
    with pytest.raises(SemanticReuseError) as error:
        run_attempt(r, batch, verdict)
    assert error.value.code == "proof_reuse_invalid_response"


STATED = "0^0=1 とする。任意の自然数 n に対して、実数上の関数 x^n の連続性を証明してください。"


@pytest.mark.parametrize(
    ("statement", "known", "reaches_reviewers"),
    [
        (STATED, {}, True),
        (STATED, {"natural_zero": "include"}, True),
        (STATED, {"zero_pow_zero": "include"}, False),
        (STATED, {"zero_pow_zero": "exclude"}, False),
        ("任意の自然数 n に対して、実数上の x^n の連続性を証明してください。", {}, False),
    ],
)
def test_stated_reading_policy_only_reaches_a_statement_naming_an_unknown_reading(
    statement, known, reaches_reviewers
):
    r, batch, _ = inputs(statement)
    result = prompts(
        r,
        batch,
        known,
        assessment_session="00000000-0000-4000-8000-000000000001",
        review_session="00000000-0000-4000-8000-000000000002",
        retrieved_entry_sha256s=[batch["recipes"][0]["entry_sha256"]],
    )
    for prompt in result.values():
        assert (STATED_READING_POLICY in prompt) is reaches_reviewers
        assert ("conventions_named_in_request" in prompt) is reaches_reviewers


def test_reviews_treating_a_stated_reading_as_a_premise_publish_without_a_recorded_setting():
    r, batch, verdict = inputs(STATED)
    r["math_conventions"] = {"policy": "ask", "choices": {}}
    verdict["relevant_conventions"] = []
    result = run_attempt(r, batch, verdict)
    assert result.answer is not None
    # The learner's text carries the reading; no setting, answer or default was applied.
    assert result.evidence["applied_conventions"] == []


def test_naming_a_reading_supplies_nothing_when_reviews_still_list_it():
    r, batch, verdict = inputs(STATED)
    r["math_conventions"] = {"policy": "ask", "choices": {}}
    verdict["relevant_conventions"] = ["zero_pow_zero"]
    result = run_attempt(r, batch, verdict)
    assert result.answer is None


NONREUSE = {
    "recipe_id": None,
    "recipe_revision": None,
    "source_target_sha256": None,
}


@pytest.mark.parametrize("action", ["miss", "needs_input", "nonproof"])
def test_a_review_declining_reuse_is_nonacceptance_whatever_its_answer_qa(action):
    r, batch, verdict = inputs()
    verdict.update(NONREUSE, action=action, answer_qa=True)
    result = run_attempt(r, batch, verdict)
    assert result.answer is None
    assert set(result.evidence) == {"recipe_semantic_attempt"}


def test_a_declining_peer_with_answer_qa_withholds_the_other_reviews_reuse():
    r, batch, verdict = inputs()
    provider = Provider(verdict)
    original = provider.request

    def declining(**kwargs):
        response = original(**kwargs)
        body = json.loads(response.body)
        if body.get("id") == "resp_review_b":
            value = json.loads(body["output"][0]["content"][0]["text"])
            value.update(NONREUSE, action="miss", answer_qa=True)
            body["output"][0]["content"][0]["text"] = json.dumps(value)
        return HttpResponse(200, json.dumps(body).encode())

    provider.request = declining
    result = attempt(
        OpenAIResponsesClient(api_key="test", transport=provider),
        r,
        batch["claim_id"],
        lambda: batch,
        deadline=time.monotonic() + 30,
    )
    assert result.answer is None


@pytest.mark.parametrize("answer_qa", [True, False])
@pytest.mark.parametrize("kept", ["recipe_id", "recipe_revision", "source_target_sha256"])
def test_a_review_declining_reuse_cannot_still_select_a_recipe(kept, answer_qa):
    r, batch, verdict = inputs()
    selection = {key: verdict[key] for key in NONREUSE}
    verdict.update(NONREUSE, action="miss", answer_qa=answer_qa)
    verdict[kept] = selection[kept]
    with pytest.raises(SemanticReuseError) as error:
        run_attempt(r, batch, verdict)
    assert error.value.code == "proof_reuse_invalid_response"
