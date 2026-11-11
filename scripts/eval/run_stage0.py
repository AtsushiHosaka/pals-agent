"""End-to-end stage 0 on generation-eval-v1 (all 100 items), gate on, one warm Lean worker.

Items with a `fixed_lean_statement` use it as the given formal statement; the others go through
two formalisations and the fidelity gate.  Records per item: outcome, reason, closer, seconds,
gate fields, and the explanation text for manual review.  Prints the machine load.

    uv run python scripts/eval/run_stage0.py --out DIR --env-file ENVFILE
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/eval"))

from pals_agent import automation_portfolio as ap  # noqa: E402
from pals_agent import fidelity_gate as gate  # noqa: E402
from pals_agent import general_recipe_lane as lane  # noqa: E402
from pals_agent import stage0  # noqa: E402


def main() -> None:
    from formalise import load_key  # noqa: PLC0415

    from pals_agent.evals.runner import estimate_usd  # noqa: PLC0415
    from pals_agent.usage import usage_scope  # noqa: PLC0415

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--budget-given", type=float, default=stage0.BUDGET_GIVEN_S)
    parser.add_argument("--budget-formalised", type=float, default=stage0.BUDGET_FORMALISED_S)
    parser.add_argument("--ids")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    spend = [0.0]

    def add(row: dict) -> None:
        spend[0] += estimate_usd(row["model"], row["input_tokens"], row["output_tokens"]) or 0.0

    runner = lane.LeanRunner.from_workspace(
        ROOT / "lean-workspace", lake=str(Path.home() / ".elan/bin/lake")
    )
    worker = ap.WarmWorker(runner, ROOT / "scripts/eval/warm_worker.lean")
    pool = lane.load_fixture_recipes(ROOT / "testdata")
    model = gate.openai_model_call(load_key(args.env_file))
    s0 = stage0.Stage0(worker, pool, model, require_flags=False)
    print("exact? index prewarm s", round(worker.prewarm_search(), 2), flush=True)
    load0 = os.getloadavg()
    print("load", load0, "worker start", round(worker.startup_s, 2), flush=True)
    problems = json.loads((ROOT / "testdata/generation-eval-v1/manifest.json").read_text())[
        "problems"
    ]
    if args.ids:
        problems = [p for p in problems if p["id"] in args.ids.split(",")]
    with usage_scope(add), (args.out / "stage0.jsonl").open("w") as fh:
        for p in problems:
            given = p.get("fixed_lean_statement")
            t0 = time.monotonic()
            r = s0.run(
                p["statement"],
                p["language"],
                formal=given or None,
                budget_s=args.budget_given if given else args.budget_formalised,
            )
            wall = time.monotonic() - t0
            row = {
                "id": p["id"],
                "tier": p["tier"],
                "field": p["field"],
                "split": p["split"],
                "language": p["language"],
                "formal_source": r.formal_source,
                "outcome": r.outcome,
                "reason": r.reason,
                "route": r.route,
                "by": r.by,
                "lemma": r.lemma,
                "wall_s": round(wall, 2),
                "seconds": r.seconds,
                "model_calls": r.model_calls,
                "formal": r.formal,
                "answer_text": r.answer_text,
                "evidence": r.evidence(),
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print(p["id"], r.outcome, r.by, r.reason, round(wall, 1), flush=True)
    print("load", load0, "->", os.getloadavg(), f"spend_est_usd={spend[0]:.4f}")
    worker.close()


if __name__ == "__main__":
    main()
