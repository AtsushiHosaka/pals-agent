"""Test doubles shared by the pipeline tests (moved out of test_pipeline.py, pals#487).

Names are re-exported from ``tests.unit.test_pipeline``, which other test modules import them from.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pals_agent.benchmarks import BENCHMARK_PROBLEMS
from pals_agent.draft_catalog import DraftSearchResult, SeedDraftCatalog
from pals_agent.generator import _prompt_for
from pals_agent.models import (
    Diagnostic,
    GeneratedDraft,
    GeneratedProof,
    GeneratedSketch,
    GenerationFeedback,
    ProofDraft,
    ProofRequest,
    RepairRoute,
    RepairRouteAttemptEvidence,
    RepairRouteDecision,
    VerificationResult,
)
from pals_agent.openmath import canonicalize_openmath_xml
from pals_agent.private_draft_candidates import (
    DraftCandidate,
    DraftCandidateResult,
    DraftEmbeddingFingerprint,
)

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
