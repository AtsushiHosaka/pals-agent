import random

import pytest

from pals_agent.evals.analysis import (
    compare,
    format_report,
    mcnemar_exact,
    mde_binary,
    mde_continuous,
    paired_bootstrap,
    paired_permutation_test,
)


def run(pid, arm, rep, **kw):
    row = {
        "schema": "pals.generation-eval.run.v1",
        "problem_id": pid,
        "arm": arm,
        "repeat": rep,
        "success": 1,
        "first_attempt_ok": 1,
        "repairs_used": 0,
        "wall_s": 100.0,
        "cost_usd": 0.05,
        "error": None,
    }
    row.update(kw)
    return row


def test_mcnemar_exact_known_values():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 5) == 1.0
    assert mcnemar_exact(0, 5) == pytest.approx(0.0625)
    assert mcnemar_exact(1, 9) == pytest.approx(2 * 11 / 1024)


def test_bootstrap_constant_difference_has_degenerate_interval():
    mean, lo, hi = paired_bootstrap([-3.0] * 20, n_boot=500)
    assert mean == lo == hi == -3.0


def test_identical_arms_show_no_effect():
    rows = [run(f"p{i}", arm, r, wall_s=50 + i) for i in range(30) for arm in "AB" for r in (1, 2)]
    res = compare(rows, "A", "B", n_boot=500)
    for m, e in res["metrics"].items():
        assert e["diff"] == 0 and not e["ci_excludes_zero"], m
    ok = res["metrics"]["success"]
    assert ok["perm_p"] == 1.0 and "mcnemar_p" not in ok  # 2 repeats: no pooled McNemar
    assert all(v["p"] == 1.0 for v in ok["mcnemar_by_repeat"].values())


def test_clear_effect_is_detected_and_repeats_are_averaged():
    rows = []
    for i in range(40):
        for r in (1, 2):
            rows.append(run(f"p{i}", "A", r, success=0 if i < 14 else 1, wall_s=200))
            rows.append(run(f"p{i}", "B", r, success=1, wall_s=150))
    res = compare(rows, "A", "B", n_boot=2000)
    s = res["metrics"]["success"]
    assert res["n_problems"] == 40 and s["n"] == 40  # 80 rows per arm, 40 problems
    assert s["improved"] == 14 and s["worsened"] == 0
    assert s["ci_excludes_zero"] and s["perm_p"] < 0.001
    assert set(s["mcnemar_by_repeat"]) == {1, 2}
    assert res["metrics"]["wall_s"]["diff"] == pytest.approx(-50)
    assert "(no effect shown)" not in format_report(res).split("success")[1].splitlines()[0]


def test_only_shared_problems_and_error_rows_are_excluded():
    rows = [
        run("p1", "A", 1),
        run("p1", "B", 1),
        run("only_a", "A", 1),
        run("p2", "A", 1),
        run("p2", "B", 1, success=0, error="TimeoutError"),
    ]
    res = compare(rows, "A", "B", n_boot=100)
    assert res["n_problems"] == 1
    assert res["excluded_error_rows"] == {"A": 0, "B": 1}
    assert "excluded error rows" in format_report(res)


def test_small_true_difference_is_not_over_read_at_n24():
    """A 4-point true gain with n=24 problems is below the MDE: intervals must usually include 0."""
    rng = random.Random(7)
    hits = 0
    for trial in range(60):
        rows = []
        for i in range(24):
            base = rng.random() < 0.80
            new = base or rng.random() < 0.2
            rows += [
                run(f"p{i}", "A", 1, success=int(base)),
                run(f"p{i}", "B", 1, success=int(new)),
            ]
        e = compare(rows, "A", "B", n_boot=300, seed=trial)["metrics"]["success"]
        hits += e["ci_excludes_zero"]
    assert hits / 60 < 0.6


def test_null_false_positive_rate_is_controlled():
    rng = random.Random(11)
    fp = 0
    for trial in range(100):
        rows = []
        for i in range(70):
            p = rng.random() < 0.7
            rows += [
                run(f"p{i}", "A", 1, success=int(p)),
                run(f"p{i}", "B", 1, success=int(p if rng.random() < 0.8 else rng.random() < 0.7)),
            ]
        fp += (
            compare(rows, "A", "B", n_boot=200, seed=trial)["metrics"]["success"]["mcnemar_p"]
            < 0.05
        )
    assert fp <= 12  # nominal 5%; generous bound for 100 trials


def test_mde_values_and_monotonicity():
    assert mde_binary(100, 0.2) == pytest.approx(0.1252, abs=1e-3)
    assert mde_binary(70, 0.2) == pytest.approx(0.1497, abs=1e-3)
    assert mde_binary(70, 0.2) > mde_binary(100, 0.2) > mde_binary(200, 0.2)
    assert mde_binary(70, 0.3) > mde_binary(70, 0.1)
    assert mde_continuous(70, 75) == pytest.approx(25.1, abs=0.1)
    assert mde_continuous(100, 75) == pytest.approx(21.0, abs=0.1)
    assert mde_continuous(24, 75) > 40


