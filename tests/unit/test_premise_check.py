"""Ask before proving when a request looks false or its truth depends on a choice (PFR-014)."""

import pytest

from pals_agent.proof_reuse import PREFLIGHT_SCHEMA
from tests.unit.test_proof_reuse import READY, REQUEST, decision, runtime

ODD = {"statement": "Prove that for every natural number n, n^2 + n is odd.",
       "output_language": "en", "context_turns": []}


def checked(**check):
    return dict(READY, premise_check=dict(READY["premise_check"], **check))


def test_schema_and_prompt_require_the_premise_check():
    check = PREFLIGHT_SCHEMA["properties"]["premise_check"]
    assert check["required"] == [
        "counterexample", "truth_depends_on", "assumed_defaults", "conventions"
    ]
    engine, transport = runtime([READY, decision()])
    engine.answer(REQUEST)
    prompt = transport.calls[0]["input"]
    assert "concrete admissible instance makes the claim false" in prompt
    assert "keep and prove the statement as written" in prompt
    assert "do not ask about it again" in prompt
    assert "use the most general reading" in prompt
    assert "must itself pass the same counterexample check" in prompt
    assert "Standard textbook definitions and conventions" in prompt
    assert "never replace it by its negation, a refutation, a weaker claim" in prompt
    assert "once its known_reading is given, a counterexample under that reading" in prompt


def test_model_question_about_a_suspected_counterexample_is_asked_first():
    question = {"text": "As stated, this seems to fail for n = 0. Which claim do you mean?",
                "options": ["n^2 + n is even for every natural n", "Prove it as written"]}
    asked = dict(checked(counterexample="n = 0 gives 0, which is even"),
                 action="needs_input", statement="", question=question)
    engine, transport = runtime([asked])
    result = engine.answer(ODD)
    assert result.outcome == "needs_input" and result.formal_plan is None
    assert result.question["options"] == question["options"]
    check = result.private_evidence["preflight"]["premise_check"]
    assert check["counterexample"].startswith("n = 0")
    # No retrieval, decision or Lean happens before the learner answers.
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    ("language", "phrase", "option"),
    [
        ("en", "may fail in this case: n = 0", "Prove the statement as written"),
        ("ja", "成り立たない可能性があります：n = 0", "このまま証明を試す"),
        ("zh-Hans", "可能不成立：n = 0", "按原样尝试证明"),
        ("zh-Hant", "可能不成立：n = 0", "照原樣嘗試證明"),
    ],
)
def test_reported_counterexample_without_a_question_still_asks(language, phrase, option):
    engine, transport = runtime([checked(counterexample="n = 0")])
    result = engine.answer(dict(ODD, output_language=language))
    assert result.outcome == "needs_input"
    assert phrase in result.question["text"] and result.question["options"] == [option]
    assert result.private_evidence["premise_check_fallback"] is True
    assert len(transport.calls) == 1


def test_longest_fallback_questions_fit_the_api_question_text():
    for check in ({"counterexample": "x" * 1000}, {"truth_depends_on": ["x" * 300] * 4}):
        for language in ("en", "ja", "zh-Hans", "zh-Hant"):
            engine, _ = runtime([checked(**check)])
            result = engine.answer(dict(ODD, output_language=language))
            assert len(result.question["text"]) <= 2000


def test_unresolved_truth_dependent_choice_still_asks():
    engine, _ = runtime([checked(truth_depends_on=["the scalar field (ℝ or ℂ)"])])
    result = engine.answer(ODD)
    assert result.outcome == "needs_input"
    assert "depends on: the scalar field (ℝ or ℂ)" in result.question["text"]
    assert result.question["options"] == []


def test_answered_clarification_is_not_asked_again():
    turns = [{"question_id": "q1", "question": "This seems to fail for n = 0. Which claim?",
              "answer": "Prove the statement as written"}]
    engine, transport = runtime([checked(counterexample="n = 0"), decision()])
    result = engine.answer(dict(ODD, context_turns=turns))
    assert result.outcome == "answered"
    assert "premise_check_fallback" not in result.private_evidence


def test_conventional_defaults_never_cause_a_question():
    engine, _ = runtime([checked(assumed_defaults=["x ranges over the real numbers"]), decision()])
    assert engine.answer(REQUEST).outcome == "answered"


