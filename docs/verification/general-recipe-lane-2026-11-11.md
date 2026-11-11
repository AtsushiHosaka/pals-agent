# 一般形 Recipe → 具体的な依頼(モデル呼び出し0回)の実測 (2026-11-11)

関連: 親リポジトリ Issue #137(T1 lane)、#327。フラグ `PALS_GENERAL_RECIPE_LANE`(既定 off)。

## 何を作ったか

`pals_agent/general_recipe_lane.py`。依頼の形式命題 `P` に対し、Recipe の定理 `G`(∀ で量化された一般形)を次の形で実 Lean に渡す。

```lean
<Recipe のソース。無変更>
theorem pals_recipe_instance_i : P := by
  first | exact G | exact G _ | … | (intros; apply G <;> first | assumption | fun_prop | positivity | norm_num | linarith | simp)
```

- 引数は Lean の(高階)単一化が見つける。モデルは何も提案しない。固定した語彙(`exact` / `apply` と、前提を閉じる tactic)だけを使う。
- 宣言する型は `P` 自身なので、Lean が受理できるのは `P` の証明だけ。そのうえで決定的な背面検査を行う: (1) コンパイル対象の宣言文が依頼から導いた文と一致する、(2) `#print axioms` が標準の3公理のみ(`sorryAx` は却下)、(3) Recipe 自身も標準3公理のみ、(4) 証明項が一般定理 `G` を実際に使っている(閉じ手の tactic だけで証明した偽装を防ぐ)。
- 上位 N 件(既定4)の候補を**1つの Lean プロセス**で一括コンパイルする。Mathlib の import(約4秒)を1回で済ませるため。失敗する候補は他の候補を巻き込まない。
- 候補の選択は Lean 命題の定数と演算子の IDF 重みつき cosine。言語フィルタも32件の batch 上限もない(本番のローカル検索は言語一致で絞り、32件が上限)。Lean が最終判定するので、選択は絞り込みにすぎない。
- `recipe_instantiation.py`(API に同じものがある)は変更していない。回答文は既存の `render_answer` を使う。

## 実測 1: 固定評価セット generation-eval-v1(100題、モデル0回、実 Lean)

Recipe の集まり: 固定の `*-recipe-v1` カード(以下 fixtures、10個。本番に載っている一般形に近い手書きの Recipe)、および `recovered-recipes-v1` の82個(以下 recovered。**未公開の候補**で、評価題の元になったカード由来)。

| 条件 | 答えた題 | 内訳 |
|---|---|---|
| ベース(フラグ既定): 完全一致プロファイルのみ | 1 / 100 | `seed-natural_power_continuous`(保存済みバイトを返すので Lean は走らない) |
| ベース(`PALS_RECIPE_INSTANTIATION` on): + 文法 | 1 / 100 | 同じ1題。文法は評価題100題のどれも解析できない(`grammar_no_parse` 99) |
| 新 lane、fixtures | 0 / 100 | 58題は形式命題が無い、7題は命題でない(tactic 構文を含む)、35題は4候補とも Lean が却下 |
| 新 lane、fixtures + recovered | 7 / 100 | 下記。7題とも recovered の Recipe と命題が同一(恒等の具体化) |

新 lane + recovered の7題: calculus_v5 の5題(held-out 4、tuning 1)、la_v5 の2題(held-out 1、tuning 1)。難度は easy 1、medium 4、hard 2。**これらは評価題の元になったカードの Recipe なので、一般→具体の汎化の証拠にはならない**(命題が同一)。公開済みの Recipe ではないので、本番の被覆率でもない。

答えた7題の時間(実 Lean 込み、1題ずつ直列、ホスト負荷平均 約12–15): 合計 p50 4.8 秒、p90 5.7 秒、最大 5.7 秒。内訳は p50 で候補選択 1.7 ms、ソース組み立て 0.7 ms、Lean 4.8 秒。時間はほぼ Lean プロセスの起動と Mathlib の読み込み(空のファイルで3.6–4.4秒)。

難度別(評価セット全体、新 lane + recovered): easy 1/25、medium 4/50、hard 2/25。**新 lane の被覆が低い最大の理由は、評価題100題のうち58題(easy 18、medium 26、hard 14)に形式命題が無く、モデルなしでは Lean の命題にできないこと。** 残りの形式命題42題のうち35題(+7題が命題の形でない)は、既存の Recipe のどれの特殊化でもなかった。

## 実測 2: 特殊化の探針(テスト専用、18題、モデル0回、実 Lean)

評価セットには既存の Recipe の特殊化にあたる題がほとんどないので、既存の Recipe 系列(冪・1次・比例の連続性、微分可能性、一様連続性、奇数冪の単調性)の特殊化を18題(`testdata/general-recipe-probes-v1`。評価セットには含めず、カタログにも追加しない)作って測った。

| | ベース(文法あり) | 新 lane(fixtures のみ) |
|---|---|---|
| 特殊化の依頼(15題)に答えた数 | 2 / 15 | 15 / 15 |
| 特殊化でない依頼(3題、負の対照)に答えた数 | 0 / 3 | 0 / 3(`x^2+1` の連続性、`|x|` の微分可能性、`x^2` の一様連続性) |
| 答えた題の時間(実 Lean 込み) | 4.9–5.9 秒(2題。別に独立審査のモデル呼び出し1回が要る) | p50 5.8 秒、p90 6.4 秒、最大 6.7 秒(モデル0回) |
| 外れた理由 | 文法が解析できない 12、言語フィルタ 4 | — |

