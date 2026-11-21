# ruff: noqa: E501, B023, SIM115
"""Cover-all-lines instruction (PALS_EXPLANATION_COVER_ALL_LINES_ENABLED), old vs new, pals#232.

Usage (one process per arm, started together so both see the same provider conditions):
  OPENAI_API_KEY=... uv run python testdata/explanation-cover-all-lines-v1/run.py --arm old --reps 3 --out results/old.json
  OPENAI_API_KEY=... uv run python testdata/explanation-cover-all-lines-v1/run.py --arm new --reps 3 --out results/new.json

The arm sets the flag in this process only. Both arms run the production explanation path
(`_generate_reviewed_candidate`: writer, QA, one repair) with the explanation role's release binding.
An independent call (same model, fresh session) then judges, per reference, whether the cited lines are
what the section prose is about. No Lean is run: every source is already compiled.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from pathlib import Path

from pals_agent import explanations as expl
from pals_agent.explanations import (
    ExplanationGenerationError,
    LeanGroundedOutputReviewer,
    LeanProofExplainer,
    ProofOutputReviewError,
    _parse_json_object,
)
from pals_agent.model_roles import ModelRole, fixed_model_default
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.usage import usage_scope
from pals_agent.worker import _generate_reviewed_candidate, _public_explanation_content

HERE = Path(__file__).resolve().parent
PRICE_IN, PRICE_OUT = 0.25 / 1e6, 0.50 / 1e6


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
                    self.stats.setdefault("tok", {}).setdefault(self.tag, [0, 0])
                    self.stats["tok"][self.tag][0] += r["input_tokens"]
                    self.stats["tok"][self.tag][1] += r["output_tokens"]


def coverage(lean: str, sections) -> dict:
    lines = lean.splitlines()
    covered = set()
    nrefs = 0
    for s in sections:
        for r in s.references:
            nrefs += 1
            covered.update(range(r.start_line, r.end_line + 1))
    end = _statement_end(lines)
    body = [i for i, t in enumerate(lines, 1) if t.strip() and i > end]
    return dict(
        refs=nrefs,
        cited_lines=len(covered),
        body_lines=len(body),
        body_lines_uncovered=sum(1 for i in body if i not in covered),
        headers_missing=len([1 for a, b in expl._local_claim_headers(lean) if not any(all(any(r.start_line <= n <= r.end_line for r in s.references) for n in range(a, b + 1)) for s in sections)]),
    )


def _statement_end(lines) -> int:
    """1-based line of the `:= by` that ends the (last) theorem statement; 0 if none."""
    start = max((i for i, t in enumerate(lines, 1) if t.startswith(("theorem", "lemma"))), default=0)
    for i in range(start, len(lines) + 1):
        if lines[i - 1].rstrip().endswith(":= by"):
            return i
    return 0


JUDGE_PROMPT = """You check whether each cited Lean range is what a proof-explanation section is about.

Lean proof (line numbers on the left):
{numbered}

Sections, each with its prose and the Lean line ranges it cites:
{sections}

