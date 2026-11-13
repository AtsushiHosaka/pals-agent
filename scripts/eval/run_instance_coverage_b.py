# ruff: noqa: E501
"""(B) coverage: a cheap model formalisation + a faithfulness check + general-Recipe instantiation.

Population: the items that (A) (``run_instance_coverage.py``) classes ``a_no_formal`` (no
``fixed_lean_statement`` and the grammar does not parse the request) among tuning + dev_unseen.
Only ``split in KEEP`` items are kept; any other item (held_out) is dropped as it is read and is
never printed, stored or run.

Per item (serial):
  1. ONE formalisation call (``gate.formalise_typed`` variant 0, the stage-0 binding: Luna, low).
     ``explain`` / ``compute`` kinds or an empty / non-plain statement -> b1.
  2. Fidelity checks that need no Lean process and one cheap call: an independent ``gate.review``
     (one call), ``gate.structure_check``, ``gate.triviality_check``, ``gate.numerals_signal``
     (signal only).  Pass = reviewed AND no structure mismatch AND no triviality.
     NOT used (expensive / need a warm worker): roundtrip, the second formalisation and the
     Lean-checked agreement of the two, the Lean vacuity probe.  A failed statement -> b2 and is
     never instantiated.
  3. ``lane.answer`` on the fixed ``*-recipe-v1`` fixtures (no model, no proof generation).

  b1 no formal statement / formalisation failed / out of scope
  b2 a statement was produced but is not faithful (never counted as verified)
  b3 faithful statement, no fitting general form (Lean rejected every candidate / none ranked)
  b4 a fitting form exists but instantiation did not close (back-check rejected, error, timeout)
  b5 verified: instance of a Recipe that passed the back-check

Spend is accumulated from recorded usage (``estimate_usd``); the run stops before an item once
the total reaches ``--max-usd`` (default 0.8).  The key is read from OPENAI_API_KEY only.

    OPENAI_API_KEY=... nohup uv run python scripts/eval/run_instance_coverage_b.py --out DIR \
        --dev-manifest PARENT/docs/generation-eval-freshman-v1/manifest.json \
        --workspace /path/to/pals-agent/lean-workspace > DIR.log 2>&1 &
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pals_agent import fidelity_gate as gate  # noqa: E402
from pals_agent import general_recipe_lane as lane  # noqa: E402
from pals_agent.automation_portfolio import check_formal_statement  # noqa: E402
from pals_agent.recipe_instantiation import InstantiationRejected  # noqa: E402
from pals_agent.request_proposition import parse_request  # noqa: E402

TUNING_MANIFEST = ROOT / "testdata/generation-eval-v1/manifest.json"
KEEP = {"tuning", "dev_unseen"}
CLASSES = ("b1_no_formal", "b2_unfaithful", "b3_no_general_form", "b4_not_closed", "b5_verified")


def load(path: Path) -> list[dict]:
    """Kept items only; every other split (held_out) is dropped as it is read."""
    out = []
    for p in json.loads(path.read_text())["problems"]:
        if p.get("split") in KEEP:
            out.append(p)
        del p
    return out


def pct(values: list[float], p: float) -> float | None:
    s = sorted(values)
    return s[min(len(s) - 1, int(p * len(s)))] if s else None


class Meter:
    """Serial spend meter fed by ``usage_scope``; ``take`` returns the cost since the last call."""

    def __init__(self) -> None:
        from pals_agent.evals.runner import estimate_usd

        self._estimate = estimate_usd
        self.total = 0.0
        self.calls = 0
        self._mark = 0.0

    def add(self, row: dict) -> None:
        self.total += self._estimate(row["model"], row["input_tokens"], row["output_tokens"]) or 0.0
        self.calls += 1

    def take(self) -> float:
        delta, self._mark = self.total - self._mark, self.total
        return delta


def process(p: dict, model, meter: Meter, pool, runner, candidates: int) -> dict:
    row: dict = {"model_calls": 0, "usd": 0.0, "sec": {}}
    request = p["statement"]
    calls0 = meter.calls

    def finish(cls: str, code: str | None) -> dict:
        row.update({"class": cls, "code": code, "model_calls": meter.calls - calls0})
        return row

    # 1. formalisation (one call)
    t = time.monotonic()
    try:
        typed = gate.formalise_typed(model, request, 0)
    except Exception as error:  # noqa: BLE001 - recorded
        row["sec"]["formalise"] = round(time.monotonic() - t, 2)
        row["usd"] = round(meter.take(), 6)
        return finish("b1_no_formal", f"formalise_error:{type(error).__name__}")
    row["sec"]["formalise"] = round(time.monotonic() - t, 2)
    row["kind"], row["expression"] = typed.kind, typed.expression
    row["formal"] = typed.formal
    row["usd"] = round(meter.take(), 6)
    if typed.kind == "explain":
        return finish("b1_no_formal", "kind_explain")
    if typed.kind == "compute":
        return finish("b1_no_formal", "kind_compute_out_of_scope")
    if not typed.formal:
        return finish("b1_no_formal", "formalisation_empty")
    try:  # the production allow-list grammar (no Lean); also what lane.answer enforces
        check_formal_statement(typed.formal)
    except InstantiationRejected as error:
        return finish("b1_no_formal", f"statement_not_plain:{str(error)[:80]}")

    # 2. fidelity (review = 1 call; the rest deterministic)
    t = time.monotonic()
    fid: dict = {
        "numerals_signal": gate.numerals_signal(request, typed.formal),
        "structure": gate.structure_check(request, typed.formal),
        "triviality": gate.triviality_check(typed.formal),
    }
    try:
        fid["reviewed"], fid["review_issue"] = gate.review(model, request, typed.formal, typed.kind)
    except Exception as error:  # noqa: BLE001 - a missing check is a failed check
        fid["reviewed"], fid["review_issue"] = False, f"review_unavailable:{type(error).__name__}"
    row["sec"]["review"] = round(time.monotonic() - t, 2)
    row["usd"] = round(row["usd"] + meter.take(), 6)
    reasons = []
    if not fid["reviewed"]:
        reasons.append("review_rejected" if not fid["review_issue"].startswith("review_unavailable") else "review_unavailable")
    if fid["structure"]:
        reasons.append("structure_mismatch")
    if fid["triviality"]:
        reasons.append("trivial_statement")
    fid["passed"], fid["reasons"] = not reasons, reasons
    row["fidelity"] = fid
    if reasons:
        return finish("b2_unfaithful", "+".join(reasons))

    # 3. instantiation of a general Recipe (no model)
    try:
        res = lane.answer(typed.formal, pool, runner, language=p["language"], candidates=candidates)
    except Exception as error:  # noqa: BLE001
        return finish("b4_not_closed", f"exception:{type(error).__name__}")
    row["sec"]["lean"] = round(res.timings_ms.get("lean", 0.0) / 1000, 2)
    row["sec"]["lane_total"] = round(res.timings_ms.get("total", 0.0) / 1000, 2)
    row["verdicts"] = [
        {k: t[k] for k in ("recipe", "score", "verdict", "stage") if k in t}
        for t in res.tried
        if "verdict" in t
    ]
    if res.outcome == "answered":
        row.update(recipe=res.recipe_id, origin=res.recipe_origin, instance_proposition=res.proposition)
        return finish("b5_verified", None)
    if res.code in {"lean_rejected_all", "no_candidate", "no_instance"}:
        return finish("b3_no_general_form", res.code)
    return finish("b4_not_closed", res.code)


def summary_md(rows: list[dict], total_usd: float, population: int, skipped: int, max_usd: float) -> str:
    n = len(rows)
    out = ["# Instance coverage (B): model formalisation + fidelity + general Recipe", ""]
    out.append(
        f"population = {population} items (A's a_no_formal among tuning + dev_unseen); run = {n}; "
        f"stopped by budget (skipped) = {skipped}"
    )
    out.append(f"model calls = {sum(r['model_calls'] for r in rows)}; total cost = US${total_usd:.4f} "
               f"(cap {max_usd}); estimate from recorded usage (upper bound pricing)")
    out += [
        "",
        "Model: Luna low (`proof_reuse_judge` binding) for formalisation and review. Fidelity used: "
        "one independent review + structure_check + triviality_check (+ numerals_signal, signal only). "
        "NOT used: roundtrip, second formalisation + Lean-checked agreement, Lean vacuity probe "
        "(they need warm workers / more calls). Statements that pass here are therefore weaker "
        "evidence than the production gate: b5 is an upper bound for what stage 0 would release.",
        "",
        "## Classes",
        "",
        "| class | n |",
        "|---|---|",
    ]
    counts = Counter(r["class"] for r in rows)
    out += [f"| {c} | {counts.get(c, 0)} |" for c in CLASSES]
    for key in ("split", "tier", "field"):
        out += ["", f"## by {key}", "", f"| {key} | " + " | ".join(c[:2] for c in CLASSES) + " | n |",
                "|---|" + "---|" * (len(CLASSES) + 1)]
        for value in sorted({str(r[key]) for r in rows}):
            sub = [r for r in rows if str(r[key]) == value]
            cs = Counter(r["class"] for r in sub)
            out.append(f"| {value} | " + " | ".join(str(cs.get(c, 0)) for c in CLASSES) + f" | {len(sub)} |")
    b5 = [r for r in rows if r["class"] == CLASSES[4]]

    def wall(r: dict) -> float:
        return r["sec"].get("formalise", 0) + r["sec"].get("review", 0) + r["sec"].get("lane_total", 0)

    out += ["", "## b5 time per item (seconds; formalise + review + lane; one serial run each)", "",
            "| stage | p50 | p90 | max |", "|---|---|---|---|"]
    for label, fn in (
        ("formalise", lambda r: r["sec"].get("formalise", 0)),
        ("review", lambda r: r["sec"].get("review", 0)),
        ("lean (lane)", lambda r: r["sec"].get("lean", 0)),
        ("total", wall),
    ):
        v = [fn(r) for r in b5]
        out.append(f"| {label} | {pct(v, 0.5)} | {pct(v, 0.9)} | {round(max(v), 2) if v else None} |")
    allc = [r["usd"] for r in rows]
    b5c = [r["usd"] for r in b5]
    out += ["", "## Cost per item (USD)", "",
            f"- all items: mean {sum(allc) / n:.5f}, max {max(allc):.5f}" if n else "- none",
            f"- b5 items: mean {sum(b5c) / len(b5c):.5f}, max {max(b5c):.5f}" if b5c else "- b5: none",
            f"- cost per b5 item incl. spend on all others: {total_usd / len(b5):.5f}" if b5 else ""]
    out += ["", "## b5 items", "", "| id | recipe | total s |", "|---|---|---|"]
    out += [f"| {r['id']} | {r['recipe']} | {round(wall(r), 2)} |" for r in b5]
    codes = Counter((r["class"][:2], r["code"]) for r in rows if r["class"] != CLASSES[4])
    out += ["", "## rejection codes", "", "| class | code | n |", "|---|---|---|"]
    out += [f"| {c} | {code} | {k} |" for (c, code), k in sorted(codes.items(), key=lambda x: str(x[0]))]
    b3 = [r for r in rows if r["class"] == CLASSES[2]]
    out += ["", "## b3: material for tabulating the missing general forms", "",
            "Formal statements are in coverage_b.jsonl (`formal`, `verdicts` = Recipes tried with Lean "
            "verdicts); the table lists id, tier, field, rejection code and the best-scored Recipe tried.", "",
            "| id | tier | field | code | best recipe tried (score, verdict) |", "|---|---|---|---|---|"]
    for r in b3:
        v = max(r.get("verdicts", []), key=lambda t: t.get("score", 0), default=None)
        best = f"{v.get('recipe')} ({v.get('score')}, {v.get('verdict')})" if v else "-"
        out.append(f"| {r['id']} | {r['tier']} | {r['field']} | {r['code']} | {best} |")
    if rows:
        out += ["", "Load averages (1/5/15 min) first/last row: "
                + json.dumps(rows[0]["loadavg"]) + " .. " + json.dumps(rows[-1]["loadavg"])]
    return "\n".join(out) + "\n"


def main() -> None:
    from formalise import load_key  # noqa: PLC0415

    from pals_agent.usage import usage_scope  # noqa: PLC0415

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--dev-manifest", type=Path, required=True)
    ap.add_argument("--workspace", type=Path, default=ROOT / "lean-workspace")
    ap.add_argument("--lake", default=str(Path.home() / ".elan/bin/lake"))
    ap.add_argument("--candidates", type=int, default=lane.DEFAULT_CANDIDATES)
    ap.add_argument("--max-usd", type=float, default=0.8)
    ap.add_argument("--ids")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    items = load(TUNING_MANIFEST) + load(args.dev_manifest)
    # population = what (A) calls a_no_formal
    items = [p for p in items if not p.get("fixed_lean_statement") and parse_request(p["statement"]) is None]
    population = len(items)
    if args.ids:
        items = [p for p in items if p["id"] in args.ids.split(",")]
    pool = lane.load_fixture_recipes(ROOT / "testdata")
    runner = lane.LeanRunner.from_workspace(args.workspace, lake=args.lake)
    model = gate.openai_model_call(load_key(None))
    meter = Meter()
    print(f"{population} population, {len(items)} to run, {len(pool)} recipes, lean={runner.lean_binary}", flush=True)
    rows: list[dict] = []
    skipped = 0
    with usage_scope(meter.add), (args.out / "coverage_b.jsonl").open("w") as fh:
        for i, p in enumerate(items):
            if meter.total >= args.max_usd:
                skipped = len(items) - i
                print("budget reached", flush=True)
                break
            t0 = time.monotonic()
            r = process(p, model, meter, pool, runner, args.candidates)
            r["loadavg"] = [round(x, 2) for x in os.getloadavg()]
            r["wall_s"] = round(time.monotonic() - t0, 2)
            r.update(id=p["id"], split=p["split"], tier=p["tier"], field=p.get("field"),
                     language=p["language"], statement=p["statement"])
            rows.append(r)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            print(p["id"], r["class"], r["code"], r["wall_s"], f"spend~{meter.total:.4f}", flush=True)
    (args.out / "summary.md").write_text(summary_md(rows, meter.total, population, skipped, args.max_usd))
    print(json.dumps(Counter(r["class"] for r in rows)), flush=True)
    print(f"DONE n={len(rows)} spend_est_usd={meter.total:.4f}", flush=True)


if __name__ == "__main__":
    main()
