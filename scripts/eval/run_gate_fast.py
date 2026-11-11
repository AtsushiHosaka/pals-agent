"""Gate variants on the adversarial set: false accepts, false rejects, latency (model effort).

Compares the pipeline's review, the single-call round trip and the terse review at given efforts
on 19 weakened statements (must be rejected) and their 19 faithful forms (should be approved).

    uv run python scripts/eval/run_gate_fast.py --out DIR --env-file F --effort none
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

from run_fast_variants import Recorder, instrumented_model  # noqa: E402

from pals_agent import fast_answer as fa  # noqa: E402
from pals_agent import fidelity_gate as gate  # noqa: E402


def main() -> None:
    from formalise import load_key  # noqa: PLC0415

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--env-file", type=Path)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    model = instrumented_model(load_key(args.env_file), Recorder(), f"gpt-6-luna:{args.effort}", {})
    cases = json.loads((ROOT / "testdata/fidelity-adversarial-v1/cases.json").read_text())["cases"]
    items = []
    for c in cases:
        lang = "ja" if any(ord(ch) > 0x3000 for ch in c["request"]) else "en"
        for label, key in (("bad", "bad"), ("faithful", "faithful")):
            items.append((c["id"], label, c["request"], c[key], lang))
    variants = {
        "review": lambda i: gate.review(model, i[2], i[3]),
        "review_terse": lambda i: fa.terse_review(model, i[2], i[3]),
        "roundtrip_single": lambda i: gate.roundtrip_single(model, i[2], i[3], i[4]),
        "roundtrip_terse": lambda i: fa.terse_roundtrip(model, i[2], i[3], i[4]),
    }
    pool = futures.ThreadPoolExecutor(max_workers=4)
    rows = []
    for _ in range(args.repeat):
        jobs = []
        for it in items:
            for name, fn in variants.items():

                def run(fn=fn, it=it):
                    t0 = time.monotonic()
                    ok, _ = fn(it)
                    return ok, round(time.monotonic() - t0, 2)

                jobs.append((it, name, pool.submit(contextvars.copy_context().run, run)))
        for it, name, job in jobs:
            try:
                ok, seconds = job.result()
            except Exception:  # noqa: BLE001
                ok, seconds = False, None
            rows.append({"id": it[0], "label": it[1], "variant": name, "approved": ok,
                         "seconds": seconds})
    (args.out / f"gate_{args.effort}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    )
    for name in variants:
        bad = [r for r in rows if r["variant"] == name and r["label"] == "bad"]
        good = [r for r in rows if r["variant"] == name and r["label"] == "faithful"]
        secs = sorted(r["seconds"] for r in rows if r["variant"] == name and r["seconds"])
        print(args.effort, name, "false-accept", sum(r["approved"] for r in bad), "/", len(bad),
              "false-reject", sum(not r["approved"] for r in good), "/", len(good),
              "p50", secs[len(secs) // 2], "p90", secs[int(len(secs) * 0.9)], flush=True)


if __name__ == "__main__":
    main()
