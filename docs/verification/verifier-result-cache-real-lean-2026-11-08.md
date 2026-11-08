# verifier結果キャッシュの実Lean検証

2026-11-08。ブランチ `claude/seq27-verifier-cache-shadow`。生データは `tools/verifier_cache_real_lean_results.json`、再現は `uv run --extra dev python tools/verifier_cache_real_lean.py --out <json>`(約11分)。オプトインのpytestは `tests/unit/test_verifier_result_cache_real_lean.py`(固定のLeanとMathlibが無ければskip。約2分)。

## 1. 何を実際に動かしたか

| 項目 | 実物か |
|---|---|
| HTTPサーバー(TLS1.3 mTLS、`create_server`) | 実物。同一プロセス内、単体テストと同じ証明書とヘッダー |
| 結果キャッシュ(`build_result_cache`、許可リスト52件) | 実物 |
| `LeanVerifier`(ソース方針、コメント除去、`--threads=1` のコンパイル、コンパイル済みmoduleの公理監査、診断の解釈、supervisor、期限) | 実物。本番コードのまま |
| Lean | 固定の `v4.32.0-rc1`(arm64 macOS)を直接実行。`import Mathlib` は構築済みMathlibの `LEAN_PATH` で解決 |
| Mathlib | OrbStack volumeの読み取り専用パッケージ。変更・削除はしていない |

**`lake` は一度も実行していない。** `LeanVerifier` は `project_dir=None` で作ると `lean` を直接実行するが、子プロセスの環境に `LEAN_PATH` を渡す口が無い。そこでツール内だけで `pals_agent.lean._run_limited_process` を包み、`LEAN_PATH` を足した(`tools/verifier_cache_real_lean.py` の `RealLeanAdapter`)。本番コードは変えていない。

## 2. 結果(要約)

28項目の確認はすべて通った。

| 場面 | 期待 | 結果 |
|---|---|---|
| A shadowのみ(SHADOW=true、ENABLED=false)。許可リスト4本を各4回 | 応答は変わらず(200、ヘッダー `compile`)。1回目は `stored`、2回目以降は `shadow_match` | 一致。16回すべて200/`compile`/Lean 1回。`stored`=4、`shadow_match`=12、mismatch 0 |
| B 配信(ENABLED=true)。許可リスト4本 | 1回目 `compile`、2回目以降 `cache` でLeanを呼ばない | 一致。ヒット32回、アダプターの呼び出し増加は0。最遅ヒット約2msに対し最速コンパイル17.9s |
| B 許可リスト外(末尾にコメント1行) | 毎回 `compile`、`cache` にならない | 一致。2回ともコンパイル(`ineligible`) |
| B 失敗する本文 | 保存せず、通常の422 | 一致。誤った補題(Leanが拒否、約8.5s)と `sorry`(ソース方針が拒否、Leanは起動しない)は毎回422/`compile` |
| B2 許可リスト内でLeanが拒否する本文 | 保存・配信しない | 一致。`failure_not_stored`=2、エントリ0、毎回コンパイル |
| C タイムアウト(10ms) | 504、`shadow_inconclusive`(WARNING)、`shadow_mismatch` ではない、配信を止めない | 一致。保存済みの本文は `shadow_inconclusive`、未保存は `inconclusive_not_stored`。直後の通常要求は200(`shadow_match` / `stored`)。SERVEでもタイムアウト後に保存し、次の要求が `cache` |
| D 不一致 | ERRORに `shadow_mismatch`、以後は配信しない | 一致。下記 |

D の内訳:

- D1(実Leanの拒否): 保存済みの本文について、Mathlibを `LEAN_PATH` から外して実Leanに `import Mathlib` を拒否させた。422/`compile`、`ERROR: result=shadow_mismatch`、カウンタ1、`serving_blocked=true`。その後の通常要求は200/`compile`で、ブロックは残る。
- D2(ENABLEDで配信を止める): SERVEキャッシュに、保存済みの成功と、その後の実Leanの拒否を同じキーに入れた(単体テストと同じ重なり要求の再現)。以後、同じ本文と別の本文のどちらも `compile`(`blocked_by_mismatch`=3)で、`cache` は1回も返らなかった。

