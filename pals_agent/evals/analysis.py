"""Paired comparison of two arms on identical problems (standard library only).

Unit of analysis is the PROBLEM: repeats are averaged inside a problem first, because repeats of one
problem are not independent samples. The primary analysis, for every metric (binary ones too), is
the per-problem difference of repeat means (B - A, so values like 0.5 are fine), tested with a
problem-clustered paired sign-flip permutation test and a problem-clustered paired bootstrap
interval. McNemar's exact test needs paired BINARY observations, so it is reported only when every
problem has a single repeat per arm, or per repeat index (r-th repeat of A against r-th repeat of
B), never on averaged outcomes. Nothing here claims an effect when the interval contains 0.
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


def _cells(rows: Iterable[dict[str, Any]], arm: str, metric: str) -> dict[tuple[str, int], float]:
    """(problem, repeat index) -> value for the non-error rows of one arm."""
    out: dict[tuple[str, int], float] = {}
    for r in rows:
        if (
            r.get("schema", "").endswith("run.v1")
            and r["arm"] == arm
            and r.get(metric) is not None
            and not r.get("error")
        ):
            out[(r["problem_id"], int(r.get("repeat", 1)))] = float(r[metric])
    return out


def per_problem_means(rows: Iterable[dict[str, Any]], arm: str, metric: str) -> dict[str, float]:
    """Per-problem mean over ALL non-error repeats of one arm. For a comparison of two arms use
    ``paired_problem_means``: averaging each arm separately lets A=[1, 0] meet B=[1, error] as a
    difference of +0.5 although the only complete pair agrees."""
    acc: dict[str, list[float]] = defaultdict(list)
    for (problem, _repeat), value in _cells(rows, arm, metric).items():
        acc[problem].append(value)
    return {k: float(fmean(v)) for k, v in acc.items()}


def paired_problem_means(
    rows: list[dict[str, Any]], arm_a: str, arm_b: str, metric: str
) -> tuple[dict[str, float], dict[str, float], dict[str, Any]]:
    """Per-problem means over the repeat indices present in BOTH arms (non-error, metric set).

    Problems with no common repeat are dropped. Returns the two mean maps and a report of what
    was left out: unpaired repeats per arm (one arm has the cell, the other has none or an error)
    and the problems dropped because no repeat was complete in both arms."""
    ca, cb = _cells(rows, arm_a, metric), _cells(rows, arm_b, metric)
    common = set(ca) & set(cb)
    a: dict[str, list[float]] = defaultdict(list)
    b: dict[str, list[float]] = defaultdict(list)
    for key in common:
        a[key[0]].append(ca[key])
        b[key[0]].append(cb[key])
    seen = {k[0] for k in ca} | {k[0] for k in cb}
    report = {
        "excluded_pairs": {arm_a: len(set(ca) - common), arm_b: len(set(cb) - common)},
        "dropped_problems": sorted(seen - set(a)),
    }
    return (
        {k: float(fmean(v)) for k, v in a.items()},
        {k: float(fmean(v)) for k, v in b.items()},
        report,
    )


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact p-value for discordant counts b (A only) and c (B only)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return float(min(1.0, 2 * p))


def paired_permutation_test(
    diffs: list[float], *, n_perm: int = 20000, seed: int = 20261110, exact_limit: int = 16
) -> float:
    """Two-sided paired sign-flip test of H0: mean per-problem difference = 0.

    Problems are the exchangeable units; zero differences carry no information and are dropped.
    Exact enumeration of all 2^k sign patterns up to ``exact_limit`` non-zero problems, a seeded
    Monte Carlo (with the +1 correction, so p is never 0) beyond that."""
    nz = [d for d in diffs if d != 0]
    if not nz:
        return 1.0
    k = len(nz)
    observed = abs(sum(nz))
    eps = 1e-12 * max(1.0, observed)
    if k <= exact_limit:
        hits = 0
        for mask in range(1 << k):
            total = sum(d if (mask >> i) & 1 else -d for i, d in enumerate(nz))
            hits += abs(total) >= observed - eps
        return hits / (1 << k)
    rng = random.Random(seed)
    hits = 0
    for _ in range(n_perm):
        total = sum(d if rng.random() < 0.5 else -d for d in nz)
        hits += abs(total) >= observed - eps
    return (hits + 1) / (n_perm + 1)


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


def _binary_cells(
    rows: Iterable[dict[str, Any]], arm: str, metric: str, problems: set[str]
) -> dict[tuple[str, int], int]:
    cells: dict[tuple[str, int], int] = {}
    for r in rows:
        if (
            r.get("schema", "").endswith("run.v1")
            and r["arm"] == arm
            and r["problem_id"] in problems
            and r.get(metric) is not None
            and not r.get("error")
        ):
            cells[(r["problem_id"], int(r.get("repeat", 1)))] = int(bool(r[metric]))
    return cells


def _mcnemar_entry(
    rows: list[dict[str, Any]], arm_a: str, arm_b: str, metric: str, problems: set[str]
) -> dict[str, Any]:
    """McNemar on genuinely paired binary outcomes: (problem, repeat r) of A vs the same of B.

    One repeat everywhere -> a single test over problems (``mcnemar_p``). Several repeats -> one
    test per repeat index (``mcnemar_by_repeat``); the repeats are not pooled, because outcomes of
    one problem are not independent. The permutation test above remains the primary result."""
    a = _binary_cells(rows, arm_a, metric, problems)
    b = _binary_cells(rows, arm_b, metric, problems)
    by_repeat: dict[int, list[int]] = {}
    for key in set(a) & set(b):
        counts = by_repeat.setdefault(key[1], [0, 0])
        counts[0] += a[key] > b[key]  # only A succeeded
        counts[1] += b[key] > a[key]  # only B succeeded
    if len(by_repeat) == 1:
        ((only_a, only_b),) = by_repeat.values()
        return {
            "mcnemar_p": mcnemar_exact(only_a, only_b),
            "discordant": only_a + only_b,
        }
    return {
        "mcnemar_by_repeat": {
            r: {"p": mcnemar_exact(c[0], c[1]), "discordant": c[0] + c[1]}
            for r, c in sorted(by_repeat.items())
        }
    }


def compare(
    rows: list[dict[str, Any]], arm_a: str, arm_b: str, *, n_boot: int = 10000, seed: int = 20261110
) -> dict[str, Any]:
    """Differences are B - A, over repeat indices complete in BOTH arms (see
    ``paired_problem_means``); ``pairing`` reports what each metric left out."""
    out: dict[str, Any] = {"arm_a": arm_a, "arm_b": arm_b, "metrics": {}, "pairing": {}}
    shared: set[str] | None = None
    means: dict[str, tuple[dict[str, float], dict[str, float]]] = {}
    for m in METRICS:
        a, b, report = paired_problem_means(rows, arm_a, arm_b, m)
        means[m] = (a, b)
        out["pairing"][m] = report
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
        a, b = means[m]
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
        entry["perm_p"] = paired_permutation_test(diffs, seed=seed)
        if m in BINARY:
            entry.update(_mcnemar_entry(rows, arm_a, arm_b, m, set(common)))
        out["metrics"][m] = entry
    return out


def mde_binary(n: int, discordant_rate: float, *, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest true difference in mean success rate detectable at ``n`` problems.

    ``discordant_rate`` is the share of problems whose arms differ. For a single repeat the
    per-problem difference is in {-1, 0, 1}, so Var(d) ~ discordant_rate and
    SE(mean d) ~ sqrt(discordant_rate / n). With repeats the per-problem difference is a mean of
    repeat differences and has less variance, so this figure is a conservative bound for the
    permutation/bootstrap analysis (it is the one-repeat McNemar-equivalent MDE)."""
    z = NormalDist().inv_cdf
    return (z(1 - alpha / 2) + z(power)) * math.sqrt(discordant_rate / n)


