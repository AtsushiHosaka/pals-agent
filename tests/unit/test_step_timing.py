from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pals_agent import quality_events, step_timing
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


def _events(path: Path) -> list[dict[str, Any]]:
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
    assert SECRET_MESSAGE not in jsonl.read_text(encoding="utf-8")


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
    assert step_timing.sink_errors() > before


def test_exception_in_a_step_is_recorded_and_reraised(jsonl: Path) -> None:
    with pytest.raises(RuntimeError, match="boom"), step_timing.step("lean_check"):
        raise RuntimeError("boom " + SECRET_USER)
    (event,) = _events(jsonl)
    assert event["outcome"] == "error"
    assert SECRET_USER not in jsonl.read_text(encoding="utf-8")


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
    assert event["diag_codes"] == ["lean.unknown_identifier"]
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
    written = jsonl.read_text(encoding="utf-8") + capsys.readouterr().err
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
        "reasoning_tokens", "diag_codes", "http_status", "cache",
    }
    run_keys = {
        "schema", "event", "ts_ms", "run", "total_ms", "model_calls", "model_ms", "lean_ms",
        "step_count", "step_ms", "input_tokens", "cached_input_tokens", "output_tokens",
        "reasoning_tokens", "state", "termination_reason", "attempts", "repairs_used",
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
    assert not any(secret in jsonl.read_text(encoding="utf-8") for secret in SECRETS)


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
    sent: list[str] = []

    class Capture:
        def send(self, line: str) -> None:
            sent.append(line)

    monkeypatch.setenv(step_timing.ENV_EMF, "1")
    monkeypatch.setenv("PALS_QUALITY_EVENTS_TRANSPORT", "file")
    monkeypatch.setenv("PALS_QUALITY_EVENTS_FILE", "/var/empty/events.log")
    with quality_events.use_transport(Capture()):
        step_timing.record_step("queue_wait", 1500, job="job-9")
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
    samples = collect(jsonl.read_text(encoding="utf-8").splitlines())
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
