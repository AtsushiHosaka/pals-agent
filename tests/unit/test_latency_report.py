import io
import json

import pytest

from pals_agent import latency_report as r


def _phase(service, phase, role, elapsed, server=None):
    return {
        "service": service, "phase": phase, "role": role, "calls": 1,
        "elapsed_total_ms": elapsed, "server_timed_calls": 0 if server is None else 1,
        "server_elapsed_total_ms": server or 0.0,
        "transport_overhead_total_ms": 0.0 if server is None else elapsed - server,
    }


def _trace(kind="proof_request", elapsed=1000.0, phases=()):
    return json.dumps({"event": "proof_request_latency", "metrics": {
        "trace_kind": kind, "processor_elapsed_ms": elapsed, "unattributed_ms": 100.0,
        "queue": {"queue_wait_ms": 30, "receive_count": 1}, "notes": {"reconciliation_polls": 4},
        "phases": list(phases),
    }}, separators=(",", ":"))


def test_percentile_matches_the_documented_interpolation():
    values = [float(v) for v in range(1, 12)]
    assert r.percentile(values, 0.5) == 6.0
    assert r.percentile(values, 0.95) == pytest.approx(10.5)
    assert r.percentile([7.0], 0.95) == 7.0


def test_events_follow_log_prefixes_and_other_lines_are_ignored():
    samples = r.collect([
        "2026-11-02 INFO pals.answer_path_timing "
        '{"duration_ms":12.5,"event":"api_route_timing","route":"settle"}\n',
        "unrelated line with statement text\n",
        '{"event":"proof_request_latency","metrics":' + "{broken\n",
        "lean_stage stage=compile elapsed_ms=6800.500 environment_cache=none\n",
    ])
    assert samples["api", "route/settle"] == [12.5]
    assert samples["verifier", "lean/compile"] == [6800.5]
    assert len(samples) == 2


def test_paths_are_named_from_the_calls_actually_made():
    assert r._path({"trace_kind": "proof_job"}) == "fresh_proof_job"
    assert r._path({"trace_kind": "proof_request", "phases": []}) == "assessment_no_model"
    semantic = [
        _phase("provider", "generation", "recipe_semantic_assessment", 1.0),
        _phase("provider", "generation", "token_answer_qa", 1.0),
    ]
    assert r._path({"phases": semantic}) == "recipe_semantic"
    assert r._path({"phases": [
        *semantic, _phase("provider", "generation", "chat_intent", 1.0),
    ]}) == "recipe_semantic_then_assessment"
    chat = {"phases": [_phase("provider", "generation", "chat_intent", 1.0)]}
    assert r._path(chat) == "assessment"


def test_trace_sums_a_stage_within_one_delivery_and_separates_server_from_overhead():
    line = _trace(phases=[
        _phase("provider", "generation", "recipe_semantic_assessment", 900.0, 800.0),
        _phase("provider", "generation", "token_answer_qa", 700.0, 650.0),
        _phase("api", "permit", "recipe_semantic_assessment", 40.0, 10.0),
        _phase("api", "permit", "token_answer_qa", 60.0, 20.0),
    ])
    samples = r.collect([line])
    path = "recipe_semantic"
    assert samples[path, "api/permit"] == [100.0]
    assert samples[path, "provider/generation[recipe_semantic_assessment]"] == [900.0]
    assert samples[path, "trace/api_server_total"] == [30.0]
    assert samples[path, "trace/provider_server_total"] == [1450.0]
    assert samples[path, "trace/transport_overhead_total"] == [220.0]
    assert samples[path, "queue/sqs_wait"] == [30.0]
    assert samples[path, "note/reconciliation_polls"] == [4.0]


def test_handoff_joins_the_assessment_and_its_linked_job_by_correlation_only():
    event = {"event": "proof_request_latency"}
    assessment = dict(event, metrics={
        "trace_kind": "proof_request", "request_correlation_sha256": "a",
        "started_unix_ms": 1000, "processor_elapsed_ms": 500.0,
    })
    job = dict(event, metrics={
        "trace_kind": "proof_job", "linked_request_correlation_sha256": "a",
        "request_correlation_sha256": "b", "started_unix_ms": 1750,
        "processor_elapsed_ms": 10.0,
    })
    samples = r.collect([json.dumps(assessment), json.dumps(job)])
    assert samples["fresh_proof_job", "handoff/assessment_to_job"] == [250.0]


def test_cli_prints_rows_from_a_file_and_json(tmp_path, capsys):
    log = tmp_path / "worker.log"
    phases = [_phase("local", "explanation", "other", 5.0)]
    log.write_text(_trace("proof_job", phases=phases) + "\n")
    assert r.main([str(log)]) == 0
    assert "fresh_proof_job" in capsys.readouterr().out
    assert r.main(["--json", str(log)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert {"path": "fresh_proof_job", "stage": "local/explanation", "n": 1, "p50_ms": 5.0,
            "p95_ms": 5.0, "max_ms": 5.0} in report


def test_cli_reads_standard_input(monkeypatch, capsys):
    monkeypatch.setattr(r.sys, "stdin", io.StringIO(
        '{"event":"proof_request_dispatch","queued_age_ms":25.0,"send_ms":4.0,"finish_ms":1.0}\n'
    ))
    assert r.main(["-"]) == 0
    assert "proof_request_dispatch/queued_age_ms" in capsys.readouterr().out
