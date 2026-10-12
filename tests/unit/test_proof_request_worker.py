import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from pals_agent.api_client import PalsApiClient, PalsApiError
from pals_agent.http_transport import HttpResponse
from pals_agent.lean import LeanVerifier
from pals_agent.proof_request_worker import ProofRequestProcessor
from pals_agent.proof_reuse import ProofReuseResult
from pals_agent.worker import SqsProofWorker, parse_agent_task, parse_sqs_agent_message
from tests.unit.test_proof_reuse import READY, REQUEST, decision, runtime

REQUEST_ID = "11111111-1111-4111-8111-111111111111"
CLAIM_ID = "22222222-2222-4222-8222-222222222222"


class ApiBoundary:
    def __init__(self, status="acquired", settle_error=False):
        self.status = status
        self.settle_error = settle_error
        self.settlements = []
        self.usage = []

    def acquire_proof_request_claim(self, **kwargs):
        return {
            "status": self.status,
            "claim_id": kwargs["claim_id"],
            "request": dict(REQUEST, id=REQUEST_ID, status="assessing", revision=2),
            "lease_expires_at": (datetime.now(UTC) + timedelta(seconds=240)).isoformat(),
        }

    def record_proof_request_usage(self, **kwargs):
        self.usage.append(kwargs)

    def settle_proof_request(self, *, request_id, payload):
        self.settlements.append(payload)
        if self.settle_error:
            raise PalsApiError("uncertain commit")
        return {"id": request_id, "status": payload["outcome"]}


def test_processor_settles_revision_sources_instantiation_and_per_call_usage():
    engine, provider = runtime([READY, decision()])
    api = ApiBoundary()
    visibility = []
    assert ProofRequestProcessor(api, engine).process(REQUEST_ID, CLAIM_ID, visibility.append)
    assert visibility == [270]
    settlement = api.settlements[0]
    assert settlement["expected_revision"] == 2 and settlement["claim_id"] == CLAIM_ID
    assert (
        settlement["outcome"] == "answered"
        and settlement["answer"]["evidence_kind"] == "llm_assessed"
    )
    assert len(settlement["usage"]) == len(api.usage) == len(provider.calls) == 3
    assert settlement["usage"][0]["input_tokens"] == 100
    assert settlement["private_evidence"]["instantiation"]["substitutions"][0]["domain"] == "Nat"


@pytest.mark.parametrize("status,ack", [("busy", False), ("terminal", True)])
def test_claim_busy_or_terminal_never_spends_tokens(status, ack):
    engine, provider = runtime([])
    assert (
        ProofRequestProcessor(ApiBoundary(status), engine).process(
            REQUEST_ID,
            CLAIM_ID,
            lambda seconds: None,
        )
        is ack
    )
    assert provider.calls == []


def test_uncertain_settlement_does_not_generate_again():
    engine, provider = runtime([READY, decision()])
    assert not ProofRequestProcessor(ApiBoundary(settle_error=True), engine).process(
        REQUEST_ID,
        CLAIM_ID,
        lambda seconds: None,
    )
    assert len(provider.calls) == 3


def test_worker_routes_new_sqs_message_before_lean_pipeline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Natural proof SQS must never enter Lean/proof-job pipeline")

    monkeypatch.setattr(LeanVerifier, "verify", forbidden)
    monkeypatch.setattr(SqsProofWorker, "process_proof_job", forbidden)
    engine, provider = runtime([READY, decision()])
    api = ApiBoundary()
    deleted = []
    sqs = SimpleNamespace(
        receive_message=lambda **kwargs: {
            "Messages": [
                {
                    "Body": f"proof_request:{REQUEST_ID}",
                    "MessageId": "delivery-1",
                    "ReceiptHandle": "receipt",
                }
            ]
        },
        change_message_visibility=lambda **kwargs: None,
        delete_message=lambda **kwargs: deleted.append(kwargs),
    )
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *a, **kw: sqs)
    settings = SimpleNamespace(
        proof_jobs_queue_url="queue", aws_endpoint_url=None, aws_region="ap-northeast-1"
    )
    worker = SqsProofWorker(
        settings=settings,
        api_client=api,
        pipeline=None,
        explainer=None,
        pipeline_factory=forbidden,
        proof_request_processor=ProofRequestProcessor(api, engine),
    )
    assert worker.run_once()
    assert len(deleted) == 1 and api.settlements[0]["outcome"] == "answered"
    assert len(provider.calls) == 3


