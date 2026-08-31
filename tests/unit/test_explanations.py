import json
import uuid

import pytest

from pals_agent.explanations import (
    ExplanationGenerationError,
    LeanGroundedOutputReviewer,
    LeanProofExplainer,
    LeanProofSemanticReviewer,
    ProofClarification,
    ProofExplanation,
    ProofOutputReview,
    ProofOutputReviewError,
    _parse_json_object,
)
from pals_agent.lean_target import LeanTargetDeclaration

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


def test_explanation_json_parser_repairs_only_bare_latex_backslashes() -> None:
    assert _parse_json_object(r'{"formula":"\varepsilon>0,\underbrace{x}"}') == {
        "formula": r"\varepsilon>0,\underbrace{x}"
    }
    assert _parse_json_object(r'{"formula":"\text{x}\neq y\to z"}') == {
        "formula": r"\text{x}\neq y\to z"
    }
    assert _parse_json_object(r'{"excerpt":"first\n  second"}') == {
        "excerpt": "first\n  second"
    }

    with pytest.raises(json.JSONDecodeError):
        _parse_json_object('{"formula": }')


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


def _reviewable_explanation() -> ProofExplanation:
    explainer, _client = build_explainer(explanation_payload())
    return explainer.explain(
        theorem_statement="n + 0 = n を示せ",
        lean_code=LEAN_CODE,
        verified=True,
    )


def test_independent_output_reviewer_requires_explicit_approval_against_lean_source() -> None:
    explanation = _reviewable_explanation()
    client = FakeClient('{"approved": true, "rationale": "Lean source supports the explanation."}')
    reviewer = LeanGroundedOutputReviewer(
        client=client,
        model="explain-model",
        provider="review-provider",
        session_id_factory=lambda: uuid.UUID("33333333-3333-4333-8333-333333333333"),
    )

    review = reviewer.review_explanation(
        theorem_statement="n + 0 = n を示せ",
        lean_code=LEAN_CODE,
        explanation=explanation,
        language="ja",
    )

    prompt = client.prompts[0]
    assert "independent review session" in prompt
    assert LEAN_CODE in prompt
    assert explanation.overview in prompt
    assert '"approved": true' in prompt
    assert (
        "Mathematical notation, formula variables, and exact Lean excerpts are language-neutral"
        in prompt
    )
    assert "standard mathematical derivations of its stated claim are grounded" in prompt
    assert review == ProofOutputReview(
        kind="explanation",
        reviewer_provider="review-provider",
        reviewer_model="explain-model",
        session_id="33333333-3333-4333-8333-333333333333",
        rationale="Lean source supports the explanation.",
    )


def test_independent_output_reviewer_rejects_nonapproval_and_checks_clarification_context() -> None:
    explanation = _reviewable_explanation()
    clarification = ProofClarification(
        section_id="apply-add-zero",
        question="なぜ成り立ちますか？",
        answer="この等式は、任意の自然数に 0 を加えても値が変化しないという性質を使います。",
        key_points=("0 は加法の単位元です。", "等式の両辺は同じ値です。"),
        references=explanation.sections[0].references,
        model="explain-model",
        provider="test-provider",
        prompt="private",
        raw_model_output="private",
        elapsed_ms=1,
    )
    client = FakeClient('{"approved": false, "rationale": "The output is not grounded."}')
    reviewer = LeanGroundedOutputReviewer(
        client=client,
        model="explain-model",
        provider="review-provider",
        max_attempts=1,
    )

    with pytest.raises(ProofOutputReviewError):
        reviewer.review_clarification(
            theorem_statement="n + 0 = n を示せ",
            lean_code=LEAN_CODE,
            explanation=explanation,
            clarification=clarification,
            language="ja",
        )

    prompt = client.prompts[0]
    assert len(client.prompts) == 1
    assert "Candidate clarification JSON" in prompt
    assert clarification.answer in prompt
    assert explanation.sections[0].summary in prompt


def test_independent_output_reviewer_rechecks_a_rejection_without_biasing_the_decision() -> None:
    explanation = _reviewable_explanation()
    client = FakeClient(
        '{"approved": false, "rationale": "The first review is inconclusive."}',
        '{"approved": true, "rationale": "The verified theorem supports the explanation."}',
    )
    reviewer = LeanGroundedOutputReviewer(
        client=client,
        model="explain-model",
        provider="review-provider",
    )

    review = reviewer.review_explanation(
        theorem_statement="n + 0 = n を示せ",
        lean_code=LEAN_CODE,
        explanation=explanation,
        language="ja",
    )

    assert review.rationale == "The verified theorem supports the explanation."
    assert len(client.prompts) == 2
    assert "Do not infer a preferred outcome from this retry." in client.prompts[1]


