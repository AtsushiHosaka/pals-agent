from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pals_agent import step_timing
from pals_agent.artifacts import FileArtifactStore
from pals_agent.http_transport import HttpResponse
from pals_agent.models import Diagnostic, GeneratedProof, GenerationFeedback, ProofRequest
from pals_agent.openai import OpenAIError, OpenAIResponsesClient
from pals_agent.pipeline import ProofPipeline
from pals_agent.proof_reuse_usage import model_role
from pals_agent.step_timing_report import collect, render, rows
from tests.unit.test_pipeline import (
    BROKEN_REPAIRABLE_CODE,
    FIXED_REPAIRABLE_CODE,
    ContentAwareVerifier,
    RepairingGenerator,
    StatementSeedDraftCatalog,
)

# Strings that must never reach an event: a question, a Lean body, a user ID, a
# diagnostic message, a model answer and a credential.
SECRET_QUESTION = "SECRET-QUESTION prove that every widget is a gadget"
SECRET_LEAN = "SECRET-LEAN-BODY exact broken_identifier"
SECRET_USER = "user-7f3a-SECRET-USER-ID"
SECRET_MESSAGE = "SECRET-DIAGNOSTIC unknown identifier 'broken_identifier'"
SECRET_ANSWER = "SECRET-MODEL-ANSWER"
SECRETS = (SECRET_QUESTION, SECRET_LEAN, SECRET_USER, SECRET_MESSAGE, SECRET_ANSWER, "sk-test")


class FakeTransport:
    def __init__(self, status: int = 200, usage: dict[str, Any] | None = None) -> None:
        self.status = status
        self.usage = usage if usage is not None else {
            "input_tokens": 1200, "output_tokens": 300,
            "input_tokens_details": {"cached_tokens": 1000},
            "output_tokens_details": {"reasoning_tokens": 250},
        }

    def request(self, **kwargs: Any) -> HttpResponse:
        if self.status != 200:
            body = json.dumps({"error": {"message": SECRET_MESSAGE, "code": "server_error"}})
            return HttpResponse(status_code=self.status, body=body.encode())
        model = json.loads(kwargs["body"])["model"]
        body = json.dumps({
            "id": "resp_abc123", "model": model, "output_text": SECRET_ANSWER,
            "usage": self.usage,
        })
        return HttpResponse(status_code=200, body=body.encode())


def _client(transport: FakeTransport, effort: str | None = "medium") -> OpenAIResponsesClient:
    return OpenAIResponsesClient(
        api_key="sk-test", transport=transport, reasoning_effort=effort,  # type: ignore[arg-type]
    )


@pytest.fixture
def jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "steps.jsonl"
    monkeypatch.setenv(step_timing.ENV_JSONL, str(path))
    monkeypatch.delenv(step_timing.ENV_EMF, raising=False)
    return path


def _text(path: Path) -> str:
    step_timing.flush()
    return path.read_text(encoding="utf-8")


def _events(path: Path) -> list[dict[str, Any]]:
    step_timing.flush()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_disabled_by_default_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(step_timing.ENV_JSONL, raising=False)
    monkeypatch.delenv(step_timing.ENV_EMF, raising=False)
    assert not step_timing.enabled()
    with step_timing.run_scope("job-1") as run, step_timing.step("sketch") as record:
        assert run is None and record is None
    step_timing.record_step("queue_wait", 5)
    with model_role("sketch"):
        _client(FakeTransport()).generate(model="gpt-6.1-terra", prompt=SECRET_QUESTION)
    assert capsys.readouterr().err == ""
    assert list(tmp_path.iterdir()) == []


