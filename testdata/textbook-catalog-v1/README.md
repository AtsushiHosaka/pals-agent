# Textbook Recipe and Draft candidates

These cards aim to cover the standard propositions of Japanese undergraduate mathematics through
the fourth year, middle and high school mathematics including elementary geometry, and problems
famous from university entrance exams. Most are small lemmas meant to close a gap in a proof sketch,
and famous theorems are included so nobody has to add them later.

Each card in `cards/<domain>.yaml` yields one Recipe authoring manifest, one unsealed Japanese
search candidate and one Draft candidate. See `AUTHORING.md` for the contract.

| Cards | Domains | gap | textbook | named |
| ---:| ---:| ---:| ---:| ---:|
| 1,899 | 41 | 1,143 | 576 | 180 |

| Level | middle | high | 1 | 2 | 3 | 4 |
| ---:| ---:| ---:| ---:| ---:| ---:| ---:|
| Cards | 119 | 718 | 263 | 308 | 329 | 162 |

## What was checked

Lean 4.32.0-rc1 with Mathlib `8b62164d808cd0f23b7d8cc28190a6c1a1bb483a`, the frozen AWS v2 toolchain
binding used by `requested-math-seeds-v1`.

- All 1,899 materialized sources compiled individually without errors.
- All 1,899 passed an axiom audit allowing only `propext`, `Classical.choice` and `Quot.sound`.
- Every manifest passed the API's `RecipeAuthoringManifestV1.parse`, `RecipeMaterializerV1` and
  `validate_materialized_recipe`.
- All 67,864 formulas in the Japanese text rendered with KaTeX 0.16.47 in strict mode.
- A reviewer other than the author compared each card's text and OpenMath against its Lean target.
  The answers were later rewritten into complete proofs, and that rewrite was checked by its author
  only. It is not the signed independent review that search publication requires.
- The 837 middle school, high school and geometry cards had one reviewer other than the author, who
  read them after their answers were written. Answers that a reviewer rewrote have only that
  reviewer's reading. This is not the signed review either.

The compile report is a local generated artifact and is not committed. It binds
`generated/index.json` at SHA-256
`7030d9f286940b092b5cfeb795a337c84e86a7b96b74d835e8bb5511149e1c55`.

## What this does not establish

This is an offline authoring batch. Nothing here has an AWS admission receipt, a signed search
entry, an embedding, a database row or a measured retrieval result. The release boundary must
compile each manifest again. Search publication also needs the 32-entry retrieval limit lifted
first (`recipe_local_retrieval.py`, `recipe_semantic_contract.py`).

## Known risk before search publication

With real reviewers on 1,082 candidates, a general question about two lists of real numbers
wrongly reused `cauchy_schwarz_two_dimensional` in 10 of 10 reviews. It also happens with the earlier
answer text, so the cause is in the review, not the rewrite. Special and general forms of one fact
exist elsewhere too, such as `amgm_two_variables` with `amgm_finite_family`, and
`total_probability_two` with `total_probability_partition`. Publishing them needs that review fix
first. Measurements are in `AtsushiHosaka/pals#150`.

## Draft tiers

Only 460 Draft candidates (`tier: generic_now`) pass the deployed retrieval validator and are new.
One more (`tier: duplicate_of_existing`) has the same canonical OpenMath as the existing Draft
`nt_gcd_lcm_product_identity`, so it is not a new Draft, although its Recipe is. The comparison used
the 427 canonical records found in this repository's sources, not a read of the production table,
so it must be repeated at load time. The other 1,438 (`tier: needs_vocabulary`) use a proposed additive OpenMath dictionary, `pals2`, listed in
`generated/vocabulary.json` with 1,055 symbols. The deployed validator rejects unknown symbols when it
reads a row, so these rows must not be loaded until the validator and query structuring accept that
vocabulary. `catalog.py` layers the dictionary over the runtime tables for validation only and
changes nothing at runtime.

## Minimal imports

`generated/min-imports.json` records a narrow import list per card, as extra data. The materializer
and the admitted source stay on `import Mathlib`. The list comes from Mathlib's `#min_imports` and
is adopted only when the card compiles with that list alone and its statement prints identically
under `pp.all`. 1,888 of 1,899 were adopted; 6 kept `import Mathlib` because the statement differed
and 5 because the narrow file did not compile. Lists can include modules the proof does not really
need, so they are sufficient rather than strictly minimal.

## Case coverage

`case-coverage/quadratic-cases.json` lists the quadratic function questions a school course asks,
with every case for each one, including boundaries and a negative leading coefficient. Each case
names the general cards it relies on and has one concrete problem, proved in Lean by substituting
into those cards. `python case_coverage.py quadratic` compiles them, so a failure means the cards do
not cover that case. It has 13 questions and 132 cases: existing cards covered 81, and
`cards/school_quadratic_cases.yaml` adds 19 cards for the other 51. These concrete problems are
evaluation data and are not cards. The table only shows that a card exists for each case. It says
nothing about whether retrieval finds that card.

`specs/draft-catalog-expansion/coverage-matrix.v1.json` cannot hold this table: its `family` object
is closed and has no case axis, and a Draft binding has one primary mode and difficulty, while one
general card serves many cases. The two are joined by `coverage_matrix_family`.

## Other files

- `old-draft-generalization-proposal.json` lists older high school Draft candidates with a general
  form for each one that could be replaced, and compiled Lean for those forms. It is a proposal, and
  nothing has been deleted.
- `pilot/` holds 162 university cards used to measure authoring cost. They pass `check` and
  `lint-text` but have not been reviewed, and they are outside `build`, the counts above and the
  index.

## Commands

Run from this directory with the API environment and both repositories on `PYTHONPATH`, plus
`PALS_LEAN_WORKSPACE` naming an existing compiled pinned workspace:

```sh
python catalog.py check <domain>
python catalog.py lint-text <domain>
python catalog.py apply-text <domain> <patch.yaml>
python catalog.py build
python catalog.py verify --jobs 12 --output /absolute/report.json
python catalog.py min-imports --jobs 12 --output /absolute/report.json
python case_coverage.py quadratic
```

`apply-text` can change only the Japanese learner-facing fields, so it cannot alter Lean or Draft
data. `check` loads only `vocabulary/core.yaml` and that domain's file; `build` merges all of them
and fails on a conflicting signature.
