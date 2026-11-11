# 独立レビュー(3回目)への対応 (2026-11-11)

前: [stage0-review2-fixes-2026-11-11.md](stage0-review2-fixes-2026-11-11.md)。フラグ既定 off、デプロイなし、マージしない。**設計の決定(リードの指示): 許可リストは多層防御であって境界ではない。段階0は、実際の OS 封じ込めの backend がある環境でだけ動き、なければ起動を拒否する。** 本番検証器の中で動かす案は [stage0-in-verifier-proposal-2026-11-11.md](stage0-in-verifier-proposal-2026-11-11.md)。

**CI の緑は実 Lean のテストを動かさない**(`agent_regression_manifest.json` の skip 一覧)。実 Lean のテストはローカル(macOS)で全件通した。

## 修正

| # | 内容 | テスト |
|---|---|---|
| 1 | **封じ込めがなければ起動しない**。`sandbox.available()` は macOS の `sandbox-exec` だけで True(Linux には backend がない)。`command()`、`WarmWorker`、`Stage0.__init__` は `ContainmentUnavailable` を投げる。**`PALS_LEAN_SANDBOX=off` は無効化せず、拒否になる**(以前は黙って無防備になった)。無防備な実行は、プロセス内の `sandbox.test_only_unsandboxed()` だけ。環境変数では設定できない | `test_sandbox_containment.py`(linux・darwin・sandbox-exec なし・off の各値・環境変数が効かないこと・test 専用スイッチは bare 実行を許さないこと) |
| 2 | **`Stage0` を再入可能に**。リクエストごとのワーカーは `_Req`(ローカル)で持ち、インスタンスに置かない。model が書いた命題で `worker_factory` がなければ共有ワーカーに落とさず拒否(`no_fresh_worker_factory`)。**同時実行の上限**(既定 2、超えたら `busy` でワーカーを起動せず通常のパイプラインへ)。先読みの対は lock で守り、共有ワーカーはリクエストを直列化する。プロセス数の上限は 2×同時数 + 先読み 2 + 共有 1(各 7〜9 GiB) | `test_a_model_statement_never_falls_back_to_the_shared_worker`、`test_concurrent_runs_keep_their_own_workers_and_do_not_close_each_others`、`test_admission_cap_turns_the_excess_request_away_without_starting_workers` |
| 3 | CI の skip 一覧。pytest の ID は非 ASCII を `ℝ` のように書く。それに合わせて、実 Lean テスト 65 件を JUnit から再生成(古い・足りない ID は 0) | 一覧は `agent_regression_gate.py` と同じ形式。`test_agent_regression_gate.py` が通る |
| 4 | **層 1 の挙動と文書を一致させる**(下の「層 1 が拒否するもの・しないもの」)。束縛変数への `.forM`・`.mapM` は拒否 | 実 Lean: `∀ n : ℕ, n.forM (fun i => pure ()) = pure ()`、`(n + 1).forM …`、`l.mapM …`、`(n.succ).forM …`(拒否)。`f.comp g`、`l.map id`、`s.card`、`n.succ`(受理) |
| 5 | `exact?` の呼び出しと2つ目の形式化を、層 0 と層 1 の**両方**に通してから検証ワーカーで elaborate する | `test_the_second_formalisation_goes_through_layer_zero_before_the_lean_check`、`test_an_exact_call_from_the_search_worker_passes_both_layers_before_the_verifier` |
| 6 | **層 0 の長さ・トークン上限を層 1 の前**に適用(20000 個の入れ子の括弧で Lean が stack overflow した) | `test_an_oversized_statement_is_stopped_in_python_before_lean_sees_it` |
| 7 | `ps` の cputime の `D-HH:MM`・`D-HH:MM:SS` に対応。**出力の上限**(1リクエスト 8 MiB、超えたらワーカーとグループを kill、stream も)。`close()` が失敗して kill に落ちたとき scratch ディレクトリも消す | `test_ps_cputime_formats_including_days`、`test_a_worker_that_floods_its_output_is_killed_and_reaped`、`test_a_worker_that_cannot_close_is_killed_and_its_scratch_directory_removed` |
| 8 | Mac のプロファイルを `(allow default)` + deny から **`(deny default)` + 明示の allow** に変更(必要だった読み取りは、ルート `/` のリストを含む最小の集合)。シグナルは自分にだけ | 実 Lean: `/etc/hosts`・`/private/var/tmp`・`/opt`・`/Library/Keychains`・`/private/etc/passwd`・`/Users` の読み取りとリストが拒否される。`/bin/kill`・`curl` は成功しない。`test_the_profile_is_deny_default_and_says_it_is_a_development_aid` |

## 層 1 が拒否するもの・しないもの(正確に)

拒否する:
- 許可リスト(手で確認した 105 種)にない構文ノード種別(`by`、`show`、`do`、`by_elab`、`type_of%`、`binop%`、`%[ ]`、匿名コンストラクタ、`·` など)。
- 識別子が `resolveGlobalName` で解決されたとき、その定数が (a) `Lean`/`IO`/`Elab`/`Meta`/`Tactic` などの名前空間、(b) `unsafe`、`partial`、内部名、(c) 型に (a)(b) の定数を**直接**含む(1段だけ)、のどれか。`_root_` 接頭辞。
- 束縛変数・射影の**フィールド名**が、`Nat`・`Int`・`List`・`Array`・`Option`・`String`・`Fin`・`Prod`・`Sum`・`Subtype`・`Set`・`Finset`・`Multiset`・`Rat`・`Real`・`Complex`・`Function` の中で (b)(c) に当たる宣言の名前(`forM`、`mapM` など)と一致するとき。

**拒否しない(確認していない)**:
- 型を**推移的に**は調べない(定数の型の中の定数の型は見ない)。
- 解決できない名前は通す(`autoImplicit` を切っているので、束縛変数でなければ elaborate で失敗する)。
- 上の名前空間以外の型の束縛変数へのフィールド参照は、型が elaborate なしでは分からないので調べない。名前だけの検査で、型の解決ではない(Mathlib 全体の名前表は `.comp`・`.map` のような普通のフィールドを誤って拒否するので採らなかった)。
- したがって「unsafe・partial・不適切な型の定数は常に拒否される」とは**言えない**。

## まだサンドボックスだけで封じているもの
review 2 の文書に加えて:
- Mac の `sandbox-exec` は開発用の補助で、**境界ではない**。`lean --run` が `lean` を再実行するため `process-fork` を許している。watchdog はプロセスグループで数えるので、`setsid` する二重 fork は数えない(その実行には Lean 内のコード実行が先に要る。許可リストがそれを防ぐ設計)。
- Linux には backend がなく、段階0は動かない(本番検証器の Landlock・seccomp・cgroup が backend になる前提)。

## 100題の再測定
**していない**(リードの指示: Mac の設計にこれ以上時間をかけない)。review 2 の測定(12/100、負荷 15〜33)は、ワーカー対の数・同時実行の上限・層 1 のフィールド検査の追加より前の数字。層 1 の初回検査はワーカーごとに1回、環境の走査(負荷 13 で約 1 秒)を払うので、検証ワーカーの起動時に先に払う(`prime_checker`)。
