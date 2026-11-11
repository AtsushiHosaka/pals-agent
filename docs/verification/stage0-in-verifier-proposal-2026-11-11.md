# 段階0を本番検証器の新リクエスト種別として動かす案(2026-11-11)

状態: 設計提案。コード変更なし、Lean・テストは実行していない。[読] = コードか文書を読んで確認、[仮] = 推測・未検証。
前提文書: [stage0-production-wiring-design](stage0-production-wiring-design-2026-11-11.md)、[stage0-review2-fixes](stage0-review2-fixes-2026-11-11.md)、[warm-portfolio-worker-design](warm-portfolio-worker-design-2026-11-11.md)。`http_server.py` は読み取りのみ。

## 0. 前提の訂正

依頼文の「既にウォームな Mathlib」は、コードを読む限り**当てはまらない**。本番検証器は1リクエストにつき新しい `lake env lean` プロセスを起動し、毎回 Mathlib を `.olean` から import する([読] warm-portfolio-worker-design §1)。温まっているのはページキャッシュだけである。したがって「検証器の中で動かせば起動 3.6〜9.5 秒が消える」は成り立たない。消えるのは、(a)エージェント側の自前 sandbox(macOS `sandbox-exec`)への依存と、(b)承認済みの隔離境界の外で model の命題を elaborate する問題である。起動の短縮には、検証器側に常駐プールという別の大工事が要る([仮]、警告は §3)。

## 1. リクエストとレスポンス

先例: `POST /v1/recipe-admissions/verify`(閉じた source を compile するだけで proof job の意味を持たない)があり、mTLS・リリース束縛・`compile_slot`・503 の作法をそのまま使える([読] `http_server.py:394,465-550`)。新経路 `POST /v1/portfolio/verify`(名前は仮)を同じ形で足す。

リクエスト(JSON、`schema_version` 付き、キーは閉集合、重複キー拒否。既存の `_unique_object` と同じ流儀):

| フィールド | 内容 |
|---|---|
| `phase` | `search` または `verify`(§2。別 invocation) |
| `statement` | 形式命題の本文(層0を通過済みでも、検証器が層1を必ずかけ直す) |
| `portfolio_id` | 固定の手の表のバージョン(`portfolio-v1`)。**tactic の文字列は受け取らない**。表は検証器側が持つ |
| `tactic` | `verify` のときだけ。表の `name`、または `exact?` が返した項(`replay_tactic` と同じ検査) |
| `deadline_ms` | 上限つき。検証器側で `min(要求値, 固定上限)` に切り詰める |

レスポンス: `verdict`(`proved`/`not_proved`/`refused`/`aborted`)、`tactic_used`、`axioms`(検証器が自分で集めたもの。標準3公理のみ許可)、`used_lemma`、`diagnostics`(閉じたコード。source 本文は返さない)、`lean_sha256`、`toolchain_fingerprint_sha256`、リリース束縛。HTTP の意味は既存に合わせる: 中断は 503/504 で判定にしない、拒否は 422。

evidence_kind(読んだ事実): API 側の `evidence_kind` は閉じた4値 Literal で、DB の CHECK、web の `evidenceKinds` も閉集合であり、未知の種別は web で例外になる([読] production-wiring-design §1.1・§2)。よって **API 契約 → web の縮退表示 → 検証器・agent の順**でないと出せない。検証器の応答に新 `evidence_kind` は入れない(種別は API が決める)。それまでは `Stage0Result.evidence()` の `lean_portfolio` は内部の記録にとどまり、利用者には既存の通常パイプラインの答えだけが出る。`lean_verified` の流用は、モデルが書いた命題で「Lean 検証済み」と読まれるため不可。

## 2. 責務の分担

