# pals-agent

Public OSS LangGraph agent toolkit for PALS.

`pals-agent` contains the proof-generation agent, tool interfaces, and Lean
verification runtime used by PALS. The repository is designed to work without
private PALS infrastructure. It may include public/local integration adapters
for the documented proof-job worker protocol; deployment-specific endpoints,
credentials, and production prompts must live outside this public boundary.

## Scope

- LangGraph proof-generation workflow
- Lean compile tool interface
- Lean verifier runtime and diagnostics parser
- Provider adapters for local and hosted LLMs
- Evaluation fixtures that are safe to publish
- Local SQS worker, public proof-job protocol adapter, and benchmark runner for
  `.local` development

## Repository Boundaries

This repository must not contain:

- API keys or provider credentials
- private or production PALS API endpoint values
- AWS account IDs or production configuration
- private prompts or private datasets
- files under `.claude/`, `.codex/`, or `.env.*`

Lean verification code lives here because it is a first-class agent tool. The
credentialed worker does not contain Lean, Lake, Elan, or a local compiler
fallback. All untrusted Lean executes in the dedicated verifier image.

## Isolated Lean Verifier

Build the separate verifier and worker images:

```bash
docker build -f docker/lean-verifier.Dockerfile -t pals-lean-verifier .
docker build -t pals-agent-worker .
```

The verifier accepts only private TLS 1.3 mTLS requests on port `18117`. It has
no Unix socket, plaintext listener, or Worker client. The API-owned verified
reconciler is its only application caller. The Worker submits a persisted
candidate, then reads the API's authoritative `verified` or failed result.

Verifier startup consumes only Infra-published full-ARN plus immutable-VersionId
SecretBinary references for its server certificate, private key, and CA. It
starts fail-closed when trust, resource, filesystem, process-boundary, or
toolchain checks fail. The compiler receives no Worker, API, model, database,
or cloud credential.

## Local Worker

The worker is API-reconciliation-first:

- reads proof job ids from LocalStack SQS,
- fetches job input from the PALS API,
- asks the configured LLM provider for a Lean attempt,
- rejects `sorry` / `admit`,
- submits the generated candidate to the API under its claim,
- reads verifier diagnostics only after API-owned reconciliation,
- asks the configured LLM provider whether repair should resume from draft,
  sketch, or prove,
- stores generated code, model output, diagnostics, timings, and artifacts.

Provider selection is controlled by environment variables:

```bash
# Default local mode
PALS_LLM_PROVIDER=ollama
OLLAMA_PROVE_MODEL=qwen2.5:3b

# OpenAI mode
PALS_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
PALS_OPENAI_MODEL=gpt-5.4-nano
PALS_OPENAI_BASE_URL=https://api.openai.com/v1
PALS_OPENAI_MAX_OUTPUT_TOKENS=12000

# Bounded Lean diagnostic repair loop
PALS_MAX_REPAIR_ATTEMPTS=12

# API-only Proof Flow Index retrieval
PALS_API_BASE_URL=http://localhost:8000
PALS_WORKER_SHARED_SECRET=...
OPENAI_API_KEY=sk-...
PALS_DRAFT_EMBEDDING_DIM=384
```

Each failed repairable candidate is checkpointed before another LLM-selected
`draft`, `sketch`, or `prove` route. Route selection makes at most three real
calls and never invents a fallback route. The default budget permits twelve
repair generations after the initial candidate.

## Verified Worker Updates

For `state=verified`, the worker sends nonblank Lean and result artifact URI
plus this exact evidence object:

```json
{
  "schema_version": "pals.verifier-attestation.v1",
  "proof_job_id": "<proof job id>",
  "lean_sha256": "<lowercase SHA-256 of the exact Lean UTF-8 bytes>",
  "result_artifact_uri": "<the same URI as the update>",
  "verification_succeeded": true
}
```

The API client validates all five keys, types, identities, and values before
HTTP. Intermediate, failed, and canceled wire payloads omit
`verifier_attestation`; supplying one for those states fails before transport.

## Semantic Evaluation

Deterministic evaluation remains canonical. A live semantic judge is optional
and has no generation-model fallback. Configure all four variables or none:

```bash
PALS_SEMANTIC_EVALUATOR_PROVIDER=openai
PALS_SEMANTIC_EVALUATOR_MODEL=gpt-evaluator-2026-07
PALS_SEMANTIC_EVALUATOR_REVISION=deploy:sha256-abc
PALS_SEMANTIC_EVALUATOR_BASE_URL=https://evaluator.example/v1
```

`PALS_SEMANTIC_EVALUATOR_PROVIDER` is exactly `openai` or `ollama`. Model and
revision are pinned ASCII identity tokens. The base URL must be absolute HTTP(S)
without userinfo, query, or fragment. The evaluator provider/model must differ
from the active generation provider/model. OpenAI evaluation uses the existing
OpenAI credential only for transport; evaluator endpoint, credential, prompts,
outputs, and errors are not persisted. With all four variables absent,
`--semantic-judge` makes zero judge calls and records explicit
`not_evaluated` metrics with unconfigured provenance.

## Evaluation History Migration

Ordinary `evaluation-history` loading is strict and never edits, skips, or
quarantines a malformed record automatically. The only legacy schema-v2 repair
is the explicit, source-digest-pinned operation:

```bash
.venv/bin/python -m pals_agent.cli evaluation-history-migrate \
  --migration semantic-comments-v2 \
  --history .pals-agent-artifacts/evaluations/history.jsonl \
  --expected-sha256 b32d19c0a6f66b5140c37d161d83bf291a1fa969a82b5e59d5bcdc07c43879fa
```

