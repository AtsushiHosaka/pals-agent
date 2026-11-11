# 独立レビュー(2回目)への対応と再測定 (2026-11-11)

前: [stage0-coverage-2026-11-11.md](stage0-coverage-2026-11-11.md)。フラグ既定 off、デプロイなし、カタログ追加なし。本番経路から到達できるものはない(`ProofReuseRuntime.stage0_input` の1か所だけ。既定では何も import せず何も評価しない)。

**CI の緑は実 Lean のテストを動かさない**(`tests/qualification/agent_regression_manifest.json` の skip 一覧)。CI が守るのは Python 側の文法と段階0の制御だけで、Lean 側の許可リストとサンドボックスは、この PR の実 Lean テスト(ローカル、macOS)でしか確かめていない。

## 修正(先に)

| # | 指摘 | 対応 | テスト |
|---|---|---|---|
| 1 | 文法が拒否リストで、`_root_`、`by_elab`、`type_of%`、`binop%`、`%[ ]`、`ptrAddrUnsafe`、`dbgTrace` で抜けた | **2層の許可リスト**。層0: Python の字句許可リスト(`_root_` 拒否、`%` の接尾辞拒否、NFKC・紛らわしい文字・ホモグリフ拒否)。層1: **Lean 内、構文解析だけ**(命題は elaborate しない)。`runParserCategory` で得た構文ノード種別が、手で確認した 105 種(`allowed-syntax-kinds-v1.txt`、`gen_allowed_kinds.py` が生成)に入っていること。識別子は `resolveGlobalName` で解決し、`Lean`/`IO`/`Elab`/`Meta`/`Tactic` などの名前空間、`unsafe`、`partial`、内部名、型にこれらを含む定数なら拒否 | CI: `test_statement_grammar.py`(攻撃と受理の各ケース、`test_the_allowed_kinds_file_matches_the_lean_worker_and_has_no_dangerous_kind`)。実 Lean: `test_the_lean_side_allow_list_refuses_the_payloads_with_the_python_layer_bypassed`(17 件)、`test_the_lean_side_allow_list_accepts_plain_mathematics`(8 件)、`test_a_refused_statement_is_never_elaborated`(ファイルを書く `by_elab` が実行されない) |
| 2 | 命題が判定を出す elaboration の中でコードを実行できないことの保証 | **採用した方式: 新しい別プロセスで再検査**。model が書いた命題は、探索用の新しいワーカーと、検証用の新しいワーカーに分ける。検証ワーカーは (a) 構文解析だけの許可リスト検査を通った命題を、(b) 探索の結果(戦術の文字列)を再生して一度だけ elaborate し、参照宣言、エラーなし、標準公理のみを確認する。探索ワーカーの汚染は判定に影響しない | `test_a_search_result_the_clean_verifier_rejects_is_never_released`(探索が「証明した」と言い、検証が認めない場合は出さない。`recheck_failed`)、実 Lean `test_the_clean_verifier_rejects_a_proof_that_does_not_close_the_statement` |
| 3 | stream とウォームワーカーに RSS 監視と CPU 制限がない | `sandbox.Watchdog`: プロセスグループの RSS(既定 14 GiB、ベースライン約 7 GiB)と累積 CPU(ワーカー 900 秒)を 0.25 秒間隔で監視し、超えたらグループごと kill。cold・stream・ウォームの3つに適用 | `test_sandbox_watchdog.py`、実 Lean `test_a_memory_hog_*`(3経路)、`test_the_warm_worker_has_a_cumulative_cpu_budget_*` |
| 4 | `warm_worker` の「リクエスト間で影響しない」の記述 | 記述を削除し、**逆を明記**(プロセス大域の状態は残る)。model/利用者の命題は**リクエストごとに新しいワーカー対**(探索・検証)。カタログの命題(人手で確認済み)は共有ワーカー。共有ワーカーが CPU 予算で再利用に回った後は再起動する | `test_model_statement_runs_in_two_fresh_workers_that_are_closed_afterwards`、`test_prefetched_workers_serve_exactly_one_request_and_unused_ones_are_closed`、`test_a_dead_shared_worker_is_replaced_for_catalog_statements_even_with_fresh_workers` |
| 5 | `fenced()` が入れ子のタグを1回しか除かない | 反復して除去し、`<`・`>` を無害化 | `test_the_fence_cannot_be_closed_from_inside_by_nesting_or_odd_spacing` |
| 6 | `stage0_input` が None 判定の前に import する | 先に `self.stage0 is None` を返す | `test_the_default_path_does_not_import_stage_zero` |

**model が書いた命題の答えは、引き続き「未検証の形式化」として提示する**(`unverified_formalisation=True`)。

