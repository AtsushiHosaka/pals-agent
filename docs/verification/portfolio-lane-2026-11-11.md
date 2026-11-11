# Mathlib を一般形 Recipe の書庫として使う: 自動化ポートフォリオの実測 (2026-11-11)

関連: [general-recipe-lane-2026-11-11.md](general-recipe-lane-2026-11-11.md)(前段の Recipe lane)、親リポジトリ #137、#327。フラグ `PALS_GENERAL_RECIPE_LANE`(既定 off、本番の依頼経路には未接続)。

## 何を作ったか

`pals_agent/automation_portfolio.py`。依頼の形式命題 `P` に対し、**1つの Lean プロセス**で次を順に試す。

1. 前段の一般形 Recipe lane(同じ雛形と背面検査)。
2. 固定の自動化ポートフォリオ。各手が `theorem pals_portfolio_k : P` という独立の宣言で、`maxHeartbeats`(決定的な時間上限、30000)を持つ。順序は安い手から: `fun_prop`、`positivity`、`norm_num`、`simp`、`ring`、`omega`、`decide`、`linarith`、`tauto`、`gcongr`、`bound`、`field_simp <;> ring`、`constructor <;> …`、`nlinarith`、`continuity`、`measurability`、`simp_all`、`intro n; induction n <;> simp_all`、`aesop`、`grind`。どれも固定 Mathlib(8b62164)と Lean 4.32.0-rc1 に存在する。`native_decide` は公理 `Lean.ofReduceBool` を足すので入れない。ヒント項は束縛名を要するので入れない。
3. Mathlib の補題検索 `exact?`(上限 100000)。**最後**に置く。初回の索引構築が数秒かかるため。見つけた補題名を記録する(説明で引く「一般定理」)。

宣言する型は常に `P`。受理は次の全部が揃ったときだけ: その宣言に **error が1つも出ていない**、`#print axioms` が標準の3公理のみ(`sorryAx` は失敗)。Recipe の経路は前段の背面検査(宣言文の一致、一般定理の使用)に加える。`stop_on_accept` で最初の受理で Lean を止められる(pty で行ごとに読む)。

`open`/`universe` だけの前置きつきカード(scheme の6題)は、その2種のコマンドだけを前置きとして受け入れる。それ以外の命令、`sorry`、コメントを含む命題は Lean に渡さない。

### 計測中に見つけた健全性の欠陥(修正済み)

`maxHeartbeats` の決定的タイムアウトは error を出すが、宣言は `sorryAx` を含まないまま環境に残ることがある(`'x' does not depend on any axioms`)。公理の一覧だけで受理すると、**タイムアウトした手を証明として誤受理する**。最初の冷起動の集計はこれで膨らんだ(`continuity` が6題を誤って答えた)。宣言ごとに「直前の `#print axioms` 以降に error が出たか」を見て却下するようにした(`errored_declarations`、前段の Recipe lane にも同じ検査を入れた)。単体テストと実 Lean のテストで固定。前段の数字(探針 15/15、評価の元カードの7題)は修正後に再確認した。

## 実測(モデル0回の部分は費用0ドル、実 Lean 4.32.0-rc1 + Mathlib 8b62164)

100題を全部、1題ずつ直列で測った。ホスト負荷平均は 約11–25(他セッションと共有)で、時間は上振れしている可能性がある。

- 冷: 依頼ごとに新しい Lean プロセス(Mathlib の import を毎回払う)。全手を走らせる行列モード(各手の独立の寄与が分かる)で、最初の受理の到着時刻を所要時間とする。
- 温: 常駐プロセスで、各依頼を「Recipe → 手を1つずつ → 最初の受理で止める」で測る(下の「常駐プロセス」)。

形式命題の出どころ: 評価題の `fixed_lean_statement`(42題。うち7題は `theorem … := by` の全体で、前置き `open`/`universe` を含む)と、残り58題への**モデル1回の形式化**(下記)。

### 100題の被覆(答えた題数)

| | 形式命題あり(42題、モデル0回) | 形式命題なし(58題、形式化1回) | 計(100題) |
|---|---|---|---|
| 前段まで(ベース、フラグ既定) | 0 | 1(完全一致) | 1 |
| 冷、依頼ごとに新しい Lean | 12(ポートフォリオ5、Recipe7) | 17(ポートフォリオ16、Recipe1) | 29 |
| 温、常駐 Lean | **23**(ポートフォリオ16、Recipe7) | **24**(ポートフォリオ23、Recipe1) | **47** |

Recipe の7題は、評価題の元になった未公開の recovered カードの恒等の具体化で、汎化の証拠ではない。これを除いた温の数字は **40/100**(モデル0回 16、形式化1回 24)。冷で `exact?` が働かないのは、初回の索引構築がその宣言の heartbeat を使い切るため、と推定している(冷の `exact?` は上限内で失敗し、常駐では同じ上限で成功する。原因の切り分けまではしていない)。温では索引が常駐するので `exact?` が18題を閉じる。冷と温で結果が違う18題は全部この `exact?`。

