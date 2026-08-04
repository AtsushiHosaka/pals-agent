# Tasks: Proof Flow Index — Agent Runtime

`tasks.md` is non-normative. Product, generated-artifact, documentation, packaging, and
production/runtime edits are blocked until Task 16 completes. The sole earlier exception is the
Task 13a--15a synthetic-only PFI-AG-009 bootstrap, whose Task 14a/15a pair constitutes parent
Task 24c after Task 13a. The later PFI-AG-008 Task 14 creates catalog-path Red tests and Task 15
implements the catalog/receipt/seed path. Tasks 9 through 12 are historical to
the superseded parent revision.

## Current Specification Lifecycle

- [x] 9. Restore the exact final approved parent seed-conformance identity, Spec only.
  - Change ID: `SPEC-CHG-2026-07-27-PFI-AG-PARENT-SEED-CONFORMANCE-SYNC`
  - Covers: PFI-AG-001–PFI-AG-007
  - Verification: requirements first return to `draft` and import exact parent hashes
    `8a2a65f1f2141a6b75a09ba454a5d83bfcdb91226731251ee994c469c7bb0b36`,
    `44ec529797a2a727fdef9bf8e13d9fba4c0a50f3d510b002b54bae6e57d05116`, and
    `42d604dde4d0aa105dbb6e6e9928cfbe9a2df38d3c83860e02aa26f822f5545a`;
    design and tasks project only the parent restoration; no seed, validator, corpus, generated
    artifact, test, implementation, packaging, documentation, or runtime byte changes.

- [x] 10. Independently converge the exact current draft child.
  - Covers: PFI-AG-001–PFI-AG-007
  - Depends on: Task 9 and the exact approved parent authority
  - Verification: CRITICAL=0, HIGH=0, material questions=0, exact authority/ownership/traceability,
    and `IMPLEMENTATION READY`; review evidence remains external.

- [x] 11. Publish the exact status-only promotion.
  - Covers: PFI-AG-001–PFI-AG-007
  - Depends on: Task 10
  - Verification: change only requirements frontmatter `draft` to `approved`, prove its exact
    inverse, then publish only this completion marker.

- [x] 12. Run a distinct promoted-byte review.
  - Covers: PFI-AG-001–PFI-AG-007
  - Depends on: Task 11
  - Verification: a reviewer distinct from Task 10 returns `IMPLEMENTATION READY`, CRITICAL=0,
    HIGH=0, and no material question. Only its inverse-proved completion marker may then be
    published; every other edit restarts Task 10.

## Content-Family Lifecycle (current)

- [x] 13a. Converge, promote, and post-review the PFI-AG-009 C14N-only child amendment.
  - Covers: PFI-AG-009
  - Depends on: approved/post-reviewed parent PFI Task 38; no curriculum companion input.
  - Verification: the exact parent import, in-memory-only boundary, no-side-effect constraints, and
    PFI-AG-008 isolation independently reach C/H=0, status-promote, and receive a distinct
    post-promotion review.
  - Evidence: parent Task 38 is recorded complete and post-reviewed with current triple
    `d5585793b5ba66a9304c9fa2592af7306f06ee259ce3ee5f0d7f403123e23571`,
    `cbbf107e5f0900eb2c7bf997dd2a2345c2a46c986bb30c496d5df0869588a1ec`, and
    `ef1c639dc84225105b179c37f0d74eabacf2acdaeb3fcb48495a04f5177f7d10`; the
    Agent child independently converged C/H=0, status-promoted, and received a distinct
    C/H=0 post-promotion review before the Red/Green work below.

- [x] 14a. Generate PFI-AG-009 Red tests.
  - Covers: PFI-AG-009
  - Depends on: Task 13a. This task and Task 15a are the Agent-owned Red/Green substeps that
    constitute parent Task 24c; they do not wait for that parent task to be complete.
  - Verification: golden/rejection tests cover typed sorts, binders, lexical scope, valid-XML C14N
    v4, direct parser round-trip, raw-artifact rejection, and the exact novelty JCS preimage;
    planted path/catalog/card/Lean/seed/manifest/evidence/receipt/image/network/API/database/runtime
    attempts prove no side effect.
  - Evidence: from `/Users/atsushi/Desktop/projects/personal/pals/pals-agent`,
    `.venv/bin/python -m pytest tests/unit/test_openmath.py -q` failed before implementation at
    `test_pfi_ag_009_c14n_v4_returns_parseable_bytes_and_rejects_raw_artifact` because the returned
    synthetic canonical XML still contained `xmlns:n0=""`.

