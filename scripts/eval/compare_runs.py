"""Paired comparison of two arms from one or more records.jsonl files.

Primary result per metric: difference of per-problem repeat means with a problem-clustered
sign-flip permutation p-value and bootstrap interval. McNemar appears only for one repeat per
problem, or separately per repeat index.

python3 scripts/eval/compare_runs.py RUN_DIR/records.jsonl --a base --b new [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pals_agent.evals.analysis import compare, format_report  # noqa: E402
from pals_agent.evals.records import read_rows  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("records", nargs="+", type=Path)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = [r for p in args.records for r in read_rows(p)]
    result = compare(rows, args.a, args.b)
    print(json.dumps(result, indent=1) if args.json else format_report(result))


if __name__ == "__main__":
    main()