VALID = {"counterexample": "", "truth_depends_on": [], "assumed_defaults": [], "conventions": []}


@pytest.mark.parametrize(
    "check",
    [
        None,
        {"counterexample": "", "truth_depends_on": []},
        dict(VALID, counterexample=1),
        dict(VALID, truth_depends_on="field"),
        dict(VALID, truth_depends_on=[""]),
        dict(VALID, truth_depends_on=["x"] * 5),
        dict(VALID, truth_depends_on=["x" * 301]),
        dict(VALID, assumed_defaults=["x"] * 9),
        dict(VALID, counterexample="x" * 1001),
        dict(VALID, assumed_defaults=["y" * 501]),
        dict(VALID, conventions=["not_a_convention"]),
        dict(VALID, conventions=["natural_zero", "natural_zero"]),
    ],
)
def test_malformed_premise_check_is_rejected(check):
    engine, _ = runtime([dict(READY, premise_check=check)])
    result = engine.answer(REQUEST)
    assert (result.outcome, result.error_code) == ("failed", "proof_reuse_invalid_response")


def test_a_claim_kept_as_written_with_a_counterexample_is_refuted_with_lean():
    turns = [{"question_id": "q1", "question": "This seems to fail for n = 0. Which claim?",
              "answer": "Prove the statement as written"}]
    kept = checked(counterexample="n = 0 gives 0, which is even")
    engine, transport = runtime([dict(kept, statement=ODD["statement"])])
    result = engine.answer(dict(ODD, context_turns=turns), lambda sources: [])
    assert result.outcome == "formal" and result.private_evidence["lean_route"] == "refute"
    plan = result.formal_plan
    assert plan["kind"] == "refute" and plan["claim"] == ODD["statement"]
    assert plan["counterexample"] == "n = 0 gives 0, which is even"
    assert plan["statement"].startswith("Show that the following claim is false")
    assert ODD["statement"] in plan["statement"]
    assert len(transport.calls) == 1  # no retrieval or decision for a refutation


def test_refutation_needs_the_lean_flow_and_a_clarification():
    engine, _ = runtime([checked(counterexample="n = 0")])
    first = engine.answer(dict(ODD, output_language="ja"), lambda sources: [])
    assert first.outcome == "needs_input"  # asked first (PFR-014)
    turns = [{"question_id": "q1", "question": "Which claim?", "answer": "As written"}]
    engine, _ = runtime([checked(counterexample="n = 0"), decision()])
    legacy = engine.answer(dict(ODD, context_turns=turns))
    assert legacy.outcome == "answered" and legacy.formal_plan is None


def test_refutation_statement_is_in_the_output_language_with_conventions():
    turns = [{"question_id": "q1", "question": "零環が反例のようです。",
              "answer": "このまま証明を試す"}]
    check = dict(READY["premise_check"], counterexample="零環", conventions=["zero_ring_domain"])
    engine, _ = runtime([dict(READY, premise_check=check, statement="有限整域は体である。")])
    result = engine.answer(
        {"statement": "有限整域は体であることを示せ。", "output_language": "ja",
         "context_turns": turns,
         "math_conventions": {"policy": "ask", "choices": {"zero_ring_domain": "include"}}},
        lambda sources: [],
    )
    plan = result.formal_plan
    assert plan["statement"].startswith("次の主張が偽であることを、その否定を証明して示せ。")
    assert "Conventions: the zero ring (where 1 = 0) counts as an integral domain." in plan["claim"]
    assert "反例の候補：零環" in plan["statement"]


def test_recipe_first_keeps_confirmed_refutation_before_search():
    turns = [{"question_id": "q1", "question": "Which claim?", "answer": "As written"}]
    kept = checked(counterexample="n = 0 gives 0, which is even")
    engine, transport = runtime([dict(kept, statement=ODD["statement"])])

    def no_search(query, language):
        raise AssertionError("A confirmed false claim must be refuted before Recipe search")

    result = engine.answer(dict(ODD, context_turns=turns), recipe_search=no_search)
    assert result.outcome == "formal"
    assert result.formal_plan["kind"] == "refute"
    assert result.formal_plan["claim"] == ODD["statement"]
    assert len(transport.calls) == 1