- [x] 15a. Implement and verify the synthetic C14N bootstrap.
  - Covers: PFI-AG-009
  - Depends on: Task 14a.
  - Verification: the Red tests turn Green without a companion read or persistent/release/runtime
    output. Parent Task 24c completion is recorded only after this Agent-owned verification.
  - Evidence: from `/Users/atsushi/Desktop/projects/personal/pals/pals-agent`,
    `.venv/bin/python -m ruff check pals_agent/openmath.py tests/unit/test_openmath.py
    tests/unit/test_proof_flow_seed_build.py tests/unit/test_private_draft_candidate_client.py`
    passed; focused `.venv/bin/python -m pytest tests/unit/test_openmath.py
    tests/unit/test_private_draft_candidate_client.py tests/unit/test_proof_flow_evidence.py -q`
    passed; and `.venv/bin/python -m pytest tests/unit/test_proof_flow_seed_build.py -k
    'v4_prefix_oracle' -q` passed. No catalog was read by the PFI-AG-009 test path and no
    persistent/release/runtime output was created.

- [x] 13. Historical PFI-008 child lifecycle placeholder; superseded by Task 16.
  - Covers: PFI-AG-008
  - Superseded because: it names the predecessor amendment before the current parent C14N v4
    release-tooling and full-card-fidelity triple. Task 16 is the sole current parent-exact
    convergence/promotion/post-review gate.
  - Unchanged: this historical marker neither authorizes nor records implementation, a receipt,
    seed, signature, image, API request, database action, or release.

- [x] 14. Historical PFI-008 Agent Red-test placeholder; superseded by Task 17.
  - Covers: PFI-AG-008
  - Superseded because: Task 17 retains the complete-evidence rejection scope and adds the current
    110-card/100-ID candidate oracle under Task 16's exact parent triple.
  - Unchanged: no test, catalog, evidence, receipt, seed, image, API, database, or release output
    is claimed by this historical marker.

- [x] 15. Historical PFI-008 content-family-builder placeholder; superseded by Task 17.
  - Covers: PFI-AG-008
  - Superseded because: Task 17 starts with the parent-exact, side-effect-free candidate gate;
    later signed-worker construction remains separately gated by complete formal evidence.
  - Unchanged: no signature, seed, image, API, database, or release is claimed by this historical
    marker.

- [x] 16. Re-pin, converge, promote, and post-review the parent-exact PFI-AG-008 candidate gate.
  - Covers: PFI-AG-001, PFI-AG-008
  - Change ID: `SPEC-CHG-2026-08-05-PFI-AG-008-RELEASE-CANDIDATE-RESTORATION`
  - Verification: requirements first return to `draft`, import the current parent
    `358225…c4ac/a4e031…2a4d/44effa…8de0` triple, and restore the missing PFI-AG-008 Must row;
    fresh convergence reports C/H=0 with no material question; promotion changes only the status;
    a separate promoted-byte review reports the same verdict. This lifecycle work creates no
    catalog, evidence, receipt, seed, signing, image, API, database, or release output.
  - Evidence: fresh post-correction convergence and a separate promoted-byte pass verified the
    exact `358225…c4ac/a4e031…2a4d/44effa…8de0` parent triple, the restored PFI-AG-008 Must/design/
    task trace, and `git diff --check`, each with Critical=0, High=0, and no material open
    question. No independent-agent slot was available for this pass, so the checks were performed
    as separate read-only reviews after the authoring update and after the status-only promotion.

