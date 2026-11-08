# Stacks declaration index

A model-free, source-only index of the declarations in
[AxiomMath/Stacks](https://github.com/AxiomMath/Stacks) (Lean formalization of the Stacks Project),
with the same search API as `tools/mathlib_index` (`text_search`, `symbol_search`, `describe`).
It is an *investigation aid* for finding statements. It is **not** a source of trust: only Lean,
in an environment that contains Stacks, decides whether a statement holds or applies.

## Scope and trust

| Layer | Content | Default |
|---|---|---|
| `StacksCore` | human-reviewed, ~445 files | indexed, `trust = core` |
| `StacksFrontier` | AI-generated, **not reviewed**, ~62k files | only with `--include-frontier`, `trust = frontier` |

Every entry records its trust level. Searches default to `scope="core"`. A tag written in
`StacksFrontier` never annotates a `StacksCore` declaration, and each tag carries its own trust.
Entries of kind `upstream` come from `add_to_stacks TAG decl` lines: the tag points at a
declaration that lives in Mathlib, so the entry has a name and tag but no statement.

Stacks pins Lean v4.35.0 / Mathlib tag v4.35.0, PALS pins Lean v4.32.0-rc1 / Mathlib 8b62164.
The manifest records both Stacks versions; names found here may not exist, or may differ, in PALS's
Mathlib.

## Build

```bash
git clone --depth 1 https://github.com/AxiomMath/Stacks.git stacks
python -m tools.stacks_index.build_index --stacks stacks --out out/stacks-core
# unreviewed layer too (about 2.5 minutes, 4.5 GB RAM, 2 GB SQLite):
python -m tools.stacks_index.build_index --stacks stacks --out out/stacks-all --include-frontier
```

Outputs: `index.sqlite` (FTS5), `decls.jsonl.gz` (all rows, deterministic), `manifest.json`
(Stacks commit, Lean/Mathlib versions, counts, tagged share, skipped declarations).

## Search

```bash
python -m tools.stacks_index.search --index out/stacks-core "flat module tensor product"
python -m tools.stacks_index.search --index out/stacks-core --lean "theorem t ... : Module.Flat R M"
python -m tools.stacks_index.search --index out/stacks-core --tag 00DJ
python -m tools.stacks_index.probe --index out/stacks-core        # smoke queries, no model calls
```

## What the extractor does (and does not)

Lexical parsing of `.lean` text; nothing is built or elaborated. Declaration names are qualified by
`namespace`, but not resolved against `open`. A signature is the source text up to the first
top-level `:=` / `where` / pattern bar, plus the `variable` binders the signature depends on.
`symbol_search` uses identifiers not bound in the statement as "constants" (the Mathlib index uses
the elaborated type). Skipped and counted: `private` declarations, anonymous instances, `example`,
`alias`. EGA/SGA references are not indexed.
