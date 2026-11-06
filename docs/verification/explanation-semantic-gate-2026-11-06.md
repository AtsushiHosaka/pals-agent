# Explanation validation: semantic gate instead of surface patterns, 2026-11-06

## Why

Production returned `validation:x_squared_epsilon_delta` three times in a row for "why is x²
continuous". The proof was Lean-verified; only the explanation step failed. Two hotfixes had
widened a regular-expression gate (`_has_x_squared_epsilon_delta`) and valid explanations were
still rejected: a chain ending in `= ε`, `\dfrac`, `\vert`, `\mathrm{min}`/`\operatorname{min}`,
`\leqslant`, `|(x-a)(x+a)|`, "δ is positive" in words, openings that name the point before ε or
use `\gt` or `$$…$$`, renamed variables. A text pattern for "this is a valid ε–δ proof" either
rejects valid notation or accepts invalid mathematics, so the pattern was removed instead of
widened again.

## Who now guarantees what

| Concern | Enforced by |
|---|---|
| The theorem is true | Lean (unchanged, source of truth) |
| Learner text is faithful, valid mathematics, and (for x² continuity) an ε–δ argument | Independent QA review (`LeanGroundedOutputReviewer`), whose rubric carries the requirement |
| JSON shape, 1–20 sections, exact Lean line ranges and excerpts, length limits, no Lean tactic or identifier in prose, repeated final equation | Structural checks in `_parse_explanation` (unchanged) |
| Whether the requirement applies | The verified Lean statement (`matches_x_squared_continuity`), with the request wording as a fallback only |

## Removed checks and where each one went

| Removed deterministic check | What it was meant to catch | Replacement |
|---|---|---|
| Text must start with `$ε>0$` or `$0<ε$` (`x_squared_opening`) | Summary-first or plan-first exposition | Generation prompt (unchanged) and QA: "Reject summary-first or conclusion-preview exposition", visible headings, numbered steps. The notation and word order of the opening are tolerated; a proof-plan or conclusion preview in the opening is still rejected |
| `δ=min(1, …)` found in the text | An explicit δ exists | QA: explicit positive δ required; rejects a δ without the minimum with 1 |
| Coefficient check (`≥2|a|+1`, factor forms) | δ is sufficient | QA lists the failing cases (coefficient too small such as ε/(|a|+1), δ plus 1, δ doubled, no minimum). **No deterministic sufficiency check remains** |
| `δ>0` / `0<δ` present | δ is positive | QA: reject when δ is not shown to be positive (words are fine) |
| One point `a` bound across δ, the neighborhood and the estimate | The proof is about one function and one point | QA: reject another function or another point than the fixed one |
| `|x-a|<δ` followed by `|x²-a²|=|x-a||x+a|` followed by `≤ε` | A real estimate down to ε | QA: justified bound on `|x+a|`, a valid chain to ε; a bound ending in ε+1 or 2ε is rejected; ending in `= ε` is accepted |
| Word 連続/continuity after the estimate | A conclusion exists | QA: concludes continuity at the point, hence everywhere |
| Suffix guards (`+1`, `*2`, `=1`, `の2倍`) | A modified δ | QA enumerates adding 1 and multiplying by a constant |
| Labels `x_squared_opening`, `x_squared_epsilon_delta` | Failure reasons | Retired. A persistent defect now ends as `review:rejected,…` (`pals.explanation_review_failed`) |

A QA rejection feeds its rationale into the existing single correction attempt.

Unrelated structural fix: the Lean-identifier prose check matched the English abbreviations
`e.g.` and `i.e.`. They are allowed now; `Nat.add_zero` is still rejected.

## When the requirement applies

`_requires_epsilon_delta(theorem_statement, lean_code)` reads the single target declaration of the
verified Lean code. It is true exactly for `Continuous (fun x : ℝ => x ^ 2)` (any variable name,
redundant parentheses allowed), whatever language or notation the learner used (`x^{2}`, `xの2乗`,
full-width, `x**2`, English). When the artifact has no single readable target, the old wording
heuristic (連続 plus x² or x^2, now excluding 導関数, 微分, 一様, derivative, differentiable,
uniform) is the fallback. The same wording heuristic gates the worker's pre-verification
alignment check (`_target_matches_statement`); it no longer forces an x² target for a request
about the derivative or the uniform continuity of x². The log field `x_squared_gate=` keeps its
name for compatibility and now means "the ε–δ requirement applies".

Because Lean decides, a request that says x² continuity but whose verified artifact is another
theorem gets no ε–δ requirement. The pipeline already refuses such a mismatch before
verification (`pals.theorem_alignment_failed`). A Lean statement written another way
(`fun x => x * x`, `(· ^ 2)`) is not recognised either, as in the alignment check.

