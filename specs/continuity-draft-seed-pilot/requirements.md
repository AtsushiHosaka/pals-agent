---
status: approved
repositories:
  - pals-agent
parent_spec:
  path: specs/proof-flow-index
  requirements_sha256: 358225f8fce24dbaf3b8a87dd71b674a2968979a9f60e3106ec8cce8a530c4ac
  design_sha256: a4e03127d9903495ee6444d87df238025cbdabdce0b2e8d9d9a6d417413b2a4d
  tasks_sha256: 44effa741ddad7740325c7b7e9d389c23da51ecd57cf96450cd722ab87fc8de0
catalog_companion:
  path: pals-agent/specs/continuity-draft-seed-pilot/continuity-v1-catalog.json
  sha256: 29f8a35e628d5aef2b40a1bb71582e87b3e5dc001024f8f9c39e0a3906ac49a7
  state: profile_complete_v2_c14n_v4_with_local_lean_receipts_pending_signed_seed
---

# Requirements: Continuity Draft Seed Pilot

## Parent C14N v4 Release-Tooling Pin Resynchronization

- Change ID: `SPEC-CHG-2026-08-05-CDS-PARENT-C14N-V4-RELEASE-TOOLING-PIN`.
- Classification: behavior-preserving `RESTORATION` of CDS-001's exact-parent-byte requirement.
- Current: this child pins the preceding PFI-010 parent triple, before the parent restored C14N v4
  identity in the seed, image, and runtime compatibility paths and full-card fidelity in the
  detached fixture.
- Expected: the frontmatter imports the exact current approved parent triple. The catalog bytes,
  110 IDs, receipt collection, content boundary, CDS-006 evidence gate, and API-only publication
  prohibition are unchanged.
- Unchanged: this re-pin neither creates nor upgrades a Lean receipt, source-review disposition,
  signed seed, fixture result, database row, active generation, or release claim.

## One-Hundred-and-Ten-Card Original Continuity Collection

- Change ID: `SPEC-CHG-2026-08-05-CDS-CONTINUITY-ONE-HUNDRED-AND-TEN`.
- Classification: `ADDED` initial content collection implementing parent PFI-010's minimum
  admission floor.
- Authority: the user's instruction to implement, not merely specify, more than one hundred
  continuity/limit/sequence Drafts and Lean-verifiable proofs with original explanatory material.
- Current: the valid-XML source candidate has 37 general laws. It has no card-specific Lean source,
  compilation receipt collection, signed seed delta, or active database generation, and therefore
  cannot satisfy the parent floor.
- Expected: the first complete collection contains exactly 110 unique `cv1_` IDs: the retained 37
  general laws plus 73 independently authored concrete examples. The new examples cover 25
  globally continuous real functions (polynomial and everywhere-defined rational forms), 25
  pointwise-continuity instances, 12 punctured-point limits of explicit constant functions, and 11
  convergent explicit constant real sequences. Each card contains independently authored English
  and Japanese retrieval prompts, a semantic hard negative, canonical typed OpenMath, an exact Lean
  target, an explanatory proof strategy, and a Sketch. A deterministic verifier produces one
  source-hash-bound successful Lean receipt for every ID using the pinned Lean workspace; no card
  without a receipt advances to seed construction.
- Unchanged: this collection does not quote, transcribe, translate, or closely paraphrase Tao or
  any other protected source; it is not a raw-model dump. It does not relax C0 coverage, the
  original-content review gate, manifest/evidence/receipt/seed ID-set equality, API-only database
  authority, or the parent minimum of 100. It creates no direct pgvector write or public release.

## C14N v4 Companion Lifecycle-Evidence Restoration

- Change ID: `SPEC-CHG-2026-08-04-CDS-CONTINUITY-C14N-V4-LIFECYCLE-EVIDENCE`.
- Classification: behavior-preserving `RESTORATION` of CDS Task 14's lifecycle-evidence custody only.
  CDS-001--CDS-009 behavior, the v4 catalog, its parent pins, original-content boundary, Lean/
  seed/release gates, and database prohibition are unchanged.
