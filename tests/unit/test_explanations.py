import json

import pytest

from pals_agent.explanations import (
    ExplanationGenerationError,
    LeanProofExplainer,
)

LEAN_CODE = """import Mathlib

theorem add_zero_nat (n : Nat) : n + 0 = n := by
  simpa using Nat.add_zero n"""


class FakeClient:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        timeout_seconds: float | None = None,
    ) -> str:
        _ = timeout_seconds
        assert model == "explain-model"
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("unexpected LLM call")
        return self.responses.pop(0)


def explanation_payload(*, excerpt: str = "  simpa using Nat.add_zero n") -> str:
    return json.dumps(
        {
            "overview": "加法の単位元に関する既存定理を使います。",
            "sections": [
                {
                    "id": "apply-add-zero",
                    "title": "既存定理の適用",
                    "summary": "0 を足しても値が変わらない性質を、現在の等式に当てはめます。",
                    "references": [
                        {
                            "start_line": 4,
                            "end_line": 4,
                            "excerpt": excerpt,
                        }
                    ],
                }
            ],
            "conclusion": "任意の自然数 n について n + 0 = n が従います。",
        },
        ensure_ascii=False,
    )


def epsilon_delta_payload(
    *,
    overview: str = (
        "$\\varepsilon>0$ を任意に取ります。"
        "実数の点 $a$ を固定し、"
        "$\\delta=\\min(1,\\varepsilon/(2|a|+1))$ と定めます。"
        "この $\\delta$ は $\\delta>0$ です。"
    ),
    conclusion: str = (
        "$|x^2-a^2|=|x-a||x+a|<\\varepsilon$ と評価できるため、"
        "$x^2$ は点 $a$ で連続です。"
    ),
) -> str:
    return json.dumps(
        {
            "overview": overview,
            "sections": [
                {
                    "id": "choose-delta",
                    "title": "δ の選び方",
                    "summary": (
                        "$|x-a|<\\delta$ と仮定します。すると、"
                        "積の形にした差を指定された誤差内へ抑えられます。"
                    ),
                    "references": [
                        {
                            "start_line": 4,
                            "end_line": 4,
                            "excerpt": "  simpa using Nat.add_zero n",
                        }
                    ],
                }
            ],
            "conclusion": conclusion,
        },
        ensure_ascii=False,
    )


def build_explainer(*responses: str) -> tuple[LeanProofExplainer, FakeClient]:
    client = FakeClient(*responses)
    return (
        LeanProofExplainer(
            client=client,
            model="explain-model",
            provider="openai",
        ),
        client,
    )


def test_explains_only_verified_lean_with_exact_line_references() -> None:
    explainer, client = build_explainer(explanation_payload())

    result = explainer.explain(
        theorem_statement="n + 0 = n を示せ",
        lean_code=LEAN_CODE,
        verified=True,
    )

    assert result.overview.startswith("加法")
    assert result.sections[0].id == "apply-add-zero"
    assert result.sections[0].references[0].start_line == 4
    assert result.sections[0].references[0].excerpt == "  simpa using Nat.add_zero n"
    assert result.model == "explain-model"
    assert result.provider == "openai"
    assert "only sources of truth" in client.prompts[0]
    assert LEAN_CODE in client.prompts[0]
    assert "hidden chain-of-thought" in client.prompts[0]
    assert "Canonical Lean line table" in client.prompts[0]
    assert '"line": 4' in client.prompts[0]
    assert '"text": "  simpa using Nat.add_zero n"' in client.prompts[0]


