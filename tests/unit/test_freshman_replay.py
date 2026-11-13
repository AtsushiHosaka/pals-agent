"""The replay of a recorded normal-path run must not turn a failure into an answer (#123)."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/eval"))

from run_freshman_fast import make_replay  # noqa: E402

from pals_agent import fast_answer as fa  # noqa: E402


def _run(record: dict, deadline: float = 5.0):
    cancel, claim = threading.Event(), fa.RaceClaim()
    seen: list = []
    replay = make_replay(record, seen.extend)
    result = replay(cancel, time.monotonic() + deadline, claim)
    return result, seen


def test_recorded_success_answers() -> None:
    result, seen = _run({"ok": True, "answer_s": 0.05, "usd": 0.5})
    assert result == "normal answer (replayed)"
    assert seen[0]["usd"] == 0.5


def test_recorded_failure_returns_no_answer_but_bills() -> None:
    result, seen = _run({"ok": False, "answer_s": 0.05, "usd": 0.5})
    assert result is None
    assert seen[0]["usd"] == 0.5


def test_recorded_failure_cannot_win_the_race() -> None:
    class SlowFast:
        def run(self, request, language, cancel=None):
            cancel.wait(0.3)
            return fa.FastAnswerResult(outcome="fallthrough")

    replay = make_replay({"ok": False, "answer_s": 0.05, "usd": 0.0}, lambda r: None)
    race = fa.run_with_fallback(SlowFast(), "q", "en", replay, deadline_s=2.0)
    assert race.winner == "none"
    race.settle(2.0)
