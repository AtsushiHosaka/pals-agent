"""Mathlib-as-library portfolio with the REAL pinned Lean + Mathlib, zero model calls."""

import os
import shutil
from pathlib import Path

import pytest

from pals_agent import automation_portfolio as ap
from pals_agent import general_recipe_lane as lane

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = Path(os.environ.get("PALS_LEAN_WORKSPACE", ROOT / "lean-workspace"))
LAKE = shutil.which("lake") or str(Path.home() / ".elan/bin/lake")
pytestmark = pytest.mark.skipif(
    not (WORKSPACE / ".lake/packages/mathlib").exists() or not Path(LAKE).exists(),
    reason="a Lake workspace with built Mathlib (pinned v4.32.0-rc1) is required",
)


@pytest.fixture(scope="module")
def runner() -> lane.LeanRunner:
    return lane.LeanRunner.from_workspace(WORKSPACE, lake=LAKE)


@pytest.fixture(scope="module")
def pool() -> list[lane.PoolRecipe]:
    return lane.load_test_fixtures(ROOT / "tests/fixtures/general_recipes") + (
        lane.load_fixture_recipes(ROOT / "testdata")
    )


@pytest.mark.parametrize(
    ("statement", "tactic"),
    [
        ("∀ x : ℝ, 0 ≤ x ^ 2", "positivity"),
        ("∀ n : ℕ, ¬ n < 0", "simp"),
        ("example (a b : ℤ) : (a + b) * (a - b) = a ^ 2 - b ^ 2 := by sorry", "ring"),
        ("∀ n : ℕ, n < 3 → n + n < 6", "omega"),
    ],
)
def test_portfolio_closes_without_a_model_and_reports_the_tactic(statement, tactic, pool, runner):
    result = ap.solve(
        statement, [], runner, budget_s=90, allow_header=statement.startswith("example")
    )
    assert result.outcome == "answered" and result.route == "portfolio"
    assert result.model_calls == 0
    names = [a.name for a in result.attempts if a.verdict is None]
    assert tactic in names


def test_a_false_statement_is_never_answered(runner):
    quick = tuple(t for t in ap.PORTFOLIO if t.name != "exact?")
    result = ap.solve("∀ x : ℝ, x ^ 2 < 0", [], runner, portfolio=quick, budget_s=90)
    assert result.outcome == "miss"


def test_a_recipe_wins_before_the_portfolio_and_the_portfolio_never_changes_the_statement(
    pool, runner
):
    result = ap.solve("Continuous (fun x : ℝ => x ^ 7)", pool, runner, budget_s=90)
    assert result.outcome == "answered" and result.route == "recipe"
    assert result.proposition == "Continuous (fun x : ℝ => x ^ 7)"


def test_exact_search_records_the_mathlib_lemma_it_found(runner):
    only_search = (ap.PORTFOLIO[-1],)
    result = ap.solve("∀ x : ℝ, Real.exp x > 0", [], runner, portfolio=only_search, budget_s=120)
    assert result.outcome == "answered" and result.by == "exact?"
    assert result.lemma and "Real.exp_pos" in result.lemma


def test_warm_worker_serves_several_requests_from_one_import(pool, runner):
    worker = ap.WarmWorker(runner, ROOT / "scripts/eval/warm_worker.lean")
    try:
        quick = tuple(t for t in ap.PORTFOLIO if t.name != "exact?")
        first = ap.solve_warm("∀ x : ℝ, 0 ≤ x ^ 2", [], worker, portfolio=quick)
        second = ap.solve_warm("∀ n : ℕ, ¬ n < 0", [], worker, portfolio=quick)
        bad = ap.solve_warm("∀ x : ℝ, x ^ 2 < 0", [], worker, portfolio=quick)
    finally:
        worker.close()
    assert first.outcome == second.outcome == "answered" and bad.outcome == "miss"
    assert second.total_s < 3.0  # no Mathlib import per request


def test_a_heartbeat_timeout_is_never_accepted_as_a_proof(runner):
    # With a 1-heartbeat cap the tactic times out; Lean logs an error but may leave the declaration
    # without sorryAx.  The error veto must reject it.
    starved = (ap.Tactic("starved", "intros; nlinarith [sq_nonneg (1 : ℝ)]", heartbeats=1),)
    result = ap.solve(
        "∀ x y : ℝ, x * y ≤ (x ^ 2 + y ^ 2) / 2 + 1", [], runner, portfolio=starved, budget_s=60
    )
    assert result.outcome == "miss"


def test_a_timed_out_warm_worker_is_replaced_and_never_leaks_output_into_the_next_request(runner):
    worker = ap.WarmWorker(runner, ROOT / "scripts/eval/warm_worker.lean")
    try:
        slow = "theorem pals_slow : ∀ n : ℕ, n ≤ n + 1 := by\n  intros; exact?\n"
        with pytest.raises(TimeoutError):
            worker.check(slow, timeout_s=0.5)
        assert not worker.alive()
        worker.restart()
        out, _ = worker.check("theorem t : (1 : ℕ) + 1 = 2 := rfl\n#print axioms t\n")
        assert "'t' does not depend on any axioms" in out and "pals_slow" not in out
    finally:
        worker.close()
