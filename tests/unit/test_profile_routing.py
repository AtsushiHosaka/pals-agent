from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pals_agent.factory import build_pipeline
from pals_agent.pipeline import _request_for_statement
from pals_agent.private_draft_candidates import DraftCandidateUnavailableError
from pals_agent.profile_routing import SUPPORTED_TYPED_PROFILES, ProfileRoutedProofFlowRuntime
from pals_agent.proof_flow_runtime import DraftRetrievalResult
from pals_agent.recipe_attempt import exact_retrieved_draft_reference
from pals_agent.settings import AgentSettings
from pals_agent.typed_runtime import TypedRetrievalResult


@pytest.mark.parametrize(
    "output",
    [
        '{"profile_id":"made-up"}',
        '{"profile_id":["generic-v1"]}',
        '{"profile_id":"generic-v1","fallback":true}',
        '{"profile_id":"generic-v1","profile_id":"typed-math-matrix-v1"}',
        "not json",
    ],
)
def test_invalid_selection_never_queries_any_catalog(output):
    client, typed, generic = Mock(), Mock(), Mock()
    client.generate.return_value = output
    result = ProfileRoutedProofFlowRuntime(client, typed, generic).retrieve("A matrix theorem")
    assert result.as_json()["reason"] == "profile_selection_invalid"
    typed.retrieve_for_profile.assert_not_called()
    generic.retrieve.assert_not_called()


def test_unavailable_selected_profile_records_reason_without_generic_fallback():
    client, typed, generic = Mock(), Mock(), Mock()
    client.generate.return_value = '{"profile_id":"typed-math-matrix-v1"}'
    typed.retrieve_for_profile.side_effect = DraftCandidateUnavailableError("private detail")
    request = _request_for_statement(
        "A matrix theorem",
        proof_flow_retriever=ProfileRoutedProofFlowRuntime(client, typed, generic),
    )
    assert request.proof_flow_result["reason"] == "typed_profile_unavailable"
    assert request.proof_flow_result["profile_id"] == "typed-math-matrix-v1"
    assert request.related_draft_contexts == ()
    assert "private detail" not in str(request.proof_flow_result)
    assert exact_retrieved_draft_reference(request) is None
    generic.retrieve.assert_not_called()


@pytest.mark.parametrize(
    "selected,reason",
    [
        (None, "profile_ambiguous_or_unsupported"),
        ("generic-v1", "generic_profile_unconfigured"),
    ],
)
def test_ambiguous_or_unconfigured_generic_preserves_custom_generation(selected, reason):
    import json

    client, typed = Mock(), Mock()
    client.generate.return_value = json.dumps({"profile_id": selected})
    request = _request_for_statement(
        "exact theorem", proof_flow_retriever=ProfileRoutedProofFlowRuntime(client, typed, None)
    )
    assert request.prompt == "exact theorem"
    assert request.proof_flow_result["reason"] == reason
    assert request.related_draft_contexts == ()
    typed.retrieve_for_profile.assert_not_called()


def test_selected_generic_keeps_existing_result_and_failure_contract():
    client, typed, generic = Mock(), Mock(), Mock()
    client.generate.return_value = '{"profile_id":"generic-v1"}'
    generic.retrieve.return_value = DraftRetrievalResult("no_match", "xml", (), {"binding": "v1"})
    router = ProfileRoutedProofFlowRuntime(client, typed, generic)
    assert router.retrieve("theorem") is generic.retrieve.return_value
    generic.retrieve.side_effect = RuntimeError("existing closed error")
    with pytest.raises(RuntimeError, match="existing closed error"):
        router.retrieve("theorem")
    typed.retrieve_for_profile.assert_not_called()


def test_typed_match_reaches_generator_context_but_never_generic_recipe_alignment():
    client, typed, generic = Mock(), Mock(), Mock()
    client.generate.return_value = '{"profile_id":"typed-math-matrix-v1"}'
    draft = SimpleNamespace(
        id="typed-matrix",
        matched_prompt="P squared is identity",
        openmath_xml="<typed-matrix />",
        proof_strategy="Entrywise matrix multiplication",
        sketch_steps=("Expand each entry",),
    )
    evidence = SimpleNamespace(
        candidate=SimpleNamespace(draft=draft, cosine_distance=0.0),
        exact_equivalence=True,
        vector_score=1.0,
        structural_score=1.0,
    )
    typed.retrieve_for_profile.return_value = TypedRetrievalResult(
        "match",
        "<typed-matrix />",
        (evidence,),
        {"profile_id": "typed-math-matrix-v1"},
        "typed-math-matrix-v1",
        (draft.id,),
    )
    request = _request_for_statement(
        "P squared is identity",
        proof_flow_retriever=ProfileRoutedProofFlowRuntime(client, typed, generic),
    )
    assert request.proof_flow_result["schema_version"] == "pals.typed-draft-retrieval.v1"
    assert request.proof_flow_result["profile_id"] == "typed-math-matrix-v1"
    assert request.related_draft_contexts[0].strategy_notes == (draft.proof_strategy,)
    assert exact_retrieved_draft_reference(request) is None
    generic.retrieve.assert_not_called()


def test_factory_wires_worker_capability_without_release_or_database_credentials(monkeypatch):
    monkeypatch.setenv("PALS_TYPED_CATALOG_ENABLED", "true")
    monkeypatch.delenv("PALS_PFI_PROVENANCE_SHA256", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("PALS_WORKER_SHARED_SECRET", "worker-only")
    monkeypatch.setenv("PALS_API_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("PALS_TYPED_CATALOG_RELEASE_SECRET", "forbidden-release-secret")
    monkeypatch.setenv("PALS_DATABASE_URL", "forbidden-database-capability")
    monkeypatch.setattr("pals_agent.factory.build_artifact_store", lambda _: Mock())
    with pytest.raises(ValueError, match="forbids removed direct-storage"):
        AgentSettings.from_env()
    monkeypatch.delenv("PALS_DATABASE_URL")
    settings = AgentSettings.from_env()
    pipeline = build_pipeline(settings)
    router = pipeline.proof_flow_retriever
    assert isinstance(router, ProfileRoutedProofFlowRuntime)
    assert router.generic is None
    assert router.typed.candidates.worker_secret == "worker-only"
    assert router.typed.candidates.evaluation_generation_id is None
    assert "forbidden" not in repr(router)
    assert len(SUPPORTED_TYPED_PROFILES) == 16
    assert (
        build_pipeline(replace(settings, typed_catalog_enabled=False)).proof_flow_retriever is None
    )


def test_configuration_rejects_misspelled_enable_flag(monkeypatch):
    monkeypatch.setenv("PALS_TYPED_CATALOG_ENABLED", "tru")
    with pytest.raises(ValueError, match="must be true or false"):
        AgentSettings.from_env()
