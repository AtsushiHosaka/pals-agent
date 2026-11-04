"""Fakes only: no model, AWS or network call. Real I/O is a temp file and a loopback UDP port."""

from __future__ import annotations

import ast
import json
import os
import re
import socket
import time
from pathlib import Path
from typing import Any

import pytest

from pals_agent import quality_events as qe
from pals_agent.proof_request_worker import (
    _RESULT_ERROR_CODES,
)
from tests.unit.test_proof_request_worker import REQUEST_ID

# The failure codes in docs/quality-ledger/taxonomy.md (parent repo, PR #221), verbatim.
TAXONOMY_CODES = {
    "infra.timeout", "infra.http_5xx", "infra.capacity_or_quota", "infra.network_or_dependency",
    "infra.verifier_interrupted", "infra.cache_fallback", "infra.result_parse_failure",
    "infra.app_defect", "infra.monitoring_gap", "infra.queue_auth_unavailable",
    "infra.deploy_subprocess_failed",
    "verifier.trusted_audit_failed", "verifier.runtime_unavailable",
    "verifier.lean_compile_error", "verifier.statement_mismatch",
    "verifier.formal_harness_mismatch", "verifier.theorem_alignment_failed",
    "verifier.heartbeat_limit", "verifier.statement_format_error", "verifier.exact_not_closed",
    "model.could_not_prove", "model.invalid_response", "model.selection_invalid",
    "model.preflight_misjudgment", "model.structuring_fidelity_error",
    "retrieval.index_miss", "retrieval.unmatched_recipe",
    "review.rejected", "review.false_accept", "review.unavailable",
    "policy.guest_formal_unavailable", "policy.unsupported_request",
}
QUESTION_LIKE = [
    "Prove that the square of every real number is nonnegative.",
    "実数 x に対して x^2 >= 0 を示してください",
    "theorem foo (x : Nat) : x + 0 = x := by simp",
    "Why is sqrt 2 irrational?",
    "student.name@example.com asked about limits",
]
NOW = int(time.time() * 1000)


class FakeTransport:
    def __init__(self, fail: bool = False) -> None:
        self.lines: list[str] = []
        self.fail = fail

    def send(self, line: str) -> None:
        if self.fail:
            raise OSError("down")
        self.lines.append(line)

    @property
    def events(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.lines]


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        qe.ENABLED_ENV, qe.TRANSPORT_ENV, qe.AGENT_ENDPOINT_ENV, qe.FILE_ENV, qe.ENVIRONMENT_ENV,
        qe.REVISION_ENV, "PALS_ENV",
    ):
        monkeypatch.delenv(name, raising=False)
    qe.reset_for_tests()


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch) -> FakeTransport:
    monkeypatch.setenv(qe.ENABLED_ENV, "true")
    monkeypatch.setenv(qe.ENVIRONMENT_ENV, "probe")
    transport = FakeTransport()
    with qe.use_transport(transport):
        yield transport


def _check_structure(event: dict[str, Any]) -> None:
    aws = event["_aws"]
    assert isinstance(aws["Timestamp"], int)
    for directive in aws["CloudWatchMetrics"]:
        assert directive["Namespace"] == qe.NAMESPACE
        for dimension_set in directive["Dimensions"]:
            assert set(dimension_set) <= qe.ALLOWED_DIMENSIONS
            assert all(isinstance(event[name], str) for name in dimension_set)
        for metric in directive["Metrics"]:
            assert metric["Name"] in qe.ALLOWED_METRICS
            assert isinstance(event[metric["Name"]], int | float)
    allowed = qe.ALLOWED_LOG_FIELDS | qe.ALLOWED_DIMENSIONS | qe.ALLOWED_METRICS | {"_aws"}
    assert set(event) <= allowed


# --------------------------------------------------------------------- disabled by default


def test_disabled_by_default_builds_sends_and_counts_nothing(monkeypatch):
    transport = FakeTransport()
    calls: list[str] = []
    monkeypatch.setenv(qe.ENVIRONMENT_ENV, "prod")
    with qe.use_transport(transport):
        assert not qe.enabled()
        assert qe.emit(lambda config: calls.append("built") or []) is False
        qe.record_proof_request_settled(
            request_id=REQUEST_ID, status="failed", error_code="lean_flow_unavailable",
            phase=None, elapsed_ms=1,
        )
        qe.record_lean_attempt(diagnostic_codes=["lean.compile_error"], success=False, elapsed_ms=1)
        qe.record_explanation_failure(resource="explanation", reason="deadline")
        assert qe.emit_eval_run(suite="s", model_config="m", cases=1, succeeded=1) is False
    assert calls == [] and transport.lines == [] and qe.dropped_count() == 0