- Authority: parent Task 24a may begin only after a clearly recorded, independently post-reviewed
  CDS Task 14 valid-XML C14N v4 companion reapproval; an unchecked task row cannot serve as that
  evidence.
- Current: this child has a 37-card valid-XML companion that passed catalog validation; Task 14
  is the sole gate for its independent approval, promotion, and post-promotion-review lifecycle.
- Expected: the exact Task 14 inverse/status/post-review identity and catalog-validation outcome
  are mandatory before any downstream PFI-008 child
  synchronization, Lean receipt, seed, fixture, or database work uses it.
- Unchanged: the evidence record creates no Lean receipt, signed seed, local pgvector load, database
  write, active generation, or publication. Failure leaves the v4 candidate source unconsumed.

## Historical Valid-XML C14N v4 Companion Restoration

This change record is historical at its own restoration revision. Its `Current` and `Expected`
labels describe the preceding raw-C14N candidate and its mechanical repair; they do not describe
the current companion. The current contract is CDS-002--CDS-009, the 37-card valid-XML v4 catalog
pin, and the separate Task 14 lifecycle gate above.

- Change ID: `SPEC-CHG-2026-08-04-CDS-CONTINUITY-C14N-V4-TRANSPORT-RESTORATION`.
- Classification: behavior-preserving `RESTORATION` of CDS-001--CDS-006's parent-required source
  identity. CDS-007--CDS-009, original-content boundaries, all Lean/attestation/seed/release
  gates, and the direct-database prohibition are unchanged.
- Authority: the approved/post-reviewed parent PFI C14N v4 transport restoration and the
  approved/post-reviewed Agent PFI-AG-009 synthetic canonicalizer.
- Current: all 37 otherwise profile-complete source fields carry the invalid historical
  `xmlns:n0=""` raw artifact and their novelty keys hash those non-XML bytes. The pinned
  `5bde5f...a37e` companion is therefore not admissible as a catalog, Lean, seed, fixture, or
  database input.
- Expected: mechanically remove only the one raw artifact from each field, validate each direct
  XML parse and exact v4 regeneration, and recompute every novelty key from its unchanged
  coverage object and valid v4 UTF-8 bytes. The resulting exact no-LF JCS companion is 37 cards,
  99,641 bytes, SHA-256 `17825e31e699fb63be07d75b2aed36cac39c8757b9286e1de660abcd5070b0bd`.
  IDs, coverage/profile, original natural-language fields, Lean targets, proof strategies, Sketches,
  theorem shapes, and card count remain byte-for-byte or semantically unchanged as applicable.
- Unchanged: regeneration makes no Tao/raw-model/completed-Lean-source claim and creates no
  authorship/source-review attestation, Lean receipt, signed seed, local pgvector load, direct
  database write, active generation, or publication. It is an admissible source candidate only
  after this child's separate convergence, status promotion, and post-promotion review.
- Compatibility, security, data, rollout, rollback, recovery, observability, cost, and
  documentation: the v3/raw source hash and every field containing the artifact reject without
  conversion. No persisted generation exists to migrate; a failed mechanical regeneration has no
  derived publication. Tests record only bounded hashes/counts and parser/identity outcomes.

## Historical C14N Companion Restoration

This change record is historical at its own canonicalization revision. Its `Current` and
`Expected` labels describe the former raw-byte companion and correction; they do not describe the
current valid-XML v4 companion or supersede the current CDS-002--CDS-009 contract.

- Change ID: `SPEC-CHG-2026-08-04-CDS-CONTINUITY-C14N-RESTORATION`.
- Classification: behavior-preserving `RESTORATION` of CDS-002--CDS-006's existing parent PFI-008
  canonical-OpenMath and novelty-key contract; CDS-001/CDS-007--CDS-009, all release gates, and
  the direct-database prohibition are unchanged.
- Authority: the parent PFI-008 canonical serialization and novelty-key requirements, plus the
  observed 37-card companion mismatch during implementation.
