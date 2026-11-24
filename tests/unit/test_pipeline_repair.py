"""Repair behaviour of the proof pipeline (moved out of test_pipeline.py, pals#487)."""

import json
from pathlib import Path
from typing import Any

import pytest

from pals_agent.artifacts import FileArtifactStore
from pals_agent.models import (
    Diagnostic,
    RepairRoute,
)
from pals_agent.pipeline import (
    ProofPipeline,
    _with_repair_stagnation,
)
from tests.unit.pipeline_support import (
    BROKEN_REPAIRABLE_CODE,
    FIXED_REPAIRABLE_CODE,
    AlwaysBrokenRepairingGenerator,
    ContentAwareVerifier,
    EmptyGenerator,
    EmptyThenRepairingGenerator,
    InterruptingRouteGenerator,
    MissingLeanProjectVerifier,
    RepairingGenerator,
    RepairWithoutRouteSelectorGenerator,
    SketchMismatchInterruptingGenerator,
    SketchMismatchSuccessfulLeanGenerator,
    StatementSeedDraftCatalog,
    SucceedsOnNthRepairGenerator,
)


@pytest.mark.parametrize("route", ["draft", "sketch", "prove"])
def test_pipeline_repairs_after_lean_compile_failure_from_selected_route(
    tmp_path: Path,
    route: RepairRoute,
) -> None:
    generator = RepairingGenerator(route=route)
    verifier = ContentAwareVerifier()
    statuses = []
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id="job-1",
        on_status=lambda state, diagnostics, uri, lean_code, context: statuses.append(
            (state, context)
        ),
    )

    assert [state for state, _context in statuses] == [
        "retrieving_context",
        "proving",
        "compiling",
        "repairing",
        "proving",
        "compiling",
        "verified",
    ]
    assert result.state == "verified"
    assert result.model_attempt_success is False
    assert result.model_attempt.lean_code == BROKEN_REPAIRABLE_CODE
    assert result.generated.lean_code == FIXED_REPAIRABLE_CODE
    assert verifier.calls == [BROKEN_REPAIRABLE_CODE, FIXED_REPAIRABLE_CODE]
    assert len(generator.route_feedback) == 1
    assert len(generator.feedback) == 1
    assert generator.feedback[0].repair_route == route
    assert generator.feedback[0].repair_rationale == f"test route: {route}"
    feedback = generator.feedback[0]
    assert feedback.attempt == 1
    assert feedback.previous_lean_code == BROKEN_REPAIRABLE_CODE
    assert feedback.diagnostics[0].code == "lean.unknown_identifier"
    assert statuses[3][1]["feedback_diagnostics"][0]["code"] == "lean.unknown_identifier"
    assert statuses[3][1]["repair_route"] == route
    assert statuses[3][1]["repair_route_prompt"] == ""
    assert statuses[3][1]["repair_route_model"] == ""
    assert statuses[3][1]["repair_route_provider"] == ""
    assert statuses[3][1]["repair_route_elapsed_ms"] == 0
    assert statuses[3][1]["repair_route_attempt_outputs"] == []
    assert statuses[4][1]["repair_route"] == route
    assert statuses[4][1]["single_stage_generator"] is True

    metadata = json.loads((tmp_path / "job-1" / "result.json").read_text())
    assert metadata["attempts"][0]["verification"]["success"] is False
    assert metadata["attempts"][1]["verification"]["success"] is True
    assert metadata["attempts"][1]["repair_route"]["route"] == route
    assert metadata["model_attempt_verification"]["success"] is False