@pytest.mark.parametrize("value", ["", "false", "0", "yes", "TRUEISH"])
def test_only_true_or_one_enables(monkeypatch, value):
    monkeypatch.setenv(qe.ENABLED_ENV, value)
    assert not qe.enabled()


def test_enabled_without_valid_destination_or_environment_stays_silent(monkeypatch):
    monkeypatch.setenv(qe.ENABLED_ENV, "true")
    # No environment and no transport settings: nothing is built and nothing is counted.
    assert qe.emit(lambda config: pytest.fail("must not build")) is False
    monkeypatch.setenv(qe.ENVIRONMENT_ENV, "prod")
    assert qe.emit(lambda config: pytest.fail("must not build")) is False  # no agent endpoint
    monkeypatch.setenv(qe.TRANSPORT_ENV, "file")
    monkeypatch.setenv(qe.FILE_ENV, "relative/path.log")
    assert qe.emit(lambda config: pytest.fail("must not build")) is False
    monkeypatch.setenv(qe.TRANSPORT_ENV, "stdout")
    assert qe.emit(lambda config: pytest.fail("must not build")) is False
    assert qe.dropped_count() == 0


# --------------------------------------------------------------------- taxonomy


def test_every_taxonomy_code_maps_to_exactly_one_metric_and_tag():
    assert set(qe.TAXONOMY) == TAXONOMY_CODES | {qe.UNCLASSIFIED}
    metrics = {qe.METRIC_REQUESTS_FAILED, qe.METRIC_REQUESTS_REFUSED, qe.METRIC_ATTEMPTS_FAILED}
    prefix_tag = {
        "infra": "infra", "verifier": "verifier", "model": "model", "retrieval": "model",
        "review": "review", "policy": "policy-refusal",
    }
    seen = [row[0] for row in qe._TAXONOMY_ROWS]
    assert len(seen) == len(set(seen)) == len(TAXONOMY_CODES)  # no code listed twice
    for code in TAXONOMY_CODES:
        entry = qe.TAXONOMY[code]
        assert entry.code == code
        assert isinstance(entry.tag, str) and isinstance(entry.metric, str)
        assert entry.tag == prefix_tag[code.split(".")[0]]
        assert entry.metric in metrics
        assert (entry.metric == qe.METRIC_REQUESTS_REFUSED) == (entry.tag == "policy-refusal")
        assert entry.tag in qe.FAILURE_CLASSES
        assert entry.notify in {"immediate", "rate", "aggregate", "none", "regression"}
    assert qe.TAXONOMY[qe.UNCLASSIFIED].tag == qe.UNCLASSIFIED


def test_unknown_codes_are_unclassified_not_filed_under_another_class():
    for value in ("brand_new_error", "", None, 7, {"x": 1}, "infra.unknown"):
        assert qe.taxonomy_entry(value).code == qe.UNCLASSIFIED
        assert qe.classify_request_error(value) == qe.UNCLASSIFIED
    assert qe.classify_lean_codes([]) == qe.UNCLASSIFIED
    assert qe.classify_lean_codes(["lean.something_new", None]) == qe.UNCLASSIFIED


def test_request_error_mapping_targets_taxonomy_and_covers_the_worker_allowlist():
    assert set(qe.REQUEST_ERROR_TAXONOMY.values()) <= TAXONOMY_CODES
    unmapped = {"proof_reuse_input_invalid", "proof_reuse_query_invalid"}
    assert _RESULT_ERROR_CODES - set(qe.REQUEST_ERROR_TAXONOMY) == unmapped
    # These refusals originate at API admission, before a worker ever receives a claim.
    api_admission_codes = {
        "guest_quota_exhausted", "guest_session_rate_limited", "guest_global_daily_limit",
    }
    assert set(qe.REQUEST_ERROR_TAXONOMY) - _RESULT_ERROR_CODES == api_admission_codes
    # Documented taxonomy examples keep their codes.
    assert qe.classify_request_error("proof_reuse_unsupported") == "policy.unsupported_request"
    assert qe.classify_request_error("material_citation_invalid") == "model.invalid_response"
    assert qe.classify_request_error("proof_reuse_invalid_response") == "model.invalid_response"
    assert qe.classify_request_error("lean_flow_unavailable") == "verifier.runtime_unavailable"


