# Design: Proof Explanation and DSP Evaluation

## Current Parent PRX T-052 Import Synchronization

`SPEC-CHG-2026-07-31-PAE-PRX-T052-CHILD-SYNC` updates only the active parent identity consumed
by `PaeDeoTask48ReportRebaselineGate` and the PAE-033 trace. The parent requirements/design/tasks
SHA-256 triple is
`c8f585e26d664f5e6cf3b1d56cb917f17bbac7a5192cddc421ee0b6b8b40b3e2` /
`5b90d8afbcb2f5446d84150e22d18d2c8b1dc8748ba44192dece41c8dbdd5a51` /
`4e01c8a80e1f7921e2f488a887bfcf09004c0b82601a6c2168c6585d26e63a82`.
It adds no component, port, data shape, behavior, or review result; historical triples remain
historical and the applicable independent child review must be renewed before parent T-011.

## Current DEO Task-48 Report Rebaseline

`SPEC-CHG-2026-07-27-PAE-DEO-T48-REPORT-REBASELINE` adds only
`PaeDeoTask48ReportRebaselineGate`. It waits for the external current DEO Task-48 report, then
Task 84 records the report's exact requirements/design/tasks identity and the current approved PRX
three-file identity before Task 73 performs its import/draft-review/promotion gate. PAE imports no
future or guessed DEO byte and remains non-authoritative until Task 64. The current authority path
is `74 -> 80 -> 81 -> 82 -> 83 -> 84 -> 73 -> 64 -> PRX T011`; no runtime component changes.

The Task-84 record consumes the external report only for DEO
`9cb00ba39a34cc0fb035507dd4499c94a9c7b229f6abb4bda9795ffa01397efc` /
`ee7e8d754668e9fb7639e6f691840f0bfb79c793f63909912f944ce3954120cf` /
`759014da8d79a13bd1bb5f1b92096506837049f751d3ac49672448549a67d0c4` and current approved PRX
`c8f585e26d664f5e6cf3b1d56cb917f17bbac7a5192cddc421ee0b6b8b40b3e2` /
`5b90d8afbcb2f5446d84150e22d18d2c8b1dc8748ba44192dece41c8dbdd5a51` /
`4e01c8a80e1f7921e2f488a887bfcf09004c0b82601a6c2168c6585d26e63a82`.
It records no report verdict, reviewer, or ledger and adds no runtime authority.

`PaeCurrentCandidateReviewerIndependenceGate` consumes only invocation-local reports for Task 73
and Task 64. Each report names its reviewer, enumerates every current-candidate author/remediator
including Task 84, proves the reviewer is outside that set, and binds the result to the reviewed
requirements/design/tasks triple. Missing, ambiguous, incomplete, non-disjoint, or mismatched input
fails the review; no report ledger is written to this bundle.

## Historical PRX T-047 PAE-033 Amendment

`SPEC-CHG-2026-07-27-PAE-PRX-T047-CHILD-SYNC` superseded only the then-current PAE-033 parent tuple
and review-gate projection in this design: its PRX requirements/design/tasks identity is
`2814ff312e4b4dac941c3cfcf74f54b7aaf3da7b818ac688083d0f577a951e59` /
`d2aa7f3d061879fdd01c8a26c897d9bc91c44a8750a5884965862950ec46ee05` /
`95b0430e195d572e970367854bf12b4467a6cf032f953f318a1147a085ec91d9`, and Task 83 precedes
current Tasks 73/64. It changes no component, port, data shape, ownership boundary, or runtime
behavior; the preceding PAE-033 tuple is historical only.

## Overview

Add a strict Lean-grounded explainer beside the existing LangGraph workflow and a separate,
immutable evaluation model around workflow artifacts. The API remains the durable product-state
owner; local JSONL remains the reproducible evaluation record. Optional observability adapters
consume completed records without controlling evaluation truth.

## Historical DEO Final-Identity Reopen (superseded by Task 84)

`SPEC-CHG-2026-07-27-PAE-DEO-FINAL-IDENTITY-REOPEN` historically added governance-only
`PaeDeoFinalIdentityGate`. Task 82 demotes requirements to draft and reopens Tasks 73/64 because
their checked state pins the DEO identity preceding DEO-R48-001. The historical gate admitted only
the then-current DEO requirements/design/tasks
`e1d0aba03da548336a5b59dab329c6a0f3bd14c9ad101a866e316070b8487f60` /
`58f2cc33142016d736748ed103aabf10892f060ecf1cf5e16e15e00b2c4b017c` /
`1ef03cbcb186c0709415363e6a0e11c572deff18d85f89fc8023f8afe53324e2`
plus the external fresh current-byte DEO Task-48 report for those bytes. Those bytes are superseded;
current Task 84 instead records the exact triple covered by the current external report.

Task 73 was blocked until that report existed, then performed exact import synchronization, fresh
draft convergence, the explicitly authorized frontmatter-only promotion, ownership PASS, and its
inverse-proved completion marker. A different reviewer then runs Task 64 against promoted bytes and
published only its inverse-proved completion marker. The historical path was superseded by the exact
current authority path `74 -> 80 -> 81 -> 82 -> 83 -> 84 -> 73 -> 64 -> PRX T011`; both current
DEO Task 48 and renewed Task 64 must complete before PRX T011. No runtime design changes.

## Historical Upstream Drift Demotion and Convergence Reopen

`SPEC-CHG-2026-07-27-PAE-CURRENT-UPSTREAM-DRIFT-REOPEN` changes no runtime design. Bundle authority
follows the requirements frontmatter, which is demoted to `draft`; Task 81 invalidates and reopens
Tasks 73 and 64. The historical authority path was
`Task 74 -> Task 80 -> Task 81 -> Task 73 -> Task 64`; it is superseded by the Task-84 path at
this document's head. Task 73 must bind the final
approved/post-reviewed DEO bundle
`3c3317964acfd48909f3a55c45e40980ed355b2346dc0d9e8ef4e5cf7b719174` /
`0a1e61cd4e06c3af535602dd9e980bb779843dd9b55eb2a10b954931a03295c7` /
`e9dc5d78eb1e013f18c6cf7fd7f9e5ac2c62e7e0bbd91bd7fa3da35dfa990d4d` and final API PEX triple
`be13cca1231ae0611f130e726af8f51281dbb06660d5a863c29f370ff30281c7` /
`96876ae940e6013c293b8e0d8978695cb75472dfb074f3608394f6657af12984` /
`086b07f9cbc42c54cafd99cd425dfbc74c36fe38347738169aa305e8b4ef10d7`
before fresh draft review and promotion; Task 64 remains the distinct promoted-byte review. No
implementation or test may use the prior checked markers.

## Current Upstream Authority Imports

`SPEC-CHG-2026-07-27-PAE-UPSTREAM-AUTHORITY-IMPORTS` replaces the completed EXP/PJR/PWA
placeholders with immutable approved bundle identities. `PaeAuthorityImportGate` validates EXP
`a2a3e97055951bae745932e91693f9e6e09de2d1c4edb8d33ddb902a94063563` /
`f66d0ca6650d1bfb6e9dfb8fc6bd8690b6e475ee02d645e5cb895d226f97c055` /
`7fea5fc7eae2e8ace80028a6415ed4f5ae3f02113e3be84d8f6dc76ba5cd5285`, PJR
`75c0dd6f44da5db808d767749896cf751895910cb520e606c796407759b245c4` /
`a59af7fa1fdd6cc0594a123045260db9ac135c37c09d03a5ccb43555de5b86f3` /
`33dd054c62bc02e0efc1fa2e6e6dbe9b88e91c64efb74984b1ae8db066c1627b`, and PWA
`c6e7232aad472529139a7fa91351a1942b0ac4987abaea5089e3bbb4d3aa5f02` /
`92f576820a9c3d1041f90163574e80bcc4ce355ff5c6c6e36cb3d047be4a8f4e` /
`686598da329b043e17efdf91562cd61c202dbe7423d23c8e08e4cc478e2dedcc`, and API PEX
`6a3775af76a224cba05f611980639e54a40d36be8ecbc798c679a7c1469243c1` /
`3af51d11d7f8ca78f02f99362dcacc399286b985b27c0ac99b4bb33760405bf9` /
`6dc7d1f86ab1e693c9a85f1e7830c041dbf29e2d1f69f5d7a8a71fd4d1820d3d`.
Task 73 pins those exact approved/post-reviewed triples before PAE draft review. The gate fails
closed on status or byte drift and imports
only authority already traced by PAE-001 through PAE-038. No runtime component or ownership changes.

## Task-73 Completion Marker and Status Projection

`SPEC-CHG-2026-07-27-PAE-TASK73-COMPLETION-MARKER` adds `Task73CompletionMarkerPublisher`.
Task 73 stays unchecked while exact imports, draft review, frontmatter-only promotion, and ownership
PASS execute. After success, the publisher proves that changing only Task 73 from `[x]` back to
`[ ]` reproduces the consumed tasks bytes, then publishes only `[ ]` to `[x]`. That sole transform
does not invalidate Task 73. Bundle authority follows requirements frontmatter; checked Task 64 is
the implementation-readiness gate.

## Task-64 Completion-Marker Cycle Restoration

`SPEC-CHG-2026-07-27-PAE-TASK64-COMPLETION-MARKER` adds no runtime component. The external
different-reviewer Task-64 review reads exact promoted bytes while the Task-64 checkbox is `[ ]`.
`Task64CompletionMarkerPublisher` is the governance-only publication rule: after and only after a
successful review, it proves that changing the Task-64 token from `[x]` back to `[ ]` reproduces the
exact reviewed task bytes, then changes only that token from `[ ]` to `[x]`. This sole
inverse-proved transform does not invalidate Task 64; any other byte change restarts the applicable
Task-73/Task-64 sequence. Parent DEO Task 36 can therefore observe current approved PAE bytes plus
checked Task 64 without a DEO edit. The SDD-024 side-branch backbone is
`Task 75 -> Task 77 -> Task 78 -> Task 76`, with an additional direct `Task 75 -> Task 78` edge;
it remains independent from `Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64`. Task 79 records this Spec-only
authoring and leaves status, the Task-64 checkbox, code, tests, external reports, DEO, and LFE
unchanged.

## SDD-024 Residual Review-Output Cleanup

`SPEC-CHG-2026-07-27-PAE-SDD024-RESIDUAL-CLEANUP` is a Spec-metadata-only restoration.
`PaeSpecReviewReportBoundary` excludes past review counts, reviewer/source provenance,
review-finding fingerprints, reviewed/baseline bundle hashes, gate output, and verdict copies from
the canonical three-file bundle. It preserves substantive remediation decisions, task state, and
implementation/test evidence. `PfiRetrievalAuthorityImport` uses only the current approved PFI
three-file identity. Task 78 records the corrective authoring; Task 76 remains the fresh external
review and persists no result here. Runtime components and the two existing authority/side-branch
DAGs are unchanged.

## Current Approved PFI Byte Synchronization

`SPEC-CHG-2026-07-26-PAE-PFI-BYTE-SYNC` replaces only the exact active PFI bundle identity. It
changes no imported behavior, component, authority owner, lifecycle, or runtime/test contract.

## Historical Report-Only Review-Ledger Restoration

`SPEC-CHG-2026-07-26-PAE-REPORT-ONLY-LEDGER` removes review-invocation output from the canonical
bundle. Current and historical Spec-review hashes, counters, fingerprints, gate transcripts, and
verdicts live only in the external invocation report. Stable remediation scope, task state, and
implementation/test evidence remain canonical. Task 75 authors this restoration, Task 77
synchronizes current approved PFI bytes, and Task 76 reviews both as a non-authorizing side branch;
they do not reorder the current Task-84 authority path. The same
authoring pins the current approved DEO triple used by the external Task-48 input. No runtime
component or behavior changes.

## Historical DEO Task-48 Authority Import

`SPEC-CHG-2026-07-26-PAE-DEO-TASK48-AUTHORITY-IMPORT` adds one external report-only authority
input to both current review stages without changing the child sequence. `DeoTask48AuthorityImport`
requires exact current DEO requirements
`3c3317964acfd48909f3a55c45e40980ed355b2346dc0d9e8ef4e5cf7b719174`, design
`0a1e61cd4e06c3af535602dd9e980bb779843dd9b55eb2a10b954931a03295c7`, and tasks
`e9dc5d78eb1e013f18c6cf7fd7f9e5ac2c62e7e0bbd91bd7fa3da35dfa990d4d`, plus the fresh external
Task-48 report for those bytes. Task 73 validates that input before its import/draft-review/promotion
work; Task 64 independently revalidates it before promoted-byte review. The input creates no runtime
capability and is never persisted into this bundle. Its historical gate was
`Task 74 -> Task 80 -> Task 81 -> Task 73 -> Task 64 -> PRX T011`; Task 84 supersedes it.

## Historical DEO Task-64 Post-Review Compatibility Restoration

`SPEC-CHG-2026-07-26-PAE-DEO-TASK64-POST-REVIEW-RESTORATION` changes only authority-gate
composition. Completed Task 74 repairs the child trace without editing approved DEO. Task 73 owns
exact approved PFI plus exact approved/post-reviewed EXP/PJR/PWA/API PEX imports, the fresh
all-zero non-authoritative draft review, explicit status-only promotion, and ownership PASS. Current
Task 64 depends on Task 73 and owns only the different-reviewer exact promoted-byte/import all-zero
post-promotion review across PAE-001 through PAE-038. Every pending executable Agent task depends on
Task 64, followed only by the inverse-proved single-token Task-64 completion-marker publication.
The historical gate was `Task 74 -> Task 80 -> Task 81 -> Task 73 -> Task 64`; the current
Task-84 path at this document's head controls. Prior task states authorize nothing.
Runtime components, behavior, status, security, toolchain, persistence,
release, rollback, recovery, tests, and evidence do not change.

## Current Authority-Relocation Gate

`SPEC-CHG-2026-07-26-PAE-AUTHORITY-RELOCATION-GATE` realizes the authority split without changing
Agent runtime behavior; bundle authority follows requirements frontmatter.
`PfiRetrievalAuthorityImport` pins the approved PFI
requirements/design/tasks bytes to
`32fa6f5113712d3e8bfe7484cad65ed0ffd525212a36511a5cd95a3eb3fca243`,
`f00c8e7ad2c151a4e89a47c20dfd7480845db3596c5f38c2e7175fa3b1755129`, and
`d5212f09e8a1edcf93a0af895f84a5d2b1d463c3021267574e4b8f591e7a9739`. PAE uses that authority for
the API-owned top-eight candidate port and Agent-owned real `draft`-role zero-through-four rerank; it
does not redefine PFI behavior.

