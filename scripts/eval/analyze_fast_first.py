"""Tables from ``run_hetero_api_sim.py`` records: off vs fast-first runs of the same problems.

    analyze_fast_first.py RUN_DIR [RUN_DIR ...]      (each holds records.jsonl)

Per run: problems, verified, first-attempt success, share within 10 s and 30 s (to verified, and
to the shown answer), p50/p90, usd per problem, the fast lane's outcomes and the load average
(start/end).  Then, for the problems that did not fit 10 s, where the time went.  Statements are
never printed.  Seconds are wall clock on this machine with the resident Lean standing in for the
API's compile plus a fixed API round trip (see run_hetero_api_sim.py).
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:.1f}"


def main() -> None:
    runs = {Path(p).name: [json.loads(x) for x in (Path(p) / "records.jsonl").read_text().splitlines() if x.strip()] for p in sys.argv[1:]}
    print("| 実行 | 題数 | 検証済み | 初回成功 | ≤10 s | ≤30 s | 回答まで ≤10 s | 検証 p50/p90 | 回答 p50/p90 | $/題 | 高速経路の結果 | 負荷(開始平均) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name, rows in runs.items():
        n = len(rows)
        ver = [r for r in rows if r["verified"]]
        wall = [r["wall_s"] for r in ver]
        ans = [r["answer_s"] for r in ver]
        fast = Counter(
            e["reason"] for r in rows for e in r.get("fast_first", {}).get("events", [])[:1]
        )
        print(
            f"| {name} | {n} | {len(ver)} | {sum(r['first_attempt_ok'] for r in rows)} "
            f"| {sum(w <= 10 for w in wall)} | {sum(w <= 30 for w in wall)} "
            f"| {sum(a <= 10 for a in ans)} | {fmt(pct(wall, .5))}/{fmt(pct(wall, .9))} "
            f"| {fmt(pct(ans, .5))}/{fmt(pct(ans, .9))} "
            f"| {sum(r['usd'] for r in rows) / n:.4f} | {dict(fast) or '-'} "
            f"| {statistics.mean(r['load_start'] for r in rows):.1f} |"
        )
    print("\n10 秒に収まらなかった題の内訳(検証までの秒。高速=高速経路が使った秒、"
          "検証=API 往復+検証器、通常=それ以外)\n")
    print("| 実行 | 題 | 検証 | 検証までの秒 | 高速経路の理由 | 高速 | 検証(全送信) | 通常(残り) | 送信数 | 負荷 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for name, rows in runs.items():
        for r in rows:
            if r["verified"] and r["wall_s"] <= 10:
                continue
            ev = (r.get("fast_first", {}).get("events") or [{}])[0]
            fast_s = ev.get("seconds", {}).get("total", 0.0)
            ver_s = sum(s["verify_s"] + r["api_overhead_s"] for s in r["submits_detail"])
            rest = r["wall_s"] - fast_s - ver_s
            print(
                f"| {name} | {r['problem_id']} | {'○' if r['verified'] else '×'} | {r['wall_s']:.1f} "
                f"| {ev.get('reason', '-')} | {fast_s:.1f} | {ver_s:.1f} | {rest:.1f} "
                f"| {r['submits']} | {r['load_start']:.0f} |"
            )


if __name__ == "__main__":
    main()
