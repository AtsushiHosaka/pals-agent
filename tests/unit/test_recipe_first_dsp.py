"""Recipe miss enters full DSP, with natural Draft hints inside its Draft stage.

Catalog/model doubles isolate only external ports; production factory/pipeline/worker run.
"""

from types import SimpleNamespace
from typing import cast

import pytest

from pals_agent.artifacts import FileArtifactStore
from pals_agent.factory import build_pipeline
from pals_agent.models import ProofDraft
from pals_agent.natural_draft_evidence import NaturalDraftContext, NaturalDraftRetrievalResult
from pals_agent.pipeline import ProofPipeline
from pals_agent.private_draft_candidates import DraftCandidate
from pals_agent.proof_flow_runtime import ProofFlowRetrievalError
from pals_agent.proof_reuse import ProofReuseError
from pals_agent.proof_reuse_catalog import NaturalDspDraftRetriever
from pals_agent.settings import AgentSettings
from pals_agent.worker import SqsProofWorker, _api_repair_seed_from_worker_input
from tests.unit.test_api_repair_stagnation import resource
from tests.unit.test_pipeline import RecordingStagedGenerator
from tests.unit.test_repair_runtime_spec import ApiRepairGenerator
from tests.unit.test_worker import ExplainerThatMustNotRun, RecordingApi


class Catalog:
    def __init__(self, *, error=None):
        self.calls, self.error = [], error

    def retrieve(self, statement, profile_id, *, deadline):
        self.calls.append((statement, profile_id, deadline))
        if self.error:
            raise self.error
        draft = ProofDraft(
            "add_zero_hint",
            "Every natural number plus zero is itself",
            "<OMOBJ/>",
            "Apply the additive identity law.",
            ("Use the identity.",),
        )
        return NaturalDraftRetrievalResult(
            "match",
            "<OMOBJ/>",
            (NaturalDraftContext(DraftCandidate(draft, 0.17)),),
            {"evidence_kind": "unverified_strategy", "source_revision": "actual-db-revision"},
        )


def pipeline(tmp_path, catalog, generator=None):
    return ProofPipeline(
        generator=generator or RecordingStagedGenerator(),
        verifier=None,
        artifact_store=FileArtifactStore(tmp_path),
        verification_mode="api_reconcile",
        natural_draft_retriever=NaturalDspDraftRetriever(catalog),
    )


def test_linked_dsp_retrieves_real_natural_result_once_and_never_fabricates_formal_evidence(
    tmp_path,
):
    class CapturingStagedGenerator(RecordingStagedGenerator):
        def generate_draft(self, request, feedback=None):
            self.request = request
            return super().generate_draft(request, feedback)

    catalog = Catalog()
    generator = CapturingStagedGenerator()
    engine = pipeline(tmp_path, catalog, generator)
    statuses = []
    result = engine.run_statement(
        statement="Prove n+0=n for natural n",
        proof_job_id="dsp-natural",
        request_linked=True,
        on_status=lambda state, d, a, code, context: statuses.append((state, context)),
    )
    assert result.verification_pending and result.state == "compiling"
    assert len(catalog.calls) == 1 and catalog.calls[0][1] == "generic-v1"
    assert engine.generator.calls == ["draft", "sketch", "prove"]
    initial = statuses[0][1]
    raw = initial["retrieval"]["proof_flow_result"]
    assert raw["schema_version"] == "pals.natural-draft-retrieval.v1"
    assert raw["contexts"][0]["cosine_distance"] == 0.17
    assert "structural_score" not in raw["contexts"][0]
    assert "vector_score" not in raw["contexts"][0]
    assert "exact_equivalence" not in raw["contexts"][0]
    assert initial["retrieval"]["formal_statement_source"] is None
    prepared = engine._request_for_statement("legacy ordinary statement")
    assert prepared.related_draft_contexts == ()  # ordinary route retains its own catalog
    request = statuses[1][1]["draft"]["related_contexts"][0]
    assert generator.request.related_draft_contexts[0].exact_equivalence is False
    assert request["strategy_notes"] == ["Apply the additive identity law."]