It creates an immutable mode-`0600`, digest-named byte-exact backup, changes
only legacy non-null semantic comments to null, validates all records, and uses
file and directory fsync around atomic replacement. Its JSON report contains
digests/counts, not comment content. A wrong digest, unrelated invalidity,
backup mismatch, or migration/recovery fence fails closed. On any extant fence,
stop writers and inspect the source, backup, and fence; startup/load never
restores or migrates automatically. Application rollback retains the migrated
history and its source backup.

The packaged seed catalog is only signed-worker build input. Runtime Draft
retrieval validates and alpha-canonicalizes the query, embeds it once, and sends
one vector/fingerprint-only request to the worker-authenticated API private port.
The Agent has no direct storage driver, credential, configuration, migration, or
fallback catalog. Before retrieval, the OpenMath structuring role uses the
code-owned `gpt-5.4` default through `OPENAI_API_KEY` and
`PALS_OPENAI_BASE_URL`; there is no environment model selector for this role.
Draft, sketch, prove, and repair keep their existing provider/model routing.

The packaged bootstrap catalog currently contains 31 Drafts. Thirty are
continuity examples spanning direct Lipschitz estimates, closure constructions,
powers and polynomials, absolute-value compositions, and rational functions with
positive denominators. Each record stores only an id, a human-readable theorem statement, a
theorem-level OpenMath proposition, a proof strategy, and ordered Sketch steps. Lean
targets, OMDoc wrappers, aliases, status labels, and unconnected quality counters are
not Draft data. A request such as "prove continuity
by epsilon-delta" is structured as a continuity proposition; the proof-method phrase
is consumed by Draft/Sketch/Prove and is never expanded into the retrieval proposition.
Real coefficient membership and real-valued function image constraints are encoded in
OpenMath rather than inferred from display text.

The standard OpenMath dictionaries cover arithmetic, logic, sets, functions,
and quantifiers. PALS-specific topology and linear-algebra symbols are defined
in the packaged `pals_agent/content_dictionaries/pals1.ocd` Content Dictionary.
OpenMath symbol identity includes `cdbase`, `cd`, and `name`; `pals1` uses the
versioned base `urn:pals:openmath:cd:v1`. The validator accepts only the
documented profile and checks each symbol's construction role and arity.
Unknown external Content Dictionaries are rejected as well; every OMS must resolve to
an explicitly supported `(cdbase, cd, name)` identity. Packaged seeds run through the
same natural-language/OpenMath semantic validator used for runtime structuring.

The API returns at most eight ordered active-snapshot candidates. Agent computes
vector and structural evidence without selecting, filtering, or reordering them,
then sends one strict-schema request to the pinned Draft reranker. The reranker
selects zero through four candidate IDs; zero is a typed no-match. The embedding
fingerprint includes provider, model, endpoint, deployment identity, immutable
revision, dimension, and canonicalizer version. Any compatibility or transport
failure closes the retrieval path without a fallback.

The Agent creates the signed-worker seed input and then builds the worker image;
API release tooling owns catalog publication and the private candidate port:

```bash
cd pals-agent && .venv/bin/python -m pals_agent.cli build-pfi-worker-image \
  --source-commit <40-lowercase-hex> --tag pals-agent-worker
```

The command first reads `ElementTree.py` from the same `python:3.12.13-slim`
container used by the final image. It then generates `build/proof-flow-index/`,
passes the generated provenance labels to Docker, and rejects the image unless its
labels, packaged seed hash, and in-image `ElementTree.py` path/hash all match. The
seed directory must not exist before the command starts. The command removes that
command-owned generated directory after either success or failure.

### PFI manual release evidence

The cost-bearing release evaluation is manual and is not part of normal proof
jobs. `load_governed_release_corpus` accepts only the byte-exact approved
six-query corpus. `ProofFlowIndexReleaseEvaluator` checks the admitted API
generation, manifest, eligible count, runtime provenance, fingerprint, exact
canonical OpenMath, and all eight candidate IDs before each paid call. It then
makes one strict reranker call per query, requires the exact ordered selection
and aggregate metrics, and verifies that the external store contains exactly
one record for every governed query. A partial prior run blocks the next run
before any provider call.

The reranker parser accepts only the exact content-free token-usage object.
`DraftRerankerReleaseEvidenceWriter` uses only the embedded
`openai-gpt-5.4-mini-2026-07-27` USD price snapshot and integer rational
arithmetic; it does not read a provider dashboard or use floating point.

Release tooling must supply the admitted publication witness and a production
external evidence-store adapter. Before the first paid call, the adapter must
prove TLS, at-rest encryption, active exact retention/deletion scheduling, no
overdue record, no incomplete prior corpus run, immutability through expiry, no
dataset replication, and exactly these readable roles:
`pals_release_operator` and `pals_release_auditor`. Each record is content-free
and carries the exact expiry of 15,552,000 seconds after observation and a
deletion deadline 86,400 seconds later. Any absent control, mismatched receipt,
incomplete run, or overdue retained record blocks the release. Never put these records, provider
envelopes, prompts, IDs outside the governed inventory, or token usage in the
repository, corpus, normal runtime DTOs, logs, traces, metrics labels, or Notion.

Run the test gate:

```bash
make agent-test
```

From the parent repository, run the honest model-attempt benchmark:

```bash
make agent-benchmark
```

This exits non-zero when the local model attempt fails. To produce verified
benchmark artifacts, the model-generated Lean itself must satisfy the hidden
benchmark target and proof-method requirements, pass safety validation, and pass
Lean verification. Hidden targets are evaluator-only and are never included in
generation prompts. For normal jobs, a catalog Draft is context rather than a
trusted harness; semantic verification requires an independently supplied user
formal statement. The verifier also rejects disallowed Lean metaprogramming and
interactive commands such as `run_cmd` and `#check` as defense in depth. There
is no deterministic verified template fallback.

## License

Apache License 2.0.