def test_every_lean_diagnostic_code_in_the_package_is_classified():
    package = Path(qe.__file__).parent
    found: set[str] = set()
    for name in ("lean.py", "lean_audit.py", "lean_source_policy.py", "lean_target.py",
                 "lean_supervisor.py", "lean_child.py", "lean_environment.py"):
        found |= set(re.findall(r'"((?:lean|pals)\.[a-z_]+)"', (package / name).read_text()))
    found = {code for code in found if code.startswith("lean.")} - {"lean.verified"}
    assert found, "the scan found no Lean diagnostic codes"
    for code in sorted(found):
        assert qe.classify_lean_codes([code]) in TAXONOMY_CODES, code


@pytest.mark.parametrize("codes,expected", [
    (["lean.compile_error"], "verifier.lean_compile_error"),
    (["lean.unsolved_goals", "lean.type_mismatch"], "verifier.lean_compile_error"),
    (["lean.statement_mismatch"], "verifier.statement_mismatch"),
    (["lean.formal_harness_mismatch"], "verifier.formal_harness_mismatch"),
    (["pals.theorem_alignment_failed"], "verifier.theorem_alignment_failed"),
    (["lean.trusted_audit_failed", "lean.compile_error"], "verifier.trusted_audit_failed"),
    (["lean.timeout"], "infra.timeout"),
    (["lean.verifier_timeout", "lean.compile_error"], "infra.timeout"),
    (["lean.compile_interrupted"], "infra.verifier_interrupted"),
    (["lean.compile_deadline_interrupted", "lean.timeout"], "infra.verifier_interrupted"),
    (["lean.sandbox_setup_failed"], "verifier.runtime_unavailable"),
])
def test_lean_attempt_classification_precedence(codes, expected):
    assert qe.classify_lean_codes(codes) == expected


@pytest.mark.parametrize("reason,kind,code", [
    ("deadline", "deadline", "infra.timeout"),
    ("review:rejected", "review", "review.rejected"),
    ("review:schema", "review", "review.unavailable"),
    ("review:transport,rejected", "review", "review.rejected"),
    ("review:none", "review", "review.unavailable"),
    ("validation:json,other", "validation", "model.invalid_response"),
    ("validation:reference_header", "validation", "model.invalid_response"),
    ("provider:stage=transport,transport_kind=deadline", "provider", "infra.timeout"),
    ("provider:stage=transport,transport_kind=transport_error", "provider",
     "infra.network_or_dependency"),
    ("provider:http_status=429,stage=http,provider_code=insufficient_quota", "provider",
     "infra.capacity_or_quota"),
    ("provider:http_status=503,stage=http", "provider", "infra.http_5xx"),
    ("provider:http_status=400,stage=http", "provider", "infra.app_defect"),
    ("provider:stage=content,response_status=incomplete", "provider", "model.invalid_response"),
    ("provider:", "provider", "unclassified"),
    ("exception:KeyError", "exception", "unclassified"),
    ("exception:Not a name", "exception", "unclassified"),
    ("deadline:extra", "unrecognized", "unclassified"),
    ("review", "unrecognized", "unclassified"),
    ("something else entirely", "unrecognized", "unclassified"),
    ("validation:Why is sqrt 2 irrational?", "validation", "unclassified"),
    (None, "unrecognized", "unclassified"),
    ("x" * 500, "unrecognized", "unclassified"),
])
def test_explanation_reason_classification(reason, kind, code):
    parsed = qe.classify_explanation_reason(reason)
    assert (parsed.kind, parsed.taxonomy_code) == (kind, code)


def test_explanation_validation_labels_keep_known_checks_and_replace_unknown_short_values():
    for label in qe.EXPLANATION_VALIDATION_LABELS:
        event = qe.build_explanation_failure(
            environment="probe", resource="clarification", reason="validation:" + label,
        ).emf
        assert event["reason_labels"] == label
        assert event["FailureClass"] == "model"
        assert event["failure_code"] == "model.invalid_response"
    event = qe.build_explanation_failure(
        environment="probe", resource="explanation",
        reason="validation:reference_header,private_student,brand_new_check",
    )
    assert event.emf["reason_labels"] == "reference_header,unrecognized,unrecognized"
    assert "private_student" not in event.line and "brand_new_check" not in event.line


def test_direct_schema_cannot_bypass_closed_validation_labels():
    event = qe.validate_and_build(
        dimensions={"Environment": "probe"},
        groups=[([("Environment",)], {"ExplanationsFailed": 1})],
        fields={"event": "explanation_failure", "reason_kind": "validation",
                "reason_labels": "unknown_label,reference_header"},
        timestamp_ms=NOW,
    )
    assert event.emf["reason_labels"] == "unrecognized,reference_header"


