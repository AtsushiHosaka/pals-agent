"""The production shape of the T2 lane, end to end, with a resident Lean standing in for the API.

The worker has no compiler under ``verification_mode="api_reconcile"``: it submits one candidate,
the API compiles it, and a failed compile comes back as a repair seed. This driver runs exactly
that loop around the real ``ProofPipeline`` (api_reconcile) and measures it:

    run_statement -> (API_OVERHEAD_S of submit + poll) -> compile with the resident Lean
      -> verified: semantic review + explanation (adopting the early calls, as the worker does)
      -> failed:   ApiRepairSeed -> run_statement(api_repair_seed=...) with the race's held
                   alternate available (PALS_T2_HETERO_RACE_ENABLED) -> ...

Not the real API: the submit/poll round trips are a fixed ``API_OVERHEAD_S`` (0.3 s submit, about
0.5 s mean poll wait, 0.3 s read) added to the clock, and the compile is this machine's resident
Lean. Needs OPENAI_API_KEY in the environment. Records go to the run directory (they hold Lean
source and statements: keep that directory out of git).

    run_hetero_api_sim.py --out DIR --n 14 --arm hetero_par --max-usd 0.9 --spend-ledger L ...
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
from contextlib import ExitStack
from types import SimpleNamespace
import time
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_stages  # noqa: E402

API_OVERHEAD_S = 1.1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n", type=int, default=14)
    ap.add_argument("--ids")
    ap.add_argument("--arm", default="hetero_par", choices=sorted(run_stages.ARM_FLAGS))
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--total-cap", type=float, default=1.0)
    ap.add_argument("--spend-ledger", type=Path, required=True)
    ap.add_argument("--model-timeout", type=float, default=240.0)
    ap.add_argument("--max-output-tokens", type=int, default=12000)
    ap.add_argument("--max-repairs", type=int, default=6)
    ap.add_argument("--no-answer", action="store_true")
    ap.add_argument(
        "--problems-file", type=Path,
        help="JSON {'problems': [...]} of dev_unseen items only; replaces the generation-eval-v1 tuning set",
    )
    ap.add_argument("--first-attempt-only", action="store_true",
                    help="stop after the first submitted candidate (first-attempt rate and time)")
    ap.add_argument("--efforts", help="override the race's two efforts, e.g. none,low")
    ap.add_argument("--pin-effort", help="pin one effort on the prove client (single candidate arms)")
    for name in ("lean", "lake", "project", "elan-home"):
        ap.add_argument(f"--{name}", required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    from pals_agent import t2_lane
    from pals_agent.artifacts import FileArtifactStore
    from pals_agent.evals.runner import estimate_usd
    from pals_agent.generator import HybridLeanGenerator
    from pals_agent.lean import LeanVerifier
    from pals_agent.lean_verifier.resident import ResidentConfig, ResidentLean
    from pals_agent.lean_verifier.resident.manager import default_read_roots
    from pals_agent.models import Diagnostic
    from pals_agent.openai import OpenAIResponsesClient
    from pals_agent.pipeline import ApiRepairSeed, ProofPipeline
    from pals_agent.usage import usage_scope

    if args.problems_file is not None:
        problems = json.loads(args.problems_file.read_text())["problems"]
        # The freshman-v1 held_out split is for the final check only: never loaded here.
        if any(p["split"] != "dev_unseen" for p in problems):
            raise SystemExit("problems-file must contain dev_unseen items only")
        if args.ids:
            wanted = args.ids.split(",")
            problems = [next(p for p in problems if p["id"] == i) for i in wanted]
        problems = problems[: args.n]
    else:
        problems = run_stages.select(
            json.loads(run_stages.DEFAULT_MANIFEST.read_text()), args.ids, args.n
        )
    if args.efforts:
        t2_lane.HETERO_EFFORTS = tuple(args.efforts.split(","))
    steps_path = args.out / "steps.jsonl"
    os.environ["PALS_STEP_TIMING_JSONL"] = str(steps_path)
    from pals_agent import step_timing
    lean_path = subprocess.run(
        [args.lake, "env", "printenv", "LEAN_PATH"],
        cwd=args.project, capture_output=True, text=True, check=True,
    ).stdout.strip()
    scratch = Path(mkdtemp(prefix="pals-heterosim-"))  # no spaces: the resident worker needs it
    resident = ResidentLean(
        ResidentConfig(
            project_dir=Path(args.project),
            confine=sys.platform.startswith("linux"),
            request_root=scratch,
            read_roots=default_read_roots(args.lean, lean_path),
            lean_binary=args.lean,
            lean_path=lean_path,
            build_dir=scratch / "resident",
            max_children=4,
            warm_exact=False,
            queue_timeout_s=30.0,
        )
    )
    print(f"resident startup {resident.start():.1f}s", flush=True)
    verifier = LeanVerifier(
        lean_binary=args.lean, lake_binary=args.lake, project_dir=Path(args.project),
        child_path=f"{Path(args.lean).parent}:/usr/bin:/bin", elan_home=args.elan_home,
        scratch_dir=scratch, timeout_seconds=300.0, resident=resident,
    )
    client = OpenAIResponsesClient(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ.get("PALS_OPENAI_BASE_URL", "https://api.openai.com/v1"),
        timeout_seconds=args.model_timeout,
        max_output_tokens=args.max_output_tokens,
        reasoning_effort=args.pin_effort,
    )
    generator = HybridLeanGenerator(
        model="gpt-6.1-terra", provider="openai", client=client, use_release_role_bindings=True
    )
    explainer, reviewer = (None, None) if args.no_answer else run_stages.build_answer_stage(args)
    env = run_stages.set_arm(args.arm)
    pipeline = ProofPipeline(
        generator=generator,
        verifier=None,
        verification_mode="api_reconcile",
        artifact_store=FileArtifactStore(args.out / "art"),
        max_repair_attempts=args.max_repairs,
        explainer=explainer,
        reviewer=reviewer,
        explanation_language="ja",
        accounting_wait_seconds=0.0,
    )
    # The worker's own carry/resume code runs the hand-off: _t2_carry_scope keeps what the first
    # run left running, _resume_with_carry settles it and gives a failed compile the held
    # alternate. Only the API client (usage sink) and the nested repair run are stand-ins.
    from pals_agent.worker import SqsProofWorker

    sink: dict[str, Any] = {"on_usage": None}
    worker = SqsProofWorker(
        settings=SimpleNamespace(explanation_model_timeout_seconds=120),  # type: ignore[arg-type]
        api_client=SimpleNamespace(  # type: ignore[arg-type]
            record_usage=lambda **kw: sink["on_usage"](kw["usage"])
        ),
        pipeline=None, explainer=None, proof_reviewer=None, output_reviewer=None,
    )
    nested: dict[str, Any] = {}

    def repair_run(self: Any, proof_job_id: str, **_kw: Any) -> bool:
        with t2_lane.alternate_limits(lease_deadline=None, should_stop=None):
            nested["res"] = pipeline.run_statement(
                statement=nested["problem"]["statement"],
                formal_statement=nested["problem"].get("fixed_lean_statement"),
                proof_job_id=nested["run_id"], api_repair_seed=nested["seed"],
                routine=nested["problem"].get("tier") == "easy",
                on_status=lambda *_a: None,
            )
        return True

    SqsProofWorker.process_proof_job = repair_run  # type: ignore[method-assign,assignment]
    meter = run_stages.Meter(args.spend_ledger, args.out.name, args.max_usd, args.total_cap)
    meter.arm = args.arm
    PROBE = run_stages.PROBE_CODE
    probe = [round(_t(lambda: verifier.verify(PROBE)), 2) for _ in range(3)]
    print("lean probe (resident)", probe, "load", round(os.getloadavg()[0], 1), flush=True)

    for problem in problems:
        if meter.exhausted():
            print("budget reached; stopping", flush=True)
            break
        usage: list[dict[str, Any]] = []

        def on_usage(row: dict[str, Any], usage: list[dict[str, Any]] = usage) -> None:
            usage.append(row)
            meter.add(row)

        step_offset = steps_path.stat().st_size if steps_path.exists() else 0
        base_id = f"hsim-{args.arm}-{problem['id']}"
        t0 = time.monotonic()
        load_start = os.getloadavg()[0]
        submits: list[dict[str, Any]] = []
        sink["on_usage"] = on_usage
        carry_stack = ExitStack()
        carry = None
        final = None
        seed = None
        attempt = 1
        error = None
        try:
            with usage_scope(on_usage):
                while True:
                    run_id = base_id if seed is None else f"{base_id}.repair-{seed.attempt + 1}"
                    if seed is None:
                        res = pipeline.run_statement(
                            statement=problem["statement"],
                            formal_statement=problem.get("fixed_lean_statement"),
                            proof_job_id=run_id,
                            api_repair_seed=None,
                            routine=problem.get("tier") == "easy",
                            on_status=lambda *_a: None,
                        )
                        carry = carry_stack.enter_context(
                            worker._t2_carry_scope(res, proof_job_id=base_id, claim_id="claim")
                        )
                    else:
                        nested.update(problem=problem, run_id=run_id, seed=seed)
                        worker._resume_with_carry(
                            carry, {"state": "repairing"}, proof_job_id=base_id,
                            claim_id="claim", extend_visibility=None,
                        )
                        res = nested["res"]
                    if not res.verification_pending:
                        break  # the pipeline gave up (budget, early stop, preflight exhausted)
                    code = res.generated.lean_code
                    time.sleep(API_OVERHEAD_S)
                    started = time.monotonic()
                    ver = verifier.verify(code)
                    submits.append(
                        {
                            "attempt": attempt,
                            "ok": bool(ver.success),
                            "verify_s": round(time.monotonic() - started, 2),
                            "alternate": _used_alternate(res),
                        }
                    )
                    if ver.success:
                        final = dataclasses.replace(
                            res, verification=ver, verification_pending=False
                        )
                        break
                    if args.first_attempt_only:
                        break
                    # The API's compile failure: the verifier_compile_failed marker the seed
                    # requires, then the compiler's own diagnostics as repair feedback.
                    failed = dataclasses.replace(
                        ver,
                        diagnostics=[
                            Diagnostic(
                                severity="error", code="verifier_compile_failed",
                                message="The Lean compiler rejected the candidate.",
                            ),
                            *ver.diagnostics,
                        ],
                    )
                    seed = ApiRepairSeed(
                        generated=res.generated, verification=failed, attempt=attempt,
                        repairs_used=attempt - 1,
                    )
                    attempt += 1
                wall_s = time.monotonic() - t0
                answer: dict[str, Any] = {}
                if final is not None and not args.no_answer:
                    answer = run_stages.answer_stage(
                        final, problem, explainer, reviewer
                    )
                answer_s = time.monotonic() - t0
                carry_stack.close()  # the worker settles what nobody adopted
                undrained = (
                    res.background.drain(180) if getattr(res, "background", None) else 0
                )
        except Exception as exc:  # noqa: BLE001
            error = type(exc).__name__
            wall_s = answer_s = time.monotonic() - t0
            answer, undrained = {}, 0
        step_timing._queue.join()  # the writer thread is asynchronous
        steps: list[dict[str, Any]] = []
        if steps_path.exists():
            with steps_path.open("rb") as fh:
                fh.seek(step_offset)
                steps = [json.loads(x) for x in fh.read().decode().splitlines() if x.strip()]
        row = {
            "problem_id": problem["id"],
            "steps": steps,
            "arm": args.arm,
            "verified": final is not None,
            "first_attempt_ok": bool(submits and submits[0]["ok"]),
            "submits": len(submits),
            "repairs": max(0, len(submits) - 1),
            "wall_s": round(wall_s, 2),
            "answer_s": round(answer_s, 2),
            "answer": {k: v for k, v in answer.items() if k != "answer_note"},
            "usd": round(sum(
                estimate_usd(u["model"], u["input_tokens"], u["output_tokens"]) or 0.0
                for u in usage
            ), 4),
            "input_tokens": sum(u["input_tokens"] for u in usage),
            "cached_input_tokens": sum(u.get("cached_input_tokens", 0) for u in usage),
            "undrained": undrained,
            "error": error,
            "load_start": round(load_start, 1),
            "api_overhead_s": API_OVERHEAD_S,
            "flags": env,
            "submits_detail": submits,
        }
        with (args.out / "records.jsonl").open("a") as fh:
            fh.write(json.dumps(row) + "\n")
        if final is not None:
            # Lean source and statement: local notes only, for reading verified answers by hand.
            with (args.out / "proofs.jsonl").open("a") as fh:
                fh.write(json.dumps({
                    "problem_id": problem["id"], "statement": problem["statement"],
                    "lean_code": final.generated.lean_code,
                    "review_approved": answer.get("review_approved"),
                }, ensure_ascii=False) + "\n")
        print(
            f"{problem['id']} ok={row['verified']} first={row['first_attempt_ok']} "
            f"submits={row['submits']} wall={row['wall_s']} answer={row['answer_s']} "
            f"usd={row['usd']} run_usd={meter.run_usd:.4f} err={error}",
            flush=True,
        )
    resident.close()
    print(f"DONE run_usd={meter.run_usd:.4f} session_total={meter.total():.4f}", flush=True)


def _used_alternate(res: Any) -> bool:
    """Whether the candidate of this run was the held second candidate (no model repair)."""
    try:
        meta = json.loads(Path(res.artifact.uri).read_text(encoding="utf-8"))
        route = (meta.get("attempts") or [{}])[-1].get("repair_route") or {}
        return route.get("provider") == "pals-t2-alternate"
    except Exception:  # noqa: BLE001
        return False


def _t(fn: Any) -> float:
    started = time.monotonic()
    fn()
    return time.monotonic() - started


if __name__ == "__main__":
    main()
