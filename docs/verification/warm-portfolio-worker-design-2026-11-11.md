# 常駐ポートフォリオワーカー設計メモ(2026-11-11)

状態: 設計案。コードは変更していない。[確認]=コードで確認、[推測]=コードにない推論。

## 1. 現行の本番検証器(確認)

- 1リクエストにつき新しいLeanプロセス。常駐はしない。`lean.py:339-385` で `TemporaryDirectory` を作り、`lake env lean --threads=1 Main.lean` を起動する(`lean.py:614-621`)。
- Mathlibは毎回 `.olean` から読み込む。`PALS_LEAN_REUSE_LAKE_ENVIRONMENT=true` で効くのは `lake env` の環境変数の再利用だけ(`lean_environment.py` の `LakeEnvironmentCache`、鍵は設定ファイルとバイナリのハッシュ)。Leanの import 結果は再利用しない。
- `PALS_LEAN_IMPORT_PLAN` は import を絞って読み込みを軽くする(`lean_import_plan.py`)。失敗時は元の import で1回だけ再試行する。
- 隔離は3層。
  - `prlimit`(CPU=タイムアウト+1秒、AS=16GiB、FSIZE=16MiB、NPROC=4096、NOFILE=1024、CORE=0。`lean.py:764-801`)。
  - `lean_child.py` が rlimit を再適用し、Landlock で読み取り専用の実行環境(toolchain、workspace、lib)と scratch だけを許可、seccomp で socket 系と kill 系を遮断し、`fcntl` の F_SETOWN 等も遮断する(`lean_child.py:112-139, 282-429`)。
  - `lean_supervisor.py` が subreaper として働き、期限かSIGTERMで子孫を全員 SIGKILL し、結果を専用 pipe で返す。死ねば「中断」で、判定にはしない(`lean_supervisor.py:27-59`)。
- scratch は `/run/pals-verifier-requests/pals-lean-*`(64MiB 以下の tmpfs、0700、非root)。起動時に境界を検査する: ネットワークは lo のみ、root と workspace は読み取り専用、memory と pids の cgroup 制限あり(`boundary.py:53-92, 215-262`)。
- 認証は mTLS 1.3。クライアント証明書の SPKI ハッシュと SPIFFE URI を照合する(`http_server.py:285-307`)。さらにリリース束縛ヘッダを照合する。
- エンドポイントは `POST /v1/verify`(`proof_job_id`、`lean_code`、`result_artifact_uri`)と `POST /v1/recipe-admissions/verify`。
- 同時実行は `BoundedSemaphore`(既定1、上限2)で、満杯なら待たせず 503 を返す(`http_server.py:57, 224, 412-414`)。
- 入力検査の順序(`lean.py:224-277`):
  1. `sorry`、`admit`、`sorryAx`
  2. `axiom`、`constant`、`opaque`、`unsafe`
  3. `lean_source_policy`: native_decide 系、メタプログラミング(`elab`、`macro`、`run_cmd`、`IO` 等)、`#` コマンド、`eval%`、許可外の attribute と option、`include_str`
  4. プロファイルの import 検査
- `set_option maxHeartbeats` は許可リストにある(`lean_source_policy.py:105-115`)。値は制限されない。[確認] 実際の上限は wall 時間と CPU rlimit だけ。
- 事後監査(`lean_audit.py` の `TRUSTED_AUDIT_SOURCE`)は別プロセスで次を行う。
  1. `.olean` を読む。
  2. `env.replay` でカーネル再検査する。
  3. `collectAxioms` で公理を集め、許可は propext、Classical.choice、Quot.sound のみ。
  4. 文面と statement を突き合わせる。
  nonce は候補の実行後に作る。この監査には本番側で1回の追加起動が要る。
- 受領証: 成功時の応答は `lean_sha256`、`proof_job_id`、`verification_succeeded`。admission は `toolchain_fingerprint` と正規化 command の SHA を束縛する(`http_server.py:84-134, 923`)。

## 2. 常駐ワーカーは何を壊すか(確認)

試作の `scripts/eval/warm_worker.lean` と `automation_portfolio.py:366` の `WarmWorker` は、この性質を満たさない。
- sandbox、rlimit、supervisor、source policy、監査、認証がない(自ら docstring で明記)。
- 1リクエストの暴走が worker 全体を巻き込む。タイムアウトは `kill()` のみ。
- `.olean` を出力しないので、現行の事後監査(olean 再生)が使えない。
- 現行の「プロセス=リクエスト」前提のコードがある: `lean_child.py` は起動時に Landlock を1回かけて exec する。リクエスト固有の scratch を後から許可できない([推測] 常駐化は scratch を固定の worker 専用 dir にする設計が必要)。
- `lake env` 抜きで `LEAN_PATH` を直接渡している(試作)。本番は Landlock が workspace と LEAN_PATH の整合を検査する(`lean_child.py:219-227`)。

