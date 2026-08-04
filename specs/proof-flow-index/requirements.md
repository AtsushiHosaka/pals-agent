---
status: approved
repositories:
  - pals-agent
parent_spec:
  path: specs/proof-flow-index
  requirements_sha256: 358225f8fce24dbaf3b8a87dd71b674a2968979a9f60e3106ec8cce8a530c4ac
  design_sha256: a4e03127d9903495ee6444d87df238025cbdabdce0b2e8d9d9a6d417413b2a4d
  tasks_sha256: 44effa741ddad7740325c7b7e9d389c23da51ecd57cf96450cd722ab87fc8de0
---

# Requirements: Proof Flow Index — Agent Runtime

## PFI-AG-008 Parent-Exact Release-Candidate Restoration

- Change ID: `SPEC-CHG-2026-08-05-PFI-AG-008-RELEASE-CANDIDATE-RESTORATION`.
- Classification: behavior-preserving `RESTORATION` of the parent PFI-008/PFI-010 content-family
  release contract and the existing Agent-owned PFI-AG-008 execution boundary.
- Authority: the user's instruction to complete the 110-card continuity implementation through
  compiled Lean evidence and the seed-release path rather than stopping at a catalog or detached
  pgvector fixture.
- Current: the Agent child pins a superseded parent triple and has an acceptance criterion and
  design text named `PFI-AG-008`, but no corresponding functional-requirement row.  The local
  110-card receipt collection is therefore not connected to an exact, fail-closed candidate
  binding for the required authorship/source-review attestations and formal Lean receipts.
- Expected: `PFI-AG-008` is an explicit Must requirement under the current approved parent triple.
  Agent release tooling shall project the approved catalog to Draft values without rewriting any
  raw card field, then require one exact hash-bound authorship attestation, one exact
  `manual_external_comparison_v1` source-review attestation, and one exact formal Lean receipt for
  every derived ID before it returns an in-memory seed candidate. It shall reject local-only
  receipts, missing/extra/duplicate/mismatched evidence, non-JCS evidence objects, or a source-set
  below the parent 100-ID floor before embedding, seed construction, signing, image packaging, API
  request, or database action. The candidate binding itself neither creates nor represents a
  signed seed, public release, active generation, or database row.
- Unchanged: PFI-AG-001--PFI-AG-007 and PFI-AG-009; C14N v4 bytes; the exact parent manifest and
  evidence schemas; external-review and signed-worker authority; API-only atomic publication;
  zero Agent database capability; no protected-source, raw-model, or completed-Lean-source
  retention; semantic retrieval; rollback; and PFI-009's detached local-only role.
- Compatibility, security, data, migration, rollout, rollback, recovery, observability, cost, and
  documentation: no compatibility alias, evidence conversion, migration, provider call, database
  write, telemetry record, or release artifact is created. Existing local receipts remain usable
  only as local compile evidence and fail formal-candidate admission. A candidate-gate failure has
  no output and leaves any prior immutable generation untouched.

## CDS Reapproval Task-Reference Synchronization

- Change ID: `SPEC-CHG-2026-08-04-PFI-AG-CDS-REAPPROVAL-TASK-SYNC`.
- Classification: behavior-preserving `RESTORATION` of dependency evidence only. Every
  PFI-AG-009 v4 canonicalizer behavior and side-effect prohibition, PFI-AG-008 release gate, and
  all parent contracts remain unchanged.
- Current: parent/Curriculum task split distinguishes Task 13's mechanical valid-XML restoration
  from Task 14's child status-promotion/post-review, while this child still names Task 13 as the
  PFI-AG-008 reapproval predecessor.
- Expected: this child pins the exact current parent triple and names completed CDS Task 14 as the
  sole companion reapproval predecessor. It stays draft until this dependency-only synchronization
  independently converges, status-promotes, and receives a distinct post-promotion review.
- Unchanged: this update performs no catalog, Lean, seed, image, network, API, database, fixture,
  runtime, or publication operation.

## C14N v4 Bootstrap Lifecycle-Evidence Restoration

