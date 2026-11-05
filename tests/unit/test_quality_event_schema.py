"""A standard Draft 2020-12 validator checks the versioned content-free EMF wire contract."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from pals_agent import quality_events as qe

SCHEMA_PATH = Path(qe.__file__).parent / "contracts" / "quality-event-v1.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())
VALIDATOR = Draft202012Validator(SCHEMA)


def heartbeat():
    return dict(qe.validate_and_build(
        dimensions={"Environment": "probe"}, groups=[([("Environment",)], {"WorkerHeartbeat": 1})],
        fields={"event": "worker_heartbeat"}, timestamp_ms=qe._now_ms(),
    ).emf)


def test_artifact_is_valid_versioned_and_matches_the_runtime_contract():
    Draft202012Validator.check_schema(SCHEMA)
    assert SCHEMA["$id"] == qe.QUALITY_EVENT_SCHEMA_ID == "urn:pals:quality-event:1"
    assert qe.quality_event_json_schema() == SCHEMA
    assert set(SCHEMA["properties"]) == (
        qe.ALLOWED_LOG_FIELDS | qe.ALLOWED_DIMENSIONS | qe.ALLOWED_METRICS | {"_aws"}
    )
    assert SCHEMA["additionalProperties"] is False


def test_all_canonical_request_routes_statuses_and_failure_mappings_validate():
    for status, code in [("answered", None), ("needs_input", None), ("failed", None),
                         *(("failed", code) for code in qe.REQUEST_ERROR_TAXONOMY),
                         ("failed", "unknown_short")]:
        for route in (None, *qe.ROUTES, "unknown_short"):
            value = qe.build_proof_request_terminal(
                environment="probe", status=status, error_code=code, route=route,
                request_id="11111111-1111-4111-8111-111111111111", revision="source.123",
            )
            VALIDATOR.validate(value.emf)


def test_all_lean_diagnostics_and_explanation_categories_validate():
    for diagnostic in qe._KNOWN_LEAN_CODES | {"unknown_short"}:
        for success in (True, False):
            VALIDATOR.validate(qe.build_lean_attempt(
                environment="probe", diagnostic_codes=[diagnostic], success=success,
                duration_ms=1, revision="source.123",
            ).emf)
    for resource in ("explanation", "clarification"):
        for reason in ("deadline", "review:rejected", "review:schema",
                       "provider:stage=http,http_status=429,provider_code=insufficient_quota",
                       "exception:RuntimeError", "unknown_short",
                       *("validation:" + label for label in qe.EXPLANATION_VALIDATION_LABELS),
                       "validation:unknown_short"):
            VALIDATOR.validate(qe.build_explanation_failure(
                environment="probe", resource=resource, reason=reason,
            ).emf)
    VALIDATOR.validate(heartbeat())
    for value in qe.build_eval_run(
        suite="reasoning", model_config="luna-low", cases=10, succeeded=7,
        failures={"infra.timeout": 1, "model.invalid_response": 1, "unknown_short": 1},
        cost_usd=0.01, duration_s=2, ledger_id="fixture-run",
    ):
        VALIDATOR.validate(value.emf)


@pytest.mark.parametrize("field", ["question", "lean_code", "message", "user_id", "session_id"])
def test_extra_fields_and_personal_identifiers_are_rejected(field):
    value = heartbeat()
    value[field] = "private_input"
    with pytest.raises(ValidationError):
        VALIDATOR.validate(value)


@pytest.mark.parametrize("field", ["revision", "suite", "model_config", "exception_type"])
@pytest.mark.parametrize("private", [
    "private learner question", "日本語の質問", "private/path", "x\n",
    "sk-" + "project-abcdefghijklmnop", "ey" + "JhbGciOiJIUzI1NiIsInR5cCI6",
    "github_pat_" + "a" * 20, "bearer" + "a" * 15,
    "123e4567-e89b-42d3-a456-426614174000", "10.0.0.12",
])
def test_prose_source_paths_and_secret_identity_shapes_are_rejected(field, private):
    value = heartbeat()
    value[field] = private
    with pytest.raises(ValidationError):
        VALIDATOR.validate(value)


@pytest.mark.parametrize("name", ["request_hash", "UserId", "RequestId", "Host", "WorkerId"])
def test_high_cardinality_dimension_names_are_rejected(name):
    value = heartbeat()
    value["_aws"]["CloudWatchMetrics"][0]["Dimensions"] = [[name]]
    with pytest.raises(ValidationError):
        VALIDATOR.validate(value)


@pytest.mark.parametrize("mutation", [
    lambda value: value["_aws"].update(extra="private"),
    lambda value: value["_aws"]["CloudWatchMetrics"][0].update(extra="private"),
    lambda value: value["_aws"]["CloudWatchMetrics"][0].update(Namespace="Other"),
    lambda value: value["_aws"]["CloudWatchMetrics"][0]["Metrics"][0].update(Unit="Seconds"),
    lambda value: value["_aws"]["CloudWatchMetrics"][0]["Metrics"][0].update(Name="NewMetric"),
    lambda value: value["_aws"]["CloudWatchMetrics"][0]["Metrics"][0].update(extra="private"),
    lambda value: value.pop("WorkerHeartbeat"),
    lambda value: value.pop("Environment"),
    lambda value: value.update(Environment="individual-user"),
    lambda value: value.update(WorkerHeartbeat=-1),
    lambda value: value.update(WorkerHeartbeat=True),
    lambda value: value.update(event="new_event"),
])
def test_metadata_units_targets_and_closed_values_are_checked(mutation):
    value = copy.deepcopy(heartbeat())
    mutation(value)
    with pytest.raises(ValidationError):
        VALIDATOR.validate(value)


def test_unknown_validation_label_must_be_normalized_before_it_is_on_the_wire():
    value = dict(qe.build_explanation_failure(
        environment="probe", resource="explanation", reason="validation:unknown_check",
    ).emf)
    assert value["reason_labels"] == "unrecognized"
    VALIDATOR.validate(value)
    value["reason_labels"] = "unknown_check"
    with pytest.raises(ValidationError):
        VALIDATOR.validate(value)


@pytest.mark.parametrize("kind", ["provider", "review"])
def test_unknown_provider_and_review_labels_must_be_normalized_before_the_wire(kind):
    value = dict(qe.build_explanation_failure(
        environment="probe", resource="explanation", reason=kind + ":private_student",
    ).emf)
    VALIDATOR.validate(value)
    value["reason_labels"] = "private_student"
    with pytest.raises(ValidationError):
        VALIDATOR.validate(value)


def test_emitter_rejects_missing_events_and_empty_or_duplicate_dimension_references():
    base = {"dimensions": {"Environment": "probe"},
            "groups": [([("Environment",)], {"WorkerHeartbeat": 1})],
            "fields": {"event": "worker_heartbeat"}, "timestamp_ms": qe._now_ms()}
    for delta in ({"fields": {}},
                  {"groups": [([], {"WorkerHeartbeat": 1})]},
                  {"groups": [([("Environment", "Environment")], {"WorkerHeartbeat": 1})]}):
        with pytest.raises(qe.QualityEventRejected):
            qe.validate_and_build(**{**base, **delta})


def test_real_emitter_drop_recovery_is_valid_under_the_same_schema(tmp_path, monkeypatch):
    path = tmp_path.resolve() / "events"
    for name, value in ((qe.ENABLED_ENV, "true"), (qe.ENVIRONMENT_ENV, "probe"),
                        (qe.TRANSPORT_ENV, "file"), (qe.FILE_ENV, str(path))):
        monkeypatch.setenv(name, value)
    qe.reset_for_tests()
    try:
        qe.record_worker_heartbeat()  # Missing pre-provisioned file: drop, without an exception.
        assert qe.dropped_count() == 1
        path.touch(mode=0o600)
        qe.record_worker_heartbeat()
        value = json.loads(path.read_text())
        assert value["QualityEventsDropped"] == 1
        VALIDATOR.validate(value)
    finally:
        qe.reset_for_tests()
