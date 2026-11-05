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

Optional, measured [Lake environment reuse](tools/lean_acceleration/README.md)
is disabled by default. It retains fresh compilation for every proof and keeps
Recipe admission on its receipt-bound compiler command.

## Production Worker Lanes

The production assessment service uses `Dockerfile.natural-production` and
`start-worker-with-credentials.sh`, which require `natural-only` capability.
The separate formal proof service uses `Dockerfile.full-production`:

```bash
docker build -f Dockerfile.full-production -t pals-agent-proof-worker .
```

Its launcher requires `PALS_ENV=prod`, `PALS_PROOF_CAPABILITY=full`,
`PALS_TOKEN_ACCOUNTING_ENABLED=true`, and an explicit `--lane proof` (the image
command supplies it). Set both `PALS_PROOF_JOBS_QUEUE_URL` and
`PALS_PROOF_REQUESTS_QUEUE_URL` to distinct queues; the `PALS_SQS_*` aliases are
also supported. The existing assessment service continues consuming its
dedicated queue. Both launchers scrub ambient AWS credentials and endpoint
overrides, pin the production region, and validate the same rotating worker
credential handoff before startup.

For a shared signed worker image, `Dockerfile.full-production` also includes
the unchanged natural-only launcher. Run the assessment service from that same
image with `PALS_PROOF_CAPABILITY=natural-only`, `PALS_ENV=prod`, token accounting
enabled, and both distinct queue URLs. Override its command with:

```bash
sh /app/scripts/start-worker-with-credentials.sh --lane assessment
```

The shared image defaults to the full proof service; each service must select
its own capability and command explicitly.

The full image supports direct generation followed by API-owned Lean
reconciliation. Provision its API worker secret, model provider configuration,
artifact bucket, credential/policy mounts, and token accounting, together with
the API reconciler and isolated verifier. It needs no Lean compiler in the
credentialed worker. An unconfigured PFI runtime retains direct generation;
this image supplies no Draft seed or PFI provenance. Enabling PFI requires the
existing provenance-verified seed/image build and a pinned runtime configuration,
not guessed provenance values.

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

Release roles are code-owned in `pals_agent/model_roles.py`. Lean Draft, Sketch,
Prove, and Repair use `gpt-6.1-terra` with medium reasoning. OpenMath, route selection,
retrieval ranking, explanations, and independent review use `gpt-6-luna` with low
reasoning. A user-selected Lean model remains selected throughout its retries;
explanations keep their separate cheaper model. Compiler failures do not switch
the selected model or reasoning effort, and there is no automatic Sol or Astra
fallback.

Configure the release client's credentials and bounded output budget:

```bash
OPENAI_API_KEY=sk-...
PALS_OPENAI_BASE_URL=https://api.openai.com/v1
PALS_OPENAI_MAX_OUTPUT_TOKENS=16384

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
code-owned `gpt-6-luna` default through `OPENAI_API_KEY` and
`PALS_OPENAI_BASE_URL`; there is no environment model selector for this role.
Release startup rejects provider/model override variables such as
`PALS_LLM_PROVIDER`, `PALS_OPENAI_MODEL`, and `OPENAI_MODEL`.

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
repository, corpus, normal runtime DTOs, logs, traces, metrics labels, or external workspaces.

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
formal statement. The verifier rejects code-executing Lean forms, `#` commands,
native evaluation and unlisted attributes and options before compiling. Because a
Lean command can exit the compiler with status 0, an accepted compile is not enough:
a separate process replays the compiled module through the kernel and allows only
the `propext`, `Classical.choice` and `Quot.sound` axioms. There is no deterministic
verified template fallback.

## Opt-in synthetic geometry domain

`pals-geometry` checks the explicitly structured
`isosceles-midpoint-perpendicular-v1` family: ABC is non-collinear, AB = AC,
and M is the midpoint of BC. It proves both line directions are nonzero and
orthogonal using Mathlib's perpendicular-bisector theorems. See
[testdata/synthetic-geometry-v1/isosceles-request.json](testdata/synthetic-geometry-v1/isosceles-request.json)
for the closed input schema.

