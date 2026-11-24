import json
from pathlib import Path

import pytest

from pals_agent.artifacts import FileArtifactStore
from pals_agent.benchmarks import BENCHMARK_PROBLEMS
from pals_agent.draft_catalog import SeedDraftCatalog
from pals_agent.lean import LeanVerifier
from pals_agent.models import (
    BenchmarkProblem,
    GeneratedDraft,
    GeneratedProof,
    GeneratedSketch,
    ProofRequest,
)
from pals_agent.pipeline import (
    ProofPipeline,
    _problem_for_statement,
    _validate_proof_preserves_sketch,
    validate_generated_lean,
)
from tests.unit.pipeline_support import (  # noqa: F401
    BROKEN_REPAIRABLE_CODE,
    EPSILON_DELTA_SQUARE_CODE,
    FIXED_REPAIRABLE_CODE,
    MODEL_CONTINUOUS_CODE,
    AlwaysBrokenRepairingGenerator,
    ApproximateSquareDraftCatalog,
    CommentSpoofedFragmentGenerator,
    ContentAwareVerifier,
    ContinuousGenerator,
    EmptyGenerator,
    EmptyThenRepairingGenerator,
    FakeVerifier,
    FormalStatementCapturingGenerator,
    FormalStatementGenerator,
    InterruptingRouteGenerator,
    MissingLeanProjectVerifier,
    OpenAIErrorGenerator,
    RecordingContinuousGenerator,
    RecordingStagedGenerator,
    RecordingStructurer,
    RenamedContinuousGenerator,
    RepairingGenerator,
    RepairingStagedGenerator,
    RepairWithoutRouteSelectorGenerator,
    ShortSquareGenerator,
    SketchMismatchInterruptingGenerator,
    SketchMismatchSuccessfulLeanGenerator,
    SquareCandidateResponse,
    SquareRerankerResponse,
    StatementSeedDraftCatalog,
    StringSpoofedFormalHarnessGenerator,
    SucceedsOnNthRepairGenerator,
    SyntaxQuotationSpoofGenerator,
    UnitEmbeddingModel,
    WrongStatementGenerator,
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


def test_generation_empty_names_the_stage_failure_that_explains_it(tmp_path: Path) -> None:
    pipeline = ProofPipeline(
        generator=OpenAIErrorGenerator(),
        verifier=FakeVerifier(),
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_problem(problem=BENCHMARK_PROBLEMS[0], proof_job_id="job-1")

    empty = [d for d in result.verification.diagnostics if d.code == "pals.generation_empty"]
    assert [d.metadata for d in empty] == [{"explained_by": "openai.error"}]


def test_generation_empty_is_unexplained_only_when_the_model_returned_nothing(
    tmp_path: Path,
) -> None:
    pipeline = ProofPipeline(
        generator=EmptyGenerator(),
        verifier=FakeVerifier(),
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StatementSeedDraftCatalog(),
    )

    result = pipeline.run_problem(problem=BENCHMARK_PROBLEMS[0], proof_job_id="job-1")

    empty = [d for d in result.verification.diagnostics if d.code == "pals.generation_empty"]
    assert [d.metadata for d in empty] == [{"explained_by": "none"}]


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