- Current: the former companion stored noncanonical typed OpenMath source bytes and derived every
  `novelty_key` from those raw bytes. It therefore could not satisfy the parent C14N identity
  requirement and is not a seed or database input.
- Expected: each `openmath_xml` is the exact closed typed valid-XML OpenMath C14N v4 UTF-8 string, and each
  `novelty_key` is the lowercase `sha256:` of no-LF JCS
  `{"coverage_signature":coverage,"openmath_xml_sha256":"sha256:" + SHA256(openmath_xml)}`.
  The companion is re-pinned only after all IDs, coverage, original natural-language fields, Lean
  targets, and C0 theorem shapes remain unchanged under the canonical XML representation.
- Unchanged: there is no Tao/raw-model/completed-Lean-source input, no authorship or source-review
  attestation claim, no Lean receipt, no signed seed, no direct pgvector write, and no immutable
  generation publication. C14N normalization changes neither the mathematical propositions nor
  their user-facing natural-language fields.
- Compatibility, security, data, rollout, rollback, and recovery: the prior companion hash is
  invalid for any future admission and must fail closed. The corrected no-LF JCS hash defines a new
  candidate source identity; it cannot rewrite an active generation because none exists. Rollback
  discards the candidate and retains no generated release artifact.

## Content-Family Formal Seed Expansion

- Change ID: `SPEC-CHG-2026-08-04-CDS-CONTINUITY-CONTENT-FAMILIES`.
- Classification: `MODIFIED` CDS-002--CDS-007 and CDS-009 from a fixed-card registry to the
  approved parent PFI-008 content-profile contract. CDS-001/CDS-008 ownership, all release gates,
  and the prohibition on direct database publication remain unchanged.
- Authority: the approved parent PFI-008/009 content-family amendment and the user's explicit
  direction to grow original, Lean-verified continuity variants by mathematical coverage rather
  than a target row count.
- Current: the pinned companion is a no-LF JCS v4 source candidate with 37 C0-covering cards. It has not yet
  received card-specific Lean receipts, a complete manifest/evidence/seed delta, or immutable
  generation publication, so it is neither a release artifact nor a database input.
- Expected: the current v4 catalog remains nonempty, sorted, and C0-complete and may gain any
  number of profile-valid original concrete or sequence variants within the existing 4,096-row
  resource bound. Every card has a unique `novelty_key`, exact C0/theorem-shape realization where
  applicable, Japanese/English positive and hard-negative evaluation, and, before release, one
  matching manifest/evidence/Lean-receipt/seed-delta ID. The equal derived source set is governed
  by content, not a count.
- Unchanged: no Tao-derived text, quotation, close paraphrase, raw model content, completed Lean
  source, direct pgvector write, partial seed, public/admin curation endpoint, or release claim is
  permitted. A failed card, coverage signature, review, receipt, evaluation, or release check
  blocks the entire immutable-generation candidate.
- Compatibility, security, data, rollout, rollback, and recovery: content changes create a new
  complete signed seed and immutable generation only; no active generation is rewritten or
  appended. PFI-009 may read the approved source set only as its isolated tmpfs fixture and is not
  release evidence.

## Historical Fixed-Card Expansion

The complete fixed-card change record below is historical at its own revision only. Its labels
`Current`, `Expected`, `Unchanged`, and every fixed-ID/count/mutation clause neither define nor
constrain the current child behavior. The sole current contract is
`SPEC-CHG-2026-08-04-CDS-CONTINUITY-CONTENT-FAMILIES` and CDS-002--CDS-009 as amended below.

- Change ID: `SPEC-CHG-2026-08-04-CDS-CONTINUITY-CATALOG-EXPANSION`.
- Classification: `MODIFIED` CDS-001--CDS-007 and CDS-009. CDS-008 ownership, all parent PFI-008
  release gates, and the prohibition on direct database publication remain unchanged.