- Change ID: `SPEC-CHG-2026-08-04-PFI-AG-C14N-V4-LIFECYCLE-EVIDENCE`.
- Classification: behavior-preserving `RESTORATION` of PFI-AG-009 lifecycle evidence only.
  PFI-AG-001--PFI-AG-009 behavior, the parent triple, C14N v4 bytes, all no-side-effect
  boundaries, and every catalog/Lean/seed/database/runtime restriction are unchanged.
- Authority: the CDS Task 13 gate requires an exact, independently post-reviewed record that the
  approved PFI-AG-009 boundary completed its Red/Green implementation before a curriculum
  companion can be approved.
- Current: the approved PFI-AG-009 child and focused Green suite exist, but Tasks 13a--15a do not
  record the convergence/promotion/post-review and Red/Green evidence. CDS cannot distinguish an
  executed bootstrap from an unstarted task solely from the current Spec bytes.
- Expected: the task record names the exact parent/child post-promotion evidence, the Red
  raw-artifact failure, and the focused Green command. This child independently reconverges,
  status-promotes, and receives a distinct post-promotion review of that evidence record before
  CDS Task 13 uses it. No implementation, catalog access, Lean action, seed, image, network,
  database, fixture, API, or runtime retrieval action is added.
- Unchanged: all evidence remains synthetic/in-memory and content-free except test source literals;
  no card or release artifact is created. A missing/mismatched evidence record blocks CDS approval
  without changing the candidate catalog or any persistent state.

## Valid-XML C14N v4 Parent Synchronization

- Change ID: `SPEC-CHG-2026-08-04-PFI-AG-C14N-V4-TRANSPORT-SYNC`.
- Classification: behavior-preserving `RESTORATION` of PFI-AG-009's synthetic-only parent
  canonicalizer boundary. PFI-AG-001--PFI-AG-008, all curriculum/card content, Lean receipts,
  seeds, API/database authority, and runtime retrieval behavior are unchanged.
- Authority: the post-reviewed parent
  `SPEC-CHG-2026-08-04-PFI-C14N-VALID-XML-TRANSPORT-RESTORATION` exact triple above.
- Current: this child pins the superseded parent v3 triple and its lower-level canonicalizer returns
  the raw `xmlns:n0=""` artifact, requiring an impermissible read-time workaround. It cannot prove
  a valid-XML canonical field or v4 fingerprint identity.
- Expected: PFI-AG-009 may, after this child independently converges, status-promotes, and receives
  a distinct post-promotion review, process only supplied in-memory synthetic/golden typed XML
  through the exact parent v4 transport-canonical algorithm. It returns parseable canonical XML,
  rejects a supplied raw-artifact field, and hashes only its v4 UTF-8 bytes in the fixed two-member
  novelty JCS preimage. It has no catalog/path/card/Lean/seed/manifest/evidence/receipt/image/
  network/API/database/runtime interaction.
- Unchanged: the companion remains unopened and unapproved; no C0/card/theorem-shape projection,
  receipt, seed, local fixture, generation, database write, or publication occurs. All failures
  have no persistent side effect.
- Compatibility, security, data, rollout, rollback, recovery, observability, cost, and
  documentation: v3 raw fields/fingerprints are rejected rather than converted. No persisted
  generation exists to migrate. The only migration evidence is synthetic direct-parser round-trip,
  raw-artifact rejection, exact regeneration, and JCS novelty identity; it emits no telemetry or
  content-bearing artifact.

## C14N Bootstrap Child Synchronization

- Change ID: `SPEC-CHG-2026-08-04-PFI-AG-C14N-BOOTSTRAP`.
- Classification: `ADDED` PFI-AG-009 as the parent-authorized synthetic-only PFI-001 canonicalizer
  restoration. PFI-AG-001--PFI-AG-008 and all existing runtime, seed, receipt, and database
  behavior are unchanged.
- Authority: approved parent `SPEC-CHG-2026-08-04-PFI-C14N-IDENTITY-BOOTSTRAP-RESTORATION`.
- Current: the Agent child has no independently reviewable implementation boundary for the exact
  typed C14N v4 and novelty-JCS primitives needed to repair a draft curriculum companion; requiring
  full PFI-AG-008 admission first would recreate the parent-resolved dependency cycle.
