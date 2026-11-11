import threading
import time
from typing import Any

import pytest

from pals_agent import t2_lane
from pals_agent.t2_lane import (
    ExplanationRun,
    VerificationMemo,
    drain_background,
    race_candidates,
    t2_run_scope,
    variant_instruction,
)
from pals_agent.usage import usage_scope


def test_flags_default_off_and_are_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        t2_lane.NO_SKETCH_ENV,
        t2_lane.PARALLEL_CANDIDATES_ENV,
        t2_lane.PATCH_REPAIR_ENV,
        t2_lane.PARALLEL_EXPLANATION_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    assert not t2_lane.no_sketch_enabled()
    assert not t2_lane.parallel_candidates_enabled()
    assert not t2_lane.patch_repair_enabled()
    assert not t2_lane.parallel_explanation_enabled()
    monkeypatch.setenv(t2_lane.PATCH_REPAIR_ENV, "true")
    assert t2_lane.patch_repair_enabled()
    monkeypatch.setenv(t2_lane.PATCH_REPAIR_ENV, "yes")
    with pytest.raises(ValueError):
        t2_lane.patch_repair_enabled()


def _usage(model_tokens: int) -> dict[str, Any]:
    return {"input_tokens": model_tokens, "output_tokens": 1, "model": "m"}


def _spend(tokens: int) -> None:
    from pals_agent.usage import _reporter

    reporter = _reporter.get()
    assert reporter is not None
    reporter(_usage(tokens))


def test_first_winner_returns_early_and_the_loser_is_cancelled_but_counted() -> None:
    release = threading.Event()
    started_compile = {"loser": False}

    def winner(cancel: threading.Event) -> str:
        _spend(100)
        return "win"

    def loser(cancel: threading.Event) -> str:
        _spend(7)  # the model call that cannot be recalled
        release.wait(5)
        if not cancel.is_set():
            started_compile["loser"] = True
        return "late"

    seen: list[dict[str, Any]] = []
    with usage_scope(seen.append):
        t0 = time.monotonic()
        result = race_candidates([winner, loser], is_win=lambda v: v == "win", rank=lambda v: 0.0)
        assert time.monotonic() - t0 < 2  # did not wait for the loser
        assert result.winner is not None and result.winner.value == "win"
        assert result.cancelled == 1
        # the winner is counted at once; the loser has not ended yet
        assert [r["input_tokens"] for r in seen] == [100]
        release.set()
        assert drain_background(5) == 0
    # the loser's tokens arrive exactly once, after it ends; it saw the cancel and did not compile
    assert sorted(r["input_tokens"] for r in seen) == [7, 100]
    assert started_compile["loser"] is False


def test_each_candidate_runs_with_its_own_variant() -> None:
    styles: list[str] = []
    lock = threading.Lock()

    def task(cancel: threading.Event) -> int:
        with lock:
            styles.append(variant_instruction())
        return 0

    race_candidates([task, task], is_win=lambda v: False, rank=lambda v: 0.0)
    assert len(set(styles)) == 2 and all(styles)
    assert variant_instruction() == ""


def test_when_nobody_wins_the_best_ranked_finished_candidate_is_returned() -> None:
    result = race_candidates(
        [lambda c: 5, lambda c: 2, lambda c: 9], is_win=lambda v: False, rank=lambda v: float(v)
    )
    assert result.winner is None
    assert result.best is not None and result.best.value == 2
    assert result.cancelled == 0


def test_candidate_errors_are_captured_not_raised() -> None:
    def boom(cancel: threading.Event) -> int:
        raise RuntimeError("model down")

    result = race_candidates([boom, lambda c: 1], is_win=lambda v: v == 1, rank=lambda v: 0.0)
    assert result.winner is not None and result.winner.value == 1
    only_errors = race_candidates([boom, boom], is_win=lambda v: True, rank=lambda v: 0.0)
    assert only_errors.best is None
    assert all(isinstance(c.error, RuntimeError) for c in only_errors.candidates)


def test_usage_of_all_finished_candidates_is_forwarded_once_when_nobody_wins() -> None:
    seen: list[dict[str, Any]] = []

    def task(tokens: int):
        def run(cancel: threading.Event) -> int:
            _spend(tokens)
            return tokens

        return run

    with usage_scope(seen.append):
        race_candidates([task(3), task(4)], is_win=lambda v: False, rank=lambda v: float(v))
    assert sorted(r["input_tokens"] for r in seen) == [3, 4]


def test_verification_memo_is_exact_and_one_shot() -> None:
    memo = VerificationMemo()
    memo.put("code", "result")
    assert memo.take("code2") is None
    assert memo.take("code") == "result"
    assert memo.take("code") is None


class _Explainer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def explain(self, **kwargs: Any) -> str:
        self.calls.append(kwargs["lean_code"])
        _spend(11)
        return f"explained:{kwargs['lean_code']}"


def test_explanation_run_keeps_a_matching_call_and_discards_a_changed_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(t2_lane.PARALLEL_EXPLANATION_ENV, "true")
    explainer = _Explainer()
    run = ExplanationRun(explainer.explain, "ja")
    run.start(statement="s", lean_code="v1")
    run.start(statement="s", lean_code="v1")  # same source: no second call
    run.start(statement="s", lean_code="v2")  # the proof changed: v1 is discarded
    for handle in run.discarded:
        handle.wait(5)
    kept = run.finish(verified=True, statement="s", lean_code="v2")
    assert kept is not None
    assert sorted(explainer.calls) == ["v1", "v2"]
    assert len(run.discarded) == 1
    assert run.discarded[0].held_usage()[0]["input_tokens"] == 11  # billed though unused
    seen: list[dict[str, Any]] = []
    with usage_scope(seen.append):
        text = kept.adopt(theorem_statement="s", lean_code="v2", language="ja", wait_seconds=5)
    assert text == "explained:v2" and len(seen) == 1


def test_explanation_run_discards_when_not_verified_or_source_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(t2_lane.PARALLEL_EXPLANATION_ENV, "true")
    for verified, final in ((False, "v1"), (True, "other")):
        explainer = _Explainer()
        run = ExplanationRun(explainer.explain, "ja")
        run.start(statement="s", lean_code="v1")
        assert run.finish(verified=verified, statement="s", lean_code=final) is None
        assert len(run.discarded) == 1


def test_explanation_run_is_inert_when_the_flag_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(t2_lane.PARALLEL_EXPLANATION_ENV, raising=False)
    explainer = _Explainer()
    with t2_run_scope(explainer.explain, "ja") as (_memo, run):
        run.start(statement="s", lean_code="v1")
        assert explainer.calls == []
