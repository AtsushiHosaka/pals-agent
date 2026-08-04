# Tasks: Proof Explanation and DSP Evaluation

`tasks.md` is non-normative. It cannot add behavior absent from requirements. Bundle authority
follows requirements frontmatter, and no implementation or test edit is authorized before checked
Task 64.

Completed tasks 1–7 describe the initial revision only. They do not claim the current security,
fail-closed, independent-evaluator, or repair-continuation restoration, which is owned by ordered
tasks 15–18, 20, 22, and 23. The current proof-fencing, integrity, runtime-oracle, and evidence-suite
revision is owned by ordered tasks 28–37 and supersedes task 27 as the final gate. Pending tasks 11–13
retain broader pre-existing provenance/claim rollout work; their overlapping checkpoint, history-lock,
and HTTP-deadline scope is superseded by tasks 16–18 and is not a dependency of this P0/P1 batch.
Tasks 8 and 14 are superseded by task 19; task 19 and task 21 are superseded by the current-revision
final review in task 23. The DEO-v1 Agent producer implementation is owned by tasks 39–46.

Historical task 38/53/64 states authorize nothing for current bytes. Task 72 demoted the bundle for
parent-authority relocation; completed tasks 74, 80, 81, 82, and historical 83 are followed by current
Task 84 and reopened current tasks 73 and 64. Tasks
75/77/78/76 are a non-authorizing SDD-024 restoration/review side branch whose backbone is
`Task 75 -> Task 77 -> Task 78 -> Task 76`, with an additional direct
`Task 75 -> Task 78` dependency edge.
Current task 64 blocks every still-pending implementation/test task in this file, including tasks
50–52. Historical state cannot satisfy the sole current sequence
`Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64 -> PRX T011`. The
producer tasks supersede task 35 and
the DEO-producer clause of task 37; they do not supersede task 37's unrelated PAE/PJR/PEX gate work.
No pending implementation/test edit is authorized until Task 82 has demoted requirements, Task 84
has synchronized the current DEO/PRX imports, and
reopened the stale completion markers, current DEO Task 48 is complete, and task 73 records exact approved authority
imports, an all-zero technical `IMPLEMENTATION READY` but non-authoritative draft review, explicit
status-only promotion, ownership PASS, and its inverse-proved single-token completion marker.
Current task 64 then records a distinct fresh
promoted-byte/import `IMPLEMENTATION READY`, CRITICAL=0, HIGH=0, no-material-question verdict while
unchecked, followed only by its inverse-proved single-token completion-marker publication.

The PAE-017 direct-execution/environment/cleanup restoration is owned by tasks 47–49 and supersedes
only those portions of task 26; task 26 retains production resource viability. Task 26 is blocked by
current task 64 and is the shared prerequisite for task 47. Task 49 waits for task 48. Parent DEO-021 Make and
PLS-012 resource-oracle implementation belong only to their parent tasks; this file retains read-only
integration references, not parent edit ownership. Tasks 51–52 own PAE-034 runtime Red/Green work.
Task 50 is the sole cost-bearing `lean-explanation-ja-v1` release gate and waits for tasks 37, 49, 52,
57, and 60.

Historical PRX T-010 Agent alignment is recorded by tasks 53–64. Its HTTP-verifier/API-refetch/attestation/
receipt clauses supersede every Unix transport, direct worker verifier, worker-attestation, network-
none service, and shared-socket clause in earlier pending tasks; the compiler/toolchain/environment/
resource/cleanup clauses remain inputs to tasks 56–57. Tasks 24, 36, and 38 are never-executed
superseded history. Task 28 owns worker verifier-client removal, worker-attestation rejection, and
authoritative API refetch Red/Green; tasks 56–57 own server attestation. Task 53 and prior Task 64
states authorize nothing for current bytes; tasks 75/76 own report-only restoration/review, Task 82
owns the current DEO-final-identity demotion/reopen, Task 83 is historical PRX provenance, and Task
84 binds the external current DEO Task-48 report identity and current PRX triple before Task 73 owns
the current authority import, draft review, status-only promotion, and ownership. Completed tasks
77/78 own byte synchronization/residual cleanup and current Task 64 owns the distinct
post-promotion review. No PRX
implementation or test task may begin before current task 64 completes. This authoring update
completes neither task 73/current task 64 nor any implementation task.

## Implementation Plan

- [x] 1. Implement strict Lean-grounded explanation and clarification generation.
  - Covers: PAE-001–PAE-006
  - Repository: `pals-agent`
  - Verification: explanation unit tests plus a real verified Lean/model smoke artifact

- [x] 2. Integrate typed explanation and clarification work into the worker.
  - Covers: PAE-015
  - Repository: `pals-agent`
  - Verification: worker unit and queue/API story tests for success, duplicate, and failure

- [x] 3. Implement immutable state-level evaluation and append-only history.
  - Covers: PAE-007–PAE-013
  - Repository: `pals-agent`
  - Verification: evaluator, concurrent store, artifact regression, and summary tests

- [x] 4. Add optional semantic evaluation without weakening deterministic truth.
  - Covers: PAE-008, PAE-010, PAE-013
  - Repository: `pals-agent`
  - Verification: bounded score, malformed response, transport failure, and unavailable tests

- [x] 5. Define the generic export boundary and implement vendor-specific integration in its owning
  observability repository.
  - Covers: PAE-014
  - Repositories: `pals-agent`, `pals-observability`
  - Verification: mapping/idempotency/failure tests plus optional local Langfuse smoke

- [x] 6. Complete cross-repository API and learner UX integration.
  - Covers: PAE-002, PAE-004, PAE-006, PAE-015
  - Repositories: `pals-api`, `pals-webfront`
  - Verification: owning Specs' full unit, contract, story, accessibility, and build gates

- [x] 7. Record a versioned baseline and comparison report.
  - Covers: PAE-007–PAE-014
  - Repository: `pals-agent`
  - Verification: persisted JSONL run plus stage pass-rate and metric-average output

- [ ] 8. Superseded by task 14: run independent architecture, bug, privacy, and test-quality reviews.
  - Covers: all requirements
  - Repositories: all affected
  - Verification: no unresolved P0/P1 findings and explicit residual-risk report

- [x] 9. Lock the proof repair state to repeated diagnose/route/regenerate/verify cycles.
  - Covers: PAE-009, PAE-016
  - Repository: `pals-agent`
  - Verification: deterministic success on repairs 5 and 12; custom and default-budget exhaustion;
    exact `[1,64]` configuration acceptance/rejection before model/verifier work;
    all 13 ordered candidate/phase/diagnostic/verification/route fields; empty-candidate repair;
    generator-unavailable and route-selection terminal diagnostics; exact three-consecutive
    stagnation fingerprint semantics; `repairs_used`/`termination_reason`; checkpoint-before-route,
    create-only hard-link/file+directory-fsync fault matrix, immutable duplicate rejection,
    simulated interruption recovery evidence; and a recorded real
    x^2 run

- [x] 85. Enforce an ε–δ proof method explicitly requested by the learner.
  - Covers: PAE-013, PAE-016
  - Repository: `pals-agent`
  - Verification: a shortcut `continuous_id.pow` candidate is rejected before verifier invocation;
    the Lean-verified `PalsX2Verified.lean` artifact passes; comment-only ε/δ markers do not bypass
    the gate.

- [x] 86. Require ε–δ for an exact retrieved x²-continuity method.
  - Covers: PAE-013, PAE-016; `SPEC-CHG-2026-07-31-PAE-EXACT-X2-EPSILON-DELTA`
  - Repository: `pals-agent`
  - Verification: the raw learner input `x² が連続であることを説明してください。` reaches an
    exact `continuous_square` retrieval, a short `continuous_id.pow` candidate is rejected before
    verifier invocation, the explicit ε–δ Lean artifact passes, and approximate/reranked contexts
    remain method-advisory.

- [x] 10. Historical intermediate revision: preserve Lean compiler visibility while still treating
  sketch divergence as failure. This completed record is superseded by task 34 and does not
  authorize a sketch/scaffold runtime diagnostic or proof veto.
  - Covers: PAE-016
  - Repository: `pals-agent`
  - Verification: a safe candidate with both scaffold and compiler failures invokes Lean once,
    records one compile-phase checkpoint containing both diagnostic classes, and passes both to the
    next LLM-selected repair route; a Lean-compiling scaffold mismatch still fails; safety,
    formal-harness, and exact-draft-method preflight fixtures still invoke Lean zero times; rerun the
    real x^2 case and archive its ordered attempts

- [ ] 11. Restore fail-closed evaluation provenance gates.
  - Covers: PAE-001, PAE-007–PAE-012, PAE-016
  - Repository: `pals-agent`
  - Verification: table-driven fixtures cover every extraction formula and roll-up; explanation
    gate cases separately cover verification absent/null/false/wrong/true, missing Lean, exact
    references/coverage, verified missing explanation, clarification expectation absent/wrong/
    false/true, omitted/empty/invalid/overlapping sequences, Japanese/code-point/non-repetition
    parser bounds, and fixed semantic-rubric dimension/threshold averaging;
    repair cases cover every
    mandatory key absent versus null/wrong type, attempt numbering/routes, preceding success,
    checkpoint status, top-level code/verification mismatch, counts/bounds, all reason/event/source/final/budget
    combinations including checkpoint and aggregate-store failure, error reduction, and fully
    consistent pass/fail artifacts. Retrieval/draft/sketch/prove/end-to-end fixtures independently
    cover parent/key absent, null, wrong type, blank, false, valid, and numeric out-of-range cases.
    Summary denominator/boolean exclusion and exact unique-case/suite/empty-intersection comparison
    rules pass. Shared-lock concurrent reader/writer snapshots, torn-tail detection, quarantine recovery, pre-truncation fault injection, and
    post-truncation ambiguous fsync pass. Captured-prompt sentinels prove suite strategy, rubric, and
    `expect_clarification` are absent from every draft/sketch/prove/repair/explain/clarify prompt.
    Candidate-level safety, explicitly supplied formal-theorem identity, and exact-Draft
    identity/equivalence failures each checkpoint and continue to nth-repair success or exact budget
    exhaustion while invoking Lean zero times for those candidates. Separate prompt captures cover
    initial generation, every selector retry, every routed repair, and post-runtime evaluator scope;
    benchmark methods/harnesses/rubrics/relevance/sentinels are absent from generation and required
    only in the applicable one-way evaluator prompt.

- [ ] 12. Gate worker model calls with persisted API claims and a hard deadline.
  - Covers: PAE-015
  - Repository: `pals-agent`; API contract is separately authorized by PEX-009/012/017–019 in
    `pals-api/specs/proof-explanations`
  - Verification: explanation/clarification fake-clock tests cover different/same claim, fresh-ID
    takeover and no reuse, `not_ready`, ambiguous response, stale terminal write, exact
    lease/visibility formulas, acquired-response monotonic lease deadline, visibility-call elapsed
    time, pre-request lease anchoring with delayed commit/response, exact 30-second final-margin pass/fail boundary, 1/90/300-second timeout bounds,
    per-attempt remaining-time caps, before/after transport/parser deadline crossings, discarded late output, fixed failed write,
    every delete/retain outcome, and
    exactly zero/one explainer workflow invocation. Worker-secret/claim/receipt sentinels are absent
    from all payload/prompt/artifact/diagnostic/exception/error/log/metric/trace/history surfaces.

- [ ] 13. Implement claim-contract rollout and operations evidence.
  - Covers: PAE-011–PAE-015; external API PEX-018–PEX-019
  - Repository: `pals-agent`
  - Verification: runbook and tests cover configuration preflight, Agent receipt stop/retain/drain,
    consumption of parent-authorized Infra/API quiescence and persistence results without provider/
    ECS/SQS polling or a shared cutover sink, API schema/contract-first activation, no legacy fallback,
    pending-dispatch expiry, DLQ retain/redrive, closed telemetry labels/timers, and abort conditions.

- [ ] 14. Superseded by task 19: run current-revision gates and independent implementation reviews.
  - Covers: PAE-001–PAE-016
  - Repository: `pals-agent`
  - Verification: exact pytest/Ruff/strict-mypy commands, API/LocalStack queue story, real Lean plus
    configured-model explanation/clarification smoke, mandatory configured `lean-explanation-ja-v1`
    semantic gate with reviewed positive/negative fixtures, canonical evaluation comparison, no unresolved
    P0/P1 review findings, and explicit generated Lean/model artifacts are recorded.

- [ ] 15. **Never executed; superseded by tasks 26, 47–49, and 56–57.** The historical broad Unix-
  verifier task is non-executable. Tasks 26 and 47–49 retain its compiler/toolchain/resource/isolation
  scope; tasks 56–57 replace its transport with the sole private TLS-1.3 mTLS HTTP server. No worker
  verifier client, Unix/plaintext route, or compatibility transport may be implemented from this task.

- [ ] 16. Restore pipeline and evaluation-history fail-closed transitions with TDD.
  - Covers: PAE-011, PAE-012, PAE-016
  - Repository: `pals-agent`
  - Red verification before implementation: compile-success/checkpoint-failure returns verified;
    benchmark exact-Draft mismatch invokes Lean; append can pass a stale pre-lock fence check; and
    injected ambiguity-marker creation failure follows `ftruncate` without a durable fence.
  - Implementation: coerce checkpoint publication failure to fixed failed verification before
    aggregate/state emission; run exact-Draft preflight for every harness source; use the stable
    sibling lock for all history operations; create/validate the recovery fence before truncation
    and check fences under lock.
  - Green verification: exact result/attempt/event provenance, zero verifier call on exact-Draft
    mismatch, blocked racing append, resumable matching pre-truncate fence, and full marker/fsync
    fault matrix.

