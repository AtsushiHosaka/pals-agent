"""Can ONE model call give the statement and a proof that Lean accepts, and how long is it?

For each item: the merged call (statement + up to 3 proofs, +3 for the negation of a question) at
a given effort, then every candidate and the automation portfolio raced on the resident Lean.
Reports the call's seconds/tokens, which candidate closed the statement and when.  No gate here.

    uv run python scripts/eval/run_merged_probe.py --out DIR --env-file F --effort none
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/eval"))

from _resident_eval import confinement_kwargs  # noqa: E402
from run_fast_variants import SETS, Recorder, instrumented_model  # noqa: E402

from pals_agent import automation_portfolio as ap  # noqa: E402
from pals_agent import fast_answer as fa  # noqa: E402
from pals_agent.fast_lane import candidate_source  # noqa: E402
from pals_agent.lean_verifier.resident import (  # noqa: E402
    ResidentConfig,
    ResidentLean,
    ResidentWorker,
)


def main() -> None:
    from formalise import load_key  # noqa: PLC0415

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--effort", default="low")
    parser.add_argument("--model", default="")
    parser.add_argument("--parallel", type=int, default=1, help="concurrent merged calls")
    parser.add_argument("--items", choices=sorted(SETS), default="freshman_nl")
    parser.add_argument(
        "--toolchain", default=str(Path.home() / ".elan/toolchains/leanprover--lean4---v4.32.0-rc1")
    )
    parser.add_argument("--project", type=Path, default=ROOT / "lean-workspace")
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    lean = f"{args.toolchain}/bin/lean"
    lean_path = subprocess.run(
        [f"{args.toolchain}/bin/lake", "env", "printenv", "LEAN_PATH"],
        cwd=args.project,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    resident = ResidentLean(
        ResidentConfig(
            project_dir=args.project,
            lean_binary=lean,
            lean_path=lean_path,
            build_dir=args.out / "resident",
            max_children=8,
            queue_timeout_s=30.0,
            warm_exact=True,
            **confinement_kwargs(lean, lean_path, args.out),
        )
    )
    resident.start()
    worker = ResidentWorker(resident, scratch_dir=args.out)
    recorder = Recorder()
    spec = f"{args.model}:{args.effort}"
    model = instrumented_model(load_key(args.env_file), recorder, spec, {})
    problems = json.loads((ROOT / "testdata/generation-eval-v1/manifest.json").read_text())[
        "problems"
    ]
    rows = []
    for pid in SETS[args.items]:
        p = next(x for x in problems if x["id"].startswith(pid))
        if p.get("fixed_lean_statement"):
            continue
        recorder.reset()
        t0 = time.monotonic()
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            request = p["statement"]
            calls = list(
                pool.map(lambda _, r=request: fa.merged_call(model, r), range(args.parallel))
            )
        call_s = time.monotonic() - t0
        m = calls[0]
        # the candidates of all calls (the statements must agree to share a race: the first call's
        # statement is used, the others only contribute proofs when they wrote the same text)
        for other in calls[1:]:
            if other.formal == m.formal:
                m.tactics = [*m.tactics, *other.tactics]
                m.negation_tactics = [*m.negation_tactics, *other.negation_tactics]
        row = {
            "id": pid,
            "effort": args.effort,
            "call_s": round(call_s, 2),
            "kind": m.kind,
            "formal": m.formal,
            "tactics": m.tactics,
            "neg": m.negation_tactics,
            "tokens": recorder.events[0]["output_tokens"] if recorder.events else None,
            "same_statement": sum(c.formal == m.formal for c in calls),
            "closed_by": None,
            "race_s": None,
        }
        if m.kind in {"prove", "decide"} and m.formal:
            statements = [(m.formal, fa.model_tactics(m.tactics))]
            if m.kind == "decide":
                statements.append((f"¬ ({m.formal})", fa.model_tactics(m.negation_tactics, "neg")))
            for statement, extra in statements:
                try:
                    proposition = ap.check_formal_statement(statement)
                except Exception:  # noqa: BLE001
                    continue
                tactics = [*extra, *ap.PORTFOLIO]
                header = len("import Mathlib\n")
                sources = [candidate_source(proposition, t)[header:] for t in tactics]
                ok = [fa.acceptable_source(s) for s in sources]
                t1 = time.monotonic()
                done = worker.check_race(
                    [s if good else "" for s, good in zip(sources, ok, strict=True)],
                    lambda i, out, ok=ok: (
                        ok[i] and "error" not in out.lower() and "sorry" not in out.lower()
                    ),
                    timeout_s=20.0,
                )
                winners = [
                    tactics[i].name
                    for i, out in sorted(done.items())
                    if ok[i] and "error" not in out.lower() and "sorry" not in out.lower()
                ]
                if winners:
                    row["closed_by"] = f"{'neg:' if statement.startswith('¬') else ''}{winners[0]}"
                    row["race_s"] = round(time.monotonic() - t1, 2)
                    break
        rows.append(row)
        print(
            pid[:34],
            args.effort,
            m.kind,
            row["call_s"],
            row["tokens"],
            row["closed_by"],
            row["race_s"],
            "same",
            row["same_statement"],
            flush=True,
        )
    name = f"merged_{args.effort}_p{args.parallel}.json"
    (args.out / name).write_text(json.dumps(rows, ensure_ascii=False))
    resident.close()


if __name__ == "__main__":
    main()
