from __future__ import annotations

import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pals_agent import cli
from pals_agent.settings import AgentSettings
from pals_agent.worker import AgentTask, SqsProofWorker, worker_queue_url


class Queue:
    def __init__(self, body: str, *, attributes: dict | None = None, on_receive=lambda: None):
        self.message = {
            "MessageId": "delivery", "ReceiptHandle": "receipt", "Body": body,
            "MessageAttributes": attributes or {},
        }
        self.received = []
        self.visibility = []
        self.deleted = []
        self.on_receive = on_receive

    def receive_message(self, **kwargs):
        self.received.append(kwargs)
        self.on_receive()
        return {"Messages": [self.message]}

    def change_message_visibility(self, **kwargs):
        self.visibility.append(kwargs)

    def delete_message(self, **kwargs):
        self.deleted.append(kwargs)


def settings(**changes):
    return SimpleNamespace(
        **dict(
            proof_jobs_queue_url="proof-queue", proof_requests_queue_url="assessment-queue",
            aws_endpoint_url=None, aws_region="ap-northeast-1", worker_idle_sleep_seconds=0,
            worker_shared_secret="secret", api_base_url="http://api.invalid",
        ) | changes
    )


def worker(lane, processor=None, stop=lambda: False):
    return SqsProofWorker(
        settings=settings(), api_client=None, pipeline=None, explainer=None,
        proof_request_processor=processor, lane=lane, stop_requested=stop,
    )


@pytest.mark.parametrize("lane,expected", [("all", "proof-queue"), ("proof", "proof-queue"),
                                           ("assessment", "assessment-queue")])
def test_queue_selection(lane, expected):
    assert worker_queue_url(settings(), lane) == expected


@pytest.mark.parametrize("lane", ["proof", "assessment"])
@pytest.mark.parametrize("queue", [None, "proof-queue"])
def test_dedicated_lanes_fail_closed_without_distinct_queues(lane, queue):
    with pytest.raises(RuntimeError):
        worker_queue_url(settings(proof_requests_queue_url=queue), lane)


def test_all_lane_preserves_single_queue_configuration():
    assert worker_queue_url(settings(proof_requests_queue_url=None), "all") == "proof-queue"


def test_proof_lane_requires_formal_capability():
    with pytest.raises(RuntimeError, match="PALS_PROOF_CAPABILITY=full"):
        worker_queue_url(settings(proof_capability="natural-only"), "proof")


@pytest.mark.parametrize("acknowledged", [True, False])
def test_assessment_claim_visibility_and_ack_use_only_assessment_queue(monkeypatch, acknowledged):
    request_id = str(uuid4())
    queue = Queue(f"proof_request:{request_id}")
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *a, **kw: queue)
    calls = []

    def process(task_id, claim_id, extend_visibility):
        calls.append((task_id, claim_id))
        extend_visibility(270)
        return acknowledged

    assert worker("assessment", SimpleNamespace(process=process)).run_once()
    assert calls[0][0] == request_id and calls[0][1]
    assert queue.received[0]["QueueUrl"] == "assessment-queue"
    assert queue.visibility == [{
        "QueueUrl": "assessment-queue", "ReceiptHandle": "receipt", "VisibilityTimeout": 270,
    }]
    assert queue.deleted == ([{"QueueUrl": "assessment-queue", "ReceiptHandle": "receipt"}]
                             if acknowledged else [])


@pytest.mark.parametrize("lane,kind", [("proof", "proof_request"), ("assessment", "proof"),
                                      ("assessment", "clarification"),
                                      ("assessment", "explanation"),
                                      ("assessment", "external_operation")])
def test_misrouted_tasks_never_claim_process_delete_or_release(monkeypatch, caplog, lane, kind):
    task_id = str(uuid4())
    if kind in {"proof_request", "external_operation"}:
        body = f"{kind}:{task_id}"
    elif kind == "proof":
        body = task_id
    elif kind == "clarification":
        body = f'{{"kind":"clarification","id":"{task_id}"}}'
    else:
        body = f'{{"kind":"explanation","id":"{task_id}","retry_id":"{uuid4()}"}}'
    queue = Queue(body, attributes={"task": {"StringValue": task_id}} if kind == "proof" else {})
    if kind == "external_operation":
        # A lane rejects every unsupported task kind, including optional tool
        # capabilities, without requiring those capabilities to be installed.
        monkeypatch.setattr("pals_agent.worker.parse_sqs_agent_message",
                            lambda message: (AgentTask(kind=kind, id=task_id), "receipt"))
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *a, **kw: queue)
    monkeypatch.setattr(SqsProofWorker, "_fresh_claim_id", lambda self: pytest.fail("claimed"))
    assert worker(lane).run_once()
    assert not queue.deleted and not queue.visibility
    assert "worker_task_lane_mismatch" in caplog.text
    assert task_id not in caplog.text and body not in caplog.text


