# Dedicated x² continuity Recipe: what exists and what publication still needs

Recipe id `continuity.square.explicit-epsilon-delta`, revision 1, statement "the function
f(x)=x² is continuous at every point of ℝ", stored answer an explicit ε–δ proof in Japanese.
Tracking issue: AtsushiHosaka/pals#287 (incident #223).

**Status: authored and locally checked only. Nothing below is admitted, reviewed, signed,
embedded, published or deployed.** `card.json` keeps every lifecycle flag except `authored` false.

## What is in this repository

All files are under `testdata/square-continuity-recipe-v1/`.

| File | Role |
| --- | --- |
| `card.json` | Statement, domain, assumptions, quantifiers, conclusion, `proof_method_tag: epsilon_delta`, stored Japanese answer, paraphrases, aliases, ten hard negatives |
| `proofs/square_continuous_explicit_epsilon_delta.lean` | The single theorem; its proof body is the one in the manifest |
| `publication/continuity.square.explicit-epsilon-delta.json` | Canonical `pals.recipe-authoring-manifest.v1` (author `pals.principal.v1/claude/square-continuity-recipe-20261106`) |
| `publication.py` | `manifest` and `entry` commands; `entry` needs a real admitted compiler receipt |
| `verify.py` | Local compile of the exact materialized source plus a transitive axiom audit |
| `tests/unit/test_square_continuity_recipe.py` | Contract tests; the API repository holds copies of the artifacts and asserts the same digests |

The target is `Continuous (fun x : ℝ => x ^ 2)`: domain and codomain ℝ, exponent the literal `2`,
no further hypothesis. The proof does not use a shortcut continuity lemma. It takes
`δ = min 1 (ε / (2|a|+1))`, bounds `|x+a| < 2|a|+1` from `|x-a| < 1`, and factors
`|x²-a²| = |x-a||x+a|`. The stored answer carries the same δ and the same chain, with inline
KaTeX only and no headings. The statement ends with an English gloss on purpose: the local
2–4-gram ranker reads only `statement`, and without the gloss English requests fall outside the
five-entry judge window.

The authoring manifest binds the toolchain frozen by `requested-math-seeds-v1`
(`lean-4.32.0-rc1-mathlib-8b62164d-aws-v2`, verifier hash `8a13da18…`). **That is the last binding
recorded in this repository, not an observation of production.** See step 0.

## What was checked locally

- Lean `v4.32.0-rc1` (commit `b4812ae5…`, not the PATH `4.35.0`), Mathlib `8b62164d…`, an existing
  compiled project whose `lake-manifest.json` hashes to the frozen fingerprint's
  `lake_manifest_sha256` (`290f048c…`). `verify.py` compiled the exact materialized source
  (SHA-256 `e2da4f1a…`) with exit 0 and no diagnostics in 28.8 s, and `#print axioms` listed only
  `propext`, `Classical.choice`, `Quot.sound`. The report is private and not committed.
  This is a direct `lean` run without Lake, not the isolated verifier: it is no receipt.
- The API repository's `RecipeAuthoringManifestV1.parse`, `RecipeMaterializerV1`,
  `validate_materialized_recipe` and `RecipeSearchEntry` accept the manifest and an entry built
  with a synthetic receipt (see its `tests/unit/test_square_continuity_recipe.py`).
- All 82 formulas in `card.json` render with KaTeX 0.16.47 in strict mode.
- The answer passes the repository's own x² gate (`_has_x_squared_epsilon_delta`) and the Lean
  vocabulary gate, and its inequalities hold in exact rational arithmetic on 94,464 points.
- The local ranker puts the card in the top three of 21 entries for the exact statement and all
  eleven paraphrases. With scripted judge replies the real client path returns the stored answer
  with a `lean_catalog` binding. **The judges' replies in that test are scripted. No model judged
  anything**, so rejection of wrong statements by the real judges is not shown.

## What cannot be done offline and remains

0. **Read production.** Look up every revision of this id in the Recipe catalog and the active
   toolchain. If revision 1 already exists with other content, raise `revision` in `card.json` and
   regenerate every pin. If the verifier fingerprint differs from the frozen one (a changed
   verifier makes every older Recipe unselectable, see `recipe_toolchain_readmission`), pass the
   observed object: `publication.py manifest --toolchain-json F` and `entry --toolchain-json F`.
   Do not reuse the frozen binding by assumption.
1. **Compiler evidence.** Admit the manifest through the existing mTLS verifier:
   `python -m app.release.lean_recipe_catalog_admit publication/continuity.square.explicit-epsilon-delta.json`
   in the release environment. The local run does not count. A failure there (policy or a
   verifier-side difference) must be fixed in the proof, not waived.
2. **Entry.** Export the admitted revision's real `pals.recipe-admission-compiler-receipt.v1` and run
   `publication.py entry --compiler-receipt R --output-directory D`. The entry is unreviewed.
3. **Independent review and signature.** A principal other than the author runs
   `python -m pals_agent.recipe_entry_review` on `D/entry.json` and `D/Main.lean` with a real
   provider request, signing with the existing approved review key. A human check of the answer
   against the Lean target is advised. No new key is created.
4. **Embedding.** Compute the 1024-dimension `text-embedding-3-large` vector (binding
   `pals.recipe-retrieval-text.v1`) for `retrieval_text(entry)`, which is the statement, domain,
   conclusion and assumptions, not `search_text`.
5. **Publication transaction.** `recipe_search_admit` and `recipe_retrieval_admit` are separate
   commands with separate connections. The issue requires entry and vector in one transaction so
   that the vector search does not drop to the lexical fallback for the whole catalog. Both expose
   functions that take a cursor, but no wrapper exists. Either add one, or quiesce traffic.
6. **Replay on the real path.** The Japanese incident request must return a `lean_catalog`
   answer with `answer_sha256`, `lean_sha256` and the source hash equal to the admitted entry, and
   no `formal_job_id`. Run the ten hard negatives in `card.json` through the real two judges
   (a small paid regression) and expect no reuse for any of them; none of that has been run.

## Not done on purpose

- No exact-input profile (the zero-model path). It pins the entry, receipt and source hashes,
  which exist only after step 1 to 3, and must be added to both repositories together.
- No Draft alignment. `pals-scripts/prepare-square-recipe-witness.py` in the parent repository
  prepares one for the seed Draft `continuous_square`; it was not ported.
- No change to matching, admission, review prompts or retrieval. In particular this card does
  not rely on specializing the natural-power Recipe, which remains rejected as the same content.

## Risks to know before step 5

- The lexical fallback is weak for short symbolic queries. Against a catalog where all ten hard
  negatives are separate near-duplicate entries, three of twelve paraphrases left the API's top
  five. The embedding path must carry those; publish the vector with the entry.
- The five-entry judge window may contain the natural-power Recipe ahead of this card. The judges
  must pick the exact one; that is a model behaviour that offline tests do not cover.
- A request that demands a method other than ε–δ, or any request whose scope differs on one
  dimension, relies entirely on the judges. The card's `quantifiers` field states the pointwise
  reading ("δ may depend on a") so that uniform continuity is separable.
