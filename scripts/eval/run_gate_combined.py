"""The `terse2` gate as a whole on the adversarial set (without the Lean agreement check).

A statement passes when both terse reviews approve (the second told to look for a difference)
and the structure and triviality checks are quiet.  Reports false accepts (weakened statements
that pass) and false rejects (faithful statements that fail), with the ids.

    uv run python scripts/eval/run_gate_combined.py --out DIR --env-file F --effort none --repeat 3
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import contextvars
import json
import sys
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
    ap.add_argument("--effort", default="none")
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    model = instrumented_model(load_key(args.env_file), Recorder(), f"gpt-6-luna:{args.effort}", {})
    cases = json.loads((ROOT / "testdata/fidelity-adversarial-v1/cases.json").read_text())["cases"]
    items = [
        (c["id"], label, c["request"], c[label]) for c in cases for label in ("bad", "faithful")
    ]

    def passes(item: tuple[str, str, str, str]) -> bool:
        _, _, request, formal = item
        a, _ = fa.terse_review(model, request, formal)
        b, _ = fa.terse_review(model, request, formal, skeptical=True)
        quiet = not gate.structure_check(request, formal) and not gate.triviality_check(formal)
        return a and b and quiet

    pool = futures.ThreadPoolExecutor(max_workers=4)
    jobs = [
        (it, pool.submit(contextvars.copy_context().run, passes, it))
        for _ in range(args.repeat)
        for it in items
    ]
    rows = [{"id": it[0], "label": it[1], "passed": job.result()} for it, job in jobs]
    (args.out / f"combined_{args.effort}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n"
    )
    bad = [r for r in rows if r["label"] == "bad"]
    good = [r for r in rows if r["label"] == "faithful"]
    accepted = sorted({r["id"] for r in bad if r["passed"]})
    rejected = sorted({r["id"] for r in good if not r["passed"]})
    print(
        args.effort,
        "false-accept",
        sum(r["passed"] for r in bad),
        "/",
        len(bad),
        accepted,
        "false-reject",
        sum(not r["passed"] for r in good),
        "/",
        len(good),
        rejected,
    )


if __name__ == "__main__":
    main()