def test_model_call_records_step_model_effort_tokens_and_outcome(jsonl: Path) -> None:
    with model_role("sketch"):
        text = _client(FakeTransport()).generate(model="gpt-6.1-terra", prompt=SECRET_QUESTION)
    assert text == SECRET_ANSWER  # the call itself is unchanged
    (event,) = _events(jsonl)
    assert event["schema"] == step_timing.SCHEMA
    assert (event["step"], event["model"], event["effort"], event["outcome"]) == (
        "sketch", "gpt-6.1-terra", "medium", "ok",
    )
    assert event["input_tokens"] == 1200 and event["cached_input_tokens"] == 1000
    assert event["output_tokens"] == 300 and event["reasoning_tokens"] == 250
    assert event["duration_ms"] >= 0


@pytest.mark.parametrize(("status", "outcome"), [(429, "http_429"), (503, "http_5xx"),
                                                   (400, "http_4xx")])
def test_provider_failure_becomes_a_bounded_outcome_and_still_raises(
    jsonl: Path, status: int, outcome: str,
) -> None:
    with model_role("prove"), pytest.raises(OpenAIError):
        _client(FakeTransport(status=status)).generate(model="gpt-6.1-terra", prompt="p")
    (event,) = _events(jsonl)
    assert (event["step"], event["outcome"], event["http_status"]) == ("prove", outcome, status)
    assert SECRET_MESSAGE not in _text(jsonl)


def test_unknown_role_and_model_collapse_to_other(jsonl: Path) -> None:
    with model_role("free text role"):
        _client(FakeTransport(), effort=None).generate(model="gpt-6-luna", prompt="p")
    (event,) = _events(jsonl)
    assert event["step"] == "other"
    assert step_timing.model_dimension("some-private-finetune-7") == "other"


def test_a_failing_sink_never_changes_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(step_timing.ENV_JSONL, str(tmp_path / "missing-dir" / "x.jsonl"))
    before = step_timing.sink_errors()
    with model_role("draft"):
        text = _client(FakeTransport()).generate(model="gpt-6-luna", prompt="p")
    assert text == SECRET_ANSWER
    step_timing.flush()
    assert step_timing.sink_errors() > before


def test_exception_in_a_step_is_recorded_and_reraised(jsonl: Path) -> None:
    with pytest.raises(RuntimeError, match="boom"), step_timing.step("lean_check"):
        raise RuntimeError("boom " + SECRET_USER)
    (event,) = _events(jsonl)
    assert event["outcome"] == "error"
    assert SECRET_USER not in _text(jsonl)


def test_lean_step_keeps_error_codes_only(jsonl: Path) -> None:
    diagnostics = [
        Diagnostic(severity="error", code="lean.unknown_identifier", message=SECRET_MESSAGE),
        Diagnostic(severity="warning", code="lean.unused_variable", message=SECRET_MESSAGE),
        Diagnostic(severity="error", code=SECRET_QUESTION, message="x"),  # not a token
        Diagnostic(severity="error", code=None, message=SECRET_LEAN),
    ]
    with step_timing.step("lean_check") as record:
        assert record is not None
        record.set_lean(False, diagnostics)
    (event,) = _events(jsonl)
    # the question-shaped code is not in the closed list, so it is recorded as lean.other
    assert event["diag_codes"] == ["lean.other", "lean.unknown_identifier"]
    assert event["outcome"] == "lean_error"
    assert event["model"] is None


def test_deadline_interruption_is_its_own_outcome() -> None:
    assert step_timing.classify_lean(False, ["lean.compile_deadline_interrupted"]) == "timeout"
    assert step_timing.classify_lean(False, ["lean.compile_interrupted"]) == "interrupted"
    assert step_timing.classify_lean(True, []) == "ok"


