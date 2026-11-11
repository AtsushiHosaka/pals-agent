"""``solve_warm`` over a worker that can race its attempts (the resident Lean)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from pals_agent import automation_portfolio as ap

TACTICS = (ap.Tactic("a", "intros; simp"), ap.Tactic("b", "intros; ring"), ap.Tactic("c", "omega"))


class FakeWorker:
    def __init__(self, finished: dict[int, str]) -> None:
        self.finished = finished
        self.checked: list[str] = []
        self.raced = 0

    def check(self, source: str, *, timeout_s: float = 60.0) -> tuple[str, float]:
        self.checked.append(source)
        return "PALS_REF_OK=true\n", 0.0

    def check_race(
        self, sources: Sequence[str], accept: Callable[[int, str], bool], *, timeout_s: float
    ) -> dict[int, str]:
        self.raced = len(sources)
        return self.finished


def ok(k: int) -> str:
    return f"'_pals_portfolio_{k}' does not depend on any axioms\n"


def failed(k: int) -> str:
    return (
        "x.lean:3:2: error: unsolved goals\n"
        f"'_pals_portfolio_{k}' depends on axioms: [sorryAx]\n"
    )


def test_the_raced_attempts_are_judged_in_portfolio_order() -> None:
    worker = FakeWorker({0: failed(0), 2: ok(2), 1: ok(1)})
    statement = "∀ n : ℕ, n + 0 = n"
    result = ap.solve_warm(statement, [], worker, portfolio=TACTICS)  # type: ignore[arg-type]
    assert worker.raced == 3
    assert (result.outcome, result.by) == ("answered", "b")
    assert [a.verdict for a in result.attempts] == ["error_logged", None]


def test_cancelled_attempts_are_not_judged_and_a_total_miss_stays_a_miss() -> None:
    worker = FakeWorker({0: failed(0)})
    result = ap.solve_warm("∀ n : ℕ, n + 0 = n", [], worker, portfolio=TACTICS)  # type: ignore[arg-type]
    assert result.outcome == "miss" and len(result.attempts) == 1


def test_a_timeout_error_with_an_accept_looking_line_is_not_an_answer() -> None:
    # the declaration logged an error even though its axioms line looks clean
    out = "x.lean:3:2: error: (deterministic) timeout\n" + ok(0)
    result = ap.solve_warm(
        "∀ n : ℕ, n + 0 = n", [], FakeWorker({0: out}), portfolio=TACTICS  # type: ignore[arg-type]
    )
    assert result.outcome == "miss"
