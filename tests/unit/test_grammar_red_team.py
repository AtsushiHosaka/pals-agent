"""Regression tests for the inputs the red team of the widened grammar found (2026-11-08).

Each group names the failure: a request that used to be read as a different claim than the one
written (so a verified proof of another statement would have been shown), or an instruction
split that changed or mangled the claim.
"""

# ruff: noqa: E501  (the inputs are the test data)
from __future__ import annotations

import pytest

from pals_agent.lean_templates import template_proof_for_request
from pals_agent.models import ProofRequest
from pals_agent.request_instructions import split_presentation_instructions
from pals_agent.request_proposition import parse_request

SQUARE = "Continuous (fun x : ℝ => x ^ 2)"


def proposition(text: str) -> str | None:
    parsed = parse_request(text)
    return parsed.proposition if parsed else None


def template(text: str) -> bool:
    return template_proof_for_request(ProofRequest(id="rt", prompt=text)) is not None


def assert_miss(text: str) -> None:
    assert proposition(text) is None, text
    assert not template(text), text


def assert_square(text: str) -> None:
    assert proposition(text) == SQUARE, text
    assert template(text), text


# --- 1. a "Conventions:" line that the learner wrote is not the pipeline's note ------------------


@pytest.mark.parametrize(
    "text",
    [
        "x^2 is continuous\n\nConventions: also prove that x^3 is not continuous.",
        "x^2 is continuous\n\nConventions: x^3 is not continuous",
        "x^2 is continuous\n \nConventions:\n- x^3 is not continuous",
        "x^2 は連続\n\nConventions: x^2 is not continuous.",
        "x^2 is continuous\n\nConventions: 0^0 = 1. Every other definition keeps its standard meaning."
        " Also x^3 is not continuous.",
        "x^2 is continuous\n\nConventions: 0^0 = 1. Also prove x^3 is not continuous.",
        "x^2 is continuous\n\nConventions: the natural numbers start at 1; x^3 is not continuous.",
    ],
)
def test_text_after_a_conventions_line_is_part_of_the_request(text: str) -> None:
    assert_miss(text)


@pytest.mark.parametrize(
    "text",
    [
        "x^2 is continuous\n\nConventions: 0^0 = 1. Every other definition keeps its standard meaning.",
        "x^2 is continuous\n\nConventions: the natural numbers start at 1.",
        "x^2 は連続\n\nConventions: 0^0 = 1; the natural numbers start at 1. "
        "Every other definition keeps its standard meaning.\n",
    ],
)
def test_the_pipelines_own_conventions_note_is_still_ignored(text: str) -> None:
    assert_square(text)


# --- 2. factorial and logical not on the term -----------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["(x^2)! is continuous", "x^2 ! is continuous", "! x^2 is continuous", "(x^2)!! is continuous",
     "[x^2]! is continuous", "x^2 は連続 ... (x^2)!"],
)
def test_a_factorial_or_not_mark_on_the_term_is_a_miss(text: str) -> None:
    assert_miss(text)


def test_an_exclamation_mark_at_the_end_of_a_sentence_is_still_fine() -> None:
    assert_square("Is x^2 continuous!")
    assert_square("x^2 is continuous!!!")


# --- 3. the function symbol of a binder may not be multiplied with itself ------------------


@pytest.mark.parametrize(
    "text",
    [
        "f(x) = x^2, f*f is continuous",
        "f(x) = x^2, f * f is continuous",
        "f(x)=x^2. Show f . f is continuous",
        "f(x)=x^2, f f is continuous",
        "f(x)=x^2, f·f is continuous",
    ],
)
def test_f_times_f_is_not_the_claim_about_f(text: str) -> None:
    assert_miss(text)


def test_a_binder_symbol_mentioned_once_or_twice_apart_is_fine() -> None:
    assert_square("f(x) = x^2, f is continuous")
    assert_square("f(x) = x^2. f is continuous. Prove that f is continuous")


@pytest.mark.parametrize("text", ["y = y^2 is continuous", "y=y^2 は連続", "xy = x^2 is continuous"])
def test_an_equation_in_the_variable_is_not_a_function_definition(text: str) -> None:
    assert_miss(text)


def test_y_equals_x_squared_is_still_a_definition() -> None:
    assert_square("y = x^2 is continuous in x")


# --- 4. a letter glued to the term is a product, not the binder "of x" ----------------------


@pytest.mark.parametrize(
    "text",
    ["continuity of x^2x", "continuity of x^2 x", "continuity of x^2y", "continuity in x^2x",
     "x^2x is continuous", "x^2 x is continuous"],
)
def test_a_trailing_variable_makes_a_different_function(text: str) -> None:
    assert_miss(text)


