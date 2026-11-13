# 一般 Recipe の具体化を API が再導出する(2026-11-14)

関連: pals-agent#126(lane の本線接続、マージ済み)、pals-api の同名 PR(本書と対)。フラグは既定 off。

## 設計の結論: 新しい証拠の種別は要らない

#126 の時点では「API が `lean_general_recipe` を受理しない」ことが本番で on にできない理由だった。調べると、API には Lean の単一化に任せる instantiation 経路(`recipe_instantiation.elaborate`、`catalog_reuse_instantiation`)が既にあった(seq27 系の pals-api#88)。それは次を行う。

- worker は「どの Recipe か」「命題が依頼どおりか」の判断だけを出す。
- API が自分の封印済み Recipe のバイトと依頼の命題から、固定のラッパーを再導出し、API 所有の検証器で compile する。worker の申告は使わない。
- 独立した審査(別セッション)が、導出された命題が依頼と同じ主張か、表示文が忠実かを確認する。回答 QA が精算の根拠になる。

したがって、一般 Recipe の lane は**この経路の提案元**にするのが、既存の信頼の方針(worker の自己申告を信用しない)を保つ最小の変更である。新しい証拠の種別や、worker 側で完結する「検証済み」は作らない。

## 変更

- agent: `general_recipe_input` は、文法の段が既に独立審査にかけた依頼には走らない(却下は最終で、審査を二度かけない)。lane(モデル呼び出し 0 回、agent 側の Lean)が plain 段で受理した Recipe を、提案として既存の `_recipe_instantiation` に渡す。独立審査と API 再導出は変えない。lane は「API が再導出できる範囲」である plain 段だけを使う(`bound=False`)。bound 段(`convert` 系の閉じ手)は、「一般定理が証明項にある」ことを `#print` で確かめる必要があり、API の source policy は `#` コマンドを拒否するので、API は再導出できない。使わない。
- 共通モジュール `recipe_instantiation.py`(pals-agent と pals-api でバイト同一): `elaborate` の alternatives の最後に、一般定理の前提を閉じる固定の閉じ手 `(intros; apply G <;> first | assumption | fun_prop | positivity | (norm_num; done) | linarith | (simp; done))` を足した(Mathlib を import する Recipe のみ)。**`(by norm_num)` を引数に持つ既存の alternative より前**に置く。項の中の `by` は、goal が残っても例外を投げずに「unsolved goals」をログに出すだけなので、`first` がその後ろの alternative に戻れない。後ろに置くと、lane が受理した命題(例: `0 < √(exp 1 + 1)`)を API のラッパーが compile できなかった(独立レビューで再現、実 Lean の回帰テストを追加)。これで lane の plain 段が受理するもの ⊆ API のラッパーが compile できるもの、が成り立つ。宣言する型は依頼の命題そのものなので、閉じ手は前提を閉じるだけで命題は変えられない。`module_sha256` を両リポジトリのベクトルで更新。
- 整数リテラル以外の束縛: lane は束縛を出さない(引数は Lean の単一化が決める)ので、新たに必要な束縛の型はない。有理数・変数名の付け替え・式の代入は、Lean の高階単一化がそのまま扱う(例: `f := x^2+1`、`3x-5` の引き算の吸収)。hint は従来どおり、任意で未検証。

## 通しの確認(手元、モデル呼び出しなし)

`scripts/eval/run_api_roundtrip.py`: 特殊化の探針(`testdata/general-recipe-probes-v1`、18 題。評価題ではない)で、(1) agent の lane が plain 段で Recipe を提案し、(2) API の `derive` が、Recipe のバイトと命題だけから(lane の compile 結果を使わずに)ラッパーを再導出し、(3) 再導出したソースを固定版 Lean 4.32.0-rc1 で compile する。

| 項目 | 結果 |
|---|---|
| 特殊化(15) | lane が提案 15 / 15、API 再導出ソースの compile 成功 15 / 15 |
| 特殊化でない(3) | lane が提案 0 / 3(`x^2+1` の連続性、`|x|` の微分可能性、`x^2` の一様連続性) |
| lane の時間(1 題 1 回、直列) | p50 3.9 s、最大 4.6 s |
| API ラッパーの compile | p50 3.9 s、最大 4.3 s |
| 負荷平均 | 6〜7(別セッションが並走) |

前提つきの一般定理(`0 ≤ a → a ≤ b → a^n ≤ b^n` から `∀ n, (3:ℝ)^n ≤ 5^n`)は、単体テスト(再導出)と実 Lean の統合テスト(API ラッパーが compile、lane の plain 段も受理)で確認した。

### 評価セット(tuning 70 + dev_unseen 20)での、通しで検証済みになる題数

前回の表と同じ形。**評価セットでは、新しく届く題はない。**

| 段 | 検証済み(通し) | 備考 |
|---|---|---|
| (A) モデルなし(形式命題がある題だけ) | 0 / 90 | 一般 Recipe の具体例にあたる題がない |
| (B) 形式化 Luna 1 回 + 審査(形式命題なしの 64 題) | 1 / 64 | その 1 題 `seed-natural_power_continuous` は Recipe と命題が同一で、既存の正確一致の経路が既に答える。新規の到達ではない |

届かない理由は前回の記録のとおり: 形式命題がない(64/90)、手持ちの 10 カードに合う一般形がない(51/64)。API を直しても、この数字は変わらない。変わるのは、一般形を整備したとき(微分の規則、不等式、恒等式、数列の極限、写像・集合の規則)に、**本番の API が受理できる**ことだけである。

### モデル呼び出しと費用(通しの 1 題あたり)

証明の生成は 0 回。残るのは既存経路の 2 回: 独立審査(instantiation review)と回答 QA(精算の根拠。`lean_catalog` の token 台帳の契約)。どちらも小さなモデル(Luna)で、(B) の測定では審査 1 回が約 5 秒、費用は 1 回あたり US$0.0003 前後。したがって、検証済みになった題の所要時間は、lane 約 4 秒 + 審査 約 5 秒 + API の compile 約 4 秒(待ち行列を除く)で、約 13 秒。10 秒の目標には届かない(下限は Lean の起動 3.5 秒が 2 回と審査)。

## 範囲外・未確認

- 実際の API サーバーと検証器(mTLS)を通した E2E は行っていない。API の settlement(`resolve`)は単体テストの偽の検証器で、compile は agent と同じ Lean を直接呼んだ。
- seq28 系の pals-api には、この instantiation 経路そのものが入っていなかった(seq27 系にだけあった)。pals-api の PR には、その 6 コミットの取り込みが含まれる。
- 本番で on にする順序と制約は `docs/recipe-instantiation-rollout.md`(pals-api)のとおり。これも未実施。
