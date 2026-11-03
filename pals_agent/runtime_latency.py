"""Bounded metadata-only timing for the existing proof-request and proof-job paths.

The SQS dispatcher supplies the original resource, claim and visibility callback.
The wrappers delegate every transport call without changing request or response.
Only bounded phase aggregates go to the injected existing operational logger.
No raw request/claim IDs, URL, headers, body, content hash, credentials, provider
ID or exception text are included. A canonical resource UUID's SHA-256 provides
opaque correlation for authorized diagnostics. Nothing is persisted here.

Three kinds of span are recorded: ``provider`` and ``api`` wrap one transport call,
``local`` names in-process work. A ``local`` stage listed in ``_CONTAINER_STAGES``
encloses other spans and never counts toward attribution. ``unattributed_ms`` is the
delivery's wall time outside every other span, so overlapping parallel reviews are
counted once.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

# One fresh proof can legitimately take 12 repair rounds of several calls each.
MAX_SPANS = 512
_ACTIVE: ContextVar[_Trace | None] = ContextVar("pals_runtime_latency_trace", default=None)
_LABEL: ContextVar[str | None] = ContextVar("pals_runtime_latency_label", default=None)
_ROLES = frozenset({
    "recipe_semantic_assessment", "token_answer_qa",
    # The ModelRole vocabulary plus model calls that only exist as trace labels.
    "openmath", "draft", "sketch", "prove", "route", "repair", "explain", "clarify",
    "proof_review", "proof_reuse_judge", "proof_reuse_judge_escalation",
    "chat_intent", "chat_explanation", "chat_explanation_qa", "draft_embedding",
    "explanation_review", "clarification_review", "semantic_review",
})
_STAGES = frozenset({
    "assessment", "context_retrieval", "explanation", "lean_compile_local",
    "lean_reconciliation_wait", "proof_pipeline", "recipe_attempt_selection",
    "recipe_batch_validate", "recipe_prompt_build", "recipe_rank",
    "recipe_response_parse", "semantic_review",
})
# These enclose transport spans and other stages; they describe, never attribute.
_CONTAINER_STAGES = frozenset({"assessment", "explanation", "proof_pipeline", "semantic_review"})
_NOTES = frozenset({"lean_verification_ms", "reconciliation_polls"})
_MAX_SERVER_MS = 3_600_000.0
_API_TIMING = re.compile(r"(?:^|,)\s*app;dur=([0-9]{1,10}(?:\.[0-9]{1,6})?)\s*(?:,|$)")
_JOB_ROUTES = {
    "worker-input": "job_read",
    "chat-input": "job_read",
    "generation-claims": "claim",
    "worker-updates": "job_update",
    "usage": "usage",
    "verification-candidates": "candidate_submit",
    "recipe-verification-candidates": "candidate_submit",
    "recipe-selection-traces": "recipe_selection_trace",
    "semantic-reviews": "semantic_settle",
    "semantic-review-unavailable": "semantic_settle",
    "explanation": "explanation_upsert",
}
_RETRIEVAL_ROUTES = {
    "/v1/internal/proof-requests/draft-candidates": "retrieval_candidates",
    "/v1/internal/proof-flow-index/candidates": "retrieval_candidates",
    "/v1/internal/typed-catalog/candidates": "retrieval_candidates",
    "/v1/internal/typed-catalog/evaluation-candidates": "retrieval_candidates",
    "/v1/internal/lean-recipe-catalog/selections": "recipe_selection",
}
_CANDIDATE_ROUTE = re.compile(r"verification-candidates/[0-9a-f-]{36}/(binding|reconciliation)")


def _request_correlation(request_id: str) -> str | None:
    # Do not turn accidental free text, another identifier, or a malformed
    # delivery into a log fingerprint. This never changes task eligibility.
    if type(request_id) is not str:
        return None
    try:
        parsed = UUID(request_id)
    except ValueError:
        return None
    if parsed.version != 4 or str(parsed) != request_id:
        return None
    return hashlib.sha256(request_id.encode("ascii")).hexdigest()


class Transport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> Any: ...


class Processor(Protocol):
    def process(
        self, request_id: str, claim_id: str, extend_visibility: Callable[[int], None]
    ) -> Any: ...


def _role() -> str:
    try:
        from pals_agent.proof_reuse_usage import explicit_role

        result = _LABEL.get() or explicit_role()
        return result if result in _ROLES else "other"
    except Exception:  # noqa: BLE001 -- instrumentation must never alter application behavior.
        return "other"


def _origin(url: str) -> tuple[str, str | None, int | None] | None:
    try:
        value = urlsplit(url)
        if (
            value.scheme not in {"http", "https"}
            or not value.hostname
            or value.username
            or value.password
        ):
            return None
        return value.scheme, value.hostname, value.port or (443 if value.scheme == "https" else 80)
    except (TypeError, ValueError):
        return None


def _phase(service: str, base_origin: Any, method: str, url: str, request_id: str) -> str:
    if base_origin is None or _origin(url) != base_origin:
        return "other_origin"
    parsed = urlsplit(url)
    path = parsed.path
    if service == "api" and not parsed.query and not parsed.fragment:
        job_prefix = "/v1/internal/proof-jobs/" + request_id + "/"
        if path.startswith(job_prefix):
            suffix = path[len(job_prefix):]
            candidate = _CANDIDATE_ROUTE.fullmatch(suffix)
            if candidate is not None:
                return "candidate_" + candidate.group(1)
            return _JOB_ROUTES.get(suffix, "api_other")
    if method != "POST" or parsed.query or parsed.fragment:
        return service + "_other"
    if service == "provider":
        return {
            "/v1/responses/input_tokens": "input_tokens",
            "/v1/responses": "generation",
            "/v1/embeddings": "generation",
        }.get(path, "provider_other")
    if path in _RETRIEVAL_ROUTES:
        return _RETRIEVAL_ROUTES[path]
    fixed = {
        "/v1/internal/billing/token-permits": "permit",
        "/v1/internal/billing/token-receipts": "receipt",
        "/v1/internal/billing/semantic-call-results": "semantic_result",
    }
    if path in fixed:
        return fixed[path]
    prefix = "/v1/internal/proof-requests/" + request_id + "/"
    return {
        prefix + "claims": "claim",
        prefix + "recipe-batch": "batch_load",
        prefix + "recipe-search": "recipe_search",
        prefix + "recipes": "recipe_lookup",
        prefix + "materials": "materials_load",
        prefix + "attachments": "attachments_load",
        prefix + "usage": "usage",
        prefix + "settlements": "settle",
    }.get(path, "api_other")


def _server_elapsed_ms(service: str, response: Any) -> float | None:
    """Time the responding server reports; only this bounded number leaves the headers."""
    for name, value in getattr(response, "headers", ()):
        lowered = name.lower()
        parsed = None
        if service == "provider" and lowered == "openai-processing-ms":
            parsed = float(value)
        elif service == "api" and lowered == "server-timing":
            match = _API_TIMING.search(value)
            parsed = float(match.group(1)) if match is not None else None
        if parsed is not None:
            return parsed if math.isfinite(parsed) and 0 <= parsed <= _MAX_SERVER_MS else None
    return None


def _union_ms(intervals: list[tuple[float, float]]) -> float:
    total = 0.0
    current_start: float | None = None
    current_end = 0.0
    for start, end in sorted(intervals):
        if current_start is None or start > current_end:
            if current_start is not None:
                total += current_end - current_start
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if current_start is not None:
        total += current_end - current_start
    return total * 1000


def queue_observation(message: Any, now_ms: float | None = None) -> dict[str, int] | None:
    """Queue delay from SQS's own attributes; clock skew makes this approximate."""
    try:
        attributes = message["Attributes"]
        sent = int(attributes["SentTimestamp"])
        observed = time.time() * 1000 if now_ms is None else now_ms
        return {
            "queue_wait_ms": max(0, round(observed - sent)),
            "receive_count": int(attributes["ApproximateReceiveCount"]),
        }
    except Exception:  # noqa: BLE001 -- missing attributes must not affect the delivery.
        return None


