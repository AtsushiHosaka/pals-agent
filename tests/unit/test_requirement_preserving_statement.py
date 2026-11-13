# ruff: noqa: E501
"""Generation prompts carry the statement requirements a request imposes (default off).

Measured (testdata/answer-accuracy-regression-v1): the post-Lean semantic review rejected every
verified candidate whose Lean statement did not carry an explicit witness or the requested
definition, and approved those that did. The guidance is generic over requirement kinds
(explicit witness, specified definition); the review prompt is untouched.
"""

from __future__ import annotations

import pytest

from pals_agent.generator import (
    REQUIREMENT_PRESERVING_ENV,
    _problem_section,
    _sketch_prompt_for,
    requirement_guidance,
)
from pals_agent.models import GeneratedDraft, ProofRequest

WITNESS = "数列 $a_n=1/(n+1)$ が $0$ に収束することを、明示的な N を与えて示せ。"
DEFINITION = "関数 $x^2$ が連続であることを、連続の ε-δ 定義を使って示せ。"
PLAIN = "整数 $a,b$ がともに偶数ならば $a+b$ も偶数であることを示せ。"


def test_off_by_default_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(REQUIREMENT_PRESERVING_ENV, raising=False)
    assert requirement_guidance(WITNESS) == ""
    assert "Requirements of this request" not in _problem_section(ProofRequest(id="x", prompt=WITNESS))


def test_flag_must_be_a_strict_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REQUIREMENT_PRESERVING_ENV, "yes")
    with pytest.raises(ValueError):
        requirement_guidance(WITNESS)


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        (WITNESS, "explicit witness"),
        ("Show 1/(n+1) -> 0 by giving an explicit N(ε) in terms of ε.", "explicit witness"),
        ("f(x)=3x+1 の連続性を示せ。δ を ε の式で明示せよ。", "explicit witness"),
        (DEFINITION, "specific definition"),
        ("Prove continuity of x^2 using the definition of continuity.", "specific definition"),
        ("連続性を ε-δ 論法で示せ。", "specific definition"),
    ],
)
def test_requirement_kinds_are_detected(monkeypatch: pytest.MonkeyPatch, prompt: str, expected: str) -> None:
    monkeypatch.setenv(REQUIREMENT_PRESERVING_ENV, "true")
    text = requirement_guidance(prompt)
    assert expected in text
    assert "statement itself must carry" in text


@pytest.mark.parametrize(
    "prompt",
    [
        PLAIN,
        "Prove that the sum of two even integers is even.",
        "極限を求めよ。",
        "素数 p が ab を割り切るなら p は a か b を割り切ることを示せ。",
        "この定理の意味を説明してください。",
    ],
)
def test_requests_without_such_requirements_get_no_guidance(monkeypatch: pytest.MonkeyPatch, prompt: str) -> None:
    monkeypatch.setenv(REQUIREMENT_PRESERVING_ENV, "true")
    assert requirement_guidance(prompt) == ""


def test_guidance_reaches_the_generation_prompts_and_names_no_specific_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REQUIREMENT_PRESERVING_ENV, "true")
    request = ProofRequest(id="x", prompt=WITNESS + DEFINITION)
    section = _problem_section(request)
    assert "explicit witness" in section and "specific definition" in section
    # generic wording only: no concrete witness expression for a particular problem
    assert "⌈" not in section and "1/ε" not in section
    draft = GeneratedDraft(text="Draft.", model="m", raw_model_output="")
    assert "statement itself must carry" in _sketch_prompt_for(request, draft)
