import json
import uuid
from dataclasses import replace

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
    ProofSemanticReviewUnavailable,
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
    assert _parse_json_object(r'{"excerpt":"first\n  second"}') == {"excerpt": "first\n  second"}

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
        "$|x^2-a^2|=|x-a||x+a|<\\varepsilon$ と評価できるため、$x^2$ は点 $a$ で連続です。"
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
    assert "reject duplicated substantive derivations or calculations" in prompt
    assert "Reject circular reasoning that assumes the requested claim" in prompt
    assert "rephrases the requested claim without a supporting argument" in prompt
    assert "Standard theorems may be used under their required hypotheses" in prompt
    assert "do not demand that every auxiliary lemma be proved again" in prompt
    assert "A brief final statement of the established result is allowed" in prompt
    assert "Reusing an expression to continue a deduction is also allowed" in prompt
    assert review == ProofOutputReview(
        kind="explanation",
        reviewer_provider="review-provider",
        reviewer_model="explain-model",
        session_id="33333333-3333-4333-8333-333333333333",
        rationale="Lean source supports the explanation.",
    )


def test_explanation_reviewer_gets_visible_prose_once_without_internal_labels() -> None:
    explanation = _reviewable_explanation()
    explanation = replace(
        explanation,
        sections=(replace(explanation.sections[0], title="INTERNAL_LABEL_NOT_VISIBLE"),),
    )
    client = FakeClient('{"approved": true, "rationale": "Grounded continuous proof."}')
    reviewer = LeanGroundedOutputReviewer(
        client=client,
        model="explain-model",
        provider="review-provider",
    )
    reviewer.review_explanation(
        theorem_statement="n + 0 = n を示せ",
        lean_code=LEAN_CODE,
        explanation=explanation,
        language="ja",
    )
    prompt = client.prompts[0]
    visible = prompt.split("BEGIN LEARNER-VISIBLE PROOF\n", 1)[1].split(
        "\nEND LEARNER-VISIBLE PROOF",
        1,
    )[0]
    assert visible == "\n\n".join(
        [
            explanation.overview,
            explanation.sections[0].summary,
            explanation.conclusion,
        ]
    )
    assert "INTERNAL_LABEL_NOT_VISIBLE" not in visible
    assert explanation.sections[0].references[0].excerpt not in visible
    structured = json.loads(
        prompt.split(
            "Candidate explanation JSON (structured evidence; field names and internal titles "
            "are not shown):\n",
            1,
        )[1]
    )
    assert structured["explanation"]["sections"][0]["title"] == "INTERNAL_LABEL_NOT_VISIBLE"
    assert structured["explanation"]["sections"][0]["references"][0]["excerpt"] == (
        explanation.sections[0].references[0].excerpt
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
    client = FakeClient(
        '{"approved": false, "rationale": "The output is not grounded."}',
        '{"approved": true, "rationale": "A second vote must not override rejection."}',
    )
    reviewer = LeanGroundedOutputReviewer(
        client=client,
        model="explain-model",
        provider="review-provider",
        max_attempts=3,
    )

    with pytest.raises(ProofOutputReviewError):
        reviewer.review_clarification(
            theorem_statement="n + 0 = n を示せ",
            lean_code=LEAN_CODE,
            explanation=explanation,
            clarification=clarification,
            language="ja",
            selected_text="選択した一意の式",
            after_clarification_id="parent-1",
            parent_clarification={
                "id": "parent-1",
                "question": "先の質問",
                "answer": "親でのみ定義した変数",
                "key_points": ["親の仮定", "親の結論"],
            },
        )

    prompt = client.prompts[0]
    assert "選択した一意の式" in prompt
    assert "親でのみ定義した変数" in prompt
    assert "先の質問" in prompt
    assert len(client.prompts) == 1
    assert "Candidate clarification JSON" in prompt
    assert clarification.answer in prompt
    assert explanation.sections[0].summary in prompt
    assert "reject a circular restatement" in prompt
    assert "Review the explanation as the learner reads it" not in prompt
    assert len(client.responses) == 1


@pytest.mark.parametrize("malformed_first", [False, True])
def test_independent_output_rejection_is_final_even_if_next_response_would_approve(
    malformed_first: bool,
) -> None:
    explanation = _reviewable_explanation()
    responses = [
        '{"approved": false, "rationale": "The derivation is repeated."}',
        '{"approved": true, "rationale": "The theorem is verified."}',
    ]
    if malformed_first:
        responses.insert(0, "not valid JSON")
    client = FakeClient(*responses)
    reviewer = LeanGroundedOutputReviewer(
        client=client,
        model="explain-model",
        provider="review-provider",
        max_attempts=3,
    )

    with pytest.raises(ProofOutputReviewError, match="rejected") as error:
        reviewer.review_explanation(
            theorem_statement="n + 0 = n を示せ",
            lean_code=LEAN_CODE,
            explanation=explanation,
            language="ja",
        )

    assert error.value.category == "rejected"
    assert error.value.rationale == "The derivation is repeated."
    assert error.value.session_id is not None
    assert len(client.prompts) == (2 if malformed_first else 1)
    assert len(client.responses) == 1
    assert json.loads(client.responses[0])["approved"] is True


def test_independent_output_reviewer_can_retry_an_invalid_schema() -> None:
    client = FakeClient(
        '{"approved": "yes", "rationale": "not a boolean"}',
        '{"approved": true, "rationale": "Continuous and grounded proof."}',
    )
    reviewer = LeanGroundedOutputReviewer(
        client=client,
        model="explain-model",
        provider="review-provider",
    )
    review = reviewer.review_explanation(
        theorem_statement="n + 0 = n を示せ",
        lean_code=LEAN_CODE,
        explanation=_reviewable_explanation(),
        language="ja",
    )
    assert review.rationale == "Continuous and grounded proof."
    assert len(client.prompts) == 2
    assert "failed schema validation" in client.prompts[1]


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


def test_independent_proof_reviewer_raises_operational_failure_when_review_cannot_complete(
) -> None:
    client = FakeClient('{"approved": true}')
    reviewer = LeanProofSemanticReviewer(
        client=client,
        model="explain-model",
        provider="openai",
        max_attempts=1,
        session_id_factory=lambda: uuid.UUID("33333333-3333-4333-8333-333333333333"),
    )

    with pytest.raises(ProofSemanticReviewUnavailable) as error:
        reviewer.review_proof(
            theorem_statement="Show that adding zero does not change a natural number.",
            formal_statement=None,
            target_declaration=LeanTargetDeclaration(
                kind="theorem",
                name="add_zero_nat",
                proposition="∀ n : Nat, n + 0 = n",
            ),
            lean_code=LEAN_CODE,
        )
    assert error.value.failure_kind == "schema"
    assert len(client.prompts) == 1


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
            ("$|x^2-a^2|=|x-a|\\cdot|x+a|\\le 2|x-a|(|a|+1)<\\epsilon$ と評価できるので連続です。"),
        ),
        (
            (
                "$\\varepsilon>0$ を任意に取ります。実数の点 $a$ を固定し、"
                "$\\delta=\\min(1,\\varepsilon/(3|a|+2))$ と定めます。"
                "この $\\delta$ は $\\delta>0$ です。"
            ),
            ("$|x^2-a^2|=|x+a|\\cdot|x-a|<\\varepsilon$ と評価できるので連続です。"),
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
    explainer, _ = build_explainer(epsilon_delta_payload(overview=overview, conclusion=conclusion))

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
            ("$|x^2-a^2|=|x-a||x+a|$ と因数分解します。別に $|x-a|<\\varepsilon$ とします。"),
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
        parent_clarification={
            "id": "clarification-parent",
            "question": "先の質問",
            "answer": "親回答だけの追加仮定",
            "key_points": ["仮定", "結論"],
        },
        question="なぜ 0 を足しても値が変わらないのですか？",
    )

    assert result.section_id == "apply-add-zero"
    assert result.question == "なぜ 0 を足しても値が変わらないのですか？"
    assert result.references[0].start_line == 4
    assert "加法" in result.answer
    assert "Selected section id: apply-add-zero" in client.prompts[1]
    assert "Selected learner text: 0 を足しても値が変わらない" in client.prompts[1]
    assert "Preceding clarification id: clarification-parent" in client.prompts[1]
    assert "親回答だけの追加仮定" in client.prompts[1]
    assert "先の質問" in client.prompts[1]
    assert "なぜ 0 を足しても値が変わらないのですか？" in client.prompts[1]
    assert "Canonical Lean line table" in client.prompts[1]
    assert "KaTeX-compatible LaTeX" in client.prompts[1]


