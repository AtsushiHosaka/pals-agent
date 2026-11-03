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


def _failing_worker(monkeypatch, errors, *, slept):
    from botocore.exceptions import EndpointConnectionError

    class Unreachable:
        def __init__(self):
            self.calls = 0

        def receive_message(self, **kwargs):
            self.calls += 1
            if self.calls <= errors:
                raise EndpointConnectionError(endpoint_url="https://sqs.invalid")
            return {"Messages": []}

    queue = Unreachable()
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *a, **kw: queue)
    clock = [0.0]

    def sleep(seconds):
        slept.append(seconds)
        clock[0] += seconds

    settings = SimpleNamespace(
        aws_endpoint_url=None, aws_region="ap-northeast-1",
        sqs_proof_jobs_queue_url="proof-queue", worker_idle_sleep_seconds=1.0,
        proof_capability="full",
    )
    worker = SqsProofWorker(
        settings=settings, api_client=SimpleNamespace(), pipeline=None, explainer=None,
        lane="proof", sleep=sleep, monotonic=lambda: clock[0],
        stop_requested=lambda: queue.calls > errors,
    )
    return worker, queue


def test_transient_sqs_error_backs_off_instead_of_killing_the_worker(monkeypatch):
    slept = []
    worker, queue = _failing_worker(monkeypatch, 3, slept=slept)
    monkeypatch.setattr("pals_agent.worker.worker_queue_url", lambda *a: "proof-queue")
    worker.run_forever()
    assert queue.calls == 4
    assert sum(slept) == 2 + 4 + 8


def test_sqs_outage_past_its_limit_ends_the_worker_for_a_lane_restart_decision(monkeypatch):
    from pals_agent.worker import WorkerSqsUnavailableError

    slept = []
    worker, _queue = _failing_worker(monkeypatch, 10_000, slept=slept)
    monkeypatch.setattr("pals_agent.worker.worker_queue_url", lambda *a: "proof-queue")
    with pytest.raises(WorkerSqsUnavailableError):
        worker.run_forever()
    assert 900 <= sum(slept) < 960


def test_run_once_reports_a_receive_only_when_it_succeeded(monkeypatch):
    from botocore.exceptions import EndpointConnectionError

    worker, _queue = _failing_worker(monkeypatch, 1, slept=[])
    monkeypatch.setattr("pals_agent.worker.worker_queue_url", lambda *a: "proof-queue")
    received = []
    with pytest.raises(EndpointConnectionError):
        worker.run_once(on_received=lambda: received.append(True))
    assert received == []
    worker.run_once(on_received=lambda: received.append(True))
    assert received == [True]


def test_an_error_after_a_long_delivery_is_not_a_continuous_sqs_outage(monkeypatch):
    from botocore.exceptions import EndpointConnectionError
    from pals_agent.worker import WorkerSqsUnavailableError

    slept = []
    worker, queue = _failing_worker(monkeypatch, 0, slept=slept)
    monkeypatch.setattr("pals_agent.worker.worker_queue_url", lambda *a: "proof-queue")
    original = queue.receive_message
    events = iter(["fail", "long-then-fail", "long-then-fail", "stop"])

    def run_once(*, on_received=None):
        event = next(events)
        if event == "fail":
            raise EndpointConnectionError(endpoint_url="https://sqs.invalid")
        original()
        on_received()
        if event == "stop":
            stops.append(True)
            return True
        worker.sleep(1000)  # A job longer than the outage limit, ending in a failed delete.
        raise EndpointConnectionError(endpoint_url="https://sqs.invalid")

    stops = []
    runner = SimpleNamespace(
        run_once=run_once, monotonic=worker.monotonic, sleep=worker.sleep,
        settings=worker.settings, lane=worker.lane, stop_requested=lambda: bool(stops),
        _sleep_until_stop=lambda seconds: worker.sleep(seconds),
    )
    try:
        SqsProofWorker.run_forever(runner)
    except WorkerSqsUnavailableError:  # pragma: no cover
        pytest.fail("two errors around a successful receive stopped the lane")
    assert stops == [True]


def test_deliveries_that_keep_failing_after_their_receive_stop_the_lane(monkeypatch):
    from botocore.exceptions import ClientError
    from pals_agent.worker import WorkerSqsUnavailableError

    slept = []
    worker, _queue = _failing_worker(monkeypatch, 0, slept=slept)
    calls = []

    def run_once(*, on_received=None):
        calls.append(True)
        on_received()
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteMessage")

    runner = SimpleNamespace(
        run_once=run_once, monotonic=worker.monotonic, sleep=worker.sleep,
        settings=worker.settings, lane=worker.lane, stop_requested=lambda: False,
        _sleep_until_stop=lambda seconds: worker.sleep(seconds),
    )
    with pytest.raises(WorkerSqsUnavailableError, match="delivery failure"):
        SqsProofWorker.run_forever(runner)
    assert len(calls) == 5


def test_a_finished_delivery_clears_the_failed_delivery_count(monkeypatch):
    from botocore.exceptions import ClientError

    slept = []
    worker, _queue = _failing_worker(monkeypatch, 0, slept=slept)
    outcomes = iter(([False] * 4 + [True]) * 3)
    finished = []

    def run_once(*, on_received=None):
        on_received()
        try:
            good = next(outcomes)
        except StopIteration:
            finished.append(True)
            return True
        if not good:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteMessage")
        return True

    runner = SimpleNamespace(
        run_once=run_once, monotonic=worker.monotonic, sleep=worker.sleep,
        settings=worker.settings, lane=worker.lane, stop_requested=lambda: bool(finished),
        _sleep_until_stop=lambda seconds: worker.sleep(seconds),
    )
    SqsProofWorker.run_forever(runner)
    assert finished == [True]


def test_cli_removes_readiness_and_exits_nonzero_on_an_sqs_outage(monkeypatch, tmp_path):
    from pals_agent.worker import WorkerSqsUnavailableError

    ready = tmp_path / "ready"

    class Worker:
        def __init__(self, **kwargs):
            pass

        def run_forever(self):
            assert ready.exists()
            raise WorkerSqsUnavailableError("outage")

    for name in ("configure_worker_api_trust", "worker_queue_url", "build_proof_request_processor"):
        monkeypatch.setattr(cli, name, lambda *a, **kw: None)
    monkeypatch.setattr(cli, "SqsProofWorker", Worker)
    monkeypatch.setattr(cli, "AgentSettings", SimpleNamespace(from_env=lambda: SimpleNamespace(
        worker_shared_secret="fixture-only", api_base_url="https://api.invalid",
        proof_capability="natural-only", api_ca_certificate_path=None,
    )))
    monkeypatch.setenv("PALS_WORKER_PROCESSES", "1")
    code = cli.main(["worker", "--lane", "assessment", "--ready-file", str(ready)])
    assert code == cli.LANE_UNAVAILABLE_EXIT != 0
    assert not ready.exists()


def test_worker_once_still_surfaces_an_sqs_error(monkeypatch):
    from botocore.exceptions import BotoCoreError

    worker, _queue = _failing_worker(monkeypatch, 1, slept=[])
    monkeypatch.setattr("pals_agent.worker.worker_queue_url", lambda *a: "proof-queue")
    with pytest.raises(BotoCoreError):
        worker.run_once()