- Expected: PFI-AG-009 owns only in-memory synthetic/golden XML canonicalization and the exact
  two-member novelty preimage. It cannot open a companion/catalog path, create a card projection,
  invoke Lean, embed, build a seed/manifest/evidence/receipt, use an image/network/database/API, or
  affect runtime retrieval. The parent Task 24c is the sole implementation gate. PFI-AG-008 remains
  blocked until the separate curriculum child completes its C14N reapproval.
- Unchanged: mathematical card contents, canonical Lean targets, source-review/authorship, Lean
  receipts, signed seed, API generation admission, PFI-009 exclusion, and all user-visible behavior.
- Compatibility, security, data, rollout, rollback, and recovery: a malformed/free/wrong-sort/non-
  canonical synthetic input rejects without output or side effect. The bootstrap creates no
  persistent artifact and cannot publish or mutate a generation.

## Current Content-Family Parent Synchronization

- Change ID: `SPEC-CHG-2026-08-04-PFI-AG-CONTENT-FAMILY-SYNC`.
- Classification: dependency-authority `RESTORATION`; no Agent behavior changes.
- Current: this child is approved against a superseded parent triple, so its validator/seed/runtime
  authority cannot admit the current parent PFI-008 content-profile contract.
- Expected: this child is draft, imports the exact approved parent triple in frontmatter, and is
  independently converged, status-promoted, and post-reviewed under parent Task 24a before
  PFI-008 code or tests use that contract.
- Unchanged: Agent zero-database capability; all PFI-001--PFI-004 behavior; private candidate
  transport; and the new PFI-008 typed catalog/Lean/seed responsibility allocated by the parent.

## PFI-008 Content-Family Execution Boundary

- Change ID: `SPEC-CHG-2026-08-04-PFI-AG-CONTENT-FAMILY-EXECUTION`.
- Current: no Agent-child requirement allocates the approved continuity-v2 catalog to an executable
  validator, Lean receipt pipeline, signed seed, and comparison evidence gate.
- Expected: PFI-AG-008 below owns that Agent-only pipeline. It consumes only the approved v2
  catalog, validates its C0/profile/AST/novelty and full derived-ID-set contract before any
  embedding, builds the exact parent Lean target in temporary no-follow modules using PAE-017,
  obtains one verified receipt per card, then emits the one complete signed seed/artifact. Agent
  has no database capability and retains no Tao material, raw model material, Lean source, or proof
  prose. Every failure occurs before seed publication.
- Unchanged: parent PFI defines schemas and API owns generation persistence/admission; this child
  defines no direct DB write, new public route, alternate signer, live provider call, or PFI-009 use
  as release evidence.

## Overview

Define the `pals-agent` implementation boundary for approved parent PFI-001 through PFI-004.
The parent bundle remains normative for every OpenMath byte, bound, formula, DTO, provider request,
privacy rule, and error precedence. This child allocates those obligations to build and runtime
components and proves that Agent has zero database capability.

## Parent Authority Restoration

- Change ID: `SPEC-CHG-2026-07-27-PFI-AG-PARENT-SEED-CONFORMANCE-SYNC`.
- Classification: behavior-preserving dependency-authority `RESTORATION`.
- Authority: the exact approved parent `specs/proof-flow-index` revision declared in frontmatter.
- Baseline parent revision: requirements
  `066ea92e458ba638d0d6f3f4b4b4c82a9c34d20373d8e1d01a70ace3b716c3a9`, design
  `778cbc387a813b060059a4bddc3d076a400b2ffda73ed35a54255c5f280df623`, and tasks
  `cf55a8424085ea97b1b7b9e4b25d08a9f8622200e72dab07a09ccfe3666abee0`.
- Reason: the approved parent restoration invalidates the child's pinned authority and every
  artifact derived from the incompatible source inventory.
- Affected IDs: PFI-AG-001, PFI-AG-002, PFI-AG-007, AC-AG-001, AC-AG-003, AC-AG-005, and
  AC-AG-006; their normative meaning is preserved.
