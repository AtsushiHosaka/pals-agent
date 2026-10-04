"""Advisory hints use the production assessor and its existing answer QA gate."""

import hashlib
import json

import pytest

from pals_agent.proof_reuse import DECISION_SCHEMA
from tests.unit.test_proof_reuse import READY, REQUEST, decision, runtime
from tests.unit.test_token_proof_request import run as run_metered


@pytest.mark.parametrize(
    ("language", "hint"),
    [
        ("en", "How does the argument extend to higher powers?"),
        ("ja", "この議論は高い次数のべき乗でも使えますか？"),
        ("zh-Hans", "这个论证也适用于更高次幂吗？"),
        ("zh-Hant", "這個論證也適用於更高次冪嗎？"),
    ],
)
def test_existing_assessor_generates_hint_in_requested_language_after_answer_qa(language, hint):
    turns = [{"question_id": "domain", "question": "Which domain?", "answer": "The reals."}]
    request = dict(REQUEST, output_language=language, context_turns=turns)
    engine, transport = runtime([READY, decision(next_input_suggestion=hint)])

    result = engine.answer(request)

    assert result.outcome == "answered"
    assert result.answer["next_input_suggestion"] == hint
    assert result.answer["text"] == decision()["answer"]
    assert result.answer["sources"][0]["draft_id"] == "power"
    assert result.private_evidence["answer_qa"]["approved"] is True
    assert result.private_evidence["answer_qa"]["answer_sha256"] == hashlib.sha256(
        result.answer["text"].encode()
    ).hexdigest()
    assert len(transport.calls) == 3
    assert [call["model"] for call in transport.calls] == ["gpt-6-luna"] * 3
    assert all(call["service_tier"] == "default" for call in transport.calls)
    assert all(call["reasoning"] == {"effort": "low"} for call in transport.calls)
    generated = transport.calls[1]
    schema = generated["text"]["format"]["schema"]
    assert schema["properties"]["next_input_suggestion"] == {"type": ["string", "null"]}
    assert "next_input_suggestion" in schema["required"]
    assert DECISION_SCHEMA["properties"]["next_input_suggestion"] == {"type": ["string", "null"]}
    prompt = generated["input"]
    assert "the exact original request" in prompt
    assert "explicit clarification answers" in prompt
    assert "the answer you just wrote" in prompt
    assert "learner's perspective in request.output_language" in prompt
    assert "one line of at most 160 characters" in prompt
    assert "with no label or Markdown" in prompt
    assert "Use null when there is no useful next question" in prompt
    assert json.loads(prompt.split("DATA:\n", 1)[1])["request"] == {
        "original_statement": request["statement"], "output_language": language,
        "clarifications": turns,
    }
    qa_data = json.loads(transport.calls[2]["input"].split("DATA:\n", 1)[1])
    assert qa_data["answer"] == decision()["answer"]
    assert "next_input_suggestion" not in qa_data
    qa_schema = transport.calls[2]["text"]["format"]["schema"]
    assert "next_input_suggestion" not in qa_schema["properties"]


@pytest.mark.parametrize(
    "hint",
    [
        None, "", "   ", 123, False, [], {"text": "A question?"},
        "A" * 161, "First line\nSecond line", "First\rSecond",
        "First\u2028Second", "First\u2029Second", "A\x00B", "A\ud800B", "A\udfffB",
        "\tQuestion?", "Question?\t", "A\tB",
        {"invalid": "\x00\ud800"}, "```lean theorem example : True := by trivial```",
    ],
)
def test_invalid_advisory_hint_never_rejects_a_valid_answer_or_escapes_into_evidence(hint):
    engine, transport = runtime([READY, decision(next_input_suggestion=hint)])

    result = engine.answer(REQUEST)

    assert result.outcome == "answered"
    assert "next_input_suggestion" not in result.answer
    assert result.answer["text"] == decision()["answer"]
    assert result.private_evidence["primary_assessment"]["next_input_suggestion"] is None
    assert len(transport.calls) == 3


def test_missing_advisory_is_backward_compatible_and_does_not_weaken_closed_math_schema():
    engine, transport = runtime([READY, decision()])
    result = engine.answer(REQUEST)
    assert result.outcome == "answered"
    assert "next_input_suggestion" not in result.answer
    assert len(transport.calls) == 3

    malformed = decision(next_input_suggestion="Could you give an example?")
    del malformed["conclusion"]
    engine, transport = runtime([READY, malformed])
    assert engine.answer(REQUEST).error_code == "proof_reuse_invalid_response"
    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    "review",
    [{"approved": False, "rationale": "Proof is mathematically incomplete."}, 500],
)
def test_suggestion_is_never_published_if_existing_independent_answer_qa_fails(review):
    engine, transport = runtime([
        READY, decision(next_input_suggestion="Could you give a related example?"), review,
    ])
    result = engine.answer(REQUEST)
    assert result.outcome == "failed"
    assert result.answer is None
    assert len(transport.calls) == 3


