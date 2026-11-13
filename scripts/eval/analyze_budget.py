"""Time budget (median / p90) of the problems that passed on the first attempt.

    analyze_budget.py NAME=RUN_DIR [NAME=RUN_DIR ...]

From ``run_hetero_api_sim.py`` records: per stage of the first attempt, seconds from the question
to the shown answer.  Stages the driver does not run (OpenMath structuring, retrieval, queue and
poll waits, the explanation output review) are listed as not measured, never filled in.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def pct(v: list[float], q: float) -> float:
    s = sorted(v)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def stage(rows: list[dict], name: str, pick) -> str:
    v = [x for x in (pick(r) for r in rows) if x is not None]
    return f"{pct(v, .5):.1f} / {pct(v, .9):.1f}" if v else "-"


def first(r: dict, step: str) -> float | None:
    v = [s["duration_ms"] / 1000 for s in r["steps"]
         if s.get("event") == "pipeline_step" and s.get("step") == step and s.get("attempt") == 1]
    return max(v) if v else None  # parallel candidates: the slower one bounds the stage


def main() -> None:
    runs = {}
    for arg in sys.argv[1:]:
        name, _, path = arg.partition("=")
        rows = [json.loads(x) for x in (Path(path) / "records.jsonl").read_text().splitlines() if x.strip()]
        runs[name] = [r for r in rows if r["first_attempt_ok"]]
    print("| 段(秒、中央値 / p90) | " + " | ".join(f"{n}(n={len(r)})" for n, r in runs.items()) + " |")
    print("|---|" + "---|" * len(runs))
    picks = [
        ("Draft(初回)", lambda r: first(r, "draft")),
        ("Sketch(初回)", lambda r: first(r, "sketch")),
        ("Prove(初回、並列候補は遅い方)", lambda r: first(r, "prove")),
        ("検証(API 往復 1.1 固定 + 検証器)", lambda r: r["api_overhead_s"] + r["submits_detail"][0]["verify_s"]),
        ("意味審査(検証後の待ち)", lambda r: r["answer"].get("review_s")),
        ("解説(検証後の待ち)", lambda r: r["answer"].get("explain_wait_s")),
        ("検証済みまで(wall)", lambda r: r["wall_s"]),
        ("表示まで(answer、解説・審査まで)", lambda r: r["answer_s"]),
        ("負荷平均(開始)", lambda r: r["load_start"]),
    ]
    for label, pick in picks:
        print(f"| {label} | " + " | ".join(stage(r, label, pick) for r in runs.values()) + " |")
    print("\n測っていない段: OpenMath 化、検索(Draft の検索)、worker・API のキュー待ちと poll、"
          "解説の出力レビュー(解説の後の 2 本目の呼び出し)、トークン精算。")


if __name__ == "__main__":
    main()