- Current at baseline: the approved child pins the superseded parent revision from before
  `SPEC-CHG-2026-07-27-PFI-SEED-FUNCTION-SORT-CONFORMANCE`; its build, corpus, provenance, tests,
  and documentation may therefore still admit or describe the parent's nine known incompatible
  source rows and stale 40-row source inventory.
- Expected: this child returns to `draft`, imports the exact current approved parent triple, and
  completes only Tasks 9 through 12 before implementation resumes. The parent-exact builder
  validates every function-consuming position, excludes exactly the parent's nine named
  incompatible source IDs without replacement, and regenerates child-owned seed, manifest,
  fingerprint/provenance, corpus-source metadata, tests, packaging evidence, and documentation
  from the remaining 31 rows.
- Unchanged: PFI-AG-001 through PFI-AG-007; the parent four-sort grammar and six governed query
  candidate/selection outcomes; Agent/API/Draft-admin ownership; API-only candidate transport;
  strict reranker and final DTO contracts; zero database capability; privacy, release-evidence,
  rollback, and recovery behavior. The row count remains source-inventory evidence, not a new
  normative retrieval minimum.
- Compatibility and rollout: no seed, validator, corpus, generated artifact, test, runtime,
  release, or documentation edit is authorized while this child is `draft`. Existing artifacts
  are invalidated evidence until this exact draft is independently converged, status-only
  promoted, and distinctly post-reviewed.
- Assumptions: none.
- Open decisions: none.

## Goals

- Build one validated, signed-worker-bound Draft seed artifact.
- Execute canonicalization, embedding, structural evidence, and strict semantic reranking.
- Consume candidates only through the API-owned private candidate port.
- Remove direct Agent database access and every retrieval fallback.

## Non-Goals

- Own Draft persistence, migration, active generation, SQL, or database credentials.
- Expose a browser, public, user-authenticated, or proxy PFI route.
- Index proof attempts, prompts, model output, explanations, traces, or user content.
- Implement retired PFI-005 through PFI-007 graph behavior.

## Functional Requirements

| ID | Requirement | Priority | Source |
|---|---|---|---|
| PFI-AG-001 | The repository shall import only the exact approved parent PFI requirements/design/tasks triple declared in frontmatter. Drift, draft status, or a missing parent file shall fail before test, build, or runtime work. | Must | Parent Task 5a; REP-005 |
| PFI-AG-002 | Release build tooling shall apply the exact parent OpenMath grammar/canonicalization/resource contracts, validate and embed the sole-source seed, map `matched_prompt` byte-for-byte to `canonical_statement`, emit the exact no-LF seed manifest and seven-field fingerprint, and package the bounded seed plus canonicalizer child-property evidence inside the signed worker image. Invalid input shall create no partial artifact. | Must | PFI-001–PFI-004 |
| PFI-AG-003 | Runtime retrieval shall validate and alpha-canonicalize the bounded closed proposition, embed it once, and call exactly one API-owned `POST /v1/internal/proof-flow-index/candidates` request with the exact vector/fingerprint-only DTO, worker secret, 10-second hard deadline, and no redirect, retry, cache, alternate route, direct database access, or packaged-seed fallback. | Must | PFI-001, PFI-003, PFI-004 |
| PFI-AG-004 | Agent shall duplicate-aware validate the exact candidate response, active-snapshot compatibility, candidate order/count/IDs/fields, binary32/binary64 numeric rules, and runtime provenance before computing the complete parent-defined structural feature multiset and evidence values. Candidate scores are evidence only and shall not select, exclude, threshold, reorder, or truncate. | Must | PFI-003–PFI-004 |
| PFI-AG-005 | Agent shall invoke exactly one PAE `draft` role reranker using the parent-defined prompt, provider/model/API, strict schema, request bytes, headers, 90-second hard deadline, response/usage parser, and zero-retry/fallback contract. It shall return only the exact `match|no_match|error` DTO and first-applicable closed error token. | Must | Parent PFI-003–PFI-004 PAE-role import |
| PFI-AG-006 | Production Agent code, configuration, image, dependency graph, and runtime environment shall contain no PostgreSQL driver, database URL, database IAM token, SQL, catalog migration, direct Draft relation, or database network capability. | Must | API database-authority closure; PRX-004 |
| PFI-AG-007 | Release evaluation shall run only after the approved API child has published and admitted the exact signed-seed generation with at least eight eligible rows. It shall use the exact parent corpus and exactly one real strict-schema reranker call per query, record only the closed content-free usage/cost/evidence object with its access/encryption/retention/deletion contract, and block release on unavailable, incomplete, incompatible, unexpected-ID, metric, schema-admission, price, arithmetic, privacy, access, encryption, expiry, or deletion evidence. Deterministic recorded-envelope, usage, price, arithmetic, schema, and lifecycle tests shall precede the cost-bearing run. | Must | Parent Tasks 6, 9, and 10; parent release gate |
| PFI-AG-008 | Agent release tooling shall load only the exact approved `continuity-v1` catalog, preserve each card's five Draft fields byte-for-byte, and derive an in-memory continuity seed candidate only after one-to-one parent-exact authorship, external source-review, and formal Lean-receipt objects validate against every catalog card. It shall enforce the complete derived-ID-set equality and the parent 100-ID floor before embedding, seed construction, signing, image packaging, API, or database work. Local-only Lean receipts and any missing, extra, duplicate, non-JCS, wrong-schema, wrong-role, wrong-protocol, non-`original`, non-`verified`, or hash-mismatched evidence reject with no output. | Must | Parent PFI-008/PFI-010; user-authorized continuity implementation |
| PFI-AG-009 | Before the curriculum child is re-approved, Agent may validate only in-memory synthetic/golden typed OpenMath strings under the parent valid-XML C14N v4/sort/scope contract, reject the historical raw `xmlns:n0=""` artifact as supplied input, and derive exactly the parent-defined two-member novelty JCS digest from v4 bytes. It shall not discover/read a curriculum catalog or perform any card, Lean, embedding, seed, manifest, evidence, receipt, image, network, API, database, or runtime-retrieval action. | Must | Parent PFI-001/PFI-008; Task 24c |

