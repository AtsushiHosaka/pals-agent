import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from pals_agent.artifacts import FileArtifactStore
from pals_agent.benchmarks import BENCHMARK_PROBLEMS
from pals_agent.draft_catalog import DraftSearchResult, SeedDraftCatalog
from pals_agent.generator import _prompt_for
from pals_agent.lean import LeanVerifier
from pals_agent.models import (
    BenchmarkProblem,
    Diagnostic,
    GeneratedDraft,
    GeneratedProof,
    GeneratedSketch,
    GenerationFeedback,
    ProofDraft,
    ProofRequest,
    RelatedDraftContext,
    RepairRoute,
    RepairRouteAttemptEvidence,
    RepairRouteDecision,
    VerificationResult,
)
from pals_agent.openmath import canonicalize_openmath_xml, canonicalize_retrieval_openmath_xml
from pals_agent.pipeline import (
    ProofPipeline,
    _problem_for_statement,
    _validate_proof_preserves_sketch,
    _with_repair_stagnation,
    validate_generated_lean,
)
from pals_agent.private_draft_candidates import (
    DraftCandidate,
    DraftCandidateResult,
    DraftEmbeddingFingerprint,
)
from pals_agent.proof_flow_runtime import ProofFlowRuntime

MODEL_CONTINUOUS_CODE = """import Mathlib

open Metric

theorem pals_continuous_square : Continuous (fun x : ℝ => x ^ 2) := by
  rw [Metric.continuous_iff]
  intro x ε hε
  let δ : ℝ := min 1 (ε / (2 * |x| + 1))
  have hdist : ∀ y : ℝ, dist (y ^ 2) (x ^ 2) = dist (y ^ 2) (x ^ 2) := by
    intro y
    rfl
  simpa [hdist]
"""

EPSILON_DELTA_SQUARE_CODE = (
    Path(__file__).parents[1] / "fixtures" / "PalsX2Verified.lean"
).read_text(encoding="utf-8")


class RecordingStructurer:
    def __init__(self, openmath_by_statement: dict[str, str], default_xml: str) -> None:
        self.openmath_by_statement = openmath_by_statement
        self.default_xml = default_xml
        self.statements: list[str] = []

    def structure(self, statement: str) -> str:
        self.statements.append(statement)
        return self.openmath_by_statement.get(statement, self.default_xml)


class StatementSeedDraftCatalog:
    def __init__(self) -> None:
        self.seed = SeedDraftCatalog()
        drafts = self.seed.all_drafts()
        self.draft_by_statement = {draft.matched_prompt: draft for draft in drafts}
        for problem in BENCHMARK_PROBLEMS:
            draft = self.seed.find_by_id(problem.id)
            if draft is not None:
                self.draft_by_statement[problem.prompt] = draft
        self.structurer = RecordingStructurer(
            {statement: draft.openmath_xml for statement, draft in self.draft_by_statement.items()},
            drafts[0].openmath_xml,
        )
        self.statement_calls: list[str] = []
        self.id_calls: list[str] = []

    def search_by_statement(self, statement: str) -> DraftSearchResult | None:
        self.statement_calls.append(statement)
        query_xml = canonicalize_openmath_xml(self.structurer.structure(statement))
        draft = self.draft_by_statement.get(statement)
        if draft is None:
            return None
        return DraftSearchResult(
            draft=draft,
            query_openmath_xml=query_xml,
            vector_score=1.0,
            structural_score=1.0,
            final_score=1.0,
            exact_equivalence=(query_xml == canonicalize_openmath_xml(draft.openmath_xml)),
        )

    def find_by_statement(self, statement: str) -> ProofDraft | None:
        return self.draft_by_statement.get(statement)

    def find_by_openmath(self, openmath_xml: str) -> ProofDraft | None:
        _ = openmath_xml
        return None

    def find_by_id(self, draft_id: str) -> ProofDraft | None:
        self.id_calls.append(draft_id)
        return self.seed.find_by_id(draft_id)


@dataclass
class SquareCandidateResponse:
    draft: ProofDraft
    fingerprint: DraftEmbeddingFingerprint
    calls: list[tuple[list[float], DraftEmbeddingFingerprint]]

    def find_candidates(
        self,
        *,
        embedding: list[float],
        fingerprint: DraftEmbeddingFingerprint,
    ) -> DraftCandidateResult:
        self.calls.append((embedding, fingerprint))
        return DraftCandidateResult(
            generation_id="11111111-1111-4111-8111-111111111111",
            manifest_sha256="sha256:" + "a" * 64,
            seed_count=1,
            runtime_provenance_sha256="b" * 64,
            fingerprint=self.fingerprint,
            candidates=(DraftCandidate(draft=self.draft, cosine_distance=0.0),),
        )


@dataclass
class SquareRerankerResponse:
    calls: list[object]

    def rerank(self, request: object) -> tuple[str, ...]:
        self.calls.append(request)
        return ("continuous_square",)


@dataclass
class UnitEmbeddingModel:
    calls: list[str]

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [1.0, 0.0]


class ContinuousGenerator:
    model = "fake-model"

    def generate(self, request: ProofRequest) -> GeneratedProof:
        return GeneratedProof(
            lean_code=MODEL_CONTINUOUS_CODE,
            model=self.model,
            raw_model_output=f"```lean\n{MODEL_CONTINUOUS_CODE}\n```",
        )


class RecordingContinuousGenerator(ContinuousGenerator):
    def __init__(self) -> None:
        self.requests: list[ProofRequest] = []
        self.prompts: list[str] = []

    def generate(self, request: ProofRequest) -> GeneratedProof:
        self.requests.append(request)
        self.prompts.append(_prompt_for(request))
        return super().generate(request)


