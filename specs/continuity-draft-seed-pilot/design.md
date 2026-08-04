# Design: Continuity Draft Seed Pilot

## Parent C14N v4 Release-Tooling Pin

CDS-001 reads only the exact parent requirements/design/tasks triple named in this child's
frontmatter. The C14N v4 release-tooling and full-card fixture restorations change that triple but
not the child catalog or projection. Any future parent-byte drift rejects before the catalog is
consumed; this child does not implement parent seed, image, runtime, or fixture behavior.

## One-Hundred-and-Ten-Card Collection and Receipt Flow

The first collection is a fixed authored realization of the parent minimum, not a replacement for
the content-profile validator: 37 retained general laws plus 73 concrete cards, divided into 25
global-continuity, 25 point-continuity, 12 explicit constant-limit, and 11 explicit constant-
sequence propositions. The catalog generator receives only a closed in-repository table of formula,
statement, bilingual prompts, coverage signature, Lean target, and proof body. It independently
constructs each OpenMath tree, applies the existing valid-XML v4 canonicalizer, derives the novelty
key from the canonical bytes, sorts all IDs bytewise, and writes one no-LF JCS file.

The receipt builder reads that generated catalog, renders an isolated temporary Lean wrapper for
each card, and invokes the workspace-pinned direct Lean command after setup. A receipt binds the
ID, canonical OpenMath digest, Lean target digest, exact proof source digest, toolchain identity,
command outcome, and compiler output digest. The builder fails the complete batch on its first
missing, duplicate, mismatched, or unsuccessful receipt; it never treats a local host Lean version
as a release receipt. The receipt collection is an input to the existing evidence and signed-seed
gates and remains distinct from retrieval rows or database publication.

## Parent-Owned Detached Local Validation Input

CDS-009 adds no child runtime path. In addition to the unchanged CDS-006 PFI-008 release
projection, after CDS-001 verifies the current approved parent triple and CDS-002 verifies the
exact companion bytes, the catalog may be opened read-only by the one parent-owned PFI-009 runner
at `pals-scripts/continuity-pgvector-validation`. The child contributes only the already-defined
raw card fields and catalog digest; it neither imports nor configures Docker/pgvector, creates a
card projection file, computes a vector, opens a database connection, or receives local-fixture
output. The parent runner independently applies every PFI-009 image, network, tmpfs, DDL, vector,
nearest-neighbour, output, and teardown restriction.

The catalog identity gate is deliberately shared but one-way: the parent fixture must reject stale
child/parent status or hash before Docker startup, while the child neither needs nor receives a
fixture success result. Therefore detached local validation cannot mutate this companion or be
mistaken for a PFI-008 seed/manifest/evidence projection, a Lean receipt, semantic retrieval, or
release admission; it also does not remove or supersede the CDS-006 release projection.

## Overview

The child has one normative companion, `continuity-v1-catalog.json`. It becomes the only raw source
for the nonempty content-profile-complete source set after its exact JCS SHA-256 is pinned in `requirements.md`. The
parent PFI-008 translator, `CurriculumSeedGate`, evidence-bundle schema, signed-worker binding,
catalog admission, and rollback remain external contracts.

Before any profile or theorem-shape projection, the companion admission gate validates each closed
typed OpenMath field with the parent valid-XML C14N v4 serializer and compares the resulting bytes
directly to the stored field. It rejects a stored raw `xmlns:n0=""` artifact before parsing or
projection. It independently recomputes the parent `novelty_key` JCS preimage from the seven-field
coverage object and those exact v4 canonical bytes. This is an admission check, not a normalization
path: a noncanonical XML string or stale novelty key emits no card projection. The gate retains
neither pre-normalized XML nor any protected-source material.

## Requirements Traceability

| Requirement | Design coverage |
|---|---|
| CDS-001 | exact parent identity gate before catalog consumption |
| CDS-002 | no-LF JCS companion and one field-to-hash projection |
| CDS-003 | parent C0/profile-complete, no-fixed-count coverage validator |
| CDS-004 | forward-only sequential card validator |
| CDS-005 | constructor/nonzero matrix validator |
| CDS-006 | attestation and Lean receipt binding adapter |
| CDS-007 | recorded bilingual evaluation fixture projection |
| CDS-008 | REP-005 ownership registration pre-approval gate |
| CDS-009 | read-only catalog identity gate for the parent-owned PFI-009 fixture; no child fixture/runtime ownership |

## Artifact Flow

```text
PFI-008 release path:

catalog JCS v2
  -> parent hash + profile/card/source-set byte validation
  -> C0 theorem-shape + forward-sequential + role/nonzero validation
  -> authorship/source-review hash binding
  -> parent OpenMath-to-Lean target and temporary wrapper
  -> Lean receipt binding
  -> PFI coverage-manifest/evidence-bundle projection
  -> existing PFI CurriculumSeedGate
```

```text
PFI-009 detached validation side path:

catalog JCS + current approved parent triple
  -> read-only parent-owned fixture input
  -> no child projection, no fixture result, no PFI-008 release artifact
```

The catalog parser preserves every field value exactly after decoding JCS. It verifies the parent
identity before interpreting a card and rejects missing, duplicate, unordered, noncanonical, or
uncovered entries. It does not synthesize a statement, OpenMath tree, proof strategy, Sketch,
query, source-review object, or Lean theorem.

## Validation and Failure Handling

- The sequential validator requires one implication from the continuity/convergence hypotheses to
  both convergence conclusions, one `sequence_compose`, one `sequence_lambda`, and its scoped
  `sequence_apply`; reverse directions and `logic1:equivalent` reject.
- The profile validator expands parent C0, requires every signature, and compares every generic
  card against the exact parent theorem-binder prefix and residual shape. It requires the
  parent-specified role connection and nonzero premise for every quotient clause; valid original
  concrete/sequence variants are admitted without a construction-count quota.
- Before projection, the catalog, coverage manifest, evidence bundle, Lean receipts, and signed-seed
  delta must have the same nonempty unique derived ID set. A profile omission, duplicate novelty or
  OpenMath byte string, or any source-set mismatch produces no projection.
- The later evidence adapter recomputes each parent-prescribed hash from the exact catalog field
  bytes; it accepts only a matching external review disposition and a `verified` Lean receipt.
  This child specifies that release input/output boundary and does not claim the generated evidence
  exists before the downstream red/green implementation sequence.
- Any failure produces no PFI projection. It does not write a catalog row, make a database call,
  invoke a live model, or alter parent rollback behavior.

## Security and Public Boundary

The companion, temporary build area, and generated projection are scanned for prohibited material
before embedding. Completed Lean proof modules are temporary no-follow verifier inputs only and do
not become catalog, image, manifest, evidence, API, log, trace, or public Agent artifacts.

## Testing Strategy

Implementation derives deterministic fixtures from the complete catalog: hash/JCS mutations,
parent-drift failure, exact C0/profile expansion and profile omission, all nine objectives, each
construction, each quotient nonzero premise,
forward-only sequential mutations, bilingual expected IDs, hard negatives, attestation/receipt
mutations, and a no-projection failure assertion. CDS-009 additionally verifies that the parent
fixture's supported input is read-only and rejects stale status/hash without a child
database/API/model/fixture side effect. This child defines no OS-level file-reader identity;
parent PFI owns PostgreSQL integration, the local PFI-009 fixture, and the six pre-PFI-008
query-regression oracle.

## Risks

- Some closure targets may require Mathlib theorem composition not yet confirmed in the pinned
  verifier toolchain. Their cards cannot be released without actual receipt success.
- A source review can establish only a review disposition. It never authorizes retaining source
  text or derivative comparison notes.