## Acceptance Criteria

### PFI-AG-009

Every typed-sort, binder/scope, C14N v4 byte, direct-parser round-trip, raw-artifact rejection,
and two-member novelty-preimage golden/rejection test operates only on in-memory synthetic input.
Any attempted path/catalog/card/Lean/seed/manifest/evidence/receipt/image/network/API/database/
runtime access rejects before side effect.

### PFI-AG-008

Before embedding or a seed write, the Agent shall validate the exact approved `continuity-v1` v2
JCS catalog; mechanically expand C0; check every card coverage object against its closed theorem-
binder prefix and residual shape; reject free/extra/vacuous binders except the two parent
exceptions, wrong premise roles/points/limits, profile omission, duplicate OpenMath/novelty, or any
catalog/manifest/evidence/receipt/seed-delta ID-set mismatch. It shall print canonical Lean targets,
compile each in a temporary `Pals.ContinuityV1.<draft_id>` module under the fixed PAE-017 protocol,
retain only the parent receipt metadata, and admit only a complete verified source set to signed-
seed construction. It shall run the parent-required independent holdout by signature, record
`no_prior_generation` only where appropriate, and exclude PFI-009 test vectors.
For every derived ID, before seed construction it shall require exactly one hash-bound independent
authorship attestation and one admissible hash-bound external source-review disposition; missing,
duplicate, mismatched, or non-admissible records reject the entire source set. It shall retain
neither protected source material nor comparison notes.

The candidate projector accepts only no-LF JCS objects whose fields exactly match the parent
attestation and formal receipt schemas. It preserves the catalog statement, OpenMath XML, strategy,
and Sketch values byte-for-byte in the resulting `ProofDraft` values; the source-review and Lean
evidence are returned only as hash-bound metadata for the subsequent signed-worker gate. A
`pals.continuity-lean-receipts.local.v1` collection, including a successful fixed-container compile,
is explicitly not a formal receipt object and cannot cross this boundary.

### AC-AG-001 — Exact authority and build artifact

- Exact parent hashes/status pass; any byte/status mutation fails closed.
- Golden and adversarial build tests cover every parent XML/profile/resource/seed/manifest/
  fingerprint/OCI-child-property bound and prove atomic no-output failure.