- [x] 17. Add and execute PFI-AG-008 candidate-gate Red/Green tests and implementation.
  - Covers: PFI-AG-008
  - Depends on: Task 16.
  - Verification: all 110 catalog cards project to byte-identical Draft fields only when complete
    formal JCS attestations and receipts bind every ID. Local-scope receipts; count/set/schema/JCS/
    role/protocol/result/hash mutations reject before embedding, seed, image, API, or database work.
    The focused suite uses synthetic formal evidence only and does not claim review, signature, or
    publication.
  - Evidence: the Red import failed before implementation because
    `pals_agent.continuity_release_candidate` did not exist. The Green suite
    `uv run pytest tests/unit/test_continuity_release_candidate.py -q` passed 6 tests; focused
    continuity/seed regressions passed 63 tests; `uv run pytest -q` passed in full. The suite
    confirms all 110 catalog cards preserve the five Draft fields byte-for-byte under complete
    synthetic formal evidence and rejects local-only receipts plus role/result/ID/JCS mutations.

## Historical Specification Lifecycle

- [ ] 1. Independently converge the draft child bundle against the exact approved parent.
  Historical creation-cycle invocation; superseded by Tasks 9 through 12.
  - Covers: PFI-AG-001–PFI-AG-007
  - Verification: CRITICAL=0, HIGH=0, material questions=0, and `IMPLEMENTATION READY`

- [ ] 2. Promote only requirements frontmatter and run a distinct promoted-byte review.
  Historical creation-cycle invocation; superseded by Tasks 9 through 12.
  - Covers: PFI-AG-001–PFI-AG-007
  - Depends on: Task 1
  - Verification: design/tasks byte identity, exact inverse, all-zero promoted review

## Implementation

- [ ] 3. Add Spec-derived Red tests for build-time canonical seed/manifest/OCI evidence and every
  exact parent grammar/resource/fingerprint mutation.
  - Covers: PFI-AG-001–PFI-AG-002
  - Depends on: Task 12
  - Verification: expected missing build behavior fails before production edits

- [ ] 4. Add Spec-derived Red tests for the private candidate client, response compatibility,
  complete structural/numeric evidence, exact reranker request/parser/usage, final DTO precedence,
  zero database capability, pinned-price rational cost, closed release-evidence schema, and exact
  access/encryption/expiry/deletion controls.
  - Covers: PFI-AG-003–PFI-AG-007
  - Depends on: Task 12
  - Verification: every parent assertion has a stable failing oracle and no external paid call

- [ ] 5. Implement the atomic build-time seed artifact and canonicalizer child property.
  - Covers: PFI-AG-002
  - Depends on: Task 3
  - Verification: all build/golden/adversarial tests pass and invalid input publishes nothing

- [ ] 6. Implement the API-only runtime retrieval pipeline and remove production database
  capability.
  - Covers: PFI-AG-003–PFI-AG-006
  - Depends on: Tasks 4–5 and approved/Green API PFI child
  - Verification: focused boundary/evidence/reranker/error tests pass; zero-DB gates pass

- [ ] 6a. Implement and document the deterministic release-evidence path and operational
  prerequisites without making a paid call.
  - Covers: PFI-AG-007
  - Depends on: Tasks 4 and 6
  - Verification: recorded envelopes, exact usage normalization, pinned pricing, rational
    arithmetic/rounding, closed evidence schema, exact-role access, encryption, expiry, scheduled
    deletion, overdue blocking, public docs, and rollback/recovery commands are Green; raw content
    is absent

- [ ] 7. Run the sole cost-bearing release corpus evaluation and evidence lifecycle checks.
  - Covers: PFI-AG-007
  - Depends on: Task 6a, approved/Green API PFI child, parent Task 6 catalog admission, and parent
    Task 9 operational readiness
  - Verification: exact real-call count, schema admission, IDs/metrics, usage/cost/privacy/
    retention/deletion evidence pass without retry

- [ ] 8. Run full Agent gates and independent code/test/security/implementation audits.
  - Covers: PFI-AG-001–PFI-AG-007
  - Depends on: Task 7
  - Verification: unit/integration/type/lint/security/build/packaging, parent vectors, ownership,
    topology, secrets, and diff checks pass; P0=0 and P1=0

## Traceability Check

- [x] Every Must requirement has design coverage.
- [x] Every Must requirement has a verification task.
- [x] No task introduces behavior absent from requirements.
