"""PFR-016–020 protocol tests isolate provider HTTP, not real-model accuracy."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from pals_agent.api_client import PalsApiError
from pals_agent.input_fence import InputSnapshotObsolete, input_fence_scope
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_input import (
    InputInterpretationError,
    ProofInputInterpreter,
    validate_decision,
)
from pals_agent.proof_request_worker import ProofRequestProcessor
from tests.unit.test_proof_request_worker import CLAIM_ID, REQUEST_ID, ApiBoundary
from tests.unit.test_proof_reuse import REQUEST, ProviderTransport, runtime
from tests.unit.test_token_meter import OP, Ledger
from tests.unit.test_token_proof_request import CountedProvider

INPUT_ID = "33333333-3333-4333-8333-333333333333"


def amendment(statement="Prove n²+n is even for every integer n."):
    return {"kind": "amend", "effective_statement": statement,
            "independent_statement": None, "question": None}


class InputApi(ApiBoundary, Ledger):
    def __init__(self, *, current=True, paid=False, **kwargs):
        ApiBoundary.__init__(self)
        Ledger.__init__(self, [], **kwargs)
        self.current = current
        self.paid = paid
        self.checks = []

    def acquire_proof_request_claim(self, **kwargs):
        result = super().acquire_proof_request_claim(**kwargs)
        result["request"] = dict(REQUEST, id=REQUEST_ID, status="verifying", revision=4,
                                 input_generation=1, input_state="pending")
        result["lease_expires_at"] = (datetime.now(UTC) + timedelta(seconds=240)).isoformat()
        result["input_work"] = {
            "id": INPUT_ID, "text": "Integers, not reals.", "input_generation": 1,
            "confirmed_intent": None, "original_statement": "Prove n²+n is even for real n.",
            "prior_inputs": [],
        }
        if self.paid:
            result["billing_operation_id"] = OP
        return result

    def check_proof_request_claim(self, **kwargs):
        self.checks.append(kwargs)
        return self.current

    def settle_proof_request_input(self, *, request_id, input_id, payload):
        assert input_id == INPUT_ID
        self.settlements.append(payload)
        return {"id": request_id, "input_generation": 2, "input_state": "ready"}


def run(response, api=None, *, paid=False):
    api = api or InputApi(paid=paid)
    provider = CountedProvider([response], []) if paid else ProviderTransport([response])
    engine, old_provider = runtime([])
    processor = ProofRequestProcessor(
        api, engine, token_accounting_enabled=paid,
        input_interpreter=ProofInputInterpreter(OpenAIResponsesClient("test", transport=provider)),
    )
    result = processor.process(REQUEST_ID, CLAIM_ID, lambda _: None)
    assert old_provider.calls == []  # an intake claim never continues old mathematics
    return result, api, provider


@pytest.mark.parametrize("decision", [
    amendment(),
    {"kind": "independent", "effective_statement": None,
     "independent_statement": "Prove infinitely many primes exist.", "question": None},
    {"kind": "mixed", "effective_statement": "Prove n²+n is even for integer n.",
     "independent_statement": "Prove infinitely many primes exist.", "question": None},
    {"kind": "needs_intent", "effective_statement": None, "independent_statement": None,
     "question": "Is this a correction or a separate question?"},
])
def test_saved_input_routes_to_durable_interpretation_without_mathematics(decision):
    processed, api, provider = run(decision)
    assert processed and api.settlements[0]["decision"] == decision
    assert api.settlements[0]["error_code"] is None
    assert api.settlements[0]["usage"][0]["model_role"] == "proof_input_interpreter"
    context = json.loads(provider.calls[0]["input"].split("rules:\n")[1])
    assert context["original_statement"] == "Prove n²+n is even for real n."
    assert context["confirmed_premises"] == []
    assert all(check["input_id"] == INPUT_ID for check in api.checks)


@pytest.mark.parametrize("response", [429, "not JSON", amendment("\ud800"),
    {**amendment(), "question": "Should I prove it?"},
    {**amendment(), "extra": "untrusted"},
    '{"kind":"amend","kind":"independent"}',
])
def test_provider_or_contract_failure_retains_recoverable_input_hold(response):
    processed, api, _ = run(response)
    assert processed
    assert api.settlements[0]["decision"] is None
    assert api.settlements[0]["error_code"] == "input_interpretation_failed"


def test_intake_permit_and_receipt_bind_actual_call_to_saved_input_and_generation():
    processed, api, provider = run(amendment(), paid=True)
    assert processed and len(api.permits) == len(api.receipts) == len(provider.calls) == 1
    permit = api.permits[0]
    assert (permit["binding_kind"], permit["input_id"], permit["input_generation"]) == (
        "intake", INPUT_ID, 1
    )
    assert permit["model_role"] == "proof_input_interpreter"


def test_exhaustion_stops_before_provider_and_settles_saved_input_allowance_wait():
    api = InputApi(paid=True, permit_error=PalsApiError(
        "denied", status_code=402, error_code="token_budget_exceeded"
    ))
    processed, api, provider = run(amendment(), api, paid=True)
    assert processed and provider.calls == []
    assert api.settlements[0]["error_code"] == "token_budget_exceeded"


def test_obsolete_claim_never_calls_provider_or_settles_newer_input():
    processed, api, provider = run(amendment(), InputApi(current=False))
    assert not processed and not provider.calls and not api.settlements


def test_confirmed_intent_is_not_overwritten_by_provider():
    with pytest.raises(InputInterpretationError):
        validate_decision(amendment(), "independent")


def test_late_addition_stops_second_provider_call_at_boundary():
    provider = ProviderTransport([amendment(), amendment()])
    client = OpenAIResponsesClient("test", transport=provider)
    current = True
    with input_fence_scope(lambda: current):
        client.generate(model="gpt-6-luna", prompt="data")
        current = False
        with pytest.raises(InputSnapshotObsolete):
            client.generate(model="gpt-6-luna", prompt="data")
    assert len(provider.calls) == 1