class OpenAIBackedGenerator(RepairingGenerator):
    """Real OpenAI client calls (fake transport) in the roles the pipeline uses."""

    def __init__(self) -> None:
        super().__init__(route="prove")
        self.client = _client(FakeTransport())

    def _call(self, role: str) -> None:
        with model_role(role):
            self.client.generate(model="gpt-6.1-terra", prompt=SECRET_QUESTION + SECRET_LEAN)

    def generate(self, request: ProofRequest) -> GeneratedProof:
        self._call("prove")
        return GeneratedProof(
            lean_code=BROKEN_REPAIRABLE_CODE + SECRET_LEAN, model=self.model,
            raw_model_output=SECRET_ANSWER,
        )

    def select_repair_route(self, request: ProofRequest, feedback: GenerationFeedback) -> Any:
        self._call("route")
        return super().select_repair_route(request, feedback)

    def repair(self, request: ProofRequest, feedback: GenerationFeedback) -> GeneratedProof:
        self._call("repair")
        return GeneratedProof(
            lean_code=FIXED_REPAIRABLE_CODE, model=self.model, raw_model_output=SECRET_ANSWER,
        )


class LeakyVerifier(ContentAwareVerifier):
    def verify(self, lean_code: str) -> Any:
        result = super().verify(lean_code)
        if result.success:
            return result
        return type(result)(
            success=False,
            diagnostics=[Diagnostic(severity="error", code="lean.unknown_identifier",
                                    message=SECRET_MESSAGE, line=4, column=9)],
            stdout=SECRET_LEAN, stderr=SECRET_LEAN, elapsed_ms=9,
        )


def _run_pipeline(tmp_path: Path) -> Any:
    pipeline = ProofPipeline(
        generator=OpenAIBackedGenerator(),
        verifier=LeakyVerifier(),
        artifact_store=FileArtifactStore(tmp_path / "artifacts"),
        draft_catalog=StatementSeedDraftCatalog(),
    )
    return pipeline.run_statement(
        statement=SECRET_QUESTION,
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id=SECRET_USER,
    )


def test_one_repair_run_yields_the_per_step_breakdown(tmp_path: Path, jsonl: Path) -> None:
    result = _run_pipeline(tmp_path)
    assert result.state == "verified"
    events = _events(jsonl)
    steps = [(e["step"], e.get("attempt")) for e in events if e["event"] == "pipeline_step"]
    assert steps == [
        ("prove", 1), ("lean_check", 1), ("route", 2), ("repair", 2), ("lean_check", 2),
    ]
    checks = [e for e in events if e.get("step") == "lean_check"]
    assert [e["outcome"] for e in checks] == ["lean_error", "ok"]
    assert checks[0]["diag_codes"] == ["lean.unknown_identifier"]
    (run,) = [e for e in events if e["event"] == "pipeline_run"]
    assert run["state"] == "verified" and run["attempts"] == 2 and run["repairs_used"] == 1
    assert run["model_calls"] == 3 and run["input_tokens"] == 3600
    assert set(run["step_ms"]) == {"prove", "lean_check", "route", "repair"}
    assert run["run"] == step_timing.job_ref(SECRET_USER)
    assert all(e["run"] == run["run"] for e in events)


