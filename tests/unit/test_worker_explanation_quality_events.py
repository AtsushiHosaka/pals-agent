"""Real local-file EMF; the named claim/API, generator, reviewer and SQS fixtures stay local.

These tests prove worker wiring, not database commit, Lean verification or model quality.
"""

import json
from dataclasses import replace

import pytest

from pals_agent import explanations
from pals_agent import quality_events as qe
from pals_agent.api_client import PalsApiError
from tests.unit import test_explanation_deadline_spec as generation
from tests.unit import test_worker_claim_spec as claims


@pytest.fixture(autouse=True)
def isolated_events(monkeypatch):
    for name in (qe.ENABLED_ENV, qe.ENVIRONMENT_ENV, qe.REVISION_ENV, qe.TRANSPORT_ENV,
                 qe.FILE_ENV, qe.AGENT_ENDPOINT_ENV, "PALS_ENV"):
        monkeypatch.delenv(name, raising=False)
    qe.reset_for_tests()
    yield
    qe.reset_for_tests()


def destination(tmp_path, monkeypatch):
    path = tmp_path.resolve() / "quality.jsonl"
    path.touch(mode=0o600)
    for name, value in ((qe.ENABLED_ENV, "true"), (qe.ENVIRONMENT_ENV, "probe"),
                        (qe.TRANSPORT_ENV, "file"), (qe.FILE_ENV, str(path))):
        monkeypatch.setenv(name, value)
    return path


def local_worker(resource, monkeypatch, *, mode=None, terminal=False):
    resource_id = ("proof-1" if resource == "explanation" else
                   "8bf36a9a-5d98-4e19-8f70-7f07dfc881a1")
    body = "proof-1" if resource == "explanation" else (
        '{"kind":"clarification","id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"}'
    )
    sqs = claims.FakeSqs(body)
    claims._install_sqs(monkeypatch, sqs)
    clock = claims.FakeClock()
    failure = None
    if mode == "generation":
        failure = explanations.ExplanationGenerationError(
            "PRIVATE_MODEL_RESPONSE", attempt_outputs=("PRIVATE_BODY",),
            attempt_failures=("reference_header", "json"),
        )
    elif mode == "deadline":
        failure = explanations.ExplanationDeadlineExceeded("PRIVATE_DEADLINE")
    explainer = claims.RecordingExplainer(error=failure)
    reviewer = claims.RecordingOutputReviewer(error=(
        explanations.ProofOutputReviewError(
            "PRIVATE_REVIEW", category="rejected", rationale="PRIVATE_RATIONALE",
        ) if mode == "review" else None
    ))
    api = claims.ClaimApi(
        claim_response=claims._envelope(
            "terminal" if terminal else "acquired", None if terminal else 600_000,
            resource_kind=resource, resource_id=resource_id,
        ),
        completed_error=(PalsApiError(
            "PRIVATE_API_ERROR", error_code="proof_" + resource + "_reference_mismatch",
        ) if mode == "reference_mismatch" else None),
        terminal_response=claims._failed_terminal_envelope(resource_kind=resource,
                                                          resource_id=resource_id),
    )
    return claims._worker(api, explainer, clock, output_reviewer=reviewer), api, explainer, sqs


@pytest.mark.parametrize("resource", ["explanation", "clarification"])
@pytest.mark.parametrize("mode,expected", [
    ("generation", "model.invalid_response"), ("deadline", "infra.timeout"),
    ("review", "review.rejected"), ("reference_mismatch", "model.invalid_response"),
])
def test_exhausted_generation_or_review_emits_one_content_free_failure(
    resource, mode, expected, tmp_path, monkeypatch,
):
    path = destination(tmp_path, monkeypatch)
    worker, api, explainer, sqs = local_worker(resource, monkeypatch, mode=mode)
    assert worker.run_once()
    (event,) = [json.loads(line) for line in path.read_text().splitlines()]
    assert event["event"] == "explanation_failure"
    assert event["resource"] == resource and event["failure_code"] == expected
    assert event["ExplanationsFailed"] == 1
    updates = api.explanation_updates if resource == "explanation" else api.clarification_updates
    assert updates[-1]["state"] == "failed" and len(sqs.delete_calls) == 1
    for forbidden in ("PRIVATE", "proof-1", "8bf36a9a", "theorem", "trivial"):
        assert forbidden not in path.read_text()
    if mode == "review":
        calls = explainer.explain_calls if resource == "explanation" else explainer.clarify_calls
        assert len(calls) == 2  # A rejected candidate is repaired before one final failure.


@pytest.mark.parametrize("resource", ["explanation", "clarification"])
def test_terminal_redelivery_emits_nothing_and_spends_no_generation(
    resource, tmp_path, monkeypatch,
):
    path = destination(tmp_path, monkeypatch)
    worker, _, explainer, _ = local_worker(resource, monkeypatch, mode="generation", terminal=True)
    assert worker.run_once()
    assert explainer.explain_calls == explainer.clarify_calls == []
    assert path.read_text() == "" and qe.dropped_count() == 0


def test_rejected_then_corrected_candidate_never_counts_as_a_terminal_failure(
    tmp_path, monkeypatch,
):
    path = destination(tmp_path, monkeypatch)
    claims.test_rejected_summary_generates_one_new_candidate_and_keeps_private_reason(
        monkeypatch, reference_error=False,
    )
    assert path.read_text() == "" and qe.dropped_count() == 0


@pytest.mark.parametrize("exhausted", [False, True])
def test_real_generation_retry_loop_emits_only_when_all_attempts_are_exhausted(
    exhausted, tmp_path, monkeypatch,
):
    path = destination(tmp_path, monkeypatch)
    worker, api, _, _ = local_worker("explanation", monkeypatch)
    responses = ["invalid", "invalid", "invalid"] if exhausted else [
        "invalid", generation._valid_payload(),
    ]
    client = generation.TimedClient(worker.monotonic, responses, [0.0] * len(responses))
    worker = replace(worker, explainer=generation._explainer(client, worker.monotonic))
    assert worker.run_once()
    assert len(client.timeouts) == (3 if exhausted else 2)
    if exhausted:
        (event,) = [json.loads(line) for line in path.read_text().splitlines()]
        assert event["reason_labels"] == "json,json,json"
        assert api.explanation_updates[-1]["state"] == "failed"
    else:
        assert path.read_text() == "" and api.explanation_updates[-1]["state"] == "completed"


def test_disabled_failure_hook_preserves_the_existing_terminal_operation(monkeypatch):
    worker, api, _, sqs = local_worker("explanation", monkeypatch, mode="generation")
    assert worker.run_once()
    assert api.explanation_updates[-1]["state"] == "failed" and len(sqs.delete_calls) == 1
    assert qe.dropped_count() == 0 and qe._TRANSPORTS == {}


def test_emission_failure_does_not_change_the_terminal_write_or_ack(tmp_path, monkeypatch):
    path = destination(tmp_path, monkeypatch)
    path.unlink()  # A missing pre-provisioned file is a real transport failure.
    worker, api, _, sqs = local_worker("explanation", monkeypatch, mode="generation")
    assert worker.run_once()
    assert api.explanation_updates[-1]["state"] == "failed" and len(sqs.delete_calls) == 1
    assert qe.dropped_count() == 1 and not path.exists()
