"""The worker's use of the T2 lane's early calls under API reconciliation."""

import time
from types import SimpleNamespace
from typing import Any, cast

import pytest

from pals_agent import t2_lane
from pals_agent.explanations import ProofSemanticReview
from pals_agent.lean_templates import XSquaredBindings, render_x_squared_epsilon_delta
from pals_agent.pipeline import ProofPipeline
from pals_agent.settings import AgentSettings
from pals_agent.speculative_explanation import SpeculativeExplanation
from pals_agent.usage import _reporter
from pals_agent.worker import _T2_CARRY, SqsProofWorker, _T2Carry
from tests.unit.test_worker import (
    ExplainerThatMustNotRun,
    RecordingSemanticReviewer,
    SemanticReviewApi,
)

STATEMENT = "theorem sample : True := by trivial"
LEAN = "theorem sample : True := by\n  trivial"


def _review() -> ProofSemanticReview:
    return ProofSemanticReview(
        decision="approved",
        rationale="The target and proof match the learner request.",
        reviewer_provider="openai",
        reviewer_model="gpt-5.4-mini-2026-03-17",
        session_id="33333333-3333-4333-8333-333333333333",
    )


def _early(lean_code: str, produce: Any = _review) -> SpeculativeExplanation:
    return SpeculativeExplanation.start(
        explain=lambda **_kwargs: produce(),
        theorem_statement=STATEMENT,
        lean_code=lean_code,
        language="zh-Hans",
        deadline=time.monotonic() + 30,
        timeout_seconds=5,
    )


def _worker(api: Any, reviewer: Any) -> SqsProofWorker:
    return SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(explanation_model_timeout_seconds=17)),
        api_client=cast(Any, api),
        pipeline=None,
        explainer=ExplainerThatMustNotRun(),
        proof_reviewer=cast(Any, reviewer),
    )


def _process(worker: SqsProofWorker, carry: _T2Carry | None) -> Any:
    token = _T2_CARRY.set(carry)
    try:
        return worker.process_proof_job("job-semantic")
    finally:
        _T2_CARRY.reset(token)


def test_the_review_started_beside_the_compile_is_used_for_the_same_source() -> None:
    api, reviewer = SemanticReviewApi(), RecordingSemanticReviewer()
    _process(_worker(api, reviewer), _T2Carry(review=_early(LEAN)))

    assert reviewer.calls == []  # the early call replaced the review
    assert [e["decision"] for e in api.evidence] == ["approved"]


def test_a_review_started_for_another_source_is_not_used() -> None:
    api, reviewer = SemanticReviewApi(), RecordingSemanticReviewer()
    other = LEAN.replace("trivial", "exact True.intro")
    _process(_worker(api, reviewer), _T2Carry(review=_early(other)))

    assert len(reviewer.calls) == 1  # the ordinary call ran
    assert [e["decision"] for e in api.evidence] == ["approved"]


def test_a_failed_early_review_is_settled_like_a_failed_direct_one() -> None:
    api, reviewer = SemanticReviewApi(), RecordingSemanticReviewer()

    def fail() -> Any:
        raise RuntimeError("provider unavailable")

    _process(_worker(api, reviewer), _T2Carry(review=_early(LEAN, fail)))

    assert reviewer.calls == []
    assert api.evidence == []
    assert api.state == "failed"  # settled as unavailable, never as an approval


def test_the_early_review_is_used_once_even_when_the_job_is_read_twice() -> None:
    api, reviewer = SemanticReviewApi(), RecordingSemanticReviewer()
    handle = _early(LEAN)
    worker = _worker(api, reviewer)
    _process(worker, _T2Carry(review=handle))
    api.state = "semantic_review"
    _process(worker, _T2Carry(review=handle))  # the same handle again: already adopted

    assert len(reviewer.calls) == 1  # the second delivery paid for its own review


