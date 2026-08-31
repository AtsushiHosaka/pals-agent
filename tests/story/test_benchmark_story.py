from pathlib import Path

from pals_agent.artifacts import FileArtifactStore
from pals_agent.benchmarks import BENCHMARK_PROBLEMS
from pals_agent.draft_catalog import DraftSearchResult, SeedDraftCatalog
from pals_agent.models import GeneratedProof, ProofDraft, ProofRequest, VerificationResult
from pals_agent.openmath import canonicalize_openmath_xml
from pals_agent.pipeline import ProofPipeline


class StoryGenerator:
    def generate(self, request: ProofRequest) -> GeneratedProof:
        return GeneratedProof(
            lean_code=f"-- generated for {request.id}\nexample : True := by\n  trivial",
            model="story-model",
            raw_model_output="story",
        )


class StoryVerifier:
    def verify(self, lean_code: str) -> VerificationResult:
        return VerificationResult(
            success=True,
            diagnostics=[],
            stdout="",
            stderr="",
            elapsed_ms=1,
        )


class StoryDraftCatalog:
    def __init__(self) -> None:
        self.seed = SeedDraftCatalog()

    def find_by_statement(self, statement: str) -> ProofDraft | None:
        return next(
            (
                draft
                for draft in self.seed.all_drafts()
                if draft.matched_prompt == statement
            ),
            None,
        )

    def search_by_statement(self, statement: str) -> DraftSearchResult | None:
        draft = self.find_by_statement(statement)
        if draft is None:
            return None
        query_xml = canonicalize_openmath_xml(draft.openmath_xml)
        return DraftSearchResult(
            draft=draft,
            query_openmath_xml=query_xml,
            vector_score=1.0,
            structural_score=1.0,
            final_score=1.0,
            exact_equivalence=(
                query_xml == canonicalize_openmath_xml(draft.openmath_xml)
            ),
        )

    def find_by_openmath(self, openmath_xml: str) -> ProofDraft | None:
        _ = openmath_xml
        return None

    def find_by_id(self, draft_id: str) -> ProofDraft | None:
        return self.seed.find_by_id(draft_id)


def test_three_benchmark_runtime_inputs_do_not_receive_evaluator_oracles(
    tmp_path: Path,
) -> None:
    pipeline = ProofPipeline(
        generator=StoryGenerator(),
        verifier=StoryVerifier(),
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=StoryDraftCatalog(),
    )

    results = [pipeline.run_problem(problem=problem) for problem in BENCHMARK_PROBLEMS]

    assert [result.problem_id for result in results] == [
        "continuous_square",
        "rank_nullity",
        "compact_image",
    ]
    assert all(result.verification.success for result in results)
    assert all(Path(result.artifact.lean_uri).exists() for result in results)
