from __future__ import annotations

import json
from typing import Any

import pytest

from pals_agent.explanations import (
    ExplanationGenerationError,
    LeanProofExplainer,
    proof_explanation_from_api,
)

LEAN_CODE = "example : True := by\n  trivial"
REFERENCE = {"start_line": 2, "end_line": 2, "excerpt": "  trivial"}


class FakeClient:
    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses = [json.dumps(item, ensure_ascii=False) for item in responses]
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
        return self.responses.pop(0)


def _explanation_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "overview": "証明の方針です。",
        "sections": [
            {
                "id": "finish",
                "title": "証明を閉じる",
                "summary": "目標である True は、定義からすぐに成り立つ命題です。",
                "references": [REFERENCE],
            }
        ],
        "conclusion": "したがって True が証明されました。",
        "model": "explain-model",
        "provider": "test-provider",
        "elapsed_ms": 1,
    }
    payload.update(overrides)
    return payload


def _explainer(*responses: dict[str, Any]) -> tuple[LeanProofExplainer, FakeClient]:
    client = FakeClient(*responses)
    return (
        LeanProofExplainer(
            client=client,
            model="explain-model",
            provider="test-provider",
            max_attempts=1,
        ),
        client,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("overview", "日"),
        ("overview", "日" + "a" * 599),
        ("conclusion", "結"),
        ("conclusion", "結" + "a" * 599),
    ],
)
def test_pae_002_overview_and_conclusion_accept_exact_codepoint_boundaries(
    field: str,
    value: str,
) -> None:
    explanation = proof_explanation_from_api(
        _explanation_payload(**{field: value}),
        lean_code=LEAN_CODE,
    )

    assert getattr(explanation, field) == value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("overview", ""),
        ("overview", "日" + "a" * 600),
        ("overview", "ASCII only"),
        ("conclusion", "\u3000\u00a0"),
    ],
)
def test_pae_002_overview_and_conclusion_reject_invalid_shape(
    field: str,
    value: str,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        proof_explanation_from_api(
            _explanation_payload(**{field: value}),
            lean_code=LEAN_CODE,
        )


def test_pae_002_section_text_boundaries_and_storage_are_exact() -> None:
    title = "\u3000日" + "a" * 79 + "\u3000"
    summary = "\u00a0要" + "a" * 799 + "\u00a0"
    payload = _explanation_payload()
    payload["sections"][0]["title"] = title
    payload["sections"][0]["summary"] = summary

    explanation = proof_explanation_from_api(payload, lean_code=LEAN_CODE)

    assert explanation.sections[0].title == title
    assert explanation.sections[0].summary == summary


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "題" + "a" * 80),
        ("title", "title only"),
        ("summary", "要" + "a" * 800),
        ("summary", 123),
    ],
)
def test_pae_002_section_text_rejects_out_of_bounds_or_non_japanese(
    field: str,
    value: Any,
) -> None:
    payload = _explanation_payload()
    payload["sections"][0][field] = value

    with pytest.raises((TypeError, ValueError)):
        proof_explanation_from_api(payload, lean_code=LEAN_CODE)


@pytest.mark.parametrize(("count", "valid"), [(1, True), (20, True), (0, False), (21, False)])
def test_pae_002_section_cardinality_is_one_through_twenty(
    count: int,
    valid: bool,
) -> None:
    payload = _explanation_payload()
    template = payload["sections"][0]
    payload["sections"] = [
        {**template, "id": f"section-{index}"} for index in range(count)
    ]

    if valid:
        assert len(proof_explanation_from_api(payload, lean_code=LEAN_CODE).sections) == count
    else:
        with pytest.raises(ValueError):
            proof_explanation_from_api(payload, lean_code=LEAN_CODE)


@pytest.mark.parametrize(("count", "valid"), [(1, True), (20, True), (0, False), (21, False)])
def test_pae_002_reference_cardinality_is_one_through_twenty(
    count: int,
    valid: bool,
) -> None:
    payload = _explanation_payload()
    payload["sections"][0]["references"] = [dict(REFERENCE) for _ in range(count)]

    if valid:
        section = proof_explanation_from_api(payload, lean_code=LEAN_CODE).sections[0]
        assert len(section.references) == count
    else:
        with pytest.raises(ValueError):
            proof_explanation_from_api(payload, lean_code=LEAN_CODE)


def _clarification_payload(
    *,
    answer: Any | None = None,
    key_points: Any | None = None,
    references: Any | None = None,
) -> dict[str, Any]:
    return {
        "section_id": "finish",
        "answer": answer
        if answer is not None
        else (
            "詳しい説明として、この命題は前提を追加せずに成り立つ形なので、"
            "残った目標を直接確認して証明を閉じます。"
        ),
        "key_points": key_points
        if key_points is not None
        else ["目標は True です。", "この形の命題は追加の仮定なしに成り立ちます。"],
        "references": references if references is not None else [REFERENCE],
    }