def test_prefix_requires_exact_uuid_and_sqs_has_no_proof_job_attributes():
    assert parse_agent_task(f"proof_request:{REQUEST_ID}").kind == "proof_request"
    for body in ("proof_request:garbage", f"proof_request:{REQUEST_ID} "):
        with pytest.raises(ValueError):
            parse_agent_task(body)
    with pytest.raises(ValueError):
        parse_sqs_agent_message(
            {
                "Body": f"proof_request:{REQUEST_ID}",
                "MessageId": "id",
                "ReceiptHandle": "receipt",
                "MessageAttributes": {"job": {}},
            }
        )


def test_real_api_client_uses_worker_authenticated_claim_settlement_and_usage_contract():
    calls = []

    class Transport:
        def request(self, **kwargs):
            calls.append(kwargs)
            response = {"recorded": True} if kwargs["url"].endswith("/usage") else {}
            return HttpResponse(200, json.dumps(response).encode())

    client = PalsApiClient("http://localhost:8000", "worker-test", transport=Transport())
    client.acquire_proof_request_claim(request_id=REQUEST_ID, claim_id=CLAIM_ID, lease_ms=240000)
    client.record_proof_request_usage(request_id=REQUEST_ID, claim_id=CLAIM_ID, usage={"x": 1})
    client.settle_proof_request(request_id=REQUEST_ID, payload={"outcome": "answered"})
    assert [call["url"].rsplit("/", 1)[1] for call in calls] == ["claims", "usage", "settlements"]
    assert all(call["headers"]["X-PALS-Worker-Secret"] == "worker-test" for call in calls)
    assert json.loads(calls[0]["body"]) == {"claim_id": CLAIM_ID, "lease_ms": 240000}


def test_api_validation_diagnostics_keep_only_bounded_known_location_and_type_identifiers():
    secret = "PRIVATE_API_INPUT_SECRET"
    detail = [
        {"loc": ["body", "answer", "text"], "type": "string_too_long",
         "msg": secret, "input": {"prompt": secret}, "ctx": {"credential": secret}},
        {"loc": ["body", "usage", 0, "provider_request_id"], "type": "string_type",
         "msg": secret, "input": secret},
        {"loc": ["body", "private_evidence", secret], "type": secret,
         "msg": secret, "input": secret},
    ]

    class Transport:
        def request(self, **kwargs):
            return HttpResponse(422, json.dumps({"detail": detail}).encode())

    client = PalsApiClient("http://localhost:8000", secret, transport=Transport())
    with pytest.raises(PalsApiError) as failure:
        client.settle_proof_request(request_id=REQUEST_ID, payload={"answer": secret})
    error = failure.value
    assert error.status_code == 422 and error.error_code is None
    assert error.validation_errors == (
        ("body.answer.text", "string_too_long"),
        ("body.usage.0.provider_request_id", "string_type"),
        ("body.private_evidence._redacted", "_redacted"),
    )
    assert secret not in str(error) + repr(vars(error))
    assert error.__cause__ is None
    assert len(PalsApiError("safe", validation_errors=detail * 10).validation_errors) == 8
    deep = PalsApiError("safe", validation_errors=[{
        "loc": ["body"] * 20 + [secret], "type": "missing", "input": secret,
    }])
    assert deep.validation_errors == ((".".join(["body"] * 12 + ["_truncated"]), "missing"),)


@pytest.mark.parametrize("body", [b"not JSON", b"[]", b'{"detail":"PRIVATE"}',
                                 b'{"detail":[{"msg":"PRIVATE","input":"PRIVATE"}]}'])
def test_unstructured_api_error_has_no_validation_diagnostics(body):
    class Transport:
        def request(self, **kwargs):
            return HttpResponse(422, body)

    client = PalsApiClient("http://localhost:8000", "PRIVATE", transport=Transport())
    with pytest.raises(PalsApiError) as failure:
        client.settle_proof_request(request_id=REQUEST_ID, payload={})
    assert failure.value.validation_errors == ()
    assert "PRIVATE" not in str(failure.value) + repr(vars(failure.value))