- **agent 側に残す**: 層0(Python の字句許可リスト)、忠実さの関所(2通りの形式化、意味審査、往復検査)、モデル呼び出し(トークンメーター経由にする課題は既存設計の PR1)、説明テンプレート、予算と deadline の管理、失敗時に通常パイプラインへ落とす制御。[読] `stage0.py` の構成。
- **検証器側に移す**: 層1(構文解析だけの許可リスト、105 種のノード種別と名前空間の拒否)、ポートフォリオの探索、クリーンな再検査。
- **`search` と `verify` は別 invocation(別プロセス)**。`search` の出力は戦術の文字列だけで、信用しない。`verify` は新しい process で層1を通した命題に `replay_tactic` の結果を1回だけ当て、参照宣言の存在、error なし、標準公理のみを確認する([読] `ap.recheck` が今そうしている)。
- **判定には `#print axioms` を使わない**。本番の source policy は `#print axioms` を `lean.disallowed_interactive_command` として拒否する([読] production-wiring-design §3)。検証器は `lean_audit.py` の olean 再生と `collectAxioms` を使うか、検証器自身が組み立てる固定テンプレートだけを policy の外で扱う。ただし後者でも命題部分には policy をかける。どちらにするかは**未決**。
- **`maxHeartbeats`**: policy は値を制限しない(`0` も通る)([読])。検証器側が固定上限を被せる。
- **search 段をどこで動かすか(選択肢)**。search の出力は候補にすぎず、信頼が要るのは verify だけである。したがって案 A: verify だけを検証器へ移し、search は agent 側に残す。案 B: 両方を検証器へ。案 A なら、`exact?`(索引 12〜15 秒、約6コア)を、PID 64・memory 上限付きの検証器コンテナに入れずに済む。ただし案 A でも model の命題は agent 側の search 段で elaborate されるので、層1がその境界になり、サンドボックスの問題は残る。この点の判断はリードに委ねる。

## 3. 想定レイテンシ(測定値は文書の引用、検証器内は未測定)

| 項目 | 値 | 出典 |
|---|---|---|
| 現状の worker 起動 | 空き 3.6 秒、負荷下 7.5〜9.5 秒(リクエストごとに2つ) | review2-fixes |
| `exact?` の索引構築 | 1プロセスにつき最初の1回、12〜15 秒 | stage0-lane |
| 温かい状態の1題 | p50 0.6 秒、全手を使い切る題で p50 1.7 秒・最大 9.4 秒 | portfolio-lane |
| 形式化のモデル呼び出し | p50 4.1 秒、往復検査は各 4〜5 秒 | portfolio-lane、stage0-lane |

読み取り:
- **per-request プロセス型(検証器の現行方式のまま)**では、`search` と `verify` の2回分の起動が毎回乗る。現状と同じか、mTLS・直列の待ちを足して悪化する([仮])。10 秒の目標(大学1年レベル)は、形式化の呼び出し 4〜8 秒の後では守れない。
- **短縮できるのは検証器に常駐ワーカー(import 済み・リクエストごとに新しい状態)を持たせたときだけ**。その場合の1題は上表の「温」(0.6〜1.7 秒)が目安だが、model の命題はリクエストごとに新しい process が要るというレビュー指摘との緊張がある。常駐を共有できるのは与えられた(カタログの)命題だけで、model の命題は別途 prefetch したプールを1リクエストにつき1個使い切る形になる([読] review2-fixes の prefetch)。
- **測るべきこと**(いずれも未測定): (1) 検証器の現行 `/v1/verify` の素の所要時間(Mathlib import 込み、本番構成で)。(2) 検証器コンテナ内での `search`・`verify` 各 invocation の p50/p90、負荷別。(3) `exact?` を検証器に置いたときの索引構築と、他リクエストへの影響。(4) mTLS と 503 リトライを含む agent からの往復。(5) 常駐プールのときのリクエストあたり RSS の増分と、再起動の頻度。

## 4. リスクと未決事項

