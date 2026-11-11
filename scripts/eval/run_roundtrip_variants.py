"""Choose the round-trip variant: two serial calls, one structured call, and the plain review.

Measures false-accept on the adversarial weakened statements (19 cases) and false-reject on
faithful statements (the 19 faithful forms plus the faithful formalisations found earlier), and
latency per variant.  Each variant is run 1 time per statement (set --repeat for more).

    uv run python scripts/eval/run_roundtrip_variants.py --out DIR --env-file ENVFILE \
        [--faithful-jsonl gate-items.jsonl]
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import contextvars
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/eval"))

from pals_agent import fidelity_gate as gate  # noqa: E402


def main() -> None:
    from formalise import load_key  # noqa: PLC0415

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--env-file", type=Path)
    ap.add_argument("--faithful-jsonl", type=Path)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--effort", default=None)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    model = gate.openai_model_call(load_key(args.env_file), effort=args.effort)
    cases = json.loads((ROOT / "testdata/fidelity-adversarial-v1/cases.json").read_text())["cases"]
    items: list[dict] = []
    for c in cases:
        lang = "ja" if any(ord(ch) > 0x3000 for ch in c["request"]) else "en"
        items.append(
            {
                "id": c["id"],
                "label": "bad",
                "request": c["request"],
                "formal": c["bad"],
                "lang": lang,
            }
        )
        items.append(
            {
                "id": c["id"],
                "label": "faithful",
                "request": c["request"],
                "formal": c["faithful"],
                "lang": lang,
            }
        )
    if args.faithful_jsonl:
        manifest = {
            p["id"]: p
            for p in json.loads((ROOT / "testdata/generation-eval-v1/manifest.json").read_text())[
                "problems"
            ]
        }
        for line in args.faithful_jsonl.read_text().splitlines():
            r = json.loads(line)
            if r.get("proof", {}).get("proved") and r["id"] != "seed-rank_nullity":
                p = manifest[r["id"]]
                items.append(
                    {
                        "id": r["id"],
                        "label": "faithful",
                        "request": p["statement"],
                        "formal": r["formal_a"],
                        "lang": p["language"],
                    }
                )
    variants = {
        "review": lambda it: gate.review(model, it["request"], it["formal"]),
        "roundtrip_two_calls": lambda it: gate.roundtrip(
            model, it["request"], it["formal"], it["lang"]
        ),
        "roundtrip_single": lambda it: gate.roundtrip_single(
            model, it["request"], it["formal"], it["lang"]
        ),
    }
    pool = futures.ThreadPoolExecutor(max_workers=args.workers)
    rows = []
    for rep in range(args.repeat):
        jobs = []
        for it in items:
            for name, fn in variants.items():

                def run(fn=fn, it=it):
                    t0 = time.monotonic()
                    ok, issue = fn(it)
                    return ok, issue, round(time.monotonic() - t0, 2)

                jobs.append((it, name, pool.submit(contextvars.copy_context().run, run)))
        for it, name, job in jobs:
            try:
                ok, issue, seconds = job.result()
            except Exception as error:  # noqa: BLE001
                ok, issue, seconds = False, type(error).__name__, None
            rows.append(
                {
                    "id": it["id"],
                    "label": it["label"],
                    "variant": name,
                    "approved": ok,
                    "seconds": seconds,
                    "issue": issue,
                    "rep": rep,
                }
            )
    with (args.out / "variants.jsonl").open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    for name in variants:
        bad = [r for r in rows if r["variant"] == name and r["label"] == "bad"]
        good = [r for r in rows if r["variant"] == name and r["label"] == "faithful"]
        secs = sorted(r["seconds"] for r in rows if r["variant"] == name and r["seconds"])
        print(
            name,
            "false-accept",
            sum(r["approved"] for r in bad),
            "/",
            len(bad),
            "false-reject",
            sum(not r["approved"] for r in good),
            "/",
            len(good),
            "latency p50",
            secs[len(secs) // 2],
            "p90",
            secs[int(0.9 * len(secs))],
        )


if __name__ == "__main__":
    main()
