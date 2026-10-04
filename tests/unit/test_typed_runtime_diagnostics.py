from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from pals_agent.draft_embeddings import EmbeddingError
from pals_agent.generator import _draft_prompt_for
from pals_agent.openai import OpenAIError
from pals_agent.pipeline import _request_for_statement
from pals_agent.private_draft_candidates import (
    DraftCandidateCompatibilityError,
    DraftCandidateUnavailableError,
)
from pals_agent.private_typed_candidates import TypedCandidateResult
from pals_agent.profile_routing import ProfileRoutedProofFlowRuntime
from pals_agent.proof_flow_reranker import DraftRerankerInvalidError, DraftRerankerUnavailableError
from pals_agent.typed_openmath_ast import SCHEMA_VERSION
from pals_agent.typed_runtime import TypedProofFlowRuntime
from pals_agent.typed_runtime_failures import TypedRetrievalFailure
from tests.unit.test_typed_openmath_ast import ast_json
from tests.unit.test_typed_profile_guidance import example

PROFILE = "typed-math-matrix-v1"


def runtime():
    grammar, document, _ = example(PROFILE)
    model = Mock()
    model.generate.return_value = ast_json(grammar.document(document))
    embeddings = SimpleNamespace(
        model="text-embedding-3-small",
        dimension=384,
        revision="openai-release-2024-01-25",
        endpoint_identity="https://api.openai.com/v1",
        deployment_identity="text-embedding-3-small",
        embed=Mock(return_value=[1.0] * 384),
    )
    candidates = Mock()
    candidates.find_candidates.return_value = TypedCandidateResult(
        str(uuid4()), "a" * 64, PROFILE, 1, ()
    )
    reranker = Mock()
    reranker.rerank.return_value = ()
    return TypedProofFlowRuntime(model, embeddings, candidates, reranker)


@pytest.mark.parametrize(
    "stage,error,code",
    [
        ("structuring", OpenAIError("secret transport body"), "typed_structuring_unavailable"),
        ("embedding", EmbeddingError("secret transport body"), "typed_embedding_unavailable"),
        (
            "candidates",
            DraftCandidateUnavailableError("secret transport body"),
            "typed_candidates_unavailable",
        ),
        (
            "candidates",
            DraftCandidateCompatibilityError("secret transport body"),
            "typed_candidates_incompatible",
        ),
        (
            "reranking",
            DraftRerankerUnavailableError("secret transport body"),
            "typed_reranking_unavailable",
        ),
        (
            "reranking",
            DraftRerankerInvalidError("secret transport body"),
            "typed_reranking_invalid",
        ),
    ],
)
def test_runtime_failure_has_exact_stage_without_transport_exception_leaks(stage, error, code):
    r = runtime()
    {
        "structuring": r.client.generate,
        "embedding": r.embeddings.embed,
        "candidates": r.candidates.find_candidates,
        "reranking": r.reranker.rerank,
    }[stage].side_effect = error
    with pytest.raises(TypedRetrievalFailure) as caught:
        r.retrieve_for_profile(PROFILE, "Matrix statement")
    assert caught.value.code == code
    assert caught.value.private_evidence["code"] == code
    assert (
        caught.value.private_evidence["structuring_transport"]
        == SCHEMA_VERSION
    )
    assert "secret" not in str(caught.value)


def test_grammar_is_supplied_before_validation_and_candidate_read():
    r = runtime()
    result = r.retrieve_for_profile(PROFILE, "Matrix statement")
    prompt = r.client.generate.call_args.kwargs["prompt"]
    assert "ROW-MAJOR" in prompt and "field_nat_cast" in prompt and "GRAMMAR:" in prompt
    assert result.profile_id == PROFILE
    r.candidates.find_candidates.assert_called_once()


def test_invalid_structure_private_evidence_is_bounded_and_not_a_generator_instruction():
    r = runtime()
    r.client.generate.return_value = (
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath"><OMI>5</OMI></OMOBJ>'
    )
    selector = Mock()
    selector.generate.return_value = '{"profile_id":"typed-math-matrix-v1"}'
    request = _request_for_statement(
        "Matrix statement", proof_flow_retriever=ProfileRoutedProofFlowRuntime(selector, r, None)
    )
    result = request.proof_flow_result
    assert result["reason"] == "typed_structuring_invalid"
    assert (
        result["private_diagnostics"]["bounded_private_json"]["prefix"]
        == r.client.generate.return_value
    )
    assert len(result["private_diagnostics"]["bounded_private_json"]["sha256"]) == 64
    r.embeddings.embed.assert_not_called()
    r.candidates.find_candidates.assert_not_called()
    assert "raw_openmath_prefix" not in _draft_prompt_for(request)
    huge = TypedRetrievalFailure(
        "typed_structuring_invalid", raw_openmath="界" * 5000, validation_error="界" * 1000
    ).private_evidence
    assert len(huge["raw_openmath_prefix"].encode()) <= 4096
    assert len(huge["validation_error_prefix"].encode()) <= 512
    assert huge["raw_openmath_bytes"] == 15000 and huge["raw_openmath_truncated"] is True


def test_private_retrieval_evidence_is_not_projected_into_public_status():
    from pals_agent.worker import _status_retrieval

    projected = _status_retrieval(
        {
            "candidate_draft_id": None,
            "proof_flow_result": {"private_diagnostics": {"raw_openmath_prefix": "private XML"}},
        }
    )
    assert "private" not in str(projected)
    assert "proof_flow_result" not in projected


def test_reranker_request_failure_is_classified_before_any_reranker_call(monkeypatch):
    r = runtime()

    def invalid_request(**kwargs):
        raise DraftRerankerInvalidError("not public")

    monkeypatch.setattr(
        "pals_agent.typed_runtime.build_typed_draft_reranker_request", invalid_request
    )
    with pytest.raises(TypedRetrievalFailure, match="typed_reranking_invalid"):
        r.retrieve_for_profile(PROFILE, "Matrix statement")
    r.reranker.rerank.assert_not_called()