def test_x_squared_continuity_requires_an_epsilon_delta_explanation() -> None:
    explainer, client = build_explainer(epsilon_delta_payload())

    result = explainer.explain(
        theorem_statement="x² が連続であることを説明してください。",
        lean_code=LEAN_CODE,
        verified=True,
    )

    assert "\\varepsilon" in result.overview
    assert "|x^2-a^2|" in result.conclusion
    assert "epsilon-delta explanation" in client.prompts[0]
    assert "Do not say that the learner requested epsilon-delta" in client.prompts[0]
    assert "KaTeX-compatible LaTeX" in client.prompts[0]
    assert "$\\varepsilon$" in client.prompts[0]
    assert "Write the mathematical proof itself from the first sentence" in client.prompts[0]
    assert "$\\varepsilon>0$ を任意に取ります。" in client.prompts[0]
    assert "fix the real point" in client.prompts[0]
    assert "choose delta explicitly" in client.prompts[0]
    assert "delta-neighborhood condition" in client.prompts[0]
    assert "derive the factorization and epsilon bound" in client.prompts[0]
    assert "section titles that name mathematical steps" in client.prompts[0]
    assert "Do not begin with a summary" in client.prompts[0]
    assert "Do not first summarize the proof" in client.prompts[0]
    assert "describe imports or libraries" in client.prompts[0]
    assert "preview the conclusion" in client.prompts[0]
    assert "source lines" in client.prompts[0]
    assert "commands, or tactics" in client.prompts[0]
    assert "ライブラリの利用" in client.prompts[0]
    assert "示したい内容" in client.prompts[0]
    assert "連続性判定を使う" in client.prompts[0]


def test_x_squared_continuity_retries_old_summary_first_exposition() -> None:
    old_style = epsilon_delta_payload(
        overview=(
            "実数の平方関数について、差を因数分解する証明方針を先に要約します。"
            "$\\delta=\\min(1,\\varepsilon/(2|a|+1))$ と定め、"
            "$\\delta>0$ とします。"
        )
    )
    explainer, client = build_explainer(old_style, old_style)

    with pytest.raises(ExplanationGenerationError):
        explainer.explain(
            theorem_statement="x² が連続であることを説明してください。",
            lean_code=LEAN_CODE,
            verified=True,
        )

    assert len(client.prompts) == 2


@pytest.mark.parametrize(
    ("overview", "conclusion"),
    [
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "$\\delta=\\min\\{1,\\varepsilon/(2|a|+1)\\}>0$"
                " と具体的に定めます。"
            ),
            (
                "$\\lvert x^2-a^2\\rvert="
                "\\lvert x-a\\rvert\\,\\lvert x+a\\rvert<\\varepsilon$"
                " なので連続です。"
            ),
        ),
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "$\\delta:=\\min\\{1,\\varepsilon/(4|a|+2)\\}$"
                " と定め、$0<\\delta$ です。"
            ),
            (
                "$|x^2-a^2|=|x-a|\\cdot|x+a|"
                "\\le 2|x-a|(|a|+1)<\\epsilon$ と評価できるので連続です。"
            ),
        ),
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "$\\delta=\\min(1,\\varepsilon/(3|a|+2))$ と定めます。"
                "この $\\delta$ は $\\delta>0$ です。"
            ),
            (
                "$|x^2-a^2|=|x+a|\\cdot|x-a|"
                "<\\varepsilon$ と評価できるので連続です。"
            ),
        ),
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "$\\delta=\\min(1,\\varepsilon/(1+2|a|))>0$ と定めます。"
            ),
            "$|x^2-a^2|=|x-a||x+a|<\\varepsilon$ なので連続です。",
        ),
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "$\\delta=\\min(1,\\varepsilon/(2(|a|+1)))>0$ と定めます。"
            ),
            "$|x^2-a^2|=|x-a||x+a|<\\varepsilon$ なので連続です。",
        ),
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "$\\delta=\\min(1,\\varepsilon/(2\\cdot|a|+1))>0$ と定めます。"
            ),
            "$|x^2-a^2|=|x-a||x+a|<\\varepsilon$ なので連続です。",
        ),
    ],
)
def test_x_squared_continuity_accepts_equivalent_katex_notation(
    overview: str,
    conclusion: str,
) -> None:
    explainer, _ = build_explainer(
        epsilon_delta_payload(overview=overview, conclusion=conclusion)
    )

    result = explainer.explain(
        theorem_statement="x² が連続であることを説明してください。",
        lean_code=LEAN_CODE,
        verified=True,
    )

    assert result.conclusion == conclusion


