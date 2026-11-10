> **Superseded (2026-11-06).** The text gate described here (`_has_x_squared_epsilon_delta`
> and the opening-pattern requirement) was removed. The epsilon-delta requirement is now judged
> by the independent QA review; see `explanation-semantic-gate-2026-11-06.md`. This record is
> kept unchanged as history.

# X-squared explanation validator hotfix, 2026-11-06

This records the initial `0b340f8` candidate, which was held before production
activation after additional regressions were found. The corrected source and
new evidence are in `x-squared-validator-followup-2026-11-06.md`.

Working baseline: deployed worker source
`6e5c58dec2459962b2df498385d47cd8d6abe3a2`.

The incident investigation observed three consecutive
`x_squared_epsilon_delta` validation failures after model HTTP success. This
change addresses independently reproduced false rejection in that gate. The
failed production model outputs were not replayed, so this does not establish
recovery of the original request or a production success rate.

## Scope

The explicit positive delta, neighborhood condition, square-difference
factorization, epsilon estimate, and continuity conclusion remain required.
The existing sufficient-delta coefficient check remains unchanged. The gate now
recognizes consistent alpha-renaming, equivalent orders of the absolute-value
terms, and natural Japanese text after the complete delta expression. It refuses
arithmetic suffixes such as `+1`, `*2`, or `=1` rather than silently truncating
them. Only complete Japanese definition clauses end an un-delimited expression;
value-changing modifiers such as doubling or adding one are rejected. Japanese
proof openings can use either positive-epsilon notation with
natural wording rather than one exact sentence.

The epsilon estimate must follow the factorization or restate the same square
difference or the same distance-times-sum product. A bound on a different product
with an extra coefficient does not qualify. An unrelated `0 < epsilon` statement
is not an estimate of that
difference. The new negative cases expose and correct this pre-existing false
acceptance, including an upper bound of `epsilon + 1`.

Source-reference validation, generation-attempt limits, independent output review,
the verified proof state, request accounting, and failure diagnostics are
unchanged. There is no unreviewed-output fallback.

## Offline evidence

Existing development environment: Python 3.12, using `PYTHONPATH=.` from the
dedicated hotfix worktree. No package installation, model, AWS, database,
application process, or container operation was performed.

- Exact baseline's existing explanation suite: 66 passed.
- New 43 synthetic gate/parser cases on exact baseline: 14 failed, 29 passed.
- Same cases and seven related suites on the candidate: 255 passed.
- Changed-file Ruff, strict mypy of `pals_agent/explanations.py`, and
  `git diff --check`: passed.
- Worker story suite: 43 passed, one failed. The failure
  `test_committed_import_transport_failure_keeps_exact_candidate_and_bounded_visibility[False]`
  also fails on the exact baseline: the test expects a synthetic clock of 330,
  while the unchanged reconciliation timeout advances it to 2000. This assertion
  and production timeout were not changed.

Independent review found two defects in the initial candidate: Japanese
arithmetic modifiers were mistaken for expression endings, and a valid separate
estimate of the same product was rejected. Both are corrected with positive and
negative regressions. The doubling negative includes an exact rational
counterexample (`a = 0`, `epsilon = 1/2`, `x = 9/10`).

The related suite command is:

```sh
PYTHONPATH=. python -m pytest \
  tests/unit/test_explanations.py \
  tests/unit/test_x_squared_validator_incident.py \
  tests/unit/test_explanation_deadline_spec.py \
  tests/unit/test_explanation_linear_ending.py \
  tests/unit/test_explanation_shape_spec.py \
  tests/unit/test_automation_explanation_grounding.py \
  tests/unit/test_worker_claim_spec.py \
  tests/unit/test_semantic_review_exact_property.py
```

These tests exercise the actual deterministic parser/gate and the existing
isolated worker contracts. They do not prove mathematical accuracy of a model,
Lean compilation of new source, production deployment, or browser recovery.
The bounded gate still supports a specific epsilon-delta proof structure; it is
not a general mathematical equivalence checker. Independent review and actual
production acceptance remain necessary.