- Authority: the user's request to grow the actual continuity retrieval catalog through the formal
  OpenMath, Lean-verifier, independent-review, signed-seed, and atomic-publication path rather than
  treating PFI-009's local pgvector fixture as publication.
- Current: the companion has nine unverified draft cards, four of which combine multiple closure
  laws into one retrieval result. The old exact-nine registry cannot provide the requested
  finer-grained formal seed.
- Expected: the companion is replaced before child convergence by a no-LF JCS catalog with exactly
  the 22 IDs in CDS-003. Each ID has one exact source card, manifest row, evidence-bundle record,
  Lean receipt, Japanese positive, English positive, and semantic hard negative. The 22 IDs are the
  exact child catalog, parent coverage-manifest, evidence-bundle, and signed-seed-delta set.
- Unchanged: the curriculum has exactly the existing nine objectives and uses only the approved
  `continuity-v1` grammar. No Tao text, quotation, close paraphrase, source derivative, raw model
  content, completed Lean source, direct pgvector write, public/admin curation endpoint, partial
  seed, or release claim is allowed. All 22 rows must pass the parent Lean, independent authorship,
  external source-review, signed-worker, API atomic-generation, evaluation, and rollback gates.
- Compatibility, security, data, rollout, rollback, and recovery: this supersedes an unverified
  source candidate only; it cannot alter an active catalog. A missing, duplicate, non-JCS,
  21/23-card, or unequal ID-set artifact blocks the whole candidate before embedding. Failure of
  one card, review, receipt, evaluation, or release check blocks all 22 and leaves any prior
  immutable generation unchanged.

### Historical 22-Card Detached-Input Resynchronization

This entire detached-input resynchronization record is also historical at its own revision only.
It has no current cardinality, catalog-identity, fixture-input, or rejection behavior; current
PFI-009 input is exclusively the approved profile-complete v2 catalog under CDS-009.

- Change ID: `SPEC-CHG-2026-08-04-CDS-PFI009-22-CARD-INPUT-RESYNC`.
- Classification: `MODIFIED` CDS-001 and CDS-009's current catalog-identity and detached-fixture
  cardinality wording. CDS-002--CDS-008, the parent PFI-008 release path, and every PFI-009
  isolation and non-publication boundary are unchanged.
- Authority: the user's request to construct the 22-card candidate and to measure retrieval only
  after Lean-verified formal release, while retaining PFI-009 strictly as a non-release plumbing
  fixture.
- Current: the preceding PFI-009 change record still refers to its historical nine-card candidate
  as an unchanged input. That language conflicts with CDS-003 and the current parent PFI-009
  contract, which require the exact current 22-card catalog identity before any detached load.
- Expected: after Task 10 pins the 22-card JCS companion, the parent-owned detached fixture may
  read only that exact current 22-card catalog after its parent triple and companion hash pass. A
  nine-card file, a 21/23-card mutation, or a different ID set fails before container startup. The
  fixture remains incapable of producing a Lean receipt, seed, evidence bundle, release claim, or
  database publication.
- Unchanged: the catalog remains the sole raw-card source; Tao-derived material, raw model
  outputs, completed Lean source, and user data remain prohibited. Direct database writes and
  partial publication remain prohibited. Every PFI-008 seed still requires independent authorship
  and source review, one successful Lean receipt per card, signed-worker packaging, API-owned
  complete-generation admission, recorded evaluation, and rollback evidence.
- Compatibility, security, data, rollout, rollback, and recovery: this changes no persisted data
  or API surface. It replaces only a stale pre-expansion identity reference. The detached fixture
  has tmpfs-only state and cannot modify an active or application catalog.

## Historical Parent-Owned Detached Local Validation Input

This change record is historical at its own PFI-009 import revision. Its `Current` and `Expected`
labels describe the preceding parent identity and detached-input resynchronization. The current
read-only fixture-input allowance is defined only by CDS-009 and the exact frontmatter parent and
catalog pins; it authorizes neither a fixture execution nor any database or release artifact.

