"""Recompile the first candidate of every problem a measurement run failed on the first try.

The measurement driver keeps each run's first submitted source (``art/<run>/result.lean``) but not
the Lean diagnostics of a failed compile. This re-runs the resident Lean on those sources (no model
call, no cost) and writes the diagnostics, so failures can be classified from Lean's own words.
Output goes to a local file (it holds Lean messages and source excerpts: keep it out of git).

    recheck_first_candidates.py --runs DIR [DIR ...] --out FILE --lean L --lake K --project P \
        --elan-home H
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from tempfile import mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=Path, nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--hygiene", action="store_true", help="apply normalise_source_header first")
    for name in ("lean", "lake", "project", "elan-home"):
        ap.add_argument(f"--{name}", required=True)
    args = ap.parse_args()

    from pals_agent.lean import LeanVerifier
    from pals_agent.lean_verifier.resident import ResidentConfig, ResidentLean
    from pals_agent.lean_verifier.resident.manager import default_read_roots

    lean_path = subprocess.run(
        [args.lake, "env", "printenv", "LEAN_PATH"],
        cwd=args.project, capture_output=True, text=True, check=True,
    ).stdout.strip()
    scratch = Path(mkdtemp(prefix="pals-recheck-"))
    resident = ResidentLean(
        ResidentConfig(
            project_dir=Path(args.project), confine=False, request_root=scratch,
            read_roots=default_read_roots(args.lean, lean_path), lean_binary=args.lean,
            lean_path=lean_path, build_dir=scratch / "resident", max_children=2,
            warm_exact=False, queue_timeout_s=60.0,
        )
    )
    resident.start()
    verifier = LeanVerifier(
        lean_binary=args.lean, lake_binary=args.lake, project_dir=Path(args.project),
        child_path=f"{Path(args.lean).parent}:/usr/bin:/bin", elan_home=args.elan_home,
        scratch_dir=scratch, timeout_seconds=300.0, resident=resident,
    )
    rows = []
    for run in args.runs:
        for rec in map(json.loads, (run / "records.jsonl").read_text().splitlines()):
            if rec["first_attempt_ok"] or not rec["submits"]:
                continue
            source = run / "art" / f"hsim-{rec['arm']}-{rec['problem_id']}" / "result.lean"
            if not source.exists():
                continue
            code = source.read_text()
            if args.hygiene:
                from pals_agent.lean_hygiene import normalise_source_header

                code = normalise_source_header(code)
            result = verifier.verify(code)
            errors = [d for d in result.diagnostics if d.severity == "error"]
            rows.append({
                "run": run.name, "problem_id": rec["problem_id"], "compiled": result.success,
                "errors": [{"code": d.code, "message": d.message[:600]} for d in errors[:4]],
                "n_errors": len(errors),
            })
            status = "ok" if result.success else f"{len(errors)} errors"
            print(rec["problem_id"], status, flush=True)
    args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    resident.close()


if __name__ == "__main__":
    main()