def test_every_existing_generation_validation_label_is_retained():
    tree = ast.parse((Path(qe.__file__).parent / "explanations.py").read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_validation_failure_reason")
    actual = {node.value.value for node in ast.walk(function)
              if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant)
              and isinstance(node.value.value, str)}
    assert actual <= qe.EXPLANATION_VALIDATION_LABELS
    assert qe.EXPLANATION_VALIDATION_LABELS - actual == {"reference_header", "reference_mismatch"}


def test_review_and_provider_labels_are_closed_and_keep_existing_provider_diagnostics():
    for key, values in qe._PROVIDER_DIAGNOSTIC_ENUMS.items():
        for value in values:
            label = key + "=" + value
            event = qe.build_explanation_failure(
                environment="probe", resource="explanation", reason="provider:" + label,
            )
            assert event.emf["reason_labels"] == label
    for kind in ("review", "provider"):
        event = qe.build_explanation_failure(
            environment="probe", resource="explanation", reason=kind + ":private_student",
        )
        assert event.emf["reason_labels"] == "unrecognized" and "private_student" not in event.line
    with pytest.raises(qe.QualityEventRejected):
        qe.build_explanation_failure(
            environment="probe", resource="explanation", reason="provider:stage=eyJ" + "a" * 20,
        )


# --------------------------------------------------------------------- allow-list


def test_allow_list_rejects_unexpected_fields_dimensions_and_metrics():
    base: dict[str, Any] = {
        "dimensions": {"Environment": "prod"},
        "groups": [([("Environment",)], {"WorkerHeartbeat": 1})],
        "fields": {"event": "lean_attempt"},
        "timestamp_ms": NOW,
        "now_ms": NOW,
    }
    assert qe.validate_and_build(**base).emf["WorkerHeartbeat"] == 1
    for override, reason in [
        ({"fields": {"event": "lean_attempt", "question": "x"}}, "field_not_allowed"),
        ({"fields": {"user_id": "u1"}}, "field_not_allowed"),
        ({"dimensions": {"Environment": "prod", "UserId": "u1"}}, "dimension_not_allowed"),
        ({"groups": [([("Environment",)], {"TokensUsed": 5})]}, "metric_not_allowed"),
        ({"groups": [([("Environment", "Route")], {"WorkerHeartbeat": 1})]}, "dimension_missing"),
        ({"groups": [([("Environment",)], {"WorkerHeartbeat": float("nan")})]},
         "metric_value_invalid"),
        ({"groups": [([("Environment",)], {"WorkerHeartbeat": -1})]}, "metric_value_invalid"),
        ({"groups": []}, "no_metrics"),
        ({"timestamp_ms": NOW - 15 * 24 * 3600 * 1000}, "timestamp_out_of_range"),
        ({"timestamp_ms": NOW + 3 * 3600 * 1000}, "timestamp_out_of_range"),
    ]:
        with pytest.raises(qe.QualityEventRejected) as rejected:
            qe.validate_and_build(**{**base, **override})
        assert str(rejected.value) == reason


def test_dimensions_are_limited_to_the_spec_list():
    assert {
        "Environment", "Route", "FailureClass", "FailureCode", "Suite", "ModelConfig",
    } == qe.ALLOWED_DIMENSIONS


def test_unknown_short_labels_become_unrecognized_but_stay_attributable_to_nothing():
    event = qe.build_proof_request_terminal(
        environment="somewhere_else", status="failed", error_code="brand_new_error",
        route="not_a_route", timestamp_ms=NOW, ).emf
    assert event["Environment"] == event["Route"] == event["route"] == qe.UNRECOGNIZED
    assert event["raw_code"] == qe.UNRECOGNIZED
    assert event["failure_code"] == event["FailureCode"] == qe.UNCLASSIFIED
    assert event["FailureClass"] == qe.UNCLASSIFIED
    assert "brand_new_error" not in json.dumps(event)


# --------------------------------------------------------------------- forbidden content


