import random

import pytest

from pals_agent.evals.analysis import (
    compare,
    format_report,
    mcnemar_exact,
    mde_binary,
    mde_continuous,
    paired_bootstrap,
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
    assert res["metrics"]["success"]["mcnemar_p"] == 1.0


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
    assert s["ci_excludes_zero"] and s["mcnemar_p"] < 0.001
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