@pytest.mark.parametrize(
    ("overview", "conclusion"),
    [
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "正の $\\delta$ を選びます。"
            ),
            "$|x^2-a^2|=|x-a||x+a|<\\varepsilon$ なので連続です。",
        ),
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "$\\delta=\\min(1,\\varepsilon/(2|a|+1))$ と選びます。"
            ),
            "$|x^2-a^2|=|x-a||x+a|<\\varepsilon$ なので連続です。",
        ),
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "$\\delta=\\min(1,\\varepsilon/(2|a|+1))$ と定め、"
                "$\\delta>0$ とします。"
            ),
            "$|x^2-a^2|<\\varepsilon$ なので連続です。",
        ),
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "$\\delta=\\min(1,\\varepsilon/(2|a|+1))$ と定め、"
                "$\\delta>0$ とします。"
            ),
            "$|x^2-a^2|=|x-a||x+a|$ を考えるので連続です。",
        ),
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "$\\delta=\\min(1,\\varepsilon/(2|a|+1))$ と定め、"
                "$\\delta>0$ とします。"
            ),
            (
                "$|x^2-a^2|=|x-a||x+a|$ と因数分解します。"
                "別に $|x-a|<\\varepsilon$ とします。"
            ),
        ),
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "$\\delta=\\varepsilon$ と定め、$\\delta>0$ とします。"
            ),
            "$|x^2-a^2|=|x-a||x+a|<\\varepsilon$ と主張します。",
        ),
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "$\\delta=\\min(1,\\varepsilon)$ と定め、$\\delta>0$ とします。"
            ),
            "$|x^2-a^2|=|x-a||x+a|<\\varepsilon$ と主張します。",
        ),
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "$\\delta=\\min(1,\\varepsilon/(2|a|+1))+1>0$ と定めます。"
            ),
            "$|x^2-a^2|=|x-a||x+a|<\\varepsilon$ と主張します。",
        ),
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "$\\delta=\\min(1,\\varepsilon/(2|a|+1))$ と定め、"
                "$\\delta>0$ とします。"
            ),
            "$|x^2-a^2|=|x-a||x+a|\\quad 0<\\varepsilon$ と書きます。",
        ),
    ],
)
def test_x_squared_continuity_rejects_incomplete_epsilon_delta_markers(
    overview: str,
    conclusion: str,
) -> None:
    invalid = epsilon_delta_payload(overview=overview, conclusion=conclusion)
    explainer, client = build_explainer(invalid, invalid)

    with pytest.raises(ExplanationGenerationError):
        explainer.explain(
            theorem_statement="x² が連続であることを説明してください。",
            lean_code=LEAN_CODE,
            verified=True,
        )

    assert len(client.prompts) == 2


def test_refuses_to_explain_unverified_lean_without_calling_llm() -> None:
    explainer, client = build_explainer()

    with pytest.raises(ExplanationGenerationError, match="accepted by Lean"):
        explainer.explain(
            theorem_statement="broken",
            lean_code="theorem broken : False := by sorry",
            verified=False,
        )

    assert client.prompts == []


def test_retries_invalid_reference_then_uses_corrected_actual_output() -> None:
    explainer, client = build_explainer(
        explanation_payload(excerpt="invented code"),
        explanation_payload(),
    )

    result = explainer.explain(
        theorem_statement="n + 0 = n を示せ",
        lean_code=LEAN_CODE,
        verified=True,
    )

    assert len(client.prompts) == 2
    assert "previous response was invalid" in client.prompts[1]
    assert "Re-read the canonical line table" in client.prompts[1]
    assert result.raw_model_output == explanation_payload()


def test_invalid_grounding_fails_instead_of_returning_placeholder() -> None:
    explainer, _client = build_explainer(
        explanation_payload(excerpt="invented one"),
        explanation_payload(excerpt="invented two"),
    )

    with pytest.raises(ExplanationGenerationError) as error_info:
        explainer.explain(
            theorem_statement="n + 0 = n を示せ",
            lean_code=LEAN_CODE,
            verified=True,
        )

    assert len(error_info.value.attempt_outputs) == 2


def test_reference_indentation_must_match_verified_lean_exactly() -> None:
    explainer, _client = build_explainer(
        explanation_payload(excerpt="simpa using Nat.add_zero n"),
        explanation_payload(excerpt="simpa using Nat.add_zero n"),
    )

    with pytest.raises(ExplanationGenerationError, match="exactly match"):
        explainer.explain(
            theorem_statement="n + 0 = n を示せ",
            lean_code=LEAN_CODE,
            verified=True,
        )


