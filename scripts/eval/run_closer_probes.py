"""Recipe-lane probes on the 48 statements of the instantiation experiment (pals-agent#108).

Pool: the repo's 10 recipe cards plus two test-only Recipes (add_continuous, const_mul_continuous).
Per statement the lane compiles the top candidates in ONE sandboxed Lean process; a statement is
`proved` only if every back-check passes (no error, standard axioms, G used, type unchanged).

    uv run python scripts/eval/run_closer_probes.py --out FILE.jsonl [--candidates 8]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pals_agent import general_recipe_lane as lane  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--candidates", type=int, default=8)
    args = parser.parse_args()
    runner = lane.LeanRunner.from_workspace(
        ROOT / "lean-workspace", lake=str(Path.home() / ".elan/bin/lake")
    )
    pool = lane.load_fixture_recipes(ROOT / "testdata") + lane.load_test_fixtures(
        ROOT / "tests/fixtures/general_recipes"
    )
    pool = [r for r in pool if not r.recipe_id.startswith("testfixture.pow_")]
    data = json.loads((ROOT / "testdata/recipe-closer-probes-v1/statements.json").read_text())
    with args.out.open("w") as fh:
        for s in data["statements"]:
            res = lane.answer(s["stmt"], pool, runner, candidates=args.candidates)
            row = {
                "id": s["id"],
                "kind": s["kind"],
                "proved": res.outcome == "answered",
                "recipe": res.recipe_id,
                "ms": res.timings_ms,
                "tried": [t.get("verdict") for t in res.tried],
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print(s["id"], s["kind"], row["proved"], res.recipe_id, flush=True)


if __name__ == "__main__":
    main()
