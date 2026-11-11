"""Paired, problem-clustered analysis for run_stages.py output (Tier 1 / Tier 2 records.jsonl).

All statistics come from ``pals_agent.evals.analysis`` (one implementation): per-problem
differences of repeat means, a paired sign-flip permutation test (exact up to 16 non-zero problems,
seeded Monte Carlo beyond), a problem-clustered bootstrap interval, McNemar only on paired binary
cells (one test per repeat index when there are several repeats), and the minimum detectable
difference. This script adds per-arm summaries (p50/p90, stage breakdown) on top.

    analyze_stages.py RUN_DIR --base base --treat combined [--errors sketch_errors.jsonl]
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pals_agent.evals.analysis import (  # noqa: E402
    _mcnemar_entry,
    mde_binary,
    paired_bootstrap,
    paired_permutation_test,
    per_problem_means,
)


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _parse_ts(value: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(value).timestamp()


def add_normalised(
    runs: list[dict[str, Any]], attempts: list[dict[str, Any]], lean_normal_s: float
) -> None:
    """PROJECTION, not a measurement: ``wall_norm_s`` / ``answer_norm_s`` with every Lean check
    shortened to ``lean_normal_s``.

    Per run, the Lean intervals (lean_check and sketch_check) are merged where they overlap (a
    race compiles two candidates at once, which costs the clock once), and each merged interval
    longer than ``lean_normal_s`` is cut to that length. Model time and everything else stay as
    measured; this assumes the model calls would not have been slower or faster with a quiet
    machine.
    """
    by_run: dict[tuple[str, str, int], list[tuple[float, float]]] = defaultdict(list)
    for a in attempts:
        if a.get("stage") in ("lean_check", "sketch_check") and a.get("started_at"):
            key = (a["problem_id"], a["arm"], int(a.get("repeat", 1)))
            by_run[key].append((_parse_ts(a["started_at"]), _parse_ts(a["ended_at"])))
    for r in runs:
        merged: list[list[float]] = []
        for start, end in sorted(by_run.get((r["problem_id"], r["arm"], int(r["repeat"])), [])):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        cut = sum(max(0.0, end - start - lean_normal_s) for start, end in merged)
        for raw, norm in (("wall_s", "wall_norm_s"), ("answer_s", "answer_norm_s")):
            if r.get(raw) is not None:
                r[norm] = max(0.0, float(r[raw]) - cut)


def quantile(values: list[float], q: float) -> float:
    """Linear-interpolated quantile (type 7)."""
    xs = sorted(values)
    if not xs:
        return float("nan")
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def arm_summary(runs: list[dict[str, Any]], arm: str) -> None:
    """Per-arm totals, p50/p90 and the mean stage breakdown (rows are runs, not problems)."""
    rows = [r for r in runs if r["arm"] == arm and not r["error"]]
    if not rows:
        print(f"[{arm}] no rows")
        return
    n = len(rows)

    def col(key: str) -> list[float]:
        return [float(r[key]) for r in rows if r.get(key) is not None]

    line = (
        f"[{arm}] n={n} success={sum(bool(r['success']) for r in rows)}"
        f" first_attempt_ok={sum(bool(r['first_attempt_ok']) for r in rows)}"
        f" repairs_total={sum(int(r['repairs_used']) for r in rows)}"
        f" cost_total=${sum(col('cost_usd')):.3f} calls_mean={st.mean(col('model_calls')):.1f}"
    )
    print(line)
    loads = [
        (r["load_1m_start"], r["load_1m_end"]) for r in rows if r.get("load_1m_start") is not None
    ]
    if loads:
        print(
            f"    host load (1 min) at item start: mean={st.mean(a for a, _ in loads):.1f}"
            f" max={max(a for a, _ in loads):.1f};"
            f" at item end: mean={st.mean(b for _, b in loads):.1f}"
            f" max={max(b for _, b in loads):.1f}"
        )
    lean_s = sorted(
        float(x) for x in col("lean_check_median_s")
    )  # filled by main() from the attempt rows
    if lean_s:
        print(
            f"    measured Lean check per item (median of checks): p50={quantile(lean_s, 0.5):.1f}s"
        )
    for key in (
        "wall_s",
        "wall_norm_s",
        "answer_s",
        "answer_norm_s",
        "review_s",
        "explain_wait_s",
    ):
        v = col(key)
        if v:
            print(
                f"    {key}: n={len(v)} mean={st.mean(v):.1f} p50={quantile(v, 0.5):.1f}"
                f" p90={quantile(v, 0.9):.1f} max={max(v):.1f}"
            )
    stages: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        for k, ms in (r.get("stage_ms") or {}).items():
            stages[k].append(ms / 1000)
    parts = ", ".join(f"{k}={sum(v) / n:.1f}s(x{len(v)})" for k, v in sorted(stages.items()))
    print(f"    mean stage seconds per item (concurrent candidates add up): {parts}")


def report_metric(
    runs: list[dict[str, Any]], base: str, treat: str, key: str, label: str, *, binary: bool
) -> None:
    """One metric, via the shared implementation in ``pals_agent.evals.analysis``.

    Problem-clustered paired sign-flip permutation test (exact up to 16 non-zero problems) and
    bootstrap interval on the per-problem differences of repeat means; McNemar only on genuinely
    paired binary cells (``_mcnemar_entry``), never on averaged values.
    """
    a = per_problem_means(runs, base, key)
    t = per_problem_means(runs, treat, key)
    common = sorted(set(a) & set(t))
    if not common:
        print(f"{label}: no problems with both arms; nothing to compare")
        return
    diffs = [t[p] - a[p] for p in common]
    mean, lo, hi = paired_bootstrap(diffs)
    n = len(common)
    out = (
        f"{label}: n={n} base={st.mean(a[p] for p in common):.3f}"
        f" treat={st.mean(t[p] for p in common):.3f} diff={mean:+.3f}"
        f" boot95=[{lo:+.3f},{hi:+.3f}] perm_p={paired_permutation_test(diffs):.3f}"
        f" better={sum(d < 0 for d in diffs) if not binary else sum(d > 0 for d in diffs)}"
        f" worse={sum(d > 0 for d in diffs) if not binary else sum(d < 0 for d in diffs)}"
        f" median_diff={st.median(diffs):+.3f}"
    )
    if binary:
        entry = _mcnemar_entry(runs, base, treat, key, set(common))
        out += " " + json.dumps(entry, sort_keys=True)
        disc = sum(d != 0 for d in diffs) / n
        out += f" MDE(obs discordance {disc:.2f})={mde_binary(n, max(disc, 0.05)):.2f}"
        out += f" MDE(disc 0.30)={mde_binary(n, 0.30):.2f}"
    print(out)


def error_totals(
    errs: list[dict[str, Any]], base: str, treat: str, key: str
) -> tuple[dict[str, float], dict[str, float]]:
    """Per-problem sums of ``key`` for the two selected arms only (other arms are ignored)."""
    a: dict[str, float] = defaultdict(float)
    t: dict[str, float] = defaultdict(float)
    for e in errs:
        if e["arm"] == base:
            a[e["problem_id"]] += e[key]
        elif e["arm"] == treat:
            t[e["problem_id"]] += e[key]
    return a, t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--base", default="base")
    ap.add_argument("--treat", default="combined")
    ap.add_argument(
        "--lean-normal-s",
        type=float,
        default=None,
        help="projection: cut every Lean check to this many seconds (the unloaded figure)",
    )
    ap.add_argument("--arms", help="comma list for the per-arm summary (default: base,treat)")
    args = ap.parse_args()
    rows = load(args.run_dir / "records.jsonl")
    runs = [r for r in rows if r.get("schema", "").endswith("run.v1")]
    attempts = [r for r in rows if r.get("schema", "").endswith("attempt.v1")]
    print(f"runs={len(runs)} attempts={len(attempts)} errors={sum(1 for r in runs if r['error'])}")
    ok = [r for r in runs if not r["error"]]
    checks: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    for a in attempts:
        if a.get("stage") == "lean_check":
            checks[(a["problem_id"], a["arm"], int(a.get("repeat", 1)))].append(
                a["elapsed_ms"] / 1000
            )
    for r in runs:
        c = checks.get((r["problem_id"], r["arm"], int(r["repeat"])))
        if c:
            r["lean_check_median_s"] = st.median(c)
    if args.lean_normal_s is not None:
        add_normalised(runs, attempts, args.lean_normal_s)
    for arm in args.arms.split(",") if args.arms else (args.base, args.treat):
        arm_summary(runs, arm)
    for key, label in (("first_attempt_ok", "first-attempt ok"), ("success", "success")):
        report_metric(ok, args.base, args.treat, key, label, binary=True)
    for key in (
        "input_tokens",
        "output_tokens",
        "wall_s",
        "answer_s",
        "wall_norm_s",
        "answer_norm_s",
        "review_s",
        "explain_wait_s",
        "cost_usd",
        "repairs_used",
        "model_calls",
    ):
        report_metric(ok, args.base, args.treat, key, key, binary=False)
    err_path = args.run_dir / "sketch_errors.jsonl"
    if err_path.exists():
        errs = load(err_path)
        for key in ("errors", "unknown_identifier", "import_error"):
            a, t = error_totals(errs, args.base, args.treat, key)
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