```bash
pals-geometry testdata/synthetic-geometry-v1/isosceles-request.json \
  --lean-workspace "$PALS_GEOMETRY_LEAN_WORKSPACE"
```

The workspace must match the pinned Lean toolchain, complete Lake manifest,
and clean dependency source revisions. Supply `--lean`, `--lake`, `--elan-home`,
and `--child-path` for a local installation that differs from the verifier image.
The command runs the existing resource-limited verifier and a trusted fixed-source
transitive-axiom audit. Its JSON contains original input, exact source, ordered
step dependencies, source ranges and digests, toolchain identities, and axioms.
Only `propext`, `Classical.choice`, and `Quot.sound` are allowed.

The caller supplies the structured interpretation and its exact text spans.
This does not establish natural-language equivalence. Existing immutable OCR
snapshots and figure metadata are retained; OCR propositions require the existing
exact confirmation turn. Consequential ambiguity returns `needs_input` before
Lean runs. Drawing coordinates cannot supply hypotheses. Diagram payloads consume
the working `pals.diagram.v1` contract and remain `prepared_unrendered` until
rendered elsewhere; unsupported labels or inconsistent drawings report diagram
unavailability while retaining the checked proof.

This entry point is an opt-in domain tool. The existing worker, catalog admission,
semantic review, chat persistence and rendering flows keep their current contracts.
Operator-provisioned Lean executables and compiled dependencies remain trusted;
source/version checks do not attest compiled artifact provenance. Exit 0 means
this structured family was checked; exit 2 means clarification or verification
failure; malformed input, environment mismatch and audit errors exit 1.

## 品質イベントのworker配線