def test_pae_016_attempt_checkpoint_and_status_retain_exact_candidate_evidence(
    tmp_path: Path,
) -> None:
    generator = RepairingGenerator(route="prove")
    verifier = ContentAwareVerifier()
    statuses: list[
        tuple[
            str,
            list[dict[str, Any]],
            str | None,
            dict[str, Any],
        ]
    ] = []
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id="candidate-evidence",
        on_status=lambda state, diagnostics, uri, lean_code, context: statuses.append(
            (
                state,
                [diagnostic.to_api() for diagnostic in diagnostics],
                lean_code,
                context,
            )
        ),
    )

    assert result.state == "verified"
    assert verifier.calls == [BROKEN_REPAIRABLE_CODE, FIXED_REPAIRABLE_CODE]
    metadata = json.loads(
        (tmp_path / "candidate-evidence" / "result.json").read_text(encoding="utf-8")
    )
    checkpoints = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((tmp_path / "candidate-evidence" / "attempts").glob("*.json"))
    ]
    repairing = next(event for event in statuses if event[0] == "repairing")
    terminal = statuses[-1]

    assert repairing[2] == BROKEN_REPAIRABLE_CODE
    assert repairing[3]["attempt_evidence"] == metadata["attempts"][0]
    assert repairing[3]["attempt_evidence"] == checkpoints[0]["attempt"]
    assert repairing[3]["repair_route"] == "prove"
    assert (
        repairing[3]["selector_attempts"]
        == (metadata["attempts"][1]["repair_route"]["selector_attempts"])
    )
    assert terminal[0] == "verified"
    assert terminal[2] == FIXED_REPAIRABLE_CODE
    assert terminal[3]["attempt_evidence"] == metadata["attempts"][1]
    assert terminal[3]["attempt_evidence"] == checkpoints[1]["attempt"]
    assert metadata["attempts"][0]["generated"]["lean_code"] == (BROKEN_REPAIRABLE_CODE)
    assert metadata["attempts"][0]["diagnostics"][0]["code"] == ("lean.unknown_identifier")
    assert metadata["attempts"][1]["generated"]["lean_code"] == (FIXED_REPAIRABLE_CODE)
    assert metadata["attempts"][1]["repair_route"]["route"] == "prove"


def test_pipeline_stops_after_repair_attempt_limit(tmp_path: Path) -> None:
    generator = AlwaysBrokenRepairingGenerator()
    verifier = ContentAwareVerifier()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
        max_repair_attempts=1,
    )

    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id="job-1",
    )

    assert result.state == "failed"
    assert len(generator.feedback) == 1
    assert verifier.calls == [BROKEN_REPAIRABLE_CODE, BROKEN_REPAIRABLE_CODE]
    assert result.verification.diagnostics[0].code == "lean.unknown_identifier"
    metadata = json.loads((tmp_path / "job-1" / "result.json").read_text())
    assert metadata["repairs_used"] == 1
    assert metadata["termination_reason"] == "repair_budget_exhausted"


def test_pipeline_default_allows_three_llm_selected_repairs(tmp_path: Path) -> None:
    generator = SucceedsOnNthRepairGenerator(3)
    verifier = ContentAwareVerifier()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id="three-repair-job",
    )

    assert result.state == "verified"
    assert len(generator.feedback) == 3
    assert len(generator.route_feedback) == 3
    assert [feedback.attempt for feedback in generator.feedback] == [1, 2, 3]
    assert verifier.calls == [BROKEN_REPAIRABLE_CODE] * 3 + [FIXED_REPAIRABLE_CODE]
    assert any(
        diagnostic.code == "pals.repair_stagnation"
        for diagnostic in generator.route_feedback[2].diagnostics
    )


def test_pae_016_default_budget_can_verify_on_sixth_repair_and_persists_order(
    tmp_path: Path,
) -> None:
    generator = SucceedsOnNthRepairGenerator(6)
    verifier = ContentAwareVerifier()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id="repair-six",
    )

    assert result.state == "verified"
    assert len(generator.feedback) == 6
    metadata = json.loads((tmp_path / "repair-six" / "result.json").read_text(encoding="utf-8"))
    assert metadata["repairs_used"] == 6
    assert metadata["termination_reason"] == "verified"
    assert [attempt["attempt"] for attempt in metadata["attempts"]] == list(range(1, 8))
    assert all(
        set(attempt) >= {"attempt", "phase", "generated", "verification", "diagnostics"}
        for attempt in metadata["attempts"]
    )
    assert "repair_route" not in metadata["attempts"][0]
    assert all("repair_route" in attempt for attempt in metadata["attempts"][1:])
    checkpoint_paths = sorted((tmp_path / "repair-six" / "attempts").glob("*.json"))
    assert [path.name for path in checkpoint_paths] == [
        f"{attempt:04d}.json" for attempt in range(1, 8)
    ]
    for attempt_number, checkpoint_path in enumerate(checkpoint_paths, start=1):
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert checkpoint["checkpoint_schema_version"] == 1
        assert checkpoint["run_id"] == "repair-six"
        assert checkpoint["problem_id"] == "custom_statement"
        assert checkpoint["max_repair_attempts"] == 6
        assert checkpoint["attempt"] == metadata["attempts"][attempt_number - 1]


