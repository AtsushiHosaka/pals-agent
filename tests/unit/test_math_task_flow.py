"""Request handoff checks; mocked provider output does not prove intent accuracy."""

import json

import pytest

from tests.unit.test_chat_runtime import engine, route
from tests.unit.test_proof_reuse import READY
from tests.unit.test_proof_reuse_lean_flow import CLAIM_ID, REQUEST_ID


@pytest.mark.parametrize("statement", [
    "Compute the rank over R of [[1,2,3],[2,4,6],[1,1,1]].",
    "Find all real solutions of sqrt(x+2)=x.",
    "What are the units of Z/12Z?",
    "Determine whether every real x satisfies x^2-6*x+13 >= 5.",
])
def test_unknown_answer_survives_routing_and_search_miss_as_a_dsp_task(statement):
    intent = {
        "query": statement, "domain": "As stated in the request",
        "assumptions": [], "quantifiers": [], "conclusion": statement,
        "proof_method_tag": None,
    }
    runtime, provider = engine([
        route("lean", extracted_statement=statement),
        dict(READY, statement=statement), intent,
    ])
    searches = []

    def search(query, language):
        searches.append((query, language))
        return []

    result = runtime.answer(
        {"id": REQUEST_ID, "revision": 3, "statement": statement,
         "context_turns": [], "output_language": "en"},
        recipe_search=search, claim_id=CLAIM_ID,
    )

    assert result.outcome == "formal"
    assert result.answer is None
    assert result.formal_plan == {"kind": "dsp", "statement": statement}
    assert searches == [(statement, "en")]
    assert len(provider.calls) == 3  # Router, preflight, search intent; no unverified answer.
    data, _ = json.JSONDecoder().raw_decode(
        provider.calls[-1]["input"].split("DATA:\n", 1)[1]
    )
    assert data["request"]["original_statement"] == statement
    assert data["resolved_statement"] == statement
