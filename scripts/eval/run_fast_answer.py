"""End to end for ``FastAnswer``: N concurrent merged calls, resident Lean race, verifier,
fidelity gate and explanation in parallel.  Records every model call (label, model, effort,
tokens, start/end) and the time to verified and to answer shown, per item and per variant.

    uv run python scripts/eval/run_fast_answer.py --out DIR --env-file F --name A
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/eval"))

from run_fast_variants import SETS, Recorder, instrumented_model  # noqa: E402

from pals_agent.fast_answer import FastAnswer  # noqa: E402
from pals_agent.lean import LeanVerifier  # noqa: E402
from pals_agent.lean_verifier.resident import ResidentConfig, ResidentLean  # noqa: E402


def main() -> None:
    from formalise import load_key  # noqa: PLC0415

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--items", choices=sorted(SETS), default="freshman_nl")
    parser.add_argument("--calls", type=int, default=3)
    parser.add_argument("--roundtrip", choices=["two_calls", "single"], default="single")
    parser.add_argument("--default", default="gpt-6-luna:none")
    parser.add_argument("--override", action="append", default=[])
    parser.add_argument("--gate-mode", default="classic")
    parser.add_argument("--race-budget", type=float, default=4.0)
    parser.add_argument("--no-speculative-gate", action="store_true")
    parser.add_argument("--no-explain", action="store_true")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--toolchain", default=str(Path.home() / ".elan/toolchains/leanprover--lean4---v4.32.0-rc1")
    )
    parser.add_argument("--project", type=Path, default=ROOT / "lean-workspace")
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    overrides = dict(item.split("=", 1) for item in args.override)
    lean = f"{args.toolchain}/bin/lean"
    lake = f"{args.toolchain}/bin/lake"
    lean_path = subprocess.run(
        [lake, "env", "printenv", "LEAN_PATH"],
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
        )
    )
    print("resident startup s", round(resident.start(), 2), "load", os.getloadavg(), flush=True)
    scratch = args.out / "scratch"
    scratch.mkdir(exist_ok=True)
    verifier = LeanVerifier(
        lean_binary=lean,
        lake_binary=lake,
        project_dir=args.project,
        child_path=f"{args.toolchain}/bin:/usr/bin:/bin",
        elan_home=str(Path.home() / ".elan"),
        scratch_dir=scratch,
        timeout_seconds=120.0,
        resident=resident,
    )
    recorder = Recorder()
    model = instrumented_model(load_key(args.env_file), recorder, args.default, overrides)
    fast = FastAnswer(
        resident,
        verifier,
        model,
        scratch,
        calls=args.calls,
        roundtrip=args.roundtrip,
        explain=not args.no_explain,
        gate_mode=args.gate_mode,
        speculative_gate=not args.no_speculative_gate,
        race_budget_s=args.race_budget,
    )
    problems = json.loads((ROOT / "testdata/generation-eval-v1/manifest.json").read_text())[
        "problems"
    ]
    with (args.out / f"{args.name}.jsonl").open("a") as fh:
        for repeat in range(args.repeats):
            for pid in SETS[args.items]:
                p = next(x for x in problems if x["id"].startswith(pid))
                if p.get("fixed_lean_statement"):
                    continue  # catalog statements take the FastLane path, not this one
                if p["split"] != "tuning":
                    continue  # held_out is opened only for a final comparison with a stated reason
                recorder.reset()
                r = fast.run(p["statement"], p["language"])
                row = {
                    "variant": args.name,
                    "id": pid,
                    "repeat": repeat,
                    "tier": p["tier"],
                    "field": p["field"],
                    "language": p["language"],
                    "outcome": r.outcome,
                    "reason": r.reason,
                    "kind": r.kind,
                    "answer": r.answer,
                    "tactic": r.tactic,
                    "tactic_text": r.tactic_text,
                    "verified": r.verified,
                    "formal": r.formal,
                    "proved": r.proved,
                    "explanation": r.explanation,
                    "request": p["statement"],
                    "seconds": r.seconds,
                    "statements": r.statements,
                    "gate": None
                    if r.gate is None
                    else {
                        "passed": r.gate.passed,
                        "reasons": r.gate.reasons,
                        "agree": r.gate.agree,
                        "reviewed": r.gate.reviewed,
                        "roundtrip": r.gate.roundtrip,
                        "issue": r.gate.review_issue,
                        "rt_issue": r.gate.roundtrip_issue,
                    },
                    "calls": list(recorder.events),
                }
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                print(pid[:34], r.outcome, r.kind, r.tactic, r.reason, r.seconds, flush=True)
                time.sleep(0.2)
    print("load", os.getloadavg(), flush=True)
    resident.close()


if __name__ == "__main__":
    main()
