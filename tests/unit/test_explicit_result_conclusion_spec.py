"""#382 structural regressions: scripted transport, no provider, compiler or QA claims."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pals_agent.explanation_v2 import (
    ExplanationWriterV2,
    explanation_prompt_v2,
    review_prompt_v2,
    validate_v2_payload,
)
from pals_agent.explanations import (
    ExplanationGenerationError,
    LeanProofExplainer,
    _parse_explanation,
)

# Only a line-binding input for structural tests; this suite does not compile it.
LEAN = (Path(__file__).parents[1] / "fixtures/reciprocal_minimum.lean").read_text().rstrip("\n")
REQUEST = "正の実数 $x$ について、$x+1/x$ の最小値と、それを達成する $x$ を求めよ。"
GENERIC = "以上で、主張が確かめられました。"
RESULT = "最小値は $2$ で、$x=1$ のときに限り達成されます。"


def payload(conclusion: str, *, v2: bool = False) -> dict[str, Any]:
    reference: dict[str, Any] = {"start_line": 1, "end_line": len(LEAN.splitlines())}
    if not v2:
        reference["excerpt"] = LEAN
    return {
        "overview": RESULT if v2 else "平方の非負性から下界と等号条件を調べます。",
        "sections": [
            {
                "id": "lower-bound",
                "title": "下界と等号条件",
                "summary": (
                    "$x>0$ より $(x-1)^2/x=x+1/x-2\\ge 0$ です。等号が成り立つのは、"
                    "分子の平方が $0$ になるときに限られます。"
                ),
                "references": [reference],
            }
        ],
        "conclusion": conclusion,
    }


class ScriptedClient:
    def __init__(self, *outputs: dict[str, Any]) -> None:
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        timeout_seconds: float | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.outputs.pop(0), ensure_ascii=False)


def test_v1_missing_result_is_corrected_within_existing_attempt_budget() -> None:
    client = ScriptedClient(payload(GENERIC), payload(RESULT))
    result = LeanProofExplainer(client=client, model="scripted", provider="test").explain(
        theorem_statement=REQUEST,
        lean_code=LEAN,
        verified=True,
    )
    assert result.conclusion == RESULT
    assert len(client.prompts) == 2
    assert "explicit result" in client.prompts[1]


@pytest.mark.parametrize("v2", [False, True])
def test_missing_result_never_returns_when_existing_budget_is_exhausted(v2: bool) -> None:
    client = ScriptedClient(payload(GENERIC, v2=v2))
    with pytest.raises(ExplanationGenerationError, match="explicit result"):
        if v2:
            ExplanationWriterV2(
                client=client, model="scripted", provider="test", max_attempts=1
            ).explain(
                theorem_statement=REQUEST,
                lean_code=LEAN,
                draft_text="平方の非負性から下界を導き、等号条件を調べます。",
            )
        else:
            LeanProofExplainer(
                client=client, model="scripted", provider="test", max_attempts=1
            ).explain(
                theorem_statement=REQUEST,
                lean_code=LEAN,
                verified=True,
            )
    assert len(client.prompts) == 1


def test_v2_missing_conclusion_is_corrected_even_with_an_explicit_overview() -> None:
    client = ScriptedClient(payload(GENERIC, v2=True), payload(RESULT, v2=True))
    result = ExplanationWriterV2(client=client, model="scripted", provider="test").explain(
        theorem_statement=REQUEST,
        lean_code=LEAN,
        draft_text="平方の非負性から下界を導き、等号条件を調べます。",
    )
    assert result.conclusion == RESULT
    assert "$2$" in result.overview
    assert "$x=1$" in result.overview
    assert len(client.prompts) == 2
    assert "explicit result" in client.prompts[1]


def test_v2_requires_the_result_in_conclusion_not_only_in_overview() -> None:
    with pytest.raises(ValueError, match="explicit result"):
        validate_v2_payload(
            payload(GENERIC, v2=True),
            theorem_statement=REQUEST,
            lean_code=LEAN,
            language="ja",
        )


def test_v2_keeps_its_explicit_overview_requirement() -> None:
    value = payload(RESULT, v2=True)
    value["overview"] = "平方の非負性から下界を調べます。"
    with pytest.raises(ValueError, match="overview"):
        validate_v2_payload(value, theorem_statement=REQUEST, lean_code=LEAN, language="ja")


@pytest.mark.parametrize(
    "statement",
    [
        "正の実数 $x$ について、$x+1/x$ の最小値と、それを達成する $x$ を求めよ。",
        "行列の行列式を計算せよ。",
        "Compute the determinant of the matrix.",
        "Find the derivative of $e^x$.",
    ],
)
def test_explicit_result_orders_reject_a_generic_conclusion(statement: str) -> None:
    client = ScriptedClient(payload(GENERIC))
    with pytest.raises(ExplanationGenerationError, match="explicit result"):
        LeanProofExplainer(
            client=client, model="scripted", provider="test", max_attempts=1
        ).explain(
            theorem_statement=statement,
            lean_code=LEAN,
            verified=True,
        )


@pytest.mark.parametrize(
    "statement",
    [
        "いくつかのコンパクト集合の有限個の和集合はコンパクトであることを示せ。",
        "計算機を使わずに、$2^{10}>1000$ を示せ。",
        "方程式が実数の範囲で解けないことを示せ。",
        "Prove that we can find a prime between n and 2n.",
        "Determine whether the function is differentiable at zero.",
    ],
)
def test_proof_cue_words_do_not_spend_an_extra_writer_attempt(statement: str) -> None:
    client = ScriptedClient(payload(GENERIC))
    result = LeanProofExplainer(
        client=client, model="scripted", provider="test", max_attempts=1
    ).explain(
        theorem_statement=statement,
        lean_code=LEAN,
        verified=True,
    )
    assert result.conclusion == GENERIC
    assert len(client.prompts) == 1


def test_saved_explanations_with_generic_conclusions_stay_readable() -> None:
    assert _parse_explanation(payload(GENERIC), LEAN)[2] == GENERIC


def test_a_result_without_digits_or_equals_is_not_rejected() -> None:
    client = ScriptedClient(payload("したがって導関数は $e^x$ です。"))
    result = LeanProofExplainer(client=client, model="scripted", provider="test").explain(
        theorem_statement="$e^x$ の導関数を求めよ。",
        lean_code=LEAN,
        verified=True,
    )
    assert "$e^x$" in result.conclusion


def test_v1_unverified_source_is_still_refused_without_a_writer_call() -> None:
    client = ScriptedClient(payload(RESULT))
    with pytest.raises(ExplanationGenerationError, match="accepted by Lean"):
        LeanProofExplainer(client=client, model="scripted", provider="test").explain(
            theorem_statement=REQUEST,
            lean_code=LEAN,
            verified=False,
        )
    assert not client.prompts


def test_new_conclusion_rule_does_not_relax_exact_line_references() -> None:
    value = payload(RESULT)
    value["sections"][0]["references"][0]["excerpt"] = "different source"
    client = ScriptedClient(value)
    with pytest.raises(ExplanationGenerationError):
        LeanProofExplainer(
            client=client, model="scripted", provider="test", max_attempts=1
        ).explain(
            theorem_statement=REQUEST,
            lean_code=LEAN,
            verified=True,
        )


def test_v2_writer_and_review_both_require_the_final_result_in_conclusion() -> None:
    client = ScriptedClient(payload(RESULT, v2=True))
    explanation = ExplanationWriterV2(client=client, model="scripted", provider="test").explain(
        theorem_statement=REQUEST,
        lean_code=LEAN,
        draft_text="平方の非負性から下界を導き、等号条件を調べます。",
    )
    writer_prompt = explanation_prompt_v2(
        theorem_statement=REQUEST,
        lean_code=LEAN,
        draft_text="平方の非負性から下界を導き、等号条件を調べます。",
        language="ja",
    )
    reviewer_prompt = review_prompt_v2(
        theorem_statement=REQUEST,
        lean_code=LEAN,
        explanation=explanation,
        draft_text=None,
        language="ja",
    )
    assert "conclusion must state the explicit result" in writer_prompt
    assert "Both the overview and conclusion must state" in reviewer_prompt
    assert "Reject if either omits that result" in reviewer_prompt
    assert "unfaithful_to_statement" in reviewer_prompt
    assert "unjustified_leap" in reviewer_prompt
