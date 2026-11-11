"""Measure the fidelity gate: adversarial cases and the 58 items that need a formalisation.

    uv run python scripts/eval/run_gate.py --out DIR --env-file ENVFILE --part adv|items|both

Model calls use the assessment binding (Luna, low); spend is estimated from recorded usage.
Lean runs in one warm worker.  Prints the machine load at start and end.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import contextvars
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


def agree(worker: ap.WarmWorker, first: str, second: str) -> bool:
    text, _ = gate.equivalence_source(first, second)
    try:
        output, _ = worker.check(text, timeout_s=30.0)
    except TimeoutError:
        worker.restart()
        return False
    return gate.equivalence_verdict(output)


def prove(worker: ap.WarmWorker, formal: str) -> dict:
    try:
        r = ap.solve_warm(formal, [], worker, deadline=time.monotonic() + 15.0)
    except Exception as error:  # noqa: BLE001
        if not worker.alive():
            worker.restart()
            worker.prewarm_search()
        return {"proved": False, "by": None, "code": type(error).__name__}
    if not worker.alive():
        worker.restart()
        worker.prewarm_search()
    return {"proved": r.outcome == "answered", "by": r.by, "code": r.code}


def main() -> None:
    from formalise import load_key  # noqa: PLC0415

    from pals_agent.evals.runner import estimate_usd  # noqa: PLC0415
    from pals_agent.usage import usage_scope  # noqa: PLC0415

    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--out", type=Path, required=True)
    ap_.add_argument("--env-file", type=Path)
    ap_.add_argument("--max-usd", type=float, default=0.3)
    ap_.add_argument("--part", default="both")
    args = ap_.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    spend = [0.0]

    def add(row: dict) -> None:
        spend[0] += estimate_usd(row["model"], row["input_tokens"], row["output_tokens"]) or 0.0

    model = gate.openai_model_call(load_key(args.env_file))
    runner = lane.LeanRunner.from_workspace(
        ROOT / "lean-workspace", lake=str(Path.home() / ".elan/bin/lake")
    )
    worker = ap.WarmWorker(runner, ROOT / "scripts/eval/warm_worker.lean")
    print("exact? index prewarm s", round(worker.prewarm_search(), 2), flush=True)
    print("load", os.getloadavg(), "worker start", round(worker.startup_s, 2), flush=True)
    pool = futures.ThreadPoolExecutor(max_workers=4)

    with usage_scope(add):
        if args.part in ("adv", "both"):
            cases = json.loads((ROOT / "testdata/fidelity-adversarial-v1/cases.json").read_text())[
                "cases"
            ]
            with (args.out / "adversarial.jsonl").open("w") as fh:
                for c in cases:
                    rv_bad = pool.submit(
                        contextvars.copy_context().run, gate.review, model, c["request"], c["bad"]
                    )
                    rv_good = pool.submit(
                        contextvars.copy_context().run,
                        gate.review,
                        model,
                        c["request"],
                        c["faithful"],
                    )
                    lang = "ja" if any(ord(ch) > 0x3000 for ch in c["request"]) else "en"
                    trip_bad = pool.submit(
                        contextvars.copy_context().run,
                        gate.roundtrip,
                        model,
                        c["request"],
                        c["bad"],
                        lang,
                    )
                    trip_good = pool.submit(
                        contextvars.copy_context().run,
                        gate.roundtrip,
                        model,
                        c["request"],
                        c["faithful"],
                        lang,
                    )
                    row = {
                        "id": c["id"],
                        "kind": c["kind"],
                        "structure_bad": gate.structure_check(c["request"], c["bad"]),
                        "triviality_bad": gate.triviality_check(c["bad"]),
                        "bad_proved_by_portfolio": prove(worker, c["bad"]),
                        "agree_bad_vs_faithful": agree(worker, c["bad"], c["faithful"]),
                        "agree_faithful_vs_itself": agree(worker, c["faithful"], c["faithful"]),
                    }
                    row["review_bad_approved"], row["review_bad_issue"] = rv_bad.result()
                    row["review_faithful_approved"], _ = rv_good.result()
                    row["roundtrip_bad_ok"], row["roundtrip_bad_issue"] = trip_bad.result()
                    row["roundtrip_faithful_ok"], _ = trip_good.result()
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fh.flush()
                    print(
                        row["id"],
                        row["agree_bad_vs_faithful"],
                        row["review_bad_approved"],
                        row["review_faithful_approved"],
                        flush=True,
                    )
        if args.part in ("items", "both"):
            manifest = json.loads((ROOT / "testdata/generation-eval-v1/manifest.json").read_text())[
                "problems"
            ]
            todo = [p for p in manifest if not p.get("fixed_lean_statement")]
            with (args.out / "items.jsonl").open("w") as fh:
                for p in todo:
                    if spend[0] >= args.max_usd:
                        print("budget reached", flush=True)
                        break
                    t0 = time.monotonic()
                    fa = pool.submit(
                        contextvars.copy_context().run, gate.formalise, model, p["statement"], 0
                    )
                    fb = pool.submit(
                        contextvars.copy_context().run, gate.formalise, model, p["statement"], 1
                    )
                    row = {"id": p["id"], "tier": p["tier"], "language": p["language"]}
                    try:
                        a = fa.result()
                    except Exception as error:  # noqa: BLE001
                        a = ""
                        row["error_a"] = type(error).__name__
                    try:
                        b = fb.result()
                    except Exception as error:  # noqa: BLE001
                        b = ""
                        row["error_b"] = type(error).__name__
                    row.update(formal_a=a, formal_b=b, formalise_s=round(time.monotonic() - t0, 2))
                    plain = True
                    try:
                        ap.check_formal_statement(a)
                    except Exception:  # noqa: BLE001
                        plain = False
                    row["plain_a"] = plain
                    if plain:
                        t1 = time.monotonic()
                        rv = pool.submit(
                            contextvars.copy_context().run, gate.review, model, p["statement"], a
                        )
                        row["proof"] = prove(worker, a)
                        row["agree"] = bool(b) and agree(worker, a, b)
                        row["review_approved"], row["review_issue"] = rv.result()
                        row["gate_extra_s"] = round(time.monotonic() - t1, 2)
                        row["gate_passed"] = bool(row["agree"] and row["review_approved"])
                        row["numerals_signal"] = gate.numerals_signal(p["statement"], a)
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fh.flush()
                    print(
                        p["id"],
                        row.get("proof", {}).get("proved"),
                        row.get("agree"),
                        row.get("review_approved"),
                        flush=True,
                    )
    print("load", os.getloadavg(), f"spend_est_usd={spend[0]:.4f}")
    worker.close()


if __name__ == "__main__":
    main()
