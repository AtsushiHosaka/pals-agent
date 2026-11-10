# Library profiles

A *library profile* (`pals_agent/lean_profiles.py`) names one pinned verification environment:
Lean toolchain, library set, workspace and import allow-list. One verifier process serves exactly
one profile, chosen by `PALS_LEAN_LIBRARY_PROFILE` (omitted = `mathlib-4.32`). A request body never
names a profile, so a proof cannot widen the libraries it may import; routing to a profile means
routing to that profile's verifier deployment.

| Profile | Lean | Workspace | Import roots |
|---|---|---|---|
| `mathlib-4.32` (default) | `v4.32.0-rc1` | `lean-workspace/` | unrestricted (unchanged) |
| `stacks-4.35` | `v4.35.0` | `lean-workspaces/stacks-4.35/` | `Mathlib`, `StacksCore` |
| `stacks-frontier-4.35` (flag, off by default) | `v4.35.0` | `lean-workspaces/stacks-4.35/` | `Mathlib`, `StacksCore`, built `StacksFrontier` modules |
| `stacks-frontier-defs-4.35` (own flag, off by default) | `v4.35.0` | `lean-workspaces/stacks-4.35/` | same; statements may also use Frontier definitions |

## Adding a library: a manifest, not code

Each library is one TOML file in `pals_agent/lean_libraries/` (schema
`pals.lean-library-manifest.v1`, loader `pals_agent/lean_library_manifest.py`): source repository,
exact commit, SPDX licence and attribution, Lean toolchain, workspace, pins, dependency roots,
trust *layers* by import root, the profiles it yields (import roots, statement policy, enabling flag),
the audit's axiom allow-list (a manifest may narrow it, never widen it), a reference to the build
recipe and the pinned declaration-index digest. `lean_profiles.py` derives every profile from the
manifests; tests pin the derived profiles to the values issued before manifests existed.

Trust words are generic: `kernel-checked-reviewed`, `kernel-checked-unreviewed`, `statement-only`.
The earlier words `core` and `frontier` stay readable as aliases (`canonical_trust`); audit result
levels (`mathlib`, `core`, `frontier_proof`, `frontier_statement`) are stored data and unchanged.

`python -m tools.library_index.build --library NAME --source DIR --out OUT` indexes any manifest's
layers (declaration name, kind, statement text, module, path, line, trust). Stacks tag parsing is
the optional `--plugin stacks-tags`.

## Digests

A non-default profile adds `"library_profile": "<name>"` to the toolchain fingerprint, so its
fingerprint digest, and every Recipe admitted under it, can never equal another profile's. The
default profile omits the key: its fingerprints are byte-identical to those issued before profiles
existed (pinned by `tests/unit/test_lean_profiles.py`). The key is accepted by the verifier and the
selection client; the Recipe catalog (`pals-api`) must accept it before a non-default profile's
Recipes can be admitted or selected.

## stacks-4.35

`StacksCore` (human-reviewed) is the only Stacks library built. `StacksFrontier` (AI-generated,
unreviewed) is kept out three ways: its sources are removed from the working tree by a sparse
checkout, nothing builds it, and the verifier rejects any import outside the allow-list
(`import Stacks` is rejected too, since it imports the Frontier).

`docker/lean-verifier-stacks.Dockerfile` is a definition only. To reproduce its steps by hand:

```bash
cd lean-workspaces/stacks-4.35
lake exe cache get            # Mathlib cache; resolves packages from the committed manifest
git -C .lake/packages/Stacks sparse-checkout set --no-cone '/*' '!/StacksFrontier/' '!/StacksFrontier.lean'
lake build StacksCore.Data.Finset.Card   # or `lake build StacksCore` for the whole library
```

Updating a pin means editing `lakefile.lean`, regenerating `lake-manifest.json` with `lake update`,
and updating the pins in `lean_profiles.py`; `test_lean_profiles.py` fails if they disagree.

## stacks-frontier-4.35 (disabled unless `PALS_LEAN_ALLOW_FRONTIER_PROOFS=true`)

`StacksCore` has no algebraic geometry; schemes and sheaf cohomology exist only in the unreviewed
`StacksFrontier`. This profile draws the line between *statement* and *proof* instead of at
`import`: a proof may use Frontier lemmas (the Lean kernel checks them; `sorry` and extra axioms
stay forbidden), but every constant a statement reaches (through the user's own definitions too)
must come from Lean, its reviewed dependencies, Mathlib or `StacksCore`. The trusted audit program
enumerates the constants of each restated statement and reports `untrusted_statement` for any
whose home module is outside those roots (`lean.statement_uses_untrusted_library`). It applies to
every `theorem`/`example` statement in the file, so state helper lemmas without Frontier constants.

Only the Frontier modules named in the image's `FRONTIER_MODULES` build argument exist; anything
else fails as an unknown module. `scripts/audit_frontier_closure.py` screens those modules and their
Stacks import closure with the candidate source policy (no `notation`, `macro`, `initialize`,
`unsafe`, native evaluation, ...) and stops the image build on a failure. The verifier refuses to
start with this profile unless the flag is set, and the Dockerfile deliberately does not set it.

## stacks-frontier-defs-4.35 (disabled unless `PALS_LEAN_ALLOW_FRONTIER_STATEMENTS=true`)

Relaxes `stacks-frontier-4.35` for one reason: schemes, ample line bundles, Picard groups and
similar objects have no Mathlib definition, so a statement about them can only be written with a
`StacksFrontier` definition. That definition was written by an AI and no human has reviewed it.
This profile accepts such a statement and records the fact; it does not make the statement
trustworthy. The flag is separate from `PALS_LEAN_ALLOW_FRONTIER_PROOFS`; neither opens the other.

What the trusted audit program records (all in the verification result as non-error diagnostics, so
the result stays `verified`):

- `lean.library_trust` with `metadata.trust_level`: `mathlib` (Lean and Mathlib only), `core`
  (uses the reviewed `StacksCore`), `frontier_proof` (only the proof uses Frontier lemmas) or
  `frontier_statement` (a statement reaches a Frontier definition; show it as *Frontier
  (human-unreviewed)*). Metadata also lists the Frontier constants and modules the statement
  reaches and the library roots of the statement and the proof. The statement walk goes through
  the file's own definitions and stops at the first imported constant on each path; the proof walk
  goes through file-local constants only, not through imported ones. A walk that cannot finish
  fails the audit instead of reporting a lower level.
- `lean.frontier_duplicate_definition`: a Frontier definition a statement reaches that looks like a
  Lean/Mathlib/StacksCore one: `same_value` (same type and body) or `same_shape` (same type and
  constructor names) are strong; `same_name` (same last name component and kind) is only a hint.
  Recorded, never rejected. It cannot find a concept defined differently under a different name.

What stays forbidden, unchanged: `sorry`, any axiom beyond `propext`, `Classical.choice` and
`Quot.sound`, native evaluation (`native_decide`, `decide +native`, `ofReduceBool`), imports outside
`Mathlib`, `StacksCore` and the built Frontier modules, and a statement constant from a root that is
neither reviewed nor Frontier. The kernel replay is mandatory. The level applies to every
`theorem` in the file, so keep helper lemmas free of Frontier definitions.

What it does not guarantee: that the Frontier definition means what Stacks or Mathlib means, or what
the user asked. Lean accepts a weaker or different theorem just as happily. Faithfulness comes only
from the pinned `formal_statement` (`lean.formal_harness_mismatch`) and from a review of it.
