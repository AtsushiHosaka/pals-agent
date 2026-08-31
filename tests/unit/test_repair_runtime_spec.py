from __future__ import annotations

from typing import Any

import pytest

from pals_agent import artifacts
from pals_agent.draft_catalog import SeedDraftCatalog
from pals_agent.models import (
    Diagnostic,
    GeneratedProof,
    GenerationFeedback,
    ProofArtifact,
    ProofRequest,
    RepairRouteDecision,
    VerificationResult,
)
from pals_agent.pipeline import ApiRepairSeed, ProofPipeline
from pals_agent.settings import AgentSettings

BROKEN = "example : True := by\n  exact missing_name"


class AlwaysBrokenGenerator:
    model = "test-model"

    def __init__(self) -> None:
        self.generate_calls = 0
        self.route_calls = 0
        self.repair_calls = 0

    def generate(self, request: ProofRequest) -> GeneratedProof:
        _ = request
        self.generate_calls += 1
        return GeneratedProof(BROKEN, self.model, BROKEN)

    def select_repair_route(
        self,
        request: ProofRequest,
        feedback: GenerationFeedback,
    ) -> RepairRouteDecision:
        _ = (request, feedback)
        self.route_calls += 1
        return RepairRouteDecision(
            route="prove",
            rationale="retry proof",
            raw_model_output='{"route":"prove","rationale":"retry proof"}',
        )

    def repair(
        self,
        request: ProofRequest,
        feedback: GenerationFeedback,
    ) -> GeneratedProof:
        _ = (request, feedback)
        self.repair_calls += 1
        return GeneratedProof(BROKEN, self.model, BROKEN)


class ApiRepairGenerator:
    model = "api-repair-model"

    def __init__(self) -> None:
        self.generate_calls = 0
        self.route_feedback: list[GenerationFeedback] = []
        self.repair_feedback: list[GenerationFeedback] = []

    def generate(self, request: ProofRequest) -> GeneratedProof:
        _ = request
        self.generate_calls += 1
        raise AssertionError("API repair resume must not generate a replacement from scratch")

    def select_repair_route(
        self,
        request: ProofRequest,
        feedback: GenerationFeedback,
    ) -> RepairRouteDecision:
        _ = request
        self.route_feedback.append(feedback)
        return RepairRouteDecision(
            route="prove",
            rationale="The API verifier rejected only the final proof term.",
            raw_model_output='{"route":"prove","rationale":"local Lean repair"}',
        )

    def repair(
        self,
        request: ProofRequest,
        feedback: GenerationFeedback,
    ) -> GeneratedProof:
        _ = request
        self.repair_feedback.append(feedback)
        repaired = "theorem repaired_after_api_failure : True := by\n  trivial\n"
        return GeneratedProof(repaired, self.model, repaired)


class FailingVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, lean_code: str) -> VerificationResult:
        _ = lean_code
        self.calls += 1
        return VerificationResult(
            success=False,
            diagnostics=[
                Diagnostic(
                    severity="error",
                    code="lean.unknown_identifier",
                    message="unknown identifier",
                )
            ],
            stdout="",
            stderr="",
            elapsed_ms=1,
        )


class AcceptingVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, lean_code: str) -> VerificationResult:
        _ = lean_code
        self.calls += 1
        return VerificationResult(
            success=True,
            diagnostics=[
                Diagnostic(
                    severity="info",
                    code="lean.verified",
                    message="accepted",
                )
            ],
            stdout="compiler accepted candidate",
            stderr="",
            elapsed_ms=1,
        )


