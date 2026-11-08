# verifierの結果キャッシュ(shadow先行版)の実装と調査

2026-11-08。ブランチ `claude/seq27-verifier-cache-shadow`(基点 `claude/seq27-worker` a6d36bc)。設計は親リポジトリの `docs/verifier-result-cache-design-2026-11-08.md` の案1である。本番、AWS、Docker、実Lean、`lake` は使っていない。

## 1. 実装したもの

| 項目 | 内容 |
|---|---|
| キャッシュ本体 | `pals_agent/lean_verifier/result_cache.py`(新規)。プロセス内メモリのみ。書き込みAPI、消去APIは無い。再起動で空になる |
| 許可リスト | verifierが起動時に `render_x_squared_epsilon_delta` で再生成する。**52件**。変数の1文字(`A-Za-z`)ごとに1本で、設計の「約50件」とほぼ同じである。内訳は下記 |
| 許可リストの列挙 | `lean_templates.x_squared_worker_bindings()`(新規)。`_bindings_for_prompt` が使う点の選び方(`a`、変数が `a` のときだけ `c`)を `_point_for_variable` に切り出して共有した。テストが、workerの全経路の出力と一致することを確かめる |
| 適格性 | 受け取った本文が許可リストの1件とバイト単位で一致するときだけ。辞書の完全一致で、ハッシュは比較に使わない |
| 保存 | 成功だけ。1キーにつき最初の成功だけを保存する(先着。2回目以降は比較のみ) |
| 上限 | エントリ数の上限は許可リストの件数(52)。許可リスト外のキーは保存を拒む |
| shadow | 常に通常どおりコンパイルし、応答は変えない。許可リスト内の本文について、保存済みの成功が有ればfreshな結果と比べて `shadow_match` か `shadow_mismatch` を記録する |
| 不一致 | `shadow_mismatch`(保存済みの成功に対し、freshがverifierの拒否判定)をERRORで1行ログし、カウンタを上げ、以後プロセスの終わりまで全キーで配信を止める |
| 配信 | 別フラグ。許可リスト内で、同じ完全keyの保存済み成功が有り、不一致が無いとき、コンパイルせずに成功を返す。attestationは毎回その要求のjob IDとURIで組み立て直す(保存済みの再送はしない) |
| 応答ヘッダー | `Pals-Verification-Source: cache` または `compile`。コンパイルまで進んだ応答(200、422、504、503の中断)に付く。JSON本文のキーは増やしていない |
| 失敗時 | キャッシュ内部の例外はログだけで、通常のコンパイル経路に戻る |

許可リスト52件の内訳: ASCII英字52字(小文字26、大文字26)。文法が読む変数 `s t u v w x y` はその部分集合である。Sketch経由の安全網(`x`/`a`)、変数が無い・複数ある・非ASCII(`α²`)の入力は、すべて `x` の1本に落ちる。`a` を変数にすると点は `c` になる。

### フラグ

| 環境変数 | 既定 | 意味 |
|---|---|---|
| `PALS_VERIFIER_RESULT_CACHE_SHADOW` | `false` | shadow(比較と保存) |
| `PALS_VERIFIER_RESULT_CACHE_ENABLED` | `false` | 配信。`SHADOW=true` と `REVALIDATE=true` が必要。どちらかが欠けると起動拒否 |
| `PALS_VERIFIER_RESULT_CACHE_REVALIDATE` | `false` | 背景再検証(第6節)。`SHADOW` か `ENABLED` が必要で、単独は起動拒否 |
| `PALS_VERIFIER_RESULT_CACHE_REVALIDATE_EVERY` | `20` | 間引き。1〜10000の正準な整数だけを受理する。`REVALIDATE=false` でも不正値は起動拒否 |