The exact `TDG -> EXP -> PJR -> PWA -> API PEX` chain is approved and each bundle has passed its
distinct post-promotion review. Task 73 records and validates the exact approved
requirements/design/tasks identities of EXP, PJR, PWA, and API PEX, imports the applicable
deadline/rubric, proof-runtime, workspace-predecessor, and explanation API composition authority,
and rejects missing, draft, stale, drifted, or partially imported bytes. Runtime components continue
to implement the candidate semantics already closed in this draft; an import may not add a second
deadline, rubric, retrieval, lifecycle, persistence, or release authority.

Task 76 independently audits the non-authorizing SDD-024 side branch and is not a predecessor of
Task 73. After Task 82, Task 83, Task 84, current DEO Task 48, and the approved upstream import chain, Task 73
executes two distinct gates
over one immutable candidate sequence: a fresh independent all-zero technical review while status
remains non-authoritative `draft`, then an explicitly authorized status-only promotion followed by
exact ownership PASS and the sole inverse-proved Task-73 completion-marker publication. Current
Task 64 depends on checked Task 73 and uses a different fresh reviewer for the all-zero exact
promoted-byte/import post-promotion
review. Any content byte edit restarts the applicable review. Historical task states authorize
nothing for current bytes. Every still-pending
implementation/test task depends on completed current Task 64. Tasks 28/29 additionally require current real
API Green PJR T-053 and API PEX T-065 after exact approved/post-reviewed PJR T-061, PWA Task 3, and
API PEX T-073; historical PJR T-020/PEX T-033 cannot satisfy that dependency.

## Current PRX T-010 Design Precedence

This section is the current design for the PAE-017 transport/caller/attestation slice and for
PAE-035 through PAE-038. Any later historical `UnixLeanVerifierClient`, shared socket,
loopback/network-none service, worker-direct verifier call, or worker-synthesized attestation text is
superseded by this section; the PAE-017 compiler/toolchain/environment/resource/cleanup mechanics
remain normative inside the HTTP verifier.

- `ProofDispatchV1Consumer` receives exactly one parent-imported
  `pals.proof-job-dispatch.v1` message with long-poll/initial-visibility parameters fixed by
  PAE-035. `ProofDispatchV1Validator` validates manifest queue ARN/URL, raw ID body, exact
  attributes, digest, `MessageId`, and current `ReceiptHandle` before constructing any API/DSP
  command. `ReceiptLifecycle` alone extends visibility, deletes exact terminal work, retains
  ambiguity/invalid/poison work, and creates a fresh claim on redelivery.
- `ClarificationDispatchV1Consumer` imports PRX-009 receive routing and validates the canonical
  empty application-attribute projection, exact body/UUID, system attributes, and same-target API
  `dispatch_schema_version` before any claim/model/update. `dispatch_uncertain` is a terminal
  delete-without-generation outcome; no child codec or delivery inference exists.
- The DSP graph remains Draft -> Sketch -> Prove -> Route/Repair, but candidate/artifact submission
  goes to the API. `AuthoritativeVerificationResultPort` refetches the API-owned persisted result;
  the worker has no verifier client, compiler, mTLS material, or attestation producer. Explain and
  Clarify begin only from that exact verified resource.
- `IsolatedVerifierHttpServer` is a distinct Agent image/task/role. It binds only private port
  18117 with TLS 1.3 mutual authentication and implements only imported `GET /ready` and
  `POST /v1/verify`. After transport/header/DTO/deployment/readiness validation and one-slot
  admission, it invokes the unchanged PAE-017 compiler engine. It returns an imported success
  attestation only after real compile and outcome-anchored cleanup; cleanup uncertainty closes the
  connection and terminates the service without a body.
- `VerifierServerCertificatePort`, `VerifierServerPrivateKeyPort`, and
  `VerifierCaCertificatePort` fetch only exact full ARN plus immutable VersionId SecretBinary.
  Parsed cert/key/CA bytes remain memory-only. The service owns no DB/SQS/model/provider/release
  resource client and cannot consume the API client certificate/key or opposite-role secrets.
- `AgentBehaviorPropertyRegistry` loads the exact PAE-037 artifact, validates its eleven IDs and
  exact mappings across the closed four-requirement set PAE-035 through PAE-038, computes the
  canonical digest, and requires the matching
  `org.pals.agent.behavior-properties.sha256` image label before active receipt mode. The
  `proof-worker-v1 --receipt-mode blocked|active` entrypoint has no legacy/unversioned mode. The two
  Agent image digests, toolchain manifest/digest, and property artifact/digest are only Agent-owned
  PRX-006 release-provenance inputs; Infra owns provider/quiescence observation and durable release
  effects, and API owns admission/reconciliation persistence.

## Requirements Traceability

| Requirement | Design Coverage |
|---|---|
| PAE-001–PAE-006 | `LeanProofExplainer`, typed content objects, strict parser/reference validator |
| PAE-007–PAE-013 | immutable evaluation run/stage/metric objects, artifact evaluator, JSONL store and summaries |
| PAE-010 | isolated semantic-judge interface plus exact one-test/create-only-evidence `lean-explanation-ja-v1` live release oracle |
| PAE-014 / DEO-001–DEO-020 | explicit `evaluation-export-dsp-v1` application service, post-persistence completed-invocation producer boundary, deterministic targets/results, and parent-owned cross-repository contract |
| PAE-015 | typed worker task parser, API PEX-009/012/017–019 claim-status client methods, monotonic hard deadline, dispatch/claim-gated execution, receipt lifecycle, and rollout runbook |
| PAE-016 | bounded `ProofPipeline` verify/diagnose/LLM-route/regenerate loop with ordered attempt artifacts |
| PAE-017 | PAE-036-hosted compiler engine; canonical exhaustive toolchain manifest with exact Lean/Git descriptors, Git executable/version/content, and six exact descriptor-`root/src/lean`-relative source path/hash pairs; descriptor-authoritative toolchain and fixed project-root/Git pinned FDs with per-phase re-attestation; O_EXCL mutable-file and manifest-listed immutable-input validation; startup-pinned direct Lake/Lean via validated `setup-file`; exact five-variable environment; outcome-anchored descendant cleanup; complete grammar and setup/direct-Lean outcome matrices |
| PAE-018 | strict non-mutating reader plus explicit digest-pinned semantic-comment-v2 history migration with stable lock, byte-exact backup, fence, atomic replace, and audit report |
| PAE-019 | exact five-variable semantic-evaluator state, exact private/public identity, separately bound unequal credential, loopback-HTTP/remote-HTTPS transport, normalized inequality from every contributor, distinct post-runtime request/no same-call reuse, pinned provenance, and zero-call unconfigured judge |
| PAE-020 | verifier-server-only imported attestation production after real compile/cleanup plus worker synthesis denial and authoritative API-resource validation |
| PAE-021 | exact PJR acquisition `acquired|busy|terminal`, renewal `renewed|terminal`, forbidden-status rejection, terminal stop/ack handling, lease renewal, API candidate submission, and authoritative verified-resource refetch with no direct verifier call |
| PAE-022 | extra-forbid proof-status projection, metadata-free API diagnostics, and fixed public failure classification |
| PAE-023 | full clarification-resource validation before acknowledgement and byte-exact theorem/Lean preservation |
| PAE-024 | exact finite semantic threshold comparison without tolerance |
| PAE-025 | version-dispatched closed history registries and deterministic status recomputation |
| PAE-026–PAE-029 | immutable suite manifest, schema-v3 evidence recorder with exact eight-role registry/comparability/model-call/cardinality and evaluator-contributor/distinct-call validation plus Git-bound toolchain provenance, fail-closed aggregates, child CLI plus parent-owned GNU Make 0/2 orchestration, and durable summaries |
| PAE-030 | exact completed-invocation DTO projector, integer/half-even case mapping, and summary truth oracle |
| PAE-031 | canonical material fingerprints, parent-framed producer HMAC, OS-CSPRNG provisioning, and environment-specific durable key binding |
| PAE-032 | exact-byte payload/sidecar serializer, deterministic names, ordered create-only publication, exact replay/conflict behavior, privacy guard, and torn-pair behavior |
| PAE-033 | Task 82 demotion/reopen; Task 83 historical PRX provenance; Task 84 external current DEO Task-48 report and approved PRX triple binding; then Task 73/64 import, independent review, status/marker gates. PAE-035–PAE-038 import PRX-001–PRX-009/AC-001–AC-009 only from current parent triple `c8f585e26d664f5e6cf3b1d56cb917f17bbac7a5192cddc421ee0b6b8b40b3e2` / `5b90d8afbcb2f5446d84150e22d18d2c8b1dc8748ba44192dece41c8dbdd5a51` / `4e01c8a80e1f7921e2f488a887bfcf09004c0b82601a6c2168c6585d26e63a82`. The sole active order is `Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64 -> PRX T011`; historical report/triple/marker state is non-authorizing. |
| PAE-034 | natural-statement/OpenMath entry, PostgreSQL/pgvector top-8 authority, canonical structural plus real LLM 0..4 rerank, complete bounded graph, fixed eight-role `openai/gpt-5.4-mini-2026-03-17` registry, and full real live gate |
| PAE-035 | parent-imported proof-dispatch validator, one-receipt DSP worker, visibility/delete ambiguity, redelivery, poison retention, and fresh-claim lifecycle |
| PAE-036 | parent-imported private TLS-1.3 mTLS HTTP verifier on port 18117, exact readiness/request/response production, one-slot compiler admission, and three immutable SecretBinary consumer ports |
| PAE-037 | blocked/active v1 worker lifecycle, old-worker denial participation, behavior-property/OCI binding, Agent images/toolchain PRX-006 provenance inputs, repository-local commands/docs/telemetry, and no-provider/no-persistence ownership audits |
| PAE-038 | parent-imported PRX-009 clarification receive/router and API marker validator, fresh-claim/visibility/update lifecycle, terminal `dispatch_uncertain` zero-generation deletion, and ambiguity/poison receipt retention |

### Parent PRX Traceability

| Parent requirement | Agent realization or explicit boundary |
|---|---|
| PRX-001 | Agent owns only receipt/DSP worker and verifier server/compiler; API owns HTTP/DB/reconciliation and Infra owns resources/secrets/IAM. |
| PRX-002 | PAE-035 imports the exact v1 dispatch DTO and queue registry without redefining either. |
| PRX-003 | PAE-036 produces the exact isolated-verifier HTTP readiness/result contract; API reconciler is sole caller. |
| PRX-004 | PAE-037 implements only Agent blocked/drain/resume participation and old-worker denial behavior. |
| PRX-005 | PAE-036 consumes only server cert/key/shared CA by full ARN plus VersionId; Infra creates and rotates them. |
| PRX-006 | Agent contributes only its worker/verifier image identities, toolchain manifest/digest, behavior-property artifact/digest, and imported closed telemetry; Infra owns provider/quiescence evidence, bundle/signature/archive custody, and durable release effects, while API owns admission persistence. |
| PRX-007 | Agent tests use the parent corpus and exact child property IDs; no second shared registry exists. |
| PRX-008 | PAE-033/PAE-037 define child convergence, evidence, commands, docs, and rollout contribution without promoting status. |
| PRX-009 | PAE-038 imports clarification wire/marker/terminal meaning and owns only Agent receive, validation, claim/model/update, visibility, retain, and delete implementation. |

### Parent DEO producer traceability

| Parent requirement | Agent realization or explicit boundary |
|---|---|
| DEO-001 | PAE-014 owns only canonical-to-DTO production; every consumer/vendor surface remains outside Agent. |
| DEO-002–DEO-006 | PAE-030 completed-invocation membership, exact case mapping, and summary truth; PAE-032 exact artifact. |
| DEO-007 | Consumer command/parser behavior is explicitly excluded by PAE-014. |
| DEO-008 | PAE-031 exact producer identity/comparability HMAC framing and vectors. |
| DEO-009 | Remote projection registry/read-back behavior is explicitly excluded by PAE-014. |
| DEO-010 | PAE-030 never filters/shards for the consumer object bound; keyless counting remains consumer-only. |
| DEO-011 | Helper/remote state, marker, receipt, and read-back behavior is explicitly excluded by PAE-014. |
| DEO-012 | PAE-031 private key/material handling and PAE-032 closed DTO/log privacy guard. |
| DEO-013 | PAE-033 independent grammar, parent vectors, producer baseline, and shared cross gate. |
| DEO-014 | PAE-031 producer secret and exact environment/version binding; projection secret remains consumer-only. |
| DEO-015 | PAE-033 current Task 82 demotion/reopen, Task 83 historical PRX provenance, Task 84 external current DEO Task-48 report identity binding, then Task 73 focused imports/draft-review/status-only-promotion/ownership gate and Task 64 independent revalidation/post-promotion readiness; current DEO Task 48 and renewed Task 64 precede PRX T011. Tasks 75/76 are a non-authorizing SDD-024 side review and historical task states authorize nothing. |
| DEO-016 | PAE-032/PAE-033 no authenticity or mathematical-truth overclaim. |
| DEO-017–DEO-018 | Consumer CLI outcome/helper behavior is explicitly excluded; PAE-032 owns only producer per-file publication. |
| DEO-019 | PAE-031 OS-CSPRNG, shared `.local` registry, and `.dev`/`.prod` exact ARN+VersionId. |
| DEO-020 | PAE-032 privacy/fault tests and PAE-033 Red evidence, baseline, vectors, cross gate, and tiers. |

## Affected Repositories

- `pals-agent`: generation, validation, evaluation, history, v1 receipt/DSP worker orchestration,
  verifier server/compiler images, and Agent-owned behavior-property evidence.
- `pals-api`: proof generation claim/fence and verified-resource authority are governed by its
  proof-job-runtime Spec; transactional explanation references are governed by proof-explanations.
- Parent repository: DEO-021 exclusively owns the three PAE-029 Make targets. PLS-012 resource-
  boundary evidence is read-only only for unchanged verifier limits; it cannot authorize its
  superseded Unix/network-none topology. Approved PRX and the Infra child exclusively own the current
  private mTLS HTTP deployment binding. This child owns none of those parent/Infra surfaces.
- `pals-webfront`: governed separately by its proof-explanation-clarification Spec.
- `pals-observability`: downstream consumer/vendor implementation is outside this child revision.
  Parent `specs/dsp-evaluation-observability-export` DEO-001 through DEO-020 own the complete
  cross-repository contract; this bundle neither defines that consumer nor treats a local LFE ID as
  authority.
- `pals-infra`: exclusively owns queue/DLQ, ECS/ALB/network/IAM/KMS/Secrets resources and secret
  versions. This child defines consumer ports and evidence only and creates or mutates none.

## Architecture and Components