- [ ] 17. Restore worker authorization, hard HTTP deadlines, safe paths, and clarification proof
  gating with TDD.
  - Covers: PAE-004, PAE-015
  - Repository: `pals-agent`
  - Red verification before implementation: malformed/mismatched acquired and terminal resources
    authorize a model or delete; slow-drip OpenAI/Ollama/PALS responses exceed their timeout;
    clarification traversal IDs alter the URL; and direct/worker unverified clarification reaches
    the model.
  - Implementation: exact resource-aware claim parser; killable shared hard-deadline transport;
    strict ID grammar plus one-segment encoding; fresh proof/input identity and verified-state
    cross-check; mandatory strict `verified` clarification argument.
  - Green verification: complete envelope mutation matrix, slow-header/body process termination,
    exact 1,048,576-byte/oversized-body boundary, no live helper, recording-server path oracle, and
    zero model/claim/write/ack on failed proof gate.

- [ ] 18. Add and execute the explicit schema-v2 semantic-comment history migration.
  - Covers: PAE-011, PAE-018
  - Repository: `pals-agent`
  - Authorized real source: ignored
    `.pals-agent-artifacts/evaluations/history.jsonl`, five lines, source SHA-256
    `b32d19c0a6f66b5140c37d161d83bf291a1fa969a82b5e59d5bcdc07c43879fa` fails strict load at
    line 5 while preserving the exact bytes.
  - Red verification before implementation: the equivalent five-line regression and an extant
    migration fence fail strict load without changing/returning history bytes.
  - Implementation: add only `evaluation-history-migrate --migration semantic-comments-v2
    --expected-sha256 ...`; require stable exclusive lock, exact digest/schema/defect shape,
    byte-exact mode-0600 digest backup, durable migration fence, validated temp, atomic replace,
    directory fsync, strict reload, and content-free audit JSON. Document the exact explicit
    operation, evidence, fence response, immutable-backup purpose, and no-automatic-restore rollback
    behavior in README.
  - Green verification: synthetic wrong-digest/non-applicable/unrelated-invalid/backup-mismatch and
    every temp/fsync/replace/concurrent-append fault fail closed; migrate the authorized real five
    lines, prove exactly four semantic comments became null and every other JSON value is equal,
    verify backup digest/bytes, capture the old/new digest audit report, and run `evaluation-history`
    successfully on five records.

- [ ] 19. Superseded by task 21: run the final current-revision gates and fresh independent
  implementation/security review.
  - Covers: PAE-001–PAE-018
  - Repository: `pals-agent`
  - Verification: focused Red evidence retained in test names/results; full `python -m pytest`
    including available integration and Docker security tiers; `python -m ruff check .`; strict
    `python -m mypy pals_agent tests`; worker-image toolchain inspection; real migrated-history CLI
    read; no unresolved P0/P1 findings; exact files/results and residual risks reported.

- [ ] 20. Separate and pin semantic evaluator identity/configuration with TDD.
  - Covers: PAE-010, PAE-019
  - Repository: `pals-agent`
  - Red verification before implementation: generation-only OpenAI/Ollama settings can build the same
    provider/model as judge; non-loopback HTTP, redirects, generation-key reuse, and cross-origin
    forwarding are not closed; only one active generation identity is compared; absent evaluator
    settings cannot produce explicit zero-call unavailable provenance; configured metric sources omit
    model revision; and no exact live release evidence writer/entrypoint exists.
  - Implementation: parse the exact three permitted states of the ordered five evaluator variables;
    require the OpenAI evaluator key binding/bytes to differ from generation; implement exact loopback-
    HTTP/remote-HTTPS, no-redirect/no-proxy normalized-origin policy; bind the private OpenAI Bearer
    credential only to that origin; reject it for Ollama/unconfigured mode; add distinct post-runtime
    request evidence with no generation-response/cache/batch reuse; and add the exact ASCII-
    lower independence validator over every contributing generation role/content. Add model revision
    to configured sources, a transport-free unconfigured judge path, and the strict create-only
    `LeanExplanationReleaseEvidenceWriter` used by the exact live test entrypoint. Document every env,
    security boundary, command, result, evidence field/path, and release preflight in README.
  - Green verification: provider/credential/endpoint/DNS/origin/redirect matrix; partial/invalid/
    all-contributor normalized same-model matrix; planted generation-key sentinels; configured request
    model/endpoint; exact configured/unconfigured source strings; deterministic-result equality;
    zero-call absence; strict evidence schema/O_EXCL/mode/fsync/privacy faults; and fake/stale/skip/
    false-rubric rejection all pass without executing the cost-bearing live command.

- [ ] 21. Superseded by task 23: run the final current-revision gates and fresh independent implementation/security and
  evaluation-integrity review.
  - Covers: PAE-001–PAE-019
  - Repository: `pals-agent`
  - Verification: focused Red evidence retained in test names/results; full `python -m pytest`
    including available integration and Docker security tiers; `python -m ruff check .`; strict
    `python -m mypy pals_agent tests`; worker-image toolchain inspection; real migrated-history CLI
    read; independent-evaluator provenance/configuration evidence; no unresolved P0/P1 findings;
  exact files/results and residual risks reported.

- [ ] 22. Restore real repair continuation and bounded route-selector evidence with TDD.
  - Covers: PAE-016
  - Repository: `pals-agent`
  - Red verification before implementation: an execution-level compile failure can be observed to
    stop without proving the selected route reached another candidate; malformed selector JSON has
    only two total calls; status evidence is not compared with aggregate/checkpoint candidate fields.
  - Implementation: use exactly three real selector calls with corrective strict-JSON prompts and
    no fallback route; return immediately on a valid decision; attach it to the generated next
    candidate; add exact closed `selector_attempts`; carry the canonical aggregate/checkpoint
    attempt object as post-checkpoint status `attempt_evidence`.
  - Green verification: malformed/malformed/valid reaches candidate 2 with exactly three selector
    calls; three malformed/transport failures terminate with ordered fixed evidence and zero repair;
    valid route selection never terminates; real execution reaches success, explicit non-repairable,
    or all twelve repairs; every candidate's aggregate/checkpoint/status evidence compares exactly;
    configured real-model/manual-release evidence has no route-success premature stop.

- [ ] 23. Superseded by task 25: run the final current-revision gates and fresh independent implementation/security,
  repair-continuation, and evaluation-integrity review.
  - Covers: PAE-001–PAE-019
  - Repository: `pals-agent`
  - Verification: tasks 15–18, 20, and 22 Red/Green evidence; full `python -m pytest` including
    available integration and Docker security tiers; `python -m ruff check .`; strict
    `python -m mypy pals_agent tests`; worker-image toolchain inspection; real migrated-history CLI
    read; independent evaluator identity; real multi-attempt route/repair evidence; no unresolved
    P0/P1 findings; exact files/results and residual risks reported.

- [ ] 24. **Never executed; superseded by tasks 28 and 56–57.** The historical worker-attestation-
  builder plan is non-executable. Task 28 owns worker builder/client removal, worker-supplied
  attestation rejection, and authoritative API refetch Red/Green; tasks 56–57 own verifier-server-only
  imported attestation production after real compile/cleanup. No worker attestation DTO/builder,
  signer, cache, fixture, verified callback, or transport payload may be added from this task.

- [ ] 25. Superseded by task 27: run the final current-revision gates and fresh independent implementation/security,
  repair-continuation, evaluation-integrity, and API-contract review.
  - Covers: PAE-001–PAE-020
  - Repository: `pals-agent`
  - Verification: tasks 15–18, 20, 22, and 24 Red/Green evidence; full `python -m pytest`
    including available integration and Docker security tiers; `python -m ruff check .`; strict
    `python -m mypy pals_agent tests`; exact verified-attestation recording payload and no-call
    mutation matrix; worker-image toolchain inspection; real migrated-history CLI read; independent
    evaluator identity; real multi-attempt route/repair evidence; no unresolved P0/P1 findings;
    exact files/results and residual risks reported.

- [ ] 26. **Resource-viability prerequisite; depends on current task 64.** Restore the unchanged outer and
  child resource boundary with TDD before task 32 or task 47.
  - Covers: PAE-017 bounded Lean runtime viability restoration.
  - Repository: `pals-agent`.
  - Red verification before implementation: a valid Mathlib compile aborts under the 2 GiB virtual
    address cap with `failed to create thread`; after raising only that diagnostic cap, the historical
    environment-mediated project launcher lacks Git metadata tooling and attempts a forbidden
    read-only project refresh. Once Git and UID-owned cache reads are present, Landlock denies Git's
    `/dev/null` open and the project launcher again
    misclassifies the local package URL, rejecting exact fixture SHA
    `572596a39973c1c0deeee7a7b9b92acfd5c840219399e3cd0bb9ee12f68a7d68`. After that fix, the
    descriptor-only diagnosis is disproved: with `nofile=1024`, no Landlock, and the production
    8 GiB address-space limit, the exact fixture still fails immediately at `Ultra.olean.private`,
    while an unlimited comparison reaches the wall timeout without that read error. Runtime
    evidence shows nine open descriptors and `VmPeak=10,780,620 kB` for UID/GID 65532. With the
    corrected 16 GiB cap, the immediate read failure disappears but the current 90-second server
    and 95-second client deadlines terminate the valid one-CPU cold compile with exit 137.
  - Implementation: change only the shared resource/cache boundary: use a strict outer
    two-vCPU/4-GiB resident-memory/64-PID cgroup; set child virtual-address and process rlimits to
    16 GiB and 64, reserve one Lean file-processing thread, and include Git solely for
    offline package-origin validation against the prebuilt read-only Lake cache. Copy that complete
    cache as UID/GID 65532 and grant the child only existing `/dev/null` read/write-file access in
    addition to bounded scratch. Set outer verifier and child soft/hard descriptor ceilings to the
    bounded value 1024 and make startup reject missing/unlimited/greater values; retain every
    persistent write and compiler-child network restriction. Set the production verifier server hard
    wall to 300 seconds and consume the parent-imported API reconciler 310-second private mTLS HTTP
    client bound only as integration evidence, while retaining an explicit short test-local server
    timeout setting. This task adds no API client, child command wrapper, environment-selected
    toolchain, or proof of direct-launch isolation; task 47–48 exclusively own setup/direct-Lean
    command shape, exact-fixture compile, and descendant cleanup.
  - Green verification: exact resource defaults/settings/boundary-threshold contracts; UID/GID-owned
    cache and offline-Git provenance; `/dev/null`-only device grant; 16-GiB/64-process/1024-nofile/
    one-thread child settings; exact two-vCPU/4-GiB/64-PID outer evidence; 300-second Agent server and
    imported 310-second API client production bounds plus explicit short-test server parsing;
    32-GiB-allocation and 80-child failures; every resource
    startup omission remains rejected. Do not count an environment-mediated compile or a historical
    Unix/network-none Compose script as Green: task 48 owns the exact descriptor setup/direct-Lean
    fixture, while tasks 56–57 and parent PRX own the private mTLS HTTP deployment integration.

- [ ] 27. Superseded by task 33: run the final current-revision gates and fresh independent implementation/security,
  repair-continuation, evaluation-integrity, API-contract, and test-oracle review.
  - Covers: PAE-001–PAE-020, including the PAE-017 runtime viability restoration.
  - Repository: `pals-agent`.
  - Verification: tasks 15–18, 20, 22, 24, and 26 Red/Green evidence; full `python -m pytest`
    including available integration and Docker security tiers; `python -m ruff check .`; strict
    `python -m mypy pals_agent tests`; exact verified-attestation recording/no-call matrix;
    worker-image toolchain inspection; real migrated-history CLI read and digest evidence;
    independent evaluator identity; real multi-attempt route/repair evidence; no unresolved P0/P1
    findings; exact files/results, manual/live gaps, and residual risks reported.

- [ ] 28. **WORKER CLIENT REMOVAL/API REFETCH RED-GREEN; depends on current task 64 and completed current API
  claim-contract Green PJR T-053 plus API PEX T-065.** Fence proof generation at the API boundary and
  remove worker verification authority with TDD.
  - Covers: PAE-020–PAE-021; cross-repository authority PRX-003 and API PJR-012–PJR-014.
  - Repository: `pals-agent` only. The receiving API claim/resource contract must already be Green in
    `pals-api` PJR T-053 and API PEX T-065 after exact approved/post-reviewed PJR T-061, PWA Task 3,
    and API PEX T-073. Historical PJR T-020/PEX T-033 are superseded evidence and cannot satisfy this
    dependency. Parent PRX supersedes the former PJR-015 Agent provider/quiescence/cutover dependency.
    An API Spec verdict, Red evidence, historical Green, or partial route implementation cannot
    satisfy the predecessor.
  - Red verification before implementation: two workers receiving the same nonterminal proof job
    both enter generation and can produce different valid Lean; the losing terminal write is not a
    conflict fence; local losing Lean can reach explanation; or the worker can instantiate/call a
    verifier client, construct/supply an attestation, or trust candidate-local verification. Add API-
    client contract tests for every exact claim/update/refetch envelope and a real Agent/API
    serialization story. Red must fail on the current worker client/builder/refetch gap, not fixture setup.
  - Implementation: create a fresh UUIDv4 claim for each delivery, acquire before pipeline entry,
    declare the exact 3,600,000-millisecond lease, and carry the claim on every status update. Before
    every initial generation, each selector attempt, each repair generation, each candidate/artifact
    API submission, and every authoritative verifier-result API refetch, perform exact API renewal
    then receipt-visibility extension under separate 30-second hard walls.
    Start spend only with its configured hard wall plus the exact 30-second margin remaining; pass
    the smaller lease deadline to a killable transport and cancel/kill/reap/join everything by
    `lease_deadline-30`. Parse acquisition only as `acquired|busy|terminal` and renewal only as
    `renewed|terminal`; any `lease_too_short` is malformed. Exact terminal starts no later proof
    spend or update, acknowledges failed/canceled, and after PAE-020-valid verified retains the
    receipt through a distinct explanation claim until exact terminal completed/failed.
    Raise a closed stop exception on stale/expired/conflicting/malformed or ambiguous renewal/
    visibility responses. Remove every worker verifier-client constructor/import/call, client trust,
    compiler path, attestation builder, and verified-callback synthesis path. Submit only candidate/
    artifact values; reject any worker-supplied attestation; refetch and validate authoritative
    persisted state, Lean, artifact, and server-produced attestation before Route/Repair termination
    or separately claimed explanation. No claimless/direct-verifier compatibility path or model
    fallback is permitted.
  - Green verification: only one duplicate worker calls the pipeline; different valid losing Lean is
    rejected and never explained; exact replay is idempotent; source/import/constructor spies prove
    zero worker verifier client/transport/trust/compiler/attestation builder; worker-supplied
    attestation and local verified status are rejected; persisted API compile failure drives only the
    fixed Route/Repair diagnostic and exact persisted verified refetch alone opens Explain;
    acquisition/renewal terminal and
    forbidden-status matrices prove exact stop/ack behavior; stale/expired/conflict/visibility/
    malformed matrices make zero later route/model/API-submit/refetch/explanation calls and retain the receipt. A
    clock-controlled expiry/takeover story proves renewal before every spend and no prior helper or
    descendant remains live when a distinct claim acquires.

