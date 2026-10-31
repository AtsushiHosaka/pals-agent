# Requested mathematics seed candidates

Twenty original question/answer candidates cover natural-power continuity, a
right-hand limit with a different point value, standard calculus and linear
algebra proofs/decisions/computations, `tan(π/180)` irrationality, and `π>3.05`.
Each `proofs/*.lean` file contains one named theorem. Statements include their
hypotheses; the right-limit problem leaves all negative-side values arbitrary.
The degree/radian conversion for the tangent problem is explicit.

`corpus.json` uses the existing `pals.mathematical-breadth-corpus.v1` input schema.
Each case includes a full `question`, natural-language `answer`, ordered proof
outline, a false extension/counterexample, a pinned primary-library reference,
and the exact single-theorem witness. The Lean statements—not just the natural
answers—must pass the compiler before this batch is handed to publication.

From the agent repository, reuse the already installed pinned toolchain and
compiled dependencies. The verifier invokes the Lean executable directly with
existing library search paths: it does not call Lake, fetch/build dependencies,
or write to the reused project or its cache.

```sh
PYTHONPATH=. python testdata/requested-math-seeds-v1/verify.py \
  --project "$EXISTING_LEAN_PROJECT" \
  --lean-binary "$PINNED_LEAN_BINARY" \
  --output "$NEW_PRIVATE_REPORT_FILE"
```

The output must not exist. The project must have Lean `v4.32.0-rc1`, Mathlib
`8b62164d808cd0f23b7d8cc28190a6c1a1bb483a`, and the exact clean dependency
checkouts recorded in its Lake manifest. The report binds corpus/source/compiler
bytes, actual compiler exit codes and a separately compiled `#print axioms`
audit. Only the standard foundational axioms `propext`, `Classical.choice`, and
`Quot.sound` are accepted. No witness declares a new axiom or uses an admission
placeholder. Existing prebuilt artifact origin is not audited by this runner.

## Local verification result

The 2026-10-31 final run compiled all 20 exact witnesses and the transitive axiom
inspection. Only `propext`, `Classical.choice` and `Quot.sound` occurred; some
witnesses used no axioms. Seventeen files use focused imports; three retain the
Mathlib umbrella import. With the reused native macOS cache, per-case compiler
median was 1.183 seconds and maximum 2.575 seconds; the batch plus axiom audit took
29.417 seconds. These are local compiler timings, not AWS or end-to-end response
latency. The report is a private generated artifact and is not committed.

Final corpus SHA256:
`806611664808cb605e04108dc86cce85efb997050e6f0ae2fd66398ffc1fea2c`.
Local report SHA256:
`6e0ff3a5c85074ee4a433c288466df11c9a1b34327e0e0e494fd5ae90e96d6bf`.

## Publication boundary

This is an offline authoring batch. It is **not** a signed PFI seed, a production
verification receipt, a DB admission, a retrieval claim, or a deployed release.
The report never changes these lifecycle flags.

The existing supported DB route is owned by `pals-api`:

1. Run each full question through the real proof/answer/review flow after the
   runtime is ready. The repository captures eligible candidates only from
   immutable verified proof data with matching explanation-review hashes
   (`app/infrastructure/repositories/draft_addition_candidates.py`). These local
   witnesses may guide/compare the result; they do not replace that authority.
2. An operator lists the captured candidates with
   `python -m app.release.draft_candidates list`, using the dedicated protected
   `PALS_DRAFT_CANDIDATE_OPERATOR_DATABASE_URL`.
3. Prepare the actual reviewed recipe, then approve its complete signed bundle:

   ```sh
   python -m app.release.draft_candidates prepare-recipe \
     --candidate-id "$ACTUAL_CANDIDATE_ID" --recipe-manifest "$ACTUAL_RECIPE_MANIFEST"
   python -m app.release.draft_candidates approve \
     --bundle "$ACTUAL_PUBLICATION_BUNDLE" --review-keys "$ACTUAL_REVIEW_KEYS"
   ```

   The existing bundle schema is `pals.candidate-publication.v1` with exactly
   `candidate_id`, `recipe_manifest`, `draft_manifest`, and `entry_manifest` plus
   `schema_version`. Its `pals.candidate-draft.v1` manifest contains the five
   Draft payload fields (`id`, `canonical_statement`, `openmath_xml`,
   `proof_strategy`, `sketch_steps`), the exact embedding input/binding, and the
   signed semantic review bound to the candidate's real Lean/answer hashes.

The operator CLI has no arbitrary local-source import/INSERT action. OpenMath
alignment, signed semantic reviews, actual embeddings and runtime admission
remain required. This corpus deliberately does not fabricate them. The separate
110-card continuity catalog also retains its existing authorship/source-review/
formal-receipt requirements and signed-worker publication path.
