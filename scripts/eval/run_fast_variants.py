"""Model-time breakdown and variants of stage 0 on the resident Lean.

Every model call is recorded: label, model, reasoning effort, prompt characters, input/output
tokens, start and end offsets from the start of the request (so serial and parallel calls can be
read off), then the stage-0 result and the existing verifier's audit of the answered theorem.

Variants (all flags are arguments of this script, nothing changes in the product):
  --roundtrip two_calls|single          back-translation then compare, or one call
  --override LABEL=MODEL:EFFORT         per-call model/effort; labels: formalise, review,
                                        backtranslate, compare, roundtrip_single
  --default MODEL:EFFORT                everything else (default: the pipeline's judge binding)

    uv run python scripts/eval/run_fast_variants.py --out DIR --env-file F --name V0
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/eval"))

from pals_agent import automation_portfolio as ap  # noqa: E402
from pals_agent import general_recipe_lane as lane  # noqa: E402
from pals_agent import stage0  # noqa: E402
from pals_agent.fast_lane import candidate_source  # noqa: E402
from pals_agent.lean import LeanVerifier  # noqa: E402
from pals_agent.lean_verifier.resident import (  # noqa: E402
    ResidentConfig,
    ResidentLean,
    ResidentWorker,
)

LABELS = (
    ("Classify the request, translate it into Lean 4 (Mathlib) and give", "merged"),
    ("Classify the request", "formalise"),
    (
        "You review a formalisation. REQUEST is what a learner asked. STATEMENT is a Lean 4 "
        "(Mathlib) proposition that will be proved. Approve only if STATEMENT is exactly the "
        "mathematical claim of REQUEST: same",
        "review_terse",
    ),
    ("You review a formalisation", "review"),
    ("Describe in plain", "backtranslate"),
    ("REQUEST is what a learner asked. DESCRIPTION", "compare"),
    ("A learner asked REQUEST", "roundtrip_single"),
    ("Write the explanation of a result", "explain"),
)


def label_of(prompt: str) -> str:
    return next((name for prefix, name in LABELS if prompt.startswith(prefix)), "other")


class Recorder:
    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.events: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def reset(self) -> None:
        with self.lock:
            self.t0 = time.monotonic()
            self.events = []


def instrumented_model(key: str, recorder: Recorder, default: str, overrides: dict[str, str]):
    from pals_agent.model_roles import ModelRole, fixed_model_default  # noqa: PLC0415
    from pals_agent.openai import OpenAIResponsesClient  # noqa: PLC0415
    from pals_agent.usage import usage_scope  # noqa: PLC0415

    binding = fixed_model_default(ModelRole.PROOF_REUSE_JUDGE)
    base = OpenAIResponsesClient(api_key=key, timeout_seconds=60.0, max_output_tokens=3000)

    def parse(spec: str) -> tuple[str, str]:
        if not spec:
            return binding.model, binding.reasoning_effort
        model, _, effort = spec.partition(":")
        return model or binding.model, effort or binding.reasoning_effort

    def call(prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        label = label_of(prompt)
        model, effort = parse(overrides.get(label, default))
        client = dataclasses.replace(base, reasoning_effort=effort)  # type: ignore[arg-type]
        rows: list[dict[str, Any]] = []
        start = time.monotonic()
        error = None
        try:
            with usage_scope(rows.append):
                raw = client.generate(
                    model=model, prompt=prompt, response_schema=schema, timeout_seconds=60.0
                )
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("model reply is not an object")
            return value
        except Exception as exc:  # noqa: BLE001
            error = type(exc).__name__
            raise
        finally:
            end = time.monotonic()
            with recorder.lock:
                recorder.events.append(
                    {
                        "label": label,
                        "model": model,
                        "effort": effort,
                        "prompt_chars": len(prompt),
                        "input_tokens": sum(r.get("input_tokens", 0) for r in rows),
                        "output_tokens": sum(r.get("output_tokens", 0) for r in rows),
                        "start": round(start - recorder.t0, 3),
                        "end": round(end - recorder.t0, 3),
                        "seconds": round(end - start, 3),
                        "error": error,
                    }
                )

    return call


FRESHMAN_NL = [
    "ode_separable_zero_solution",
    "pq-absolute-value-nondifferentiability",
    "poly_square_nonnegative",
    "pq-sum-of-first-n-integers",
    "seed-absolute_value_not_differentiable",
    "seed-cubic_derivative",
    "seed-determinant_nonzero_decision",
    "seed-linear_system_inconsistent",
    "seed-natural_power_continuous",
    "seed-projection_not_injective",
    "seed-quadratic_not_injective",
    "seed-reciprocal_derivative",
]
FRESHMAN_GIVEN = [
    "calculus_v3_limit_fixed_shift",
    "calculus_v3_limit_order",
    "la_reuse_kernel_detects_zero",
    "la_v5_matrix_of_composition",
]
UNDERGRAD = [
    "nt_bezout_101_37",
    "exlog_exp_strictly_positive",
    "trig_expand_difference_square_le_two",
    "disc_size_difference_closed",
    "coord_quarter_turn_orthogonal_components",
    "calc_integral_square_zero_one",
    "pq-irrational-square-root-two",
    "pq-continuous-interval-self-map-fixed-po",
]
SETS = {
    "freshman": FRESHMAN_NL + FRESHMAN_GIVEN,
    "freshman_nl": FRESHMAN_NL,
    "undergrad": UNDERGRAD,
    "all": FRESHMAN_NL + FRESHMAN_GIVEN + UNDERGRAD,
    "eval": FRESHMAN_NL + UNDERGRAD,
}


def main() -> None:
    from formalise import load_key  # noqa: PLC0415

    from pals_agent.evals.runner import estimate_usd  # noqa: PLC0415
    from pals_agent.usage import usage_scope  # noqa: PLC0415

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--items", choices=sorted(SETS), default="freshman_nl")
    parser.add_argument("--roundtrip", choices=["two_calls", "single"], default="two_calls")
    parser.add_argument("--default", default="")
    parser.add_argument("--override", action="append", default=[])
    parser.add_argument("--max-usd", type=float, default=0.8)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-children", type=int, default=8)
    parser.add_argument("--budget-formalised", type=float, default=20.0)
    parser.add_argument("--budget-given", type=float, default=stage0.BUDGET_GIVEN_S)
    parser.add_argument(
        "--toolchain", default=str(Path.home() / ".elan/toolchains/leanprover--lean4---v4.32.0-rc1")
    )
    parser.add_argument("--project", type=Path, default=ROOT / "lean-workspace")
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    overrides = dict(item.split("=", 1) for item in args.override)
    spend = [0.0]

    def add(row: dict) -> None:
        spend[0] += estimate_usd(row["model"], row["input_tokens"], row["output_tokens"]) or 0.0

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
            max_children=args.max_children,
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
    s0 = stage0.Stage0(
        ResidentWorker(resident, scratch_dir=scratch),
        lane.load_fixture_recipes(ROOT / "testdata"),
        model,
        require_flags=False,
        roundtrip_mode=args.roundtrip,
        worker_factory=lambda: ResidentWorker(resident, scratch_dir=scratch),
        prefetch=False,
    )
    problems = json.loads((ROOT / "testdata/generation-eval-v1/manifest.json").read_text())[
        "problems"
    ]
    with usage_scope(add), (args.out / f"{args.name}.jsonl").open("a") as fh:
        for repeat in range(args.repeats):
            for pid in SETS[args.items]:
                if spend[0] >= args.max_usd:
                    print("budget reached", round(spend[0], 3), flush=True)
                    break
                p = next(x for x in problems if x["id"].startswith(pid))
                given = p.get("fixed_lean_statement")
                recorder.reset()
                t0 = time.monotonic()
                r = s0.run(
                    p["statement"],
                    p["language"],
                    formal=given or None,
                    budget_s=args.budget_given if given else args.budget_formalised,
                )
                stage0_s = time.monotonic() - t0
                events = list(recorder.events)
                verified, audit_s = None, 0.0
                if r.outcome == "answered" and r.formal_proved:
                    t1 = time.monotonic()
                    try:
                        prop = ap.check_formal_statement(r.formal_proved, allow_header=bool(given))
                        tactic = next((t for t in ap.PORTFOLIO if t.name == r.by), None)
                        if tactic is not None:
                            verified = verifier.verify(candidate_source(prop, tactic)).success
                    except Exception as error:  # noqa: BLE001
                        verified = f"error:{type(error).__name__}"
                    audit_s = time.monotonic() - t1
                row = {
                    "variant": args.name,
                    "id": pid,
                    "repeat": repeat,
                    "tier": p["tier"],
                    "field": p["field"],
                    "language": p["language"],
                    "formal_source": r.formal_source,
                    "outcome": r.outcome,
                    "reason": r.reason,
                    "kind": r.kind,
                    "by": r.by,
                    "stage0_s": round(stage0_s, 2),
                    "seconds": r.seconds,
                    "audit_s": round(audit_s, 2),
                    "verified": verified,
                    "shown_s": round(stage0_s + audit_s, 2),
                    "calls": events,
                    "formal": r.formal,
                    "request": p["statement"],
                    "answer_text": r.answer_text,
                    "gate": None
                    if r.gate is None
                    else {
                        "passed": r.gate.passed,
                        "reasons": r.gate.reasons,
                    },
                }
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                print(pid[:36], r.outcome, r.by, r.reason, row["stage0_s"], verified, flush=True)
    print("load", os.getloadavg(), f"spend_est_usd={spend[0]:.4f}", flush=True)
    s0.close()
    resident.close()


if __name__ == "__main__":
    main()