@pytest.mark.parametrize("parent_revision", [False, True])
def test_canvas_revision_splices_only_selection_and_allows_shorter_proof(
    parent_revision: bool,
) -> None:
    explanation = _reviewable_explanation()
    current = (
        "保存済みの前半。値が変わらないという長い説明。保存済みの後半。"
        if parent_revision else explanation.sections[0].summary
    )
    selected = "値が変わらない"
    response = json.dumps({
        "section_id": "apply-add-zero", "answer": "簡潔にしました。",
        "replacement_text": "不変", "key_points": ["加法の単位元です。", "値は同じです。"],
        "references": [{"start_line": 4, "end_line": 4, "excerpt": "  simpa using Nat.add_zero n"}],
    }, ensure_ascii=False)
    explainer, client = build_explainer(response)
    parent = {
        "id": "parent", "question": "先の質問", "answer": "改善しました。",
        "key_points": ["一つ", "二つ"], "replacement_text": "前の修正",
        "revised_section": current,
    } if parent_revision else None
    result = explainer.clarify(
        theorem_statement="n + 0 = n を示せ", lean_code=LEAN_CODE, verified=True,
        explanation=explanation, section_id="apply-add-zero", question="短くして",
        selected_text=selected, parent_clarification=parent,
        after_clarification_id="parent" if parent_revision else None,
    )
    assert result.answer == "簡潔にしました。"
    assert result.replacement_text == "不変"
    assert result.revised_section == current.replace(selected, "不変", 1)
    assert len(result.revised_section) < len(current)
    assert explanation.sections[0].summary != result.revised_section
    assert "Current proof section" in client.prompts[0]
    assert current in client.prompts[0]

    review_client = FakeClient('{"approved": true, "rationale": "The shorter proof is grounded."}')
    reviewer = LeanGroundedOutputReviewer(
        client=review_client, model="explain-model", provider="independent",
    )
    reviewer.review_clarification(
        theorem_statement="n + 0 = n を示せ", lean_code=LEAN_CODE, explanation=explanation,
        clarification=result, language="ja", selected_text=selected, parent_clarification=parent,
    )
    assert result.revised_section in review_client.prompts[0]
    assert '"replacement_text": "不変"' in review_client.prompts[0]
    assert "entire revised section in the surrounding proof" in review_client.prompts[0]