```text
natural statement
  -> OpenMathStructurer[openmath] (at most 3 parse/canonicalize/validate attempts)
  -> PgvectorDraftRetriever (PostgreSQL cosine LIMIT 8, no cutoff)
  -> OpenMathStructuralEvidence + RelevanceReranker[draft] (0..4)
  -> DraftGenerator[draft] (also when context is empty)
  -> SketchGenerator[sketch]
  -> Prover[prove]
  -> API candidate/artifact submission -> API-owned reconciler -> PAE-036 HTTP verifier
  -> API authoritative result refetch
  -> failed: RepairRouter[route] -> RepairGenerator[repair] -> selected node -> API submission
  -> verified durable artifact: LeanProofExplainer[explain]
  -> selected explanation section: LeanProofExplainer[clarify]

verified Lean + theorem statement
  -> LeanProofExplainer.explain
  -> strict JSON parse + exact line validation
  -> API explanation state
  -> frontend concise explanation
  -> learner selects section + asks question
  -> typed clarification queue task
  -> LeanProofExplainer.clarify(section, verified Lean)
  -> overlap validation
  -> API clarification state
  -> frontend detailed answer

proof queue delivery
  -> fresh UUIDv4 generation claim at API PJR-012
  -> acquired + visibility extension; busy retains receipt; terminal stops and acknowledges by exact state
  -> generate / submit / refetch / checkpoint with claimed PJR-013 status updates
  -> every pre-spend renewal is renewed or terminal; any other response is malformed
  -> stale, expired, conflict, malformed, or visibility failure: stop all later work and retain receipt
  -> accepted verified write
  -> refetch authoritative persisted verified Lean/attestation
  -> end proof claim but retain the same receipt
  -> separately claimed explanation flow
  -> exact terminal completed|failed explanation
  -> delete the retained proof receipt

DSP artifact + optional explanation
  -> deterministic stage evaluator
  -> optional separately configured semantic evaluator
       - exact five-variable state and private (provider,model,revision,origin) identity
       - normalized provider/model differs from every contributing generation identity
       - dedicated evaluator credential differs from generation binding/bytes
       - one new post-runtime evaluator-only request; no generation response/cache/batch reuse
       - loopback-HTTP/remote-HTTPS endpoint; no redirects
       - no generation-setting or generation-credential fallback
       - absent tuple -> zero-call not_evaluated enrichment
  -> immutable EvaluationRun
  -> append-only JSONL history (canonical)
  -> optional observability exporter
  -> history summaries / comparisons

versioned suite manifest (evaluation-only expectations)
  -> fresh BenchmarkProblem(id, prompt) runtime input only
  -> pipeline + scoped generation/evaluator evidence recorders
  -> one strict schema-v3 case record per completed case
  -> re-read persisted run -> atomic JSON + Markdown summary
  -> smoke/full/compare parent Make targets

strict completed schema-v3 invocation + canonical PAE-028 summary
  -> AgentDspExportCommand(invocation_id, pinned output directory)
  -> CompletedInvocationView in journal expected-case order
  -> DspExportV1Projector
       - canonical material SHA-256 fingerprints
       - producer identity/comparability HMAC
       - exact 26-metric integer mapping + summary oracle
       - independent Agent DTO validation + recursive privacy guard
  -> deterministic invocation-fingerprint payload/sidecar names
  -> create-only publication | exact-existing replay | immutable conflict
  -> DspExportArtifactPublisher
       - exact compact payload + LF
       - SHA-256 sidecar + LF
       - payload commit, then sidecar commit
  -> parent vectors / producer baseline / cross-repository gate

credentialed worker (no Lean toolchain, verifier client, or mTLS material)
  -> API candidate/artifact submission and authoritative result refetch

API-owned verified reconciler (sole application caller)
  -> private TLS-1.3 mTLS HTTP :18117
  -> Agent verifier container boundary
       - non-root / no capabilities / no_new_privs
       - only imported private service network and startup/rotation Secrets endpoint
       - read-only root and Lean project; bounded request tmpfs
       - cgroup CPU/memory/PID limits
  -> networkless scrubbed, rlimited Lean process group

invalid legacy schema-v2 JSONL
  -> strict normal load failure (no mutation)
  -> explicit semantic-comments-v2 CLI + expected source SHA-256
  -> stable exclusive history lock
  -> byte-exact digest-named backup + durable migration fence
  -> validated same-directory temporary + atomic replace + directory fsync
  -> strict five-record reload + audit-only report
```

Repair execution remains inside the proof pipeline:

```text
candidate -> blocking preflight (safety/user formal identity/exact-Draft identity)
  -> pass: isolated Lean verify
  -> success: persist verified result
  -> repairable failure: persist only actual runtime/preflight/compiler diagnostics
     -> route role selects draft | sketch | prove (at most three real calls; no fallback route)
     -> one repair role call -> selected node and every downstream node -> preflight/Lean verify
  -> non-repairable failure | route selection failure | budget exhausted: persist failed result

terminal runtime artifact
  -> post-runtime evaluator scope only
  -> generated-sketch/final-Lean structural adherence metric
  -> may fail without changing verification, diagnostics, repair, or terminal state
```

No expected benchmark method, hidden harness, rubric, relevance label, sentinel, or generated-sketch
text is a runtime oracle. Once safety, explicitly supplied formal-theorem identity, and exact-Draft
identity/equivalence preflight pass, isolated Lean success is proof-correctness authority. A
semantically equivalent or rephrased sketch may therefore yield a verified proof and a false
post-runtime sketch-adherence metric. Blocking safety/formal-identity/exact-Draft preflight still
makes zero verifier calls; compiler failure remains repairable and never becomes success.

## Interfaces and Contracts

- `LeanProofExplainer` receives verification success explicitly; it does not infer verification
  from non-empty code.
- `LeanProofExplainer.clarify` independently requires strict `verified=true` before selecting a
  section or constructing a prompt. The worker cross-checks PEX-011 proof-job ID, theorem, and Lean
  against a fresh proof worker-input whose state is exactly `verified` before claim acquisition.
- Explanation sections carry stable IDs and exact `start_line`, `end_line`, `excerpt` references.
- Clarification receives the full completed explanation plus a selected section ID and question;
  its answer is a more detailed learner-facing treatment grounded in the same verified Lean.
- `PalsApiClient.acquire_proof_generation_claim` validates the PJR-012 response as one exact closed
  envelope. `process_proof_job` creates one fresh UUIDv4 per nonterminal delivery and cannot enter
  the pipeline before same-target `acquired` plus successful visibility extension. Every pipeline
  status callback carries that claim and consumes the exact PJR-013 update envelope; stale,
  expired, conflict, malformed, or visibility-renewal failure raises a terminal local control-flow
  exception that prevents every later model, route, verifier, or explanation call.
- An accepted verified callback is not explanation authority. The worker re-fetches the proof-job
  worker input and validates exact verified Lean, artifact, and attestation before entering the
  separately claimed explanation path. Local candidate Lean is discarded for that decision. The
  proof claim ends, but the current proof receipt is retained as the only durable recovery trigger
  until that proof-ID-keyed explanation is durably completed or failed.
- Proof-status serialization is a pure extra-forbid projection to
  `pals.proof-status-context.v1`. It removes diagnostic metadata and every prompt, raw output,
  rationale, stdout/stderr, endpoint, credential, and exception field before the API client sees
  the value. Known provider/model/selector/transport failures map to the fixed PAE-022 public
  code/message pairs; unknown caught model/provider failures map to `llm.generation_failed`.
- Clarification worker inputs are parsed as complete closed resources and checked against the
  requested clarification ID before terminal acknowledgement. The nonblank helper tests
  `value.strip()` only as a predicate and returns the original theorem/Lean string unchanged.
- Evaluation stages and statuses are closed literal sets and serialized with a schema version.
- A table-driven deterministic evaluator implements the exact per-stage extraction/roll-up oracle.
  Explanation-stage evaluation first requires exact boolean proof verification success; reference
  validation cannot upgrade rejected or unverified Lean. Repair-stage evaluation validates every
  mandatory key, ordered attempt, final/top-level equality, and structured terminal event.
- A semantic judge returns only closed-rubric numeric dimensions; no generated comments/rationales
  are requested or persisted. Exceptions become unevaluated metrics. `AgentSettings` parses the
  exact PAE-019 five-variable state independently of generation
  settings. `EvaluatorEndpointPolicy` canonicalizes the exact origin, permits HTTP only for proven
  loopback, requires HTTPS otherwise, disables redirects/proxy forwarding, and gives the private
  transport helper only the dedicated OpenAI Bearer credential for that origin. Ollama and
  unconfigured factories reject a credential. `EvaluatorCredentialPolicy` proves the OpenAI
  evaluator credential binding and bytes differ from generation. `build_semantic_stage_judge` constructs only that
  configured provider/model/endpoint. After generation termination,
  `EvaluatorIndependenceValidator` lowercases exact ASCII provider/model tokens and rejects equality
  with any non-null identity attached to contributing generation rows/content before the first judge
  request. `EvaluatorCallSeparationRecorder` requires one fresh evaluator-only request and rejects a
  generation request/response ID, cache entry, batch member, or pre-runtime start. Otherwise the factory returns an unconfigured judge that can only mark available stages
  `not_evaluated`; it never copies generation defaults or credentials.
- `tests/live/test_lean_explanation_release.py::test_lean_explanation_ja_v1` is the only release
  harness. It records process start, rejects an existing evidence target, and runs the complete
  PAE-034 graph through real OpenAI, PostgreSQL/pgvector, repeated Route/Repair, PAE-017, durable
  artifact persistence, Explain, required Clarify, reference validation, and a distinct configured
  evaluator request. It validates the exact role registry/call counts, retrieval counts, identity/
  request separation, and direct rubric thresholds. Only
  after all checks pass does `LeanExplanationReleaseEvidenceWriter` create/file-fsync the closed
  mode-`0600` evidence object and directory-fsync it. The exact pytest/JUnit command and the strict
  one-test/no-skip/evidence checks remain operational acceptance, not a second product API.
- Semantic pass helpers reject booleans/non-finite values and use only direct `value >= threshold`
  comparisons. No tolerance, rounding, or display conversion participates in an evaluation oracle.
- `EvaluationRun.from_dict` first dispatches on an exact supported integer schema version. Separate
  v2 and v3 parsers reject unknown keys and enforce stage-specific metric name/kind/source/status
  registries, then recompute deterministic stage status rather than trusting serialized status.
- `EvaluationSuiteRunner` loads the immutable PAE-026 manifest but constructs only a fresh
  `BenchmarkProblem(id, prompt)` for the production pipeline. Suite expectations, strategies,
  compile oracles, semantic rubrics, and prompt sentinels remain evaluation-side inputs.
- Scope-tagged prompt recorders capture every OpenMath, Draft relevance/ordinary Draft, Sketch,
  Prove, selector-retry, routed-repair, Explain, and Clarify generation call separately from schema-v3 `draft_semantic` and
  `sketch_semantic` evaluator calls. Runtime must terminate before evaluator scope starts.
  Generation capture rejects every manifest strategy/relevance/rubric/sentinel/hidden-harness
  value; evaluator capture requires the case sentinel and applicable rubric. Raw captures are
  discarded after the closed prompt-channel evidence is assembled.
- Scoped evidence recorders collect every attempted generation/evaluator call, typed usage and
  provider actual-cost evidence, distinct evaluator/rubric provenance, ranked retrieval, first and
  final isolated compiles, repair rounds, monotonic latency, and explanation-chain digests. A case
  assembler emits null/`not_evaluated` for every missing family; it never fills missing usage or
  cost with zero and never treats non-empty draft/sketch text as semantic accuracy.
- `EvaluationSummaryV1` is derived only after strict re-read of one completed live invocation whose
  journal, manifest case set, origin, case digests, and exact comparability object/digest match.
  Closed rate/scalar/transition/histogram types construct the exact PAE-028 root, count/status/null
  equations, hit@k, distinct rubric rates, sketch adherence, paired compile/uplift, repair
  distribution/convergence, nearest-rank p50/p95, complete token totals, overall cost totals, and
  chain completeness. Synthetic aggregate helpers and partial serializer fixtures cannot call live
  authorization or produce a production exit code. Canonical JSON and derived Markdown publish
  through same-directory temporary file, file fsync, `os.replace`, and directory fsync.
- `DspExportV1Projector` receives only a validated `CompletedInvocationView` built from the strict
  post-persistence re-read. It emits one closed DEO envelope and never accepts a raw history path,
  caller case selection, schema-v2 row, consumer model, or vendor type. Consumer, projection-HMAC,
  SDK/helper/receipt/outcome/read-back behavior remains outside Agent under DEO-001 through
  DEO-020. Export compatibility or failure cannot change history, journal, summary, comparison,
  gate, or CLI exit.
- `ProofDispatchV1Consumer` and `AuthoritativeVerificationResultPort` are the only proof-runtime
  boundaries constructed by the production worker factory. They consume the imported queue/API
  contracts and expose no compiler, verifier transport, mTLS, or attestation-construction method.
- `IsolatedVerifierHttpServer` is constructed only in the verifier service entrypoint. Its router
  has exactly the imported readiness and verify operations, validates mTLS/deployment/request bytes
  before one-slot admission, invokes the PAE-017 engine, and maps only to imported responses.
- Claim envelopes are parsed together with expected resource kind and ID. Exact PEX internal
  resource key sets, identity, state/content/diagnostic types, lease/status combinations, and
  status-to-state mapping are checked before either model permission or acknowledgement.
- All API methods validate dynamic IDs with the PAE-015 ASCII grammar and percent-encode them as
  one path segment. Callers cannot pass a pre-escaped value, slash, backslash, query, fragment,
  control character, leading dot, or oversized ID.
- OpenAI, Ollama, and PALS API clients share `HardDeadlineHttpTransport`. A request body and secret
  headers pass to a spawned helper over a private pipe, never argv/environment. The parent measures
  one monotonic deadline covering process startup, DNS, connect, headers, and a 1,048,576-byte body;
  expiry terminates, then kills if necessary, joins, closes the pipe, and returns a closed timeout.
  The helper reads at most 1,048,577 bytes so exactly 1,048,576 bytes plus EOF succeeds while any
  larger success/error body returns a typed oversized-response failure without parsing its prefix.
  HTTP error bodies are never retained in public exceptions.

## Release Runtime Architecture

`ReleaseRoleRegistry` is an immutable code constant with revision
`pals.release-role-registry.v1`. Its constructor validates the exact ordered eight PAE-034 entries
and exposes no mutation or environment merge method. `ReleaseConfiguration` accepts only OpenAI
endpoint, credential, and bounded transport settings; it rejects every known provider/model selector
before constructing a client. Every response passes `ReleaseModelIdentityValidator` before its
content is consumed. Test adapters live behind an explicit non-release factory that cannot create
`origin=live`, release evidence, or an authorized journal.

