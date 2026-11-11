"""Zero-model coverage and latency of Recipe reuse on generation-eval-v1.

Arms (no model call anywhere; the real pinned Lean is used for every compile):

  baseline_default        flags at defaults: only the exact-input profile can answer (no Lean at
                          request time: stored sealed bytes).
  baseline_instantiation  PALS_RECIPE_INSTANTIATION on: exact input + the vocabulary grammar
                          (parse_request -> bind_recipe -> elaborate -> real Lean).
  lane                    PALS_GENERAL_RECIPE_LANE on: general_recipe_lane.answer on the request's
                          formal statement (fixed_lean_statement, else the grammar's proposition).

Pools: ``fixtures`` (the hand-written *-recipe-v1 cards) and ``recovered`` (+82 closed manifests,
not published; counted separately).  Output: one JSON line per (arm, pool, item) in --out.

    uv run python scripts/eval/run_recipe_lane.py --out DIR --arms lane --pool fixtures,recovered
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pals_agent import general_recipe_lane as lane  # noqa: E402
from pals_agent.recipe_exact_input import STATEMENTS  # noqa: E402
from pals_agent.recipe_instantiation import InstantiationRejected, elaborate  # noqa: E402
from pals_agent.request_proposition import bind_recipe, parse_request  # noqa: E402

MANIFEST = ROOT / "testdata/generation-eval-v1/manifest.json"


def pools(names: list[str]) -> dict[str, list[lane.PoolRecipe]]:
    fixtures = lane.load_fixture_recipes(ROOT / "testdata")
    out = {"fixtures": fixtures}
    if "recovered" in names:
        out["recovered"] = fixtures + lane.load_recovered_recipes(ROOT / "testdata")
    return out


def baseline_default(problem: dict) -> dict:
    t0 = time.monotonic()
    hit = problem["statement"] in STATEMENTS
    return {
        "covered": hit,
        "code": None if hit else "no_exact_profile_and_grammar_inert",
        "ms": {"total": round((time.monotonic() - t0) * 1000, 2)},
        "lean_compile": False,
    }


def baseline_instantiation(problem, pool, runner) -> dict:
    row = baseline_default(problem)
    if row["covered"]:
        return row
    parsed = parse_request(problem["statement"])
    if parsed is None:
        return {**row, "code": "grammar_no_parse"}
    t0 = time.monotonic()
    filtered = False
    for recipe in pool:
        if bind_recipe(recipe.target_source, parsed.proposition) is None:
            continue
        if recipe.answer_language != ("ja" if problem["language"] == "ja" else "en"):
            filtered = True  # sealed in another language: ineligible, never translated
            continue
        try:
            inst = elaborate(recipe.lean_code, parsed.proposition, [])
        except InstantiationRejected:
            continue
        code, out, sec = runner.run(inst.source)
        ok = code == 0 and "error" not in out
        return {
            "covered": ok,
            "code": None if ok else "lean_rejected",
            "recipe": recipe.recipe_id,
            "ms": {"lean": round(sec * 1000), "total": round((time.monotonic() - t0) * 1000)},
            "lean_compile": True,
        }
    return {**row, "code": "language_filter" if filtered else "grammar_parsed_no_recipe_binds"}


def lane_arm(problem, pool, runner, candidates) -> dict:
    formal = problem.get("fixed_lean_statement")
    source = "fixed_lean_statement"
    if not formal:
        parsed = parse_request(problem["statement"])
        if parsed is None:
            return {
                "covered": False,
                "code": "no_formal_statement_without_model",
                "ms": {},
                "lean_compile": False,
            }
        formal, source = parsed.proposition, "grammar"
    res = lane.answer(formal, pool, runner, language=problem["language"], candidates=candidates)
    return {
        "covered": res.outcome == "answered",
        "code": res.code,
        "formal_source": source,
        "recipe": res.recipe_id,
        "origin": res.recipe_origin,
        "ms": res.timings_ms,
        "tried": res.tried,
        "model_calls": res.model_calls,
        "lean_compile": True,
        "has_stored_answer": res.answer_text is not None,
        "identity": bool(res.proposition and res.recipe_id and _identity(res, pool)),
    }


def _identity(res, pool) -> bool:
    recipe = next(r for r in pool if r.recipe_id == res.recipe_id)
    norm = lambda t: "".join(t.split())  # noqa: E731
    return norm(lane.closed_proposition(res.proposition)) == norm(recipe.target_source) or norm(
        res.proposition
    ) == norm(recipe.target_source)


def summarize(rows: list[dict]) -> dict:
    cov = [r for r in rows if r["covered"]]
    lean = sorted(r["ms"].get("total", 0) for r in cov if r["lean_compile"])
    q = lambda p: lean[min(len(lean) - 1, int(p * len(lean)))] if lean else None  # noqa: E731
    return {
        "n": len(rows),
        "covered": len(cov),
        "p50_ms": q(0.5),
        "p90_ms": q(0.9),
        "codes": {
            c: sum(1 for r in rows if r["code"] == c)
            for c in sorted({r["code"] for r in rows if r["code"]})
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--arms", default="baseline_default,baseline_instantiation,lane")
    ap.add_argument("--pool", default="fixtures,recovered")
    ap.add_argument("--candidates", type=int, default=lane.DEFAULT_CANDIDATES)
    ap.add_argument("--workspace", type=Path, default=ROOT / "lean-workspace")
    ap.add_argument("--lake", default=str(Path.home() / ".elan/bin/lake"))
    ap.add_argument("--ids")
    ap.add_argument("--probes", action="store_true", help="test-only specialisation probes")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    problems = json.loads(MANIFEST.read_text())["problems"]
    if args.probes:
        probes = json.loads((ROOT / "testdata/general-recipe-probes-v1/probes.json").read_text())
        problems = [
            {
                "id": q["id"],
                "tier": q["family"],
                "split": "probe",
                "language": "ja" if q["nl"] and any(ord(c) > 0x3000 for c in q["nl"]) else "en",
                "statement": q["nl"] or q["formal"],
                "fixed_lean_statement": q["formal"],
            }
            for q in probes["probes"]
        ]
    if args.ids:
        problems = [p for p in problems if p["id"] in args.ids.split(",")]
    runner = lane.LeanRunner.from_workspace(args.workspace, lake=args.lake)
    summary = {}
    for arm in args.arms.split(","):
        for pool_name, pool in pools(args.pool.split(",")).items():
            if arm == "baseline_default" and pool_name != "fixtures":
                continue
            rows = []
            with (args.out / f"{arm}.{pool_name}.jsonl").open("w") as fh:
                for p in problems:
                    if arm == "baseline_default":
                        r = baseline_default(p)
                    elif arm == "baseline_instantiation":
                        r = baseline_instantiation(p, pool, runner)
                    else:
                        r = lane_arm(p, pool, runner, args.candidates)
                    r.update(id=p["id"], tier=p["tier"], split=p["split"], language=p["language"])
                    rows.append(r)
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    fh.flush()
            summary[f"{arm}/{pool_name}"] = summarize(rows)
            print(
                arm,
                pool_name,
                json.dumps(summary[f"{arm}/{pool_name}"], ensure_ascii=False),
                flush=True,
            )
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