def _every_text_builder(text: str):
    """Each builder call feeds the text through one string-typed parameter."""
    ok = {"environment": "prod", "timestamp_ms": NOW}
    return [
        lambda: qe.build_proof_request_terminal(**ok, status=text),
        lambda: qe.build_proof_request_terminal(**ok, status="failed", error_code=text),
        lambda: qe.build_proof_request_terminal(**ok, status="failed", route=text),
        lambda: qe.build_proof_request_terminal(**ok, status="failed", revision=text),
        lambda: qe.build_proof_request_terminal(**{**ok, "environment": text}, status="failed"),
        lambda: qe.build_lean_attempt(**ok, diagnostic_codes=[text], success=False, duration_ms=1),
        lambda: qe.build_lean_attempt(
            **ok, diagnostic_codes=[], success=False, duration_ms=1, raw_code=text),
        lambda: qe.build_explanation_failure(**ok, resource=text, reason="deadline"),
        lambda: qe.build_explanation_failure(**ok, resource="explanation", reason=text),
        lambda: qe.build_explanation_failure(
            **ok, resource="explanation", reason="validation:" + text),
        lambda: qe.build_explanation_failure(
            **ok, resource="explanation", reason="exception:" + text),
        lambda: qe.build_eval_run(
            suite=text, model_config="m", cases=1, succeeded=1, timestamp_ms=NOW),
        lambda: qe.build_eval_run(
            suite="s", model_config=text, cases=1, succeeded=1, timestamp_ms=NOW),
        lambda: qe.build_eval_run(
            suite="s", model_config="m", cases=1, succeeded=1, ledger_id=text, timestamp_ms=NOW),
        lambda: qe.build_eval_run(
            suite="s", model_config="m", cases=1, succeeded=1, revision=text, timestamp_ms=NOW),
        lambda: qe.build_eval_run(
            suite="s", model_config="m", cases=2, succeeded=1, failures={text: 1},
            timestamp_ms=NOW),
    ]


@pytest.mark.parametrize("text", QUESTION_LIKE)
def test_question_like_text_never_reaches_an_event(text):
    for build in _every_text_builder(text):
        try:
            produced = build()
        except qe.QualityEventRejected as rejected:
            assert text not in str(rejected)  # closed code only
            continue
        events = produced if isinstance(produced, list) else [produced]
        for event in events:
            assert event is None or text not in event.line
            # Whatever was kept must be the harmless replacement, never the text.
            assert event is None or "Prove" not in event.line and "theorem" not in event.line


@pytest.mark.parametrize("text", QUESTION_LIKE)
def test_question_like_text_fails_closed_and_emits_nothing(enabled, text):
    emitted = qe.emit_eval_run(suite="suite", model_config=text, cases=2, succeeded=1)
    assert emitted is False and enabled.lines == []
    assert qe.dropped_count() == 1
    qe.record_proof_request_settled(
        request_id=REQUEST_ID, status="failed", error_code=text, phase=None, elapsed_ms=1,
    )
    qe.record_explanation_failure(resource="explanation", reason="validation:" + text)
    assert enabled.lines == [] and qe.dropped_count() == 3


# Assembled at runtime so that no secret-shaped literal sits in the repository.
@pytest.mark.parametrize("secret", [
    "sk-" + "proj-abcdefghijklmnop", "AK" + "IA" + "ABCDEFGHIJKLMNOP",
    "ey" + "JhbGciOiJIUzI1NiIsInR5cCI6", "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz",
    "-----" + "BEGIN", "10.0.0.12", "123e4567-e89b-42d3-a456-426614174000", "a@b.co",
])
def test_secret_shaped_and_identity_shaped_values_are_rejected(secret):
    for field in ("suite", "model_config", "ledger_id", "revision"):
        arguments = {"suite": "s", "model_config": "m", "cases": 1, "succeeded": 1,
                     "timestamp_ms": NOW, field: secret}
        with pytest.raises(qe.QualityEventRejected):
            qe.build_eval_run(**arguments)


def test_raw_request_ids_are_never_emitted_only_their_sha256():
    event = qe.build_proof_request_terminal(
        environment="prod", status="answered", request_id=REQUEST_ID, timestamp_ms=NOW,
    )
    assert REQUEST_ID not in event.line
    import hashlib
    assert event.emf["request_hash"] == hashlib.sha256(REQUEST_ID.encode()).hexdigest()
    # A malformed or non-canonical ID is not fingerprinted at all.
    for bad in ("not-a-uuid", "ABCDEF12-1111-4111-8111-111111111111", 5, None):
        event = qe.build_proof_request_terminal(
            environment="prod", status="answered", request_id=bad, timestamp_ms=NOW,
        )
        assert "request_hash" not in event.emf


