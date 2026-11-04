"""Worker boundaries use controlled API/SQS fixtures; heartbeat writes a real local file.

These tests do not execute a model, Lean compiler, AWS service or database transaction.
"""

import json
import threading
import time
from types import SimpleNamespace

import pytest

from pals_agent import cli
from pals_agent import quality_events as qe
from pals_agent.proof_request_worker import ProofRequestProcessor
from pals_agent.proof_reuse import ProofReuseResult
from tests.unit.test_proof_request_worker import CLAIM_ID, REQUEST_ID, ApiBoundary


@pytest.fixture(autouse=True)
def isolated_quality_state(monkeypatch):
    for name in (qe.ENABLED_ENV, qe.ENVIRONMENT_ENV, qe.REVISION_ENV, qe.TRANSPORT_ENV,
                 qe.FILE_ENV, qe.AGENT_ENDPOINT_ENV, "PALS_ENV"):
        monkeypatch.delenv(name, raising=False)
    qe.reset_for_tests()
    yield
    assert not any(t.name == "pals-quality-worker-heartbeat" for t in threading.enumerate())
    qe.reset_for_tests()


def enable_file(monkeypatch, path):
    monkeypatch.setenv(qe.ENABLED_ENV, "1")
    monkeypatch.setenv(qe.ENVIRONMENT_ENV, "probe")
    monkeypatch.setenv(qe.TRANSPORT_ENV, "file")
    monkeypatch.setenv(qe.FILE_ENV, str(path))
    monkeypatch.setenv(qe.REVISION_ENV, "test-revision")


def records(path):
    if not path.exists():
        return []
    # Reading may race the next write; the writer sends a complete line in one write.
    return [json.loads(line) for line in path.read_text().splitlines() if line.endswith("}")]


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline, "heartbeat_timeout"
        time.sleep(0.002)


def test_actual_heartbeat_keeps_running_during_busy_consumer_and_stops_on_failure(
    tmp_path, monkeypatch,
):
    path = tmp_path / "quality.jsonl"
    enable_file(monkeypatch, path)
    with (pytest.raises(RuntimeError, match="consumer_failed"),
          qe.worker_heartbeat(interval_seconds=0.01)):
        wait_for(lambda: len(records(path)) >= 3)
        raise RuntimeError("consumer_failed")
    before = path.read_bytes()
    time.sleep(0.025)
    assert path.read_bytes() == before
    for event in records(path):
        assert set(event) == {"_aws", "Environment", "WorkerHeartbeat", "event", "revision"}
        assert event["event"] == "worker_heartbeat" and event["WorkerHeartbeat"] == 1
        assert event["Environment"] == "probe" and event["revision"] == "test-revision"
        directive = event["_aws"]["CloudWatchMetrics"]
        assert directive == [{"Namespace": "PALS/ProofQuality", "Dimensions": [["Environment"]],
                              "Metrics": [{"Name": "WorkerHeartbeat", "Unit": "Count"}]}]


