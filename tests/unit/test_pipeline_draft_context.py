"""Retrieved and approximate drafts inform, but never replace, the learner problem.

Moved out of test_pipeline.py (pals#487).
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from pals_agent.artifacts import FileArtifactStore
from pals_agent.draft_catalog import SeedDraftCatalog
from pals_agent.generator import _prompt_for
from pals_agent.models import (
    Diagnostic,
    GenerationFeedback,
    ProofRequest,
    RelatedDraftContext,
    RepairRoute,
)
from pals_agent.openmath import canonicalize_retrieval_openmath_xml
from pals_agent.pipeline import (
    ProofPipeline,
    validate_generated_lean,
)
from pals_agent.private_draft_candidates import (
    DraftEmbeddingFingerprint,
)
from pals_agent.proof_flow_runtime import ProofFlowRuntime
from tests.unit.pipeline_support import (
    EPSILON_DELTA_SQUARE_CODE,
    ApproximateSquareDraftCatalog,
    ContinuousGenerator,
    FakeVerifier,
    RecordingContinuousGenerator,
    RecordingStructurer,
    ShortSquareGenerator,
    SquareCandidateResponse,
    SquareRerankerResponse,
    StatementSeedDraftCatalog,
    UnitEmbeddingModel,
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
