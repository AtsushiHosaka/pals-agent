# Design: Proof Flow Index — Agent Runtime

## Parent Seed-Conformance Restoration

`SPEC-CHG-2026-07-27-PFI-AG-PARENT-SEED-CONFORMANCE-SYNC` rebinds this child to the exact approved
parent revision declared in requirements frontmatter. `OpenMathCanonicalizer` validates the
declared sort of every function-consuming position, including nested applications.
`ProofDraftSeedBuilder` rejects the parent's nine known incompatible source rows and atomically
builds only the unchanged 31-row remainder; it never synthesizes replacement theorems or OpenMath.
The seed, no-LF manifest, fingerprint/build provenance, OCI child-property evidence, and
corpus-source metadata are regenerated together from those exact source bytes. The six governed
queries and their candidate/selection outcomes remain byte-for-byte unchanged.

This is an authority and evidence restoration only. It adds no Agent route, database capability,
fallback, reranker behavior, result token, release threshold, or runtime behavior. Existing
40-row-derived build, corpus, packaging, test, and documentation evidence is stale and cannot be
used for promotion or release.

## Overview

## PFI-AG-009 Synthetic C14N Bootstrap

`ContinuityOpenMathCanonicalizer` is a pure in-memory boundary. It accepts a supplied typed XML
string and, after exact parent profile/sort/scope validation, returns only the valid-XML C14N v4
transport-canonical string. It treats raw C14N as internal, removes its one prescribed empty-prefix
artifact before returning, reparses the returned value directly, and requires exact regeneration.
Supplied `xmlns:n0=""` transport bytes reject; no caller may repair them. Its novelty helper
accepts only that v4 string and a supplied seven-field coverage object to emit the parent fixed
two-member JCS digest. It has no `Path`, catalog, card, Lean, embedding, seed, manifest, evidence,
receipt, image, network, API, database, or runtime dependency. Tests inject strings and mappings
only. `ContinuityCatalogGate` is separate, remains PFI-AG-008 work, and cannot be called by this
bootstrap. The Agent's Task 14a/15a Red/Green pair is the implementation evidence for parent
Task 24c, not a dependency on its later completion.

## PFI-008 Content-Family Release Builder

`ContinuityCatalogGate` reads only the approved child v2 JCS bytes and parent hash pins. It expands
C0 to canonical signature JCS, validates profile/card/source-set equality and theorem-shape ASTs,
and emits no card projection on a single error. `ContinuityLeanReceiptRunner` converts each admitted
target to the parent canonical Lean form, creates an isolated no-follow temporary
`Pals.ContinuityV1.<draft_id>` module and wrapper, invokes the PAE-017 fixed setup-file protocol,
and returns only receipt metadata. `ContinuitySeedBuilder` requires a verified receipt, approved
authorship/source-review disposition, and JP/EN/negative evaluation for every card, joins the pilot
delta with the immutable base projection, and emits one signed artifact. `HoldoutComparator` runs
only recorded independent holdout evidence, reports per-signature/aggregate metrics or
`no_prior_generation`, and never uses PFI-009 vectors. No component has database credentials or
writes a catalog generation.

`ContinuityReleaseCandidateProjector` is the first persistent-input stage after catalog admission.
It decodes each supplied authorship attestation, source-review attestation, and formal Lean receipt
as an independently no-LF JCS object, rejects an object whose exact field set or hash-bound card
values differ from the parent schema, and requires exactly one of each for every UTF-8-sorted
catalog ID. It projects the five Draft fields directly from the catalog, without generated prose,
normalization, or a fallback field. Its sole output is an in-memory candidate containing the Draft
tuple and evidence digests; it has no embedding, signer, image, API, database, provider, logging,
or filesystem-output dependency. In particular, the local receipt collection has schema
`pals.continuity-lean-receipts.local.v1`, so it is rejected rather than relabelled as a formal
receipt. `ContinuitySeedBuilder` remains the later component that consumes an admitted candidate
together with the existing signed-worker, base-projection, and evaluation gates.

Split PFI Agent work into a release-only seed producer and a runtime retrieval pipeline. Runtime
depends on a narrow API client and contains no persistence adapter.

## Requirements Traceability

| Requirement | Design Coverage |
|---|---|
| PFI-AG-001 | exact-parent authority gate |
| PFI-AG-002 | `ProofDraftSeedBuilder` and signed-worker artifact projector |
| PFI-AG-003 | `DraftCandidateClient` and bounded runtime orchestration |
| PFI-AG-004 | candidate validator, structural projector, numeric guard |
| PFI-AG-005 | strict `DraftRelevanceReranker` and result/error reducer |
| PFI-AG-006 | dependency/config/image/network zero-DB gate |
| PFI-AG-007 | release corpus runner and content-free evidence writer |
| PFI-AG-008 | `ContinuityCatalogGate`, `ContinuityReleaseCandidateProjector`, receipt runner, complete seed builder, holdout comparator |
| PFI-AG-009 | pure `ContinuityOpenMathCanonicalizer` and novelty preimage helper |

## Components

- `OpenMathCanonicalizer`: parent-exact parse/profile/semantic/canonical byte boundary.
- `ProofDraftSeedBuilder`: build-time-only validated seed, fingerprint, manifest, and child
  property producer. It writes atomically after the whole artifact validates.