### AC-AG-002 — Private candidate client

- Request capture proves one exact content type, worker header, path, DTO, deadline, and call.
- Redirect, retry, cache, fallback, public route, database access, and packaged runtime seed are
  absent.
- Every malformed/media/size/status/body/schema/order/count/fingerprint/provenance response
  mutation maps to the first parent-defined token without partial context.

### AC-AG-003 — Evidence and reranker

- The free-variable 48-weight map is exercised only as a rejected lower-level
  canonicalizer/feature oracle; the closed quantified 71-weight map is the admitted retrieval
  oracle. Both maps, binary arithmetic, exact equivalence, and candidate-order vectors match the
  parent golden cases.
- Exact request bytes/schema/prompt/provider identity and completed message/output-text/usage parser
  pass recorded-envelope mutations.
- Zero through four unique supplied IDs preserve reranker order; zero is typed `no_match`.

### AC-AG-004 — Zero database capability

- Production dependency, import, environment, image, socket/network-policy, and source scans find no
  database client, URL, token, SQL, or direct catalog operation.
- Attempts to configure database access are rejected before runtime retrieval.

### AC-AG-005 — Release evidence

- Every corpus query performs exactly one admitted real reranker call with exact selected-ID and
  metric oracles.
- Usage normalization, pinned pricing, rational micro-USD rounding, content-free evidence, access,
  180-day expiry, and scheduled deletion pass; any missing or overdue evidence blocks release.

### AC-AG-006 — Cross-cutting closure

- Natural statements are opaque exact Unicode through validation/request construction; PFI adds no
  user-facing UI, translation, locale selector, or accessibility surface.
- Runtime and release observability is limited to the parent-defined closed error DTO, content-free
  counters/classes, governed evaluation evidence, and closed release-evidence schema. No query,
  Draft content, prompt, provider envelope, database value, user content, trace, or identifier
  outside the parent-governed corpus/Draft-ID fields is emitted.
- Deterministic PR, main integration, signed-image, manual-release, rollback, and recovery commands
  and prerequisites are executable in the order defined by design and tasks.

## Constraints

- The parent PFI bundle owns behavior and all exact literals; this child cannot extend or relax it.
- `pals-api` exclusively owns catalog persistence, migration, SQL, active snapshot, and the private
  candidate route.
- The worker secret is imported from the existing PEX-008 authority; no second secret is created.
- No implementation begins or resumes before the current Tasks 9 through 12 lifecycle is complete
  and this child is approved and distinctly post-reviewed.
- Runtime candidate work requires an approved/Green API PFI child. Cost-bearing release evaluation
  additionally requires the parent Task 6 catalog publication/admission and Task 9 operational
  readiness; neither condition may be simulated or bypassed.

## Cross-Cutting Coverage

- API/event/schema: Agent owns no API route, event, database schema, migration, or ACL. It consumes
  only the exact private candidate DTO and emits only the exact internal PFI result.
- Authentication/secrets/privacy: only the imported worker secret and provider credential enter
  their exact HTTP adapters; neither enters DTOs, evidence, files, logs, traces, metrics, or errors.
- Internationalization/accessibility: natural statements remain exact Unicode opaque data. There is
  no Agent UI, so visual/keyboard accessibility is not applicable.
- Observability/cost: runtime emits only closed content-free counters/error classes. Cost exists
  only in the manual release evidence path under the exact parent pricing/access/lifecycle contract.
- Compatibility/migration/rollout/rollback/recovery: API owns database migration and rollback.
  Agent seed publication is atomic; runtime and release fail closed on incompatible provenance.
  Rollback selects one mutually compatible signed worker/seed/fingerprint/canonicalizer set and
  never restores direct DB or a fallback catalog.
- Documentation/toolchain: public docs shall remove every direct-DB instruction and describe the
  API-only boundary, exact release prerequisites, evidence lifecycle, and recovery commands.

## Assumptions

- The approved parent PFI bundle is the authority for the exact PAE `draft`-role invocation; this
  child does not import or depend on a separate draft PAE bundle. Approved PRX remains the
  signed-worker admission authority identified by the parent.

## Open Questions

None.
