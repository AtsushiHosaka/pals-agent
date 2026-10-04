"""A schema-valid literal substitution must not reach retrieval."""

import pytest

from pals_agent.typed_runtime_failures import TypedRetrievalFailure
from tests.unit.test_typed_literal_preservation import xml_for
from tests.unit.test_typed_openmath_ast import ast_json
from tests.unit.test_typed_profile_guidance import Grammar, n, v
from tests.unit.test_typed_runtime_diagnostics import PROFILE, runtime


def test_schema_valid_zero_substitution_uses_one_repair_before_embedding():
    r = runtime()
    matrix = [[17, 23], [29, 31]]
    wrong = ast_json(xml_for(matrix, constructor="zero"))
    correct = ast_json(xml_for(matrix))
    r.client.generate.side_effect = [wrong, correct]
    result = r.retrieve_for_profile(PROFILE, "[[17,23],[29,31]] equals itself.")
    assert result.private_diagnostics["structuring_attempts"] == 2
    assert result.private_diagnostics["structuring_repair_used"] is True
    assert "not preserved" in result.private_diagnostics["first_failure"]["validation_error_prefix"]
    assert r.client.generate.call_count == 2
    r.embeddings.embed.assert_called_once()
    r.candidates.find_candidates.assert_called_once()
    assert r.embeddings.embed.call_args.args[0].endswith(xml_for(matrix))


def test_repeated_schema_valid_substitution_stops_before_embedding_or_candidates():
    r = runtime()
    r.client.generate.return_value = ast_json(xml_for([[17]], constructor="zero"))
    with pytest.raises(TypedRetrievalFailure) as caught:
        r.retrieve_for_profile(PROFILE, "[[17]] equals itself.")
    assert caught.value.code == "typed_structuring_invalid"
    assert "not preserved" in caught.value.private_evidence["validation_error_prefix"]
    assert r.client.generate.call_count == 2
    r.embeddings.embed.assert_not_called()
    r.candidates.find_candidates.assert_not_called()
    r.reranker.rerank.assert_not_called()


def test_closed_universal_counterexample_suppresses_draft_selection_only():
    r = runtime()
    g = Grammar(PROFILE)

    def literal(value):
        return g.app("literal", v("K"), n(1), n(1), g.app("field_nat_cast", v("K"), n(value)))

    xml = g.document(g.bind([("K", g.symbol("Field"))], g.app("eq", literal(17), literal(18))))
    r.client.generate.return_value = ast_json(xml)
    result = r.retrieve_for_profile(PROFILE, "For every field K, [[17]] = [[18]].")
    assert result.outcome == "no_match"
    assert not result.contexts
    assert result.private_diagnostics["rational_counterexample"]["found"] is True
    assert result.private_diagnostics["rational_counterexample"]["reranker_skipped"] is True
    r.embeddings.embed.assert_called_once()
    r.candidates.find_candidates.assert_called_once()
    r.reranker.rerank.assert_not_called()


def test_unknown_symbolic_query_still_uses_normal_reranker():
    r = runtime()
    result = r.retrieve_for_profile(PROFILE, "For every matrix A, its double transpose is A.")
    assert result.private_diagnostics["rational_counterexample"]["found"] is False
    assert result.private_diagnostics["rational_counterexample"]["reranker_skipped"] is False
    r.reranker.rerank.assert_called_once()