真偽値は `true` と `false` だけを受理する(`PALS_LEAN_REUSE_LAKE_ENVIRONMENT` と同じ厳密さ)。両方 `false` のときは、キャッシュのオブジェクトも許可リストも作らない。`lean_templates` の読み込みもしない。名前は `boundary.py` の資格情報らしい名前の検査に掛からない(テスト済み)。

### keyの成分

`SHA-256(JCS{schema, endpoint_kind="proof_job", source_sha256, toolchain{lean_version, lean-toolchainファイルのsha256, lake-manifest.jsonのsha256, PALS_VERIFIER_TOOLCHAIN_SHA256, PALS_VERIFIER_IMAGE_DIGEST}, policy{version, sha256}, options})`。

- lean_version、lean-toolchainのsha256、lake-manifestのsha256は、既存の `pinned_recipe_admission_context`(起動時にプロジェクトのファイルを読む)の値を再利用した。
- toolchain digestとimage digestは、既存の `VerifierDeploymentBinding` の値である。
- **policy version はコードに無かった**(設計の `audit_version` は仕様のみ)。定数 `VERIFIER_POLICY_VERSION = "pals.verifier-policy.v1"` を新設した。受理条件を変えるときに上げる。加えて `lean.py`、`lean_audit.py`、`lean_source_policy.py`、`lean_supervisor.py` のバイト列のSHA-256を起動時に計算してkeyに入れた。版を上げ忘れても、別のビルドのエントリは使われない。
- optionsは、`allow_sorry=False`、`--threads=1`、期限、出力上限、prlimit(AS、FSIZE、NPROC、NOFILE)、cgroupのメモリとPIDの上限、`literal_admission_command`、verifierのクラス名。`reuse_lake_environment` は入れていない(設計どおり)。

### 入れていないもの

TTL(設計の24時間)と起動時の予熱は入れていない。背景再検証は第6節で追加した。

## 2. 確かめたこと・確かめていないこと

確かめた(いずれも単体テスト。Leanはスタブで、実Leanもverifierコンテナも動かしていない):

- 許可リストが実際のレンダラーの出力であり、列挙と等しく、workerの経路(Draft経路で全52字、文法で `stuvwxy`、Sketch、フォールバック)の全出力を覆うこと。
- 1文字の違い(置換、削除、追記、全位置)、CRLF、タブ、NBSP、BOM、ギリシャ文字の同形字、ゼロ幅文字、コメント、`sorry`、`axiom`、同名定理の別証明が、許可リストに入らず保存もされないこと。
- クライアントが送れるヘッダー(`Pals-Verification-Source: cache`、独自のキー名、`Cache-Control`)や追加の本文フィールドで、キャッシュを名指しできないこと。追加フィールドは既存どおり400になる。
- 失敗と中断は保存されない。shadowは応答を変えない(キャッシュ無しの結果と同一)。不一致はERRORとカウンタに出て、配信を止める。
- keyの成分のどれが変わっても別キーになる。再起動で空になる。メモリ上限。並行アクセス(24スレッドの同時保存で1件、保存中の読み取り、同じ要求の同時2件)。デッドロック無し。

変異テスト(本文のstrip、shadowでの配信、失敗の保存、不一致のブロック除去、keyからimage digest除去、ロック除去)を各1回入れて、テストが失敗することを確認した。

確かめていない:

- 本番、AWS、実コンテナ。実Leanでのコンパイルと、実Leanでの `shadow_match`(同じ本文が2回とも受理されること)。
- 実際のverifierイメージのビルド。代わりに `uv build --wheel`(Dockerfileと同じ `pip wheel` 相当)で作ったwheelを展開し、`lean_templates` が読み込めて許可リスト52件が作れることだけ確かめた。
- 配備済みAPIクライアントが追加ヘッダーを無視すること。配備中の `9f45a39` の `isolated_http.py` を読んだ範囲では、レスポンスヘッダーのうち `Pals-Release-Id`、`Pals-Deployment-Binding-Sha256`、`content-length`、`content-type`、`transfer-encoding` しか見ていない(実際に動かして確かめてはいない)。
- mismatchの「失敗」はverifierの拒否判定(422)に限った。タイムアウトと中断(504、503)は `inconclusive` として別にWARNINGで数え、配信は止めない。これらは判定ではなく、APIも再試行する扱いだからである。全て不一致として数える方針に変えるなら、`_fresh_outcome` の1か所を直す。