`OpenMathStructurer` owns one three-attempt transaction. It calls the `openmath` client, then passes
bytes through `OpenMathProfileParser`, `CanonicalOpenMathWriter`, and
`OpenMathPropositionValidator`. The canonicalizer alpha-renames binders in traversal order and uses
exact content-dictionary symbol identities. Attempts 2/3 receive only bounded diagnostics from the
previous candidate. Exhaustion returns `pals.openmath_structuring_failed`; the application service
has no alternate parser, catalog lookup, benchmark fixture, or default expression edge.

`PgvectorDraftRepository` is the sole release `DraftRepository`. It checks the catalog/embedding
fingerprint, executes one parameterized cosine query with fixed limit 8 and stable ID tie-break, and
returns at most eight minimal immutable rows. `OpenMathStructuralScorer` computes only canonical-tree
evidence. `DraftRelevanceReranker` makes one real `draft`-role call over those rows and validates an
ordered unique 0..4 ID selection. `DraftGenerator` is a separate ordinary `draft`-role call and is
always invoked, including an empty selection. Repository/scoring/rerank failure returns a typed
failure; dependency injection does not install a packaged, in-memory, lexical, exact-match, cutoff,
threshold, benchmark, or ad-hoc candidate fallback in release composition.

`ReleaseProofGraph` has explicit nodes `openmath -> retrieve -> draft -> sketch -> prove -> verify`.
On repairable verification failure, `RepairRouter` uses the `route` role under PAE-016's three-call
parser, `RepairGenerator` uses the `repair` role once, and a closed transition table re-enters
`draft`, `sketch`, or `prove` and runs all later nodes. `RepairBudget` counts completed repair
generations and retains the existing 12/[1,64] contract. `VerifiedArtifactGate` accepts only a
successful PAE-017 result whose checkpoint is durable; it alone opens `explain`, and the selected
section plus the same artifact alone opens `clarify`.

### User- or exact-retrieval-selected ε–δ preflight

Before `verify` invokes the isolated verifier, `ProofPipeline` derives the ε–δ method constraint
from either the user's explicit request or one exact OpenMath-equivalent `continuous_square` Draft
retrieval. The retrieval path carries exact-equivalence evidence with each selected context; only
that exact Draft ID is a method source, while approximate/reranked/nonmatching contexts stay
advisory. For either ε–δ source it strips Lean comments and strings, then requires executable
uses of `Metric.continuous_iff`, an introduced `ε`, and a `let` or `set` binding for `δ` (or `delta`).
It rejects `continuous_*` shortcuts other than `continuous_iff`, `Continuous.*` shortcuts, and the
`continuity` tactic with typed diagnostic `pals.proof_method_mismatch`. The diagnostic enters the
ordinary repair route; no candidate can be published as verified until a repaired candidate passes
this gate and isolated Lean verification. No benchmark, hidden harness, evaluator, or approximate
retrieval context is a method source. (PAE-013, PAE-016;
`SPEC-CHG-2026-07-31-PAE-EXACT-X2-EPSILON-DELTA`)

`LeanExplanationLiveReleaseHarness` composes only the production registry/repository/graph/verifier/
artifact/evaluator factories. Private recorders count role calls, structurer attempts, pgvector rows,
selected contexts, repair cycles, verifier failures/success, artifact commit, and evaluator request
separation. The evidence writer receives only closed validated counters/identities/digests after the
run; a fixture/mock/recorded/template/cached/patched provider cannot implement the production marker
interfaces required by the harness.

## DEO-v1 Agent Producer Architecture

### Readiness and ownership boundary

Historical parent and child task states authorize nothing for current bytes. The current child gate
is Task 73 followed by current Task 64. Current Task 64 is a hard predecessor of every
still-pending PAE-001 through PAE-038 test and implementation task, not only the producer tasks. The
dependency is:

```text
approved PFI exact three-file identity
  + TDG convergence/status-only promotion/distinct post-review
  -> EXP exact TDG import/convergence/status-only promotion/distinct post-review
  -> PJR exact EXP import/T-059/T-060/T-061
  -> PWA Task 3 convergence/status-only promotion/distinct post-review
  -> API PEX T-070/T-071/T-072/T-073
  -> Task 74 / Task 80 / Task 81 completed authoring
  -> Task 82 demotion/reopen
  -> Task 83 historical PRX provenance
  -> Task 84 external Task-48 report identity binding
  -> Task 73 exact PFI/EXP/PJR/PWA/API PEX import-only alignment
  -> Task 73 fresh child draft pre-promotion review:
       technical verdict == IMPLEMENTATION READY;
       CRITICAL=0; HIGH=0; no material question;
       authority == false while status is draft
  -> Task 73 explicit authorized status-only draft -> approved promotion
  -> global REP-005 ownership checker == PASS
  -> inverse-proved Task-73 completion-marker publication:
       change only the Task-73 checkbox token [ ] -> [x]
  -> Task 64 different fresh promoted-byte/import post-promotion child review:
       CRITICAL=0; HIGH=0; no material question; IMPLEMENTATION READY
       Task-64 checkbox remains [ ]
  -> inverse-proved Task-64 completion-marker publication:
       change only the Task-64 checkbox token [ ] -> [x]
  -> failing mapping/key/publication/privacy tests
  -> dependent producer implementation
  -> producer baseline + parent vectors
  -> parent cross-repository gate
  -> dark rollout and export-disable rollback
```

Completed PLS T-071, completed parent T-011, and completed parent DEO T-036 are independent hard
predecessors of every pending Agent implementation or test task. They are not Task 73 Spec-promotion
predecessors; PLS T-071 and parent T-011 have no ordering edge, while DEO
`T-048 -> (T-011) -> T-049 -> T-050 -> T-051 -> T-052 -> T-053 -> T-036` remains acyclic.

Historical Task 38/53/64 states authorize nothing for current bytes. Current Task 73 owns
import/pre-review/promotion/ownership and current Task 64 owns the distinct post-promotion
review plus its sole inverse-proved completion-marker publication. Before promotion, the ownership
checker is diagnostic only. Any byte change after
pre-promotion review restarts the applicable review. The draft reviewer records the all-zero
technical verdict and explicitly records that draft status is non-authoritative. Approved status
alone, a historical task state, parent ownership PASS, consumer readiness, or fixture
acceptance cannot substitute for the current distinct post-promotion verdict. Only the exact
Task-64 checkbox-token publication is exempt from invalidating that verdict; every other promoted
byte change restarts Task 64. No pending test or
implementation task may start before current Task 64 completes; Tasks 28/29 then additionally wait for real
PJR T-053/API PEX T-065 Green, and no Green task may run before its named Red predecessor has failed
for the intended missing behavior. This realizes PAE-033 without claiming Tasks 73/64 have run.

The Agent package contains no parent or Observability runtime dependency. Parent contract files and
vectors are test inputs only. Source/import checks fail on a shared parser, generated schema/model,
validator package, formula helper, code-generation output, or consumer class. Agent's independent
grammar is implemented from the parent text in Agent-owned frozen DTO types.

### Completed invocation adapter

`AgentDspExportCommand` is the only application-service invocation surface. Its CLI adapter parses
the exact PAE-014 options, traverses every absolute output-directory component no-follow from a
pinned filesystem-root descriptor, requires a final effective-UID-owned mode-`0700` directory, pins
that descriptor, resolves the UUIDv4
through canonical repositories, and calls the reader/projector/key/serializer/publisher once. It
accepts no injectable source objects or filenames. It maps closed domain results to the exact
stdout/stderr/exit contract and formats no exception, identity, path, digest, key, or DTO value.
The adapter applies the requirements' first-match failure table at explicit phase boundaries:
request/directory validation, completed-source read, key/configuration resolution, target inspection,
then publication. Domain failures are closed tagged values rather than exception-string matching;
publication-started is carried as an internal boolean capability so every later durability ambiguity
maps only to `publication_failed`.

`CompletedInvocationReader` acquires the existing history/journal read capability and constructs a
frozen `CompletedInvocationView` only after the ordinary PAE-025/PAE-029 strict re-read proves:

- one `completed` live journal and canonical PAE-028 summary;
- a completed PAE-029 outcome corresponding to exit 0, 1, or 2, without requiring exit-0
  authorization; exit 3 and every running/interrupted/incomplete journal are rejected;
- exact invocation/run/suite/profile/manifest/comparability identity;
- `case_count` in `[1,1000]`;
- one and only one history row per journal `expected_case_ids` element;
- no extra represented case and exact case-manifest digest equality.

The view stores cases in `expected_case_ids` order and exposes no selection/filter function.
`DspExportV1Projector` enumerates that tuple once to assign ordinals and rejects any identity,
membership, order, or summary mismatch before resolving a producer key. The adapter never rewrites
history or summary and does not accept in-memory pipeline results. This realizes PAE-014 and
PAE-030's complete-invocation boundary.

### Closed DTO and mapping pipeline

Agent-owned frozen types are `DspMetricV1`, `DspCaseV1`, `DspStageStatusCountsV1`,
`DspBooleanRateV1`, `DspAggregateV1`, `DspSummaryV1`, and `DspExportEnvelopeV1`. Constructors use
extra-forbid closed key registries, preserve the requirements' key/array order, distinguish JSON
booleans from integers, and reject unknown/missing/duplicate names, invalid statuses, bounds,
nullability, ordinals, duplicate fingerprints, or summary/case fingerprint mismatch. These types do
not inherit from or serialize `EvaluationRun`, `EvaluationSummaryV1`, a parent class, or a consumer
class.

`DspCaseMapper` uses one immutable 26-entry registry whose entries contain only the canonical stage
and metric name, expected canonical kind/status/value family, exact conversion function, DTO name,
and parent bound. Registry order is DTO order. It copies seven stage statuses and maps
`not_evaluated` only to null. An evaluated value is converted once; no alternate metric, summary
fallback, source inference, default, or coercion exists.

`DecimalIntegerMapper` receives the exact persisted JSON number token through a Decimal-preserving
strict read path. Quality and USD values are multiplied by `Decimal(1000000)` and quantized to a
zero-scale Decimal with `ROUND_HALF_EVEN`, then converted to a bounded integer. Binary float,
formatted display text, and canonical summary rounding are absent from this path. Integer/boolean
sources are type-checked directly. A bound or token failure raises a closed mapping error before
publication and leaves the source untouched.

`DspSummaryMapper` consumes the completed tuple of already mapped cases and the strict PAE-028
summary. It first rederives the PAE-028 source-domain statuses/counts/raw Decimal formulas, then
independently constructs mapped-domain stage triplets, boolean rates, quality means, scalar totals, latency
percentiles, and the 65-bucket repair histogram using exact integer arithmetic. `round_half_even`
for a rational is implemented as quotient/remainder with an explicit less-than/greater-than/tie
branch and even-quotient tie selection; it does not use float division. Percentiles sort mapped
latency integers and use `ceil(p*n)-1`. Exact integer/count facts are compared directly; decimal
facts are validated in their source domain and mapped facts in their converted domain. It never
equates a once-rounded raw aggregate with a sum or mean of individually rounded values. It compares
`summary_status`, then validates all parent equations/bounds. Parent-only aggregates are still
Agent-derived truth from the same canonical cases. No consumer or remote-object-count code is
called.

### Material fingerprints and producer HMAC

`CanonicalMaterialFingerprintBuilder` canonicalizes only the five exact material objects from
PAE-031 with an Agent-owned material encoder that preserves PAE-026 key/string/array rules and
normalizes every persisted Decimal token directly to the exact exponent-free arbitrary-precision
form in PAE-031. Integers remain minimal decimal and binary float is forbidden. It computes each case-record digest,
frames `kind` and object bytes behind `PALS-PAE-DEO-MATERIAL-v1`, and returns five families of private
lowercase SHA-256 `hex64` values. The builder validates exact object keys and invocation-wide
comparability before hashing. Material values are held only long enough to construct producer HMACs
and are neither serialized nor logged.

`ProducerFingerprintHmac` is a small parent-contract implementation with two closed methods:

- `identity(kind, material_fingerprint)` for `invocation|run|suite|case`, prefix
  `PALS-DSP-FINGERPRINT-v1`, and parts `kind,"deo-v1",key_version,material_fingerprint`;
- `comparability(material_fingerprint)` for prefix `PALS-DSP-COMPARABILITY-v1` and parts
  `"comparability","deo-v1",key_version,material_fingerprint`.

Both use UTF-8 u32-big-endian length frames and full lowercase HMAC-SHA-256 output. Inputs are
nonempty and unnormalized. There is no truncation in Agent. The implementation exposes a test-only
message-bytes hook for exact public-vector assertions but never logs bytes. The parent projection
vector is passed by the independent test harness without adding the projection HMAC domain to
production Agent code.

### Producer key providers

`ProducerKeyProvider` returns one private 32-byte key capability and its validated nonsecret version
for the exact environment. It has no generic fallback chain.

- `LocalProducerKeyProvider` requires the absolute
  `PALS_DSP_KEY_VERSION_REGISTRY_PATH`, local-version grammar, and a
  `PALS_DSP_PRODUCER_FINGERPRINT_KEY` value of exactly 64 lowercase hex characters decoding to 32
  bytes before any registry mutation. `SharedDspKeyVersionRegistry`
  implements the exact DEO-019 shared document, sorted entries, sibling lock, ownership/mode/
  no-symlink checks, exclusive compare-or-bind, temporary/file-fsync/replace/directory-fsync
  sequence, and collision failure. The resolved inode is exposed only to a test/activation
  attestation, never logs. Agent binds the `producer_fingerprint` purpose in the one file shared
  with Observability's `langfuse_projection` purpose.
- `AwsProducerKeyProvider` receives deployment-pinned environment-specific full secret ARN and
  immutable VersionId. It calls only
  `GetSecretValue(SecretId=full_arn,VersionId=version_id)` with no stage and validates exact response
  identity and 64-lowercase-hex/32-byte key shape. It has no name/partial-ARN/alias/stage/latest
  resolution, host registry, alternate version, local cache, or fallback secret.

`ProducerKeyProvisioner` requests exactly 32 bytes from an injected CSPRNG protocol whose production
implementation delegates to the OS. The production method accepts no key bytes; only tests inject a
deterministic CSPRNG. Rotation creates a new key/version, performs compare-or-bind before use, and
retains old bindings. Key bytes and SHA-256 binding digests remain inside the provider/registry
capability and are excluded from all exception formatting and evidence.

### Serialization and publication

`DspExportV1Serializer` validates the frozen envelope with the independent Agent grammar, writes
compact UTF-8 JSON in the frozen field order, and appends one LF. It rejects empty/BOM/trailing/
oversized output and computes SHA-256 over that one immutable byte snapshot including LF.
`DspExportArtifact` holds payload bytes and exact `<hex64>\n` sidecar bytes; it has no serializer to
history, summary, logs, or CLI outcome.

