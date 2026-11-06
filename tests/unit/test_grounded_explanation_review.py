"""Quote-grounded rejection of explanations: only a verbatim-quoted error defect can reject.

An approved=false answer that quotes no real defect (or contradicts itself) is re-checked once
and, if still ungrounded, overridden. Transport and schema failures stay fail-closed. Stub
models only.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from pals_agent.explanations import (
    ExplanationSection,
    LeanGroundedOutputReviewer,
    LeanLineReference,
    ProofClarification,
    ProofExplanation,
    ProofOutputReview,
    ProofOutputReviewError,
    _ground_defects,
    _normalize_quote_text,
    _output_review_prompt,
)
from pals_agent.worker import _note_ungrounded_override

LEAN = "theorem t : Continuous (fun x : ℝ => x ^ 2) := by\n  continuity"
STATEMENT = "x² が連続であることを説明してください。"
OVERVIEW = "$\\varepsilon>0$ を任意に取り、実数 $a$ を固定します。"
SUMMARY = (
    "$\\delta=\\min\\left(1,\\dfrac{\\varepsilon}{2|a|+1}\\right)$ とおきます。\n"
    "$|x-a|<\\delta$ のとき $|x^2-a^2|<\\delta(2|a|+1)\\le\\varepsilon$ です。"
)
CONCLUSION = "$a$ は任意なので、$x^2$ は連続です。"


def _explanation() -> ProofExplanation:
    ref = LeanLineReference(2, 2, "  continuity")
    return ProofExplanation(
        overview=OVERVIEW,
        sections=(ExplanationSection("s", "t", SUMMARY, (ref,)),),
        conclusion=CONCLUSION,
        model="m",
        provider="p",
        prompt="",
        raw_model_output="",
        elapsed_ms=0,
    )


class Client:
    def __init__(self, *answers: str | Exception) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def generate(self, *, model: str, prompt: str, timeout_seconds: float | None = None) -> str:
        _ = (model, timeout_seconds)
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _answer(approved: bool, defects: list[dict[str, str]] | None = None, why: str = "r") -> str:
    payload: dict[str, Any] = {"approved": approved, "rationale": why}
    if defects is not None:
        payload["defects"] = defects
    return json.dumps(payload, ensure_ascii=False)


def _error(quote: str, reason: str = "bad step") -> dict[str, str]:
    return {"severity": "error", "quote": quote, "reason": reason}


def _nit(quote: str) -> dict[str, str]:
    return {"severity": "nit", "quote": quote, "reason": "style"}


def _review(client: Client, *, attempts: int = 2) -> ProofOutputReview:
    reviewer = LeanGroundedOutputReviewer(
        client=client, model="m", provider="p", max_attempts=attempts
    )
    return reviewer.review_explanation(
        theorem_statement=STATEMENT, lean_code=LEAN, explanation=_explanation(), language="ja"
    )


# --- quote grounding ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "quote",
    [
        r"\delta(2|a|+1)\le\varepsilon",  # plain
        "$|x-a|<\\delta$ のとき\n$|x^2-a^2|$",  # delimiters and a newline
        "|x-a| < \\delta  のとき",  # extra spaces
        "｜x-a｜＜\\delta",  # full-width forms are folded by NFKC
        r"\frac{\varepsilon}{2|a|+1}",  # \dfrac in the proof, \frac in the quote
        r"\left(1,\dfrac{\varepsilon}{2|a|+1}\right)",  # \left and \right
        r"|x\,^2-a^2|",  # TeX spacing is ignored
    ],
)
def test_quote_in_the_visible_proof_is_grounded_despite_surface_differences(quote: str) -> None:
    visible = _normalize_quote_text("\x00".join([OVERVIEW, SUMMARY, CONCLUSION]))
    (defect,) = _ground_defects((("error", quote, "r"),), visible)
    assert defect.grounded, quote


@pytest.mark.parametrize(
    "quote",
    [
        "この文は説明にありません",  # hallucinated
        "\\delta=\\min(1,\\varepsilon)",  # plausible but different
        "a|x",  # too short after normalization? (4 chars) and not present
        "x",  # below the minimum length
        "実数 $a$ を固定します。$\\delta",  # spans two fields
        "",
    ],
)
def test_quote_not_in_the_visible_proof_or_too_short_is_not_grounded(quote: str) -> None:
    visible = _normalize_quote_text("\x00".join([OVERVIEW, SUMMARY, CONCLUSION]))
    (defect,) = _ground_defects((("error", quote, "r"),), visible)
    assert not defect.grounded, quote


# --- decision procedure ------------------------------------------------------------------


def test_grounded_error_rejects_and_carries_the_defect_reason_not_the_quote() -> None:
    client = Client(_answer(False, [_error("|x-a|<\\delta", "delta is wrong")], "no"))
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert raised.value.category == "rejected"
    assert "delta is wrong" in raised.value.rationale
    assert "|x-a|<" not in raised.value.rationale
    assert len(client.prompts) == 1
    assert raised.value.defects[0].grounded


def test_approved_true_with_a_grounded_error_is_rejected_safe_side() -> None:
    client = Client(_answer(True, [_error("|x-a|<\\delta")], "fine"))
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert raised.value.category == "rejected"
    assert len(client.prompts) == 1


def test_approved_true_with_nits_or_ungrounded_errors_is_approved_without_recheck() -> None:
    client = Client(
        _answer(True, [_nit("|x-a|<\\delta"), _error("invented sentence here")], "fine")
    )
    review = _review(client)
    assert review.ungrounded_rejection_overridden is False
    assert len(client.prompts) == 1
    assert [d.grounded for d in review.defects] == [True, False]


def test_missing_defects_key_is_accepted_for_compatibility() -> None:
    review = _review(Client(_answer(True)))
    assert review.defects == ()
    assert review.ungrounded_rejection_overridden is False


@pytest.mark.parametrize(
    "first",
    [
        _answer(False, [], "The proof is valid ... but not approved"),  # self-contradiction
        _answer(False, None, "vague"),  # no defects key
        _answer(False, [_nit("|x-a|<\\delta")], "style only"),
        _answer(False, [_error("hallucinated quote not in proof")], "invented"),
    ],
)
def test_rejection_without_a_real_quoted_error_is_rechecked_once_then_overridden(
    first: str,
) -> None:
    client = Client(first, _answer(False, [], "still unsure"))
    review = _review(client)
    assert review.ungrounded_rejection_overridden is True
    assert len(client.prompts) == 2
    assert "listed no error defect with a verbatim quote" in client.prompts[1]
    assert client.prompts[1].startswith(client.prompts[0])
    assert "approved" not in client.answers  # both answers consumed
    assert not client.answers


def test_recheck_that_approves_also_counts_as_an_overridden_rejection() -> None:
    client = Client(_answer(False, [], "vague"), _answer(True, [], "valid"))
    review = _review(client)
    assert review.ungrounded_rejection_overridden is True
    assert review.rationale == "valid"


def test_recheck_with_a_grounded_error_rejects() -> None:
    client = Client(
        _answer(False, [], "vague"),
        _answer(False, [_error("\\delta(2|a|+1)\\le\\varepsilon", "unjustified")], "found"),
    )
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert raised.value.category == "rejected"
    assert "unjustified" in raised.value.rationale
    assert len(client.prompts) == 2


def test_recheck_with_only_a_hallucinated_error_is_still_overridden() -> None:
    client = Client(_answer(False, [], "vague"), _answer(False, [_error("made up text!")], "x"))
    assert _review(client).ungrounded_rejection_overridden is True


# --- fail-closed behaviour is unchanged --------------------------------------------------


def test_transport_failure_is_never_an_approval_even_on_the_recheck() -> None:
    with pytest.raises(ProofOutputReviewError) as first:
        _review(Client(RuntimeError("down")))
    assert first.value.category == "transport"
    with pytest.raises(ProofOutputReviewError) as second:
        _review(Client(_answer(False, [], "vague"), RuntimeError("down")))
    assert second.value.category == "transport"


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        '{"approved": "yes", "rationale": "x"}',
        '{"approved": true, "rationale": "x", "defects": "none"}',
        '{"approved": true, "rationale": "x", "defects": [{"severity": "fatal", "quote": "q", '
        '"reason": "r"}]}',
        '{"approved": true, "rationale": "x", "defects": [{"severity": "error", "quote": "q"}]}',
        '{"approved": true, "rationale": "x", "extra": 1}',
        '{"approved": true}',
    ],
)
def test_malformed_output_stays_a_schema_failure_never_an_approval(bad: str) -> None:
    client = Client(bad, bad)
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert raised.value.category == "schema"
    assert len(client.prompts) == 2


def test_malformed_recheck_is_a_schema_failure_not_an_override() -> None:
    client = Client(_answer(False, [], "vague"), "not json", "not json")
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client, attempts=2)
    assert raised.value.category == "schema"


def test_a_malformed_first_answer_can_still_be_retried_into_a_valid_decision() -> None:
    review = _review(Client("not json", _answer(True, [])))
    assert review.ungrounded_rejection_overridden is False


# --- prompts and other reviews are unchanged ---------------------------------------------


def test_explanation_prompt_requires_quotes_and_clarification_prompt_is_unchanged() -> None:
    explanation_prompt = _output_review_prompt(
        theorem_statement=STATEMENT, lean_code=LEAN, explanation=_explanation(), language="ja"
    )
    assert "DEFECT REPORTING" in explanation_prompt
    assert "copied verbatim" in " ".join(explanation_prompt.split())
    assert '"defects": []' in explanation_prompt
    assert "quote the sentence just before" in " ".join(explanation_prompt.split())
    clarification = ProofClarification(
        section_id="s",
        question="q",
        answer="a",
        key_points=("k",),
        references=(LeanLineReference(2, 2, "  continuity"),),
        model="m",
        provider="p",
        prompt="",
        raw_model_output="",
        elapsed_ms=0,
    )
    clarification_prompt = _output_review_prompt(
        theorem_statement=STATEMENT,
        lean_code=LEAN,
        explanation=_explanation(),
        clarification=clarification,
        language="ja",
    )
    assert "DEFECT REPORTING" not in clarification_prompt
    assert '{"approved": false, "rationale": "a concise review reason"}' in clarification_prompt


def test_clarification_review_still_rejects_on_approved_false_alone() -> None:
    reviewer = LeanGroundedOutputReviewer(
        client=Client(_answer(False, None, "no reason quoted"), _answer(True)),
        model="m",
        provider="p",
    )
    clarification = ProofClarification(
        section_id="s",
        question="q",
        answer="a",
        key_points=("k",),
        references=(LeanLineReference(2, 2, "  continuity"),),
        model="m",
        provider="p",
        prompt="",
        raw_model_output="",
        elapsed_ms=0,
    )
    with pytest.raises(ProofOutputReviewError) as raised:
        reviewer.review_clarification(
            theorem_statement=STATEMENT,
            lean_code=LEAN,
            explanation=_explanation(),
            clarification=clarification,
            language="ja",
        )
    assert raised.value.category == "rejected"
    assert raised.value.rationale == "no reason quoted"
    assert len(reviewer.client.prompts) == 1  # type: ignore[attr-defined]


# --- recording ---------------------------------------------------------------------------


def test_override_is_logged_without_any_proof_text_or_quote(
    caplog: pytest.LogCaptureFixture,
) -> None:
    review = ProofOutputReview(
        "explanation",
        "p",
        "m",
        "s",
        "valid",
        defects=(_ground_defects((("error", "secret quoted proof text", "secret reason"),), "")),
        ungrounded_rejection_overridden=True,
    )
    with caplog.at_level(logging.WARNING):
        _note_ungrounded_override("explanation", "job-1", review)
    assert "ungrounded_rejection_overridden=true" in caplog.text
    assert "job-1" in caplog.text
    assert "secret" not in caplog.text

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        _note_ungrounded_override(
            "explanation", "job-1", ProofOutputReview("explanation", "p", "m", "s", "ok")
        )
    assert caplog.text == ""