class RecordingStagedGenerator:
    model = "draft-sketch-model"
    prove_model = "prove-model"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate_draft(
        self,
        request: ProofRequest,
        feedback: GenerationFeedback | None = None,
    ) -> GeneratedDraft:
        _ = (request, feedback)
        self.calls.append("draft")
        return GeneratedDraft(
            text="Use the natural-number add-zero identity.",
            model=self.model,
            raw_model_output="Use the natural-number add-zero identity.",
        )

    def generate_sketch(
        self,
        request: ProofRequest,
        draft: GeneratedDraft,
        feedback: GenerationFeedback | None = None,
    ) -> GeneratedSketch:
        _ = (request, feedback)
        assert "add-zero" in draft.text
        self.calls.append("sketch")
        code = (
            "import Mathlib\n\n"
            "theorem add_zero_nat (n : Nat) : n + 0 = n := by\n"
            "  have h : n + 0 = n := by\n"
            "    sorry\n"
            "  exact h"
        )
        return GeneratedSketch(
            code,
            self.model,
            f"```lean\n{code}\n```",
            has_gaps=True,
        )

    def generate_proof(
        self,
        request: ProofRequest,
        draft: GeneratedDraft,
        sketch: GeneratedSketch,
        feedback: GenerationFeedback | None = None,
    ) -> GeneratedProof:
        _ = (request, feedback)
        assert "sorry" in sketch.lean_code
        self.calls.append("prove")
        completed_code = (
            "import Mathlib\n\n"
            "theorem add_zero_nat (n : Nat) : n + 0 = n := by\n"
            "  have h : n + 0 = n := by\n"
            "    simpa using Nat.add_zero n\n"
            "  exact h"
        )
        return GeneratedProof(
            lean_code=completed_code,
            model=self.prove_model,
            raw_model_output=f"```lean\n{completed_code}\n```",
            draft=draft,
            sketch=sketch,
        )


class RepairingStagedGenerator(RecordingStagedGenerator):
    def __init__(self) -> None:
        super().__init__()
        self.sketch_attempts = 0
        self.route_feedback: list[GenerationFeedback] = []

    def generate_sketch(
        self,
        request: ProofRequest,
        draft: GeneratedDraft,
        feedback: GenerationFeedback | None = None,
    ) -> GeneratedSketch:
        self.sketch_attempts += 1
        if self.sketch_attempts == 1:
            self.calls.append("sketch-invalid")
            return GeneratedSketch(
                lean_code="",
                model=self.model,
                raw_model_output=(
                    "[generation-error] sketch stage returned Lean code without a "
                    "sorry gap.\n\n[raw-model-output]\n```lean\n"
                    f"{FIXED_REPAIRABLE_CODE}\n```"
                ),
            )
        return super().generate_sketch(request, draft, feedback)

    def select_repair_route(
        self,
        request: ProofRequest,
        feedback: GenerationFeedback,
    ) -> RepairRouteDecision:
        _ = request
        self.route_feedback.append(feedback)
        return RepairRouteDecision(
            route="sketch",
            rationale="The formal Sketch did not contain localized proof gaps.",
            raw_model_output=('{"route":"sketch","rationale":"missing formal sketch gaps"}'),
        )

    def repair(
        self,
        request: ProofRequest,
        feedback: GenerationFeedback,
    ) -> GeneratedProof:
        raise AssertionError("The pipeline must resume through the public stage methods.")


class RenamedContinuousGenerator(ContinuousGenerator):
    def generate(self, request: ProofRequest) -> GeneratedProof:
        generated = super().generate(request)
        return GeneratedProof(
            lean_code=generated.lean_code.replace(
                "theorem pals_continuous_square",
                "theorem model_chosen_square_name",
            ),
            model=generated.model,
            raw_model_output=generated.raw_model_output,
        )


class ShortSquareGenerator(ContinuousGenerator):
    def generate(self, request: ProofRequest) -> GeneratedProof:
        code = """import Mathlib

theorem model_chosen_square_name : Continuous (fun x : ℝ => x ^ 2) := by
  simpa using (continuous_id.pow 2 : Continuous fun x : ℝ => x ^ 2)
"""
        return GeneratedProof(lean_code=code, model=self.model, raw_model_output=code)


class ApproximateSquareDraftCatalog:
    def __init__(self) -> None:
        draft = SeedDraftCatalog().find_by_id("continuous_square")
        assert draft is not None
        self.draft = draft
        self.query_openmath_xml = canonicalize_openmath_xml(
            draft.openmath_xml.replace("<OMI>2</OMI>", "<OMI>3</OMI>")
        )

    def search_by_statement(self, statement: str) -> DraftSearchResult | None:
        assert statement == "x^3が連続であることを示せ"
        return DraftSearchResult(
            draft=self.draft,
            query_openmath_xml=self.query_openmath_xml,
            vector_score=0.98,
            structural_score=0.94,
            final_score=0.956,
            exact_equivalence=False,
        )

    def find_by_statement(self, statement: str) -> ProofDraft | None:
        _ = statement
        return self.draft

    def find_by_openmath(self, openmath_xml: str) -> ProofDraft | None:
        _ = openmath_xml
        return self.draft

    def find_by_id(self, draft_id: str) -> ProofDraft | None:
        return self.draft if draft_id == self.draft.id else None


class EmptyGenerator:
    model = "fake-model"

    def generate(self, request: ProofRequest) -> GeneratedProof:
        return GeneratedProof(
            lean_code="",
            model=self.model,
            raw_model_output="informal prose only",
        )


class OpenAIErrorGenerator:
    model = "gpt-5.4-nano"

    def generate(self, request: ProofRequest) -> GeneratedProof:
        return GeneratedProof(
            lean_code="",
            model=self.model,
            raw_model_output=(
                "[openai-error] OPENAI_API_KEY is required when PALS_LLM_PROVIDER=openai."
            ),
        )


class WrongStatementGenerator:
    model = "fake-model"

    def generate(self, request: ProofRequest) -> GeneratedProof:
        return GeneratedProof(
            lean_code="example : True := by\n  trivial",
            model=self.model,
            raw_model_output="```lean\nexample : True := by\n  trivial\n```",
        )


class CommentSpoofedFragmentGenerator:
    model = "fake-model"

    def generate(self, request: ProofRequest) -> GeneratedProof:
        return GeneratedProof(
            lean_code=(
                "-- Metric.continuous_iff\n"
                "-- ε / (2 * |x| + 1)\n"
                "-- dist (y ^ 2) (x ^ 2)\n"
                "example : True := by\n"
                "  trivial"
            ),
            model=self.model,
            raw_model_output="",
        )


class StringSpoofedFormalHarnessGenerator:
    model = "fake-model"

    def generate(self, request: ProofRequest) -> GeneratedProof:
        return GeneratedProof(
            lean_code=(
                "import Mathlib\n\n"
                "def claimedTarget : String := "
                '"theorem pals_continuous_square : '
                "Continuous (fun x : ℝ => x ^ 2) := by "
                "Metric.continuous_iff ε / (2 * |x| + 1) "
                'dist (y ^ 2) (x ^ 2)"\n\n'
                "example : True := by\n"
                "  trivial"
            ),
            model=self.model,
            raw_model_output="",
        )