## 3. `PALS_VERIFIER_TOOLCHAIN_SHA256` などの出所

### 3.1 コードで確認できる流れ

1. 署名付きreleaseマニフェストが `verifier_image_digest`、`verifier_toolchain_sha256`、`recipe_active_lean_version`、`recipe_active_lake_manifest_sha256` を持つ(`pals-api/app/release/proof_runtime_release_manifest.py` のキー集合と検証。toolchainは64桁hex、imageは `sha256:` 形式)。
2. `pals-api/app/release/host_verifier_pki.py` が、マニフェストの値から `binding.env` を作る。`PALS_VERIFIER_IMAGE_DIGEST` と `PALS_VERIFIER_TOOLCHAIN_SHA256` はそのまま書かれ、imageはマニフェストの `images.verifier` と `PALS_VERIFIER_IMAGE_URI` の一致を確かめる。
3. verifierは `http_runtime.py` で、この2つを環境変数から必須の文字列として読むだけである。自分で計算も検証もしない。値は `/ready` の応答で返し、Recipe admission用の指紋の `verifier_sha256` に入れる(`pinned_recipe_admission_context(verifier_sha256=…)`)。
4. APIのreconcilerは、`/ready` が返す値を自分の設定(マニフェスト由来)と照合する(`candidate_verification.py`、`isolated_http.py`)。
5. Lake manifestのdigestは別である。verifierが起動時にプロジェクトの `lake-manifest.json` を読んで計算する(`http_server.py` の `pinned_recipe_admission_context`)。API側の期待値は `PALS_RECIPE_ACTIVE_LAKE_MANIFEST_SHA256` で、マニフェスト由来である。

### 3.2 toolchain digestの中身

**画像digestとは別の値で、コードからは導出されない。** 次の証拠がある。

- `pals-agent/testdata/requested-math-seeds-v1/README.md:70-72`: 期待するverifier指紋 `8a13da18…` は「コンパイラのビルドに使った `pals_agent` のsource archive」の値だと書く。
- **再現した**: `git archive --format=tar f851917 pals_agent` のSHA-256は `8a13da18825fc857f150220dc7aec489318dc7d2354a05bb955207e4764f284f` で、上の値と完全に一致する(2026-11-08にこのリポジトリで計算)。gz、zip、全体のarchiveは一致しない。コミットでなくツリーを渡すと別の値になる(`cc2db5ec…`)ため、`git archive` がtarに埋めるコミット情報(コミットIDと時刻)にも依存する。
- 同じ式を現在の配備中verifier `189b443` に当てると `bf9a202c44ef4242a8e6989405563343abe0f1590c58e3b96a4502ee8df45a3f` になる。リポジトリにも文書にも、配備中の実際の値は書かれていない。**この値が本番の値かは未確認(unknown)**。
- ローカルは別である。`pals-scripts/bootstrap-local-recipe-config.py:149-151` はローカルでは `image digest == "sha256:" + 指紋` を要求する。一方 `docs/local-lean-runtime-recovery-2026-10-13.md` はローカルの派生イメージで指紋を据え置いたと書き、「ローカルの証拠は本番のrelease規則を変えない」と断っている。
- 仕様 `specs/lean-recipe-catalog/design.md`(LRC-030〜036)は、v1が「verifierのOCIまたはsource digest」に各Recipeを結び付け、verifierをreleaseすると全Recipeが選べなくなる、と書く。v2(verifierの版を含まない指紋)は仕様だけで、`tasks.md` の LRC-T030 は未了である。

