# ruff: noqa: E501, SIM115, F841
"""Post-Lean semantic review (the gate after compilation) on the fixed set, repeated.

Valid pairs should be approved; mismatched pairs (a Lean statement that does not match the request)
should be rejected. Two epsilon-N requests that demand an explicit N test the suspicion that
requirements hard to express in a Lean statement make the reviewer reject.
Usage: OPENAI_API_KEY=... uv run python run_semantic.py --reps 4 --out <json>
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from pals_agent.explanations import LeanProofSemanticReviewer, ProofSemanticReviewUnavailable
from pals_agent.lean_target import extract_single_target_declaration
from pals_agent.model_roles import ModelRole, fixed_model_default
from pals_agent.openai import OpenAIResponsesClient

HERE = Path(__file__).resolve().parent
EPSN_STATEMENT = "数列 $a_n=\\dfrac{1}{n+1}$ が $0$ に収束することを、ε-N の定義を使って、明示的な N を与えて示せ。"
EPSN_PLAIN = "数列 $a_n=\\dfrac{1}{n+1}$ が $0$ に収束することを示せ。"


def cases():
    probs = {p["id"]: p for p in json.load(open(HERE / "problems.json"))}
    out = [dict(case=f"{pid}/valid", expected="approve", statement=p["statement"], lean=p["lean"]) for pid, p in probs.items()]
    out += [
        dict(case="epsn_plain/tendsto", expected="approve", statement=EPSN_PLAIN, lean=(HERE / "epsn_tendsto.lean").read_text()),
        dict(case="epsn_explicitN_request/tendsto", expected="approve?", statement=EPSN_STATEMENT, lean=(HERE / "epsn_tendsto.lean").read_text()),
        dict(case="epsn_explicitN_request/epsilonN", expected="approve", statement=EPSN_STATEMENT, lean=(HERE / "epsn_explicit.lean").read_text()),
        dict(case="epsn_explicitN_request/explicit_witness_in_statement", expected="approve", statement=EPSN_STATEMENT, lean=(HERE / "epsn_explicit_witness.lean").read_text()),
        dict(case="epsn_plain/epsilonN", expected="approve", statement=EPSN_PLAIN, lean=(HERE / "epsn_explicit.lean").read_text()),
        dict(case="even_sum/mismatch_prime", expected="reject", statement=probs["even_sum"]["statement"], lean=probs["prime_dvd"]["lean"]),
        dict(case="ratio_two/mismatch_weaker", expected="reject", statement=probs["ratio_two"]["statement"],
             lean="import Mathlib\n\ntheorem ratio_nonneg (a b : ℝ) (ha : 0 < a) (hb : 0 < b) : 0 ≤ a / b + b / a := by positivity\n"),
        dict(case="roots_quadratic/mismatch_wrong_set", expected="reject", statement=probs["roots_quadratic"]["statement"],
             lean=probs["roots_quadratic"]["lean"].replace("{2, 3}", "{2, 4}")),
    ]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=4)
    ap.add_argument("--only", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    b = fixed_model_default(ModelRole.PROOF_REVIEW)
    client = OpenAIResponsesClient(api_key=os.environ["OPENAI_API_KEY"], max_output_tokens=6000)
    rv = LeanProofSemanticReviewer(client=client, model=b.model, provider=b.provider, max_attempts=2)
    res = []
    for rep in range(a.reps):
        for c in cases():
            if a.only and a.only not in c["case"]:
                continue
            target = extract_single_target_declaration(c["lean"])
            if target is None:
                continue
            try:
                r = rv.review_proof(theorem_statement=c["statement"], formal_statement=None, target_declaration=target, lean_code=c["lean"], timeout_seconds=120)
                verdict, reason = r.decision, r.rationale
            except ProofSemanticReviewUnavailable as e:
                verdict, reason = f"unavailable:{e.failure_kind}", ""
            row = dict(rep=rep, case=c["case"], expected=c["expected"], verdict=verdict, reason=reason[:500])
            res.append(row)
            print(json.dumps({k: row[k] for k in ("rep", "case", "expected", "verdict")}, ensure_ascii=False), flush=True)
            json.dump(res, open(a.out, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