class SyntaxQuotationSpoofGenerator:
    model = "fake-model"

    def generate(self, request: ProofRequest) -> GeneratedProof:
        return GeneratedProof(
            lean_code=(
                "import Mathlib\n\n"
                "run_cmd do\n"
                "  let _stx ← `(command| "
                "theorem pals_continuous_square : "
                "Continuous (fun x : ℝ => x ^ 2) := by\n"
                "    rw [Metric.continuous_iff]\n"
                "    let δ : ℝ := min 1 (ε / (2 * |x| + 1))\n"
                "    have h : dist (y ^ 2) (x ^ 2) = "
                "dist (y ^ 2) (x ^ 2) := by rfl)\n\n"
                "example : True := by\n"
                "  trivial"
            ),
            model=self.model,
            raw_model_output="",
        )


class FormalStatementCapturingGenerator:
    model = "fake-model"

    def __init__(self) -> None:
        self.requests: list[ProofRequest] = []

    def generate(self, request: ProofRequest) -> GeneratedProof:
        self.requests.append(request)
        return GeneratedProof(
            lean_code=(
                "import Mathlib\n\n"
                f"{request.formal_statement}\n"
                "  rw [Metric.continuous_iff]\n"
                "  intro x ε hε\n"
                "  let δ : ℝ := min 1 (ε / (2 * |x| + 1))\n"
                "  have hdist : ∀ y : ℝ, dist (y ^ 2) (x ^ 2) = "
                "dist (y ^ 2) (x ^ 2) := by\n"
                "    intro y\n"
                "    rfl\n"
                "  simpa [hdist]"
            ),
            model=self.model,
            raw_model_output="",
        )


class FormalStatementGenerator:
    model = "fake-model"

    def generate(self, request: ProofRequest) -> GeneratedProof:
        return GeneratedProof(
            lean_code=(
                "import Mathlib\n\n"
                "theorem add_zero_nat (n : Nat) : n + 0 = n := by\n"
                "  simpa using Nat.add_zero n"
            ),
            model=self.model,
            raw_model_output="",
        )


BROKEN_REPAIRABLE_CODE = """import Mathlib

theorem add_zero_nat (n : Nat) : n + 0 = n := by
  exact broken_identifier
"""

FIXED_REPAIRABLE_CODE = """import Mathlib

theorem add_zero_nat (n : Nat) : n + 0 = n := by
  simpa using Nat.add_zero n
"""


class RepairingGenerator:
    model = "fake-model"

    def __init__(self, *, route: RepairRoute = "prove") -> None:
        self.route = route
        self.feedback: list[GenerationFeedback] = []
        self.route_feedback: list[GenerationFeedback] = []

    def generate(self, request: ProofRequest) -> GeneratedProof:
        return GeneratedProof(
            lean_code=BROKEN_REPAIRABLE_CODE,
            model=self.model,
            raw_model_output=f"```lean\n{BROKEN_REPAIRABLE_CODE}\n```",
        )

    def select_repair_route(
        self,
        request: ProofRequest,
        feedback: GenerationFeedback,
    ) -> RepairRouteDecision:
        self.route_feedback.append(feedback)
        return RepairRouteDecision(
            route=self.route,
            rationale=f"test route: {self.route}",
            raw_model_output=f'{{"route":"{self.route}","rationale":"test route"}}',
            selector_attempts=(
                RepairRouteAttemptEvidence(
                    attempt=1,
                    outcome="selected",
                    diagnostic_code=None,
                    route=self.route,
                ),
            ),
        )

    def repair(self, request: ProofRequest, feedback: GenerationFeedback) -> GeneratedProof:
        self.feedback.append(feedback)
        return GeneratedProof(
            lean_code=FIXED_REPAIRABLE_CODE,
            model=self.model,
            raw_model_output=f"```lean\n{FIXED_REPAIRABLE_CODE}\n```",
        )


class AlwaysBrokenRepairingGenerator(RepairingGenerator):
    def repair(self, request: ProofRequest, feedback: GenerationFeedback) -> GeneratedProof:
        self.feedback.append(feedback)
        return GeneratedProof(
            lean_code=BROKEN_REPAIRABLE_CODE,
            model=self.model,
            raw_model_output=f"```lean\n{BROKEN_REPAIRABLE_CODE}\n```",
        )


class SucceedsOnFifthRepairGenerator(RepairingGenerator):
    def repair(self, request: ProofRequest, feedback: GenerationFeedback) -> GeneratedProof:
        self.feedback.append(feedback)
        lean_code = FIXED_REPAIRABLE_CODE if len(self.feedback) == 5 else BROKEN_REPAIRABLE_CODE
        return GeneratedProof(
            lean_code=lean_code,
            model=self.model,
            raw_model_output=f"```lean\n{lean_code}\n```",
        )


class SucceedsOnNthRepairGenerator(RepairingGenerator):
    def __init__(self, repair_number: int) -> None:
        super().__init__()
        self.repair_number = repair_number

    def repair(self, request: ProofRequest, feedback: GenerationFeedback) -> GeneratedProof:
        self.feedback.append(feedback)
        lean_code = (
            FIXED_REPAIRABLE_CODE
            if len(self.feedback) == self.repair_number
            else BROKEN_REPAIRABLE_CODE
        )
        return GeneratedProof(
            lean_code=lean_code,
            model=self.model,
            raw_model_output=f"```lean\n{lean_code}\n```",
        )


class EmptyThenRepairingGenerator(RepairingGenerator):
    def generate(self, request: ProofRequest) -> GeneratedProof:
        return GeneratedProof(
            lean_code="",
            model=self.model,
            raw_model_output="no extractable Lean candidate",
        )


class SketchMismatchInterruptingGenerator(RepairingGenerator):
    def generate(self, request: ProofRequest) -> GeneratedProof:
        draft = GeneratedDraft(
            text="Prove add-zero through an explicit retained fact.",
            model=self.model,
            raw_model_output="Prove add-zero through an explicit retained fact.",
        )
        sketch_code = (
            "import Mathlib\n\n"
            "theorem add_zero_nat (n : Nat) : n + 0 = n := by\n"
            "  have retained : n + 0 = n := by\n"
            "    sorry\n"
            "  exact retained"
        )
        return GeneratedProof(
            lean_code=BROKEN_REPAIRABLE_CODE,
            model=self.model,
            raw_model_output=f"```lean\n{BROKEN_REPAIRABLE_CODE}\n```",
            draft=draft,
            sketch=GeneratedSketch(
                lean_code=sketch_code,
                model=self.model,
                raw_model_output=f"```lean\n{sketch_code}\n```",
                has_gaps=True,
            ),
        )

    def repair(self, request: ProofRequest, feedback: GenerationFeedback) -> GeneratedProof:
        self.feedback.append(feedback)
        raise RuntimeError("stop after observing combined repair feedback")