- `DraftEmbeddingProvider`: one fingerprint-bound embedding operation under the exact parent
  numeric and identity contract; this child adds no transport shape or provider fallback.
- `DraftCandidateClient`: worker-authenticated API port with one request and a 10-second deadline.
- `DraftCandidateResultValidator`: closed response and active-compatibility validator.
- `DraftStructuralEvidenceProjector`: complete deterministic parent feature map and arithmetic.
- `DraftRelevanceReranker`: exact PAE role request/response/usage boundary.
- `ProofFlowIndexRetriever`: ordered orchestration and closed final DTO/error reducer.
- `ProofFlowIndexReleaseEvaluator`: cost-bearing corpus runner and content-free evidence lifecycle.
- `ContinuityReleaseCandidateProjector`: exact JCS evidence/card binding with no side effects and
  no authority to sign, embed, package, or publish.

`PostgresDraftCatalog`, SQL helpers, database settings, and database drivers are excluded from the
production runtime graph. Active-generation compatibility is consumed only through the exact API
candidate result; migration and publication remain entirely API-owned.

## Runtime Flow

1. Enforce natural/XML aggregate bounds and the exact error precedence.
2. Parse, validate, and alpha-canonicalize one closed OpenMath proposition.
3. Verify canonicalizer and embedding fingerprints; embed once.
4. Send one vector/fingerprint-only private API request.
5. Validate the complete response before accepting any candidate.
6. Compute vector/structural/exact-equivalence evidence without selection. The 48-weight free-
   variable case remains a rejected lower-level test oracle; only the closed 71-weight quantified
   case is an admitted retrieval oracle.
7. Build exact request-subject JCS and invoke the strict reranker once.
8. Validate zero-through-four unique supplied IDs and usage.
9. Emit exact `match`, `no_match`, or content-free first-error DTO.

Every step is fail-closed. No later step runs after an earlier error and no alternate provider,
catalog, seed, cache, lexical match, exact-text match, or score cutoff participates.

## Build Flow

Build tooling reads only the pinned source seed, validates all rows and aggregate bounds, computes
canonical OpenMath and embeddings, maps the six fields, sorts by Draft ID byte order, and computes
the no-LF JCS manifest. It emits the parent-defined seed artifact and canonicalizer child property
into a private temporary tree, verifies final bytes, then atomically publishes them to the image
build context. The signed worker image is the sole runtime provenance carrier.

## Interfaces

- Candidate request/response: byte-for-byte parent private-port contracts.
- Reranker: byte-for-byte parent Responses API contract.
- Final result: byte-for-byte parent `pals.draft-retrieval.v1` contract.
- Release evidence: parent content-free usage/cost/access/retention/deletion schema only.

## Security and Privacy

- Worker secret is used only by the client and never enters DTOs, errors, or telemetry.
- No raw provider envelope, query, Draft content, database value, prompt, or trace is logged.
- Production packaging scans imports, distributions, configuration names, image files, and network
  policy for database capability.
- Corpus evidence is encrypted, role-restricted, expiring, and content-free.

## State, Failure, and Recovery

- Every local/provider/API failure maps through the exact parent first-applicable error precedence;
  no child-specific error token, free-form message, partial context, retry, or fallback is added.
- A build failure leaves no seed, manifest, fingerprint, or OCI child property at the publication
  path. Runtime incompatibility stops before later calls. Release evidence failure blocks release
  without rewriting the corpus or retaining raw envelopes.
- Rollback selects one previously admitted signed worker whose seed, canonicalizer provenance,
  fingerprint, API generation, and database provenance remain mutually compatible. Agent never
  repairs or rolls back the database.

## Testing Strategy

- Parent golden/adversarial XML, feature, numeric, DTO, and corpus vectors.
- Request/response capture and mutation tests at both external boundaries.
- Source/dependency/image/environment/network zero-DB tests.
- Deterministic unit/property tests plus one release-only real reranker evaluation.
- Full unit/type/lint/security/build and independent code/test/implementation audits.

## Toolchain and Delivery

- PR deterministic gate: `.venv/bin/python -m pytest`, `.venv/bin/python -m ruff check .`, and
  `.venv/bin/python -m mypy pals_agent tests`, plus exact-parent, zero-DB source/dependency, request,
  recorded-provider, usage/price/cost/evidence, and packaging scans.
- Main adds signed-worker build/OCI extraction compatibility against the approved API child and the
  API-only private-client integration; the worker image command is
  `docker build -t pals-agent-worker .` and this tier performs no real reranker call.
- Manual release runs only after parent Task 6 catalog admission and Task 9 operational readiness,
  observes at least eight eligible rows, then performs exactly one real reranker call per governed
  corpus query and validates the complete external evidence lifecycle.
- Public package/image scans reject `psycopg`, PostgreSQL DSNs/tokens/settings, SQL/catalog helpers,
  and direct database network capability. Documentation and parent helper commands must be updated
  with the same removal before release.

## Risks

- Legacy `PostgresDraftCatalog` may remain reachable through a factory: remove it from production
  exports and prove the built wheel/image dependency graph.
- Provider SDK defaults may add request fields: serialize and send the exact body at the HTTP
  boundary and compare captured bytes.
- A release run can start against an unpopulated or incompatible API generation: enforce the parent
  Task 6/9 admission prerequisites and observed eight-row minimum before the first paid call.
