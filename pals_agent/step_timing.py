"""Opt-in, content-free timing events for each step of one proof run.

``runtime_latency`` aggregates one SQS delivery by transport phase. This module adds
the per-step view that module cannot give: which model and reasoning effort ran, how
many tokens it used, which repair attempt it belonged to, how it ended, and how long
the Lean check took with which diagnostic codes. Both can run together.

Off by default. Turn it on with environment variables:

``PALS_STEP_TIMING_JSONL=<path>``
    Append one JSON object per line to ``<path>`` (local analysis, ``hint_ab.py``).
``PALS_STEP_TIMING_EMF=1``
    Write the same events to stderr as CloudWatch Embedded Metric Format lines
    (namespace ``PALS/Pipeline``), for the container log driver to forward.

Nothing from a question, a Lean source, a prompt, a model answer, a diagnostic
message or a user identity can enter an event. Every field is a number, a member of
a closed vocabulary, or a short token that matches ``_TOKEN``; anything else is
dropped before it is written. Recording never raises and never changes the traced
call: a sink failure is swallowed and counted. The design is in
``docs/pipeline-step-timing-2026-11-08/README.md`` in the parent repository.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

SCHEMA = "pals.pipeline-step.v1"
RUN_SCHEMA = "pals.pipeline-run.v1"
NAMESPACE = "PALS/Pipeline"
ENV_JSONL = "PALS_STEP_TIMING_JSONL"
ENV_EMF = "PALS_STEP_TIMING_EMF"

# Step names are the only values that can become a CloudWatch dimension besides the
# model and the outcome, so each set is closed. Unknown values collapse to "other".
MODEL_STEPS = frozenset({
    "openmath", "draft", "sketch", "prove", "route", "repair", "explain", "clarify",
    "proof_review", "proof_reuse_judge", "proof_reuse_judge_escalation",
    "recipe_semantic_assessment", "token_answer_qa", "chat_intent", "chat_explanation",
    "chat_explanation_qa", "draft_embedding", "explanation_review",
    "clarification_review", "semantic_review",
})
OTHER_STEPS = frozenset({
    "lean_check", "lean_sketch_check", "lean_reconcile_wait", "lean_env_cache", "queue_wait",
    "template_hit",
    # In-process stages named by runtime_latency.latency_stage, bridged as steps.
    "context_retrieval", "recipe_attempt_selection", "recipe_batch_validate",
    "recipe_prompt_build", "recipe_rank", "recipe_response_parse",
})
# These enclose other steps. They are recorded for reading, never added into run totals.
CONTAINER_STEPS = frozenset({"assessment", "explanation", "proof_pipeline", "semantic_review"})
STEPS = MODEL_STEPS | OTHER_STEPS | CONTAINER_STEPS | {"other"}
OUTCOMES = frozenset({
    "ok", "empty", "timeout", "transport_error", "http_429", "http_4xx", "http_5xx",
    "malformed", "model_mismatch", "config_error", "error",
    "lean_error", "interrupted", "hit", "miss", "fallback",
})
EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})
# Exact model identities that may appear as a dimension. Everything else is "other".
_MODELS = frozenset({
    "gpt-6-luna", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-5.6-terra", "gpt-5.4-mini",
    "gpt-5.4-nano", "text-embedding-3-small",
})
_TOKEN = re.compile(r"[A-Za-z0-9_.\-]{1,64}")
_MAX_CODES = 8
_MAX_MS = 86_400_000.0

_RUN: ContextVar[RunRecorder | None] = ContextVar("pals_step_timing_run", default=None)
_ATTEMPT: ContextVar[int | None] = ContextVar("pals_step_timing_attempt", default=None)
_CURRENT: ContextVar[StepRecord | None] = ContextVar("pals_step_timing_current", default=None)

_sink_lock = threading.Lock()
_sink_errors = 0


def enabled() -> bool:
    import os

    return bool(os.environ.get(ENV_JSONL) or os.environ.get(ENV_EMF) == "1")


def sink_errors() -> int:
    """Events lost to a failing sink since start-up; recording itself never raises."""
    return _sink_errors


def _token(value: object) -> str | None:
    return value if isinstance(value, str) and _TOKEN.fullmatch(value) else None


def _member(value: object, allowed: frozenset[str], fallback: str | None = "other") -> str | None:
    if isinstance(value, str) and value in allowed:
        return value
    return fallback


def _ms(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return round(min(max(float(value), 0.0), _MAX_MS), 1)


def _count(value: object) -> int | None:
    if type(value) is int and 0 <= value <= 9_007_199_254_740_991:
        return value
    return None


def job_ref(proof_job_id: object) -> str | None:
    """A 16-hex digest that joins events of one run without carrying the job ID."""
    if not isinstance(proof_job_id, str) or not proof_job_id:
        return None
    return hashlib.sha256(proof_job_id.encode("utf-8", "replace")).hexdigest()[:16]


def model_dimension(model: object) -> str:
    return _member(model, _MODELS, "other") or "other"


def classify_openai_error(diagnostics: Mapping[str, Any] | None) -> str:
    """Map the already-sanitized provider diagnostics to one bounded outcome."""
    d = diagnostics or {}
    stage = d.get("stage")
    if stage == "transport":
        return "timeout" if d.get("transport_kind") == "deadline" else "transport_error"
    if stage == "http":
        status = d.get("http_status")
        if status == 429:
            return "http_429"
        if type(status) is int and status >= 500:
            return "http_5xx"
        return "http_4xx"
    if stage == "empty_text":
        return "empty"
    if stage == "model":
        return "model_mismatch"
    if stage == "configuration":
        return "config_error"
    if stage in {"json", "structured_status", "output", "content"}:
        return "malformed"
    return "error"


# The metric dimension is coarser than the logged outcome, to bound CloudWatch series.
_COARSE = {
    "ok": "ok", "hit": "hit", "miss": "miss", "fallback": "fallback",
    "timeout": "timeout", "interrupted": "timeout",
    "empty": "rejected", "malformed": "rejected", "model_mismatch": "rejected",
    "lean_error": "rejected",
}


def coarse_outcome(outcome: object) -> str:
    """ok, hit, miss, fallback, timeout, rejected (the content failed), or error."""
    return _COARSE.get(outcome, "error") if isinstance(outcome, str) else "error"


def classify_lean(success: bool, codes: list[str]) -> str:
    if success:
        return "ok"
    if "lean.compile_deadline_interrupted" in codes:
        return "timeout"
    if "lean.compile_interrupted" in codes:
        return "interrupted"
    return "lean_error"


# ---------------------------------------------------------------- run aggregation


@dataclass
class RunRecorder:
    ref: str | None
    label: str | None
    started: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    steps: list[dict[str, Any]] = field(default_factory=list)
    final: dict[str, Any] = field(default_factory=dict)

    def add(self, event: dict[str, Any]) -> None:
        with self.lock:
            if len(self.steps) < 2048:
                self.steps.append(event)

    def summary(self) -> dict[str, Any]:
        with self.lock:
            steps = list(self.steps)
        by_step: dict[str, float] = {}
        tokens = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
                  "reasoning_tokens": 0}
        model_calls = 0
        model_ms = 0.0
        lean_ms = 0.0
        for event in steps:
            ms = event.get("duration_ms") or 0.0
            step = event["step"]
            if event.get("container"):
                continue
            by_step[step] = by_step.get(step, 0.0) + ms
            if step in MODEL_STEPS:
                model_calls += 1
                model_ms += ms
                for key in tokens:
                    tokens[key] += event.get(key) or 0
            elif step in {"lean_check", "lean_sketch_check"}:
                lean_ms += ms
        summary: dict[str, Any] = {
            "schema": RUN_SCHEMA,
            "event": "pipeline_run",
            "ts_ms": round(time.time() * 1000),
            "run": self.label or self.ref,
            "total_ms": _ms((time.monotonic() - self.started) * 1000),
            "model_calls": model_calls,
            "model_ms": _ms(model_ms),
            "lean_ms": _ms(lean_ms),
            "step_count": len(steps),
            "step_ms": {k: _ms(v) for k, v in sorted(by_step.items())},
            **tokens,
        }
        for key, value in self.final.items():
            summary[key] = value
        return summary


def note_run(
    *,
    state: object = None,
    termination_reason: object = None,
    attempts: object = None,
    repairs_used: object = None,
) -> None:
    """Record how the run ended. The state and reason are the pipeline's own enums."""
    run = _RUN.get()
    if run is None:
        return
    for key, value in (("state", state), ("termination_reason", termination_reason)):
        token = _token(value)
        if token is not None:
            run.final[key] = token
    for key, value in (("attempts", attempts), ("repairs_used", repairs_used)):
        count = _count(value)
        if count is not None:
            run.final[key] = count


