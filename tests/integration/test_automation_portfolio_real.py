"""Mathlib-as-library portfolio with the REAL pinned Lean + Mathlib, zero model calls."""

import os
import shutil
import time
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


# --- computation, yes/no and the let hoist with the real Lean ---------------------------------
@pytest.mark.parametrize(
    ("type_symbol", "expression", "value"),
    [
        ("ℤ", "(2 : ℤ) ^ 10 + 3", "1027"),
        ("ℚ", "(1 : ℚ) / 2 + 1 / 3", "5 / 6"),
        ("ℕ", "∑ k ∈ Finset.range 11, k", "55"),
        ("ℝ", "∫ x in (0 : ℝ)..(1 : ℝ), x ^ 2", "1 / 3"),
        ("ℝ", "(Matrix.det !![(1 : ℝ), 2; 3, 5])", "-1"),
        ("ℕ", "Nat.choose 5 2", "10"),
    ],
)
def test_lean_derives_the_value_and_the_closed_statement_is_reproved(
    type_symbol, expression, value, runner
):
    worker = ap.WarmWorker(runner, ROOT / "scripts/eval/warm_worker.lean")
    try:
        derived = ap.derive_value(worker, expression, type_symbol)
        assert derived is not None and "".join(derived.split()) == "".join(value.split())
        statement = ap.closed_value_statement(expression, derived, type_symbol)
        assert ap.solve_warm(statement, [], worker).outcome == "answered"
        # a wrong value is never provable, whoever proposed it
        wrong = ap.closed_value_statement(expression, "7", type_symbol)
        assert ap.solve_warm(wrong, [], worker, deadline=time.monotonic() + 8).outcome == "miss"
    finally:
        worker.close()


def test_a_derivative_value_that_lean_cannot_normalise_is_not_invented(runner):
    worker = ap.WarmWorker(runner, ROOT / "scripts/eval/warm_worker.lean")
    try:
        assert ap.derive_value(worker, "deriv (fun x : ℝ => x ^ 3 - 3 * x) 2", "ℝ") is None
    finally:
        worker.close()


def test_the_let_statement_of_the_catalog_is_hoisted_and_lean_accepts_the_same_prop(runner):
    import json

    from pals_agent import statement_normalise as normalise

    manifest = json.loads((ROOT / "testdata/generation-eval-v1/manifest.json").read_text())
    card = next(
        p["fixed_lean_statement"]
        for p in manifest["problems"]
        if p["id"] == "la_v6_nonzero_maps_zero_composite"
    )
    closed = ap.closed_statement(ap.split_preamble(card)[1])
    hoisted = normalise.hoist_lets(closed)
    assert hoisted is not None
    worker = ap.WarmWorker(runner, ROOT / "scripts/eval/warm_worker.lean")
    try:
        out, _ = worker.check(normalise.equivalence_source(closed, hoisted), timeout_s=60)
        assert "'_pals_hoist' depends on axioms" in out and "error" not in out
        # a hoist that changes the meaning is refused by Lean
        wrong = hoisted.replace("≠ 0 ∧", "= 0 ∧", 1)
        bad, _ = worker.check(normalise.equivalence_source(closed, wrong), timeout_s=60)
        assert "error" in bad
    finally:
        worker.close()
