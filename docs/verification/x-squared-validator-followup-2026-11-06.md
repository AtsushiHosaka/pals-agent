> **Superseded (2026-11-06).** The text gate described here (`_has_x_squared_epsilon_delta`
> and the opening-pattern requirement) was removed. The epsilon-delta requirement is now judged
> by the independent QA review; see `explanation-semantic-gate-2026-11-06.md`. This record is
> kept unchanged as history.

# Continuity-validator follow-up, 2026-11-06

This follow-up is an uncommitted delta over
`0b340f8877f93bfb4ac9c94c926eeb673018c113`. That commit and its earlier evidence
are retained. No release or production recovery is claimed.

Independent review found two valid proof forms rejected by the first hotfix:
an equality chain rewriting the factored product before the epsilon estimate,
and a general square-difference identity appearing before the point-specific
proof. The first matching pair of variables must not determine the proof scope.

The validator now considers each varying point paired with the delta's fixed
point, then connects a neighborhood condition to a later factorization for that
same literal variable pair. Mathematical equality tokens may connect the product
to its inequality estimate. This retains separate estimates of the same product.

A further negative case during implementation exposed capture when the entire
proof was renamed to a/x. A preceding b/y identity could then mix its neighborhood
with an unrelated a/x estimate. The implementation now normalizes only the
isolated delta expression for the existing coefficient check. It matches the
proof's point and varying variable literally; both capture negatives are refused.
All matching factorizations after the neighborhood are considered, so an earlier
general identity using the same pair does not mask a later connected estimate.

The same delta bounds, source references, independent model review, attempt limits,
failure diagnostics, accounting, and verified proof state remain in force. This
bounded text gate does not establish semantic validity of arbitrary algebraic
chains and cannot replace the independent mathematical review.

## Evidence

The final new regression file contains 62 synthetic cases, including 19 added in
this follow-up. Using the exact historical modules with the unchanged new tests:

| Module | Passed | Failed |
|---|---:|---:|
| Original deployed 6e5c58d | 39 | 23 |
| First hotfix 0b340f8 | 51 | 11 |
| Follow-up candidate | 62 | 0 |

The full parser is exercised alongside the internal gate. Positive cases include
connected equalities, unrelated u/v identities, general identities sharing the
fixed point, and a general identity using the same pair before its neighborhood.
Negative cases retain missing setup, wrong delta, unrelated epsilon comparisons,
epsilon + 1, an extra product coefficient, mismatched points, and bad references.

Eight related suites pass 274 tests. Changed-file Ruff, strict mypy for
`pals_agent/explanations.py`, and `git diff --check` pass. The broader worker-story
suite remains at 43 passed and its one established baseline failure: synthetic
clock 330 expected versus the unchanged reconciliation timeout of 2000 observed.
No assertion or timeout was changed to hide this failure.

Execution reused the existing Python 3.12 development environment with
`PYTHONPATH=.`. New logs are isolated under `.incident-verification/revision2/`;
the earlier artifacts were not overwritten. Baseline comparison loads each exact
historical module in a separate test process without changing the candidate file.

No model, AWS, database, application process, container, commit, push, or production
operation was performed for this follow-up. The original production model output
has not been replayed, and deployment/browser acceptance remains unverified.