def test_assessment_long_poll_drain_returns_to_its_own_queue(monkeypatch):
    state = {"stop": False}
    queue = Queue(f"proof_request:{uuid4()}", on_receive=lambda: state.update(stop=True))
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *a, **kw: queue)
    monkeypatch.setattr(SqsProofWorker, "_fresh_claim_id", lambda self: pytest.fail("claimed"))
    worker("assessment", stop=lambda: state["stop"]).run_forever()
    assert not queue.deleted
    assert queue.visibility == [{
        "QueueUrl": "assessment-queue", "ReceiptHandle": "receipt", "VisibilityTimeout": 0,
    }]


@pytest.mark.parametrize("acknowledged", [True, False])
def test_assessment_drain_finishes_delivery_before_stopping(monkeypatch, acknowledged):
    state = {"stop": False}
    queue = Queue(f"proof_request:{uuid4()}")
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *a, **kw: queue)

    def process(*args):
        state["stop"] = True
        return acknowledged

    worker("assessment", SimpleNamespace(process=process), lambda: state["stop"]).run_forever()
    assert len(queue.received) == 1 and len(queue.deleted) == int(acknowledged)


def test_all_lane_still_processes_natural_requests_from_original_queue(monkeypatch):
    queue = Queue(f"proof_request:{uuid4()}")
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *a, **kw: queue)
    assert worker("all", SimpleNamespace(process=lambda *args: True)).run_once()
    assert queue.received[0]["QueueUrl"] == "proof-queue"
    assert queue.deleted == [{"QueueUrl": "proof-queue", "ReceiptHandle": "receipt"}]


def test_assessment_processes_while_formal_worker_is_blocked(monkeypatch):
    formal_entered, release_formal, assessment_done = (threading.Event() for _ in range(3))
    failures = []
    proof_queue = Queue("proof-id", attributes={"task": {"StringValue": "proof-id"}})
    request_queue = Queue(f"proof_request:{uuid4()}")
    queues = iter([proof_queue, request_queue])
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *a, **kw: next(queues))

    def process_formal(self, *args, **kwargs):
        formal_entered.set()
        if not release_formal.wait(5):
            raise AssertionError("formal delivery did not drain")
        return True

    def process_assessment(*args):
        assert formal_entered.is_set() and not release_formal.is_set()
        assessment_done.set()
        return True

    def run_formal():
        try:
            worker("proof").run_once()
        except BaseException as error:
            failures.append(error)

    monkeypatch.setattr(SqsProofWorker, "process_proof_job", process_formal)
    thread = threading.Thread(target=run_formal)
    thread.start()
    try:
        assert formal_entered.wait(2)
        assert worker("assessment", SimpleNamespace(process=process_assessment)).run_once()
        assert assessment_done.is_set() and request_queue.deleted and not proof_queue.deleted
    finally:
        release_formal.set()
        thread.join(5)
    assert not thread.is_alive() and not failures and proof_queue.deleted


@pytest.mark.parametrize("command", ["worker", "worker-once"])
def test_assessment_cli_constructs_only_natural_processor(monkeypatch, command):
    monkeypatch.setattr(cli.AgentSettings, "from_env", lambda: settings())
    natural = object()
    monkeypatch.setattr(cli, "build_proof_request_processor", lambda *args: natural)
    for name in (
        "build_proof_explainer", "build_proof_output_reviewer", "build_proof_semantic_reviewer",
        "build_recipe_attempt_planner", "build_pipeline", "build_external_operation_processor",
    ):
        if hasattr(cli, name):
            monkeypatch.setattr(cli, name, lambda *args: pytest.fail("formal factory constructed"))

    def construct(**kwargs):
        assert kwargs["lane"] == "assessment" and kwargs["proof_request_processor"] is natural
        assert kwargs["pipeline_factory"] is None and kwargs["recipe_attempt_planner"] is None
        assert kwargs["explainer"] is None and kwargs["proof_reviewer"] is None
        return SimpleNamespace(run_once=lambda: True, run_forever=lambda: None)

    monkeypatch.setattr(cli, "SqsProofWorker", construct)
    assert cli.main([command, "--lane", "assessment"]) == 0


@pytest.mark.parametrize("queue", [None, "proof-queue"])
def test_cli_invalid_lane_configuration_clears_readiness_before_factories(monkeypatch, tmp_path,
                                                                         queue):
    marker = tmp_path / "ready"
    marker.write_text("stale")
    monkeypatch.setattr(cli.AgentSettings, "from_env",
                        lambda: settings(proof_requests_queue_url=queue))
    monkeypatch.setattr(cli, "build_proof_request_processor", lambda *args: pytest.fail("factory"))
    with pytest.raises(RuntimeError):
        cli.main(["worker", "--lane", "assessment", "--ready-file", str(marker)])
    assert not marker.exists()


@pytest.mark.parametrize("name", ["PALS_SQS_PROOF_REQUESTS_QUEUE_URL",
                                 "PALS_PROOF_REQUESTS_QUEUE_URL"])
def test_settings_load_dedicated_assessment_queue_aliases(monkeypatch, name):
    monkeypatch.delenv("PALS_SQS_PROOF_REQUESTS_QUEUE_URL", raising=False)
    monkeypatch.delenv("PALS_PROOF_REQUESTS_QUEUE_URL", raising=False)
    monkeypatch.setenv(name, "assessment-queue")
    assert AgentSettings.from_env().proof_requests_queue_url == "assessment-queue"