def test_disabled_heartbeat_allocates_no_thread_or_transport(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("disabled telemetry allocated a resource")

    monkeypatch.setattr(qe.threading, "Thread", forbidden)
    monkeypatch.setattr(qe, "_transport", forbidden)
    with qe.worker_heartbeat():
        assert not qe.enabled()
    assert qe.dropped_count() == 0


def test_heartbeat_send_and_thread_start_failures_preserve_consumer_result(tmp_path, monkeypatch):
    # Opening a child of an ordinary file fails immediately with ENOTDIR.
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("fixture")
    enable_file(monkeypatch, parent_file / "quality.jsonl")
    with qe.worker_heartbeat(interval_seconds=0.01):
        wait_for(lambda: qe.dropped_count() >= 2)
    assert qe.dropped_count() >= 2

    def fail(*args, **kwargs):
        raise OSError("PRIVATE_THREAD_EXCEPTION")

    monkeypatch.setattr(qe.threading, "Thread", fail)
    with qe.worker_heartbeat():
        result = "consumer-completed"
    assert result == "consumer-completed" and qe.dropped_count() >= 3


@pytest.mark.parametrize("code", [
    "guest_quota_exhausted", "guest_session_rate_limited", "guest_global_daily_limit",
])
def test_guest_limits_are_policy_refusals_not_quality_failures(code):
    assert qe.classify_request_error(code) == "policy.unsupported_request"
    event = qe.build_proof_request_terminal(
        environment="probe", request_id=REQUEST_ID, status="failed", error_code=code,
    ).emf
    assert event["FailureClass"] == "policy-refusal"
    assert event["FailureCode"] == "policy.unsupported_request"
    assert event["raw_code"] == code
    assert event["ProofRequestsRefused"] == 1
    assert "ProofRequestsFailed" not in event and "ProofRequestsSucceeded" not in event


@pytest.mark.parametrize("outcome,status", [
    ("answered", "answered"), ("failed", "failed"), ("needs_input", "needs_input"),
    ("formal", "verifying"), ("formal", "failed"),
])
def test_worker_ack_and_exact_replay_never_publish_terminal_events(
    outcome, status, tmp_path, monkeypatch,
):
    path = tmp_path / "quality.jsonl"
    enable_file(monkeypatch, path)

    class ReplayedApi(ApiBoundary):
        def settle_proof_request(self, *, request_id, payload):
            self.settlements.append(payload)
            return {"id": request_id, "status": status}

    result = ProofReuseResult(outcome, None, None, "lean_verification_failed", {})
    engine = SimpleNamespace(answer=lambda *args, **kwargs: result)
    api = ReplayedApi()
    processor = ProofRequestProcessor(api, engine)
    # The API can return the same id/status for both a new settlement and a replay.
    assert processor.process(REQUEST_ID, CLAIM_ID, lambda seconds: None)
    assert processor.process(REQUEST_ID, CLAIM_ID, lambda seconds: None)
    assert len(api.settlements) == 2
    assert not path.exists() and qe.dropped_count() == 0


@pytest.mark.parametrize("state", ["terminal", "uncertain"])
def test_terminal_redelivery_and_lost_ack_never_publish_from_worker(state, tmp_path, monkeypatch):
    path = tmp_path / "quality.jsonl"
    enable_file(monkeypatch, path)
    result = ProofReuseResult("answered", None, None, None, {})
    engine = SimpleNamespace(answer=lambda *args, **kwargs: result)
    api = ApiBoundary(status="terminal" if state == "terminal" else "acquired",
                      settle_error=state == "uncertain")
    assert ProofRequestProcessor(api, engine).process(
        REQUEST_ID, CLAIM_ID, lambda seconds: None,
    ) is (state == "terminal")
    assert not path.exists() and qe.dropped_count() == 0


def configured_cli(monkeypatch):
    settings = SimpleNamespace(worker_shared_secret="fixture", api_base_url="https://api.invalid",
                               proof_jobs_queue_url="https://queue.invalid")
    monkeypatch.setattr(cli.AgentSettings, "from_env", lambda: settings)
    monkeypatch.setattr(cli, "build_proof_request_processor", lambda settings, api: None)
    for name in ("build_proof_explainer", "build_proof_output_reviewer",
                 "build_proof_semantic_reviewer", "build_recipe_attempt_planner"):
        monkeypatch.setattr(cli, name, lambda settings: None)


def test_cli_real_consumer_owns_heartbeat_and_cleans_readiness(tmp_path, monkeypatch):
    path = tmp_path / "quality.jsonl"
    marker = tmp_path / "ready"
    enable_file(monkeypatch, path)
    configured_cli(monkeypatch)

    def run():
        assert marker.read_text().isdigit()
        wait_for(lambda: len(records(path)) >= 1)
        raise cli.WorkerSqsUnavailableError("fixture")

    monkeypatch.setattr(cli, "SqsProofWorker", lambda **kwargs: SimpleNamespace(run_forever=run))
    assert cli.main(["worker", "--processes", "1", "--ready-file", str(marker)]) == 75
    assert not marker.exists() and records(path)[0]["event"] == "worker_heartbeat"


def test_supervisor_and_worker_once_do_not_mask_consumer_liveness(tmp_path, monkeypatch):
    path = tmp_path / "quality.jsonl"
    enable_file(monkeypatch, path)
    configured_cli(monkeypatch)
    monkeypatch.setattr(cli, "run_lane_workers", lambda **kwargs: 0)
    assert cli.main(["worker", "--lane", "proof", "--processes", "2"]) == 0
    monkeypatch.setattr(cli, "SqsProofWorker",
                        lambda **kwargs: SimpleNamespace(run_once=lambda: True))
    assert cli.main(["worker-once"]) == 0
    assert not path.exists()