新 lane が通した15題には、`x^3`、`x^10`、`x^0`、`∀ n, Continuous (x^(n+1))`(n := n+1 の抽象的な具体化)、`3x-5`(`a*x+b` への引き算の吸収)、`x^(2*3+1)`、一様連続性、微分可能性を含む。言語に依存しない: 英語の依頼でも、日本語で作られたカードを使える(ベースは言語フィルタで4題が落ちる)。ベースの文法は、形式命題を受け取れないため、同じ入力(形式命題)での比較ではない点に注意。

## 実測 3: 構造の異なる3系統(テスト専用 Recipe、`tests/fixtures/general_recipes/`)

実 Lean の統合テスト `tests/integration/test_general_recipe_lane_real.py` が、次を通す(モデル0回)。

1. 合成・パラメータつき関数の連続性。一般形 `∀ f g, Continuous f → Continuous g → Continuous (fun x => f x * g x + f x)` から `Continuous (fun x => (x^2+1) * Real.exp x + (x^2+1))`。`f := x^2+1`、`g := exp` は高階単一化で、前提 `Continuous f` などは `fun_prop` が閉じる。
2. 一般の可換環上の恒等式を具体的な環へ。`{R} [CommRing R] (a b : R), a^2 - b^2 = (a+b)(a-b)` から `ZMod 7` 上の全称命題と、`ℤ` 上の数値の等式。
3. 一般の仮説からの順序の命題。`0 ≤ a → a ≤ b → a^n ≤ b^n` から `∀ n, (3:ℝ)^n ≤ 5^n`。前提 `0 ≤ 3`、`3 ≤ 5` は `norm_num`。
4. (追加) 集合の包含で、前提が依頼の仮定から来る場合。

加えて: 冪の一般形 Recipe だけ(具体カードなし)で `x^2` の連続性、否定例(`x^2+1`、不等号の向きが逆)が答えにならないこと、`sorry` を含む Recipe が却下されること、一般定理を使わず `norm_num` だけで証明できる命題が無関係な Recipe の手柄にならないこと。

## 誤答(依頼と違う命題の受理)

0件。受理した全回答で、実 Lean が受理し、背面検査(宣言文の一致、標準3公理のみ、一般定理の使用)を通っている。ただし、**依頼の形式命題 `P` が自然文の依頼に忠実かどうかは、この lane の外**(評価では `fixed_lean_statement`、本番では文法か人手のカード)。

## まだできないこと・確認していないこと

- 本番の依頼経路には未接続。形式命題を得る段(モデルなしでは文法だけ)と、API の再導出・再 compile の証拠(`recipe_instantiation_evidence`)への接続は別の変更が要る。モデルの独立審査を省く判断(リード決定済み)はこの lane の前提だが、API がその証拠を受理するかは未検証。
- 時間の床は Lean の起動(Mathlib の import)の約4秒。10秒以内には収まるが、常駐の検証器(Mathlib 読み込み済み)にすれば1秒未満にできる見込み。`lean_verifier/http_server.py` は触っていないので未測定。
- 候補選択は構造の近さだけで、候補が4件を超えると見落とす。多数の Recipe には索引が要る。
- 恒等の具体化が7題あるのは、評価題の元カードの Recipe を使ったから。公開済み Recipe での被覆は、公開数(約13個が使える)では評価題にほぼ届かない。
- 回答文(説明)は Recipe に保存された回答をそのまま使う。recovered の Recipe には回答文が無いので、答えた7題には説明文がない。
- ホスト負荷が高い(負荷平均 11–15)中での測定。時間は上振れしている可能性がある。

## 被覆を上げるために足りない一般形 Recipe(提案のみ。カタログには追加していない)

評価セットの形式命題が無い題と却下された題から、モデルなしで具体化できそうな一般形を挙げる。

1. 多項式・冪の導関数 `HasDerivAt (fun x => x^n) (n * x^(n-1)) x` と和・定数倍の規則(`seed-cubic_derivative`、`calc_derivative_cubic_minus_linear`、`seed-sum_derivative`)。
2. 順序体上の `0 ≤ a^2`、`a ≤ b → a + c ≤ b + c` の形(`poly_square_nonnegative`、`poly_square_linear_bound`、`logic_add_neq_contrapositive_real`)。
3. 連続性の合成規則(和・積・商・合成)。上のテスト Recipe の一般化で、`seed-rational_power_continuous` に当たる。
4. 束・集合の恒等式 `A ∪ (A ∩ B) = A`(`logic_set_union_absorption`)。
5. 合成写像の単射性、線形写像の単射と核(`seed-composite_injective_implies_first`、`seed-linear_injective_iff_zero_kernel`)。
6. 自然数の `gcd * lcm = m * n`(`nt_gcd_lcm_product_identity`)。
7. 評価題の最大の壁は Recipe の不足より、依頼文から形式命題へ行く段(58/100)。モデル1回の形式化(1回だけ、独立審査なし、Lean の背面検査のみ)か、文法の語彙表の拡張が要る。

## 再現

```sh
uv run --extra dev python scripts/eval/run_recipe_lane.py --out OUT --arms baseline_default,baseline_instantiation,lane --pool fixtures,recovered
uv run --extra dev python scripts/eval/run_recipe_lane.py --out OUT --probes --arms baseline_instantiation,lane --pool fixtures
uv run --extra dev pytest tests/unit/test_general_recipe_lane.py tests/integration/test_general_recipe_lane_real.py
```

Lean 4.32.0-rc1、Mathlib 8b62164、`lean-workspace` はメインのチェックアウトの `.lake` を使用。