class SketchMismatchSuccessfulLeanGenerator(SketchMismatchInterruptingGenerator):
    repair: Any = None

    def generate(self, request: ProofRequest) -> GeneratedProof:
        generated = super().generate(request)
        return GeneratedProof(
            lean_code=FIXED_REPAIRABLE_CODE,
            model=generated.model,
            raw_model_output=f"```lean\n{FIXED_REPAIRABLE_CODE}\n```",
            draft=generated.draft,
            sketch=generated.sketch,
        )


class InterruptingRouteGenerator(AlwaysBrokenRepairingGenerator):
    def __init__(self, checkpoint_path: Path) -> None:
        super().__init__()
        self.checkpoint_path = checkpoint_path

    def select_repair_route(
        self,
        request: ProofRequest,
        feedback: GenerationFeedback,
    ) -> RepairRouteDecision:
        assert self.checkpoint_path.exists()
        checkpoint = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        assert checkpoint["attempt"]["attempt"] == 1
        raise RuntimeError("simulated interruption after durable checkpoint")


class RepairWithoutRouteSelectorGenerator:
    model = "fake-model"

    def generate(self, request: ProofRequest) -> GeneratedProof:
        return GeneratedProof(
            lean_code=BROKEN_REPAIRABLE_CODE,
            model=self.model,
            raw_model_output=f"```lean\n{BROKEN_REPAIRABLE_CODE}\n```",
        )

    def repair(self, request: ProofRequest, feedback: GenerationFeedback) -> GeneratedProof:
        return GeneratedProof(
            lean_code=FIXED_REPAIRABLE_CODE,
            model=self.model,
            raw_model_output=f"```lean\n{FIXED_REPAIRABLE_CODE}\n```",
        )


class FakeVerifier:
    def __init__(self, *, success: bool = True) -> None:
        self.calls: list[str] = []
        self.success = success

    def verify(self, lean_code: str) -> VerificationResult:
        self.calls.append(lean_code)
        return VerificationResult(
            success=self.success,
            diagnostics=[],
            stdout="",
            stderr="",
            elapsed_ms=7,
        )


class ContentAwareVerifier:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def verify(self, lean_code: str) -> VerificationResult:
        self.calls.append(lean_code)
        if "broken_identifier" in lean_code:
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(
                        severity="error",
                        code="lean.unknown_identifier",
                        message="unknown identifier 'broken_identifier'",
                        line=4,
                        column=9,
                    )
                ],
                stdout="",
                stderr="error: unknown identifier",
                elapsed_ms=9,
            )
        return VerificationResult(
            success=True,
            diagnostics=[
                Diagnostic(
                    severity="info",
                    code="lean.verified",
                    message="Lean accepted the generated code.",
                )
            ],
            stdout="",
            stderr="",
            elapsed_ms=5,
        )


class MissingLeanProjectVerifier:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def verify(self, lean_code: str) -> VerificationResult:
        self.calls.append(lean_code)
        return VerificationResult(
            success=False,
            diagnostics=[
                Diagnostic(
                    severity="error",
                    code="lean.project_not_found",
                    message="Lean project directory was not found",
                )
            ],
            stdout="",
            stderr="",
            elapsed_ms=0,
        )


def test_pipeline_persists_model_artifact_and_emits_statuses(tmp_path: Path) -> None:
    statuses = []
    catalog = StatementSeedDraftCatalog()
    generator = RecordingContinuousGenerator()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=FakeVerifier(),
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=catalog,
    )

    result = pipeline.run_problem(
        problem=BENCHMARK_PROBLEMS[0],
        proof_job_id="job-1",
        on_status=lambda state, diagnostics, uri, lean_code, context: statuses.append(
            (state, uri, lean_code)
        ),
    )

    assert result.state == "verified"
    assert result.model_attempt_success is True
    assert statuses[0][0] == "retrieving_context"
    assert statuses[-1][0] == "verified"
    assert statuses[-1][2] == result.generated.lean_code
    assert catalog.statement_calls == [BENCHMARK_PROBLEMS[0].prompt]
    assert catalog.structurer.statements == [BENCHMARK_PROBLEMS[0].prompt]
    assert catalog.id_calls == []
    assert generator.requests[0].formal_statement is None
    assert generator.requests[0].formal_statement_source is None
    benchmark_draft = catalog.seed.find_by_id("continuous_square")
    assert benchmark_draft is not None
    assert benchmark_draft.proof_strategy in generator.prompts[0]
    assert all(step in generator.prompts[0] for step in benchmark_draft.sketch_steps)
    assert (tmp_path / "job-1" / "result.lean").exists()
    assert (tmp_path / "job-1" / "result.json").exists()
    metadata = json.loads((tmp_path / "job-1" / "result.json").read_text())
    assert metadata["formal_statement"] is None
    assert metadata["verification_harness"] == {
        "hidden_from_generation": False,
        "source": None,
    }


def test_pipeline_executes_real_dsp_stages_and_exposes_stage_outputs(
    tmp_path: Path,
) -> None:
    generator = RecordingStagedGenerator()
    statuses: list[tuple[str, str | None, dict[str, object]]] = []
    pipeline = ProofPipeline(
        generator=generator,
        verifier=FakeVerifier(),
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id="staged-job",
        on_status=lambda state, diagnostics, uri, lean_code, context: statuses.append(
            (state, lean_code, context)
        ),
    )

    assert result.state == "verified"
    assert generator.calls == ["draft", "sketch", "prove"]
    assert [state for state, _code, _context in statuses] == [
        "retrieving_context",
        "drafting",
        "sketching",
        "proving",
        "compiling",
        "verified",
    ]
    sketch_context = statuses[2][2]
    generated_draft = sketch_context["generated_draft"]
    assert isinstance(generated_draft, dict)
    assert generated_draft["text"] == ("Use the natural-number add-zero identity.")
    proving_code = statuses[3][1]
    assert proving_code is not None and "sorry" in proving_code
    generated_sketch = statuses[3][2]["generated_sketch"]
    assert isinstance(generated_sketch, dict)
    assert generated_sketch["lean_code"] == proving_code

    metadata = json.loads((tmp_path / "staged-job" / "result.json").read_text())
    assert metadata["generated"]["draft"]["text"] == ("Use the natural-number add-zero identity.")
    assert "prompt" in metadata["generated"]["draft"]
    assert "provider" in metadata["generated"]["draft"]
    assert "elapsed_ms" in metadata["generated"]["draft"]
    assert "sorry" in metadata["generated"]["sketch"]["lean_code"]