### 難度別(温。ポートフォリオ+形式化で答えた題 / 題数。Recipe の恒等7題は除く)

| 難度 | 形式命題あり(モデル0回) | 形式化1回 | 計 |
|---|---|---|---|
| easy | 4 / 7 | 8 / 18 | 12 / 25 |
| medium | 9 / 24 | 12 / 26 | 21 / 50 |
| hard | 3 / 11 | 4 / 14 | 7 / 25 |

新入生レベル(easy)は 25題中12題。分野別(温、ポートフォリオまたは形式化で答えた題 / 題数): 微積分・解析 8/31、線形代数 8/22、代数幾何(scheme)5/6、離散論理 5/8、可換環 3/4、数論 3/6、学校代数 3/4、座標幾何 1/2、指数・対数 1/2、確率・ODE 1/2、数列・極限 1/2、三角関数 0/2、多変数 0/5、位相 0/1、抽象代数 0/3(Recipe の恒等は除く。形式化した1題の Recipe 経路 `seed-natural_power_continuous` も分野の数には入れていないので、合計は39で、上の40とは1題違う)。scheme の5題は、型クラスの instance(`instIsAffineHomCompScheme` など)で閉じる題が主で、数学的内容の証明が自動化で通ったとは限らない。

### 手ごとの寄与(温、最初に閉じた手 / 独立に閉じた題数は冷の行列モード)

最初に閉じた手(温、47題中、ポートフォリオ 39題): `exact?` 18、`norm_num` 9、`continuity` 3、`positivity` 2、`tauto` 2、`bound` 2、`ring` 1、`decide` 1、`grind` 1。

冷の行列モード(全手を独立に走らせた、`exact?` は索引構築で失敗): `bound` 14、`continuity` 14、`measurability` 13、`aesop` 13、`simp_all` 11、`norm_num` 10、`grind` 9、`simp` 8、`tauto` 4、`induction_simp_all` 4、`nlinarith` 3、`constructor` 系 3、`positivity` 2、`linarith` 2、`ring`/`omega`/`decide`/`fun_prop`/`field_simp` 各1。`exact?` が見つけた Mathlib の補題(18題、説明で引く一般定理): `Nat.gcd_dvd_left`、`Function.Injective.of_comp`、`injective_iff_map_eq_zero`、`LinearMap.finrank_range_add_finrank_ker`、`HasDerivAt.fun_add`、`HasFDerivAt.comp_hasDerivAt`、`InnerProductSpace.gramSchmidt_linearIndependent`、`exists_mem_Icc_isFixedPt_of_mapsTo`、`not_differentiableAt_abs_zero` など。

### 時間(Lean 起動を分ける)

| | 答えたポートフォリオの題 | p50 | p90 | 最大 |
|---|---|---|---|---|
| 冷(起動込み) | 21 | 4.0 秒 | 4.4 秒 | 4.6 秒 |
| 冷、起動(Lean の起動と Mathlib の import)を除く | 21 | 0.44 秒 | 0.58 秒 | — |
| 温(常駐、1題あたり) | 39 | 0.58 秒 | 1.8 秒 | 4.6 秒(`exact?` の初回の索引構築) |
| 温、答えられなかった題で全手を使い切る | 52 | 1.7 秒 | 5.0 秒 | 9.4 秒 |
| 形式化1回(Luna、reasoning low)の呼び出し | 58 | 4.1 秒 | 6.7 秒 | 10.4 秒 |
| 形式化+温の自動化(形式化した24題の合計) | 24 | 4.4 秒 | 6.8 秒 | 8.3 秒 |

常駐プロセスの起動は 4.7–6.1 秒(1回だけ)。起動を払った後の1題は p50 0.6 秒で、10秒の目標は形式化の呼び出し(約4秒)に支配される。形式化と Lean の起動は独立なので並行にできる。

## 形式化1回の測定と忠実さ

