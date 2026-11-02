# Textbook Recipe and Draft candidates

These cards aim to cover the standard propositions of Japanese undergraduate mathematics through
the fourth year, plus problems famous from university entrance exams. Most are small lemmas meant
to close a gap in a proof sketch, and famous theorems are included so nobody has to add them later.

Each card in `cards/<domain>.yaml` yields one Recipe authoring manifest, one unsealed Japanese
search candidate and one Draft candidate. See `AUTHORING.md` for the contract.

| Cards | Domains | gap | textbook | named |
| ---:| ---:| ---:| ---:| ---:|
| 1,062 | 23 | 591 | 344 | 127 |

## What was checked

Lean 4.32.0-rc1 with Mathlib `8b62164d808cd0f23b7d8cc28190a6c1a1bb483a`, the frozen AWS v2 toolchain
binding used by `requested-math-seeds-v1`.

- All 1,062 materialized sources compiled individually without errors.
- All 1,062 passed an axiom audit allowing only `propext`, `Classical.choice` and `Quot.sound`.
- Every manifest passed the API's `RecipeAuthoringManifestV1.parse`, `RecipeMaterializerV1` and
  `validate_materialized_recipe`.
- All 38,871 formulas in the Japanese text rendered with KaTeX 0.16.47 in strict mode.
- A reviewer other than the author compared each card's text and OpenMath against its Lean target.
  The answers were later rewritten into complete proofs, and that rewrite was checked by its author
  only. It is not the signed independent review that search publication requires.

The compile report is a local generated artifact and is not committed. It binds
`generated/index.json` at SHA-256
`ca12e4fed39b11ccd34ed5d01589a2570725f5c575ac18092cb1db1389b041ee`.

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

Only 87 Draft candidates (`tier: generic_now`) pass the deployed retrieval validator and are new.
One more (`tier: duplicate_of_existing`) has the same canonical OpenMath as the existing Draft
`nt_gcd_lcm_product_identity`, so it is not a new Draft, although its Recipe is. The comparison used
the 427 canonical records found in this repository's sources, not a read of the production table,
so it must be repeated at load time. The other 974 (`tier: needs_vocabulary`) use a proposed additive OpenMath dictionary, `pals2`, listed in
`generated/vocabulary.json` with 976 symbols. The deployed validator rejects unknown symbols when it
reads a row, so these rows must not be loaded until the validator and query structuring accept that
vocabulary. `catalog.py` layers the dictionary over the runtime tables for validation only and
changes nothing at runtime.

## Minimal imports

`generated/min-imports.json` records a narrow import list per card, as extra data. The materializer
and the admitted source stay on `import Mathlib`. The list comes from Mathlib's `#min_imports` and
is adopted only when the card compiles with that list alone and its statement prints identically
under `pp.all`. 1,054 of 1,062 were adopted; 6 kept `import Mathlib` because the statement differed
and 2 because the narrow file did not compile. Lists can include modules the proof does not really
need, so they are sufficient rather than strictly minimal.

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
```

`apply-text` can change only the Japanese learner-facing fields, so it cannot alter Lean or Draft
data. `check` loads only `vocabulary/core.yaml` and that domain's file; `build` merges all of them
and fails on a conflicting signature.