def test_rejects_non_positive_generation_attempt_budget() -> None:
    with pytest.raises(ValueError, match="between one and three"):
        LeanProofExplainer(
            client=FakeClient(),
            model="explain-model",
            provider="openai",
            max_attempts=0,
        )


def test_clarification_is_scoped_to_selected_section_and_lean() -> None:
    clarification = json.dumps(
        {
            "section_id": "apply-add-zero",
            "answer": (
                "加法では 0 を足しても値が変わりません。この性質を任意の自然数 n に"
                "当てはめると、左辺 n + 0 は n と等しくなります。したがって目標の"
                "等式が成り立ちます。"
            ),
            "key_points": ["0 を足しても値は変わりません。", "その性質を n に当てはめます。"],
            "references": [
                {
                    "start_line": 4,
                    "end_line": 4,
                    "excerpt": "  simpa using Nat.add_zero n",
                }
            ],
        },
        ensure_ascii=False,
    )
    explainer, client = build_explainer(explanation_payload(), clarification)
    explanation = explainer.explain(
        theorem_statement="n + 0 = n を示せ",
        lean_code=LEAN_CODE,
        verified=True,
    )

    result = explainer.clarify(
        theorem_statement="n + 0 = n を示せ",
        lean_code=LEAN_CODE,
        verified=True,
        explanation=explanation,
        section_id="apply-add-zero",
        selected_text="0 を足しても値が変わらない",
        after_clarification_id="clarification-parent",
        question="なぜ 0 を足しても値が変わらないのですか？",
    )

    assert result.section_id == "apply-add-zero"
    assert result.question == "なぜ 0 を足しても値が変わらないのですか？"
    assert result.references[0].start_line == 4
    assert "加法" in result.answer
    assert "Selected section id: apply-add-zero" in client.prompts[1]
    assert "Selected learner text: 0 を足しても値が変わらない" in client.prompts[1]
    assert "Preceding clarification id: clarification-parent" in client.prompts[1]
    assert "なぜ 0 を足しても値が変わらないのですか？" in client.prompts[1]
    assert "Canonical Lean line table" in client.prompts[1]
    assert "KaTeX-compatible LaTeX" in client.prompts[1]


def test_clarification_rejects_reference_outside_selected_section() -> None:
    clarification = json.dumps(
        {
            "section_id": "apply-add-zero",
            "answer": (
                "この説明は選択された節を詳しく扱いますが、引用箇所が異なるため"
                "正しい根拠としては利用できません。"
            ),
            "key_points": ["選択節との対応が必要です。", "引用範囲も一致が必要です。"],
            "references": [
                {"start_line": 1, "end_line": 1, "excerpt": "import Mathlib"}
            ],
        },
        ensure_ascii=False,
    )
    explainer, _client = build_explainer(
        explanation_payload(),
        clarification,
        clarification,
    )
    explanation = explainer.explain(
        theorem_statement="n + 0 = n を示せ",
        lean_code=LEAN_CODE,
        verified=True,
    )

    with pytest.raises(ExplanationGenerationError, match="selected Lean section"):
        explainer.clarify(
            theorem_statement="n + 0 = n を示せ",
            lean_code=LEAN_CODE,
            verified=True,
            explanation=explanation,
            section_id="apply-add-zero",
            question="ここがわからない",
        )


def test_pae_004_clarification_rejects_unverified_proof_before_prompt() -> None:
    explainer, client = build_explainer(explanation_payload())
    explanation = explainer.explain(
        theorem_statement="n + 0 = n を示せ",
        lean_code=LEAN_CODE,
        verified=True,
    )

    with pytest.raises(ExplanationGenerationError, match="accepted by Lean"):
        explainer.clarify(
            theorem_statement="n + 0 = n を示せ",
            lean_code=LEAN_CODE,
            verified=False,
            explanation=explanation,
            section_id="apply-add-zero",
            question="なぜ 0 を足しても値が変わらないのですか？",
        )

    assert len(client.prompts) == 1
