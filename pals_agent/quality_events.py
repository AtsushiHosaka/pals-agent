"""Failure-class quality events in CloudWatch Embedded Metric Format (EMF).

Every terminal proof request, every Lean attempt on the verifier and every terminal
explanation failure can become one single-line JSON event whose metrics CloudWatch
extracts. Emission is **disabled by default**: unless ``PALS_QUALITY_EVENTS_ENABLED``
is ``true`` (or ``1``), nothing is built, sent, logged or counted, so merging this
module cannot change production behaviour or log output.

Safety contract:

* Only ``ALLOWED_LOG_FIELDS`` and ``ALLOWED_DIMENSIONS`` can appear. Each has a validator.
* Closed-vocabulary fields replace an unknown short label with ``unrecognized``.
  A value that looks like prose (whitespace, control or non-ASCII characters, or
  longer than 80 characters), a secret-shaped token or an unexpected field **rejects
  the whole event**: nothing is emitted and ``QualityEventsDropped`` is counted.
* The rejection reason is a closed code and never contains the offending value.
* A request is correlated only by the SHA-256 of its canonical UUID, never the UUID.
* Emission never raises and never blocks a request: the transport is a non-blocking
  UDP datagram to the CloudWatch agent (design option T1) or an append to a file
  (option T2). A failed or rejected send is counted, not retried.

Configuration (all read at emit time; invalid or missing values disable emission):

``PALS_QUALITY_EVENTS_ENABLED``       ``true`` or ``1`` to enable.
``PALS_QUALITY_EVENTS_TRANSPORT``     ``agent`` (default) or ``file``.
``PALS_QUALITY_EVENTS_AGENT_ENDPOINT`` ``udp://host:port`` for ``agent``.
``PALS_QUALITY_EVENTS_FILE``          absolute path for ``file``.
``PALS_QUALITY_EVENTS_ENVIRONMENT``   ``Environment`` dimension; falls back to ``PALS_ENV``.
``PALS_QUALITY_EVENTS_REVISION``      optional software revision for the log field.

The failure taxonomy is ``docs/quality-ledger/taxonomy.md`` in the parent repository.
``FailureClass`` is the taxonomy tag and ``FailureCode`` the taxonomy code, verbatim.
"""

from __future__ import annotations

import json
import math
import os
import re
import socket
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final, Protocol
from urllib.parse import urlsplit

from pals_agent.runtime_latency import _request_correlation

ENABLED_ENV: Final = "PALS_QUALITY_EVENTS_ENABLED"
TRANSPORT_ENV: Final = "PALS_QUALITY_EVENTS_TRANSPORT"
AGENT_ENDPOINT_ENV: Final = "PALS_QUALITY_EVENTS_AGENT_ENDPOINT"
FILE_ENV: Final = "PALS_QUALITY_EVENTS_FILE"
ENVIRONMENT_ENV: Final = "PALS_QUALITY_EVENTS_ENVIRONMENT"
REVISION_ENV: Final = "PALS_QUALITY_EVENTS_REVISION"

NAMESPACE: Final = "PALS/ProofQuality"
UNRECOGNIZED: Final = "unrecognized"
UNCLASSIFIED: Final = "unclassified"
MAX_EVENT_BYTES: Final = 8192
# EMF only accepts timestamps within the last 14 days (and 2 hours ahead).
_MAX_PAST_MS: Final = 14 * 24 * 3600 * 1000
_MAX_FUTURE_MS: Final = 2 * 3600 * 1000

FAILURE_CLASSES: Final = frozenset({
    "infra", "verifier", "model", "review", "policy-refusal", UNCLASSIFIED,
})
ENVIRONMENTS: Final = frozenset({"prod", "staging", "dev", "local", "probe"})
ROUTES: Final = frozenset({"catalog_recipe", "semantic_reuse", "lean_generation", "chat_answer"})
EVENT_NAMES: Final = frozenset({
    "proof_request_terminal", "lean_attempt", "explanation_failure", "eval_run", "eval_failure",
    "repair_early_stop",
})
STOP_MODES: Final = frozenset({"stopped", "observed"})
STOP_RULES: Final = frozenset({"repeated_statement_mismatch"})
# The only diagnostic codes the repeated-statement-mismatch rule can match.
_STOP_CODES: Final = frozenset({"lean.formal_harness_mismatch", "lean.statement_mismatch"})
METRIC_REQUESTS_FAILED: Final = "ProofRequestsFailed"
METRIC_REQUESTS_REFUSED: Final = "ProofRequestsRefused"
METRIC_ATTEMPTS_FAILED: Final = "LeanAttemptsFailed"
METRIC_EXPLANATIONS_FAILED: Final = "ExplanationsFailed"
METRIC_REPAIR_EARLY_STOPS: Final = "RepairEarlyStops"
METRIC_REPAIR_EARLY_STOPS_OBSERVED: Final = "RepairEarlyStopsObserved"


class QualityEventRejected(ValueError):  # noqa: N818 -- a closed-code rejection, not an error class
    """The event was refused. The message is a closed code, never the offending value."""


# --------------------------------------------------------------------------- taxonomy


@dataclass(frozen=True, slots=True)
class TaxonomyEntry:
    code: str
    tag: str
    metric: str
    notify: str  # taxonomy.md "通知": immediate | rate | aggregate | none | regression