@pytest.mark.parametrize("replacement", [None, "", "simpa", "`source`", "x" * 4001])
def test_canvas_revision_rejects_missing_or_unsafe_replacement(replacement: str | None) -> None:
    response = json.dumps({
        "section_id": "apply-add-zero", "answer": "改善しました。",
        "replacement_text": replacement, "key_points": ["一つ", "二つ"],
        "references": [{"start_line": 4, "end_line": 4, "excerpt": "  simpa using Nat.add_zero n"}],
    }, ensure_ascii=False)
    explainer, _ = build_explainer(response, response)
    with pytest.raises(ExplanationGenerationError):
        explainer.clarify(
            theorem_statement="n + 0 = n を示せ", lean_code=LEAN_CODE, verified=True,
            explanation=_reviewable_explanation(), section_id="apply-add-zero",
            question="改善して", selected_text="値が変わらない",
        )


@pytest.mark.parametrize("selection", ["存在しない範囲", "重複", "aa"])
def test_canvas_revision_rejects_stale_or_ambiguous_selection_without_model_call(
    selection: str,
) -> None:
    explainer, client = build_explainer()
    with pytest.raises(ExplanationGenerationError, match="exactly once"):
        explainer.clarify(
            theorem_statement="n + 0 = n を示せ", lean_code=LEAN_CODE, verified=True,
            explanation=_reviewable_explanation(), section_id="apply-add-zero", question="改善して",
            selected_text=selection,
            parent_clarification={"revised_section": "重複する箇所と重複する箇所 aaa"},
        )
    assert client.prompts == []