- モデルは、パイプラインの「評価」の割り当て(`proof_reuse_judge`: Luna、reasoning low)。Lean の命題だけを返させる(`scripts/eval/formalise.py`)。58題 58回成功、推計費用 **0.0087 ドル**(記録された使用量と版付き単価による推計)。上限の1ドルに対して十分小さい。
- 形式化した58題のうち、Lean が受理する命題になったのは 54題(エラー3: `λ` を変数名に使った、型クラスの instance が合成できない、`Tendsto` に `open Filter` がない。1題は `!![…; …]` の行列リテラルの `;` を本 lane の検査が拒否した)。受理した54題のうち、モデルなしで証明まで閉じたのは 24題(30題は命題が成立するが自動化では閉じない)。
- **忠実さの確認: 自然文との一致を決定的に検査する安い方法は見つからなかった。** 数字の被覆検査(自然文の数字が形式命題に全部出る)は、58題のうち10題を誤って弾く(`n=0`、`N!+1` など自然文にだけ出る数字)。答えた24題のうち弾くのは2題で、検出力は未測定(不一致が見つからなかったため)。Lean は命題を証明するが、その命題が依頼の意味かは判定しない。
- 手作業の審査(筆者1人、独立ではない)で、答えた24題の命題を自然文と突き合わせた。**1題が依頼より弱かった**: `seed-rank_nullity` は「斜体(division ring)K 上の加群」の依頼に対し、命題は `Field K`(可換)で書かれていた。Lean はこれを証明した。**依頼と違う命題を答えた例なので、ブロッカーとして数える**(答えた24題中1題)。他の23題は、依頼の数学的内容と一致していると判断した。ただし、多くの依頼は「理由を説明せよ」「判定せよ」「反例を示せ」を含み、形式命題はその主張の部分だけを取っている(`pq-cancellation-zero-coefficient` は同値の特徴づけ、`seed-linear_system_inconsistent` は解なしの主張)。
- 提案(未実装): 形式化の呼び出しを2回(別の温度/別の言い回し)にして、2つの形式命題が Lean 上で `↔` と証明できるときだけ進める。または既存の意味審査(モデル1回)を、Lean と並行に走らせて形式命題と依頼の一致を見る。どちらも数円で、遅延は並行で隠せる。利用者には形式命題そのものも見せるのがよい。

## 常駐プロセス(Mathlib を1回だけ import)

既存の検証器(`lean_verifier/http_server.py`)は触っていない。本測定の `scripts/eval/warm_worker.lean` は、Lean 自身で Mathlib を1回 import し、以後は同じ環境からコマンドを1つずつ elaborate する小さなワーカー(依頼ごとに環境は独立)。サンドボックス、資源制限、方針検査は無い測定用で、検証器の代わりではない。結果: 起動 4.7–6.1 秒(1回)、以後は 0.6 秒(p50)。**既存の検証器が常駐のプロセスを持つかは、コードを読んでいないので未確認**。持つなら、この表の「温」の数字がそのまま目安になる。

## まだ覆えていないもの

- 100題中53題は未回答(温): 形式命題がある42題のうち19題と、形式化した58題のうち34題(30題は命題が成立するが自動化で閉じない、3題は命題が Lean に通らない、1題は行列リテラル)。閉じない題は、実質的な証明が要る(ε-δ、帰納法、構成)。ポートフォリオの手は Mathlib の補題を知らない定型の自動化なので、`exact?` の索引にある一般定理(多くの場合、既に Mathlib にある補題)が当たらない題は閉じない。
- 前段の Recipe lane が評価題に当たらない理由は変わらない(手持ちの Recipe は評価題の特殊化にならない)。
- 冷の `exact?` は初回の索引構築のため使えない。常駐の検証器が前提。`exact?` は CPU を多く使う(1回の実行で約6コア相当を観測)ので、本番の多重度の見積もりが要る。
- 命題の忠実さ(上記)が最大のリスク。1題の誤答が見つかった。

## 説明の作り方の提案(未実装)

モデルを呼ばずに学習者向けの説明を作る案:

1. Recipe の経路は、保存された回答に `render_answer` の枠をつける(実装済み)。
2. `exact?` の経路は、見つけた補題名(例 `Function.Injective.of_comp`)から、Lean に補題の型(`#check`)と docstring を決定的に出させ、「これは Mathlib の定理 X(型 …)の特別な場合」と、命題と補題の引数の対応(証明項の最上位の適用)を、固定のひな形に差し込む。
3. 手(`positivity`、`ring`、`norm_num`、`decide`、`tauto`)は、手ごとの固定の一文(「両辺は環の正規形で一致する」「各項が非負なので和も非負」など)と、命題の式を差し込む。
4. それでも**モデルが要る**もの: 依頼が証明の方法(ε-δ、帰納法、背理法)を指定する場合、「理由を説明せよ」「なぜ成り立たないか」の文章、反例の構成、自動化が通った理由が自明でない題(`continuity`、`aesop`、`grind` が閉じた題)。この分岐は、依頼の文に方法を指す語があるか、または手が `aesop`/`grind`/`continuity` かで決められる(安い判定)。

## 再現

```sh
uv run --extra dev python scripts/eval/formalise.py --out OUT/formalised.jsonl --env-file <env> --max-usd 0.3
uv run --extra dev python scripts/eval/run_portfolio.py --out OUT/cold --formal OUT/formalised.jsonl
uv run --extra dev python scripts/eval/run_portfolio.py --warm --out OUT/warm --formal OUT/formalised.jsonl
uv run --extra dev pytest tests/unit/test_automation_portfolio.py tests/integration/test_automation_portfolio_real.py
```