class RecordingFaultStore:
    def __init__(
        self,
        *,
        fail_checkpoint_at: int,
        fail_aggregate: bool = False,
    ) -> None:
        self.fail_checkpoint_at = fail_checkpoint_at
        self.fail_aggregate = fail_aggregate
        self.checkpoint_calls: list[dict[str, Any]] = []
        self.aggregate_calls: list[dict[str, Any]] = []

    def save_checkpoint(
        self,
        *,
        run_id: str,
        attempt: int,
        metadata: dict[str, Any],
    ) -> None:
        _ = run_id
        self.checkpoint_calls.append(metadata)
        if attempt == self.fail_checkpoint_at:
            raise OSError("PRIVATE_CHECKPOINT_FAILURE")

    def save(
        self,
        *,
        run_id: str,
        lean_code: str,
        metadata: dict[str, Any],
    ) -> ProofArtifact:
        _ = lean_code
        self.aggregate_calls.append(metadata)
        if self.fail_aggregate:
            raise OSError("PRIVATE_AGGREGATE_FAILURE")
        return ProofArtifact(
            uri=f"memory://{run_id}/result.json",
            lean_uri=f"memory://{run_id}/result.lean",
        )


def _pipeline(
    store: RecordingFaultStore,
    *,
    max_repair_attempts: int = 12,
) -> tuple[ProofPipeline, AlwaysBrokenGenerator, FailingVerifier]:
    generator = AlwaysBrokenGenerator()
    verifier = FailingVerifier()
    return (
        ProofPipeline(
            generator=generator,
            verifier=verifier,
            artifact_store=store,
            draft_catalog=SeedDraftCatalog(),
            max_repair_attempts=max_repair_attempts,
        ),
        generator,
        verifier,
    )


