# Existing mathematical corpus recovery and local Lean replay

This tool recovers the exact existing mathematical records named by the parent
repository's versioned inventory. It adds no renamed examples, numeric variants,
database rows, embeddings, signatures, or publication receipts. The source index
pins 42 authoring manifests and their exact witness bundles, historically 749
local typed cards across 30 profiles. The current owning loaders accept 41
manifests and 744 records. Five plane-geometry records fail the existing manifest
validator and remain excluded; this tool does not repair or bypass that evidence.

Run from `pals-agent` with the existing Python environment:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python testdata/catalog-expansion-v1/catalog.py \
  --output .local/catalog-expansion-v1/inventory.json
```

The exclusive 0600 output exports each card's original statement, proof strategy,
sketch, typed canonical XML, Lean target/witness, imports, profile, manifest and
bundle hashes, and exact source-example ordinal. An older manifest may list only
the inner conclusion as its target. In that case, recover the full outer binders
from the indexed example in the exact original bundle; do not invent premises.

All 744 IDs and canonical XML values are distinct. The existing curriculum audit
heuristic finds 736 structural signatures, ignoring variable names and numeric
literals. Repeated signatures are review signals, not proof of logical
equivalence; different signatures do not prove distinct mathematical content.
Overlap with ordinary Drafts and previously published Recipes still needs
content review. Historical ordinary Draft 433 plus local typed 749 does not
establish 1,182 usable, distinct runtime records.

Replay selected bundles against an **existing** compiled, pinned project:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python testdata/catalog-expansion-v1/catalog.py \
  --verify --project /absolute/existing/lean-workspace \
  --lean-binary /absolute/pinned/toolchain/bin/lean \
  --only-source typed.math-typical \
  --only-source typed.linear-algebra-v5 \
  --only-source typed.calculus-v5 \
  --output .local/catalog-expansion-v1/first-replay.json
```

Omit `--only-source` to replay every valid bundle. No dependency is built or
downloaded. The project must have Lean `v4.32.0-rc1`, actual clean Mathlib commit
`8b62164d808cd0f23b7d8cc28190a6c1a1bb483a`, the exact locked dependency checkouts,
and compiled library artifacts. Precompiled artifact origin is not audited.

For every selected bundle, the tool first compiles its exact original bytes. It
then replaces only the anonymous `example` declaration names, preserves the
propositions and proof bodies, and compiles an audit with `#print axioms` for
every example. The localization bundle additionally retains its existing
arbitrary section parameter `M` explicitly: anonymous examples can use it only
inside proofs, while named declarations require `include M`. No premise or proof
is weakened. Missing, duplicate or unexpected observations fail closed. Only
`propext`, `Classical.choice`, and `Quot.sound` are accepted; `sorryAx`, extra
axioms, unchecked declarations, source drift, and dependency drift are refused.
Examples that the old manifest excluded are also audited when present in its
original bundle, but are never exported as admitted candidates.

The report maps each actual compiled card back to its original source hash and
audited theorem. It proves local compilation and the stated axiom restriction,
not natural-language alignment, independent review, runtime retrieval quality,
production compiler attestation, admission, or publication. The runtime profile
registration flag is an inventory observation and may change independently of
the mathematical source; it confers no approval.

Each completed bundle also receives an exclusive private evidence file, so a
later failure cannot erase earlier observations. A partial run has no successful
aggregate report and is never silently retried. Use a new output namespace for a
separately reviewed rerun.

Publishing still requires the owning typed-catalog or Recipe release path,
actual embeddings where required, independent exact-content review, and the
ordinary signed admission/evaluation gates. This corpus tool cannot call those
paths or make the 1,100 usable-record target complete by counting local files.
