"""Local capability isolation tests; no provider, AWS or deployment acceptance."""
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pals_agent import cli
from pals_agent.settings import AgentSettings
from pals_agent.worker import SqsProofWorker, parse_sqs_agent_message


def forbidden(*args, **kwargs):
    raise AssertionError("disabled formal collaborator was called")


class ForbiddenApi:
    def __getattr__(self, name):
        return forbidden


class Queue:
    def __init__(self, body, attributes=None):
        self.message = {"MessageId": "message", "ReceiptHandle": "receipt", "Body": body,
                        "MessageAttributes": attributes or {}}
        self.deleted = []
        self.visibility = []

    def receive_message(self, **kwargs):
        return {"Messages": [self.message]}

    def delete_message(self, **kwargs):
        self.deleted.append(kwargs)

    def change_message_visibility(self, **kwargs):
        self.visibility.append(kwargs)


def natural_worker(**extra):
    return SqsProofWorker(
        settings=SimpleNamespace(proof_capability="natural-only", proof_jobs_queue_url="queue",
                                 aws_endpoint_url=None, aws_region="ap-northeast-1"),
        api_client=ForbiddenApi(), pipeline=None, explainer=None, uuid4_factory=forbidden,
        **extra,
    )


@pytest.mark.parametrize("value", ["", " ", "normal", "FULL", "natural-only "])
def test_invalid_environment_and_direct_capability_rejected(monkeypatch, value):
    monkeypatch.delenv("PALS_PROOF_CAPABILITY", raising=False)
    original = AgentSettings.from_env()
    monkeypatch.setenv("PALS_PROOF_CAPABILITY", value)
    with pytest.raises(ValueError, match="PALS_PROOF_CAPABILITY"):
        AgentSettings.from_env()
    with pytest.raises(ValueError, match="PALS_PROOF_CAPABILITY"):
        replace(original, proof_capability=value)


def test_default_full_and_explicit_natural_settings(monkeypatch):
    monkeypatch.delenv("PALS_PROOF_CAPABILITY", raising=False)
    assert AgentSettings.from_env().proof_capability == "full"
    monkeypatch.setenv("PALS_PROOF_CAPABILITY", "natural-only")
    assert AgentSettings.from_env().proof_capability == "natural-only"


@pytest.mark.parametrize("command", ["worker-once", "worker"])
def test_natural_cli_composes_only_ordinary_processor(monkeypatch, command):
    monkeypatch.setenv("PALS_PROOF_CAPABILITY", "natural-only")
    monkeypatch.setenv("PALS_WORKER_SHARED_SECRET", "worker-secret")
    monkeypatch.setenv("PALS_PROOF_JOBS_QUEUE_URL", "queue")
    for name in ("build_pipeline", "build_proof_explainer", "build_proof_output_reviewer",
                 "build_proof_semantic_reviewer", "build_recipe_attempt_planner",
                 "build_draft_embedding_model"):
        monkeypatch.setattr(cli, name, forbidden)
    ordinary = object()
    calls = []

    def processor(settings, api):
        assert settings.proof_capability == "natural-only"
        calls.append(api)
        return ordinary

    class Worker:
        def __init__(self, **kwargs):
            assert kwargs["proof_request_processor"] is ordinary
            for name in ("pipeline", "explainer", "output_reviewer", "proof_reviewer",
                         "pipeline_factory", "recipe_attempt_planner"):
                assert kwargs[name] is None

        def run_once(self):
            return False

        def run_forever(self):
            return None

    monkeypatch.setattr(cli, "build_proof_request_processor", processor)
    monkeypatch.setattr(cli, "SqsProofWorker", Worker)
    assert cli.main([command]) == 0
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["proof", "clarification", "explanation"])
def test_valid_formal_delivery_rejected_before_claim_api_visibility_or_delete(monkeypatch, kind):
    task_id, retry_id = str(uuid4()), str(uuid4())
    if kind == "proof":
        queue = Queue(task_id, {"task": {"DataType": "String", "StringValue": "proof"}})
    elif kind == "clarification":
        queue = Queue('{"kind":"clarification","id":"' + task_id + '"}')
    else:
        queue = Queue('{"kind":"explanation","id":"' + task_id + '","retry_id":"'
                      + retry_id + '"}')
    assert parse_sqs_agent_message(queue.message)[0].kind == kind
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *a, **kw: queue)
    assert natural_worker().run_once() is True
    assert queue.deleted == []
    assert queue.visibility == []


def test_direct_formal_entries_do_not_call_api_or_acquire_claim():
    worker = natural_worker()
    assert worker.process_proof_job("job") is False
    assert worker.process_clarification("clarification") is False
    assert worker.process_explanation_retry("job", retry_id="retry", claim_id="claim",
                                            extend_visibility=forbidden) is False


@pytest.mark.parametrize("acknowledge", [True, False])
def test_natural_request_retains_receipt_claim_and_ack_contract(monkeypatch, acknowledge):
    request_id, claim_id = str(uuid4()), uuid4()
    queue = Queue("proof_request:" + request_id)
    calls = []

    class Processor:
        def process(self, resource, claim, extend):
            calls.append((resource, claim))
            extend(30)
            return acknowledge

    worker = replace(natural_worker(proof_request_processor=Processor()),
                     uuid4_factory=lambda: claim_id)
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *a, **kw: queue)
    assert worker.run_once() is True
    assert calls == [(request_id, str(claim_id))]
    assert len(queue.deleted) == int(acknowledge)
    assert queue.visibility == [{"QueueUrl": "queue", "ReceiptHandle": "receipt",
                                 "VisibilityTimeout": 30}]


def test_poison_delivery_remains_unacknowledged(monkeypatch):
    queue = Queue("{broken")
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *a, **kw: queue)
    assert natural_worker().run_once() is True
    assert queue.deleted == queue.visibility == []
