#!/usr/bin/env python3
"""Check that general cards cover every case of a topic by numeric substitution.

Each case in case-coverage/<topic>-cases.json is an evaluation problem kept apart from the cards.
Its proof instantiates the listed cards, so a compile failure means the card does not cover the case.
No model is used, and this says nothing about whether reuse finds the card for a numeric question.
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent


def load_cards() -> dict[str, dict]:
    cards: dict[str, dict] = {}
    for path in sorted((ROOT / "cards").glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        for card in yaml.safe_load(path.read_text()):
            cards.setdefault(card["id"], {**card, "domain": path.stem})
    return cards


def build_source(table: dict, cards: dict[str, dict]) -> str:
    used = sorted({name for case in table["cases"] for name in case["cards"]})
    parts = ["import Mathlib", "", "set_option linter.all false", ""]
    for name in used:
        card = cards[name]
        target = " ".join(card["target"].split())
        parts += [f"theorem {name} : {target} := {card['proof'].strip()}", ""]
    for case in table["cases"]:
        body = "\n".join(f"  {line}" for line in case["proof"].split("\n"))
        parts += [f"-- case {case['id']}", f"example : {case['statement']} := by", body, ""]
    return "\n".join(parts)


def failures(source: str, output: str) -> list[str]:
    lines = source.split("\n")
    marks = [(index + 1, line[8:]) for index, line in enumerate(lines) if line.startswith("-- case ")]
    starts = [mark[0] for mark in marks]
    failed = []
    for match in re.finditer(r":(\d+):\d+: error", output):
        position = bisect.bisect(starts, int(match.group(1))) - 1
        failed.append(marks[position][1] if position >= 0 else "cards")
    return sorted(set(failed))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("topic")
    args = parser.parse_args()
    table = json.loads((ROOT / "case-coverage" / f"{args.topic}-cases.json").read_text())
    cards = load_cards()
    missing = sorted({n for case in table["cases"] for n in case["cards"]} - cards.keys())
    if missing:
        raise SystemExit(f"unknown cards: {missing}")
    added = set(table["added_cards"])
    source = build_source(table, cards)
    workspace = os.environ["PALS_LEAN_WORKSPACE"]
    with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False) as handle:
        handle.write(source)
    done = subprocess.run(["lake", "env", "lean", handle.name], cwd=workspace, capture_output=True, text=True)
    os.unlink(handle.name)
    failed = failures(source, done.stdout + done.stderr)
    by_question = Counter(case["question"] for case in table["cases"])
    needs_added = [case for case in table["cases"] if added & set(case["cards"])]
    print(json.dumps({
        "questions": len(by_question),
        "cases": len(table["cases"]),
        "covered_by_existing_cards": len(table["cases"]) - len(needs_added),
        "needing_added_cards": len(needs_added),
        "added_cards": len(added),
        "added_cards_used": len(added & {n for case in table["cases"] for n in case["cards"]}),
        "existing_cards_used": len({n for case in table["cases"] for n in case["cards"]} - added),
        "by_question": dict(by_question),
        "compile_returncode": done.returncode,
        "failed_cases": failed,
    }, ensure_ascii=False, indent=1))
    return 0 if done.returncode == 0 and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
