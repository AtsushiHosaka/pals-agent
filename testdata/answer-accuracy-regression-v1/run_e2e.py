# ruff: noqa: E501, E702, E731, B023, SIM108, SIM115, F841
"""End-to-end explanation regression (writer + QA + retry) on a small fixed set.

Usage: OPENAI_API_KEY=... uv run python testdata/answer-accuracy-regression-v1/run_e2e.py \
    --arms v1,v2 --reps 2 --out <json> [--max-usd 0.9]
Arms are code paths in this checkout (v1 = default path, v2 = PALS_EXPLANATION_V2 writer/reviewer).
No Lean is run: each problem carries an already compiled Lean source (see the .lean files).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

from pals_agent import explanations as _expl
from pals_agent.explanation_v2 import ExplanationReviewerV2, ExplanationWriterV2
from pals_agent.explanations import (
    ExplanationGenerationError,
    LeanGroundedOutputReviewer,
    LeanProofExplainer,
    ProofOutputReviewError,
)
from pals_agent.model_roles import ModelRole, fixed_model_default
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.usage import usage_scope
from pals_agent.worker import _generate_reviewed_candidate, _public_explanation_content

HERE = Path(__file__).resolve().parent
PRICE_IN, PRICE_OUT = 0.25 / 1e6, 0.50 / 1e6  # budget reserve rates used by the repo's evals


class Counting:
    def __init__(self, base, stats, tag):
        self.base, self.stats, self.tag = base, stats, tag

    def generate(self, **kw):
        rows: list = []
        with usage_scope(rows.append):
            try:
                return self.base.generate(**kw)
            finally:
                s = self.stats
                s["calls"][self.tag] = s["calls"].get(self.tag, 0) + 1
                for r in rows:
                    s["in"] += r["input_tokens"]
                    s["out"] += r["output_tokens"]


def answer_flags(problem, final):
    if final is None:
        return None, None
    concl = final["conclusion"]
    loose = concl + " " + final["overview"] + " " + " ".join(s["summary"] for s in final["sections"])
    pats = problem["answer_regex"]
    return (any(re.search(p, concl) for p in pats), any(re.search(p, loose) for p in pats))


_ORIG_REVIEW_PROMPT = _expl._output_review_prompt
_PROPOSAL = (HERE / "proposal_pr88_instruction.txt").read_text()


def _prompt_with_proposal(**kw):
    """Measurement only: PR #88's review instruction inserted before the closing line (needs owner approval)."""
    text = _ORIG_REVIEW_PROMPT(**kw)
    marker = "Do not reveal hidden chain-of-thought."
    assert marker in text
    return text.replace(marker, _PROPOSAL + marker, 1)


def build(arm, p, client, binding):
    # the reviewer calls the module-level name, so patching it selects the arm
    _expl._output_review_prompt = _prompt_with_proposal if arm == "v1p88" else _ORIG_REVIEW_PROMPT
    arm = "v1" if arm == "v1p88" else arm
    stats = {"calls": {}, "in": 0, "out": 0}
    wc, rc = Counting(client, stats, "write"), Counting(client, stats, "review")
    if arm == "v1":
        ex = LeanProofExplainer(client=wc, model=binding.model, provider=binding.provider, max_attempts=3)
        rv = LeanGroundedOutputReviewer(client=rc, model=binding.model, provider=binding.provider, max_attempts=2)
        gen = lambda fb: ex.explain(theorem_statement=p["statement"], lean_code=p["lean"], verified=True, language=p["language"], review_feedback=fb)
    else:
        ex = ExplanationWriterV2(client=wc, model=binding.model, provider=binding.provider, max_attempts=3)
        rv = ExplanationReviewerV2(client=rc, model=binding.model, provider=binding.provider, draft_text=p["draft"])
        gen = lambda fb: ex.explain(theorem_statement=p["statement"], lean_code=p["lean"], draft_text=p["draft"], language=p["language"], review_feedback=fb)
    rev = lambda cand: rv.review_explanation(theorem_statement=p["statement"], lean_code=p["lean"], explanation=cand, language=p["language"])
    return stats, gen, rev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="v1,v2")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--only", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-usd", type=float, default=0.9)
    a = ap.parse_args()
    problems = json.load(open(HERE / "problems.json"))
    if a.only:
        problems = [p for p in problems if p["id"] in a.only.split(",")]
    binding = fixed_model_default(ModelRole.EXPLAIN)
    client = OpenAIResponsesClient(api_key=os.environ["OPENAI_API_KEY"], max_output_tokens=6000)
    spent, rows = 0.0, []
    for rep in range(a.reps):
        for p in problems:
            for arm in a.arms.split(","):
                if spent > a.max_usd:
                    print("budget stop"); break
                stats, gen, rev = build(arm, p, client, binding)
                failures, produced = [], []
                def g(fb):
                    c = gen(fb); produced.append(c); return c
                outcome, error, final, final_content = "approved", None, None, None
                t0 = time.monotonic()
                try:
                    cand, _ = _generate_reviewed_candidate(generate=g, review=rev, content_of=_public_explanation_content, failures=failures)
                    final = dict(overview=cand.overview, conclusion=cand.conclusion, sections=[dict(title=s.title, summary=s.summary) for s in cand.sections])
                    final_content = _public_explanation_content(cand)
                except ProofOutputReviewError as e:
                    outcome, error = f"review_{e.category}", (e.rationale or "")[:400]
                except ExplanationGenerationError as e:
                    outcome, error = "generation_failed", str(e)[:300]
                except Exception as e:  # noqa: BLE001
                    outcome, error = "error", f"{type(e).__name__}: {str(e)[:200]}"
                cost = stats["in"] * PRICE_IN + stats["out"] * PRICE_OUT
                spent += cost
                strict, loose = answer_flags(p, final)
                row = dict(rep=rep, id=p["id"], arm=arm, outcome=outcome, error=error,
                           qa_rejections=sum(1 for f in failures if f.get("category") == "rejected"),
                           rejection_reasons=[str(f.get("rationale", ""))[:300] for f in failures if f.get("category") == "rejected"],
                           candidates=len(produced), seconds=round(time.monotonic() - t0, 1), est_usd=round(cost, 5),
                           final_content=final_content, conclusion_answer=strict, any_answer=loose,
                           last_candidate=final or (None if not produced else dict(overview=produced[-1].overview, conclusion=produced[-1].conclusion, sections=[dict(title=s.title, summary=s.summary) for s in produced[-1].sections])))
                rows.append(row)
                print(json.dumps({k: row[k] for k in ("rep", "id", "arm", "outcome", "qa_rejections", "conclusion_answer", "seconds", "est_usd")}, ensure_ascii=False), flush=True)
                json.dump(rows, open(a.out, "w"), ensure_ascii=False, indent=1)
    print("total est usd", round(spent, 4))


if __name__ == "__main__":
    main()