@contextmanager
def run_scope(
    proof_job_id: object = None, *, label: str | None = None,
) -> Iterator[RunRecorder | None]:
    """Group the steps of one proof run and emit one summary line when it ends.

    ``label`` is for local tools that choose their own run name. Production passes
    only ``proof_job_id``, which is stored as a digest.
    """
    if not enabled() or _RUN.get() is not None:
        yield None
        return
    recorder = RunRecorder(ref=job_ref(proof_job_id), label=_token(label))
    run_token = _RUN.set(recorder)
    attempt_token = _ATTEMPT.set(None)
    try:
        yield recorder
    except BaseException:
        recorder.final.setdefault("state", "exception")
        raise
    finally:
        _ATTEMPT.reset(attempt_token)
        _RUN.reset(run_token)
        _write(recorder.summary())


def set_attempt(attempt: object) -> None:
    """Attempt number (1 = first generation) for the steps that follow in this run."""
    value = _count(attempt)
    if value is not None and _RUN.get() is not None:
        _ATTEMPT.set(value)


# -------------------------------------------------------------------- step events


class StepRecord:
    """Mutable fields of one open step. Setters ignore anything out of vocabulary."""

    __slots__ = (
        "step", "model", "effort", "outcome", "tokens", "codes", "http_status", "cache",
        "container",
    )

    def __init__(self, step: str, model: str | None, effort: str | None) -> None:
        self.step = _member(step, STEPS) or "other"
        self.model = model
        self.effort = _member(effort, EFFORTS, None)
        self.outcome: str | None = None
        self.tokens: dict[str, int] = {}
        self.codes: list[str] = []
        self.http_status: int | None = None
        self.cache: str | None = None
        self.container = False

    def set_model(self, model: object, effort: object = None) -> None:
        self.model = model if isinstance(model, str) else None
        if effort is not None:
            self.effort = _member(effort, EFFORTS, None)

    def set_outcome(self, outcome: str) -> None:
        self.outcome = _member(outcome, OUTCOMES, "error")

    def set_usage(self, usage: Mapping[str, Any]) -> None:
        for source, key in (
            ("input_tokens", "input_tokens"),
            ("cached_input_tokens", "cached_input_tokens"),
            ("output_tokens", "output_tokens"),
            ("reasoning_output_tokens", "reasoning_tokens"),
        ):
            count = _count(usage.get(source))
            if count is not None:
                self.tokens[key] = self.tokens.get(key, 0) + count

    def set_lean(self, success: bool, diagnostics: object) -> None:
        """Keep only the codes of error diagnostics, never their messages."""
        codes: list[str] = []
        for diagnostic in diagnostics if isinstance(diagnostics, list | tuple) else ():
            if getattr(diagnostic, "severity", None) != "error":
                continue
            code = _token(getattr(diagnostic, "code", None))
            if code is not None and code not in codes:
                codes.append(code)
        self.codes = sorted(codes)[:_MAX_CODES]
        self.outcome = classify_lean(success, self.codes)