def test_uncertainty_escalation_publishes_only_its_final_approved_hint_without_an_extra_call():
    engine, transport = runtime([
        READY,
        decision(action="uncertain", next_input_suggestion="UNAPPROVED PRELIMINARY HINT"),
        decision(next_input_suggestion="Could you explain the induction step?"),
    ])
    result = engine.answer(REQUEST)
    assert result.outcome == "answered"
    assert result.answer["next_input_suggestion"] == "Could you explain the induction step?"
    assert result.private_evidence["primary_assessment"]["next_input_suggestion"] is None
    assert len(transport.calls) == 4
    assert [call["model"] for call in transport.calls] == [
        "gpt-6-luna", "gpt-6-luna", "gpt-5.6-terra", "gpt-6-luna",
    ]


def test_hint_never_turns_a_followup_question_into_a_published_answer():
    engine, transport = runtime([
        READY, decision(action="needs_input", question={"text": "Which domain?", "options": []},
                        next_input_suggestion="Invent an answer anyway?"),
    ])
    result = engine.answer(REQUEST)
    assert result.outcome == "needs_input"
    assert result.answer is None
    assert result.private_evidence["primary_assessment"]["next_input_suggestion"] is None
    assert len(transport.calls) == 2


def test_hint_length_counts_unicode_codepoints_and_trims_only_outer_whitespace():
    hint = "🧮" * 159 + "？"
    engine, _ = runtime([READY, decision(next_input_suggestion=f"  {hint}  ")])
    assert engine.answer(REQUEST).answer["next_input_suggestion"] == hint
    engine, _ = runtime([READY, decision(next_input_suggestion=hint + "？")])
    assert "next_input_suggestion" not in engine.answer(REQUEST).answer


@pytest.mark.parametrize("hint", ["この証明を別の方法でも示せますか？", "invalid\x00hint"])
def test_hint_keeps_existing_metered_calls_usage_receipts_and_answer_qa_binding(hint):
    processed, api, provider, events = run_metered([
        READY, decision(next_input_suggestion=hint),
        {"approved": True, "rationale": "Complete mathematical proof."},
    ])
    assert processed
    settlement = api.settlements[0]
    assert settlement["outcome"] == "answered"
    assert settlement["answer"].get("next_input_suggestion") == (
        hint if "\x00" not in hint else None
    )
    assert events == ["count", "permit", "generate", "receipt"] * 3
    assert len(provider.calls) == len(api.receipts) == len(settlement["usage"]) == 3
    assert [call["max_output_tokens"] for call in provider.calls] == [6000, 6000, 12000]
    assert [permit["output_token_bound"] for permit in api.permits] == [6000, 6000, 12000]
    assert api.permits[-1]["model_role"] == "token_answer_qa"
    assert settlement["private_evidence"]["token_qa"] == {
        "approved": True,
        "answer_sha256": hashlib.sha256(settlement["answer"]["text"].encode()).hexdigest(),
        "call_id": api.receipts[-1]["call_id"],
    }


@pytest.mark.parametrize("hint", [
    "x<0 の場合は？", "f: R→R の仮定は必要ですか？", "[0,1] でも成立しますか？",
])
def test_plain_mathematical_punctuation_is_preserved_in_advisory(hint):
    engine, _ = runtime([READY, decision(next_input_suggestion=hint)])
    assert engine.answer(REQUEST).answer["next_input_suggestion"] == hint


def test_oversized_raw_provider_envelope_still_fails_before_optional_hint_validation():
    engine, transport = runtime([READY, decision(next_input_suggestion="A" * 70000)])
    result = engine.answer(REQUEST)
    assert result.outcome == "failed"
    assert result.answer is None
    assert result.error_code == "proof_reuse_invalid_response"
    assert len(transport.calls) == 2


@pytest.mark.parametrize("invalid_answer", ["proof\x00text", "proof\ud800text", "proof\udffftext"])
def test_optional_hint_does_not_weaken_invalid_main_proof_storage_text_guard(invalid_answer):
    engine, transport = runtime([READY, decision(
        answer=invalid_answer, next_input_suggestion="Another question?",
    )])
    result = engine.answer(REQUEST)
    assert result.outcome == "failed"
    assert result.answer is None
    assert result.error_code == "proof_reuse_invalid_response"
    assert len(transport.calls) == 2