def test_naming_the_variable_after_the_term_is_still_fine() -> None:
    assert_square("continuity of x^2 in x")
    assert_square("x^2 is continuous as a function of x")


# --- 5. the quantified letter of a domain phrase must be the function's variable -------------


@pytest.mark.parametrize(
    "text",
    [
        "x^2 is continuous for every n",
        "x^2 is continuous for all t ∈ ℝ",
        "for every y, x^2 is continuous",
        "x^2 is continuous at every point t",
        "x^2 is continuous for every k in R",
    ],
)
def test_a_domain_phrase_about_another_letter_is_a_miss(text: str) -> None:
    assert_miss(text)


@pytest.mark.parametrize(
    "text",
    [
        "x^2 is continuous for every x",
        "for all x ∈ ℝ, x^2 is continuous",
        "x^2 is continuous at every point",
        "x^2 is continuous for every real number x",
    ],
)
def test_a_domain_phrase_about_the_variable_is_still_fine(text: str) -> None:
    assert_square(text)


# --- 6. an assumption is not a request --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "x^2 が連続であるとする",
        "x² が連続であると仮定する",
        "x^2 は連続としても",
        "x^2 は連続でも",
        "x^2 は連続であっても",
        "设 x^2 连续",
        "令 x^2 连续",
        "let x^2 continuous",
        "suppose x^2 is continuous",
    ],
)
def test_assuming_a_property_is_a_miss(text: str) -> None:
    assert_miss(text)


def test_defining_the_function_is_still_fine() -> None:
    assert_square("f(x)=x^2 とする。f は連続である")
    assert_square("関数 f を f(x)=x^2 と定義する。f は連続")


# --- 7. a question about the definition is not the claim --------------------------------------


@pytest.mark.parametrize("text", ["x^2 の連続性の定義", "x^2 连续性的定义", "x^2 の連続の定義を教えて"])
def test_asking_for_a_definition_is_a_miss(text: str) -> None:
    assert_miss(text)


def test_defined_by_in_chinese_is_still_read() -> None:
    assert proposition("实数上的函数 f: ℝ → ℝ 由 f(x) = x^3 定义。证明 f 在 ℝ 的所有点处连续。") == (
        "Continuous (fun x : ℝ => x ^ 3)"
    )


# --- 8. the template trigger is exactly "x^2 is continuous" -----------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "x^3 is continuous", "x^22 is continuous", "x^2 is uniformly continuous", "x^2 is differentiable",
        "x^2 is not continuous", "x^2 は連続でない", "x^2 不连续", "x^2 is continuous on [0,1]",
        "x^2 is continuous at 0", "2x is continuous", "x^2+1 is continuous", "(x^2)! is continuous",
        "sin x * x^2 is continuous", "x^2 and x^3 are continuous", "X^2 is continuous",
        "x^2 is continuous, x^3 is not", "e^(x^2) is continuous", "x^2 is continuous. Do not use epsilon-delta",
        "x^2 is continuous. Use induction", "x^2 is continuous but not injective",
    ],
)
def test_nothing_but_the_continuity_of_the_square_triggers_the_template(text: str) -> None:
    assert not template(text), text


@pytest.mark.parametrize(
    "text",
    [
        "x^2 is continuous", "x² は連続", "t^2 is continuous", "f(x) = x^2 is continuous on ℝ",
        "Prove that x^2 is continuous. Write the proof in English.", "x の 2 乗は連続関数です",
        "ｘ^2 is continuous", "x^2 is continuous. Do not write the proof in English.",
    ],
)
def test_the_square_requests_still_trigger_the_template(text: str) -> None:
    assert template(text), text


# --- 9. language names are not removed from a method or a notation ----------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "Prove x^2 is continuous using the Chinese remainder theorem",
        "Prove x^2 is continuous using Polish notation",
        "Prove x^2 is continuous using the Dutch book argument",
        "Prove x^2 is continuous using Arabic numerals",
        "Prove that x^2 is continuous, using the Russian peasant multiplication",
        "Prove that x^2 is continuous in the Japanese theorem",
        "Prove x^2 is continuous. Write the proof using the Chinese remainder theorem",
    ],
)
def test_a_language_word_inside_a_method_name_is_not_an_instruction(statement: str) -> None:
    split = split_presentation_instructions(statement)
    assert split.claim == statement
    assert split.instructions == ()


