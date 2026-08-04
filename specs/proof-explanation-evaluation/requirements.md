---
status: approved
repositories:
  - pals-agent
---

# Requirements: Proof Explanation and DSP Evaluation

## Exact x² Retrieval Must Require Its ε–δ Method

- Change ID: `SPEC-CHG-2026-07-31-PAE-EXACT-X2-EPSILON-DELTA`.
- Authority: explicit user decision to submit only `x² が連続であることを説明してください。` and
  require the real retrieval path, rather than that phrase containing a method name, to select the
  ε–δ proof.
- Current: the ε–δ preflight runs only when the learner literally requests ε–δ. A real exact
  retrieval of `continuous_square` can therefore accept `continuous_id.pow` despite that Draft's
  required method.
- Expected: an exact OpenMath-equivalent retrieval of Draft `continuous_square` is a product
  method source for that one matched theorem and requires the same executable ε–δ markers and
  shortcut rejection as an explicit learner ε–δ request. Approximate, reranked, or nonmatching
  Draft contexts remain advisory and never impose a proof method.
- Unchanged: the learner's visible prompt need not name ε–δ; user-supplied formal identity remains
  authoritative; retrieved Drafts never replace the theorem target or a formal harness; evaluation
  benchmarks, hidden harnesses, rubrics, and arbitrary retrieved prose never become runtime
  method oracles; the normal repair loop remains the only recovery path.

## Current Parent PRX T-052 Import Synchronization

- Change ID: `SPEC-CHG-2026-07-31-PAE-PRX-T052-CHILD-SYNC`.
- Authority: approved parent `specs/proof-runtime-cross-repository` Task T-052.
- Classification: behavior-preserving dependency-identity `RESTORATION`.
- Current: the active PAE-033/Task-84 import still pins the preceding approved parent bundle.
- Expected: active PAE imports the current approved parent requirements/design/tasks identity
  `c8f585e26d664f5e6cf3b1d56cb917f17bbac7a5192cddc421ee0b6b8b40b3e2` /
  `5b90d8afbcb2f5446d84150e22d18d2c8b1dc8748ba44192dece41c8dbdd5a51` /
  `4e01c8a80e1f7921e2f488a887bfcf09004c0b82601a6c2168c6585d26e63a82`.
  Historical parent identities remain historical. This synchronization restarts the child’s
  applicable independent review path before it can contribute to parent T-011.
- Unchanged: PAE-001 through PAE-038, acceptance criteria, status, runtime/code/test behavior,
  ownership, rollout, rollback, recovery, security/privacy, and external systems.

## PAE Task-84 Current-Authority Restoration

- Change ID: `SPEC-CHG-2026-07-27-PAE-T84-CURRENT-AUTHORITY-RESTORATION`.
- Classification: behavior-preserving dependency-order and external-identity `RESTORATION`.
- Current: some superseded PAE-033 and readiness prose still treats the Task-82/83 DEO triple or
  the abbreviated `82 -> 83 -> 73 -> 64` sequence as current. That permits Task 73 to appear to
  consume DEO authority before Task 84 records the report-covered identity.
- Expected: for every active PAE authority, readiness, acceptance, and traceability statement, the
  sole sequence is `Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 ->
  Task 64 -> PRX T011`. Task 84 consumes an external fresh DEO Task-48 report and records its exact
  then-current DEO requirements/design/tasks triple plus current approved PRX triple before Task 73.
  No current clause may pre-pin, infer, or accept the historical DEO triple
  `e1d0aba03da548336a5b59dab329c6a0f3bd14c9ad101a866e316070b8487f60` /
  `58f2cc33142016d736748ed103aabf10892f060ecf1cf5e16e15e00b2c4b017c` /
  `1ef03cbcb186c0709415363e6a0e11c572deff18d85f89fc8023f8afe53324e2`; those values and every
  abbreviated Task-84-omitting path are historical only. This amendment controls PAE-033 and every
  implementation/readiness gate it traces. Each Task-73 draft review and Task-64 promoted-byte
  review report must be external and bind its reviewer identity, the complete author/remediator
  identity set for every current candidate byte (including Task 84), true reviewer/set
  nonmembership, and the reviewed requirements/design/tasks triple. An absent, incomplete,
  ambiguous, non-disjoint, or mismatched report fails the respective review.
- Unchanged: PAE-001 through PAE-038, acceptance criteria, runtime/code/test behavior, status
  `draft`, DEO Task-48 report externality, Task-84's no-future-identity rule, PFI/EXP/PJR/PWA/API
  PEX/PRX ownership, rollout, rollback, recovery, security/privacy, and external systems.

## Current DEO Task-48 Report Rebaseline

- Change ID: `SPEC-CHG-2026-07-27-PAE-DEO-T48-REPORT-REBASELINE`.
- Classification: behavior-preserving dependency-identity and specification-governance
  `RESTORATION`.
- Current: historical Task 82/83 values pin DEO and PRX identities that predate the current DEO
  Task-48 convergence and current PRX tasks bytes. They cannot authorize Task 73 or Task 64.
- Expected: PAE remains `draft`. After DEO Task 48 supplies its external fresh report for the exact
  then-current DEO requirements/design/tasks bytes, Task 84 records that triple and the current
  approved PRX tasks identity in this bundle before Task 73 runs. Task 84 changes no runtime
  behavior and has no authority until the exact Task-48 report exists. The sole current path is
  `Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64`.
- Current Task-84 record: the consumed external DEO Task-48 report covers DEO requirements
  `9cb00ba39a34cc0fb035507dd4499c94a9c7b229f6abb4bda9795ffa01397efc`, design
  `ee7e8d754668e9fb7639e6f691840f0bfb79c793f63909912f944ce3954120cf`, and tasks
  `759014da8d79a13bd1bb5f1b92096506837049f751d3ac49672448549a67d0c4`. Its paired current
  approved PRX requirements/design/tasks identity is
  `c8f585e26d664f5e6cf3b1d56cb917f17bbac7a5192cddc421ee0b6b8b40b3e2` /
  `5b90d8afbcb2f5446d84150e22d18d2c8b1dc8748ba44192dece41c8dbdd5a51` /
  `4e01c8a80e1f7921e2f488a887bfcf09004c0b82601a6c2168c6585d26e63a82`.
  These are the sole Task-84 input identities; no report ledger or verdict is persisted.
- Unchanged: PAE-001 through PAE-038, every acceptance criterion, PFI/EXP/PJR/PWA/API PEX/DEO
  behavior and ownership, implementation, tests, code, migration, runtime, rollout, rollback,
  recovery, security/privacy, and external systems.

## Overview

Generate learner-facing explanations only from a successfully verified Lean proof, answer
section-specific follow-up questions from that same proof, and measure every DSP pipeline stage
with versioned, durable evaluation runs. Missing evidence must remain visibly unevaluated; it must
never be replaced by fallback content or a fabricated passing score.

## Historical Spec Update: 2026-07-27 Current DEO Final-Identity Reopen (superseded by Task 84)

- Change ID: `SPEC-CHG-2026-07-27-PAE-DEO-FINAL-IDENTITY-REOPEN`.
- Classification: behavior-preserving specification-authority `RESTORATION`.
- Historical current: PAE was `status: approved` on path
  `Task 74 -> Task 80 -> Task 81 -> Task 73 -> Task 64`, with Tasks 73/64 checked. Their active
  import pins the DEO identity preceding DEO-R48-001, so those completion markers cannot authorize
  the current DEO bytes or PRX T011.
- Historical expected: Task 82 records this requirements-first demotion to `draft` and reopens Tasks 73/64.
  The then-current authority path was
  `Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64`. Task 73 remained blocked until
  the external fresh current-byte DEO Task-48 report existed for exact then-current DEO requirements
  `e1d0aba03da548336a5b59dab329c6a0f3bd14c9ad101a866e316070b8487f60`, design
  `58f2cc33142016d736748ed103aabf10892f060ecf1cf5e16e15e00b2c4b017c`, and tasks
  `1ef03cbcb186c0709415363e6a0e11c572deff18d85f89fc8023f8afe53324e2`.
  It then synchronized that identity, ran fresh draft convergence, performed only the explicitly
  authorized status-only promotion, and required ownership PASS. Task 64 then independently
  revalidated the same report and performed the distinct fresh promoted-byte review. Task-84
  restoration now supersedes this historical input.
- Unchanged: PAE-001 through PAE-038, every acceptance criterion, PFI/EXP/PJR/PWA/API PEX/DEO
  ownership, implementation, tests, code, migration, runtime, rollout, rollback, recovery,
  security/privacy, and external systems.

## Historical Spec Update: 2026-07-27 Current Upstream Drift Demotion and Convergence Reopen

- Change ID: `SPEC-CHG-2026-07-27-PAE-CURRENT-UPSTREAM-DRIFT-REOPEN`.
- Classification: behavior-preserving specification-authority `RESTORATION`.
- Current: PAE is approved with checked Tasks 73 and 64, but its active DEO and API PEX imports
  predate DEO-R47-001 and the final approved/post-reviewed API PEX bundle. Those markers therefore
  cannot authorize the current bytes.
- Expected: demote only the requirements frontmatter to `draft`; Task 81 records this
  requirements-first reopening; reset Tasks 73 and 64 to unchecked. The current authority path is
  `Task 74 -> Task 80 -> Task 81 -> Task 73 -> Task 64`. Task 73 must synchronize the final
  approved/post-reviewed DEO requirements/design/tasks identity
  `3c3317964acfd48909f3a55c45e40980ed355b2346dc0d9e8ef4e5cf7b719174`,
  `0a1e61cd4e06c3af535602dd9e980bb779843dd9b55eb2a10b954931a03295c7`, and
  `e9dc5d78eb1e013f18c6cf7fd7f9e5ac2c62e7e0bbd91bd7fa3da35dfa990d4d`, plus the final API PEX
  requirements/design/tasks identity
  `be13cca1231ae0611f130e726af8f51281dbb06660d5a863c29f370ff30281c7`,
  `96876ae940e6013c293b8e0d8978695cb75472dfb074f3608394f6657af12984`, and
  `086b07f9cbc42c54cafd99cd425dfbc74c36fe38347738169aa305e8b4ef10d7` before its fresh draft
  review and promotion. Task 64 then performs the distinct promoted-byte review.
- Unchanged: PAE-001 through PAE-038, all acceptance behavior, PFI/EXP/PJR/PWA/API PEX/DEO
  ownership, implementation, tests, code, migration, runtime, rollout, rollback, recovery,
  security/privacy, and external systems.

## Spec Update: 2026-07-27 Current Upstream Authority Imports

- Change ID: `SPEC-CHG-2026-07-27-PAE-UPSTREAM-AUTHORITY-IMPORTS`.
- Classification: behavior-preserving specification-authority `RESTORATION`.
- Current at authoring: the active Task-73 gate describes EXP, PJR, and PWA as future imports and
  pins superseded identities for all four upstream bundles.
- Expected: active imports pin and validate these exact approved three-file identities at their
  normative source paths:
  - PFI `specs/proof-flow-index`: `32fa6f5113712d3e8bfe7484cad65ed0ffd525212a36511a5cd95a3eb3fca243` /
    `f00c8e7ad2c151a4e89a47c20dfd7480845db3596c5f38c2e7175fa3b1755129` /
    `d5212f09e8a1edcf93a0af895f84a5d2b1d463c3021267574e4b8f591e7a9739`.
  - EXP `specs/proof-explanations-and-clarifications`: `a2a3e97055951bae745932e91693f9e6e09de2d1c4edb8d33ddb902a94063563` /
    `f66d0ca6650d1bfb6e9dfb8fc6bd8690b6e475ee02d645e5cb895d226f97c055` /
    `7fea5fc7eae2e8ace80028a6415ed4f5ae3f02113e3be84d8f6dc76ba5cd5285`.
  - PJR `pals-api/specs/proof-job-runtime`: `75c0dd6f44da5db808d767749896cf751895910cb520e606c796407759b245c4` /
    `a59af7fa1fdd6cc0594a123045260db9ac135c37c09d03a5ccb43555de5b86f3` /
    `33dd054c62bc02e0efc1fa2e6e6dbe9b88e91c64efb74984b1ae8db066c1627b`.
  - PWA `pals-api/specs/project-workspace-api`: `c6e7232aad472529139a7fa91351a1942b0ac4987abaea5089e3bbb4d3aa5f02` /
    `92f576820a9c3d1041f90163574e80bcc4ce355ff5c6c6e36cb3d047be4a8f4e` /
    `686598da329b043e17efdf91562cd61c202dbe7423d23c8e08e4cc478e2dedcc`.
  - API PEX `pals-api/specs/proof-explanations`: `6a3775af76a224cba05f611980639e54a40d36be8ecbc798c679a7c1469243c1` /
    `3af51d11d7f8ca78f02f99362dcacc399286b985b27c0ac99b4bb33760405bf9` /
    `6dc7d1f86ab1e693c9a85f1e7830c041dbf29e2d1f69f5d7a8a71fd4d1820d3d`.
  Task 73 pins these exact approved/post-reviewed identities before fresh PAE draft review. Any
  missing, non-approved, stale, or drifted identity fails closed.
- Unchanged: PAE-001 through PAE-038 behavior, exact PFI and DEO imports, parent ownership,
  Task-73/Task-64 review separation, implementation/test state, runtime, and external systems.

## Spec Update: 2026-07-27 Task-73 Completion Marker and Status Projection

- Change ID: `SPEC-CHG-2026-07-27-PAE-TASK73-COMPLETION-MARKER`.
- Classification: behavior-preserving specification-governance `RESTORATION`.
- Current: Task 73 reviews draft bytes, promotes only the requirements frontmatter, and runs the
  ownership gate while unchecked, but no rule permits recording its completion without invalidating
  that evidence. Active summaries also hard-code the bundle as draft after promotion.
- Expected: Task 73 remains `[ ]` through exact imports, draft review, frontmatter-only promotion,
  and ownership PASS. After and only after all succeed, publication proves that changing the Task-73
  checkbox from `[x]` back to `[ ]` reproduces the consumed tasks bytes, then changes only `[ ]` to
  `[x]`; this sole transform does not invalidate Task 73. Bundle authority follows requirements
  frontmatter, and implementation remains blocked until checked Task 64.
- Unchanged: PAE-001 through PAE-038, all acceptance criteria, imported behavior, Task-64 marker
  semantics, implementation/test state, runtime, rollout, rollback, recovery, and external systems.

## Spec Update: 2026-07-27 Task-64 Completion-Marker Cycle Restoration

- Change ID: `SPEC-CHG-2026-07-27-PAE-TASK64-COMPLETION-MARKER`.
- Classification: behavior-preserving specification-governance `RESTORATION` of PAE-033.
- Current: Task 64 requires a different fresh reviewer to validate the exact promoted bundle while
  its checkbox remains `[ ]`, and any later task-file byte change restarts the review. Parent DEO
  Task 36, however, must observe current approved PAE bytes with Task 64 checked, so checking the
  completion marker would invalidate the review that permits it.
- Expected: the distinct external Task-64 reviewer validates exact promoted requirements, design,
  and tasks bytes while the Task-64 checkbox remains `[ ]`. After and only after a successful
  verdict, publication changes exactly that Task-64 checkbox token from `[ ]` to `[x]`, after proving
  that the inverse token change from `[x]` to `[ ]` reproduces the exact Task-64-reviewed task bytes.
  This sole inverse-proved completion-marker publication does not invalidate Task 64. Every other
  byte change restarts the applicable Task-73/Task-64 sequence. Parent DEO Task 36 can then observe
  current approved PAE bytes and checked Task 64 without changing DEO.
- Side-branch correction: its backbone is `Task 75 -> Task 77 -> Task 78 -> Task 76`, with the
  additional direct dependency edge `Task 75 -> Task 78`. It neither satisfies nor reorders the
  authority branch `Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64`.
- Unchanged: `status: draft`; the Task-64 checkbox remains `[ ]` in this authoring change;
  PAE-001 through PAE-038 product behavior; exact PFI and DEO imports; implementation, tests, code,
  runtime/generated artifacts, external reports/systems; and DEO/LFE files.

## Spec Update: 2026-07-27 SDD-024 Residual Review-Output Cleanup

- Change ID: `SPEC-CHG-2026-07-27-PAE-SDD024-RESIDUAL-CLEANUP`.
- Classification: behavior-preserving specification-governance `RESTORATION`.
- Current: completed Tasks 75 and 77 define report-only Spec review and current PFI byte
  synchronization, but historical Spec-review severity totals, source/fingerprint provenance, and
  two reviewed-baseline bundle triples remain in the canonical files, while active PFI imports
  still name the superseded approved triple.
- Expected: completed Task 78 removes only those residual past Spec-review invocation outputs and
  synchronizes every active PFI import to exact current approved requirements
  `066ea92e458ba638d0d6f3f4b4b4c82a9c34d20373d8e1d01a70ace3b716c3a9`, design
  `778cbc387a813b060059a4bddc3d076a400b2ffda73ed35a54255c5f280df623`, and tasks
  `cf55a8424085ea97b1b7b9e4b25d08a9f8622200e72dab07a09ccfe3666abee0`.
  Substantive defect/remediation descriptions remain without retaining who reported them, their
  invocation-local counts, fingerprints, reviewed/baseline hashes, gate output, or verdict copy.
  Task 76 performs the fresh review and returns all invocation output externally.
- Unchanged: PAE-001 through PAE-038, every acceptance criterion and product decision, current
  approved DEO triple, implementation/test evidence, every existing task checkbox state, the
  `Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64` authority branch, the
  `Task 75 -> Task 77 -> Task 78 -> Task 76` side-branch backbone with direct
  `Task 75 -> Task 78`,
  `status: draft`, code, tests, generated/runtime artifacts, rollout, rollback, recovery, and
  external systems.

## Spec Update: 2026-07-26 Current Approved PFI Byte Synchronization

- Change ID: `SPEC-CHG-2026-07-26-PAE-PFI-BYTE-SYNC`.
- Classification: behavior-preserving specification-authority `RESTORATION`.
- Current: the active PFI import pins a superseded approved bundle identity.
- Expected: every active PFI import pins exact current approved requirements
  `066ea92e458ba638d0d6f3f4b4b4c82a9c34d20373d8e1d01a70ace3b716c3a9`, design
  `778cbc387a813b060059a4bddc3d076a400b2ffda73ed35a54255c5f280df623`, and tasks
  `cf55a8424085ea97b1b7b9e4b25d08a9f8622200e72dab07a09ccfe3666abee0`.
- Unchanged: PFI behavior, every PAE requirement and acceptance criterion, the report-only
  restoration, draft status, authority and execution ordering, implementation, tests, rollout, and
  external systems.

## Historical Spec Update: 2026-07-26 Report-Only Review-Ledger Restoration

- Change ID: `SPEC-CHG-2026-07-26-PAE-REPORT-ONLY-LEDGER`.
- Classification: behavior-preserving specification-governance `RESTORATION`.
- Current: requirements, design, and tasks retain multiple historical Spec-review invocation
  counters, severity/fingerprint rows, reviewed-file hashes, verdicts, and a repository-persisted
  convergence ledger. Those mutable records can be mistaken for evidence about current bytes. The
  active DEO Task-48 import also pins the superseded pre-restoration DEO triple.
- Expected: every Spec-review invocation starts from current inputs and returns its hashes,
  findings, severity counts, questions, gates, and verdict only in an external report. The canonical
  bundle retains stable behavior, substantive remediation scope, task definitions, task completion
  state, and implementation/test evidence, but no current or historical Spec-review ledger or
  verdict copy. The active import pins exact current approved DEO requirements/design/tasks
  `3c3317964acfd48909f3a55c45e40980ed355b2346dc0d9e8ef4e5cf7b719174`,
  `0a1e61cd4e06c3af535602dd9e980bb779843dd9b55eb2a10b954931a03295c7`, and
  `e9dc5d78eb1e013f18c6cf7fd7f9e5ac2c62e7e0bbd91bd7fa3da35dfa990d4d`; its Task-48 review remains
  external and authority-only.
- Sequence: Task 75 performs this requirements-first authoring, Task 77 synchronizes the exact
  current approved PFI bytes, and Task 76 independently reviews both changes. That side branch does
  not satisfy or reorder the existing
  `Task 74 -> Task 80 -> Task 81 -> Task 73 -> Task 64` authority-import/promotion/readiness path; Task 73 still performs
  its own current exact-import/draft-review/status-promotion/ownership sequence.
- Unchanged: PAE-001 through PAE-038, every acceptance criterion, runtime/evaluator/deadline/rubric/
  retrieval/model/toolchain/security/persistence/release/rollback/recovery behavior, `draft`
  status, implementation/test state, and external authority ownership remain unchanged.

## Historical Spec Update: 2026-07-26 Current DEO Task-48 Authority Import

- Change ID: `SPEC-CHG-2026-07-26-PAE-DEO-TASK48-AUTHORITY-IMPORT`.
- Classification: behavior-preserving **RESTORATION** of PAE-033 external authority evidence and
  Task 73/64 dependency traceability only. No product/runtime/evaluator/deadline/rubric/retrieval/
  model/toolchain/security/persistence/rollout/rollback/recovery behavior changes.
- Current: approved DEO-R44 requires both current PAE Task 73 and Task 64 to consume the external
  fresh current-byte DEO Task-48 report authority-only, but the child currently depends only on
  `74 -> 80 -> 81 -> 73 -> 64`. The governing DEO bundle is requirements
  `3c3317964acfd48909f3a55c45e40980ed355b2346dc0d9e8ef4e5cf7b719174`, design
  `0a1e61cd4e06c3af535602dd9e980bb779843dd9b55eb2a10b954931a03295c7`, and tasks
  `e9dc5d78eb1e013f18c6cf7fd7f9e5ac2c62e7e0bbd91bd7fa3da35dfa990d4d`.
- Expected: Task 74 records this authoring. Task 73 still follows Task 74 and, before its import
  audit/draft review/promotion, requires the external fresh Task-48 report for exactly those DEO
  bytes. Current Task 64 still follows Task 73 and independently revalidates the same exact
  Task-48 report before its promoted-byte review. The report is Spec-authority evidence only,
  remains external under SDD-024, and authorizes no implementation/test/runtime work. The sole
  child sequence remains `74 -> 80 -> 81 -> 73 -> 64 -> PRX T011`.
- Unchanged: every PAE-001 through PAE-038 behavior and acceptance oracle; all other exact imports;
  fresh-review separation; explicit status-only promotion; ownership gate; final DEO Task 36 and
  PLS/PRX execution prerequisites; code, tests, generated artifacts, and historical records.

## Historical Spec Update: 2026-07-26 DEO Task-64 Post-Review Compatibility Restoration

- Change ID: `SPEC-CHG-2026-07-26-PAE-DEO-TASK64-POST-REVIEW-RESTORATION`.
- Classification: behavior-preserving **RESTORATION** of PAE-033 authority-gate ownership and
  dependency traceability only. No runtime, evaluator, deadline, rubric, retrieval, model,
  toolchain, security, persistence, rollout, rollback, recovery, requirement ID, acceptance
  criterion, wire field, state, error, or product behavior changes.
- Current: the child correctly makes Task 73 perform exact authority imports, a fresh all-zero
  non-authoritative draft review, explicit status-only promotion, and ownership PASS, but it also
  absorbs the distinct promoted-byte review and labels Task 64 historical. Approved parent
  DEO-001/DEO-015 instead require current PAE Task 64 post-promotion readiness.
- Expected: completed Spec-only Tasks 74 and 80 record this repair. Task 53 remains historical.
  Task 73 records exact approved PFI and exact current approved/post-reviewed EXP/PJR/PWA/API
  PEX three-file imports, obtains a fresh independent all-zero technical draft review, performs only
  an explicitly authorized status-only promotion, and requires exact ownership PASS. Current Task
  64 depends on Task 73 and uses a different fresh reviewer to verify the exact promoted
  requirements/design/tasks bytes, all PAE-001 through PAE-038 behavior and traceability, and every
  exact import with `IMPLEMENTATION READY`, CRITICAL=0, HIGH=0, and no material question. Every
  pending executable Agent implementation/test task waits for Task 64.
- Unchanged: approved DEO remains unedited and authoritative; PFI/EXP/PJR/PWA/API PEX ownership,
  PLS T-071, parent PRX T-011, parent DEO T-036, current API Green dependencies, Task 53 historical
  evidence, status `draft`, runtime behavior, code, tests, migration, registry, generated artifacts,
  deployment, external records, and runtime evidence remain unchanged.
- Verification: current authority and dependency prose is exactly acyclic
  `Task 74 -> Task 80 -> Task 81 -> Task 73 -> Task 64 -> pending executable work`; Task 73 contains no post-promotion
  review; Task 64 requires Task 73, a distinct reviewer, exact promoted bytes/imports, PAE-001 through
  PAE-038 coverage, and the all-zero verdict; a fresh independent whole-bundle review is required.

## Spec Update: 2026-07-26 Parent-Authority Relocation

- Change category: behavior-preserving **MODIFIED** authority and dependency ownership for
  PAE-015/PAE-019/PAE-034; status is demoted from `approved` to `draft` until the coordinated parent
  and child reviews complete.
- Authority: explicit user delegation to resolve the recorded cross-bundle authority conflicts
  without routine approval pauses.
- Current: this child and draft EXP define the same explanation deadline and
  `lean-explanation-ja-v1` rubric differently; this child and draft PFI define opposite retrieval
  candidate/rerank contracts. Keeping PAE approved would make either parent impossible to approve.
- Expected: cross-repository explanation/clarification quality and retrieval behavior move to the
  focused parent EXP and PFI bundles while preserving this child's current runtime semantics:
  configurable three-attempt generation-start deadline with private fixed deadline diagnostics;
  the current independent evaluator identity, four `[0,1]` dimensions and mean/floor gate; and
  PostgreSQL-only top-eight retrieval followed by real `draft`-role rerank to zero through four
  contexts with no runtime seed union or score cutoff. After both parents are approved, PAE imports
  them without duplicate authority and passes a new independent review before promotion.
- Unchanged: public/API state and content, proof receipt recovery, claims, queue/verifier/deployment
  imports, model snapshot, generation graph, stored evaluation history, code and tests. This
  coordinated Spec cycle authorizes no implementation while PAE remains draft.

## Historical Spec Update: 2026-07-26 Authority-Relocation Gate and API Dependency Restoration

- Change ID: `SPEC-CHG-2026-07-26-PAE-AUTHORITY-RELOCATION-GATE`.
- Classification: behavior-preserving historical **RESTORATION** of PAE-015, PAE-021, PAE-033, and PAE-034
  dependency authority, current-status wording, design traceability, and executable task ordering.
  No runtime, evaluator, deadline, rubric, retrieval, model, toolchain, security, persistence,
  rollout, rollback, recovery, requirement ID, acceptance criterion, wire field, state, error, or
  product behavior changes.
- Current: Task 72 demoted PAE to `draft` after relocating cross-repository explanation quality and
  retrieval authority, but active lower requirements/design still describe the earlier approved
  Task 53/64 gate. Task 64 depends on an unnamed import-only alignment with no executable authoring,
  pre-promotion review, or promotion step. Pending Tasks 28/29 still cite superseded API Green tasks
  PJR T-020 and PEX T-033, and Task 37 stops its API PEX trace at PEX-024.
- Expected at that historical revision: approved PFI is imported from exact requirements/design/tasks SHA-256 values
  `066ea92e458ba638d0d6f3f4b4b4c82a9c34d20373d8e1d01a70ace3b716c3a9`,
  `778cbc387a813b060059a4bddc3d076a400b2ffda73ed35a54255c5f280df623`, and
  `cf55a8424085ea97b1b7b9e4b25d08a9f8622200e72dab07a09ccfe3666abee0`.
  Its Task 73 -> Task 64 sequence was the then-current authority-relocation gate. After the ordered
  `TDG -> EXP -> PJR -> PWA -> API PEX` chain is approved and separately post-reviewed, Task 73
  records the exact approved three-file identities of EXP, PJR, PWA, and API PEX; imports only their
  applicable authority without duplicating it; runs a fresh all-zero technical pre-promotion review
  while PAE remains non-authoritative `draft`; performs only an explicitly authorized status-only
  promotion; and requires exact ownership PASS. Current Task 64 then obtains a distinct fresh
  all-zero post-promotion review over exact promoted bytes and imports. Historical Task 53 and prior
  Task 64 evidence cannot satisfy this current sequence. Pending
  Agent API-dependent work additionally waits for current real API Green PJR T-053 and API PEX
  T-065; exact approved/post-reviewed PJR T-061, PWA Task 3, and API PEX T-073 are Spec-import
  predecessors, not substitutes for those Green results.
- Unchanged: completed historical task/evidence records remain immutable history; PLS T-071, parent
  PRX T-011, and parent DEO T-036 remain independent post-Spec implementation/test prerequisites;
  PFI keeps sole cross-repository retrieval authority, EXP keeps sole cross-repository
  explanation/clarification deadline and quality authority, and PAE owns only its Agent runtime and
  evaluator realization. This requirements-first Spec-only remediation retains `status: draft` and
  edits no code, test, parent/API Spec, ownership registry, generated artifact, external record, or
  runtime evidence.
- Verification at that historical revision named Task 74 then Task 73 then Task 64. The sole
  current PAE promotion/readiness sequence is `Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83
  -> Task 84 -> Task 73 -> Task 64 -> PRX T011`, governed by
  `SPEC-CHG-2026-07-27-PAE-T84-CURRENT-AUTHORITY-RESTORATION`; any Task-84-omitting path is
  non-authorizing. Tasks 75/76 remain a non-authorizing SDD-024 side review, and every
  still-pending executable Agent task depends on Task 64.

## Goals

- Turn verified Lean into a concise Japanese explanation with exact source-line references.
- Expand a selected explanation section when the learner asks a follow-up question.
- Attribute quality changes to retrieval, draft, sketch, prove, repair, end-to-end, or explanation.
- Preserve comparable run history while allowing optional export to an observability service.

## Non-Goals

- Expose hidden chain-of-thought or internal model reasoning.
- Explain unverified or absent Lean as though a proof existed.
- Treat Langfuse, a live model, or a network service as the canonical evaluation record.
- Assign a semantic score when no configured judge actually evaluated the output.

## Spec Update: 2026-07-26 PAE-038 Behavior-Property Closure

- Change category: behavior-preserving **RESTORATION** of PAE-037/PAE-038 release-property
  traceability. No requirement, acceptance criterion, wire field, state, or runtime behavior is
  added, removed, renamed, or relaxed.
- Current: the detailed canonical artifact clause still limits the registry to PAE-035–PAE-037 and
  eight property IDs, while the later PAE-038 acceptance contract and design require the same
  artifact to contain eleven IDs mapped across PAE-035–PAE-038.
- Expected: the one canonical artifact has exactly the four-requirement set
  `PAE-035|PAE-036|PAE-037|PAE-038` and exactly the eleven mappings already listed in the acceptance
  contract, including the three clarification-dispatch properties.
- Unchanged: approved status, PRX imports, queue/receipt behavior, artifact path/schema/digest/OCI
  label, ASCII sorting, Agent/Infra/API ownership, implementation gates, and every non-property
  requirement. This decision-free Spec correction authorizes no implementation and reopens only
  the fresh Task 64 post-promotion review.

## Spec Update: 2026-07-26 Immutable OpenAI Release Snapshot

- Change category: **MODIFIED** PAE-027 and PAE-034 model identity plus their exact release,
  evaluation, and live-gate projections.
- Authority: the official OpenAI model contract and explicit user delegation to resolve the
  recorded immutable-model identity defect.
- Current: the eight release roles are pinned to mutable alias `gpt-5.4-mini` while simultaneously
  forbidding aliases and requiring one reproducible identity per admitted release.
- Expected: every `.dev|.prod` release role is pinned to immutable snapshot
  `gpt-5.4-mini-2026-03-17`; the mutable alias and every other model remain invalid. ARCH-024 imports
  the same exact snapshot. `.local` model behavior remains outside this OpenAI registry.
- Unchanged: provider `openai`, the eight role names/cardinality, environment non-override,
  evaluator separation, live-path evidence, pricing/provenance rules, no fallback, and every
  non-model requirement. This coordinated Spec-only update authorizes no implementation and
  requires a new Task 64 review.

## Spec Update: 2026-07-26 Verified-Proof Receipt Recovery Closure

- Change category: **MODIFIED** PAE-015, PAE-020, PAE-021, and PAE-035 proof-receipt acknowledgement
  ordering; no wire DTO, API schema, state, claim shape, queue, or public outcome is added.
- Authority: explicit user delegation to resolve the recorded CORE/PAE/PEX receipt-recovery
  composition defect.
- Current: the worker deletes a verified proof receipt before beginning the separate explanation
  claim, leaving no durable trigger if it crashes between those actions or while explanation work
  is recoverable.
- Expected: `failed|canceled` proof terminals are acknowledged immediately. A PAE-020-valid
  `verified` proof keeps the same proof receipt while it enters only the separate PEX explanation
  claim. The receipt is acknowledged only after the one proof-ID-keyed explanation is durably
  `completed|failed`; busy, ambiguity, crash, and nonterminal explanation outcomes retain it for
  ordinary visibility/DLQ redelivery and a fresh claim after lease expiry.
- Unchanged: the proof claim ends at verified reconciliation; explanation uses a distinct claim and
  never reopens or reuses the proof claim; proof and explanation terminal states remain independent;
  no second queue, message, outbox, direct call, fallback, duplicate model owner, or fabricated
  completion is introduced. PRX-002 still owns the same receipt transport and PEX owns explanation
  persistence/claim behavior.

## Spec Update: 2026-07-26 PLS/PRX join alignment

- Change category: behavior-preserving **RESTORATION** of PAE-033 readiness metadata only.
- Current: active PAE prose says PLS T-071 precedes parent PRX T-011. Current approved PLS instead
  defines Task 71 and PRX T-011 as separately owned prerequisites that join only at PLS Task 62;
  PLS may not add a predecessor to PRX.
- Expected: PAE Task 53/64 continues to depend on current PLS T-061 and pre-T011 DEO T-047→T-048,
  never PLS T-071. Every still-pending executable Agent task independently requires completed PLS
  T-071, completed PRX T-011, and completed DEO T-036; no ordering edge exists between PLS T-071
  and PRX T-011. DEO T-049→T-053→T-036 remains post-T011.
- Unchanged: approved status, Task-53 promotion evidence, open Task-64 fresh review, all product
  behavior, ownership, APIs, schemas, tests, runtime, security, and rollout gates. This Spec-only
  edit changes no parent/PLS/DEO file and keeps Task 64 open.

## Spec Update: 2026-07-26 Current Parent Readiness and Draft-Review Repair

- Change category: **MODIFIED** PAE-033 and its readiness/acceptance/rollout traceability;
  behavior-preserving **RESTORATION** of PAE-035 through PAE-038 parent-import scope. No requirement
  ID is added, removed, renamed, reused, or promoted; `status: draft` is retained.
- Rationale/source: the current approved parent task graphs supersede stale PRX T-033, PLS T-032,
  and DEO T-033 readiness references. The accepted review policy also distinguishes a technically
  ready draft from implementation authority.
- Current: active prose requires one artificial status HIGH and forbids an
  `IMPLEMENTATION READY` draft verdict; it cites stale parent readiness tasks and incompletely
  describes the imported PRX scope.
- Expected: Spec readiness depends exactly on completed parent PRX T-036 then T-010, renewed PLS
  T-061, current DEO T-047 -> T-048 Spec restoration/convergence, and completed Agent T-065.
  DEO T-049 through T-053 then T-036 remain post-T-011 implementation/test predecessors rather
  than child-promotion predecessors. A fresh draft review must be technically
  `IMPLEMENTATION READY`, CRITICAL=0, HIGH=0, and have no material question, while explicitly
  recording that `status: draft` remains non-authoritative and authorizes no implementation.
  Explicit status-only promotion follows; ownership must then print exact
  `spec-ownership: PASS`; a different fresh reviewer must finally return the same all-zero
  `IMPLEMENTATION READY` verdict over promoted bytes. PAE-035 through PAE-038 import approved
  PRX-001 through PRX-009 and AC-001 through AC-009, including the PRX-009 clarification
  receipt/marker/`dispatch_uncertain` contract.
- Unchanged: product behavior, evaluator and content bytes, receipt/model/verifier implementation
  ownership, Red-before-Green, explicit promotion authority, separate post-promotion review, no
  fallback/mock/direct path, and all completed historical evidence remain unchanged. This update
  edits no implementation, tests, parent Specs, inventory, external system, or status.

## Spec Update: 2026-07-26 Approved PRX-009 Clarification Consumer Import

- Change category: **ADDED** PAE-038; **MODIFIED** PAE-033 and PAE-037 traceability. No existing
  requirement is removed, renamed, reused, or relaxed; `status: draft` is retained.
- Rationale/source: approved parent `specs/proof-runtime-cross-repository` PRX-009 and AC-009 now
  own the exact clarification SQS wire, receive routing, API worker-input marker, and terminal
  `dispatch_uncertain` semantics.
- Current: PAE-015 describes clarification claim/model work after a typed delivery but this bundle
  has no requirement importing the parent clarification codec, marker, receipt lifecycle, or
  `dispatch_uncertain` delete-without-generation behavior.
- Expected: PAE-038 imports that shared contract byte-for-byte and owns only Agent receive
  validation, API marker validation, fresh generation claim/model/update behavior, visibility,
  retention, and deletion. A terminal `dispatch_uncertain` worker input causes zero generation
  claim/model/update and permits deletion only of the exact surviving receipt.
- Unchanged: PAE-015 claim clocks and generation behavior after eligibility, proof dispatch under
  PAE-035, API persistence, Infra queue/redrive behavior, and all content/evaluation/verifier
  behavior remain unchanged. No second queue, direct call, shared task ledger, resend, inferred
  success, fixture, mock, fallback, or compatibility parser is authorized.

## Spec Update: 2026-07-15 PRX Child Contract Remediation

- Change category: **RESTORATION/MODIFIED** PAE-017, PAE-020, PAE-021, PAE-033, and
  PAE-037. No requirement is removed, renamed, reused, or promoted; `status: draft` is retained.
- Rationale: approved parent PRX-001 through PRX-008 supplies decision-free remediation rules for
  stale PJR-015 ownership, duplicate readiness gates, incomplete release-task
  dependencies, a stale Unix verifier boundary, evaluator-state cardinality, stale worker attestation
  ownership, incomplete PRX-006 provenance trace, and one digest-count typo.
- Current: active rollout/task text still assigns Agent provider/ECS/SQS quiescence observation and a
  durable cross-repository cutover sink inherited from PJR-015; pending Task 38 duplicates Task 53 and
  asks draft bytes for a post-promotion verdict; pending Task 24 asks the worker to construct an
  attestation; active resource/task text still names a Unix client; Task 50 can run before the PRX
  verifier Green and real integration; and Tasks 57/60 do not wait for the PAE-017 Green, PAE-034
  Green, and worker-client-removal/API-refetch Green evidence they consume.
- Expected: parent PRX supersedes the PJR-015 provider/quiescence/cutover ownership. Agent participates
  only by stopping, retaining, and later resuming SQS receipt under the parent order and by publishing
  Agent-owned worker/verifier image, compiler/toolchain, behavior-property, and release-provenance
  evidence. Infra alone observes provider/ECS/SQS quiescence and owns the durable cross-repository
  cutover/effect sink; API alone persists release/admission/reconciliation state. PAE-017 has one
  private TLS-1.3 mTLS HTTP boundary on port 18117 and no Unix compatibility path. The verifier server
  alone produces the imported attestation after real compile/cleanup; the worker has no verifier
  client or attestation builder and accepts only an authoritative API refetch. Task 53 replaces the
  never-executed Task 38 and owns only the draft pre-promotion review plus explicitly authorized
  status-only promotion; separate Task 64 owns the fresh post-promotion all-zero
  `IMPLEMENTATION READY` review. Draft review permits exactly the one PAE-033 status HIGH and does not
  require an all-zero verdict. Task dependencies enforce PAE-017 Green, PAE-034 Green, worker-client
  removal/refetch Green, PRX verifier Green, real integration, then Task 50 release evidence.
  Lower historical update text that names a Unix client/socket records a superseded prior revision;
  it is not an active transport, caller, rollout, rollback, or test authority.
- Unchanged: PAE-001 through PAE-016, PAE-018 through PAE-019, PAE-022 through PAE-032, and
  PAE-034 through PAE-036 retain their product behavior except for the explicit cross-boundary
  ownership/transport restoration above. The natural-statement through Clarify graph, evaluator
  five-variable contract, schema-v2/v3 and DEO bytes, compiler/toolchain/resource/cleanup rules,
  no-fallback rules, and all prior review history remain unchanged. No wire DTO, parent behavior,
  API/event/product-data schema, migration, implementation, test, parent Spec, Notion, or status edit
  is introduced.
- Compatibility/security/rollout/rollback/recovery: worker-side verifier transport and attestation
  construction, Unix/plaintext transport, Agent provider observation, Agent release-state persistence,
  and old cutover sinks are rejected rather than retained as compatibility paths. Rollout starts
  blocked, consumes parent/Infra evidence without declaring it, activates only the admitted v1 worker,
  and preserves receipts on stop/ambiguity. Rollback is a higher-sequence parent-admitted compatible
  release and never restores an old worker, Unix client, worker attestation, local compiler, provider
  observer, or child-owned cross-repository sink.

## Spec Update: 2026-07-15 PRX T-010 Agent Child Alignment

- Change category: **ADDED** PAE-035 through PAE-037; **MODIFIED** PAE-017, PAE-020,
  PAE-021, PAE-033, and PAE-034. No requirement is removed, renamed, reused, or promoted, and
  frontmatter remains `status: draft`.
- Rationale/source: approved parent
  `specs/proof-runtime-cross-repository` PRX-001 through PRX-008, AC-001 through AC-008, and
  parent Task T-010 require the Agent child to import the parent proof-dispatch, isolated-verifier,
  deployment-binding, trust, outcome, and telemetry contracts while specifying only Agent-owned
  receipt/DSP/verifier behavior. Parent T-003 and T-033 are complete; this update is only the Agent
  slice of T-010 and does not complete the API or Infra child work.
- Current: this child has no exact `pals.proof-job-dispatch.v1` receipt/attribute/hash/queue-binding
  validator; PAE-017 requires a Unix-socket-only verifier and loopback-only service network;
  PAE-020 lets the credentialed worker synthesize an attestation; PAE-021 lets that worker call the
  verifier directly; and the current rollout/tasks do not bind old-worker denial, the parent mTLS
  SecretBinary consumer ports, parent PRX child convergence, or repository-local PRX commands and
  artifacts.
- Expected: PAE-035 owns strict v1 receive validation, visibility/delete ambiguity, redelivery,
  poison retention, fresh-claim DSP lifecycle, and content-free outcomes without redefining the
  parent DTO. PAE-017/PAE-036 expose the existing exact toolchain/compiler engine only as the
  parent-imported private TLS-1.3 mTLS HTTP service on port 18117; the API-owned verified reconciler
  is its sole application caller. Only that server may produce the imported attestation after actual
  compile and complete cleanup; the DSP worker neither holds verifier transport secrets nor calls or
  simulates the verifier. PAE-037 closes Agent receipt stop/resume, old-worker denial participation,
  child property evidence, image/toolchain artifacts, commands, and README/SECURITY operations.
- Unchanged: natural statement -> OpenMath -> PostgreSQL/pgvector -> Draft -> Sketch -> Prove ->
  Route/Repair -> verified durable artifact -> Explain -> Clarify remains the release workflow.
  PAE-001 through PAE-016 and PAE-018 through PAE-034 keep their content, evaluation, repair-budget,
  provenance, privacy, append-only, no-mock, no-shortcut, and no-fallback rules except for the
  explicitly replaced verifier transport/caller/attestation ownership above. Raw compiler output
  remains private; across the imported HTTP boundary a compile failure contributes only the closed
  parent `verifier_compile_failed` diagnostic to Route/Repair.
- Ownership and data: `pals-agent` owns no public/internal API route, API PostgreSQL row, lock,
  transaction, migration, outbox, admission ledger, trust fence, provider resource, queue/DLQ,
  LocalStack volume, ECS/ALB/security group, IAM policy, KMS key, or Secrets Manager secret/version.
  `pals-api` remains sole database/HTTP/reconciliation authority and `pals-infra` remains sole
  resource/secret/deployment authority. This update introduces no product-data or evaluation-history
  migration.
- Compatibility/security/rollout/rollback/recovery: there is no Unix/TCP dual transport,
  unversioned queue parser, mixed-fleet window, worker client certificate, local compiler, direct
  call, plaintext route, shared role/filesystem, mock-success route, or old-image rollback. Rollout
  keeps receipt blocked until the parent admission/quiescence/gate order authorizes the exact v1
  candidate. Rollback is a higher-sequence parent-admitted compatible release; failure retains
  receipts and keeps old-worker receipt denied. Secret bytes remain memory-only and never enter
  environment, argv, file, shared volume, Spec, artifact, log, metric, trace, fixture, or response.

## Spec Update: 2026-07-15 Runtime, Retrieval, Evaluator, and Readiness Remediation

- Change category: **ADDED** PAE-034; **MODIFIED** PAE-010, PAE-013, PAE-016, PAE-019,
  PAE-027, PAE-029, and PAE-033. PAE-010 changes from Should to Must. No requirement is removed,
  renamed, reused, or promoted, and frontmatter remains `status: draft`.
- Rationale: explicit product decisions close the recorded gaps in the release runtime,
  under-authoritative retrieval, an environment-overridable generation identity, a release oracle
  that did not exercise the complete real path, stale PLS/DEO readiness sequencing, an evaluator
  state/identity gap, contradictory GNU Make exit expectations, and incomplete task traceability.
- Current: the Spec starts generation after retrieval without one closed natural-statement entry;
  does not normatively require OpenMath structuring or PostgreSQL/pgvector top-8 retrieval and
  reranking; permits inherited provider/model routing; records seven generation roles that omit
  OpenMath; permits an evaluator result without an explicit distinct-call oracle; the live release
  gate can pass without actual pgvector or repeated repair; Task 38 attempts to re-promote completed
  historical PLS Task 25 and uses the wrong child-draft status oracle; Task 32 cites historical PLS
  Task 28 and ambiguous parent exit propagation.
- Expected: PAE-034 defines the complete natural statement -> OpenMath -> PostgreSQL/pgvector
  retrieval -> Draft -> Sketch -> Prove -> isolated Lean -> Route/Repair -> Explain -> section
  Clarify flow. Structuring has at most three diagnostic attempts and fails closed. Retrieval always
  issues a pgvector top-8 query, applies canonical OpenMath structure plus a real LLM relevance
  rerank to zero through four contexts, and never uses a cutoff, exact-match shortcut, lexical,
  benchmark, mock, or ad-hoc verified fallback. The code-owned release registry pins all eight roles
  to `openai/gpt-5.4-mini-2026-03-17`; environment supplies connection credentials/endpoints and transport only.
  The semantic evaluator has one exact five-variable state and exact identity, uses a separate
  credential and distinct post-runtime request, and cannot reuse a generation call as an oracle.
  The sole live gate exercises every generation role, actual pgvector, at least two repair cycles,
  isolated Lean, a durable verified artifact, explanation, and clarification with no fixture/mock/
  recorded/template success. Parent Make maps child success to GNU Make exit 0 and every child
  nonzero/signal to GNU Make exit 2 without changing the direct child CLI contract.
- Readiness: current parent DEO Task 33 and current approved PLS Task 32 are the only Spec-readiness
  predecessors. PLS Task 25 stays completed and is never reopened or re-promoted. Applicable parent
  implementation evidence follows through PLS Tasks 21-24 and 33-36; child Task 32 waits for the
  final applicable PLS Task 36 evidence. At that historical revision, the draft pre-promotion gate
  permitted only the status-transition issue; the current Task 73 gate instead requires its external
  all-zero review. Only explicit authorization may then change frontmatter status;
  ownership PASS and a different fresh post-promotion review are still mandatory.
- Unchanged: verified-only explanation/clarification semantics, Japanese/reference bounds,
  PJR/PEX fencing, twelve-cycle repair maximum, PAE-017 isolation, schema-v2 history, schema-v3
  deterministic truth, DEO DTO/HMAC/publication bytes, privacy, append-only persistence, and parent/
  child repository ownership remain unchanged. No code, tests, parent files, Notion, API/event,
  product-data schema, migration, deployment, or status edit occurs in this Spec-only remediation.
- Compatibility/rollout/rollback: the release role registry and complete live gate intentionally
  reject environment model selectors and non-real success paths. Existing history is not rewritten;
  the eight-role comparability shape and registry revision form a new schema-v3 comparability group.
  Rollback disables the release workflow or evaluator and preserves artifacts/history; it cannot
  restore model override, retrieval shortcut, evaluator credential reuse, or fake success.

## Historical Spec Update: 2026-07-14 F-001 through F-006 Remediation

- Change category: **MODIFIED** PAE-010, PAE-017, PAE-019, PAE-027, and PAE-033; no requirement ID
  is added, removed, renamed, reused, or promoted.
- Rationale/source: the remediation addressed F-001 parent PLS-012 readiness/status conflict,
  F-002 an impossible child draft/pre/post-promotion gate, F-003 under-bound evaluator transport and
  credential origin, F-004 incomplete evaluator-versus-generation identity separation, F-005 no
  executable current-task release oracle for `lean-explanation-ja-v1`, and F-006 no Git
  executable/version/content attestation in `verifier_toolchain_sha256`.
- Current: changed parent PLS bytes are labeled approved while current task 25 is open; the child
  pre-promotion gate allows a blocking HIGH while also claiming no blocking quality defect; evaluator
  HTTP, redirects, credential reuse, and origin ownership are not closed; equality checks only one
  configured generation identity; the live explanation rubric has no exact command/result/evidence
  gate in the current DAG; and runtime Git can influence Lake metadata resolution without entering
  the verifier-toolchain digest.
- Expected at that revision: the parent PLS bundle was treated as draft pending an explicit
  current-byte promotion sequence, and the child draft gate expected zero CRITICAL/HIGH findings
  before authorization. Both readiness statements are superseded by the 2026-07-15 update: PLS is
  already approved and waits only for current Task 32 readiness, while the child draft review admits
  only the parent's exact PAE-033 status fingerprint. Evaluator HTTP is loopback-only, every non-loopback origin requires
  HTTPS, a dedicated evaluator credential is bound to exactly one configured OpenAI origin with no
  redirect or generation-secret reuse, and evaluator identity differs under one closed normalization
  from every non-null contributing generation identity. The exact live pytest command, process/JUnit
  result, and create-only private evidence object below are the sole `lean-explanation-ja-v1` release
  oracle. The build/startup manifest additionally binds a closed Git descriptor, executable bytes,
  and exact `git --version` output into `verifier_toolchain_sha256`.
- Unchanged: explanation/clarification content and rubric thresholds, deterministic evaluation truth,
  generation/evaluator prompt separation, schema-v2/v3 field grammar, DEO DTO/HMAC bytes, PAE-017
  Unix isolation/resource/deadline/cleanup behavior, parent/child ownership, no-fallback behavior,
  canonical history, and completed historical evidence remain unchanged. No API/event/product-data
  schema or migration is introduced.
- Compatibility/security/rollout/rollback: evaluator configuration intentionally becomes stricter;
  legacy generation-key reuse, non-loopback HTTP, redirects, and ambiguous/self-judge identities fail
  before a judge request. Rollback removes the complete evaluator configuration and yields explicit
  zero-call `not_evaluated`; it may not restore credential reuse or insecure transport. The Git
  descriptor changes the verifier-toolchain digest and therefore starts a new comparability group
  without rewriting old rows. No code, test, deployment, parent promotion, or child promotion occurs
  in this Spec-only update.

## Spec Update: 2026-07-14 Whole-Bundle Convergence Remediation

- Change category: **MODIFIED** PAE-014, PAE-021, PAE-027, PAE-029, PAE-032, and PAE-033; no requirement ID
  is added, removed, renamed, or reused.
- Rationale/source: the remediation addressed stale parent readiness metadata,
  a partial implementation gate, a PJR-012 response contradiction, unbound model-call provenance,
  a contradictory schema-v3 evaluator role, an undefined producer invocation surface, missing API Green predecessors, misplaced parent
  orchestration ownership, and an incomplete approval/post-promotion audit sequence.
- Current: the child imports a historical parent revision, blocks only selected future tasks, permits
  `lease_too_short` on the proof-generation claim path, records model calls without proving their
  identity/count agreement with comparability while admitting an evaluator `explanation` row that
  the smoke-v1 semantic contract excludes, and describes a projector/publisher without one
  callable idempotent export operation. Child task text also assigns parent Make/Compose behavior.
- Expected: the parent Task 2 state is retained only as historical DEO-001 through DEO-020 task
  context; any parent ownership update receives its own fresh current-byte review before
  child promotion. Every still-pending PAE-001 through PAE-034 implementation/test task is blocked by
  one whole-child gate. PAE-021 consumes the exact PJR-012 acquisition/renewal unions and terminal
  stop/ack rules. Every model call is cross-bound to comparability and prompt-channel cardinality;
  schema-v3 evaluator rows are closed to `draft|sketch` only.
  One closed Agent CLI operation selects a completed invocation, publishes deterministic create-only
  targets, returns exact replay/error results, and never mutates canonical evidence.
- Unchanged: the DTO field grammar, existing material/HMAC messages and pinned digests, canonical
  evaluation truth, PAE-017 isolation contract, parent/consumer independence, schema-v2 behavior,
  privacy exclusions, and no-fallback rules remain unchanged. No DTO/HMAC digest is recomputed
  because this update changes operation/control validation only, not any hashed normative byte input.
- Compatibility/migration/rollout/recovery: no persisted schema or data migration is introduced.
  The stricter schema-v3 provenance validation rejects formerly under-bound records rather than
  rewriting them. Export target conflicts and torn pairs remain explicit and non-mutating. Rollout
  remains blocked until parent current-byte reviews, explicit child status promotion, and a fresh
  post-promotion whole-child audit complete; rollback disables the optional operation and preserves
  canonical data and existing private artifacts.

## Spec Update: 2026-07-13 Iterative Repair Restoration

- Change category: **ADDED** PAE-016; no existing requirement ID is repurposed.
- Current: the implementation has a configurable multi-attempt repair loop, but the approved Spec
  does not prevent a regression that stops after the first failed repaired candidate.
- Expected: every repairable Lean failure, including an empty initial generated candidate, feeds
  its latest diagnostics into another LLM-selected DSP repair route until verification succeeds or
  an explicit terminal condition is reached, with a default budget of twelve repair generations,
  durable per-attempt checkpoints, and an explicit final termination reason.
- Unchanged: invalid infrastructure/configuration diagnostics are not sent to the LLM, repair-route
  selection failure remains explicit, and no failed candidate may be reported as verified.

## Spec Update: 2026-07-13 Compiler Diagnostics Visibility

- Change category: **RESTORATION** of PAE-016's diagnose/repair loop from new live evidence.
- Current: a `pals.sketch_contract_mismatch` preflight finding prevents Lean compilation, so all
  twelve repairs can receive only the same scaffold diagnostic while real Lean errors remain hidden.
- Expected at that intermediate revision: a sketch-scaffold mismatch remained a failing contract
  diagnostic but no longer suppressed compilation. This intermediate product-truth rule is
  superseded by the current Runtime Oracle Separation update below.
- Unchanged at that revision: safety and formal-theorem identity preflight remained compile-blocking
  and compiler failure never became success. The current update preserves those properties while
  removing method/scaffold adherence from proof correctness.

## Spec Update: 2026-07-14 Evaluation Provenance Restoration

- Change category: **RESTORATION** of PAE-001, PAE-008, PAE-009, and PAE-016.
- Current: deterministic explanation evaluation can validate line references without first proving
  that the evaluated proof artifact has `verification.success=true`; repair evaluation can also
  pass when the terminal artifact omits `repairs_used` or `termination_reason`.
- Expected: explanation quality is `not_evaluated` unless successful Lean verification is present,
  and repair quality is `not_evaluated` whenever either mandatory terminal provenance field is
  absent. Rejected Lean and incomplete terminal artifacts never contribute a passing score.
- Unchanged: explanation generation remains verified-only, present but invalid evidence still
  fails rather than becoming unevaluated, and the canonical stages, metric definitions, schema
  version, history format, and repair state machine remain unchanged.

## Spec Update: 2026-07-14 Worker Claim Restoration

- Change category: **MODIFIED** PAE-015 to make its existing idempotency requirement executable.
- Current: concurrent duplicate SQS deliveries can both observe a non-terminal API record and call
  the explanation or clarification model before either terminal write wins.
- Expected: each delivery uses a fresh opaque claim ID, calls the model only after the API reports
  `acquired`, skips all other claim statuses, and supplies that claim on terminal writes.
  The worker declares its required lease before acquisition, has a hard total generation deadline,
  and refuses model work unless the API-granted remaining lease covers that deadline plus the
  required safety margin.
- Unchanged: task message shapes, verified-only explanation generation, typed clarification input,
  explicit generating/completed/failed persistence, and absence of canned/local fallback output
  remain unchanged.

## Spec Update: 2026-07-14 Security and Fail-Closed Restoration

- Change category: **ADDED** PAE-017 and PAE-018; **RESTORATION** of PAE-004, PAE-011, PAE-012,
  PAE-015, and PAE-016. No existing requirement ID is repurposed.
- Current: generated Lean can execute compile-time IO in the credentialed worker process; a
  successful compile followed by checkpoint failure can still serialize as verified; malformed
  claim resources can authorize model work or acknowledgement; evaluation-history recovery checks
  its ambiguity marker outside the history lock and creates that marker only after destructive
  truncation; exact-Draft mismatch can reach Lean for benchmark candidates; HTTP socket inactivity
  timeouts can be extended indefinitely by slow response bytes; clarification IDs enter URL paths
  without single-segment validation/encoding; and clarification generation has no explicit
  successful-verification argument or worker-side proof cross-check. The real five-record schema-v2
  evaluation history also contains four legacy non-null semantic comments in line 5, so the current
  strict reader rejects the whole history even though the remaining records and fields are valid.
- Expected: all Lean invocations execute only in the self-verifying PAE-017 sandbox boundary;
  checkpoint, claim, history, preflight, timeout, path, and clarification gates fail closed under
  the exact contracts below, with adversarial regression tests for each reported bypass. Legacy
  semantic comments are repaired only by the explicit, digest-pinned, backup-first PAE-018 CLI
  migration; ordinary load never edits or ignores a record.
- Unchanged: lexical Lean checks remain defense in depth but are not the security boundary; API
  PEX response schemas and claim ownership remain unchanged; successful verified proof and
  clarification behavior, iterative repair, exact-Draft semantics, append-only history, provider
  selection, and truthful no-fallback model behavior remain unchanged.

## Spec Update: 2026-07-14 Independent Semantic Evaluator

- Change category: **ADDED** PAE-019 and **MODIFIED** PAE-010's evaluator provenance/configuration
  contract; no existing requirement ID is repurposed.
- Current: `build_semantic_stage_judge` implicitly selects the generation pipeline's
  `PALS_LLM_PROVIDER` and `PALS_OPENAI_MODEL`/`OLLAMA_*` model, so an evaluation can silently
  self-judge without a separately pinned evaluator identity.
- Expected at that revision: semantic evaluation has an explicit all-or-none
  provider/model/revision/endpoint configuration, rejects the same configured generation
  provider/model, records the evaluator identity and rubric on every semantic metric, and emits
  explicit `not_evaluated` metrics with zero judge calls when the evaluator is unconfigured. The
  current F-003/F-004 remediation supersedes only its transport, credential, and identity-comparison
  breadth with the stricter PAE-019 contract below. No generation setting is an evaluator fallback.
- Unchanged: deterministic metrics and stage status remain canonical; semantic judging is optional,
  unavailable/invalid judging never fabricates a value or changes deterministic truth, and prompts,
  outputs, free-text comments, endpoints, credentials, and errors remain outside history/public
  payloads.

## Spec Update: 2026-07-14 Repair Continuation and Route Retry Evidence

- Change category: **MODIFIED** PAE-016; no requirement ID is added or repurposed.
- Current: a real-model run can appear to stop after the first failed compile/repair transition,
  and route-selector malformed JSON has insufficient retry/evidence coverage to distinguish a
  truthful exhausted selector from premature termination.
- Expected: a selected route always drives repair generation and verification of the next
  candidate. Repair continues until verification success, an explicitly diagnosed non-repairable
  failure, checkpoint-store failure, or exact configured budget exhaustion. Each route selection
  permits exactly three real selector calls (initial plus two corrective retries), succeeds on the
  first valid strict decision, and only then may fail explicitly; it never invents a heuristic or
  configured-model fallback. Candidate artifacts, immutable checkpoints, and status evidence retain
  every candidate's Lean code, diagnostics, and inbound selected-route evidence in order.
- Unchanged: the default repair-generation budget remains 12, route-selector retries do not consume
  that generation budget, checkpoints precede later route selection, truthful provider/model
  behavior and PAE-017 verification remain mandatory, and route-selection exhaustion remains the
  closed terminal reason `repair_route_selection_failed`.

## Spec Update: 2026-07-14 Complete Capability Attestation

- Change category: **MODIFIED** PAE-017 to close an isolation-attestation gap discovered by the
  real Docker omission matrix; no requirement ID is added or repurposed.
- Current: a non-root Docker process can report a zero effective capability set while retaining a
  nonzero bounding set when `--cap-drop ALL` is omitted, so effective-only startup attestation
  accepts a weaker outer boundary.
- Expected: startup proves that Linux inherited, permitted, effective, bounding, and ambient
  capability sets are all zero; omission of capability dropping fails before the verifier socket
  is published.
- Unchanged: all other PAE-017 process, network, filesystem, environment, cgroup, child-resource,
  and no-fallback requirements remain unchanged; the capability change is additive and requires no
  persisted-data migration.

## Spec Update: 2026-07-14 Bounded Lean Runtime Viability Restoration

- Change category: **RESTORATION** of PAE-017; no requirement ID is added or repurposed.
- Current: the first real Docker compile proves that the design's 2 GiB virtual-address and
  32-process child limits abort valid Mathlib/Lake startup with `failed to create thread`; once
  virtual startup proceeds, the runtime image lacks Git metadata tooling and Lake attempts a
  forbidden project refresh instead of using the complete read-only cache.
- Expected: the outer verifier cgroup remains capped at 4 GiB resident memory and 64 PIDs while
  each Lean child has a 16 GiB virtual-address cap, a 64-process `RLIMIT_NPROC`, and
  `--threads=1`. The runtime image includes the local Git metadata reader needed for `lake env` to
  validate its prebuilt cache without a network or write. Valid Mathlib Lean compiles, while a
  32 GiB allocation, process fan-out, output flood, and timeout descendants still fail closed.
- Unchanged: the worker has no Lean toolchain; verifier root/project remain read-only; network-none,
  socket seccomp, Landlock, secret-free environment, CPU/file/descriptor/output limits, startup
  attestation, and no local/TCP fallback remain mandatory. No API, history, or product-data schema
  changes or migration are introduced.

## Spec Update: 2026-07-14 Landlock Git Metadata Viability Restoration

- Change category: **RESTORATION** of PAE-017; no requirement ID is added or repurposed.
- Current: after cache ownership permits UID 65532 to read mode-0600 Mathlib objects, direct
  `lake env lean` accepts the exact verified fixture, but the Landlock child denies Git's
  read/write open of `/dev/null`. Lake treats that metadata-reader failure as a changed package URL
  and attempts a forbidden delete/clone on the read-only project.
- Expected: the runtime copy owns the complete Lake workspace as UID/GID 65532. Landlock keeps the
  root and project read-only and grants read/write only to the already-existing `/dev/null` device
  as a non-persistent Git sink, in addition to the bounded scratch directory. The exact UTF-8
  fixture with SHA-256
  `572596a39973c1c0deeee7a7b9b92acfd5c840219399e3cd0bb9ee12f68a7d68` compiles through the Unix
  verifier without update, clone, fetch, or project write.
- Unchanged: `/dev/null` is not a filesystem persistence channel; creation, removal, truncation,
  rename, or write access anywhere else under root/project/socket remains denied. Network-none,
  socket seccomp, secret-free environment, cgroup/rlimit/output bounds, startup attestation, and
  no local/TCP fallback remain mandatory.

## Spec Update: 2026-07-14 Bounded Mathlib File-Descriptor Viability

- Change category: **RESTORATION** of PAE-017; no requirement ID is added or repurposed.
- Current: with cache ownership and the narrow `/dev/null` Landlock rule fixed, the exact fixture
  still fails only through the Unix child at `Ultra.olean.private`. A controlled same-image
  comparison holds non-root, read-only root/project, network-none, zero capabilities, 64 PIDs,
  2 GiB memory, and one CPU constant: `nofile=128` fails while `nofile=1024` compiles the exact
  fixture with exit zero.
- Expected: both the outer verifier container and every Lean child use a hard soft/hard open-file
  limit of 1024, and startup attestation rejects a missing, unlimited, or greater limit. The exact
  fixture compiles through the Unix client while descriptor exhaustion remains bounded.
- Unchanged: CPU, resident/virtual memory, PID/process, file-size, output, timeout, filesystem,
  network, environment, capability, and no-fallback boundaries remain unchanged. No unbounded or
  host-default descriptor limit is authorized.

## Spec Update: 2026-07-14 Mathlib Address-Space Viability Correction

- Change category: **RESTORATION** of PAE-017; no requirement ID is added or repurposed.
- Current: the prior `Ultra.olean.private` diagnosis incorrectly attributed success to the
  descriptor change without independently holding the child address-space limit constant. In the
  final image, plain `lake env lean` with `nofile=1024` reaches the 95-second wall timeout without
  that read error, while the same command without Landlock but with the production
  `RLIMIT_AS=8 GiB` fails immediately at `Ultra.olean.private`. The actual UID/GID-65532 Lean
  process has only nine open descriptors but reaches `VmPeak=10,780,620 kB`, proving that 8 GiB is
  below valid Mathlib virtual-address demand.
- Expected: every Lean child has a bounded 16 GiB virtual-address limit and retains the
  1024-descriptor soft/hard limit. The digest-pinned exact fixture compiles successfully through
  the Unix verifier under the complete production child boundary, while a real 32 GiB virtual
  allocation fails closed.
- Unchanged: the outer verifier remains bounded by an attested cgroup; Landlock, seccomp,
  read-only filesystems, network isolation, closed environment, timeout,
  output/file/process limits, startup attestation, and no-fallback behavior remain mandatory.

## Spec Update: 2026-07-14 Cold Mathlib Deadline Viability

- Change category: **RESTORATION** of PAE-017; no requirement ID is added or repurposed.
- Current: the 16 GiB child address-space cap removes the immediate `Ultra.olean.private` failure,
  but the digest-pinned Mathlib fixture exceeds the current 90-second server and 95-second client
  defaults on one CPU and terminates with exit 137. A bounded one-off compile completes only after
  several minutes, so the old deadlines reject valid cold-cache work.
- Expected: the production verifier uses a hard 300-second server wall deadline and the production
  Unix client uses a hard 310-second end-to-end transport deadline. The server continues to reject
  values above 300 seconds, production client settings accept only a finite value greater than 300
  and at most 360 seconds, and the exact fixture succeeds through the Unix boundary on the
  production-sized path.
  Adversarial timeout coverage uses an explicit short test-local server/client deadline
  and still proves complete process-group termination.
- Unchanged: all deadlines remain finite hard walls; the 16 GiB child virtual-address cap, bounded
  outer resident memory, 64-PID, 1024-descriptor, one-thread, output/file, filesystem, network,
  environment, capability, startup-attestation, and no-fallback boundaries remain mandatory.

## Spec Update: 2026-07-14 Production-Sized Mathlib Outer Cgroup

- Change category: **MODIFIED** PAE-017 to restore valid exact-fixture execution under strict outer
  limits; no requirement ID is added or repurposed.
- Current: with child `RLIMIT_AS=16 GiB`, `nofile=1024`, one Lean processing thread, and a
  240-second observation window, the one-vCPU/two-GiB verifier runs at about 98.5% CPU and
  1.912 GiB resident usage and does not finish the exact fixture before the prior deadline. The
  cgroup is a material production bottleneck rather than merely a health-check boundary.
- Expected: the verifier outer cgroup is strictly capped and startup-attested at no more than two
  vCPUs, 4 GiB resident memory, and 64 PIDs, matching the intended Fargate task size. Under those
  limits plus the complete child isolation boundary, the digest-pinned exact fixture succeeds
  through `UnixLeanVerifierClient` before the 300-second server deadline. Missing, unlimited, or
  greater CPU/memory/PID limits fail startup.
- Unchanged: child `RLIMIT_AS=16 GiB`, `RLIMIT_NPROC=64`, `nofile=1024`, `--threads=1`, the
  300/310-second hard deadline pair, read-only filesystems, Landlock, seccomp, no network, closed
  environment, zero capabilities, bounded scratch/output/file size, startup attestation, and
  no-fallback behavior remain mandatory.

## Spec Update: 2026-07-14 Compose Contract Oracle Alignment

- Change category: **RESTORATION** of PAE-017 test evidence; no behavior or requirement ID changes.
- Current: the root Compose contract test still asserts `cpus=1` even though the approved PAE-017
  production boundary and current Compose declaration require the measured viable `cpus=2` cap.
- Expected: the Spec-traced test asserts exact `cpus=2` and continues to assert the existing 4 GiB,
  64-PID, 1024-nofile, read-only/network/capability, and deadline boundary values.
- Unchanged: production remains strictly capped at two CPUs; no runtime value is reduced to satisfy
  a stale test, and no Docker build/recreate is part of this source/test correction.

## Spec Update: 2026-07-14 Verified Worker Attestation Contract

- Change category: **ADDED** PAE-020; no existing requirement ID is repurposed.
- Current: the agent sends a `verified` proof-job worker update with Lean and artifact URI but no
  verifier attestation, so the now-confirmed API discriminated contract rejects the update and
  cannot bind verified state to the exact Lean/artifact identity.
- Expected: the worker derives the exact v1 attestation from the verified callback, and the API
  client sends it only with a nonblank-Lean/nonblank-artifact `verified` update after validating the
  job ID, UTF-8 Lean digest, URI, singleton success value, and exact field set. Every non-verified
  wire payload omits the attestation key.
- Unchanged: Lean verification and checkpoint publication still precede `verified`; failed and
  intermediate update fields/states otherwise retain their existing contract; no verifier secret,
  prompt, output, or new persisted-data migration is introduced; no legacy/fabricated attestation
  fallback is authorized.

## Spec Update: 2026-07-14 Proof Generation Fencing and Integrity Restoration

- Change category: **ADDED** PAE-021 through PAE-025 and **MODIFIED** the API-wire, clarification,
  semantic-threshold, and history-reader contracts; no existing requirement ID is repurposed.
- Current: duplicate proof deliveries can both enter generation; an API terminal response can hide
  conflicting Lean/attestation and let the loser explain unpersisted Lean. Repair-route diagnostics
  serialize local `metadata` that the API rejects, raw prompt/output/provider failure material can
  enter API diagnostics/context, clarification extraction strips exact Lean bytes, and malformed or
  wrong-target terminal clarification input is acknowledged before schema/ID validation. Semantic
  threshold tolerance accepts the representable float immediately below `0.80`. The history reader
  also accepts unknown fields/arbitrary metrics and trusts a persisted stage status that contradicts
  its metric evidence.
- Expected: proof model work starts only after an exact API-owned generation claim and every status
  write is fenced; verified explanation uses an authoritative post-write API re-read. API diagnostic
  and context projection is closed and redacted without losing required Lean/diagnostic/route
  evidence. Clarification validates the exact target/schema before terminal acknowledgement and
  preserves Lean/theorem bytes. The semantic boundary is exact comparison, and every supported
  history schema is closed and recomputes allowed stage status from metric evidence.
- Unchanged: no heuristic/model fallback is added; local artifacts/checkpoints may retain internal
  prompts/outputs under their existing private boundary; exact verifier/attestation, twelve-repair,
  explanation claim, privacy, migration, and append-only durability requirements remain in force.

## Spec Update: 2026-07-14 Versioned Evidence Evaluation Suite

- Change category: **ADDED** PAE-026 through PAE-029 and **MODIFIED** PAE-007 through PAE-013 for a
  new schema-v3 suite record while preserving strict schema-v2 history compatibility.
- Current: the built-in benchmark runs three prompts and reports model-attempt success, while the
  canonical evaluator can label draft/sketch stages passed from mere non-empty output. There is no
  versioned suite runner that binds expected retrieval evidence, independently judged state
  accuracy, first/final compile, repair convergence, latency percentiles, token usage, or cost
  evidence into one repeatable run/summary contract.
- Expected: a versioned suite keeps the exact original three smoke prompts, passes only clean runtime
  input to generation, and applies expected draft IDs/semantic rubrics only after runtime completion.
  Each case records ranked retrieval evidence, independent draft/sketch judge evidence, compile and
  repair outcomes, wall latency, complete provider token evidence, and estimated/actual cost when
  supported. Missing token, cost, or judge evidence is null/`not_evaluated`, never zero or passing.
  Typed JSON and Markdown summaries aggregate exact rates, nearest-rank p50/p95, usage, and cost;
  parent Make targets run smoke/full/compare against append-only JSONL.
- Unchanged: deterministic compile/retrieval facts remain canonical, semantic judging never borrows
  a generation model, raw runtime input contains no expected strategy/rubric, ordinary history load
  never mutates data, live model success is never fabricated by a fixture, and Langfuse remains an
  optional noncanonical export.

## Spec Update: 2026-07-14 Runtime Oracle Separation and Lean-Compile Truth

- Change category: **MODIFIED** PAE-013 and PAE-016; no requirement ID is added or repurposed.
- Current: runtime code contains benchmark-specific formal harnesses and expected method fragments.
  Failed method/oracle checks become diagnostics and can flow verbatim into route/repair/generation
  prompts. Sketch text is also treated as a proof-correctness contract. The real x² artifact
  `/private/tmp/x2-repair-checkpoint-gpt54mini-20260713.json` establishes only that its final attempt
  was `phase=preflight`, `elapsed_ms=0`, and compilation was blocked by sketch text mismatch; it is
  not evidence that the candidate would compile.
- Expected: normal generation/repair has no benchmark ID/prompt registry, expected strategy,
  required/forbidden method fragment, hidden harness, evaluation rubric, relevance label, or sketch
  text oracle. Repair prompts contain only the candidate and actual runtime generation/transport,
  safety, user-supplied formal-theorem identity, verifier, and Lean compiler diagnostics. Once those
  blocking checks pass, successful isolated Lean verification is the proof-correctness oracle.
  Sketch/scaffold adherence is computed only after runtime as an evaluation metric; it may fail for
  a semantically equivalent or rephrased scaffold while the proof remains `verified`.
- Unchanged: exact-Draft retrieval identity/equivalence evidence and the generated theorem's binding
  to an explicitly user-supplied formal statement remain deterministic blocking preflight; neither
  can be bypassed by comments/strings. All Lean comparison/compile work remains inside PAE-017,
  compiler failure remains failed, repair has no fallback route, and expected benchmark strategy is
  evaluation-only.

## Spec Update: 2026-07-14 Comparable State-Evaluation Evidence

- Change category: **MODIFIED** PAE-012, PAE-025, and PAE-026 through PAE-029.
- Current: the existing five schema-v2 rows mix runs/cases without immutable suite, case, generation,
  evaluator, or toolchain digests. Their draft/sketch non-empty values and the displayed `0.4` are
  structural observations, not accuracy. The current history summary can combine heterogeneous
  records, and no explanation-chain digest proves which verified Lean was explained.
- Expected: schema-v3 records bind independently reviewed relevant draft IDs, distinct draft/sketch
  rubrics, paired first/final compile and repair uplift, latency, complete usage/cost, explanation
  chain, and exact suite/case/generation/evaluator/toolchain digests. Summaries exclude every
  `not_evaluated` fact and group only one exact comparability key; comparison rejects heterogeneous
  keys rather than averaging them. Legacy v2 remains readable but is labeled structural legacy
  evidence and cannot produce a state-accuracy or complete-suite claim.
- Unchanged: the five migrated records are never deleted or silently rewritten; ordinary load stays
  strict/non-mutating; missing evidence remains null/`not_evaluated`; evaluator identity is separate
  from generation; and no fake compiler/model fixture establishes live success.

## Spec Update: 2026-07-14 Schema-v3 Observability Compatibility

- Historical change category: **MODIFIED** PAE-014, PAE-027, and PAE-028 to depend on the then
  current parent requirements DEO-001 through DEO-015; no canonical evaluation field or gate was
  weakened. The current DEO-v1 producer alignment below supersedes only that parent range and
  producer-fixture description.
- Current: `pals-observability` has a strict schema-v2 parser and rejects the current local history;
  it has no schema-v3 case/summary branch. Task ownership previously named only `pals-agent`, so a
  live v3 suite could be canonical locally while being silently unexportable despite the optional
  Langfuse claim; PAE-028 summary export was also unspecified.
- Expected at that revision: parent Spec `specs/dsp-evaluation-observability-export` and DEO-001
  through DEO-015 are
  the sole cross-repository authority. `pals-agent` retains only canonical v3 case/summary fields,
  formulas, serializers, and DEO-011 producer fixtures. Consumer/projection/SDK/read-back behavior
  and the shared compatibility gate are referenced from DEO rather than repeated here.
- Unchanged: Langfuse remains optional and noncanonical; no vendor SDK enters `pals-agent`; prompts,
  Lean, expected strategy/rubrics, model identity, chain digests, and credentials are never exported.

## Spec Update: 2026-07-14 DEO-v1 Agent Producer Alignment

- Rationale and source: parent Task 2 was complete for the then-current DEO-001 through DEO-020
  revision. The user explicitly requested those Agent-owned producer obligations be made exact
  here. That historical task state is not a child verdict and does not review later DEO-021 or
  PLS-012 ownership bytes; its per-invocation review evidence is not retained here.
- Change category: **MODIFIED** PAE-014, PAE-025, PAE-027, and PAE-028; **ADDED** PAE-030 through
  PAE-033. No requirement is removed or renamed and no existing ID is repurposed.
- Current at the last independently reviewed historical child revision: the child Spec bound
  cross-repository behavior only through DEO-001 through
  DEO-015 and describes byte-stable schema-v3 case/summary fixtures, but does not define the exact
  completed-invocation-to-`pals.dsp-export.v1` mapping, complete case membership/order, integer and
  aggregate oracle, canonical material fingerprints, producer HMAC/key binding, payload/sidecar
  publication, or the independent parent-vector/cross-gate obligations now owned by Agent.
- Expected: after one schema-v3 invocation and its canonical summary are durably completed, Agent
  projects every case exactly once in manifest/journal order into one exact ten-key DEO envelope,
  derives all 26 case metrics and the complete summary through the integer/half-even oracle below,
  creates the five canonical material fingerprints and parent-framed producer HMAC outputs, binds
  the producer key through the exact environment policy, and publishes exact payload then detached
  sidecar bytes. Agent mapping tests alone prove canonical origin, membership, and mathematics.
- Unchanged: PAE-001 through PAE-013 and PAE-015 through PAE-029 retain their verified explanation,
  clarification, repair, security, evaluator, schema-v2, schema-v3, journal, summary, comparison,
  quality-gate, and CLI behavior. No canonical field, formula, serialized schema-v3 byte, history
  row, summary, gate, comparison, or exit code changes. Export remains post-persistence,
  noncanonical, and unable to mutate or certify those sources.
- Compatibility and data: this adds one new exchange artifact only. It introduces no history/API
  migration, schema-v2 conversion, schema-v3 rewrite, backfill, deletion, or automatic recovery.
  A mapping/key/publication failure leaves canonical bytes intact and produces no valid pair.
- Security and privacy: the artifact contains only the parent-closed DTO; raw identities, canonical
  material fingerprints, prompts, Lean, explanations, model/evaluator identity, chain digests,
  keys, key digests, paths, and credentials do not enter it or runtime logs. The detached digest is
  byte-integrity evidence only and neither it nor DTO/HMAC acceptance authenticates Agent origin or
  mathematical truth at an operator-controlled consumer boundary.
- Rollout, rollback, cost, observability, and documentation: producer implementation and tests are
  blocked on fresh child convergence; rollout also requires the parent vectors and cross-repository
  gate. Rollback disables only DSP export and preserves canonical data and key-version history. The
  producer adds no vendor/SDK request, remote-object cost, learner-facing locale/UI, or accessibility
  behavior. Operations documentation must state the exact key/publication/privacy rules without
  values or authenticity overclaim.

## Spec Update: 2026-07-14 DEO-v1 Producer Convergence Remediation

- Change category: **RESTORATION** of PAE-014 and PAE-030 through PAE-033 after the first fresh child
  convergence pass; no canonical evaluation schema, formula, gate, or CLI exit changes.
- Current: the producer eligibility text accidentally equates a completed invocation with PAE-029
  exit-0 authorization, despite the required mixed passed/failed/not-evaluated baseline. Summary
  comparison also fails to distinguish raw-decimal canonical aggregates from sums/means of individually
  half-even-mapped DTO integers. Private material JSON lacks one numeric token normal form, producer
  wording assigns torn-pair consumption and parent planned-object evidence to Agent, and task
  dependencies do not wait for parent vectors.
- Expected: producer eligibility requires the strict completed PAE-029 journal/case-set/durability
  preconditions shared by exits 0, 1, and 2, while exit 3/incomplete state remains rejected. Raw
  PAE-028 and mapped-integer summaries are independently rederived from the same cases under their own
  exact arithmetic; private material numbers have one arbitrary-precision normal form. Agent reports
  publication failure but does not consume/classify pairs, and the parent alone owns object counting
  and four-field gate evidence.
- Unchanged: Agent owns canonical source truth and producer bytes only; Observability owns consumption,
  object counting, projection, and remote reconciliation. Export remains optional/read-only and cannot
  alter history, summary, gate, comparison, or exit semantics.

## Spec Update: 2026-07-14 Direct Lean Environment Isolation Restoration

- Rationale and source: the required real-Docker PAE-017 suite currently reports 14 passing and two
  failing tests. The isolation probe proves that project-backed verification executes
  `lake env lean`, which repopulates `LEAN_PATH`, `LD_LIBRARY_PATH`, `ELAN_TOOLCHAIN`, and related
  toolchain variables after the verifier constructs its closed child environment. The timeout test
  uses `import Mathlib`, so its two-second wall can expire before the fixture creates the descendant
  it purports to test. These are implementation and test-oracle defects, not authorization to weaken,
  skip, retry, or replace real-Docker security evidence.
- Change category: **RESTORATION** and **MODIFIED** PAE-017. The existing security intent and ID are
  retained; no requirement is added, removed, renamed, or repurposed.
- Current: generated compile-time `run_tac` can observe toolchain environment that is absent from the
  verifier's current six-variable launch dictionary because Lake mutates the environment before
  invoking Lean. The timeout case can pass through a pre-descendant startup timeout and therefore
  does not deterministically prove descendant termination. The observed current suite is exactly
  14 passed and two failed; it is not a release-security pass.
- Expected: before publishing the Unix socket, the verifier resolves one immutable toolchain to
  absolute real `lake` and `lean` executables from one build-time descriptor covered by the verifier
  toolchain digest; request-time Elan is never involved. A project-backed request runs the resolved Lake binary
  only for a bounded, no-build/no-cache `setup-file` phase, validates its `ModuleSetup` JSON inside
  request scratch, and then runs the resolved Lean binary directly with that setup file. Generated
  Lean never runs through `lake env`, an Elan shim, a shell, or environment-selected toolchain. Both
  phases receive only the exact five-variable environment and complete under one serialized,
  subreaper-owned descendant-cleanup boundary. The structured setup phase has its own exact
  8,388,608-byte combined-output cap because the pinned valid fixture emits a measured 4,320,763-byte
  `ModuleSetup`; generated Lean retains the unchanged 1,048,576-byte combined-output cap. A
  deterministic timeout fixture uses the lightweight
  `Lean.Elab.Tactic` import, proves its ordinary and process-group-escaped descendants existed before
  timeout, and proves both were killed and reaped before any response or subsequent request.
- Unchanged: the worker remains toolchain-free; all Lean work remains in the dedicated Unix verifier;
  the exact valid Mathlib fixture, two-vCPU/four-GiB/64-PID/1024-nofile outer boundary, 16-GiB child
  address-space cap, 300/310-second production deadlines, Landlock, seccomp, read-only filesystems,
  network-none, zero capabilities, output/file/process limits, startup attestation, toolchain digest,
  lexical defense in depth, and no local/TCP/fake-success fallback remain mandatory.
- Compatibility, migration, rollout, rollback, recovery, observability, and cost: no API, queue,
  artifact, history, evaluation, or product-data schema changes and no data migration are introduced.
  This is an intentional internal configuration break: production verifier deployments shall remove
  `PALS_LEAN_BINARY` and `PALS_LAKE_BINARY`; a nonblank legacy value fails startup and there is no
  dual-mode or deprecation window.
  The verifier image and its implementation/tests must move together. Rollout rebuilds the image and
  requires the complete real-Docker PAE-017 matrix before worker activation. Rollback may select only
  a previously compatible image that satisfies this closed environment and cleanup contract; the
  leaking `lake env lean` revision is not an authorized rollback. Setup/toolchain/cleanup outcomes use
  fixed content-free diagnostics and counters, add no model or AWS call, and do not expose paths,
  environment values, generated Lean, or process identifiers.
  The new descriptor changes the immutable verifier-toolchain digest and therefore creates a new
  schema-v3 comparability group without rewriting or reclassifying any existing history row.

### Toolchain remediation scope and unchanged behavior

- Rationale and source: the remediation addressed eight PAE-017/PAE-027 specification defects:
  cleanup was anchored to cleanup entry instead of each phase outcome; the
  verifier-toolchain manifest was not one reproducible byte grammar; startup did not pin and
  re-attest the project root; the path rules required an unobservable outside-root hard-link fact;
  design added an unauthorized literal toolchain-root parent prefix; positive `ModuleSetup` coverage was
  incomplete; descendant cleanup lacked the setup/direct-Lean cross-product; and task 26/32 order
  and `lake env` wording were stale.
- Change category: **MODIFIED** and **RESTORATION** of PAE-017, plus a consistency
  **RESTORATION** of PAE-027's existing `verifier_toolchain_sha256` provenance. No requirement ID is
  added, removed, renamed, or repurposed.
- Current: the descriptor, manifest, root, link, cleanup-anchor, grammar-test, and dependency wording
  permits materially different implementations or a non-executable oracle.
- Expected: the contracts below define one canonical manifest byte stream and exhaustive input set;
  pin exact project/toolchain roots and re-attest them for every request; separate enforceable
  mutable-file and immutable-input rules; anchor each five-second cleanup budget at the exact setup
  or direct-Lean phase outcome; and require complete positive/rejection and phase/outcome Red
  matrices.
- Unchanged: the pinned Lake/Lean/source hashes and grammar ID, exact child environment, setup and
  Lean output caps, one untrusted-work deadline, fixed public diagnostics, outer resource boundary,
  no-local/no-TCP/no-Elan/no-`lake env` fallback, evaluation semantics, APIs, product data, rollout
  gate, and compatible-image-only rollback remain unchanged. The manifest clarification changes the
  PAE-017 digest and therefore creates a new schema-v3 comparability group; it never rewrites old
  history. No data migration is authorized.

### Source-path feasibility remediation

- Rationale: the six-source table is explicitly relative to descriptor `root/src/lean`, but its two
  Lake rows omitted the repository's `lake/` directory and therefore named nonexistent canonical
  inputs.
- Change category: **RESTORATION** of PAE-017 and PAE-027 source-path/digest consistency. No
  requirement ID is added, removed, renamed, or repurposed.
- Current: the table names `Lake/Build/Module.lean` and `Lake/CLI/Serve.lean` beneath descriptor
  `root/src/lean`, which cannot resolve the pinned Lake sources.
- Expected: the six exact `root/src/lean`-relative paths are `Lean/Setup.lean`,
  `Lean/Util/LeanOptions.lean`, `Lean/Data/Json/FromToJson/Basic.lean`,
  `Lean/Elab/Deriving/FromToJson.lean`, `lake/Lake/Build/Module.lean`, and
  `lake/Lake/CLI/Serve.lean`; their existing content SHA-256 values remain unchanged. Manifest
  records and PAE-027 `verifier_toolchain_sha256` provenance use the corrected canonical paths.
- Unchanged: grammar ID, source bytes and content hashes, executable hashes, descriptor-root
  authority, manifest framing/set rules, runtime behavior, APIs, schemas, security/privacy, cost,
  observability, migration, rollout, rollback, recovery, and implementation/test blockers remain
  unchanged. This deterministic Spec correction authorizes no code or test edit.

### Canonical verifier-toolchain manifest

The image build shall create a root-owned, no-symlink, regular mode-`0444` file exactly at
`/app/lean-verifier-toolchain.manifest`. Its complete bytes use grammar
`pals.verifier-toolchain-manifest.v1`:

```text
pals.verifier-toolchain-manifest.v1<LF>
<P>:<PATH><TAB><L><TAB><H><LF>
...
```

`P` and `L` are minimal unsigned ASCII decimal matching `0|[1-9][0-9]*`; `P` is nonzero and equals
the number of UTF-8 bytes in `PATH`, and `L` equals the exact regular-file byte length. `PATH` is
those next `P` bytes, is valid UTF-8, and is the normalized no-symlink canonical absolute image path.
`H` is exactly the 64-byte lowercase ASCII SHA-256 of the file's raw bytes. `<TAB>` is byte `0x09`,
`<LF>` is byte `0x0a`, the fixed header is exactly the ASCII characters before its `<LF>` token plus
that one LF byte, the manifest
has at least one record, and EOF follows the final record LF. Records are strictly increasing by raw
`PATH` UTF-8 bytes, with no duplicate path. No BOM, CR, blank line, padding, alternate number form,
or additional byte is permitted. `verifier_toolchain_sha256` is SHA-256 of this complete manifest
byte sequence, including the header and every LF.

The exhaustive record set is the path-union, deduplicated only by identical canonical absolute path,
of exactly:

1. `/app/lean-toolchain-resolution.json`;
2. `/app/lean-git-resolution.json`;
3. the exact canonical Git executable path recorded by `/app/lean-git-resolution.json`;
4. every no-follow regular file reached by a no-follow recursive walk rooted at the exact pinned
   project root `/app/lean-workspace`; and
5. every no-follow regular file reached by the same walk rooted at the descriptor's exact `root`.

A symlink is neither traversed nor recorded. The manifest file itself is outside both roots and is
not a record, avoiding self-reference. This exhaustive rule includes both exact descriptors and the
Git executable as ordinary records, the exact project
`lean-toolchain`, `lakefile.lean`, `lake-manifest.json`, descriptor-selected Lake/Lean binaries, all
six `root/src/lean`-relative grammar sources (with Lake entries exactly
`lake/Lake/Build/Module.lean` and `lake/Lake/CLI/Serve.lean`), every `.olean`/`.olean.private`, and
every other regular project/toolchain input that setup or direct Lean may read. The descriptor is
represented exactly once by its canonical path, raw-byte length, and raw-byte SHA-256; its raw bytes
are not separately concatenated or embedded in the manifest. The Git descriptor and executable use
the same one-record semantics. Thus "descriptor/executable bytes are covered" has only that one
meaning. Build/startup fails if the set, order, framing, size, digest, type, or path cannot be
reproduced exactly.

### Canonical runtime Git attestation

The image build shall resolve the sole runtime Git executable without a shell, reject every shim or
symlink, and create one root-owned no-symlink regular mode-`0444` file exactly at
`/app/lean-git-resolution.json`. Its complete bytes are one compact UTF-8 JSON object with keys in
exact order `schema_version`, `path`, `version`, `sha256`, followed by exactly one LF and EOF:

```json
{"schema_version":"pals.lean-git-resolution.v1","path":"<PATH>","version":"<VERSION>","sha256":"<H>"}
```

`PATH` is the normalized no-symlink canonical absolute path of one root-owned regular executable
whose mode is exactly `0755`, with no setuid, setgid, or sticky bit. `VERSION` is the exact nonempty
ASCII token after `git version `, has length 1–128, and matches
`^[0-9]+(?:\.[0-9]+){1,3}(?:[.-][0-9A-Za-z]+)*$`. `H` is the lowercase SHA-256 of that executable's
exact raw bytes. Values use unescaped printable ASCII `0x21..0x7e` excluding `"` and `\`; escapes,
unknown/duplicate/reordered keys, BOM, CR, surrounding whitespace, alternate path, or trailing byte
fail the image build and verifier startup.

The literal five-entry child environment gives Lake the exact
`PATH=/usr/local/bin:/usr/bin:/bin`. At image build and again before HTTP readiness publication, the verifier
shall implement POSIX executable search for the literal basename `git` over those three components
in that order without a shell. It shall inspect every candidate, require the first executable
candidate's normalized no-symlink canonical path and `st_dev`/`st_ino` to equal the descriptor path
and retained FD, and require every later executable candidate to be absent or resolve to that same
retained inode. A prior shadow, distinct later executable, non-regular candidate, inaccessible or
ambiguous component, mutable candidate directory, or search/result mismatch fails closed. This is
the sole permitted basename resolution used by pinned Lake's offline package-origin metadata path;
no alias, shim, request field, inherited environment, or alternate executable may win it.

Before HTTP readiness publication the verifier no-follow opens and retains the Git executable FD, requires
the descriptor path/metadata/length/hash and manifest records to match that FD, and invokes only that
absolute executable with the single argument `--version` under the exact five-variable child
environment. Success is exit zero, stderr exactly empty, and stdout exactly ASCII
`git version <VERSION><LF>` matching the descriptor; every other byte or status is startup failure.
At every request admission and immediately before setup and direct Lean, the verifier repeats the
closed `PATH` candidate search, no-follow reopens the descriptor path and Git path, compares canonical
path plus `st_dev`/`st_ino` with the retained FDs, then `fstat`s and rehashes the retained Git FD. No
unchecked `PATH` lookup, alias, request field, environment value, mutable package metadata, or later
executable may satisfy Git metadata access. Both descriptor bytes and executable bytes therefore contribute to
`verifier_toolchain_sha256`; changing path, version, content, metadata, or version output creates a
different comparability digest and never rewrites an existing record.

### Startup descriptor and pinned roots

The only project root is the literal canonical path `/app/lean-workspace`. A missing
`PALS_LEAN_PROJECT_DIR` uses that fixed path; when present, the variable is accepted only when its
value is exactly `/app/lean-workspace` and never selects another root.
Before publishing HTTP readiness, the verifier shall:

1. open `/app/lean-toolchain-resolution.json` no-follow and require the exact root-owned regular
   mode-`0444`, at-most-4,096-byte identity and canonical five-key bytes defined below;
2. open `/app/lean-git-resolution.json` and its exact Git executable no-follow, require the closed
   descriptor, executable metadata/content, exact five-entry-`PATH` basename-resolution oracle, and
   exact version-output oracle above, and retain both FDs plus startup `st_dev`/`st_ino`;
3. open `/app/lean-workspace` no-follow as a directory, require its canonical path to equal that
   literal and its mount to be read-only, and retain its FD plus startup `st_dev`/`st_ino`;
4. open the descriptor's exact canonical `root` no-follow as a directory, require it to be immutable
   and read-only, and retain its FD plus startup `st_dev`/`st_ino`; the descriptor value is the sole
   toolchain-root authority and no literal parent prefix is required or permitted;
5. open the manifest no-follow, verify its exact grammar/digest/set, verify both descriptor records
   and the Git executable record against retained FDs, and verify every root-member record against a
   no-follow file opened relative to the appropriate pinned root FD; and
6. open the project `lean-toolchain` relative to the pinned project-root FD and require its exact 28
   bytes `leanprover/lean4:v4.32.0-rc1` with no final LF, then require exact equality with descriptor
   `toolchain`.

At admission of every request before any request-specific preflight, and again immediately before
every setup and direct-Lean launch, the verifier shall repeat the closed five-entry-`PATH` candidate
search, no-follow re-open each absolute root path and the Git descriptor/executable paths, compare
canonical path and `st_dev`/`st_ino` with every retained FD, `fstat` the retained FDs again, rehash
Git, and fail closed on any mismatch or ambiguity. Thus even
a request rejected before child launch has root/Git-attestation results. Project working-directory
and containment operations use the retained project-root FD; toolchain containment uses the retained
descriptor-root FD. No request field, current directory, environment variable, symlink, mount/path
replacement, or alias may select or replace either root or Git executable.

### Pinned `ModuleSetup` evidence and closed acceptance grammar

PAE-017 uses grammar ID `pals.lake-module-setup.external.b4812ae.v1`. It is valid only for project
token `leanprover/lean4:v4.32.0-rc1`, Lake
`5.0.0-src+b4812ae`, and Lean `4.32.0-rc1` commit
`b4812ae53eea93439ad5dce5a5c26591c31cb697`. The pinned executable SHA-256 values are
`8229bc302b0b7d0e7679e28cc2b830c5aec995ffe5714833503360252f1490ba` for `lake` and
`79fb1d26fa5a39385d59fdc48a711a14b0710ca6480271acce99b4d177cea085` for `lean`. The
following public source bytes define the grammar and Lake's external-file projection. Every table
path is relative to the descriptor root's exact `src/lean/` directory; the executables are exactly
the descriptor's `bin/lake` and `bin/lean`. Image build shall compare every digest and include every
listed source and executable as canonical path/byte-length/digest records in the manifest:

| Pinned source | SHA-256 |
|---|---|
| `Lean/Setup.lean` | `7f085003e696df5c29af1dc1342ef3dfaaca70b6eaa5d357ce832abd49e9554c` |
| `Lean/Util/LeanOptions.lean` | `801fdd22788045c918d75bb4a2af201b3f0d50ce31a35749081491d8819001eb` |
| `Lean/Data/Json/FromToJson/Basic.lean` | `d98f160b7f300cedb0248cf1afcd90ec6dba97255ed1562a67cc33bad64c3a03` |
| `Lean/Elab/Deriving/FromToJson.lean` | `f77b755cef1930a76ac51a631467de28e23e6c183a8657d349cbb13a9206a0ca` |
| `lake/Lake/Build/Module.lean` | `186a211523ea5e503af2811921adc47b5df3120eeadd8dbe719e2ba628c80169` |
| `lake/Lake/CLI/Serve.lean` | `013ee743584ca9d0f19ce886aa795cdb93f59e3c389965667626d09912e0d600` |

Any token, version, commit, executable digest, source digest, or accepted JSON shape change requires
a new grammar ID and approved Spec update; it is a startup failure under this grammar. The local
evidence image was
`pals-local-lean-verifier@sha256:05d56357e0717e72f21de39c956505738d73a42919043e4b36e90a8c44d7c6f8`;
that image digest identifies the measurement only and does not authorize the current failing
implementation for release.

For this grammar, successful setup means all of the following, with no coercion or extension:

- Process exit is exactly zero. Captured stderr is exactly zero bytes. Any stderr byte on exit zero,
  or any nonzero/signal exit regardless of its streams, is fixed `lean.setup_file_failed` and makes
  zero Lean calls.
- Captured stdout is valid UTF-8 consisting of exactly one JSON object followed by exactly one LF.
  It has no BOM, no whitespace outside JSON strings, no duplicate key at any object depth, and no
  leading or trailing byte or second JSON value. Setup stdout plus stderr is counted byte-for-byte,
  including the LF, against one combined 8,388,608-byte cap; equality may pass after complete
  validation, and receipt of byte 8,388,609 terminates the phase and fails. There is no independent
  stream allowance that can raise the combined cap.
- The top object has exactly six required keys, with order semantically irrelevant:
  `dynlibs`, `importArts`, `isModule`, `name`, `options`, and `plugins`. `name` is the string
  `_unknown`; `isModule` is a JSON boolean; `dynlibs` is an array of path strings; `importArts` is an
  object whose unique data keys use the pinned `NameMap.fromJson?` string rule: exactly
  `[anonymous]`, or a string for which pinned `String.toName` is non-anonymous. Its values are
  `ImportArtifacts`; `options` is an object whose unique data keys use that same Name rule and whose
  values are exactly JSON string, boolean, or a canonical nonnegative decimal token matching
  `0|[1-9][0-9]*`, the pinned Lake `ToJson Nat` form accepted by `Json.getNat?`; `plugins` is an
  array of objects with exactly one required key `path`, a path
  string. Empty arrays and maps are valid. Top-level `package`/`imports`, plugin string shorthand,
  plugin `initFn`, null, and every other key or value type are rejected even though the broader Lean
  public decoder can accept some of them.
- Each `ImportArtifacts` value is an array of exactly one, three, or four path strings. Their pinned
  positions are `[olean]`, `[olean, ir, oleanServer]`, or
  `[olean, ir, oleanServer, oleanPrivate]`; every other length or element type is rejected.
  The path-bearing fields are therefore exactly every `dynlibs[]`, every `importArts.*[]`, and every
  `plugins[].path`. Each shall byte-equal one canonical absolute `PATH` in the verified toolchain
  manifest, be opened no-follow relative to the matching pinned project/toolchain root FD, remain a
  strict descendant of that root, name a regular file, and match that record's exact `L` and `H`
  before direct Lean launches. No relative, unlisted, nonexistent, device, directory, socket, FIFO,
  symlink, changed-root, changed-size, changed-digest, or changed-file target is accepted. Read-only
  manifest-listed inputs do not require `st_nlink == 1`: an unobserved hard-link alias elsewhere is
  neither discoverable nor an escape grant, because only the listed in-root path opened from the
  pinned root FD is authorized; an alias path is rejected unless it independently satisfies that
  same listed-path contract.

Generated mutable request state follows a separate enforceable rule. `R/Main.lean` and
`R/ModuleSetup.json`, and every future mutable regular request file authorized by a new grammar, shall
be created no-follow with `O_CREAT|O_EXCL`, shall be a regular file beneath the retained mode-`0700`
request-root FD, and shall have `st_nlink == 1` from creation through its final use and unlink. A
collision, replacement, additional link, non-regular inode, path escape, or unverifiable observation
fails the request. `R/ModuleSetup.json` is never linked from stdout or another path; it is a fresh
mode-`0400` file containing the exact validated bytes.

The positive conformance suite shall accept every row below using only manifest-listed valid paths;
rows are cumulative coverage obligations, not alternate grammars:

| Positive row | Required accepted shape |
|---|---|
| `P1-empty-false` | `isModule=false`; empty `dynlibs`, `importArts`, `options`, and `plugins` |
| `P2-anonymous-one` | `isModule=true`; `[anonymous]` keys; one-element `[olean]`; string options including `""` and a nonempty value; one `dynlibs` path; one exact `{path}` plugin |
| `P3-named-three` | `isModule=false`; a non-anonymous dotted Name; three-element `[olean,ir,oleanServer]`; option values `false`, `0`, and a positive canonical Nat; multiple dynlibs/plugins |
| `P4-mixed-four` | `isModule=true`; anonymous and named keys together; four-element `[olean,ir,oleanServer,oleanPrivate]`; option values `true`, `1`, and another multi-digit canonical positive Nat |
| `P5-key-order` | every one of the `6!` top-level key permutations plus forward/reverse orders of at least two `importArts` and two `options` data keys; all decode to the same accepted semantics while the original validated bytes are preserved |

The rejection suite shall independently mutate every category below and prove zero direct-Lean
launches:

| Rejection family | Required rejected variants |
|---|---|
| framing | invalid UTF-8, BOM, CR, absent/extra LF, out-of-string whitespace, leading/trailing byte, and second JSON value |
| object keys | missing/extra/duplicate key at top, `importArts`, `options`, or plugin depth; wrong top container; wrong `name`; non-boolean `isModule` |
| names/options | an invalid Name key; a string other than exact `[anonymous]` that decodes anonymous; null, array, object, negative, fraction, exponent, leading-zero, signed, or whitespace-padded option numbers |
| artifacts/plugins | artifact lengths `0`, `2`, `5`, wrong element type, plugin string shorthand, missing/extra plugin key, non-string path, and `initFn` |
| paths/files | every path-bearing field as relative, unlisted, nonexistent, symlink, non-regular, wrong-root, changed-root/inode, wrong-size, wrong-digest, replaced-after-validation, or request-file link-count violation |

The real pinned `PalsX2Verified.lean` measurement exited zero with stdout exactly 4,320,763 bytes,
SHA-256 `f60caa318a75a8886d50e9c13e574c47ba7d4e2b8108b7946eaf8c74ab818ad3`, and empty
stderr SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
It had the six keys above, 8,586 `importArts` entries, every artifact array length four, and empty
`dynlibs`, `plugins`, and `options`. The lightweight exact source `import Lean.Elab.Tactic\n`
produced the following 92 stdout bytes, including its final LF, SHA-256
`aa437ed53b7cd68fecaa91252549dd39538fc7b16f5ff0d85645d4c14c7c0740`, and the same
empty-stderr digest:

```json
{"dynlibs":[],"importArts":{},"isModule":false,"name":"_unknown","options":{},"plugins":[]}
```

The pinned direct Lean command accepted those exact 92 bytes with
`--setup=/tmp/pals-evidence/ModuleSetup.json --threads=1 /tmp/pals-evidence/Main.lean`, exit zero,
and zero stdout/stderr bytes under the same five evidence variables.

These are deterministic real-Docker oracles for the pinned grammar, not alternate setup results or
fake compiler success.

### Exact child environment and phase-specific oracles

For each request, let `N` be exactly 32 lowercase hexadecimal characters encoding 16 bytes read once
from the OS CSPRNG, let `R` be the canonical mode-`0700` directory `/tmp/pals-lean-<N>` created with
exclusive no-follow semantics, and let `R/home` be a newly created canonical mode-`0700` directory.
The source path is exactly `R/Main.lean` and the validated setup path is exactly
`R/ModuleSetup.json`. Setup and Lean receive this exact five-entry map and no sixth entry:

| Key | Exact value |
|---|---|
| `PATH` | `/usr/local/bin:/usr/bin:/bin` |
| `HOME` | `/tmp/pals-lean-<N>/home` |
| `TMPDIR` | `/tmp/pals-lean-<N>` |
| `LANG` | `C.UTF-8` |
| `LC_ALL` | `C.UTF-8` |

PAE-017 requires two independent executable observations. First, a real-Docker setup-phase ELF
probe shall be invoked through the production phase launcher and shall inspect its own OS-provided
`envp`; it exits successfully only for the exact five-entry map above and emits only the pinned
92-byte setup stdout with zero stderr. This probe is an environment oracle only: it cannot satisfy
the separate real pinned-Lake setup, direct-Lean compile, or release-security acceptance. Second, a
real direct-Lean `run_tac` fixture shall inspect the environment visible to compile-time Lean IO and
verify successfully only for the same exact map. Both oracles independently mutate every missing,
additional, wrong-key, wrong-value, `HOME`/`TMPDIR` cross-request, and canary case; both must pass in
addition to the real Lake/Lean transaction.

### Phase-outcome-anchored descendant cleanup

Every launched setup phase and every launched direct-Lean phase owns its own cleanup deadline.
`phase_outcome_at` is captured exactly once from the transaction's monotonic clock at the first
parent-side observation that irrevocably classifies that phase: complete successful result; nonzero
or signal failure; untrusted-work timeout; receipt of the first combined-output byte over the phase
cap; accepted cancellation; or an exception caught at the launcher/collector transaction boundary.
The exact cleanup deadline is `phase_outcome_at + 5 seconds`. It is never based on cleanup-function
entry, first signal, first wait, response serialization, or a later retry, and it never resets.

The phase launcher shall enter cleanup even when classification itself found no live leader. Any
scheduler, handoff, lock, logging, signal, or other delay between `phase_outcome_at` and cleanup entry
consumes the same five-second budget. Descendant absence completing exactly at the deadline may pass;
observing the first monotonic instant after it fails closed with no response and verifier termination.
After successful setup cleanup only, the transaction may re-attest roots and launch direct Lean with
the remaining untrusted-work duration. After direct-Lean cleanup, or after any unsuccessful setup
cleanup, no phase follows.

The required Red matrix is the Cartesian product of phases `{setup,direct_lean}` and outcomes
`{normal,failure,timeout,overflow,cancel,exception}`. Every cell creates and pre-observes both an
ordinary descendant and a descendant that escapes to a distinct process group/session, verifies the
cell's exact `phase_outcome_at`, and proves both descendants and all adopted children absent before
response or next-phase/request reuse. A fake-clock delay-before-entry oracle for every cell advances
time after `phase_outcome_at` but before the first cleanup operation: a completion at exactly
`phase_outcome_at + 5 seconds` passes, while entry or completion at the first later instant sends no
response and terminates service. Missing pre-observation is a failed oracle, not cleanup success.

## Current, Expected, and Unchanged Behavior

### Current

- The explanation, clarification, canonical evaluator, and JSONL history flows exist with the
  PAE-004/011/012/015/016 fail-open paths and the PAE-017 missing trust boundary recorded above.
- The ignored local history `.pals-agent-artifacts/evaluations/history.jsonl` has five schema-v2
  records and exact SHA-256
  `b32d19c0a6f66b5140c37d161d83bf291a1fa969a82b5e59d5bcdc07c43879fa`; its fifth record contains
  four non-null semantic comments and therefore fails the strict reader without mutating the file.
- Proof-job generation remains claimless, API-wire diagnostic/context projection is not closed, and
  the evaluator has neither a strict schema registry nor a versioned live suite/summary runner.
- Runtime benchmark/method/sketch checks can leak evaluation-only expectations into repair prompts,
  and the five heterogeneous v2 rows cannot establish state accuracy.
- Before the parent DEO contract, the optional observability parser had no parent-owned schema-v3
  case/summary compatibility contract and could not be cited as v3 exportability evidence.
- The child Spec currently lacks the exact Agent producer contract required by the now-ready parent
  DEO-001 through DEO-020; prior case/summary fixtures are not the required one-envelope baseline.
- PAE-017 real-Docker evidence is 14 passed and two failed: `lake env lean` reintroduces toolchain
  variables into generated `run_tac`, and the Mathlib-based two-second timeout fixture does not prove
  that its target descendant started before timeout.
- The current release worker accepts proof-job IDs without the parent PRX-002 version attributes,
  body digest, manifest queue identity, and receipt metadata gate. The current PAE-017 transport is
  Unix-socket-only, so it cannot satisfy the approved PRX-003 mTLS HTTP verifier boundary.

### Expected

- Verification gates explanation generation, and all learner-facing claims cite exact Lean lines.
- Evaluation produces one result for every canonical state and appends it to durable history.
- Repeated suites expose numeric stage pass rates and metric averages without rewriting prior runs.
- Duplicate proof work is fenced by API PJR-012–PJR-014, while PRX-004 exclusively governs release
  stop/drain/resume participation; clarification bytes/targets fail closed,
  history v2/v3 records are strictly validated, and smoke/full/compare report complete evidence
  without treating output presence or missing usage/cost/judge data as accuracy or zero.
- Isolated Lean verification after safety and formal-theorem identity checks is proof authority;
  sketch adherence is post-runtime evaluation only. Live evaluation gates bind all current manifest
  cases and one exact provenance key to the invocation that produced them.
- The strict DEO-001 through DEO-020 producer contract can create one complete-invocation exchange
  batch and detached digest without changing local truth, live gate status, comparison, or CLI exit
  semantics; consumer projection remains separately owned by `pals-observability`.
- PAE-017 resolves and pins the direct Lake/Lean executables before serving, converts the generated
  header to validated `ModuleSetup` with bounded `lake setup-file --no-build --no-cache`, executes
  direct Lean with no toolchain environment, uses one exhaustive canonical toolchain manifest,
  re-attests pinned project/toolchain roots before each phase, applies enforceable mutable/read-only
  file rules, and proves outcome-anchored descendant cleanup across every setup/direct-Lean outcome.
  That compiler engine is hosted only by the parent-imported private mTLS HTTP service; the API-owned
  verified reconciler is the sole caller and the credentialed DSP worker consumes only authoritative
  API state.
- Every proof receipt passes the exact parent v1 queue/body/attribute/hash/identity gate before any
  API, model, or verifier-related action. Valid redelivery is resolved by the API claim; invalid or
  ambiguous work is retained for the parent/Infra redrive contract and never converted to success.

### Unchanged

- Draft, sketch, prove, repair, and Lean verification remain the proof-generation workflow.
- Non-release deterministic adapters remain valid only for Red/Green tests; release provider/model
  selection is replaced by the code-owned PAE-034 registry and has no environment override.
- Prompts and model output remain internal trace material, but hidden reasoning is never requested,
  persisted, or returned to users.
- The exact three original benchmark prompts remain the initial smoke profile; deterministic stage
  facts and the explicit semantic evaluator identity remain separate evidence families.
- Existing schema-v2 and schema-v3 parsers, records, summary JSON/Markdown, explanation and
  clarification payloads, worker/API contracts, locale, and release authorization remain unchanged.
- All PAE-017 outer-container, resource, filesystem, network, provenance-role, untrusted-work/client
  deadline, and no-fallback contracts remain unchanged except that the service network and client
  deadline are now the imported PRX-003 private mTLS HTTP/300-second server and API-owned
  310-second reconciler boundary. The compiler child itself remains networkless. The manifest byte
  grammar, covered set, pinned-root/file validation, cleanup anchor, and their oracles remain closed;
  the resulting verifier-toolchain digest separates comparability without changing prior records.

## Functional Requirements

## PRX T-047 PAE-033 Amendment

`SPEC-CHG-2026-07-27-PAE-PRX-T047-CHILD-SYNC` is a behavior-preserving SDD-024 parent-workflow
identity synchronization. It amends only PAE-033's current parent-import triple and current
authority-relocation order: PAE-035 through PAE-038 import PRX-001 through PRX-009 and AC-001
through AC-009 from the T-046-reviewed requirements/design/tasks SHA-256 triple
`2814ff312e4b4dac941c3cfcf74f54b7aaf3da7b818ac688083d0f577a951e59` /
`d2aa7f3d061879fdd01c8a26c897d9bc91c44a8750a5884965862950ec46ee05` /
`95b0430e195d572e970367854bf12b4467a6cf032f953f318a1147a085ec91d9`.
Task 83 records that historical synchronization; Task 84 then records the current external report
identity, and the current gate is
`Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64`.
The superseded tuple and predecessor chain in the historical PAE-033 record below have no current
authority. No PAE runtime behavior, acceptance criterion, ownership, implementation, test, or
external system changes.

| ID | Requirement | Priority | Source |
|---|---|---|---|
| PAE-001 | Explanation generation shall reject any proof whose Lean verification did not succeed. | Must | User request |
| PAE-002 | A completed explanation shall contain a concise overview, ordered sections, and a conclusion in Japanese; every section shall contain 1–20 exact 1-based Lean line references and excerpts. The parser shall require 1–20 sections, overview/conclusion of 1–600 code points, section title of 1–80, section summary of 1–800, and at least one Hiragana, Katakana, or CJK Unified Ideograph in every overview/title/summary/conclusion after trimming. | Must | User request |
| PAE-003 | Explanation parsing shall validate reference ranges and exact excerpts against the verified Lean source. Malformed model output may be regenerated with a bounded real-model retry, but shall end as an explicit failure rather than placeholder content. | Must | User request |
| PAE-004 | Clarification generation shall require an explicit successful-verification gate for the same immutable Lean proof before any prompt/model call. A clarification shall answer a non-empty learner question for one existing explanation section and shall cite 1–20 Lean line references including at least one line referenced by that section. Its Japanese answer shall be 40–4,000 code points, contain at least one Hiragana, Katakana, or CJK Unified Ideograph, contain 2–10 nonblank key points of at most 500 code points each, and after Unicode-whitespace normalization shall differ from and be longer than the selected concise section summary. | Must | User request |
| PAE-005 | Explanation and clarification prompts shall state that the theorem statement and verified Lean are the only sources of truth and shall request user-facing rationale, not hidden chain-of-thought. | Must | Privacy requirement |
| PAE-006 | Public explanation and clarification payloads shall contain only typed learner-facing content, model/provider identifiers, and elapsed time; raw prompts, raw output, hidden reasoning, and worker diagnostics shall not cross the public boundary. | Must | User request |
| PAE-007 | The evaluator shall emit the canonical ordered stages `retrieval`, `draft`, `sketch`, `prove`, `repair`, `end_to_end`, and `explanation` for every run. | Must | User request |
| PAE-008 | Every stage shall have exactly one status `passed`, `failed`, or `not_evaluated`; every metric shall separately have exactly one status `evaluated` or `not_evaluated`. Missing prerequisite evidence or unavailable judges shall produce `not_evaluated`, never a default success or fabricated value. Once the deterministic oracle's prerequisite is satisfied, a missing output that the suite explicitly requires shall be an evaluated false/count-zero metric and a failed stage. | Must | User request |
| PAE-009 | Deterministic metrics shall include ranked retrieval candidate/score evidence, non-empty draft/sketch/prove outputs, the post-runtime generated-sketch/final-Lean structural-adherence metric below, first-candidate isolated Lean compile success, final isolated Lean compile success, paired compile uplift, repair attempts/error reduction/convergence, final verification, and verified-flow explanation/clarification presence, exact reference validity, chain digests, and coverage. Sketch adherence is a sketch-stage metric only, is computed only after the terminal runtime result, and shall never change proof verification, create a diagnostic, enter a generation-scope prompt, trigger repair, or establish terminal provenance. Once proof verification is true, missing required explanation or requested clarification evidence shall fail rather than disappear from the evaluated denominator. | Must | User request |
| PAE-010 | Optional semantic judges shall return only bounded numeric dimension scores and closed judge metadata; free-text comments/rationales shall neither be requested nor persisted. Judge transport, parsing, or configuration failure shall leave semantic metrics `not_evaluated` while preserving deterministic results. Every semantic metric shall carry the exact PAE-019 evaluator/rubric provenance source. For the release/live PAE-002/PAE-004/PAE-034 quality gate, the explanation judge is mandatory and the gate fails when it is unavailable or does not pass the closed rubric below; this release gate never changes deterministic stage status. Only the exact executable command, result, and private evidence oracle defined under `lean-explanation-ja-v1 live release oracle` may satisfy that gate; a unit fixture, schema-v3 draft/sketch judge row, prior artifact, skipped test, cached generation response, or hand-entered score cannot. | Must | User request |
| PAE-011 | Each evaluation run shall record a schema version, immutable run ID, case ID, suite revision, timestamp, model metadata, and all stage results in an append-only local history. Append and explicit torn-tail recovery shall use the fail-closed lock/fence protocol below; no marker creation failure, recovery race, or ambiguous durability outcome may authorize an append. | Must | User request |
| PAE-012 | History summaries shall calculate per-stage evaluated count, pass rate, and numeric metric averages from persisted runs, excluding every `not_evaluated` metric and without mutating history. Schema-v3 summary/compare shall accept only one exact comparability key; heterogeneous keys are returned as separate groups by history listing and are rejected by single-run summary/compare. Schema-v2 rows are labeled `legacy_structural`, grouped by their exact available suite/model metadata, and shall never be titled, gated, or reported as draft/sketch state accuracy or complete-suite accuracy. | Must | User request |
| PAE-013 | Evaluation suites shall keep generation inputs independent from expected outputs and shall use Spec-derived or independently reviewed fixtures as post-runtime evaluator oracles. The generation-scope channel includes `openmath`, `draft` relevance and ordinary Draft, `sketch`, `prove`, `route`, `repair`, `explain`, and `clarify` calls and shall never receive a benchmark expected strategy or method requirement, hidden harness, expected relevance label, rubric, or sentinel. An explicit proof-method instruction in the user's theorem request is generation input, not evaluation evidence. In addition, only an exact OpenMath-equivalent runtime retrieval of catalog Draft `continuous_square` selects its declared ε–δ method; that narrowly scoped retrieved method reaches Draft/Sketch/Prove and the PAE-016 preflight without becoming a theorem target or harness. Approximate, reranked, or other retrieved contexts remain advisory and cannot synthesize a method requirement. Runtime structural/LLM relevance may receive only the actual query and fetched catalog rows, never benchmark labels. The separately configured evaluator-scope channel may receive evaluation-only values only after all generation-scope calls for the case terminate; it is one-way and cannot mutate runtime artifacts, retrieval selection, diagnostics, repair routing, verification, or terminal state. Tests capture and assert both channels independently. | Must | User decision; `SPEC-CHG-2026-07-31-PAE-EXACT-X2-EPSILON-DELTA` |
| PAE-014 | DSP observability export shall be only the explicit Agent operation `pals-agent evaluation-export-dsp-v1 --invocation-id <UUIDv4> --output-directory <absolute-existing-private-directory>` after canonical persistence and completed-invocation validation. It shall accept no case/summary/filename/schema/provider override; select exactly the strict persisted invocation; conform to parent DEO-001 through DEO-020; and implement the exact target naming, create-only publication, replay, result, and error contract below. `pals-agent` owns canonical case/summary truth, PAE-030 mapping, PAE-031 fingerprints/key binding, PAE-032 publication, and PAE-033 baseline/conformance evidence. It owns no consumer parser, projection HMAC, vendor projection, SDK, remote mapping, helper, receipt, outcome, or read-back behavior. Export incompatibility, absence, conflict, or failure shall never mutate, certify, or determine history, summary, journal, quality gate, comparison, evaluation CLI exit, proof/evaluation completion, or schema-v2 behavior. | Must | User request; DEO-001–DEO-020 |
| PAE-015 | Under the exact approved EXP identity pinned by `SPEC-CHG-2026-07-27-PAE-UPSTREAM-AUTHORITY-IMPORTS` deadline/lifecycle import and exact approved API PEX composition, Agent worker tasks shall generate one explanation after a proof reaches `verified` and process typed clarification queue messages through API PEX-009, PEX-012, and PEX-017–PEX-019. A PAE-020-valid verified proof ends its proof claim but retains that proof receipt as the durable trigger until the separate proof-ID-keyed explanation is terminal; no second message or proof-claim reuse exists. Each eligible receive creates one fresh explanation/clarification UUIDv4 claim, never reuses a prior/expired claim, and sends its generating request once; an ambiguous outcome performs no model call and only a later receive with a fresh claim may retry after expiry. Immediately before sending that request the worker captures `claim_request_started_at` on its monotonic clock. The request declares `required_lease_ms = (3 * model_timeout_seconds + 30) * 1000`, where `model_timeout_seconds` is `PALS_EXPLANATION_MODEL_TIMEOUT_SECONDS` (default 90, integer range 1–300) and is the upper bound for each of the explainer's at most three model attempts. Only an exact typed `acquired` envelope whose resource kind, identity, state, fields, and nonnegative integer `lease_remaining_ms` match the requested target may proceed to visibility extension and the final monotonic lease check below; only an exact typed terminal explanation/clarification resource for that target may acknowledge without a local terminal write. Before model work, the worker extends receipt visibility to `ceil(required_lease_ms / 1000) + 30` seconds. `busy`, `lease_too_short`, `not_ready`, malformed/ambiguous/transport/configuration response, visibility failure, or final lease insufficiency performs zero model calls and does not acknowledge. Every dynamic proof/clarification API path ID shall first match `^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$` and then be percent-encoded as one path segment; rejected or mismatched IDs cause no request, model call, unrelated update, or acknowledgement. If a current-claim completed write receives exactly `proof_explanation_reference_mismatch` or `proof_clarification_reference_mismatch`, the worker performs zero further model calls and attempts exactly one content-free `failed` write using the same claim and a fixed private-safe diagnostic; it acknowledges only an exact same-target terminal failed resource, otherwise leaves the receipt. The monotonic hard-deadline and acknowledgement rules below apply; terminal writes carry the current claim. | Must | Exact approved EXP identity pinned by `SPEC-CHG-2026-07-27-PAE-UPSTREAM-AUTHORITY-IMPORTS`; API PEX-009, PEX-012, PEX-017–PEX-019, PEX-024, PEX-027 |
| PAE-016 | After each actual repairable runtime failure, including an empty generated candidate, the pipeline shall pass the latest candidate plus only generation/transport, safety, explicitly supplied formal-theorem identity, selected proof-method diagnostics, isolated-verifier, and Lean compiler diagnostics to the `route` role, which selects only `draft`, `sketch`, or `prove` under the exact three-attempt selector contract. A valid route triggers exactly one `repair` role call; its typed output re-enters the selected PAE-034 node and executes every downstream generation node through Prove before the new candidate is verified. Route success alone never creates a candidate or terminal state, and no heuristic/configured-model fallback exists. Exact-Draft retrieval identity/equivalence and generated-theorem binding to an explicitly supplied formal statement remain deterministic compile-blocking preflight and resist comment/string/syntax-quotation spoofing. Expected Draft proof-strategy fragments, benchmark ID/prompt registries, hidden benchmark formal harnesses, evaluation rubrics/relevance labels, and sketch/scaffold text adherence shall not create runtime diagnostics, enter repair prompts, trigger repair, change verification, or choose a terminal reason. The selected method is either an explicit learner request or, only for an exact OpenMath-equivalent `continuous_square` retrieval, that Draft's ε–δ method. For either ε–δ source, preflight shall inspect executable Lean only (comments and strings do not count), require `Metric.continuous_iff`, an introduced `ε`, and an explicit `δ` choice, and reject continuity shortcut lemmas or the `continuity` tactic with `pals.proof_method_mismatch` before the verifier is called. That diagnostic is repairable. Once this preflight and safety/formal-theorem identity preflight pass, isolated Lean verification success is proof correctness authority; a semantically equivalent/rephrased sketch mismatch may be recorded only by post-runtime PAE-009 evaluation and the proof remains `verified`. Candidate-level safety/formal-identity, selected-method, or Lean failures are repairable; only an explicit verifier/tool/generator configuration diagnostic is non-repairable. `PALS_MAX_REPAIR_ATTEMPTS` shall default to 12 and accept only a base-10 integer in `[1,64]`; missing uses 12 and empty, signed, decimal, exponent, whitespace-padded, zero, negative, or above-64 values fail startup before any model/verifier call. One failed repair or a repeated diagnostic fingerprint alone shall not terminate the run. A fingerprint shall be the exact diagnostic code plus its Unicode-casefolded message with every whitespace run normalized to one space; a stagnation warning shall be added only when at least one error fingerprint is present in each of the latest three consecutive failed candidates. The run shall terminate only on successful isolated verification, exhausted budget, an explicitly diagnosed non-repairable verifier/generator configuration failure, explicit repair-route selection failure, or a checkpoint-store failure. Before selecting the next route, every attempted candidate shall be durably checkpointed in order with phase, diagnostics, verification result, and selected route evidence. A checkpoint failure shall replace any candidate-level compile success with a failed top-level/final-attempt verification containing fixed `pals.artifact_checkpoint_failed`; it shall serialize/emit only `failed` with `termination_reason=artifact_store_failure`, never `verified`. The terminal artifact shall include ordered attempts, `repairs_used`, exactly one closed `termination_reason`, and the matching structured `termination_event`; no free-form or evaluation-only diagnostic shall establish terminal provenance. | Must | User decision; `SPEC-CHG-2026-07-31-PAE-EXACT-X2-EPSILON-DELTA` |
| PAE-017 | Every untrusted Lean invocation, including final candidate compiles, explicitly supplied formal-statement identity checks that invoke Lean, suite compile evidence, generated headers processed for project setup, and compile-time `run_tac`/IO, shall execute outside the credentialed worker in the dedicated Agent-owned verifier service imported by PAE-036. The worker image contains no Lean/Lake toolchain, verifier transport credential, or local verifier client and never instantiates or simulates a compiler. Inside the service, the existing exact `/app/lean-toolchain-resolution.json`, `/app/lean-git-resolution.json`, `pals.verifier-toolchain-manifest.v1`, pinned project/toolchain/Git FDs, six exact `root/src/lean` source path/hash pairs, `setup-file --no-build --no-cache` then direct Lean `--setup --threads=1`, five-variable child environment, mutable/read-only file rules, resource limits, one 300-second untrusted-work deadline, outcome-anchored five-second descendant cleanup, and no-Elan/no-`lake env`/no-shell/no-fallback contracts below remain mandatory. The service task may use only the imported PRX-003 private mTLS network and startup/rotation Secrets endpoint; every setup/Lean child remains networkless and receives no service, worker, cloud, database, model, or secret variable. Startup, per-request admission, and pre-phase attestation failure prevents readiness or compiler launch. Request-specific setup/compiler failure maps only to the imported parent HTTP failure outcome; cleanup uncertainty emits no success/error body, closes the connection, and terminates service. Lexical rejection remains defense in depth and is never verification evidence. | Must | Security review; PRX-003/AC-003; real-Docker restoration |
| PAE-018 | Ordinary evaluation-history load shall remain strict and non-mutating when a persisted record violates its declared schema. The only authorized repair for legacy schema-v2 non-null semantic metric comments is an explicit CLI migration selected by closed ID `semantic-comments-v2` and pinned to the caller-supplied full lowercase SHA-256 of the exact source snapshot. Under the history migration contract below it shall preserve an immutable digest-named byte-exact backup, set only offending semantic `comment` values to null, validate every transformed record against the current schema-v2 reader, atomically replace and directory-fsync the history, and emit only an audit summary. It shall never delete, skip, silently coerce during load, overwrite a backup, or migrate any other malformed field/schema. | Must | Real-data regression |
| PAE-019 | Under the exact approved EXP identity pinned by `SPEC-CHG-2026-07-27-PAE-UPSTREAM-AUTHORITY-IMPORTS` quality/evaluator import, Agent semantic judging shall use only the exact five-variable state `(PALS_SEMANTIC_EVALUATOR_PROVIDER,PALS_SEMANTIC_EVALUATOR_MODEL,PALS_SEMANTIC_EVALUATOR_REVISION,PALS_SEMANTIC_EVALUATOR_BASE_URL,PALS_SEMANTIC_EVALUATOR_API_KEY)` below. The evaluator's exact private identity is `(provider,model,revision,normalized_origin)`; its persisted public identity remains `(provider,model,revision,source)` and never exposes origin. Provider is exactly lowercase `openai` or `ollama`; model/revision each match ASCII `^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$`. HTTP is permitted only for exact loopback and every other origin requires HTTPS; redirect, proxy, cross-origin credential forwarding, generation-credential reuse, and same-call/cached/batched generation-response reuse are forbidden. After all generation scope has terminated and before each evaluator request, normalized evaluator `(provider,model)` shall differ from every non-null contributing generation `(provider,model)`. Each semantic result requires one new evaluator-only transport request with its own request lifecycle and dedicated credential; it cannot be derived from a generation response, request ID, tool result, cache entry, or combined provider call. Partial/invalid five-variable state, forbidden transport/credential state, unresolved contributor, identity equality, or missing distinct-call evidence fails before scoring. Explicitly requested semantic enrichment in the all-absent state performs zero judge requests and adds `not_evaluated` metrics. Configured source is exactly `semantic_judge:<provider>/<encoded-model>@<encoded-revision>:<rubric_revision>` under the encoding below; unconfigured source is exactly `semantic_judge:unconfigured:<rubric_revision>`. Endpoint, origin, credential, request identity, prompt/output, and error text are never persisted. | Must | Exact approved EXP identity pinned by `SPEC-CHG-2026-07-27-PAE-UPSTREAM-AUTHORITY-IMPORTS`; evaluation-integrity review |
| PAE-020 | Only the PAE-036 isolated verifier service shall produce `pals.verifier-attestation.v1`, and only after actual PAE-017 compilation succeeds and complete descendant cleanup is proven. Its values bind the imported parent request's exact proof-job ID, exact artifact URI, and lowercase SHA-256 of the exact Lean UTF-8 bytes; the exact parent schema and field registry are imported, not restated by this child. The DSP worker and its API client shall reject and omit every caller-, model-, fixture-, cache-, or worker-derived attestation and shall never submit a `verified` update that claims local compiler success. After API-owned reconciliation, terminal worker-resource handling shall strict-validate the exact persisted parent attestation before acknowledgement or Explain. Missing, additional, mismatched, wrongly typed, blank, or false evidence is ambiguous, performs no later model call or receipt deletion, and is never replaced by a fabricated or legacy payload. | Must | PRX-003/AC-003; API reconciliation boundary |
| PAE-021 | For each PAE-035-valid nonterminal proof delivery the worker shall create one fresh UUIDv4 and acquire API PJR-012 before pipeline/model work, declaring `required_lease_ms=3_600_000`. Acquisition accepts only the exact same-target union `acquired|busy|terminal`; `lease_too_short` is not a PJR response and its appearance is malformed. Only `acquired` permits receipt visibility extension and pipeline entry. Before and between every initial generation call, route-selection attempt, repair-generation call, candidate submission, and authoritative verifier-result refetch, with no two operations overlapping, the worker shall run the exact renewal/visibility/deadline sequence below. The worker shall not call PAE-036 or hold its client trust. Renewal accepts only exact same-target `renewed|terminal`. `renewed` alone grants the next spend; exact terminal response stops proof control before another spend/update and acknowledges failed/canceled. Exact verified ends the proof claim after PAE-020 validation but retains the same receipt while explanation proceeds only through its distinct PEX claim; only a same-target terminal `completed|failed` explanation permits acknowledgement. Malformed/forbidden/ambiguous/transport/control outcomes, including any `lease_too_short`, start zero later calls and do not acknowledge. Renewal and visibility each have a 30-second hard wall and may start only when the prior local lease deadline leaves that wall plus the exact 30-second stop margin. The renewal duration is anchored before its request; after visibility success, spend may start only when ownership is at least its hard wall plus 30 seconds, equality passing. The smaller lease-derived deadline is passed to a killable transport/client; every helper/process/descendant is canceled, killed, reaped, and joined by `lease_deadline-30`, and a live call at return is claim loss. Therefore distinct takeover cannot overlap earlier model/API work. Every status update carries the claim and validates PJR-013. The worker consumes compile success/failure only from an authoritative same-target API resource produced after the API-owned reconciler uses PAE-036; parent `verifier_compile_failed` becomes the sole release Route/Repair compiler diagnostic across that boundary. After accepted verified, the worker refetches the exact resource, requires same IDs/state, nonblank Lean/artifact, and matching attestation, and explains only persisted theorem/Lean under a separate explanation claim. | Must | P0 duplicate-worker/lease review; PRX-003; API PJR-012–PJR-014 |
| PAE-022 | Agent proof-job diagnostics sent to the API shall contain exactly `severity`, `message`, `code`, `line`, and `column`; local `metadata` is never serialized. API status context shall use schema `pals.proof-status-context.v1` and the closed projection below. It may retain full generated draft text, sketch Lean, final Lean, ordered typed diagnostics, verification booleans/elapsed time, candidate number/phase/checkpoint status, selected route, closed selector-attempt evidence, repair counts, and closed termination evidence. It shall omit every prompt, raw model/provider/selector output, route rationale, stdout/stderr, endpoint, credential, exception object/text, and arbitrary diagnostic metadata. Model/provider/route/transport/configuration failure diagnostics use fixed reviewed code/message pairs; raw failures remain private local artifact material only. | Must | P1 schema/privacy review |
| PAE-023 | Worker clarification handling shall first validate the complete exact worker-input schema and require its `id` to equal the requested clarification ID before terminal-state acknowledgement, claim request, proof lookup, model call, update, or receipt deletion. Cross-target, missing/additional/wrong-typed, or malformed terminal resources are ambiguous and unacknowledged. Nonblank theorem and Lean validation may inspect `.strip()` only as a predicate but shall return and compare the original strings byte-for-byte, including trailing newline; no worker helper may trim the Lean or theorem value passed to proof cross-check, reference parsing, or the model. | Must | P1 clarification-integrity review |
| PAE-024 | Every semantic pass boundary, including the `lean-explanation-ja-v1` mean threshold, shall use exact finite numeric `>=` comparison with no `math.isclose`, epsilon, rounding, string formatting, or tolerance. Therefore `math.nextafter(0.80,0.0)` fails and exact `0.80` passes when all dimension minima also pass. | Must | P1 threshold review |
| PAE-025 | Evaluation-history parsing shall dispatch by declared supported schema version and reject unknown fields at run, invocation, provenance, retrieval-evidence, explanation-chain, stage, metric, candidate, and nested evidence levels; duplicate/unknown metric names, wrong metric kind/source/status/value types, arbitrary semantic provenance, and metrics not authorized for that stage/version are invalid. It shall recompute deterministic stage status and paired compile/sketch metrics rather than trust serialized status; sketch adherence never affects prove/end-to-end verification. The schema-v2 registry remains available for the migrated five-record history as `legacy_structural` only. Schema-v3 records use the closed registry and exact comparability key below; history listing groups heterogeneous records, while summary/compare refuses to combine them. No version guesses, field dropping, status trust, schema coercion, or legacy accuracy claim is allowed. PAE remains the canonical producer/parser authority; the only cross-repository projection is the separate PAE-030 through PAE-033 mapping governed by parent DEO-001 through DEO-020. | Must | P1 history/state-integrity review; DEO-001–DEO-020 |
| PAE-026 | The packaged evaluation suite shall have immutable ID `pals.dsp-evaluation`, revision `smoke-v1`, exact manifest/case digests, and profiles `smoke|full`. In this initial revision both profiles contain exactly, in order, `continuous_square` / `x^2が連続であることを示せ`, `rank_nullity` / `rank A = n - Ker Aを示せ`, and `compact_image` / `cpt集合の連続写像による像はcpt集合であることを示せ`. The immutable manifest below defines independently reviewed relevant Draft IDs, top-k, isolated compile oracle, evaluation-only strategy reference, and exact stage-specific draft/sketch rubrics. The runner passes only a fresh `BenchmarkProblem(id,prompt)` into the generation-scope pipeline. Expected IDs, strategy, hidden harness, rubric, and evaluator sentinel are forbidden from generation-scope requests/prompts but are required in separately captured evaluator-scope prompts after runtime. Any suite content change requires a new revision and digests. | Must | Core evaluation-gap/state audit |
| PAE-027 | Every schema-v3 case record shall include exact live invocation binding/origin; suite/run/case identity and immutable digests; the closed run-comparability object and digest below binding the code-owned PAE-034 eight-role generation registry/revision, evaluator/rubric, price revision, repair budget, agent source, and verifier toolchain; runtime-input SHA-256; creation/completion times; all canonical stages; closed ranked retrieval evidence against independently reviewed relevant IDs; prompt-channel separation evidence; explanation-chain digests; and exact origin evidence. `verifier_toolchain_sha256` shall be the exact PAE-017 manifest digest including the Git resolution descriptor, Git executable bytes, and version attestation. Every `model_calls` row shall satisfy exact scope/role/provider/model and per-scope cardinality binding; release-origin rows require all eight roles to use `openai/gpt-5.4-mini-2026-03-17`. Before an evaluator row/call, normalized evaluator identity shall differ from every non-null contributing generation identity and distinct evaluator-request evidence shall pass PAE-019. Any registry, cross-field, normalized-identity, request-separation, or Git/toolchain mismatch invalidates the complete record. It shall record draft/sketch semantic quality under distinct rubrics; post-runtime sketch adherence separately from proof truth; paired first/final isolated compile, repair uplift/rounds/convergence; latency; complete generation/evaluator/overall token usage; estimated cost only from complete usage/pricing; and actual cost only when typed for every applicable call. Missing candidates, evaluator, usage, pricing, cost, prompt-channel proof, toolchain, call-separation, or chain evidence is null/`not_evaluated`, never passing/zero/partial. Non-empty output is structural only. Cross-repository use shall occur only through PAE-030 through PAE-033 under parent DEO-001 through DEO-020; the canonical record itself is never a DEO DTO. | Must | Core evaluation-gap/state audit; DEO-001–DEO-020 |
| PAE-028 | A schema-v3 summary shall first require one exact comparability key and report it, including `max_repair_attempts`. It reports hit@k, stage-specific draft/sketch semantic evaluated/pass counts/rates, sketch-adherence counts without proof veto, paired first/final compile counts/rates and compile-uplift categories, repair-round histogram/convergence, nearest-rank p50/p95 latency, complete token totals, estimated/actual cost, and explanation-chain completeness, each with evaluated/missing counts and excluding all `not_evaluated` values. With zero evaluated values an aggregate is null/not-evaluated; with some missing it is partial. Its JSON form shall use the exact canonical `pals.evaluation-summary.v1` producer envelope and aggregate unions below; Markdown is never a canonical machine source. Quality can pass only when every required family is evaluated and applicable booleans pass; any evaluated false fails, otherwise missing is not-evaluated. Release authorization additionally requires origin `live`, exact current invocation binding, and all current manifest cases exactly once; synthetic math fixtures can prove formulas but can never authorize a live gate or CLI exit 0. Cross-repository use shall occur only through the separate PAE-030 DEO summary mapping under parent DEO-001 through DEO-020; the canonical summary schema and mathematics remain unchanged. | Must | Core evaluation-gap/state audit; DEO-001–DEO-020 |
| PAE-029 | `pals-agent evaluation-run --profile smoke|full` shall create a fresh UUIDv4 `run_id` and `invocation_id`, atomically reserve a durable invocation journal bound to the exact manifest/provenance key, execute every current manifest case once, append one fsynced schema-v3 `origin=live` record per completed case, and derive deterministic atomic+fsync JSON/Markdown only from strict re-read records for that invocation. A completed case means the pipeline returned a typed terminal result and its case record durably appended. Existing IDs, duplicate pairs, stale/foreign records, provenance drift, durability failure, or uncaught operational error returns exit 3 without overwrite; missing cases/running interruption also exits 3; SIGINT/SIGTERM retain 130/143 with auditable state. For a completed live invocation, direct child exit 0 means authorized pass, 1 evaluated failure, and 2 required evidence not-evaluated. Synthetic inputs are pure-helper only and cannot produce exit 0. The sole comparison invocation is `pals-agent evaluation-compare --baseline-run <UUIDv4> --candidate-run <UUIDv4>` with each option once and no other argument; it strict-reads without mutation. Parent smoke/full/compare GNU Make targets invoke the exact child commands directly: child exit 0 yields Make exit 0, while every child nonzero value, signal, missing/blank required compare variable, or recipe failure yields Make exit 2. Make never propagates child 1/2/3/37 as its own exit and never changes the direct child CLI contract or evidence. | Must | Core evaluation-gap/state audit |
| PAE-030 | From exactly one strict, durably completed schema-v3 invocation and its canonical PAE-028 summary, including completed PAE-029 exits 0, 1, or 2 but never exit 3/incomplete state, Agent shall create exactly one immutable `pals.dsp-export.v1` ten-key envelope satisfying the exact parent DTO grammar. It shall include every invocation case exactly once in journal `expected_case_ids` order with ordinals `0..case_count-1`, one summary with the same fingerprint order, all seven stage statuses, and the 26 metrics and aggregate oracle below. It shall not select, filter, pass-only select, omit, reorder, duplicate, combine, shard, or import a foreign case. Canonical-to-DTO metric status, integer bounds, half-even millionths/USD-micros conversion, rates, totals, nearest-rank percentiles, stage counts, and histogram values are Agent-owned truth and shall fail closed before publication when the source cannot map exactly. | Must | DEO-002–DEO-006, DEO-013, DEO-016 |
| PAE-031 | Agent shall derive the five exact child-owned canonical material fingerprints below using the exact arbitrary-precision material-number normal form, then apply the parent DEO-008 producer identity/comparability HMAC-SHA-256 framing with mandatory `contract_revision="deo-v1"` and exact producer key version. Normal provisioning/rotation obtains exactly 32 key bytes only from the OS CSPRNG. `.local` shall use the single shared absolute DEO-019 registry/inode for both repositories and purposes; `.dev` and `.prod` shall use only their fixed full producer secret ARN plus exact immutable AWS `VersionId`, with no name, partial ARN, alias, stage, mutable selector, host registry, cache fallback, or alternate secret. Same-version/different-key binding, malformed key/version, malformed `PALS_DSP_PRODUCER_FINGERPRINT_KEY`, or registry/secret ambiguity shall fail before artifact publication without logging key bytes or digests. | Must | DEO-008, DEO-014, DEO-019 |
| PAE-032 | Agent shall serialize the exact envelope as one nonempty UTF-8 JSON object followed by exactly one LF, no BOM or trailing byte, and at most 64 MiB, and its detached SHA-256 sidecar as exactly 64 lowercase hexadecimal characters plus LF. The deterministic names and replay rules are PAE-014's exact contract. First publication of each absent target shall be create-only and atomic in the same directory with file and directory fsync, payload first then sidecar; no existing target is overwritten. An exact existing pair equal to the newly derived bytes is only an idempotent `already_published` result when both are effective-UID-owned mode-`0600` regular single-link files, not consumer acceptance. Missing-one, unequal, malformed, wrong-owner, wrong-mode, multi-link, symlink, or non-regular existing targets are `publication_conflict` and remain unchanged. The pair is not atomic: failure reports publication failure and leaves exact committed state without inferring consumer validity, repairing, deleting, or relabeling it. Pair acceptance belongs only to the DEO-003 consumer. Export failure never alters canonical data. DTO, result, logs, and documentation obey the privacy rules and never claim that digest, shape, HMAC, fixture, replay, or downstream acceptance authenticates Agent origin or mathematical truth. | Must | DEO-003, DEO-012, DEO-016, DEO-020 |
| PAE-033 | Agent shall hand-implement the parent DEO DTO grammar/projector without sharing a parent/Observability runtime validator. PAE-035 through PAE-038 import PRX-001 through PRX-009 and AC-001 through AC-009 only from the approved parent requirements/design/tasks triple `c8f585e26d664f5e6cf3b1d56cb917f17bbac7a5192cddc421ee0b6b8b40b3e2` / `5b90d8afbcb2f5446d84150e22d18d2c8b1dc8748ba44192dece41c8dbdd5a51` / `4e01c8a80e1f7921e2f488a887bfcf09004c0b82601a6c2168c6585d26e63a82`; they shall not redefine, alias, extend, or reinterpret it. The current whole-child authority gate is exactly Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64 -> PRX T011. Task 83 is historical PRX provenance only; Task 84 alone records the exact then-current DEO requirements/design/tasks triple covered by the external fresh Task-48 report and this PRX triple. Task 73 validates only the Task-84-recorded report identity, imports current approved PFI/EXP/PJR/PWA/API PEX authority, obtains fresh independent all-zero technical/non-authoritative draft review, performs the authorized status-only promotion and ownership PASS, and publishes its sole inverse-proved marker. Task 64 independently revalidates the same Task-84 report identity and promoted imports before its sole inverse-proved marker. The report remains external under SDD-024 and supplies no implementation/test authority. Historical reports/markers and pre-Task-84 identities cannot satisfy this gate. PRX T-011 remains blocked until current DEO Task 48 and renewed PAE Task 64 complete; all pending implementation/test work remains blocked until Task 64's marker. | Must | PFI-001–PFI-004; EXP-001–EXP-007; DEO-013, DEO-015, DEO-020; DEO-R44-001; DEO-R50-001; SDD-024; PLS-012; PRX-001–PRX-009; PJR-012–PJR-014; PEX-001–PEX-027; AC-001–AC-009 |
| PAE-034 | Under the exact approved PFI-001–PFI-004 retrieval import, the current Agent release runtime shall implement the exact natural-statement, OpenMath, PostgreSQL/pgvector retrieval, Draft, Sketch, Prove, asynchronous isolated-verification, bounded Route/Repair, Explain, and section-Clarify contract below. Candidate Lean/artifact values are submitted under the API claim; the API-owned verified reconciler alone sends its locked stored values to PAE-036, and the worker consumes only the authoritative persisted outcome. Its code-owned role registry shall contain exactly `openmath`, `draft`, `sketch`, `prove`, `route`, `repair`, `explain`, and `clarify`, each pinned to provider `openai` and model `gpt-5.4-mini-2026-03-17`; release environment/configuration shall not override, alias, default, or fall back from either value. The sole live release gate shall prove the complete real path, including actual pgvector retrieval, every role, at least two parent-bound `verifier_compile_failed` repair cycles followed by a durable verified artifact carrying the PAE-036-produced attestation, explanation, and clarification; fixture, mock, recorded, synthetic, lexical, exact-match, benchmark, canned, template, local ad-hoc, direct verifier call, worker-synthesized attestation, or fabricated success is forbidden. | Must | Exact approved PFI-001–PFI-004; user decision; PRX-003 |
| PAE-035 | The proof worker shall consume only the exact parent-imported `pals.proof-job-dispatch.v1` queue contract. Before any API, model, artifact, or verifier-related action it shall validate the manifest-bound queue ARN/URL identity, raw UTF-8 proof-job-ID body grammar, exact parent message-attribute set and values, exact body SHA-256, nonblank SQS `MessageId`, and nonblank current `ReceiptHandle`. It owns initial visibility, PAE-021 extensions, one-receipt-at-a-time processing, delete/retain ambiguity, redelivery, and poison retention under the exact lifecycle below. Invalid/versionless/wrong-queue/malformed work performs zero downstream calls, is never deleted or visibility-shortened, and reaches the parent-bound DLQ only through Infra redrive. A valid redelivery creates a fresh API claim and never infers order, uniqueness, or success from SQS. | Must | PRX-001, PRX-002; AC-002 |
| PAE-036 | The Agent-owned verifier shall expose only the exact parent-imported isolated-verifier HTTP readiness/request/response/failure contract on private DNS port 18117 over TLS 1.3 mutual authentication. It shall validate request transport, release/deployment-binding headers, parent DTO bytes, image/toolchain binding, and readiness before compiler work; run exactly the PAE-017 compiler engine under its one-slot semaphore and 300-second compile/cleanup wall; and produce only the imported readiness, attestation, or error response with exact status, framing, and response binding. Readiness is true only after toolchain/image/deployment/trust/capacity attestation. The API-owned verified reconciler is the sole application caller. The server has no DB, SQS, model, worker, release-signing, barrier, provider-mutation, or application-data capability and no plaintext, Unix-socket, sidecar, local, fixture, cached, or status-only success path. | Must | PRX-001, PRX-003, PRX-005; AC-003, AC-005 |
| PAE-037 | Agent release integration shall start proof receipt blocked, participate in parent PRX-004 stop/drain/resume order without defining a new shared control DTO, fail closed unless the admitted worker image and exact v1 queue binding match, and never let an old/unversioned worker resume or bypass Infra-owned explicit SQS denial. It shall publish only Agent-owned worker/verifier images, the PAE-017 toolchain manifest/digest, and the closed Agent behavior-property artifact below as Agent-owned inputs to PRX-006 release provenance; it shall consume but not create or mutate mTLS secrets through exact full-ARN plus immutable-VersionId ports. The repository-local commands, README/SECURITY content, content-free telemetry, rollout, rollback, and recovery evidence below are mandatory. Agent owns no provider/ECS/SQS quiescence observation, durable cross-repository cutover/effect sink, release archive/signature/admission persistence, API PostgreSQL, or Infra resource behavior. | Must | PRX-001, PRX-004–PRX-008; AC-001, AC-004–AC-008 |
| PAE-038 | The Agent worker shall consume clarification deliveries only through the exact imported PRX-009 `pals.proof-clarification-dispatch.v1` boundary on the admitted proof queue. Before any API/model/update action it shall validate the shared receive response shape, queue binding, nonblank `MessageId`/current `ReceiptHandle`, canonical empty application-attribute projection, separate system attributes, and byte-exact 68-byte body/UUID routing exactly in the parent order; it shall then fetch the same-target API worker input and require exact `dispatch_schema_version="pals.proof-clarification-dispatch.v1"`. Invalid/poison/wrong-marker/not-ready/busy/ambiguous work performs zero model/update/delete and retains the receipt. An exact same-target terminal `completed|failed|dispatch_uncertain` input permits deletion of only that receipt without generation claim/model/update; otherwise each eligible redelivery creates one fresh PAE-015 API claim, extends visibility before model work, and deletes only after a known durable same-target completed/failed response. Delete ambiguity retains the receipt. Agent never defines another codec/marker/state meaning, queries delivery success, requests resend, uses PRX-002 proof attributes/redrive, or supplies API/Infra behavior. | Must | PRX-009; AC-009 |

## Release Runtime, Retrieval, and Role Registry

### OpenMath structuring

The release entry accepts one nonblank natural-language mathematical statement. Before retrieval or
Draft, the `openmath` role produces an OpenMath 2.0 proposition. One structuring transaction permits
at most three real model calls total: attempt 1 receives only the statement and closed structuring
contract; attempts 2 and 3 additionally receive only the prior candidate plus exact bounded
parse/canonicalization/validation diagnostics. The first candidate that passes all three phases wins.

Parsing shall accept only the supported OpenMath XML profile. Canonicalization alpha-renames bound
variables by deterministic binder order and normalizes every symbol to its exact supported
`(cdbase,cd,name)` identity before canonical serialization. Validation requires a closed,
well-scoped proposition with known symbol construction roles/arities and no placeholder. A malformed
third result or any call/configuration/transport failure emits only typed
`pals.openmath_structuring_failed`, persists no substitute expression, and performs zero retrieval,
Draft/Sketch/Prove/Route/Repair, verifier, Explain, Clarify, or verified-status calls. Natural-text
token matching, regex/lexical parsing, exact catalog lookup, benchmark registry, canned OpenMath,
mock/template expression, or last-known-good value is never a structuring fallback.

### PostgreSQL/pgvector retrieval

The sole release retrieval authority is the configured PostgreSQL catalog with the `pgvector`
extension. Packaged files may seed that catalog but are never queried, unioned, or substituted at
request time. A minimal Draft record contains only a stable `draft_id`, human theorem statement,
canonical OpenMath proposition, semantic embedding plus immutable embedding fingerprint, proof
strategy, and ordered Sketch steps. Runtime authority excludes status labels, aliases, benchmark
expectations, exact-match indexes, Lean targets, quality counters, and mock records.

The query embeds the validated canonical OpenMath under the catalog's exact embedding fingerprint
and always issues one pgvector cosine nearest-neighbor request with `LIMIT 8`, no score predicate,
and stable `draft_id` tie-breaking. It returns exactly `min(8, eligible_catalog_rows)` rows; the live
release catalog must contain at least eight eligible rows and the gate must observe eight. The
pipeline computes structural evidence from the alpha-renamed, symbol-normalized OpenMath trees, then
uses a separate real `draft`-role relevance subcall to rerank the eight rows and select an ordered,
unique context list of zero through four rows. The LLM may reject all eight. No hard cosine/final
score cutoff, exact-equivalence shortcut, lexical fallback, union with packaged seeds, threshold,
or benchmark label may add, remove, preselect, or auto-accept a context.

A PostgreSQL/pgvector, embedding-fingerprint, embedding, structural, or reranker failure is explicit
and does not fall back to local/in-memory/exact/lexical retrieval. A successful rerank with zero
contexts is ordinary success: the pipeline still invokes the ordinary `draft` generation call with
the natural statement, canonical OpenMath, and an empty context list. It never constructs or verifies
an `ad_hoc` candidate outside that Draft call, and zero context never authorizes verified state.
The smoke-v1 `retrieval_top_k=5` field remains only an evaluation hit-at-k cutoff over the returned
runtime ordering; it cannot change the fixed release fetch limit 8 or rerank output limit 4.

### Bounded proof graph

The only release graph order is:

```text
natural statement
  -> openmath structure/parse/canonicalize/validate
  -> PostgreSQL/pgvector top 8
  -> structural + draft-role LLM relevance rerank to 0..4
  -> ordinary Draft LLM
  -> Sketch LLM
  -> Prove LLM
  -> isolated PAE-017 Lean verification
  -> on failure: Route LLM -> Repair LLM -> selected re-entry
  -> on verified durable artifact: Explain LLM
  -> learner selects one explanation section: Clarify LLM
```

`route` returns only `draft`, `sketch`, or `prove` under PAE-016's exact three-attempt selector
contract. A valid route causes exactly one `repair` call with the latest candidate, actual allowed
diagnostics, and selected route. Its typed repaired input re-enters the selected node and then runs
every downstream node in order: `draft` runs Draft -> Sketch -> Prove, `sketch` runs Sketch -> Prove,
and `prove` runs Prove. Every resulting candidate receives the same preflight, checkpoint, and
isolated verification contract. One repair cycle is one valid Route decision, one Repair call, the
selected forward path, checkpoint, and verification. The PAE-016 generation budget remains 12 by
default and `[1,64]` when explicitly configured; selector retries do not consume it. No route,
repair, Draft, Sketch, or Prove output can set verified state without successful PAE-017 verification
and durable artifact checkpointing.

Explain begins only from the authoritative durable verified artifact and exact Lean/theorem bytes.
Clarify begins only after a learner selects one existing explanation section and uses that same
artifact under PAE-004. A failed/absent artifact cannot produce either call. There is no graph edge
from retrieval, context absence, model self-report, fixture, template, benchmark oracle, local Lean,
or evaluation score directly to verified, Explain, or Clarify.

### Code-owned release role registry

The immutable registry revision is `pals.release-role-registry.v1` and its complete ordered entries
are:

| Role | Provider | Model |
|---|---|---|
| `openmath` | `openai` | `gpt-5.4-mini-2026-03-17` |
| `draft` | `openai` | `gpt-5.4-mini-2026-03-17` |
| `sketch` | `openai` | `gpt-5.4-mini-2026-03-17` |
| `prove` | `openai` | `gpt-5.4-mini-2026-03-17` |
| `route` | `openai` | `gpt-5.4-mini-2026-03-17` |
| `repair` | `openai` | `gpt-5.4-mini-2026-03-17` |
| `explain` | `openai` | `gpt-5.4-mini-2026-03-17` |
| `clarify` | `openai` | `gpt-5.4-mini-2026-03-17` |

Release environment/configuration may provide only the OpenAI endpoint, API credential, and bounded
transport controls. It may not provide a provider, model, alias, deployment-to-model mapping,
role-specific model, fallback model, or local provider. A nonblank `PALS_LLM_PROVIDER`,
`PALS_OPENAI_MODEL`, `OPENAI_MODEL`, `OLLAMA_DRAFT_MODEL`, `OLLAMA_PROVE_MODEL`, or any role-specific
provider/model override fails release preflight before retrieval/model/verifier work. Missing endpoint
or credential, registry mutation, unknown/duplicate/missing/reordered role, provider/model mismatch in
an actual response, fallback attempt, or provider failover also fails closed. Non-release fixtures
may inject adapters only for deterministic Red/Green tests and can never satisfy release evidence.

The schema-v3 generation-role names are exactly the registry names above. `explain` and `clarify`
replace the former provenance-only labels `explanation` and `clarification`; no alias is accepted.
Every release-origin comparability object binds the exact registry revision and all eight non-null
`openai/gpt-5.4-mini-2026-03-17` entries. The semantic evaluator is outside this registry and remains governed
only by PAE-019.

## Proof Claim and Status Projection Contract

PAE-021 uses the exact API PJR-012/PJR-013 claim, renewal, update, and worker-input contracts. The
shared extra-forbid worker resource has exactly `id`, `job_id`, `project_id`, `theorem_statement`,
`formal_statement`, `state`, `request_context`, `status_context`, `diagnostics`,
`result_artifact_uri`, `lean_code`, and `verifier_attestation`; `id=job_id` equals the requested path
ID and every nested shape/invariant is the PJR worker-resource contract. The authoritative refetch
is exactly `GET /v1/internal/proof-jobs/{encoded_id}/worker-input`. The worker rejects missing or
additional keys, aliases, public-resource fields, request echoes, wrong identity/state, or invalid
verified binding before the response affects control flow.

Claim acquisition is `POST .../generation-claims` and renewal is
`POST .../generation-claims/renewals`; both bodies are exactly
`{claim_id,required_lease_ms}` with the delivery UUIDv4 and `required_lease_ms=3600000`. Acquisition
is exactly `{claim_status,lease_remaining_ms,resource}` with `claim_status=acquired|busy|terminal`;
`acquired|busy` require integer remaining lease and a nonterminal persisted resource, while
`terminal` requires null remaining lease and an exact persisted terminal resource. Renewal is
exactly one of `{renewal_status:"renewed",lease_remaining_ms:<integer>,resource:<nonterminal>}` or
`{renewal_status:"terminal",lease_remaining_ms:null,resource:<terminal>}`. `renewed` exists only for
the current strictly unexpired claim and resets expiry to authoritative PostgreSQL time plus
3,600,000ms; terminal-state precedence occurs before claim comparison and grants no permission.
Stale/expired/reused nonterminal claims use the PJR 409 family without mutation. `lease_too_short`,
another status, a wrong nullability/state/identity, or an extra/missing field is a malformed PJR
response, never a control branch. Claim/update/renewal resources are persisted projections, never
request echoes.

For acquisition and every renewal, the worker samples `request_started_at` immediately before HTTP
and computes `lease_deadline=request_started_at+lease_remaining_ms/1000`; response latency only
subtracts ownership. Claim/renewal/status/refetch HTTP and SQS visibility operations each use a
30-second total monotonic hard wall. Before a renewal starts, the prior local deadline must satisfy
`prior_lease_deadline-(renewal_started_at+30) >= 30`; if it does not, the worker starts no renewal or
later spend. A renewal response is not usable until its complete exact body is parsed; timeout,
commit ambiguity, malformed response, or late response loses permission even if the API may have
committed.

Immediately before every individual initial-generation call, each of the up to three selector
calls, each routed repair-generation call, each candidate/artifact submission to the API, and each
authoritative verifier-result refetch from the API, the worker performs a fresh
renewal, then extends SQS visibility to `ceil(lease_remaining_ms/1000)+30`, then samples
`call_started_at`. Let `call_timeout_seconds` be that adapter's finite configured total hard wall
(`1..300` for each model/selector call and 30 seconds for each API submission/refetch). The spend
call starts only when
`lease_deadline-(call_started_at+call_timeout_seconds) >= 30`; equality passes. Its actual deadline
is `min(call_started_at+call_timeout_seconds, lease_deadline-30)`. The transport/client must own a
killable helper/process group and cannot return until every helper, socket, child, and descendant is
closed, canceled, killed where necessary, reaped, and joined. A deadline-unaware or background-only
adapter is a startup error. No renewal or spend call overlaps another, and the next call requires a
new renewal. Claimed status writes complete under their own 30-second hard wall before another spend
begins.

Therefore at the earliest distinct-claim takeover instant the prior worker has had no active
model or API submission/refetch spend for at least 30 seconds. Any renewal, visibility, margin, cancellation,
join/reap, or response-validation failure aborts pipeline control flow and retains the receipt. A
well-formed terminal acquisition or renewal starts no spend or status update. Terminal
`failed|canceled` deletes the proof receipt. Terminal `verified` ends proof control only after the
exact same-target resource independently satisfies PAE-020, but retains the same receipt as the
durable trigger while explanation starts only through the separate explanation claim path and never
under the ended proof claim. Exact same-target explanation `completed|failed` then permits receipt
deletion; busy, ambiguity, crash, and every nonterminal explanation outcome retain it. Every other
terminal-looking response is malformed and retains the receipt. Claim UUIDs never enter
prompts, diagnostics, context, artifacts, history, logs, traces, metrics, or public content.

The PAE-022 worker `context` update is an extra-forbid object with required exact
`schema_version="pals.proof-status-context.v1"` and `stage`, plus only optional `problem_id`,
`draft_id`, `retrieval`, `attempt_evidence`, `repair_route`, `selector_attempts`, `repairs_used`,
`max_repair_attempts`, `termination_reason`, `termination_event`, and
`verification_elapsed_ms`. `retrieval` contains only candidate/related draft IDs, strict
equivalence, and finite vector/structural/final scores. `selector_attempts` is the closed PAE-016
array. `termination_reason/event` use the closed PAE-016 enums/shapes. Counts/timing are bounded
nonnegative integers. Missing optional evidence is omitted, not synthesized.

`attempt_evidence` is exactly `{attempt,phase,generated,verification,diagnostics,
checkpoint_status,repair_route}`. `repair_route` is null for attempt 1 or exactly
`{route,selector_attempts}`; it contains no rationale. `generated` is exactly
`{lean_code,model,provider,elapsed_ms,draft,sketch,stage_diagnostics}`. Optional `draft` is exactly
`{text,model,provider,elapsed_ms}`; optional `sketch` is exactly
`{lean_code,has_gaps,model,provider,elapsed_ms}`. `verification` is exactly
`{success,diagnostics,elapsed_ms}` and excludes stdout/stderr. Every diagnostic in all three lists
uses the five-field API shape. Thus aggregate artifact and
private checkpoint retain full internal attempt material, while status retains all generated code,
typed diagnostics, phase/checkpoint, and route evidence needed by PAE-016 without raw prompt/output.
Every diagnostic serializes all five keys; `code`, `line`, and `column` are JSON null when absent.

The fixed sensitive diagnostic projection is:

| Local code family | API code | Exact API message |
|---|---|---|
| `openai.error`, `ollama.error`, `llm.generation_failed`, `pals.repair_generator_unavailable` | original code | `Proof generation failed.` |
| `llm.empty`, `pals.generation_empty` | original code | `Proof generation returned no usable Lean code.` |
| `pals.repair_route_invalid_response`, `pals.repair_route_transport_error`, `pals.repair_route_selection_failed` | original code | `Repair route selection failed.` |
| `pals.openmath_structuring_failed` | original code | `The theorem statement could not be structured.` |
| `pals.artifact_checkpoint_failed`, `pals.artifact_persistence_failed` | original code | `Proof artifact persistence failed.` |

All other verifier/preflight diagnostics preserve their typed bounded message. A diagnostic with a
missing/unknown code that originated from a caught model/provider/transport exception is projected
to code `llm.generation_failed` and its fixed message; exception text is never used as an API
message.

For PAE-016, an explicit route-selection failure exists only after exactly three unsuccessful real
selector calls for one failed candidate. Invalid/malformed output receives a corrective strict-JSON
prompt on each remaining call; a typed transport failure retries without changing provider/model.
The first valid `draft`, `sketch`, or `prove` decision ends selector retry and must be attached to the
next generated candidate before that candidate is preflighted, Lean-verified when eligible, and
checkpointed. Route selection success alone is never terminal. Selector exhaustion records the
three ordered attempt outputs plus `selector_attempts` evidence, emits no fabricated route, performs
no repair generation, and terminates as
`repair_route_selection_failed`.

`selector_attempts` is an ordered array of one to three exact objects with keys `attempt`, `outcome`,
`diagnostic_code`, and `route`. `attempt` is consecutive from 1; `outcome` is exactly `selected`,
`invalid_response`, or `transport_error`; `diagnostic_code` is respectively null,
`pals.repair_route_invalid_response`, or `pals.repair_route_transport_error`; and `route` is the
selected closed route only for `selected`, otherwise null. No free-text exception, endpoint,
credential, prompt, or output enters this closed evidence array. Raw selector outputs remain only in
the existing internal attempt material.

Every PAE-016 candidate record in the aggregate artifact and its corresponding immutable checkpoint
shall contain the same full generated Lean code, exact ordered diagnostics/verification, phase, and
inbound route decision when one exists. After that checkpoint publishes, the next callback event for
that candidate is `repairing` when route selection is attempted and otherwise the terminal
`verified`/`failed` event; its context key `attempt_evidence` shall equal the aggregate/checkpoint
attempt object field-for-field. A successful-selection `repairing` event additionally records the
outbound `repair_route` and exact `selector_attempts`. Raw model prompts/outputs remain internal and
retain all existing privacy exclusions.

For PAE-002/PAE-004, a Japanese code point is exactly one in Unicode ranges Hiragana
`U+3040–U+309F`, Katakana `U+30A0–U+30FF`, or CJK Unified Ideographs `U+4E00–U+9FFF`.
Lengths count Unicode code points after trimming leading/trailing Unicode `White_Space=Yes`; the
stored text itself is not normalized. Structural validation is deterministic and precedes exact
Lean-reference validation.

## Deterministic Evaluation Oracle

This section is normative for PAE-007–PAE-012 and PAE-016. Every run emits all seven stages in the
listed order. Each deterministic metric has `kind="deterministic"`, a fixed source path, status
`evaluated` exactly when its value is non-null, and otherwise value null/status `not_evaluated`.
Boolean extraction accepts only a JSON boolean. A required-boolean roll-up is `failed` if any input
is false, `passed` if all inputs are true, and otherwise `not_evaluated`.

| Stage | Metric formula and stage roll-up |
|---|---|
| `retrieval` | If root key `retrieval` is absent, all four metrics and the stage are not evaluated. If present, `candidate_present` is evaluated and true only for an object with nonblank `candidate_draft_id`; `exact_equivalence` is the strict boolean field when present, is false when present with a wrong type, and is otherwise not evaluated; `top_score` is evaluated only for finite numeric `scores.final` in `[-1,1]`; `top_score_present` is evaluated and true exactly when that valid score exists. A present wrong-typed retrieval/scores object or out-of-range/non-finite score makes the relevant presence metric false. Roll up candidate/score presence only. |
| `draft` | If `model_attempt.draft` key is absent, both metrics and the stage are not evaluated. If present, both metrics are evaluated: `output_present` is whether it is an object and `output_nonempty` is whether that object's `text` is a nonblank string; null/wrong/blank is false. Roll up both. |
| `sketch` | If `model_attempt.sketch` key is absent, the three schema-v2 structural metrics and the stage are not evaluated. If present, all are evaluated: `code_present` is whether the value is an object whose `lean_code` is a string, `code_nonempty` is whether that string is nonblank, and `has_gaps` is the strict boolean field or false when absent/wrong. Roll up code present/nonempty only. Schema v3 additionally records post-runtime `sketch_adherence` by the exact formula below; that metric does not participate in this structural roll-up or any proof/terminal roll-up. |
| `prove` | If root key `model_attempt` is absent, both metrics and the stage are not evaluated. If present, both are evaluated: `code_extracted` is true only for an object with nonblank `lean_code`; `compile_success` is true only when `model_attempt_verification` is an object with strict boolean `success=true`. Missing/null/wrong/false evidence is false. Roll up both. |
| `repair` | Use the complete provenance matrix below. |
| `end_to_end` | If both root keys `generated` and `verification` are absent, both metrics and the stage are not evaluated. If either is present, both metrics are evaluated: `verified` is true only for an object with strict boolean `success=true`; `final_code_present` is true only for an object with nonblank `lean_code`. Missing/null/wrong/false/blank evidence is false. Roll up both. |
| `explanation` | Use the verified-only reference/clarification formula below. |

`top_score` is bounded to `[-1,1]`; coverage metrics are bounded to `[0,1]`; count metrics are
nonnegative integers no greater than `2^53`. The table above is the complete absent/present
precedence for retrieval/draft/sketch/prove/end-to-end. A present malformed required boolean becomes
evaluated false. A malformed or out-of-range optional numeric value remains not evaluated while its
paired presence boolean becomes evaluated false, so the stage fails without fabricating a number.
The repair and explanation matrices below override this rule for their closed evidence.

Schema-v3 `sketch_adherence` has source
`post_runtime.generated_sketch_final_lean_structural_subsequence.v1`. It is evaluated only after the
runtime pipeline has terminated and both the generated sketch Lean and terminal generated Lean are
nonblank strings; otherwise it is null/`not_evaluated`. The pure evaluator removes Lean comments and
string literals, normalizes each remaining nonblank line by replacing every whitespace run with one
ASCII space and trimming it, and retains only lines beginning exactly `theorem `, `lemma `,
`example `, `have `, `let `, or `set `. For theorem/lemma/example/have lines it removes the first
`:=` and everything after it; for every retained line it removes the first token `sorry` or `admit`
and everything after it, then drops empty lines and lines containing `?_`. Adherence is true exactly
when the resulting ordered sketch sequence is a subsequence of the resulting terminal-Lean
sequence. It is false otherwise, including a rephrased but Lean-valid proof. The evaluator cannot
emit a diagnostic or callback and receives immutable runtime artifacts only after the terminal
checkpoint, so this observation cannot trigger repair or veto verification.

### Repair provenance matrix

The mandatory top-level keys are `attempts`, `repairs_used`, `max_repair_attempts`,
`termination_reason`, `termination_event`, `generated`, and `verification`. If any is absent, every
repair consistency/convergence metric and the repair stage are `not_evaluated`. If present but
null, wrong-typed, out of range, or inconsistent, the repair stage is `failed`.

For present provenance all conditions below are required:

- `attempts` is non-empty. Attempt objects have integer `attempt` exactly `1..len(attempts)`, phase
  `preflight|compile`, object `generated`, object `verification` with strict boolean `success`, a
  typed diagnostic list, and closed `checkpoint_status=published|failed`. All attempts except the
  final `artifact_store_failure` attempt require `published`. Attempt 1 has no `repair_route`; every
  later attempt has exactly one route object whose `route` is `draft|sketch|prove`, except that a
  final `checkpoint_status=failed` has no route selected after that failure.
- `repairs_used` and `max_repair_attempts` are integers satisfying
  `0 <= repairs_used <= max_repair_attempts` and `repairs_used = len(attempts)-1`.
- Every attempt before the final one has `verification.success=false`. Thus the array stops at the
  first success. Top-level `verification.success` equals the final attempt success, and top-level
  `generated.lean_code` exactly equals the final attempt generated Lean string (including empty).
- `termination_reason` is one of `verified`, `repair_budget_exhausted`,
  `non_repairable_failure`, `repair_generator_unavailable`, `repair_route_selection_failed`, or
  `artifact_store_failure`.
  `termination_event` is exactly `{reason,attempt,source}`; reason equals `termination_reason`,
  attempt equals the final attempt number, and source is respectively `verification_success`,
  `repair_budget`, `verifier_configuration`, `repair_generator`, `repair_route_selector`, or
  `artifact_store`.
- `verified` requires final success true. Every other reason requires false.
  `repair_budget_exhausted` additionally requires `repairs_used=max_repair_attempts`; every other
  failed reason requires `repairs_used<max_repair_attempts`. `artifact_store_failure` requires the
  final attempt `checkpoint_status=failed`, no route on that attempt, and every prior checkpoint
  published. Evaluation judges only that structured aggregate evidence; the runtime test below,
  not a persisted artifact, proves no later route/model call occurred.

If an attempt checkpoint fails, the pipeline constructs an in-memory terminal result with
`termination_reason=artifact_store_failure` and makes one create-only aggregate-result persistence
attempt without selecting a route or calling another model. If that aggregate persistence also
fails, the pipeline raises typed `ArtifactPersistenceError`; no terminal pipeline artifact or
evaluation run is claimed, and the worker reports only fixed code `pals.artifact_persistence_failed`
to the separately durable proof-job API. Evaluation accepts `artifact_store_failure` only when the
terminal aggregate exists and its final attempt records the failed checkpoint outcome.

A local checkpoint is published create-only in its final directory: create a mode-`0600` temporary
file with `O_EXCL`, write the complete canonical object, file-`fsync`, create the final name with a
same-directory hard link that fails on `EEXIST`, then directory-`fsync` before reporting
`checkpoint_status=published`. It never uses replacing rename. Temporary cleanup is followed by a
second directory-`fsync`; a failure before the first directory fsync is not published, while a
failure after link but before confirmed directory fsync is an ambiguous artifact-store failure and
never permits another route/model call. S3 uses a create-only conditional put. Tests inject every
file/link/directory-fsync failure and duplicate final key.

`attempts`, `repairs_used`, `max_repair_attempts`, and `converged` report the derived count/values.
`attempt_count_consistent` is the conjunction of ordering/count/route shape. Error count is the
number of typed diagnostics with severity `error`, using `attempt.verification.diagnostics` when
present and otherwise `attempt.diagnostics`; `error_reduction = first_errors-last_errors` only when
at least one repair exists, otherwise it is not evaluated. `termination_reason_consistent` is the
conjunction of final/top-level success, generated-code, reason/event/source, and budget rules.
Repair passes only when convergence is true and both consistency booleans are true; any present
inconsistency or honest non-convergence fails.

### Verified-only explanation formula

Explanation evaluation is gated by `artifact.verification.success is true`. If that field is
absent, false, null, or non-boolean, every explanation metric and the stage are `not_evaluated`,
regardless of supplied explanation/clarification text. With a true gate, `payload_present` and
`shape_valid` are always evaluated. `payload_present` is true only for an explanation object.
`shape_valid` is true only when that object satisfies every PAE-002 Japanese/code-point/
cardinality/field-type requirement before reference matching; absent/null/wrong-typed explanation
makes both false, while a present malformed object makes `payload_present=true` and
`shape_valid=false`. Either false fails the stage. In the absent case, both reference counts are `0`,
`references_valid=false`, and `reference_coverage=0.0`. With a true gate and explanation but
missing/blank final Lean, `payload_present=true`, `references_valid=false`, and the stage fails.

For valid Lean, each reference is valid only when its integer 1-based range is inside the source
and its excerpt exactly equals the separator-preserving source slice defined by API PEX-024. The
agent uses the same known-answer algorithm: CRLF is one separator; LF, CR, U+0085, U+2028, and
U+2029 are the other separators; adjacent separators retain interior empty lines; a terminal
separator adds no line; and no split/join/normalization occurs. `reference_count` counts all submitted
references; `valid_reference_count` counts exact matches; `references_valid` requires at least one
and equality of both counts. `reference_coverage` is the size of the union of referenced nonblank
Lean line numbers divided by all nonblank Lean line numbers, or `0.0` when Lean has none.

The evaluation-only input `expect_clarification` is a required strict boolean for a verified-flow
suite case and is never passed to draft/sketch/prove/repair/explanation/clarification prompts. When
false, all four clarification metrics are `not_evaluated` and stage roll-up uses
`payload_present`, `shape_valid`, and `references_valid`. When true, an absent/null/wrong-typed clarification
sequence evaluates as count `0` and all three booleans false; a sequence evaluates
`clarification_count` as its length. `clarifications_complete` requires a non-empty sequence and each item to have a known section,
nonblank question/answer, non-empty nonblank key points, and non-empty references;
`clarification_references_valid` requires every reference exact; and
`clarification_section_overlap` requires each clarification to cite at least one Lean line cited by
its selected explanation section. With true expectation, roll up `payload_present`, `shape_valid`,
`references_valid`, and all three clarification booleans. If `expect_clarification` is absent or
wrong-typed under a true verification gate, clarification metrics are `not_evaluated`; the stage
remains `failed` when `payload_present`, `shape_valid`, or `references_valid` is false and otherwise becomes
`not_evaluated`. Thus incomplete harness evidence cannot erase an already observed explanation
failure. Explanation/clarification shape checks include the Japanese, code-point, key-point, and
non-repetition bounds in PAE-002/PAE-004. Unicode-whitespace normalization replaces every maximal
run of code points with Unicode `White_Space=Yes` by one ASCII space and then trims that space.

### History summaries and semantic enrichment

Per stage, `evaluated` excludes `not_evaluated`; pass rate is `passed/evaluated` or null when the
denominator is zero. Metric averages include only evaluated finite integer/float values, exclude
booleans/text/null, and group by exact metric name. Case/suite/model filters use exact equality and
never mutate history.

The legacy `compare_evaluation_runs` helper may summarize schema-v2 structural records only when
both operands share their exact available suite/model grouping. It is labeled `legacy_structural`,
never state accuracy, and may report unmatched case IDs; it cannot authorize a CLI gate or compare
against schema v3. Schema-v3 summary and comparison use only the stricter completed-live-invocation
and comparability contract below. Input order and JSONL history are never mutated.

Every history append, read, recovery, and migration first opens mode-`0600` stable sibling
`<history-name>.lock` and holds its exclusive writer/recovery/migration or shared reader `flock`
through the complete filesystem operation. The stable lock inode is never replaced with the history,
so an opener cannot append to an unlinked pre-migration inode. After acquiring that lock, every
ordinary append/read/summary operation requires that no sibling recovery or migration fence exists;
either fence causes an explicit typed failure and no history bytes are returned or changed. Explicit
recovery may recognize only its matching recovery fence under the recovery contract; migration
refuses every pre-existing fence. A pre-lock marker check is never an authorization decision. JSONL
append then opens the history, writes exactly one UTF-8 JSON object plus LF, and `fsync`s. Every
normal reader acquires the shared stable lock, performs the under-lock fence check, opens the same
history read-only, and copies one bounded byte
snapshot through the observed file size, then releases the lock before parsing. Thus a reader sees
either the pre-append or post-fsync record set, never an in-progress append. A shared-lock or snapshot
read failure is explicit and never treated as empty history.
A nonempty history whose final byte is not LF is a torn tail: normal reads fail closed with typed
`EvaluationHistoryTornTailError` and do not ignore, parse, or truncate it. Explicit
`recover_torn_history(path)` takes the exclusive lock, revalidates every LF-terminated prefix record,
writes the exact unterminated suffix create-only with mode `0600` to sibling
`<history-name>.torn-<first-16-lowercase-SHA256-of-suffix>.fragment`, fsyncs that file and directory,
then, before `ftruncate`, durably creates sibling `<history-name>.recovery-ambiguous` with mode
`0600` and deterministic prefix-length/suffix-digest evidence. Marker creation or marker-directory
`fsync` failure performs no truncation. While holding the exclusive history lock, recovery truncates
only the quarantined suffix and `fsync`s history; only confirmed history `fsync` permits durable
marker removal and marker-directory `fsync`. Existing valid records are byte-for-byte unchanged. If
the prefix is invalid, the suffix is empty, the quarantine already exists, or any quarantine/fence
write/file-fsync/directory-fsync fails, recovery raises. A crash with a matching durable fence before
truncation may resume recovery; a malformed/mismatched fence fails closed. An `fsync` failure after
`ftruncate` is `EvaluationHistoryRecoveryAmbiguousError`; the durable fence remains, and the
under-lock append check blocks every writer until operator verification. Recovery is never automatic
and its fence/artifact are ignored from version control and excluded from public/telemetry surfaces.

`pals-agent evaluation-history-migrate --migration semantic-comments-v2 --history <path>
--expected-sha256 <64-lowercase-hex>` is the sole PAE-018 mutation entrypoint. Under the exclusive
stable history lock it snapshots the complete source, requires the exact expected digest, and parses
raw JSONL without relaxing the normal reader. Every record must declare `schema_version=2`; the only
permitted current-reader failure is one or more non-null `comment` fields on metrics whose
`kind="semantic"`. The transform sets exactly those values to null, preserves record order/count and
all other JSON values, and validates every transformed object with the normal schema-v2 reader.
No applicable comment, wrong digest, torn tail, malformed JSON, another schema violation, or any
non-semantic invalid comment aborts without replacing the source.

Before replacement, migration create-only writes the exact source bytes mode `0600` to
`<history-name>.pre-semantic-comments-v2.<full-source-sha256>.backup`, file-`fsync`s it, and
directory-`fsync`s it. An existing backup is accepted only when its bytes and digest exactly match
the source snapshot. Migration then create-only writes and file/directory-`fsync`s mode-`0600`
`<history-name>.migration-semantic-comments-v2-ambiguous`; its exact closed JSON evidence is
`migration`, `source_sha256`, `result_sha256`, `backup_name`, `record_count`, and `change_count`.
It writes the fully validated canonical JSONL to a same-directory mode-`0600` `O_EXCL` temporary,
file-`fsync`s it, atomically replaces the history, directory-`fsync`s, and while still locked
reopens the path through the strict reader and requires the original record count and result digest.
Only then may it remove the fence and directory-`fsync` that removal before reporting success.
A failure proven to occur before `os.replace` leaves the source byte-identical and may report a
non-ambiguous migration failure only after durable fence cleanup; a fence-cleanup failure, any
failure at or after `os.replace`, or an unclassifiable failure leaves the fence and raises typed
`EvaluationHistoryMigrationAmbiguousError`. That fence blocks ordinary read/summary/append and all
migration attempts until explicit operator inspection; it is never silently cleared or resumed.
The immutable backup is never removed automatically. CLI output contains migration ID,
record/change counts, source and result SHA-256, and backup path only; it contains no metric comments
or artifact content.

Schema-v2 optional semantic enrichment may append, in stages `retrieval`, `draft`, `sketch`,
`prove`, `repair`, and `explanation`, `semantic_quality` finite float `[0,1]` and
`semantic_quality_pass`, both kind `semantic`. Schema v3 permits that ordered pair only in `draft`
and `sketch`, using their immutable stage-specific smoke-v1 rubric/formula below. The existing
explanation rubric remains available to the separate explanation-quality flow but is not a
schema-v3 smoke-v1 metric or model call. Every other schema-v3 stage rejects semantic metrics; any
future stage rubric requires a new suite/rubric and DEO contract revision rather than a mutable
threshold. Both
metrics are `not_evaluated` on judge configuration/transport/parse failure and never alter
deterministic stage status. The explanation-stage rubric revision is persisted in judge metadata and scores four
equally weighted dimensions in `[0,1]`: mathematical fidelity to verified Lean, concise explanatory
structure, pedagogical clarity, and (when clarification is expected) whether the detailed answer
directly resolves the selected question without merely repeating the concise section. Its
`semantic_quality` is the arithmetic mean of the applicable dimensions. For rubric revision
`lean-explanation-ja-v1`, `semantic_quality_pass` is true only when every applicable dimension is at
least `0.70` and their mean is at least `0.80`; it is false otherwise. PR tests use reviewed positive
and negative judge fixtures. Manual/release runs require a configured judge and fail the quality
gate on `not_evaluated` or false. The rubric and clarification expectation are evaluation-only data,
enter only the post-runtime evaluator-scope prompt, and never enter generation input.

Semantic judge output is exactly `{rubric_revision,dimensions}` where `rubric_revision` is a closed
configured token and `dimensions` has only the rubric's fixed numeric keys. Draft/sketch use the
exact smoke-v1 dimensions, direct floors, and arithmetic-mean threshold; no shared generic rubric
may score both stages. Canonical metric
`comment` is always null for semantic metrics. Judge/provider/model/rubric metadata uses fixed
configuration values only; no judge-generated prose, question, theorem, Lean, prompt, or answer is
persisted in evaluation history.

Semantic evaluator configuration is independent of generation configuration. Let the exact
five-variable state be ordered tuple
`E=(PROVIDER,MODEL,REVISION,BASE_URL,API_KEY)` using the five PAE-019 environment names. Exactly these
three states are valid:

| State | Exact presence contract |
|---|---|
| `unconfigured` | all five variables absent |
| `openai` | all five present and valid, with `PROVIDER=openai` |
| `ollama` | first four present and valid, `PROVIDER=ollama`, and `API_KEY` absent |

Empty is present and invalid. Every other presence vector is partial/stray and fails before DNS,
generation, evaluator, or verifier work. None of `PALS_LLM_PROVIDER`, `PALS_OPENAI_MODEL`,
`OPENAI_MODEL`, `OLLAMA_DRAFT_MODEL`, `OLLAMA_PROVE_MODEL`, their defaults, the PAE-034 registry, or
a generation client may populate an evaluator field. The exact private evaluator identity is
`(provider,model,revision,normalized_origin)` after the URL normalization below. The persisted
identity omits origin and is exactly `(provider,model,revision,source)`. Changing any private identity
member or rubric revision creates different provenance; no endpoint alias or revision inference is
allowed.

Generation credentials shall never authenticate an evaluator request. The only evaluator credential
is `PALS_SEMANTIC_EVALUATOR_API_KEY`: it contains 1–8,192 UTF-8 bytes with no NUL, CR, or LF in the
`openai` state and is absent in the other two states. It must be bytewise different from every
configured generation credential and originate from a separately named secret binding; reusing the
same secret reference, capability, object, or bytes is invalid even when endpoint/model differ.
Empty, whitespace-only, over-limit, forbidden-control, wrong-provider, equal-byte, or shared-binding
state fails before DNS or transport. The bytes pass only through the evaluator's private request
pipe, are never helper argv/environment, and become only `Authorization: Bearer <credential>` at the
configured evaluator origin. They are never copied from `OPENAI_API_KEY`, `PALS_OPENAI_API_KEY`, a
generation request, or another provider setting.

`PALS_SEMANTIC_EVALUATOR_BASE_URL` is parsed once as an absolute URL with scheme exactly lowercase
`http` or `https`, a nonempty ASCII host, optional canonical decimal port `1..65535`, and no userinfo,
query, fragment, percent-encoded host, or control/whitespace byte. The configured base path may be
empty or absolute; dot-segment normalization, scheme-relative resolution, and a host-changing path are
forbidden. `http` is accepted only when the host is exactly lowercase `localhost` and every address
resolved for that request is loopback, or when the host is an IPv4/IPv6 literal for which the standard
IP loopback predicate is true. Every other host requires `https`. The normalized credential origin is
exactly `(scheme, lowercase ASCII host without IPv6 brackets, effective port)` where omitted ports are
80 for HTTP and 443 for HTTPS. The transport disables redirects. Every retry recomputes and requires
the same origin; a redirect, DNS result outside loopback for HTTP, origin change, proxy forwarding,
or request to another origin sends no credential and fails closed. Endpoint, origin, resolved address,
and credentials never enter metric source, evidence, logs, traces, history, summaries, exports, or
public payloads.

After generation scope terminates and immediately before any semantic judge request, identity
normalization validates each provider/model token under PAE-019 and returns the pair
`(provider.lower(), model.lower())`; because the grammar is ASCII, this is exact ASCII lowercase with
no trimming, alias expansion, endpoint inference, revision folding, or percent decoding. For a
schema-v3 case, the contributing generation set is every non-null comparability generation-role
provider/model pair whose role has at least one exact generation `model_calls` row and matching
evaluated prompt-channel count. For the release flow, the contributing set is all eight PAE-034
registry roles and every actual call row beneath them, including OpenMath, retrieval rerank, each
Route/Repair cycle, Explain, and Clarify. The evaluator normalized pair must differ from every member.
A missing identity, inconsistent row/cardinality, or equality produces zero evaluator calls and an
invalid configured case/release result; it is not downgraded to ordinary unconfigured
`not_evaluated`. Exact original tokens remain persisted provenance.

Each rubric evaluation starts one new evaluator-only transport request after the complete immutable
runtime artifact is closed. A private call-separation recorder assigns fresh process-local request
identity and proves the evaluator request was not any generation request, response, batch member,
tool call, provider response ID, or cache entry. The evaluator request may contain only the approved
post-runtime artifact and rubric; generation hidden state, cached scores, and same-response metadata
are forbidden. Missing/duplicate/reused call identity, a request starting before runtime termination,
or a score without one completed evaluator response makes the metric invalid and the live gate fail.
Request identity is test/evidence control data only and is never persisted or logged.

With no evaluator tuple or credential, `--semantic-judge` preserves deterministic results and adds
only the closed unconfigured `not_evaluated` metrics; without that flag no semantic metrics are
requested or added. Release/live semantic quality gates still fail because unconfigured metrics are
not evaluated.

### `lean-explanation-ja-v1` live release oracle

The sole executable release command is the following exact argv from the `pals-agent` repository
root, with the complete valid evaluator configuration above and real generation/verifier
configuration already present:

```text
python -m pytest -q tests/live/test_lean_explanation_release.py::test_lean_explanation_ja_v1 --junitxml=.pals-agent-artifacts/lean-explanation-ja-v1.junit.xml
```

Before process start, `.pals-agent-artifacts/lean-explanation-ja-v1.evidence.json` must not exist; the
test creates it with no-follow `O_CREAT|O_EXCL`, effective-user ownership, mode exactly `0600`, one
compact UTF-8 JSON object plus LF, file `fsync`, and parent-directory `fsync`. An existing/symlink/
non-regular target is an operational failure and is never read as current evidence. The JUnit target
may be replaced by pytest for reporting but cannot satisfy the gate by itself.

The extra-forbid evidence root has exactly keys `schema_version`, `rubric_revision`,
`role_registry_revision`, `started_at`, `completed_at`, `openmath_attempt_count`,
`retrieval_backend`, `retrieval_fetched_count`, `retrieval_context_count`, `repair_cycles`,
`generation_role_calls`, `artifact_persistence_succeeded`, `proof_verification_succeeded`,
`reference_validation_succeeded`, `clarification_expected`, `clarification_completed`,
`evaluator_request_separate`, `generation_identities`, `evaluator`, `dimensions`,
`semantic_quality`, `semantic_quality_pass`, `lean_sha256`, `verified_artifact_sha256`,
`explanation_sha256`, `clarification_sha256`, and `verifier_toolchain_sha256`. Schema is exactly
`pals.lean-explanation-release-evidence.v1`; rubric is exactly `lean-explanation-ja-v1`; timestamps are
UTC RFC 3339 with microseconds and `Z`, with completion not earlier than start. Every boolean field is
true; `evaluator_request_separate` is true only under PAE-019's private distinct-call oracle.
`role_registry_revision` is exactly `pals.release-role-registry.v1`. `openmath_attempt_count` is an
integer in `[1,3]`; `retrieval_backend` is exactly `postgresql_pgvector`;
`retrieval_fetched_count=8`; `retrieval_context_count` is an integer in `[0,4]`; and
`repair_cycles` is an integer in `[2,64]`. `generation_role_calls` is the exact PAE-034 eight-role
ordered array of `{role,provider,model,call_count}`: every provider/model is
`openai/gpt-5.4-mini-2026-03-17`, every count is positive, the OpenMath count equals
`openmath_attempt_count`, and Route/Repair counts are each at least `repair_cycles`.
`generation_identities` is the nonempty unique array of exact contributing `{provider,model}`
objects sorted by normalized provider then model then original provider/model bytes. `evaluator` is
exactly `{provider,model,revision,source}` and source equals the PAE-019 configured source for this
rubric. Its normalized identity differs from every array member.

`dimensions` has exactly finite numeric `[0,1]` values `mathematical_fidelity`,
`concise_explanatory_structure`, `pedagogical_clarity`, and `clarification_resolution`.
`semantic_quality` is their exact arithmetic mean, every dimension is at least `0.70`, the mean is at
least `0.80`, and `semantic_quality_pass` is true under direct finite comparison only. The five digest
fields are lowercase SHA-256: exact verified Lean bytes, exact durable verified-artifact
bytes, canonical typed public explanation content, canonical typed public clarification content, and
the current PAE-017 manifest respectively. The run must perform the complete PAE-034 graph with actual
OpenAI `gpt-5.4-mini-2026-03-17` calls for every role, actual PostgreSQL/pgvector top-8 retrieval and real LLM
reranking, at least two failed isolated-verification/Route/Repair cycles, later successful isolated
PAE-017 verification, durable artifact persistence, explanation, required clarification, exact
reference validation, and one new separately credentialed evaluator request. Fixture, mock, fake,
synthetic, recorded, replayed, benchmark-template, canned, local ad-hoc, cached-provider, or patched
success is forbidden at every generation/retrieval/verifier/artifact/evaluator boundary.

The command passes only when process exit is exactly zero, JUnit reports exactly one collected test
with failures=0, errors=0, skipped=0, and the newly created evidence strict-reads and satisfies every
oracle above. Any nonzero process result, no/extra test, skip/xfail/xpass, missing/stale/malformed/
unfsynced evidence, `not_evaluated`, false rubric result, identity equality, credential/transport
violation, missing required clarification, invalid reference, or non-real model/verifier path fails
release. stdout/stderr, JUnit properties, and evidence shall contain no endpoint, origin, address,
credential, prompt/output, theorem, Lean, explanation, clarification, exception text, or raw provider
response; only the closed identifiers, booleans, numeric scores, timestamps, and digests above are
retained.

## Versioned Suite and History-v3 Contract

### Strict version registries

The strict schema-v2 reader accepts exactly the run keys `schema_version`, `suite_revision`,
`run_id`, `case_id`, `model`, `model_metadata`, `created_at`, and `stages`; stage keys `stage`,
`status`, and `metrics`; and metric keys `name`, `value`, `status`, `source`, `kind`, and `comment`.
The exact deterministic metric names remain: retrieval `candidate_present`, `exact_equivalence`,
`top_score_present`, `top_score`; draft `output_present`, `output_nonempty`; sketch `code_present`,
`code_nonempty`, `has_gaps`; prove `code_extracted`, `compile_success`; repair `attempts`,
`repairs_used`, `max_repair_attempts`, `attempt_count_consistent`, `error_reduction`, `converged`,
`termination_reason`, `termination_reason_consistent`; end-to-end `verified`,
`final_code_present`; and explanation `payload_present`, `shape_valid`, `reference_count`,
`valid_reference_count`, `references_valid`, `reference_coverage`, `clarification_count`,
`clarifications_complete`, `clarification_references_valid`, and
`clarification_section_overlap`. The existing semantic pair is allowed only with PAE-019 source
grammar. The reader recomputes deterministic status and rejects every unknown/duplicate field or
metric. Schema-v2 rows are always classified `legacy_structural`; their five-row history and `0.4`
never become accuracy, a live gate, or a schema-v3 comparison operand.

Schema v3 is a separate closed parser. It does not call the schema-v2 parser and never accepts a
v2-only key, metric, inferred default, field drop, version guess, or serialized status that differs
from recomputation. Unknown fields are rejected recursively in invocation, comparability,
retrieval, prompt-channel, model-call, explanation-chain, stage, metric, and candidate evidence.
One invalid physical line fails the complete load at that line without returning earlier records or
changing bytes.
Its semantic pair is allowed only in `draft` and `sketch`, in that order after all deterministic
metrics, with rubric revisions respectively `dsp-draft-ja-v1` and `dsp-sketch-lean-v1` inside the
exact PAE-019 source grammar.

### Immutable smoke-v1 manifest

Canonical JSON means UTF-8, sorted object keys, no ASCII escaping, separators `(',',':')`, no
insignificant whitespace, and the original array order. SHA-256 is lowercase hexadecimal over those
canonical bytes. The packaged `smoke-v1` manifest content is exactly:

```json
{
  "schema_version": "pals.evaluation-suite.v1",
  "suite_id": "pals.dsp-evaluation",
  "suite_revision": "smoke-v1",
  "profiles": {
    "smoke": ["continuous_square", "rank_nullity", "compact_image"],
    "full": ["continuous_square", "rank_nullity", "compact_image"]
  },
  "rubrics": {
    "draft": {
      "revision": "dsp-draft-ja-v1",
      "dimensions": ["problem_fidelity", "formal_statement_fidelity", "strategy_soundness", "strategy_completeness"],
      "formula": "arithmetic_mean",
      "dimension_floor": 0.7,
      "mean_threshold": 0.8
    },
    "sketch": {
      "revision": "dsp-sketch-lean-v1",
      "dimensions": ["draft_fidelity", "lean_structure_soundness", "step_completeness", "gap_discipline"],
      "formula": "arithmetic_mean",
      "dimension_floor": 0.7,
      "mean_threshold": 0.8
    }
  },
  "cases": [
    {
      "id": "continuous_square",
      "prompt": "x^2が連続であることを示せ",
      "relevant_draft_ids": ["continuous_square", "continuous_power"],
      "retrieval_top_k": 5,
      "compile_oracle": "isolated_lean_compile",
      "strategy_reference": "Establish continuity of the real function x ↦ x^2 by a mathematically sound Lean proof; semantically equivalent methods are acceptable.",
      "draft_rubric_revision": "dsp-draft-ja-v1",
      "sketch_rubric_revision": "dsp-sketch-lean-v1",
      "evaluator_sentinel": "PAE_SMOKE_V1_EVAL_CONTINUOUS_SQUARE",
      "expect_explanation": true,
      "expect_clarification": false
    },
    {
      "id": "rank_nullity",
      "prompt": "rank A = n - Ker Aを示せ",
      "relevant_draft_ids": ["rank_nullity"],
      "retrieval_top_k": 5,
      "compile_oracle": "isolated_lean_compile",
      "strategy_reference": "Formalize and prove rank-nullity for the requested finite-dimensional linear map; direct theorem use or an equivalent derivation is acceptable.",
      "draft_rubric_revision": "dsp-draft-ja-v1",
      "sketch_rubric_revision": "dsp-sketch-lean-v1",
      "evaluator_sentinel": "PAE_SMOKE_V1_EVAL_RANK_NULLITY",
      "expect_explanation": true,
      "expect_clarification": false
    },
    {
      "id": "compact_image",
      "prompt": "cpt集合の連続写像による像はcpt集合であることを示せ",
      "relevant_draft_ids": ["compact_image"],
      "retrieval_top_k": 5,
      "compile_oracle": "isolated_lean_compile",
      "strategy_reference": "Formalize and prove that the image of a compact set under a map continuous on that set is compact; direct theorem use or an equivalent derivation is acceptable.",
      "draft_rubric_revision": "dsp-draft-ja-v1",
      "sketch_rubric_revision": "dsp-sketch-lean-v1",
      "evaluator_sentinel": "PAE_SMOKE_V1_EVAL_COMPACT_IMAGE",
      "expect_explanation": true,
      "expect_clarification": false
    }
  ]
}
```

Its exact digests are:

| Object | SHA-256 |
|---|---|
| complete manifest | `86af97980af6a88068c4729900a8045f1005ec7fda9251d8b886b8fae08d08b0` |
| rubric bundle | `7ae4164a8ed5fe4d02f3b16d635bdac93f4696e7cb2e75b210d18eae52bb5334` |
| `continuous_square` case object | `72be75eb765eca5ad568d0a131a3e654ed6fd48f18335ad37461c67f5aa892a9` |
| `rank_nullity` case object | `b49ccd27cee625ce0cf5e2e4d33a8c913aa892b5fe51960dc70a36909a29c413` |
| `compact_image` case object | `979e535da64659b510a745ea8d080b7806e03c02f3dfece1e76e6dc287fbd7c2` |

Every semantic dimension is a finite JSON number in `[0,1]`. For each rubric, quality is the exact
arithmetic mean of all four named dimensions and pass is true only when every dimension is `>=0.70`
and the mean is `>=0.80`, using PAE-024 direct comparisons. Missing/extra dimensions, booleans,
non-finite numbers, or a wrong rubric revision are not evaluated. The relevant Draft IDs, strategy
reference, rubric, expectations, and sentinel are independently reviewed evaluation-only fields;
only a fresh `{id,prompt}` reaches runtime generation.

### Prompt-channel separation

Generation scope is exactly `openmath|draft|sketch|prove|route|repair|explain|clarify`; the `draft`
role includes both its retrieval-relevance subcall and ordinary Draft generation. Schema-v3
evaluator scope is exactly `draft_semantic|sketch_semantic`. Every generation call for a
case, including initial generation, each selector retry, and every routed repair, must terminate
before the first evaluator call for that case. Generation prompts may contain runtime artifacts and
actual typed generation/transport/safety/formal-identity/verifier/compiler diagnostics only. They
must contain none of the case's strategy reference, relevant-ID label, rubric revision/dimension,
compile oracle token, evaluator sentinel, hidden harness, expected method, or benchmark registry
material. Evaluator prompts must contain the exact case sentinel and applicable rubric revision and
may receive the immutable runtime artifacts plus evaluation-only manifest fields after runtime; no
evaluator output or error can call a pipeline callback, append a runtime diagnostic, route repair,
or change terminal state.

The runner captures every prompt in a scope-tagged in-memory audit sink until case assembly, checks
generation prompts against all manifest evaluation-only values, and checks evaluator prompts and
timestamps independently. Raw prompts are then discarded under the existing privacy contract.
Schema-v3 `prompt_channel_evidence` is exactly
`{status,generation_call_count,evaluator_call_count,generation_forbidden_match_count,
evaluator_required_sentinel_count,evaluator_started_after_runtime}`. With `status=evaluated`, counts
are nonnegative integers, forbidden matches are zero, every configured evaluator call contains the
sentinel, and `evaluator_started_after_runtime=true`; with `not_evaluated`, all five values are null.
Missing capture cannot pass. Unit sentinels inspect the full initial, every selector retry, and every
routed repair prompt as well as the independent post-runtime evaluator prompts.

### Schema-v3 case and provenance

A schema-v3 line has exactly these root keys in any JSON object order:
`schema_version`, `origin`, `invocation_id`, `run_id`, `suite_id`, `suite_revision`,
`suite_profile`, `suite_manifest_sha256`, `case_id`, `case_manifest_sha256`,
`runtime_input_sha256`, `comparability`, `comparability_sha256`, `created_at`, `completed_at`,
`retrieval_evidence`, `prompt_channel_evidence`, `model_calls`, `explanation_chain`, and `stages`.
`schema_version=3`, `origin="live"`, both IDs are UUIDv4, profile is `smoke|full`, and the suite/case
IDs and digests exactly match the packaged manifest. `runtime_input_sha256` is the canonical digest
of exactly `{id,prompt}`. Timestamps are timezone-aware UTC RFC 3339; completion is not earlier than
creation. Production CLI accepts no caller-supplied origin, run ID, invocation ID, manifest, pipeline
factory, verifier result, judge score, token count, or cost.

`comparability` is exactly:

```json
{
  "schema_version": "pals.evaluation-comparability.v1",
  "suite_manifest_sha256": "<64 lowercase hex>",
  "generation": {
    "revision": "pals.release-role-registry.v1",
    "roles": [
      {"role": "openmath", "provider": "<nonblank or null>", "model": "<nonblank or null>"},
      {"role": "draft", "provider": "<nonblank or null>", "model": "<nonblank or null>"},
      {"role": "sketch", "provider": "<nonblank or null>", "model": "<nonblank or null>"},
      {"role": "prove", "provider": "<nonblank or null>", "model": "<nonblank or null>"},
      {"role": "route", "provider": "<nonblank or null>", "model": "<nonblank or null>"},
      {"role": "repair", "provider": "<nonblank or null>", "model": "<nonblank or null>"},
      {"role": "explain", "provider": "<nonblank or null>", "model": "<nonblank or null>"},
      {"role": "clarify", "provider": "<nonblank or null>", "model": "<nonblank or null>"}
    ]
  },
  "evaluator": {"provider": "<provider>", "model": "<model>", "revision": "<revision>"},
  "rubric_bundle_sha256": "<64 lowercase hex>",
  "price": {
    "revision": "<revision>",
    "generation_input_usd_per_million": "<canonical decimal>",
    "generation_output_usd_per_million": "<canonical decimal>",
    "evaluator_input_usd_per_million": "<canonical decimal or null>",
    "evaluator_output_usd_per_million": "<canonical decimal or null>"
  },
  "max_repair_attempts": 12,
  "agent_source_sha256": "<64 lowercase hex>",
  "verifier_toolchain_sha256": "<64 lowercase hex>"
}
```

`evaluator` is either that exact object or JSON null; `price` is either that exact object or null.
For every generation role, provider/model are both nonblank bounded strings or both null; the exact
eight-role order is fixed. Release-origin records require revision
`pals.release-role-registry.v1` and all eight pairs exactly `openai/gpt-5.4-mini-2026-03-17`; no environment
revision/model override is accepted. Non-release deterministic fixtures may use a separately named
test revision but cannot produce origin `live`, authorization, export, or release evidence.
`comparability_sha256` is the canonical
digest of this complete object. Every record in one invocation has byte-equivalent comparability and
digest; case digests remain separate because they differ by case. Summary and compare require exact
object and digest equality, then additionally require each paired case's case digest equality.

`agent_source_sha256` is the canonical digest of an ordered manifest of relative POSIX path, byte
length, and file SHA-256 for `pyproject.toml` plus every packaged regular `.py`/`.json` file under
`pals_agent`; symlink, unreadable file, duplicate path, or mutation during hashing aborts before a
model call. `verifier_toolchain_sha256` comes only from API-provided deployment-binding evidence
admitted from PAE-036 readiness and equals
SHA-256 of the one exact `pals.verifier-toolchain-manifest.v1` byte stream defined above. That stream's
exhaustive path/byte-length/file-SHA-256 record set covers the exact Lean descriptor, exact Git
descriptor, exact Git executable bytes/version binding, and every no-follow regular file beneath the
pinned project and descriptor-authoritative toolchain roots, including
`lean-toolchain`, `lakefile.lean`, `lake-manifest.json`, Lake/Lean, the six grammar sources, and every
runtime `.olean`/`.olean.private`; PAE-027 defines no second manifest, relative-path form, raw-byte
concatenation, or reduced input set. The manifest is read-only and included in startup boundary
attestation; it is provenance, not a substitute for isolation, per-request root re-attestation,
manifest-listed path/size/digest validation, or compile success. Missing or changing either digest
makes the case not authorizable and separates comparison groups.

`retrieval_evidence` is exactly `{status,expected_draft_ids,requested_top_k,candidates}`. Expected
IDs and top-k equal the case manifest. `status=evaluated|not_evaluated`; candidates are empty when
not evaluated. Evaluated candidates are zero to top-k objects exactly
`{rank,draft_id,vector_score,structural_score,final_score,exact_equivalence}`, ordered ranks `1..n`,
unique nonblank IDs, strict boolean equivalence, and finite scores `[0,1]`. Expected hit is true when
candidate IDs intersect expected IDs and rank is the first such rank; a complete miss is evaluated
false with null hit rank, while unavailable retrieval is not evaluated.

`model_calls` is an ordered array of exact objects
`{scope,role,ordinal,provider,model,outcome,input_tokens,output_tokens,total_tokens,
actual_cost_usd,duration_ms}`. Scope is `generation|evaluator`. Generation role is exactly one of
`openmath|draft|sketch|prove|route|repair|explain|clarify`; evaluator role is exactly one of
`draft|sketch`. The separate explanation-quality flow is not a schema-v3 smoke-v1 `model_calls`
row, consistently with the semantic-metric contract above. Ordinal is consecutive from one within
`(scope,role)`; outcome is
`succeeded|failed`; duration is a measured nonnegative integer. Usage fields are all nonnegative
integers with total equal to input+output, or all null. Actual cost is a finite nonnegative JSON
number from typed provider evidence or null. Every transport-attempted call, including failed
selectors/repairs/judges, has exactly one item; raw prompt/output/error is absent.

Cross-field binding is mandatory. For a generation row, provider/model must equal the nonnull pair
in the unique same-role `comparability.generation.roles` entry; a null pair permits zero rows for that
role. For an evaluator row, role `draft|sketch` corresponds only to the captured
`draft_semantic|sketch_semantic` evaluator prompt kind, `comparability.evaluator` must be nonnull,
and row provider/model must equal its provider/model; a null evaluator permits zero evaluator rows.
The containing generation
revision or evaluator revision, respectively, is the revision identity for every matching row and
cannot be replaced by a row-local value. With `prompt_channel_evidence.status=evaluated`,
`generation_call_count` and `evaluator_call_count` equal exactly the respective row counts, and each
equals the sum of its allowed role cardinalities. With prompt-channel status `not_evaluated`, a
schema-v3 live record is not authorizable and cannot claim model-call completeness. Mutating a row's
scope, role, provider, model, ordinal, adding/removing/duplicating a row, nulling a referenced
comparability identity, or changing either prompt count while leaving the other fields fixed
invalidates the complete record before summary, comparison, gate, or export.

Generation and evaluator token totals are independently evaluated only when every call in that
scope has complete usage. Overall tokens/cost are evaluated only when every applicable scope is
complete; no partial sum becomes a value or zero.

Estimated-price configuration keeps the generation variables
`PALS_EVALUATION_INPUT_COST_USD_PER_MILLION_TOKENS`,
`PALS_EVALUATION_OUTPUT_COST_USD_PER_MILLION_TOKENS`, and
`PALS_EVALUATION_COST_REVISION`, and adds evaluator rates
`PALS_EVALUATION_EVALUATOR_INPUT_COST_USD_PER_MILLION_TOKENS` and
`PALS_EVALUATION_EVALUATOR_OUTPUT_COST_USD_PER_MILLION_TOKENS`. Generation price variables are all
absent or all present. Evaluator rates are both absent when no evaluator is configured; with a
configured evaluator they are both present for complete estimated cost or both absent to produce
explicit not-evaluated cost. Every rate is a canonical finite ASCII decimal in `(0,1000]`; partial
or invalid pairs fail before model work. Per scope, estimated cost is
`(input*input_rate + output*output_rate)/1_000_000`, quantized to 12 decimal places with
`ROUND_HALF_EVEN`. No web lookup, model-name inference, local-zero assumption, or missing-call
proration is allowed. Actual-cost totals likewise require typed evidence from every applicable call.

`explanation_chain` is exactly
`{status,lean_sha256,explanation_sha256,clarification_sha256s,chain_sha256,complete}`. Before verified
Lean it is `not_evaluated` with the other five values null. After verification it is `evaluated`:
Lean hash is required; explanation hash is the canonical digest of the exact typed public content or
null when missing; clarification hashes are an ordered array of canonical typed-content digests;
`complete` is strict boolean; and chain hash is the canonical digest of exactly
`{lean_sha256,explanation_sha256,clarification_sha256s}` only when all manifest-required explanation/
clarification evidence exists, otherwise null and complete false. Digests never replace the
verified-only reference checks and never cross PAE-014 export.

Schema v3 retains the canonical seven stages and schema-v2 deterministic metrics, then adds only:
retrieval `expected_hit`, `expected_hit_rank`, `requested_top_k`, `ranked_candidate_count`; sketch
`sketch_adherence`; prove `first_compile_success`; repair `repair_rounds`; end-to-end
`final_compile_success`, `compile_transition`, `case_latency_ms`,
`generation_input_tokens`, `generation_output_tokens`, `generation_total_tokens`,
`generation_estimated_cost_usd`, `generation_actual_cost_usd`, `evaluator_input_tokens`,
`evaluator_output_tokens`, `evaluator_total_tokens`, `evaluator_estimated_cost_usd`,
`evaluator_actual_cost_usd`, `overall_input_tokens`, `overall_output_tokens`,
`overall_total_tokens`, `overall_estimated_cost_usd`, and `overall_actual_cost_usd`; and explanation
`clarification_expected`, `chain_complete`. Draft and sketch each have their exact
stage-specific semantic pair and rubric source. `first_compile_success` and
`final_compile_success` come only from typed isolated-verifier evidence for the first and final
attempt, before checkpoint-state rewriting; absent verifier invocation is not evaluated.
`compile_transition` is evaluated text exactly `improved`, `regressed`, `stable_pass`, or
`stable_fail` when both booleans exist and otherwise null/not-evaluated. Repair rounds equal
`repairs_used`. Latency is measured monotonic case completion minus start. Semantic and sketch
adherence metrics never participate in prove/end-to-end verification status.

### Live invocation, summary, and comparison

Before any case work, `evaluation-run` create-only publishes a mode-0600 journal
`invocations/<invocation_id>.json`, file-fsyncs and directory-fsyncs it. The extra-forbid journal is
exactly `{schema_version,origin,invocation_id,run_id,suite_id,suite_revision,suite_profile,
suite_manifest_sha256,comparability_sha256,expected_case_ids,completed_case_ids,state,created_at,
updated_at,failure_code}`. Schema is `pals.evaluation-invocation.v1`, origin is `live`, expected IDs
equal the selected manifest profile, completed IDs are an ordered prefix without duplicates, state
is `running|completed|failed|interrupted`, and failure code is null only for running/completed.
Every case append fsyncs history before an atomic+fsync journal replacement adds that case ID. The
final journal becomes `completed` only after strict re-read proves every expected case exactly once,
matching invocation/run/origin/manifest/comparability and no foreign or duplicate case.

An existing journal is never resumed, adopted, overwritten, or used by a new invocation. A stale
`running` journal remains auditable but incomplete. Duplicate `(run_id,case_id)` or
`(invocation_id,case_id)`, stale/foreign history, provenance drift, case operational exception,
append ambiguity, journal write/fsync ambiguity, or summary failure preserves completed history,
sets `failed` when durably possible, and returns operational exit 3. SIGINT/SIGTERM first attempt to
publish `interrupted` with fixed failure code and then return 130/143; a failed signal-state write
leaves `running`, which is still non-authorizing. No interrupted/failed/running journal can be
relabelled completed by summary.

The canonical JSON summary schema is `pals.evaluation-summary.v1`. Its root has exactly
`schema_version`, `origin`, `invocation_id`, `run_id`, `suite_id`, `suite_revision`,
`suite_profile`, `suite_manifest_sha256`, `case_manifest_sha256s`, `comparability`,
`comparability_sha256`, `created_at`, `completed_at`, `expected_case_count`,
`included_case_count`, `max_repair_attempts`, `overall_quality`, and `aggregates`.
`schema_version` is that exact string, origin is `live`, IDs/timestamps/tokens use the case-record
domains, and completion is not earlier than creation. `case_manifest_sha256s` is the nonempty unique
ordered manifest-case digest list. Canonical comparability bytes and digest equal every represented
case; suite/invocation/run/profile/manifest identity is also identical. `expected_case_count` equals
the digest-list length, `included_case_count` is in `[0,expected_case_count]`, and a completed live
publisher requires equality. `max_repair_attempts` is `[1,64]` and equals comparability. The pure
typed serializer may represent a partial/non-authorizing summary for deterministic contract tests,
but production `evaluation-run` publishes only from a strict completed journal and complete exact
case set.

`aggregates` has exactly:

| Aggregate key | Canonical aggregate type |
|---|---|
| `retrieval_hit_at_k` | rate |
| `draft_semantic_pass_rate` | rate |
| `sketch_semantic_pass_rate` | rate |
| `sketch_adherence_pass_rate` | rate |
| `first_compile_success_rate` | rate |
| `final_compile_success_rate` | rate |
| `repair_convergence_rate` | rate |
| `explanation_chain_complete_rate` | rate |
| `case_latency_p50_ms` | count scalar |
| `case_latency_p95_ms` | count scalar |
| `generation_input_tokens` | count scalar |
| `generation_output_tokens` | count scalar |
| `generation_total_tokens` | count scalar |
| `evaluator_input_tokens` | count scalar |
| `evaluator_output_tokens` | count scalar |
| `evaluator_total_tokens` | count scalar |
| `overall_input_tokens` | count scalar |
| `overall_output_tokens` | count scalar |
| `overall_total_tokens` | count scalar |
| `estimated_cost_usd` | nonnegative finite decimal scalar |
| `actual_cost_usd` | nonnegative finite decimal scalar |
| `compile_transition_counts` | transition |
| `repair_round_histogram` | histogram |

Every aggregate status is exactly `complete|partial|not_evaluated`. A rate is exactly
`{status,evaluated_count,missing_count,passed_count,value}`; the first two counts sum to
`expected_case_count`, passed is at most evaluated, value is exact `passed_count/evaluated_count`
when evaluated is positive and null otherwise. A scalar is exactly
`{status,evaluated_count,missing_count,value}` with the same count equation and a typed nonnull value
only when evaluated is positive. A transition uses that scalar shape with nonnull value exactly
`{improved,regressed,stable_pass,stable_fail}` whose counts sum to evaluated. A histogram uses that
shape with nonnull value exactly `max_repair_attempts+1` entries `{round,count}` ordered from round
zero through the budget and summing to evaluated. Status is complete only when missing is zero,
partial only when evaluated and missing are both positive, and not-evaluated only when evaluated is
zero. Values exclude every not-evaluated observation; token/cost totals require complete per-case
evidence and never prorate. Latency percentiles use sorted nearest-rank index `ceil(p*n)-1`.

`overall_quality` is exactly `passed|failed|not_evaluated` under the gate formula below. JSON and
Markdown are projections of the same typed facts; Markdown adds no value and is not a canonical
machine source. The canonical JSON publisher uses mode 0600, a same-directory exclusive temporary,
file fsync, atomic replace, and directory fsync; derived Markdown uses the same durability sequence
but is never authority. Any cross-repository consumption of this schema occurs only through the
separate PAE-030 through PAE-033 projection governed by parent DEO-001 through DEO-020.

Overall quality is `failed` if any required evaluated boolean/rubric/compile/chain fact fails;
otherwise it is `not_evaluated` if any required family is missing/partial; otherwise it is `passed`.
Live authorization additionally requires a completed current journal, origin live, all current
manifest cases exactly once, exact manifest/case/comparability digests, prompt separation, and no
foreign record. Exit 0 is only that authorized pass; exit 1 is completed/evaluated failure; exit 2
is completed required evidence not evaluated; exit 3 is operational/incomplete/stale/duplicate
failure. Synthetic aggregate fixtures may call pure formula helpers and assert math, but cannot
create production journals/history, call the authorization function, or produce a production CLI
exit 0.

History listing returns separate groups by schema and exact v3 comparability digest/object. Summary
refuses heterogeneous groups. Compare requires two completed live invocations with identical suite
ID/revision/profile/manifest, exact comparability object/digest, complete current profile case sets,
and equal paired case digests; any mismatch is explicit drift/exit 3 rather than averaging. For each
paired case it reports baseline/candidate values and candidate-minus-baseline only when both are
numeric/evaluated. The five schema-v2 rows are listed only as heterogeneous `legacy_structural`
groups and cannot be operands for v3 accuracy comparison. PAE-014 export occurs only after canonical
append and never participates in these decisions.

## DEO-v1 Agent Producer Contract

This section is normative for PAE-014 and PAE-030 through PAE-033. The parent
`specs/dsp-evaluation-observability-export` DEO-001 through DEO-020 remain the sole
cross-repository exchange authority. This child section fixes only Agent-owned canonical mapping,
producer identity material, producer key binding, artifact publication, and producer evidence. It
does not define or import consumer/projection behavior.

### Explicit export operation

The sole production invocation is:

```text
pals-agent evaluation-export-dsp-v1 \
  --invocation-id <UUIDv4> \
  --output-directory <absolute-existing-private-directory>
```

The parser accepts each option exactly once and no positional argument or additional option. The
output path must be absolute and every existing component must be traversed no-follow beneath an
already-open filesystem-root descriptor; its final object must already be a directory owned by the effective UID with exact
mode `0700`. The directory is opened with directory/no-follow semantics and pinned by descriptor
before canonical reads; the operation creates no directory and never re-resolves the caller path. The
invocation ID selects the one canonical journal/history/summary set through repository configuration,
not a caller path. There is no case, summary, filename, schema, provider, key, source-record, or
in-memory-object override.

After PAE-030/PAE-031 derives the full lowercase `invocation_fingerprint`, targets are exactly sibling
regular files `<invocation_fingerprint>.pals.dsp-export.v1.json` and
`<invocation_fingerprint>.pals.dsp-export.v1.sha256` beneath the pinned directory. Path separators,
relative traversal, symlink targets, alternate extensions, and caller names are impossible. If both
targets are absent, PAE-032 performs its ordered create-only publication. If both already exist as
no-follow regular single-link files owned by the effective UID with exact mode `0600`, and their exact
bytes equal the newly derived payload and
sidecar, the operation performs no write/fsync and returns idempotent `already_published`. Any
one-file state, byte mismatch, malformed file, symlink, non-regular object, or identity collision is
`publication_conflict`; neither target nor canonical evidence changes. This equality is only a
producer replay oracle, never DEO consumer acceptance or Agent-origin authentication.

Success writes exactly one stdout JSON object plus LF and empty stderr. Its keys are exactly
`schema_version`, `status`, and `case_count` in that order; `schema_version` is exactly
`pals.agent-dsp-export-result.v1`, `status` is exactly one of `published|already_published`, and
`case_count` is the exact exported integer in `[1,1000]`. It exits 0. Failure stdout is empty and
stderr is exactly one fixed line
`pals-agent: evaluation-export-dsp-v1: <error-code>\n`, where code is one of
`invalid_request|invocation_not_completed|source_invalid|configuration_error|publication_conflict|publication_failed`.
Exception text, path, invocation ID, fingerprints, digest, key/version, DTO value, or source value is
never printed or logged. No exit, including replay, changes PAE-029's stored exit or any canonical
record.

The failure mapping is total and ordered; the first applicable row wins:

| Condition | Error code | Exit |
|---|---|---:|
| Missing, duplicate, unknown, or positional CLI argument; malformed UUIDv4; non-absolute, absent, symlink-containing, non-directory, non-effective-UID-owned, or non-mode-`0700` output directory | `invalid_request` | 2 |
| Invocation not found; journal absent, `running`, interrupted, incomplete, or bound to PAE-029 exit 3 | `invocation_not_completed` | 2 |
| Canonical repository configuration/read is unavailable, or a nominally completed invocation has unreadable, malformed, heterogeneous, inconsistent, out-of-bound, unmappable, or unserializable canonical journal/history/summary/case evidence | `source_invalid` | 3 |
| Environment, key provider, registry, CSPRNG, secret ARN/VersionId, or key-binding configuration is absent, malformed, ambiguous, or unavailable before target publication | `configuration_error` | 3 |
| Either deterministic target already exists in any state except the exact two-file byte-identical, effective-UID-owned, mode-`0600`, regular single-link replay | `publication_conflict` | 2 |
| Temporary creation, write, file fsync, create-only install, directory fsync, or publication-outcome determination fails after publication begins | `publication_failed` | 3 |

Argument/directory validation occurs before canonical reads; completed-invocation validation occurs
before key resolution; key/configuration resolution occurs before target-state inspection; target
inspection occurs before the first publication write. Once publication begins, every filesystem or
durability ambiguity is `publication_failed` even if a payload target became visible. No exception is
reclassified from its private text.

### Completed-invocation input and envelope

The projector accepts only a strict schema-v3 invocation whose durable journal is `completed` and
whose canonical history re-read and PAE-028 summary satisfy the PAE-029 identity, live-origin,
manifest, comparability, complete-case-set, and durability preconditions common to completed exits
0, 1, and 2. It does not require or imply the separate exit-0 authorized-pass verdict: canonical
`overall_quality=passed|failed|not_evaluated` are all eligible after completion. It does not accept a
schema-v2 row, partial/running/interrupted/incomplete exit-3 journal, synthetic aggregate,
caller-supplied case, or an in-memory pre-persistence result. The operation is read-only with respect
to journal, history, canonical JSON/Markdown summary, comparison, gate, and CLI outcome.

`case_count` is the exact length of journal `expected_case_ids` and must be in `[1,1000]`. Cases are
looked up from the strict re-read and emitted in that exact array order, not physical JSONL order or
caller order. Each expected ID must resolve to exactly one record with the same invocation/run,
suite/profile/manifest, comparability object/digest, and matching case manifest digest. Any missing,
duplicate, extra represented, foreign, stale, or mismatched case fails the complete mapping before
key binding or publication. No quality/status/result condition may change membership or order.

The envelope has exactly these keys in this serialization order:

```json
{
  "batch_schema": "pals.dsp-export.v1",
  "contract_revision": "deo-v1",
  "invocation_fingerprint": "<hex64>",
  "run_fingerprint": "<hex64>",
  "suite_fingerprint": "<hex64>",
  "producer_fingerprint_key_version": "<key-version>",
  "comparability_fingerprint": "<hex64>",
  "case_count": 1,
  "cases": [],
  "summary": {}
}
```

Every case has exactly, in order, `case_ordinal`, `case_fingerprint`, `stage_statuses`, and
`metrics`. `case_ordinal` is its zero-based position. `stage_statuses` copies the canonical strict
stage status without inference and has exactly, in order, `retrieval`, `draft`, `sketch`, `prove`,
`repair`, `end_to_end`, and `explanation`; every value remains `passed|failed|not_evaluated`.
Every case fingerprint is unique. The summary has exactly, in order, `summary_status`,
`ordered_case_fingerprints`, `stage_status_counts`, `boolean_rates`, `quality_rates`,
`scalar_aggregates`, and `repair_rounds_histogram`. `summary_status` is the exact canonical PAE-028
`overall_quality` for the same strict case set. `ordered_case_fingerprints` is the case fingerprint
array without change.

### Case metric mapping and integer oracle

Every DTO metric is exactly `{name,status,value}` in the following order. A source metric with
canonical status `not_evaluated` maps only to `status="not_evaluated",value=null`. A source metric
with canonical status `evaluated` maps only to `status="evaluated"` and the conversion below. A
missing, duplicated, wrong-stage, wrong-kind, wrong-source, malformed, out-of-domain, or
status/value-contradictory source fails the complete mapping; no default, zero, false, omission,
coercion, or alternate source is permitted.

| Ordinal | DTO metric | Exact schema-v3 source | Exact evaluated conversion/domain |
|---:|---|---|---|
| 0 | `retrieval_hit` | `retrieval.expected_hit` | strict JSON boolean |
| 1 | `draft_quality` | `draft.semantic_quality` | half-even millionths integer `[0,1000000]` |
| 2 | `sketch_quality` | `sketch.semantic_quality` | half-even millionths integer `[0,1000000]` |
| 3 | `sketch_adherence` | `sketch.sketch_adherence` | strict JSON boolean |
| 4 | `first_compile_success` | `prove.first_compile_success` | strict JSON boolean |
| 5 | `final_compile_success` | `end_to_end.final_compile_success` | strict JSON boolean |
| 6 | `repair_rounds` | `repair.repair_rounds` | exact integer `[0,64]` |
| 7 | `repair_converged` | `repair.converged` | strict JSON boolean |
| 8 | `verification_success` | `end_to_end.verified` | strict JSON boolean |
| 9 | `explanation_chain_complete` | `explanation.chain_complete` | strict JSON boolean |
| 10 | `latency_ms` | `end_to_end.case_latency_ms` | exact integer `[0,86400000]` |
| 11 | `generation_input_tokens` | same-named `end_to_end` metric | exact integer `[0,1000000000]` |
| 12 | `generation_output_tokens` | same-named `end_to_end` metric | exact integer `[0,1000000000]` |
| 13 | `generation_total_tokens` | same-named `end_to_end` metric | exact integer `[0,1000000000]` |
| 14 | `evaluator_input_tokens` | same-named `end_to_end` metric | exact integer `[0,1000000000]` |
| 15 | `evaluator_output_tokens` | same-named `end_to_end` metric | exact integer `[0,1000000000]` |
| 16 | `evaluator_total_tokens` | same-named `end_to_end` metric | exact integer `[0,1000000000]` |
| 17 | `overall_input_tokens` | same-named `end_to_end` metric | exact integer `[0,1000000000]` |
| 18 | `overall_output_tokens` | same-named `end_to_end` metric | exact integer `[0,1000000000]` |
| 19 | `overall_total_tokens` | same-named `end_to_end` metric | exact integer `[0,1000000000]` |
| 20 | `generation_estimated_cost_usd_micros` | `end_to_end.generation_estimated_cost_usd` | half-even USD-micros integer `[0,1000000000000]` |
| 21 | `generation_actual_cost_usd_micros` | `end_to_end.generation_actual_cost_usd` | half-even USD-micros integer `[0,1000000000000]` |
| 22 | `evaluator_estimated_cost_usd_micros` | `end_to_end.evaluator_estimated_cost_usd` | half-even USD-micros integer `[0,1000000000000]` |
| 23 | `evaluator_actual_cost_usd_micros` | `end_to_end.evaluator_actual_cost_usd` | half-even USD-micros integer `[0,1000000000000]` |
| 24 | `overall_estimated_cost_usd_micros` | `end_to_end.overall_estimated_cost_usd` | half-even USD-micros integer `[0,1000000000000]` |
| 25 | `overall_actual_cost_usd_micros` | `end_to_end.overall_actual_cost_usd` | half-even USD-micros integer `[0,1000000000000]` |

For an evaluated quality or USD value, the exporter parses the exact persisted JSON number token as
an arbitrary-precision decimal, rejects a non-finite or out-of-canonical-domain value, multiplies by
`1000000`, and rounds to an integer with IEEE-754 decimal `ROUND_HALF_EVEN`. It does not first
convert through binary floating point, display formatting, or a rounded canonical summary. The
integer result must satisfy the DTO bound. Canonical quality-gate comparisons remain governed by
PAE-024 and are not changed by this export-only conversion.

### Summary truth oracle

The summary is derived from the mapped case metrics for this exact invocation. `summary_status`,
membership, metric statuses, evaluated/missing/passed counts, integer token/latency/repair facts, and
histogram facts are checked against the same strict PAE-028 summary. PAE-028 decimal quality/rate/cost
values are independently rederived from the exact raw Decimal case tokens under PAE-028; DTO
millionths/USD-micros values are independently derived from the already mapped per-case integers
under the rules below. The projector requires both source-domain and mapped-domain oracles to pass,
but never compares `round(sum(raw)*1000000)` with `sum(round(each_raw*1000000))`, nor a rounded raw
mean with a mean of mapped millionths. Thus each representation remains exact for its own formula
without a double-rounding contradiction. DEO-only stage counts, quality means, verification rate,
and per-scope cost totals are computed from the canonical cases. This is Agent truth; the consumer
validates only parent DTO structure and never recomputes it.

- `stage_status_counts` has the seven stage keys in stage order. Each value is exactly
  `{passed_count,failed_count,not_evaluated_count}`; counts are exact occurrences and sum to
  `case_count`.
- The seven `boolean_rates` keys in order are `retrieval_hit_rate`, `sketch_adherence_rate`,
  `first_compile_success_rate`, `final_compile_success_rate`, `repair_converged_rate`,
  `verification_success_rate`, and `explanation_chain_complete_rate`, sourced respectively from
  case metrics 0, 3, 4, 5, 7, 8, and 9.
- A boolean rate is exactly
  `{status,evaluated_count,missing_count,passed_count,value_millionths}`. Counts are occurrences;
  `passed_count` counts strict true. For a nonzero evaluated count,
  `value_millionths=round_half_even(passed_count*1000000/evaluated_count)` using exact integer
  rational arithmetic. With zero evaluated count it is null.
- `quality_rates` has exactly `draft_quality_rate` then `sketch_quality_rate`, sourced from mapped
  case metrics 1 and 2. Each is exactly
  `{status,evaluated_count,missing_count,value_millionths}`. For a nonzero evaluated count, value is
  exact half-even rounding of the arithmetic mean of the already mapped case millionths integers;
  otherwise it is null.
- `scalar_aggregates` has exactly, in parent order, `repair_rounds_total`, `latency_p50_ms`,
  `latency_p95_ms`, the nine generation/evaluator/overall token totals, and the six
  generation/evaluator/overall estimated/actual USD-micros totals. Every value is exactly
  `{status,evaluated_count,missing_count,value}`. Totals are exact sums of mapped evaluated integers.
  Latency percentiles sort evaluated `latency_ms` integers and use nearest-rank index
  `ceil(p*n)-1` for `p=0.50` and `p=0.95`; with no evaluated latency the value is null.
- Nonnull `repair_rounds_total` is in `[0,64000]`; each latency percentile is in
  `[0,86400000]`; each token total is in `[0,1000000000000]`; and each USD-micros total is in
  `[0,1000000000000000]`. Every evaluated/missing/passed/stage count is an integer in
  `[0,case_count]`; every nonnull boolean/quality millionths value is in `[0,1000000]`.
- `repair_rounds_histogram` is exactly `{status,evaluated_count,missing_count,buckets}`. With one or
  more evaluated values, `buckets` is exactly 65 integer counts for rounds `0..64` and sums to
  `evaluated_count`; with none it is null.
- Every aggregate uses `complete` only when `evaluated_count=case_count` and `missing_count=0`,
  `partial` only when both counts are positive and sum to `case_count`, and `not_evaluated` only
  when evaluated is zero and missing equals `case_count`. Nonnull summary values must remain within
  every DEO-006 bound; overflow fails the complete mapping rather than clipping or omitting data.

No parent object-limit decision changes this mapping. Agent creates all cases and scores implied by
the DTO regardless of whether the Observability consumer later rejects the valid DTO at the
DEO-010 5000-object boundary. Agent does not count, filter, shard, or drop values to fit that bound.

### Canonical material fingerprints and producer HMAC

Canonical JSON for material objects uses the existing PAE-026 object-key/string/array rules plus one
material-only numeric rule. Integers serialize as minimal base-10 with no plus sign or leading zero.
Every other JSON number is parsed directly from its persisted token as an arbitrary-precision finite
Decimal, rejects negative zero, and serializes in plain base-10 with no exponent, a required leading
zero before a fractional point, no trailing fractional zero, and no point for an integral value;
zero is exactly `0`. Binary floating point is never used. Therefore `0.1`, `0.10`, and `1e-1` have the
one material representation `0.1`, while malformed/non-finite values fail before hashing. This rule
changes no persisted PAE-026/PAE-029 record or summary byte; it applies only while constructing the
private PAE-031 material objects. For each strict case, `canonical_case_record_sha256` is lowercase
SHA-256 of those material-canonical JSON bytes of the complete schema-v3 case object. Define:

```text
material_prefix = ASCII("PALS-PAE-DEO-MATERIAL-v1")
frame(bytes) = uint32_big_endian(len(bytes)) || bytes
material_message(kind, object) = material_prefix
                                 || frame(UTF8(kind))
                                 || frame(canonical_json_bytes(object))
material_fingerprint = lowercase_hex(SHA-256(material_message))
```

`kind` is exactly `invocation|run|suite|case|comparability`. The five exact material objects are:

| Kind | Exact object keys and values |
|---|---|
| `invocation` | `origin`, `invocation_id`, `run_id`, `suite_id`, `suite_revision`, `suite_profile`, `suite_manifest_sha256`, `ordered_case_ids`, `ordered_case_record_sha256s` from the strict completed invocation |
| `run` | `origin`, `run_id`, `ordered_case_record_sha256s` from that same invocation |
| `suite` | `suite_id`, `suite_revision`, `suite_profile`, `suite_manifest_sha256`, `ordered_case_manifest_sha256s` in journal order |
| `case` | `case_ordinal`, `case_id`, `case_manifest_sha256`, `runtime_input_sha256`, `canonical_case_record_sha256` for that ordinal |
| `comparability` | `comparability`, `comparability_sha256`, with exact object/digest equality already proved across all cases |

The resulting names are `canonical_invocation_material_fingerprint`,
`canonical_run_material_fingerprint`, `canonical_suite_material_fingerprint`, one
`canonical_case_material_fingerprint` per ordered case, and
`canonical_comparability_material_fingerprint`. All are lowercase `hex64`, remain Agent-private,
and never enter the DTO, sidecar, log, output, marker, SDK argument, or remote object.

The producer key `PALS_DSP_PRODUCER_FINGERPRINT_KEY` is exactly 64 lowercase hexadecimal characters
decoded to 32 bytes. Parent framing is reproduced exactly:

```text
full_mac_hex = lowercase_hex(HMAC-SHA-256(key_bytes, message_bytes))
parent_frame(part) = uint32_big_endian(len(part.encode("UTF-8"))) || part.encode("UTF-8")

identity message_bytes = ASCII("PALS-DSP-FINGERPRINT-v1")
  || parent_frame(identity_kind)
  || parent_frame("deo-v1")
  || parent_frame(producer_fingerprint_key_version)
  || parent_frame(canonical_<identity_kind>_material_fingerprint)

comparability message_bytes = ASCII("PALS-DSP-COMPARABILITY-v1")
  || parent_frame("comparability")
  || parent_frame("deo-v1")
  || parent_frame(producer_fingerprint_key_version)
  || parent_frame(canonical_comparability_material_fingerprint)
```

`identity_kind` is exactly `invocation`, `run`, `suite`, or `case`. Parts are nonempty and receive no
normalization, trimming, case conversion, sentinel substitution, or alternate encoding. Full
lowercase `hex64` outputs populate the five DTO fingerprint families. Agent tests reproduce the
parent public case vector with framed-message SHA-256
`61802bf2ed76d44f8dc5a0f3722c42941b71b732e04f77776a703fccc86594f7` and full HMAC
`74ba3efef617f96edd73b67ff2a591a1c4239332fcd1c8fd50760be2af9340b2`, and the comparability vector
with framed-message SHA-256
`dd25ef4cb94ab7d6ed2a2015737271d394f90154f9155a93fbf53aede258eda2` and full HMAC
`58b9ad27eb0fc9325c9bed776aef64d8420190a0cd6e9c2de2166541007d4afb`. The parent projection vector
is consumed as a conformance vector but is not implemented in Agent production code.

### Producer key provisioning and binding

Normal provisioning and rotation request exactly 32 bytes from the operating-system CSPRNG and
lowercase-hex encode them. Caller-provided deterministic bytes are forbidden outside an injected
test CSPRNG boundary. Tests assert one 32-byte request and zero key/digest occurrence in artifacts,
outputs, evidence, or logs.

In `.local`, `PALS_DSP_PRODUCER_FINGERPRINT_KEY_VERSION` is mandatory and matches
`^[a-z0-9][a-z0-9._-]{0,31}$`. Agent resolves the mandatory absolute
`PALS_DSP_KEY_VERSION_REGISTRY_PATH`; Agent and Observability must observe the same host path and
inode for both `producer_fingerprint` and `langfuse_projection`. Agent binds only its
`producer_fingerprint` tuple but reads/writes the exact shared `pals.dsp-key-version-registry.v1`
document, sibling lock, sorted-entry, owner/mode/no-symlink, exclusive-lock, same-directory
temporary, file-fsync, atomic-replace, directory-fsync, 10000-entry, and no-empty-bootstrap contract
in DEO-019. Per-process, per-repository, relative, default, or fallback paths are forbidden.

In `.dev` and `.prod`, the producer deployment has one fixed full AWS Secrets Manager secret ARN
and one configured immutable `VersionId` for that exact environment/purpose. The nonsecret producer
key version is exactly that opaque AWS-enforced 32-through-64-character VersionId without
normalization. Agent invokes
`GetSecretValue(SecretId=<exact-full-ARN>,VersionId=<exact-VersionId>)`, omits `VersionStage`, and
requires exact response ARN and VersionId plus a secret value of exactly 64 lowercase hexadecimal
characters decoding to 32 bytes. Secret names, partial ARNs, aliases, stages, latest/version probes,
host registry files, local fallback, alternate secrets, or response mismatch fail before
publication. Rotation uses a new key and new immutable version; old/new ID spaces may coexist.

For every environment, reusing a purpose/version with a different key digest, malformed binding,
secret/configuration error, or persistence ambiguity fails before payload publication. Raw key
bytes and key digests never leave the secret loader/private registry. The nonsecret producer key
version appears only in its dedicated configuration/registry or Secrets Manager identity, the DTO
root, parent-authorized HMAC parts, and downstream parent-authorized metadata/marker/receipt fields;
Agent does not place it in arbitrary metadata, logs, sidecars, or approved test evidence.

### Exact bytes, privacy, and conformance

The Agent serializer emits compact UTF-8 JSON with no BOM or insignificant whitespace, preserves
the envelope/case/stage/metric/summary key and array orders above and in parent DEO, and appends
exactly one LF. Numeric values are JSON integers and booleans remain booleans. The complete payload
must be nonempty and at most 64 MiB. `batch_source_sha256` is lowercase SHA-256 of those exact bytes
including the final LF; the detached sidecar bytes are exactly `<hex64>\n` and never occur inside
the payload.

Payload and sidecar each publish through a mode-`0600` same-directory exclusive temporary, complete
write, file fsync, create-only no-replace installation, and parent-directory fsync. Payload
publication and its directory fsync complete before sidecar publication begins. Existing targets are
never replaced. There is no two-file transaction: interruption may leave neither, payload only, or
both. Apart from the exact newly-derived-byte replay comparison above, the producer makes no
consumability decision. Agent does not infer a digest from an existing file, repair or delete a torn
pair automatically, claim pair atomicity, or alter canonical data during retry/recovery. Matching-pair
validation belongs only to the Observability consumer.

The DTO contains no prompt/model output, theorem/Lean/diagnostics, explanation/clarification,
hidden reasoning, raw run/invocation/suite/case/user/project/conversation identity,
provider/model/revision, price object, artifact URI/path, endpoint, credential, arbitrary metadata,
canonical case/chain/comparability digest, canonical material fingerprint, raw key, or key digest.
Runtime stdout/stderr/logs contain no payload/source value, detached digest, fingerprint, key
version, key/digest, path, target, exception text, or fixture content. The output is a pseudonymous
projection, not an authentication protocol: digest verification proves only byte integrity; shape,
HMAC, parent vectors, fixture acceptance, cross-gate acceptance, or Langfuse read-back never proves
Agent origin, canonical correctness, or mathematics for operator-provided bytes.

Agent owns an independent hand-written `pals.dsp-export.v1` grammar and projector. Production code
does not import a validator, parser, generated schema, model, formula, or package from the parent or
Observability repository. Test-only parent vectors are consumed byte-for-byte without being used as
runtime validation code. The Agent producer baseline is generated only through the real projector
from one strict completed invocation containing passed, failed, and not-evaluated cases. It pins the
exact payload and sidecar bytes and proves membership, order, values, rounding, aggregates,
fingerprints, and publication through Agent mapping tests. Downstream use treats it only as
compatibility evidence.

The parent positive/negative vectors cover every DTO status/union/boundary, integer token,
histogram edge, all three HMAC vectors, privacy mutation, and complete-invocation mismatch. Agent
passes them with its independent grammar. The parent cross-repository gate then runs the same parent
vectors through both independent implementations and supplies the producer baseline bytes directly
to the consumer. Contract revision and detached digests must match exactly. No shared runtime
validator or fixture-copy drift is permitted.

## Worker Deadline, Acknowledgement, and Secret Contract

Before claim status affects control flow, the worker validates the exact PEX response envelope and
the exact typed internal resource for the requested kind and ID. `acquired|busy` requires the same
resource in `generating`; `terminal` requires the same resource in `completed|failed`; clarification
`not_ready` requires the same resource in `queued`; and `lease_too_short` permits only its
Spec-authorized typed resource or null case. Missing/additional fields, wrong identity/kind/state,
wrong content/diagnostic shape, or an otherwise inconsistent status is ambiguous: zero model calls,
zero terminal writes, and no acknowledgement.

For clarification, before acquisition the worker re-reads the referenced proof job and requires
exact `state="verified"`, nonblank Lean, and byte-identical theorem/Lean values to the typed PEX-011
worker input. Mismatch/absence performs no claim, model call, terminal write, or acknowledgement.
The explainer's clarification method also receives a required strict `verified` argument and rejects
anything except true before prompt construction, independently of the worker gate.

After parsing a valid `acquired` response, the worker conservatively sets
`lease_deadline = claim_request_started_at + lease_remaining_ms / 1000`; it never anchors the
server-reported duration at response receipt. Request, server transaction/commit, and response
latency therefore only reduce local usable lease and can never be added back. It then extends visibility and
samples `generation_started_at`. The final check requires
`lease_deadline - (generation_started_at + 3 * model_timeout_seconds) >= 30` seconds; equality
passes and any smaller value performs zero model calls, no terminal write, and no receipt deletion.
The worker does not refresh or estimate server time. Configuration preflight requires enough API
lease headroom for this measured elapsed time.

After that final lease-sufficiency check, the worker sets
`generation_deadline = generation_started_at + 3 * model_timeout_seconds`. Before each
of at most three model attempts, the explainer computes positive remaining monotonic time and gives
the OpenAI/Ollama transport `min(model_timeout_seconds, remaining_time)` as that attempt's timeout;
zero remaining time starts no call. After each transport return and after parsing it checks the
deadline again. OpenAI, Ollama, and PALS explanation/claim HTTP timeouts are total monotonic wall
deadlines from before DNS/connect through the complete bounded response body, not socket-inactivity
timeouts. Every success or HTTP-error response body is capped at exactly 1,048,576 bytes; reaching
that count before EOF is a typed oversized-response failure and no partial body is parsed. A
slow-drip header/body cannot extend the deadline. On timeout the transport is forcibly closed, any
killable helper is terminated and joined, and no request/model call continues in a background
thread or process. A call cannot run beyond its assigned transport timeout. Local
parsing/serialization overhead consumes the same total deadline. The API lease's additional 30
seconds is reserved for this overhead and the terminal write, not an additional model attempt.

If the monotonic deadline is reached, any output is discarded. The worker attempts a claimed
`failed` terminal write with fixed diagnostic code `pals.explanation_deadline_exceeded` or
`pals.clarification_deadline_exceeded`; no model text enters that diagnostic. A successfully
persisted completed/failed terminal result or API `terminal` deletes the receipt. `busy`,
`lease_too_short`, `not_ready`, claim/config/transport/visibility failure, ambiguous claim result,
deadline terminal-write failure, or any other unpersisted outcome does not delete it, so SQS
visibility timeout/DLQ redrive remains the recovery trigger.

`PALS_WORKER_SHARED_SECRET` must be nonblank and is sent only in the internal HTTP header. The
worker secret, claim UUID, SQS receipt handle, and their values are prohibited from public/internal
learner content, prompts, raw-attempt artifacts, diagnostics, exception messages, HTTP error-body
text retained by the client, logs, metrics, traces, evaluation history, and Langfuse payloads.
Telemetry has only closed labels `resource_kind=explanation|clarification`, claim outcome/error
token, model invocation outcome, deadline outcome, and receipt action; it contains no resource ID,
question, theorem, Lean, URL, header, or free-text exception.

## Parent PRX Import and Agent Runtime Ports

### Imported authority

This child normatively imports by reference the approved parent
`specs/proof-runtime-cross-repository` PRX-001 through PRX-008 and AC-001 through AC-008. The exact
proof-dispatch body/attributes, queue/deployment/trust objects, verifier request/readiness/
attestation/error objects, release-binding headers, status/error/outcome registries, metric names and
label domains are parent-owned. This child does not repeat their object definitions. A local type,
serializer, parser, fixture, generated model, or documentation snippet is conforming only when the
parent corpus accepts its exact bytes and semantics; it never becomes an alternate registry or
compatibility authority. Unknown, additional, legacy, aliased, or child-only shared tokens fail.

Agent imports only the ports it implements:

- PRX-002 receive/visibility/delete outcomes and the admitted proof-queue binding for PAE-035;
- PRX-003 verifier deployment binding, HTTP application contract, and response registry for
  PAE-017/PAE-020/PAE-036;
- PRX-005 `verifier_server` certificate/private-key plus shared CA references for PAE-036;
- PRX-004 receipt stop/resume order, PRX-006 Agent image/toolchain/property release-provenance
  contribution, PRX-007 child property mapping, PRX-008 ownership participation, and the applicable
  parent telemetry registry for PAE-037.

It does not import an API database capability or an Infra resource-management capability. Parent
external-operation kinds and non-Agent metric families may be parsed for conformance but have no
Agent dispatcher, persistence adapter, or provider implementation. Agent never queries provider/ECS/
SQS quiescence, constructs provider evidence, or persists a cross-repository cutover/effect result;
those are Infra-owned provider/effect ports and API-owned persistence under the parent contract.

### PAE-035 receipt and DSP lifecycle

The v1 proof worker calls `ReceiveMessage` only against the admitted parent queue URL with
`MaxNumberOfMessages=1`, `WaitTimeSeconds=20`, `VisibilityTimeout=900`, and
`MessageAttributeNames=["All"]`; it supplies no FIFO field or per-receive queue override. It processes
one returned receipt at a time. The exact internal lifecycle is
`receipt_blocked -> receiving -> validating -> claimed -> processing -> retained|terminal ->
deleted|delete_ambiguous`; `invalid` branches from `validating` to `retained`, and stop/cancel branches
from any nonterminal work state to `retained` then `receipt_blocked`. These are Agent-local behavior
tokens, not a parent DTO.

Validation occurs before proof-job-ID path encoding, API claim, artifact lookup, model call, status
write, or verification-result wait. It checks the parent-imported queue binding and complete v1
receipt exactly once against the same immutable receive snapshot. `received` is emitted only after
queue identity, body, two message attributes, body digest, `MessageId`, and `ReceiptHandle` pass.
Mutation or replacement of any value after validation is ambiguity and retains the receipt.

For a valid receipt, PAE-021 acquisition and every visibility extension use the current receipt
handle. `ChangeMessageVisibility` receives only the admitted queue URL, current handle, and the exact
PAE-021 integer timeout. A known failure or unknown/timeout response stops all later work, emits the
imported `visibility_failed` then `retained` outcomes, and performs no delete or visibility-shortening
call. Agent never sets visibility to zero and never substitutes a local retry timer for SQS.

The worker calls `DeleteMessage` at most once for a receipt and only after PAE-020/PAE-021 proves an
exact persisted terminal acknowledgement. A known successful SDK response emits `deleted`; timeout,
connection loss, process interruption, or indeterminate service outcome emits `delete_ambiguous` and
returns without another delete attempt. Every nonterminal, busy, stale, malformed, canceled-helper,
claim-lost, API-ambiguous, or artifact-ambiguous outcome emits `retained`. A later valid SQS redelivery
revalidates all parent bytes and uses a fresh claim UUID; it never reuses process memory, prior
`MessageId`, receipt handle, claim, order, or model/verifier result.

An invalid/versionless/wrong-queue message makes no API/model/artifact/verifier-related call, receives
no visibility extension, is never deleted, and is left for the parent-bound SQS redrive policy. Agent
does not consume, purge, move, or inspect the DLQ and never emits `redriven` from queue depth,
`ApproximateReceiveCount`, elapsed time, or operator assertion. Thus poison retention and eventual
redrive remain exact Infra queue behavior while Agent owns the required non-deletion.

PAE-034 proof execution uses the claim-fenced DSP flow after receipt validation. Each generated
candidate is checkpointed and submitted under the current API claim. The worker then renews and
refetches the authoritative same-target API resource; it does not open a verifier connection. A
persisted parent `verifier_compile_failed` outcome is an actual failed verification and may enter the
existing Route/Repair loop as that one fixed content-free compiler diagnostic. A persisted verified
resource must carry the exact PAE-036-produced attestation before it can terminate the loop, delete
the receipt, or open Explain/Clarify. API absence, stale state, or any other verifier-looking value is
ambiguous and retained; no local compile, cached status, benchmark, fixture, or model claim fills it.

### PAE-036 isolated HTTP verifier and readiness

The release verifier process binds only the parent deployment endpoint's private DNS host and port
18117. It exposes only the imported `GET /ready` and `POST /v1/verify`; every method/path/header/body/
framing/size/status/response-binding decision is the imported PRX-003 contract. There is no Unix
socket, plaintext listener, loopback sidecar, alternate port/path, redirect, compatibility route,
debug compile route, or operator-supplied attestation.

Startup order is exact: load and validate the complete admitted release/deployment binding; fetch
and construct the complete mTLS context; attest verifier image identity; attest the PAE-017
toolchain manifest and compiler boundary; create a one-slot nonqueued execution semaphore; perform
one positive capacity self-check without compiling caller Lean; then begin listening. A failed or
unknown step binds no listener and cannot return ready. `GET /ready` returns imported success only
while the same release/deployment/trust/image/toolchain identities remain current and capacity is
configured positive. Occupation of the sole slot does not change startup readiness; a conforming
POST received while occupied returns only imported `verifier_unavailable` before a compiler child
starts.

For POST, mTLS and HTTP framing complete first; release/deployment request headers are validated
second; the strict imported request is validated third; current image/toolchain/root/Git attestation
is repeated fourth; and only then may the server acquire the one slot and start PAE-017. Binding
mismatch and invalid request make zero compiler calls. A request-specific setup or Lean nonzero
result after proven cleanup becomes only imported `verifier_compile_failed`; no raw diagnostic,
stdout, stderr, path, source, setup JSON, process identity, or timing enters the response. The
300-second untrusted-work deadline becoming final after compiler start yields only imported
`verifier_timeout`. Cleanup uncertainty, server crash, response-write ambiguity, or inability to
prove descendant absence sends no substitute body and terminates the service; the API caller can
classify only the imported transport failure.

HTTP 200 is constructed only from the validated request snapshot after actual Lean exit zero and
complete PAE-017 cleanup. PAE-020 computes the exact Lean digest from those immutable request bytes
and emits the imported attestation with the same proof-job ID and artifact URI. The response is not
cached, replayed across requests, inferred from process exit alone, or written before cleanup.
Readiness, image/toolchain attestation, a benchmark match, fixture, old artifact, model output, local
Lean, or status 200 alone cannot create it.

### mTLS secret consumer ports

Agent implements exactly three server-side read-only secret consumer ports:
`VerifierServerCertificatePort`, `VerifierServerPrivateKeyPort`, and
`VerifierCaCertificatePort`. Each receives only its exact tuple from the parent-imported admitted
`verifier_transport_trust` object and makes one
`GetSecretValue(SecretId=<full ARN>,VersionId=<exact VersionId>)` call through the admitted private
Secrets endpoint at startup or an explicitly admitted rotation. It omits stage/name/alias/fallback,
requires exact response ARN/VersionId and `SecretBinary`, validates every parent PEM/DER/SPKI/SAN/
CA/key-match/revocation property in memory, and clears SDK response buffers after constructing the
TLS context.

The verifier role may read only its leaf certificate, leaf private key, and the shared CA. It cannot
read the reconciler client leaf/key or any barrier, database, model, worker, producer, release-signing,
or alternate secret. Agent does not create/version/rotate/revoke a secret, KMS key, policy, role, or
endpoint. A partial/one-sided/mismatched rotation never replaces the active context or preserves a
fallback context; receipt/gate activation remains blocked until a higher-sequence admitted release
provides one complete valid set. No runtime refresh occurs outside startup/rotation.

### PAE-037 lifecycle, properties, artifacts, and commands

The exact worker entrypoints are `pals-agent proof-worker-v1 --receipt-mode blocked` and
`pals-agent proof-worker-v1 --receipt-mode active`; the option occurs exactly once and no other token
selects receipt mode. Missing mode defaults to no action and exits configuration failure. `blocked`
performs configuration/image/queue-binding validation but makes zero `ReceiveMessage` calls.
`active` additionally requires the exact admitted release ID, worker image digest, and parent v1
queue binding supplied by deployment configuration. Any absent/mismatched/unadmitted value remains
blocked. `SIGTERM`/`SIGINT` stops new receives immediately, cancels and joins current helpers, retains
uncommitted work, and exits only after no Agent-owned spend remains. Resume is a fresh admitted
candidate process; an old process never toggles itself back to active.

Infra owns old-principal SQS explicit denial and candidate task/service start. Agent participates by
shipping no queue URL override or direct endpoint, making old/unversioned builds reject the v1
binding, and proving the blocked command and stop path make zero receives. Queue-policy denial,
zero-fleet evidence, admission, gate opening, candidate start, and rollback order remain parent/Infra/
API authority. Agent cannot simulate or declare them.

The child-owned canonical JCS-plus-LF artifact is exactly
`pals_agent/proof_runtime/behavior_properties.v1.json`. Its schema version is
`pals.agent-proof-runtime-behavior-properties.v1`; its requirement set is exactly
`PAE-035|PAE-036|PAE-037|PAE-038`; and its closed property IDs are exactly:

```text
pae.clarification_dispatch.marker_validation.v1
pae.clarification_dispatch.receipt_validation.v1
pae.clarification_dispatch.uncertain_terminal.v1
pae.dsp.claimed_execution.v1
pae.proof_dispatch.poison_retention.v1
pae.proof_dispatch.receipt_lifecycle.v1
pae.proof_dispatch.receipt_validation.v1
pae.release.old_worker_denial.v1
pae.verifier.compiler_truth.v1
pae.verifier.http_readiness.v1
pae.verifier.mtls_secret_consumer.v1
```

The eleven properties map exactly as enumerated under the PAE-035 through PAE-038 acceptance
contract, to one or more of those four requirement IDs and no other owner; rows and arrays are
ASCII-sorted and duplicate-free. Unknown/missing/cross-owner/unmapped properties fail the child
contract gate. This is only the PRX-007 Agent behavior-property namespace, not a copy or extension
of any parent DTO/outcome/error/telemetry registry. The exact artifact is packaged in both
Agent-owned images, and each image records its raw-file SHA-256 in OCI label
`org.pals.agent.behavior-properties.sha256`. The worker OCI digest, verifier OCI digest, this label,
`/app/lean-verifier-toolchain.manifest`, and `verifier_toolchain_sha256` are the only new Agent release
artifacts and are the complete Agent-owned contribution to PRX-006 release provenance. Agent creates
no parent release archive, signature, Infra bundle, provider/quiescence evidence, durable cutover/effect
sink, or admission row.

The repository-local PRX commands are exactly:

```text
python -m pytest -q tests/contract/test_proof_dispatch_v1_contract.py
python -m pytest -q tests/integration/test_proof_dispatch_v1_localstack.py
python -m pytest -q tests/contract/test_isolated_verifier_http_v1_contract.py
python -m pytest -q tests/integration/test_isolated_verifier_http_mtls.py tests/integration/test_lean_isolation_docker.py
python -m pytest -q tests/story/test_proof_runtime_v1_story.py
python -m pytest
python -m ruff check .
python -m mypy pals_agent tests
```

The first five commands are mandatory focused gates; the final three are full repository gates. No
skip, xfail, fake SQS, fake compiler, plaintext server, local HTTP substitute, recorded mTLS result,
or generated success artifact satisfies their Green/release oracle. `README.md` shall contain
`Proof Runtime v1 Operations` with the exact entrypoints, commands, receipt/DLQ/stop/resume/
redelivery/rollback behavior and content-free evidence. `SECURITY.md` shall contain
`Isolated Verifier mTLS Boundary` with secret consumer ports, caller/capability separation, toolchain/
compiler limits, rotation failure, and no-fallback response. Neither document contains a credential,
ARN/VersionId value, endpoint value, proof content, or claim of API/Infra ownership.

Agent emits only the applicable parent-imported
`proof_runtime_queue_messages_total{outcome}` and
`proof_runtime_verifier_requests_total{outcome}` combinations. It emits queue `redriven` only from
an imported authoritative provider event, never from Agent inference; absent such a port, Agent does
not emit that combination. IDs, receipt handles, ARNs, versions, digests, paths, principals, proof/
model/compiler content, and free-form reasons are forbidden labels and logs. Existing PAE stage/model/
claim metrics remain child-owned and do not alias a parent metric.

## Acceptance Criteria

### PAE-001 through PAE-006

- A verified Lean fixture produces a structured Japanese explanation whose every excerpt exactly
  matches the declared separator-preserving source slice. Known-answer fixtures cover CRLF, LF, CR,
  U+0085, U+2028, U+2029, mixed separators, interior empty lines, and terminal separators without
  split/join normalization.
- An unverified fixture, malformed references after the retry budget, or malformed JSON produces
  an explicit generation failure and no substitute explanation.
- A clarification for one section includes an overlapping reference; another section or an
  unknown section is rejected. Direct `verified=false` clarification and worker proof/input
  state/code mismatch both make zero model calls.
- Serialization tests prove that prompts, raw output, reasoning, and diagnostics are absent from
  public content.

### PAE-007 through PAE-014

- Successful, failed, and partially populated artifacts produce all seven stages in canonical
  order with honest statuses.
- Before proof verification succeeds, a missing explanation is `not_evaluated`; an unavailable
  semantic judge is always `not_evaluated` without changing deterministic results.
- For a verified flow, a missing explanation is an evaluated failure. A required clarification
  that is omitted, empty, malformed, non-overlapping, or unsupported by exact Lean references is an
  evaluated failure; a case that does not request clarification leaves only clarification metrics
  `not_evaluated`.
- An explanation attached to absent, failed, or non-boolean proof verification is
  `not_evaluated`, even when all cited lines happen to match the generated Lean text.
- A repair stage with any mandatory provenance key absent is `not_evaluated`, even when a recorded
  final attempt compiled successfully. Any present null/wrong-typed/invalid value is `failed`.
- Present repair provenance passes only with exact attempt numbering, all preceding attempts
  failed, first success at the final attempt, route/count/top-level code and verification equality,
  and matching structured termination event/reason/source/budget. Negative fixtures independently
  violate every rule; no free-form diagnostic is used to infer a reason.
- Two suite runs append two immutable JSONL records and a summary computes stage pass rates and
  numeric averages from both.
- Semantic retrieval can pass without exact text equivalence when candidate and score evidence
  are present.
- Langfuse-disabled and Langfuse-unavailable runs still persist the complete canonical result.
- Prompt-capture tests place all three exact smoke sentinels, strategies, relevant IDs, compile
  oracle, and rubric dimensions in evaluator-only fixtures. They are absent from every initial,
  selector-retry, and routed-repair generation prompt, present in the correct independent evaluator
  prompts only after runtime termination, and evaluator output cannot invoke a pipeline callback.
- Real schema-v3 case and `pals.evaluation-summary.v1` serializer fixtures remain canonical PAE
  evidence and are not themselves DEO exchange artifacts. Export failure leaves history, summary,
  journal, comparison, and gate/exit results byte-for-byte unchanged; every consumer/projection
  assertion remains owned by parent DEO and the Observability child rather than duplicated here.

### PAE-018

- The authorized ignored local file `.pals-agent-artifacts/evaluations/history.jsonl`, represented
  by a five-line real-regression fixture with source SHA-256
  `b32d19c0a6f66b5140c37d161d83bf291a1fa969a82b5e59d5bcdc07c43879fa` fails ordinary strict load
  at line 5 without changing a byte, then explicit `semantic-comments-v2` migration creates an exact
  digest-named backup, changes exactly four semantic comments to null, retains five records and all
  other JSON values, and makes `evaluation-history` succeed.
- Wrong-digest, non-applicable, unrelated-invalid-field, backup mismatch,
  temporary-write/file-fsync/replace/directory-fsync, migration-fence, and concurrent append fault
  tests all fail closed without deleting or silently ignoring history. An extant migration fence
  also makes ordinary load/summary fail before returning records.

### PAE-019

- With generation `openai/generation-model`, complete credential-free evaluator configuration
  `ollama/evaluator-model@sha256:evaluator-v1` at loopback HTTP builds only that Ollama evaluator,
  performs its requests with `evaluator-model`, and persists the exact source prefix
  `semantic_judge:ollama/evaluator-model@sha256%3Aevaluator-v1:` followed by each fixed rubric,
  without persisting the endpoint.
- With all five evaluator variables absent, semantic evaluation makes zero transport calls,
  preserves every deterministic metric/status byte-for-byte, and appends only `not_evaluated`
  semantic metrics whose source is `semantic_judge:unconfigured:<rubric_revision>`.
- The five-variable presence matrix accepts only all-absent, complete OpenAI, and credential-absent
  complete Ollama. OpenAI evaluator credential bytes and secret binding differ from generation
  credentials. A recording transport proves each score came from one new evaluator-only request
  after runtime termination and rejects a generation response/request ID, cache entry, batch member,
  tool result, or missing/duplicate call-separation record.
- Every partial tuple, unknown provider, malformed model/revision/base URL, stray/wrong-provider/
  malformed credential, non-loopback HTTP, mixed loopback resolution, redirect, proxy/cross-origin
  request, and evaluator normalized identity equal to any non-null contributing generation identity
  fails before a judge request. Matrix cases cover exact `localhost`, IPv4 loopback, IPv6 loopback,
  remote HTTPS, remote HTTP, explicit/default ports, path/query/fragment/userinfo, and redirect origin.
  OpenAI uses only `PALS_SEMANTIC_EVALUATOR_API_KEY` as a Bearer credential at the exact normalized
  configured origin; generation credentials are planted as sentinels and never appear on evaluator
  transport. Ollama and unconfigured modes reject that credential.
- Identity tests use at least two distinct non-null contributing generation roles plus one null/zero-
  call role. Exact case differences in provider/model are rejected by ASCII-lower normalization;
  different revision or endpoint cannot make the same normalized provider/model independent. Every
  contributor must differ, while a noncontributing null role adds no comparison member.
- The exact release command creates one fresh strict mode-`0600` evidence object, exits zero, and
  yields one unskipped JUnit pass only when the complete PAE-034 real flow, verified Lean/artifact,
  explanation, required clarification, reference validation, all four direct-threshold rubric
  dimensions, normalized identity and distinct-call separation, and all five content/toolchain
  digests satisfy the closed oracle. Every stale/skip/fake/missing/
  false/unevaluated mutation fails. No test may satisfy evaluator configuration by setting only
  generation variables.

### PAE-034

- OpenMath tests accept only a parsed, alpha-renamed, symbol-normalized, validated proposition. They
  prove at most three total real calls, exact prior diagnostics on calls 2/3, first-valid stop, and
  zero retrieval/downstream calls after final invalidity. Lexical/exact/benchmark/canned/mock/
  template/last-good substitutions are independently rejected.
- A real PostgreSQL catalog with at least eight eligible rows records one pgvector cosine `LIMIT 8`
  query with no cutoff. Stable ties, canonical structural evidence, and a real `draft`-role relevance
  call produce each allowed output size 0..4. Zero context still makes one ordinary Draft call;
  database/embedding/structural/rerank failures never use packaged/in-memory/exact/lexical fallback.
- Graph tests prove Draft -> Sketch -> Prove -> isolated Lean, then every Route choice re-enters the
  selected node through one Repair call and all downstream nodes. Only successful isolated Lean plus
  durable checkpoint produces verified; Explain and section Clarify consume that artifact only.
- Registry mutation tests reject every missing/extra/reordered/duplicate role, non-OpenAI provider,
  non-`gpt-5.4-mini-2026-03-17` model, environment provider/model selector, response identity mismatch, failover,
  fallback, or alias before release work.
- The exact live command observes all eight actual OpenAI roles, real pgvector fetch count 8,
  context count 0..4, at least two complete failed-verification Route/Repair cycles, one later durable
  verified artifact, Explain, selected-section Clarify, and one distinct evaluator request. Every
  fixture/mock/recorded/synthetic/template/cached/patched success mutation fails release.

### PAE-035 through PAE-038

- Parent-corpus contract tests accept only the imported `pals.proof-job-dispatch.v1` body,
  attributes, digest, queue identity, `MessageId`, and current `ReceiptHandle`. Every single-field
  mutation performs zero API/model/artifact/verifier-related calls, never deletes or shortens
  visibility, and remains available for Infra redrive to the parent-bound DLQ.
- LocalStack stories prove one-at-a-time receipt handling, initial 900-second visibility, PAE-021
  renewal/extensions, immediate delete for exact failed/canceled proof, verified-receipt retention
  through the distinct explanation claim, delete only after an exact same-target terminal
  completed/failed explanation resource, ambiguous delete
  retention, poison retention, redelivery with a fresh UUIDv4 claim, and no FIFO/order/uniqueness
  inference.
- Parent-corpus HTTP tests prove only TLS-1.3 mTLS `GET /ready` and `POST /v1/verify` on private
  port 18117, exact request/header/body/response/status/framing behavior, one-slot admission,
  readiness truth, the 300-second compile/cleanup wall, and no response after cleanup uncertainty.
  Plaintext, Unix socket, alternate route/port, worker caller, fixture, cache, lexical success, and
  status-only success all fail closed.
- Secret-consumer tests prove the server fetches only its exact full-ARN plus immutable-VersionId
  `SecretBinary` values through `VerifierServerCertificatePort`,
  `VerifierServerPrivateKeyPort`, and `VerifierCaCertificatePort`, keeps bytes in memory, and
  cannot access the API client certificate/key, database, SQS, model, deployment resource, or
  opposite-role secret.
- Release tests prove receipt remains blocked until parent admission, an old/unversioned worker
  cannot resume or consume, rollback uses only a higher-sequence admitted compatible release, and
  Agent code never creates/mutates API PostgreSQL or Infra resources.
- The exact focused commands, README/SECURITY headings, worker/verifier images, toolchain manifest,
  behavior-property artifact, OCI digest label, PRX-006 release-provenance contribution, and closed
  content-free telemetry below exist and agree. Tests prove Agent does not query provider/ECS/SQS
  quiescence and has no durable cutover/effect or API persistence adapter. Every property row has one
  of these exact mappings:
  `pae.dsp.claimed_execution.v1 -> PAE-035`,
  `pae.proof_dispatch.poison_retention.v1 -> PAE-035`,
  `pae.proof_dispatch.receipt_lifecycle.v1 -> PAE-035,PAE-037`,
  `pae.proof_dispatch.receipt_validation.v1 -> PAE-035`,
  `pae.clarification_dispatch.receipt_validation.v1 -> PAE-038`,
  `pae.clarification_dispatch.marker_validation.v1 -> PAE-038`,
  `pae.clarification_dispatch.uncertain_terminal.v1 -> PAE-038`,
  `pae.release.old_worker_denial.v1 -> PAE-037`,
  `pae.verifier.compiler_truth.v1 -> PAE-036`,
  `pae.verifier.http_readiness.v1 -> PAE-036`, and
  `pae.verifier.mtls_secret_consumer.v1 -> PAE-036`.
- Parent PRX-009 corpus and real queue/API races prove exact clarification-vs-proof routing, canonical
  empty application attributes, marker validation, fresh claims, visibility-before-model, and
  receipt retention on every invalid/busy/not-ready/ambiguous outcome. A same-target
  `dispatch_uncertain` input causes zero generation claim/model/update and permits only exact-receipt
  deletion; delete ambiguity retains it.

### PAE-020

- The PAE-036 HTTP verifier server alone emits the exact parent-imported attestation after real
  compiler success and complete descendant cleanup. Its request/job/artifact/digest bindings pass
  the parent positive and negative corpus byte-for-byte.
- Worker tests prove no attestation constructor, signer, fixture, cache, verifier client, or
  worker-synthesized verified callback exists. The worker submits candidate/artifact values to the
  API and accepts verification authority only from a fresh exact persisted API resource.
- Intermediate, failed, canceled, malformed, ambiguous, mismatched, or unattested API resources
  cannot authorize explanation or receipt deletion.

### PAE-021 through PAE-025

- Two duplicate proof workers receive different valid Lean candidates. Exactly one API claim is
  acquired and one pipeline runs; the loser makes zero generation/route/verifier calls. Exact
  same-final-claim replay is idempotent, while stale or conflicting Lean/attestation gets 409 and
  cannot reach explanation. The winner refetches and explains byte-identical persisted Lean.
- Acquisition contract tests accept only exact `acquired|busy|terminal`; renewal tests accept only
  exact `renewed|terminal`. Every acquisition/renewal `lease_too_short`, wrong union member,
  wrong lease nullability, cross-target resource, or extra/missing key is malformed, starts no later
  spend/update, and retains the receipt. Exact terminal failed/canceled deletes the proof receipt;
  exact terminal verified ends proof control only after full PAE-020 validation, retains the
  receipt, and can trigger only a separately claimed explanation. The receipt is deleted only after
  that explanation is exact same-target terminal completed/failed. Terminal proof response grants
  no proof spend.
- An injected monotonic/killable-transport matrix covers renewal before every initial generation,
  each individual selector retry, every repair generation, every candidate/artifact API submission,
  and every authoritative verifier-result API refetch. Prior-lease and
  spend margins just above/exactly/below 30 seconds, renewal immediately before/exactly at/after API
  expiry, delayed/ambiguous renewal, visibility failure, and cancellation/join failure all follow the
  exact start/no-start and no-later-call rules. A takeover story advances to expiry and proves the
  first worker's model/API helper and descendants were stopped by `lease_deadline-30`, so two
  claims never have concurrent spend.
- A real agent `Diagnostic` carrying route-selection `metadata` serializes through the actual API
  Pydantic request without 422 and only the exact five fields remain. Status projection preserves
  every candidate's code, typed diagnostics, phase/checkpoint, and route while table-driven raw
  prompts/outputs/rationales/provider exceptions/endpoints/stdout/stderr are absent from the wire,
  API row, public GET/SSE, logs, and error bodies.
- Clarification input with Lean ending in LF passes the exact bytes to proof comparison, parser, and
  model. A terminal same-target input acknowledges only after full schema validation; wrong ID,
  missing/additional field, malformed content, or cross-proof terminal input is unacknowledged and
  causes no claim/model/update/delete.
- `math.nextafter(0.80,0.0)` produces semantic pass false and exact `0.80` true when dimension floors
  pass. No tolerance helper is called.
- For schema v2 and v3, table-driven unknown run/stage/metric/candidate fields, arbitrary metric
  name/source/kind, duplicate metric, invalid semantic provenance, and contradictory persisted
  status fail at the exact JSONL line without returning earlier records or changing history bytes.
  The explicitly migrated five-line v2 history remains readable.

### PAE-026 through PAE-029

- The packaged `smoke-v1` manifest contains exactly the three PAE-026 IDs/prompts in order. A spy
  pipeline receives only those fresh `BenchmarkProblem` values. The exact manifest, rubric, and
  three case digests equal the literals in this Spec; relevant IDs, evaluation cutoff top-k 5,
  compile oracle, strategy,
  rubric dimensions/formula/floors, expectations, and sentinels match exactly. Evaluation-only
  values appear only in post-runtime evaluator inputs and never in captured generation prompts.
- One real or explicitly unevaluated case record exposes ranked top-k IDs/scores and expected hit,
  draft/sketch independently pinned judge evidence, post-runtime sketch adherence, first/final
  compile and one exact transition category, repair rounds/convergence, measured latency, complete
  generation/evaluator/overall token evidence, estimated/actual cost evidence, prompt separation,
  explanation chain, and the exact case/run provenance. Tests do not use a fake successful
  model/compiler response as live success evidence.
- Cross-field provenance mutations independently change every model-call scope, all eight allowed
  generation roles, every forbidden/aliased role, provider, model, ordinal and row cardinality;
  every comparability generation-role pair and
  evaluator null/non-null identity; and each prompt-channel generation/evaluator count. Only exact
  provider/model identity and exact per-scope/role cardinality passes; every mismatch rejects the
  entire live record before summary, comparison, gate, or export.
- Missing judge, one missing model-call usage object, missing/partial price tuple, and absent
  provider cost, prompt capture, agent/toolchain digest, or chain evidence independently produce
  null/`not_evaluated`; none is serialized or summarized as zero, false completeness, state
  accuracy, or a passed gate. A nextafter-below semantic score also fails the gate.
- Aggregate fixtures prove exact evaluated/missing counts, hit/compile/convergence rates,
  four-category compile uplift and repair-round distributions, nearest-rank p50/p95, separate and
  overall complete token/cost totals, chain completeness, partial/not-evaluated propagation, and
  passed/failed/not-evaluated pure status math. JSON and Markdown render the same typed values and
  report the exact maximum repair budget.
- Live CLI tests use a recording real runner boundary, not synthetic success injection. A complete
  journal with all three current cases exactly once and matching live origin/digests is the only path
  to exit 0/1/2. Duplicate run/invocation case pairs, a stale running journal, foreign record,
  interrupted case, operational exception after one append, append/journal/summary fsync failure,
  provenance drift, and missing manifest case all retain prior history and exit 3; SIGINT/SIGTERM
  leave running/interrupted audit evidence and return 130/143. Pure synthetic aggregates cannot call
  live authorization or produce CLI exit 0. Parent smoke/full/compare targets invoke the documented
  commands, and compare rejects any suite/case/generation/evaluator/rubric/price/budget/source/
  toolchain drift.

### PAE-030 through PAE-033

- A strict completed invocation containing passed, failed, and not-evaluated cases produces one
  ten-key envelope with exactly all journal cases in `expected_case_ids` order, ordinals
  `0..N-1`, unique case fingerprints, one matching ordered summary fingerprint list, all seven
  stage statuses, and all 26 metrics. Omission, pass-only filtering, reordering, duplication,
  foreign/mixed invocation, summary mismatch, case count 0/1001, or source status/value mismatch
  fails before key binding or publication and leaves canonical bytes unchanged.
- Table-driven Agent truth-oracle tests cover every metric source, evaluated/not-evaluated branch,
  strict boolean/integer domain, exact half-even tie on both sides and tie-to-even for quality and
  USD-micros, each parent min/max/overflow, seven stage-count triplets, seven boolean rates, two
  quality means, every scalar total, nearest-rank p50/p95, all 65 repair buckets, and
  complete/partial/not-evaluated summary status. An intentionally inaccurate but shape-valid DTO is
  rejected by mapping tests while remaining acceptable to the independent shape parser.
- Cross-representation tests include two costs of exact Decimal `0.0000005` and prove the PAE-028 raw
  total equals the raw Decimal sum while the DTO total equals the sum of per-case half-even micros;
  they never compare the DTO total to a once-rounded raw aggregate. Equivalent numeric tokens
  `0.1`, `0.10`, and `1e-1` produce one private material byte sequence/fingerprint without changing
  persisted canonical record bytes.
- Known-answer material tests pin every exact material object and byte frame, detect mutation of
  each identity/case record/order/comparability field, reject duplicate case outputs, and reproduce
  the parent producer identity and comparability framed-message SHA-256 and full HMAC vectors. The
  projection vector is accepted as a test vector without adding projection production code.
- Provisioning tests prove one OS-CSPRNG request for exactly 32 bytes and no normal caller-supplied
  key. `.local` tests prove Agent and Observability resolve one absolute shared registry inode,
  exact registry grammar/order/modes/lock/fsync, same-key reuse, and same-version/different-key
  failure. `.dev`/`.prod` tests prove exact full-ARN plus VersionId request/response binding and
  reject name/partial ARN/alias/stage/latest, mismatch, host registry, local/alternate fallback,
  malformed hex, wrong decoded length, and key/digest leakage.
- Exact-byte tests cover compact JSON, key/array order, UTF-8, BOM, final LF, trailing byte,
  64-MiB, payload digest including LF, exact 65-byte sidecar, mode `0600`, both per-file atomic
  create-only commits, payload-before-sidecar order, every temporary/file-fsync/no-replace/
  directory-fsync fault, and absent/exact/mismatched/torn target states. CLI tests prove exact option
  grammar, component-by-component no-follow effective-UID-owned mode-`0700` pinned directory,
  deterministic fingerprint names, exact published/replay JSON, fixed exit-2/exit-3 codes,
  empty/private-safe output, and no canonical mutation. Exact-existing
  bytes return `already_published` without a write; every partial/different target returns
  `publication_conflict` without change; replay additionally requires exact owner/mode/link count.
  Producer replay is not pair acceptance. No case claims pair
  atomicity, digest inference, origin, or truth.
- Recursive privacy canaries prove every prohibited identity/content/secret family is absent from
  payload, sidecar, stdout, stderr, logs, errors, evidence, and documentation. Only the exact
  producer version DTO/configuration/registry-or-Secret-identity/HMAC slots are allowed; raw
  material fingerprints, keys, and key digests are absent everywhere outside their private
  computation/binding boundary.
- A source/import audit rejects any shared parent/Observability runtime validator, parser, schema
  package, generated model, or formula path. The independent Agent grammar passes the complete
  parent positive/negative/HMAC vector corpus. The real-projector baseline is byte-stable and is
  consumed byte-for-byte by the cross-repository gate, where fixture acceptance is labeled
  compatibility only and Agent mapping tests remain the sole canonical truth/origin oracle.
- Parent tasks 5 and 6 must publish the exact positive/negative/HMAC vector corpus before an Agent
  task consumes it. Agent baseline generation satisfies the producer portion of parent task 11 by
  handing exact payload/sidecar bytes, detached digest, and case count to the parent; Agent never
  computes planned remote objects or writes the parent's four-field evidence record.
- Historical parent and child task states authorize nothing for current bytes. Current readiness is
  `Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64 -> PRX T011`, with
  Task 83 as historical PRX provenance and both current review stages consuming or
  independently revalidating the external exact current DEO Task-48 report: exact approved PFI identity is
  pinned above; TDG, EXP, PJR, PWA, and
  API PEX must complete their ordered approval and distinct post-promotion reviews; Task 73 records
  the exact approved EXP/PJR/PWA/API PEX identities pinned by `SPEC-CHG-2026-07-27-PAE-UPSTREAM-AUTHORITY-IMPORTS` requirements/design/tasks identities and completes
  the import-only alignment before review. The draft child then requires a fresh pre-promotion
  technical verdict `IMPLEMENTATION READY`, CRITICAL=0, HIGH=0, and no material question, explicitly
  marked non-authoritative while status remains draft. It is followed by an explicitly authorized
  status-only promotion and exact ownership PASS. Current Task 64 then performs the distinct fresh
  post-promotion whole-child
  verdict exactly `IMPLEMENTATION READY`, CRITICAL=0, HIGH=0, and no material question while its
  checkbox remains `[ ]`; only the inverse-proved single-token Task-64 marker publication
  `[ ]` to `[x]` may then complete the PAE-001 through PAE-038 Spec gate without invalidating that
  review. Every other byte change restarts the applicable review. PLS T-071, parent PRX T-011,
  and parent DEO T-036 remain separate implementation/test predecessors. Red tests must demonstrably
  fail for intended missing behavior before dependent Green work.
- Before promotion, `./pals-scripts/check-spec-ownership.sh` is diagnostic and cannot substitute for
  the technical draft review or authorize implementation. Immediately after the authorized
  status-only edit and before the post-promotion review, the command must exit 0 and print exactly
  `spec-ownership: PASS`.
- Parent GNU Make recording tests prove direct child exit 0 -> Make 0 and child exit 1, 2, 3, 37,
  signal, or recipe/precondition failure -> Make 2. Direct child CLI 0/1/2/3 semantics remain intact.

### PAE-015

- A verified proof task generates at most one completed explanation; a duplicate delivery is
  idempotent.
- Two concurrent deliveries with different claim IDs produce one claim winner and exactly one
  explainer workflow invocation (whose internal parser retry budget remains three). Same-delivery
  ambiguous or deliberately delayed response performs no model call when the conservative
  pre-request anchor leaves insufficient margin; an expired claim is recoverable by a fresh later SQS
  receive, and a stale claimant cannot persist completion or failure.
- `terminal` is acknowledged; `busy`, `lease_too_short`, `not_ready`, visibility extension, and claim
  transport/configuration errors are not acknowledged. All produce zero model calls and no
  fabricated failed/completed content. Deadline success/failure uses an injected monotonic clock;
  deadline output is discarded, and the receipt is deleted only after terminal failure persistence.
- Worker secret, claim ID, and receipt handle are absent from public/internal content, prompts,
  artifacts, diagnostics, exception/error text, logs, metrics, traces, evaluation history, and
  Langfuse payloads.
- `{"kind":"clarification","id":"..."}` routes to clarification processing, and malformed task
  bodies fail without updating an unrelated proof job. Traversal/reserved/control/oversized IDs are
  rejected before HTTP; accepted IDs are observed by a recording server as one encoded path segment.
- Table-driven envelope tests mutate every required/additional resource field, target ID, kind,
  state, content/diagnostic shape, lease/status combination, and prove that only exact `acquired`
  authorizes one model workflow and only exact same-target `terminal` authorizes deletion.
- Real slow-header and slow-body servers prove OpenAI, Ollama, and PALS API requests stop at the
  configured wall deadline and leave no live helper/request after return. An exactly 1,048,576-byte
  response may complete; a larger response fails as oversized without parsing its prefix.

### PAE-016

- A deterministic generator that becomes valid only on repair 5 and one that becomes valid only on
  repair 12 both reach `verified` under the default configuration, with every intermediate failed
  verification preserved in artifact order.
- A generator that remains invalid performs exactly the configured number of repair generations,
  then fails honestly; setting the budget to 1 produces exactly one repair generation.
- Configuration tests accept missing/default, `1`, `12`, and `64`, and reject empty, signed,
  whitespace-padded, decimal, exponent, zero, negative, `65`, and nonnumeric values before any
  model/verifier/artifact call.
- Repeated diagnostics add stagnation context for route selection but do not by themselves stop the
  next repair. Non-repairable verifier configuration failures and route-selection failures do stop
  without fabricating another candidate.
- Stagnation tests use three consecutive failed-candidate sets and require an exact intersection of
  `code + normalized message` fingerprints. Same code with a materially different normalized
  message does not count; matching non-consecutive attempts do not count.
- An empty initial candidate receives another repair generation when budget remains. A generator
  without repair capability fails with an explicit non-repairable diagnostic rather than silently
  ending.
- After each failed candidate and before the next route-selection call, a durable attempt checkpoint
  exists with `checkpoint_status=published`. Simulated process interruption after that checkpoint
  does not erase prior attempt evidence. Fault-injected file/link/parent-directory fsync and
  duplicate-key tests fail closed; an artifact-store failure records final `failed` status in the
  aggregate and an instrumented runtime oracle proves zero later route/model calls.
- A compile-success/checkpoint-failure fixture records final/top-level `verification.success=false`,
  fixed checkpoint diagnostic, failed state/event, and never emits or serializes verified.
- Terminal artifacts report the exact `repairs_used`, `termination_reason`, and structured matching
  `termination_event`; budget exhaustion,
  verifier/generator configuration failure, route-selection failure, artifact-store failure, and
  verification success are distinguishable without inferring from free-form diagnostics.
- Termination tests cover every allowed enum value and reject/never emit any value outside
  `verified`, `repair_budget_exhausted`, `non_repairable_failure`,
  `repair_generator_unavailable`, `repair_route_selection_failed`, and `artifact_store_failure`.
- A candidate whose generated sketch fails the structural-subsequence metric and whose Lean has
  compiler errors calls the verifier once, records only actual compiler/runtime diagnostics in its
  compile-phase checkpoint and next repair prompt, and records sketch adherence only after terminal
  runtime evaluation. A separate semantically equivalent/rephrased candidate whose Lean compiles is
  `verified` while its post-runtime `sketch_adherence` may be evaluated false; no
  `pals.sketch_contract_mismatch` runtime diagnostic, repair, or terminal reason is emitted. A
  safety, explicitly supplied formal-statement identity, or exact-Draft retrieval identity/
  equivalence preflight error still makes zero verifier calls for that candidate, but checkpoints
  and enters another LLM-selected repair route while budget remains. The cited real x² artifact is
  asserted only as `phase=preflight`, `elapsed_ms=0`, compile blocked by the old sketch check; tests
  make no claim that it compiled.
- Sentinel regressions capture candidate 1, all three selector retries, and every routed repair
  prompt through budget exhaustion and prove that benchmark registry values, hidden harnesses,
  expected strategies/methods, relevance labels, rubric values, compile-oracle tokens, sketch
  adherence findings, and evaluator sentinels never enter generation scope. Separate evaluator
  captures prove the exact sentinel/rubric appears only after terminal runtime.
- A real-execution repair fixture fails Lean on candidate 1, obtains a valid route, and proves that
  candidate 2 is generated, verified, checkpointed, and represented in status evidence rather than
  terminating at route selection. Separate fixtures reach verification success, an explicit
  non-repairable terminal, and the default twelve-repair exhaustion boundary.
- Route-selector fixtures return malformed JSON twice then a valid decision and prove exactly three
  calls followed by candidate generation/verification. Three malformed or typed transport failures
  prove exactly three calls, three ordered internal outputs/errors, exact closed
  `selector_attempts`, fixed
  `pals.repair_route_selection_failed` evidence, zero heuristic route/repair call, and the matching
  terminal event.
- For a multi-candidate run, aggregate `attempts[n]`, immutable checkpoint `n`, and the corresponding
  post-checkpoint status `attempt_evidence` are compared field-for-field for candidate number, full
  Lean code, ordered diagnostic code/message/severity/location, verification, phase, checkpoint
  status, and inbound route decision. A configured real-model/manual-release run must likewise show
  either verified continuation, an explicit non-repairable terminal, or all twelve repairs without a
  route-success premature stop.

### PAE-017

- The production worker factory has no verifier client or verifier transport secret; the worker
  image contains no Lean/Elan/Lake binary or project cache, and verifier/API unavailability never
  selects local Lean or synthesizes verification.
- Image build creates the exact mode-`0444` five-key `pals.lean-toolchain-resolution.v1` descriptor,
  exact mode-`0444` four-key `pals.lean-git-resolution.v1` descriptor, and exact mode-`0444`
  `pals.verifier-toolchain-manifest.v1`. Each descriptor and the exact Git executable has exactly one
  manifest record using canonical path, raw-byte length, and raw-byte SHA-256; no second raw-byte
  concatenation exists. Before HTTP readiness publication, a real-image startup oracle proves exact Git
  owner/mode/path/content, retained FD identity, and `git --version` stdout/stderr/status, plus the fixed
  `/app/lean-workspace` identity and exact 28-byte `lean-toolchain`, pins no-follow project/toolchain
  root and Git FDs with canonical path plus `st_dev`/`st_ino`, reproduces the exhaustive manifest set/bytes/
  digest, and proves the descriptor's root/`lean`/`lake` plus all six exact `root/src/lean`-relative
  grammar-source path/hash pairs, including `lake/Lake/Build/Module.lean` and
  `lake/Lake/CLI/Serve.lean`. No Elan
  process is invoked. A missing/extra/wrong-typed key, manifest set/framing/order/length/digest
  mismatch, source or executable mismatch, Git descriptor/version/content/output mismatch, shim,
  symlink escape, changed root, replaced inode,
  missing/non-executable binary, malformed toolchain file, `ELAN_TOOLCHAIN`, or generated-input
  influence fails startup. Nonblank `PALS_LEAN_BINARY` or `PALS_LAKE_BINARY` also fails startup;
  production has no environment-configured compiler compatibility path.
- Descriptor bytes are one ordered compact UTF-8 JSON object with keys exactly
  `schema_version`, `toolchain`, `root`, `lean`, `lake`, followed by exactly one LF and no BOM,
  whitespace outside JSON strings, duplicate key, or trailing byte. All five values are nonblank
  strings encoded as unescaped printable ASCII bytes `0x21..0x7e` excluding `"` and `\`; JSON escape
  sequences are rejected. The three paths are normalized absolute strings and `lean`/`lake` are
  strict descendants of `root`. The descriptor is one root-owned regular no-symlink file, mode exactly `0444`, and at
  most 4,096 bytes; any metadata or size mismatch fails before HTTP readiness publication. The exact
  descriptor `root`, not any literal parent prefix, is authority.
- Before every setup and direct-Lean phase, tests replace/rebind each root and Git path and
  independently mutate canonical path, `st_dev`, `st_ino`, Git bytes, descriptor token/hash, version
  output, and the exact five-entry-`PATH` candidate set; a prior shadow, distinct later candidate,
  candidate replacement, non-regular candidate, or search-result drift must fail before child
  launch. The unchanged case must prove that Lake's basename search resolves to the retained
  descriptor Git inode, compare the re-opened roots/Git with retained FDs, rehash Git, and launch
  Lake/Lean from the pinned project FD rather than a request/current-directory-selected executable.
- A recording process oracle for one project-backed request observes exactly two ordered phases:
  absolute Lake `setup-file R/Main.lean --no-build --no-cache`, then absolute direct Lean with
  `--setup=R/ModuleSetup.json`, `--threads=1`, and `R/Main.lean`. It observes no
  `lake env`, `lake lean`, Elan shim, shell wrapper, build, cache fill, update, fetch, clone, or
  project write. It requires exit zero, zero stderr bytes, one compact UTF-8 JSON object plus one LF,
  and the complete closed grammar above. Malformed/unknown/duplicate-at-any-depth/extra/trailing JSON,
  public-schema fields excluded by the external-file grammar, wrong artifact tuple length, a path
  outside the canonical project/toolchain roots, stale imports, nonzero setup exit, any successful
  stderr byte, or setup combined output above exactly 8,388,608 bytes produces fixed
  `lean.setup_file_failed` and zero Lean calls. The pinned exact valid fixture's measured
  4,320,763-byte stdout and empty stderr are accepted; equality at the combined cap is accepted only
  after complete validation, one byte over fails, and direct Lean remains capped at exactly
  1,048,576 combined bytes.
- The positive `ModuleSetup` grammar matrix executes `P1` through `P5` above: both JSON booleans;
  one/three/four artifact tuples; empty/nonempty string, both boolean, zero, one, and multi-digit
  positive canonical Nat options; nonempty dynlibs/plugins; anonymous and named keys; every top-key order and
  forward/reverse nested-key order. The rejection matrix independently covers every listed framing,
  key, name/option, artifact/plugin, and path/file mutation. Every rejection makes zero Lean calls.
- Request-file tests require no-follow `O_CREAT|O_EXCL`, regular type, in-request-root containment,
  and `st_nlink == 1` for `Main.lean` and `ModuleSetup.json` through use/unlink. Read-only setup inputs
  instead require the exact manifest path/size/digest under a pinned root; their `st_nlink` is not an
  escape oracle, and an unlisted alias path is never authorized.
- Container integration starts the verifier only with non-root/no-capability/no-new-privileges,
  the exact private mTLS service network plus networkless compiler children, read-only root,
  bounded request tmpfs, CPU, memory, PID, and open-file limits; independently omitting each
  required boundary property makes startup fail before HTTP readiness.
- The root Compose contract test asserts exact `cpus=2` together with 4 GiB memory, 64 PIDs, and
  nofile 1024; no test or fixture retains the obsolete one-CPU expectation.
- Real Lean adversarial fixtures use compile-time `run_tac`/IO (not string matching) to prove a
  credential canary is absent, a root/project write cannot occur, an external callback cannot be
  reached, timeout kills spawned descendants, and CPU/memory/process/output limits fail closed.
- A separate real-Docker setup-phase executable oracle invokes a statically linked ELF probe through
  the production phase launcher. The probe reads its own OS-provided `envp`, succeeds only for the
  exact five-entry table above with `HOME=R/home` and `TMPDIR=R`, and emits exactly the pinned 92-byte
  setup stdout and zero stderr. Missing/additional/wrong-key/wrong-value/cross-request path/canary
  mutations fail. This probe cannot satisfy the real pinned-Lake setup, direct-Lean compile, or
  release gate; those run separately against the production descriptor.
- Independently, the real direct-Lean `run_tac` environment oracle succeeds only when compile-time
  Lean IO sees exact keys `PATH`, `HOME`, `TMPDIR`, `LANG`, and `LC_ALL` with their exact table values.
  It plants parent and worker canaries and explicitly rejects `ELAN_HOME`,
  `ELAN_TOOLCHAIN`, `LEAN_PATH`, `LEAN_SRC_PATH`, `LD_LIBRARY_PATH`, every additional key, and every
  canary value; `HOME` or `TMPDIR` from any other request also fails, and the Lean fixture itself must
  still verify successfully. Both executable environment oracles are mandatory.
- With the attested two-vCPU/4-GiB-memory/64-PID outer cgroup, the child uses a 16 GiB
  virtual-address cap,
  64-process rlimit, 1024-descriptor soft/hard limit, and one Lean file-processing thread; the
  outer verifier also has a 1024-descriptor soft/hard limit. The prebuilt read-only Lake workspace
  is owned by UID/GID 65532, resolves local Git metadata with only the existing `/dev/null` device
  available as a non-persistent read/write sink, and compiles valid Mathlib Lean without update,
  clone, fetch, or project write.
  A real `run_tac` 32 GiB virtual allocation and 80-child fan-out fail inside those limits.
- The exact fixture whose UTF-8 SHA-256 is
  `572596a39973c1c0deeee7a7b9b92acfd5c840219399e3cd0bb9ee12f68a7d68` compiles in the dedicated
  verifier behind the private TLS-1.3 mTLS HTTP boundary under the production 300-second server and
  imported API reconciler 310-second client hard deadlines;
  malformed/oversized verifier responses become typed failures without exposing code,
  environment, socket path, or secrets. A separate short-deadline fixture proves timeout and
  descendant reaping without weakening the production cold-compile acceptance test.
- The descendant-cleanup Red matrix crosses setup/direct-Lean with normal/failure/timeout/overflow/
  cancel/exception. Every cell imports or emits only the minimum phase-appropriate fixture, starts
  both an ordinary descendant and a descendant that creates a distinct process group/session, and
  requires real PID/PGID/SID observation of both before accepting cleanup. A phase outcome before
  this precondition is a failed oracle, not cleanup success. Before the next phase, response, or
  second request, neither descendant nor any adopted child remains. Injected kill/reap/enumeration
  uncertainty produces no successful response and causes the verifier to stop serving; no retry,
  skip, Mathlib-startup timeout, or local-only substitute satisfies this criterion.
- Clock-controlled command tests prove one deadline is captured before setup, setup elapsed time is
  subtracted from Lean's allowance, and no phase resets that deadline. For every cell in the cleanup
  matrix, the test captures the exact outcome event and sets `cleanup_deadline = phase_outcome_at + 5
  seconds`; cleanup-entry delay consumes that budget. Completion exactly at the deadline passes;
  delayed entry or completion at the first later instant sends no response and terminates service.
  The production 300-second untrusted-work/310-second client pair and test-only two-second/eight-second
  pair remain unchanged.
- Image-build tests generate the exact length-prefixed manifest grammar and exhaustive no-follow
  record union over both descriptors, the exact Git executable, and every regular project/toolchain-
  root file. They prove raw UTF-8 path ordering, descriptor/Git single-record semantics, exact Git
  owner/mode/path/content/version-output binding, path/byte-length/file-SHA-256 framing,
  EOF, and complete reproduction; startup/compile responses expose only its lowercase SHA-256.
  Mutating any covered byte, set member, path, length, order, separator, or final LF changes or
  invalidates the digest; missing/malformed digest fails schema-v3 provenance and cannot be replaced
  by an image tag or agent-supplied value. This remediation creates a new comparability digest and
  never rewrites an existing schema-v3 row.

## Contracts and Data

- Agent explanation objects follow the API Spec in
  `pals-api/specs/proof-explanations/requirements.md`.
- Frontend behavior follows
  `pals-webfront/specs/proof-explanation-clarification/requirements.md`.
- Evaluation history is UTF-8 JSON Lines with one schema-versioned `EvaluationRun` per line.
- Schema changes require a version increment and a compatibility or migration decision.
- The DEO exchange is a separate `pals.dsp-export.v1` payload plus detached digest. It is never a
  history line, schema-v3 summary replacement, API/event payload, or schema-v2 conversion.

## Security and Privacy

- Model credentials remain in ignored environment files and never enter artifacts or history.
- Public content is allow-listed; diagnostics and observability payloads stay internal.
- Hidden chain-of-thought is neither requested nor stored. Concise user-facing explanations and
  inspectable source references are permitted.
- DEO export uses only the closed pseudonymous DTO. Raw canonical identities/material
  fingerprints, prompts, Lean, explanation content, provenance objects, keys, key digests, and
  detached digest are excluded from runtime logs and every unlisted artifact field.

## Internationalization and Accessibility

- Learner-facing explanation and clarification content is Japanese unless a future approved Spec
  adds locale selection.
- Structured sections and line references must remain usable by screen readers in the owning UI.

## Observability and Cost

- Record provider/model, elapsed time, run/case/suite IDs, stage status, and metric provenance.
- PAE-016 records closed selector-attempt outcome counters and per-run selector-call/repair counts;
  no prompt, output, exception text, code, or diagnostic message becomes a telemetry label. Three
  calls per selection raises the maximum selector cost by one call versus the prior implementation,
  with at most 36 selector calls across the default twelve-repair run.
- Live semantic evaluation is opt-in because it incurs model cost; deterministic evaluation is
  always available offline.
- Optional Langfuse export failure does not fail or erase an evaluation run and does not change its
  completed journal, summary, authorization, comparison, or exit code. Parent DEO-001 through
  DEO-020 own the cross-repository contract; PAE-030 through PAE-033 implement only Agent producer
  responsibilities and create no SDK/HTTP request estimate or vendor cost.
- PAE-027 records generation and evaluator token/cost only from typed per-call evidence. Missing
  usage/pricing/billing in any applicable call is a counted not-evaluated fact for that scope and the
  overall total, never a partial sum or inferred zero. Evaluation summaries contain no prompt,
  expected strategy, Lean, provider response, or error text.

## Test Requirements

| Requirement | Test Level | Required Scenarios | Execution Tier |
|---|---|---|---|
| PAE-001–PAE-006 | Unit, contract, live smoke | verified, unverified, malformed JSON/reference, exact Japanese/code-point/section/key-point/non-repetition boundaries, scoped clarification, privacy, exact one-test/create-only-evidence `lean-explanation-ja-v1` release command and oracle | PR except live model/judge smoke; manual/release live smoke |
| PAE-007–PAE-013 | Unit, recorded artifact, regression | every metric formula/roll-up, verification gate truth table, verified explanation absence, clarification expectation/absence/malformed/overlap and separator matrix, distinct draft/sketch semantic rubrics, generation/evaluator prompt-channel capture, repair missing/malformed/sequence/event matrix, append/concurrent write, aggregate/filter/compare | PR |
| PAE-010, PAE-014 | Unit, CLI, producer boundary, integration | evaluated/unavailable/malformed judge; exact export invocation/options/target/result/exit/replay/conflict matrix; exporter disabled; canonical-history/summary/journal/gate/exit independence; no consumer/vendor code in Agent | PR; manual export-disable rehearsal |
| PAE-015 | Unit, clock-controlled concurrent story, queue/API integration | explanation/clarification, concurrent different/same-claim winner/busy, fresh expiry takeover and reuse rejection, not-ready dispatch, stale terminal write, exact lease/deadline/visibility boundaries, every ack/no-ack outcome, secret redaction, malformed task | PR/main |
| PAE-016 | Unit, execution integration, recorded artifact, live regression | success on repairs 5 and 12, exhausted custom/default budget, valid-route continuation, three-call malformed/transport selector matrix with no fallback, aggregate/checkpoint/status evidence equality, repeated diagnostics, non-repairable and route-selection stops, compile-success/checkpoint-failure false provenance, explicit-formal/exact-Draft zero-verifier preflight, Lean-valid sketch-mismatch verification, all-generation-prompt oracle sentinels | PR; manual/release live model |
| PAE-017 | Unit, root Compose contract, Docker integration, real Lean security regression | exact two-CPU/four-GiB/64-PID/1024-nofile contract; worker/server/compiler separation; canonical exhaustive manifest bytes/digest; exact Lean and Git descriptors, Git executable/version/content, and pinned project/toolchain/Git startup plus per-phase re-attestation; O_EXCL/link-count mutable files; manifest path/size/digest read-only inputs; exact setup-file/direct-Lean order; complete positive/rejection ModuleSetup grammar; separate setup ELF `envp` and direct-Lean `run_tac` five-variable oracles; setup/direct-Lean x normal/failure/timeout/overflow/cancel/exception descendant cleanup with phase-outcome anchor and delay-before-entry; secret/filesystem/network/resource bypass; no local fallback | PR contract test; unskipped real Docker on main/release security gate |
| PAE-018 | Unit, CLI, filesystem fault injection, real-data regression | strict non-mutating load failure, exact digest pin, five-record/four-comment migration, byte-exact backup, stable-lock concurrency, atomic replace/fsync/fence ambiguity, transformed schema validation, audit-only output | PR; explicit local migration evidence |
| PAE-019 | Unit, settings/factory, evaluator integration | exact five-variable states; separate unequal credential binding; loopback-only HTTP/remote HTTPS; redirect/DNS/origin isolation; normalized inequality against every contributor; distinct post-runtime request/no cache-batch-response reuse; zero-call unconfigured metrics; configured provenance; privacy; exact live oracle | PR; mandatory release evaluator preflight and live oracle |
| PAE-020 | Unit, parent-corpus HTTP contract, worker story | verifier-server-only attestation production after real compile/cleanup; exact parent binding; worker constructor/client/synthesis denial; authoritative API refetch; non-verified omission/rejection | PR; parent T-016/T-017 and API/Agent contract gate |
| PAE-021 | Unit, API contract, killable-transport clock matrix, queue race, real agent/API story | exact acquisition `acquired|busy|terminal`; renewal `renewed|terminal`; forbidden `lease_too_short`; terminal stop/ack/explanation separation; different valid Lean workers; renewal before/between every model and API submission/refetch spend; exact 30-second margins; expiry/takeover without overlap; visibility/cancellation/join failure; stale/conflict stop; authoritative refetch; no direct verifier call; exact replay | PR/main after current API Green |
| PAE-022–PAE-023 | Unit, serialization, privacy, worker story | metadata-free diagnostics, closed context, fixed errors, newline Lean, terminal wrong-ID/malformed/cross-target no-ack | PR |
| PAE-024–PAE-025 | Unit, JSONL regression, real migrated history | nextafter boundary, exact threshold, closed v2/v3 schema, metric/source/status contradictions | PR |
| PAE-026–PAE-029 | Unit, CLI, runner integration, parent Make contract, manual live suite | exact manifest/rubric/case digests and three prompts, clean runtime input, live invocation journal, ranked retrieval, separate stage judges, prompt separation, exact eight-role call/comparability/count binding, evaluator-versus-all-contributors and distinct-call mutations, rejection of evaluator `explain`, sketch adherence, paired compile/uplift/repair, latency, usage/cost, Git-bound toolchain, chain digests, missing evidence, grouping, durable summary, stale/duplicate/interruption exits, append/compare, exact GNU Make 0/2 | PR except cost-bearing live model; manual/release live suite |
| PAE-030 | Unit, mapping contract, property/boundary | complete invocation membership/order; exact 26-source matrix; integer/half-even/bounds; stage counts, rates, totals, percentiles, histogram; inaccurate-shape separation | PR after child readiness |
| PAE-031 | Unit, security, configuration/registry integration | exact material bytes; parent HMAC vectors; OS-CSPRNG; `.local` shared inode; `.dev`/`.prod` full ARN+VersionId; rotation/collision/fallback rejection | PR/security/main after child readiness |
| PAE-032 | Unit, CLI, filesystem fault injection, privacy | exact payload/sidecar bytes and names; ordered create-only commits; exact-existing replay; torn/conflicting targets; exact result/error/exit; canonical independence; recursive canaries; no authenticity overclaim | PR/security after child readiness |
| PAE-033 | Spec gate, exact import audit, producer baseline, parent vector/cross gate | The sole active path is `Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64 -> PRX T011`. Task 82 reopens, Task 83 is historical PRX provenance, and Task 84 binds the external current DEO Task-48 report and current PRX triple. Task 73 validates that binding plus exact PFI/EXP/PJR/PWA/API PEX imports, performs independent draft review, status-only promotion, ownership PASS, and its marker; Task 64 independently revalidates promoted bytes before its marker. | before implementation, then PR/main |
| PAE-034 | Unit, PostgreSQL/pgvector integration, graph/registry contract, live release | three-attempt OpenMath fail-closed matrix; actual top-8/no-cutoff fetch; structural/LLM 0..4 rerank; zero-context ordinary Draft; exact graph/re-entry; fixed eight-role registry; no model override/fallback; real repeated repair, isolated Lean, durable artifact, Explain/Clarify, no fake path | PR deterministic/DB integration; mandatory cost-bearing release live gate |
| PAE-035 | Parent-corpus contract, LocalStack integration, queue race | exact v1 queue/body/attribute/digest/receipt validation; 900-second initial visibility; extension/delete ambiguity; retain invalid/poison; DLQ only by redrive; fresh-claim redelivery; one receipt; no ordering inference | parent T-014 Red then T-015 Green; PR/main |
| PAE-036 | Parent-corpus contract, mTLS integration, Docker security | exact port/routes/TLS/status/framing; readiness/startup order; one-slot admission; real compiler truth; cleanup-before-response; three immutable SecretBinary ports; server-only attestation; API-only caller; no DB/SQS/model/plaintext/Unix | parent T-016 Red then T-017 Green; PR/main/release |
| PAE-037 | Property/OCI contract, release story, import/ownership audit, docs/command audit | blocked/active entrypoint; old-worker denial; stop/retain/resume participation; exact property IDs/mappings/digest label; PRX-006 Agent image/toolchain/property provenance; focused/full commands; README/SECURITY headings; content-free telemetry; no provider/ECS/SQS observation, cutover sink, API PostgreSQL, or Infra resource ownership | after Task 64; parent T-018/T-020/T-022/T-024–T-027 |
| PAE-038 | Parent-corpus contract, LocalStack/API integration, receipt race | exact clarification body/empty-attribute/system-attribute routing; marker; fresh claim; visibility; terminal `dispatch_uncertain` zero-claim/model/update delete; poison/not-ready/busy/ambiguity/delete retention; no proof-codec/redrive/direct/fallback path | parent PRX-009 Red/Green predecessors; PR/main |

## Quality Gates

- PR: `python -m pytest`, `python -m ruff check .`, strict `python -m mypy pals_agent tests`, API
  contract tests, and deterministic evaluation suite.
- Main: API/worker queue story and frontend story tests.
- Manual/release: isolated real Lean compile/security bypass suite plus the exact
  `python -m pytest -q tests/live/test_lean_explanation_release.py::test_lean_explanation_ja_v1
  --junitxml=.pals-agent-artifacts/lean-explanation-ja-v1.junit.xml` argv. The semantic gate requires
  complete PAE-019 evaluator configuration and distinct request, exact PAE-034 role registry, actual
  pgvector retrieval, repeated Repair, durable verified artifact, normalized inequality from every
  contributor, process exit 0, exactly one unskipped JUnit pass, and a fresh strict create-only
  evidence object. No other command or prior artifact substitutes.
- Parent `agent-evaluation-smoke`, `agent-evaluation-full`, and `agent-evaluation-compare` are
  repeatable evidence gates. A completed live suite may exit 2 honestly when judge/token/cost or
  other required evidence is unavailable; exit 3 is operational/incomplete and neither can be
  relabeled passed. Release requires one current completed journal and exit 0.
- Historical parent and child task states authorize nothing for current bytes. Current readiness is
  `Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64 -> PRX T011`, with the external exact current DEO
  Task-48 report validated at
  both stages. It runs after the exact approved/post-reviewed
  `TDG -> EXP -> PJR -> PWA -> API PEX` authority chain and
  exact PFI/EXP/PJR/PWA/API PEX import identity validation. No still-pending implementation/test work
  for any PAE-001 through PAE-038 requirement starts until Task 82 has demoted/reopened the stale
  authority, Task 83 has synchronized the PRX import, Task 84 has recorded the report identity, and Task 73 completes fresh pre-promotion
  review, status-only promotion, and ownership PASS and current Task 64 then returns the distinct
  promoted-byte verdict `IMPLEMENTATION READY`, CRITICAL=0, HIGH=0, with no material question.
- After child readiness, PR requires retained failing Red evidence before each dependent Green
  change, the independent Agent grammar/mapping/key/publication suites, exact producer baseline,
  parent vectors, import/code-generation audit, and parent cross-repository gate. Optional live
  Langfuse checks remain nonblocking and cannot authorize evaluation truth.
- Nightly-only and load gates are not introduced: the worker processes one receipt at a time and
  bounded concurrency/clock-controlled queue stories cover the changed claim path. Live model
  quality remains manual/release because it incurs cost and is nondeterministic.

## Rollout, Rollback, and Recovery

- The claim contract has no dual legacy mode. Before API PEX-018 activation, Agent stops new
  explanation/clarification receipt and drains or cancels only its current helpers. Infra supplies
  provider/ECS/SQS quiescence evidence and controls candidate start/receipt authorization; API
  supplies claim persistence. Agent consumes those parent-authorized results without polling provider
  counts or writing a shared cutover sink. Deploy and preflight the API schema and exact envelope,
  deploy the matching Agent in blocked mode, then enter active mode only under the parent order and
  run the queue story plus authenticated smoke. Configuration preflight verifies nonblank worker
  secret, API base URL, admitted queue binding, timeout range, and API lease sufficiency before receipt.
- Rollback stops new receipt and drains or cancels Agent-owned helpers, consumes Infra/API recovery
  evidence, restores only a higher-sequence compatible Agent/API release, and resumes only under the
  parent order. Agent neither queries PostgreSQL claims nor provider/ECS/SQS quiescence and never
  writes a shared rollback/cutover sink. No fallback claimless request is sent.
- Failed generation remains visible and may be retried by a new explicit task/fresh claim without
  changing the verified proof.
- Evaluation history is append-only. Rollback disables new generation/export while preserving
  existing records.
- PAE-018 is a one-way content repair within schema v2, not a schema-version reinterpretation.
  Application rollback retains the repaired schema-v2 history and disables evaluation writers that
  could reintroduce legacy comments; it never restores the known-invalid source. The exact
  digest-named backup is immutable audit/recovery evidence only in this change, and no automatic or
  application CLI restoration path is authorized. Normal load and application startup never restore
  or migrate it.
- Rollout starts the isolated HTTP verifier with every PAE-017/PAE-036 boundary property, consumes
  the exact immutable mTLS secret versions, proves private TLS-1.3 readiness, startup attestation,
  pinned absolute toolchain resolution, setup-file/direct-Lean command oracle, exact generated
  environment, complete descendant cleanup, and real bypass suite, then admits the API reconciler
  and only afterward resumes the exact v1 worker under the parent gate. A failed readiness,
  deployment-binding, secret, transport, compiler, cleanup, or security test aborts rollout.
  Rollback blocks receipt first and uses only a higher-sequence parent-admitted compatible
  worker/verifier pair; it never reactivates the old worker, environment-leaking `lake env lean`
  image, local Lean, Unix/plaintext transport, or direct worker verifier call.
- No product-data migration is authorized. PAE-018 is the only authorized local-history repair and
  must retain its immutable source backup.
- PAE-019 rollout preflights the exact five-variable state, separately bound unequal credential,
  exact private identity, loopback-HTTP/remote-HTTPS and no-redirect origin rule, normalized
  inequality against every contributor, and a distinct post-runtime request before enabling a gate.
  Rollback removes all five
  evaluator variables together; optional runs then become explicit unconfigured `not_evaluated`,
  while the mandatory exact release command aborts and creates no passing evidence.
- PAE-020 rollout deploys and contract-tests the API's extra-forbid verified-update schema before
  activating the matching agent. There is no legacy verified payload fallback. Rollback stops proof
  workers before restoring a mutually compatible API/agent pair; existing verified records and
  attestations are preserved and require no migration.
- PAE-016 rollout runs the deterministic three-call selector/continuation matrix and one configured
  real-model repair before worker activation. `selector_attempts` and status `attempt_evidence` are
  additive internal artifact/context fields under checkpoint schema 1 and require no product-data or
  history migration. Rollback may omit those new fields but shall preserve existing immutable
  checkpoints and shall not introduce a fallback route or reduce the twelve-repair budget.
- PAE-021 rollout participates only in the parent PRX-004 receipt stop/drain/resume protocol. Agent
  starts blocked, stops new receives immediately, retains uncommitted receipts, cancels/joins its own
  helpers, validates the admitted worker image and v1 queue binding, and resumes only as a fresh
  admitted candidate process. Infra alone observes provider/ECS/SQS quiescence, owns explicit old-
  worker queue denial and durable cross-repository cutover/effect evidence, and controls candidate
  start; API alone persists claims, admission, reconciliation, and gate state. Unavailable, stale, or
  mismatched imported authorization keeps receipt blocked. Rollback repeats the Agent stop/retain
  participation under a higher-sequence admitted release and never sends claimless updates, clears a
  live claim, queries provider state, or writes a cutover sink. Explanation always restarts from the
  authoritative persisted proof.
- Schema-v3 evaluation records may coexist with strict schema-v2 records. Rollback may stop v3
  writers and summaries but keeps all appended records; it never down-converts v3 or weakens the v2
  migration/reader. Suite, generation, evaluator, price, rubric, repair-budget, source, or toolchain
  changes create a different comparability group; suite/rubric content changes require new immutable
  revisions and digests. Running/failed/interrupted journals remain audit evidence and are never
  promoted during rollback.
- Schema-v3 DSP export activates only after fresh Agent and Observability child convergence, the
  PAE-033 producer baseline, shared parent vectors, cross-repository gate, key-binding rehearsal,
  payload/sidecar fault matrix, and export-disable rollback pass. `.local` activation proves one
  shared registry inode; `.dev`/`.prod` prove the exact full producer ARN and immutable VersionId.
  Disabling or rolling back the optional exporter leaves canonical v3 history, journals, summaries,
  comparisons, live gate outcomes, receipts, registry history, and old/new ID spaces unchanged; no
  v2 fallback parser is used for v3 records and no automatic key/data cleanup occurs.

## Cross-Cutting Operations

- Closed counters record claim outcome, model invocation outcome, deadline outcome, receipt
  delete/retain reason, DLQ-visible failure, and stage evaluation status; timers record claim API,
  model, terminal-write, and end-to-end worker duration. Labels are the closed secret-free tokens in
  the worker contract. No cost-bearing model call occurs before claim/visibility gates.
- The local/AWS runbook documents queue visibility, DLQ inspection/redrive, expired-claim recovery,
  pending-dispatch expiry, quiescence, rollout/rollback, live-smoke cost, and how to find canonical
  JSONL without exposing content in telemetry.
- Locale/accessibility remain owned by explanation payload/UI requirements; this worker change adds
  no UI. API/event/error contracts are imported only from approved PEX IDs. Performance SLOs are
  not added; exact bounded retries and one-receipt worker execution are verified instead.
- DEO producer operations expose only content-free success/failure categories and bounded counts;
  payload values, digests, fingerprints, key versions/digests, paths, ARNs, VersionIds, and exception
  text are never telemetry labels or runtime log fields.

## Constraints

- This feature Spec does not depend on the draft platform-architecture Spec for implementation
  authority. `pals-agent` owns proof generation, repair orchestration, Lean verifier tooling,
  explanation generation, canonical evaluation records, and generic export data.
- Keep DTO consumption, projection HMAC, vendor SDK, helper/receipt/outcome/read-back behavior, and
  private observability deployment in `pals-observability`. `pals-agent` owns only PAE-030 through
  PAE-033 producer mapping, key binding, publication, and evidence.
- Persist visible prompts, model outputs, compiler/tool diagnostics, timings, and artifact
  references only inside internal attempt/evaluation boundaries. Do not request or persist hidden
  reasoning, and enforce the public allow-list in PAE-006.
- Do not introduce a local-only shortcut, canned proof/explanation, or fake-success fallback.
- Migration backups/fences/locks are local private operational artifacts: mode `0600`, ignored from
  version control, excluded from public responses/telemetry/exports, and never printed with content.
- Evaluator provider/model/revision and fixed rubric are allowed semantic provenance; evaluator
  endpoint, credential, prompt/output, diagnostics, and free-text transport/configuration errors are
  prohibited from metric sources, comments, history, logs, traces, exports, and public payloads.
  The dedicated evaluator credential is provider/origin scoped under PAE-019 and no generation
  credential, redirect, proxy, or alternate origin may receive or substitute for it.
- The credentialed worker has no verifier transport credential or route. The API-owned reconciler
  is the sole application caller of the private mTLS verifier, and the verifier may consume only its
  server certificate/private key and shared CA through the PAE-036 ports. Worker and verifier shall
  not share environment secrets, AWS credentials, database/API/model credentials, writable
  artifact directories, a Unix socket, a role, a task, or a local compiler fallback.
- Toolchain resolution is trusted verifier-startup work over the immutable project file and
  digest-covered image only. Generated source, request fields, inherited parent environment, and
  runtime model/API settings shall not select a toolchain or enter setup/Lean child environment.
  Direct absolute binaries and validated `ModuleSetup` replace, rather than emulate, `lake env`.
- Parent DEO-021 exclusively owns the three PAE-029 root Make delegation targets and their parent
  contract test. Parent PLS-012 resource evidence is read-only for unchanged verifier limits and
  cannot authorize Unix/network-none transport; approved PRX and the Infra child own the current
  private mTLS HTTP deployment binding. This child references those completed parent tasks only.
  Evaluation implementation, CLI behavior, manifests, history, summaries, verifier implementation/
  images, and security tests remain owned by `pals-agent`.
- Unit fixtures may test parsers and failure/unevaluated control flow, but no fixture-generated Lean,
  verifier boolean, token count, judge score, or cost may be represented as a successful live model
  evaluation. Only runtime/provider/verifier evidence can satisfy the v3 quality gate.

## Assumptions

- The API owns durable product records; JSONL is the canonical local evaluation-history format.
- Exact Lean line excerpts are stable enough for explanation grounding within one proof version.
- Provider token/cost fields are optional evidence; absence is expected and remains explicitly
  unevaluated unless a complete typed source is available.
- The operating system and AWS Secrets Manager provide the CSPRNG and immutable secret-version
  primitives required by PAE-031; failures are explicit and do not authorize publication.

## Historical Promotion State and Current Authority Gate

- Historical pre-promotion state: `status: draft` was intentionally retained by that authoring
  update, which did not authorize or perform promotion. Historical remediation scope and task states
  remain, but per-invocation findings, counts, hashes, and verdicts are external and are not retained.
- Historical parent and child task states authorize nothing for current bytes. Current readiness
  follows `Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64 -> PRX T011`, with the external exact current DEO
  Task-48 report validated by Task 73 and independently revalidated by Task 64, after the exact approved/post-reviewed
  `TDG -> EXP -> PJR -> PWA -> API PEX` chain and exact PFI/EXP/PJR/PWA/API PEX imports. Historical
  predecessor tasks remain completed history and are never reopened, demoted, or promoted again.
- Approved parent PRX T-036 and completed T-010 were exact predecessors. The completed Task 53
  draft review and status-only promotion supplied only the Agent child input for parent T-011;
  parent T-014/T-016 and their dependent
  Green/integration/release
  tasks cannot begin their Agent slice until that child gate completes.
- The ModuleSetup question remains resolved from pinned public source rather than assumption:
  this
  Spec accepts only the closed external-file projection, preserves the exact validated bytes for
  direct Lean, and rejects the broader derived decoder's extensions. The measured x2 setup stdout is
  4,320,763 bytes with the pinned SHA-256 above and stderr is empty; the lightweight setup stdout is
  exactly 92 bytes; direct `lean --setup=R/ModuleSetup.json --threads=1 R/Main.lean` accepts the
  result with exit zero. The later remediation adds the exhaustive positive/rejection grammar and
  phase/outcome cleanup matrices, one manifest grammar, and pinned-root oracles. This evidence
  supports feasibility only and does not satisfy the deferred fresh review or real-Docker release gate.
- Current authority follows requirements frontmatter. Task 82 invalidates the preceding promoted
  authority after DEO-R50-001 and follows completed Tasks 74, 80, and 81; Task 83 synchronizes
  historical PRX provenance, Task 84 records the external report identity, then reopened Tasks 73/64 follow Task 84. No
  implementation or test edit is
  authorized until Task 73 validates exact imports, obtains the all-zero technical draft verdict,
  performs only an explicitly authorized status-only promotion, obtains exact ownership PASS, and
  publishes only its inverse-proved `[ ]` to `[x]` completion marker;
  current Task 64 must then use a different fresh reviewer and return the all-zero
  `IMPLEMENTATION READY` verdict over promoted bytes and exact imports while its checkbox remains
  `[ ]`, followed only by the inverse-proved single-token `[ ]` to `[x]` completion-marker
  publication.
  The historical promotion sequence was exact: (1) parent PRX T-036/T-010,
  PLS T-061, DEO T-047 -> T-048 Spec restoration/convergence, and Agent T-065 complete; (2) a fresh
  independent review of this draft bundle reports technical verdict `IMPLEMENTATION READY`,
  CRITICAL=0, HIGH=0, and no material question while explicitly recording that draft bytes remain
  non-authoritative; (3) an explicit
  maintainer/user authorization changes only frontmatter `status: draft` to `status: approved`;
  Task 53 owns only steps 1-3 and replaces never-executed Task 38; (4) the global ownership checker
  exits zero with exact `spec-ownership: PASS`; (5) separate Task 64 uses a different fresh independent
  reviewer to re-read the
  promoted three-file bundle from disk and returns exact `IMPLEMENTATION READY`, CRITICAL=0, HIGH=0,
  and no material question. A sole inverse-proved Task-64 checkbox-token publication then completes
  PAE-033/Task 64 without invalidating step 5 and permits Spec-derived Red-before-Green work for
  those historical bytes. That prior evidence cannot satisfy current Task
  64. Any Task 73 import or remediation byte change precedes and restarts the current fresh draft
  review; any promoted-byte change other than that exact marker publication restarts current Task 64.

## Open Questions

None.

## Definition of Done

- [ ] Every Must requirement has executable Spec-derived tests.
- [ ] A real verified Lean proof completes explanation and clarification generation.
- [ ] A DSP artifact is recorded and summarized by state with no fabricated scores.
- [ ] API, worker, and frontend story tests pass together.
- [ ] Review finds no unresolved P0/P1 Spec or implementation issue.
- [ ] Semantic evaluation uses a separately pinned evaluator or explicit zero-call unconfigured
  `not_evaluated`; dedicated credentials stay at their exact origin, HTTP is loopback-only, and the
  normalized evaluator identity differs from every contributing generation identity; every score
  comes from a new evaluator-only post-runtime request.
- [ ] Proof generation is API-claimed/fenced and explanation consumes only authoritative persisted
  verified Lean after a terminal refetch.
- [ ] Smoke/full/compare produce strict append-only v3 records and matching JSON/Markdown summaries;
  missing judge/token/cost evidence cannot pass or become zero.
- [ ] Root Compose contract test asserts the approved two-CPU verifier cap.
- [ ] The exact one-test `lean-explanation-ja-v1` live command yields exit zero, one unskipped JUnit
  pass, and one fresh strict private evidence object after actual pgvector top-8 retrieval, all eight
  `openai/gpt-5.4-mini-2026-03-17` roles, at least two Repair cycles, isolated Lean, durable verified artifact,
  Explain, and Clarify; no alternate, stale, fixture, mock, recorded, or template path authorizes release.
- [ ] `verifier_toolchain_sha256` binds the exact Git descriptor, executable bytes, and version output,
  and the closed five-entry-`PATH` search proves pinned Lake's basename lookup selects that retained
  Git inode for offline metadata access.
- [ ] Task 82 records the DEO-final-identity requirements-first demotion and reopens Tasks 73/64;
  Task 83 then synchronizes the PRX import, Task 84 records the external DEO Task-48 report identity, and Task 73 records exact approved DEO/PFI/EXP/PJR/PWA/API PEX three-file identity, runs an all-zero
  technical `IMPLEMENTATION READY` draft review as non-authoritative, performs only an explicitly
  authorized status-only promotion, requires ownership PASS, validates the external exact current
  DEO Task-48 report, and publishes only its inverse-proved `[ ]` to `[x]` completion marker;
  current Task 64 independently revalidates that report and then obtains a
  distinct fresh promoted-byte/import all-zero `IMPLEMENTATION READY` while unchecked, followed by
  only its inverse-proved single-token completion-marker publication, before any Red/Green edit.
- [ ] The complete-invocation DTO, material/HMAC/key registry, exact payload/sidecar pair, privacy
  canaries, producer baseline, parent vectors, and cross-repository gate satisfy PAE-030–PAE-033
  without changing schema-v2/schema-v3 or explanation/clarification behavior.
- [ ] PAE-035 queue receipt validation/lifecycle passes the parent corpus and LocalStack redelivery/
  poison-retention stories without deleting invalid or ambiguous work.
- [ ] PAE-036 serves only the parent-imported private TLS-1.3 mTLS HTTP contract on port 18117,
  produces attestations only after real compile and cleanup, and consumes only its three immutable
  SecretBinary ports.
- [ ] PAE-037 old-worker denial, blocked/active entrypoint, behavior-property artifact/OCI label,
  PRX-006 release-provenance contribution, repository-local commands, operations/security
  documentation, and no-provider-observation/no-cutover-sink/no-API-DB/no-Infra-ownership audits pass.
- [ ] PAE-038 imports PRX-009 exactly, validates the API marker, and treats terminal
  `dispatch_uncertain` as delete-without-generation/model/update while retaining every ambiguous
  receipt.
- [ ] Fresh child convergence/status-only promotion/post-promotion review completes PAE-001 through
  PAE-038 before parent PRX consumes the evidence; this draft update does not promote status.
