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
median was 1.179 seconds and maximum 2.735 seconds; the batch plus axiom audit took
29.722 seconds. These are local compiler timings, not AWS or end-to-end response
latency. The report is a private generated artifact and is not committed.

Final corpus SHA256:
`c96876b736d92c73ac48f51f5093eed08ea45b006574058f89e75c0ec77514c5`.
Local report SHA256:
`f1856209dce8dda2ffe5929e35e832f9b1331b8a356e3e904aaed5e8272611fd`.

All 20 exact closed authoring materializations also compiled successfully in a
separate local run. Its report SHA256 is
`15e4f96bb4616f8ab451600944ddcdc72cd3ab881128be14f6c2d1bc759e1670`.
This checks the actual manifest renderer bytes, not an isolated-runtime receipt.

## Publication boundary

This is an offline authoring batch. It is **not** a signed PFI seed, a production
verification receipt, a DB admission, a retrieval claim, or a deployed release.
The report never changes these lifecycle flags.

The shortest supported manual route publishes searchable **Recipes and reviewed
Japanese answers**; it does not create Draft/OpenMath/embedding rows. Normal
proof-request candidate capture remains available separately. Twenty canonical
`publication/*.json` files use the existing `pals.recipe-authoring-manifest.v1`
schema. The operator-approved author is
`pals.principal.v1/codex/requested-math-seeds-20261031`; the toolchain identifier is
`lean-4.32.0-rc1-mathlib-8b62164d-aws-v1`. Their expected fingerprint uses the
observed active source pins. The real isolated verifier must independently
measure and match that fingerprint; these files do not assert it has done so.

1. In the API release environment, run each canonical authoring file through the
   existing real mTLS verifier and catalog admission:

   ```sh
   python -m app.release.lean_recipe_catalog_admit publication/requested.natural_power_continuous.json
   ```

   Required protected variables are `PALS_RECIPE_CATALOG_ADMISSION_DATABASE_URL`,
   `PALS_RECIPE_ADMISSION_VERIFIER_URL`, `PALS_RECIPE_ADMISSION_RELEASE_ID`,
   `PALS_RECIPE_ADMISSION_DEPLOYMENT_BINDING_SHA256`,
   `PALS_RECIPE_ADMISSION_VERIFIER_IMAGE_DIGEST`,
   `PALS_RECIPE_ADMISSION_VERIFIER_TOOLCHAIN_SHA256`, and
   `PALS_RECIPE_ADMISSION_TLS_{CA,CERT,KEY}_FILE`. Use actual release bindings and
   the admitted mTLS client, never guessed values. The release login must be able
   to `SET LOCAL ROLE pals_api_recipe_catalog_owner`.

   A separate profile/toolchain registration is unnecessary: the owning
   `_insert_all` transaction inserts these from the verified manifest and
   rejects conflicting pre-existing identities. Compilation occurs before that
   transaction. CLI stdout reports status, not the compiler receipt.

2. Export each real admitted revision's compiler receipt from the catalog owner
   transaction. Construct the existing
   `pals.recipe-admission-compiler-receipt.v1` object using its immutable
   `recipe_evidence` columns: `materialized_source_sha256`,
   `toolchain_fingerprint_sha256`, `compiler_command_sha256`, and parsed
   `compiler_result_jcs`. Verify its RFC8785 SHA against the stored
   `compiler_receipt_sha256`, and require the actual revision lifecycle to be
   `admitted`. Never substitute the local compilation report.

   Prepare an **unsealed** Japanese search candidate and the exact materialized
   Lean source, using that exported receipt:

   ```sh
   python testdata/requested-math-seeds-v1/publication.py \
     --recipe-id requested.natural_power_continuous \
     --compiler-receipt "$ACTUAL_ADMITTED_RECEIPT" \
     --output-directory "$NEW_PRIVATE_ENTRY_DIRECTORY"
   ```

   This helper has no DB/network/key access and cannot establish receipt origin;
   the release admission tool independently checks all identities against DB
   evidence. No receipt or search entry with invented receipt hashes is included
   in this corpus. Output is create-only, private, and remains unreviewed.

3. Run the existing independent real-provider review in the agent environment:

   ```sh
   python -m pals_agent.recipe_entry_review \
     --entry "$NEW_PRIVATE_ENTRY_DIRECTORY/entry.json" \
     --lean-source "$NEW_PRIVATE_ENTRY_DIRECTORY/Main.lean" \
     --output "$NEW_SEALED_ENTRY" \
     --reviewer-principal pals.principal.v1/reviewer/requested-math-seeds-20261031 \
     --review-key-id "$APPROVED_REVIEW_KEY_ID" \
     --private-key "$EXISTING_PRIVATE_ED25519_PKCS8_FILE"
   ```

   It requires an actual provider credential (`PALS_OPENAI_API_KEY`, or the
   supported `OPENAI_API_KEY` fallback). The independent provider request and
   approval are mandatory; the reviewer identity must differ from the author.
   Keep keys and provider credentials outside the repository. This command does
   not generate signing keys.

4. In the API release environment, admit the sealed search entry:

   ```sh
   python -m app.release.recipe_search_admit \
     --manifest "$NEW_SEALED_ENTRY" --review-keys "$PINNED_PUBLIC_REVIEW_KEYRING"
   ```

   It requires `PALS_RECIPE_ENTRY_RELEASE_DATABASE_URL`. The explicit operator
   keyring maps the approved key ID to its Ed25519 public key hex. A new key can
   be deliberately pinned there; no runtime global keyring initialization is
   required. The admitted row stores that public key and the runtime rechecks its
   signature, independent reviewer identity, exact compiled source, and immutable
   compiler evidence. Admission is followed by actual search/answer replay;
   local compilation alone does not establish retrievability or runtime success.

To independently compile all exact closed materializations before publication:

```sh
PYTHONPATH=. python testdata/requested-math-seeds-v1/verify_publication.py \
  --project "$EXISTING_LEAN_PROJECT" --lean-binary "$PINNED_LEAN_BINARY" \
  --output "$NEW_PRIVATE_PUBLICATION_REPORT"
```

The witness corpus uses Japanese primary questions and answers because the
existing schemas have no paraphrase field. In particular the tangent problem
asks whether the value is rational; its answer and Lean target establish
irrationality. English authoring history remains available in commit `06815bc`.