def test_unadopted_early_calls_are_reported_against_the_claim_not_dropped() -> None:
    recorded: list[dict[str, Any]] = []

    class Api:
        def record_usage(self, **kwargs: Any) -> None:
            recorded.append(kwargs)

    def expensive() -> Any:
        reporter = _reporter.get()
        assert reporter is not None
        reporter({"input_tokens": 7, "output_tokens": 1})
        return _review()

    handle = _early(LEAN, expensive)
    worker = _worker(Api(), RecordingSemanticReviewer())
    result = SimpleNamespace(
        speculative_explanation=None, speculative_review=handle, background=None
    )
    with worker._t2_carry_scope(result, proof_job_id="job-1", claim_id="claim-1"):
        pass  # nobody adopted it

    assert [r["usage"]["input_tokens"] for r in recorded] == [7]
    assert recorded[0]["proof_job_id"] == "job-1" and recorded[0]["claim_id"] == "claim-1"


def test_nothing_is_held_when_the_pipeline_started_nothing() -> None:
    worker = _worker(SemanticReviewApi(), RecordingSemanticReviewer())
    result = SimpleNamespace(
        speculative_explanation=None, speculative_review=None, background=None
    )
    with worker._t2_carry_scope(result, proof_job_id="j", claim_id="c") as carry:
        assert carry is None


def _real_pipeline(tmp_path: Any) -> ProofPipeline:
    from pals_agent.artifacts import FileArtifactStore

    return ProofPipeline(
        generator=cast(Any, object()),
        verifier=None,
        artifact_store=FileArtifactStore(tmp_path),
        verification_mode="api_reconcile",
    )


def test_the_pipeline_gets_the_early_callers_only_when_a_switch_is_on(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    for env in (t2_lane.PARALLEL_EXPLANATION_ENV, t2_lane.PARALLEL_REVIEW_ENV):
        monkeypatch.delenv(env, raising=False)
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(template_fixed_explanation_enabled=False)),
        api_client=cast(Any, SemanticReviewApi()),
        pipeline=None,
        explainer=cast(Any, SimpleNamespace(explain=lambda **_k: "e")),
        proof_reviewer=cast(Any, RecordingSemanticReviewer()),
        output_reviewer=cast(Any, object()),
    )
    base = _real_pipeline(tmp_path)

    assert worker._with_t2_calls(base, "ja") is base  # default: unchanged

    monkeypatch.setenv(t2_lane.PARALLEL_REVIEW_ENV, "true")
    with_review = worker._with_t2_calls(base, "ja")
    assert with_review.reviewer is not None and with_review.explainer is None

    monkeypatch.setenv(t2_lane.PARALLEL_EXPLANATION_ENV, "true")
    both = worker._with_t2_calls(base, "ja")
    assert both.explainer is not None and both.explanation_language == "ja"

    # A pipeline that compiles locally is never given them: this is the API-reconcile path only.
    local = SimpleNamespace(verification_mode="local")
    assert worker._with_t2_calls(local, "ja") is local


def test_a_source_the_fixed_template_covers_never_starts_an_explanation_call(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(t2_lane.PARALLEL_EXPLANATION_ENV, "true")
    calls: list[str] = []
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(template_fixed_explanation_enabled=True)),
        api_client=cast(Any, SemanticReviewApi()),
        pipeline=None,
        explainer=cast(Any, SimpleNamespace(explain=lambda **k: calls.append(k["lean_code"]))),
        proof_reviewer=cast(Any, RecordingSemanticReviewer()),
        output_reviewer=cast(Any, object()),
    )
    explain = worker._with_t2_calls(_real_pipeline(tmp_path), "ja").explainer.explain
    kwargs = {
        "theorem_statement": "s", "verified": True, "language": "ja",
        "deadline": 1.0, "timeout_seconds": 1.0,
    }
    with pytest.raises(RuntimeError):
        explain(lean_code=render_x_squared_epsilon_delta(XSquaredBindings()), **kwargs)
    explain(lean_code="theorem t : True := by trivial", **kwargs)
    assert calls == ["theorem t : True := by trivial"]


# ---- review fixes: usage never lost, off means unchanged, repair settles early -----------------


def test_adopting_without_a_reporter_does_not_consume_the_usage() -> None:
    def expensive() -> Any:
        reporter = _reporter.get()
        assert reporter is not None
        reporter({"input_tokens": 9, "output_tokens": 1})
        return _review()

    handle = _early(LEAN, expensive)
    assert _reporter.get() is None
    handle.adopt(
        theorem_statement=STATEMENT, lean_code=LEAN, language="zh-Hans", wait_seconds=5
    )
    # Nobody could report it, so it is still there for whoever settles it later.
    assert [r["input_tokens"] for r in handle.take_usage_once()] == [9]