## 3. 維持する性質

- 同一: source policy(`find_source_violation`、`_PLACEHOLDER_RE`、`_TRUSTED_DECLARATION_RE`)、公理許可リスト、statement 照合、mTLS、リリース束縛、503 で待たせない動作、「中断は判定にしない」。
- worker 起動時に1回だけ: Landlock(読み取り専用の toolchain、workspace、worker 専用 scratch のみ書き込み)、seccomp、rlimit(AS、NOFILE、NPROC、CORE=0)、subreaper。
- worker の CPU rlimit は「累積」なので使えない([推測])。リクエストごとの上限は supervisor が wall 時間で SIGKILL する形にする。FSIZE は維持する。

## 4. リクエスト単位の設計案(推測)

- 1 worker = 同時に1リクエスト。プールは `PALS_LEAN_MAX_CONCURRENT_COMPILES` と同じ枠(既定1、上限2)に載せる。上限を上げるなら先に `MAX_CONCURRENT_COMPILES` と cgroup の memory を見直す。
- 各リクエストは `Command.mkState env`(不変の import 済み環境)から始める。環境は共有でも、`IO.processCommands` の状態はリクエストごとに新規。
- リクエストごとに wall 時間と heartbeat を設定する。`set_option maxHeartbeats` はリクエスト側で変えられるので、`maxHeartbeats` の上限は worker 側で再度被せる(または全体を `withHeartbeats` で包む)。
- 判定: 各 declaration の `#print axioms` に `sorryAx` がない、かつ message に `error` がない、かつ `declaration uses 'sorry'` がない。
  - ハートビート超過では、error が出たのに宣言が `sorryAx` を持たない場合がある。error があれば必ず不採用にする(拒否権を維持)。`WarmWorker.check` の戻り値は message 文字列だけなので、重大度を構造化して返す必要がある。
- exact? は索引を作り約6コアを使うので専用 worker に分け、`--threads=1` 相当の枠に収めない。[推測] 通常プールに混ぜると他リクエストの wall 時間を悪化させる。

## 5. kill と再起動

- 最大 wall 時間、output 上限、heartbeat 超過、応答なし、supervisor 側の cgroup 圧迫のいずれかで worker ごと SIGKILL して再起動する。プロセスツリーは `lean_supervisor.py` の方式を流用する。
- 再起動コストは Mathlib の import 一回分。[推測] 「中断」として 503 を返し、判定にはしない。
- 回収方針(推測): N リクエスト後、または RSS が閾値を超えたら、リクエストの境界で再起動する。N と RSS の値は実測してから決める。RSS は `/proc/<pid>/statm` で読む。

## 6. 変更が必要な箇所と所有者

git log の著者は全ファイルで Atsushi Hosaka のみ、`CODEOWNERS` は無い。以下の「所有者」はブランチ/作業者で、リードの指示によるもの。

| ファイル | 変更 | 所有者 |
|---|---|---|
| `pals_agent/lean_verifier/http_server.py` | `/v1/verify` の `verifier.verify` を worker プール経由に。503 経路を維持 | 別作業者(リード指示) |
| `pals_agent/lean_verifier/http_runtime.py` | プール設定(`PALS_*` フラグ、既定 off)、起動時の warm | 同ディレクトリのため要確認 |
| `pals_agent/lean_verifier/boundary.py` | 常駐 worker 用の cgroup と scratch 検査 | 同上 |
| `pals_agent/lean.py` | `_verify` 内で worker 経路に分岐。`prlimit` と事後監査の呼び出し | 本作業ツリー(要調整) |
| `pals_agent/lean_child.py` / `lean_supervisor.py` | worker 起動用の変種(Landlock 1回、リクエスト単位 kill) | 同上 |
| `pals_agent/lean_audit.py` | olean を作らない場合の監査経路 | 同上 |
| `scripts/eval/warm_worker.lean` | 構造化出力(severity、axioms)、wall と heartbeat、1リクエストの状態分離 | 本作業ツリー |
| `pals_agent/automation_portfolio.py` | `WarmWorker` を検証器クライアントに差し替え | 本作業ツリー |

## 7. 未確認事項

- 本番の memory cgroup 値、`MAX_CONCURRENT_COMPILES` の実運用値は、コードの既定のみ確認(AWS 側 Terraform は未参照)。
- 事後監査を常駐 worker でどう維持するか(olean を出す、またはメモリ上で `Environment` を直接再生するか)は未決。後者はカーネル再検査の独立性が弱まる。
- 常駐 worker の効果(秒数、RSS 増加率)は未測定。測定してから採否を決める。