_F, _R, _A = METRIC_REQUESTS_FAILED, METRIC_REQUESTS_REFUSED, METRIC_ATTEMPTS_FAILED
# (code, tag, primary failure metric, notify). ``retrieval.*`` carries the ``model`` tag.
# The metric is where the code is primarily counted: policy refusals are never failures,
# and verifier codes that exist only per Lean compile belong to LeanAttemptsFailed.
# Emitters still pick the metric by event kind (an attempt event always increments
# LeanAttemptsFailed, a terminal request event ProofRequestsFailed or ProofRequestsRefused).
_TAXONOMY_ROWS: Final = (
    ("infra.timeout", "infra", _F, "rate"),
    ("infra.http_5xx", "infra", _F, "immediate"),
    ("infra.capacity_or_quota", "infra", _F, "immediate"),
    ("infra.network_or_dependency", "infra", _F, "rate"),
    ("infra.verifier_interrupted", "infra", _F, "immediate"),
    ("infra.cache_fallback", "infra", _F, "aggregate"),
    ("infra.result_parse_failure", "infra", _F, "aggregate"),
    ("infra.app_defect", "infra", _F, "rate"),
    ("infra.monitoring_gap", "infra", _F, "immediate"),
    ("infra.queue_auth_unavailable", "infra", _F, "immediate"),
    ("infra.deploy_subprocess_failed", "infra", _F, "immediate"),
    ("verifier.trusted_audit_failed", "verifier", _A, "immediate"),
    ("verifier.runtime_unavailable", "verifier", _F, "immediate"),
    ("verifier.lean_compile_error", "verifier", _A, "aggregate"),
    ("verifier.statement_mismatch", "verifier", _A, "aggregate"),
    ("verifier.formal_harness_mismatch", "verifier", _A, "aggregate"),
    ("verifier.theorem_alignment_failed", "verifier", _A, "rate"),
    ("verifier.heartbeat_limit", "verifier", _A, "aggregate"),
    ("verifier.statement_format_error", "verifier", _A, "aggregate"),
    ("verifier.exact_not_closed", "verifier", _A, "none"),
    ("model.could_not_prove", "model", _F, "aggregate"),
    ("model.invalid_response", "model", _F, "rate"),
    ("model.selection_invalid", "model", _F, "rate"),
    ("model.preflight_misjudgment", "model", _F, "aggregate"),
    ("model.structuring_fidelity_error", "model", _F, "aggregate"),
    ("retrieval.index_miss", "model", _F, "aggregate"),
    ("retrieval.unmatched_recipe", "model", _F, "aggregate"),
    ("review.rejected", "review", _F, "aggregate"),
    ("review.false_accept", "review", _F, "regression"),
    ("review.unavailable", "review", _F, "rate"),
    ("policy.guest_formal_unavailable", "policy-refusal", _R, "none"),
    ("policy.unsupported_request", "policy-refusal", _R, "aggregate"),
)
TAXONOMY: Final[Mapping[str, TaxonomyEntry]] = {
    code: TaxonomyEntry(code, tag, metric, notify) for code, tag, metric, notify in _TAXONOMY_ROWS
} | {UNCLASSIFIED: TaxonomyEntry(UNCLASSIFIED, UNCLASSIFIED, _F, "aggregate")}


def taxonomy_entry(code: str | None) -> TaxonomyEntry:
    """The entry for a taxonomy code; anything else is ``unclassified`` (PQO-001)."""
    if isinstance(code, str) and code in TAXONOMY:
        return TAXONOMY[code]
    return TAXONOMY[UNCLASSIFIED]


# Request-level ``proof_requests.error_code`` -> taxonomy code. A code absent here is
# ``unclassified`` and is never silently filed under another class.
REQUEST_ERROR_TAXONOMY: Final[Mapping[str, str]] = {
    "proof_request_delivery_exhausted": "infra.app_defect",
    "proof_reuse_provider_unavailable": "infra.network_or_dependency",
    "proof_reuse_recipe_unavailable": "infra.network_or_dependency",
    "material_context_unavailable": "infra.network_or_dependency",
    "proof_reuse_catalog_invalid": "infra.app_defect",
    "proof_reuse_token_accounting_failed": "infra.app_defect",
    "token_usage_unknown": "infra.app_defect",
    "proof_reuse_deadline": "infra.timeout",
    "lean_flow_unavailable": "verifier.runtime_unavailable",
    "lean_verification_failed": "model.could_not_prove",
    "proof_reuse_invalid_response": "model.invalid_response",
    "proof_reuse_invalid_instantiation": "model.invalid_response",
    "proof_reuse_invalid_source": "model.invalid_response",
    "proof_reuse_recipe_invalid": "model.invalid_response",
    "material_citation_invalid": "model.invalid_response",
    "material_citation_missing": "model.invalid_response",
    "proof_reuse_answer_review_failed": "review.rejected",
    "lean_explanation_failed": "review.rejected",
    "proof_reuse_unsupported": "policy.unsupported_request",
    "lean_verification_required": "policy.unsupported_request",
    "token_budget_exceeded": "policy.unsupported_request",
    "material_context_invalid": "policy.unsupported_request",
    "material_context_too_large": "policy.unsupported_request",
    "material_proposition_invalid": "policy.unsupported_request",
    "material_proposition_unconfirmed": "policy.unsupported_request",
    # Deliberately unmapped (no taxonomy home yet, so ``unclassified``):
    # proof_reuse_input_invalid, proof_reuse_query_invalid.
}
_KNOWN_REQUEST_ERRORS: Final = REQUEST_ERROR_TAXONOMY.keys() | {
    "proof_reuse_input_invalid", "proof_reuse_query_invalid",
}