pals-infraはチェックアウトされていないため、本番のrelease作成手順そのもの(マニフェストを作るツール)は読めていない。上の導出はverifierコミット `f851917` の1件で再現できた範囲である。

### 3.3 このキャッシュのコードを入れるとRecipeの再admissionが要るか

- 上の導出が現在も本番で使われているなら、**要る**。`pals_agent/` 全体のtarが対象なので、`result_cache.py` の追加と `http_server.py`、`http_runtime.py`、`lean_templates.py` の変更だけでなく、コミットが1つ変わるだけでも値が変わるからである。
- 値が変わると、v1の指紋に `verifier_sha256` を持つ既存Recipeはすべて選択・検索から外れる(`recipe_toolchain_readmission.py` の冒頭と、コミット `cdfa790` のメッセージ)。再admissionと、公開エントリの新しい独立レビューが要る(README記載の admitted 102件、検索公開20件)。仕様の v1 規則は「新しいdigestで公開済みRecipeを先にadmitし、そのあとreleaseする」である(`specs/lean-recipe-catalog/design.md` の Cutover の節)。
- 本番のrelease手順が上の導出と違うなら、結論は変わる。その場合は **unknown** である。確かめる最短の方法は、配備中のマニフェストの `verifier_toolchain_sha256` を `bf9a202c…`(`git archive --format=tar 189b443 pals_agent` のSHA-256)と突き合わせることである。一致すれば導出が確定する。

### 3.4 配備の費用と順序(上の証拠に基づく結論)

1. このキャッシュだけのためにverifierを単独でreleaseしない。releaseするたびに全Recipeの再admissionとエントリの再レビューが要るため、**ほかに必要なverifier変更(例: Lake環境キャッシュの `pals-agent#24`)と同じreleaseにまとめる**。
2. 順序: 新verifierのビルド → 新digestで公開済みRecipeを先にadmit → release。配備の前にadmissionを済ませる。
3. 初回の配備は `SHADOW=true`、`ENABLED=false` にする。`ENABLED` への切り替えは、同じイメージのままの環境変数の変更である。イメージもsource archiveも変わらないので、toolchain digestは変わらず、再admissionは要らない(マニフェストの署名と配備の手続きは通常どおり要る)。
4. 有効化の判断材料は、ログの `verifier_cache result=shadow_match` と `result=shadow_mismatch`(ERROR)である。`stored` が各本文で付いたあと、`shadow_match` が積み上がり `shadow_mismatch` が0のままであることを、設計第6.5節の条件(各本文10件以上、7日以上、配備をまたぐ)で見る。
5. 回避策としてfingerprint v2を先に実装する案がある(LRC-030)。大きな変更で、この作業の範囲外である。

## 4. ログとカウンタ

ロガー `pals_agent.lean_verifier.result_cache`。本文、key、job IDは出さない。許可リストの序数 `key_index` と、保存時に作る乱数の `origin_id` だけを出す。

| 結果 | レベル | 意味 |
|---|---|---|
| `ineligible` | INFO | 許可リスト外。キャッシュは触らない |
| `eligible_compile` | INFO | 許可リスト内でコンパイルする |
| `hit` | INFO | 保存済みの成功を配信 |
| `stored` | INFO | 最初の成功を保存 |
| `shadow_match` | INFO | freshな成功が保存済みの成功と一致 |
| `shadow_mismatch` | **ERROR** | freshな拒否が保存済みの成功と食い違い。配信を停止 |
| `shadow_inconclusive` | WARNING | 保存済みの成功に対し、freshがタイムアウトか中断 |
| `failure_not_stored`、`inconclusive_not_stored` | INFO | 失敗は保存しない |

起動時に `verifier result cache: mode=… allow_list_entries=…` を1行出す。

## 5. 設計文書の第8節への回答

設計文書の第8節(b)(c)に、この調査の結果を書き込んだ。

## 6. 背景再検証(`claude/seq27-verifier-cache-revalidate`)

