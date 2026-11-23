"""Agent lane -> API re-derivation -> compile, on the general-Recipe probes (no model calls).

Per probe (testdata/general-recipe-probes-v1, formal statements, not evaluation items):
  1. agent: ``general_recipe_lane.answer(..., bound=False)`` over the fixed ``*-recipe-v1`` cards
     names the Recipe whose plain instance Lean accepts (the proposal);
  2. API: ``app.domain.recipe_instantiation_evidence.derive`` re-derives the wrapper from the
     Recipe bytes and the proposition alone (nothing the agent compiled is reused);
  3. the derived source is compiled by the pinned Lean (stand-in for the API's verifier).

    PYTHONPATH=<pals-agent> <pals-api>/.venv/bin/python scripts/eval/run_api_roundtrip.py \\
        --workspace <lean-workspace> --out OUT.jsonl
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pals_agent import general_recipe_lane as lane  # noqa: E402


def main() -> None:
    from app.domain import recipe_instantiation_evidence as contract  # noqa: PLC0415

    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    runner = lane.LeanRunner.from_workspace(args.workspace)
    pool = lane.load_fixture_recipes(ROOT / "testdata")
    probes = json.loads((ROOT / "testdata/general-recipe-probes-v1/probes.json").read_text())["probes"]
    rows = []
    for probe in probes:
        started = time.monotonic()
        proposed = lane.answer(probe["formal"], pool, runner, bound=False)
        row = {"id": probe["id"], "expect_instance": probe["expect_instance"],
               "lane": proposed.outcome, "lane_ms": round((time.monotonic() - started) * 1000)}
        if proposed.outcome == "answered":
            recipe = next(r for r in pool if r.recipe_id == proposed.recipe_id)
            derived = contract.derive(recipe.lean_code, [], probe["formal"])
            code, output, seconds = runner.run(derived.source)
            row.update(
                recipe=recipe.recipe_id, api_derived_sha=derived.source_sha256[:12],
                api_compile_ok=code == 0 and ": error" not in output,
                api_compile_ms=round(seconds * 1000),
            )
        rows.append(row)
        print(row, flush=True)
    args.out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    answered = [r for r in rows if r["lane"] == "answered"]
    print(json.dumps({
        "probes": len(rows), "lane_answered": len(answered),
        "api_compile_ok": sum(1 for r in answered if r.get("api_compile_ok")),
        "expected_instances": sum(1 for r in rows if r["expect_instance"]),
        "false_acceptance": sum(1 for r in rows if r["lane"] == "answered" and not r["expect_instance"]),
        "load": os.getloadavg(),
    }))


if __name__ == "__main__":
    main()