def test_pipeline_repairs_a_failed_sketch_from_the_sketch_stage(
    tmp_path: Path,
) -> None:
    generator = RepairingStagedGenerator()
    statuses: list[str] = []
    pipeline = ProofPipeline(
        generator=generator,
        verifier=FakeVerifier(),
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id="sketch-repair-job",
        on_status=lambda state, diagnostics, uri, lean_code, context: statuses.append(state),
    )

    assert result.state == "verified"
    assert generator.calls == ["draft", "sketch-invalid", "sketch", "prove"]
    assert statuses == [
        "retrieving_context",
        "drafting",
        "sketching",
        "repairing",
        "sketching",
        "proving",
        "compiling",
        "verified",
    ]
    assert len(generator.route_feedback) == 1
    route_feedback = generator.route_feedback[0]
    assert route_feedback.previous_draft is not None
    assert route_feedback.previous_sketch is not None
    assert route_feedback.previous_sketch.lean_code == ""
    assert any(
        diagnostic.code == "llm.generation_failed" for diagnostic in route_feedback.diagnostics
    )


def test_completed_proof_must_preserve_the_formal_sketch_scaffold() -> None:
    draft = GeneratedDraft("Use add-zero.", "draft-model", "Use add-zero.")
    sketch_code = (
        "import Mathlib\n\n"
        "theorem add_zero_nat (n : Nat) : n + 0 = n := by\n"
        "  have h : n + 0 = n := by\n"
        "    sorry\n"
        "  exact h"
    )
    sketch = GeneratedSketch(
        sketch_code,
        "sketch-model",
        f"```lean\n{sketch_code}\n```",
        has_gaps=True,
    )
    preserved = GeneratedProof(
        lean_code=FIXED_REPAIRABLE_CODE.replace(
            "  simpa using Nat.add_zero n",
            "  have h : n + 0 = n := by\n    simpa using Nat.add_zero n\n  exact h",
        ),
        model="prove-model",
        raw_model_output="",
        draft=draft,
        sketch=sketch,
    )
    replaced = GeneratedProof(
        lean_code=FIXED_REPAIRABLE_CODE,
        model="prove-model",
        raw_model_output="",
        draft=draft,
        sketch=sketch,
    )

    assert _validate_proof_preserves_sketch(preserved) == []
    diagnostics = _validate_proof_preserves_sketch(replaced)
    assert diagnostics[0].code == "pals.sketch_contract_mismatch"


def test_completed_proof_may_replace_refine_gap_syntax_while_preserving_structure() -> None:
    sketch_code = (
        "import Mathlib\n\n"
        "theorem positive_witness : ∃ n : Nat, n = n := by\n"
        "  refine ⟨0, by\n"
        "    sorry⟩\n"
        "  have h : True := by trivial"
    )
    proof_code = (
        "import Mathlib\n\n"
        "theorem positive_witness : ∃ n : Nat, n = n := by\n"
        "  refine ⟨0, ?_⟩\n"
        "  have h : True := by trivial\n"
        "  rfl"
    )
    generated = GeneratedProof(
        lean_code=proof_code,
        model="prove-model",
        raw_model_output="",
        sketch=GeneratedSketch(
            lean_code=sketch_code,
            model="sketch-model",
            raw_model_output="",
            has_gaps=True,
        ),
    )

    assert _validate_proof_preserves_sketch(generated) == []


@pytest.mark.parametrize("has_gaps", [False, True])
def test_completed_proof_cannot_drop_named_sketch_structure(has_gaps: bool) -> None:
    sketch_code = (
        "import Mathlib\n\n"
        "theorem structured : True := by\n"
        f"  have retained : True := by {'sorry' if has_gaps else 'trivial'}\n"
        "  exact retained"
    )
    generated = GeneratedProof(
        lean_code="import Mathlib\n\ntheorem structured : True := by\n  trivial",
        model="prove-model",
        raw_model_output="",
        sketch=GeneratedSketch(
            lean_code=sketch_code,
            model="sketch-model",
            raw_model_output="",
            has_gaps=has_gaps,
        ),
    )

    diagnostics = _validate_proof_preserves_sketch(generated)

    assert diagnostics[0].code == "pals.sketch_contract_mismatch"
    assert "have retained : True" in diagnostics[0].message


def test_benchmark_oracle_ignores_the_model_chosen_theorem_name(tmp_path: Path) -> None:
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=RenamedContinuousGenerator(),
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_problem(problem=BENCHMARK_PROBLEMS[0])

    assert result.state == "verified"
    assert verifier.calls


def test_exact_draft_method_does_not_override_explicit_formal_identity(
    tmp_path: Path,
) -> None:
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=ShortSquareGenerator(),
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement=BENCHMARK_PROBLEMS[0].prompt,
        formal_statement=(
            "theorem model_chosen_square_name : Continuous (fun x : ℝ => x ^ 2) := by"
        ),
        proof_job_id="exact-draft-preflight",
    )

    assert result.state == "verified"
    assert verifier.calls == [result.generated.lean_code]


def test_benchmark_oracle_compares_theorem_type_not_term_proof_syntax() -> None:
    request = ProofRequest(id="compact_image", prompt=BENCHMARK_PROBLEMS[2].prompt)
    code = """import Mathlib

theorem model_compact_image {α β : Type*} [TopologicalSpace α]
    [TopologicalSpace β] {s : Set α} {f : α → β}
    (hs : IsCompact s) (hf : ContinuousOn f s) : IsCompact (f '' s) :=
  hs.image_of_continuousOn hf
"""
    harness = (
        "theorem pals_compact_image {α β : Type*} [TopologicalSpace α] "
        "[TopologicalSpace β] {s : Set α} {f : α → β} (hs : IsCompact s) "
        "(hf : ContinuousOn f s) : IsCompact (f '' s) := by"
    )

    assert (
        validate_generated_lean(
            request,
            code,
            verification_harness=harness,
            allow_theorem_name_variance=True,
        )
        == []
    )


def test_pipeline_fails_when_model_returns_no_lean_code(tmp_path: Path) -> None:
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=EmptyGenerator(),
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_problem(
        problem=BENCHMARK_PROBLEMS[0],
        proof_job_id="job-1",
    )

    assert result.state == "failed"
    assert verifier.calls == []
    assert result.verification.diagnostics[0].code == "pals.generation_empty"
    assert result.artifact.uri.endswith("job-1/result.json")