### 6.1 目的と動き

ENABLEDでは、ヒットはコンパイルしない。保存済みの成功が今のコンパイルと食い違っても(toolchainのずれ、非決定性、プロセス内ストアの改ざん)、第2節の実Lean検証で書いたとおり観測できなくなる。背景再検証がこれを戻す。

- ヒットの応答を書き終えた後で、条件を満たしたヒットだけが、その許可リスト項目(要求ではなく、キャッシュが持つ許可リストの本文)を1回コンパイルする。要求のパスには乗らない。HTTPハンドラは非ブロックのロック操作とスレッド起動だけを行い、コンパイルはdaemonスレッドで走る。
- 結果は、一致(`revalidation_match`)、不一致(`revalidation_mismatch`)、判定不能(`revalidation_inconclusive`)のどれかである。
  - 不一致 = freshなコンパイルが、同じキーの保存済み成功に対し、verifierの拒否判定(422相当)を返した。ERRORを1行出し、カウンタを上げ、既存の `serving_blocked` を立てる。以後プロセスの終わりまで、どの項目の要求も必ずコンパイルする。
  - 判定不能 = タイムアウト、中断(504、503系)、期限、コンパイラ側の例外。WARNINGで数える。不一致にはせず、配信も止めない。判定ではなく、APIも再試行する扱いだからである。
  - 一致 = 何も書き換えない。保存済みの判定(origin id)は変えず、再検証の記録(カウンタと最終時刻)だけを更新する。
- ブロックは一方向である。再検証の完了も、先着の保存も、`shadow_match` も `_blocked` を戻さない。再検証が配信と競合しても、ブロックを外したり、ブロック中の保存を上書きしたりする経路は無い(テスト済み)。

### 6.2 間引き: 項目ごとのカウンタ

| 方式 | 内容 |
|---|---|
| 採用 | 項目ごとのカウンタ。その項目の**最初の配信**と、前回の再検証開始から**N回目の配信**ごとに1回 |
| 不採用 | 全体カウンタ。人気の項目がカウンタを消費し、めったに配信されない項目が長く再検証されないため |

「配信された項目は必ずいつか再検証される」の保証: 各項目は、最初の配信で期限に入る。再検証が空き枠不足や実行中で見送られても(`skipped_*`)、カウンタは戻さないので、項目は期限のままで、次の配信で再試行する。したがって、配信が続く項目は、配信回数N回以内(見送りが続けばその分だけ)に再検証される。**限界**: 見送られたまま、その項目が二度と配信されなければ、再検証されない。ただしその項目は配信もされないので、露出は増えない(タイマーは持たない)。再検証が判定不能で終わった項目は、次のN回の配信まで再試行しない。タイムアウトが続くときに、毎回の配信で60秒のコンパイルが枠を占有するのを避けるためである。

### 6.3 資源: 1本、枠は待たない、期限60秒

- 同時に走る再検証は1本までである(ロック下のフラグ)。実行中に期限が来た別の配信は `revalidation_skipped_busy` を数えて見送る。同じ項目の同時の2配信は、片方が開始時にカウンタを戻すため、片方しか開始しない(テスト済み、40回繰り返し)。
- verifierのコンパイル枠(`compile_slot`)を**待たずに**取る。取れなければ `revalidation_skipped_no_slot` で見送る。取れたら、コンパイルの間だけ保持して、必ず戻す(例外でも)。
- 期限は定数 `REVALIDATION_DEADLINE_SECONDS = 60.0`。本番の `http_runtime` は、同じ `LeanVerifier` を `timeout_seconds=min(60, 設定値)` で作り直したものを再検証に使う(実要求の期限300秒は変えない)。キャッシュのキーの `timeout_seconds` は実要求のままである。通常のコンパイルは約10〜18秒、ページキャッシュが冷えていると約50秒以上かかる(実Lean検証の文書)。60秒はその範囲を覆い、超えたら判定不能として枠を返す。
- **実要求への影響**(`max_concurrent_compiles=1`、既定): 再検証の最中に、キャッシュに無い実要求が来ると、既存の再試行可能な503 `verifier_unavailable` を返す。最悪の窓は1回の再検証の長さで、通常10〜18秒、上限60秒である。配信中の実要求が503になる確率は、再検証の稼働率にほぼ等しい。再検証の頻度は、配信率をrとして最大で約 r/N(項目ごとの初回を除く)で、稼働率は約 (r/N)×15秒 である。r = 日500件(0.006/s)、N = 20 なら約0.4%、日5,000件なら約4%。配信が毎秒1件を超える(N=20で稼働率が約75%を超える)と、実要求を圧迫する。その場合はNを上げる。`max_concurrent_compiles=2` なら、再検証が1枠を使う間も実要求は残りの1枠で走る(ただしPID上限の余裕は小さい、`http_server.py` の注記)。