_LEAN_COMPILE_CODES: Final = frozenset({
    "lean.compile_error", "lean.unsolved_goals", "lean.type_mismatch", "lean.tactic_failed",
    "lean.syntax_error", "lean.unknown_identifier", "lean.declaration_uses_sorry",
    "lean.output_limit", "lean.already_declared", "lean.no_goals", "lean.not_found",
    "lean.undeclared_theorem", "lean.failed", "lean.disallowed_metaprogramming",
    "lean.disallowed_attribute", "lean.disallowed_trusted_declaration",
    "lean.disallowed_syntax_quotation", "lean.disallowed_placeholder", "lean.disallowed_option",
    "lean.disallowed_native_evaluation", "lean.disallowed_interactive_command",
    "lean.disallowed_axiom", "lean.disallowed_ambiguous_lexing",
    "pals.target_declaration_invalid",
    # A profile's statement-origin check rejected a constant from an unreviewed library: a verdict
    # about the proof text, like the other `lean.disallowed_*` rejections.
    "lean.statement_uses_untrusted_library",
})
# Advisory diagnostics a *verified* result may carry (library trust level, a Frontier definition
# that resembles a reviewed one). They are never the reason an attempt failed, so they have no
# failure taxonomy code; listing them here keeps the "every package code is classified" scan honest.
LEAN_ADVISORY_CODES: Final = frozenset({
    "lean.library_trust", "lean.frontier_duplicate_definition",
})
# Lean diagnostic codes in precedence order: infrastructure first, then trust, then verdicts.
_LEAN_PRECEDENCE: Final[tuple[tuple[frozenset[str], str], ...]] = (
    (frozenset({"lean.compile_interrupted", "lean.compile_deadline_interrupted"}),
     "infra.verifier_interrupted"),
    (frozenset({"lean.timeout", "lean.verifier_timeout"}), "infra.timeout"),
    (frozenset({"lean.sandbox_setup_failed", "lean.project_not_found", "lean.prlimit_not_found"}),
     "verifier.runtime_unavailable"),
    (frozenset({"lean.trusted_audit_failed"}), "verifier.trusted_audit_failed"),
    (frozenset({"lean.statement_mismatch"}), "verifier.statement_mismatch"),
    (frozenset({"lean.formal_harness_mismatch"}), "verifier.formal_harness_mismatch"),
    (frozenset({"pals.theorem_alignment_failed"}), "verifier.theorem_alignment_failed"),
    (_LEAN_COMPILE_CODES, "verifier.lean_compile_error"),
)
_KNOWN_LEAN_CODES: Final = frozenset().union(*(codes for codes, _ in _LEAN_PRECEDENCE)) | {
    "lean.verified",
} | LEAN_ADVISORY_CODES
# Closed raw vocabulary for the ``raw_code`` log field (anything else becomes unrecognized).
_RAW_CODES: Final = frozenset(_KNOWN_REQUEST_ERRORS | _KNOWN_LEAN_CODES) | {
    "verifier_internal_error",
}


def classify_request_error(error_code: object) -> str:
    """Taxonomy code for a terminal request ``error_code``."""
    if isinstance(error_code, str):
        return REQUEST_ERROR_TAXONOMY.get(error_code, UNCLASSIFIED)
    return UNCLASSIFIED


def classify_lean_codes(codes: Sequence[object]) -> str:
    """Taxonomy code for one failed Lean attempt from its closed diagnostic codes."""
    present = {code for code in codes if isinstance(code, str)}
    for vocabulary, taxonomy_code in _LEAN_PRECEDENCE:
        if present & vocabulary:
            return taxonomy_code
    return UNCLASSIFIED


_PROVIDER_PAIR = re.compile(r"^[a-z][a-z_]{0,30}=[A-Za-z0-9_.]{1,40}$")
_REASON_TOKEN = re.compile(r"^[a-z][a-z0-9_]{0,40}(?:=[A-Za-z0-9_.]{1,40})?$")
_EXCEPTION_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_REASON_KINDS: Final = frozenset({"deadline", "review", "validation", "provider", "exception"})
_MODEL_OUTPUT_STAGES: Final = frozenset({
    "json", "model", "structured_status", "output", "content", "empty_text",
})


@dataclass(frozen=True, slots=True)
class ExplanationReason:
    kind: str
    taxonomy_code: str
    labels: tuple[str, ...]
    exception_type: str | None


def classify_explanation_reason(reason: object) -> ExplanationReason:
    """Parse the fixed-label ``reason=`` token from the explanation failure log line.

    The token is ``deadline``, ``review:<categories>``, ``validation:<checks>``,
    ``provider:<key=value,...>`` or ``exception:<TypeName>``. Free text is never
    carried: anything that does not parse becomes ``unclassified``.
    """
    unknown = ExplanationReason(UNRECOGNIZED, UNCLASSIFIED, (), None)
    if not isinstance(reason, str) or len(reason) > 400:
        return unknown
    if reason == "deadline":
        return ExplanationReason("deadline", "infra.timeout", (), None)
    kind, separator, rest = reason.partition(":")
    if kind not in _REASON_KINDS or kind == "deadline" or not separator:
        return unknown
    if kind == "exception":
        valid = _EXCEPTION_TYPE.fullmatch(rest) is not None
        return ExplanationReason(
            kind, UNCLASSIFIED, (), rest if valid else None,
        )
    labels = tuple(item for item in rest.split(",") if item) if rest else ()
    if len(labels) > 12 or not all(_REASON_TOKEN.fullmatch(item) for item in labels):
        return ExplanationReason(kind, UNCLASSIFIED, (), None)
    if kind == "review":
        code = "review.rejected" if "rejected" in labels else "review.unavailable"
        return ExplanationReason(kind, code, labels, None)
    if kind == "validation":
        return ExplanationReason(kind, "model.invalid_response", labels, None)
    return ExplanationReason(kind, _classify_provider(labels), labels, None)


def _classify_provider(labels: tuple[str, ...]) -> str:
    pairs = dict(item.split("=", 1) for item in labels if _PROVIDER_PAIR.fullmatch(item))
    stage = pairs.get("stage")
    status = int(pairs["http_status"]) if pairs.get("http_status", "").isdigit() else None
    if stage == "transport":
        if pairs.get("transport_kind") == "deadline":
            return "infra.timeout"
        return "infra.network_or_dependency"
    if stage == "http":
        if status == 429 or pairs.get("provider_code") in {
            "insufficient_quota", "rate_limit_exceeded",
        }:
            return "infra.capacity_or_quota"
        if status is not None and status >= 500:
            return "infra.http_5xx"
        return "infra.app_defect"
    if stage == "configuration":
        return "infra.app_defect"
    if stage in _MODEL_OUTPUT_STAGES:
        return "model.invalid_response"
    return UNCLASSIFIED


