# 一般 Recipe の具体化を本線へ(フラグつき)と、評価セットでの被覆(2026-11-13)

関連: pals-agent#106(lane 本体)、#108(閉じ手の実験、本書の「#108 の取り込み」)、親 pals#343・#360。
本書の測定は、モデル呼び出しなしの (A) と、形式化に Luna を 1 回使う (B) の 2 段。held_out は読まず・実行していない。

## 利用者にとって何が変わったか

**今は何も変わらない。** フラグ既定 off、本番で on にもできない(下の「API 側の前提」)。変わったのは、(1) 誤って「検証済みの具体例」と数える穴を 1 つ塞いだこと、(2) 「質問が一般 Recipe の具体例か」を実測し、届く範囲を決めているのが一般形の数ではなく質問→形式命題の段だと分かったこと。

## 本線に入れたもの

- `pals_agent/general_recipe_stage.py`: lane の薄い接続層。`PALS_GENERAL_RECIPE_LANE` が on で Lean の作業場所(`PALS_GENERAL_RECIPE_LANE_WORKSPACE`)が設定されたときだけ生成される。失敗・時間切れ・back-check 却下はすべて miss。
- `ProofReuseRuntime.general_recipe_input`(`general_lane` 既定 None): 正確一致と文法の段の後、段0の前。形式命題は文法の表から(モデルなし)、候補は同じ Recipe 検索から。会話履歴・添付つきは対象外。miss は `None` を返し、通常経路へ進む。
- 検査: Lean 受理、宣言文が依頼の命題と同一、標準 3 公理のみ、一般定理が証明項に実在(#106)。**新規: 結論の種類が同じ Recipe だけを採用する**(`related`)。
- テスト: `tests/unit/test_general_recipe_stage.py`(無効時に何も起きない・検索も呼ばない、miss は None、会話付きは対象外、lane の例外は miss)、`tests/integration/test_general_recipe_stage_real.py`(実 Lean)。

### 見つけた穴
`bound` 段の `convert … using 1` は、異なる種類の命題でも `propext` 経由で閉じ、Recipe が項に残るため「一般定理を使った」検査を通る。実 Lean で `(2:ℝ)+2=4` が微分可能性の Recipe の手柄として受理された。真偽は Lean が保証するので誤答ではないが、**回答に別の Recipe の説明が付く(帰属の誤り)**。評価セットでも、線形代数の 1 題(`la_reuse_kernel_detects_zero`)に微分可能性の Recipe が当たっていた。`related` 追加後はその 1 題も拒否される。`ContinuousAt` ↔ `Continuous` のような、述語名が接頭辞の関係にある点別の系は同じ種類とみなす(#106 の既存テストが要求)。

### API 側の前提(本番に出せない理由)
API は証拠の種別 `lean_general_recipe` を受理せず(閉じた集合)、既存の instantiation は整数リテラルの束縛だけを再導出できる。この経路の答えを精算するには、API での新種別・再導出・再 compile が要る(設計は段0の本番接続設計と同じ)。pals-api は別リポジトリで、本件の範囲外。フラグは on にしない。

## #108 の取り込み
#108(実験: 48 文 × 5〜6 の閉じ手、import 形/append 形)を実 Lean(4.32.0-rc1)で再実行し、344 件すべて通過可否・使用定数・公理が元の結果と一致した(時間は 3.5〜4.2 秒/件で、元より 0.4〜1 秒短い)。種別ごとの結果:

| 種別 | 閉じた閉じ手 | 閉じない理由 |
|---|---|---|
| 定義どおりの形(7) | すべて | — |
| 定義形からずれた形(`x*x`、`x^1` 等 8) | `funext; ring` で全て、`convert` 系で一部 | 構文のずれは `exact` / `apply` では型不一致 |
| 1 点での連続性(2) | `ContinuousAt` 経由の閉じ手 | `funext` 系は適用外 |
| 部品の合成・仮説つき(12) | 部品ごとの閉じ手(`fun_prop` 系)で 10 | 1 つの Recipe では足りない(`x^2+3x+1`、`x^2+x` は閉じず) |
| 単調性(4) | `funext; ring` | `aesop` は進まない |
| 否定例(10) | 閉じない(`x^2*x` だけは真なので正当) | — |

closer と使用定数の検査は #106 の lane に既にあり、#108 が足す機能コードは無い。取り込むのは上の結果(根拠として本書に記録)だけで、`scripts/experiments/` は取り込まない。#108 と pals#343 は、この範囲を書いて閉じる。

## 評価セットでの被覆

対象: tuning 70 題(generation-eval-v1)+ dev_unseen 20 題(freshman-v1)= 90 題。カタログ = 固定の `*-recipe-v1` 10 個(本番の一般形に近い手書きカード)。1 題 1 回、直列、実 Lean。負荷平均は (A) 開始時 約 6〜8、(B) 実行中 5.6〜26.9(別セッションが並走)。時間は上振れしている。

| 段 | 届いた(形式命題あり) | 検証済み | 1 題あたり時間(検証済み題) | 1 題あたり費用 |
|---|---|---|---|---|
| (A) モデルなし(`fixed_lean_statement` か文法) | 26 / 90 | **0 / 90** | — | 0 |
| (B) + 形式化 Luna 1 回 + 独立審査 1 回(64 題) | 58 / 64 | **1 / 64**(1.6%) | 12.0 秒(形式化 3.2 + 審査 4.9 + Lean 4.0)。n=1 | 全題平均 US$0.0003、合計 US$0.0206(123 回呼び出し) |

- (A) の最初の測定で「検証済み」だった 1 題は、上記の関連性検査で拒否された(誤採用)。
- (B) の 1 題は `seed-natural_power_continuous`(Recipe と命題が同一の恒等の具体化)。**一般→具体の汎化の証拠ではない**。
- (B) の忠実性確認は、既存の `fidelity_gate` のうち、形式化 1 回 + 独立審査 1 回 + 構造語検査 + 自明性検査だけ。往復、2 回目の形式化と Lean 等価、空虚性の Lean 探針は未使用(warm worker と追加呼び出しが要る)。審査は 59 題すべて承認(構造語で落ちたのは 1 題)で甘く、b3/b4 の形式命題が質問と同値かは確認できていない。本番の段0の検査を使えば、b2 は増える。

### 届かない題の内訳(64 題、(B))

| 分類 | 件数 | 内容 |
|---|---|---|
| b1 形式命題が作れない | 5 | 説明型 4、文法外 1 |
| b2 作れたが忠実でない | 1 | 構造語規則 |
| b3 忠実な形式命題だが合う一般形がない | 51 | Lean が全候補を却下 50、候補なし 1 |
| b4 合う形はあるが具体化が閉じない | 6 | back-check 却下(ODE 2、積分 2、行列式 1、対偶 1) |
| b5 検証済み | 1 | 恒等の具体化 |

dev_unseen 20 題: b1 1、b3 18、b4 1、b5 0。tier 別・field 別は生データ(題文を含むため git に置かない)。

### b3 に必要な一般形(カードは足さない。提案のみ)

b3 の 51 題は、形式命題は作れているが、手持ちの 10 カード(冪・1 次・比例の連続性/微分可能性/一様連続性、奇数冪の単調性)に当たらない。必要な一般形を系列でまとめる。「題数」は、b3/b4 の形式命題を目で読んで系列に振り分けた代表の数で、51 題の全数ではない(機械分類ではなく、合計は 51 に合わない)。

| 一般形 | 題数(tuning / dev_unseen) | 例(tuning の id) |
|---|---|---|
| 1. 微分の規則: `HasDerivAt (fun x => x^n ± c·x) …`、`1/x`、`exp(c·x)` の合成 | 4 / 1 | calc_derivative_cubic_minus_linear, seed-cubic_derivative, seed-reciprocal_derivative |
| 2. 順序体の平方・絶対値の不等式 `0 ≤ a²`、`2a ≤ a²+1`、三角不等式・逆三角不等式、Lipschitz | 3 / 2 | poly_square_nonnegative, poly_square_linear_bound, trig_expand_difference_square_le_two |
| 3. 可換環・体の恒等式(部分分数、`tan²+1`、`exp` の加法) | 4 / 0 | rat_adjacent_partial_fractions, exlog_expand_exp_sub_recover, trig_expand_tan_square_plus_one |
| 4. 数列の極限の規則(和、`rⁿ→0`、`(-1)ⁿ/n→0`、一意性、有界単調) | 2 / 3 | pq-real-sequence-limit-uniqueness, pq-bounded-monotone-real-sequence-convergence |
| 5. 整数の整除・互いに素・Bézout・合同方程式 | 3 / 3 | nt_bezout_101_37, pq-coprime-moduli-unique-residue-solution |
| 6. 写像・集合の包含の規則(合成の単射、`A⊆B → A∪C⊆B∪C`、単射でない例) | 4 / 1 | seed-composite_injective_implies_first, seed-quadratic_not_injective |
| 7. 連続関数の定理(中間値、区間の自己写像の不動点) | 2 / 0 | seed-continuous_endpoint_sign_change_has_root |
| 8. 1 点の連続/微分(`|x|` の 0 での性質) | 1 / 1 | seed-absolute_value_not_differentiable |
| 9. ε-δ の形の連続性(`Continuous` を `∀ε∃δ` に展開した形) | 1 / 0 | pq-real-square-continuity |
| 10. 線形代数(固有値と独立性、冪等写像、行列式の積、具体行列の可逆性・従属性) | 6 / 3 | pq-distinct-eigenvalues-linear-independence, seed-product_determinant_nonzero_iff |
| 11. 和・確率の恒等式(`Σk`、偏差の和、独立事象の和) | 1 / 3 | pq-sum-of-first-n-integers |
| 12. 具体値の事実(`π > 3.05`、`∫₀¹x²`、`tan 1° ∉ ℚ`、`101a+37b=1`) | 5 / 2 | seed-pi_gt_305, calc_integral_square_zero_one |

観察:

- 12 と 5 の一部は、一般形のパラメータ化(「`101a+37b=1` を `gcd=1 → ∃`」)で届くものの、多くは個別の事実で、一般形を足しても具体化の対象にならない。段0 の自動化ポートフォリオ(#106)の領分。
- 1・2・3・4・6 は、一般形が変数(`n`、`c`、体・環)で書ける系列で、Recipe を整備すれば、定数を入れた問題をモデルなしで導ける見込みが最もある(今回測っていない、仮説)。
- どの系列も、質問を形式命題にする段(Luna 1 回 + 審査)が前提で、(A) の範囲(26 / 90)だけでは届かない。

## 再現
```sh
PALS_LEAN_WORKSPACE=<固定版の lean-workspace> uv run --extra dev python scripts/eval/run_instance_coverage.py --out DIR --workspace <lean-workspace> --dev-manifest <親>/docs/generation-eval-freshman-v1/manifest.json
uv run --extra dev python scripts/eval/run_instance_coverage_b.py --out DIR ...   # OPENAI_API_KEY が要る
PALS_LEAN_WORKSPACE=<lean-workspace> uv run --extra dev pytest tests/unit/test_general_recipe_stage.py tests/integration/test_general_recipe_stage_real.py tests/integration/test_general_recipe_lane_real.py
```
Lean 4.32.0-rc1、Mathlib 8b62164。