def test_api_repair_uses_durable_seed_without_new_draft_retrieval(tmp_path):
    catalog = Catalog(error=AssertionError("API repair must not query Draft DB"))
    generator = ApiRepairGenerator()
    engine = pipeline(tmp_path, catalog, generator)
    seed = _api_repair_seed_from_worker_input(resource())
    assert seed is not None
    result = engine.run_statement(
        statement="Prove True",
        proof_job_id="repair-natural",
        request_linked=True,
        api_repair_seed=seed,
    )
    assert result.verification_pending and catalog.calls == []
    assert generator.generate_calls == 0 and len(generator.repair_feedback) == 1


def test_natural_catalog_outage_fails_closed_in_dsp_instead_of_becoming_empty_hints(tmp_path):
    catalog = Catalog(error=ProofReuseError("proof_reuse_catalog_unavailable"))
    engine = pipeline(tmp_path, catalog)
    with pytest.raises(ProofFlowRetrievalError):
        engine.run_statement(statement="Prove True", proof_job_id="failure", request_linked=True)
    assert engine.generator.calls == []


def test_unrepresentable_draft_query_keeps_full_original_goal_and_runs_dsp(tmp_path):
    catalog = Catalog(error=ProofReuseError("proof_reuse_query_invalid"))
    engine = pipeline(tmp_path, catalog)
    statuses = []
    result = engine.run_statement(
        statement="Prove the full original Lean goal", proof_job_id="no-query",
        request_linked=True,
        on_status=lambda state, d, a, code, context: statuses.append(context),
    )
    assert result.verification_pending
    assert engine.generator.calls == ["draft", "sketch", "prove"]
    retrieval = statuses[0]["retrieval"]["proof_flow_result"]
    assert retrieval["contexts"] == [] and retrieval["query_openmath"] == ""
    assert retrieval["compatibility"]["reason"] == "query_invalid"
    assert retrieval["compatibility"]["catalog_query_performed"] == 0


def test_factory_wires_natural_drafts_for_linked_requests_without_pfi_or_typed_catalog(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")
    monkeypatch.setenv("PALS_ARTIFACTS_BUCKET", "unit-test-bucket")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "unit-test-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "unit-test-secret")
    monkeypatch.delenv("PALS_PFI_RUNTIME_PROVENANCE_SHA256", raising=False)
    monkeypatch.delenv("PALS_TYPED_CATALOG_ENABLED", raising=False)
    engine = build_pipeline(AgentSettings.from_env())
    assert engine.proof_flow_retriever is None
    assert isinstance(engine.natural_draft_retriever, NaturalDspDraftRetriever)


def test_worker_disables_both_recipe_selection_branches_for_request_linked_dsp():
    class LinkedApi(RecordingApi):
        def get_proof_job(self, proof_job_id):
            return dict(
                super().get_proof_job(proof_job_id),
                request_context={
                    "proof_request_id": "11111111-1111-4111-8111-111111111111",
                    "formal_statement": "True",
                },
            )

    class NoSecondRecipeSelection:
        def decide(self, **kwargs):
            raise AssertionError("Recipe selection already happened before DSP")

    class PipelineBoundary:
        def prepare_statement(self, **kwargs):
            raise AssertionError("must not pre-search Draft before DSP")

        def run_statement(self, *, request_linked, on_status, **kwargs):
            assert request_linked is True
            on_status("failed", [], None, None, {})
            return SimpleNamespace(verification_pending=False)

    api = LinkedApi()
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace()),
        api_client=api,
        pipeline=PipelineBoundary(),
        explainer=ExplainerThatMustNotRun(),
        recipe_attempt_planner=NoSecondRecipeSelection(),
    )
    assert worker.process_proof_job(
        "job-1", claim_id="11111111-1111-4111-8111-111111111111", extend_visibility=lambda _: None
    )
