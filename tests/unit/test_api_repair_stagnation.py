"""WORKING: API-reconciled failures retain bounded candidate-bound stagnation evidence."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest

from pals_agent.models import Diagnostic
from pals_agent.pipeline import ProofPipeline, _with_repair_stagnation
from pals_agent.worker import _api_repair_seed_from_worker_input
from tests.unit.test_repair_runtime_spec import ApiRepairGenerator, RecordingFaultStore


def diagnostic(code: str = "lean.syntax_error") -> dict[str, Any]:
    messages = {
        "lean.syntax_error": "Lean reported a syntax error.",
        "lean.type_mismatch": "Lean reported a type mismatch.",
    }
    return dict(severity="error", message=messages[code], code=code, line=12, column=7)


def resource(count: int = 3) -> dict[str, Any]:
    code = "theorem broken : True := by\n  exact unavailable\n"
    candidate = str(uuid4())
    detail = diagnostic()
    history = [
        dict(
            attempt=3 - index,
            candidate_id=candidate if index == 0 else str(uuid4()),
            lean_sha256=hashlib.sha256(code.encode()).hexdigest(),
            event_sequence=30 - index * 10,
            diagnostics=[deepcopy(detail)],
        )
        for index in range(count)
    ]
    generic = dict(
        severity="error",
        message="Lean verification failed.",
        code="verifier_compile_failed",
        line=None,
        column=None,
    )
    return dict(
        state="compiling",
        lean_code=code,
        verification_candidate_id=candidate,
        verification_candidate_state="verification_failed",
        diagnostics=[generic],
        compile_failure_history=history,
        status_context=dict(
            stage="compiling",
            repairs_used=2,
            max_repair_attempts=12,
            verification_elapsed_ms=1,
            attempt_evidence=dict(
                attempt=3,
                phase="compile",
                generated=dict(
                    lean_code=code,
                    model="test",
                    provider="test",
                    elapsed_ms=1,
                    draft=None,
                    sketch=None,
                    stage_diagnostics=[],
                ),
                verification=dict(success=False, diagnostics=[generic, detail], elapsed_ms=1),
                repair_route=dict(
                    route="prove",
                    selector_attempts=[
                        dict(attempt=1, outcome="selected", diagnostic_code=None, route="prove")
                    ],
                ),
            ),
        ),
    )


def run_repair(payload: dict[str, Any]):
    seed = _api_repair_seed_from_worker_input(payload)
    assert seed is not None
    generator = ApiRepairGenerator()
    store = RecordingFaultStore(fail_checkpoint_at=99)
    pipeline = ProofPipeline(
        generator=generator, verifier=None, artifact_store=store, verification_mode="api_reconcile"
    )
    result = pipeline.run_statement(
        statement="Prove True", proof_job_id="history-test", api_repair_seed=seed
    )
    assert result.state == "compiling"
    assert result.verification_pending
    assert len(generator.route_feedback) == len(generator.repair_feedback) == 1
    assert generator.generate_calls == 0
    assert store.aggregate_calls[0]["repairs_used"] == 3
    assert store.aggregate_calls[0]["attempts"][-1]["attempt"] == 4
    return seed, generator.route_feedback[0]


def stagnation(feedback):
    return [d for d in feedback.diagnostics if d.code == "pals.repair_stagnation"]


def test_three_bound_consecutive_failures_reach_selector_once_without_changing_budget():
    payload = resource()
    original = deepcopy(payload)
    seed, feedback = run_repair(payload)
    assert len(seed.prior_failure_fingerprints) == 2
    assert len(stagnation(feedback)) == 1
    assert stagnation(feedback)[0].severity == "warning"
    assert "diagnostic signatures" in stagnation(feedback)[0].message
    assert "does not establish" in stagnation(feedback)[0].message
    assert payload == original


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_redelivery_does_not_accumulate_or_double_count_current_candidate(count):
    payload = resource(count)
    for _ in range(2):
        seed, feedback = run_repair(payload)
        assert len(stagnation(feedback)) == (1 if count == 3 else 0)
        assert len(seed.prior_failure_fingerprints) == max(0, count - 1)


def test_different_diagnostic_breaks_consecutive_signature():
    payload = resource()
    payload["compile_failure_history"][1]["diagnostics"] = [diagnostic("lean.type_mismatch")]
    seed, feedback = run_repair(payload)
    assert len(seed.prior_failure_fingerprints) == 2
    assert not stagnation(feedback)


@pytest.mark.parametrize(
    "mutation",
    [
        "gap",
        "reverse",
        "foreign_current",
        "wrong_hash",
        "top_source",
        "oversized",
        "duplicate_candidate",
        "equal_sequence",
        "reverse_sequence",
        "bool_attempt",
        "bool_sequence",
        "extra_field",
        "extra_diagnostic_field",
        "unknown_code",
        "raw_message",
        "too_many_diagnostics",
        "position_too_large",
        "current_diagnostic",
        "uppercase_hash",
        "pending_candidate",
        "current_success",
        "nonlist",
    ],
)
def test_invalid_history_is_ignored_without_bypassing_repair_or_budget(mutation):
    payload = resource()
    h = payload["compile_failure_history"]
    if mutation == "gap":
        h[1]["attempt"] = 1
    elif mutation == "reverse":
        h.reverse()
    elif mutation == "foreign_current":
        h[0]["candidate_id"] = str(uuid4())
    elif mutation == "wrong_hash":
        h[0]["lean_sha256"] = "a" * 64
    elif mutation == "top_source":
        payload["lean_code"] += "-- other\n"
    elif mutation == "oversized":
        h.append(deepcopy(h[-1]))
    elif mutation == "duplicate_candidate":
        h[1]["candidate_id"] = h[0]["candidate_id"]
    elif mutation == "equal_sequence":
        h[1]["event_sequence"] = h[0]["event_sequence"]
    elif mutation == "reverse_sequence":
        h[1]["event_sequence"] = 40
    elif mutation == "bool_attempt":
        h[2]["attempt"] = True
    elif mutation == "bool_sequence":
        h[2]["event_sequence"] = True
    elif mutation == "extra_field":
        h[1]["prompt"] = "untrusted"
    elif mutation == "extra_diagnostic_field":
        h[1]["diagnostics"][0]["raw"] = "untrusted"
    elif mutation == "unknown_code":
        h[1]["diagnostics"][0]["code"] = "other"
    elif mutation == "raw_message":
        h[1]["diagnostics"][0]["message"] += " private output"
    elif mutation == "too_many_diagnostics":
        h[1]["diagnostics"] *= 9
    elif mutation == "position_too_large":
        h[1]["diagnostics"][0]["line"] = 1_000_001
    elif mutation == "current_diagnostic":
        h[0]["diagnostics"] = [diagnostic("lean.type_mismatch")]
    elif mutation == "uppercase_hash":
        h[0]["lean_sha256"] = h[0]["lean_sha256"].upper()
    elif mutation == "pending_candidate":
        payload["verification_candidate_state"] = "compiling"
    elif mutation == "current_success":
        payload["status_context"]["attempt_evidence"]["verification"]["success"] = True
    elif mutation == "nonlist":
        payload["compile_failure_history"] = {}
    seed, feedback = run_repair(payload)
    assert seed.prior_failure_fingerprints == ()
    assert not stagnation(feedback)


def test_missing_history_keeps_legacy_repair_behavior():
    payload = resource()
    del payload["compile_failure_history"]
    seed, feedback = run_repair(payload)
    assert seed.prior_failure_fingerprints == ()
    assert not stagnation(feedback)


def test_common_compile_failure_does_not_create_stagnation_for_unrelated_failures():
    history: list[frozenset[str]] = []
    generic = Diagnostic("error", "Lean verification failed.", "verifier_compile_failed")
    for code, message in [
        ("lean.syntax_error", "syntax"),
        ("lean.type_mismatch", "type"),
        ("lean.unsolved_goals", "goals"),
    ]:
        result = _with_repair_stagnation([generic, Diagnostic("error", message, code)], history)
        assert not any(d.code == "pals.repair_stagnation" for d in result)


@pytest.mark.parametrize("include_history", [False, True])
def test_generation_claim_accepts_old_and_new_api_resource_fields(include_history):
    from pals_agent.worker import _validate_claim_resource
    from tests.unit.test_worker import RecordingApi

    claim = RecordingApi().acquire_proof_generation_claim(
        proof_job_id="job-1", claim_id="11111111-1111-4111-8111-111111111111"
    )
    payload = claim["resource"]
    if include_history:
        payload["compile_failure_history"] = []
    _validate_claim_resource(
        payload, resource_kind="proof_job", resource_id="job-1", status="acquired"
    )
    payload["unrecognized"] = []
    with pytest.raises(ValueError, match="fields"):
        _validate_claim_resource(
            payload, resource_kind="proof_job", resource_id="job-1", status="acquired"
        )


def test_history_never_bypasses_exhausted_repair_budget():
    payload = resource()
    payload["status_context"]["max_repair_attempts"] = 2
    assert _api_repair_seed_from_worker_input(payload) is None