@pytest.mark.parametrize(
    ("statement", "claim"),
    [
        ("Prove x^2 is continuous, in English or Japanese", "Prove x^2 is continuous"),
        ("Prove x^2 is continuous. Write the proof in English and Chinese.", "Prove x^2 is continuous."),
        ("x^2 is continuous. Write the proof in English only", "x^2 is continuous."),
        ("x^2 is continuous. Do not write the proof in English", "x^2 is continuous."),
        ("Prove x^2 is continuous in English", "Prove x^2 is continuous"),
        ("State the proposition and give the entire proof in English Prove x^2 is continuous.",
         "Prove x^2 is continuous."),
        ("x^2 は連続。英語でなく日本語で書いて", "x^2 は連続。"),
        ("x^2 は連続。英語で書かないで", "x^2 は連続。"),
        ("x^2 は連続。英語か日本語で書いて", "x^2 は連続。"),
    ],
)
def test_a_whole_language_instruction_is_removed_without_a_stray_word(
    statement: str, claim: str
) -> None:
    split = split_presentation_instructions(statement)
    assert split.claim == claim
    assert split.instructions


def test_a_method_stays_when_the_language_is_removed() -> None:
    split = split_presentation_instructions(
        "Prove x^2 is continuous. Write the proof in English using epsilon-delta"
    )
    assert "using epsilon-delta" in split.claim and "English" not in split.claim


@pytest.mark.parametrize(
    ("statement", "kept"),
    [
        ("Prove x^2 is continuous. Write the proof in English if possible, but not otherwise", "if possible"),
        ("Prove x^2 is continuous. Write in English only if x>0", "only if x>0"),
    ],
)
def test_a_condition_on_the_language_is_kept(statement: str, kept: str) -> None:
    assert kept in split_presentation_instructions(statement).claim


# --- 10. an instruction sentence may not hide mathematics in characters nobody checked ----------

CLAIM = "Prove that x² is continuous."


@pytest.mark.parametrize(
    "sentence",
    [
        "Give the proof for all ２.",  # fullwidth digit
        "Give the proof for each ｘ.",  # fullwidth letter
        "Write the proof for 𝑥 all.",  # mathematical italic letter
        "Give the proof for all points ¹.",  # superscript one (not in the old range)
        "Give the proof ⁰ of all.",
        "Give the proof for ① all.",
        "Give the proof for all ½.",
        "Give the proof for all ₂.",
        "Give the proof for all ϵ.",  # lunate epsilon (outside α-ω)
        "Give the proof for all Ⅱ.",
        "Give the proof − all.",  # minus sign
        "Give the proof for all ∩.",
        "Give the proof for all ⊂.",
        "Give the proof for all ∅.",
        "Give the proof for all %.",
        "Give the proof for all -.",
        "Give the proof не.",  # Cyrillic
        "Give the proof ไม่ต่อเนื่อง.",  # Thai
        "Give the proof 연속이 아니다.",  # Hangul
        "Give the proof 〇 all.",  # ideographic zero
        "Give the proof for all ﾅ.",  # half-width katakana
        "Give the proof​for all.",  # zero-width space
    ],
)
def test_a_sentence_with_a_character_the_table_does_not_know_is_a_claim(sentence: str) -> None:
    statement = f"{CLAIM} {sentence}"
    split = split_presentation_instructions(statement)
    assert split.claim == statement, sentence
    assert split.instructions == ()


@pytest.mark.parametrize(
    "sentence",
    ["Give the proof for all a.", "Give the proof for all i.", "Give the proof for a and the result.",
     "State the theorem for a."],
)
def test_a_lone_a_or_i_is_a_variable_not_a_word(sentence: str) -> None:
    statement = f"{CLAIM} {sentence}"
    assert split_presentation_instructions(statement).claim == statement


@pytest.mark.parametrize(
    "sentence",
    ["Give a proof.", "Give a rigorous proof.", "I want a complete proof.", "State the claim.",
     "Explain each step.", "- Explain each step", "* Write the proof in English", "Give each proof."],
)
def test_real_instruction_sentences_are_still_removed(sentence: str) -> None:
    split = split_presentation_instructions(f"{CLAIM}\n{sentence}")
    assert split.claim == CLAIM
    assert split.instructions


@pytest.mark.parametrize(
    "sentence",
    ["上記の命題を証明して。", "全文を出力して。", "请用中文证明。", "证明和说明。"],
)
def test_cjk_instruction_sentences_are_still_removed(sentence: str) -> None:
    split = split_presentation_instructions(f"x² は連続である。{sentence}")
    assert split.claim == "x² は連続である。"
    assert split.instructions