@dataclass
class _Trace:
    request_id: str
    kind: str = "proof_request"
    queue: dict[str, int] | None = None
    started: float = field(default_factory=lambda: time.monotonic())
    started_unix_ms: int = field(default_factory=lambda: round(time.time() * 1000))
    spans: list[dict[str, Any]] = field(default_factory=list)
    dropped: int = 0
    instrumentation_errors: int = 0
    linked_request_id: str | None = None
    notes: dict[str, int] = field(default_factory=dict)
    lock: Any = field(default_factory=threading.Lock, repr=False)

    def begin(self, phase: str, role: str, service: str = "api") -> int | None:
        with self.lock:
            if len(self.spans) >= MAX_SPANS:
                self.dropped += 1
                return None
            self.spans.append(
                {
                    "phase": phase,
                    "role": role,
                    "start": time.monotonic(),
                    "end": None,
                    "status": None,
                    "transport_failed": False,
                    "service": service,
                    "server_ms": None,
                }
            )
            return len(self.spans) - 1

    def fault(self) -> None:
        with self.lock:
            self.instrumentation_errors += 1

    def end(
        self, index: int | None, status: Any, failed: bool, server_ms: float | None = None,
    ) -> None:
        if index is None:
            return
        with self.lock:
            span = self.spans[index]
            span["end"] = time.monotonic()
            span["status"] = status if type(status) is int and 100 <= status <= 599 else None
            span["transport_failed"] = failed
            span["server_ms"] = server_ms

    def note(self, name: str, value: int) -> None:
        with self.lock:
            self.notes[name] = self.notes.get(name, 0) + value

    def summary(self, finished: float) -> dict[str, Any]:
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        with self.lock:
            spans = [dict(s) for s in self.spans]
            dropped = self.dropped
            faults = self.instrumentation_errors
            notes = dict(self.notes)
            linked = self.linked_request_id
        if (
            not math.isfinite(finished)
            or not math.isfinite(self.started)
            or finished < self.started
        ):
            raise ValueError("invalid monotonic observation")
        for span in spans:
            if not math.isfinite(span["start"]) or span["start"] < self.started:
                raise ValueError("invalid monotonic span")
            if span["end"] is not None:
                if (
                    not math.isfinite(span["end"])
                    or span["end"] < span["start"]
                    or span["end"] > finished
                ):
                    raise ValueError("invalid monotonic span")
                groups.setdefault((span["service"], span["phase"], span["role"]), []).append(span)
        phases = []
        for (service, phase, role), group in sorted(groups.items()):
            durations = [max(0.0, (s["end"] - s["start"]) * 1000) for s in group]
            server_timed = [
                (s["server_ms"], (s["end"] - s["start"]) * 1000)
                for s in group if s["server_ms"] is not None
            ]
            phases.append(
                {
                    "service": service,
                    "phase": phase,
                    "role": role,
                    "calls": len(group),
                    "elapsed_total_ms": math.fsum(durations),
                    "elapsed_max_ms": max(durations),
                    "first_start_offset_ms": max(
                        0.0, (min(s["start"] for s in group) - self.started) * 1000
                    ),
                    "last_end_offset_ms": max(
                        0.0, (max(s["end"] for s in group) - self.started) * 1000
                    ),
                    "transport_failures": sum(s["transport_failed"] for s in group),
                    "server_timed_calls": len(server_timed),
                    "server_elapsed_total_ms": math.fsum(server for server, _ in server_timed),
                    "transport_overhead_total_ms": math.fsum(
                        max(0.0, elapsed - server) for server, elapsed in server_timed
                    ),
                    "http_status_counts": [
                        {"status": key, "count": count}
                        for key, count in sorted(
                            Counter(s["status"] for s in group if s["status"] is not None).items()
                        )
                    ],
                }
            )
        finished_spans = [s for s in spans if s["end"] is not None]

        def union(*services: str) -> float:
            return _union_ms([
                (s["start"], s["end"]) for s in finished_spans
                if s["service"] in services and s["phase"] not in _CONTAINER_STAGES
            ])

        elapsed_ms = max(0.0, (finished - self.started) * 1000)
        model_union_ms = _union_ms([
            (s["start"], s["end"]) for s in finished_spans
            if s["service"] == "provider" and s["phase"] == "generation"
        ])
        return {
            "schema_version": "pals.runtime-latency-aggregates.v2",
            "trace_kind": self.kind,
            "request_correlation_sha256": _request_correlation(self.request_id),
            "linked_request_correlation_sha256": (
                _request_correlation(linked) if linked is not None else None
            ),
            "started_unix_ms": self.started_unix_ms,
            "queue": self.queue,
            "notes": notes,
            "processor_elapsed_ms": elapsed_ms,
            "model_generation_union_ms": model_union_ms,
            "non_model_ms": max(0.0, elapsed_ms - model_union_ms),
            "provider_union_ms": union("provider"),
            "api_union_ms": union("api"),
            "local_stage_union_ms": union("local"),
            "unattributed_ms": max(0.0, elapsed_ms - union("provider", "api", "local")),
            "recorded_spans": len(spans),
            "dropped_spans": dropped,
            "instrumentation_errors": faults,
            "complete_timing_capture": dropped == 0
            and faults == 0
            and all(s["end"] is not None for s in spans),
            "all_recorded_spans_finished": all(s["end"] is not None for s in spans),
            "phase_totals_can_overlap": True,
            "transport_scope": "full_delegate_call_including_helper_TLS_body_read_and_join",
            "phases": phases,
        }