## 3. 時間

計測は単調時計。1要求ごとに新しいTLS接続を張る。コンパイル時間はコンパイル本体と監査の2回のLean実行を含む。

| 変数 | 初回コンパイル s | 反復コンパイル s(最小 / 中央 / 最大、n=3) | キャッシュヒット ms |
|---|---|---|---|
| x(プロセス内で最初) | 21.49 | 17.42 / 17.74 / 20.04 | 全体で p50 1.3、p95 1.6、最大 1.9(n=32) |
| t | 17.50 | 17.78 / 18.50 / 20.27 | 〃 |
| y | 18.23 | 17.98 / 18.23 / 20.23 | 〃 |
| s | 18.37 | 17.93 / 18.22 / 20.51 | 〃 |

- 比較用に、同じ接続方式の `GET /ready`(Leanもキャッシュも通らない)は p50 1.24 ms、p95 1.35 ms、最大 1.59 ms(n=20)。ヒットはほぼ通信とTLSの時間だけである。
- 周辺の時間: 誤った補題の拒否 約8.5 s、10msタイムアウトの504 約42 ms、`sorry` の拒否 約2 ms。
- 許可リスト52件のうち4本だけを測った。ヒットは4本合算で、本文ごとの差は見ていない。

**coldについて正直に書く。** OSのページキャッシュはsudoなしでは落とせない。本測定の「初回」は「このプロセスでの最初のコンパイル」であり、直前の試験実行でMathlibのoleanがOSのキャッシュに載っていた。そのため初回と反復の差はほぼ無い(xの初回 21.5 s が最大だが、反復の最大も 20 s 台)。OSが再起動直後でoleanを読み直す真のcold時間は測れていない。

## 4. このアダプターが本番verifierと違う点(検証していないこと)

- Linuxの隔離。landlock、seccomp、`prlimit`、cgroupのメモリ・PID上限と圧迫の検知、subreaperは動いていない(macOSのため)。`_cgroup_pressure()` は常に0で、「cgroup圧迫による中断(`verifier_compile_interrupted` 系)」の経路は通っていない。中断はキャッシュ上はタイムアウトと同じ `inconclusive` で扱うが、実際の発火は確かめていない。
- `lake env`。本番の `LeanVerifier` は `project_dir` を持ち `lake env lean` で実行する。ここでは `lean` を直接実行した。`reuse_lake_environment` も使っていない。Lakeの環境の差でコンパイル結果が変わることは、この検証では見えない。
- Mathlibの版。OrbStackのvolumeのパッケージが、リポジトリの `lake-manifest.json` の固定版と一致するかは確かめていない(既存の `test_recipe_elaboration_lean.py` と同じ前提)。
- コンテナ、イメージ、cgroup、実際のTLS証明書の管理(`tls_material.py`)、`http_runtime` の環境変数の読み取り。フラグは `result_cache_mode(shadow=…, enabled=…)` を直接呼んだ。環境変数から解釈する経路は単体テストでのみ確認済みである。
- キーの成分のうち、toolchain digestとimage digestは固定のダミー値。Leanバージョン、`lean-toolchain` と `lake-manifest.json` のhashはリポジトリの実ファイル。
- タイムアウト値。ここでは通常300 s、タイムアウト試験で10 ms。本番の設定値は読んでいない。
- 同時要求は1件のみ(`max_concurrent_compiles=1`、クライアントは直列)。複数の同時コンパイルと負荷は見ていない。
- Recipe admission用のエンドポイント(`/v1/recipe-admissions/verify`)は通していない(キャッシュの対象外)。
- 許可リスト52件のうち4本。残り48本が実Leanで通るかは確かめていない。

## 5. 気づいたこと

- 本番コードの不具合は見つからなかった。本番コードは変更していない。
- SERVEモードでは、保存済みの本文はコンパイルされないため、同じ本文での不一致は構造的に観測できない(重なり要求の競合を除く)。不一致を見つけられるのはshadow期間だけである。設計どおりの動きだが、ENABLEDに切り替えた後は新たな不一致検知が弱くなる。切り替え後も保存済み本文を定期的に再検証するなら、設計にある背景再検証が必要になる。
- ブロック中(`serving_blocked=true`)も、新しい成功の保存と `shadow_match` の記録は続く。配信だけが止まる。意図どおりである。
- 1回のコンパイル約18 sは、コンパイル本体と公理監査の2回のLean実行を含む。内訳は取っていない(`timing_observer` は使っていない)。キャッシュヒットは両方を省く。

