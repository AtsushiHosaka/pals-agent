# ruff: noqa: E501, E702, E731, B023, SIM108, SIM115, F841
"""Fixed-output QA regression: the same saved explanations are reviewed repeatedly.

Positives = approved explanations saved by run_e2e.py (`final_content`), which carry a verified Lean
source, so a rejection of them is a false rejection candidate. Negatives = the same explanations
with one deliberate defect applied by `mutate`; a correct reviewer rejects them.
Usage: OPENAI_API_KEY=... uv run python run_fixed_qa.py --e2e <e2e.json> --reps 3 --out <json>
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path

from pals_agent import explanations as _expl
from pals_agent.explanation_v2 import ExplanationReviewerV2
from pals_agent.explanations import (
    LeanGroundedOutputReviewer,
    ProofOutputReviewError,
    proof_explanation_from_api,
)
from pals_agent.model_roles import ModelRole, fixed_model_default
from pals_agent.openai import OpenAIResponsesClient

HERE = Path(__file__).resolve().parent
VAGUE = {"ja": "以上で、主張が確かめられました。"}


def mutate(kind, problem, content):
    """Return (mutated content, defect description) or None if not applicable."""
    c = copy.deepcopy(content)
    if kind == "no_result":  # computation whose conclusion no longer states the answer
        if problem["kind"] != "computation":
            return None
        c["conclusion"] = VAGUE["ja"]
        return c, "conclusion states no result"
    if kind == "false_claim":  # a section asserts a wrong mathematical statement
        text = c["sections"][0]["summary"]
        swaps = [("2", "5"), ("3", "4"), ("≥", "≤"), ("\\ge", "\\le"), ("偶数", "奇数")]
        for a, b in swaps:
            if a in text:
                c["sections"][0]["summary"] = text.replace(a, b, 1)
                return c, f"first section: {a}->{b}"
        c["sections"][0]["summary"] = text + " ここで、この主張は仮定なしに任意の実数 a に対して成り立つ。"
        return c, "unsupported universal claim added"
    if kind == "wrong_answer":  # conclusion states a wrong final result
        if problem["kind"] != "computation":
            return None
        text = c["conclusion"]
        for a, b in [("3", "4"), ("2", "5"), ("1", "2"), ("n", "2n")]:
            if a in text:
                c["conclusion"] = text.replace(a, b, 1)
                return c, f"conclusion: {a}->{b}"
        return None
    raise ValueError(kind)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--e2e", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-usd", type=float, default=0.6)
    ap.add_argument("--arm", default="v1", choices=["v1", "v1p88", "v2"])
    a = ap.parse_args()
    problems = {p["id"]: p for p in json.load(open(HERE / "problems.json"))}
    rows_in = json.load(open(a.e2e))
    # one saved approved explanation per problem (first v1 approval; else any)
    saved = {}
    for r in rows_in:
        if r["final_content"] and (r["id"] not in saved or r["arm"] == "v1" and saved[r["id"]][0] != "v1"):
            saved[r["id"]] = (r["arm"], r["final_content"])
    binding = fixed_model_default(ModelRole.EXPLAIN)
    client = OpenAIResponsesClient(api_key=os.environ["OPENAI_API_KEY"], max_output_tokens=6000)
    orig = _expl._output_review_prompt
    if a.arm == "v1p88":  # measurement only: PR #88's instruction, not in main
        proposal = (HERE / "proposal_pr88_instruction.txt").read_text()
        marker = "Do not reveal hidden chain-of-thought."
        _expl._output_review_prompt = lambda **kw: orig(**kw).replace(marker, proposal + marker, 1)
    reviewer = LeanGroundedOutputReviewer(client=client, model=binding.model, provider=binding.provider, max_attempts=2)
    cases = []
    for pid, (_, content) in saved.items():
        p = problems[pid]
        cases.append(dict(case=f"{pid}/valid", pid=pid, expected="approve", content=content, defect=None))
        for kind in ("no_result", "false_claim", "wrong_answer"):
            m = mutate(kind, p, content)
            if m:
                cases.append(dict(case=f"{pid}/{kind}", pid=pid, expected="reject", content=m[0], defect=m[1]))
    results, n_calls = [], 0
    for rep in range(a.reps):
        for cs in cases:
            if n_calls * 0.0035 > a.max_usd:
                print("budget stop"); break
            p = problems[cs["pid"]]
            try:
                expl = proof_explanation_from_api({**cs["content"], "model": binding.model, "provider": binding.provider}, lean_code=p["lean"])
                if a.arm == "v2":
                    reviewer = ExplanationReviewerV2(client=client, model=binding.model, provider=binding.provider, draft_text=p["draft"])
                rev = reviewer.review_explanation(theorem_statement=p["statement"], lean_code=p["lean"], explanation=expl, language=p["language"])
                verdict, reason = "approve", rev.rationale
            except ProofOutputReviewError as e:
                verdict, reason = ("reject" if e.category == "rejected" else f"error:{e.category}"), (e.rationale or "")
            except ValueError as e:  # mutated content no longer passes the deterministic validators
                verdict, reason = "invalid_before_qa", str(e)
            n_calls += 1
            row = dict(rep=rep, case=cs["case"], expected=cs["expected"], verdict=verdict, reason=reason[:400], defect=cs["defect"])
            results.append(row)
            print(json.dumps({k: row[k] for k in ("rep", "case", "expected", "verdict")}, ensure_ascii=False), flush=True)
            json.dump(dict(cases=cases, results=results), open(a.out, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
