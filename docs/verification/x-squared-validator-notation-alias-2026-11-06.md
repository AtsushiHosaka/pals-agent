# Continuity explanation notation and bound aliases

This is a source-only follow-up to deployed worker
`cc75c3fb2d4ec18b2e30b1f4eea9fa0c304ea171`. The explicit working contract is
the incident's existing explanation validation plus standard mathematical layout
and one safely bound positive-constant alias. It does not change the proof,
independent answer review, retry limit, provider configuration, accounting,
source-reference checks, or production runtime.

## Evidence and scope

The original three failed production outputs were not retained. A separate,
explicitly bounded diagnostic generated one new explanation for the same verified
proof. Its public mathematical payload defines `C = 2|a| + 1`, chooses
`delta = min(1, epsilon/C)`, factors the square difference, first bounds it by
`|x-a|C`, and later bounds it strictly by `(epsilon/C)C = epsilon`.

The deployed validator rejects that new sample because it expects the fixed
point's absolute value literally inside the delta expression. Resolving that
alias alone is insufficient: its first separate estimate has no epsilon ending,
and the later estimate finishes with an exact cancellation rather than a literal
inequality ending in epsilon. This reproduces a supported-form rejection in the
new diagnostic. It is not a replay of the original failed outputs and does not
prove their exact cause.

Independent offline notation probes also found nine rejections among fourteen
equivalent representations of a complete epsilon-delta proof. The rejected
representations use sized absolute-value delimiters or alignment markers in
`aligned`, `align*`, and `array`.

## Changes and retained boundaries

The normalizer removes only the finite `big`/`Big`/`bigg`/`Bigg` size-command
families when followed by a delimiter. It flattens only matching, non-nested,
bounded alignment environments. Arrays require a small closed `l`/`c`/`r`
column preamble; unknown commands and text commands keep the layout unchanged.
The added presentation handling preserves unknown macro names, text, unmatched
environments, and ampersands outside these environments. Cell/row boundaries between mathematical
atoms remain intact; only explicit relation continuations are joined, so layout
cannot synthesize a multiplication from independent cells or rows.

The delta may refer to one uppercase single-letter bound alias. Its sole
assignment must precede the delta within a bounded span. The assigned expression
must pass the existing sufficient positive-denominator check and contain exactly
one fixed point. Rebinding, circular definitions, and collisions with the fixed
point or varying variable are refused. Only the isolated delta choice is
expanded; the whole proof is never renamed or rewritten. Parenthesized
assignments, finite definition/assignment symbols, and completed explicit
Japanese replacement/scaling-update clauses are included in the rebinding check; a cancellation
product ending in `)C=epsilon` is not a new assignment.

The existing ordinary epsilon-ending test remains in place. An additional route
examines later estimates of the same literal difference or factored product,
but accepts only closed cancellation by that same positive alias or the exact
literal denominator from the sufficient delta choice. The literal denominator
is retained before fixed-point normalization and is matched to both the divisor
and multiplier. A strict delta-times-bound bridge followed by its canonical
quotient product is accepted; weak-only chains are not.
It does not turn a bare conclusion `|difference| < epsilon` into a new bridge,
or accept a different denominator, different multiplying constant, unrelated
comparison, non-strict cancellation, or an `epsilon + 1` ending.

## Local verification

The existing 62 incident regressions pass. The new 154-case notation/alias suite
covers the fourteen positive forms, 42 mathematically invalid variants, fourteen
weaker-ending gate controls, delimiter families, unknown-command boundaries,
unique alias definitions, rebinding/collision errors, later estimates, and exact
cancellation. The weaker-ending controls retain a correct delta and auxiliary
bounds; they test the gate's required bridge, not falsity of the theorem.

Replaying the unchanged seventy-case offline matrix gives:

| Cases | Deployed source accepted | Candidate accepted |
|---|---:|---:|
| Correct equivalent forms, 14 | 5 | 14 |
| Mathematical errors, 42 | 0 | 0 |
| Weaker-ending controls, 14 | 1 | 0 |

The new isolated public payload passes the candidate's full parser against the
actual saved 66-line Lean proof, including all four exact source excerpts,
Japanese output, the epsilon-delta requirement, and the linear-ending check.
The unmodified payload and actual proof remain private local evidence, not Git
fixtures. Committed tests use synthetic mathematical examples only. No
independent model QA or new provider call was run by this implementation task.

The final combined nine-file explanation/source/deadline run passes all 526
tests, including both regression files. HTTP deadline tests require
temporary loopback listeners: the sandbox initially refused their binds, and
the nine tests passed when run with loopback permission. Changed-file Ruff and
strict mypy for the production module pass.

Verification reused the existing Python 3.12 development environment and
`PYTHONPATH=.`. The final run selected `test_explanations`,
`test_explanation_deadline_spec`, `test_explanation_linear_ending`,
`test_explanation_shape_spec`, `test_http_hard_deadline_spec`,
`test_automation_explanation_grounding`, `test_lean_source_policy`,
`test_x_squared_validator_incident`, and `test_x_squared_validator_notation`.
An independent seven-case adversarial probe also confirms rejection of wrapped
alias rebinding and independent-cell/row factorization synthesis.

The worker-story suite remains 43 passed and one established baseline failure:
its synthetic clock expects 330 while the unchanged reconciliation timeout
produces 2000. No clock assertion or runtime timeout was modified.

This evidence validates source behavior only. No AWS, database, model, container,
deployment, or production request was executed by this implementation task.
The candidate still needs independent source review and a separately authorized
release; successful production explanation delivery is not claimed.
