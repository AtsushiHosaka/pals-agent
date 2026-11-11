"""Single configs and COMPUTED two-config races from run_prove_matrix.py's matrix.jsonl.

A candidate of a race runs at the same time as its rival, so it finishes at model_s + verify_s
(the verifier is a separate resident process). The race's time is the earliest *verified* finish;
if no candidate verifies, the first attempt failed (a repair would follow: not measured here).
Race cost is both candidates' cost. This is a projection from independent single runs, not a
measured race: it assumes two concurrent calls are as fast as two sequential ones.

    analyze_prove_matrix.py RUN_DIR
"""

from __future__ import annotations

import itertools
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path


def q(values: list[float], p: float) -> float:
    xs = sorted(values)
    if not xs:
        return float("nan")
    pos = (len(xs) - 1) * p
    lo, hi = int(pos), min(int(pos) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - int(pos))


def summarize(label: str, times: list[float | None], usd: list[float], n: int) -> None:
    ok = [t for t in times if t is not None]
    # p50/p90 over all problems with a failure counted as infinitely slow
    inf = sorted(t if t is not None else float("inf") for t in times)

    def over_all(p: float) -> str:
        v = q(inf, p)
        return "fail" if v == float("inf") else f"{v:.1f}"

    print(
        f"{label:34s} first-attempt ok {len(ok):2d}/{n}  "
        f"p50(all) {over_all(0.5):>5s}  p90(all) {over_all(0.9):>5s}  "
        f"p50(ok) {q(ok, 0.5):5.1f}  p90(ok) {q(ok, 0.9):5.1f}  "
        f"cost ${sum(usd):.3f}"
    )


def main() -> None:
    run = Path(sys.argv[1])
    rows = [json.loads(x) for x in (run / "matrix.jsonl").read_text().splitlines() if x.strip()]
    by: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        by[r["config"]][r["problem_id"]] = r
    configs = sorted(by)
    problems = sorted(set.intersection(*(set(v) for v in by.values())))
    n = len(problems)
    print(f"problems with every config: {n}; configs: {configs}")
    loads = [r["load_1m"] for r in rows]
    print(f"host load (1 min) during the run: mean {st.mean(loads):.1f} max {max(loads):.1f}")
    print("\n== single configs (model call + one resident verification) ==")
    for c in configs:
        ts = [
            (by[c][p]["model_s"] + by[c][p]["verify_s"]) if by[c][p]["verified"] else None
            for p in problems
        ]
        summarize(c, ts, [by[c][p]["usd"] for p in problems], n)
    print("\n   model-call seconds p50/p90, verify seconds p50, tokens (in/cached/out/reasoning) mean")
    for c in configs:
        rs = [by[c][p] for p in problems]
        print(
            f"   {c:20s} model {q([r['model_s'] for r in rs], .5):5.1f}/"
            f"{q([r['model_s'] for r in rs], .9):5.1f}  verify p50 "
            f"{q([r['verify_s'] for r in rs if r['verify_s']], .5):4.1f}  "
            f"in {st.mean(r['input_tokens'] for r in rs):.0f} "
            f"cached {st.mean(r['cached_input_tokens'] for r in rs):.0f} "
            f"out {st.mean(r['output_tokens'] for r in rs):.0f} "
            f"reasoning {st.mean(r['reasoning_output_tokens'] for r in rs):.0f}"
        )
    print("\n== computed two-config races (earliest verified finish) ==")
    for a, b in itertools.combinations(configs, 2):
        ts: list[float | None] = []
        for p in problems:
            finishes = [
                by[c][p]["model_s"] + by[c][p]["verify_s"]
                for c in (a, b)
                if by[c][p]["verified"]
            ]
            ts.append(min(finishes) if finishes else None)
        summarize(
            f"{a}+{b}", ts, [by[a][p]["usd"] + by[b][p]["usd"] for p in problems], n
        )
    pre = run / "prefix.json"
    if pre.exists():
        print("\n== prompt prefix shared across problems (chars) ==")
        for row in json.loads(pre.read_text()):
            print("  ", row)


if __name__ == "__main__":
    main()