- Change ID: `SPEC-CHG-2026-08-01-CDS-PFI009-LOCAL-VALIDATION-INPUT`.
- Classification: `ADDED` CDS-009 and `MODIFIED` CDS-001 parent import only. Its references to
  nine-card catalog values describe the historical pre-expansion candidate and are superseded for
  current detached input by `SPEC-CHG-2026-08-04-CDS-CONTINUITY-CONTENT-FAMILIES`. CDS-002--CDS-008,
  the PFI-008 release-evidence boundary, and Agent/API/database non-ownership are unchanged.
- Authority: the user's request for local pgvector validation, represented by the draft parent
  PFI-009 amendment and limited, after that parent is approved, to a detached, non-semantic,
  non-release fixture.
- Current: CDS-001 deliberately rejects catalog-derived work when its parent PFI triple drifts.
  The current draft PFI-009 amendment adds a detached local validation contract, but this child
  pins preceding parent bytes and does not say whether its catalog may be read by that parent-owned
  fixture. It must therefore remain unavailable as a local-fixture input until the exact parent
  import and boundary are resynchronized.
- Expected: after the PFI-001--PFI-009 parent is approved, this child imports its exact triple and
  additionally permits its existing hash-pinned catalog as the sole supported input to PFI-009's
  parent-owned `pals-scripts/continuity-pgvector-validation` fixture. That fixture load validates
  local vector plumbing; it neither creates a seed/manifest/evidence object nor changes the child
  into a database, API, embedding, retrieval, semantic-evaluation, Lean-verification, or release
  owner.
- Unchanged: the catalog remains the sole raw-card source and retains its then-current exact JCS
  identity; Tao-derived material, raw model outputs, completed Lean source, and user data remain
  prohibited. Any PFI-008 seed still requires all independent-authorship/source-review/Lean,
  complete-generation, API-admission, and evaluation gates. PFI-009 test vectors are not
  embeddings and cannot establish semantic matching or a theorem/proof claim.
- Compatibility, security, data, rollout, rollback, and recovery: this change introduces no child
  migration, schema, SQL, Docker command, credential, provider/API call, telemetry, or durable
  data. A missing/changed parent/catalog identity blocks the parent fixture before it starts; the
  fixture's PFI-009 teardown/reload rules are external and do not alter the catalog or this child.

## Overview

Define the Agent-owned, first-party `continuity-v1` curriculum source that adds independently
authored continuity material to the Proof Flow Index. It owns the exact card values, their
originality/review bindings, Lean-verification inputs, and the deterministic projection consumed by
the parent PFI-008 release gate.

The current companion is the content-profile-complete valid-XML C14N v4 source set. It is not a
seed, manifest, evidence bundle, or release input. The hash-pinned catalog contract is separate
from generated source-review attestations and Lean receipts, which remain later release evidence.
Any parent-hash or catalog-contract change requires independent review, promotion, and
post-promotion review before downstream use resumes.

When the catalog changes, its changed JCS SHA-256 and state shall be updated here before the child
enters independent convergence. No catalog byte can be treated as normative for approval unless this
frontmatter value matches it exactly.

## Goals

- Define original, Lean-verifiable Draft cards for limits, sequences, continuity, and closure laws.
- Make card content, OpenMath, Lean targets, evaluation queries, and review evidence deterministic.
- Preserve PFI-008's no-Tao-input, no-direct-database, and atomic-publication boundaries.

## Non-Goals

- Own any Draft schema, migration, SQL, active generation, API route, DTO, reranker, or retrieval
  selection behavior.
- Ingest, store, quote, OCR, embed, prompt with, or closely paraphrase Tao source material.
- Ship completed Lean proof source, raw model output, source-review work notes, or a separate
  signing/identity system.
- Add a tenth curriculum objective, expand the closed `continuity-v1` grammar, or add a reverse/biconditional
  sequential-continuity claim.

## Functional Requirements