- [ ] 29. **Depends on current task 64 and completed current API claim-contract Green PJR T-053 plus API PEX
  T-065 after exact approved/post-reviewed PJR T-061, PWA Task 3, and API PEX T-073.** Close
  Agent proof-status and diagnostic privacy projection with TDD.
  - Covers: PAE-022; API PJR-014.
  - Repository: `pals-agent` only; API parser/contract tests are read-only prerequisite evidence.
  - Red verification before implementation: route diagnostics serialize `metadata` into the API's
    extra-forbid object and trigger 422/retry; provider prompts, outputs, error bodies, rationale, or
    exception text can enter public diagnostic/context fields.
  - Implementation: serialize exactly five diagnostic keys and an extra-forbid
    `pals.proof-status-context.v1` projection; map model/provider/route/transport/configuration
    failures to the fixed public code/message pairs while retaining private raw evidence only in
    already-authorized local artifacts.
  - Green verification: real agent/API payloads parse once without 422; mutation/property tests
    reject every additional/nested key; secret/prompt/output/error sentinels are absent from wire,
    public persistence, public responses, logs, metrics, and canonical evaluation history.

- [ ] 30. **Depends on current task 64.** Restore clarification-byte, threshold, and history-reader integrity
  with TDD.
  - Covers: PAE-023–PAE-025.
  - Repository: `pals-agent`.
  - Red verification before implementation: trailing-newline Lean is stripped; malformed or
    cross-target terminal clarification is acknowledged before identity/schema validation;
    `nextafter(.80, 0)` passes; unknown run/stage/metric fields, arbitrary metric names/sources, or
    forged persisted stage status load successfully.
  - Implementation: validate the complete clarification resource and exact ID before terminal
    handling; preserve theorem/Lean bytes; use one separator-preserving CRLF/LF/CR/U+0085/U+2028/
    U+2029 span algorithm shared with the PEX-024 known-answer contract; use direct finite `>=`; and
    dispatch strict v2/v3 history parsing through closed field/metric/provenance registries with
    deterministic status recomputation.
  - Green verification: newline clarification reaches proof cross-check/model unchanged; wrong-ID,
    malformed, additional-field, and cross-target terminal cases make no request/model/write/ack;
    exact `.80` passes while nextafter-below fails; malformed histories fail line-atomically without
    mutation and the migrated real five-line v2 history still reloads.

- [ ] 31. **Depends on current task 64.** Add the versioned evidence-complete evaluation suite and runner with
  TDD.
  - Covers: PAE-026–PAE-029.
  - Repositories: `pals-agent`; parent Make delegation is task 32.
  - Red verification before implementation: state accuracy can pass from non-empty output; no
    packaged exact three-prompt suite or per-case ranked retrieval/semantic/compile/repair/latency/
    usage/cost evidence exists; missing judge/token/cost can pass or be reported as zero.
  - Implementation: add the exact immutable `pals.dsp-evaluation@smoke-v1` manifest, three case and
    rubric digests, independently reviewed relevant Draft IDs/top-k, distinct draft/sketch rubric
    dimensions/formula/threshold, schema-v3 case/comparability/journal models, exact
    `pals.evaluation-summary.v1` root plus rate/scalar/transition/histogram unions, scoped prompt
    and call evidence, strict append-only duplicate rejection, nearest-rank aggregates, and
    deterministic atomic+fsync JSON/Markdown. `evaluation-run --profile smoke|full` create-only
    reserves a live invocation, appends every current case once, and authorizes only after strict
    re-read; compare requires exact suite/case/generation/evaluator/rubric/price/budget/agent/
    toolchain provenance. The compare CLI accepts exactly one UUIDv4 `--baseline-run` and one UUIDv4
    `--candidate-run`, no positional/additional option, and strict-reads without canonical mutation.
    Runtime receives only fresh `{id,prompt}`; expectations stay evaluation-only.
  - Green verification: exact three original prompts/order and known digests; sentinels absent from
    every initial/selector/repair generation prompt and present only in post-runtime evaluator scope;
    ranked expected hit/top-k, distinct semantic rubrics, post-runtime sketch adherence, paired
    first/final compile and uplift, repair distribution/convergence, nearest-rank p50/p95, complete
    generation/evaluator/overall usage, estimated/actual cost, explanation-chain digests, and missing
    counts serialize exactly. Missing evidence is null/not-evaluated and exits 2; evaluated failure
    exits 1; operational/incomplete/stale/duplicate/provenance/interruption cases exit 3 (signals
    130/143). Only a completed current `origin=live` invocation with all manifest cases can exit 0;
    synthetic formula fixtures and fake model/compiler success cannot authorize.
  - Cross-field provenance oracle: independently mutate every `model_calls` scope, generation/
    evaluator role (including forbidden evaluator `explain` and wrong
    `draft|sketch` to `draft_semantic|sketch_semantic` pairing), provider, model, ordinal,
    add/remove/duplicate cardinality, comparability role pair/evaluator nullability, and
    prompt-channel count. For every non-null role with positive contributing rows, apply the exact
    ASCII-lower evaluator inequality; include two-contributor, case-only-difference, null/zero-call,
    same-model-different-revision, and same-model-different-endpoint cases. Require exact identity,
    normalized inequality, and both scope/role counts before record acceptance, summary, comparison,
    authorization, or export. Mutate the Git descriptor/executable/version contribution to
    `verifier_toolchain_sha256` and require comparability drift/rejection rather than reuse.

- [ ] 32. **Child Make integration verification; depends on current task 64 and completed parent DEO Task 36;
  may run in parallel with tasks 26/47.** Consume parent-owned Make evidence without editing parent
  files. Its former Unix/network-none PAE-017 Compose scope is superseded by the parent PRX private
  mTLS deployment contract and tasks 56–57; it cannot be used as current verifier transport evidence.
  - Covers: PAE-029.
  - Repository: `pals-agent` verification/evidence only; no parent `Makefile` or `pals-scripts` edit.
  - Verification: invoke the completed parent DEO-021 recording Make contract against current child
    CLI names. Require exact single
    delegation, child success -> GNU Make 0, every child nonzero/signal/precondition failure -> GNU
    Make 2 without changing direct child CLI 0/1/2/3 and no canonical mutation. Parent test failure
    blocks child integration evidence; it is not repaired here. Current verifier deployment/resource
    evidence is consumed only through tasks 26, 49, and 56–57 under parent PRX.

- [ ] 33. Superseded by task 37: run all affected gates and fresh Spec/code/test/security reviews.
  - Covers: PAE-001–PAE-029, PJR-001–PJR-021, and PEX-001–PEX-027.
  - Repositories: `pals-agent`, `pals-api`, and the explicitly authorized parent tests/targets.
  - Verification: preserve Red evidence per tasks 28–32; run complete agent/API pytest including
    available integration tiers, root Compose contract without an image build, Ruff, strict mypy,
    migration/OpenAPI generation and drift checks, real migrated-history CLI reload, and fresh
    independent Spec/code/test audits. Report exact commands/counts/skips/files and any remaining
    P0/P1 or manual/live/Docker risk. Do not claim the main-owned verifier rebuild/Unix fixture as
    this task's evidence.

- [ ] 34. **Depends on current task 64.** Remove generation-oracle leakage and make sketch adherence
  evaluation-only with TDD.
  - Covers: PAE-009, PAE-013, PAE-016, PAE-025, PAE-027–PAE-028.
  - Repository: `pals-agent`.
  - Red verification before implementation: benchmark methods/hidden harness/rubric/relevance or
    sentinel values appear in initial, selector, or repair prompts; a generated-sketch text mismatch
    blocks Lean or creates repair/terminal failure despite a successful isolated compile.
  - Implementation: remove benchmark/method/sketch oracle checks from runtime diagnostics and
    generation prompts while retaining safety, explicitly supplied formal identity, exact-Draft
    identity/equivalence, and isolated verification. Compute the exact structural-subsequence
    sketch-adherence metric only after terminal runtime and never feed it back.
  - Green verification: sentinel matrix covers initial generation, all selector retries, and every
    routed repair; evaluator-only values appear only in one-way post-runtime evaluator prompts. A
    semantically equivalent/rephrased sketch whose exact theorem passes preflight and isolated Lean
    verifies is `verified` while `sketch_adherence=false`; compiler failure remains failed. The real
    x2 artifact is asserted only as old preflight blocking with `elapsed_ms=0`, never as compile
    evidence.

- [ ] 35. Superseded by tasks 38–45. The prior case/summary-fixture plan does not satisfy the final
  parent one-envelope producer contract and shall not be implemented as DEO evidence.
  - Historical covers: PAE-001–PAE-029 and the then-current parent DEO range.
  - Replacement: tasks 38–45 produce the exact completed-invocation envelope, key binding,
    payload/sidecar pair, producer baseline, parent vectors, and cross-gate contribution.

- [ ] 36. **Never executed; superseded by tasks 58–59 and parent PRX.** The historical PJR-015 Agent
  provider/ECS/SQS quiescence observer and durable `pals.proof-generation-cutover.v1` sink are non-
  executable. Tasks 58–59 own only Agent blocked/stop/retain/resume participation, old-worker fail-
  closed behavior, and Agent image/toolchain/property evidence. Infra owns provider/quiescence
  observation and durable release effects; API owns persistence. No implementation or test may be
  derived from this task's old observer/sink clauses.

- [ ] 37. **Depends on current task 64 and tasks 20, 28–32, and 34.** Run all non-DEO current-revision gates and fresh
  Spec/code/test/security reviews. Its
  former DEO-producer scope is superseded by tasks 38–46.
  - Covers: PAE-001–PAE-034, API PJR-012–PJR-014, and PEX-001–PEX-027. Parent PRX release
    integration is completed separately by tasks 54–63.
  - Repository: `pals-agent` evidence only. Invoke completed API/parent gates read-only; do not edit
    their files from this child task.
  - Verification: preserve Red evidence for tasks 28–32 and 34; run complete agent/API pytest
    including available integrations, evaluator endpoint/credential/all-contributor identity and
    release-evidence contract tests, paired takeover/refetch stories, applicable parent resource evidence,
    an image build, Ruff, strict mypy, migration/OpenAPI generation and drift, real migrated-history
    CLI reload and fresh independent Spec/code/test/security audits. Record exact commands/counts/
    skips/files and remaining P0/P1/manual/live risk. The cost-bearing exact live release command is
    task 50 and is not inferred from these deterministic tests. DEO producer evidence is recorded
    only by task 46 after tasks 38–45.

## DEO-v1 Agent Producer: Readiness, Red, then Green

- [ ] 38. **Never executed; historical and superseded by current tasks 73/64.** This duplicate
  whole-child gate is non-executable. Historical task states authorize nothing for current bytes.
  Task 73 now owns current exact-import alignment, the all-zero non-authoritative
  draft review, status-only promotion, and ownership PASS; current Task 64 separately owns the
  distinct all-zero promoted-byte post-review.

- [ ] 39. **RED; depends on current task 64.** Add failing independent grammar and canonical mapping tests
  before any projector/mapping implementation.
  - Covers: PAE-014, PAE-030, PAE-033; DEO-002–DEO-006, DEO-013, DEO-016.
  - Repository: `pals-agent` tests only in the Red commit/evidence step.
  - Red oracle: one strict completed invocation with passed, failed, and not-evaluated cases must
    require one exact ten-key envelope, every journal case in `expected_case_ids` order, contiguous
    ordinals, unique fingerprints, matching summary order, seven statuses, and 26 ordered metrics.
  - Mutation matrix: missing/extra/duplicate/foreign/mixed/reordered/pass-only cases; invalid
    journal/summary/comparability; every source status/type/null/bound; JSON boolean-versus-integer;
    half-even below/above/tie-to-even quality and USD cases; stage counts, seven boolean rates, two
    quality means, all totals/bounds, nearest-rank p50/p95, every histogram edge, aggregate statuses,
    and a shape-valid intentionally inaccurate DTO.
  - Independence oracle: imports/code generation/shared package spies fail if a parent or
    Observability runtime parser, validator, model, schema, or formula path is used.
  - Completion evidence: tests fail for the intended absent independent DTO/projector behavior,
    not because of fixture setup, import errors unrelated to the behavior, or an already-green stub.

- [ ] 40. **GREEN; depends on task 39's verified Red and completed parent tasks 5 and 6.** Implement the independent completed-
  invocation reader, closed Agent DTO grammar, case mapper, Decimal integer oracle, and summary
  mapper; make task 39 pass without weakening its assertions.
  - Covers: PAE-014, PAE-030, PAE-033.
  - Repository: `pals-agent`.
  - Implementation: add `CompletedInvocationView`, `DspExportV1Projector`, closed frozen DTO types,
    the immutable 26-entry source registry, Decimal-token `ROUND_HALF_EVEN` mapper, exact-rational
    rate/mean helper, nearest-rank percentile helper, and parent-equation validation. Read only
    strict persisted schema-v3/journal/summary data; add no schema-v2 conversion, case selection,
    consumer parser, object-limit filtering, vendor code, or canonical mutation.
  - Green verification: all task-39 tests pass; existing PAE-001–PAE-029/schema-v2/schema-v3 suites
    remain byte/behavior compatible; the independent Agent grammar accepts the parent's shape-valid
    1000-case vector without filtering, while the projector emits every case of each currently
    completed canonical invocation for PAE-029 exit 0, 1, or 2 and never changes membership for a
    downstream object limit.

