"""Real pipeline/parser state transitions; scripted generation proves no provider/Lean result."""

import json
from pathlib import Path
from typing import Any

import pytest

from pals_agent.artifacts import FileArtifactStore
from pals_agent.models import (
    Diagnostic,
    GeneratedProof,
    GenerationFeedback,
    ProofRequest,
    RepairRouteDecision,
    VerificationResult,
)
from pals_agent.pipeline import ApiRepairSeed, ProofPipeline, validate_generated_lean

STATEMENT = "For maps f:A→B and g:B→C, injectivity of g∘f implies injectivity of f."
HARNESS = (
    "theorem first_map_injective {A B C : Type*} (f : A → B) (g : B → C) "
    "(h : Function.Injective (g ∘ f)) : Function.Injective f := by"
)
SINGLE = HARNESS + """
  intro x y hxy
  apply h
  change g (f x) = g (f y)
  rw [hxy]
"""
MULTIPLE = """theorem composition_equality {A B C : Type*} (f : A → B) (g : B → C)
    {x y : A} (hxy : f x = f y) : g (f x) = g (f y) := by rw [hxy]
""" + SINGLE


class ScriptedGenerator:
    """Only the external model boundary is scripted; run the actual bounded repair loop."""

    def __init__(self, sources: list[str]) -> None:
        self.sources = list(sources)
        self.feedback: list[GenerationFeedback] = []
        self.generated = 0

    def _next(self) -> GeneratedProof:
        source = self.sources.pop(0)
        return GeneratedProof(lean_code=source, model="scripted", raw_model_output=source)

    def generate(self, request: ProofRequest) -> GeneratedProof:
        self.generated += 1
        return self._next()

    def select_repair_route(
        self, request: ProofRequest, feedback: GenerationFeedback,
    ) -> RepairRouteDecision:
        return RepairRouteDecision(
            route="prove", rationale="Preserve the claim and use local helper facts.",
            raw_model_output='{"route":"prove","rationale":"Localize helper facts."}',
        )

    def repair(self, request: ProofRequest, feedback: GenerationFeedback) -> GeneratedProof:
        self.feedback.append(feedback)
        return self._next()


def pipeline(tmp_path: Path, generator: ScriptedGenerator, budget: int = 2) -> ProofPipeline:
    return ProofPipeline(
        generator=generator, verifier=None, artifact_store=FileArtifactStore(tmp_path),
        verification_mode="api_reconcile", max_repair_attempts=budget,
    )


def test_single_target_reaches_only_api_reconciliation(tmp_path: Path) -> None:
    generator = ScriptedGenerator([SINGLE])
    result = pipeline(tmp_path, generator).run_statement(
        statement=STATEMENT, proof_job_id="single-target",
    )
    assert result.verification_pending
    assert not result.verification.success
    assert result.generated.lean_code == SINGLE
    assert not generator.feedback
    metadata = json.loads(Path(result.artifact.uri).read_text())
    assert metadata["termination_reason"] == "awaiting_api_reconciliation"
    assert metadata["repairs_used"] == 0


def test_local_validation_keeps_its_existing_multiple_declaration_contract() -> None:
    assert validate_generated_lean(ProofRequest(id="local", prompt=STATEMENT), MULTIPLE) == []


def test_multiple_targets_are_repaired_before_api_submission(tmp_path: Path) -> None:
    generator = ScriptedGenerator([MULTIPLE, SINGLE])
    statuses: list[tuple[str, str | None]] = []
    result = pipeline(tmp_path, generator).run_statement(
        statement=STATEMENT, proof_job_id="repaired-target",
        on_status=lambda state, diagnostics, uri, code, context: statuses.append((state, code)),
    )
    assert len(generator.feedback) == 1
    feedback = generator.feedback[0]
    assert feedback.previous_lean_code == MULTIPLE
    assert feedback.attempt == 1
    assert any(item.code == "pals.target_declaration_invalid" for item in feedback.diagnostics)
    assert result.generated.lean_code == SINGLE
    assert result.verification_pending and not result.verification.success
    compiling_sources = [code for state, code in statuses if state == "compiling"]
    assert compiling_sources and set(compiling_sources) == {SINGLE}
    assert all(state != "verified" for state, _ in statuses)
    metadata = json.loads(Path(result.artifact.uri).read_text())
    assert [attempt["phase"] for attempt in metadata["attempts"]] == ["preflight", "compile"]
    assert metadata["attempts"][0]["generated"]["lean_code"] == MULTIPLE
    assert metadata["attempts"][0]["checkpoint_status"] == "published"
    assert metadata["repairs_used"] == 1


