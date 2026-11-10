"""Paired comparison of two arms on identical problems (standard library only).

Unit of analysis is the PROBLEM: repeats are averaged inside a problem first, because repeats of one
problem are not independent samples. Binary metrics get an exact McNemar test on the problems whose
repeat-mean differs between arms (sign of the difference); every metric gets a
problem-clustered paired bootstrap interval. Nothing here claims an effect when the interval
contains 0.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Iterable
from statistics import NormalDist, fmean
from typing import Any

BINARY = ("success", "first_attempt_ok")
CONTINUOUS = ("repairs_used", "wall_s", "cost_usd")
METRICS = BINARY + CONTINUOUS


def per_problem_means(rows: Iterable[dict[str, Any]], arm: str, metric: str) -> dict[str, float]:
    acc: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if (
            r.get("schema", "").endswith("run.v1")
            and r["arm"] == arm
            and r.get(metric) is not None
            and not r.get("error")
        ):
            acc[r["problem_id"]].append(float(r[metric]))
    return {k: float(fmean(v)) for k, v in acc.items()}


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact p-value for discordant counts b (A only) and c (B only)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return float(min(1.0, 2 * p))


def paired_bootstrap(
    diffs: list[float], *, n_boot: int = 10000, seed: int = 20261110, level: float = 0.95
) -> tuple[float, float, float]:
    """Mean of per-problem differences and a percentile interval over resampled problems."""
    if not diffs:
        raise ValueError("no paired problems")
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(fmean(rng.choices(diffs, k=n)) for _ in range(n_boot))
    lo = means[int((1 - level) / 2 * n_boot)]
    hi = means[min(n_boot - 1, int((1 + level) / 2 * n_boot))]
    return fmean(diffs), lo, hi


def compare(
    rows: list[dict[str, Any]], arm_a: str, arm_b: str, *, n_boot: int = 10000, seed: int = 20261110
) -> dict[str, Any]:
    """Differences are B - A. Only problems present in BOTH arms are used."""
    out: dict[str, Any] = {"arm_a": arm_a, "arm_b": arm_b, "metrics": {}}
    shared: set[str] | None = None
    for m in METRICS:
        a, b = per_problem_means(rows, arm_a, m), per_problem_means(rows, arm_b, m)
        found = set(a) & set(b)
        shared = found if shared is None else shared & found
    out["n_problems"] = len(shared or ())
    # Rows with `error` set (verifier crash, API failure) are infrastructure noise, not a verdict on
    # the arm: they are excluded here and counted so nobody reads them as proof failures.
    out["excluded_error_rows"] = {
        arm: sum(1 for r in rows if r.get("arm") == arm and r.get("error"))
        for arm in (arm_a, arm_b)
    }
    for m in METRICS:
        a, b = per_problem_means(rows, arm_a, m), per_problem_means(rows, arm_b, m)
        common = sorted(set(a) & set(b))
        if not common:
            continue
        diffs = [b[p] - a[p] for p in common]
        mean, lo, hi = paired_bootstrap(diffs, n_boot=n_boot, seed=seed)
        entry: dict[str, Any] = {
            "n": len(common),
            "mean_a": fmean(a[p] for p in common),
            "mean_b": fmean(b[p] for p in common),
            "diff": mean,
            "ci95": [lo, hi],
            "ci_excludes_zero": lo > 0 or hi < 0,
            "improved": sum(d > 0 for d in diffs),
            "worsened": sum(d < 0 for d in diffs),
        }
        if m in BINARY:
            only_b = sum(d > 0 for d in diffs)
            only_a = sum(d < 0 for d in diffs)
            entry["mcnemar_p"] = mcnemar_exact(only_a, only_b)
            entry["discordant"] = only_a + only_b
        out["metrics"][m] = entry
    return out


def mde_binary(n: int, discordant_rate: float, *, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest true difference in success proportion detectable by a paired test.

    Normal approximation to McNemar: SE(d) ~ sqrt(discordant_rate / n)."""
    z = NormalDist().inv_cdf
    return (z(1 - alpha / 2) + z(power)) * math.sqrt(discordant_rate / n)


def mde_continuous(n: int, sd_diff: float, *, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest true mean paired difference detectable, given the SD of per-problem differences."""
    z = NormalDist().inv_cdf
    return (z(1 - alpha / 2) + z(power)) * sd_diff / math.sqrt(n)


def format_report(result: dict[str, Any]) -> str:
    lines = [
        f"A={result['arm_a']}  B={result['arm_b']}  problems={result['n_problems']}"
        "  (diff = B - A)",
        "metric | mean A | mean B | diff [95% CI] | better/worse | p(McNemar)",
        "---|---|---|---|---|---",
    ]
    for m, e in result["metrics"].items():
        verdict = "" if e["ci_excludes_zero"] else " (no effect shown)"
        p = f"{e['mcnemar_p']:.3f}" if "mcnemar_p" in e else "-"
        lines.append(
            f"{m} | {e['mean_a']:.3f} | {e['mean_b']:.3f} | {e['diff']:+.3f} "
            f"[{e['ci95'][0]:+.3f}, {e['ci95'][1]:+.3f}]{verdict} | "
            f"{e['improved']}/{e['worsened']} | {p}"
        )
    if any(result.get("excluded_error_rows", {}).values()):
        lines.append(
            f"excluded error rows (not counted as failures): {result['excluded_error_rows']}"
        )
    return "\n".join(lines)