- [ ] 41. **RED; depends on current task 64 and completed parent tasks 5 and 6; may run in parallel with task 39.** Add failing canonical-
  material, producer-HMAC, provisioning, and environment key-binding tests before implementation.
  - Covers: PAE-031, PAE-033; DEO-008, DEO-014, DEO-019, DEO-020.
  - Repository: `pals-agent` tests only in the Red commit/evidence step.
  - Material/HMAC oracle: pin all five exact material objects, exponent-free arbitrary-precision
    Decimal canonical JSON and u32 frames; prove `0.1`, `0.10`, and `1e-1` converge without binary
    float and without changing persisted history bytes;
    mutate each identity/order/case-record/comparability field; reproduce the parent case and
    comparability framed-message SHA-256/full-HMAC vectors; consume the projection vector only in
    the test harness; reject normalization, empty part, wrong prefix/order/algorithm/encoding, and
    duplicate case output.
  - Provisioning/registry oracle: one injected OS-CSPRNG request for exactly 32 bytes; normal
    caller-supplied bytes rejected; exact lowercase encoding; missing/uppercase/nonhex/short/long/
    wrong-decoded-length `PALS_DSP_PRODUCER_FINGERPRINT_KEY` rejected before registry access;
    `.local` one absolute shared path and
    inode, both purposes, strict registry grammar/order/modes/no-symlink/lock/fsync/collision matrix.
  - AWS oracle: exact `.dev`/`.prod` full producer ARN and immutable VersionId request/response,
    omitted stage, exact 64-hex/32-byte secret; reject names, partial ARNs, aliases, stages, latest/
    probes, response mismatch, host registry, alternate/local fallback, malformed secret, and every
    key/digest log/evidence leak.
  - Completion evidence: tests fail specifically because the producer material/key implementation
    is absent or violates the exact contract.

- [ ] 42. **GREEN; depends on tasks 40 and 41's verified Red.** Implement material fingerprints,
  exact parent-framed producer HMAC, OS-CSPRNG provisioner, local shared registry, and exact-version
  AWS producer key provider; make task 41 pass.
  - Covers: PAE-031, PAE-033.
  - Repository: `pals-agent`.
  - Implementation: add the five-kind private material builder, identity/comparability HMAC
    methods, no-truncation full outputs, `ProducerKeyProvider`, OS-CSPRNG-only provisioner,
    DEO-019 local registry compare-or-bind, and `.dev`/`.prod` exact ARN+VersionId adapter. Keep raw
    material fingerprints, keys, and key digests inside private capabilities and exception/log
    deny-lists.
  - Green verification: task-41 vectors and all fault matrices pass; rotating to a new key/version
    creates a separate output space, old bindings remain, and same-version/different-key fails
    before projector publication.

- [ ] 43. **RED; depends on current task 64 and may run in parallel with tasks 39 and 41.** Add failing
  explicit-CLI, exact-byte create-only publication/replay/conflict, torn-pair, privacy, and
  no-authenticity-overclaim tests before application-service/publisher implementation.
  - Covers: PAE-014, PAE-032, PAE-033; DEO-003, DEO-012, DEO-016, DEO-020.
  - Repository: `pals-agent` tests only in the Red commit/evidence step.
  - Byte oracle: compact ordered UTF-8 JSON, no BOM/whitespace/trailing byte, one final LF,
    nonempty/64-MiB boundaries, digest over exact payload including LF, exact 65-byte sidecar, and
    mode `0600` files.
  - CLI oracle: exact command/options once, UUIDv4, absolute component-by-component no-follow
    effective-UID-owned mode-`0700` pinned directory, no override,
    deterministic invocation-fingerprint names, exact published/already-published stdout, empty
    success stderr, fixed six error codes, exit 0/2/3, and no private value in output/logs. Mutate
    every row of the ordered failure table, including overlapping faults at adjacent phase boundaries,
    and require the exact first-applicable code/exit with no exception-text classification.
  - Publication oracle: payload and sidecar each use exclusive same-directory temporary, complete
    write, file fsync, create-only no-replace install, directory fsync; sidecar cannot begin before
    confirmed payload commit. Exact existing bytes perform zero writes and replay; partial/different/
    malformed/wrong-owner/wrong-mode/multi-link/symlink/nonregular targets conflict unchanged.
    Exact replay requires effective-UID ownership, mode `0600`, and link count one. Inject every write/fsync/no-replace
    fault and torn state; assert no pair atomicity, digest inference, repair, deletion, or canonical mutation.
  - Privacy/authenticity oracle: recursive sentinels cover every prohibited content/identity/key/
    path/exception family across DTO, sidecar, stdout/stderr/logs/errors/evidence/documentation;
    exact producer-version slots only; assertions reject wording that digest, DTO shape, HMAC,
    baseline, cross-gate, or downstream acceptance proves Agent origin or mathematical truth.
  - Completion evidence: tests fail for the absent exact serializer/publisher/privacy behavior.

- [ ] 44. **GREEN; depends on tasks 40, 42, and 43's verified Red.** Implement exact serialization,
  explicit export operation, privacy validation, ordered create-only publication, replay/conflict,
  and closed failure handling; make task 43 pass.
  - Covers: PAE-014, PAE-032, PAE-033.
  - Repository: `pals-agent`.
  - Implementation: add `AgentDspExportCommand`, exact CLI adapter/result mapper,
    `DspExportV1Serializer`, recursive closed `DspExportPrivacyGuard`, deterministic target resolver,
    immutable payload/sidecar snapshots, `CreateOnlyPrivateFilePublisher`, and payload-first
    `DspExportArtifactPublisher`. Add no automatic torn-pair repair/deletion, DTO self-digest,
    consumer call, vendor SDK, schema-v2 fallback, or canonical-state write.
  - Green verification: exact CLI/bytes and all target/filesystem/privacy faults pass; exact replay
    performs no write and conflict remains unchanged; schema-v3/history/summary/gate/evaluation-exit
    bytes remain unchanged for success and every failure.

- [ ] 45. **Verification; depends on tasks 40, 42, 44, and completed parent tasks 5 and 6.** Generate the real-projector producer
  baseline, consume the full parent vector corpus independently, and provide Agent evidence to the
  parent cross-repository gate.
  - Covers: PAE-030–PAE-033; DEO-002–DEO-008, DEO-012–DEO-016, DEO-019–DEO-020.
  - Repository: `pals-agent`; the parent gate and Observability consumer remain owned by their Specs.
  - Baseline: use only `CompletedInvocationReader -> DspExportV1Projector -> serializer/publisher`
    on a strict completed invocation with passed, failed, and not-evaluated cases; pin exact payload
    and sidecar bytes, detached digest, and case count. Hand those inputs to the parent task-11
    boundary; do not compute `planned_remote_object_count` or construct the parent's four-field evidence.
  - Parent vectors: run every positive/negative/status/union/boundary/integer/histogram/privacy and
    all three HMAC vectors through the independent Agent harness. Do not copy vectors into runtime
    validation code or implement projection behavior.
  - Cross-gate dependency: baseline generation and Agent parent-vector execution may complete after
    tasks 40/42/44; the shared cross-gate substep additionally waits for the independently ready
    Observability child and every parent task prerequisite for that gate.
  - Cross gate: prove both implementations consume the same parent corpus and the consumer receives
    the Agent baseline bytes and detached digest byte-for-byte, with matching contract revision.
    Fixture/cross-gate success is compatibility only; mapping tests remain the truth/origin oracle.

- [ ] 46. **Final producer gate; depends on current task 64, tasks 39–45, and the independently ready Observability
  child for the shared cross gate.** Run Agent producer quality/security/operations gates and a
  fresh code/test review without claiming a new Spec convergence verdict.
  - Covers: PAE-014, PAE-030–PAE-033; DEO-001–DEO-020 producer obligations.
  - Repository: `pals-agent`, with parent shared-gate evidence referenced rather than re-owned.
  - Verification: preserve task-39/41/43 Red evidence; run full Agent pytest, Ruff, strict mypy,
    import/code-generation audit, parent vectors, baseline regeneration, `.local` shared-inode and
    `.dev`/`.prod` fake-Secrets-Manager matrices, recursive privacy scan, torn-pair faults, and
    unchanged schema-v2/schema-v3/explanation/clarification regressions. Record exact commands,
    counts, skips, files, and residual risks.
  - Operations/documentation: document key/version names without values, OS-CSPRNG provisioning,
    local shared registry, exact AWS ARN+VersionId policy, payload/sidecar bytes and torn-pair
    response, retry/rotation, dark rollout, audited manual compromise cleanup, and export-disable
    rollback. Rehearse rollback without requiring optional live Langfuse and preserve canonical
    data, registry history, receipts, and old/new ID spaces.

## PAE-017 Direct Lean Isolation Restoration

- [ ] 47. **RED; depends on current task 64 and task 26's verified resource Green; may run in parallel with
  task 32.** Add Spec-derived failing command, environment, setup, and
  deterministic real-Docker cleanup tests before production changes.
  - Covers: PAE-017 and every PAE-017 acceptance criterion added by the
    `Direct Lean Environment Isolation Restoration` update.
  - Repository: `pals-agent` tests only in the retained Red evidence step.
  - Unit/contract Red oracle: record the exact startup-resolved realpaths and request command order;
    require exact five-key Lean and four-key Git mode-`0444` descriptor bytes and exact
    `pals.verifier-toolchain-manifest.v1` fixed-header/length-prefixed records at their fixed paths.
    Prove the exhaustive two-descriptor + exact Git executable + all no-follow project/toolchain
    regular-file set, raw UTF-8 path order, one path/length/hash record per descriptor/executable with
    no raw-byte concatenation, exact lowercase
    digest, pinned Lake/Lean hashes, and all six exact descriptor-`root/src/lean`-relative source
    path/hash pairs, with Lake rows exactly `lake/Lake/Build/Module.lean` and
    `lake/Lake/CLI/Serve.lean`, plus PAE-027 equality. Fail every manifest set/order/
    framing/length/hash/path/EOF mutation and every descriptor key/order/encoding/4,096-byte/mode/
    owner/type/token/path/inode/symlink mutation, every Git descriptor key/order/schema/path/version/
    hash framing case, Git owner/mode/type/content/version stdout/stderr/exit/path/inode mutation,
    exact `/usr/local/bin:/usr/bin:/bin` basename-search mutations including rejection of a
    preceding same-inode alias or other shadow, acceptance of a later executable candidate only
    when it resolves to the retained inode, rejection of a distinct later executable and every
    non-regular/inaccessible/ambiguous candidate, and candidate replacement between
    startup/admission/phases,
    nonblank `PALS_LEAN_BINARY`, `PALS_LAKE_BINARY`, or
    `ELAN_TOOLCHAIN`, and any startup/request Elan call. Pin `/app/lean-workspace` and the descriptor
    root and Git executable with no-follow FDs, canonical paths, `st_dev`, and `st_ino`; at every
    request admission and before both phases mutate each path/mount/device/inode/content/version
    independently and require zero child calls.
    Include a preflight-rejected request to prove admission attestation still occurs. The descriptor
    root must pass without any literal parent-prefix assertion. Fail the current `lake env lean`
    shape; require Lake
    `setup-file R/Main.lean --no-build --no-cache` followed by direct Lean
    `--setup=R/ModuleSetup.json --threads=1 R/Main.lean`. Mutation cases cover malformed
    toolchain files, inherited selector, shim/symlink/root mismatch, missing executable, nonzero
    setup exit, signal exit, any exit-zero stderr byte, stale import, BOM/whitespace/multiple/trailing/
    malformed/unknown/duplicate-at-any-depth setup JSON, excluded public `package`/`imports`/plugin
    forms, each wrong scalar/container/artifact tuple length, and every escaped path-bearing field,
    omitted no-build/no-cache, setup output overflow, build/write attempt, and any Lean call after a
    setup failure.
    Pin the x2 stdout at exactly 4,320,763 bytes and its exact SHA-256, empty stderr and its SHA-256,
    and the lightweight setup stdout at exactly 92 bytes and its exact SHA-256. Test exact one-LF
    framing, the shared stdout-plus-stderr 8,388,608-byte equality/one-byte-over boundary, and direct
    Lean's separate exact 1,048,576-byte combined-output limit.
  - `ModuleSetup` grammar Red oracle: the positive matrix accepts both `isModule` booleans;
    one/three/four artifact tuples; empty/nonempty string, false/true, zero/one/multi-digit positive Nat
    options; dynlibs; exact `{path}` plugins; anonymous/named keys; all 720 top-key permutations; and
    forward/reverse nested-key order. The rejection matrix independently mutates every framing,
    key-depth, name/option, artifact/plugin, and path/file row in requirements. Every rejection makes
    zero Lean calls and never substitutes the broader public decoder.
  - File-boundary Red oracle: create `R/Main.lean` and `R/ModuleSetup.json` only no-follow with
    `O_CREAT|O_EXCL`; mutate collision, type, containment, replacement, and `st_nlink != 1` at creation,
    validation, and final use. For read-only setup inputs, require exact manifest path/size/digest under
    a pinned root; accept an unchanged listed path without trying to discover an outside hard-link
    alias, and reject every unlisted alias path, size/digest change, symlink, or root replacement.
  - Setup environment Red oracle: compile a statically linked ELF `SetupEnvpProbe` and invoke it in
    real Docker only through the production setup-phase launcher. Its own `envp` must be exactly
    `{PATH=/usr/local/bin:/usr/bin:/bin, HOME=/tmp/pals-lean-<N>/home,
    TMPDIR=/tmp/pals-lean-<N>, LANG=C.UTF-8, LC_ALL=C.UTF-8}` for the current 32-lowercase-hex `N`;
    it emits only the pinned 92-byte setup stdout. Mutate each missing/additional/wrong key/value,
    parent/worker canary, malformed `N`, and prior/parallel-request path. The probe cannot count as the
    real Lake/direct-Lean or release oracle.
  - Lean environment Red oracle: separately run descriptor Lake and real direct Lean; compile-time
    `run_tac` must inspect its actual environment and verify only with that same exact map. It rejects
    every extra key, `ELAN_HOME`, `ELAN_TOOLCHAIN`, `LEAN_PATH`, `LEAN_SRC_PATH`,
    `LD_LIBRARY_PATH`, canary, or cross-request path. The current implementation must fail because
    Lake re-injects toolchain variables. Both executable environment Red oracles are required.
  - Cleanup Red oracle: execute all twelve `{setup,direct_lean}` x
    `{normal,failure,timeout,overflow,cancel,exception}` cells through the production phase launcher.
    Every cell spawns and pre-observes one normal sleeper and one distinct-PGID/SID sleeper, captures
    the exact specified `phase_outcome_at`, and requires no descendant/adopted child before next
    phase, response, or second request. Missing pre-observation fails the cell. Signal/wait/enumeration
    ambiguity and response-before-cleanup mutations fail closed. A fake-clock companion proves one
    pre-setup untrusted-work deadline, setup-elapsed subtraction before Lean, no phase reset, and for
    every cell `cleanup_deadline = phase_outcome_at + 5 seconds`. Inject delay after outcome but before
    cleanup entry: equality may pass; entry or completion one instant over sends no response and stops
    the verifier under both production 300/310 and test-only two/eight-second pairs.
  - Completion evidence: run the real Docker suite and retain the current 14-pass/two-failure
    baseline plus focused failures for the intended absent direct-launch/setup/environment/cleanup
    behavior. No skip,
    retry-until-green, Mathlib timeout substitute, local-only path, string-only security oracle, or
    fake verifier success is permitted.

