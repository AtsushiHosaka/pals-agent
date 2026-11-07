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