def _generate_clarification(payload: dict[str, Any]) -> Any:
    explanation_payload = _explanation_payload()
    explanation = proof_explanation_from_api(explanation_payload, lean_code=LEAN_CODE)
    explainer, _client = _explainer(payload)
    return explainer.clarify(
        theorem_statement="True を証明せよ",
        lean_code=LEAN_CODE,
        verified=True,
        explanation=explanation,
        section_id="finish",
        question="trivial はなぜ使えますか？",
    )


@pytest.mark.parametrize("length", [40, 4000])
def test_pae_004_answer_accepts_exact_codepoint_boundaries(length: int) -> None:
    answer = "詳" + "あ" * (length - 1)

    result = _generate_clarification(_clarification_payload(answer=answer))

    assert result.answer == answer


@pytest.mark.parametrize(
    "answer",
    ["詳" + "あ" * 38, "詳" + "あ" * 4000, "a" * 100],
)
def test_pae_004_answer_rejects_length_and_language_violations(answer: str) -> None:
    with pytest.raises(ExplanationGenerationError):
        _generate_clarification(_clarification_payload(answer=answer))


@pytest.mark.parametrize(("count", "valid"), [(2, True), (10, True), (1, False), (11, False)])
def test_pae_004_key_point_cardinality_is_two_through_ten(
    count: int,
    valid: bool,
) -> None:
    points = [f"要点 {index}" for index in range(count)]

    if valid:
        assert len(
            _generate_clarification(_clarification_payload(key_points=points)).key_points
        ) == count
    else:
        with pytest.raises(ExplanationGenerationError):
            _generate_clarification(_clarification_payload(key_points=points))


@pytest.mark.parametrize("points", [["a" * 501, "要点"], [1, "要点"], ["\u3000", "要点"]])
def test_pae_004_key_points_are_strict_nonblank_bounded_strings(points: list[Any]) -> None:
    with pytest.raises(ExplanationGenerationError):
        _generate_clarification(_clarification_payload(key_points=points))


def test_pae_004_answer_must_be_longer_and_not_repeat_normalized_summary() -> None:
    summary = _explanation_payload()["sections"][0]["summary"]
    normalized_summary = summary.replace(" ", "\u00a0" * 20)
    repeated = f"\u3000{normalized_summary}\u3000"

    with pytest.raises(ExplanationGenerationError, match="longer"):
        _generate_clarification(_clarification_payload(answer=repeated))


@pytest.mark.parametrize(("count", "valid"), [(1, True), (20, True), (0, False), (21, False)])
def test_pae_004_clarification_reference_cardinality_is_bounded(
    count: int,
    valid: bool,
) -> None:
    payload = _clarification_payload(references=[dict(REFERENCE) for _ in range(count)])
    if valid:
        assert len(_generate_clarification(payload).references) == count
    else:
        with pytest.raises(ExplanationGenerationError):
            _generate_clarification(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("overview", "この段階では simp により式を整理します。"),
        ("conclusion", "したがって Metric.continuous_iff が使えます。"),
    ],
)
def test_pae_002_learner_prose_rejects_lean_commands_and_identifiers(
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match="Lean"):
        proof_explanation_from_api(
            _explanation_payload(**{field: value}),
            lean_code=LEAN_CODE,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "rw の意味"),
        ("summary", "ここでは `exact h` を使います。"),
    ],
)
def test_pae_002_learner_section_prose_rejects_lean_source(
    field: str,
    value: str,
) -> None:
    payload = _explanation_payload()
    payload["sections"][0][field] = value

    with pytest.raises(ValueError, match="Lean"):
        proof_explanation_from_api(payload, lean_code=LEAN_CODE)


@pytest.mark.parametrize(
    ("answer", "key_points"),
    [
        ("詳しい説明として、simp により目標を変形して結論を得ます。" * 2, None),
        (None, ["rw で等式を書き換えます。", "数学的な関係を確認します。"]),
    ],
)
def test_pae_004_learner_clarification_rejects_lean_source(
    answer: str | None,
    key_points: list[str] | None,
) -> None:
    with pytest.raises(ExplanationGenerationError, match="Lean"):
        _generate_clarification(
            _clarification_payload(answer=answer, key_points=key_points)
        )


def test_pae_005_prompts_name_both_sources_and_exclude_evaluation_sentinels() -> None:
    explainer, client = _explainer(
        _explanation_payload(),
        _clarification_payload(),
    )
    explanation = explainer.explain(
        theorem_statement="True を証明せよ",
        lean_code=LEAN_CODE,
        verified=True,
    )
    explainer.clarify(
        theorem_statement="True を証明せよ",
        lean_code=LEAN_CODE,
        verified=True,
        explanation=explanation,
        section_id="finish",
        question="なぜですか？",
    )

    for prompt in client.prompts:
        lowered = prompt.lower()
        assert "theorem statement" in lowered
        assert "verified lean" in lowered
        assert "only sources of truth" in lowered
        assert "user-facing rationale" in lowered
        assert "lean identifiers" in lowered
        assert "suite strategy" not in lowered
        assert "rubric" not in lowered
        assert "expect_clarification" not in lowered