def test_pae_016_default_budget_exhaustion_runs_all_six_repairs(
    tmp_path: Path,
) -> None:
    generator = AlwaysBrokenRepairingGenerator()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=ContentAwareVerifier(),
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id="repair-exhausted",
    )

    assert result.state == "failed"
    assert len(generator.feedback) == 6
    metadata = json.loads(
        (tmp_path / "repair-exhausted" / "result.json").read_text(encoding="utf-8")
    )
    assert len(metadata["attempts"]) == 7
    assert metadata["repairs_used"] == 6
    assert metadata["termination_reason"] == "repair_budget_exhausted"
    assert any(
        diagnostic["code"] == "pals.repair_budget_exhausted"
        for diagnostic in metadata["diagnostics"]
    )


def test_pae_016_empty_initial_candidate_is_repaired_when_budget_remains(
    tmp_path: Path,
) -> None:
    generator = EmptyThenRepairingGenerator()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=ContentAwareVerifier(),
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id="empty-then-repair",
    )

    assert result.state == "verified"
    assert len(generator.feedback) == 1
    assert generator.feedback[0].diagnostics[-1].code == "pals.generation_empty"
    metadata = json.loads(
        (tmp_path / "empty-then-repair" / "result.json").read_text(encoding="utf-8")
    )
    assert metadata["repairs_used"] == 1
    assert metadata["termination_reason"] == "verified"


def test_pae_016_sketch_mismatch_is_not_added_to_repair_feedback(
    tmp_path: Path,
) -> None:
    generator = SketchMismatchInterruptingGenerator()
    verifier = ContentAwareVerifier()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    with pytest.raises(
        RuntimeError,
        match="stop after observing combined repair feedback",
    ):
        pipeline.run_statement(
            statement="Every natural number plus zero is itself.",
            formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
            proof_job_id="combined-diagnostics",
        )

    assert verifier.calls == [BROKEN_REPAIRABLE_CODE]
    assert len(generator.route_feedback) == 1
    assert len(generator.feedback) == 1
    expected_codes = {"lean.unknown_identifier"}
    assert {
        diagnostic.code for diagnostic in generator.route_feedback[0].diagnostics
    } == expected_codes
    assert {diagnostic.code for diagnostic in generator.feedback[0].diagnostics} == expected_codes
    checkpoint = json.loads(
        (tmp_path / "combined-diagnostics" / "attempts" / "0001.json").read_text(encoding="utf-8")
    )
    assert checkpoint["attempt"]["phase"] == "compile"
    assert {
        diagnostic["code"] for diagnostic in checkpoint["attempt"]["diagnostics"]
    } == expected_codes


def test_pae_016_sketch_mismatch_is_evaluated_after_successful_compile(
    tmp_path: Path,
) -> None:
    generator = SketchMismatchSuccessfulLeanGenerator()
    verifier = ContentAwareVerifier()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
        max_repair_attempts=1,
    )

    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id="lean-success-sketch-mismatch",
    )

    assert result.state == "verified"
    assert verifier.calls == [FIXED_REPAIRABLE_CODE]
    assert all(
        diagnostic.code != "pals.sketch_contract_mismatch"
        for diagnostic in result.verification.diagnostics
    )
    metadata = json.loads(
        (tmp_path / "lean-success-sketch-mismatch" / "result.json").read_text(encoding="utf-8")
    )
    assert metadata["post_runtime_evaluation"]["sketch_adherence"] is False
    checkpoint = json.loads(
        (tmp_path / "lean-success-sketch-mismatch" / "attempts" / "0001.json").read_text(
            encoding="utf-8"
        )
    )
    assert checkpoint["attempt"]["phase"] == "compile"
    assert checkpoint["attempt"]["verification"]["success"] is True


def test_pae_016_generator_without_repair_fails_with_explicit_reason(
    tmp_path: Path,
) -> None:
    pipeline = ProofPipeline(
        generator=EmptyGenerator(),
        verifier=ContentAwareVerifier(),
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id="repair-unavailable",
    )

    assert result.state == "failed"
    metadata = json.loads(
        (tmp_path / "repair-unavailable" / "result.json").read_text(encoding="utf-8")
    )
    assert metadata["repairs_used"] == 0
    assert metadata["termination_reason"] == "repair_generator_unavailable"
    assert any(
        diagnostic["code"] == "pals.repair_generator_unavailable"
        for diagnostic in metadata["diagnostics"]
    )