- [ ] 48. **GREEN; depends on task 47's verified Red.** Implement startup-pinned setup-file/direct
  Lean execution and complete descendant cleanup without weakening PAE-017.
  - Covers: PAE-017.
  - Repository: `pals-agent` production code and verifier image only after Red evidence.
  - Implementation: strict immutable toolchain resolver; absolute real Lake/Lean paths; closed
    build-time five-key Lean and four-key Git resolution descriptors; exhaustive canonical manifest
    generator/parser/index; descriptor/Git executable single path/length/hash coverage; pinned Git
    version output, executable/source and all-root-file digests; startup no-follow descriptor/
    manifest/project/toolchain/Git FD pinning and per-phase root/Git canonical-path/device/inode/
    content re-attestation; exact repeated POSIX basename search proving pinned Lake's only `git`
    lookup resolves to the retained descriptor inode, with no shadow or alternate executable;
    `ModuleSetupWireValidator`, duplicate-preserving closed shape validator, `SetupPathValidator`, and
    exact-byte `O_CREAT|O_EXCL` mode-`0400` link-count-one `SetupFileWriter`; manifest path/size/digest
    validation for every read-only setup input; exact `R`/`R/home`/source/setup paths and literal
    five-variable environment; bounded
    setup-file then direct-Lean transaction; single-flight subreaper ownership; process-group plus
    adopted descendant kill/reap; exact per-phase outcome capture and outcome-plus-five-second cleanup
    deadline whose pre-entry delay closes the HTTP connection and terminates the verifier on
    ambiguity; fixed `lean.setup_file_failed` after proven cleanup and no-response termination
    observed by the API caller only as the imported transport failure. Remove the
    request-time `lake env lean` and six-variable `ELAN_HOME` child contract rather than retaining a
    compatibility branch.
  - Green verification: make every task-47 oracle pass, then rerun the exact production-sized valid
    fixture, the separate setup ELF and direct-Lean `run_tac` envp matrices, all startup omission
    tests, secret/write/callback/32-GiB/80-child/output probes, and
    worker no-toolchain/no-local-fallback tests. Report the exact generated Lean fixtures used by
    the security tests as test fixtures, never as model-generated proof success.

- [ ] 49. **PAE-017 Green/final compiler security gate; depends on tasks 26 and 48.** Run all PAE-017 and repository gates and a
  fresh independent implementation/test/security review.
  - Covers: PAE-017; preserves PAE-016 verifier ordering and PAE-020 attestation provenance.
  - Repository: `pals-agent`; private mTLS HTTP deployment integration remains tasks 56–57 and parent
    PRX/Infra ownership.
  - Verification: task 26 resource evidence; full unskipped real-Docker
    isolation suite; exact manifest/Lean-and-Git-descriptor/Git-version-content/basename-resolution/
    root/file/command/environment/positive-and-rejection
    setup matrices; complete phase/outcome escaped-session cleanup and delay-before-entry matrix;
    pinned source/binary/Git grammar provenance; exact x2 and 92-byte setup stdout/stderr/digest oracles;
    production 300/310-second digest-pinned fixture; full Agent
    pytest; Ruff; strict mypy; image inspection; root Compose contract; no unresolved P0/P1/P2
    finding. Record exact counts, elapsed time, files, Docker availability, and residual risks.
  - Rollout/rollback evidence: rebuild the verifier image, abort activation on any failed real-Docker
    criterion and rehearse rollback only to a compatible verifier image that has no `lake env lean`
    child path. Worker activation waits for tasks 28, 57, and 60; Task 49 does not start or authorize
    receipt. No Unix/plaintext/local/toolchain-environment fallback is authorized.
  - Documentation: update the verifier runbook/README with the build descriptor, direct setup/Lean
    sequence, exact Git descriptor/version/content attestation, caps/deadlines/environment, removal of
    `PALS_LEAN_BINARY`/`PALS_LAKE_BINARY`,
    fixed content-free failure meanings, real-Docker command, activation abort, and compatible-image
    rollback. Do not print descriptor contents beyond its fixed schema/path, resolved toolchain
    values, setup JSON, generated Lean, process IDs, or environment values.

- [ ] 50. **Exact live `lean-explanation-ja-v1` release contribution; depends on tasks 37, 49, 52,
  57, and 60.** Execute only after the PAE-017 compiler Green, PAE-034 runtime Green, private mTLS
  verifier Green, worker-client-removal/API-refetch Green consumed by Task 57/60, and real integration:
  exactly, from the `pals-agent` repository root and with complete real generation/verifier plus
  PAE-019 evaluator configuration:

  ```text
  python -m pytest -q tests/live/test_lean_explanation_release.py::test_lean_explanation_ja_v1 --junitxml=.pals-agent-artifacts/lean-explanation-ja-v1.junit.xml
  ```

  - Covers: PAE-001–PAE-006, PAE-010, PAE-013, PAE-016–PAE-017, PAE-019, PAE-024,
    PAE-027, and PAE-034.
  - Repository: `pals-agent` live release evidence only; no parent/API/Observability edit.
  - Precondition: `.pals-agent-artifacts/lean-explanation-ja-v1.evidence.json` is absent; the exact
    code-owned registry, actual OpenAI credential/endpoint, actual PostgreSQL/pgvector catalog with at
    least eight eligible rows, isolated verifier, and artifact store are configured; and no fake,
    recorded, synthetic, template, cached, patched, or skipped path is configured. Do not remove or overwrite an
    old evidence file as part of this command; archive handling is an explicit operator action outside
    the gate.
  - Result oracle: require process exit 0 and strict JUnit counters exactly one collected test,
    failures=0, errors=0, skipped=0, with no xfail/xpass. Every other process/JUnit result fails.
  - Evidence oracle: strict-read the newly create-only effective-user-owned mode-`0600`, file/directory-
    fsynced evidence object and require its exact closed schema, current timestamps, exact eight-role
    `openai/gpt-5.4-mini-2026-03-17` calls, OpenMath attempts, actual pgvector fetch 8 and context 0..4, at least
    two complete failed-verification Route/Repair cycles, later successful PAE-017 verification,
    durable artifact, explanation/required clarification/reference booleans, contributor identities,
    evaluator provenance/normalized inequality/distinct request, all four direct-threshold dimensions/
    mean/pass, and exact Lean/artifact/explanation/clarification/toolchain digests. Reject stale/malformed/
    unevaluated/false evidence or any forbidden endpoint/origin/address/credential/content/error field.
  - Record only exact command, exit, JUnit counters, evidence path/digest, closed provider/model/
    revision identifiers, rubric scores/pass, and content/toolchain digests. No prompt, response,
    theorem, Lean, explanation, clarification, endpoint, origin, credential, or exception text enters
    the release record.

- [ ] 51. **PAE-034 RED; depends on current task 64.** Add Spec-derived failing runtime, retrieval, graph,
  registry, and release-evidence tests before production changes.
  - Covers: PAE-010, PAE-013, PAE-016, PAE-019, PAE-027, PAE-029, PAE-034.
  - Red oracle: three-attempt OpenMath parse/canonicalize/validate and zero-downstream exhaustion;
    real PostgreSQL/pgvector fixed top-8/no-cutoff query, stable ties, structural plus real LLM 0..4
    rerank, zero-context ordinary Draft, and every no-fallback failure; exact graph/re-entry and
    durable-verification-only Explain/Clarify; exact eight-role registry and environment override/
    response mismatch/failover rejection; exact five-variable evaluator states, unequal credential,
    and distinct-call rejection; live-evidence mutation matrix including at least two repair cycles.
  - Completion evidence: focused tests fail for the intended absent/incorrect production behavior,
    never from fixture setup and never by treating a mock as live success.

- [ ] 52. **PAE-034 GREEN; depends on task 51's verified Red and task 28 worker-client-removal/API-
  refetch Green.** Implement the release runtime and make task 51 pass without weakening assertions.
  - Covers: PAE-010, PAE-013, PAE-016, PAE-019, PAE-027, PAE-029, PAE-034.
  - Implementation: immutable `ReleaseRoleRegistry`; strict `OpenMathStructurer`; authoritative
    `PgvectorDraftRepository`; canonical structural scorer; real `draft` relevance reranker and
    ordinary Draft generator; explicit Draft/Sketch/Prove/API-candidate-submission/authoritative-
    result-refetch/Route/Repair re-entry graph consuming Task 28's ports and prohibitions;
    durable verified-artifact gate; Explain/Clarify gates; exact evaluator state/credential/request
    separation; eight-role schema-v3 provenance; expanded strict live evidence writer.
  - Green verification: all task-51 deterministic and real-DB integration tests pass; release
    composition exposes no packaged/in-memory/exact/lexical/model/local/fake fallback; direct child
    CLI and parent GNU Make 0/2 contracts remain Green. The cost-bearing real release execution is
    exclusively task 50.

## PRX T-010 Agent Child: Convergence, Red, Green, and Release

- [x] 65. **PRX-009 clarification consumer import, Spec only.** Add PAE-038 requirements-first,
  then design and tasks; import the exact clarification receive/marker/`dispatch_uncertain`
  contract, add child property/traceability rows, retain only Agent receive/claim/model/update/
  visibility/retain/delete implementation authority, and edit no implementation/test/status.

- [x] 66. **Current parent-readiness and draft-review repair, Spec only.** Requirements-first
  replace stale readiness predecessors with parent PRX T-036/T-010, PLS T-061/T-071, current DEO
  T-047 through T-053 then T-036, and completed Task 65; record complete
  PRX-001–PRX-009/AC-001–AC-009 import through PAE-035–PAE-038 from the exact parent triple
  `8d892980c636b831511314edf9ff9b104f9d395f7ffec1506bfb4f87a674d8f8` /
  `e6c8dde804d9d7127f8d38290a10bc5c69fc3bc85fd0397a1548f6a26f1d1980` /
  `00b972b01ce2dba3fe66557cc7db0ec897b42c5d1851d277fc7736ad6f19f71a`; require Task 53's all-zero technical
  `IMPLEMENTATION READY` verdict to remain explicitly non-authoritative while draft. Then update
  design and tasks. Preserve status/history and edit no implementation/test/parent/inventory file.

- [x] 67. **Completed historical T-011 cycle removal, Spec only.** At that revision, preserve Task
  66 as history and remove PLS T-071 from the active child Spec convergence/promotion predecessors.
  Keep renewed approved PLS T-061 as the Spec predecessor and retain T-071 as an independent hard
  prerequisite of every applicable Agent implementation/test task. The later PLS/PRX join
  restoration supersedes only the old claimed `T-071 -> T-011` edge. Edit no
  implementation/test/parent/inventory file.

- [x] 68. **DEO implementation-gate cycle removal, Spec only.** Preserve Task 66 as history but
  narrow the active child Spec convergence/promotion predecessor to current parent DEO
  T-047 -> T-048 Spec restoration/convergence. Move DEO T-049 through T-053 then T-036 to the hard
  post-T-011 implementation/test gate because T-049 and T-050 edit tests and cannot precede parent
  T-011. Preserve all DEO behavior and edit no implementation/test/parent/inventory file.

- [x] 69. **PAE-038 behavior-property closure, Spec only.** Requirements-first replace the stale
  eight-property/three-requirement canonical artifact clause with the exact eleven-property/four-
  requirement PAE-035–PAE-038 mapping already required by the later acceptance contract and design.
  Preserve artifact path/schema/JCS-plus-LF/digest/OCI binding, ownership, runtime behavior, approved
  status, and all implementation gates; edit no implementation, test, parent, or inventory file.

- [x] 70. **Immutable OpenAI release snapshot, Spec only.** Requirements-first replace the mutable
  eight-role `gpt-5.4-mini` alias with exact snapshot `gpt-5.4-mini-2026-03-17`, then align design,
  task verification, and coordinated draft ARCH-024 import. Preserve provider, roles, cardinality,
  evaluator separation, pricing/provenance, live-gate behavior, `.local`, and every non-model
  contract. Edit no implementation or test file. At that revision it required a new Task 64 review;
  current Tasks 73 then 64 supersede that prior-byte authority; Tasks 75/76 separately verify
  report-only governance.