def test_events_never_contain_question_lean_user_or_messages(
    tmp_path: Path, jsonl: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(step_timing.ENV_EMF, "1")
    monkeypatch.delenv("PALS_QUALITY_EVENTS_AGENT_ENDPOINT", raising=False)
    _run_pipeline(tmp_path)
    with model_role("route"), pytest.raises(OpenAIError):
        _client(FakeTransport(status=500)).generate(model="gpt-6.1-terra", prompt=SECRET_LEAN)
    with pytest.raises(RuntimeError), step_timing.step("lean_check"):
        raise RuntimeError(SECRET_LEAN)
    step_timing.flush()
    written = _text(jsonl) + capsys.readouterr().err
    assert written.count("\n") >= 12  # both sinks saw every event
    for secret in SECRETS:
        assert secret not in written, secret


def test_only_allow_listed_keys_and_token_shaped_strings_appear(
    tmp_path: Path, jsonl: Path,
) -> None:
    _run_pipeline(tmp_path)
    step_keys = {
        "schema", "event", "ts_ms", "run", "step", "model", "effort", "duration_ms", "outcome",
        "attempt", "start_offset_ms", "input_tokens", "cached_input_tokens", "output_tokens",
        "reasoning_tokens", "diag_codes", "http_status", "cache", "container", "model_call",
    }
    run_keys = {
        "schema", "event", "ts_ms", "run", "total_ms", "model_calls", "model_ms", "lean_ms",
        "step_count", "step_ms", "input_tokens", "cached_input_tokens", "output_tokens",
        "reasoning_tokens", "state", "termination_reason", "attempts", "repairs_used",
        "busy_ms", "overlap_ms", "unattributed_ms", "truncated", "dropped_steps",
    }
    for event in _events(jsonl):
        allowed = step_keys if event["event"] == "pipeline_step" else run_keys
        assert set(event) <= allowed, set(event) - allowed
        for key, value in event.items():
            if key in {"step_ms", "diag_codes"}:
                continue
            if isinstance(value, str):
                assert step_timing._TOKEN.fullmatch(value), (key, value)


def test_free_text_is_refused_by_every_setter(jsonl: Path) -> None:
    step_timing.note_run()  # no run open: ignored
    with step_timing.run_scope(None, label="has spaces and SECRET") as run:
        assert run is not None and run.label is None
        step_timing.note_run(state=SECRET_QUESTION, termination_reason="lean error!", attempts=-3)
        with step_timing.step("not a step", model="x", effort="warp") as record:
            assert record is not None
            record.set_outcome("custom failure text")
    events = _events(jsonl)
    assert events[0]["step"] == "other" and events[0]["effort"] is None
    assert events[0]["outcome"] == "error"
    assert "state" not in events[1]  # SECRET_QUESTION was not a valid token
    assert not any(secret in _text(jsonl) for secret in SECRETS)


def test_emf_line_has_only_step_model_outcome_dimensions(jsonl: Path) -> None:
    with model_role("repair"):
        _client(FakeTransport()).generate(model="gpt-6.1-terra", prompt="p")
    (event,) = _events(jsonl)
    line = step_timing.to_emf(event)
    (directive,) = line["_aws"]["CloudWatchMetrics"]
    assert directive["Namespace"] == "PALS/Pipeline"
    assert directive["Dimensions"] == [["step", "model", "outcome"]]
    assert directive["Metrics"] == [{"Name": "step_duration_ms", "Unit": "Milliseconds"}]
    assert (line["step"], line["model"], line["outcome"]) == ("repair", "gpt-6.1-terra", "ok")
    assert line["outcome_detail"] == "ok"
    assert line["input_tokens"] == 1200  # a property for Logs Insights, not a metric
    assert len(json.dumps(line)) < 1024


def test_run_summary_emf_uses_the_outcome_dimension_only(tmp_path: Path, jsonl: Path) -> None:
    _run_pipeline(tmp_path)
    (run,) = [e for e in _events(jsonl) if e["event"] == "pipeline_run"]
    line = step_timing.to_emf(run)
    (directive,) = line["_aws"]["CloudWatchMetrics"]
    assert directive["Dimensions"] == [["outcome"]]
    assert line["outcome"] == "verified"
    assert {m["Name"] for m in directive["Metrics"]} == {
        "run_total_ms", "run_model_ms", "run_lean_ms", "run_model_calls",
    }
    assert "step_ms" not in line


def test_emf_uses_the_quality_events_transport_when_configured(
    jsonl: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    quality_events = pytest.importorskip("pals_agent.quality_events")
    sent: list[str] = []

    class Capture:
        def send(self, line: str) -> None:
            sent.append(line)

    monkeypatch.setenv(step_timing.ENV_EMF, "1")
    monkeypatch.setenv("PALS_QUALITY_EVENTS_TRANSPORT", "file")
    monkeypatch.setenv("PALS_QUALITY_EVENTS_FILE", "/var/empty/events.log")
    with quality_events.use_transport(Capture()):
        step_timing.record_step("queue_wait", 1500, job="job-9")
        step_timing.flush()
    assert len(sent) == 1 and json.loads(sent[0])["step"] == "queue_wait"
    assert capsys.readouterr().err == ""


def test_queue_wait_and_cache_steps(jsonl: Path) -> None:
    step_timing.record_step("queue_wait", 4321.04, job="job-9")
    step_timing.record_step("lean_env_cache", 12, outcome="hit")
    step_timing.record_step("lean_env_cache", 12, outcome="unexpected value")
    first, second, third = _events(jsonl)
    assert first["duration_ms"] == 4321.0 and first["run"] == step_timing.job_ref("job-9")
    assert second["outcome"] == "hit" and third["outcome"] == "error"


def test_report_aggregates_percentiles_totals_and_shares(tmp_path: Path, jsonl: Path) -> None:
    _run_pipeline(tmp_path)
    _run_pipeline(tmp_path / "second")
    samples = collect(_text(jsonl).splitlines())
    table = {(r["step"], r["model"], r["outcome"]): r for r in rows(samples)}
    assert table[("lean_check", "-", "lean_error")]["n"] == 2
    assert table[("repair", "gpt-6.1-terra", "ok")]["n"] == 2
    text = render(samples)
    assert "share" in text and "per run" in text.lower()


@pytest.mark.parametrize(("outcome", "coarse"), [
    ("ok", "ok"), ("lean_error", "rejected"), ("empty", "rejected"), ("timeout", "timeout"),
    ("interrupted", "timeout"), ("http_429", "error"), ("http_5xx", "error"),
    ("transport_error", "error"), ("hit", "hit"), ("unknown", "error"),
])
def test_the_metric_dimension_uses_the_coarse_outcome(outcome: str, coarse: str) -> None:
    event = {"event": "pipeline_step", "step": "sketch", "model": "gpt-6.1-terra",
             "duration_ms": 5.0, "outcome": outcome}
    line = step_timing.to_emf(event)
    assert line["outcome"] == coarse and line["outcome_detail"] == outcome


def test_latency_stages_become_steps_and_containers_stay_out_of_run_totals(
    jsonl: Path,
) -> None:
    from pals_agent.runtime_latency import latency_label, latency_stage, traced_delivery

    with (
        traced_delivery("proof_request", "request-1", emit=lambda _report: None),
        step_timing.run_scope("job-3"),
        latency_stage("assessment"),
    ):
        with latency_stage("recipe_attempt_selection"):
            pass
        with latency_stage("lean_compile_local"):  # timed by lean_check instead
            pass
        with latency_stage("not a stage"):  # free text never becomes a step
            pass
        with latency_label("explanation_review"):
            _client(FakeTransport()).generate(model="gpt-6-luna", prompt=SECRET_QUESTION)
    events = _events(jsonl)
    names = [(e.get("step"), e.get("container", False)) for e in events]
    assert ("assessment", True) in names and ("recipe_attempt_selection", False) in names
    assert all(step != "lean_compile_local" for step, _ in names)
    assert ("explanation_review", False) in names  # the model call carries the label role
    (run,) = [e for e in events if e["event"] == "pipeline_run"]
    assert "assessment" not in run["step_ms"]
    assert set(run["step_ms"]) == {"recipe_attempt_selection", "explanation_review"}
    assert SECRET_QUESTION not in _text(jsonl)


def test_report_keeps_containers_out_of_the_shares(jsonl: Path) -> None:
    with (
        step_timing.run_scope("job-4"),
        step_timing.step("assessment", container=True),
        step_timing.step("recipe_rank"),
    ):
        pass
    text = render(collect(_text(jsonl).splitlines()))
    assert "assessment (container)" in text and "encloses other steps" in text



# ---- review findings on PR 77: each test first reproduced the finding, then pinned the fix ----


def test_compiler_output_cannot_smuggle_text_through_a_diagnostic_code(jsonl: Path) -> None:
    from pals_agent.lean import parse_lean_diagnostics

    # Lean prints `error(<code>)`; a candidate that prints its own line can choose the code.
    stderr = (
        "Main.lean:3:2: error(secret_question_text_here): anything\n"
        "Main.lean:4:2: error(unknownIdentifier): unknown identifier 'x'\n"
        "Main.lean:5:2: error(unknown_identifier): known\n"
    )
    with step_timing.step("lean_check") as record:
        assert record is not None
        record.set_lean(False, parse_lean_diagnostics(stderr))
    (event,) = _events(jsonl)
    assert "lean.secret_question_text_here" not in _text(jsonl)
    assert set(event["diag_codes"]) <= step_timing.LEAN_CODES | {"lean.other"}
    assert "lean.other" in event["diag_codes"] and "lean.unknown_identifier" in event["diag_codes"]


def test_the_model_name_is_checked_when_the_event_is_built(jsonl: Path) -> None:
    with step_timing.step("sketch", model="gpt 6 SECRET QUESTION") as record:
        assert record is not None
    with step_timing.step("sketch", model="gpt-6.1-terra"):
        pass
    first, second = _events(jsonl)
    assert first["model"] == "other" and second["model"] == "gpt-6.1-terra"


def test_run_state_and_reason_come_from_closed_lists(jsonl: Path) -> None:
    with step_timing.run_scope("job-6"):
        step_timing.note_run(state="secret_question", termination_reason="secret_question")
    with step_timing.run_scope("job-7"):
        step_timing.note_run(state="verified", termination_reason="verified")
    first, second = [e for e in _events(jsonl) if e["event"] == "pipeline_run"]
    assert "state" not in first and "termination_reason" not in first
    assert second["state"] == "verified" and second["termination_reason"] == "verified"


def test_a_failing_jsonl_sink_does_not_stop_the_emf_sink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(step_timing.ENV_JSONL, str(tmp_path / "missing" / "x.jsonl"))
    monkeypatch.setenv(step_timing.ENV_EMF, "1")
    monkeypatch.delenv("PALS_QUALITY_EVENTS_AGENT_ENDPOINT", raising=False)
    step_timing.record_step("queue_wait", 5)
    step_timing.flush()
    assert '"step":"queue_wait"' in capsys.readouterr().err


def test_a_failing_emf_sink_does_not_stop_the_jsonl_sink(
    jsonl: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(step_timing.ENV_EMF, "1")

    def boom(_line: str) -> bool:
        raise RuntimeError("transport down")

    monkeypatch.setattr(step_timing, "_send_over_agent", boom)
    step_timing.record_step("queue_wait", 5)
    step_timing.flush()
    assert [e["step"] for e in _events(jsonl)] == ["queue_wait"]


def _emf_lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return [line for line in capsys.readouterr().err.splitlines() if line.startswith("{")]


def test_an_emf_only_report_recovers_the_run_step_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(step_timing.ENV_JSONL, raising=False)
    monkeypatch.setenv(step_timing.ENV_EMF, "1")
    monkeypatch.delenv("PALS_QUALITY_EVENTS_AGENT_ENDPOINT", raising=False)
    _run_pipeline(tmp_path)
    step_timing.flush()
    samples = collect(_emf_lines(capsys))
    summary = run_summary_of(samples)
    assert summary["runs"] == 1
    assert "lean_check" in summary["share_of_run_time"]
    assert "prove" in summary["share_of_run_time"]
    assert summary["share_of_run_time"]["unattributed"] < 1.0


def run_summary_of(samples: Any) -> dict[str, Any]:
    from pals_agent.step_timing_report import run_summary

    return run_summary(samples)


def test_the_report_ignores_foreign_or_incomplete_records() -> None:
    lines = [
        json.dumps({"schema": "pals.pipeline-step.v1", "event": "pipeline_step"}),
        json.dumps({"schema": "pals.pipeline-step.v1", "event": "pipeline_step",
                    "step": "sketch", "outcome": "ok", "duration_ms": "fast"}),
        json.dumps({"schema": "pals.pipeline-run.v1", "event": "pipeline_run", "run": "a"}),
        json.dumps({"schema": "pals.pipeline-run.v1", "event": "pipeline_run", "run": "b",
                    "total_ms": 1000.0, "step_ms": {"sketch": 400.0}, "unattributed_ms": 500.0}),
    ]
    samples = collect(lines)
    assert not samples.steps and len(samples.runs) == 1
    summary = run_summary_of(samples)
    assert summary["share_of_run_time"] == {"sketch": 0.4, "unattributed": 0.5}


def test_unattributed_time_is_the_recorded_union_not_the_sum_of_overlapping_steps() -> None:
    run = {"schema": "pals.pipeline-run.v1", "event": "pipeline_run", "run": "a",
           "total_ms": 100.0, "step_ms": {"a": 40.0, "b": 40.0}, "unattributed_ms": 60.0}
    summary = run_summary_of(collect([json.dumps(run)]))
    assert summary["share_of_run_time"]["unattributed"] == 0.6
    assert summary["step_shares_can_overlap"] is True


def test_a_huge_integer_duration_is_clamped_not_raised(jsonl: Path) -> None:
    step_timing.record_step("queue_wait", 10**400)
    step_timing.record_step("queue_wait", -(10**400))
    first, second = _events(jsonl)
    assert first["duration_ms"] == step_timing._MAX_MS and second["duration_ms"] == 0.0


def test_the_verifiers_ordinary_deadline_is_a_timeout() -> None:
    assert step_timing.classify_lean(False, ["lean.timeout"]) == "timeout"
    assert step_timing.classify_lean(False, ["lean.verifier_timeout"]) == "timeout"


def test_a_truncated_run_summary_says_so(
    jsonl: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(step_timing, "_QUEUE_LIMIT", 10_000)
    with step_timing.run_scope("job-8"):
        for _ in range(2050):
            step_timing.record_step("queue_wait", 1)
    (run,) = [e for e in _events(jsonl) if e["event"] == "pipeline_run"]
    assert run["truncated"] is True and run["dropped_steps"] == 2
    assert run["step_count"] == 2048
    samples = collect([json.dumps(run)])
    assert "truncated" in render(samples)


def test_a_model_call_without_a_recognized_role_still_counts_as_a_model_call(
    jsonl: Path,
) -> None:
    with step_timing.run_scope("job-9"), model_role("free text role"):
        _client(FakeTransport(), effort=None).generate(model="gpt-6-luna", prompt="p")
    (run,) = [e for e in _events(jsonl) if e["event"] == "pipeline_run"]
    assert run["model_calls"] == 1 and run["input_tokens"] == 1200


def test_a_stalled_sink_does_not_block_the_traced_call(
    jsonl: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    import time

    release = threading.Event()
    real = step_timing._write_sinks

    def stalled(line: str, emf_line: str | None) -> None:
        release.wait(timeout=5)
        real(line, emf_line)

    monkeypatch.setattr(step_timing, "_write_sinks", stalled)
    started = time.monotonic()
    step_timing.record_step("queue_wait", 5)
    assert time.monotonic() - started < 1.0  # returned while the sink was still stalled
    release.set()
    step_timing.flush()
    assert [e["step"] for e in _events(jsonl)] == ["queue_wait"]


def test_a_full_queue_drops_events_and_counts_them(
    jsonl: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    gate = threading.Event()
    monkeypatch.setattr(step_timing, "_write_sinks", lambda *_: gate.wait(timeout=5))
    monkeypatch.setattr(step_timing, "_QUEUE_LIMIT", 4)
    before = step_timing.sink_errors()
    for _ in range(30):
        step_timing.record_step("queue_wait", 1)
    assert step_timing.sink_errors() > before
    gate.set()
    step_timing.flush()


def test_a_delivery_is_one_run_so_worker_stages_share_its_summary(jsonl: Path) -> None:
    from pals_agent.runtime_latency import latency_stage, traced_delivery

    job = "11111111-1111-4111-8111-111111111111"
    with traced_delivery("proof_job", job, emit=lambda _r: None):
        with latency_stage("recipe_attempt_selection"):
            pass
        with latency_stage("explanation"), model_role("explain"):
            _client(FakeTransport()).generate(model="gpt-6-luna", prompt="p")
    events = _events(jsonl)
    (run,) = [e for e in events if e["event"] == "pipeline_run"]
    assert all(e["run"] == step_timing.job_ref(job) for e in events)
    assert run["model_calls"] == 1 and "explain" in run["step_ms"]


def test_the_overlap_calculation_does_not_depend_on_thread_scheduling() -> None:
    recorder = step_timing.RunRecorder(ref="r", label=None, started=0.0)
    event = {"event": "pipeline_step", "step": "explain", "duration_ms": 40.0}
    recorder.add(dict(event), (0.00, 0.04))
    recorder.add(dict(event, step="recipe_rank"), (0.00, 0.04))
    recorder.add(dict(event, step="lean_check", duration_ms=20.0), (0.06, 0.08))
    summary = recorder.summary()
    assert summary["busy_ms"] == 60.0 and summary["overlap_ms"] == 40.0


def test_the_report_numbers_follow_the_events() -> None:
    def step(name: str, ms: float, outcome: str = "ok") -> str:
        return json.dumps({"schema": "pals.pipeline-step.v1", "event": "pipeline_step",
                           "step": name, "model": None, "duration_ms": ms, "outcome": outcome})

    samples = collect([step("lean_check", ms) for ms in (100.0, 200.0, 300.0, 400.0, 500.0)])
    (row,) = rows(samples)
    assert (row["n"], row["p50_ms"], row["p95_ms"], row["max_ms"], row["sum_ms"]) == (
        5, 300.0, 480.0, 500.0, 1500.0,
    )


def test_the_closed_lists_match_the_pipeline_enums() -> None:
    from typing import get_args

    from pals_agent.pipeline import TerminationReason

    assert set(get_args(TerminationReason)) == step_timing.TERMINATION_REASONS


def test_the_reconciliation_wait_step_ends_as_error_when_visibility_cannot_be_renewed(
    jsonl: Path,
) -> None:
    from types import SimpleNamespace
    from typing import cast

    from pals_agent.settings import AgentSettings
    from pals_agent.worker import SqsProofWorker
    from tests.unit.test_worker import (
        ExplainerThatMustNotRun,
        PendingCandidateApi,
        StructuringFailurePipeline,
    )

    clock = [0.0]

    def worker(**options: Any) -> SqsProofWorker:
        return SqsProofWorker(
            settings=cast(AgentSettings, SimpleNamespace()),
            api_client=cast(Any, PendingCandidateApi()),
            pipeline=StructuringFailurePipeline(),
            explainer=ExplainerThatMustNotRun(),
            monotonic=lambda: clock[0],
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            **options,
        )

    def denied(seconds: int) -> None:
        raise RuntimeError("denied")

    assert worker()._wait_for_candidate_reconciliation(
        proof_job_id="job-pending", extend_visibility=denied, refresh_visibility=False,
    ) is None
    clock[0] = 0.0
    assert worker(stop_requested=lambda: clock[0] >= 10)._wait_for_candidate_reconciliation(
        proof_job_id="job-pending", extend_visibility=lambda seconds: None,
        refresh_visibility=False,
    ) is None
    waits = [e for e in _events(jsonl) if e.get("step") == "lean_reconcile_wait"]
    assert [e["outcome"] for e in waits] == ["error", "interrupted"]


def test_template_lookup_is_a_hit_or_miss_step(jsonl: Path) -> None:
    from pals_agent.pipeline import _template_lookup

    assert _template_lookup(lambda: None) is None
    assert _template_lookup(lambda: object()) is not None
    first, second = _events(jsonl)
    assert (first["step"], first["outcome"]) == ("template_hit", "miss")
    assert second["outcome"] == "hit"
