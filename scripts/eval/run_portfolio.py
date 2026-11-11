"""Zero-model portfolio on the formal statements of generation-eval-v1 (matrix mode).

One Lean process per item elaborates every attempt (Recipe candidates, then the automation
portfolio, then exact?) so each tactic's independent contribution is measured; the time a
first-success run would take is the arrival time of the first accepted attempt in portfolio order
(`answered_s`), and `startup_s` is the Lean start + Mathlib import (the floor).

    uv run python scripts/eval/run_portfolio.py --out DIR [--formal FILE.jsonl] [--ids a,b]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pals_agent import automation_portfolio as ap  # noqa: E402
from pals_agent import general_recipe_lane as lane  # noqa: E402

MANIFEST = ROOT / "testdata/generation-eval-v1/manifest.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--formal", type=Path, help="jsonl {id, formal} for items without one")
    parser.add_argument("--ids")
    parser.add_argument("--no-recipes", action="store_true")
    parser.add_argument("--budget", type=float, default=150.0)
    parser.add_argument(
        "--first-success", action="store_true", help="stop at first accepted attempt"
    )
    parser.add_argument(
        "--warm", action="store_true", help="long-lived worker, staged first-success"
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    runner = lane.LeanRunner.from_workspace(
        ROOT / "lean-workspace", lake=str(Path.home() / ".elan/bin/lake")
    )
    pool = lane.load_fixture_recipes(ROOT / "testdata") + lane.load_recovered_recipes(
        ROOT / "testdata"
    )
    extra = {}
    if args.formal:
        for line in args.formal.read_text().splitlines():
            row = json.loads(line)
            if row.get("formal"):
                extra[row["id"]] = row["formal"]
    problems = json.loads(MANIFEST.read_text())["problems"]
    if args.ids:
        problems = [p for p in problems if p["id"] in args.ids.split(",")]
    worker = None
    if args.warm:
        worker = ap.WarmWorker(runner, ROOT / "scripts/eval/warm_worker.lean")
        print(f"warm worker ready after {worker.startup_s:.2f} s", flush=True)
        (args.out / "warm_startup_s.txt").write_text(f"{worker.startup_s:.3f}\n")
    with (args.out / ("portfolio_warm.jsonl" if args.warm else "portfolio.jsonl")).open("a") as fh:
        for p in problems:
            formal = p.get("fixed_lean_statement") or extra.get(p["id"])
            if not formal:
                continue
            if worker is not None:
                res = ap.solve_warm(
                    formal,
                    pool if not args.no_recipes else [],
                    worker,
                    allow_header=bool(p.get("fixed_lean_statement")),
                )
            else:
                res = ap.solve(
                    formal,
                    pool,
                    runner,
                    budget_s=args.budget,
                    use_recipes=not args.no_recipes,
                    stop_on_accept=args.first_success,
                    allow_header=bool(p.get("fixed_lean_statement")),
                )
            row = {
                "id": p["id"],
                "tier": p["tier"],
                "field": p["field"],
                "split": p["split"],
                "language": p["language"],
                "formal_source": "fixed" if p.get("fixed_lean_statement") else "formalised",
                "outcome": res.outcome,
                "route": res.route,
                "by": res.by,
                "lemma": res.lemma,
                "code": res.code,
                "startup_s": res.startup_s,
                "answered_s": res.answered_s,
                "total_s": round(res.total_s, 2),
                "model_calls": res.model_calls,
                "succeeded": [
                    a.name for a in res.attempts if a.at_s is not None and a.verdict is None
                ],
                "attempt_s": {a.name: a.at_s for a in res.attempts if a.at_s is not None},
                "failed_codes": sorted({a.verdict for a in res.attempts if a.verdict}),
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print(p["id"], res.outcome, res.route, res.by, res.answered_s, flush=True)


if __name__ == "__main__":
    main()
