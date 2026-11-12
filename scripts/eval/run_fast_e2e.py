"""End to end on the resident Lean: stage 0 (formalise -> portfolio -> gate -> explanation) with
every Lean call answered by a forked child of one warm Mathlib process, then the EXISTING verifier
(policy + compile + trusted audit, also on the resident worker) on the answered theorem.

Per item: outcome, seconds per phase (formalise / portfolio / total of stage 0), the time the
trusted audit takes afterwards, and the wall time to "answer shown" = stage 0 + verifier.
Paid: Luna/low model calls only (a few per item).  The key is read from the env file's single
variable; spend is estimated and the run stops at --max-usd.  Prints the machine load.

    uv run python scripts/eval/run_fast_e2e.py --out DIR --env-file ENVFILE --set freshman
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

from _resident_eval import confinement_kwargs  # noqa: E402

from pals_agent import automation_portfolio as ap  # noqa: E402
from pals_agent import fidelity_gate as gate  # noqa: E402
from pals_agent import general_recipe_lane as lane  # noqa: E402
from pals_agent import stage0  # noqa: E402
from pals_agent.lean import LeanVerifier  # noqa: E402
from pals_agent.lean_verifier.resident import (  # noqa: E402
    ResidentConfig,
    ResidentLean,
    ResidentWorker,
)

FRESHMAN = [
    "calculus_v3_limit_fixed_shift", "calculus_v3_limit_order", "la_reuse_kernel_detects_zero",
    "la_v5_matrix_of_composition", "ode_separable_zero_solution",
    "pq-absolute-value-nondifferentiability", "seed-cubic_derivative",
    "seed-determinant_nonzero_decision", "seed-linear_system_inconsistent",
    "seed-reciprocal_derivative", "seed-quadratic_not_injective", "seed-projection_not_injective",
    "pq-sum-of-first-n-integers",
]
UNDERGRAD = [
    "nt_bezout_101_37", "exlog_exp_strictly_positive", "trig_expand_difference_square_le_two",
    "disc_size_difference_closed", "la_v2_distinct_eigenspaces_intersection",
    "calculus_v5_derivative_difference_quotient", "mv_foundation_nondifferentiable_minimum",
    "calculus_v2_integral_scalar_linearity",
]


def main() -> None:
    from formalise import load_key  # noqa: PLC0415

    from pals_agent.evals.runner import estimate_usd  # noqa: PLC0415
    from pals_agent.usage import usage_scope  # noqa: PLC0415

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--set", choices=["freshman", "undergrad", "both"], default="freshman")
    parser.add_argument("--max-usd", type=float, default=0.8)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--warm-exact", action="store_true")
    parser.add_argument("--max-children", type=int, default=8)
    parser.add_argument(
        "--toolchain",
        default=str(Path.home() / ".elan/toolchains/leanprover--lean4---v4.32.0-rc1"),
    )
    parser.add_argument("--project", type=Path, default=ROOT / "lean-workspace")
    parser.add_argument("--budget-given", type=float, default=stage0.BUDGET_GIVEN_S)
    parser.add_argument("--budget-formalised", type=float, default=stage0.BUDGET_FORMALISED_S)
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    spend = [0.0]

    def add(row: dict) -> None:
        spend[0] += estimate_usd(row["model"], row["input_tokens"], row["output_tokens"]) or 0.0

    lean = f"{args.toolchain}/bin/lean"
    lake = f"{args.toolchain}/bin/lake"
    lean_path = subprocess.run(
        [lake, "env", "printenv", "LEAN_PATH"], cwd=args.project, capture_output=True, text=True,
        check=True,
    ).stdout.strip()
    resident = ResidentLean(
        ResidentConfig(
            project_dir=args.project,
            lean_binary=lean, lean_path=lean_path, build_dir=args.out / "resident",
            max_children=args.max_children, queue_timeout_s=30.0, warm_exact=args.warm_exact,
            **confinement_kwargs(lean, lean_path, args.out / "scratch"),
        )
    )
    startup = resident.start()
    print("resident startup s", round(startup, 2), "load", os.getloadavg(), flush=True)
    scratch = args.out / "scratch"
    scratch.mkdir(exist_ok=True)
    verifier = LeanVerifier(
        lean_binary=lean, lake_binary=lake, project_dir=args.project,
        child_path=f"{args.toolchain}/bin:/usr/bin:/bin", elan_home=str(Path.home() / ".elan"),
        scratch_dir=scratch, timeout_seconds=120.0, resident=resident,
    )
    pool = lane.load_fixture_recipes(ROOT / "testdata")
    model = gate.openai_model_call(load_key(args.env_file))
    s0 = stage0.Stage0(
        ResidentWorker(resident, scratch_dir=scratch), pool, model, require_flags=False,
        worker_factory=lambda: ResidentWorker(resident, scratch_dir=scratch), prefetch=False,
    )
    problems = {
        p["id"]: p
        for p in json.loads((ROOT / "testdata/generation-eval-v1/manifest.json").read_text())[
            "problems"
        ]
    }
    ids = {"freshman": FRESHMAN, "undergrad": UNDERGRAD, "both": FRESHMAN + UNDERGRAD}[args.set]
    rows = []
    with usage_scope(add), (args.out / "fast_e2e.jsonl").open("w") as fh:
        for repeat in range(args.repeats):
            for pid in ids:
                if spend[0] >= args.max_usd:
                    print("budget reached", spend[0], flush=True)
                    break
                p = next(v for k, v in problems.items() if k.startswith(pid))
                given = p.get("fixed_lean_statement")
                t0 = time.monotonic()
                r = s0.run(
                    p["statement"], p["language"], formal=given or None,
                    budget_s=args.budget_given if given else args.budget_formalised,
                )
                stage0_s = time.monotonic() - t0
                verified = None
                audit_s = None
                if r.outcome == "answered" and r.formal_proved:
                    t1 = time.monotonic()
                    try:
                        prop = ap.check_formal_statement(r.formal_proved, allow_header=bool(given))
                        tactic = next((t for t in ap.PORTFOLIO if t.name == r.by), None)
                        if tactic is not None:
                            from pals_agent.fast_lane import candidate_source  # noqa: PLC0415

                            res = verifier.verify(candidate_source(prop, tactic))
                            verified = res.success
                    except Exception as error:  # noqa: BLE001
                        verified = f"error:{type(error).__name__}"
                    audit_s = time.monotonic() - t1
                row = {
                    "id": pid, "repeat": repeat, "tier": p["tier"], "field": p["field"],
                    "formal_source": r.formal_source, "outcome": r.outcome, "reason": r.reason,
                    "by": r.by, "stage0_s": round(stage0_s, 2), "seconds": r.seconds,
                    "verifier_audit_s": None if audit_s is None else round(audit_s, 2),
                    "verifier_success": verified,
                    "shown_s": round(stage0_s + (audit_s or 0), 2),
                    "model_calls": r.model_calls, "formal": r.formal,
                }
                rows.append(row)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                print(pid, r.outcome, r.by, r.reason, row["stage0_s"], row["verifier_audit_s"],
                      verified, flush=True)
    print("load", os.getloadavg(), f"spend_est_usd={spend[0]:.4f}")
    s0.close()
    resident.close()


if __name__ == "__main__":
    main()
