# ruff: noqa: E501, B023, SIM115
"""Claim-header coverage on explanations: old (no check) vs new (check + one retry), same code.

Usage: OPENAI_API_KEY=... uv run python testdata/explanation-claim-headers-v1/run.py \
    --reps 2 --out results/<name>.json [--max-usd 0.6]

The old arm patches the header prompt block and the header check out of this checkout, so both arms
run the same writer, QA and one-repair pipeline (`_generate_reviewed_candidate`) on the same Lean
sources with the explanation role's release binding. No Lean is run: each source is already
compiled (see README.md). Cost is estimated from token counts at the repo's reserve rates.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from pals_agent import explanations as expl
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
PRICE_IN, PRICE_OUT = 0.25 / 1e6, 0.50 / 1e6
_REAL_REQUIRE = expl._require_local_claim_headers
_REAL_BLOCK = expl._claim_header_prompt


class Counting:
    def __init__(self, base, stats, tag):
        self.base, self.stats, self.tag = base, stats, tag

    def generate(self, **kw):
        rows: list = []
        with usage_scope(rows.append):
            try:
                return self.base.generate(**kw)
            finally:
                self.stats["calls"][self.tag] = self.stats["calls"].get(self.tag, 0) + 1
                for r in rows:
                    self.stats["in"] += r["input_tokens"]
                    self.stats["out"] += r["output_tokens"]


def select_arm(arm: str) -> None:
    if arm == "old":
        expl._require_local_claim_headers = lambda sections, source: None
        expl._claim_header_prompt = lambda lean_code: ""
    else:
        expl._require_local_claim_headers = _REAL_REQUIRE
        expl._claim_header_prompt = _REAL_BLOCK


def coverage(lean: str, sections) -> dict:
    lines = lean.splitlines()
    covered = set()
    for s in sections:
        for r in s.references:
            covered.update(range(r.start_line, r.end_line + 1))
    body = [
        i
        for i, text in enumerate(lines, 1)
        if text.strip() and not text.startswith(("import", "theorem", "lemma"))
    ]
    headers = expl._local_claim_headers(lean)
    missing = [
        (a, b)
        for a, b in headers
        if not any(
            all(any(r.start_line <= n <= r.end_line for r in s.references) for n in range(a, b + 1))
            for s in sections
        )
    ]
    return dict(
        headers=len(headers),
        headers_missing=len(missing),
        body_lines=len(body),
        body_lines_uncovered=sum(1 for i in body if i not in covered),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--only", default="")
    ap.add_argument("--arms", default="old,new")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-usd", type=float, default=0.6)
    a = ap.parse_args()
    corpus = json.load(open(HERE / "corpus.json"))["cases"]
    if a.only:
        corpus = [c for c in corpus if c["id"] in a.only.split(",")]
    binding = fixed_model_default(ModelRole.EXPLAIN)
    client = OpenAIResponsesClient(api_key=os.environ["OPENAI_API_KEY"], max_output_tokens=6000)
    spent, rows = 0.0, []
    for rep in range(a.reps):
        arms = a.arms.split(",")
        if rep % 2:
            arms = arms[::-1]  # alternate order so a drifting provider does not favour one arm
        for p in corpus:
            lean = (HERE / p["source"]).read_text()
            for arm in arms:
                if spent > a.max_usd:
                    print("budget stop")
                    break
                select_arm(arm)
                stats = {"calls": {}, "in": 0, "out": 0}
                ex = LeanProofExplainer(
                    client=Counting(client, stats, "write"),
                    model=binding.model,
                    provider=binding.provider,
                    max_attempts=3,
                )
                rv = LeanGroundedOutputReviewer(
                    client=Counting(client, stats, "review"),
                    model=binding.model,
                    provider=binding.provider,
                    max_attempts=2,
                )
                failures, produced = [], []

                def gen(fb, p=p, lean=lean, ex=ex):
                    c = ex.explain(
                        theorem_statement=p["statement"],
                        lean_code=lean,
                        verified=True,
                        language=p["language"],
                        review_feedback=fb,
                        deadline=time.monotonic() + 240,
                        timeout_seconds=100,
                    )
                    produced.append(c)
                    return c

                def rev(cand, p=p, lean=lean, rv=rv):
                    return rv.review_explanation(
                        theorem_statement=p["statement"],
                        lean_code=lean,
                        explanation=cand,
                        language=p["language"],
                        deadline=time.monotonic() + 240,
                        timeout_seconds=100,
                    )

                outcome, error, final = "approved", None, None
                attempt_failures: list = []
                t0 = time.monotonic()
                try:
                    cand, _ = _generate_reviewed_candidate(
                        generate=gen,
                        review=rev,
                        content_of=_public_explanation_content,
                        failures=failures,
                    )
                    final = cand
                except ProofOutputReviewError as e:
                    outcome, error = f"review_{e.category}", (e.rationale or "")[:300]
                except ExplanationGenerationError as e:
                    outcome, error = "generation_failed", str(e)[:200]
                    attempt_failures = list(e.attempt_failures)
                except Exception as e:  # noqa: BLE001
                    outcome, error = "error", f"{type(e).__name__}: {str(e)[:200]}"
                cost = stats["in"] * PRICE_IN + stats["out"] * PRICE_OUT
                spent += cost
                last = final or (produced[-1] if produced else None)
                row = dict(
                    rep=rep,
                    id=p["id"],
                    arm=arm,
                    outcome=outcome,
                    error=error,
                    attempt_failures=attempt_failures,
                    writer_calls=stats["calls"].get("write", 0),
                    review_calls=stats["calls"].get("review", 0),
                    qa_rejections=sum(1 for f in failures if f.get("category") == "rejected"),
                    seconds=round(time.monotonic() - t0, 1),
                    est_usd=round(cost, 5),
                    final=coverage(lean, final.sections) if final else None,
                    last_candidate=coverage(lean, last.sections) if last else None,
                )
                rows.append(row)
                print(
                    json.dumps(
                        {
                            k: row[k]
                            for k in (
                                "rep",
                                "id",
                                "arm",
                                "outcome",
                                "writer_calls",
                                "seconds",
                                "final",
                            )
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                json.dump(rows, open(a.out, "w"), ensure_ascii=False, indent=1)
    select_arm("new")
    print("total est usd", round(spent, 4))


if __name__ == "__main__":
    main()