def mde_continuous(n: int, sd_diff: float, *, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest true mean paired difference detectable, given the SD of per-problem differences
    (differences of repeat means, the quantity the permutation test is about)."""
    z = NormalDist().inv_cdf
    return (z(1 - alpha / 2) + z(power)) * sd_diff / math.sqrt(n)


def format_report(result: dict[str, Any]) -> str:
    lines = [
        f"A={result['arm_a']}  B={result['arm_b']}  problems={result['n_problems']}"
        "  (diff = B - A)",
        "metric | mean A | mean B | diff [95% CI] | better/worse | p(perm) | McNemar",
        "---|---|---|---|---|---|---",
    ]
    for m, e in result["metrics"].items():
        verdict = "" if e["ci_excludes_zero"] else " (no effect shown)"
        if "mcnemar_p" in e:
            mc = f"{e['mcnemar_p']:.3f}"
        elif "mcnemar_by_repeat" in e:
            mc = " ".join(f"r{r}:{v['p']:.3f}" for r, v in e["mcnemar_by_repeat"].items())
        else:
            mc = "-"
        lines.append(
            f"{m} | {e['mean_a']:.3f} | {e['mean_b']:.3f} | {e['diff']:+.3f} "
            f"[{e['ci95'][0]:+.3f}, {e['ci95'][1]:+.3f}]{verdict} | "
            f"{e['improved']}/{e['worsened']} | {e['perm_p']:.3f} | {mc}"
        )
    pairing = result.get("pairing", {})
    unpaired = {
        arm: max((r["excluded_pairs"].get(arm, 0) for r in pairing.values()), default=0)
        for arm in (result["arm_a"], result["arm_b"])
    }
    dropped = sorted({p for r in pairing.values() for p in r["dropped_problems"]})
    if any(unpaired.values()) or dropped:
        lines.append(
            f"unpaired repeats left out (max over metrics): {unpaired}; "
            f"problems dropped (no complete repeat in both arms): {dropped}"
        )
    if any(result.get("excluded_error_rows", {}).values()):
        lines.append(
            f"excluded error rows (not counted as failures): {result['excluded_error_rows']}"
        )
    return "\n".join(lines)
