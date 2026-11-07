"""Presentation/language instructions are separated from the claim the proof review judges."""

from __future__ import annotations

import json
import uuid

import pytest

from pals_agent.explanations import LeanProofSemanticReviewer, _proof_semantic_review_prompt
from pals_agent.lean_target import LeanTargetDeclaration
from pals_agent.request_instructions import (
    SCHEMA_VERSION,
    build_table,
    split_presentation_instructions,
)

# The statements the production router produced (proof_jobs.theorem_statement).
CLAIM = "Prove that the function f: ℝ → ℝ defined by f(x) = x² is continuous on ℝ."
INSTRUCTION = "Write the proposition and the entire proof in English."
PRODUCTION_WITH_INSTRUCTION = f"{CLAIM} {INSTRUCTION}"
EXPLAIN_STATEMENT = (
    "Explain why the function f : ℝ → ℝ defined by f(x) = x² is continuous on ℝ."
)
JAPANESE_STATEMENT = (
    "実数上の関数 f: ℝ → ℝ を f(x) = x² と定める。f が ℝ のすべての点で連続であることを証明せよ。"
)


@pytest.mark.parametrize(
    "statement",
    [
        PRODUCTION_WITH_INSTRUCTION,
        # spacing variants of the same two statements
        f"{CLAIM}{INSTRUCTION}",
        f"{CLAIM}   Write the proposition  and the entire proof in English.",
        f"{CLAIM}\n\n{INSTRUCTION}",
        f"{CLAIM} Write the proposition and the entire proof in English",
        f"{CLAIM}  write the proposition and the entire proof in english.  ",
        f"{CLAIM} Please write the proposition and the entire proof in English.",
    ],
)
def test_the_production_instruction_is_separated_from_the_claim(statement: str) -> None:
    split = split_presentation_instructions(statement)
    assert split.claim == CLAIM
    assert len(split.instructions) == 1
    assert "entire proof in english" in split.instructions[0].lower()


@pytest.mark.parametrize("statement", [CLAIM, EXPLAIN_STATEMENT, JAPANESE_STATEMENT])
def test_a_statement_without_an_instruction_is_unchanged(statement: str) -> None:
    split = split_presentation_instructions(statement)
    assert split.claim == statement
    assert split.instructions == ()


@pytest.mark.parametrize(
    ("statement", "claim"),
    [
        # Japanese
        ("x²の連続性を英語で証明せよ", "x²の連続性を証明せよ"),
        ("x²は連続であることを英語で書いて", "x²は連続である"),
        (
            "f(x)=x² が連続であることを、命題も証明も英語で書いてください。",
            "f(x)=x² が連続である。",
        ),
        (f"{JAPANESE_STATEMENT} 命題と証明をすべて英語で書いてください。", JAPANESE_STATEMENT),
        # Chinese
        ("请用英语写出命题和证明：x² 在实数上连续", "x² 在实数上连续"),
        ("請用英文寫出命題和證明：x² 在實數上連續", "x² 在實數上連續"),
        ("请用英语证明 x² 连续", "证明 x² 连续"),
        # another language and several instructions
        (f"{CLAIM} Answer in French, step by step.", CLAIM),
        (f"{CLAIM} Write the entire proof in Japanese. Be brief: answer concisely.", None),
        ("Prove x² is continuous, and answer in English, step by step.", "Prove x² is continuous."),
    ],
)
def test_other_languages_and_several_instructions(statement: str, claim: str | None) -> None:
    split = split_presentation_instructions(statement)
    assert split.instructions
    if claim is not None:
        assert split.claim == claim
    assert "in Japanese" not in split.claim and "French" not in split.claim
    assert "英語で" not in split.claim and "用英" not in split.claim


def test_a_method_the_learner_requires_is_part_of_the_claim() -> None:
    statement = (
        "Prove that x² is continuous using the epsilon-delta definition. "
        "Write the entire proof in English."
    )
    split = split_presentation_instructions(statement)
    assert split.claim == "Prove that x² is continuous using the epsilon-delta definition."
    assert "epsilon-delta" not in " ".join(split.instructions)
    japanese = split_presentation_instructions("x²の連続性をε-δ論法で証明せよ。英語で書いて。")
    assert "ε-δ論法で" in japanese.claim


