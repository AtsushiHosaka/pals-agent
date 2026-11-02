"""Bounded metadata-only timing for the existing proof-request processing path.

The SQS dispatcher supplies the original request, claim and visibility callback.
The wrappers delegate every transport call without changing request or response.
Only bounded phase aggregates go to the injected existing operational logger.
No request/claim IDs, URL, headers, body, content hash, credentials, provider ID
or exception text are included in the emitted report. Nothing is persisted here.
"""

from __future__ import annotations

import json
import math
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

MAX_SPANS = 32
_ACTIVE: ContextVar[_Trace | None] = ContextVar("pals_runtime_latency_trace", default=None)
_ROLES = {"recipe_semantic_assessment", "token_answer_qa"}


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
        from pals_agent.proof_reuse_usage import current_role

        result = current_role()
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
    if method != "POST" or parsed.query or parsed.fragment:
        return service + "_other"
    path = parsed.path
    if service == "provider":
        return {"/v1/responses/input_tokens": "input_tokens", "/v1/responses": "generation"}.get(
            path, "provider_other"
        )
    fixed = {
        "/v1/internal/billing/token-permits": "permit",
        "/v1/internal/billing/token-receipts": "receipt",
    }
    if path in fixed:
        return fixed[path]
    prefix = "/v1/internal/proof-requests/" + request_id + "/"
    return {
        prefix + "claims": "claim",
        prefix + "recipe-batch": "batch_load",
        prefix + "recipe-search": "recipe_search",
        prefix + "usage": "usage",
        prefix + "settlements": "settle",
    }.get(path, "api_other")


@dataclass
class _Trace:
    request_id: str
    started: float = field(default_factory=time.monotonic)
    spans: list[dict[str, Any]] = field(default_factory=list)
    dropped: int = 0
    instrumentation_errors: int = 0
    lock: Any = field(default_factory=threading.Lock, repr=False)

    def begin(self, phase: str, role: str) -> int | None:
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
                }
            )
            return len(self.spans) - 1

    def fault(self) -> None:
        with self.lock:
            self.instrumentation_errors += 1

    def end(self, index: int | None, status: Any, failed: bool) -> None:
        if index is None:
            return
        with self.lock:
            span = self.spans[index]
            span["end"] = time.monotonic()
            span["status"] = status if type(status) is int and 100 <= status <= 599 else None
            span["transport_failed"] = failed

    def summary(self, finished: float) -> dict[str, Any]:
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        with self.lock:
            spans = [dict(s) for s in self.spans]
            dropped = self.dropped
            faults = self.instrumentation_errors
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
                groups.setdefault((span["phase"], span["role"]), []).append(span)
        phases = []
        for (phase, role), group in sorted(groups.items()):
            durations = [max(0.0, (s["end"] - s["start"]) * 1000) for s in group]
            phases.append(
                {
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
                    "http_status_counts": [
                        {"status": key, "count": count}
                        for key, count in sorted(
                            Counter(s["status"] for s in group if s["status"] is not None).items()
                        )
                    ],
                }
            )
        return {
            "schema_version": "pals.runtime-paid-latency-aggregates.v1",
            "processor_elapsed_ms": max(0.0, (finished - self.started) * 1000),
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
                )
            except Exception:  # noqa: BLE001 -- failed telemetry cannot change a billable call.
                trace.fault()
        status = None
        failed = True
        try:
            response = self.delegate.request(
                method=method, url=url, headers=headers, body=body, timeout_seconds=timeout_seconds
            )
            failed = False
            try:
                status = response.status_code
            except Exception:  # noqa: BLE001 -- preserve the original response object untouched.
                if trace is not None:
                    trace.fault()
            return response
        finally:
            if trace is not None:
                try:
                    trace.end(index, status, failed)
                except Exception:  # noqa: BLE001 -- preserve original result/exception identity.
                    trace.fault()


@dataclass(frozen=True)
class TracedProcessor:
    delegate: Processor = field(repr=False)
    emit: Callable[[dict[str, Any]], None] = field(repr=False)

    def process(
        self, request_id: str, claim_id: str, extend_visibility: Callable[[int], None]
    ) -> Any:
        # No IDs are invented or claimed here. The original process does the
        # real claim acquisition, quota, TokenMeter, settlement and acknowledgement.
        if _ACTIVE.get() is not None:
            return self.delegate.process(request_id, claim_id, extend_visibility)
        trace = _Trace(request_id)
        token = _ACTIVE.set(trace)
        try:
            return self.delegate.process(request_id, claim_id, extend_visibility)
        finally:
            _ACTIVE.reset(token)
            try:
                self.emit(trace.summary(time.monotonic()))
            except Exception:  # noqa: BLE001, S110 -- logging failure must not cause paid-call replay.
                pass
            finally:
                trace.spans.clear()


def process_with_latency(
    delegate: Processor,
    request_id: str,
    claim_id: str,
    extend_visibility: Callable[[int], None],
    *,
    emit: Callable[[dict[str, Any]], None],
) -> Any:
    """Thin call-site adapter; keeps the existing worker processor field/type intact."""
    return TracedProcessor(delegate, emit).process(request_id, claim_id, extend_visibility)


def report_latency(report: dict[str, Any]) -> None:
    """One metadata-only JSON event on stderr; leave CLI stdout and logging levels alone."""
    event = {"event": "proof_request_latency", "metrics": report}
    sys.stderr.write(
        json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    )
