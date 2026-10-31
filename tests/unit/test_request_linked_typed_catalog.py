"""Opt-in composition tests; external retrieval/generation ports are isolated.

These tests never claim a real model, compiler, API job or publication succeeded.
"""

from dataclasses import replace

import pytest

from pals_agent.artifacts import FileArtifactStore
from pals_agent.factory import build_pipeline
from pals_agent.pipeline import ProofPipeline
from pals_agent.profile_routing import ProfileRoutedProofFlowRuntime
from pals_agent.proof_flow_runtime import DraftRetrievalResult
from pals_agent.settings import AgentSettings
from pals_agent.worker import _api_repair_seed_from_worker_input
from tests.unit.test_api_repair_stagnation import resource
from tests.unit.test_pipeline import RecordingStagedGenerator
from tests.unit.test_recipe_first_dsp import Catalog, pipeline
from tests.unit.test_repair_runtime_spec import ApiRepairGenerator

FLAG = "PALS_REQUEST_LINKED_TYPED_CATALOG_ENABLED"


def settings(monkeypatch, *, linked=None, typed=None):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")
    monkeypatch.setenv("PALS_ENV", "local")
    monkeypatch.setenv("PALS_WORKER_SHARED_SECRET", "unit-test-worker")
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.delenv("PALS_TYPED_CATALOG_ENABLED", raising=False)
    if linked is not None:
        monkeypatch.setenv(FLAG, linked)
    if typed is not None:
        monkeypatch.setenv("PALS_TYPED_CATALOG_ENABLED", typed)
    return AgentSettings.from_env()


def test_default_keeps_existing_linked_natural_path(monkeypatch, tmp_path):
    config = settings(monkeypatch)
    monkeypatch.setattr(
        "pals_agent.factory.build_artifact_store", lambda _: FileArtifactStore(tmp_path)
    )
    engine = build_pipeline(config)
    assert config.request_linked_typed_catalog_enabled is False
    assert engine.request_linked_typed_retriever is None
    assert engine.natural_draft_retriever is not None


@pytest.mark.parametrize("raw", ["yes", "1", "TRUE", "", "false "])
def test_new_flag_uses_existing_strict_boolean_contract(monkeypatch, raw):
    with pytest.raises(ValueError):
        settings(monkeypatch, linked=raw, typed="true")


def test_opt_in_requires_typed_and_formal_capability(monkeypatch):
    with pytest.raises(ValueError, match="requires typed catalog"):
        settings(monkeypatch, linked="true")
    config = settings(monkeypatch, linked="true", typed="true")
    with pytest.raises(ValueError, match="full proof capability"):
        replace(config, proof_capability="natural-only")


def test_factory_shares_typed_capability_and_retains_exact_natural_generic_port(
    monkeypatch, tmp_path
):
    config = settings(monkeypatch, linked="true", typed="true")
    monkeypatch.setattr(
        "pals_agent.factory.build_artifact_store", lambda _: FileArtifactStore(tmp_path)
    )
    engine = build_pipeline(config)
    linked = engine.request_linked_typed_retriever
    standalone = engine.proof_flow_retriever
    assert isinstance(linked, ProfileRoutedProofFlowRuntime)
    assert isinstance(standalone, ProfileRoutedProofFlowRuntime)
    assert linked.typed is standalone.typed
    assert linked.generic is engine.natural_draft_retriever


class UnavailableTyped:
    def __init__(self):
        self.calls = []

    def retrieve(self, statement):
        self.calls.append(statement)
        return DraftRetrievalResult("no_match", "", (), {"typed_selection": "unavailable"})


def test_opt_in_preserves_exact_original_goal_and_does_not_create_a_formal_claim(tmp_path):
    class CapturingGenerator(RecordingStagedGenerator):
        def generate_draft(self, request, feedback=None):
            self.request = request
            return super().generate_draft(request, feedback)

    catalog = Catalog()
    generator = CapturingGenerator()
    typed = UnavailableTyped()
    engine = replace(pipeline(tmp_path, catalog, generator), request_linked_typed_retriever=typed)
    statement = (
        "For every field K, prove the specified linear map is injective "
        "under exactly the given kernel assumption."
    )
    result = engine.run_statement(
        statement=statement, proof_job_id="owned-typed", request_linked=True
    )
    assert typed.calls == [statement]
    assert catalog.calls == []  # A typed failure must not search another profile.
    assert generator.request.prompt == statement
    assert generator.request.formal_statement is None
    assert generator.request.related_draft_contexts == ()
    assert result.verification_pending and result.state == "compiling"


def test_api_repair_still_uses_durable_seed_without_any_catalog_query(tmp_path):
    typed = UnavailableTyped()
    catalog = Catalog(error=AssertionError("no re-query during repair"))
    engine = replace(
        pipeline(tmp_path, catalog, ApiRepairGenerator()), request_linked_typed_retriever=typed
    )
    seed = _api_repair_seed_from_worker_input(resource())
    result = engine.run_statement(
        statement="Prove True",
        proof_job_id="owned-repair",
        request_linked=True,
        api_repair_seed=seed,
    )
    assert result.verification_pending
    assert typed.calls == catalog.calls == []


def test_pipeline_cannot_replace_existing_natural_route_with_typed_only(tmp_path):
    with pytest.raises(ValueError, match="retain the natural Draft route"):
        ProofPipeline(
            generator=RecordingStagedGenerator(),
            verifier=None,
            artifact_store=FileArtifactStore(tmp_path),
            verification_mode="api_reconcile",
            request_linked_typed_retriever=UnavailableTyped(),
        )


def test_selected_generic_profile_keeps_original_natural_hints_untrusted(monkeypatch, tmp_path):
    from pals_agent.proof_reuse_catalog import NaturalDspDraftRetriever

    class GenericChoiceModel:
        def generate(self, **kwargs):
            return '{"profile_id":"generic-v1"}'

    class CapturingGenerator(RecordingStagedGenerator):
        def generate_draft(self, request, feedback=None):
            self.request = request
            return super().generate_draft(request, feedback)

    config = settings(monkeypatch, linked="true", typed="true")
    monkeypatch.setattr(
        "pals_agent.factory.build_artifact_store", lambda _: FileArtifactStore(tmp_path)
    )
    engine = build_pipeline(config)
    catalog = Catalog()
    generator = CapturingGenerator()
    router = replace(
        engine.request_linked_typed_retriever,
        client=GenericChoiceModel(),
        generic=NaturalDspDraftRetriever(catalog),
    )
    engine = replace(engine, generator=generator, request_linked_typed_retriever=router)
    statement = "Prove the original real function is continuous under its stated hypotheses."
    result = engine.run_statement(
        statement=statement, proof_job_id="owned-generic", request_linked=True
    )
    assert len(catalog.calls) == 1 and catalog.calls[0][0] == statement
    assert generator.request.prompt == statement
    assert generator.request.related_draft_contexts[0].exact_equivalence is False
    assert (
        generator.request.proof_flow_result["schema_version"] == "pals.natural-draft-retrieval.v1"
    )
    assert result.verification_pending and result.state == "compiling"