def test_uncertain_settlement_warning_is_safe_and_does_not_retry_or_regenerate(caplog):
    secret = "PRIVATE_PROMPT_INPUT_CREDENTIAL"

    class RejectedApi(ApiBoundary):
        def settle_proof_request(self, *, request_id, payload):
            self.settlements.append(payload)
            raise PalsApiError(secret, status_code=422, error_code="proof_request_invalid",
                               validation_errors=[{
                                   "loc": ["body", "answer", "text"],
                                   "type": "string_too_long", "msg": secret, "input": secret,
                               }])

    engine, provider = runtime([READY, decision()])
    api = RejectedApi()
    assert not ProofRequestProcessor(api, engine).process(REQUEST_ID, CLAIM_ID, lambda _: None)
    assert len(api.settlements) == 1 and len(provider.calls) == 3
    assert len(caplog.records) == 1
    warning = caplog.records[0]
    assert warning.levelname == "WARNING" and warning.exc_info is None
    assert "proof_request_settlement_failed" in warning.message
    assert f"request_id={REQUEST_ID}" in warning.message
    assert f"claim_id={CLAIM_ID}" in warning.message
    assert "status_code=422 error_code=proof_request_invalid" in warning.message
    assert "body.answer.text" in warning.message and "string_too_long" in warning.message
    assert secret not in caplog.text


def test_settlement_warning_elides_unsafe_error_code_and_exception_message(caplog):
    secret = "PRIVATE\nSECRET-KEY"

    class RejectedApi(ApiBoundary):
        def settle_proof_request(self, **kwargs):
            raise PalsApiError(secret, error_code=secret)

    engine, provider = runtime([READY, decision()])
    assert not ProofRequestProcessor(RejectedApi(), engine).process(
        REQUEST_ID, CLAIM_ID, lambda _: None,
    )
    assert len(provider.calls) == 3
    assert "status_code=None error_code=None validation_errors=()" in caplog.text
    assert secret not in caplog.text and "SECRET-KEY" not in caplog.text


@pytest.mark.parametrize("outcome,status,level", [
    ("answered", "answered", "INFO"),
    ("needs_input", "needs_input", "INFO"),
    ("formal", "verifying", "INFO"),
    ("failed", "failed", "WARNING"),
])
def test_committed_assessment_logs_safe_status_phase_and_review_without_private_data(
    caplog, outcome, status, level,
):
    secret = "PRIVATE_PROMPT_ANSWER_REVIEW_RATIONALE"
    result = ProofReuseResult(
        outcome, {"text": secret}, {"text": secret},
        "proof_reuse_answer_review_failed" if outcome == "failed" else None,
        {"phase": "independent_answer_qa", "token_qa": {"approved": outcome != "failed"},
         "token_qa_rationale": secret, "provider_failure": {"message": secret}},
    )

    class SettledApi(ApiBoundary):
        def settle_proof_request(self, *, request_id, payload):
            self.settlements.append(payload)
            return {"id": request_id, "status": status, "error_code": result.error_code}

    api = SettledApi()
    caplog.set_level(logging.INFO, logger="pals_agent.proof_request_worker")
    assert ProofRequestProcessor(api, SimpleNamespace(answer=lambda *a, **k: result)).process(
        REQUEST_ID, CLAIM_ID, lambda _: None,
    )
    assert len(api.settlements) == 1 and len(caplog.records) == 1
    event = caplog.records[0]
    assert event.levelname == level and event.exc_info is None
    assert "proof_request_settled" in event.message
    assert f"request_id={REQUEST_ID} claim_id={CLAIM_ID} status={status}" in event.message
    assert "assessment_phase=independent_answer_qa" in event.message
    assert f"review_approved={outcome != 'failed'}" in event.message
    assert secret not in caplog.text


def test_committed_failure_uses_api_failure_code_and_never_echoes_unknown_labels(caplog):
    secret = "private_prompt_that_is_a_valid_identifier"
    result = ProofReuseResult(
        "formal", None, None, None,
        {"phase": secret, "answer_qa": {"approved": secret}, "failure_details": secret},
    )

    class SettledApi(ApiBoundary):
        def settle_proof_request(self, *, request_id, payload):
            return {"id": request_id, "status": "failed", "error_code": "lean_flow_unavailable"}

    processor = ProofRequestProcessor(SettledApi(), SimpleNamespace(answer=lambda *a, **k: result))
    assert processor.process(
        REQUEST_ID, CLAIM_ID, lambda _: None,
    )
    assert (
        "status=failed assessment_phase=unrecognized "
        "error_code=lean_flow_unavailable" in caplog.text
    )
    assert "review_approved=None" in caplog.text and secret not in caplog.text


