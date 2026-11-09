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

## Import index: which modules does a statement need?

`StacksFrontier` has 62,528 modules. Importing all of it is not an option (about 10 GB of `.olean`,
about 15 hours to build), and even the part an image builds costs time and memory on every
verification, so a verification should `import` only what its statement names. The import index
answers "which modules?" from source alone: no model, no Lean build.

Two tables carry the answer. Both are in `import_index.sqlite`; the declaration index above
(PR #72) already had the first one for the Stacks layers (`decl.module`), so the builder can reuse
it (`--from-stacks-index`); it had no import edges and no Mathlib or Lean layer, which are the new
parts.

| table | rows (Core + Frontier + Mathlib + deps + Lean) | content |
|---|---:|---|
| `decl(name, module, kind, ...)` | about 948,000 | declaration name -> defining module. Every definition is kept: a name defined in two modules is listed twice and recorded in `conflict` |
| `edge(src, dst, public, meta, all_)` | about 509,000 | module -> direct imports, with the Lean 4.35 flags. A file that is not `prelude` gets an implicit public edge to `Init` |
| `module`, `namespace`, `conflict`, `equivalent`, `meta` | | layer and file hash per module; which modules declare under a namespace; duplicate names; identical statement text across layers; version pins |

```bash
# build (about 1 minute, 0.9 GB RAM, 232 MB SQLite; sources are checkouts at the pinned revisions)
python -m tools.stacks_index.build_import_index --stacks STACKS --include-frontier \
    --mathlib MATHLIB --dep dep=PKG/batteries:Batteries ... --lean-src TOOLCHAIN/src/lean --out OUT

# imports for a statement (prints module names and counts, never the statement)
python -m tools.stacks_index.import_index --index OUT/import_index.sqlite --source statement.lean
```

```python
index = ImportIndex("OUT/import_index.sqlite")
plan = index.plan_for_source(lean_statement)  # or index.plan(identifiers, opens, namespaces)
plan.import_lines()  # irredundant: a module an earlier one already re-exports is dropped
plan.loaded_size  # modules Lean loads (every edge): what costs time and memory
plan.closure_size  # modules whose declarations are visible (public edges only)
plan.trust_level  # "core" | "frontier" | "mathlib": the lowest layer the statement names
plan.unresolved, plan.weak, plan.ambiguous, plan.conflicts, plan.namespace_added
```

What a plan is: a **proposal**. Resolution is lexical (as in `shape.py`), so it cannot see
notation, coercions and instances (they live in modules no constant names), names generated by
attributes, or `x.foo` on a variable. `unresolved` lists what it could not place; `weak` lists tail
matches taken for dot notation. A plan that does not elaborate falls back to the full import list;
compare the elaborated statements (`#check @t` with `pp.all`, or a `defeq` check in the full
environment) before trusting a plan. `open N` needs `N` to exist, so `plan` adds a reviewed module
that declares it (never a Frontier module while a reviewed one exists).

When one name is defined in several layers, the plan takes the definition an already chosen module
makes visible, else the most trusted layer (`core`, `mathlib`, `dep`, `lean`, then `frontier`).
Names defined in two Frontier modules that do not import each other cannot be imported together;
`plan.conflicts` lists any such pair that a plan would load.

### Version pin and updates

The manifest records the Stacks commit, the Mathlib commit, every dependency commit, the Lean
toolchain, a `source_digest` (SHA-256 over the sorted `module<TAB>file-sha256` lines of every scanned
file, also per layer) and a `content_digest` over the index rows. The same sources give the same
digests, whatever the worker count.

```bash
# does this checkout still match the index? (exit code 1 if not; CI and image builds run this)
python -m tools.stacks_index.build_import_index --stacks STACKS --include-frontier --mathlib MATHLIB \
    ... --verify OUT/import_index.sqlite --out /unused
```

To move to a new Stacks revision: check out the new commit by SHA, update the pins in the
verifier workspace's `lake-manifest.json` to the same commit, rebuild (about a minute), run the
command above with `--diff OLD_OUT/import_index.sqlite --out NEW_OUT` to see added and removed
modules, changed edges and moved declarations, then rerun `validate_imports` and the tests. The
index is valid only for the commit in its manifest; never serve an index built from another
commit than the one the verifier image builds.

### Checks that need no Lean build

```bash
# every constant of a sampled declaration must resolve inside the closure of its own module
python -m tools.stacks_index.validate_imports --index OUT/import_index.sqlite --stacks STACKS
# modules per statement against `import everything`
python -m tools.stacks_index.measure_imports --index OUT/import_index.sqlite --stacks STACKS
```
