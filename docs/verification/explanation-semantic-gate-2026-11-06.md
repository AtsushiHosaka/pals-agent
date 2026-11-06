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
| `|x-a|<δ` followed by `|x²-a²|=|x-a||x+a|` followed by `≤ε` | A real estimate down to ε | QA: justified bound on `|x+a|`, a valid chain to ε; a bound ending in ε+1 is rejected (a fixed multiple such as 2ε is a valid ε–δ ending, see the checklist); ending in `= ε` is accepted |
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

`testdata/explanation-qa-v1/cases.json` (v1.3 has 35 cases; the counts below are the v1.0 set): 23 labelled explanations of x² continuity, every one
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
    --input-usd-per-mtok P --output-usd-per-mtok Q [--repeats 3] [--group wrong] [--json-out report.json]
```

Prices are supplied by the operator (the repository has no price table). The run is refused when
the worst case of all cases and repeats exceeds the budget (default output bound 16384 tokens
per call; a malformed answer is retried once), and stops before a call that could exceed what is left. The report lists false
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

## Checklist review (x² epsilon-delta requirement)

This replaces the prose reject list and decision rule described in the sections above for the
x² review; those sections remain as history of how the checklist came about.

Real-model runs with the rubric-only design (v1.0 to v1.2 cases, gpt-6-luna) showed two
problems that more wording did not fix: a valid proof was sometimes rejected with
`approved=false` while the rationale called it valid, or for a step that was merely not spelled
out; and a quote-grounded rejection protocol (every rejection must quote a defect from the
proof) removed those false rejections (30/30 valid approved) but made the reviewer miss an
omission: for a delta with no `min{1,·}` it answered `approved=true, defects=[]` three times out
of three (the earlier, quote-free version rejected all 30 wrong runs). A free-form "list your
defects" question lets the reviewer skip an element it does not think of; asking about every
element does not.

So the x² review (and only it) asks for a fixed checklist and the code decides:

| id | required element |
|---|---|
| `epsilon_arbitrary` | an arbitrary positive ε is introduced |
| `point_fixed` | an arbitrary real point a is fixed; x with \|x-a\|<δ is taken |
| `delta_positive_justified` | δ>0 is justified (one clause suffices) |
| `delta_bounded_by_one` | \|x-a\|<1 follows from \|x-a\|<δ (minimum with 1 or equivalent) |
| `delta_depends_on_point_and_epsilon` | δ is an explicit formula in ε and a |
| `factorization` | \|x²-a²\| = \|x-a\|\|x+a\| |
| `sum_bound` | \|x+a\|<2\|a\|+1 (or equivalent) is derived |
| `final_inequality` | a valid chain, for the chosen δ, reaches ε or a fixed multiple of ε (not ε+1, not δ) |
| `conclusion` | continuity at a, hence everywhere |
| `presentation` | no plan or conclusion preview in the opening, headings, bullets, repeats, math outside `$`, Lean terms |

This list is the single source (`EPSILON_DELTA_CHECK_IDS`) for the prompt, the response format
and the decision; every defect the earlier rubric listed belongs to exactly one element (a
test pins that). Each answer is `{id, status: ok|missing|wrong, quote, note}`.

Decision (deterministic, `LeanGroundedOutputReviewer._review`):

- reject iff some element is `missing`, or `wrong` with a `quote` that really occurs in the
  proof (whitespace, width, `$`, braces and TeX spacing ignored; at least four characters);
- otherwise approve. The reviewer's own `approved` flag is ignored; a disagreement with the
  checklist is kept in memory and logged without text
  (`explanation_review_flag_contradicted_checklist`).
- a missing, repeated or unknown id, an unknown status, or `presentation: missing` is a schema
  failure (retried once, then fail-closed). Transport failure never approves.

Why a `wrong` that quotes nothing in the proof does not count: a false claim must point at
text. An accusation that cannot be located is more likely a hallucination or an over-reading
(the failure mode behind the false rejections), and a real error is quotable, because a wrong
statement is a statement; an absence is reported as `missing`, which needs no quote. The
cost is a real error whose quote the reviewer mangles beyond the normalization; the prompt
tells the reviewer to copy it verbatim and to use `missing` for absences.

Why rejection by `missing` is safe against over-reading: the status rule says an element is `ok`
when the text lets a reader verify it, that a brief standard fact (minimum of positives is
positive, each argument of a minimum bounds it, triangle inequality, difference of squares)
is enough, and that notation, wording, style, level of detail and order are never grounds. The
reviewer's job per element is a narrow yes/no, not a global judgement.

Clarification, answer and Recipe reviews, and explanation reviews of other theorems, keep the
original `{approved, rationale}` format and behaviour.

Regression cases (v1.3): 15 valid (including 5 where each element holds by a one-phrase
standard fact), 17 wrong (at least one case per element, each with
`expected_failed_checks`), 3 summary-first. Truth of each case was fixed mathematically before
any model run. The report lists every check with its status, the failing ids, whether the
rejection hit the expected element, and flag contradictions. `--repeats 3` is the intended
measurement; the target is no false approvals and no false rejections in any run.

Residual risks: the reviewer can still answer a single element wrongly (a false `missing` on a
valid proof rejects it; an `ok` on an absent element approves it); repeats measure how often.
Elements the checklist does not name are not checked mathematically, except through
`presentation` and the general rubric. δ sufficiency is judged by `final_inequality` and
`delta_bounded_by_one` rather than by a deterministic rule.

## Merged notation and alias regressions (Codex 210ece8)

Codex extended the text gate again (sized delimiters, `aligned`/`align*`/`array` layouts, one
named bound alias such as `C = 2|a|+1`, cancellation `(ε/C)C = ε`). This branch merged that
commit and kept the design without a text gate. What each of its rules protected, and where
that now lives:

| Mathematical point the rule protected | Now |
|---|---|
| Layout and delimiter sizes (`\bigl`, `\Bigl`, `aligned`, `align*`, `array`) do not change the proof | Structural layer accepts them in one attempt (`test_x_squared_notation_migration.py`, 14 layout styles + 8 size families); regression cases `valid-16`, `valid-17` |
| A named positive bound `C` and a closing cancellation `(ε/C)C = ε` | `final_inequality` and `sum_bound` judge the chain; cases `valid-18` (accept) |
| The alias must be defined once, with a sufficient constant, for the fixed point; rebinding or a wrong constant breaks the proof | `sum_bound`, `delta_depends_on_point_and_epsilon`, `final_inequality`; cases `wrong-18` (rebound to 1), `wrong-19` (`C = |a|+1`) |
| Connected equalities may rewrite the product before the inequality | `final_inequality`; case `valid-20` |
| A preceding general identity (other variables `u, v`) must not decide which variables the proof is about | `point_fixed`, `factorization`; case `valid-19` (accept), `wrong-21` (δ for `b` but an estimate for another point `a`: capture) |
| The neighborhood must be about the fixed point | `point_fixed`; case `wrong-20` (`|x-b|<δ`) |
| The factorization must be the product `|x-a||x+a|` | `factorization`; cases `wrong-14`, `wrong-22` |
| Insufficient or modified δ (`ε/(|a|+1)`, `+1`, `×2`, `ε+1` ending) | `delta_bounded_by_one`, `final_inequality`; cases `wrong-01`, `wrong-04`..`wrong-06` |

Every input of Codex's notation test file that the gate had to accept is a valid proof, and
every input it had to refuse is also pushed through the structural layer, which must not decide
either way (only the checklist can). 118 such parametrized inputs are in
`tests/unit/test_x_squared_notation_migration.py`.

What could not be moved, and why:

- Tests of the normalizer's own safety (unknown macros such as `\unknown`, `\text{=}`, an
  unknown environment, `\biglunknown`, `\leftarrow` not being erased): they assert behaviour of
  code that no longer exists. A reader-side analogue, "this TeX does not render", is not a
  checklist element; it would only be caught if the reviewer reports it under `presentation`
  (math outside valid TeX is not in that definition).
- Independent cells or rows that a gate must not fuse into a product (`array{ll}` with
  `|x-a|&|x+a|`): whether adjacent array cells are a product is a rendering question, not a
  mathematical error. A reviewer reading the TeX source can treat it either way; no regression
  case was added because the expected verdict is not well defined.
- "Bound alias cannot be the varying variable" (a name collision `X`/`x`): a naming-collision
  of the gate's regexes; as mathematics, using `X` for both a bound and the variable is only
  ambiguous notation, not a false proof.
- Weaker-ending gate controls (`≤ 2ε` as the last step): these tested that the gate required
  a bridge to ε, "not a claim that the theorem or retained bounds become false". A proof that
  ends at a fixed multiple of ε is a valid ε–δ proof, so the checklist accepts it (the
  `final_inequality` definition says so) and no wrong case was made from it. Endings that
  really do not reach ε (`ε+1`, `δ`) stay wrong cases.
- Strictness requirements of the gate (`<` before the cancellation, strict `δ` bridge): the
  proof is also valid with `≤`; they were gate artefacts.

Review of Codex's intent: its sample, `C = 2|a|+1`, `δ = min(1, ε/C)`, first bound `|x-a|C`
and later `(ε/C)C = ε`, is the shape of `valid-18`, so the case that motivated the change is
kept as a positive regression. The deployed gate rejected that shape because it looked for
the absolute value inside δ literally; the new design has no such dependency.