@pytest.mark.parametrize("label", ["private_identifier", {"secret": "PRIVATE"}, "PRIVATE\nKEY"])
def test_terminal_error_allowlist_does_not_echo_arbitrary_api_labels(caplog, label):
    result = ProofReuseResult("failed", None, None, "proof_reuse_provider_unavailable", {})

    class SettledApi(ApiBoundary):
        def settle_proof_request(self, *, request_id, payload):
            return {"id": request_id, "status": "failed", "error_code": label}

    processor = ProofRequestProcessor(SettledApi(), SimpleNamespace(answer=lambda *a, **k: result))
    assert processor.process(
        REQUEST_ID, CLAIM_ID, lambda _: None,
    )
    assert "error_code=unrecognized" in caplog.text
    assert "private_identifier" not in caplog.text and "PRIVATE" not in caplog.text


def test_mismatched_settlement_is_not_logged_as_committed(caplog):
    result = ProofReuseResult("answered", None, {"text": "PRIVATE"}, None, {})

    class WrongApi(ApiBoundary):
        def settle_proof_request(self, *, request_id, payload):
            return {"id": CLAIM_ID, "status": "answered"}

    caplog.set_level(logging.INFO, logger="pals_agent.proof_request_worker")
    processor = ProofRequestProcessor(WrongApi(), SimpleNamespace(answer=lambda *a, **k: result))
    assert not processor.process(
        REQUEST_ID, CLAIM_ID, lambda _: None,
    )
    assert caplog.records == []


@pytest.mark.parametrize("private_input", ["PRIVATE" * 10000, "私" * 30000])
def test_oversized_api_validation_body_is_not_retained_or_parsed_for_diagnostics(private_input):
    class Transport:
        def request(self, **kwargs):
            body = json.dumps({"detail": [{"loc": ["body", "answer", "text"],
                                          "type": "string_too_long", "input": private_input}]},
                              ensure_ascii=False).encode()
            assert len(body) > 65536
            return HttpResponse(422, body)

    client = PalsApiClient("http://localhost:8000", "PRIVATE", transport=Transport())
    with pytest.raises(PalsApiError) as failure:
        client.settle_proof_request(request_id=REQUEST_ID, payload={})
    assert failure.value.validation_errors == ()
    assert private_input not in str(failure.value) + repr(vars(failure.value))


class LeanApiBoundary(ApiBoundary):
    def __init__(self, recipes):
        super().__init__()
        self.recipes = recipes
        self.lookups = []

    def acquire_proof_request_claim(self, **kwargs):
        return dict(super().acquire_proof_request_claim(**kwargs), lean_flow=True)

    def lookup_proof_request_recipes(self, **kwargs):
        raise AssertionError("released requests must not look up Draft-linked Recipes")

    def search_proof_request_recipes(self, **kwargs):
        self.lookups.append(kwargs)
        return list(self.recipes)

    def settle_proof_request(self, *, request_id, payload):
        self.settlements.append(payload)
        status = "verifying" if payload["outcome"] == "formal" else payload["outcome"]
        return {"id": request_id, "status": status}


def test_released_lean_flow_settles_a_formal_plan_for_the_linked_job():
    from tests.unit.test_proof_reuse_lean_flow import INTENT

    engine, _ = runtime([READY, INTENT])
    api = LeanApiBoundary([])
    assert ProofRequestProcessor(api, engine).process(REQUEST_ID, CLAIM_ID, lambda seconds: None)
    settlement = api.settlements[0]
    assert settlement["outcome"] == "formal" and settlement["answer"] is None
    assert settlement["formal_plan"] == {"kind": "dsp", "statement": READY["statement"]}
    assert api.lookups[0]["claim_id"] == CLAIM_ID and api.lookups[0]["request_id"] == REQUEST_ID


def test_unreleased_lean_flow_keeps_the_previous_answer_path():
    engine, _ = runtime([READY, decision()])
    api = ApiBoundary()
    assert ProofRequestProcessor(api, engine).process(REQUEST_ID, CLAIM_ID, lambda seconds: None)
    assert "formal_plan" not in api.settlements[0]


def test_non_boolean_lean_flag_is_rejected_before_any_model_call():
    engine, provider = runtime([])
    api = LeanApiBoundary([])
    api.acquire_proof_request_claim = lambda **kwargs: dict(
        ApiBoundary.acquire_proof_request_claim(api, **kwargs), lean_flow="yes"
    )
    assert not ProofRequestProcessor(api, engine).process(
        REQUEST_ID, CLAIM_ID, lambda seconds: None
    )
    assert provider.calls == []
