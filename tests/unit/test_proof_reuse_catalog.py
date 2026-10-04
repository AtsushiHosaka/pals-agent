import json
import time
from types import SimpleNamespace

import pytest

from pals_agent.http_transport import HttpResponse
from pals_agent.proof_reuse import ProofReuseError
from pals_agent.proof_reuse_catalog import (
    ApiProofReuseCatalog,
    BoundedEmbeddingModel,
    DeadlineOpenAIClient,
)
from pals_agent.proof_reuse_usage import current_role
from pals_agent.usage import usage_scope


def test_natural_catalog_is_distinct_from_formal_publication(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Formal pipeline must not serve natural sketch retrieval")

    monkeypatch.setattr("pals_agent.factory.build_proof_flow_runtime", forbidden)
    settings = SimpleNamespace(pfi_runtime_provenance_sha256=None, typed_catalog_enabled=False)
    catalog = ApiProofReuseCatalog(settings)
    assert catalog.profiles == ("generic-v1",)
    assert catalog.retrieve("P", None, deadline=time.monotonic() + 100).contexts == ()
    with pytest.raises(ProofReuseError, match="catalog_unavailable"):
        catalog.retrieve("P", "typed-real-analysis-v1", deadline=time.monotonic() + 100)


def test_retrieval_client_deadline_prevents_paid_call():
    client = DeadlineOpenAIClient(api_key="test", deadline=time.monotonic() - 1)
    with pytest.raises(ProofReuseError, match="deadline"):
        client.generate(model="gpt-6-luna", prompt="P", timeout_seconds=90)


def test_embeddings_have_hard_transport_bound_and_emit_measured_input_tokens():
    calls = []

    class Transport:
        def request(self, **kwargs):
            calls.append(kwargs)
            return HttpResponse(
                200,
                json.dumps(
                    {
                        "model": "text-embedding-3-small",
                        "data": [{"embedding": [0.5, 0.5]}],
                        "usage": {"prompt_tokens": 27, "total_tokens": 27},
                    }
                ).encode(),
            )

    model = BoundedEmbeddingModel(
        api_key="test", revision="revision", dimension=2, transport=Transport(), timeout_seconds=300
    )
    usage = []
    with usage_scope(lambda item: usage.append(dict(item, role=current_role()))):
        assert model.embed("statement") == [0.5, 0.5]
    assert calls[0]["timeout_seconds"] == 10
    assert usage[0]["input_tokens"] == 27 and usage[0]["output_tokens"] == 0
    assert usage[0]["role"] == "draft_embedding"


def test_search_hint_stays_v2_without_formal_query_admission(monkeypatch):
    from pals_agent.draft_catalog import SeedDraftCatalog
    from pals_agent.openmath import canonicalize_openmath_xml, canonicalize_retrieval_openmath_xml
    from pals_agent.proof_flow_runtime import DraftRetrievalResult

    source = SeedDraftCatalog().find_by_id("continuous_power").openmath_xml
    query_v2 = canonicalize_openmath_xml(source)
    query_v4 = canonicalize_retrieval_openmath_xml(query_v2)
    assert query_v2 != query_v4
    calls = {}

    def structure(self, statement):
        calls["statement"] = statement
        return query_v2

    def embed(self, text):
        calls["embedding_input"] = text
        return [0.5] * 384

    def retrieve(self, query, embedding):
        calls["evidence_query"] = query
        return DraftRetrievalResult("no_match", query, (), {})

    monkeypatch.setattr(
        "pals_agent.proof_reuse_catalog.NaturalQueryStructurer.structure", structure
    )
    monkeypatch.setattr("pals_agent.proof_reuse_catalog.BoundedEmbeddingModel.embed", embed)
    monkeypatch.setattr(
        "pals_agent.proof_reuse_catalog.NaturalDraftCandidateClient.retrieve", retrieve
    )
    settings = SimpleNamespace(
        openai_api_key="test",
        openai_base_url="https://api.openai.com/v1",
        openai_max_output_tokens=6000,
        api_base_url="https://api.example.test",
        worker_shared_secret="test",
    )
    ApiProofReuseCatalog(settings).retrieve(
        "The original goal", "generic-v1", deadline=time.monotonic() + 180
    )
    assert calls == {
        "statement": "The original goal",
        "embedding_input": query_v2,
        "evidence_query": query_v2,
    }


def test_natural_query_ignores_legacy_notation_regex_without_paid_repairs():
    from pals_agent.draft_catalog import SeedDraftCatalog
    from pals_agent.openmath import (
        MathXMLValidationError,
        canonicalize_openmath_xml,
        validate_openmath_statement_semantics,
    )
    from pals_agent.proof_reuse_catalog import NaturalQueryStructurer

    source = SeedDraftCatalog().find_by_id("continuous_square").openmath_xml
    statement = (
        "実数全体で関数 f(x)=x^2 が連続であることを、一般の自然数 n のべき "
        "f_n(x)=x^n の連続性から n=2 として示してください。"
    )
    with pytest.raises(MathXMLValidationError):
        validate_openmath_statement_semantics(source, statement)
    calls = []

    class Client:
        def generate(self, **kwargs):
            calls.append(kwargs)
            from tests.unit.test_natural_query_tree import fixture_tree

            return json.dumps(fixture_tree(source))

    assert NaturalQueryStructurer(Client()).structure(statement) == canonicalize_openmath_xml(
        source
    )
    assert len(calls) == 1
    assert statement in calls[0]["prompt"]
    assert "CLOSED " in calls[0]["prompt"]
    assert "THAT GENERAL theorem" in calls[0]["prompt"]
    assert calls[0]["response_schema"]["$defs"]["node"]["anyOf"]
    assert "type/domain " in calls[0]["prompt"]


def test_natural_query_invalid_xml_is_terminal_after_one_call():
    from pals_agent.proof_reuse_catalog import NaturalQueryStructurer

    calls = []

    class Client:
        def generate(self, **kwargs):
            calls.append(kwargs)
            return "not XML"

    with pytest.raises(ProofReuseError, match="query_invalid") as failure:
        NaturalQueryStructurer(Client()).structure("P")
    assert failure.value.details["candidate_tree"] == "not XML"
    assert len(calls) == 1


def test_malformed_natural_query_still_reports_completed_provider_cost():
    from pals_agent.proof_reuse_catalog import NaturalQueryStructurer
    from tests.unit.test_proof_reuse import ProviderTransport

    transport = ProviderTransport(["not XML"])
    client = DeadlineOpenAIClient(
        api_key="test", transport=transport, deadline=time.monotonic() + 30
    )
    usage = []
    with (
        usage_scope(lambda item: usage.append(dict(item, role=current_role()))),
        pytest.raises(ProofReuseError, match="query_invalid"),
    ):
        NaturalQueryStructurer(client).structure("x² is continuous on the reals")
    assert len(transport.calls) == 1
    assert len(usage) == 1
    assert usage[0]["model"] == "gpt-6-luna"
    assert usage[0]["input_tokens"] == 100
    assert usage[0]["role"] == "openmath"