### 6.4 カウンタとログ

`snapshot()` に出す(キャッシュと同じ場所)。

| キー | 意味 |
|---|---|
| `revalidations_started`、`revalidation_match`、`revalidation_mismatch`、`revalidation_inconclusive` | 再検証の開始数と結果 |
| `revalidation_skipped_busy`、`revalidation_skipped_no_slot` | 見送り |
| `revalidate_every` | 間引きの間隔 |
| `revalidation_in_flight` | 実行中なら1 |
| `last_revalidation_age_seconds` | 最後の再検証の完了からの秒数(未実施なら出ない) |

ログは `verifier_cache result=revalidation_started|revalidation_match|revalidation_mismatch|revalidation_inconclusive|revalidation_skipped_busy|revalidation_skipped_no_slot entry=<キーのハッシュの12桁> key_index=… elapsed_ms=… served_since=… revalidate_every=… serving_blocked=…`。`entry` はキーそのものではなく、キーをさらにハッシュした値である。本文、診断、job IDは出さない(テスト済み)。mismatchはERROR、inconclusiveはWARNING、ほかはINFO。起動時の `verifier result cache:` の行に `revalidate_every` と期限を出す。

### 6.5 導入順とアラート

1. `SHADOW=true` だけで配備する(従来どおり)。`shadow_match` が積み上がり `shadow_mismatch` が0であることを見る。
2. カウンタを確認する(各本文の `stored`、`shadow_match`)。
3. `ENABLED=true` と `REVALIDATE=true`(必要なら `REVALIDATE_EVERY`)を同時に有効にする。環境変数だけの変更で、イメージは変わらない。`ENABLED` だけは起動拒否になる。`REVALIDATE=true` を `SHADOW` だけで先に配備することもできる(ヒットが無いので動かないが、フラグと起動ログの確認になる)。
4. アラート:
   - `revalidation_mismatch` が1件でもあれば即時(ERROR。配信は自動で止まる)。原因を調べ、再起動で配信を戻す前に、toolchainとイメージの同一性を確認する。
   - `revalidation_inconclusive` の割合(started に対し)。常態的に高いなら、60秒の期限が短い(ページキャッシュが冷えている、枠が圧迫されている)。
   - `revalidation_skipped_no_slot` と `revalidation_skipped_busy` の割合。高いと再検証が回らず、露出が伸びる。`last_revalidation_age_seconds` が配信の継続中に長く伸びていないかも見る。
   - 配信が続いているのに `revalidations_started` が0のままなら、フラグが効いていない。

### 6.6 確かめていないこと

- 本番、AWS、コンテナでの再検証。Linuxの隔離(cgroup圧迫による中断)の下での実発火。
- 実Leanの確認は、macOS上の固定Lean(`lake` なし)で行った(実Lean検証の文書の第6節)。
- 再検証の最中に実要求が503を受けたとき、APIが再試行で吸収することは、リポジトリの記述(中断系の503は再試行)から読んだだけで、動かしていない。
