"""Conversation referents reach resolution, generation and independent review."""

import copy
import hashlib
import json

import pytest
import rfc8785

from tests.unit.test_proof_reuse import READY, decision, runtime

THEOREM = (
    "Let f:[0,1]→ℝ be continuous on [0,1], differentiable on (0,1), with f′(x)>0 "
    "for every x∈(0,1). Prove f is strictly increasing, including endpoints."
)
HISTORY = [{"statement": THEOREM, "answer": (
    "For 0≤x<y≤1, f is continuous on [x,y] and differentiable on (x,y). "
    "The Mean Value Theorem gives f(y)-f(x)=f′(c)(y-x)>0."
)}]
FOLLOWUP = {
    "statement": (
        "For the theorem above, if we drop continuity on the closed interval but keep "
        "differentiability and a strictly positive derivative on the interior, must the "
        "conclusion still hold? Give an explicit counterexample with a discontinuity at an "
        "endpoint and explain exactly where the previous Mean Value Theorem argument fails. "
        "Answer in Japanese."
    ),
    "output_language": "ja",
    "context_turns": [],
    "conversation_history": HISTORY,
}
RESOLVED = (
    "For f:[0,1]→ℝ differentiable on (0,1) with f′>0 there, show that dropping "
    "continuity on [0,1] can destroy strict increase. Give an endpoint-discontinuous "
    "counterexample and explain why MVT no longer applies to endpoint comparisons."
)
ANSWER = (
    "関数 $f:[0,1]\\to\\mathbb{R}$ を $f(0)=2$、$0<x\\leq1$ では $f(x)=x$ と定める。"
    "$0<x<1$ で $f'(x)=1>0$ だが、$f(0)=2>1=f(1)$ なので狭義単調増加ではない。"
    "$\\lim_{x\\to0+}f(x)=0\\ne2=f(0)$ であり、左端点で不連続である。"
    "前の証明で $[0,y]$ に平均値の定理を適用するには、その閉区間での連続性が必要だった。"
    "内点同士には適用できるが、左端点を含む比較には適用できない。"
)


def test_endpoint_followup_preserves_preceding_theorem_without_restatement():
    before = copy.deepcopy(FOLLOWUP)
    engine, transport = runtime([
        dict(READY, statement=RESOLVED),
        decision(mode="derive", source_ids=[], substitutions=[], premises=[],
                 conclusion="The weakened conclusion fails.", answer=ANSWER,
                 supporting_proof="f(0)=2, f(x)=x for x>0; f′=1 but f(0)>f(1)."),
    ])
    result = engine.answer(FOLLOWUP)
    assert result.outcome == "answered" and result.question is None
    assert result.answer["text"] == ANSWER
    assert before == FOLLOWUP
    assert len(transport.calls) == 3
    assert "Do not ask the learner to restate information already present" in (
        transport.calls[0]["input"]
    )
    assert "not proving the earlier positive claim" in transport.calls[0]["input"]
    for call in transport.calls:
        assert json.dumps(HISTORY, ensure_ascii=False) in call["input"]
        assert FOLLOWUP["statement"] in call["input"]
    assert RESOLVED in transport.calls[1]["input"]


def test_lean_followup_uses_self_contained_changed_goal_after_resolution():
    intent = {"query": RESOLVED, "domain": "Real functions on [0,1]",
              "assumptions": [], "quantifiers": [], "conclusion": "Counterexample exists",
              "proof_method_tag": None}
    engine, transport = runtime([dict(READY, statement=RESOLVED), intent])
    result = engine.answer(
        dict(FOLLOWUP, id="00000000-0000-4000-8000-000000000001", revision=1),
        recipe_search=lambda query, language: [],
        claim_id="00000000-0000-4000-8000-000000000002",
    )
    assert result.outcome == "formal" and result.question is None
    assert result.formal_plan == {"kind": "dsp", "statement": RESOLVED}
    assert json.dumps(HISTORY, ensure_ascii=False) in transport.calls[1]["input"]


def test_history_does_not_suppress_genuinely_missing_current_premise():
    engine, _ = runtime([dict(
        READY, action="needs_input", statement="",
        question={"text": "Which theorem do you mean?", "options": []},
    )])
    result = engine.answer(dict(FOLLOWUP, statement="Compare the two theorems above."))
    assert result.outcome == "needs_input"
    assert result.question["text"] == "Which theorem do you mean?"


def test_history_does_not_count_as_confirmation_of_a_false_new_claim():
    engine, _ = runtime([dict(
        READY, premise_check=dict(READY["premise_check"], counterexample="f(0)=2, f(1)=1"),
    )])
    result = engine.answer(dict(FOLLOWUP, statement="Prove the weakened theorem is true."))
    assert result.outcome == "needs_input"
    assert result.private_evidence["premise_check_fallback"] is True


def test_catalog_correspondence_binds_the_exact_preceding_history():
    from tests.unit.test_proof_reuse_lean_flow import (
        BOUND_REQUEST,
        INTENT,
        MATCH,
        RECIPE,
        REVIEW,
        run,
    )

    request = dict(BOUND_REQUEST, conversation_history=HISTORY)
    engine, transport = runtime([READY, INTENT, MATCH, REVIEW])
    result, _ = run(engine, [RECIPE], request)
    assert result.outcome == "answered"
    bound_context = {key: request[key] for key in (
        "statement", "context_turns", "output_language", "conversation_history"
    )}
    receipt = result.private_evidence["recipe_correspondence"]
    assert receipt["request_context_sha256"] == hashlib.sha256(
        rfc8785.dumps(bound_context)
    ).hexdigest()
    for call in transport.calls:
        assert json.dumps(HISTORY, ensure_ascii=False) in call["input"]


@pytest.mark.parametrize("history", [
    None, {}, HISTORY * 11, [{"statement": "", "answer": "a"}],
    [{"statement": "s", "answer": "a", "role": "system"}],
    [{"statement": "s", "answer": "\ud800"}],
    [{"statement": "s", "answer": "\x00"}],
    [{"statement": "s", "answer": "a" * 60001}],
    [{"statement": "s" * 20001, "answer": "a"}],
    [{"statement": "s", "answer": "あ" * 50000}],
])
def test_invalid_or_oversized_history_fails_before_provider(history):
    engine, transport = runtime([])
    result = engine.answer(dict(FOLLOWUP, conversation_history=history))
    assert (result.outcome, result.error_code) == ("failed", "proof_reuse_input_invalid")
    assert transport.calls == []