| ID | Requirement | Priority | Source |
|---|---|---|---|
| CDS-001 | The child shall import only the exact approved parent PFI triple in frontmatter. Parent byte/status drift shall block catalog projection, test generation, or implementation. | Must | PFI-008; REP-005 |
| CDS-002 | `continuity-v1-catalog.json` shall be the sole raw-card source. Its UTF-8 no-LF RFC 8785 JCS v2 root shall contain exactly sorted `cards`, `coverage_profile`, and `schema_version`; every card shall have the parent-required raw fields, seven-field `coverage`, exact closed typed valid-XML OpenMath C14N v4 bytes, and the parent-prescribed `novelty_key` digest over that exact canonical byte string. | Must | PFI-008 Content Coverage Contract |
| CDS-003 | The final catalog shall be nonempty and coverage-profile-complete: it shall cover every parent C0 signature, use only profile signatures and theorem shapes admitted by PFI-008, keep unique UTF-8-sorted Draft IDs/OpenMath bytes/novelty keys, and may add original content-distinct concrete or sequence variants without a fixed cardinality. | Must | PFI-008 Content Coverage Contract |
| CDS-004 | Every sequential-continuity card shall use only the parent Core Theorem-Shape Library forward rule. `sequence_compose`, `sequence_lambda`, and scoped `sequence_apply` occur only in the permitted typed positions; reverse directions and `logic1:equivalent` reject. | Must | PFI-008 Core Theorem-Shape Library |
| CDS-005 | Every closure/division card shall realize the exact parent C0 operator, premise-role, operand, point/limit, result-term, binder, and nonzero-condition shape. No card-count or one-construction-only constraint exists; uniqueness is supplied by canonical OpenMath and `novelty_key`. | Must | PFI-008 Core Theorem-Shape Library |
| CDS-006 | This child shall define the parent-exact binding from each card's original statement/strategy/Sketch hashes to authorship and external source-review attestations, and from its canonical OpenMath/Lean target to a Lean receipt. The later release build, not child approval, shall require the corresponding successful attestations and receipt; a missing, duplicate, failed, or hash-mismatched generated binding shall reject the complete pilot before embedding. | Must | PFI-008 |
| CDS-007 | The catalog shall provide one original Japanese positive query, one original English positive query, and one semantic hard negative per card. Positives shall expect that card's exact Draft ID and hard negatives shall expect `no_match`; no query may be Tao material or a user query. | Must | PFI-008 |
| CDS-008 | Before this child can be approved, the parent topology inventory shall register exactly one new behavior key `pals-agent:continuity-draft-seed-pilot` and the distinct exclusive Agent curriculum-seed and Lean-verification tooling surface `agent:continuity-draft-seed-pilot`, owned by that key. It shall preserve `cross-repo:proof-flow-index`, `schema:proof-flow-index`, and `agent:proof-flow-index-retrieval` unchanged. | Must | REP-005; PFI Task 23 |
| CDS-009 | In addition to CDS-006's existing PFI-008 release projection, the child shall permit its exact CDS-002 catalog as a read-only input to approved parent PFI-009's named detached local fixture after the complete current parent triple and catalog hash pass. It shall not own, invoke, configure, or extend that fixture, Docker, pgvector, test vectors, database, API, embedding, semantic retrieval/evaluation, Lean verification, release, or evidence behavior. | Must | PFI-009; parent Task 31 |

## Acceptance Criteria

### CDS-001

- The exact parent hashes and `approved` parent status pass before every catalog-derived action.
- A changed hash, missing file, or non-approved parent status blocks before a seed, test, or Lean
  wrapper is written.

### CDS-002 / CDS-003

- The completed catalog is one no-LF JCS v2 object, hash-pinned in this requirements file, with no
  alternate card source or hand-copied field projection.
- Cards and required profile signatures are UTF-8/JCS sorted and unique. The profile contains C0;
  every card belongs to that profile and realizes its exact permitted theorem shape. The derived
  catalog ID set equals the manifest, evidence bundle, Lean-receipt collection, and signed-seed
  delta; it has no prescribed numeric size. Each positive query's expected Draft ID equals its own
  card ID and each hard-negative expected result is exactly `no_match`.