[PALS #217](https://github.com/AtsushiHosaka/pals/issues/217)のPQO-T003/T004に対応する作業仕様です。
本変更は`7f17c526`を基点に、mainの`e779314`から品質イベントの分類・EMF生成・運び方だけを移植します。
本番系統の診断ログと既存のworker処理は維持します。

要求の終端イベントは、DBのcommitを確定できるAPIだけが発行します。
workerは、settlementの成功応答、同じ応答の再送、`terminal`の再配信、`verifying`への引き渡しから終端イベントを出しません。
`quality_events.build_proof_request_terminal`はAPIとの互換性検査用に保持します。
APIのcommit後から発行前に停止すると欠測し得ます。永続outboxによる配信保証はありません。

隔離verifierは、proof-jobとRecipe admissionの各HTTP入口で、実際に呼んだcompileごとにLean試行を記録します。
成功、固定診断コードによる失敗、例外による`unclassified`を区別します。
compile前のbusy応答は試行に数えません。ソース、コンパイラ本文、パス、job ID、admission IDはEMFに含めません。

継続実行するCLIの各consumerは、起動時と300秒ごとに`WorkerHeartbeat=1`を発行します。
in-flight処理中も発行し、終了・drain・例外時にheartbeatのthreadを止めます。
複数processのsupervisorと`worker-once`は発行しません。
heartbeatのdimensionは`Environment`だけです。workerやhostの識別子は送りません。

既定では無効です。無効時にはtransportもheartbeat threadも作りません。
有効にする場合は、以下を運用側で設定します。本変更は本番の設定や権限を変更しません。

| 環境変数 | 値・用途 |
| --- | --- |
| `PALS_QUALITY_EVENTS_ENABLED` | `true`または`1`で有効化 |
| `PALS_QUALITY_EVENTS_ENVIRONMENT` | `prod`、`staging`、`dev`、`local`、`probe`。未指定時は`PALS_ENV` |
| `PALS_QUALITY_EVENTS_TRANSPORT` | `agent`または`file` |
| `PALS_QUALITY_EVENTS_AGENT_ENDPOINT` | agent用の`udp://数値IP:port`。privateまたはloopbackの宛先だけを許可 |
| `PALS_QUALITY_EVENTS_FILE` | file用の正規絶対パス。事前に作成した所有者本人の0600通常ファイルだけを許可 |
| `PALS_QUALITY_EVENTS_REVISION` | 任意のsoftware revision。dimensionには使わない |

発行時の例外は主処理へ返さず、`QualityEventsDropped`を次に送れるイベントに付けます。
UDPは送信先からの受領確認を取りません。ファイルへの書き込み時間にも保証はありません。
UDP送信ではDNSを使わず、送信ごとにsocketを閉じます。URLの認証情報・path・query・fragmentは拒否します。
ファイルは新規作成せず、symlink、複数hardlink、FIFO、別所有者、0600以外の権限を拒否します。
特殊ファイルへのopenはnonblockingです。collectorによるrotation後も、正規パスと同じ条件を満たすファイルが必要です。
本番で有効にする前に、collectorの構成とEMF抽出を別途確認する必要があります。
説明のvalidationラベルは既存の固定コードと`reference_header`に限定し、未知の短い値は`unrecognized`に置き換えます。
本文や秘密らしい値は、置き換える前にイベントごと拒否します。説明の生成・審査条件は変えません。
reviewのラベルは既存の3分類と`none`、providerのラベルは既存の`openai_diagnostics`の固定語彙とHTTP status 100〜599に限定します。

説明とclarificationの生成では、生成・審査の再試行を使い切った場合、期限切れ、既存APIの参照一致検査で拒否された場合に、最終catchから`ExplanationsFailed=1`を発行します。
生成の途中失敗から回復した場合、審査の指摘を直して成功した場合、既terminalの再配信では発行しません。
この値は生成試行の最終失敗数です。失敗状態をAPIに書き込む前に発行するため、DBの終端数とは分けて扱います。
書き込み結果が不確実なまま再配信され、もう一度生成して失敗した場合は別の試行として数えます。永続的な重複排除はありません。
既存のログ本文、利用者向けの失敗理由、APIへの書き込みとackの条件は維持します。

版付きのwire契約は[`quality-event-v1.schema.json`](pals_agent/contracts/quality-event-v1.schema.json)です。
JSON Schema Draft 2020-12を使い、`$id`は`urn:pals:quality-event:1`です。イベントのpayloadに新しい版フィールドは加えていません。
rootとEMF metadataの許可項目、dimension、固定ラベル、metricとunitの対応、各参照先がrootにあることを検査します。
`quality_event_json_schema()`から生成した内容と、保存したSchemaの一致も検査します。
時刻の鮮度、8192 UTF-8 bytesの上限、分類の選択、directiveをまたぐmetric名の重複は、emitter側の検査です。
Schema単体から配信やCloudWatch抽出の成功は判断できません。
標準の`jsonschema` validatorは開発依存だけに加え、本番のemitterは読み込みません。

```bash
python -m pytest tests/unit/test_quality_event_schema.py tests/unit/test_worker_explanation_quality_events.py
```

回帰試験はEMFの実ファイル書き込みとループバックUDP/mTLS通信を含みます。
API、SQS、モデル、Leanコンパイラはテストで明示したfixtureの境界です。
2026年11月5日のPython 3.12による検査では、Schema、品質イベント、説明hook、claim、deadline、grounding、CLI、worker、HTTPを含む最終回帰440件が通りました。
独立レビュー後のtransport修正には、実FIFO・リンク・所有者・権限の拒否と、実UDPのsocket解放を含みます。
先行するworker、drain、Lean境界、API trust、runtime latencyを含む回帰484件も通過しています。
Ruff、品質イベントとHTTP serverのmypy、`git diff --check`は通過しています。
この試験結果は、本番DBのcommit、実モデルの精度、実Leanのcompile、CloudWatchの抽出成功を示しません。
この差分はPQO-T003のSchema欠落と説明失敗hookを補います。本番での有効化、collector設定、EMF抽出、アラーム、台帳からの評価イベント発行は別作業です。

## License

Apache License 2.0.
