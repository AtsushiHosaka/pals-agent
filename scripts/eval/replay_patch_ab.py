"""Paired A/B of the patch-repair prompt on the same failed first candidates.

Each failed first candidate that a measurement run saved (``art/<run>/result.lean``) is compiled
once for its diagnostics, then repaired once per arm (``PALS_T2_REPAIR_HINTS_ENABLED`` off, then
on) by the real ``generate_patch`` at the role's own effort, and the patched source is compiled.
Same inputs in both arms, so the comparison is paired. Needs OPENAI_API_KEY; stops at --max-usd.
Output (local, holds Lean source and statements: keep it out of git): one JSON line per case.

    replay_patch_ab.py --runs DIR [DIR ...] --problems FILE --out FILE --max-usd 0.6 \
        --lean L --lake K --project P --elan-home H
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from tempfile import mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=Path, nargs="+", required=True)
    ap.add_argument("--problems", type=Path, required=True, help="dev_unseen.json (dev items only)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-usd", type=float, required=True)
    for name in ("lean", "lake", "project", "elan-home"):
        ap.add_argument(f"--{name}", required=True)
    args = ap.parse_args()

    from pals_agent import t2_lane
    from pals_agent.evals.runner import estimate_usd
    from pals_agent.generator import HybridLeanGenerator
    from pals_agent.lean import LeanVerifier
    from pals_agent.lean_verifier.resident import ResidentConfig, ResidentLean
    from pals_agent.lean_verifier.resident.manager import default_read_roots
    from pals_agent.models import Diagnostic, GenerationFeedback, ProofRequest
    from pals_agent.openai import OpenAIResponsesClient
    from pals_agent.usage import usage_scope

    problems = {p["id"]: p for p in json.loads(args.problems.read_text())["problems"]}
    if any(p["split"] != "dev_unseen" for p in problems.values()):
        raise SystemExit("problems file must contain dev_unseen items only")
    lean_path = subprocess.run(
        [args.lake, "env", "printenv", "LEAN_PATH"],
        cwd=args.project, capture_output=True, text=True, check=True,
    ).stdout.strip()
    scratch = Path(mkdtemp(prefix="pals-replay-"))
    resident = ResidentLean(ResidentConfig(
        project_dir=Path(args.project), confine=False, request_root=scratch,
        read_roots=default_read_roots(args.lean, lean_path), lean_binary=args.lean,
        lean_path=lean_path, build_dir=scratch / "resident", max_children=2, warm_exact=False,
        queue_timeout_s=60.0,
    ))
    resident.start()
    verifier = LeanVerifier(
        lean_binary=args.lean, lake_binary=args.lake, project_dir=Path(args.project),
        child_path=f"{Path(args.lean).parent}:/usr/bin:/bin", elan_home=args.elan_home,
        scratch_dir=scratch, timeout_seconds=300.0, resident=resident,
    )
    client = OpenAIResponsesClient(
        api_key=os.environ["OPENAI_API_KEY"], timeout_seconds=240.0, max_output_tokens=12000,
    )
    generator = HybridLeanGenerator(
        model="gpt-6.1-terra", provider="openai", client=client, use_release_role_bindings=True
    )
    spent = [0.0]

    def on_usage(row: dict) -> None:
        spent[0] += estimate_usd(row["model"], row["input_tokens"], row["output_tokens"]) or 0.0

    cases = []
    for run in args.runs:
        for rec in map(json.loads, (run / "records.jsonl").read_text().splitlines()):
            if rec["first_attempt_ok"] or not rec["submits"] or rec["problem_id"] not in problems:
                continue
            src = run / "art" / f"hsim-{rec['arm']}-{rec['problem_id']}" / "result.lean"
            if src.exists():
                cases.append((run.name, rec["problem_id"], src.read_text()))
    print(f"{len(cases)} failed first candidates", flush=True)
    with args.out.open("w") as out:
        for run, pid, code in cases:
            first = verifier.verify(code)
            if first.success:
                continue
            marker = Diagnostic(
                severity="error", code="verifier_compile_failed",
                message="The Lean compiler rejected the candidate.",
            )
            feedback = GenerationFeedback(
                attempt=1, previous_lean_code=code,
                diagnostics=(marker, *first.diagnostics),
            )
            request = ProofRequest(id=pid, prompt=problems[pid]["statement"])
            row = {"run": run, "problem_id": pid}
            for arm, flag in (("plain", "false"), ("hints", "true")):
                if spent[0] >= args.max_usd:
                    print("budget reached", flush=True)
                    return
                os.environ[t2_lane.REPAIR_HINTS_ENV] = flag
                started = time.monotonic()
                with usage_scope(on_usage):
                    patched = generator.generate_patch(request, feedback)
                took = round(time.monotonic() - started, 1)
                ok = False
                if patched is not None:
                    ok = bool(verifier.verify(patched.lean_code).success)
                row[arm] = {"patched": patched is not None, "ok": ok, "s": took}
            out.write(json.dumps(row) + "\n")
            out.flush()
            print(pid, row["plain"], row["hints"], f"spent={spent[0]:.3f}", flush=True)
    resident.close()
    print(f"DONE spent={spent[0]:.3f}", flush=True)


if __name__ == "__main__":
    main()