def test_independent_proof_reviewer_binds_its_decision_to_one_new_session() -> None:
    client = FakeClient(
        json.dumps(
            {
                "approved": True,
                "rationale": "The extracted target is the requested natural-number identity.",
            }
        )
    )
    reviewer = LeanProofSemanticReviewer(
        client=client,
        model="explain-model",
        provider="openai",
        session_id_factory=lambda: uuid.UUID("33333333-3333-4333-8333-333333333333"),
    )

    review = reviewer.review_proof(
        theorem_statement="Show that adding zero does not change a natural number.",
        formal_statement="∀ n : Nat, n + 0 = n",
        target_declaration=LeanTargetDeclaration(
            kind="theorem",
            name="add_zero_nat",
            proposition="∀ n : Nat, n + 0 = n",
        ),
        lean_code=LEAN_CODE,
    )

    assert review.decision == "approved"
    assert review.rationale.startswith("The extracted target")
    assert review.reviewer_provider == "openai"
    assert review.reviewer_model == "explain-model"
    assert review.session_id == "33333333-3333-4333-8333-333333333333"
    assert "independent proof-review session" in client.prompts[0]
    assert LEAN_CODE in client.prompts[0]


def test_independent_proof_reviewer_returns_rejected_when_review_cannot_complete() -> None:
    client = FakeClient('{"approved": true}')
    reviewer = LeanProofSemanticReviewer(
        client=client,
        model="explain-model",
        provider="openai",
        max_attempts=1,
        session_id_factory=lambda: uuid.UUID("33333333-3333-4333-8333-333333333333"),
    )

    review = reviewer.review_proof(
        theorem_statement="Show that adding zero does not change a natural number.",
        formal_statement=None,
        target_declaration=LeanTargetDeclaration(
            kind="theorem",
            name="add_zero_nat",
            proposition="∀ n : Nat, n + 0 = n",
        ),
        lean_code=LEAN_CODE,
    )

    assert review.decision == "rejected"
    assert review.rationale == "The independent proof review could not be completed."
    assert review.session_id == "33333333-3333-4333-8333-333333333333"


@pytest.mark.parametrize(
    ("language", "overview", "title", "summary", "conclusion"),
    [
        (
            "en",
            "Adding zero leaves a natural number unchanged.",
            "Additive identity",
            "The additive identity gives the required equality for every natural number.",
            "Therefore the equality holds for every natural number.",
        ),
        (
            "ja",
            "自然数にゼロを加えても値は変わりません。",
            "恒等性を使う",
            "加法の単位元の性質から、すべての自然数で等式が成り立ちます。",
            "したがって、任意の自然数でこの等式が成立します。",
        ),
        (
            "zh-Hans",
            "自然数加上零后数值不变。",
            "应用恒等性质",
            "加法单位元的性质说明每个自然数都满足这个等式。",
            "因此，这个等式对所有自然数成立。",
        ),
        (
            "zh-Hant",
            "自然數加上零後數值不變。",
            "套用恆等性質",
            "加法單位元的性質說明每個自然數都滿足這個等式。",
            "因此，這個等式對所有自然數成立。",
        ),
    ],
)
def test_explanation_accepts_each_saved_chat_language(
    language: str,
    overview: str,
    title: str,
    summary: str,
    conclusion: str,
) -> None:
    payload = json.dumps(
        {
            "overview": overview,
            "sections": [
                {
                    "id": "apply-identity",
                    "title": title,
                    "summary": summary,
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
    explainer, client = build_explainer(payload)

    result = explainer.explain(
        theorem_statement="Show that adding zero does not change a natural number.",
        lean_code=LEAN_CODE,
        verified=True,
        language=language,
    )

    assert result.overview == overview
    assert result.sections[0].title == title
    assert f"Output language: {language}" in client.prompts[0]


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
    assert "Do not create visible section titles" in client.prompts[0]
    assert "section is only an internal anchor" in client.prompts[0]
    assert "Use direct proof prose" in client.prompts[0]
    assert "We will show" in client.prompts[0]
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


def test_x_squared_continuity_accepts_english_epsilon_delta_explanation() -> None:
    payload = json.dumps(
        {
            "overview": (
                "$\\varepsilon>0$ is arbitrary. Fix a real point $a$ and choose "
                "$\\delta=\\min\\!\\left(1,\\frac{\\varepsilon}{2|a|+1}\\right)>0$."
            ),
            "sections": [
                {
                    "id": "bound-the-difference",
                    "title": "Bound the difference",
                    "summary": (
                        "Assume $|x-a|<\\delta$. Then "
                        "$|x^2-a^2|=|x-a|\\,|x+a|"
                        ". Therefore $|x^2-a^2|<\\delta(2|a|+1)"
                        "\\le\\varepsilon$."
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
            "conclusion": "Therefore $x^2$ is continuous.",
        }
    )
    explainer, _ = build_explainer(payload)

    result = explainer.explain(
        theorem_statement="x^2 が連続であることを証明してください。",
        lean_code=LEAN_CODE,
        verified=True,
        language="en",
    )

    assert result.conclusion == "Therefore $x^2$ is continuous."


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