1. **同時実行の受け入れ**。Mathlib プロセスは約 7〜9 GiB RSS([読] review2 の watchdog 既定値)。`MAX_CONCURRENT_COMPILES` は 2 が上限で、コメントに「PID 64 のうち2 compile で 48、4 で 61」とある([読])。1リクエストが search+verify の2プロセスを使うなら、同時に動く本数が実質1リクエストになる。満杯なら待たせず 503(既存の挙動)にして、agent は通常パイプラインへ落とすのがよい。枠と cgroup の memory を上げる決定は本番のコスト判断で、私は値を持たない。
2. **常駐か毎回か**。毎回は安全(状態が残らない)が遅い。常駐は速いが、プロセス大域の状態が残る(review2 #4)。常駐プールを入れるなら Landlock・seccomp を worker 起動時に1回だけかける設計が要る([読] lean_child は起動時に1回)。この変更は `lean_child.py` / `lean_supervisor.py` / `boundary.py` に及び、`http_server.py` の所有者との調整が先。
3. **費用と請求**。検証器は model を呼ばない([読])。モデル費は agent 側で変わらない。検証器の CPU 時間は固定費の枠内で、利用者トークンには課金されないはず([仮]、精算の仕組みは未確認)。追加で必要なのは、モデル呼び出し ID を証拠に載せる精算の整備(既存設計 PR1)であり、本提案の範囲外。
4. **API の再検証**。検証器の応答は API から見れば worker の申告と同格の可能性がある。契約の思想は「worker を信用しない」([読])。API が自分で `statement_grammar` を再検査し、自分の検証器経路で再 compile した受領証だけを承認する前提を維持する。忠実さは Lean で確かめられないので、「検証済みの命題に対する未確認の形式化」の表示は変えない。
5. **誤受理の影響**。層1に穴があれば、検証器の隔離(Landlock・seccomp・cgroup・mTLS)が最後の砦になる。それが本提案の利点だが、**層1自体は第三者の確認を受けていない**([読] review2)。実 Lean のテストは CI で動かない。
6. **既存経路への影響**。新経路は既存の `compile_slot` を共有するので、段階0の負荷が proof job の枠を奪い得る。専用の枠か、優先度の取り決めが要る([仮])。

## 5. ロールアウトの順序(すべてフラグ既定 off)

1. web: 未知の `evidence_kind` を縮退表示にする(先に配備)。
2. API: 新種別・DB CHECK・列挙箇所の契約。承認は常に DSP へ落とす。フラグ off。
3. 検証器: 新経路を足す。フラグ off では経路自体が 404 相当(`close_connection`)。リリース束縛を更新。別担当と調整してから。
4. agent: `PALS_STAGE0_PORTFOLIO` を検証器経路に切り替える(フラグ off のまま)。ローカルの実 Lean と実モデルで `make release-local-qualify` の枠(1 回 1 ドル以下)で測る。
5. 内部のみで on。誤答 0 を確認、1件でも出れば `formal_source=formalised` だけ止める。

## 決定と、いま作らない理由(2026-11-11、リードの判断)

- **方向は案 B**: 層 1・探索・検証を検証器サービスの中で動かす。**案 A は却下**(agent ホストで model の文を elaborate することが残るため)。
- **いまは作らない**。(1) 検証器サービスのコードは別の担当、(2) API/web に `evidence_kind` の契約が先に要る(web → API → verifier → agent の順)、(3) 常駐ワーカープールがなければ遅延の利益がない(本番の検証器は毎回 `lake env lean` を起動する)。

### レビューが挙げた未決の3点(答えは未確認)
1. **公理の収集**: 検証器の source policy は `#print axioms` を拒否する。検証器は公理をどう集めるか(policy の例外か、検証器側が環境から読むか)。
2. **層 1 を検証器の policy で表せるか**: 105 種の構文ノードの許可リストと `resolveGlobalName` による定数の検査を、同じ policy の関数で実装できるか(別ファイルになる可能性)。
3. **検証器の中での探索・検証の実測コスト**: コンテナ内の時間・メモリ・`MAX_CONCURRENT_COMPILES` との関係。いまの数字は Mac のローカル実測だけで、検証器内は未測定。

### 既知の残る穴(段階0の現状)
- 型が core の名前空間(`Nat`・`List` など)の外にある束縛変数へのフィールド参照は、層 1 が検査しない。
- `setsid` する二重 fork は watchdog(プロセスグループで数える)が数えない。Mac の `sandbox-exec` は開発用の補助で境界ではない。
- CI は実 Lean のテストを動かさない(skip 一覧)。許可リストとサンドボックスの確認はローカル(macOS)のみ。

## 未確認

- 本番検証器の実際の所要時間、memory cgroup 値、`MAX_CONCURRENT_COMPILES` の運用値(コードの既定値のみ確認。Terraform は未参照)。
- 検証器で `exact?` が現実的に動くか(コア数、PID 上限)。
- 現行本番の API リビジョン(seq27 の instantiation が入っているか)と、精算が新経路を呼ぶ権限・ネットワーク設計。
- 層1の許可リストを、検証器側の source policy と同じ関数で実装できるか(別ファイルになる可能性)。
