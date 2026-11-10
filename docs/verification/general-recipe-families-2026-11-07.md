# 一般形 Recipe の追加カード 8 件(オフライン、未公開) (2026-11-07)

`testdata/power-continuity-recipe-v1/` と同じ構成(`card.json`、`proofs/*.lean`、`publication.py`、`verify.py`、`publication/<id>.json`)で、全称量化した命題の kit を 8 つ作った。どれも単一の theorem で、固定版(Lean 4.32.0-rc1、Mathlib 8b62164d808cd0f23b7d8cc28190a6c1a1bb483a)で compile でき、`#print axioms` は `propext`、`Classical.choice`、`Quot.sound` のみ、`sorry` なし。審査・admission・署名・公開はしていない(カードの `lifecycle` はすべて `false`)。

## 一覧

コンパイル時間は `verify.py` の実測(Mac 上で `lean` を直接実行、キャッシュが温まった状態で、materialized source と axioms 付き source の 2 回の合計)。分離された検証器の receipt ではない。他セッションが Lean を動かしている負荷下の `pytest` では、1 回の compile が 8〜14 秒だった。

| kit(`testdata/…`) | 命題(Recipe id) | パラメータ(型) | 証明方法(`proof_method_tag`) | compile | 公理 | 応える依頼の言い方(具体化後) |
|---|---|---|---|---|---|---|
| `power-differentiability-recipe-v1` | `∀ (n : ℕ), Differentiable ℝ (fun x : ℝ => x ^ n)`(`differentiability.power.natural.induction-product-rule`) | `n : ℕ` | n の帰納法と積の微分法則(`induction_product_rule`)。`differentiable_pow` は使わない | 6.9 秒 | 標準 3 つ | 「x^3 の微分可能性」「x² は微分可能」「x^n は微分可能であることを示せ」 |
| `linear-continuity-recipe-v1` | `∀ (c : ℝ), Continuous (fun x : ℝ => c * x)`(`continuity.linear.real.explicit-epsilon-delta`) | `c : ℝ` | ε-δ、δ = ε/(\|c\|+1)(`epsilon_delta`) | 6.6 秒 | 標準 3 つ | 「3x の連続性」「cx は連続」「比例関数の連続性を ε-δ で」 |
| `linear-differentiability-recipe-v1` | `∀ (c : ℝ), Differentiable ℝ (fun x : ℝ => c * x)`(`differentiability.linear.real.difference-quotient`) | `c : ℝ` | 差分商が定数 c で、剰余が 0(`difference_quotient`)。微分の定義から直接 | 6.1 秒 | 標準 3 つ | 「3x の微分可能性」「cx は微分可能」 |
| `linear-uniform-continuity-recipe-v1` | `∀ (c : ℝ), UniformContinuous (fun x : ℝ => c * x)`(`uniform-continuity.linear.real.explicit-epsilon-delta`) | `c : ℝ` | ε-δ、δ は点によらない(`epsilon_delta`)。ライブラリの一行証明ではない | 6.6 秒 | 標準 3 つ | 「3x の一様連続性」「cx は一様連続」 |
| `affine-continuity-recipe-v1` | `∀ (a b : ℝ), Continuous (fun x : ℝ => a * x + b)`(`continuity.affine.real.explicit-epsilon-delta`) | `a b : ℝ` | ε-δ、δ = ε/(\|a\|+1)、切片 b は打ち消し合う(`epsilon_delta`) | 6.7 秒 | 標準 3 つ | 「2x+1 の連続性」「ax+b は連続」「1次関数の連続性」 |
| `affine-differentiability-recipe-v1` | `∀ (a b : ℝ), Differentiable ℝ (fun x : ℝ => a * x + b)`(`differentiability.affine.real.difference-quotient`) | `a b : ℝ` | 差分商が定数 a(`difference_quotient`) | 6.2 秒 | 標準 3 つ | 「2x+1 の微分可能性」「ax+b は微分可能」 |
| `affine-uniform-continuity-recipe-v1` | `∀ (a b : ℝ), UniformContinuous (fun x : ℝ => a * x + b)`(`uniform-continuity.affine.real.explicit-epsilon-delta`) | `a b : ℝ` | ε-δ、δ は点によらない(`epsilon_delta`) | 10.0 秒 | 標準 3 つ | 「2x+1 の一様連続性」「ax+b は一様連続」 |
| `odd-power-strict-mono-recipe-v1` | `∀ (n : ℕ), StrictMono (fun x : ℝ => x ^ (2 * n + 1))`(`monotonicity.power.odd.sign-cases`) | `n : ℕ`(指数は `2n+1`) | x の符号による 3 場合分け(`sign_cases`)。`Odd.strictMono_pow` は使わない | 8.1 秒 | 標準 3 つ | 「x^(2n+1) は狭義単調増加」。「x³ は単調増加」は下記の制約つき |