### 再起動のコスト(実測)
- ワーカーの起動は、負荷 13 で 9.5 秒、負荷 15〜20 で 7.5〜8 秒、空きの目安は 3.6 秒。リクエストごとに2つ起動する。
- 初版は形式化の呼び出しと並行に起動したため、形式化の依頼では起動が予算 12 秒を食った。**対策として「次のリクエストの対を、リクエストの終了直後に先に起動しておく」(prefetch)**。各対は1つのリクエストにだけ使い、使い終えたら閉じる(未使用の対は `Stage0.close()` が閉じる)。本番では、起動済みのワーカープールで同じことをする設計が要る。

## 100題の再測定

負荷: **開始時 15.1、実行中 21〜33**(待っても 8 を下回らなかった直前の測定と同じ状況で、2・3回目は待たずに実行。比較は下の注意を読むこと)。推計費用 0.038 ドル。

| 実行 | 答えた | 備考 |
|---|---|---|
| 前回(02adebd、共有ワーカー、負荷 15〜20) | 18 | 与えられた命題 11、形式化 7 |
| 1回目(今回の修正版、**自分の不具合**) | 4 | 共有ワーカーが終了した後に再起動されず(終了の原因は CPU 予算か未確認)、26題が `stage0_error` |
| 2回目(新しいワーカー、prefetch なし、負荷 15〜30) | 11 | 形式化 0。起動で予算を使い切った。`Nat.gcd` を許可リストが拒否(`@[extern]`)した 3題 |
| **3回目(prefetch、`Nat.gcd` 修正)** | **12** | 与えられた命題 11、形式化 1。誤答 0。回答時間は最大 10.3 秒(10 秒以内 11) |

- 3回目: 答えた 12(easy 3、medium 5、hard 4)、検証済み・説明にモデル 3、通常のパイプラインへ 85。通常へ回った理由: 証明できず 44、予算切れ 17、関所不合格 11、elaborate できず 5、`explain` 5、ひな形なし 3、エラー 2(1題はワーカー関連の `RuntimeError`、1題は `TimeoutError`)、**Lean 側の許可リストが拒否 1**。
- **厳しい文法で失った題**: 2回目に `Nat.gcd` を拒否された 3題(`nt_gcd_lcm_product_identity`、`number_theory_gcd_dvd_left`、`pq-coprime-moduli-unique-residue-solution`)は、`@[extern]` を拒否の根拠から外して回収した(命題は実行されない。`#eval` や `by_elab` の構文は許可リストにない)。3回目に残る損失は `pq-sum-of-first-n-integers` の1題(`∑ i in …` の旧構文が構文解析で通らない)。
- **前回(18)より減った**: 形式化 7 → 1、与えられた命題 11 → 11。形式化側の減少は、(a) 負荷が前回より高く(実行中 33 まで)、(b) 新しいワーカーの起動と CPU 競合が予算 12 秒を圧迫し、(c) `exact?` を新しいワーカーから外した(索引の構築が 12〜15 秒)。これが効いたかは未確認。**3つの影響は、この実験から分離できない。負荷の低い再測定は得られていない。** 「厳しい文法・新しいワーカーでも被覆が保たれる」とは言えない。

## まだサンドボックス(macOS の `sandbox-exec`)だけで封じているもの

- **層0・層1の許可リストを通った命題**は、構文上、コードを実行できない。それでも、elaborate 中に走る Mathlib の elaborator・マクロ・simp 拡張が無限ループや大量メモリを使うことはありうる。これは Watchdog と heartbeats、タイムアウトで止める(コンテインメント、サンドボックスの外には出ない)。
- **許可リストの穴が見つかった場合**の最後の砦は、macOS のサンドボックス(ネットワーク禁止、書き込み・実行の制限)と環境変数の除去だけ。**本番の検証器の Landlock・seccomp・cgroup・mTLS ではない**。macOS では `RLIMIT_AS` が効かない。
- 層1は、拒否リストでなく許可リストだが、**手で確認した 105 種のノード種別と名前空間の拒否リストの組み合わせ**で、第三者の確認はまだ受けていない。
- 検証ワーカーと探索ワーカーは別プロセスだが、**同じユーザー・同じ読み取り専用の Mathlib** を共有する。Mathlib の olean 自体が改ざんされるなら、この設計は守れない。

## 本番へ接続するなら
[stage0-production-wiring-design-2026-11-11.md](stage0-production-wiring-design-2026-11-11.md)(設計のみ)。起動済みワーカープール、API 側の再検証、証拠の契約が前提。この PR は実験用の既定 off のレーンで、マージは3回目のレビュー(項目 1・3・5)の後に判断する。
