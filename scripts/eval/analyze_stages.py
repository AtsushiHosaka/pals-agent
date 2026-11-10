"""Paired, problem-clustered analysis for run_stages.py output (Tier 1 / Tier 2 records.jsonl).

Unit of analysis is the problem. Repeats of one (problem, arm) are averaged first, so repeats are
never counted as independent problems. Binary outcomes: exact McNemar on single-repeat pairs plus a
paired difference with a bootstrap interval; continuous outcomes: mean paired difference with a
percentile bootstrap interval and a sign-flip permutation p. Also prints the minimum detectable
difference (80% power, two-sided 5%) for the observed number of pairs.

    analyze_stages.py RUN_DIR --base base --treat combined [--errors sketch_errors.jsonl]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

B = 10000


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def per_problem(runs: list[dict[str, Any]], arm: str, key: str) -> dict[str, float]:
    acc: dict[str, list[float]] = defaultdict(list)
    for r in runs:
        if r["arm"] == arm and r.get(key) is not None:
            acc[r["problem_id"]].append(float(r[key]))
    return {k: sum(v) / len(v) for k, v in acc.items()}


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * p)


def boot_ci(d: list[float], seed: int = 1) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(d)
    means = sorted(sum(rng.choice(d) for _ in range(n)) / n for _ in range(B))
    return means[int(0.025 * B)], means[int(0.975 * B) - 1]


def sign_flip_p(d: list[float], seed: int = 2) -> float:
    rng = random.Random(seed)
    obs = abs(sum(d))
    hits = sum(
        abs(sum(x if rng.random() < 0.5 else -x for x in d)) >= obs - 1e-12 for _ in range(B)
    )
    return (hits + 1) / (B + 1)


def mdd_binary(n: int, disc: float, sims: int = 4000, seed: int = 3) -> float:
    """Smallest true difference (base-only minus treat-only share of pairs) detected with 80%
    power by exact McNemar, given the share ``disc`` of discordant pairs."""
    rng = random.Random(seed)
    for step in range(1, 100):
        delta = step / 100
        if delta > disc:
            return float("nan")
        pb, pc = (disc + delta) / 2, (disc - delta) / 2
        hit = 0
        for _ in range(sims):
            b = c = 0
            for _ in range(n):
                u = rng.random()
                if u < pb:
                    b += 1
                elif u < pb + pc:
                    c += 1
            hit += mcnemar_exact(b, c) < 0.05
        if hit / sims >= 0.8:
            return delta
    return float("nan")


def report_binary(name: str, a: dict[str, float], t: dict[str, float]) -> None:
    ids = sorted(set(a) & set(t))
    d = [t[i] - a[i] for i in ids]
    n = len(ids)
    single = all(x in (0.0, 1.0) for x in list(a.values()) + list(t.values()))
    only_b = sum(a[i] > t[i] for i in ids)
    only_t = sum(t[i] > a[i] for i in ids)
    lo, hi = boot_ci(d)
    out = (
        f"{name}: n={n} base={sum(a[i] for i in ids):.1f} treat={sum(t[i] for i in ids):.1f}"
        f" ({sum(a[i] for i in ids) / n:.3f} -> {sum(t[i] for i in ids) / n:.3f})"
        f" diff={sum(d) / n:+.3f} boot95=[{lo:+.3f},{hi:+.3f}] base-only={only_b} treat-only={only_t}"  # noqa: E501
    )
    if single:
        out += f" mcnemar_exact_p={mcnemar_exact(only_b, only_t):.3f}"
        disc = (only_b + only_t) / n
        out += f" MDD(obs discordance {disc:.2f})={mdd_binary(n, max(disc, 0.05)):.2f}"
        out += f" MDD(disc 0.30)={mdd_binary(n, 0.30):.2f}"
    else:
        out += f" signflip_p={sign_flip_p(d):.3f}"
    print(out)


def report_cont(name: str, a: dict[str, float], t: dict[str, float]) -> None:
    ids = sorted(set(a) & set(t))
    d = [t[i] - a[i] for i in ids]
    lo, hi = boot_ci(d)
    print(
        f"{name}: n={len(ids)} base_mean={st.mean(a[i] for i in ids):.2f}"
        f" treat_mean={st.mean(t[i] for i in ids):.2f} diff={st.mean(d):+.2f}"
        f" boot95=[{lo:+.2f},{hi:+.2f}] signflip_p={sign_flip_p(d):.3f}"
        f" median_diff={st.median(d):+.2f}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--base", default="base")
    ap.add_argument("--treat", default="combined")
    args = ap.parse_args()
    rows = load(args.run_dir / "records.jsonl")
    runs = [r for r in rows if r.get("schema", "").endswith("run.v1")]
    attempts = [r for r in rows if r.get("schema", "").endswith("attempt.v1")]
    print(f"runs={len(runs)} attempts={len(attempts)} errors={sum(1 for r in runs if r['error'])}")
    ok = [r for r in runs if not r["error"]]
    for key, label in (("first_attempt_ok", "first-attempt ok"), ("success", "success")):
        report_binary(
            label,
            per_problem(ok, args.base, key),
            per_problem(ok, args.treat, key),
        )
    for key in (
        "input_tokens",
        "output_tokens",
        "wall_s",
        "cost_usd",
        "repairs_used",
        "model_calls",
    ):
        report_cont(key, per_problem(ok, args.base, key), per_problem(ok, args.treat, key))
    err_path = args.run_dir / "sketch_errors.jsonl"
    if err_path.exists():
        errs = load(err_path)
        for key in ("errors", "unknown_identifier", "import_error"):
            a = defaultdict(float)
            t = defaultdict(float)
            for e in errs:
                (a if e["arm"] == args.base else t)[e["problem_id"]] += e[key]
            ids = sorted(set(a) & set(t))
            print(
                f"sketch {key}: total base={sum(a[i] for i in ids):.0f} treat={sum(t[i] for i in ids):.0f}"  # noqa: E501
                f" sketches with >=1: base={sum(a[i] > 0 for i in ids)} treat={sum(t[i] > 0 for i in ids)}"  # noqa: E501
                f" of {len(ids)}"
            )
        hdr = defaultdict(lambda: defaultdict(int))
        for e in errs:
            hdr[e["arm"]][e["header"]] += 1
        for arm, hh in hdr.items():
            print("headers", arm, dict(hh))


if __name__ == "__main__":
    main()