# --------------------------------------------------------------------------- allow-list

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_LEDGER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_SHAPES: Final = tuple(re.compile(pattern) for pattern in (
    r"sk-[A-Za-z0-9_-]{8,}", r"AKIA[0-9A-Z]{12,}", r"ASIA[0-9A-Z]{12,}", r"eyJ[A-Za-z0-9_-]{10,}",
    r"(?i)bearer", r"gh[pousr]_[A-Za-z0-9]{10,}", r"github_pat_", r"-----BEGIN",
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
))


def _reject(code: str) -> QualityEventRejected:
    return QualityEventRejected(code)


def _prose_like(value: str) -> bool:
    return (
        len(value) > 80
        or not value.isascii()
        or any(character.isspace() or not character.isprintable() for character in value)
    )


def _scan_secret_shapes(name: str, value: str) -> None:
    if any(shape.search(value) for shape in _SECRET_SHAPES):
        raise _reject(f"{name}_secret_shaped")


def _vocabulary(name: str, allowed: frozenset[str]) -> Callable[[object], str]:
    def check(value: object) -> str:
        if not isinstance(value, str):
            raise _reject(f"{name}_not_string")
        if _prose_like(value):
            raise _reject(f"{name}_prose_like")
        _scan_secret_shapes(name, value)
        return value if value in allowed else UNRECOGNIZED
    return check


def _pattern(name: str, shape: re.Pattern[str]) -> Callable[[object], str]:
    def check(value: object) -> str:
        if not isinstance(value, str) or shape.fullmatch(value) is None:
            raise _reject(f"{name}_invalid")
        _scan_secret_shapes(name, value)
        return value
    return check


def _count(name: str, maximum: int) -> Callable[[object], int]:
    def check(value: object) -> int:
        if type(value) is not int or not 0 <= value <= maximum:
            raise _reject(f"{name}_invalid")
        return value
    return check


def _number(name: str, maximum: float) -> Callable[[object], float]:
    def check(value: object) -> float:
        if (
            isinstance(value, bool) or not isinstance(value, int | float)
            or not math.isfinite(value) or not 0 <= value <= maximum
        ):
            raise _reject(f"{name}_invalid")
        return float(value)
    return check


def _reason_labels(value: object) -> str:
    if not isinstance(value, str) or len(value) > 400:
        raise _reject("reason_labels_invalid")
    for token in value.split(","):
        if _REASON_TOKEN.fullmatch(token) is None:
            raise _reject("reason_labels_invalid")
        _scan_secret_shapes("reason_labels", token)
    return value


def _stop_codes(value: object) -> str:
    """Comma-separated, sorted subset of the two rule codes; anything else rejects the event."""
    if not isinstance(value, str) or len(value) > 80:
        raise _reject("stop_codes_invalid")
    tokens = value.split(",")
    if not all(token in _STOP_CODES for token in tokens) or tokens != sorted(set(tokens)):
        raise _reject("stop_codes_invalid")
    return value


_LOG_FIELDS: Final[Mapping[str, Callable[[object], Any]]] = {
    "event": _vocabulary("event", EVENT_NAMES),
    "request_hash": _pattern("request_hash", _SHA256),
    "revision": _pattern("revision", _IDENTIFIER),
    "route": _vocabulary("route", ROUTES),
    "model_config": _pattern("model_config", _IDENTIFIER),
    "failure_class": _vocabulary("failure_class", FAILURE_CLASSES),
    "failure_code": _vocabulary("failure_code", frozenset(TAXONOMY)),
    "raw_code": _vocabulary("raw_code", _RAW_CODES),
    "diagnostic_code": _vocabulary("diagnostic_code", _KNOWN_LEAN_CODES),
    "status": _vocabulary("status", frozenset({"answered", "needs_input", "failed"})),
    "outcome": _vocabulary("outcome", frozenset({"success", "failure"})),
    "resource": _vocabulary("resource", frozenset({"explanation", "clarification"})),
    "reason_kind": _vocabulary("reason_kind", _REASON_KINDS),
    "reason_labels": _reason_labels,
    "exception_type": _pattern("exception_type", _EXCEPTION_TYPE),
    "attempts": _count("attempts", 1000),
    "repairs_used": _count("repairs_used", 1000),
    "repairs_remaining": _count("repairs_remaining", 1000),
    "stop_rule": _vocabulary("stop_rule", STOP_RULES),
    "stop_mode": _vocabulary("stop_mode", STOP_MODES),
    "stop_codes": _stop_codes,
    "window": _count("window", 8),
    "duration_ms": _number("duration_ms", 86_400_000),
    "suite": _pattern("suite", _IDENTIFIER),
    "ledger_id": _pattern("ledger_id", _LEDGER_ID),
    "cases": _count("cases", 1_000_000),
    "succeeded": _count("succeeded", 1_000_000),
    "cost_usd": _number("cost_usd", 1_000_000),
}
_DIMENSIONS: Final[Mapping[str, Callable[[object], str]]] = {
    "Environment": _vocabulary("environment", ENVIRONMENTS),
    "Route": _vocabulary("route", ROUTES),
    "FailureClass": _vocabulary("failure_class", FAILURE_CLASSES),
    "FailureCode": _vocabulary("failure_code", frozenset(TAXONOMY)),
    "Suite": _pattern("suite", _IDENTIFIER),
    "ModelConfig": _pattern("model_config", _IDENTIFIER),
}
# PQO-005: the only dimensions an event may use.
ALLOWED_DIMENSIONS: Final = frozenset(_DIMENSIONS)
ALLOWED_LOG_FIELDS: Final = frozenset(_LOG_FIELDS)
_UNITS: Final[Mapping[str, str]] = {
    "ProofRequestsSettled": "Count", "ProofRequestsSucceeded": "Count",
    METRIC_REQUESTS_FAILED: "Count", METRIC_REQUESTS_REFUSED: "Count",
    "LeanAttempts": "Count", METRIC_ATTEMPTS_FAILED: "Count",
    "LeanVerifyDurationMs": "Milliseconds", "WorkerHeartbeat": "Count",
    "QualityEventsDropped": "Count", METRIC_EXPLANATIONS_FAILED: "Count",
    "EvalSuccessRate": "Percent", "EvalCases": "Count", "EvalFailed": "Count",
    METRIC_REPAIR_EARLY_STOPS: "Count", METRIC_REPAIR_EARLY_STOPS_OBSERVED: "Count",
}
ALLOWED_METRICS: Final = frozenset(_UNITS)

