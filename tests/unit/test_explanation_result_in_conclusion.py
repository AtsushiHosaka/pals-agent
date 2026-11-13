# ruff: noqa: E501
"""A request that asks for a result needs that result in the conclusion (pals#233).

Measured: the QA reviewer approves a conclusion such as "the claim has been confirmed" for a
computation question (a fixed-output negative control), so the requirement is also enforced in
code for new generations. Saved explanations are parsed without it and stay readable.
"""

from __future__ import annotations

import json

import pytest

from pals_agent.explanations import (
    LeanProofExplainer,
    _parse_explanation,
    asks_for_explicit_result,
)

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
    assert asks_for_explicit_result(STATEMENT)
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
    assert not asks_for_explicit_result(PROOF_STATEMENT)
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


@pytest.mark.parametrize(
    "statement",
    [
        "いくつかのコンパクト集合の有限個の和集合はコンパクトであることを示せ。",
        "方程式 $x^2+1=0$ は実数解をもたないことを示せ。",
        "計算機を使わずに、$2^{10}>1000$ を示せ。",
        "数列の極限を求めることなく、収束することを示せ。",
        "実数解をもたないことを示せ。方程式が解けることも確かめよ。",
        "方程式 $x^2+1=0$ が実数の範囲で解けないことを示せ。",
        "Prove that we can find a prime between n and 2n.",
        "Determine whether f(x)=|x| is differentiable at 0.",
    ],
)
def test_proof_requests_that_contain_a_cue_word_do_not_require_a_result(statement: str) -> None:
    assert not asks_for_explicit_result(statement)


@pytest.mark.parametrize(
    "statement",
    [
        "$e^x$ の導関数を求めよ。",
        "方程式 $x^2-5x+6=0$ の解をすべて求めよ。",
        "Compute the determinant of the matrix.",
        "Find the derivative of $\\sin x$.",
    ],
)
def test_requests_that_order_a_result_are_detected(statement: str) -> None:
    assert asks_for_explicit_result(statement)


def test_a_correct_result_without_digits_or_equals_is_accepted() -> None:
    _parse_explanation(
        payload("したがって導関数は $e^x$ です。"), LEAN, require_result_in_conclusion=True
    )


def test_proof_request_with_a_cue_word_is_not_retried_for_its_conclusion() -> None:
    statement = "いくつかの素数の積が偶数ならば、その中に 2 があることを示せ。"
    client = ScriptedClient(json.dumps(payload("以上で主張が示されました。"), ensure_ascii=False))
    explainer = LeanProofExplainer(client=client, model="m", provider="p", max_attempts=3)
    explainer.explain(theorem_statement=statement, lean_code=LEAN, verified=True)
    assert len(client.prompts) == 1