def test_numeric_fields_are_bounded():
    for arguments in (
        {"cases": 0, "succeeded": 0}, {"cases": 1, "succeeded": 2}, {"cases": -1, "succeeded": 0},
    ):
        with pytest.raises(qe.QualityEventRejected):
            qe.build_eval_run(suite="s", model_config="m", timestamp_ms=NOW, **arguments)
    with pytest.raises(qe.QualityEventRejected):
        qe.build_eval_run(suite="s", model_config="m", cases=1, succeeded=1, cost_usd=-1,
                          timestamp_ms=NOW)


# --------------------------------------------------------------------- EMF shape


def test_successful_request_counts_settled_and_succeeded_by_environment_and_route():
    event = qe.build_proof_request_terminal(
        environment="prod", status="answered", route="semantic_reuse", request_id=REQUEST_ID,
        duration_ms=12.5, revision="abc1234", timestamp_ms=NOW,
    )
    emf = dict(event.emf)
    _check_structure(emf)
    assert "\n" not in event.line
    directives = emf["_aws"]["CloudWatchMetrics"]
    assert len(directives) == 1
    assert directives[0]["Dimensions"] == [["Environment"], ["Environment", "Route"]]
    assert [m["Name"] for m in directives[0]["Metrics"]] == [
        "ProofRequestsSettled", "ProofRequestsSucceeded",
    ]
    assert "failure_class" not in emf and "FailureClass" not in emf


def test_model_failure_counts_failed_by_class_and_code():
    emf = dict(qe.build_proof_request_terminal(
        environment="prod", status="failed", error_code="lean_verification_failed",
        timestamp_ms=NOW,
    ).emf)
    _check_structure(emf)
    failed = emf["_aws"]["CloudWatchMetrics"][1]
    assert failed["Dimensions"] == [["Environment", "FailureClass"], ["Environment", "FailureCode"]]
    assert [m["Name"] for m in failed["Metrics"]] == ["ProofRequestsFailed"]
    assert (emf["FailureClass"], emf["FailureCode"]) == ("model", "model.could_not_prove")
    assert "ProofRequestsSucceeded" not in emf


def test_policy_refusal_is_refused_not_failed_and_needs_input_is_not_in_the_rate():
    refused = dict(qe.build_proof_request_terminal(
        environment="prod", status="failed", error_code="proof_reuse_unsupported",
        timestamp_ms=NOW,
    ).emf)
    _check_structure(refused)
    assert refused["ProofRequestsRefused"] == 1 and "ProofRequestsFailed" not in refused
    assert refused["FailureClass"] == "policy-refusal"
    waiting = dict(qe.build_proof_request_terminal(
        environment="prod", status="needs_input", timestamp_ms=NOW).emf)
    assert waiting["ProofRequestsSettled"] == 1
    assert not {"ProofRequestsSucceeded", "ProofRequestsFailed", "ProofRequestsRefused"} & set(
        waiting
    )


def test_verifying_is_a_handoff_not_a_terminal_event():
    assert qe.build_proof_request_terminal(environment="prod", status="verifying") is None
    with pytest.raises(qe.QualityEventRejected):
        qe.build_proof_request_terminal(environment="prod", status="exploded")


def test_lean_attempt_events_never_carry_source_or_messages():
    failed = dict(qe.build_lean_attempt(
        environment="prod", diagnostic_codes=["lean.timeout"], success=False, duration_ms=450,
        timestamp_ms=NOW,
    ).emf)
    _check_structure(failed)
    assert (failed["FailureClass"], failed["failure_code"]) == ("infra", "infra.timeout")
    assert failed["LeanAttempts"] == 1 and failed["LeanAttemptsFailed"] == 1
    assert failed["LeanVerifyDurationMs"] == 450
    passed = dict(qe.build_lean_attempt(
        environment="prod", diagnostic_codes=[], success=True, duration_ms=10, timestamp_ms=NOW,
    ).emf)
    assert "LeanAttemptsFailed" not in passed and passed["outcome"] == "success"


def test_explanation_failure_event_keeps_only_closed_labels():
    emf = dict(qe.build_explanation_failure(
        environment="prod", resource="explanation",
        reason="provider:stage=http,http_status=429,provider_code=insufficient_quota",
        timestamp_ms=NOW,
    ).emf)
    _check_structure(emf)
    assert emf["ExplanationsFailed"] == 1
    assert (emf["FailureClass"], emf["failure_code"]) == ("infra", "infra.capacity_or_quota")
    assert emf["reason_labels"] == "stage=http,http_status=429,provider_code=insufficient_quota"
    assert emf["reason_kind"] == "provider"
    exception = dict(qe.build_explanation_failure(
        environment="prod", resource="clarification", reason="exception:RuntimeError",
        timestamp_ms=NOW).emf)
    assert exception["exception_type"] == "RuntimeError"
    assert exception["failure_code"] == qe.UNCLASSIFIED