@dataclass(frozen=True)
class TimedTransport:
    delegate: Transport = field(repr=False)
    service: str
    base_url: str = field(repr=False)

    def __post_init__(self) -> None:
        if self.service not in {"api", "provider"}:
            raise ValueError("timing transport classification configuration invalid")

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> Any:
        trace = _ACTIVE.get()
        if trace is None:
            return self.delegate.request(
                method=method, url=url, headers=headers, body=body, timeout_seconds=timeout_seconds
            )
        index = None
        if trace is not None:
            try:
                index = trace.begin(
                    _phase(self.service, _origin(self.base_url), method, url, trace.request_id),
                    _role(),
                    self.service,
                )
            except Exception:  # noqa: BLE001 -- failed telemetry cannot change a billable call.
                trace.fault()
        status = None
        server_ms = None
        failed = True
        try:
            response = self.delegate.request(
                method=method, url=url, headers=headers, body=body, timeout_seconds=timeout_seconds
            )
            failed = False
            try:
                status = response.status_code
                server_ms = _server_elapsed_ms(self.service, response)
            except Exception:  # noqa: BLE001 -- preserve the original response object untouched.
                if trace is not None:
                    trace.fault()
            return response
        finally:
            if trace is not None:
                try:
                    trace.end(index, status, failed, server_ms)
                except Exception:  # noqa: BLE001 -- preserve original result/exception identity.
                    trace.fault()


