# ruff: noqa: E501, E702, E731, B023, SIM115, F841
"""Re-formalization after a semantic-review rejection: does a repair with the review's reason recover?

Each case is a request whose Lean candidate compiled but was rejected by the semantic review (the
rejected Lean and the reviewer's real reason come from results/semantic_review.json). The runner
asks the generator for a repair (the same `repair` entry point the worker uses), verifies it with
Lean, runs the semantic review again and, on a compile failure, repairs again (up to --max-repairs).
Arms: `plain` = the reason is not passed (flag off, what a plain retry would do), `reason` = the
rejection is passed as a diagnostic and PALS_SEMANTIC_REFORMALIZE_ENABLED=true.
Usage: OPENAI_API_KEY=... run_reformalize.py --arms plain,reason --repeats 2 --out DIR --lean ... (as run_stages.py)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[1] / "scripts" / "eval"))

CASES = {
    "epsn_tendsto": ("数列 $a_n=\\dfrac{1}{n+1}$ が $0$ に収束することを、ε-N の定義を使って、明示的な N を与えて示せ。", "epsn_tendsto.lean", "epsn_explicitN_request/tendsto"),
    "epsn_exists_N": ("数列 $a_n=\\dfrac{1}{n+1}$ が $0$ に収束することを、ε-N の定義を使って、明示的な N を与えて示せ。", "epsn_explicit.lean", "epsn_explicitN_request/epsilonN"),
    "defn_fun_prop": ("関数 $x^2$ が実数全体で連続であることを、連続の ε-δ 定義を使って示せ。", None, "defn_request/continuous_pow"),
    "mismatch_even_prime": ("整数 $a, b$ がともに偶数ならば、$a+b$ も偶数であることを示せ。", "prime_dvd.lean", "even_sum/mismatch_prime"),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="plain,reason")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-repairs", type=int, default=3)
    ap.add_argument("--max-usd", type=float, default=0.8)
    for name in ("lean", "lake", "project", "elan-home", "scratch"):
        ap.add_argument(f"--{name}", required=True)
    ap.add_argument("--lean-timeout", type=float, default=300.0)
    ap.add_argument("--model-timeout", type=float, default=240.0)
    ap.add_argument("--max-output-tokens", type=int, default=12000)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    Path(args.scratch).mkdir(parents=True, exist_ok=True)

    import run_stages as rs

    from pals_agent.evals.runner import estimate_usd
    from pals_agent.explanations import LeanProofSemanticReviewer
    from pals_agent.lean_target import extract_single_target_declaration
    from pals_agent.model_roles import ModelRole, fixed_model_default
    from pals_agent.models import Diagnostic, GenerationFeedback, ProofRequest
    from pals_agent.openai import OpenAIResponsesClient
    from pals_agent.usage import usage_scope

    generator, verifier = rs.build(args)
    review = fixed_model_default(ModelRole.PROOF_REVIEW)
    reviewer = LeanProofSemanticReviewer(
        client=OpenAIResponsesClient(api_key=os.environ["OPENAI_API_KEY"], timeout_seconds=args.model_timeout, max_output_tokens=6000),
        model=review.model, provider=review.provider, max_attempts=2,
    )
    sem = json.load(open(HERE / "results" / "semantic_review.json"))
    problems = {p["id"]: p for p in json.load(open(HERE / "problems.json"))}
    cases = {}
    for key, (prompt, lean_file, sem_case) in CASES.items():
        reason = next(r["reason"] for r in sem if r["case"] == sem_case and r["verdict"] == "rejected")
        lean = (HERE / lean_file).read_text() if lean_file else "import Mathlib\n\ntheorem sq_continuous : Continuous (fun x : ℝ => x ^ 2) := by\n  fun_prop\n"
        cases[key] = (prompt, lean, reason)

    spent = 0.0
    rows = []
    for rep in range(args.repeats):
        for key, (prompt, lean, reason) in cases.items():
            for arm in args.arms.split(","):
                if spent > args.max_usd:
                    print("budget stop")
                    break
                os.environ["PALS_SEMANTIC_REFORMALIZE_ENABLED"] = "true" if arm == "reason" else "false"
                request = ProofRequest(id=f"reform-{key}-{rep}", prompt=prompt)
                diags = [Diagnostic("error", "Lean verification failed.", code="verifier_compile_failed")]
                if arm == "reason":
                    diags.append(Diagnostic("error", reason, code="semantic_review_rejected"))
                feedback = GenerationFeedback(attempt=1, previous_lean_code=lean, diagnostics=tuple(diags))
                usage_rows: list = []
                t0 = time.monotonic()
                outcome, note, approved, used = "not_verified", "", None, 0
                with usage_scope(usage_rows.append):
                    for used in range(1, args.max_repairs + 1):
                        proof = generator.repair(request, feedback)
                        verification = verifier.verify(proof.lean_code)
                        if not verification.success:
                            feedback = GenerationFeedback(attempt=used + 1, previous_lean_code=proof.lean_code, diagnostics=tuple(verification.diagnostics), repair_route="draft")
                            continue
                        target = extract_single_target_declaration(proof.lean_code)
                        if target is None:
                            outcome, note = "no_single_target", ""
                            break
                        r = reviewer.review_proof(theorem_statement=prompt, formal_statement=None, target_declaration=target, lean_code=proof.lean_code, timeout_seconds=120)
                        outcome, approved, note = ("approved" if r.decision == "approved" else "rejected_again"), r.decision == "approved", r.rationale[:300]
                        break
                usd = sum(estimate_usd(u["model"], u["input_tokens"], u["output_tokens"]) or 0.0 for u in usage_rows)
                spent += usd
                row = dict(rep=rep, case=key, arm=arm, outcome=outcome, repairs_used=used, approved=approved, seconds=round(time.monotonic() - t0, 1), est_usd=round(usd, 4), note=note, final_lean=proof.lean_code if outcome in ("approved", "rejected_again") else None)
                rows.append(row)
                print(json.dumps({k: v for k, v in row.items() if k != "final_lean"}, ensure_ascii=False), flush=True)
                json.dump(rows, open(args.out / "rows.json", "w"), ensure_ascii=False, indent=1)
    print("DONE est_usd", round(spent, 3))


if __name__ == "__main__":
    main()
