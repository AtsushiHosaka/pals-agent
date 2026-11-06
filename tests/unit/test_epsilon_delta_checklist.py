"""Decision table of the x² epsilon-delta checklist review (stub models only).

The reviewer answers one entry per required element and the code decides: any element that is
not "ok" rejects (a nonblank note is required for it; the quote is only informational). The
review is sampled twice, independently and in parallel, and either sample can reject. The
reviewer's own `approved` flag is ignored. Missing, repeated or unknown ids, bad statuses and
blank notes are schema failures (fail-closed). Other reviews keep their original format.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest

from pals_agent.explanations import (
    CHECKLIST_SAMPLES,
    EPSILON_DELTA_CHECK_IDS,
    EPSILON_DELTA_CORE_IDS,
    ExplanationSection,
    LeanGroundedOutputReviewer,
    LeanLineReference,
    ProofClarification,
    ProofExplanation,
    ProofOutputReview,
    ProofOutputReviewError,
    single_sample_catch_all_ids,
)
from pals_agent.usage import capture_usage, report_usage
from pals_agent.worker import _note_review_flag_contradiction, _note_single_sample_remarks

LEAN = "theorem t : Continuous (fun x : ℝ => x ^ 2) := by\n  continuity"
STATEMENT = "x² が連続であることを説明してください。"
ADD_ZERO = "theorem add_zero_nat (n : Nat) : n + 0 = n := by\n  simp"
CATCH_ALL_IDS = ["presentation", "other_defect"]  # ok or wrong only, AND over the samples
MATH_IDS = list(EPSILON_DELTA_CORE_IDS)  # OR over the samples
CALL_ID = "11111111-1111-4111-8111-111111111111"


def _explanation() -> ProofExplanation:
    ref = LeanLineReference(2, 2, "  continuity")
    return ProofExplanation(
        overview="$\\varepsilon>0$ を任意に取り、実数 $a$ を固定します。",
        sections=(ExplanationSection("s", "t", "$|x^2-a^2|<\\varepsilon$ です。", (ref,)),),
        conclusion="$a$ は任意なので、$x^2$ は連続です。",
        model="m",
        provider="p",
        prompt="",
        raw_model_output="",
        elapsed_ms=0,
    )


class Client:
    """Thread-safe stub. `answers` are consumed in call order; the last one repeats.

    `by_thread` instead gives the first sample answer set 0 and the second answer set 1, so a
    test can make exactly one of two parallel samples misbehave.
    """

    def __init__(
        self,
        *answers: str | Exception,
        by_thread: tuple[list[str | Exception], list[str | Exception]] | None = None,
        delay: float = 0.0,
        usage: bool = False,
    ) -> None:
        self.answers = list(answers)
        self.by_thread = by_thread
        self.delay = delay
        self.usage = usage
        self.prompts: list[str] = []
        self._lock = threading.Lock()
        self._roles: dict[int, int] = {}
        self._starts: list[int] = []
        self._counts = [0, 0]

    def generate(self, *, model: str, prompt: str, timeout_seconds: float | None = None) -> str:
        _ = (model, timeout_seconds)
        with self._lock:
            self.prompts.append(prompt)
            if self.by_thread is not None:
                # A new sample starts with a prompt that is not a schema retry; a retry
                # belongs to the sample running in the same thread (workers may be reused).
                ident = threading.get_ident()
                if "failed schema validation" in prompt and ident in self._roles:
                    role = self._roles[ident]
                else:
                    role = len(self._starts)
                    self._starts.append(ident)
                    self._roles[ident] = role
                script = self.by_thread[role]
                answer = script[min(self._counts[role], len(script) - 1)]
                self._counts[role] += 1
            else:
                answer = self.answers[0] if len(self.answers) == 1 else self.answers.pop(0)
        if self.delay:
            time.sleep(self.delay)
        if self.usage:
            report_usage(CALL_ID, "gpt-6-luna", {"input_tokens": 10, "output_tokens": 5})
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


def _reviewer(client: Client, **kwargs: Any) -> LeanGroundedOutputReviewer:
    return LeanGroundedOutputReviewer(
        client=client, model="m", provider="p", max_attempts=2, **kwargs
    )


def _review(
    client: Client, *, statement: str = STATEMENT, lean: str = LEAN, **kwargs: Any
) -> ProofOutputReview:
    return _reviewer(client, **kwargs).review_explanation(
        theorem_statement=statement, lean_code=lean, explanation=_explanation(), language="ja"
    )


# --- one sample: every element that is not ok rejects, with or without a quote -----------


def test_all_ok_is_approved_with_both_samples_returned_in_order() -> None:
    client = Client(_answer())
    review = _review(client)
    assert len(review.samples) == CHECKLIST_SAMPLES == 2
    for sample in review.samples:
        assert [c.id for c in sample] == list(EPSILON_DELTA_CHECK_IDS)
        assert not any(c.blocks for c in sample)
    assert len(client.prompts) == 2 and client.prompts[0] == client.prompts[1]
    assert review.approved_flag_contradicted_checks is False


@pytest.mark.parametrize("status", ["missing", "wrong"])
@pytest.mark.parametrize("check_id", MATH_IDS)
@pytest.mark.parametrize("quote", ["", "an excerpt that is not in the proof at all", "x"])
def test_any_element_that_is_not_ok_rejects_whatever_its_quote(
    check_id: str, status: str, quote: str
) -> None:
    client = Client(_answer({check_id: (status, quote, f"{check_id} is {status}")}))
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert raised.value.category == "rejected"
    assert f"{check_id} ({status}): {check_id} is {status}" in raised.value.rationale
    assert len(client.prompts) == 2  # both samples ran


@pytest.mark.parametrize("check_id", CATCH_ALL_IDS)
def test_the_catch_all_elements_reject_when_every_sample_says_wrong(check_id: str) -> None:
    client = Client(_answer({check_id: ("wrong", "", "some other defect")}))
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert f"{check_id} (wrong): some other defect" in raised.value.rationale


@pytest.mark.parametrize("check_id", CATCH_ALL_IDS)
def test_the_catch_all_elements_cannot_be_missing(check_id: str) -> None:
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(Client(_answer({check_id: ("missing", "", "n")})))
    assert raised.value.category == "schema"


def test_the_rejection_reason_keeps_notes_but_not_quotes() -> None:
    secret = "a quoted proof passage"
    client = Client(_answer({"sum_bound": ("missing", secret, "no reason for the bound")}))
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert "no reason for the bound" in raised.value.rationale
    assert secret not in raised.value.rationale


def test_notes_on_ok_elements_never_reject() -> None:
    review = _review(Client(_answer({"conclusion": ("ok", "", "could be more explicit")})))
    assert not any(c.blocks for sample in review.samples for c in sample)


@pytest.mark.parametrize("status", ["missing", "wrong"])
def test_a_failed_element_without_a_note_still_rejects_with_a_fixed_reason(status: str) -> None:
    """A negative vote stands without a reason; it is never retried into an approval."""
    client = Client(_answer({"final_inequality": (status, "q", "   ")}))
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert raised.value.category == "rejected"
    assert f"final_inequality ({status}): (the reviewer gave no reason)" in raised.value.rationale
    assert len(client.prompts) == 2  # no schema retry


def test_the_quote_key_is_optional() -> None:
    payload = json.loads(_answer())
    for check in payload["checks"]:
        del check["quote"]
    review = _review(Client(json.dumps(payload)))
    assert all(c.quote == "" for sample in review.samples for c in sample)
    rejecting = json.loads(_answer({"sum_bound": ("missing", "", "no step")}))
    for check in rejecting["checks"]:
        del check["quote"]
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(Client(json.dumps(rejecting)))
    assert raised.value.category == "rejected"


# --- two independent samples: core elements are OR, the catch-alls are AND -----------------


@pytest.mark.parametrize("check_id", CATCH_ALL_IDS)
def test_a_catch_all_reported_by_only_one_sample_does_not_reject(check_id: str) -> None:
    """The catch-alls are where a reviewer invents defects: one accusation is not enough."""
    client = Client(by_thread=([_answer()], [_answer({check_id: ("wrong", "", "invented")})]))
    review = _review(client)
    assert len(review.samples) == 2
    flagged = [c.id for sample in review.samples for c in sample if c.blocks]
    assert flagged == [check_id]  # kept in the report, not used for the decision


@pytest.mark.parametrize("check_id", CATCH_ALL_IDS)
def test_a_catch_all_wrong_in_one_sample_and_a_core_miss_in_the_other_rejects(
    check_id: str,
) -> None:
    client = Client(
        by_thread=(
            [_answer({check_id: ("wrong", "", "x")})],
            [_answer({"sum_bound": ("missing", "", "no basis")})],
        )
    )
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert "sum_bound (missing): no basis" in raised.value.rationale
    assert check_id not in raised.value.rationale  # only one sample said it


def test_the_two_catch_alls_are_counted_separately() -> None:
    client = Client(
        by_thread=(
            [_answer({"presentation": ("wrong", "", "a")})],
            [_answer({"other_defect": ("wrong", "", "b")})],
        )
    )
    assert _review(client)  # no element was reported wrong by both samples


@pytest.mark.parametrize("check_id", CATCH_ALL_IDS)
def test_a_failed_sample_leaves_a_catch_all_undecided_and_fails_closed(check_id: str) -> None:
    client = Client(by_thread=([_answer({check_id: ("wrong", "", "x")})], [RuntimeError("down")]))
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert raised.value.category == "transport"


def test_the_ablation_asks_every_core_element_but_not_other_defect() -> None:
    ids = tuple(i for i in EPSILON_DELTA_CHECK_IDS if i != "other_defect")
    answer = json.loads(_answer())
    answer["checks"] = [c for c in answer["checks"] if c["id"] != "other_defect"]
    client = Client(json.dumps(answer))
    review = _review(client, checklist_ids=ids)
    assert all(len(sample) == len(ids) for sample in review.samples)
    assert "other_defect" not in client.prompts[0]
    # An answer that still contains the dropped element is a schema failure.
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(Client(_answer()), checklist_ids=ids)
    assert raised.value.category == "schema"


def test_the_default_asks_every_element_and_the_ids_are_validated() -> None:
    client = Client(_answer())
    _review(client)
    assert "- other_defect:" in client.prompts[0]
    with pytest.raises(ValueError, match="core element"):
        _reviewer(Client(_answer()), checklist_ids=("presentation",))
    with pytest.raises(ValueError, match="unknown id"):
        _reviewer(Client(_answer()), checklist_ids=(*EPSILON_DELTA_CHECK_IDS, "made_up"))


# --- either core sample can reject ------------------------------------------


def test_one_rejecting_sample_is_enough_to_reject() -> None:
    client = Client(
        by_thread=(
            [_answer()],
            [_answer({"delta_bounded_by_one": ("missing", "", "no minimum with 1")})],
        )
    )
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert raised.value.category == "rejected"
    assert "delta_bounded_by_one (missing): no minimum with 1" in raised.value.rationale
    assert len(raised.value.samples) == 2  # the approving sample is kept for the report


def test_the_rejection_reason_is_the_union_of_what_both_samples_rejected() -> None:
    client = Client(
        by_thread=(
            [_answer({"factorization": ("wrong", "", "a sum, not a product")})],
            [_answer({"conclusion": ("missing", "", "no conclusion")})],
        )
    )
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    reason = raised.value.rationale
    assert "factorization (wrong): a sum, not a product" in reason
    assert "conclusion (missing): no conclusion" in reason
    assert reason.index("factorization") < reason.index("conclusion")  # checklist order


def test_a_sample_that_approves_cannot_outvote_a_rejection() -> None:
    client = Client(by_thread=([_answer()] * 1, [_answer({"sum_bound": ("missing", "", "n")})] * 1))
    with pytest.raises(ProofOutputReviewError):
        _review(client)


def test_two_independent_review_sessions_are_opened() -> None:
    issued: list[uuid.UUID] = []

    def factory() -> uuid.UUID:
        value = uuid.uuid4()
        issued.append(value)
        return value

    review = _review(Client(_answer()), session_id_factory=factory)
    assert len(issued) == 2 and issued[0] != issued[1]
    assert review.session_id == str(issued[0])


def test_the_samples_run_in_parallel() -> None:
    client = Client(_answer(), delay=0.3)
    started = time.monotonic()
    _review(client)
    assert time.monotonic() - started < 0.55  # sequential would take >= 0.6


def test_both_samples_are_metered() -> None:
    client = Client(_answer(), usage=True)
    with capture_usage() as records:
        _review(client)
    assert len(records) == 2
    assert all(record["input_tokens"] == 10 for record in records)


# --- fail-closed -------------------------------------------------------------------------


def test_one_sample_with_a_transport_failure_fails_the_review() -> None:
    client = Client(by_thread=([_answer()], [RuntimeError("down")]))
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert raised.value.category == "transport"
    assert len(client.prompts) == 2


def test_one_sample_with_malformed_output_fails_the_review() -> None:
    client = Client(by_thread=([_answer()], ["not json"]))
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert raised.value.category == "schema"


def test_a_rejection_is_conclusive_even_if_the_other_sample_failed() -> None:
    client = Client(
        by_thread=([_answer({"sum_bound": ("missing", "", "n")})], [RuntimeError("down")])
    )
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert raised.value.category == "rejected"


def test_an_unexpected_error_in_one_sample_surfaces_after_the_other_finished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finished = threading.Event()
    original = LeanGroundedOutputReviewer._review

    def flaky(self: LeanGroundedOutputReviewer, **kwargs: Any) -> ProofOutputReview:
        if kwargs["session_id"].endswith("-bad"):
            raise ValueError("boom")
        time.sleep(0.1)
        try:
            return original(self, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(LeanGroundedOutputReviewer, "_review", flaky)
    ids = iter(["good", "x-bad"])
    reviewer = _reviewer(Client(_answer()), session_id_factory=lambda: ids.__next__())
    with pytest.raises(ValueError, match="boom"):
        reviewer.review_explanation(
            theorem_statement=STATEMENT, lean_code=LEAN, explanation=_explanation(), language="ja"
        )
    assert finished.is_set()  # the pool joined the healthy sample before the error left


@pytest.mark.parametrize("check_id", EPSILON_DELTA_CHECK_IDS)
def test_a_missing_required_id_is_a_schema_failure_never_an_approval(check_id: str) -> None:
    client = Client(_answer(drop=check_id))
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client)
    assert raised.value.category == "schema"
    assert any("failed schema validation" in p for p in client.prompts)


def test_a_complete_second_answer_after_an_incomplete_first_is_used() -> None:
    client = Client(by_thread=([_answer(drop="conclusion"), _answer()], [_answer()]))
    review = _review(client)
    assert all(len(sample) == len(EPSILON_DELTA_CHECK_IDS) for sample in review.samples)


def _raw(mutate: Callable[[dict[str, Any]], object]) -> str:
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
        _raw(lambda p: p["checks"][-1].update(status="missing", note="n")),  # other_defect
        _raw(lambda p: p["checks"][-2].update(status="missing", note="n")),  # presentation
    ],
)
def test_malformed_checklists_are_schema_failures(bad: str) -> None:
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(Client(bad))
    assert raised.value.category == "schema"


# --- the reviewer's `approved` flag is ignored -------------------------------------------


def test_approved_true_cannot_override_a_missing_element() -> None:
    answer = _answer({"delta_bounded_by_one": ("missing", "", "no minimum")}, approved=True)
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(Client(answer))
    assert raised.value.category == "rejected"


def test_approved_false_cannot_reject_when_every_element_is_ok_and_is_flagged() -> None:
    assert _review(Client(_answer(approved=False))).approved_flag_contradicted_checks is True


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
    assert "reviewed" not in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        _note_review_flag_contradiction("explanation", "job-1", _review(Client(_answer())))
    assert caplog.text == ""


# --- other reviews are unchanged (one call, original format) -----------------------------


def test_other_theorems_keep_the_original_format_and_a_single_call() -> None:
    client = Client('{"approved": false, "rationale": "gap"}')
    with pytest.raises(ProofOutputReviewError) as raised:
        _review(client, statement="n + 0 = n を示せ", lean=ADD_ZERO)
    assert raised.value.category == "rejected" and raised.value.rationale == "gap"
    assert len(client.prompts) == 1
    assert "Checklist (give every id exactly once)" not in client.prompts[0]
    assert raised.value.samples == ()
    # A checklist answer is not valid for them.
    with pytest.raises(ProofOutputReviewError) as schema:
        _review(Client(_answer()), statement="n + 0 = n を示せ", lean=ADD_ZERO)
    assert schema.value.category == "schema"


def test_other_theorems_are_metered_once() -> None:
    client = Client('{"approved": true, "rationale": "ok"}', usage=True)
    with capture_usage() as records:
        _review(client, statement="n + 0 = n を示せ", lean=ADD_ZERO)
    assert len(records) == 1


def test_clarification_review_keeps_the_original_format_and_a_single_call() -> None:
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
    review = _reviewer(client).review_clarification(
        theorem_statement=STATEMENT,
        lean_code=LEAN,
        explanation=_explanation(),
        clarification=clarification,
        language="ja",
    )
    assert review.samples == () and review.rationale == "fine"
    assert len(client.prompts) == 1
    assert "Checklist (give every id exactly once)" not in client.prompts[0]


# --- a catch-all remark made by one sample only is counted, without content --------------


def test_single_sample_catch_all_remarks_are_identified_and_logged_without_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "a remark about the text that must not be logged"
    client = Client(
        by_thread=(
            [_answer()],
            [
                _answer(
                    {"presentation": ("wrong", "", secret), "other_defect": ("wrong", "", secret)}
                )
            ],
        )
    )
    review = _review(client)
    assert single_sample_catch_all_ids(review) == ("presentation", "other_defect")
    with caplog.at_level(logging.WARNING):
        _note_single_sample_remarks("explanation", "job-42", review)
    assert "explanation_review_single_sample_remark" in caplog.text
    assert "elements=presentation,other_defect" in caplog.text
    assert "job-42" not in caplog.text  # only a hash of the resource id
    assert "resource_sha256=" in caplog.text
    assert secret not in caplog.text


def test_no_single_sample_remark_means_no_log_line(caplog: pytest.LogCaptureFixture) -> None:
    agreeing = Client(_answer({"presentation": ("wrong", "", "both say so")}))
    with pytest.raises(ProofOutputReviewError):
        _review(agreeing)  # both samples: a rejection, not a remark
    clean = _review(Client(_answer()))
    assert single_sample_catch_all_ids(clean) == ()
    with caplog.at_level(logging.WARNING):
        _note_single_sample_remarks("explanation", "job-1", clean)
    assert caplog.text == ""
