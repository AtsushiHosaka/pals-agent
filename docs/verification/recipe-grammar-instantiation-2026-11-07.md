# 汎用 Recipe の具体化を、語彙表駆動の文法でモデルなしに行う (2026-11-07)

## 目的

`∀ n, Continuous (x^n)` のような一般形の Recipe を、「x² の連続性」のような具体的な依頼に対して
`n := 2` と具体化し、証明を LLM で書かずに答える。x² の特例にせず、語彙表の行を足すだけで他の命題へ広げられる形にする。

## すでにあったもの(`claude/recipe-specialization-reuse`、pals-agent#67 と pals-api#88)

- Lean の単一化による具体化(`recipe_instantiation.py`): Recipe の元の定理に `exact general _` を適用する wrapper を作る。引数は Lean が見つける。
- 独立審査(導出された命題が依頼そのものか)と、API の再導出・再 compile(`recipe_instantiation_evidence.py`)。
- 欠けていたのは、依頼文から Lean の命題を作る段が LLM 1回だったこと。また、この経路は本番 worker(d313d9f)の系統に入っておらず、フラグ `PALS_RECIPE_INSTANTIATION` は既定 OFF。

## この変更

| 部品 | 内容 |
|---|---|
| `content_dictionaries/request-grammar-v1.json` | 関数(冪)、性質(連続)、定義域、つなぎ語の語彙表。行を足すだけで文法が広がる(単体テストで、新しい関数・性質・つなぎ語を表の追加だけで受け付けることを確認) |
| `request_proposition.py` | `parse_request`: 依頼の全ての文字が表のどれかに消費されたときだけ Lean 命題を返す。1文字でも残れば、または関数・性質が複数なら `None`。`bind_recipe`: Recipe の `∀` 本体と命題の構文照合で、自然数パラメータのリテラルを求める(自然数以外のパラメータは扱わない) |
| `ProofReuseRuntime.grammar_recipe_input` | 完全一致入力の次に実行する。LLM の前処理・判定・提案を使わず、Recipe 検索の語も表から決め、束縛を求めて独立審査(1回)へ進む。どこかで外れたら `None` を返し、従来の経路に任せる。要求を失敗させない |
| `PALS_RECIPE_GRAMMAR` | `off`/`false`/`0` でこの段だけ止める。既定は有効だが、`PALS_RECIPE_INSTANTIATION=on` が前提なので、それが OFF のままなら何も起きない |
| `testdata/power-continuity-recipe-v1/` | 一般形の ε-δ Recipe(`∀ (n : ℕ), Continuous (fun x : ℝ => x ^ n)`)。単一の theorem、δ = min(1, ε/C)、C = n(|a|+1)^(n-1)+1。n=2 で C = 2|a|+3 |
| チェックリスト審査 | `sum_bound` と `final_inequality` の文言を、`2|a|+1` に限らない十分な定数(2(|a|+1)、2|a|+3 など)を許す形に一般化。有効ケース valid-23、valid-24 と、定数が足りない対照 wrong-31 を追加 |

連続性の依頼では、`proof_method_tag == epsilon_delta` の Recipe を先に試す(語彙表の `preferred_method`)。x² の説明に ε-δ を求める既存の方針と整合させるため。

## 文法の範囲と、受け付けない例

受け付ける: `x²`、`x^2`、`x^{2}`、全角、`xの二乗`、`xの2乗`、`x³`、`x¹⁰`、`xの零乗`、`f(x)=x^2`、`x squared`、`x cubed`、`x to the power 3`、`実数全体で`、`on the real line`、変数が `x` 以外の文字。

受け付けない(従来の経路へ): 負の冪 `x^-1`、分数・小数の冪、記号の冪 `x^n`、`x²+1`、`(x-1)²`、`2^x`、否定(連続でない)、別の性質(微分可能性、導関数、一様連続)、区間・自然数・複素数などの定義域、2つの命題、冪のない依頼、10桁以上の冪、指示を含む文。

## 検証

- 固定版 Lean(4.32.0-rc1、固定 Mathlib)で、一般形 Recipe(単一 theorem)が compile 成功し、`#print axioms` は `propext`、`Classical.choice`、`Quot.sound` のみ。
- 具体化した n=2、n=0、n=3 の wrapper が compile 成功。`x^2+1` の連続性を主張する wrapper は compile 失敗(反例)。
- 単体テスト: 文法(受け付ける例と受け付けない例の両方、表の拡張、束縛の反例)、`grammar_recipe_input`(審査1回だけでの回答、拒否された審査、検索の失敗、時間不足、文脈つき要求、フラグ)、Recipe の形式(固定版 Lean を使う任意のテストを含む)、δ の主張を厳密な有理数で2万点検査、`min 1` を外すと破れる反例。
- 実モデルは使っていない(この環境に API キーがない)。独立審査とチェックリスト審査の実モデルでの測定は未実施。

## 本番へ載せる前提(配備はしていない)

1. worker: この PR を、本番 worker の系統(d313d9f)に載せる。
2. API: `claude/recipe-specialization-reuse` の具体化部分(28c72ee、799f274、2ac4d18、842d140、3d65917、6920d8d)を、本番 API 9f45a39e の系統へ取り込む。DB のマイグレーションはない。ただし、同じ統合 branch には別の機能(要求の期限、dead-letter の終了処理)も含まれる。API の環境に `PALS_RECIPE_INSTANTIATION=on` と検証器の設定が要る(`pals-api` の `docs/recipe-instantiation-rollout.md`)。
3. 配備順: API(OFF) → worker(OFF) → API を ON にして検証器の疎通を確認 → worker を ON。worker を先に ON にしてはならない。
4. Recipe の公開(本番書き込み、オーナーの承認が要る): 一般形カードの admission(検証器での compile)、独立審査と署名、埋め込み、公開。手順は `docs/square-continuity-recipe-publication.md` と同じ。カードが公開されるまで、具体化は何も返さない。
5. 公開後の確認: 「x² の連続性を説明して」が `catalog_reuse_instantiation` で返ること。モデル呼び出しが独立審査の1回だけであること。x^-1 や x²+1 が従来の経路に残ること。
6. 戻し方: `PALS_RECIPE_GRAMMAR=off` で文法の段だけ、`PALS_RECIPE_INSTANTIATION` を外せば具体化全体を止められる。

## 残るリスク

- 文法は選択器であり、判定ではない。誤読した命題は Lean が正しく証明してしまう。独立審査(1回)を外していないのはそのため。実モデルでの審査の誤承認・誤拒否は未測定。
- 保存回答は一般形の n で書かれている。n=2 の読者には「たとえば n=2 のとき C=2|a|+3」の1文があるが、x² 専用の説明ではない。
- 一般形カードの回答は、チェックリスト審査の要素(因数分解 `|x²-a²|=|x-a||x+a|`)の形にはなっていない。チェックリスト審査は Lean 証明の説明文(`explain()`)に使われ、Recipe の回答には使われない。
- 具体化の `first` 候補のうち、使われない候補はリンタ警告を出す(動作には影響しない)。