def test_appended_conventions_survive_the_separation() -> None:
    statement = f"{CLAIM} {INSTRUCTION}\n\nConventions: natural numbers start at 1."
    split = split_presentation_instructions(statement)
    assert split.claim.startswith(CLAIM)
    assert split.claim.endswith("Conventions: natural numbers start at 1.")
    assert "Write" not in split.claim


def test_nothing_is_left_of_a_pure_instruction_so_it_is_kept() -> None:
    split = split_presentation_instructions("Write the proof in English.")
    assert split.claim == "Write the proof in English."
    assert split.instructions == ()


@pytest.mark.parametrize(
    "statement",
    [PRODUCTION_WITH_INSTRUCTION, "x²の連続性を英語で証明せよ", f"{CLAIM} Answer in French."],
)
def test_the_separation_is_idempotent(statement: str) -> None:
    once = split_presentation_instructions(statement)
    twice = split_presentation_instructions(once.claim)
    assert twice.claim == once.claim and twice.instructions == ()


def test_a_new_language_is_a_row_not_a_code_change() -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "language_names_en": ["klingon"],
        "language_names_cjk": [],
        "patterns": [{"id": "en.in_language", "re": r"\b(?:in|using)\s+(?:{LANG_EN})\b"}],
    }
    table = build_table(payload)
    assert split_presentation_instructions("Prove 1 + 1 = 2 in Klingon.", table=table).claim == (
        "Prove 1 + 1 = 2 ."
    ) or split_presentation_instructions("Prove 1 + 1 = 2 in Klingon.", table=table).claim == (
        "Prove 1 + 1 = 2."
    )
    with pytest.raises(RuntimeError):
        build_table({**payload, "schema_version": "wrong"})
    with pytest.raises(RuntimeError):  # a pattern that matches the empty text would eat the claim
        build_table({**payload, "patterns": [{"id": "x", "re": r"a*"}]})
    with pytest.raises(RuntimeError):
        build_table({**payload, "patterns": payload["patterns"] * 2})


# --- the independent proof review sees only the claim ------------------------------------------


class _Client:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, *, model: str, prompt: str, timeout_seconds: float | None = None) -> str:
        self.prompts.append(prompt)
        return json.dumps({"approved": True, "rationale": "The target is the requested claim."})


TARGET = LeanTargetDeclaration(
    kind="theorem", name="x2_continuous", proposition="Continuous (fun x : ℝ => x ^ 2)"
)
LEAN = "theorem x2_continuous : Continuous (fun x : ℝ => x ^ 2) := by\n  continuity\n"


@pytest.mark.parametrize(
    "statement",
    [PRODUCTION_WITH_INSTRUCTION, f"{CLAIM}   {INSTRUCTION}", f"{CLAIM}\n{INSTRUCTION}"],
)
def test_the_reviewer_prompt_has_the_claim_and_not_the_presentation_instruction(
    statement: str,
) -> None:
    client = _Client()
    reviewer = LeanProofSemanticReviewer(
        client=client,  # type: ignore[arg-type]
        model="m",
        provider="p",
        session_id_factory=lambda: uuid.UUID("33333333-3333-4333-8333-333333333333"),
    )
    reviewer.review_proof(
        theorem_statement=statement,
        formal_statement=None,
        target_declaration=TARGET,
        lean_code=LEAN,
    )
    prompt = client.prompts[0]
    request_section = prompt.split("Learner request:\n", 1)[1].split(
        "\n\nLearner-provided formal statement:", 1
    )[0]
    assert request_section.startswith(CLAIM)
    assert "entire proof in English" not in request_section
    assert "Write the proposition" not in prompt
    assert "were removed from this request" in request_section
    # the standing rule: a presentation request is never a reason to reject a Lean artifact
    assert "never by this Lean artifact" in prompt
    assert "Never reject because the Lean source is not\nprose" in prompt


def test_a_request_without_an_instruction_is_reviewed_as_written() -> None:
    prompt = _proof_semantic_review_prompt(
        theorem_statement=EXPLAIN_STATEMENT,
        formal_statement=None,
        target_declaration=TARGET,
        lean_code=LEAN,
    )
    assert f"Learner request:\n{EXPLAIN_STATEMENT}\n\nLearner-provided" in prompt
    assert "were removed from this request" not in prompt