# --------------------------------------------------------------------------- building

DimensionSet = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityEvent:
    """One validated EMF record. Only ``validate_and_build`` constructs it."""

    line: str
    emf: Mapping[str, Any]


def validate_and_build(
    *,
    dimensions: Mapping[str, object],
    groups: Sequence[tuple[Sequence[DimensionSet], Mapping[str, float]]],
    fields: Mapping[str, object],
    timestamp_ms: int,
    now_ms: int | None = None,
) -> QualityEvent:
    """Validate every part against the allow-list and return the one-line EMF record.

    Raises ``QualityEventRejected`` (closed code only) on anything unexpected.
    """
    current_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if not current_ms - _MAX_PAST_MS <= timestamp_ms <= current_ms + _MAX_FUTURE_MS:
        raise _reject("timestamp_out_of_range")
    record: dict[str, Any] = {}
    for name, value in fields.items():
        validator = _LOG_FIELDS.get(name)
        if validator is None:
            raise _reject("field_not_allowed")
        record[name] = validator(value)
    for name, value in dimensions.items():
        dimension_validator = _DIMENSIONS.get(name)
        if dimension_validator is None:
            raise _reject("dimension_not_allowed")
        if name in record:
            raise _reject("field_duplicated")
        record[name] = dimension_validator(value)
    directives: list[dict[str, Any]] = []
    for dimension_sets, metrics in groups:
        if not metrics:
            continue
        for dimension_set in dimension_sets:
            if not set(dimension_set) <= record.keys() & ALLOWED_DIMENSIONS or not dimension_set:
                raise _reject("dimension_missing")
        directive_metrics = []
        for metric, value in metrics.items():
            if metric not in _UNITS:
                raise _reject("metric_not_allowed")
            if metric in record:
                raise _reject("field_duplicated")
            if (
                isinstance(value, bool) or not isinstance(value, int | float)
                or not math.isfinite(value) or value < 0
            ):
                raise _reject("metric_value_invalid")
            record[metric] = value
            directive_metrics.append({"Name": metric, "Unit": _UNITS[metric]})
        directives.append({
            "Namespace": NAMESPACE,
            "Dimensions": [list(dimension_set) for dimension_set in dimension_sets],
            "Metrics": directive_metrics,
        })
    if not directives:
        raise _reject("no_metrics")
    emf = {"_aws": {"Timestamp": timestamp_ms, "CloudWatchMetrics": directives}, **record}
    line = json.dumps(emf, separators=(",", ":"), sort_keys=True, allow_nan=False)
    if len(line.encode("utf-8")) > MAX_EVENT_BYTES:
        raise _reject("event_too_large")
    return QualityEvent(line, emf)


def _now_ms() -> int:
    return int(time.time() * 1000)


def build_proof_request_terminal(
    *,
    environment: str,
    status: str,
    error_code: object = None,
    route: str | None = None,
    request_id: object = None,
    duration_ms: float | None = None,
    revision: str | None = None,
    timestamp_ms: int | None = None,
) -> QualityEvent | None:
    """Terminal request event. ``verifying`` is a handoff, not a terminal state: ``None``.

    ``needs_input`` counts as settled only; a ``policy-refusal`` code counts as
    refused only, so neither enters the success-rate denominator (PQO-006).
    """
    if status == "verifying":
        return None
    if status not in {"answered", "needs_input", "failed"}:
        raise _reject("status_invalid")
    fields: dict[str, object] = {"event": "proof_request_terminal", "status": status}
    dimensions: dict[str, object] = {"Environment": environment}
    request_hash = _request_correlation(request_id) if isinstance(request_id, str) else None
    if request_hash is not None:
        fields["request_hash"] = request_hash
    if route is not None:
        fields["route"] = route
    if duration_ms is not None:
        fields["duration_ms"] = max(0.0, float(duration_ms))
    if revision is not None:
        fields["revision"] = revision
    base_sets: list[DimensionSet] = [("Environment",)]
    if route is not None:
        dimensions["Route"] = route
        base_sets.append(("Environment", "Route"))
    groups: list[tuple[Sequence[DimensionSet], Mapping[str, float]]] = []
    settled: dict[str, float] = {"ProofRequestsSettled": 1}
    if status == "answered":
        settled["ProofRequestsSucceeded"] = 1
    groups.append((base_sets, settled))
    if status == "failed":
        entry = taxonomy_entry(classify_request_error(error_code))
        fields["failure_class"] = entry.tag
        fields["failure_code"] = entry.code
        if isinstance(error_code, str):
            fields["raw_code"] = error_code
        dimensions["FailureClass"] = entry.tag
        dimensions["FailureCode"] = entry.code
        if entry.tag == "policy-refusal":
            groups.append(([("Environment", "FailureCode")], {METRIC_REQUESTS_REFUSED: 1}))
        else:
            groups.append((
                [("Environment", "FailureClass"), ("Environment", "FailureCode")],
                {METRIC_REQUESTS_FAILED: 1},
            ))
    return validate_and_build(
        dimensions=dimensions, groups=groups, fields=fields,
        timestamp_ms=_now_ms() if timestamp_ms is None else timestamp_ms,
    )