def test_pae_016_checkpoint_is_durable_before_next_route_selection(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "checkpoint-before-route" / "attempts" / "0001.json"
    pipeline = ProofPipeline(
        generator=InterruptingRouteGenerator(checkpoint_path),
        verifier=ContentAwareVerifier(),
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    with pytest.raises(RuntimeError, match="simulated interruption"):
        pipeline.run_statement(
            statement="Every natural number plus zero is itself.",
            formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
            proof_job_id="checkpoint-before-route",
        )

    assert checkpoint_path.exists()
    assert not (tmp_path / "checkpoint-before-route" / "result.json").exists()


def test_stagnation_requires_same_error_message_not_only_generic_code() -> None:
    history: list[frozenset[str]] = []

    first = _with_repair_stagnation(
        [Diagnostic(severity="error", code="lean.error", message="unknown identifier")],
        history,
    )
    second = _with_repair_stagnation(
        [Diagnostic(severity="error", code="lean.error", message="type mismatch")],
        history,
    )
    third = _with_repair_stagnation(
        [Diagnostic(severity="error", code="lean.error", message="unsolved goals")],
        history,
    )

    assert all(
        diagnostic.code != "pals.repair_stagnation"
        for diagnostics in (first, second, third)
        for diagnostic in diagnostics
    )


def test_pae_016_stagnation_requires_three_consecutive_normalized_fingerprints() -> None:
    history: list[frozenset[str]] = []
    persistent = Diagnostic(
        severity="error",
        code="lean.typeMismatch",
        message="TYPE   mismatch\nfor X",
    )
    different = Diagnostic(
        severity="error",
        code="lean.typeMismatch",
        message="different mismatch",
    )

    outputs = [
        _with_repair_stagnation([persistent], history),
        _with_repair_stagnation([different], history),
        _with_repair_stagnation([persistent], history),
        _with_repair_stagnation([persistent], history),
    ]

    assert all(
        diagnostic.code != "pals.repair_stagnation" for output in outputs for diagnostic in output
    )
    fifth = _with_repair_stagnation(
        [
            Diagnostic(
                severity="error",
                code="lean.typeMismatch",
                message="type mismatch for x",
            )
        ],
        history,
    )
    assert fifth[-1].code == "pals.repair_stagnation"


def test_pipeline_does_not_send_verifier_configuration_failure_to_llm(
    tmp_path: Path,
) -> None:
    generator = AlwaysBrokenRepairingGenerator()
    verifier = MissingLeanProjectVerifier()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id="missing-project-job",
    )

    assert result.state == "failed"
    assert generator.route_feedback == []
    assert generator.feedback == []
    assert verifier.calls == [BROKEN_REPAIRABLE_CODE]
    metadata = json.loads(
        (tmp_path / "missing-project-job" / "result.json").read_text(encoding="utf-8")
    )
    assert metadata["repairs_used"] == 0
    assert metadata["termination_reason"] == "non_repairable_failure"


def test_pipeline_does_not_choose_repair_route_without_llm_selector(
    tmp_path: Path,
) -> None:
    generator = RepairWithoutRouteSelectorGenerator()
    verifier = ContentAwareVerifier()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
        max_repair_attempts=1,
    )

    statuses: list[tuple[str, dict[str, object]]] = []
    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id="job-1",
        on_status=lambda state, diagnostics, uri, lean_code, context: statuses.append(
            (state, context)
        ),
    )

    metadata = json.loads((tmp_path / "job-1" / "result.json").read_text())
    diagnostic_codes = [diagnostic["code"] for diagnostic in metadata["diagnostics"]]

    assert result.state == "failed"
    assert verifier.calls == [BROKEN_REPAIRABLE_CODE]
    assert "pals.repair_route_selection_failed" in diagnostic_codes
    assert metadata["repairs_used"] == 0
    assert metadata["termination_reason"] == "repair_route_selection_failed"
    route_failure = metadata["diagnostics"][-1]["metadata"]
    assert route_failure == {
        "attempt_outputs": [],
        "elapsed_ms": 0,
        "model": "",
        "prompt": "",
        "provider": "",
        "selector_attempts": [],
    }
    repairing_context = next(context for state, context in statuses if state == "repairing")
    assert repairing_context["repair_route_selection_failed"] is True
    assert repairing_context["repair_route_attempt_outputs"] == []
    assert repairing_context["selector_attempts"] == []
