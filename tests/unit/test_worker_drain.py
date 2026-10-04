from types import SimpleNamespace
from uuid import uuid4

import pytest

from pals_agent import cli
from pals_agent.worker import SqsProofWorker


class Queue:
    def __init__(self, on_receive=lambda: None):
        self.receives = 0
        self.deleted = []
        self.visibility = []
        self.on_receive = on_receive

    def receive_message(self, **kwargs):
        self.receives += 1
        assert self.receives == 1, "draining worker received a subsequent message"
        self.on_receive()
        return {
            "Messages": [
                {
                    "MessageId": "message",
                    "ReceiptHandle": "receipt",
                    "Body": '{"kind":"clarification","id":"' + str(uuid4()) + '"}',
                }
            ]
        }

    def delete_message(self, **kwargs):
        self.deleted.append(kwargs)

    def change_message_visibility(self, **kwargs):
        self.visibility.append(kwargs)


def worker(stop):
    return SqsProofWorker(
        settings=SimpleNamespace(
            proof_jobs_queue_url="local",
            aws_endpoint_url="local",
            aws_region="local",
            worker_idle_sleep_seconds=0,
        ),
        api_client=None,
        pipeline=None,
        explainer=None,
        stop_requested=stop,
    )


@pytest.mark.parametrize("outcome", [True, False, "fatal"])
def test_drain_finishes_current_delivery_and_only_acknowledges_ordinary_success(
    monkeypatch, outcome
):
    state = {"stop": False}
    queue = Queue()
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *a, **kw: queue)

    def process(self, *args, **kwargs):
        state["stop"] = True  # SIGTERM during the current model/verification work.
        assert not queue.deleted
        if outcome == "fatal":
            raise KeyboardInterrupt()
        return outcome

    monkeypatch.setattr(SqsProofWorker, "process_clarification", process)
    instance = worker(lambda: state["stop"])
    if outcome == "fatal":
        with pytest.raises(KeyboardInterrupt):
            instance.run_forever()
    else:
        instance.run_forever()
    assert queue.receives == 1
    assert len(queue.deleted) == (1 if outcome is True else 0)
    assert not queue.visibility


def test_drain_during_long_poll_returns_unclaimed_receipt_without_processing(monkeypatch):
    state = {"stop": False}
    queue = Queue(lambda: state.update(stop=True))
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *a, **kw: queue)
    monkeypatch.setattr(
        SqsProofWorker, "_fresh_claim_id", lambda self: pytest.fail("no claim on drain")
    )
    worker(lambda: state["stop"]).run_forever()
    assert not queue.deleted
    assert queue.visibility == [
        {"QueueUrl": "local", "ReceiptHandle": "receipt", "VisibilityTimeout": 0}
    ]


def test_preexisting_drain_does_not_receive(monkeypatch):
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *a, **kw: pytest.fail("received"))
    worker(lambda: True).run_forever()


def test_cli_installs_draining_signals_and_restores_handlers_and_readiness(monkeypatch, tmp_path):
    settings = SimpleNamespace(
        worker_shared_secret="secret", api_base_url="local", proof_jobs_queue_url="local"
    )
    monkeypatch.setattr(cli.AgentSettings, "from_env", lambda: settings)
    monkeypatch.setattr(cli, "build_proof_request_processor", lambda settings, api: None)
    for name in (
        "build_proof_explainer",
        "build_proof_output_reviewer",
        "build_proof_semantic_reviewer",
        "build_recipe_attempt_planner",
    ):
        monkeypatch.setattr(cli, name, lambda settings: None)
    signals = (cli.signal.SIGTERM, cli.signal.SIGINT)
    previous = {signum: object() for signum in signals}
    handlers = dict(previous)

    def register(signum, handler):
        old = handlers[signum]
        handlers[signum] = handler
        return old

    monkeypatch.setattr(cli.signal, "signal", register)
    marker = tmp_path / "ready"

    def construct(**kwargs):
        def run():
            assert marker.exists()
            assert not kwargs["stop_requested"]()
            handlers[cli.signal.SIGTERM](cli.signal.SIGTERM, None)
            assert kwargs["stop_requested"]()
            handlers[cli.signal.SIGINT](cli.signal.SIGINT, None)

        return SimpleNamespace(run_forever=run)

    monkeypatch.setattr(cli, "SqsProofWorker", construct)
    assert cli.main(["worker", "--ready-file", str(marker)]) == 0
    assert handlers == previous
    assert not marker.exists()