`DspExportTargetResolver` derives only the two PAE-014 basenames from the projected full invocation
fingerprint beneath the pinned directory FD. It opens existing targets no-follow. Two exact regular
single-link files owned by the effective UID with exact mode `0600` and equal to the newly derived
bytes return `already_published` without a write; one-file, unequal, malformed, wrong-owner,
wrong-mode, multi-link, symlink, or non-regular states return `publication_conflict` unchanged.

`DspExportArtifactPublisher` performs two calls to one `CreateOnlyPrivateFilePublisher` only when
both targets are absent. Each call uses a mode-`0600` same-directory exclusive temporary, complete
write, file fsync, create-only no-replace installation, and parent-directory fsync. The payload call
must return confirmed success before the sidecar call starts. A fault reports a closed publication
failure and never deletes, replaces, infers, or repairs the other file. A torn state is explicit and
requires operator selection of a different private output location; it is not automatically repaired.
Canonical history, summary, journal, gate, comparison, and evaluation-run CLI outcome are read-only
capabilities outside the publisher.

### Privacy and conformance guards

`DspExportPrivacyGuard` walks the complete typed envelope before serialization and asserts the exact
closed field/token/type registry. It separately scans payload, sidecar, exceptions, stdout/stderr,
structured logs, and durable test evidence with planted canaries for every PAE-032 prohibited
family. The producer key version is accepted only in its dedicated provider/registry-or-secret
identity, parent HMAC, and DTO root slots. Sidecar digest, raw material fingerprints, key bytes, and
key digests have no logging or arbitrary metadata API.

`AgentDspParentVectorHarness` loads the parent hand-authored corpus as immutable test data and runs
it through the independent Agent grammar. `AgentDspProducerBaseline` is generated only through
`CompletedInvocationReader -> DspExportV1Projector -> DspExportV1Serializer` from a fixture with
passed, failed, and not-evaluated cases. It pins payload and sidecar bytes and hands those bytes,
their detached digest, and case count to the parent task-11 boundary. It does not compute remote
object count or construct the parent's four-field evidence. The parent cross gate passes the same
corpus to both implementations
and hands these baseline bytes directly to the consumer; no child recopies or reserializes them.
Harness labels and documentation distinguish compatibility from canonical truth/authenticity.

### Failure and rollout effects

Reader/mapping/decimal/fingerprint/key/registry/secret/validation/privacy/serialization/publication
failure terminates the optional producer operation without a valid new pair and cannot alter
canonical or product state. Exact-existing replay is success without mutation; conflict/torn state
is fixed exit 2 and operational ambiguity is fixed exit 3. A valid DTO may later be rejected by the consumer object-limit gate;
Agent neither predicts nor changes that result. Rollout first proves child readiness, then Red/Green
evidence, parent vectors, one shared local inode or exact AWS identity, baseline/cross gate, torn-pair
matrix, and export-disable rollback. Rollback disables only DSP export and retains canonical data,
registry bindings, receipts owned downstream, and old/new HMAC ID spaces. This design introduces no
schema/data migration, vendor cost, locale, UI, or accessibility change.

## Data Model and Migration

- Evaluation objects are frozen dataclasses and JSON scalar metrics only.
- JSONL operations use a stable mode-`0600` sibling lock inode that is never replaced. Appenders,
  recovery, and migration hold it exclusively; readers hold it shared. This prevents a waiter from
  writing to a pre-migration unlinked inode and makes fence checks part of the authorization lock.
  Ordinary append/read/summary checks both fence names after acquiring the lock and returns no data
  when either exists. Recovery alone may validate/resume its matching pre-truncate fence; migration
  rejects every pre-existing fence.
- Each proof candidate is checkpointed before route selection as one immutable JSON object at
  `proof-jobs/{run_id}/attempts/{attempt:04d}.json` (or the equivalent file-store path). Checkpoint
  schema version 1 contains run/proof/problem IDs, max repair budget, and exactly one complete
  attempt record (`attempt`, `phase`, generated stage output including Lean, diagnostics,
  verification, `checkpoint_status`, and optional selected route). A file checkpoint is published
  with a mode-0600 same-directory O_EXCL temp, file fsync, create-only hard link, and parent-directory
  fsync; replacing rename is forbidden. An S3 checkpoint uses a create-only conditional write. Existing attempt
  keys are never overwritten.
- Route selection makes exactly three calls at most: the initial strict-JSON request and up to two
  corrective requests after malformed output; typed transport failures retry the same pinned
  provider/model. The first valid decision returns immediately. Exhaustion creates only the fixed
  `pals.repair_route_selection_failed` diagnostic and ordered internal selector-attempt evidence.
  The typed route decision/error carries the requirements' exact closed `selector_attempts` array;
  raw outputs remain separate internal material. It never synthesizes a route. A returned decision is attached as the inbound route on the next
  candidate, whose generation, eligible verification, and checkpoint must execute before any later
  route selection or terminal decision.
- The aggregate attempt object is the canonical per-candidate evidence shape. Checkpoint schema 1
  embeds that object unchanged. After checkpoint publication the pipeline attaches that same object
  as `attempt_evidence` to the next `repairing` callback for a routed candidate or to the terminal
  callback otherwise. Successful-selection `repairing` context also carries the outbound route and
  closed selector evidence. Prompt/raw model output remains internal under the existing privacy
  boundary.
- Terminal `result.json` remains the aggregate and records ordered attempts, `repairs_used`,
  `termination_reason`, and exact `{reason,attempt,source}` termination event. Its closed values are `verified`, `repair_budget_exhausted`,
  `non_repairable_failure`, `repair_generator_unavailable`, and
  `repair_route_selection_failed`, and `artifact_store_failure`. On process interruption, immutable checkpoints are
  recovery/audit evidence; a later recovery task may aggregate them, but this feature does not
  silently resume model calls.
- Schema version 2 remains a read-compatible legacy registry for the digest-migrated five-line
  history. New suite-run records use schema version 3. Each version has exact run/stage/metric and
  nested-evidence key sets; unsupported versions and cross-version fields fail the complete line.
- Product explanation data is stored by `pals-api`, not duplicated into agent persistence.
- `migrate_semantic_comments_v2` takes an expected full source digest and operates only under the
  stable exclusive lock. It parses raw LF-terminated JSONL, requires schema v2, deep-copies the
  objects, sets only non-null semantic metric comments to null, and validates each result through
  `EvaluationRun.from_dict`. It writes the exact source create-only to
  `<name>.pre-semantic-comments-v2.<full-digest>.backup` mode `0600`, then file/directory-fsyncs.
  The create-only mode-`0600` fence
  `<name>.migration-semantic-comments-v2-ambiguous` contains only migration/source/result
  digests, backup basename, and record/change counts and is file/directory-fsynced before a
  same-directory `O_EXCL` temporary is written. The temporary is file-fsynced and `os.replace`
  atomically swaps it into place. Parent-directory fsync and strict under-lock result digest/count
  validation precede durable fence cleanup. A proven pre-replace failure removes and directory-fsyncs
  the fence before returning a normal failure; uncertain phase, cleanup failure, or any at/post-replace
  failure retains it and returns `EvaluationHistoryMigrationAmbiguousError`. The report contains only
  the migration ID, record/comment counts, old/new digest, and backup path.
- `SemanticStageJudge` carries explicit `model_revision` in addition to provider/model. Configured
  score and unavailable sources are
  `semantic_judge:<provider>/<encoded-model>@<encoded-revision>:<rubric_revision>`; a shared helper
  validates the exact PAE-019 ASCII grammar and applies `urllib.parse.quote(value, safe="-._~")` to
  model and revision before interpolation. The all-absent configuration uses
  `semantic_judge:unconfigured:<rubric_revision>`. `EvaluatorSettings` accepts only the three exact
  PAE-019 five-variable states. This stays inside the existing schema-v2 metric
  `source` string for legacy records and the schema-v3 evaluator provenance fields for new records;
  no v2 record is rewritten by the v3 writer. `EvaluatorEndpointPolicy` parses the base URL to the
  exact normalized origin, requires proven loopback for HTTP and HTTPS otherwise, and constructs a
  no-redirect/no-proxy `HardDeadlineHttpTransport`. `EvaluatorCredential` exists only for the
  dedicated OpenAI evaluator variable, is delivered to the helper over the private pipe, and is
  attached only after exact-origin equality; it must differ by binding and bytes from generation and
  cannot be sourced from a generation client. `EvaluatorCallSeparationRecorder` proves one fresh
  post-runtime evaluator request and rejects generation/cache/batch reuse. Base URL,
  origin, addresses, and credential are never serialized. The reviewed revision token changes when
  endpoint-bound deployment/configuration changes.
- The schema-v3 case model contains exact suite/run/case identity, runtime-input SHA-256, ranked
  retrieval evidence, canonical stage records, first/final compile facts, repair/convergence,
  monotonic latency, all-or-none generation usage, estimated cost from the all-or-none pinned
  price tuple, and explicitly typed provider actual cost. Candidate ranks are contiguous from one;
  expected-hit rank is null/not-evaluated when ranked evidence is absent and null/evaluated miss
  when a complete top-k list lacks the expected draft.
- `ModelCallComparabilityValidator` runs during schema-v3 construction and strict read before any
  aggregate or authorization. It indexes the fixed eight generation roles
  `openmath|draft|sketch|prove|route|repair|explain|clarify` and the single optional
  evaluator identity, permits evaluator roles only `draft|sketch`, maps those roles only to captured
  `draft_semantic|sketch_semantic` prompt kinds, rejects every other scope/role (including evaluator
  `explain`), and requires every row provider/model to equal its exact comparability entry. Live rows
  additionally require registry revision `pals.release-role-registry.v1` and all eight exact
  `openai/gpt-5.4-mini-2026-03-17` pairs. Null
  generation-role identity and null evaluator identity each require zero matching rows. It then
  checks consecutive per-role ordinals and exact generation/evaluator row counts against evaluated
  prompt-channel counts. Mutation tests independently alter each side of every equality, including
  wrong evaluator role/prompt-kind pairing, add/remove/duplicate rows, and null/non-null identities.
  Before judge dispatch, `EvaluatorIndependenceValidator` forms the set of every non-null generation
  role whose exact row count and evaluated prompt count are positive, validates those original tokens,
  ASCII-lowercases provider/model, and rejects the evaluator normalized pair if it equals any member.
  Explanation release applies the same helper to all eight contributing registry roles and requires
  distinct evaluator-request evidence. Revisions/endpoints never distinguish an otherwise equal pair.
- The v3 history store rejects duplicate `(run_id, case_id)` while holding the stable exclusive
  history lock, appends one LF-terminated object, file-fsyncs, and directory-fsyncs. Summary files
  are projections, never history authority, and cannot authorize or repair a malformed record.

## State, Failure, and Recovery

- Proof generation: nonterminal delivery -> API claim `acquired` -> claimed pipeline -> exact
  `renewed` before each spend -> accepted terminal. Acquisition `busy` and every malformed/
  transport/visibility observation do no work and remain unacknowledged; `lease_too_short` is
  malformed on this PJR path. Exact acquisition/renewal `terminal` starts no later proof
  spend/update: failed/canceled acknowledges, while verified after PAE-020 validation ends the proof
  claim, retains the receipt, and can enter only a separately claimed explanation path. The receipt
  is acknowledged only after exact same-target explanation completed/failed. Stale/expired/
  conflicting updates abort the current worker and retain the receipt.
- Explanation: absent -> claimed generating -> completed | failed.
- Clarification: queued/pending-dispatch -> queued/sent -> claimed generating -> completed | failed;
  API `not_ready` is a no-model/no-ack observation, not an agent state transition.
- The claim target is the proof job ID for explanations and the clarification ID for clarifications;
  neither target identifier establishes ownership. Each SQS receive creates one fresh UUIDv4 claim
  token, sends that token exactly once for the target, and uses it as the sole ownership credential.
  An ambiguous claim response exits without model work;
  a later receive uses a fresh ID. Only API `acquired`, successful visibility extension, and the
  requirements' exact monotonic 30-second-margin check permit exactly one explainer workflow;
  explanation/clarification PEX may still return its separately specified short/not-ready outcomes;
  proof PJR accepts only `busy|terminal` besides `acquired`. Any malformed remaining duration or
  insufficient final margin performs none.
- Explanation/clarification model clients retain the configured 1–300 second per-attempt timeout
  ceiling and exactly three bounded parser attempts. Their PEX claim lease remains derived by the
  approved explanation formula. Proof generation instead declares the exact 3,600,000-millisecond
  PJR lease and uses the separate PAE-021 per-spend renewal contract below.
- After acquisition and before model work, the worker extends the current SQS receipt visibility to
  `ceil(required_lease_ms / 1000) + 30`. Only terminal status or a persisted completed/failed result
  deletes the receipt. Busy, short lease, not-ready, visibility, claim/config/transport, and terminal-write
  failures leave it for visibility-timeout retry and DLQ redrive. Expired claims are recovered by a
  distinct fresh later-receive UUID; reuse is never attempted and a stale terminal write is rejected.
- The proof worker injects a monotonic clock and, before every initial generation, each of up to
  three selector calls, each repair generation, each candidate/artifact API submission, and every
  authoritative verifier-result API refetch, executes renewal then
  receipt-visibility extension serially. Each control call has a 30-second hard wall and may start
  only when the prior local deadline leaves that wall plus the exact 30-second stop margin. The
  renewal duration is anchored immediately before request send. Only after exact renewal and
  visibility success may one spend call start, and only when its configured hard wall plus exactly
  30 seconds remains; equality passes. The transport gets the smaller configured/lease-derived
  deadline. Claim loss or any ambiguous control outcome cancels, kills, reaps, and joins every
  helper/descendant by `lease_deadline-30`, then permits no later spend or acknowledgement. A
  distinct API takeover therefore cannot overlap an earlier model/API spend.
- Parser/reference failures consume only the bounded real-generation retry budget, then fail.
- Proof repair defaults to twelve repair generations; startup accepts only an exact base-10 integer
  in `[1,64]`. Candidate-level safety, explicitly supplied formal-theorem identity, exact-Draft
  identity/equivalence, and Lean compiler failures are repairable, checkpointed, routed, and
  regenerated; only explicit generator/verifier/tool configuration diagnostics are non-repairable.
  Benchmark methods, hidden harnesses, evaluation rubrics, relevance labels, sentinels, and sketch
  adherence produce no runtime diagnostic. Each repairable candidate is persisted before another
  route is selected. A repeated fingerprint adds stagnation context but is not terminal;
  successful isolated verification, budget exhaustion, non-repairable configuration failure,
  route-selection failure, or checkpoint-store failure is terminal.
