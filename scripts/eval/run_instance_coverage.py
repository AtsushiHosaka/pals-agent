# ruff: noqa: E501
"""Zero-model coverage of the current catalog's general Recipes on tuning + dev_unseen.

For every item: how is it classified when the formal statement is obtained without a model
(fixed_lean_statement, else the grammar's proposition) and ``general_recipe_lane.answer`` runs on
the fixed ``*-recipe-v1`` fixtures (no ``recovered`` pool: unpublished, biased).

  a  no_formal            no fixed_lean_statement and the grammar does not parse
  b  not_proposition      formal statement present, not a plain proposition / unsupported
  c  not_instance         formal statement present, Lean rejected every candidate (or none ranked)
  d  verified_instance    instance of a Recipe, passed the back-check (timings recorded);
                          also whether the baseline (exact-input + PALS_RECIPE_INSTANTIATION
                          grammar, as in run_recipe_lane.py) answers the same item

Only ``split in KEEP`` items are kept; any other item (held_out) is dropped as it is read and is
never printed, stored or run.  One serial run per item; load average recorded.

    uv run python scripts/eval/run_instance_coverage.py --out DIR \
        --dev-manifest PARENT/docs/generation-eval-freshman-v1/manifest.json \
        --workspace /path/to/pals-agent/lean-workspace
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_recipe_lane as base  # noqa: E402

from pals_agent import general_recipe_lane as lane  # noqa: E402
from pals_agent.request_proposition import parse_request  # noqa: E402

TUNING_MANIFEST = ROOT / "testdata/generation-eval-v1/manifest.json"
SOURCES = (("tuning", TUNING_MANIFEST), ("dev_unseen", None))
CLASSES = ("a_no_formal", "b_not_proposition", "c_not_instance", "d_verified_instance")


def load(split: str, path: Path) -> list[dict]:
    problems = json.loads(path.read_text())["problems"]
    return [p for p in problems if p.get("split") in {split}]


def classify(problem: dict, pool, runner, candidates: int) -> dict:
    formal = problem.get("fixed_lean_statement")
    source = "fixed_lean_statement"
    if not formal:
        parsed = parse_request(problem["statement"])
        if parsed is None:
            return {"class": CLASSES[0], "code": "no_formal_statement_without_model", "ms": {}}
        formal, source = parsed.proposition, "grammar"
    try:
        res = lane.answer(formal, pool, runner, language=problem["language"], candidates=candidates)
    except Exception as error:  # noqa: BLE001 - unsupported shapes must be reported, not hidden
        return {
            "class": CLASSES[1],
            "formal": formal,
            "formal_source": source,
            "code": f"exception:{type(error).__name__}",
            "ms": {},
        }
    row = {
        "formal": formal,
        "formal_source": source,
        "code": res.code,
        "ms": res.timings_ms,
        "model_calls": res.model_calls,
        "verdicts": [
            {k: t[k] for k in ("recipe", "verdict", "stage") if k in t}
            for t in res.tried
            if "verdict" in t
        ],
    }
    if res.outcome == "answered":
        return {**row, "class": CLASSES[3], "recipe": res.recipe_id, "origin": res.recipe_origin}
    if res.code == "request_not_a_plain_proposition":
        return {**row, "class": CLASSES[1]}
    return {**row, "class": CLASSES[2]}


def baseline_answers(problem: dict, pool, runner) -> dict:
    row = base.baseline_instantiation(problem, pool, runner)
    return {
        "baseline_covered": bool(row["covered"]),
        "baseline_code": row.get("code"),
        "baseline_recipe": row.get("recipe"),
        "baseline_ms": row.get("ms", {}).get("total"),
    }


def pct(values: list[float], p: float) -> float | None:
    s = sorted(values)
    return s[min(len(s) - 1, int(p * len(s)))] if s else None


def summary_md(rows: list[dict]) -> str:
    out = ["# Instance coverage (zero model calls)", ""]
    out.append(f"n = {len(rows)} (tuning + dev_unseen); model calls = {sum(r.get('model_calls', 0) for r in rows)}")
    out += ["", "## Classes", "", "| class | n |", "|---|---|"]
    counts = Counter(r["class"] for r in rows)
    out += [f"| {c} | {counts.get(c, 0)} |" for c in CLASSES]
    d = [r for r in rows if r["class"] == CLASSES[3]]
    out += ["", "## (d) timings (ms, one serial run each)", "", "| stage | p50 | p90 | max |", "|---|---|---|---|"]
    for stage in ("match", "build", "lean", "total"):
        v = [r["ms"][stage] for r in d if stage in r["ms"]]
        out.append(f"| {stage} | {pct(v, 0.5)} | {pct(v, 0.9)} | {max(v) if v else None} |")
    b = sum(1 for r in d if r.get("baseline_covered"))
    out += ["", f"(d) also answered by baseline: {b}/{len(d)}; lane-only: {len(d) - b}", ""]
    for key in ("split", "tier", "field"):
        out += [f"## by {key}", "", "| " + key + " | " + " | ".join(c[:1] for c in CLASSES) + " | n |", "|---|---|---|---|---|---|"]
        for value in sorted({str(r[key]) for r in rows}):
            sub = [r for r in rows if str(r[key]) == value]
            cs = Counter(r["class"] for r in sub)
            out.append(f"| {value} | " + " | ".join(str(cs.get(c, 0)) for c in CLASSES) + f" | {len(sub)} |")
        out.append("")
    out += ["## (d) items", "", "| id | recipe | total ms | baseline |", "|---|---|---|---|"]
    out += [
        f"| {r['id']} | {r['recipe']} | {r['ms'].get('total')} | {r.get('baseline_covered')} |" for r in d
    ]
    codes = Counter(r["code"] for r in rows if r["class"] != CLASSES[3])
    out += ["", "## rejection codes (a/b/c)", "", "| code | n |", "|---|---|"]
    out += [f"| {c} | {n} |" for c, n in sorted(codes.items(), key=lambda x: str(x[0]))]
    out += ["", "Load averages (1/5/15 min) at start and end: " + json.dumps(rows[0]["loadavg"] if rows else None) + " .. " + json.dumps(rows[-1]["loadavg"] if rows else None)]
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--dev-manifest", type=Path, required=True)
    ap.add_argument("--workspace", type=Path, default=ROOT / "lean-workspace")
    ap.add_argument("--lake", default=str(Path.home() / ".elan/bin/lake"))
    ap.add_argument("--candidates", type=int, default=lane.DEFAULT_CANDIDATES)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    items = load("tuning", TUNING_MANIFEST) + load("dev_unseen", args.dev_manifest)
    pool = lane.load_fixture_recipes(ROOT / "testdata")
    runner = lane.LeanRunner.from_workspace(args.workspace, lake=args.lake)
    print(f"{len(items)} items, {len(pool)} fixture recipes, lean={runner.lean_binary}", flush=True)
    rows = []
    with (args.out / "coverage.jsonl").open("w") as fh:
        for p in items:
            r = classify(p, pool, runner, args.candidates)
            r["loadavg"] = [round(x, 2) for x in os.getloadavg()]
            if r["class"] == CLASSES[3]:
                r.update(baseline_answers(p, pool, runner))
            r.update(
                id=p["id"], split=p["split"], tier=p["tier"], field=p.get("field"),
                language=p["language"], statement=p["statement"],
                fixed_lean_statement=p.get("fixed_lean_statement"),
            )
            rows.append(r)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
    (args.out / "summary.md").write_text(summary_md(rows))
    print(json.dumps(Counter(r["class"] for r in rows)), flush=True)


if __name__ == "__main__":
    main()
