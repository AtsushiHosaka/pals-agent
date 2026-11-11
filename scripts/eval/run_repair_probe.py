"""Can one or two fast repair rounds (compiler error fed back, Luna) close what one call did not?

For the statements the merged call left open: round 0 = the merged call's candidates raced with
the portfolio; each further round sends the statement, the failed script and the first compiler
errors to the model (several scripts back) and races them.  Reports closure and seconds per round.

    uv run python scripts/eval/run_repair_probe.py --out DIR --env-file F --effort none
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/eval"))

from run_fast_variants import SETS, Recorder, instrumented_model  # noqa: E402

from pals_agent import automation_portfolio as ap  # noqa: E402
from pals_agent import fast_answer as fa  # noqa: E402
from pals_agent.fast_lane import candidate_source  # noqa: E402
from pals_agent.lean_verifier.resident import (  # noqa: E402
    ResidentConfig,
    ResidentLean,
    ResidentWorker,
)

REPAIR_PROMPT = (
    "A Lean 4 (Mathlib) proof attempt failed. STATEMENT is the theorem; ATTEMPTS are tactic "
    "proofs (the text after `:= by`) with the first compiler errors of each. Reply with JSON "
    "`tactics`: up to 3 DIFFERENT complete corrected tactic proofs (lines separated by \\n; no "
    "`sorry`, no comments, no `import`). Prefer Mathlib lemmas that exist for the exact shape of "
    "the goal.\n\n"
)
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["tactics"],
    "properties": {"tactics": {"type": "array", "items": {"type": "string"}}},
}


def main() -> None:
    from formalise import load_key  # noqa: PLC0415

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--effort", default="none")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument(
        "--toolchain", default=str(Path.home() / ".elan/toolchains/leanprover--lean4---v4.32.0-rc1")
    )
    parser.add_argument("--project", type=Path, default=ROOT / "lean-workspace")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    lean_path = subprocess.run(
        [f"{args.toolchain}/bin/lake", "env", "printenv", "LEAN_PATH"], cwd=args.project,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    resident = ResidentLean(ResidentConfig(
        lean_binary=f"{args.toolchain}/bin/lean", lean_path=lean_path,
        build_dir=args.out / "resident", max_children=8, queue_timeout_s=30.0, warm_exact=True,
    ))
    resident.start()
    worker = ResidentWorker(resident, scratch_dir=args.out)
    model = instrumented_model(load_key(args.env_file), Recorder(), f"gpt-6-luna:{args.effort}", {})
    problems = json.loads((ROOT / "testdata/generation-eval-v1/manifest.json").read_text())[
        "problems"
    ]
    rows = []
    for pid in SETS["eval"]:
        p = next(x for x in problems if x["id"].startswith(pid))
        t0 = time.monotonic()
        m = fa.merged_call(model, p["statement"])
        if m.kind not in {"prove", "decide"} or not m.formal:
            continue
        try:
            prop = ap.check_formal_statement(m.formal)
        except Exception:  # noqa: BLE001
            continue
        scripts = list(m.tactics)
        closed, round_no = None, 0
        while True:
            if round_no == 0:
                tactics = [*fa.model_tactics(scripts), *ap.PORTFOLIO]
            else:
                tactics = fa.model_tactics(scripts, f"r{round_no}")
            header = len("import Mathlib\n")
            sources = [candidate_source(prop, t)[header:] for t in tactics]
            ok = [fa.acceptable_source(s) for s in sources]

            def clean(i: int, out: str, ok: list[bool] = ok) -> bool:
                return ok[i] and "error" not in out.lower() and "sorry" not in out.lower()

            done = worker.check_race(
                [s if good else "" for s, good in zip(sources, ok, strict=True)],
                clean,
                timeout_s=4.0,
            )
            win = [i for i, o in sorted(done.items()) if clean(i, o)]
            if win:
                closed = tactics[win[0]].name
                break
            round_no += 1
            if round_no > args.rounds or not scripts:
                break
            attempts = "\n\n".join(
                f"ATTEMPT {i}:\n{t.text}\nERRORS:\n{done.get(i, '')[:500]}"
                for i, t in enumerate(tactics[: len(scripts)])
            )
            out = model(REPAIR_PROMPT + f"STATEMENT: {prop}\n\n{attempts}\n", SCHEMA)
            scripts = fa._scripts(out.get("tactics"))
        row = {"id": pid, "statement": prop, "closed_by": closed, "round": round_no,
               "seconds": round(time.monotonic() - t0, 2), "kind": m.kind}
        rows.append(row)
        print(pid[:34], closed, round_no, row["seconds"], flush=True)
    (args.out / "repair.json").write_text(json.dumps(rows, ensure_ascii=False))
    resident.close()


if __name__ == "__main__":
    main()