def build_lean_attempt(
    *,
    environment: str,
    diagnostic_codes: Sequence[object],
    success: bool,
    duration_ms: float,
    raw_code: str | None = None,
    revision: str | None = None,
    timestamp_ms: int | None = None,
) -> QualityEvent:
    """One compile attempt on the verifier. Never carries source, messages or paths."""
    fields: dict[str, object] = {
        "event": "lean_attempt",
        "outcome": "success" if success else "failure",
        "duration_ms": max(0.0, float(duration_ms)),
    }
    dimensions: dict[str, object] = {"Environment": environment}
    if revision is not None:
        fields["revision"] = revision
    known = [code for code in diagnostic_codes if isinstance(code, str)]
    if known:
        fields["diagnostic_code"] = known[0]
    groups: list[tuple[Sequence[DimensionSet], Mapping[str, float]]] = [
        ([("Environment",)], {"LeanAttempts": 1, "LeanVerifyDurationMs": max(0.0, duration_ms)}),
    ]
    if not success:
        entry = taxonomy_entry(classify_lean_codes(diagnostic_codes))
        fields["failure_class"] = entry.tag
        fields["failure_code"] = entry.code
        if raw_code is not None:
            fields["raw_code"] = raw_code
        dimensions["FailureClass"] = entry.tag
        groups.append(([("Environment", "FailureClass")], {METRIC_ATTEMPTS_FAILED: 1}))
    return validate_and_build(
        dimensions=dimensions, groups=groups, fields=fields,
        timestamp_ms=_now_ms() if timestamp_ms is None else timestamp_ms,
    )


def build_explanation_failure(
    *,
    environment: str,
    resource: str,
    reason: object,
    revision: str | None = None,
    timestamp_ms: int | None = None,
) -> QualityEvent:
    """A terminal explanation or clarification failure from its fixed-label ``reason``."""
    if isinstance(reason, str) and (not reason.isascii() or not reason.isprintable()
                                    or any(character.isspace() for character in reason)):
        raise _reject("reason_prose_like")  # a fixed-label token never holds whitespace
    parsed = classify_explanation_reason(reason)
    entry = taxonomy_entry(parsed.taxonomy_code)
    fields: dict[str, object] = {
        "event": "explanation_failure",
        "resource": resource,
        "reason_kind": parsed.kind,
        "failure_class": entry.tag,
        "failure_code": entry.code,
    }
    if parsed.labels:
        fields["reason_labels"] = ",".join(parsed.labels)
    if parsed.exception_type is not None:
        fields["exception_type"] = parsed.exception_type
    if revision is not None:
        fields["revision"] = revision
    return validate_and_build(
        dimensions={"Environment": environment, "FailureClass": entry.tag},
        groups=[([("Environment", "FailureClass")], {METRIC_EXPLANATIONS_FAILED: 1})],
        fields=fields,
        timestamp_ms=_now_ms() if timestamp_ms is None else timestamp_ms,
    )


def build_repair_early_stop(
    *,
    environment: str,
    mode: str,
    codes: Sequence[str],
    window: int,
    attempts: int,
    repairs_used: int,
    repairs_remaining: int,
    request_id: object = None,
    revision: str | None = None,
    timestamp_ms: int | None = None,
) -> QualityEvent:
    """A repeated-statement-mismatch stop (``stopped``) or a would-be stop (``observed``).

    Carries closed codes and counts only, never a statement, a question or Lean text.
    ``request_hash`` joins the event to the job's final outcome, which is how a stop that
    would have been wrong (the job still verified in observe mode) is counted afterwards.
    """
    if mode not in STOP_MODES:
        raise _reject("stop_mode_invalid")
    fields: dict[str, object] = {
        "event": "repair_early_stop",
        "stop_rule": "repeated_statement_mismatch",
        "stop_mode": mode,
        "stop_codes": ",".join(sorted(set(codes))),
        "window": window,
        "attempts": attempts,
        "repairs_used": repairs_used,
        "repairs_remaining": repairs_remaining,
    }
    request_hash = _request_correlation(request_id) if isinstance(request_id, str) else None
    if request_hash is not None:
        fields["request_hash"] = request_hash
    if revision is not None:
        fields["revision"] = revision
    return validate_and_build(
        dimensions={"Environment": environment},
        groups=[([("Environment",)], {
            METRIC_REPAIR_EARLY_STOPS if mode == "stopped"
            else METRIC_REPAIR_EARLY_STOPS_OBSERVED: 1,
        })],
        fields=fields,
        timestamp_ms=_now_ms() if timestamp_ms is None else timestamp_ms,
    )