# --------------------------------------------------------------------- transport and drops


def test_failed_send_never_raises_is_counted_and_reported_by_the_next_event(enabled):
    with qe.use_transport(FakeTransport(fail=True)):
        assert qe.emit_eval_run(suite="s", model_config="m", cases=1, succeeded=1) is False
        qe.record_explanation_failure(resource="explanation", reason="deadline")
    assert qe.dropped_count() == 2
    qe.record_explanation_failure(resource="explanation", reason="deadline")
    event = enabled.events[-1]
    _check_structure(event)
    assert event["QualityEventsDropped"] == 2
    assert {"Name": "QualityEventsDropped", "Unit": "Count"} in (
        event["_aws"]["CloudWatchMetrics"][-1]["Metrics"]
    )
    assert qe.dropped_count() == 0
    qe.record_explanation_failure(resource="explanation", reason="deadline")
    assert "QualityEventsDropped" not in enabled.events[-1]


def test_builder_errors_are_swallowed_and_counted(enabled):
    def explode(config):
        raise RuntimeError("boom")

    assert qe.emit(explode) is False
    assert qe.dropped_count() == 1 and enabled.lines == []


def test_file_transport_appends_one_json_line_per_event(monkeypatch, tmp_path):
    path = tmp_path.resolve() / "events.log"
    path.touch(mode=0o600)
    monkeypatch.setenv(qe.ENABLED_ENV, "1")
    monkeypatch.setenv("PALS_ENV", "prod")
    monkeypatch.setenv(qe.TRANSPORT_ENV, "file")
    monkeypatch.setenv(qe.FILE_ENV, str(path))
    monkeypatch.setenv(qe.REVISION_ENV, "abc1234")
    qe.record_explanation_failure(resource="explanation", reason="deadline")
    qe.record_explanation_failure(resource="clarification", reason="deadline")
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["resource"] for line in lines] == ["explanation", "clarification"]
    assert json.loads(lines[0])["revision"] == "abc1234"
    assert json.loads(lines[0])["Environment"] == "prod"


def test_agent_transport_sends_one_udp_datagram_to_the_configured_endpoint(monkeypatch):
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(2)
    try:
        monkeypatch.setenv(qe.ENABLED_ENV, "true")
        monkeypatch.setenv(qe.ENVIRONMENT_ENV, "probe")
        monkeypatch.setenv(qe.AGENT_ENDPOINT_ENV, f"udp://127.0.0.1:{receiver.getsockname()[1]}")
        qe.record_explanation_failure(resource="explanation", reason="deadline")
        data, _ = receiver.recvfrom(65535)
    finally:
        receiver.close()
    event = json.loads(data.decode())
    _check_structure(event)
    assert event["Environment"] == "probe" and event["failure_code"] == "infra.timeout"


def test_unusable_agent_endpoint_counts_a_drop_and_never_raises(monkeypatch):
    monkeypatch.setenv(qe.ENABLED_ENV, "true")
    monkeypatch.setenv(qe.ENVIRONMENT_ENV, "probe")
    monkeypatch.setenv(qe.AGENT_ENDPOINT_ENV, "http://example.invalid:1")  # not udp://
    qe.record_explanation_failure(resource="explanation", reason="deadline")
    assert qe.dropped_count() == 1


@pytest.mark.parametrize("endpoint", [
    "udp://example.invalid:1234", "udp://8.8.8.8:1234", "udp://0.0.0.0:1234",
    "udp://169.254.169.254:1234", "udp://224.0.0.1:1234", "https://127.0.0.1:1234",
    "udp://127.0.0.1:1234/path", "udp://127.0.0.1:1234?query=1",
    "udp://127.0.0.1:1234#fragment", "udp://user@127.0.0.1:1234",
    "udp://127.0.0.1:0", "udp://127.0.0.1:65536",
])
def test_agent_transport_rejects_dns_public_addresses_and_extra_url_fields(endpoint, monkeypatch):
    def forbidden(*args):
        pytest.fail("quality transport attempted DNS")

    monkeypatch.setattr(qe.socket, "gethostbyname", forbidden)
    assert qe._make_transport(("agent", endpoint)) is None