def test_pipeline_surfaces_openai_generation_errors(tmp_path: Path) -> None:
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=OpenAIErrorGenerator(),
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_problem(
        problem=BENCHMARK_PROBLEMS[0],
        proof_job_id="job-1",
    )

    assert result.state == "failed"
    assert verifier.calls == []
    metadata = json.loads((tmp_path / "job-1" / "result.json").read_text())
    assert metadata["diagnostics"][0]["code"] == "openai.error"
    assert [diagnostic.code for diagnostic in result.verification.diagnostics] == [
        "openai.error",
        "pals.generation_empty",
    ]


def test_benchmark_expectations_do_not_mutate_runtime_verification(
    tmp_path: Path,
) -> None:
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=WrongStatementGenerator(),
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_problem(
        problem=BENCHMARK_PROBLEMS[0],
        proof_job_id="job-1",
    )

    assert result.state == "verified"
    assert verifier.calls == [result.generated.lean_code]
    assert all(
        not (diagnostic.code or "").startswith("benchmark.")
        for diagnostic in result.verification.diagnostics
    )


def test_pipeline_rejects_commented_fragment_spoof(
    tmp_path: Path,
) -> None:
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=CommentSpoofedFragmentGenerator(),
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement=BENCHMARK_PROBLEMS[0].prompt,
        formal_statement=("theorem expected_square : Continuous (fun x : ℝ => x ^ 2) := by"),
        proof_job_id="job-1",
    )

    assert result.state == "failed"
    assert len(verifier.calls) == 0
    assert result.verification.diagnostics[0].code == "lean.formal_harness_mismatch"


def test_pipeline_rejects_string_literal_formal_harness_spoof(
    tmp_path: Path,
) -> None:
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=StringSpoofedFormalHarnessGenerator(),
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement=BENCHMARK_PROBLEMS[0].prompt,
        formal_statement=("theorem expected_square : Continuous (fun x : ℝ => x ^ 2) := by"),
        proof_job_id="job-1",
    )

    assert result.state == "failed"
    assert len(verifier.calls) == 0
    assert result.verification.diagnostics[0].code == "lean.formal_harness_mismatch"


def test_pipeline_rejects_syntax_quotation_formal_harness_spoof(
    tmp_path: Path,
) -> None:
    pipeline = ProofPipeline(
        generator=SyntaxQuotationSpoofGenerator(),
        verifier=LeanVerifier(lean_binary="missing-lean"),
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_problem(
        problem=BENCHMARK_PROBLEMS[0],
        proof_job_id="job-1",
    )

    assert result.state == "failed"
    assert result.verification.diagnostics[0].code == "lean.disallowed_metaprogramming"


def test_continuous_square_draft_keeps_epsilon_delta_strategy_and_sketch() -> None:
    problem = BENCHMARK_PROBLEMS[0]
    draft = SeedDraftCatalog().find_by_id(problem.id)

    assert draft is not None
    assert "epsilon-delta" in draft.proof_strategy
    assert any("ε" in step for step in draft.sketch_steps)
    assert "Do not close the proof with shortcut continuity lemmas" in draft.proof_strategy


def test_pipeline_compiles_self_contained_code_without_a_supplied_formal_identity(
    tmp_path: Path,
) -> None:
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=WrongStatementGenerator(),
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_problem(
        problem=BenchmarkProblem(
            id="custom_statement",
            prompt="prove anything",
        ),
        proof_job_id="job-1",
    )

    assert result.state == "verified"
    assert verifier.calls == [result.generated.lean_code]


def test_compile_diagnostics_reach_repair_without_a_supplied_formal_identity(
    tmp_path: Path,
) -> None:
    generator = AlwaysBrokenRepairingGenerator()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=ContentAwareVerifier(),
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_problem(
        problem=BenchmarkProblem(id="custom_statement", prompt="prove anything"),
        proof_job_id="missing-harness-no-repair",
    )

    assert result.state == "failed"
    assert len(generator.route_feedback) == pipeline.max_repair_attempts
    assert len(generator.feedback) == pipeline.max_repair_attempts
    assert all(
        feedback.diagnostics[0].code == "lean.unknown_identifier"
        for feedback in generator.route_feedback
    )


def test_approximate_draft_is_context_only_without_becoming_formal_identity(
    tmp_path: Path,
) -> None:
    generator = RecordingContinuousGenerator()
    verifier = FakeVerifier()
    statuses: list[tuple[str, dict[str, object]]] = []
    catalog = ApproximateSquareDraftCatalog()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=catalog,
    )

    result = pipeline.run_statement(
        statement="x^3が連続であることを示せ",
        proof_job_id="job-cubed",
        on_status=lambda state, diagnostics, uri, lean_code, context: statuses.append(
            (state, context)
        ),
    )

    assert result.state == "verified"
    assert verifier.calls == [result.generated.lean_code]
    request = generator.requests[0]
    assert request.draft == catalog.draft
    assert request.formal_statement is None
    assert request.query_openmath_xml == catalog.query_openmath_xml
    assert request.vector_score == pytest.approx(0.98)
    assert request.structural_score == pytest.approx(0.94)
    assert request.final_score == pytest.approx(0.956)
    assert request.exact_equivalence is False

    prompt = _prompt_for(request)
    assert "Target-agnostic related Draft context" in prompt
    assert "Related strategy notes after target redaction" in prompt
    assert "Related sketch pattern after target redaction" in prompt
    assert "pals_continuous_square" not in prompt
    assert "x ^ 2" not in prompt
    assert "x^2" not in prompt
    assert "2 * |x|" not in prompt
    assert request.related_draft_context is not None
    assert request.related_draft_context.strategy_notes
    assert request.related_draft_context.sketch_steps
    assert request.related_draft_context.source_draft_id == "continuous_square"
    assert all(note in prompt for note in request.related_draft_context.strategy_notes)
    assert all(step in prompt for step in request.related_draft_context.sketch_steps)

    routes: tuple[RepairRoute, ...] = ("draft", "sketch", "prove")
    for route in routes:
        repair_prompt = _prompt_for(
            request,
            feedback=GenerationFeedback(
                attempt=1,
                previous_lean_code="example : True := by trivial",
                diagnostics=(Diagnostic(severity="error", message="failed"),),
                repair_route=route,
            ),
        )
        assert "Target-agnostic related Draft context" in repair_prompt
        assert all(note in repair_prompt for note in request.related_draft_context.strategy_notes)
        assert all(step in repair_prompt for step in request.related_draft_context.sketch_steps)

    metadata = json.loads((tmp_path / "job-cubed" / "result.json").read_text())
    assert metadata["problem_id"] == "custom_statement"
    assert metadata["draft_id"] == "continuous_square"
    retrieval = metadata["retrieval"]
    assert retrieval == {
        "candidate_draft_id": "continuous_square",
        "candidate_openmath_xml": catalog.draft.openmath_xml,
        "exact_equivalence": False,
        "formal_statement_source": None,
        "query_openmath_xml": catalog.query_openmath_xml,
        "related_context": {
            "sketch_steps": list(request.related_draft_context.sketch_steps),
            "source_draft_id": "continuous_square",
            "strategy_notes": list(request.related_draft_context.strategy_notes),
        },
        "scores": {"final": 0.956, "structural": 0.94, "vector": 0.98},
    }
    assert statuses
    assert all(context["retrieval"] == retrieval for _state, context in statuses)