def build_eval_run(
    *,
    suite: str,
    model_config: str,
    cases: int,
    succeeded: int,
    failures: Mapping[str, int] | None = None,
    duration_s: float | None = None,
    cost_usd: float | None = None,
    revision: str | None = None,
    ledger_id: str | None = None,
    timestamp_ms: int | None = None,
) -> list[QualityEvent]:
    """One ``eval_run`` record plus one ``eval_failure`` record per failed taxonomy class.

    EMF cannot put several values of one metric under different dimension values in a
    single record, so the per-class ``EvalFailed`` counts need their own records; all of
    them carry the same ``ledger_id`` so a point can be traced back to the ledger row.
    Failure keys are taxonomy codes (unknown codes count as ``unclassified``).
    """
    if cases <= 0 or not 0 <= succeeded <= cases:
        raise _reject("counts_invalid")
    stamp = _now_ms() if timestamp_ms is None else timestamp_ms
    dimensions: dict[str, object] = {"Suite": suite, "ModelConfig": model_config}
    fields: dict[str, object] = {"event": "eval_run", "cases": cases, "succeeded": succeeded}
    if ledger_id is not None:
        fields["ledger_id"] = ledger_id
    if revision is not None:
        fields["revision"] = revision
    if duration_s is not None:
        fields["duration_ms"] = max(0.0, float(duration_s)) * 1000
    if cost_usd is not None:
        fields["cost_usd"] = cost_usd
    events = [validate_and_build(
        dimensions=dimensions,
        groups=[([("Suite", "ModelConfig")], {
            "EvalSuccessRate": 100.0 * succeeded / cases, "EvalCases": cases,
        })],
        fields=fields,
        timestamp_ms=stamp,
    )]
    by_class: dict[str, int] = {}
    for code, count in (failures or {}).items():
        if type(count) is not int or count < 0:
            raise _reject("counts_invalid")
        tag = taxonomy_entry(code).tag
        by_class[tag] = by_class.get(tag, 0) + count
    for tag, count in sorted(by_class.items()):
        if count == 0:
            continue
        failure_fields: dict[str, object] = {
            "event": "eval_failure", "failure_class": tag, "cases": cases,
        }
        if ledger_id is not None:
            failure_fields["ledger_id"] = ledger_id
        events.append(validate_and_build(
            dimensions={"Suite": suite, "FailureClass": tag},
            groups=[([("Suite", "FailureClass")], {"EvalFailed": count})],
            fields=failure_fields,
            timestamp_ms=stamp,
        ))
    return events


# --------------------------------------------------------------------------- transport


class Transport(Protocol):
    def send(self, line: str) -> None: ...


class AgentUdpTransport:
    """Fire-and-forget datagram to the CloudWatch agent's EMF endpoint (design T1)."""

    def __init__(self, host: str, port: int) -> None:
        self._address = (host, port)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setblocking(False)

    def send(self, line: str) -> None:
        self._socket.sendto((line + "\n").encode("utf-8"), self._address)


class FileTransport:
    """Append one line per event; rotation belongs to the file's consumer (design T2)."""

    def __init__(self, path: str) -> None:
        self._path = path

    def send(self, line: str) -> None:
        descriptor = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
        try:
            os.write(descriptor, (line + "\n").encode("utf-8"))
        finally:
            os.close(descriptor)


@dataclass(frozen=True, slots=True)
class _Config:
    environment: str | None
    revision: str | None
    key: tuple[str, str] | None  # (transport, target); None when no destination is configured


_LOCK = threading.Lock()
_DROPPED = 0
_OVERRIDE: Transport | None = None
_TRANSPORTS: dict[tuple[str, str], Transport] = {}


def enabled() -> bool:
    """True only when ``PALS_QUALITY_EVENTS_ENABLED`` is ``true`` or ``1``."""
    return os.environ.get(ENABLED_ENV, "").strip().lower() in {"1", "true"}


def _config(*, needs_environment: bool) -> _Config | None:
    value = (os.environ.get(ENVIRONMENT_ENV) or os.environ.get("PALS_ENV") or "").strip()
    environment = value if value in ENVIRONMENTS else None
    if environment is None and needs_environment:
        return None
    revision = os.environ.get(REVISION_ENV, "").strip() or None
    if revision is not None and _IDENTIFIER.fullmatch(revision) is None:
        revision = None
    kind = os.environ.get(TRANSPORT_ENV, "agent").strip().lower() or "agent"
    key: tuple[str, str] | None = None
    if kind == "file":
        path = os.environ.get(FILE_ENV, "").strip()
        key = ("file", path) if os.path.isabs(path) else None
    elif kind == "agent":
        endpoint = os.environ.get(AGENT_ENDPOINT_ENV, "").strip()
        key = ("agent", endpoint) if endpoint else None
    return _Config(environment, revision, key)


def _make_transport(key: tuple[str, str]) -> Transport | None:
    kind, target = key
    if kind == "file":
        return FileTransport(target)
    try:
        parsed = urlsplit(target)
        if parsed.scheme != "udp" or not parsed.hostname or parsed.port is None:
            return None
        host = socket.gethostbyname(parsed.hostname)
    except (ValueError, OSError):
        return None
    return AgentUdpTransport(host, parsed.port)


def _transport(config: _Config) -> Transport | None:
    if _OVERRIDE is not None:
        return _OVERRIDE
    if config.key is None:
        return None
    with _LOCK:
        if config.key not in _TRANSPORTS:
            made = _make_transport(config.key)
            if made is None:
                return None
            _TRANSPORTS[config.key] = made
        return _TRANSPORTS[config.key]


def dropped_count() -> int:
    """Events refused or lost since the last one that carried ``QualityEventsDropped``."""
    return _DROPPED


@contextmanager
def use_transport(transport: Transport | None) -> Iterator[None]:
    """Replace the transport (tests). Enablement and environment still come from env."""
    global _OVERRIDE
    previous = _OVERRIDE
    _OVERRIDE = transport
    try:
        yield
    finally:
        _OVERRIDE = previous


def reset_for_tests() -> None:
    global _DROPPED
    with _LOCK:
        _DROPPED = 0
        _TRANSPORTS.clear()


def _count_drop() -> None:
    global _DROPPED
    with _LOCK:
        _DROPPED += 1