- Route-selector retries are separate from and do not consume the repair-generation budget. A valid
  route cannot terminate the loop: it must invoke the selected staged repair and produce the next
  candidate. The default exhaustion oracle therefore observes the initial candidate plus all twelve
  failed repair candidates; success or an explicit non-repairable diagnostic may close earlier.
- A generated-sketch/final-Lean mismatch is absent from runtime preflight, diagnostics, checkpoints,
  repair prompts, and termination evidence. If safety, explicit formal identity, and exact-Draft
  identity/equivalence pass, Lean is invoked; success can become verified regardless of the later
  post-runtime sketch metric. Those three preflight families remain compile-blocking and spoof
  resistant.
- A repeated fingerprint is diagnostic code plus a case-folded, whitespace-normalized message and
  must intersect across the latest three consecutive failed-candidate sets. The warning informs the
  next LLM route selection but does not choose or terminate a route itself.
- Semantic judge or exporter failures preserve deterministic evaluation and canonical history.
- Missing artifact evidence is `not_evaluated` unless the verified-flow oracle explicitly makes it
  required. Verified explanation absence and expected clarification absence are evaluated failures;
  no retry converts absence into success.
- A syntactically valid explanation beside unverified Lean and a successful-looking last repair
  attempt without complete terminal provenance are both missing required evidence, not passes.
- Repair evaluation distinguishes any absent mandatory key from present malformed provenance. It
  uses the exact sequence/count/route/final-equality/reason-event matrix in the requirements and
  never infers terminal reason from diagnostic prose.
- Checkpoint write failure creates the closed in-memory `artifact_store_failure` result and stops
  further model calls; a candidate is never followed by another repair unless its checkpoint was
  durably published. The aggregate is persisted once create-only. If that also fails, a typed
  infrastructure error is reported to the proof-job API and no terminal artifact/evaluation is
  claimed.
- Before final-candidate verification, exact-Draft validation runs for every harness source. A
  mismatch records a preflight failure/checkpoint and enters repair without invoking Lean.
- If checkpoint publication fails after Lean returned success, the pipeline constructs a new failed
  `VerificationResult` preserving compiler output and adding fixed
  `pals.artifact_checkpoint_failed`; it replaces final-attempt and top-level verification before
  aggregate persistence and status emission. `artifact_store_failure` can therefore never yield a
  verified `ProofRunResult`.
- Recovery writes and fsyncs deterministic prefix/suffix evidence to the recovery fence before
  `ftruncate`. Every ordinary append/read/summary checks recovery and migration fences while holding
  the stable lock. Marker failure precedes destructive mutation; post-truncate history-fsync failure
  leaves the already durable fence. A matching pre-truncate crash fence can resume; mismatch is
  operator-only.
- Ordinary history load never invokes recovery or PAE-018 migration. Migration rejects wrong
  digest, no applicable semantic comments, any unrelated invalidity, pre-existing fence, and backup
  mismatch before replace. An uncertain replace/reload/directory-fsync leaves its fence and exact
  backup for audit and blocks ordinary reads as well as writers.
- PAE-019 settings have exactly three valid states over five variables: all five absent
  (`unconfigured`), all five validated with provider `openai`, or the first four validated with
  provider `ollama` and API key absent. The unconfigured
  state makes `evaluate()` raise a closed configuration error and
  `evaluate_or_mark_unavailable()` add zero-value `not_evaluated` metrics without transport. Partial,
  malformed, or same-generation identity fails settings/factory preflight before evaluation.
- PAE-020 attestation construction exists only inside `IsolatedVerifierHttpServer` after real compile
  success and outcome-anchored cleanup. The credentialed worker has no `VerifierAttestation` builder,
  verifier transport client, client trust, or verified-callback constructor. Its API adapter submits
  only candidate/artifact values, rejects any worker-supplied attestation, then uses
  `AuthoritativeVerificationResultPort` to refetch and strictly validate the same-target persisted API
  resource before Route/Repair termination or Explain. Non-verified resources omit attestation.
- PAE-023 validates clarification resource identity before inspecting terminal state, so a malformed
  or cross-target terminal-looking response is never treated as acknowledged work. Exact Lean line
  extraction scans the original source into content spans using only CRLF, LF, CR, U+0085, U+2028,
  and U+2029 separators. It slices original bytes/code points between the first selected span start
  and last selected span end; it never uses `splitlines`, joins lines, strips, normalizes, or
  encode/decode round-trips.
- PAE-025 history rejection is line-atomic and non-mutating. Unknown fields, arbitrary metrics,
  semantic provenance outside the pinned grammar, duplicate metrics, or deterministic-status
  contradictions fail the normal load; no parser branch drops or coerces evidence.
- `evaluation-run` create-only fsyncs a mode-0600 live invocation journal before case work, appends
  and fsyncs one strict v3 record per completed case, and atomically/fsyncs the journal after each
  append. It preserves completed cases when a later case fails. Existing IDs, duplicate/foreign
  rows, provenance drift, append/journal/summary ambiguity, interruption, or operational error is
  exit 3 and cannot authorize. Exit 0 requires the exact completed-current-invocation PAE-028 gate;
  exit 1 is completed evaluated failure and exit 2 is completed missing/partial evidence.
  `evaluation-compare --baseline-run <UUIDv4> --candidate-run <UUIDv4>` requires each exact option
  once, no positional/additional option, exact suite/case/comparability digests, and complete live
  case sets; it rejects heterogeneous records and never synthesizes zero for absent values.

## PAE-017 Direct Lean Execution Transaction

The verifier treats project setup and Lean execution as one untrusted-input transaction. It does
not delegate the final launch environment to Lake or Elan.

### Startup toolchain resolution

1. In the builder, after the project token resolves and before the runtime copy, capture the
   canonical toolchain root and real regular executable `lean`/`lake` paths. Serialize exactly the
   ordered compact JSON object `{schema_version,toolchain,root,lean,lake}` plus one LF as root-owned
   mode `0444` `/app/lean-toolchain-resolution.json`; schema is
   `pals.lean-toolchain-resolution.v1`. The descriptor's canonical `root` value is authority; the
   implementation accepts only the requirements' unescaped printable-ASCII value grammar and does
   not impose an Elan-directory or other literal parent prefix.
2. Resolve Git without a shell to one canonical root-owned mode-`0755` regular executable. Implement
   exact POSIX basename search for `git` over the child environment's ordered
   `/usr/local/bin:/usr/bin:/bin` components: the first executable candidate must canonicalize to
   the descriptor path/inode and every later executable candidate must be absent or resolve to that
   same inode. Reject a shadow, distinct later executable, non-regular candidate, mutable/ambiguous
   component, or search drift. Hash the selected raw bytes, run only that absolute path with
   `--version`, validate exact exit/stdout/stderr and the closed version token, and serialize ordered compact
   `{schema_version,path,version,sha256}` plus LF as root-owned mode-`0444`
   `/app/lean-git-resolution.json`. Pinned Lake may use only the now-proven basename resolution for
   offline package-origin metadata; no unverified PATH alias, symlink, generation setting, or mutable
   package metadata selects Git.
3. Build `/app/lean-verifier-toolchain.manifest` from exactly the PAE-017 path union: both descriptors,
   the exact Git executable, and every no-follow regular file beneath `/app/lean-workspace` and
   descriptor `root`. Emit the ASCII
   header `pals.verifier-toolchain-manifest.v1` plus one LF, then one
   `<path-byte-length>:<canonical-absolute-path><TAB><file-byte-length><TAB><lowercase-sha256><LF>` record per
   path in strict raw UTF-8 path order. The descriptor has one ordinary path/length/hash record; its
   raw bytes are not concatenated separately. The output manifest is outside both walked roots,
   root-owned regular mode `0444`, and excluded from its own records. Build fails on a symlink used as
   an input, set/order/framing/length/hash mismatch, duplicate path, Git descriptor/executable/version
   mismatch, or mismatch with the exact pinned Lake/Lean hashes or any of the six
   `root/src/lean`-relative source path/hash pairs, whose Lake entries are exactly
   `lake/Lake/Build/Module.lean` and `lake/Lake/CLI/Serve.lean`.
4. Before binding the private mTLS HTTP listener and publishing readiness, open both descriptors,
   `/app/lean-verifier-toolchain.manifest`, the descriptor-selected Git executable, and
   `/app/lean-workspace` no-follow. Require exact descriptor/manifest identities/bytes, exact Git
   owner/mode/path/content and `git --version` status/stdout/stderr, and require the project root to be the canonical literal
   `/app/lean-workspace`, a read-only directory. Read `lean-toolchain` relative to that root FD and
   require exactly 28 bytes `leanprover/lean4:v4.32.0-rc1` with no LF. Reject descriptor
   unknown/missing/wrong-typed/order/encoding keys, NUL, CR, whitespace/trailing bytes, nonblank
   `PALS_LEAN_BINARY`, `PALS_LAKE_BINARY`, or `ELAN_TOOLCHAIN`, a non-exact
   `PALS_LEAN_PROJECT_DIR`, or disagreement between project and descriptor tokens.
5. Open the descriptor `root`, `lean`, `lake`, and all six pinned grammar sources no-follow, resolving
   every table path relative to descriptor `root/src/lean` and the Lake rows exactly as
   `lake/Lake/Build/Module.lean` and `lake/Lake/CLI/Serve.lean`. Require canonical absolute paths, a
   read-only immutable root directory, regular executable binaries,
   matching `lstat`/`fstat` observations, no symlink, pinned hashes, and exact manifest records. Rewalk
   both roots no-follow and reproduce the complete manifest bytes and digest before HTTP readiness
   publication. Missing, replaced, escaped, extra, duplicate, or ambiguous evidence fails startup.
6. Retain project-root, toolchain-root, Git descriptor, and Git executable FDs with canonical paths
   and startup `st_dev`/`st_ino`, both descriptor and manifest FDs, parsed immutable manifest index,
   and validated absolute `lean`/`lake`/Git paths in verifier state. At every request admission before
   request-specific preflight, and again immediately before setup and direct Lean, repeat the closed
   three-component Git candidate search, no-follow re-open each root/Git path, compare canonical path
   and `st_dev`/`st_ino` with the retained FD, `fstat` every retained FD, and rehash Git. Even a
   preflight-rejected request records root/Git attestation. Launch
   setup from the pinned project-root FD. Elan is
   absent from startup and request execution; generated code, request fields, current directory,
   mount/path replacement, and runtime environment never participate in root or toolchain selection.

### Setup-file then direct Lean

For each project-backed request, under one single-flight transaction lock:

1. Capture one monotonic untrusted-work deadline before setup from the configured server wall. Read
   exactly 16 bytes once from the OS CSPRNG and lowercase-hex encode them as `N`. Create `R` exactly
   as `/tmp/pals-lean-<N>` with exclusive no-follow semantics and mode `0700`; collision is a request
   failure and does not redraw. Create only `R/home` mode `0700`, `R/Main.lean` mode `0400`, and later
   `R/ModuleSetup.json` mode `0400`. Open and retain `R` as the request-root FD. Each regular request
   file uses no-follow `O_CREAT|O_EXCL`, is verified regular and `st_nlink == 1` immediately after
   creation and immediately before each use/unlink, and is addressed relative to that FD. Construct
   one new environment object, without reading the parent environment, as exactly:

   ```text
   PATH=/usr/local/bin:/usr/bin:/bin
   HOME=/tmp/pals-lean-<N>/home
   TMPDIR=/tmp/pals-lean-<N>
   LANG=C.UTF-8
   LC_ALL=C.UTF-8
   ```

   The same immutable object is passed as the complete `envp` to both phase launches; there is no
   copy, merge, filter, restoration, inherited key, or phase-specific addition.
2. Re-attest both pinned roots and the pinned Git descriptor/executable, then run the resolved
   absolute Lake binary directly from the pinned
   project-root FD as
   `lake setup-file R/Main.lean --no-build --no-cache`. This phase is passed through the same launcher,
   Landlock, rlimits, deadline ownership, new-session launch, and cleanup path as Lean, but has a
   separate exact 8,388,608-byte stdout-plus-stderr cap. The collector counts each byte once across
   both pipes, including the final stdout LF; equality may continue and the first byte over kills the
   phase. Pass only the transaction's remaining duration; setup completion does not reset the
   deadline. Success requires exit zero, empty stderr, and stdout with exactly the framing defined by
   the pinned grammar. The pinned x2 stdout is 4,320,763 bytes; direct Lean retains its independent
   exact 1,048,576-byte combined-output cap.
   It may read the generated header and prebuilt project/toolchain artifacts but may write only
   request scratch. Exit 2/3, any other nonzero exit, a build/cache/update/fetch/clone/write attempt,
   any successful stderr byte, multiple/trailing JSON values, unknown or duplicate-at-any-depth key,
   malformed external-file `ModuleSetup`, output overflow, or a path
   whose canonical target is outside the immutable project/toolchain roots is the fixed
   `lean.setup_file_failed` result and makes zero Lean calls.
3. `ModuleSetupWireValidator` processes the raw stdout in four fail-closed layers before any Lean
   launch:
   - framing validates UTF-8, no BOM, compact JSON with no out-of-string whitespace, exactly one
     object and one final LF;
   - an object-pairs parser rejects duplicate keys before dictionary construction and enforces the
     exact six-key top object, exact nested key sets, option scalar forms, plugin object form, and
     one/three/four artifact tuple forms from
     `pals.lake-module-setup.external.b4812ae.v1`; it never delegates shape acceptance to Lean's
     broader derived `FromJson`, which ignores unknown structure fields;
   - `SetupPathValidator` visits only `dynlibs[]`, `importArts.*[]`, and `plugins[].path`; requires each
     string to byte-equal one absolute manifest `PATH`; opens it no-follow relative to the matching
     pinned project/toolchain root FD; requires a regular strict descendant; and compares exact byte
     length and SHA-256 with that manifest record immediately before the Lean launch. Read-only inputs
     do not require link-count one and the validator does not attempt to discover filesystem-wide
     aliases: an alias path grants nothing unless that exact in-root path is independently listed and
     valid;
   - after all validation, `SetupFileWriter` writes the exact validated stdout bytes, including their
     final LF and without reserialization, to a newly created no-follow `O_CREAT|O_EXCL` mode-`0400`
     regular `st_nlink == 1` `R/ModuleSetup.json`, fsyncs it, and never interprets any value as shell
     text or an environment assignment.

   This preserves the exact pinned Lake representation that direct Lean accepts while rejecting every
   public-schema extension not emitted by pinned external-file setup.