def test_plain_square_continuity_input_retrieves_epsilon_delta_strategy_without_hidden_harness(
    tmp_path: Path,
) -> None:
    generator = RecordingContinuousGenerator()
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="x^2が連続であることを示せ",
        proof_job_id="job-exact-without-harness",
    )

    assert result.state == "verified"
    assert verifier.calls == [result.generated.lean_code]
    assert generator.requests[0].exact_equivalence is True
    assert generator.requests[0].formal_statement is None
    draft = generator.requests[0].draft
    assert draft is not None
    assert draft.proof_strategy in generator.prompts[0]
    assert all(step in generator.prompts[0] for step in draft.sketch_steps)
    assert "Metric.continuous_iff" in result.generated.lean_code
    assert "intro x ε" in result.generated.lean_code
    assert "let δ" in result.generated.lean_code
    assert "continuous_id.pow" not in result.generated.lean_code


def test_plain_square_input_reaches_epsilon_delta_through_the_proof_flow_runtime(
    tmp_path: Path,
) -> None:
    statement = "x² が連続であることを説明してください。"
    source_draft = SeedDraftCatalog().find_by_id("continuous_square")
    assert source_draft is not None
    draft = replace(
        source_draft,
        openmath_xml=canonicalize_retrieval_openmath_xml(source_draft.openmath_xml),
    )
    fingerprint = DraftEmbeddingFingerprint(
        provider="openai",
        model="text-embedding-3-small",
        endpoint="https://api.openai.com/v1",
        deployment="text-embedding-3-small",
        revision="2026-07-31",
        dimension=2,
    )
    structurer = RecordingStructurer(
        {statement: source_draft.openmath_xml},
        default_xml=source_draft.openmath_xml,
    )
    candidates = SquareCandidateResponse(
        draft=draft,
        fingerprint=fingerprint,
        calls=[],
    )
    reranker = SquareRerankerResponse(calls=[])
    retriever = ProofFlowRuntime(
        structurer=structurer,
        embedding_model=UnitEmbeddingModel(calls=[]),
        embedding_fingerprint=fingerprint,
        runtime_provenance_sha256="b" * 64,
        candidate_client=candidates,
        reranker=reranker,
    )
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=ShortSquareGenerator(),
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        proof_flow_retriever=retriever,
    )

    request = pipeline.prepare_statement(statement=statement)
    result = pipeline.run_statement(
        statement=statement,
        proof_job_id="exact-proof-flow-square-method",
        prepared_request=request,
    )
    with pytest.raises(ValueError, match="does not match"):
        pipeline.run_statement(
            statement="A different theorem",
            proof_job_id="wrong-statement",
            prepared_request=request,
        )

    assert structurer.statements == [statement]
    assert len(candidates.calls) == 1
    assert len(reranker.calls) == 1
    assert result.state == "failed"
    assert verifier.calls == []
    assert result.verification.diagnostics[-1].code == "pals.proof_method_mismatch"
    assert request.related_draft_contexts[0].exact_equivalence is True
    assert request.related_draft_contexts[0].selected_proof_method == "epsilon_delta"
    assert "Required ε–δ proof method from exact retrieved Draft" in _prompt_for(request)
    assert validate_generated_lean(request, EPSILON_DELTA_SQUARE_CODE) == []


def test_retrieval_canonical_binder_names_never_replace_the_learner_problem(
    tmp_path: Path,
) -> None:
    """OpenMath alpha-normalization is a retrieval key, never generation input."""
    statement = "関数 t ↦ t^2 が実数全体で連続であることを示してください。"
    source_draft = SeedDraftCatalog().find_by_id("continuous_square")
    assert source_draft is not None
    source_xml = source_draft.openmath_xml.replace('name="x"', 'name="t"')
    query_openmath = canonicalize_retrieval_openmath_xml(source_xml)
    assert 'name="v1"' in query_openmath

    fingerprint = DraftEmbeddingFingerprint(
        provider="openai",
        model="text-embedding-3-small",
        endpoint="https://api.openai.com/v1",
        deployment="text-embedding-3-small",
        revision="2026-07-31",
        dimension=2,
    )
    retriever = ProofFlowRuntime(
        structurer=RecordingStructurer({statement: source_xml}, default_xml=source_xml),
        embedding_model=UnitEmbeddingModel(calls=[]),
        embedding_fingerprint=fingerprint,
        runtime_provenance_sha256="b" * 64,
        candidate_client=SquareCandidateResponse(
            draft=replace(source_draft, openmath_xml=query_openmath),
            fingerprint=fingerprint,
            calls=[],
        ),
        reranker=SquareRerankerResponse(calls=[]),
    )
    pipeline = ProofPipeline(
        generator=RecordingContinuousGenerator(),
        verifier=FakeVerifier(),
        artifact_store=FileArtifactStore(tmp_path),
        proof_flow_retriever=retriever,
    )

    request = pipeline._request_for_statement(statement)
    generation_prompt = _prompt_for(request)

    assert request.prompt == statement
    assert request.query_openmath_xml == query_openmath
    assert statement in generation_prompt
    assert 'name="v1"' not in generation_prompt


def test_approximate_or_reranked_square_context_does_not_select_a_method() -> None:
    draft = SeedDraftCatalog().find_by_id("continuous_square")
    assert draft is not None
    request = ProofRequest(
        id="custom_statement",
        prompt="別の連続性を説明してください。",
        related_draft_contexts=(
            RelatedDraftContext(
                source_draft_id=draft.id,
                strategy_notes=("A nearby draft mentions epsilon-delta.",),
                sketch_steps=("Use an appropriate local bound.",),
                exact_equivalence=False,
            ),
        ),
    )

    generated = ShortSquareGenerator().generate(request)
    assert validate_generated_lean(request, generated.lean_code) == []
    assert "advisory only" in _prompt_for(request)