- [x] 71. **Verified-proof receipt recovery closure, Spec only.** Requirements-first retain the
  PAE-035 proof receipt after PAE-020-valid verified reconciliation while ending the proof claim,
  run explanation only under its distinct PEX claim, and delete the receipt only after exact
  same-target explanation `completed|failed`. Preserve immediate failed/canceled acknowledgement,
  one queue/message, PRX-002 wire, PEX schemas, proof truth, separate claims, and ambiguity/DLQ
  retention. Then align design, CORE, and test tasks without implementation edits.

- [x] 53. **Historical completed draft review/status-only promotion for prior bytes; superseded by
  the current Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64 sequence.**
  Depends exactly on completed parent PRX T-036 then T-010, renewed approved PLS T-061,
  current parent DEO T-047 -> T-048 Spec restoration/convergence, and
  completed tasks 65–68. A fresh independent reviewer reads the current three child files and must
  report technical verdict `IMPLEMENTATION READY`, CRITICAL=0, HIGH=0, and no material question,
  while explicitly recording that `status: draft` remains non-authoritative and permits no
  implementation. Remediate any finding requirements -> design -> tasks, then rerun this draft
  review. After that exact result, obtain explicit maintainer/user authorization and change only
  `status: draft` to
  `status: approved`; any simultaneous byte edit invalidates the draft review. Immediately run the
  ownership checker and require exact `spec-ownership: PASS`. Record only this evidence without
  editing parent/API/Infra files or claiming parent T-011 complete. This task does not perform or
  satisfy the post-promotion review.

Every still-pending executable implementation or test task anywhere in this file additionally
depends independently on completed PLS T-071, completed parent T-011, and completed parent DEO
T-036. PLS T-071 and parent T-011 have no ordering edge; DEO T-049 through T-053 then T-036
complete after T-011 and before applicable Agent execution. This hard predecessor is omitted from repeated task prose only for readability. It does not
apply to current Spec-only Tasks 73/64, completed Task 74, completed Spec history, or
never-executed/superseded history.

- [ ] 54. **QUEUE RED; Agent slice of parent T-014.** Depends on current task 64 and parent T-013.
  Add failing parent-corpus and LocalStack tests for every v1 body/attribute/digest/queue/receipt
  mutation, initial visibility, extension/delete ambiguity, invalid/poison retention, redrive-only
  DLQ arrival, fresh-claim redelivery, old/unversioned parser denial, and zero downstream calls.
  Include PRX-009 clarification-vs-proof routing, canonical empty attributes, worker-input marker,
  and terminal `dispatch_uncertain` delete-without-claim/model/update.
  Retain test names/results proving failure is the intended missing Agent behavior.

- [ ] 55. **QUEUE GREEN; Agent slice of parent T-015.** Depends on task 54's verified Red.
  Implement only PAE-035/PAE-038 consumers/validators/receipt lifecycle and DSP wiring. Make the focused
  contract and LocalStack commands pass, followed by full pytest/Ruff/mypy. Do not add an API
  producer/reconciler/PostgreSQL behavior or create/mutate queue/DLQ/Infra resources.

- [ ] 56. **VERIFIER RED; Agent slice of parent T-016.** Depends on current task 64 and parent T-013.
  Add failing parent-corpus, mTLS, and real-Docker tests for exact port/routes/TLS/readiness/
  request/response/status/framing, deployment/image/toolchain binding, one-slot admission, 300-second
  server wall, compiler/cleanup truth, server-only attestation, API-only caller, three immutable
  SecretBinary ports, cross-role denial, and no Unix/plaintext/sidecar/worker/local/mock success.

- [ ] 57. **VERIFIER GREEN; Agent slice of parent T-017.** Depends on task 56's verified Red, task
  49 PAE-017 Green, task 52 PAE-034 Green, and task 28 worker-client-removal/API-refetch Green.
  Implement only the PAE-036 HTTP server, secret consumer adapters, readiness/response producer,
  and unchanged PAE-017 compiler engine. Make the focused HTTP/mTLS/Docker commands pass, then full
  gates. Do not implement the API reconciler, API client credential, Infra network, roles, secrets,
  KMS, ALB, ECS, or database behavior.

- [ ] 58. **RELEASE/SECRET/REGISTRY/TELEMETRY RED; Agent slices of parent T-018, T-020, T-022,
  and T-030.** Depends on current task 64 and parent T-013. Add failing tests for blocked/active v1
  entrypoint, stop/retain/resume participation, old-worker denial, wrong image/queue/toolchain/property
  binding, every property ID/mapping/digest/OCI-label mutation, secret ARN/VersionId/type/leakage/
  opposite-role access, every imported metric/label-domain mutation, and source/import/capability
  checks that reject an Agent provider/ECS/SQS observer, durable cutover/effect sink, or API
  persistence adapter.

- [ ] 59. **RELEASE/SECRET/REGISTRY/TELEMETRY GREEN; Agent slices of parent T-019, T-021, T-023,
  and T-031.** Depends on task 58's verified Red and the corresponding parent Red evidence.
  Implement only PAE-037 Agent lifecycle, property artifact loader/OCI check, least-privilege
  memory-only secret consumers, old-worker fail-closed behavior, Agent-owned PRX-006 image/toolchain/
  property provenance contribution, and imported closed telemetry. No provider/quiescence observer,
  durable cutover/effect sink, API PostgreSQL/admission persistence, or Infra resource implementation
  is permitted.

- [ ] 60. **REAL INTEGRATION; Agent contribution to parent T-024.** Depends explicitly on task 28
  worker-client-removal/API-refetch Green, task 49 PAE-017 Green, task 52 PAE-034 Green, tasks 55, 57,
  and 59, plus parent T-015/T-017/T-019/T-021/T-023/T-031 Green evidence. Run the exact real dependency
  story through v1 receipt, fresh claim, all eight DSP roles, API submission/reconciliation, private
  mTLS verifier, at least two parent-bound compile-failure repairs, durable verified artifact,
  explanation, clarification, redelivery/takeover, rotation/revocation, and forward rollback. Agent
  commands consume externally supplied API/Infra resources and provider/release evidence and never
  observe, persist, provision, or mutate those cross-repository surfaces.

- [ ] 61. **OPERATIONS/DOCS/ARTIFACTS; Agent contribution to parent T-025.** Depends on task 60.
  Execute all focused and full repository-local commands; publish worker/verifier image metadata,
  toolchain manifest/digest, exact behavior-property artifact/OCI label as the complete Agent-owned
  PRX-006 provenance contribution, content-free telemetry, and evidence locations. Add only the
  required README `Proof Runtime v1 Operations` and SECURITY
  `Isolated Verifier mTLS Boundary` sections during implementation; this Spec update edits neither.

- [ ] 62. **AWS RELEASE EVIDENCE; Agent contribution to parent T-026.** Depends on tasks 50 and 61 and the
  parent T-026 prerequisites. Execute the Agent steps of one signed higher-sequence pre-production
  release: receipt blocked, exact images/properties/readiness admitted, old worker denied, gate
  opened, nonterminal duplicate redelivered, and forward rollback completed. LocalStack, mock,
  fixture, recorded, stale, or old-image evidence cannot substitute.

- [ ] 63. **FINAL INDEPENDENT REVIEW; Agent contribution to parent T-027.** Depends on task 62.
  Independently review PAE-035–PAE-038 plus modified PAE-017/020/021/033/034 for ownership, imported
  DTO fidelity, receipt liveness, compiler truth, mTLS/secret isolation, old-worker denial,
  property/telemetry integrity, commands/docs, and no-mock/no-shortcut release evidence. Require no
  unresolved CRITICAL/HIGH finding and report residual risk without promoting any other Spec.

- [x] 72. **Parent-authority relocation authoring, Spec only.** Demote PAE to draft because EXP
  deadline/rubric authority and PFI retrieval authority were duplicated with conflicting contracts.
  Preserve the current PAE runtime semantics as the parent target, record the future import boundary,
  and change no implementation, test, parent, ownership, runtime, or external system. This authoring
  completion is not convergence, promotion, or implementation readiness.

- [x] 81. **Current upstream drift demotion and convergence reopen; Spec only; depends on completed
  Tasks 74 and 80.**
  - Change ID: `SPEC-CHG-2026-07-27-PAE-CURRENT-UPSTREAM-DRIFT-REOPEN`.
  - Requirements-first demote requirements frontmatter to `draft`; record the then-final approved/
    post-reviewed API PEX triple
    `9fdc2f0edbffcc8d10bfd2de387e8c8a2a43dae7f8970fbb6ae7e4ec6917607e`,
    `42d6bc2f80157658edd46082c35e90bf2563d4207b833598b2a1594271844996`, and
    `155be009c4f28b0b600873d31819d2dcbbf04887063c217aba7bb629bfcc1b69`; reopen Tasks 73 and
    64. A later PJSA/PJR/PWA/PEX convergence cycle superseded only that point-in-time identity;
    current Task 73 records the final API PEX import. This is authoring evidence only and authorizes
    no implementation, test, promotion, or runtime work.

- [x] 82. **Current DEO final-identity demotion and convergence reopen; Spec only; depends on
  completed Tasks 74, 80, and 81 and DEO Task 62 authoring.**
  - Change ID: `SPEC-CHG-2026-07-27-PAE-DEO-FINAL-IDENTITY-REOPEN`.
  - Requirements-first demote requirements frontmatter from `approved` to `draft`; record that the
    checked Tasks 73/64 pin the DEO identity preceding DEO-R48-001; reopen both markers to `[ ]`.
  - Historical at Task-82 execution: pin then-current DEO requirements
    `e1d0aba03da548336a5b59dab329c6a0f3bd14c9ad101a866e316070b8487f60`, design
    `58f2cc33142016d736748ed103aabf10892f060ecf1cf5e16e15e00b2c4b017c`, and tasks
    `1ef03cbcb186c0709415363e6a0e11c572deff18d85f89fc8023f8afe53324e2`.
  - Current Task 84 supersedes that point-in-time triple and must wait for the external fresh DEO
    Task-48 report before recording its report-covered triple. Only then may Task 73 synchronize
    imports, run fresh draft convergence, and perform only the explicitly
    authorized status-only promotion, and require ownership PASS. Require current Task 64 to
    independently revalidate the same report and perform the distinct promoted-byte review.
    PRX T011 remains blocked until both current DEO Task 48 and renewed Task 64 complete.
  - Change no PAE-001–PAE-038 behavior, acceptance criterion, implementation, test, code, runtime,
    migration, security/privacy, rollout, rollback, recovery, or external system. This checked
    authoring marker is not review, approval, promotion, implementation, or PRX readiness evidence.

- [x] 83. **Historical PRX T-047 parent-import synchronization, superseded by Task 84; Spec only.** It pinned the then-current PAE-033
  PRX requirements/design/tasks import to the T-046-reviewed triple
  `2814ff312e4b4dac941c3cfcf74f54b7aaf3da7b818ac688083d0f577a951e59` /
  `d2aa7f3d061879fdd01c8a26c897d9bc91c44a8750a5884965862950ec46ee05` /
  `95b0430e195d572e970367854bf12b4467a6cf032f953f318a1147a085ec91d9` and preserve draft status.
  This SDD-024 workflow-only synchronization changes no runtime behavior and is not review,
  promotion, implementation, test, or PRX T-011 evidence.

- [x] 84. **Current DEO Task-48 report and PRX import rebaseline; Spec only.**
  - Change ID: `SPEC-CHG-2026-07-27-PAE-DEO-T48-REPORT-REBASELINE`.
  - Depends on: completed Task 82, historical Task 83, and the external fresh current-byte DEO
    Task-48 report.
  - Verification: requirements first pin exactly the consumed report-covered DEO requirements/design/tasks
    identity `9cb00ba39a34cc0fb035507dd4499c94a9c7b229f6abb4bda9795ffa01397efc` /
    `ee7e8d754668e9fb7639e6f691840f0bfb79c793f63909912f944ce3954120cf` /
    `759014da8d79a13bd1bb5f1b92096506837049f751d3ac49672448549a67d0c4` and current approved PRX
    requirements/design/tasks `c8f585e26d664f5e6cf3b1d56cb917f17bbac7a5192cddc421ee0b6b8b40b3e2` /
    `5b90d8afbcb2f5446d84150e22d18d2c8b1dc8748ba44192dece41c8dbdd5a51` /
    `4e01c8a80e1f7921e2f488a887bfcf09004c0b82601a6c2168c6585d26e63a82`; no future identity is
    inferred and no report verdict/ledger is persisted. Preserve `draft` status and all runtime/test/
    implementation behavior. Task 84 is authoring only and is neither review nor promotion authority.

- [x] 87. **Current PRX T-052 parent-import synchronization, Spec only.**
  - Change ID: `SPEC-CHG-2026-07-31-PAE-PRX-T052-CHILD-SYNC`.
  - Authority: approved parent PRX Task T-052.
  - Verification: requirements first, then design and this task record, pin every active PAE parent
    import to `c8f585e26d664f5e6cf3b1d56cb917f17bbac7a5192cddc421ee0b6b8b40b3e2` /
    `5b90d8afbcb2f5446d84150e22d18d2c8b1dc8748ba44192dece41c8dbdd5a51` /
    `4e01c8a80e1f7921e2f488a887bfcf09004c0b82601a6c2168c6585d26e63a82`.
    Preserve historical parent triples and all runtime/test/code/status behavior. The applicable
    independent review must be renewed before this child contributes to parent T-011.