@contextmanager
def traced_delivery(
    kind: str,
    resource_id: str,
    *,
    emit: Callable[[dict[str, Any]], None],
    queue: dict[str, int] | None = None,
) -> Iterator[None]:
    """One SQS delivery's trace. A nested call joins the outer delivery's trace."""
    if _ACTIVE.get() is not None:
        yield
        return
    trace = _Trace(resource_id, kind=kind, queue=queue)
    token = _ACTIVE.set(trace)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
        try:
            emit(trace.summary(time.monotonic()))
        except Exception:  # noqa: BLE001, S110 -- logging failure must not cause paid-call replay.
            pass
        finally:
            trace.spans.clear()


@contextmanager
def latency_stage(name: str) -> Iterator[None]:
    """Name in-process work. Unknown names collapse so free text can't reach a log."""
    trace = _ACTIVE.get()
    if trace is None:
        yield
        return
    index = None
    try:
        index = trace.begin(name if name in _STAGES else "local_other", _role(), "local")
    except Exception:  # noqa: BLE001 -- failed telemetry cannot change the traced work.
        trace.fault()
    failed = True
    try:
        yield
        failed = False
    finally:
        try:
            trace.end(index, None, failed)
        except Exception:  # noqa: BLE001 -- preserve original result/exception identity.
            trace.fault()


@contextmanager
def latency_label(role: str) -> Iterator[None]:
    """Label model calls for tracing only; usage records keep their own model_role."""
    token = _LABEL.set(role)
    try:
        yield
    finally:
        _LABEL.reset(token)


def note_latency(name: str, value: Any) -> None:
    """Add to a fixed-name integer counter. Anything else is dropped, never raised."""
    trace = _ACTIVE.get()
    if trace is None or name not in _NOTES:
        return
    if type(value) is int and 0 <= value <= 86_400_000:
        trace.note(name, value)


def link_latency_request(request_id: Any) -> None:
    """Record the proof request behind a linked proof job, for joining the two traces."""
    trace = _ACTIVE.get()
    if trace is not None and type(request_id) is str:
        trace.linked_request_id = request_id


@dataclass(frozen=True)
class TracedProcessor:
    delegate: Processor = field(repr=False)
    emit: Callable[[dict[str, Any]], None] = field(repr=False)
    queue: dict[str, int] | None = None

    def process(
        self, request_id: str, claim_id: str, extend_visibility: Callable[[int], None]
    ) -> Any:
        # No IDs are invented or claimed here. The original process does the
        # real claim acquisition, quota, TokenMeter, settlement and acknowledgement.
        with traced_delivery("proof_request", request_id, emit=self.emit, queue=self.queue):
            return self.delegate.process(request_id, claim_id, extend_visibility)


def process_with_latency(
    delegate: Processor,
    request_id: str,
    claim_id: str,
    extend_visibility: Callable[[int], None],
    *,
    emit: Callable[[dict[str, Any]], None],
    queue: dict[str, int] | None = None,
) -> Any:
    """Thin call-site adapter; keeps the existing worker processor field/type intact."""
    return TracedProcessor(delegate, emit, queue).process(request_id, claim_id, extend_visibility)


def report_latency(report: dict[str, Any]) -> None:
    """One metadata-only JSON event on stderr; leave CLI stdout and logging levels alone."""
    event = {"event": "proof_request_latency", "metrics": report}
    sys.stderr.write(
        json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    )