4. Recheck both generated files' type/link count and re-attest both pinned roots and Git. Then run the
   resolved absolute Lean binary directly with only the remaining transaction duration as
   `lean --setup=R/ModuleSetup.json --threads=1 R/Main.lean`. `lake env`, `lake lean`, `/opt/elan/bin/lean`,
   shell execution, and a request-time Elan call are forbidden command shapes. Thus compile-time
   `run_tac` inherits exactly the five table entries above, receives no toolchain directory in `PATH`,
   and cannot observe `ELAN_HOME`, `ELAN_TOOLCHAIN`, `LEAN_PATH`, `LEAN_SRC_PATH`,
   `LD_LIBRARY_PATH`, verifier-parent settings, or worker secrets.
5. Delete request scratch only after the cleanup proof below. No setup file, source, process ID, or
   resolved path is persisted, logged, returned, exported, or added to public diagnostics.

### Descendant cleanup trust boundary

- The verifier enables Linux child-subreaper mode before serving and permits only one setup/Lean
  transaction at a time. Every phase starts a new process session and is registered to the current
  transaction before it can execute generated input.
- The transaction owner captures `phase_outcome_at` exactly once at the first irrevocable parent-side
  classification of each setup/direct-Lean phase: complete normal result, nonzero/signal failure,
  untrusted-work timeout, first over-cap byte, accepted cancellation, or launcher/collector exception.
  In the same control path and before cleanup work, it derives the sole cleanup deadline as
  `phase_outcome_at + 5 seconds`. Cleanup entry, signal, wait, retry, or response time never supplies
  or resets that deadline; any delay before entry has already consumed budget.
- For every outcome, including normal success, the verifier sends `SIGKILL` to the registered process
  group, then enumerates, kills, and reaps every adopted transaction descendant until both the process
  group and verifier child set are empty. Descendants that call `setsid` or otherwise leave the
  original group remain inside this proof. Setup success may proceed to root re-attestation/direct
  Lean only after its own absence proof; every other setup outcome ends the phase sequence.
- A response or next phase is authorized only after the applicable descendant-absence proof
  completes. Equality at `phase_outcome_at + 5 seconds` completes and the first later monotonic
  instant fails. Lookup, signal, wait, entry-delay, or absence-proof ambiguity sends no server
  response, closes the HTTP connection/listener, and terminates the verifier process before accepting
  another request. The API caller observes the imported transport failure; the worker receives only
  authoritative API state and never parses partial output or falls back. A setup failure maps to the
  imported `verifier_compile_failed` response only after
  that outcome-anchored cleanup proof succeeds.

### Deterministic real-Docker oracle

- `SetupEnvpProbe` is a statically linked ELF test executable, not a shell wrapper. A real-Docker test
  invokes it through the same production phase-launcher entry point used for setup. The probe reads
  its own OS-provided `envp`, compares the unordered entry set and exact bytes against the five-entry
  table and the current `R`, and fails every missing, additional, wrong-value, canary, or cross-request
  path case. On the sole passing case it writes exactly the measured 92-byte compact setup JSON plus
  LF to stdout, writes zero stderr bytes, and exits zero. This oracle proves setup-launch `envp` only;
  it is never substituted for descriptor Lake in the real setup/direct-Lean or release test.
- A separate environment fixture uses descriptor Lake followed by real direct Lean and compile-time
  `run_tac`; it verifies successfully only when Lean IO sees the same exact five entries and current
  `R`. Parent/worker canaries and every denied toolchain variable are asserted absent. This is a
  positive Lean compile oracle, not command recording or string inspection. Both executable oracles
  are required.
- The real grammar oracle runs descriptor Lake for the pinned x2 source and the exact lightweight
  `import Lean.Elab.Tactic\n` source. It compares exit, stdout/stderr lengths and SHA-256 values to the
  pinned evidence, then executes direct Lean using the exact validated bytes. Positive generated
  fixtures execute all PAE-017 `P1`–`P5` rows, including both booleans, all tuple lengths, every option
  scalar family, dynlibs/plugins, anonymous/named keys, all 720 top-key permutations, and nested-key
  reversal. Rejection fixtures independently cover every framing, key-depth, Name/option,
  artifact/plugin, manifest path/size/digest, root-replacement, request-file type/link, cap, stderr,
  and stale-import mutation; each fails before Lean.
- `PhaseCleanupMatrix` has twelve real-launcher cells: `{setup,direct_lean}` x
  `{normal,failure,timeout,overflow,cancel,exception}`. Each phase-appropriate fixture creates a normal
  `/bin/sleep` descendant and another under a distinct PGID/SID, then exposes the exact outcome trigger.
  Before accepting cleanup, the test observes both PIDs and their PGID/SID relation from the real
  verifier container; missing observation fails the cell. After cleanup it observes no matching
  process or adopted child before direct-Lean launch, response, or a second valid request. A fake-clock
  companion captures the specified outcome instant, inserts zero, partial, equality, and over-deadline
  delays before cleanup entry, and proves that only completion no later than outcome plus five seconds
  can continue/respond.
- Command recording/mutation tests reject every source/binary grammar-pin mismatch and every
  Git descriptor/path/owner/mode/content/version/output mismatch, reintroduction of `lake env lean`, an Elan shim,
  environment merge, omitted `--no-build`/`--no-cache`, invalid setup path, response-before-cleanup,
  or cleanup uncertainty. Existing production-sized Mathlib and all outer-boundary omission tests
  remain unchanged and unskipped.

## Security and Privacy

- Prompts and raw output are internal attempt material only and never part of public content.
- The explainer requests concise rationale and references, not hidden reasoning.
- Worker secret, claims, and receipt handles are write-only transport values and pass through no
  logging/error/diagnostic/artifact/metric/trace/prompt serializer. API client exceptions are mapped
  to closed local codes rather than retaining response bodies.
- Canonical local history may retain only Spec-authorized closed model/judge metadata. The optional
  DEO producer reads it through `CompletedInvocationView` and publishes only the closed pseudonymous
  DTO; Observability receives no canonical file and has no Agent schema/parser/formula import.
  Credentials, public-user data, raw identities, material fingerprints, and canonical provenance
  objects enter neither DTO nor consumer boundary.
- The worker image installs only Python/application dependencies and runs as UID/GID 65532; it has
  no Elan, Lake, Lean project, compiler cache, or direct-verifier factory path. The verifier image
  owns those assets, includes only the PAE-017 descriptor/manifest-attested Git executable for offline
  Lake package-origin metadata validation, and also
  runs as UID/GID 65532. Its single runtime-stage workspace copy assigns the complete prebuilt
  package/cache tree to UID/GID 65532 so mode-0600 cache objects are readable. The metadata must be
  internally consistent so descriptor Lake `setup-file --no-build --no-cache` and direct descriptor
  Lean require no update, clone, fetch, cache fill, or project write at runtime; `lake env` is absent.
- Verifier production startup is private TLS-1.3 mTLS HTTP-only on port 18117 and fails closed unless
  its three exact immutable SecretBinary values and deployment binding validate, `/` and the
  project are read-only, only bounded request `/tmp` is writable, effective UID is nonzero, all of
  `CapInh`, `CapPrm`, `CapEff`, `CapBnd`, and `CapAmb` are zero, `NoNewPrivs=1`, only the imported
  private service network and startup/rotation Secrets endpoint are reachable by the server, and
  cgroup v1/v2 evidence proves at most two vCPUs, 4 GiB memory, and 64 PIDs. It
  rejects nonblank environment names matching worker, cloud, database, model, token, password,
  API-key, credential, or secret categories.
- Each setup/Lean command runs in a new process session with only the exact five-entry map above:
  `PATH=/usr/local/bin:/usr/bin:/bin`, `HOME=R/home`, `TMPDIR=R`, `LANG=C.UTF-8`, and
  `LC_ALL=C.UTF-8`; direct Lean uses
  validated `--setup` and `--threads=1` with no request-time Lake/Elan environment mutation. `prlimit` applies CPU
  `ceil(wall_timeout)+1`, 16 GiB virtual address space, 16 MiB file size, 64 processes, 1024 file
  descriptors, and zero core size; setup stdout+stderr is capped at exactly 8,388,608 bytes and
  direct Lean stdout+stderr remains capped at exactly 1,048,576 bytes. The separate outer cgroup
  remains the 4 GiB resident-memory and 64-PID hard boundary, and the verifier container has the
  same 1024-descriptor soft/hard ceiling. Startup rejects a missing, unlimited, or greater
  descriptor limit. The repeated candidate-set oracle proves that any basename `git` lookup by
  pinned Lake under this exact map reaches the retained descriptor inode; a preceding shadow or
  distinct later executable is a boundary failure before launch. Every setup/direct-Lean outcome
  completes subreaper-owned descendant-tree cleanup
  against its exact outcome-plus-five-second deadline before any next phase or response; entry delay
  consumes the budget and cleanup uncertainty terminates service. Landlock grants root
  read/execute, the bounded per-compile scratch tree its handled
  access, and only read/write-file access to the already-existing `/dev/null` device required by
  Git's metadata reader; it grants no device creation, persistent root/project write, rename,
  removal, or truncation path. The runtime container additionally uses read-only root, the imported
  private mTLS service network, cap-drop all, no-new-privileges, two vCPUs, and bounded tmpfs. Every
  setup/Lean child is networkless. The server will not serve when any outer property is unverifiable.
- The production server wall deadline is exactly 300 seconds; the parent-imported API caller wall is
  310 seconds and is owned by the API. Docker security acceptance runs the exact digest-pinned
  fixture with the server deadline; the descendant-kill case starts a separate verifier with an
  explicit two-second server deadline, uses `Lean.Elab.Tactic`, and must observe both
  ordinary and escaped-session descendants before accepting timeout cleanup evidence.
- No filesystem or role is shared between worker and verifier. Only the API-owned reconciler reaches
  the private mTLS port; no worker secret, AWS credential, artifact mount, database/model credential,
  client certificate, Unix socket, plaintext route, or local compiler crosses the boundary.
- PAE-018 backups may contain legacy judge prose, so they remain mode `0600`, ignored, never
  exported/logged, and named/reported only by path and digest.
- Evaluator endpoint and dedicated credential remain transport-only. HTTP requires proven loopback;
  every other origin is HTTPS; redirects, proxies, cross-origin retries, generation-secret reuse, and
  Ollama credentials are rejected before request. Metric provenance includes only the allow-listed
  provider/model/revision/fixed-rubric tokens; unconfigured and transport/parse failures contain no
  endpoint, origin/address, credential, exception, prompt, output, theorem, Lean, or free text.
- The proof-status projection is an allow-list boundary, not a recursive cleanup heuristic. API
  diagnostic/context objects cannot contain private local artifacts even when a provider exception
  or route selector returned attacker-controlled text.
- Evaluation suite expectations and semantic rubrics never share an object with runtime generation
  input. Recorder output contains counts/provenance only; raw prompts/model output remain governed
  internal material and are not copied into canonical JSONL or summaries.

## Observability and Cost

- Internal artifacts correlate proof job/run/case/suite/model/provider. Operational telemetry uses
  only closed resource/outcome/stage labels and timers; raw IDs/content never become labels.
- Route selection records closed `selected`/`invalid_response`/`transport_error` counters and
  selector-call/repair counts. Exactly three calls at most adds one possible model call per selection
  versus the prior implementation and remains bounded by 36 calls for the default repair budget.
- Deterministic evaluation has no model cost. Semantic judging is explicit and records judge model.
- Schema-v3 usage and cost aggregates include evaluated/missing counts. Estimated cost is derived
  with `Decimal` from complete call usage and the pinned price revision; actual cost is summed only
  from explicit provider evidence. Missing local/provider billing evidence stays null rather than
  becoming a zero-cost claim.
- Langfuse is optional; local history and comparison continue when it is disabled or unreachable.
- Producer observability is limited to closed outcome/count categories. DTO values, payload/sidecar
  digest, material/exported fingerprints, key version/digest, registry/secret identity, path, and
  exception text are excluded from telemetry and logs. Producer work performs no vendor call and
  adds no remote-object/request-cost estimate.

## Testing Strategy