def test_mde_matches_simulated_power():
    """At the MDE, a paired test should reject about 80% of the time (loose bounds)."""
    n, d_rate = 100, 0.2
    delta = mde_binary(n, d_rate)
    rng = random.Random(3)
    rejects = 0
    trials = 400
    for _ in range(trials):
        # discordant pairs: share d_rate; among them B wins with prob (1 + delta/d_rate)/2
        b = c = 0
        for _ in range(n):
            if rng.random() < d_rate:
                if rng.random() < (1 + delta / d_rate) / 2:
                    c += 1
                else:
                    b += 1
        rejects += mcnemar_exact(b, c) < 0.05
    assert 0.65 <= rejects / trials <= 0.92


def test_permutation_exact_known_values():
    assert paired_permutation_test([]) == 1.0
    assert paired_permutation_test([0.0, 0.0]) == 1.0
    assert paired_permutation_test([1.0, 1.0, 1.0]) == pytest.approx(2 / 8)
    assert paired_permutation_test([0.5, 0.5]) == pytest.approx(0.5)  # fractional diffs are fine
    assert paired_permutation_test([1.0, -1.0]) == 1.0
    assert paired_permutation_test([1.0] * 10) == pytest.approx(2 / 1024)


def test_permutation_monte_carlo_matches_exact():
    diffs = [0.5, 1.0, 1.0, 0.5, -0.5, 1.0, 0.5, 1.0, 0.5, 0.5, 1.0, -1.0]
    exact = paired_permutation_test(diffs)
    mc = paired_permutation_test(diffs, exact_limit=0, n_perm=40000, seed=5)
    assert mc == pytest.approx(exact, abs=0.01)
    assert paired_permutation_test(diffs, exact_limit=0, n_perm=500, seed=5) == (
        paired_permutation_test(diffs, exact_limit=0, n_perm=500, seed=5)
    )


def test_fractional_repeat_outcomes_do_not_feed_mcnemar():
    """A succeeds once of two repeats, B twice: per-problem means are 0.5 and 1.0."""
    rows = []
    for i in range(12):
        rows += [
            run(f"p{i}", "A", 1, success=1),
            run(f"p{i}", "A", 2, success=0),
            run(f"p{i}", "B", 1, success=1),
            run(f"p{i}", "B", 2, success=1),
        ]
    e = compare(rows, "A", "B", n_boot=300)["metrics"]["success"]
    assert e["mean_a"] == 0.5 and e["mean_b"] == 1.0 and e["diff"] == pytest.approx(0.5)
    assert "mcnemar_p" not in e
    # repeat 1 is identical in both arms; only repeat 2 differs (B wins 12 times)
    assert e["mcnemar_by_repeat"][1] == {"p": 1.0, "discordant": 0}
    assert e["mcnemar_by_repeat"][2]["discordant"] == 12
    assert e["perm_p"] == pytest.approx(2 / 4096)
    assert e["ci_excludes_zero"]


def test_single_repeat_keeps_pooled_mcnemar():
    rows = [run(f"p{i}", a, 1, success=int(a == "B" or i > 3)) for i in range(10) for a in "AB"]
    e = compare(rows, "A", "B", n_boot=100)["metrics"]["success"]
    assert e["discordant"] == 4 and e["mcnemar_p"] == pytest.approx(0.125)
    assert "mcnemar_by_repeat" not in e


def test_permutation_false_positive_rate_with_two_repeats():
    rng = random.Random(21)
    fp = 0
    for _ in range(150):
        diffs = []
        for _ in range(70):
            pa = rng.choice([0.2, 0.8])  # problem difficulty shared by both arms
            a = sum(rng.random() < pa for _ in range(2)) / 2
            b = sum(rng.random() < pa for _ in range(2)) / 2
            diffs.append(b - a)
        fp += paired_permutation_test(diffs, n_perm=1000, seed=1) < 0.05
    assert fp <= 15  # nominal 5% of 150 = 7.5


def test_mde_gives_adequate_power_for_the_permutation_test_with_repeats():
    """Problems whose arms differ are the only informative ones; repeats only add noise to the
    non-differing ones, so the MDE (one-repeat bound) must be at least as good with 2 repeats."""
    n, d_rate = 100, 0.2
    delta = mde_binary(n, d_rate)
    rng = random.Random(8)
    trials, rejects = 200, 0
    for _ in range(trials):
        diffs = []
        for _ in range(n):
            if rng.random() < d_rate:
                b_wins = rng.random() < (1 + delta / d_rate) / 2
                a_rate, b_rate = (0.0, 1.0) if b_wins else (1.0, 0.0)
            else:
                a_rate = b_rate = float(rng.random() < 0.7)
            diffs.append(b_rate - a_rate)
        rejects += paired_permutation_test(diffs, n_perm=1000, seed=3) < 0.05
    assert 0.65 <= rejects / trials <= 0.95