作らなかったもの(偽、または別の主張になるため): 自然数冪の一様連続性(n ≥ 2 で偽)、`x ^ n` 一般の `StrictMono`(偶数 n で偽)。Mathlib が固定版で証明できなかった命題はない。

## 具体化(`recipe_instantiation.py`)について確認したこと

- 実数パラメータ(`c`、`a b`)は整数リテラルで具体化できる。`Continuous (fun x : ℝ => 3 * x)`、`2 * x + 1`、`0 * x + 5` は単一化で解ける。`x - 1` や `x` 単独のように `c * x` の形でない式は、単一化では解けないと見込まれる(未確認。`1 * x` と書く必要がある)。
- `x ^ (2 * n + 1)` は、`x ^ 3` に対して Lean が `2 * ?n + 1 = 3` を解かない。具体化には `n := 1` の束縛(hint)が必要で、hint なしでは失敗する(実 Lean で確認)。語彙表の `bind_recipe` は `x ^ 3` から `n = 1` を導けないため、このカードは現在の決定的な文法経路では `x³` に使えない。モデルの提案(束縛つき)の経路なら使える。
- 語彙表(`request-grammar-v1.json`)に載っているのは関数 `power`(`x^k`)と性質 `continuous` だけで、新しい kit が応える言い方のうち、文法だけで通る(モデルなしで束縛まで求まる)ものは現状ない。`3x`、`ax+b` の関数行と、微分可能・一様連続・狭義単調増加の性質行を足すのは別の変更で、今回は触っていない。
- 連続性の依頼は `preferred_method = epsilon_delta` の Recipe を先に試す。新しい連続性 kit も `epsilon_delta` を持つが、`x²` の依頼は構文照合で束縛されないため、既存の x^n の ε-δ カードが選ばれることをテストで確認した。

## 公開までに残っていること(どれも未実施)

1. 独立審査(別 principal による `recipe_entry_review`)と、実モデルでの `hard_negatives` の 2 審査での測定。審査はばらつく(seq16 の記録)。
2. 検証器での admission(Mathlib 込みの compile、mTLS)。この Mac からは実行できない。
3. admitted revision の receipt の取り出しと、`publication.py entry` による unsealed entry の作成。
4. Ed25519 による署名と、`recipe_search_admit` での entry の挿入(これが公開の瞬間)。
5. 検索可能 entry の上限(32)。既存が約 20 件、今回 8 件と power ε-δ の 1 件を足すと約 29 件で、余裕は 3 件。33 件以上になると `recipe-batch` が使えない。全件を公開する前に、実数を数える。
6. 出力言語は precedent と同じく `ja` の 1 回答のみ(entry の `output_language` は 1 言語)。en、zh-Hans、zh-Hant の回答は、entry の形を変えるか、言語ごとに revision を足すかを決めてから作る。
7. カタログ追加は 2026-11-04 から停止中の扱い。公開は owner の承認が要る。
8. 語彙表に行を足さない限り、これらの kit は決定的な経路から呼ばれない(上記)。

## 検証の入口

```
uv run --extra dev pytest -q -p no:cacheprovider tests/unit/test_general_recipe_families.py
PALS_GENERAL_RECIPE_LEAN=1 uv run --extra dev pytest -q -p no:cacheprovider tests/unit/test_general_recipe_families.py -k real_lean
cd testdata/<kit> && python verify.py --project <lean-workspace> --lean-binary <pinned lean> --output <report.json>
```

最後の 2 つは、固定版 Lean と、ビルド済みの Mathlib が要る(オプトイン)。実 Lean の試験は、8 kit すべてで、Recipe の compile と公理検査、具体化した 2 つの命題の compile、偽の定理(同じ形)と非インスタンスの命題が失敗することを確認し、合格した。
