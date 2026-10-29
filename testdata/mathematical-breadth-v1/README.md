# Mathematical breadth corpus v1

MRD-011 offline evaluation input, authored under Apache-2.0. This is not a runtime
catalog or an independently signed admission/evaluation receipt. Problem wording
and proofs are original synthetic examples; mathematical dependencies are pinned
Mathlib sources, also Apache-2.0. Each case records exact upstream source URLs,
assumptions, a multi-step outline, and a hard-negative counterexample. No external
exam text or dataset was copied.

Seven positive Lean witnesses cover selected projection, real-analysis,
ideal-theory, topology, complex arithmetic, Liouville, and commutative-square
arguments. Two further declarations prove concrete counterexamples. None of
these samples proves whole-family coverage. The three entrance problems and the
geometry obligation intentionally have no Lean source and remain
`authored_not_compiled`. They cannot produce a successful complete report.

From the agent repository, reuse an existing workspace with the exact pinned
Lean/Mathlib dependencies:

```sh
python -m pals_agent.breadth_evaluation \
  --corpus testdata/mathematical-breadth-v1/corpus.json \
  --lean-project "$PALS_LEAN_PROJECT" \
  --output /tmp/pals-breadth-evaluation.json
```

The CLI uses the existing bounded `LeanVerifier.verify`, checks dependency pins,
and binds exact corpus/source bytes to its report. Exit 0 means all declared
sources compiled; exit 1 means at least one pending or failed case; exit 2 means
invalid inputs/environment. The complete v1 corpus should return 1 because its
pending cases are explicit. A reported compilation is not a semantic alignment,
axiom audit, reviewed theorem, admitted Draft/Recipe, retrieval result, API proof
job, browser check, or deployment. Local execution on macOS also does not prove
the Linux production sandbox. Ignored prebuilt dependency artifacts are reused;
this runner is not an artifact-origin auditor or cache admission engine.

For a separate trusted-source axiom inspection, concatenate each distinct Lean
file once after a single `import Mathlib`, append `#print axioms NAME` for every
source-backed theorem, and run `lake env lean` in the same workspace. Do not feed
those interactive directives to the production verifier. The initial inspection
found only `propext`, `Classical.choice`, and `Quot.sound`; the pasted square has
no axioms. No unchecked solver rule or placeholder is used.

```sh
python testdata/mathematical-breadth-v1/check_entrance_finite.py
```

This performs exact finite ballot enumeration (n=1..7) and a bounded integer
solution/descent check (coordinates <=1000). These are supplementary checks,
not Lean proofs or completeness proofs. Full symbolic outlines and assumptions
are in `corpus.json`. Cubic parameter boundaries are stated symbolically; no
floating-point root sampling is counted as evidence.

`ug.category.square_pasting` still requires T3 inline rendering, TikZ source,
reload and matching arrow/proof identities. `pending.geometry.isosceles_midpoint`
requires T2 input fidelity, nondegeneracy, checked trace/axioms and T3 actual
rendering. T6 supplies acceptance obligations, not those engines.