def test_an_empty_background_with_no_handles_holds_nothing() -> None:
    worker = _worker(SemanticReviewApi(), RecordingSemanticReviewer())
    result = SimpleNamespace(
        speculative_explanation=None, speculative_review=None, background=t2_lane.RunBackground()
    )
    with worker._t2_carry_scope(result, proof_job_id="j", claim_id="c") as carry:
        assert carry is None


class _Recorder:
    def __init__(self) -> None:
        self.recorded: list[dict[str, Any]] = []

    def record_usage(self, **kwargs: Any) -> None:
        self.recorded.append(kwargs)


def _billed(tokens: int) -> Any:
    def call() -> Any:
        reporter = _reporter.get()
        assert reporter is not None
        reporter({"input_tokens": tokens, "output_tokens": 1})
        return _review()

    return call


def test_the_resumed_delivery_reports_an_adopted_calls_usage_against_the_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _Recorder()
    worker = _worker(api, RecordingSemanticReviewer())
    handle = _early(LEAN, _billed(11))
    seen: list[Any] = []

    def resume(*_a: Any, **_k: Any) -> bool:
        # What the semantic-review branch does: adopt, which forwards to the active reporter.
        carry = _T2_CARRY.get()
        assert carry is not None
        carry.review.adopt(
            theorem_statement=STATEMENT, lean_code=LEAN, language="zh-Hans", wait_seconds=5
        )
        seen.append(True)
        return True

    monkeypatch.setattr(SqsProofWorker, "process_proof_job", lambda self, *a, **k: resume())
    carry = _T2Carry(review=handle)
    worker._resume_with_carry(
        carry, {"state": "semantic_review"}, proof_job_id="job-1", claim_id="claim-1",
        extend_visibility=None,
    )

    assert seen == [True]
    assert [r["usage"]["input_tokens"] for r in api.recorded] == [11]


def test_a_failed_compile_settles_the_carry_before_the_repair_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _Recorder()
    worker = _worker(api, RecordingSemanticReviewer())
    handle = _early(LEAN, _billed(5))
    during_repair: list[int] = []

    def repair(*_a: Any, **_k: Any) -> bool:
        during_repair.append(len(api.recorded))  # reported already, before the nested run
        assert _T2_CARRY.get() is None  # and nothing is carried into the repair
        return True

    monkeypatch.setattr(SqsProofWorker, "process_proof_job", lambda self, *a, **k: repair())
    worker._resume_with_carry(
        _T2Carry(review=handle), {"state": "drafting"}, proof_job_id="job-1", claim_id="claim-1",
        extend_visibility=None,
    )

    assert during_repair == [1]
    assert [r["usage"]["input_tokens"] for r in api.recorded] == [5]  # exactly once


def test_an_explanation_is_not_started_when_the_summary_path_could_not_adopt_it(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(t2_lane.PARALLEL_EXPLANATION_ENV, "true")
    monkeypatch.delenv(t2_lane.PARALLEL_REVIEW_ENV, raising=False)
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(template_fixed_explanation_enabled=False)),
        api_client=cast(Any, SemanticReviewApi()),
        pipeline=None,
        explainer=cast(Any, SimpleNamespace(explain=lambda **_k: "e")),
        proof_reviewer=cast(Any, RecordingSemanticReviewer()),
        output_reviewer=None,  # the summary path needs it to publish an explanation
    )
    base = _real_pipeline(tmp_path)

    assert worker._with_t2_calls(base, "ja") is base


def test_resuming_after_the_compile_does_not_wait_for_a_race_loser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waited: list[float] = []

    class Background:
        def drain(self, timeout: float = 0.0) -> int:
            waited.append(timeout)
            return 0

        def pending(self) -> int:
            return 1

    monkeypatch.setattr(SqsProofWorker, "process_proof_job", lambda self, *a, **k: True)
    worker = _worker(_Recorder(), RecordingSemanticReviewer())
    worker._resume_with_carry(
        _T2Carry(background=Background()), {"state": "semantic_review"},
        proof_job_id="j", claim_id="c", extend_visibility=None,
    )

    assert waited == []  # the loser reports its own usage when it ends; the review is not held