def test_real_udp_sockets_are_closed_after_every_send(monkeypatch):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(1)
        original = socket.socket
        opened = []

        def create(*args, **kwargs):
            stream = original(*args, **kwargs)
            opened.append(stream)
            return stream

        monkeypatch.setattr(qe.socket, "socket", create)
        sender = qe.AgentUdpTransport(f"udp://127.0.0.1:{receiver.getsockname()[1]}")
        for _ in range(2):
            sender.send('{"probe":1}')
            payload, _ = receiver.recvfrom(128)
            assert json.loads(payload) == {"probe": 1}
        assert len(opened) == 2 and all(stream.fileno() == -1 for stream in opened)


def test_file_destination_requires_private_owned_regular_single_link_and_no_symlinks(
    tmp_path, monkeypatch,
):
    root = tmp_path.resolve()
    private = root / "private"
    private.touch(mode=0o600)
    public = root / "public"
    public.touch(mode=0o644)
    link = root / "link"
    link.symlink_to(private)
    hardlink = root / "hardlink"
    os.link(private, hardlink)
    folder = root / "folder"
    folder.mkdir()
    folder_link = root / "folder-link"
    folder_link.symlink_to(folder, target_is_directory=True)
    nested = folder / "private"
    nested.touch(mode=0o600)
    fifo = root / "fifo"
    os.mkfifo(fifo, mode=0o600)
    reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    try:
        monkeypatch.setenv(qe.ENABLED_ENV, "true")
        monkeypatch.setenv(qe.ENVIRONMENT_ENV, "probe")
        monkeypatch.setenv(qe.TRANSPORT_ENV, "file")
        for path in (public, link, hardlink, private, fifo,
                     folder_link / "private", root / "missing"):
            monkeypatch.setenv(qe.FILE_ENV, str(path))
            qe.record_worker_heartbeat()
        assert qe.dropped_count() == 7
        assert not (root / "missing").exists()
        assert private.read_text() == public.read_text() == nested.read_text() == ""
        assert os.read(reader, 1024) == b""
    finally:
        os.close(reader)


def test_file_destination_with_a_different_owner_is_rejected_before_write(tmp_path, monkeypatch):
    path = tmp_path.resolve() / "private"
    path.touch(mode=0o600)
    monkeypatch.setattr(qe.os, "geteuid", lambda: path.stat().st_uid + 1)
    with pytest.raises(ValueError, match="quality_file_not_private"):
        qe.FileTransport(str(path)).send('{"probe":1}')
    assert path.read_text() == ""


# --------------------------------------------------------------------- eval runs (PQO-017)


def test_eval_run_emits_one_record_per_run_and_per_failed_class(enabled):
    assert qe.emit_eval_run(
        suite="recipe-retrieval", model_config="luna-low", cases=20, succeeded=15,
        failures={"model.could_not_prove": 3, "model.invalid_response": 1,
                  "infra.timeout": 1, "brand_new": 0},
        duration_s=12.5, cost_usd=0.25, revision="abc1234",
        ledger_id="2026-11-04-recipe-retrieval",
    )
    events = enabled.events
    for event in events:
        _check_structure(event)
        assert event["ledger_id"] == "2026-11-04-recipe-retrieval"
    run, *failures = events
    assert (run["event"], run["EvalSuccessRate"], run["EvalCases"]) == ("eval_run", 75.0, 20)
    assert run["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [["Suite", "ModelConfig"]]
    assert run["duration_ms"] == 12500.0 and run["cost_usd"] == 0.25
    assert {(f["FailureClass"], f["EvalFailed"]) for f in failures} == {("infra", 1), ("model", 4)}
    assert all(f["event"] == "eval_failure" for f in failures)


def test_two_eval_runs_emit_two_run_events(enabled, monkeypatch):
    monkeypatch.delenv(qe.ENVIRONMENT_ENV)  # a ledger tool outside a deployment has none
    assert qe.emit_eval_run(suite="s", model_config="m", cases=4, succeeded=2, ledger_id="row-1")
    assert qe.emit_eval_run(suite="s", model_config="m", cases=4, succeeded=3, ledger_id="row-2")
    assert [(e["ledger_id"], e["EvalSuccessRate"]) for e in enabled.events] == [
        ("row-1", 50.0), ("row-2", 75.0),
    ]


def test_eval_run_older_than_cloudwatch_accepts_is_rejected_not_silently_lost():
    with pytest.raises(qe.QualityEventRejected) as rejected:
        qe.build_eval_run(suite="s", model_config="m", cases=1, succeeded=1, timestamp_ms=1)
    assert str(rejected.value) == "timestamp_out_of_range"