## 6. 背景再検証の実Lean検証(ブランチ `claude/seq27-verifier-cache-revalidate`)

2026-11-08。生データは `tools/verifier_cache_real_lean_revalidation_results.json`、再現は `uv run --extra dev python tools/verifier_cache_real_lean.py --scenarios E --out <json>`(約90秒)。オプトインのpytestは `tests/unit/test_verifier_result_cache_real_lean.py` の末尾2件(4件で約130秒、うち再検証の2件が約50秒)。第1〜5節と同じ前提(`lake` なし、固定Leanを直接実行、同時に動くLeanは1本、Mathlibは読み取りだけ)で、ENABLED+REVALIDATE、EVERY=2。再検証用のverifierは、本番と同じく期限60秒の `LeanVerifier` である。10項目の確認はすべて通った。

| 場面 | 結果 |
|---|---|
| E1 最初の要求(変数 x) | コンパイル 21.8 s(200、`compile`)、保存 |
| E1 最初のヒット | 2.6 ms(200、`cache`)。応答の後ろで実際のLeanによる再検証が開始(`revalidation_started`) |
| E1 再検証の最中のヒット3件 | 3.3 / 1.6 / 1.4 ms。Lean呼び出し0。EVERY=2 の周期で期限が来た2件は `revalidation_skipped_busy`(待たない、積まない) |
| E1 再検証の最中に、キャッシュに無い要求(許可リスト外) | 1.4 ms で503 `verifier_unavailable`(枠1本が再検証に使われているため。想定どおりの影響) |
| E1 再検証の結果 | 実Leanのコンパイル 18.0 s で成功。`revalidation_match`=1、mismatch 0、inconclusive 0 |
| E1 一致の後 | 配信は続く(`cache`)。周期で2回目の再検証が走り、これも `match`(合計 started=2、match=2) |
| E2 改ざん(許可リストに、実Leanが拒否する本文だけを入れ、保存済みの判定をプロセス内で「成功」に書き換え。テスト専用) | 改ざんされた成功が `cache` で配信される(2.6 ms、Lean呼び出し0)。直後の背景再検証で実Leanが拒否(9.2 s)し、`revalidation_mismatch`=1、ERROR、`serving_blocked`=true |
| E2 不一致の後 | 同じ本文の次の2要求は実際にコンパイルされ、422/`compile`(それぞれ 11.1 s、8.4 s)。`blocked_by_mismatch`=2。保存済み判定との食い違いは既存の `shadow_mismatch` としてもERRORで数えられる(2件) |

読み方

- ヒットの遅延は、再検証が走っていても数ミリ秒である(再検証なしのヒットの p50 1.3 ms、最大 1.9 ms と同じ桁)。応答の遅延は、再検証を応答の後でスレッドに出していることによる。
- 再検証1回の長さは、この環境で約18秒(許可リスト内の成功本文)で、約9秒(Leanが拒否する本文)。60秒の上限には3倍以上の余裕がある。ただし他のセッションが同じMacで別のLeanを動かしており、1回目の実行では最初のコンパイルが30.8秒かかった。ページキャッシュが冷えた真のcold時間は測れていない(第3節と同じ)。
- 再検証が走っている間の実要求は、`max_concurrent_compiles=1` では即座に再試行可能な503になる。窓は再検証1回分(この環境で約18秒)である。

この検証で確かめていないこと: 第4節の項目(Linuxの隔離、`lake env`、cgroup圧迫による中断の実発火、本番の期限設定)。60秒の期限に実際に達する場合(タイムアウトの扱いは単体テスト(偽のverifier)で確かめただけで、実Leanでは、再検証の期限を人工的に縮めた試験もしていない)。許可リスト52件のうち、使ったのは x だけ(改ざん側は x を壊した1本)。