def test_clarification_rejects_reference_outside_selected_section() -> None:
    clarification = json.dumps(
        {
            "section_id": "apply-add-zero",
            "answer": (
                "この説明は選択された節を詳しく扱いますが、引用箇所が異なるため"
                "正しい根拠としては利用できません。"
            ),
            "key_points": ["選択節との対応が必要です。", "引用範囲も一致が必要です。"],
            "references": [{"start_line": 1, "end_line": 1, "excerpt": "import Mathlib"}],
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


def test_general_case_coverage_and_induction_guidance_preserve_soundness_gate() -> None:
    from pals_agent.explanations import _explanation_prompt, _output_review_prompt

    prompt = _explanation_prompt(
        theorem_statement="Prove by induction, including n=0.",
        lean_code=LEAN_CODE,
        language="en",
        require_epsilon_delta=False,
    )
    assert "before the final conclusion" in prompt
    assert "argument covers a case without extra assumptions" in prompt
    review = _output_review_prompt(
        theorem_statement="Prove by induction, including n=0.",
        lean_code=LEAN_CODE,
        explanation=_reviewable_explanation(),
        language="en",
    )
    assert "is valid induction, not circular reasoning" in review
    assert "specific missing base case" in review
    assert "Reject circular" in review
    assert "reject duplicated substantive derivations" in review


def test_automated_source_exposition_requires_bridges_without_literal_source_steps() -> None:
    from pals_agent.explanations import _explanation_prompt, _output_review_prompt

    source = "theorem target (n : Nat) : n + 0 = n := by simp"
    prompt = _explanation_prompt(
        theorem_statement="Every natural n satisfies n + 0 = n.",
        lean_code=source, language="en", require_epsilon_delta=False,
    )
    assert "Show each essential" in prompt
    assert "why its hypotheses hold" in prompt
    assert "Do not merely assert the key intermediate fact" in prompt
    assert "not written literally in the Lean source" in prompt
    assert "separately verified by Lean" in prompt
    review = _output_review_prompt(
        theorem_statement="Every natural n satisfies n + 0 = n.",
        lean_code=source, explanation=_reviewable_explanation(), language="en",
    )
    assert "Lean source lines alone are not grounds for rejection" in review
    assert "without a bibliographic citation or Lean lemma name" in review
    assert "Still reject a missing essential inference" in review
    assert "an unchecked necessary hypothesis" in review
    assert "Reject circular reasoning" in review
    assert "reject duplicated substantive derivations" in review


def test_automation_does_not_override_rejection_for_a_missing_mathematical_bridge() -> None:
    reason = "The argument asserts a key intermediate fact without establishing it."
    client = FakeClient(
        json.dumps({"approved": False, "rationale": reason}),
        json.dumps({"approved": True, "rationale": "The source compiled."}),
    )
    reviewer = LeanGroundedOutputReviewer(
        client=client, model="explain-model", provider="review-provider", max_attempts=2,
    )
    with pytest.raises(ProofOutputReviewError) as error:
        reviewer.review_explanation(
            theorem_statement="Every natural n satisfies n + 0 = n.",
            lean_code="theorem target (n : Nat) : n + 0 = n := by simp",
            explanation=_reviewable_explanation(), language="en",
        )
    assert error.value.category == "rejected"
    assert error.value.rationale == reason
    assert len(client.prompts) == 1
    assert len(client.responses) == 1


@pytest.mark.parametrize("raw", ["not json", '{"approved": "false", "rationale": "x"}'])
def test_semantic_review_schema_retry_is_bounded_without_echoing_raw_response(raw):
    client = FakeClient(raw, raw)
    reviewer = LeanProofSemanticReviewer(
        client=client, model="explain-model", provider="test", max_attempts=2
    )
    with pytest.raises(ProofSemanticReviewUnavailable) as error:
        reviewer.review_proof(
            theorem_statement="True", formal_statement=None,
            target_declaration=LeanTargetDeclaration(kind="example", name=None, proposition="True"),
            lean_code="example : True := by trivial", timeout_seconds=4,
        )
    assert error.value.failure_kind == "schema"
    assert len(client.prompts) == 2
    assert raw not in client.prompts[1]


def test_semantic_provider_error_is_never_retried_or_cast_as_math_rejection():
    calls = []

    class FailingClient:
        def generate(self, **kwargs):
            calls.append(kwargs)
            raise RuntimeError("private authorization and provider detail")

    reviewer = LeanProofSemanticReviewer(
        client=FailingClient(), model="explain-model", provider="test"
    )
    with pytest.raises(ProofSemanticReviewUnavailable) as error:
        reviewer.review_proof(
            theorem_statement="True", formal_statement=None,
            target_declaration=LeanTargetDeclaration(kind="example", name=None, proposition="True"),
            lean_code="example : True := by trivial",
        )
    assert error.value.failure_kind == "provider"
    assert len(calls) == 1
    assert "private" not in str(error.value)


def test_valid_semantic_rejection_is_final_without_schema_revote():
    client = FakeClient('{"approved": false, "rationale": "The requested target differs."}')
    reviewer = LeanProofSemanticReviewer(client=client, model="explain-model", provider="test")
    review = reviewer.review_proof(
        theorem_statement="False", formal_statement=None,
        target_declaration=LeanTargetDeclaration(kind="example", name=None, proposition="True"),
        lean_code="example : True := by trivial",
    )
    assert review.decision == "rejected"
    assert len(client.prompts) == 1


def test_learner_facing_math_prompts_require_tex_for_membership_and_radicals() -> None:
    from pals_agent.explanations import (
        _clarification_prompt,
        _explanation_prompt,
        _output_review_prompt,
    )

    explanation = _reviewable_explanation()
    generation = _explanation_prompt(
        theorem_statement="x^m∈I ならば x∈√(IJ)",
        lean_code=LEAN_CODE,
        language="ja",
    )
    clarification = _clarification_prompt(
        theorem_statement="x^m∈I ならば x∈√(IJ)",
        lean_code=LEAN_CODE,
        explanation=explanation,
        selected=explanation.sections[0],
        question="なぜ x∈√(IJ) ですか？",
        language="ja",
    )
    review = _output_review_prompt(
        theorem_statement="x^m∈I ならば x∈√(IJ)",
        lean_code=LEAN_CODE,
        explanation=explanation,
        language="ja",
    )
    for prompt in (generation, clarification, review):
        assert "$x^m\\in I$" in prompt
        assert "$x\\in\\sqrt{IJ}$" in prompt
        assert "never bare" in prompt or "raw `x^m∈I`" in prompt
    assert "Escape each TeX backslash as `\\\\`" in generation
    assert "Escape each TeX backslash as `\\\\`" in clarification
    assert "Reject learner-visible mathematical expressions outside `$...$`" in review


def test_stated_conventions_are_premises_for_explanation_and_its_review() -> None:
    from pals_agent.explanations import _explanation_prompt, _output_review_prompt

    statement = (
        "Prove that x^0 = 1 for every real number x.\n\n"
        "Conventions: 0^0 = 1. Every other definition keeps its standard meaning."
    )
    prompt = _explanation_prompt(
        theorem_statement=statement, lean_code=LEAN_CODE, language="en",
        require_epsilon_delta=False,
    )
    review = _output_review_prompt(
        theorem_statement=statement, lean_code=LEAN_CODE,
        explanation=_reviewable_explanation(), language="en",
    )
    for text in (prompt, review):
        assert "is a premise of the claim" in text
        assert "convention or by the corresponding definition is valid" in text
        assert "every other definition keeps its standard meaning" in text
        assert "0^0 = 1 settles only the base 0" in text
        assert "citing either is valid and is not a wrong justification" in text
        assert statement in text
    # The existing soundness gates are unchanged.
    assert "Reject circular reasoning" in review
    assert "A true equality with a wrong stated justification" in review