| Requirement | Test Level | Oracle | Fixtures / Environment | Execution Tier |
|---|---|---|---|---|
| PAE-001–PAE-006 | Unit/contract/live smoke | exact verified Lean lines, concise-section schema, selected-section detailed clarification | fake transport for errors; real Lean/model smoke | PR/manual |
| PAE-007–PAE-013 | Unit/regression | exact metric formulas, roll-ups, repair/event and summary matrices | recorded positive/negative DSP artifacts | PR |
| PAE-010 | Unit/integration/live release | bounded score schema, honest unavailable status, exact one-test/JUnit/create-only-evidence command | stub judge plus real configured generation/evaluator/verifier | PR/manual-release |
| PAE-014 | CLI/producer boundary/integration | exact option/input/target/result/exit/replay/conflict contract; post-persistence read-only behavior; canonical history/summary/journal/gate/exit unchanged; no consumer/vendor import | completed/incomplete invocation and target-state fixtures | PR after child readiness |
| PAE-015 | Unit/clock-controlled concurrent story | exact API status/lease/deadline/visibility/ack matrix, model call count, secret-free telemetry, Agent receipt stop/retain behavior without provider quiescence observation | fake clock/API/SQS + LocalStack story | PR/main/release |
| PAE-016 | Unit/execution integration/recorded artifact/live regression | ordered attempts, valid-route continuation, three-call no-fallback selector evidence, aggregate/checkpoint/status equality, exact configured budget, generation-oracle sentinel absence, Lean-valid sketch-mismatch verification | deterministic nth-repair generators and selector transports; real x^2 run | PR/manual |
| PAE-017 | Unit/Docker integration/security regression | canonical manifest/set/digest; exact Lean/Git descriptors, Git executable/version/content, project/toolchain/Git pin and per-phase re-attestation; O_EXCL/link-count mutable files; manifest path/size/digest immutable inputs; setup/direct-Lean command sequence; full positive/rejection wire grammar; setup `envp` and compile-time IO isolation; phase x outcome descendants with exact outcome anchor and delay-before-entry; process/resource termination | worker/verifier images; command/root/file/Git recorder and mutation spies; setup ELF probe; real Lake/Lean `run_tac`; positive/rejection grammar corpus; twelve-cell cleanup matrix | PR-capable Docker/main/release, no skip/substitute |
| PAE-018 | Unit/CLI/filesystem/real-data regression | strict failure before explicit migration; exact-only transform, immutable backup, stable-lock atomicity, fsync/fence fault matrix, five-record reload | synthetic fixtures plus the digest-pinned local five-line history | PR/local evidence |
| PAE-019 | Unit/settings/factory/evaluator integration | exact five-variable states, unequal credential binding/bytes, loopback-HTTP/remote-HTTPS, no redirect/proxy/origin drift, normalized rejection against every contributor, distinct post-runtime request/no reuse, pinned provenance, zero-call unconfigured metrics | env/DNS/origin/identity/call-separation matrix + recording transports | PR/release preflight |
| PAE-020 | Parent-corpus HTTP contract/worker story | verifier-server-only imported attestation after real compile/cleanup; worker client/constructor/synthesis denial; authoritative API resource | parent corpus, recording API, real verifier | parent T-016/T-017; PR/API contract |
| PAE-021 | Unit/API contract/clock-controlled two-worker story | exact acquisition/renewal unions; forbidden `lease_too_short`; terminal stop/ack split; one claim owner; per-model/API-submit/refetch renewal/visibility; exact 30-second margins; helper stop before takeover; stale/conflict stop; worker verifier-client/attestation rejection; authoritative verified Lean refetch; no direct verifier call; exact replay | two workers with different valid Lean + recording API/SQS/pipeline and killable transports | PR after API claim-contract Green and Task 28 Red/Green |
| PAE-022–PAE-023 | Unit/serialization/privacy/worker story | exact five-key diagnostics, closed status context, fixed failures, newline preservation, wrong-ID terminal no-ack | adversarial provider text and malformed/cross-target resources | PR |
| PAE-024–PAE-025 | Unit/JSONL/real-data regression | nextafter-below failure, exact threshold, strict v2/v3 keys/registries/status recomputation | malformed metric/source/status records + migrated five-line history | PR/local evidence |
| PAE-026–PAE-029 | Unit/runner/CLI/Make/manual live | exact manifests/digests and clean input, eight-role model-call/comparability/count and evaluator call-separation matrix, Git-bound provenance, ranked/semantic/compile/uplift/repair/latency/usage/cost/chain evidence, journal binding, fail-closed direct exits and GNU Make 0/2 | honest missing/failure stubs for formulas only; separately configured live services for authorization | PR/manual |
| PAE-030 | Unit/property/mapping contract | every completed exit 0/1/2 case/order/source/status/bound/half-even/rate/total/percentile/histogram branch; raw-versus-mapped double-rounding separation; inaccurate shape separated from canonical truth | strict completed passed/failed/not-evaluated invocation plus boundary mutations | PR after child readiness |
| PAE-031 | Unit/security/config integration | exact normalized Decimal material bytes and parent HMAC vectors; one 32-byte OS-CSPRNG request; malformed local key rejection; local shared inode; AWS exact ARN+VersionId; collision/fallback rejection | deterministic injected CSPRNG, private registry faults, fake Secrets Manager | PR/security/main after child readiness |
| PAE-032 | Unit/CLI/filesystem/privacy | exact payload/sidecar snapshots/names, ordered create-only commits, exact-existing replay, every conflict/torn/fault state, exact closed output/exit, recursive canaries, no authenticity claim | fault-injected private publisher and planted prohibited sentinels | PR/security after child readiness |
| PAE-033 | Spec/import/contract gate | Task 82 demotion/reopen; Task 83 historical PRX provenance; Task 84 external current DEO Task-48 report plus current PRX triple binding; Task 73 exact focused imports/draft review/promotion/ownership then sole inverse-proved marker; Task 64 distinct promoted-byte review and sole inverse-proved marker. Current DEO Task 48 and renewed Task 64 precede PRX T011; retained Red evidence, no shared runtime code, producer baseline, same parent vectors through both children | parent corpus plus real-projector baseline | before implementation, then PR/main |
| PAE-034 | Unit/PostgreSQL integration/graph/registry/live release | three-attempt OpenMath; real top-8/no-cutoff pgvector; structural+LLM 0..4 rerank; zero-context Draft; exact re-entry; fixed eight roles; real repeated Repair/Lean/artifact/Explain/Clarify; no fallback/fake success | real PostgreSQL+pgvector and production live services; fakes only for Red/Green failure paths | PR integration/manual-release |
| PAE-035 | Parent corpus/LocalStack/queue race | exact v1 receipt validation, visibility/delete ambiguity, poison retention, DLQ redrive only, fresh-claim redelivery, one receipt | parent corpus plus LocalStack | parent T-014 Red, T-015 Green; PR/main |
| PAE-036 | Parent corpus/mTLS/Docker security | exact TLS/port/routes/readiness/request/response, one-slot compiler truth, cleanup, three secret ports, API-only caller | parent corpus, real TLS certs, Docker Lean | parent T-016 Red, T-017 Green; PR/main/release |
| PAE-037 | Property/OCI/release/import/docs audit | blocked/active v1, old-worker denial participation, exact property mappings/digest label, PRX-006 Agent release-provenance inputs, commands/docs/artifacts/telemetry, no provider observation/cutover sink/API DB/Infra ownership | image metadata and parent release story | after Task 64; parent T-018/T-020/T-022/T-024–T-027 |
| PAE-038 | Parent corpus/LocalStack/API race | exact clarification routing/marker, fresh claim and visibility, terminal `dispatch_uncertain` zero-generation delete, poison/not-ready/busy/ambiguity retention | parent corpus plus LocalStack/API | PRX-009 child Red/Green; PR/main |
| PAE-017 resource oracle | Shell contract | exact two CPU, 4 GiB, 64 PID, 1024 nofile, 300-second server boundary; no obsolete one-CPU value and no Unix/network-none transport authority | read-only parent resource evidence plus Agent image inspection | PR-capable Docker |

## Toolchain and Delivery

PRX delivery is repository-local and ordered: Task 82 demotion/reopen, Task 83 historical PRX
provenance, Task 84 exact external DEO-report/current-PRX-triple binding, current DEO Task 48, then
Task 73 exact authority imports, fresh draft review,
status-only promotion, and ownership PASS; current Task 64 distinct promoted-byte/import
post-promotion readiness plus inverse-proved completion-marker publication; queue Red then Green;
worker-client-removal/API-refetch Green plus
PAE-017/PAE-034 Green; verifier Red then Green; property/old-worker/secret Red then Green; real
integration; Task 50 release evidence and operations evidence; AWS release contribution; final review.
The focused commands are exactly:

- `python -m pytest -q tests/contract/test_proof_dispatch_v1_contract.py`
- `python -m pytest -q tests/integration/test_proof_dispatch_v1_localstack.py`
- `python -m pytest -q tests/contract/test_isolated_verifier_http_v1_contract.py`
- `python -m pytest -q tests/integration/test_isolated_verifier_http_mtls.py tests/integration/test_lean_isolation_docker.py`
- `python -m pytest -q tests/story/test_proof_runtime_v1_story.py`

They precede full pytest, Ruff, and strict mypy. Agent-owned PRX-006 release-provenance inputs are the
worker image, verifier image, exact PAE-017 toolchain manifest/digest, and
`pals_agent/proof_runtime/behavior_properties.v1.json` bound by
`org.pals.agent.behavior-properties.sha256`. README contains exact heading
`Proof Runtime v1 Operations`; SECURITY contains exact heading
`Isolated Verifier mTLS Boundary`. These documents describe only Agent commands, consumer
configuration, stop/retain/resume participation, rollback/recovery, and evidence locations; they do
not instruct Agent to query provider/ECS/SQS quiescence or write a shared cutover/effect sink.

- Run `python -m pytest`, `python -m ruff check .`, and strict
  `python -m mypy pals_agent tests` in the repository environment.
- Run the existing API and frontend gates from their owning Specs.
- Run the API proof-job-runtime and proof-explanations suites plus generated OpenAPI drift checks
  before activating claim-required agent code.
- Keep live model/Lean artifacts under ignored `.pals-agent-artifacts/`; publish only reviewed,
  secret-free aggregate results in development documentation.
- The release runbook executes Agent receipt stop/retain, consumes parent-authorized Infra/API
  quiescence and persistence results, preflights the API schema/contract, deploys Agent blocked,
  participates in authorized resume, runs the queue story/smoke, and rehearses symmetric rollback.
  It defines no Agent provider observer, shared cutover/effect sink, or claimless client fallback.
- The release security gate builds both images, inspects that the worker contains no Lean/Elan/Lake
  executable/cache, starts the verifier with the exact mandatory isolation flags, verifies pinned
  Lean/Git descriptor/manifest bytes, Git executable/version/content, exhaustive input digest,
  project/toolchain/Git FDs and per-phase re-attestation, runs the setup-file/direct-Lean command trace, complete ModuleSetup grammar,
  mutable/read-only file rules, exact environment, twelve-cell outcome-anchored descendant matrix,
  and real bypass suites, proves exact mTLS readiness on port 18117, admits the API caller, and only
  then activates the exact v1 worker after the parent release gate.
- The explicit history-migration CLI is never called from startup, load, evaluate, or summary paths.
  Its successful JSON report and before/after digests are operational evidence; comment content is
  never printed. README operations guidance names the ignored real-history path, digest preflight,
  explicit command, backup/fence meanings, success proof, application rollback behavior, and the
  stop-and-inspect response to any ambiguous fence; it does not provide an automatic backup restore.
- README documents `PALS_SEMANTIC_EVALUATOR_PROVIDER`, `PALS_SEMANTIC_EVALUATOR_MODEL`,
  `PALS_SEMANTIC_EVALUATOR_REVISION`, `PALS_SEMANTIC_EVALUATOR_BASE_URL`, and provider-conditional
  `PALS_SEMANTIC_EVALUATOR_API_KEY`; their tuple/credential matrix, loopback-HTTP/remote-HTTPS,
  no-redirect exact-origin rule, no generation-secret reuse, normalized all-contributor identity
  constraint, unconfigured behavior, provenance format, and mandatory release preflight.
- README records the exact `lean-explanation-ja-v1` pytest argv, pre-absent evidence prerequisite,
  process/JUnit/evidence acceptance oracle, nonzero/skip/stale response, ignored mode-`0600` evidence
  paths, and prohibition on alternate/fake/recorded success.
- README documents the PAE-029 profiles, evidence meanings, incomplete exit code, price tuple
  (`PALS_EVALUATION_INPUT_COST_USD_PER_MILLION_TOKENS`,
  `PALS_EVALUATION_OUTPUT_COST_USD_PER_MILLION_TOKENS`,
  `PALS_EVALUATION_COST_REVISION`), and that missing usage/judge/cost never passes or becomes zero.
- Parent DEO-021 owns `agent-evaluation-smoke`, `agent-evaluation-full`, and
  `agent-evaluation-compare`; this child supplies only the CLI contracts they delegate to. Parent
  PLS-012 resource evidence is consumed only for unchanged limits and never for verifier transport;
  parent PRX/Infra own the private mTLS HTTP deployment binding. Child implementation begins only
  after those parent current-byte Specs and this child complete their readiness sequence.
- DSP export delivery documents the two producer key variables without values, OS-CSPRNG-only
  provisioning, `.local` one-shared-registry path, `.dev`/`.prod` fixed-full-ARN plus immutable
  VersionId, exact payload/sidecar bytes, non-atomic pair/torn-pair response, retry, rotation,
  export-disable rollback, privacy exclusions, and byte-integrity-only digest semantics.
- Schema-v3 DSP activation follows PAE-033: both child Specs independently converge, Agent mapping/
  key/publication tests and baseline pass, Observability's independent corpus passes, the parent
  vectors/cross gate agree byte-for-byte, and key-binding/dark-rollout/export-disable evidence is
  valid. No local LFE requirement or shared runtime validator becomes producer/consumer authority.

## Rejected Alternatives

| Alternative | Reason Rejected |
|---|---|
| Generate an explanation before Lean verifies | Can confidently explain invalid code and violates PAE-001. |
| Store canned fallback explanations | Makes tests green without generated output and violates user requirements. |
| Make Langfuse the only result store | Reduces reproducibility and makes local evaluation depend on a service. |
| Use one overall success metric | Hides which DSP state improved or regressed. |
| Persist hidden reasoning for detail answers | Unnecessary for teaching output and violates the privacy boundary. |
| Keep Lean in the worker and rely on a token denylist | Lean compile-time metaprogramming/IO has many equivalent spellings and executes with worker credentials. |
| Expose plaintext, Unix-socket, worker-direct, or dual verifier transport | Conflicts with the parent-imported private TLS-1.3 mTLS HTTP contract and would bypass API reconciliation. |
| Treat urllib socket timeout as a hard deadline | Slow headers/body bytes can repeatedly satisfy inactivity timeouts while exceeding the total lease. |
| Silently accept or rewrite invalid history during load | Hides provenance loss and makes a read mutate canonical evidence. |
| Reuse the configured generation model as the semantic judge | Creates an implicit self-evaluation loop and makes score provenance depend on unrelated generation defaults. |
| Reuse a generation API key or follow evaluator redirects | A configured base URL could exfiltrate a generation credential or move it to an unreviewed origin. |
| Rely on proof state CAS without an API generation claim | Duplicate workers can both spend model budget and the losing worker can continue with unpersisted Lean. |
| Recursively redact arbitrary public status dictionaries | New or nested provider fields can bypass a denylist; a closed projection gives an auditable wire contract. |
| Treat non-empty draft/sketch output as state accuracy | Shape evidence says nothing about semantic correctness and would overstate model quality. |
| Coerce missing token, judge, or cost evidence to zero | Turns absence into favorable evidence and can incorrectly pass a release gate. |
| Send canonical schema-v3 records directly to Observability | Duplicates canonical parsing/formulas across repositories and violates the fixed DEO DTO boundary. |
| Share a generated/runtime DEO validator between children | Correlates parser failures and violates the independent grammar requirement. |
| Treat payload and sidecar as one atomic transaction | Two independent filesystem commits cannot provide that guarantee; torn pairs must be rejected. |

## Risks

- Exact source references can become stale if Lean code changes after explanation; bind explanations
  to a proof job's immutable verified code and regenerate for a new proof version.
- LLM semantic judges can drift; pin suite revision, judge model, rubric version, and fixed numeric dimensions.
- Small benchmark suites overfit; keep inputs separate from expected outputs and grow reviewed cases.
- A separately named evaluator can still be the same model as one generation role; pin and review
  provider/model/revision, apply exact ASCII-lower identity comparison to every contributing role,
  and interpret semantic scores only as optional enrichment.
- A long proof claim can delay recovery after worker loss; keep the API lease finite, renew only on
  accepted progress, expose closed claim outcomes, and drain active leases during rollback.
- Provider token and actual-cost metadata vary; adapters accept only explicit typed evidence and
  leave unsupported families not-evaluated, so initial live summaries may be incomplete by design.
- Producer key misbinding can create incomparable identity spaces; compare-or-bind the exact local
  tuple or AWS ARN+VersionId before publication, retain old versions, and reject every fallback.
- A crash between payload and sidecar commits leaves a torn pair; publish payload first, require the
  exact detached digest at consumption, and never infer or overstate pair atomicity.

## Open Questions

None.
