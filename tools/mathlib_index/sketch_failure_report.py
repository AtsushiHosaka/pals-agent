"""Summarize sketch-only runs of `hint_ab.py --stop-after-sketch` as Markdown tables.

Reads `<out>/<label>.jsonl` and, to classify, the local raw dumps in `<out>/raw` (diagnostic
messages stay there; the tables carry only classes, codes, counts and card ids).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pals_agent.models import Diagnostic
from tools.mathlib_index.sketch_failures import classify_check


def load(out: Path, labels: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label in labels:
        for line in (out / f"{label}.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            row["label"] = label
            rows.append(row)
    return rows


def classes_of(out: Path, row: dict[str, Any]) -> list[Any]:
    raw = json.loads(
        (out / "raw" / f"{row['label']}-{row['arm']}-{row['problem']}-1.json").read_text(
            encoding="utf-8"
        )
    )
    diagnostics = [
        Diagnostic(
            severity=d["severity"],
            message=d["message"],
            code=d.get("code"),
            line=d.get("line"),
            column=d.get("column"),
        )
        for d in raw["diagnostics"]
    ]
    return classify_check(diagnostics, raw["code"])


def report(out: Path, labels: list[str]) -> str:
    rows = [row for row in load(out, labels) if "outcome" in row]
    total = len(rows)
    lines = [f"Sketch checks: {total} (cards x runs)", ""]
    outcomes = Counter(row["outcome"] for row in rows)
    lines += ["| 結果 | 件数 | 割合 |", "|---|---:|---:|"]
    for name, count in outcomes.most_common():
        lines.append(f"| {name} | {count} | {count / total:.0%} |")
    failed = [row for row in rows if row["outcome"] == "lean_failed"]
    primary: Counter[str] = Counter()
    anywhere: Counter[str] = Counter()
    cards: dict[str, set[str]] = defaultdict(set)
    seconds: dict[str, list[float]] = defaultdict(list)
    region: Counter[str] = Counter()
    for row in failed:
        found = classes_of(out, row)
        head = found[0].cls
        primary[head] += 1
        region[found[0].region] += 1
        cards[head].add(row["problem"])
        seconds[head].append(row["elapsed_seconds"])
        for name in {item.cls for item in found}:
            anywhere[name] += 1
    lines += [
        "",
        f"Lean check failed: {len(failed)}",
        "",
        "| 主原因(最初のエラー) | 件数 | 失敗中の割合 | 全体の割合 | 該当カード数 | "
        "平均秒(Draft+Sketch+Lean) | 他のエラーにも出た件数 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, count in primary.most_common():
        lines.append(
            f"| {name} | {count} | {count / len(failed):.0%} | {count / total:.0%} | "
            f"{len(cards[name])} | {mean(seconds[name]):.0f} | {anywhere[name]} |"
        )
    lines += ["", "最初のエラーの位置: " + ", ".join(f"{k}={v}" for k, v in region.most_common())]
    per_card: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        per_card[row["problem"]].append(row["outcome"] == "passed")
    lines += ["", "カードごとの通過 (run順): "]
    for card, flags in sorted(per_card.items()):
        lines.append(f"- {card}: {''.join('o' if f else 'x' for f in flags)}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--labels", required=True, help="Comma-separated run labels")
    args = parser.parse_args()
    print(report(args.out, args.labels.split(",")))


if __name__ == "__main__":
    main()