def annotate_effort(effort: object) -> None:
    """Let the call being timed report the reasoning effort it actually sent."""
    record = _CURRENT.get()
    if record is not None:
        record.effort = _member(effort, EFFORTS, None)


def _event(
    record: StepRecord, duration_ms: float | None, run: RunRecorder | None,
    job: str | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "schema": SCHEMA,
        "event": "pipeline_step",
        "ts_ms": round(time.time() * 1000),
        "run": (run.label or run.ref) if run is not None else job,
        "step": record.step,
        "model": record.model if record.step in MODEL_STEPS else None,
        "effort": record.effort,
        "duration_ms": _ms(duration_ms),
        "outcome": record.outcome or "ok",
        "attempt": _ATTEMPT.get(),
    }
    if record.container:
        event["container"] = True
    if run is not None:
        event["start_offset_ms"] = _ms((time.monotonic() - run.started) * 1000 - (duration_ms or 0))
    for key, value in record.tokens.items():
        event[key] = value
    if record.codes:
        event["diag_codes"] = list(record.codes)
    if record.http_status is not None:
        event["http_status"] = record.http_status
    if record.cache is not None:
        event["cache"] = record.cache
    return event


@contextmanager
def step(
    name: str, *, model: str | None = None, effort: str | None = None, job: object = None,
    container: bool = False,
) -> Iterator[StepRecord | None]:
    """Time one step. Yields ``None`` when disabled, so callers guard each setter.

    An exception ends the step with outcome ``error`` unless the body already set one,
    and is re-raised unchanged.
    """
    if not enabled():
        yield None
        return
    record = StepRecord(name, model, effort)
    record.container = container
    current = _CURRENT.set(record)
    started = time.monotonic()
    try:
        yield record
    except BaseException:
        if record.outcome is None:
            record.outcome = "error"
        raise
    finally:
        _CURRENT.reset(current)
        _finish(record, (time.monotonic() - started) * 1000, job_ref(job))