@pytest.mark.parametrize("value", ["1", "12", "64"])
def test_pae_016_strict_repair_budget_accepts_only_ascii_base10_range(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("PALS_MAX_REPAIR_ATTEMPTS", value)
    monkeypatch.delenv("PALS_AGENT_MAX_REPAIR_ATTEMPTS", raising=False)

    assert AgentSettings.from_env().max_repair_attempts == int(value)


def test_pae_016_missing_repair_budget_uses_twelve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PALS_MAX_REPAIR_ATTEMPTS", raising=False)
    monkeypatch.delenv("PALS_AGENT_MAX_REPAIR_ATTEMPTS", raising=False)

    assert AgentSettings.from_env().max_repair_attempts == 12


@pytest.mark.parametrize(
    "value",
    ["", "+1", "-1", "1.0", "1e1", " 1", "1 ", "0", "65", "１２"],
)
def test_pae_016_invalid_repair_budget_fails_preflight(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("PALS_MAX_REPAIR_ATTEMPTS", value)

    with pytest.raises(ValueError, match="PALS_MAX_REPAIR_ATTEMPTS"):
        AgentSettings.from_env()


@pytest.mark.parametrize("value", [0, 65, True])
def test_pae_016_direct_pipeline_budget_is_closed(value: Any) -> None:
    store = RecordingFaultStore(fail_checkpoint_at=99)

    with pytest.raises(ValueError, match="between 1 and 64"):
        _pipeline(store, max_repair_attempts=value)


def test_pae_016_first_checkpoint_failure_persists_exact_terminal_provenance() -> None:
    store = RecordingFaultStore(fail_checkpoint_at=1)
    pipeline, generator, verifier = _pipeline(store)

    result = pipeline.run_statement(
        statement="prove True",
        formal_statement="example : True := by",
        proof_job_id="checkpoint-failure-first",
    )

    assert result.state == "failed"
    assert generator.generate_calls == 1
    assert generator.route_calls == 0
    assert generator.repair_calls == 0
    assert verifier.calls == 1
    assert len(store.checkpoint_calls) == 1
    assert len(store.aggregate_calls) == 1
    metadata = store.aggregate_calls[0]
    assert metadata["termination_reason"] == "artifact_store_failure"
    assert metadata["termination_event"] == {
        "reason": "artifact_store_failure",
        "attempt": 1,
        "source": "artifact_store",
    }
    assert metadata["attempts"][0]["checkpoint_status"] == "failed"
    assert "repair_route" not in metadata["attempts"][0]
    assert metadata["verification"]["success"] is False


def test_pae_016_compile_success_checkpoint_failure_never_serializes_verified() -> None:
    store = RecordingFaultStore(fail_checkpoint_at=1)
    generator = AlwaysBrokenGenerator()
    verifier = AcceptingVerifier()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=store,
        draft_catalog=SeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="prove True",
        formal_statement="example : True := by",
        proof_job_id="compile-success-checkpoint-failure",
    )

    assert verifier.calls == 1
    assert result.state == "failed"
    assert result.verification.success is False
    assert result.verification.stdout == "compiler accepted candidate"
    assert [item.code for item in result.verification.diagnostics] == [
        "lean.verified",
        "pals.artifact_checkpoint_failed",
    ]
    metadata = store.aggregate_calls[0]
    assert metadata["verification"] == metadata["attempts"][0]["verification"]
    assert metadata["verification"]["success"] is False
    assert metadata["termination_reason"] == "artifact_store_failure"


def test_pae_016_later_checkpoint_failure_stops_before_another_route_or_model() -> None:
    store = RecordingFaultStore(fail_checkpoint_at=2)
    pipeline, generator, verifier = _pipeline(store)

    pipeline.run_statement(
        statement="prove True",
        formal_statement="example : True := by",
        proof_job_id="checkpoint-failure-second",
    )

    assert generator.generate_calls == 1
    assert generator.route_calls == 1
    assert generator.repair_calls == 1
    assert verifier.calls == 2
    metadata = store.aggregate_calls[0]
    assert [attempt["checkpoint_status"] for attempt in metadata["attempts"]] == [
        "published",
        "failed",
    ]
    assert "repair_route" not in metadata["attempts"][-1]
    assert metadata["termination_event"]["attempt"] == 2


def test_pae_016_aggregate_failure_raises_typed_error_without_fake_result() -> None:
    store = RecordingFaultStore(fail_checkpoint_at=1, fail_aggregate=True)
    pipeline, generator, _verifier = _pipeline(store)

    with pytest.raises(artifacts.ArtifactPersistenceError) as error_info:
        pipeline.run_statement(
            statement="prove True",
            formal_statement="example : True := by",
            proof_job_id="aggregate-failure",
        )

    assert str(error_info.value) == "pals.artifact_persistence_failed"
    assert generator.route_calls == 0
    assert generator.repair_calls == 0
    assert len(store.aggregate_calls) == 1


def test_pae_016_api_verifier_compile_failure_resumes_through_route_and_repair() -> None:
    store = RecordingFaultStore(fail_checkpoint_at=99)
    generator = ApiRepairGenerator()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=None,
        artifact_store=store,
        verification_mode="api_reconcile",
    )
    prior_code = "theorem broken_before_api_failure : True := by\n  exact missing_name\n"
    seed = ApiRepairSeed(
        generated=GeneratedProof(prior_code, generator.model, prior_code),
        verification=VerificationResult(
            success=False,
            diagnostics=[
                Diagnostic(
                    severity="error",
                    code="verifier_compile_failed",
                    message="Lean verification failed.",
                )
            ],
            stdout="",
            stderr="",
            elapsed_ms=7,
        ),
        attempt=1,
        repairs_used=0,
    )
    statuses: list[str] = []

    result = pipeline.run_statement(
        statement="prove True",
        proof_job_id="api-repair-job",
        api_repair_seed=seed,
        on_status=lambda state, _diagnostics, _uri, _lean_code, _context: statuses.append(
            state
        ),
    )

    assert result.verification_pending is True
    assert result.state == "compiling"
    assert generator.generate_calls == 0
    assert len(generator.route_feedback) == 1
    assert len(generator.repair_feedback) == 1
    assert generator.route_feedback[0].previous_lean_code == prior_code
    assert [item["attempt"] for item in store.aggregate_calls[0]["attempts"]] == [1, 2]
    assert store.aggregate_calls[0]["attempts"][1]["repair_route"]["route"] == "prove"
    assert statuses[0] == "repairing"
    assert statuses[-1] == "compiling"