For every reference of every section decide `fits`: true when the prose of that section discusses the
claim or step contained in the cited lines (it may be a coarse anchor for a short derivation); false when the
prose does not concern the cited lines, or the cited lines are unrelated to what the section says.
Return only JSON: {{"verdicts": [{{"section": <index>, "ref": <index>, "fits": true|false}}]}} covering every reference."""


def judge(client, lean: str, sections, stats) -> dict:
    numbered = "\n".join(f"{i:>3} | {t}" for i, t in enumerate(lean.splitlines(), 1))
    secs = json.dumps(
        [dict(index=i, title=s.title, prose=s.summary, references=[dict(ref=j, start_line=r.start_line, end_line=r.end_line) for j, r in enumerate(s.references)]) for i, s in enumerate(sections)],
        ensure_ascii=False,
        indent=1,
    )
    raw = Counting(client, stats, "judge").generate(model=fixed_model_default(ModelRole.EXPLAIN).model, prompt=JUDGE_PROMPT.format(numbered=numbered, sections=secs), timeout_seconds=100)
    verdicts = _parse_json_object(raw)["verdicts"]
    total = sum(len(s.references) for s in sections)
    bad = [(v["section"], v["ref"]) for v in verdicts if v.get("fits") is False]
    return dict(judged=len(verdicts), refs=total, misfit=len(bad), misfit_refs=[(sections[a].references[b].start_line, sections[a].references[b].end_line) for a, b in bad if a < len(sections) and b < len(sections[a].references)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["old", "new"], required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--only", default="")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-usd", type=float, default=0.45)
    a = ap.parse_args()
    if a.arm == "new":
        os.environ[expl.EXPLANATION_COVER_ALL_LINES_ENV] = "true"
    else:
        os.environ.pop(expl.EXPLANATION_COVER_ALL_LINES_ENV, None)
    corpus = json.load(open(HERE / "corpus.json"))["cases"]
    if a.only:
        corpus = [c for c in corpus if c["id"] in a.only.split(",")]
    jobs = [(rep, c) for rep in range(a.reps) for c in corpus]
    random.Random(a.seed).shuffle(jobs)  # same order in both arms
    binding = fixed_model_default(ModelRole.EXPLAIN)
    client = OpenAIResponsesClient(api_key=os.environ["OPENAI_API_KEY"], max_output_tokens=6000)
    spent, rows = 0.0, []
    for rep, p in jobs:
        if spent > a.max_usd:
            print("budget stop", flush=True)
            break
        lean = (HERE / p["source"]).read_text()
        stats = {"calls": {}, "tok": {}}
        ex = LeanProofExplainer(client=Counting(client, stats, "write"), model=binding.model, provider=binding.provider, max_attempts=3)
        rv = LeanGroundedOutputReviewer(client=Counting(client, stats, "review"), model=binding.model, provider=binding.provider, max_attempts=2)
        failures, produced = [], []

        def gen(fb):
            c = ex.explain(theorem_statement=p["statement"], lean_code=lean, verified=True, language=p["language"], review_feedback=fb, deadline=time.monotonic() + 240, timeout_seconds=100)
            produced.append(c)
            return c

        def rev(cand):
            return rv.review_explanation(theorem_statement=p["statement"], lean_code=lean, explanation=cand, language=p["language"], deadline=time.monotonic() + 240, timeout_seconds=100)

        outcome, error, final, attempt_failures = "approved", None, None, []
        t0 = time.monotonic()
        try:
            final, _ = _generate_reviewed_candidate(generate=gen, review=rev, content_of=_public_explanation_content, failures=failures)
        except ProofOutputReviewError as e:
            outcome, error = f"review_{e.category}", (e.rationale or "")[:300]
        except ExplanationGenerationError as e:
            outcome, error, attempt_failures = "generation_failed", str(e)[:200], list(e.attempt_failures)
        except Exception as e:  # noqa: BLE001
            outcome, error = "error", f"{type(e).__name__}: {str(e)[:200]}"
        seconds = round(time.monotonic() - t0, 1)
        jd = None
        if final is not None:
            try:
                jd = judge(client, lean, final.sections, stats)
            except Exception as e:  # noqa: BLE001
                jd = dict(error=f"{type(e).__name__}: {str(e)[:120]}")
        tok = stats["tok"]
        cost = sum(i * PRICE_IN + o * PRICE_OUT for i, o in tok.values())
        spent += cost
        row = dict(rep=rep, id=p["id"], arm=a.arm, outcome=outcome, error=error, attempt_failures=attempt_failures, writer_calls=stats["calls"].get("write", 0), qa_rejections=sum(1 for f in failures if f.get("category") == "rejected"), seconds=seconds, est_usd=round(cost, 5), final=coverage(lean, final.sections) if final else None, judge=jd)
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("rep", "id", "arm", "outcome", "writer_calls", "seconds", "final", "judge")}, ensure_ascii=False), flush=True)
        json.dump(rows, open(a.out, "w"), ensure_ascii=False, indent=1)
    print("total est usd", round(spent, 4), flush=True)


if __name__ == "__main__":
    main()