def record_step(
    name: str,
    duration_ms: object,
    outcome: str = "ok",
    *,
    cache: str | None = None,
    attempt: int | None = None,
    job: object = None,
) -> None:
    """Record a step measured elsewhere (queue wait, environment cache)."""
    if not enabled():
        return
    record = StepRecord(name, None, None)
    record.set_outcome(outcome)
    record.cache = _member(cache, OUTCOMES, None)
    token = _ATTEMPT.set(attempt) if attempt is not None else None
    try:
        _finish(record, _ms(duration_ms), job_ref(job))
    finally:
        if token is not None:
            _ATTEMPT.reset(token)


def _finish(record: StepRecord, duration_ms: float | None, job: str | None = None) -> None:
    try:
        run = _RUN.get()
        event = _event(record, duration_ms, run, job)
        if run is not None:
            run.add(event)
        _write(event)
    except Exception:  # noqa: BLE001 -- instrumentation never changes the traced call.
        _count_sink_error()


# ------------------------------------------------------------------------- sinks


def _count_sink_error() -> None:
    global _sink_errors
    _sink_errors += 1


def _write(event: dict[str, Any]) -> None:
    """Write one event to every enabled sink; a failing sink loses only that event."""
    import os

    try:
        path = os.environ.get(ENV_JSONL)
        emf = os.environ.get(ENV_EMF) == "1"
        if not path and not emf:
            return
        line = json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with _sink_lock:
            if path:
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            if emf:
                emf_line = json.dumps(
                    to_emf(event), sort_keys=True, separators=(",", ":"), allow_nan=False,
                )
                # The CloudWatch agent transport of quality_events (UDP or file) when it
                # is configured; stderr otherwise, for the container log driver.
                if not _send_over_agent(emf_line):
                    sys.stderr.write(emf_line + "\n")
    except Exception:  # noqa: BLE001
        _count_sink_error()


def _send_over_agent(line: str) -> bool:
    """Use the quality_events transport where that module exists and is configured."""
    try:
        from pals_agent import quality_events
    except ImportError:
        return False
    return quality_events.send_line(line)


def to_emf(event: Mapping[str, Any]) -> dict[str, Any]:
    """The event as one EMF log line.

    Dimensions are only ``step``, ``model`` and ``outcome`` (per-step duration), or
    ``outcome`` alone (per-run totals). The dimension value is the coarse class
    (``coarse_outcome``); the exact outcome stays in the ``outcome_detail`` property.
    Token counts, the run reference and the attempt are plain properties too: they
    are queried with Logs Insights and never become metric series.
    """
    base = {k: v for k, v in event.items() if v is not None}
    timestamp = base.get("ts_ms", round(time.time() * 1000))
    if event.get("event") == "pipeline_run":
        outcome = _outcome_of_run(event)
        metrics = [
            {"Name": "run_total_ms", "Unit": "Milliseconds"},
            {"Name": "run_model_ms", "Unit": "Milliseconds"},
            {"Name": "run_lean_ms", "Unit": "Milliseconds"},
            {"Name": "run_model_calls", "Unit": "Count"},
        ]
        base.update(
            outcome=outcome, run_total_ms=event.get("total_ms") or 0,
            run_model_ms=event.get("model_ms") or 0, run_lean_ms=event.get("lean_ms") or 0,
            run_model_calls=event.get("model_calls") or 0,
        )
        base.pop("step_ms", None)  # nested object; keep it in the JSONL only
        base["step_ms_json"] = json.dumps(event.get("step_ms") or {}, sort_keys=True)
        directives = [{
            "Namespace": NAMESPACE, "Dimensions": [["outcome"]], "Metrics": metrics,
        }]
    else:
        base["model"] = model_dimension(event.get("model")) if event.get("model") else "none"
        base["outcome_detail"] = event.get("outcome")
        base["outcome"] = coarse_outcome(event.get("outcome"))
        base["step_duration_ms"] = event.get("duration_ms") or 0
        directives = [{
            "Namespace": NAMESPACE,
            "Dimensions": [["step", "model", "outcome"]],
            "Metrics": [{"Name": "step_duration_ms", "Unit": "Milliseconds"}],
        }]
    base["_aws"] = {"Timestamp": timestamp, "CloudWatchMetrics": directives}
    return base


def _outcome_of_run(event: Mapping[str, Any]) -> str:
    state = event.get("state")
    return state if state in {"verified", "failed"} else "other"