@pytest.mark.parametrize("invalid", [MULTIPLE, "def only_data : Nat := 3", "theorem unfinished"])
def test_invalid_target_shape_exhausts_existing_budget_without_submission(
    tmp_path: Path, invalid: str,
) -> None:
    generator = ScriptedGenerator([invalid, invalid, invalid])
    statuses: list[str] = []
    result = pipeline(tmp_path, generator).run_statement(
        statement=STATEMENT, proof_job_id="invalid-target",
        on_status=lambda state, diagnostics, uri, code, context: statuses.append(state),
    )
    assert len(generator.feedback) == 2
    assert not result.verification_pending and not result.verification.success
    assert "compiling" not in statuses and "verified" not in statuses
    metadata = json.loads(Path(result.artifact.uri).read_text())
    assert metadata["termination_reason"] == "repair_budget_exhausted"
    assert metadata["repairs_used"] == 2
    assert [item["phase"] for item in metadata["attempts"]] == ["preflight"] * 3
    assert all(item["generated"]["lean_code"] == invalid for item in metadata["attempts"])


@pytest.mark.parametrize("seed_attempt", [1, 3])
def test_api_compile_repair_reenters_shape_repair_without_resetting_budget(
    tmp_path: Path, seed_attempt: int,
) -> None:
    generator = ScriptedGenerator([MULTIPLE, SINGLE])
    seed = ApiRepairSeed(
        generated=GeneratedProof(lean_code=SINGLE, model="scripted", raw_model_output=SINGLE),
        verification=VerificationResult(
            success=False, stdout="", stderr="", elapsed_ms=1,
            diagnostics=[Diagnostic(
                severity="error", code="verifier_compile_failed", message="Compiler rejected it.",
            )],
        ),
        attempt=seed_attempt, repairs_used=seed_attempt - 1,
    )
    result = pipeline(tmp_path, generator, budget=seed_attempt + 1).run_statement(
        statement=STATEMENT, proof_job_id="compile-repair-target", api_repair_seed=seed,
    )
    assert generator.generated == 0
    assert [item.attempt for item in generator.feedback] == [seed_attempt, seed_attempt + 1]
    assert generator.feedback[0].diagnostics[0].code == "verifier_compile_failed"
    assert any(
        item.code == "pals.target_declaration_invalid" for item in generator.feedback[1].diagnostics
    )
    assert result.verification_pending and not result.verification.success
    assert result.generated.lean_code == SINGLE
    metadata: dict[str, Any] = json.loads(Path(result.artifact.uri).read_text())
    assert [item["attempt"] for item in metadata["attempts"]] == [
        seed_attempt, seed_attempt + 1, seed_attempt + 2,
    ]
    assert [item["phase"] for item in metadata["attempts"]] == ["compile", "preflight", "compile"]
    assert metadata["repairs_used"] == seed_attempt + 1
    assert metadata["attempts"][2]["repair_route"]["route"] == "prove"


def test_shape_repair_cannot_weaken_an_exact_supplied_harness(tmp_path: Path) -> None:
    weakened = SINGLE.replace("Function.Injective f :=", "True :=")
    generator = ScriptedGenerator([MULTIPLE, weakened])
    result = pipeline(tmp_path, generator, budget=1).run_statement(
        statement=STATEMENT, formal_statement=HARNESS, proof_job_id="exact-target",
    )
    assert len(generator.feedback) == 1
    assert not result.verification_pending and not result.verification.success
    metadata = json.loads(Path(result.artifact.uri).read_text())
    assert any(item["code"] == "lean.formal_harness_mismatch" for item in metadata["diagnostics"])
