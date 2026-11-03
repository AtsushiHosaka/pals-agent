# Recovered closed Recipe candidates

These 82 authoring manifests recover existing mathematical statements and proofs:
43 from calculus-v5 and 39 from linear-algebra-v5. `sources.json` binds each case
to its original parent-repository manifest, witness bundle, example ordinal,
and the new closed materialized source. They are not 82 newly distinct theorems
relative to every other PALS catalog.

The original 104-card replay also included 22 elementary group/ring cards.
Those 22 were not converted: their stored target was not an accepted complete
`example` header. No missing binder or premise was inferred.

For each converted header, the original binders become universal quantifiers.
The proof introduces those same binders and runs the unchanged original proof.
Repeating annotated lambda binders was rejected during compilation because fresh
universe metavariables changed some linear-algebra terms. The committed version
uses introductions into the existing target context.

On 2026-10-31 all 82 closed materialized sources compiled in a batch using the
existing native Lean 4.32.0-rc1 project, Mathlib revision
`8b62164d808cd0f23b7d8cc28190a6c1a1bb483a`. A second batch renamed each anonymous
example and printed its transitive axioms: all 82 passed with only `propext`,
`Classical.choice`, and `Quot.sound` allowed. The original witness source was also
compiled and audited separately. No compiler or library installation was copied.

The materialized batch SHA-256 was
`c4ed84aea6db5865fb55772d0e1ca0bf786db7ef48449b5474686d1f66020e97`.
The named axiom-audit batch SHA-256 was
`3aec5278e7996c7843f89cf30c9b62a54b773fa607dbb6e8f9cfd02ef3c13f37`.
Local diagnostics remain outside Git in the parent's
`.local/aws-migration/typed-expansion-20261031/recipe-candidates-v2/`.

This is local compiler evidence only. No AWS admission receipt, independent
semantic review, search publication, Japanese answer, or public runtime result
is asserted. The existing release boundary must compile each immutable manifest
again, and independently approved answers must precede search publication.
Do not synthesize a runtime compiler receipt from these local results.

Use the owning API's `RecipeAuthoringManifestV1.parse`,
`RecipeMaterializerV1.materialize`, and `validate_materialized_recipe` to recover
the exact closed source from each manifest. The toolchain binding is the frozen
AWS v2 binding already used by `requested-math-seeds-v1`; an updated toolchain
requires a new explicitly reviewed revision, not editing admitted artifacts.