- [x] 73. **Current authority-relocation import, fresh draft convergence, status-only promotion, and
  ownership PASS; Spec only; depends on completed Tasks 74, 80, 81, 82, and Task 84 and the external fresh current-byte DEO
  Task-48 report.**
  - Change ID: `SPEC-CHG-2026-07-26-PAE-AUTHORITY-RELOCATION-GATE`.
  - Covers: PAE-001–PAE-038; current dependency and authority gate only.
  - Current: Task 72 demoted PAE to draft, but the prior active gate still relied on completed
    Task 53 and open Task 64, contained no executable EXP/PFI import alignment, and left Tasks 28/29
    on superseded PJR T-020/PEX T-033 Green evidence.
  - Expected: first require the exact approved normative PFI `specs/proof-flow-index`
    requirements/design/tasks SHA-256 values `32fa6f5113712d3e8bfe7484cad65ed0ffd525212a36511a5cd95a3eb3fca243`,
    `f00c8e7ad2c151a4e89a47c20dfd7480845db3596c5f38c2e7175fa3b1755129`, and
    `d5212f09e8a1edcf93a0af895f84a5d2b1d463c3021267574e4b8f591e7a9739`.
    Also require Task 84's exact current external Task-48 report triple; consume it as
    Spec-authority evidence only and persist no verdict/ledger copy. No older or inferred DEO
    triple is accepted.
    The exact `TDG -> EXP -> PJR -> PWA -> API PEX` chain is approved and separately post-reviewed,
    including PJR T-061, PWA Task 3, and API PEX T-073. Record and validate the exact current
    approved requirements/design/tasks identity for EXP
    `a2a3e97055951bae745932e91693f9e6e09de2d1c4edb8d33ddb902a94063563` /
    `f66d0ca6650d1bfb6e9dfb8fc6bd8690b6e475ee02d645e5cb895d226f97c055` /
    `7fea5fc7eae2e8ace80028a6415ed4f5ae3f02113e3be84d8f6dc76ba5cd5285`,
    PJR `75c0dd6f44da5db808d767749896cf751895910cb520e606c796407759b245c4` /
    `a59af7fa1fdd6cc0594a123045260db9ac135c37c09d03a5ccb43555de5b86f3` /
    `33dd054c62bc02e0efc1fa2e6e6dbe9b88e91c64efb74984b1ae8db066c1627b`,
    PWA `c6e7232aad472529139a7fa91351a1942b0ac4987abaea5089e3bbb4d3aa5f02` /
    `92f576820a9c3d1041f90163574e80bcc4ce355ff5c6c6e36cb3d047be4a8f4e` /
    `686598da329b043e17efdf91562cd61c202dbe7423d23c8e08e4cc478e2dedcc`,
    and API PEX `6a3775af76a224cba05f611980639e54a40d36be8ecbc798c679a7c1469243c1` /
    `3af51d11d7f8ca78f02f99362dcacc399286b985b27c0ac99b4bb33760405bf9` /
    `6dc7d1f86ab1e693c9a85f1e7830c041dbf29e2d1f69f5d7a8a71fd4d1820d3d`, and
    apply the import-only alignment requirements first, then design, then tasks. A fresh independent
    reviewer who did not author or remediate any current candidate byte, including Task 84, must
    return exact `IMPLEMENTATION READY`, CRITICAL=0, HIGH=0, and no material question
    while `status: draft` is explicitly non-authoritative. Remediate and rerun until that exact
    result; then perform only an explicitly authorized `status: draft` to `status: approved` edit
    and require exact `spec-ownership: PASS`. Task 73 performs no promoted-byte post-review; that
    distinct review belongs only to current Task 64.
  - Completion-marker publication: Task 73 remains `[ ]` through exact imports, draft review,
    frontmatter-only promotion, and ownership PASS. After and only after success, prove that
    changing exactly this checkbox token from `[x]` back to `[ ]` reproduces the consumed tasks
    bytes, then change only `[ ]` to `[x]`. This sole inverse-proved transform does not invalidate
    Task 73; every other canonical edit restarts the applicable Task-73/Task-64 sequence.
  - Unchanged: all Agent runtime, evaluator, deadline, rubric, retrieval, model, toolchain, security,
    persistence, rollout, rollback, recovery, test, and public behavior; every requirement/AC ID;
    PFI/EXP/PJR/PWA/API PEX ownership; PLS T-071, parent PRX T-011, and parent DEO T-036 as
    independent implementation/test prerequisites; completed historical evidence; and every code,
    test, parent/API Spec, registry, generated artifact, external record, deployment, and runtime
    byte.
  - Verification: before any content review, independently hash all imported three-file bundles and
    reject missing/draft/stale/drifted identity. Prove requirements -> design -> tasks traceability,
    exact PFI and exact current EXP/PJR/PWA/API PEX imports, PAE-001–PAE-038 coverage, authority
    ownership, runtime/evaluator/deadline/release/security/toolchain/rollback closure, and no material
    question. Persist only the exact imported requirements/design/tasks identities that define the
    normative import boundary. Return reviewer identity, the complete current-candidate
    author/remediator identity set including Task 84, true reviewer/set nonmembership, candidate
    hashes/triple, verdict, status-only transform, ownership result, gates, and invocation ledger
    externally under SDD-024; missing, incomplete, non-disjoint, or mismatched input fails;
    do not append them here. Completion of
    Task 73 opens current Task 64 but authorizes no implementation/test work. Tasks 28/29 additionally
    wait for current real API Green PJR T-053 and API PEX T-065.
  - This task authorizes no implementation or tests; bundle authority follows requirements
    frontmatter, and current implementation remains blocked until Task 64 completes.

- [x] 64. **Current distinct promoted-byte post-review; depends on completed Task 73 and independent
  revalidation of the same external fresh current-byte DEO Task-48 report.**
  - Covers: PAE-001–PAE-038 and every exact PFI/EXP/PJR/PWA/API PEX import recorded by Task 73.
  - Current verification: a reviewer outside the complete current-candidate author/remediator set,
    including every Task-84 author/remediator and the Task-73 pre-promotion reviewer, must first
    revalidate the exact DEO identity/report pinned in Task 73, then re-read the
    exact promoted requirements/design/tasks bytes from disk, reproduce
    every imported three-file identity, verify the inverse status-only transformation, and return
    exact `IMPLEMENTATION READY`, P0/P1/P2/P3=0, CRITICAL=0, HIGH=0, and no material question.
    Runtime/evaluator/deadline/release/security/toolchain/rollback traceability, PAE-001 through
    PAE-038 coverage, DEO-001/DEO-015 compatibility, current API Green dependencies, and ownership/
    topology/secrets/diff gates are mandatory. Any content/import/status drift or nonzero finding
    keeps every pending executable task blocked and requires the applicable requirements-first
    remediation and fresh Task-73/Task-64 review sequence.
    The external report must bind reviewer identity, the complete current-candidate author/remediator
    set, true reviewer/set nonmembership, and the reviewed promoted triple; any absent, incomplete,
    non-disjoint, or mismatched input fails. The current verdict, hashes, gates, and invocation
    ledger remain only in that external report under SDD-024 and are not appended to this task.
  - Completion-marker publication: Task 64 remains `[ ]` throughout that external review. After and
    only after success, prove that changing only this Task-64 checkbox token from `[x]` back to
    `[ ]` reproduces the exact reviewed task bytes, then change only this token from `[ ]` to `[x]`.
    This sole inverse-proved transform does not invalidate Task 64. Every other byte change restarts
    the applicable Task-73/Task-64 sequence. Parent DEO Task 36 can then observe current approved PAE
    bytes and checked Task 64.
- [x] 74. **DEO Task-64 post-review compatibility and current Task-48 authority-import restoration;
  Spec only.**
  - Change ID: `SPEC-CHG-2026-07-26-PAE-DEO-TASK64-POST-REVIEW-RESTORATION`.
  - Additional change ID: `SPEC-CHG-2026-07-26-PAE-DEO-TASK48-AUTHORITY-IMPORT`.
  - Current: Task 73 correctly owns exact imports, fresh all-zero non-authoritative draft review,
    status-only promotion, and ownership PASS, but also absorbs the distinct post-promotion review
    and labels Task 64 historical, conflicting with approved DEO-001/DEO-015.
  - Expected: Task 53 remains historical; Task 73 contains no post-promotion review; current Task 64
    depends on Task 73 and owns the different-reviewer exact promoted-byte/import all-zero review for
    PAE-001 through PAE-038; both Tasks 73 and 64 consume/revalidate the external fresh current-byte
    DEO Task-48 report authority-only; every pending executable task depends on current Task 64.
  - Unchanged: approved DEO, PAE runtime behavior, evaluator/deadline/rubric/retrieval/model/toolchain/
    security/persistence/release/rollback/recovery contracts, status `draft`, every prior task state,
    code, tests, migrations, registries, generated artifacts, deployments, external records, and
    runtime evidence.
  - Historical verification at that revision: requirements, design, and tasks state exact acyclic order
    `Task 74 -> Task 80 -> Task 81 -> Task 73 -> Task 64 -> pending executable work`; Task 73 names Tasks 74,
    80, and 81, and Task 64 names Task 73; direct and global pending gates name Task 64; fresh
    independent review remains required for these exact bytes.

- [x] 75. **SDD-024 report-only review-ledger restoration; Spec only.**
  - Change ID: `SPEC-CHG-2026-07-26-PAE-REPORT-ONLY-LEDGER`.
  - Requirements-first remove every current or historical Spec-review invocation table, counter,
    fingerprint, reviewed-file hash, gate transcript, and verdict copy from requirements, design,
    and tasks. Retain stable remediation scope, monotonic task state, and implementation/test
    evidence. Keep PAE `draft`; change no runtime, test, generated artifact, external record,
    deployment, or authority owner. Pin the exact then-current approved DEO requirements/design/tasks
    identity `f46054da5304d3e890f07ab05c4de8a28388bafa9f74af5a151e766f9c9ab3fb`,
    `39584cd1d201ed28b5afb4a0ab4fd9b39535024b29c95a149cc2ae3cb5b8184b`, and
    `5bdc0249e96b428264e9508609c18854c1cea1bbf6db1f4e2c7ef185e44a36ea`; the matching Task-48
    verdict remains external and supplies Spec authority only.
- [x] 77. **Current approved PFI byte synchronization; Spec only; depends on Task 75.**
  Requirements-first replace every active PFI import with the exact current approved
  requirements/design/tasks identity, preserve imported behavior and draft status, and change no
  runtime, test, authority owner, lifecycle, external record, or implementation state. This
  authoring task supplies no review or implementation
  authority.
- [x] 78. **SDD-024 residual review-output cleanup; Spec only; depends on Tasks 75 and 77.**
  - Change ID: `SPEC-CHG-2026-07-27-PAE-SDD024-RESIDUAL-CLEANUP`.
  - Current: after Tasks 75 and 77, the canonical bundle still contains historical Spec-review
    severity totals, reviewer/source and fingerprint provenance, two reviewed-baseline bundle
    triples, and stale active PFI import hashes.
  - Expected: remove only those past invocation outputs, retain the substantive defects and
    remediations without report provenance, and synchronize every active PFI import to the exact
    current approved three-file identity. Task 76 remains the fresh independent external-only
    review; Task 78 supplies no review, promotion, implementation, test, or runtime authority.
  - Unchanged: every existing task checkbox, PAE-001–PAE-038 and their acceptance criteria,
    implementation/test evidence, then-current approved DEO triple,
    `Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64`,
    `Task 75 -> Task 77 -> Task 78 -> Task 76` plus direct `Task 75 -> Task 78`, status `draft`,
    code, tests, runtime, generated artifacts,
    rollout, rollback, recovery, and external systems.
- [x] 79. **Task-64 completion-marker cycle and Task-76 side-DAG restoration; Spec only.**
  - Change ID: `SPEC-CHG-2026-07-27-PAE-TASK64-COMPLETION-MARKER`.
  - Current: Task 64 reviews promoted bytes while unchecked, but its general byte-drift rule makes
    the required checked completion marker invalidate that same review; Task 76 also omits Task 78
    from its written side-branch DAG.
  - Expected: requirements, design, and tasks define the sole inverse-proved Task-64 checkbox-token
    publication that does not invalidate the successful external Task-64 review. Every other byte
    change restarts the applicable Task-73/Task-64 sequence. The side-branch backbone is
    `Task 75 -> Task 77 -> Task 78 -> Task 76`, with direct `Task 75 -> Task 78`.
  - Unchanged: Task 64 remains `[ ]` in this authoring pass; Task 76 remains pending and
    external-only; Task 79 adds no side-branch dependency or review authority; status remains
    `draft`; PAE-001–PAE-038, exact imports, code, tests, runtime/generated artifacts, external
    reports/systems, DEO, and LFE remain unchanged.
- [x] 80. **Historical upstream-authority/DEO synchronization and Task-73 marker/status projection,
  superseded for current import identity by Tasks 81 and 73; Spec only.**
  - Change IDs: `SPEC-CHG-2026-07-27-PAE-UPSTREAM-AUTHORITY-IMPORTS` and
    `SPEC-CHG-2026-07-27-PAE-TASK73-COMPLETION-MARKER`.
  - Historical verification: for those bytes, requirements/design/tasks pinned then-current approved EXP
    `2753566871b94546ab6cc6b43757e80dc8e69878165a5bab2a5737aba43ef649` /
    `0d88b00580297b5ec64fc1451a28aa737673321403a96253d7ef197ef0ff6eee` /
    `496439682f16140e5a19d74216eb69fd028ed14e8e4859975f393c0392f36325`,
    PJR `cdb48cd1488c91b145a4b04dc5dc19aa9c34aa468e78c70d056a6e2fbc2b4ee3` /
    `c3fb91a07dcfbf29a60038ce8278cee52927420e774a4d7bf3cfaa73128fd726` /
    `ed6dc79c87545f0949af269a4aea76469105897909c32228cefa4634e58e52c7`,
    PWA `2124f9d2122fc88893e6e74868961049678fbf386907977b94e8b964be78976c` /
    `84604455cada36b1c55cd6dc9fef2b2358afd45860a92dcd26f6bd65992c6c7d` /
    `ca616db76355e60bf1ccaa5471e76dc75a911322c230d14f8ee0d775d0565f06`,
    API PEX `0c9bd60a5e22e81d414014f60cd07d0bda836ab336c3e89da3e3ee50a6fbcbf0` /
    `65f2b13082a4cdc53a433f2292df367d14a0c4a1fe52738b926a5a1b9bfe5653` /
    `21b4e541709bbf6561bdcce02322b9107e0e204114c6ff0757f8485824fa9a59`,
    and DEO `f46054da5304d3e890f07ab05c4de8a28388bafa9f74af5a151e766f9c9ab3fb` /
    `39584cd1d201ed28b5afb4a0ab4fd9b39535024b29c95a149cc2ae3cb5b8184b` /
    `5bdc0249e96b428264e9508609c18854c1cea1bbf6db1f4e2c7ef185e44a36ea`;
    Task 73 had the sole inverse-proved completion marker and active authority prose followed
    requirements frontmatter. Later upstream drift superseded these point-in-time identities;
    current Task 73 pins the final imports. Product/runtime behavior and external evidence are
    unchanged.
