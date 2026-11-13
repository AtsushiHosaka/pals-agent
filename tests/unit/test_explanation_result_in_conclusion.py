# ruff: noqa: E501
"""A request that asks for a result needs that result in the conclusion (pals#233).

Measured: the QA reviewer approves a conclusion such as "the claim has been confirmed" for a
computation question (a fixed-output negative control), so the requirement is also enforced in
code for new generations. Saved explanations are parsed without it and stay readable.
"""

from __future__ import annotations

import json

import pytest

from pals_agent.explanations import LeanProofExplainer, _parse_explanation, asks_for_value

LEAN = "theorem cubic_deriv (x : ℝ) : deriv (fun t : ℝ => t ^ 3 - 3 * t) x = 3 * x ^ 2 - 3 := by\n  sorry\n"
STATEMENT = "実関数 $f(x)=x^3-3x$ について、任意の実数 $x$ での導関数を求めよ。"
PROOF_STATEMENT = "素数 p が ab を割り切るなら、p は a または b を割り切ることを示せ。"


def payload(conclusion: str) -> dict:
    return {
        "overview": "べき乗と定数倍の微分則を使います。",
        "sections": [
            {
                "id": "s1",
                "title": "各項の微分",
                "summary": "$t^3$ の導関数は $3x^2$、$3t$ の導関数は $3$ です。",
                "references": [{"start_line": 1, "end_line": 1, "excerpt": LEAN.splitlines()[0]}],
            }
        ],
        "conclusion": conclusion,
    }


def test_generic_completion_is_not_a_result() -> None:
    assert asks_for_value(STATEMENT)
    with pytest.raises(ValueError, match="explicit result"):
        _parse_explanation(
            payload("以上で、主張が確かめられました。"),
            LEAN,
            require_result_in_conclusion=True,
        )


def test_explicit_result_is_accepted() -> None:
    _parse_explanation(
        payload("したがって $f'(x)=3x^2-3$ です。"), LEAN, require_result_in_conclusion=True
    )


def test_a_proof_request_does_not_need_a_formula_in_the_conclusion() -> None:
    assert not asks_for_value(PROOF_STATEMENT)
    _parse_explanation(payload("以上で主張が示されました。"), LEAN)


def test_saved_generic_conclusion_stays_readable() -> None:
    _parse_explanation(payload("以上で、主張が確かめられました。"), LEAN)


class ScriptedClient:
    def __init__(self, *outputs: str) -> None:
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    def generate(self, *, model: str, prompt: str, timeout_seconds: float | None = None) -> str:
        self.prompts.append(prompt)
        return self.outputs.pop(0)


def test_writer_is_asked_again_when_the_result_is_missing() -> None:
    client = ScriptedClient(
        json.dumps(payload("以上で、主張が確かめられました。"), ensure_ascii=False),
        json.dumps(payload("したがって $f'(x)=3x^2-3$ です。"), ensure_ascii=False),
    )
    explainer = LeanProofExplainer(client=client, model="m", provider="p", max_attempts=2)
    explanation = explainer.explain(theorem_statement=STATEMENT, lean_code=LEAN, verified=True)
    assert explanation.conclusion == "したがって $f'(x)=3x^2-3$ です。"
    assert len(client.prompts) == 2
    assert "must state the explicit result" in client.prompts[1]
