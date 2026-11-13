"""Summarise a run of run_hetero_api_sim.py on the freshman-v1 dev_unseen problems.

    analyze_freshman_dev.py RUN_DIR PROBLEMS_JSON [--faithfulness-out FILE]

Prints success, answer-completion and verified-time percentiles with the 10/20/30 s shares, the
per-stage breakdown from the step-timing events (model calls by step and effort, Lean, the fixed
API round trip, the explanation and review waits), and writes a reading sheet (the manifest's
expected conclusion beside the verified Lean source) for the by-hand faithfulness check. The
sheet holds statements and Lean source: keep it out of git.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def share(values: list[float], total: int, limit: float) -> str:
    return f"{sum(1 for v in values if v <= limit)}/{total}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("problems", type=Path)
    ap.add_argument("--faithfulness-out", type=Path)
    args = ap.parse_args()
    rows = [json.loads(x) for x in (args.run / "records.jsonl").read_text().splitlines() if x]
    meta = {p["id"]: p for p in json.loads(args.problems.read_text())["problems"]}
    n = len(rows)
    ver = [r for r in rows if r["verified"]]
    print(f"problems {n}  verified {len(ver)}  first-attempt {sum(r['first_attempt_ok'] for r in rows)}"
          f"  repairs {sum(r['repairs'] for r in rows)}  usd {sum(r['usd'] for r in rows):.3f}")
    for label, subset in (
        ("all", rows),
        ("non-trivial", [r for r in rows if not meta[r['problem_id']].get('trivial')]),
    ):
        tot = len(subset)
        v = [r for r in subset if r["verified"]]
        for key in ("wall_s", "answer_s"):
            xs = [r[key] for r in v]
            print(f"[{label}] {key}: n={tot} verified={len(v)} p50={pct(xs, .5)} p90={pct(xs, .9)}"
                  f" <=10s {share(xs, tot, 10)} <=20s {share(xs, tot, 20)} <=30s {share(xs, tot, 30)}")
    print("\nper problem:")
    for r in rows:
        print(f"  {r['problem_id']:50s} ok={int(r['verified'])} first={int(r['first_attempt_ok'])} "
              f"sub={r['submits']} wall={r['wall_s']:6.1f} answer={r['answer_s']:6.1f} usd={r['usd']:.4f}"
              f" review_ok={r['answer'].get('review_approved')} load={r['load_start']}")

    # --- per stage -----------------------------------------------------------------------
    calls: dict[tuple[str, str, str], list[dict]] = {}
    for r in rows:
        for s in r["steps"]:
            if s.get("step") and s.get("model_call") is not False and s.get("model"):
                calls.setdefault((s["step"], s["model"], s.get("effort") or "-"), []).append(s)
    print("\nmodel calls (step, model, effort): n, duration median/p90/max [s], reasoning tokens"
          " median/max, output tokens median, cached/input")
    for key, ss in sorted(calls.items()):
        d = [s["duration_ms"] / 1000 for s in ss if s.get("duration_ms") is not None]
        rt = [s.get("reasoning_tokens") or 0 for s in ss]
        ot = [s.get("output_tokens") or 0 for s in ss]
        ci = sum(s.get("cached_input_tokens") or 0 for s in ss)
        it = sum(s.get("input_tokens") or 0 for s in ss)
        print(f"  {key}: n={len(ss)} dur med={statistics.median(d):.1f} p90={pct(d, .9)} "
              f"max={max(d):.1f}  reasoning med={statistics.median(rt)} max={max(rt)}  "
              f"out med={statistics.median(ot)}  cached/input={ci}/{it}")
    lean = [d["verify_s"] for r in rows for d in r["submits_detail"]]
    print(f"\nLean compile per submit: n={len(lean)} median={statistics.median(lean):.1f}"
          f" p90={pct(lean, .9)} max={max(lean):.1f}  (fixed API round trip "
          f"{rows[0]['api_overhead_s']} s per submit)")
    for k in ("review_s", "explain_wait_s"):
        xs = [r["answer"].get(k) for r in ver if r["answer"].get(k) is not None]
        print(f"after-verify wait {k}: median={statistics.median(xs):.1f} p90={pct(xs, .9)}"
              f" max={max(xs):.1f}  (0 means the call had finished beside Lean)")
    # Time from start to the first passing candidate is wall_s minus the fixed trip and Lean.
    gen = [r["wall_s"] - sum(d["verify_s"] for d in r["submits_detail"]) - r["api_overhead_s"] * r["submits"]
           for r in ver]
    print(f"generation + preflight (wall - Lean - round trip): median={statistics.median(gen):.1f}"
          f" p90={pct(gen, .9)} max={max(gen):.1f}")

    if args.faithfulness_out:
        proofs = {}
        for x in (args.run / "proofs.jsonl").read_text().splitlines():
            if x:
                p = json.loads(x)
                proofs[p["problem_id"]] = p
        out = []
        for r in rows:
            m = meta[r["problem_id"]]
            out.append(f"## {r['problem_id']}  [{m['tier']}, {m['mathlib_outlook']}, "
                       f"verified={r['verified']}, review_ok={r['answer'].get('review_approved')}]")
            out.append(f"statement: {m['statement']}")
            out.append(f"expected: {m['expected_conclusion']}")
            p = proofs.get(r["problem_id"])
            if p:
                out.append("```lean\n" + p["lean_code"] + "\n```")
            out.append("")
        args.faithfulness_out.write_text("\n".join(out))


if __name__ == "__main__":
    main()