def test_approximate_square_draft_cannot_verify_supplied_cube_target(
    tmp_path: Path,
) -> None:
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=ContinuousGenerator(),
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=ApproximateSquareDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="x^3が連続であることを示せ",
        formal_statement=("theorem pals_continuous_cube : Continuous (fun x : ℝ => x ^ 3) := by"),
        proof_job_id="job-cube-with-harness",
    )

    assert result.state == "failed"
    assert verifier.calls == []
    assert result.verification.diagnostics[0].code == "lean.formal_harness_mismatch"


def test_benchmark_runtime_performs_only_generated_code_compile(tmp_path: Path) -> None:
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=ContinuousGenerator(),
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_problem(
        problem=BenchmarkProblem(
            id="continuous_square",
            prompt="x^2が連続であることを示せ",
        ),
        proof_job_id="job-oracle-binding",
    )

    assert result.state == "verified"
    assert verifier.calls == [result.generated.lean_code]


def test_pipeline_verifies_custom_statement_code_that_contains_formal_harness(
    tmp_path: Path,
) -> None:
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=FormalStatementGenerator(),
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id="job-1",
    )

    assert result.state == "verified"
    assert len(verifier.calls) == 1
    assert "theorem add_zero_nat" in verifier.calls[0]


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


def test_pipeline_default_allows_five_llm_selected_repairs(tmp_path: Path) -> None:
    generator = SucceedsOnFifthRepairGenerator()
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
        proof_job_id="five-repair-job",
    )

    assert result.state == "verified"
    assert len(generator.feedback) == 5
    assert len(generator.route_feedback) == 5
    assert [feedback.attempt for feedback in generator.feedback] == [1, 2, 3, 4, 5]
    assert verifier.calls == [BROKEN_REPAIRABLE_CODE] * 5 + [FIXED_REPAIRABLE_CODE]
    assert any(
        diagnostic.code == "pals.repair_stagnation"
        for diagnostic in generator.route_feedback[2].diagnostics
    )


def test_pae_016_default_budget_can_verify_on_twelfth_repair_and_persists_order(
    tmp_path: Path,
) -> None:
    generator = SucceedsOnNthRepairGenerator(12)
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
        proof_job_id="repair-twelve",
    )

    assert result.state == "verified"
    assert len(generator.feedback) == 12
    metadata = json.loads((tmp_path / "repair-twelve" / "result.json").read_text(encoding="utf-8"))
    assert metadata["repairs_used"] == 12
    assert metadata["termination_reason"] == "verified"
    assert [attempt["attempt"] for attempt in metadata["attempts"]] == list(range(1, 14))
    assert all(
        set(attempt) >= {"attempt", "phase", "generated", "verification", "diagnostics"}
        for attempt in metadata["attempts"]
    )
    assert "repair_route" not in metadata["attempts"][0]
    assert all("repair_route" in attempt for attempt in metadata["attempts"][1:])
    checkpoint_paths = sorted((tmp_path / "repair-twelve" / "attempts").glob("*.json"))
    assert [path.name for path in checkpoint_paths] == [
        f"{attempt:04d}.json" for attempt in range(1, 14)
    ]
    for attempt_number, checkpoint_path in enumerate(checkpoint_paths, start=1):
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert checkpoint["checkpoint_schema_version"] == 1
        assert checkpoint["run_id"] == "repair-twelve"
        assert checkpoint["problem_id"] == "custom_statement"
        assert checkpoint["max_repair_attempts"] == 12
        assert checkpoint["attempt"] == metadata["attempts"][attempt_number - 1]


def test_pae_016_default_budget_exhaustion_runs_all_twelve_repairs(
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
    assert len(generator.feedback) == 12
    metadata = json.loads(
        (tmp_path / "repair-exhausted" / "result.json").read_text(encoding="utf-8")
    )
    assert len(metadata["attempts"]) == 13
    assert metadata["repairs_used"] == 12
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


def test_pipeline_rejects_custom_statement_code_that_omits_formal_harness(
    tmp_path: Path,
) -> None:
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=WrongStatementGenerator(),
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement="theorem add_zero_nat (n : Nat) : n + 0 = n := by",
        proof_job_id="job-1",
    )

    assert result.state == "failed"
    assert verifier.calls == []
    assert result.verification.diagnostics[0].code == "lean.formal_harness_mismatch"


def test_file_artifact_store_rejects_path_traversal(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="Unsafe artifact run id"):
        store.save(run_id="../../outside", lean_code="", metadata={})


def test_pae_016_file_attempt_checkpoint_is_create_only(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path)
    original = {"checkpoint_schema_version": 1, "attempt": {"attempt": 1}}

    store.save_checkpoint(run_id="immutable-run", attempt=1, metadata=original)

    with pytest.raises(FileExistsError):
        store.save_checkpoint(
            run_id="immutable-run",
            attempt=1,
            metadata={"checkpoint_schema_version": 1, "attempt": {"attempt": 999}},
        )
    persisted = json.loads(
        (tmp_path / "immutable-run" / "attempts" / "0001.json").read_text(encoding="utf-8")
    )
    assert persisted == original


def test_worker_prompt_mapping_requires_exact_benchmark_match() -> None:
    problem = _problem_for_statement("prove something else; x^2が連続であることを示せ")

    assert problem.id == "custom_statement"


def test_run_statement_passes_formal_statement_to_generator(tmp_path: Path) -> None:
    generator = FormalStatementCapturingGenerator()

    pipeline = ProofPipeline(
        generator=generator,
        verifier=FakeVerifier(),
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="x^2が連続であることを示せ",
        formal_statement="example : Continuous fun x : ℝ => x ^ 2 := by",
        proof_job_id="job-1",
    )

    assert result.state == "verified"
    assert generator.requests == [
        ProofRequest(
            id="continuous_square",
            prompt="x^2が連続であることを示せ",
            formal_statement="example : Continuous fun x : ℝ => x ^ 2 := by",
        )
    ]


def test_user_formal_statement_overrides_matched_draft_harness(tmp_path: Path) -> None:
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=ContinuousGenerator(),
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_statement(
        statement="x^2が連続であることを示せ",
        formal_statement="example : Continuous fun x : ℝ => x ^ 2 := by",
        proof_job_id="job-1",
    )

    assert result.state == "failed"
    assert verifier.calls == []
    assert result.verification.diagnostics[0].code == "lean.formal_harness_mismatch"
