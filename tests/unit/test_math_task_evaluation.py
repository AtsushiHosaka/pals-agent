"""Check evaluation orchestration without a provider or verifier."""

import json
from typing import Any

import pytest

from pals_agent.proof_reuse import ProofReuseError
from tools.evaluate_math_request_intent import CASES, evaluate


class FakeClient:
    def __init__(self, responses: list[Any]):
        self.responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        response = next(self.responses)
        return response if isinstance(response, str) else json.dumps(response)


def preflight(case: dict[str, Any], action: str) -> dict[str, Any]:
    return {
        "action": action,
        "statement": case["statement"],
        "profile_id": "generic-v1",
        "requires_catalog_source": False,
        "question": ({"text": "Over which number system?", "options": ["R", "C"]}
                     if action == "needs_input" else None),
        "reason": "The domain affects the solution set." if action == "needs_input"
        else "The mathematical request is sufficiently specified.",
        "premise_check": {
            "counterexample": "", "truth_depends_on": [],
            "assumed_defaults": [], "conventions": [],
        },
    }


def test_ready_evaluation_captures_preflight_and_drafts_with_three_calls():
    case = next(case for case in CASES if case["id"] == "compute")
    draft = ("The second row is twice the first, so rank is at most 2. "
             "The minor on rows 1,3 and columns 1,2 has determinant -1, "
             "so rank is at least 2. Thus the rank over R is exactly 2.")
    client = FakeClient([preflight(case, "ready"), draft,
                         {"passed": True, "reason": "Both rank bounds are justified."}])

    result = evaluate(case, client)  # type: ignore[arg-type]

    assert result["passed"] is True
    assert result["draft"] == draft
    assert len(client.calls) == 3
    assert case["statement"] in client.calls[0]["prompt"]
    assert "action" in client.calls[0]["response_schema"]["properties"]
    assert case["statement"] in client.calls[1]["prompt"]
    assert "response_schema" not in client.calls[1]
    assert "passed" in client.calls[2]["response_schema"]["properties"]
    assert all(call["store"] is False for call in client.calls)


def test_ambiguous_evaluation_skips_draft_and_uses_two_calls():
    case = next(case for case in CASES if case["id"] == "ambiguity")
    client = FakeClient([preflight(case, "needs_input"),
                         {"passed": True, "reason": "Clarification is consequential."}])

    result = evaluate(case, client)  # type: ignore[arg-type]

    assert result["passed"] is True
    assert result["draft"] is None
    assert len(client.calls) == 2
    assert all("response_schema" in call for call in client.calls)


def test_wrong_action_fails_even_when_semantic_judge_passes():
    case = next(case for case in CASES if case["id"] == "compute")
    client = FakeClient([preflight(case, "needs_input"),
                         {"passed": True, "reason": "Incorrectly approved by fake judge."}])

    result = evaluate(case, client)  # type: ignore[arg-type]

    assert result["passed"] is False
    assert len(client.calls) == 2


def test_invalid_preflight_is_rejected_before_draft_or_judgment():
    case = CASES[0]
    invalid = dict(preflight(case, "ready"), profile_id="unknown-profile")
    client = FakeClient([invalid])

    with pytest.raises(ProofReuseError, match="proof_reuse_invalid_response"):
        evaluate(case, client)  # type: ignore[arg-type]

    assert len(client.calls) == 1
