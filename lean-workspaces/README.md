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