def emit(
    builder: Callable[[_Config], Sequence[QualityEvent | None]], *, needs_environment: bool = True,
) -> bool:
    """Build and send events; never raises and does nothing while disabled.

    ``builder`` runs only when enabled, so disabled processes do no work at all.
    Returns True when every event was sent. A rejection or send failure increments the
    drop counter; the next event that is sent carries it as ``QualityEventsDropped``.
    """
    if not enabled():
        return False
    try:
        config = _config(needs_environment=needs_environment)
        if config is None:
            return False
        transport = _transport(config)
        if transport is None:
            if config.key is not None:  # configured but unusable; unconfigured stays silent
                _count_drop()
            return False
        events = [event for event in builder(config) if event is not None]
        for event in events:
            line, carried = _with_dropped(event, config)
            try:
                transport.send(line)
            except Exception:
                _restore_dropped(carried)  # the count was not delivered; keep it
                raise
    except Exception:  # noqa: BLE001 -- observability must never alter application behavior.
        _count_drop()
        return False
    return True


def send_line(line: str) -> bool:
    """Send one already-built EMF line over the configured transport, if there is one.

    For other modules that own their schema (``step_timing``). Unlike ``emit`` this has
    no ``PALS_QUALITY_EVENTS_ENABLED`` gate and counts no drop: the caller owns its flag
    and falls back to another sink on False. It never raises.
    """
    try:
        config = _config(needs_environment=False)
        transport = _transport(config) if config is not None else None
        if transport is None:
            return False
        transport.send(line)
        return True
    except Exception:  # noqa: BLE001 -- observability must never alter application behavior.
        return False


def _restore_dropped(count: int) -> None:
    global _DROPPED
    with _LOCK:
        _DROPPED += count


def _with_dropped(event: QualityEvent, config: _Config) -> tuple[str, int]:
    """Attach the pending drop count to an outgoing event; returns (line, carried count)."""
    global _DROPPED
    with _LOCK:
        pending, _DROPPED = _DROPPED, 0
    if not pending:
        return event.line, 0
    try:
        environment = event.emf.get("Environment", config.environment)
        if environment is None:  # e.g. an eval run outside a deployment: keep the count
            raise _reject("environment_missing")
        record = dict(event.emf)
        aws = dict(record["_aws"])
        record["QualityEventsDropped"] = pending
        record["Environment"] = environment
        aws["CloudWatchMetrics"] = [
            *aws["CloudWatchMetrics"],
            {
                "Namespace": NAMESPACE,
                "Dimensions": [["Environment"]],
                "Metrics": [{"Name": "QualityEventsDropped", "Unit": "Count"}],
            },
        ]
        record["_aws"] = aws
        line = json.dumps(record, separators=(",", ":"), sort_keys=True, allow_nan=False)
        return line, pending
    except Exception:  # noqa: BLE001
        _restore_dropped(pending)
        return event.line, 0


# --------------------------------------------------------------------------- hook helpers

_CHAT_PHASES: Final = frozenset({
    "premise_resolution", "catalog_retrieval", "primary_assessment", "uncertainty_escalation",
    "independent_answer_qa",
})


def route_from_phase(phase: object) -> str | None:
    """Best-effort ``Route`` from the assessment phase; ``None`` when it is not evident."""
    if phase == "recipe_exact_input":
        return "catalog_recipe"
    if isinstance(phase, str) and phase.startswith("recipe_"):
        return "semantic_reuse"
    if phase in _CHAT_PHASES:
        return "chat_answer"
    return None


def _environment(config: _Config) -> str:
    if config.environment is None:
        raise _reject("environment_missing")
    return config.environment


def record_proof_request_settled(
    *,
    request_id: str,
    status: str,
    error_code: object,
    phase: object,
    elapsed_ms: float,
) -> None:
    """Hook for the worker, called once after ``settle_proof_request`` is accepted."""
    emit(lambda config: [build_proof_request_terminal(
        environment=_environment(config), status=status, error_code=error_code,
        route=route_from_phase(phase), request_id=request_id, duration_ms=elapsed_ms,
        revision=config.revision,
    )])


def record_lean_attempt(
    *, diagnostic_codes: Sequence[object], success: bool, elapsed_ms: float,
    raw_code: str | None = None,
) -> None:
    """Hook for the isolated verifier, called once per finished compile attempt."""
    emit(lambda config: [build_lean_attempt(
        environment=_environment(config), diagnostic_codes=diagnostic_codes, success=success,
        duration_ms=elapsed_ms, raw_code=raw_code, revision=config.revision,
    )])


def record_repair_early_stop(
    *,
    mode: str,
    codes: Sequence[str],
    window: int,
    attempts: int,
    repairs_used: int,
    repairs_remaining: int,
    request_id: object = None,
) -> None:
    """Hook for the pipeline when the repeated-statement-mismatch rule fires."""
    emit(lambda config: [build_repair_early_stop(
        environment=_environment(config), mode=mode, codes=codes, window=window,
        attempts=attempts, repairs_used=repairs_used, repairs_remaining=repairs_remaining,
        request_id=request_id, revision=config.revision,
    )])


def record_explanation_failure(*, resource: str, reason: object) -> None:
    """Hook for terminal explanation failures, reusing the logged fixed-label reason."""
    emit(lambda config: [build_explanation_failure(
        environment=_environment(config), resource=resource, reason=reason,
        revision=config.revision,
    )])


def emit_eval_run(
    *,
    suite: str,
    model_config: str,
    cases: int,
    succeeded: int,
    failures: Mapping[str, int] | None = None,
    duration_s: float | None = None,
    cost_usd: float | None = None,
    revision: str | None = None,
    ledger_id: str | None = None,
) -> bool:
    """Emit one evaluation run; call it from the same function that appends the ledger row.

    The parent repository's ledger-append tool should call this immediately after it
    appends the row, passing the row's ``id`` as ``ledger_id`` so that appending and
    publishing happen in one function. Returns False when disabled or when anything was
    rejected; the ledger append must not depend on the result.
    """
    return emit(
        lambda config: build_eval_run(
            suite=suite, model_config=model_config, cases=cases, succeeded=succeeded,
            failures=failures, duration_s=duration_s, cost_usd=cost_usd,
            revision=revision or config.revision, ledger_id=ledger_id,
        ),
        needs_environment=False,
    )
