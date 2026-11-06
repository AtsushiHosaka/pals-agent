"""Decision table of the x² epsilon-delta checklist review (stub models only).

The reviewer answers one entry per required element. The decision is computed in code:
reject iff an element is "missing", or "wrong" with a quote that really occurs in the proof.
The reviewer's own `approved` flag is ignored. Missing, repeated or unknown ids and bad
statuses are schema failures (fail-closed). Other reviews keep their original format.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from pals_agent.explanations import (
    EPSILON_DELTA_CHECK_IDS,
    ExplanationSection,
    LeanGroundedOutputReviewer,
    LeanLineReference,
    ProofClarification,
    ProofExplanation,
    ProofOutputReview,
    ProofOutputReviewError,
)
from pals_agent.worker import _note_review_flag_contradiction

LEAN = "theorem t : Continuous (fun x : ℝ => x ^ 2) := by\n  continuity"
STATEMENT = "x² が連続であることを説明してください。"
OVERVIEW = "$\\varepsilon>0$ を任意に取り、実数 $a$ を固定します。"
SUMMARY = (
    "$\\delta=\\min\\left(1,\\dfrac{\\varepsilon}{2|a|+1}\\right)$ とおきます。\n"
    "$|x-a|<\\delta$ のとき $|x^2-a^2|<\\delta(2|a|+1)\\le\\varepsilon$ です。"
)
CONCLUSION = "$a$ は任意なので、$x^2$ は連続です。"
QUOTE = "|x^2-a^2|<\\delta(2|a|+1)"  # really in SUMMARY
MATH_IDS = [i for i in EPSILON_DELTA_CHECK_IDS if i != "presentation"]


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


def _answer(
    fails: dict[str, tuple[str, str, str]] | None = None,
    *,
    drop: str | None = None,
    **top: Any,
) -> str:
    fails = fails or {}
    checks = []
    for check_id in EPSILON_DELTA_CHECK_IDS:
        if check_id == drop:
            continue
        status, quote, note = fails.get(check_id, ("ok", "", ""))
        checks.append({"id": check_id, "status": status, "quote": quote, "note": note})
    payload: dict[str, Any] = {"rationale": "reviewed", "checks": checks, **top}
    return json.dumps(payload, ensure_ascii=False)


def _review(client: Client, *, statement: str = STATEMENT, lean: str = LEAN) -> ProofOutputReview:
    reviewer = LeanGroundedOutputReviewer(client=client, model="m", provider="p", max_attempts=2)
    return reviewer.review_explanation(
        theorem_statement=statement, lean_code=lean, explanation=_explanation(), language="ja"
    )


def test_all_ok_is_approved_and_the_checks_are_returned_in_order() -> None:
    review = _review(Client(_answer()))
    assert [c.id for c in review.checks] == list(EPSILON_DELTA_CHECK_IDS)
    assert not any(c.blocks for c in review.checks)
    assert review.approved_flag_contradicted_checks is False


@pytest.mark.parametrize("check_id", MATH_IDS)
def test_one_missing_element_rejects_without_any_quote(check_id: str) -> None:
    client = Client(_answer({check_id: ("missing", "", f"no {check_id} here")}))
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert raised.value.category == "rejected"
    assert f"{check_id} (missing): no {check_id} here" in raised.value.rationale
    assert len(client.prompts) == 1  # a valid negative decision is final, never re-asked


@pytest.mark.parametrize("check_id", EPSILON_DELTA_CHECK_IDS)
def test_one_wrong_element_with_a_quote_from_the_proof_rejects(check_id: str) -> None:
    client = Client(_answer({check_id: ("wrong", QUOTE, "false step")}))
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert raised.value.category == "rejected"
    assert "false step" in raised.value.rationale
    assert QUOTE not in raised.value.rationale  # quotes are never kept in the reason
    assert [c.id for c in raised.value.checks if c.blocks] == [check_id]


@pytest.mark.parametrize("quote", ["", "x", "an invented sentence that is not in the proof"])
def test_wrong_without_a_quote_from_the_proof_does_not_reject(quote: str) -> None:
    review = _review(Client(_answer({"final_inequality": ("wrong", quote, "claims error")})))
    (check,) = [c for c in review.checks if c.id == "final_inequality"]
    assert check.status == "wrong" and check.blocks is False


def test_quote_matching_ignores_whitespace_width_and_tex_spacing() -> None:
    quote = "｜x^2 - a^2｜<\\delta\\,(2|a|+1)"
    with pytest.raises(ProofOutputReviewError):
        _review(Client(_answer({"final_inequality": ("wrong", quote, "n")})))


def test_missing_with_an_invented_quote_still_rejects() -> None:
    with pytest.raises(ProofOutputReviewError):
        _review(Client(_answer({"sum_bound": ("missing", "not in the proof at all", "n")})))


def test_notes_on_ok_elements_never_reject() -> None:
    review = _review(Client(_answer({"conclusion": ("ok", QUOTE, "could be more explicit")})))
    assert not any(c.blocks for c in review.checks)


# --- the reviewer's `approved` flag is ignored -------------------------------------------


def test_approved_true_cannot_override_a_missing_element() -> None:
    answer = _answer({"delta_bounded_by_one": ("missing", "", "no minimum")}, approved=True)
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(Client(answer))
    assert raised.value.category == "rejected"


def test_approved_false_cannot_reject_when_every_element_is_ok_and_is_flagged() -> None:
    review = _review(Client(_answer(approved=False)))
    assert review.approved_flag_contradicted_checks is True


def test_agreeing_or_absent_approved_flag_is_not_flagged() -> None:
    assert _review(Client(_answer(approved=True))).approved_flag_contradicted_checks is False
    assert _review(Client(_answer())).approved_flag_contradicted_checks is False


def test_flag_contradiction_is_logged_without_any_proof_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    contradicted = _review(Client(_answer(approved=False)))
    with caplog.at_level(logging.WARNING):
        _note_review_flag_contradiction("explanation", "job-1", contradicted)
    assert "explanation_review_flag_contradicted_checklist" in caplog.text
    assert "job-1" in caplog.text
    assert "delta" not in caplog.text and "reviewed" not in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        _note_review_flag_contradiction("explanation", "job-1", _review(Client(_answer())))
    assert caplog.text == ""


# --- fail-closed -------------------------------------------------------------------------


@pytest.mark.parametrize("check_id", EPSILON_DELTA_CHECK_IDS)
def test_a_missing_required_id_is_a_schema_failure_never_an_approval(check_id: str) -> None:
    client = Client(_answer(drop=check_id), _answer(drop=check_id))
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert raised.value.category == "schema"
    assert len(client.prompts) == 2
    assert "failed schema validation" in client.prompts[1]


def test_a_complete_second_answer_after_an_incomplete_first_is_used() -> None:
    review = _review(Client(_answer(drop="conclusion"), _answer()))
    assert len(review.checks) == len(EPSILON_DELTA_CHECK_IDS)


def _raw(mutate: Any) -> str:
    payload = json.loads(_answer())
    mutate(payload)
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        _raw(lambda p: p["checks"].append(dict(p["checks"][0]))),  # repeated id
        _raw(lambda p: p["checks"][0].update(id="made_up")),  # unknown id
        _raw(lambda p: p["checks"][0].update(status="fine")),  # unknown status
        _raw(lambda p: p["checks"][0].pop("note")),  # entry missing a field
        _raw(lambda p: p["checks"][0].update(extra=1)),  # entry with an extra field
        _raw(lambda p: p.update(extra=1)),  # unknown top-level key
        _raw(lambda p: p.update(approved="yes")),  # non-boolean flag
        _raw(lambda p: p.update(checks="none")),  # not a list
        _raw(lambda p: p.pop("rationale")),
        _raw(lambda p: p["checks"][-1].update(status="missing")),  # presentation has no "missing"
    ],
)
def test_malformed_checklists_are_schema_failures(bad: str) -> None:
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(Client(bad, bad))
    assert raised.value.category == "schema"


def test_transport_failure_is_never_an_approval() -> None:
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(Client(RuntimeError("down")))
    assert raised.value.category == "transport"


# --- other reviews are unchanged ---------------------------------------------------------


def test_other_theorems_keep_the_original_approved_rationale_format() -> None:
    add_zero = "theorem add_zero_nat (n : Nat) : n + 0 = n := by\n  simp"
    client = Client('{"approved": false, "rationale": "gap"}')
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client, statement="n + 0 = n を示せ", lean=add_zero)
    assert raised.value.category == "rejected" and raised.value.rationale == "gap"
    assert "Checklist (give every id exactly once)" not in client.prompts[0]
    assert raised.value.checks == ()
    # A checklist answer is not valid for them.
    bad = Client(_answer(), _answer())
    with pytest.raises(ProofOutputReviewError) as schema:
        _review(bad, statement="n + 0 = n を示せ", lean=add_zero)
    assert schema.value.category == "schema"


def test_clarification_review_keeps_the_original_format() -> None:
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
    client = Client('{"approved": true, "rationale": "fine"}')
    reviewer = LeanGroundedOutputReviewer(client=client, model="m", provider="p")
    review = reviewer.review_clarification(
        theorem_statement=STATEMENT,
        lean_code=LEAN,
        explanation=_explanation(),
        clarification=clarification,
        language="ja",
    )
    assert review.checks == () and review.rationale == "fine"
    assert "Checklist (give every id exactly once)" not in client.prompts[0]