- [ ] 76. **Fresh report-only-ledger and byte-synchronization review; depends on Tasks 75, 77, and
  78.**
  A fresh independent reviewer verifies the current three files contain no persisted Spec-review
  invocation evidence, the PFI import is exact current approved authority, and the side branch
  `Task 75 -> Task 77 -> Task 78 -> Task 76`, with direct edge `Task 75 -> Task 78`, and authority
  branch `Task 74 -> Task 80 -> Task 81 -> Task 82 -> Task 83 -> Task 84 -> Task 73 -> Task 64` are independently
  acyclic. Return hashes, findings,
  severity counts, questions, gates, and verdict only in the external report. This task neither
  promotes status nor authorizes implementation.

## PRX Agent Verification Matrix

| Requirement / parent task | Design | Red task | Green / gate tasks |
|---|---|---:|---|
| PAE-035 / T-014–T-015 | ProofDispatchV1Consumer; ReceiptLifecycle | 54 | 55, 60–63 |
| PAE-036 / T-016–T-017 | IsolatedVerifierHttpServer; secret consumer ports; Task 28 worker-client denial/refetch | 56 | 28, 49, 52, 57, 60–63 |
| PAE-037 / T-018–T-023, T-030–T-031 | blocked/active entrypoint; property/OCI/PRX-006 provenance; no provider/persistence adapter | 58 | 59–63 |
| PAE-038 / PRX-009 | clarification router/marker/receipt lifecycle; `dispatch_uncertain` zero-generation terminal | 54 | 55, 58–63 |
| PAE-001–PAE-038 / T-011 | Task 82 exact final-DEO-identity demotion/reopen; Task 83 historical PRX T-047 identity synchronization; Task 84 records the external exact current DEO Task-48 report identity before reopened Task 73 and Task 64 independently revalidate it; current Task 73 exact PFI/EXP/PJR/PWA/API PEX/DEO imports, all-zero technical/non-authoritative draft review, status-only promotion, ownership PASS, and inverse-proved completion marker; current Task 64 distinct promoted-byte/import post-review while unchecked plus sole inverse-proved checkbox-token publication; current DEO Task 48 and renewed Task 64 both precede T-011 | 73 | 64, then 54–63 |

## PAE-017 Restoration Verification Matrix

| Requirement / AC family | Design | Red task | Green / gate tasks |
|---|---|---:|---|
| PAE-017/PAE-027 canonical exhaustive manifest grammar, descriptor coverage, and digest equality | Startup toolchain resolution | 47 | 48–49 |
| PAE-017 fixed project and descriptor-authoritative toolchain root pin/re-attestation; no literal prefix | Startup toolchain resolution | 47 | 48–49 |
| PAE-017 O_EXCL/link-count mutable files and manifest path/size/digest immutable inputs | Setup-file then direct Lean | 47 | 48–49 |
| PAE-017 setup/direct order and complete positive/rejection ModuleSetup wire grammar | Setup-file then direct Lean; Deterministic real-Docker oracle | 47 | 48–49 |
| PAE-017 exact generated environment and no toolchain variables | Setup-file then direct Lean; separate setup ELF and direct-Lean `run_tac` oracles; Security and Privacy | 47 | 48–49 |
| PAE-017 setup/direct x six outcomes, exact outcome anchor, delay-before-entry, and ordinary/escaped descendants | Descendant cleanup trust boundary; Deterministic real-Docker oracle | 47 | 48–49 |
| PAE-017 unchanged outer/resource limits and private mTLS HTTP deployment integration | Security and Privacy; Testing Strategy | 26, 47, 56 | 48–49, 57, 60 |

## DEO-v1 Producer Verification Matrix

| Requirement | Design | Red task | Green / gate tasks |
|---|---|---:|---|
| PAE-014 | Explicit export operation; ownership/read-only boundary; failure and rollout effects | 39, 43 | 40, 44–46 |
| PAE-030 | Completed invocation adapter; Closed DTO and mapping pipeline | 39 | 40, 45–46 |
| PAE-031 | Material fingerprints and producer HMAC; Producer key providers | 41 | 42, 45–46 |
| PAE-032 | Serialization, deterministic naming, create-only publication/replay/conflict; privacy and conformance guards | 43 | 44–46 |
| PAE-033 | External exact current DEO Task-48 report validation at Task 73 and independent revalidation at Task 64; Task 73 exact focused authority imports, all-zero technical/non-authoritative draft review, status-only promotion, ownership PASS, and sole inverse-proved Task-73 marker publication, followed by current Task 64 distinct promoted-byte/import post-review while unchecked and sole inverse-proved Task-64 marker publication; ownership boundary and privacy/conformance guards | 39, 41, 43 | 64, then 44–46 |

## PAE-034 Runtime Verification Matrix

| Requirement / AC family | Design | Red task | Green / gate tasks |
|---|---|---:|---|
| PAE-034 OpenMath three-attempt fail-closed structuring | Release Runtime Architecture | 51 | 52, 50 |
| PAE-034 PostgreSQL/pgvector top-8 and structural/LLM 0..4 rerank | Release Runtime Architecture | 51 | 52, 50 |
| PAE-016/PAE-034 bounded graph re-entry, API refetch, and durable verified artifact | Release Runtime Architecture; State, Failure, and Recovery | 28, 51 | 28, 52, 50 |
| PAE-019/PAE-034 evaluator state/credential/distinct call and fixed eight-role registry | Release Runtime Architecture; Interfaces and Contracts | 51 | 52, 50 |
| PAE-010/PAE-034 complete real release oracle after verifier Green and real integration | Testing Strategy | 51 | 52, 57, 60, 50 |

## Traceability Check

- [ ] Every Must requirement has implementation and test evidence.
- [ ] Missing prerequisite evidence remains `not_evaluated`; missing verified-flow output required
  by the oracle is an evaluated failure.
- [ ] No task or test uses benchmark-specific expected strategy as generation input.
- [ ] Vendor-specific observability code remains in its approved repository boundary.
- [ ] No credentialed worker path can execute Lean locally, call/simulate the verifier, hold verifier
  mTLS material, synthesize attestation, or bypass authoritative API reconciliation/refetch.
- [ ] PAE-017 project setup uses pinned absolute Lake `setup-file --no-build --no-cache`, followed
  only by pinned absolute direct Lean `--setup`; no request path uses `lake env`, an Elan shim, a
  shell wrapper, or environment-selected toolchain.
- [ ] PAE-017 and PAE-027 use one exact exhaustive length-prefixed manifest byte grammar and input
  set; both descriptors and the Git executable each have one path/length/hash record and no raw-byte concatenation or reduced
  evaluation manifest exists.
- [ ] Startup pins exact Lean/Git descriptor/manifest/project/toolchain/Git identities and every phase
  re-attests root/Git canonical path/device/inode plus Git content/version output; the descriptor root
  is authority without a literal parent prefix.
- [ ] Mutable request files are exclusive regular link-count-one files under the request-root FD;
  read-only inputs are authorized only by manifest path/size/digest under a pinned root, never by an
  alias path.
- [ ] Compile-time generated code sees exactly five environment keys and no toolchain/parent/worker
  variable; real Docker proves the environment probe itself still Lean-verifies.
- [ ] Every setup/direct-Lean normal/failure/timeout/overflow/cancel/exception cleanup cell observes
  ordinary and escaped-session descendants, anchors five seconds at exact phase outcome, charges
  delay before cleanup entry, and proves absence before next phase/response/reuse; uncertainty stops
  the verifier rather than passing.
- [ ] Normal history load is strict/non-mutating; PAE-018 is the only migration entrypoint and its
  byte-exact backup/digests are verified.
- [ ] Semantic metrics use only an explicit independent pinned evaluator or closed zero-call
  unconfigured provenance; exact five-variable state, unequal credential binding/bytes, loopback-only
  HTTP, normalized inequality, and a distinct post-runtime request prevent same-call oracle reuse.
- [ ] A valid repair route always reaches another candidate, selector failure has exactly three
  truthful calls and no fallback route, and aggregate/checkpoint/status candidate evidence agrees.
- [ ] Only the isolated HTTP verifier produces the imported attestation after real compile/cleanup;
  Task 28 proves the worker has no verifier client/builder and accepts verification only from the
  exact authoritative persisted API resource.
- [ ] Every proof pipeline invocation is authorized by one API-owned generation claim; stale or
  conflicting workers stop before any later work, every spend is preceded by renewal/visibility and
  the exact 30-second stop margin, and explanation uses only refetched persisted Lean.
- [ ] Proof-worker activation/rollback proves blocked receipt, exact v1 queue/image/property binding,
  parent-authorized stop/drain/resume, old-worker explicit denial, and failure-closed intake.
- [ ] PAE-035 parent-corpus/LocalStack receipt validation, visibility/delete ambiguity, redelivery,
  and poison-retention tests pass without an Agent queue/DLQ resource implementation.
- [ ] PAE-036 parent-corpus mTLS HTTP/readiness/compiler/cleanup and three SecretBinary consumer-port
  tests pass without an Agent API reconciler, database, network, IAM, KMS, or secret implementation.
- [ ] PAE-037 exact entrypoint, property artifact/OCI label, commands/docs/artifacts, telemetry, and
  old-worker denial evidence passes; its image/toolchain/property bytes are the complete Agent-owned
  PRX-006 provenance contribution, and source/capability audits prove no provider observer, durable
  cutover/effect sink, or API persistence adapter exists.
- [ ] Public proof status is a closed privacy projection and exact diagnostics contain no metadata.
- [ ] Clarification input bytes and target identity are preserved before any terminal acknowledgement.
- [ ] History v2/v3 readers reject unknown/forged evidence and recompute deterministic status.
- [ ] Suite-v3 runtime input is clean, and missing judge/token/cost evidence is not-evaluated rather
  than pass/zero.
- [ ] Isolated Lean success after unchanged safety/formal-identity/exact-Draft preflight is proof
  authority; sketch adherence is post-runtime only and never vetoes verification or triggers repair.
- [ ] Live exit 0 is bound to a create-only completed current invocation, all immutable manifest
  cases, exact provenance/digests, and real runtime evidence; synthetic aggregates never authorize.
- [ ] The exact task-50 pytest argv is the sole `lean-explanation-ja-v1` release oracle and requires
  exit zero, one unskipped JUnit pass, actual pgvector, all eight fixed roles, repeated Repair,
  isolated Lean, durable artifact, Explain/Clarify, and one fresh strict private evidence object only
  after tasks 57 and 60.
- [ ] PEX-024 logical-line extraction preserves CRLF/LF/CR/U+0085/U+2028/U+2029 and mixed source
  slices without `splitlines`, joining, trimming, or normalization.
- [ ] Parent DEO-001–DEO-021 are the cross-repository authority. Agent owns only the exact
  completed-invocation projector, producer key/publication behavior, baseline, and independent
  grammar; Observability owns its parser/consumer fixture and vendor plan; DEO-021 alone owns the
  parent Make delegation surface.
- [ ] Parent DEO Task 36 proves exact GNU Make 0/2 delegation only. Historical PLS resource evidence
  is read-only and cannot authorize Unix/network-none verifier transport; current parent PRX and
  tasks 56–57 exclusively bind the private mTLS HTTP deployment boundary.
- [ ] PAE-030 maps every case exactly once and proves all integer/rounding/aggregate truth without
  filtering for the consumer object bound.
- [ ] PAE-031 uses exact material/HMAC framing, OS-CSPRNG provisioning, one `.local` shared registry
  inode, and `.dev`/`.prod` exact full ARN plus immutable VersionId with no fallback.
- [ ] PAE-032 publishes exact payload then sidecar bytes by ordered create-only no-replace commits,
  returns exact no-write replay or unchanged conflict, reports exact publication failure/committed
  state without consuming or accepting a pair, preserves canonical state, and makes no origin/truth
  claim.
- [ ] PAE-033 Task 73 records exact PFI/EXP/PJR/PWA/API PEX imports, the all-zero technical
  `IMPLEMENTATION READY` draft verdict as explicitly non-authoritative, then performs only the
  authorized status-only promotion and obtains ownership PASS. Current Task 64 completes the
  distinct fresh all-zero promoted-byte/import post-review while unchecked, then publishes only its
  inverse-proved single-token completion marker; retained
  Red-before-Green evidence, no shared runtime validator, a real-projector baseline, and the same
  parent vectors/cross gate remain required.
- [ ] PAE-034 has task-51 Red and task-52 Green evidence for OpenMath, authoritative top-8 pgvector,
  0..4 LLM rerank, zero-context Draft, exact graph, eight-role registry, and no fallback; task 50
  alone supplies real release success after tasks 57 and 60.

## Implementation Evidence: 2026-07-14

- Agent full gate: `398 passed / 2 environment skips`; Ruff and strict mypy pass.
- Live real-model x² run: `gpt-5.4-mini`, 12 repairs used, honest `failed`,
  `termination_reason=repair_budget_exhausted`; compiler diagnostics now reduce errors by 4 rather
  than being hidden by the sketch contract.
- Live verified-fixture explanation/clarification: 7 sections, 7/7 valid references, reference
  coverage `0.9534883720930233`, one completed section clarification with valid/overlapping Lean
  references. The proof fixture was reviewed and Lean-verified; it is not model-generation success.
- Evaluation history: schema v2 append-only JSONL, 5 runs / 2 cases currently. This establishes the
  comparison mechanism but is explicitly too small to claim broad proof-quality coverage.
- Semantic judge: prove and explanation scores `1.0` on the reviewed live fixture. Deterministic
  truth remains canonical when semantic evaluation is absent or fails.