- Every card's source fields remain exact Unicode data; no normalizer silently rewrites statement,
  strategy, Sketch, query, or OpenMath bytes. The OpenMath field is admitted only when it already
  equals its exact valid-XML C14N v4 form; its `novelty_key` equals the specified JCS digest over
  that form.

### CDS-004 / CDS-005

- The C0 sequential theorem shape contains the parent-required forward implication and both
  prescribed sequence forms, and contains neither reverse implication nor biconditional.
- The profile gate rejects a missing C0 construction, role connection, nonzero condition, required
  signature, or corresponding Japanese/English/hard-negative case. Original variants are not
  rejected merely because they share a construction family; alpha-equivalent OpenMath and duplicate
  novelty are rejected.

### CDS-006

- The child fixes the one-to-one schema from each card to the exact parent coverage-manifest row,
  authorship/source-review attestation, and evidence-bundle/Lean-receipt object. It does not claim
  a generated attestation or receipt exists before the later release build.
- The source-review attestation is an external `manual_external_comparison_v1` disposition only;
  no review notes or source derivatives are accepted as release inputs.
- The Lean target is the parent profile's no-LF canonical translation and its later wrapper imports
  only `Pals.ContinuityV1.<draft_id>` during the temporary verifier build.

### CDS-007 / CDS-008

- Recorded reranker fixtures return the exact positive ID for every card's Japanese/English queries
  and `no_match` for every hard negative without a live model call.
- Approval fails without the new unique ownership key and surface, or if an existing parent/API/
  Agent retrieval ownership row changes.

### CDS-009

- The exact current approved parent PFI triple and the no-LF JCS companion hash pass before the
  catalog is read by the named parent PFI-009 fixture for detached validation. A stale parent byte,
  non-approved status, changed catalog byte/hash, or missing PFI-009 contract fails that fixture
  load before any local container or database exists.
- The fixture load is the sole supported detached local catalog-to-pgvector path; it preserves
  CDS-006's separately gated PFI-008 release projection. This child defines no operating-system
  file-access authorization for its ordinary repository JSON file. That detached fixture load
  creates no child seed, manifest, attestation, Lean receipt, embedding, API request, database
  capability, release artifact, semantic result, or modified catalog byte.

## Constraints

- Catalog source, seed, manifest, evidence bundle, logs, traces, and model inputs shall exclude
  Tao bytes, derivatives, raw prompts/outputs, completed Lean proof source, and user data.
- This child projects into PFI's existing `CurriculumSeedGate`; it does not redefine its manifest,
  receipt, signed-worker, API admission, rollback, or database contracts.
- The only permitted change to sequential-continuity scope is the forward rule in CDS-004.
- A failed card prevents the full pilot projection; parent PFI owns immutable-generation rollback.
- CDS-009 imports PFI-009's detached-fixture boundary without redefining or operating it; its
  deterministic test vector and local database have no child or PFI-008 release meaning.

## Cross-Cutting Coverage

- API/event/schema: none; parent PFI/API own these surfaces.
- Security/privacy: attestations are hash-bound release metadata; copyrighted and raw model content
  is prohibited.
- Locale/accessibility: the catalog owns Japanese/English recorded evaluation text, not a UI.
- Observability/cost: recorded fixtures are required; no live model call or new telemetry contract
  is introduced.
- Toolchain/operations: the parent PAE-017 verifier toolchain and exact wrapper/receipt protocol
  are imported without extension.
- PFI-009 local fixture: parent-owned only; this child supplies no invocation, network, database,
  provider, metric, or operating contract.

## Assumptions

- The parent PFI-008 wrapper/toolchain gate will be available when implementation starts; this child
  does not assert an unverified Mathlib lemma name.

## Open Questions

None. The current valid-XML C14N v4 companion can be approved as a source contract but cannot be released until
the subsequent Lean-verification and complete-generation sequence succeeds, without fabricating
evidence.