## Residual risks

- Judgement quality is unmeasured on a real model. Tests use stubs and check the prompt contract
  (every rejection condition and every tolerated notation is present, and no sentence cancels
  another), and that each wrong δ named in the rubric truly fails numerically. They do not show
  that the real reviewer rejects ε+1 or approves `\operatorname{min}`. Run the regression set
  below before releasing.
- δ sufficiency is no longer checked deterministically. A reviewer that approves a wrong δ
  publishes a wrong explanation; the earlier gate would have blocked the common wrong forms.
- A persistently over-strict reviewer turns into `explanation_review_failed` after one
  correction, the same failure the learner saw, only through a different label.
- Structural length limits (summary 800, overview and conclusion 600 code points) are unchanged
  and can still reject a long valid proof.
- Style rules that the old opening check enforced (no summary first) now depend on the reviewer.
- First real-model run (gpt-6-luna, v1.0 cases): all 10 wrong and 3 summary-first cases were rejected,
  but 4 of 10 valid notation variants were also rejected (operatorname/leqslant, mathrm/lvert,
  renamed variables, `\gt` with positivity in words). Revision below; to be re-measured.

## Real-model regression set

`testdata/explanation-qa-v1/cases.json`: 23 labelled explanations of x² continuity, every one
passing the structural layer: 10 valid notation variants (expected approve), 10 wrong (ε+1,
no minimum with 1, δ ignoring the point, coefficient too small, δ doubled, δ plus 1, product
continuity instead of ε–δ, another function, ε never introduced, δ independent of the point)
and 3 summary-first or numbered-step presentations (expected reject).

`scripts/evaluate_explanation_qa.py` runs the production reviewer path
(`AgentSettings.from_env()` → `build_proof_output_reviewer()` → `review_explanation()`).

```
# dry run (default): validates all cases and builds the QA prompts; no model, no key
python scripts/evaluate_explanation_qa.py --input-usd-per-mtok P --output-usd-per-mtok Q --budget-usd N

# live: needs OPENAI_API_KEY or PALS_OPENAI_API_KEY and all three of the options below
python scripts/evaluate_explanation_qa.py --execute --budget-usd N \
    --input-usd-per-mtok P --output-usd-per-mtok Q [--group wrong] [--json-out report.json]
```

Prices are supplied by the operator (the repository has no price table). The run is refused when
the worst case of all cases exceeds the budget (default output bound 16384 tokens per call, two
attempts), and stops before a call that could exceed what is left. The report lists false
accepts (wrong or summary-first approved), false rejects (valid rejected), errors, and the
mismatched case ids. Exit status 0 means every case got its expected decision.

## Revision after the first real-model run

The reviewer's reasons for the four false rejections were not recorded, so the causes below are
hypotheses to be confirmed with the new report fields (`rationale`, `category`,
`raw_reviewer_outputs` per case):

1. The v1.0 valid cases were thinner than the rubric: they asserted `δ>0` and
   `|x|<|a|+1` without reason and never introduced `x`. A strict reviewer can object to that
   for a mathematical reason, which would be a case defect, not a notation rejection. v1.1
   cases justify every step (positivity from two positive numbers, the triangle inequality,
   `δ ≤ ε/(2|a|+1)`), introduce `x` (or `y`) explicitly, and split into two sections. Wrong
   cases keep exactly one intended defect each.
2. The rubric said what to tolerate and what to reject but not how to decide between them.
   It now has a decision rule (approve unless one specific listed defect or one specific false
   inference can be named; never reject for notation, wording or level of detail; quote the
   defective step), accepts brief standard facts (minimum of positives, arguments of a minimum
   bound it, triangle inequality), a positivity clause of one phrase, mixed `|·|`/`\lvert`,
   braces or parentheses for the minimum, and other correct choices of δ.
3. The general review rules (`ANSWER_PRESENTATION`, `ANSWER_SCOPE_REVIEW`, "reject a missing
   essential inference", source-correspondence) were read for conflicts with an x² ε–δ proof.
   None demands more than the rubric does; the only tension is "reject a missing essential
   inference", which the brief-facts clause now settles for this context. They are unchanged.

`scripts/evaluate_explanation_qa.py` now records, per case, `category` (`approved`,
`rejected`, or the infrastructure category), the reviewer's `rationale`, the reviewer session
id, and `raw_reviewer_outputs`, the structured JSON answers exactly as returned (one per
attempt), captured by a transparent wrapper around the production client.
