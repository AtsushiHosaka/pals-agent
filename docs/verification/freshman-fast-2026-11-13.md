# 大学1年レベル dev_unseen 20 題での高速経路の測定（2026-11-13）

題: pals#351 の `docs/generation-eval-freshman-v1` のうち `dev_unseen` 20 題のみ（`held_out` は開いていない・実行していない）。ドライバー: `scripts/eval/run_freshman_fast.py`（`fy1-*` かつ split が dev_unseen/tuning 以外は拒否）。データ: 親リポジトリ `docs/improvement-journal/data/2026-11-13-freshman-dev-unseen/`。

## 条件

- 検証は Linux の検証イメージ（`pals-reliability-verifier`, aarch64）の中の、隔離（Landlock・seccomp・rlimit）つき常駐 Lean。Mac では測っていない（Mac はユニットテストのみ）。
- 高速経路: Luna（effort none）3 並列の統合呼び出し → 競走 → 推測ゲート（terse2）→ `LeanVerifier.verify`（信頼監査）→ 解説 → **既存の解説レビュー（必須）**。
- 通常経路は `run_stages tier2` を 20 題で 1 回実測（20/20 成功、費用 $0.7165）。高速経路と同じ回には重ねず、`run_with_fallback` の同時起動は「通常経路の記録をリプレイ」して再現した（予算を守るため。リプレイの時刻は通常経路の実測 `answer_s`）。
- 経路ごとの run: F1=調整前・リプレイ付き、D1=調整前・高速のみ、X1=調整後・高速のみ。**X1 は同じ 20 題を見て直した後の数字で、もう初見の数字ではない。**

## 結果（調整前 = 初見の数字）

| 項目 | 値 |
|---|---|
| 高速で答えた題（解説レビューまで通過） | F1: 1/20（abs-continuous-at-zero, 10.69 s）、D1: 1/20（consecutive-product-even, 12.2 s）|
| 10 秒以内に表示（20 題中、高速失敗は通常経路の総時間で数える） | 0/20 |
| 通常経路の表示時間 | 中央値 88.6 s（最小 32.1・最大 157.1）、費用 $0.7165 |

## 結果（調整後 X1、初見ではない）

高速のみ。「表示 s」= 高速が答えた題は解説レビュー完了まで、他は通常経路の `answer_s`。

| 題 | trivial | 高速で答えたか | 検証済み s | 表示 s | 失敗理由 | 通常 s |
|---|---|---|---|---|---|---|
| abs-continuous-at-zero | ○ | ○ | 4.37 | 10.004 | | 93.7 |
| consecutive-product-even | | ○ | 5.20 | 16.14 | | 80.5 |
| alternating-over-n-tends-to-zero | | × | | 77.2(通常) | 競走で閉じず | 77.2 |
| arctan-lipschitz | | × | | 130.4 | 競走で閉じず | 130.4 |
| coprime-sum-and-product | | × | | 102.6 | 競走で閉じず | 102.6 |
| cube-minus-self-divisible-by-six | | × | | 143.9 | 競走で閉じず | 143.9 |
| dependent-consecutive-triples | | × | | 157.1 | 文チェックが `Matrix.vecNotation` を拒否 | 157.1 |
| deviations-from-mean-sum-to-zero | | × | | 64.0 | 競走で閉じず（1 本は文法外で拒否）| 64.0 |
| exp-two-x-derivative | | × | | 44.9 | 競走で閉じず | 44.9 |
| factorial-dominates-power-of-two | | × | | 77.9 | 競走で閉じず | 77.9 |
| geometric-sequence-tends-to-zero | | × | 4.60 | 108.1 | 解説レビュー却下（冒頭と本文が重複、根拠なしの断定）| 108.1 |
| idempotent-eigenvalues | | × | | 138.3 | 競走で閉じず | 138.3 |
| image-of-intersection | | × | | 83.6 | モデルが「定理でない」と分類（explain）| 83.6 |
| independent-union-probability | | × | 3.90 | 125.9 | 推測ゲート却下（文が `True`、正しい却下）| 125.9 |
| integral-of-sine-over-half-period | | × | 4.78 | 81.4 | 解説レビュー却下後、時間切れ（25 s）| 81.4 |
| inverse-by-exhibiting | | × | | 111.5 | 競走で閉じず | 111.5 |
| limit-of-sum | | × | 4.20 | 80.5 | 解説レビュー却下（数式の制御文字の化け）| 80.5 |
| reverse-triangle-inequality | | × | 5.20 | 97.6 | 解説レビュー却下（片側の不等式の導出が無い、正しい却下）| 97.6 |
| three-tosses-two-heads | | × | 4.44 | 76.7 | 推測ゲート却下（往復不一致。文は忠実に見え、偽陰性の疑い）| 76.7 |
| union-monotone | ○ | × | 4.14 | 32.1 | 推測ゲート却下（往復不一致。文は忠実、偽陰性の疑い）| 32.1 |

集計（X1、20 題）: 高速の回答 2/20（10%）。10 秒以内に表示（厳密に ≤10.0 s）0/20（最速は 10.004 s で、4 ms 超過）。全体の表示時間の中央値 82.5 s（通常のみ 88.6 s）。trivial 2 題: 高速 1/2。trivial 以外 18 題: 高速 1/18。高速の費用は 20 題で $0.0177（通常の実費は別に $0.7165）。

## 忠実性（検証に通った題）

マニフェストの `faithfulness_rule` と各題の `expected_conclusion` と照合。結論: **解説レビューを通って表示まで届いた弱い定理はなかった（表示された 2 題はどちらも忠実）。**

| 題 | Lean の定理文 | 判定 |
|---|---|---|
| abs-continuous-at-zero（表示）| `ContinuousAt (fun x : ℝ => abs x) 0` | 忠実 |
| consecutive-product-even（表示）| `∀ n : ℤ, Even (n * (n + 1))` | 忠実 |
| geometric-sequence-tends-to-zero | `∀ r : ℝ, abs r < 1 → Tendsto (fun n : ℕ => r ^ n) atTop (nhds 0)` | 忠実（表示前に解説で却下）|
| integral-of-sine-over-half-period | `∫ x in 0..π, sin x = 2` | 忠実（解説で却下）|
| limit-of-sum | `Tendsto u … → Tendsto v … → Tendsto (u+v) … (a+b)` | 忠実（Filter.Tendsto 形は許容）|
| reverse-triangle-inequality | `∀ a b : ℝ, ||a|−|b|| ≤ |a−b|` | 忠実（解説で却下、妥当）|
| independent-union-probability | `∀ Ω P A B, True` | **弱い（空）**。ゲートが却下、表示されず |
| three-tosses-two-heads | `card {ω | card{i|ω i}=2} / card univ = 3/8` | 忠実。ゲート却下は偽陰性の疑い |
| union-monotone | `∀ A B C : Set α, A ⊆ B → A ∪ C ⊆ B ∪ C` | 忠実（`α` は自動束縛）。ゲート却下は偽陰性の疑い |

## 失敗原因の分類（X1、18 題）

| 原因 | 題数 | 一般的な手 |
|---|---|---|
| 競走で閉じない（モデルの 1 回の戦術＋固定ポートフォリオ） | 9 | 失敗時に Lean のエラーを渡して 1 回だけ修復する（モデル 1 往復 ≈3 s 加算。今回は未実装・未測定） |
| 解説レビュー却下 | 4（うち 1 は時間切れ）| 解説の重複・根拠不足・制御文字。解説プロンプトでなく後処理で数式の制御文字を直す／レビューの指摘を差し込んで再生成（今回実装、効果は geometric 等には未達）|
| 推測ゲート却下 | 3 | 空の文（independent）は正しい。往復不一致 2 題は偽陰性の疑い。ゲートは弱めない |
| 文チェックの文法拒否（`Matrix.vecNotation`）| 1 | 文法の許可リスト拡張（例: 行列の数値ベクトル記法）。信頼監査には影響しない |
| 分類ミス（定理でないと判定）| 1 | 統合プロンプトの分類基準 |

## 今回実装した一般的な手（2 つ）

1. 統合呼び出しのプロンプト規則: `open` に依存しない、修飾名を使う、ネストした絶対値は `abs x`、`λ` を変数名にしない（`rename_reserved_variable` を通す）。
2. 解説レビュー却下時に、指摘を渡して 1 回だけ解説を再生成する（`explanation_retries`、既定 0。レビューは必須のまま・コードは変えない）。

効果: 高速の回答 1/20 → 2/20（consecutive-product-even は調整前の F1 で解説却下、X1 で通過）。解説の生成は確率的で、再生成の効果と run 間のばらつきは分けられない（1 回の測定）。解説レビューは 2〜8 s と変動が大きく、再生成は 10 秒目標には時間を足す。**この 2/20 は調整後の数字で初見ではない。**

## 結論と限界

- 10 秒以内の表示は 20 題で 0。最速でも 10.004 s。大学 1 年レベルでは、競走が閉じたのは 9/20 で、そのうちゲートと解説レビューを通ったのは 2 題。残りの時間は主にモデル呼び出し（約 3.5 s）＋ゲート（約 1.5 s）＋解説（約 2 s）＋解説レビュー（約 3〜8 s）の直列。
- 通常経路のリプレイは実測値の再現で、同時起動の資源競合は入っていない（コンテナは 8 CPU）。Mac 固有の数値は取っていない。
- 費用は高速 $0.0177／20 題。上限 US$1 の合計内（通常 $0.7165 を含む）。

## 通常経路 88.6 s の工程別内訳（既存記録 `N1_normal.jsonl` の 20 題、追加の実行なし）

条件は 2026-11-11 の `run_stages tier2`（モデル gpt-6.1-terra、effort medium、全フラグ既定オフ、修復は最大 3 回）。工程の合計は run ごとの `stage_ms` と `explain_wait_s`・`review_s`。「受付・判定」は独立した工程として記録されておらず、Draft に含まれる。

| 工程 | 中央値 s（run 単位の合計） | 平均 s | 平均での割合 | 1 呼び出しの中央値 s |
|---|---|---|---|---|
| Draft（モデル 1 回）| 7.1 | 9.3 | 10% | 7.1 |
| Sketch（モデル）| 26.0 | 27.8 | 29% | 23.0（出力 約 1,840 トークン）|
| Sketch 検査（Lean 側）| 3.0 | 3.8 | 4% | 2.6 |
| Prove（モデル、修復を含む）| 24.4 | 26.7 | 28% | 23.6（出力 約 1,870 トークン）|
| Lean の最終検査 | 5.8 | 7.9 | 8% | 5.6 |
| 解説（`explain_wait_s`）| 10.2 | | | |
| 解説レビュー | 3.5 | | | |
| 解説＋レビュー | 13.6 | | 17% | |
| 工程に載らない待ち（wall − 工程の合計）| 4.0 | | | |
| **合計（answer_s）** | **88.6** | | | |

- 支配的なのは Sketch と Prove の 2 回のモデル呼び出しで、合計で約 57%。1 回あたり約 23 s かかるのは、出力が約 1,850 トークンと長いためで、effort は medium。
- 修復は 20 題中 11 題で発生（1 回 9 題、2 回 2 題）。修復 0 回の中央値は 77.2 s、1 回は 93.7 s、2 回は 127.3 s。修復 1 回で約 +16 s。
- 解説と解説レビューは直列で約 13.6 s。Lean の検査は全体の約 8% で、通常経路が遅い原因ではない。
- 1 題あたりのモデル呼び出しは 5〜9 回（中央値 6）。

## 「競走で証明が閉じない」9 題の定理文は忠実だったか（X1 の `attempt_log`）

- 命題は書けていて証明だけが閉じない: 7 題（alternating、arctan、coprime、cube、exp-two-x、factorial、idempotent）。定理文は期待する結論と一致する。失敗の中身は `omega`・`ring_nf`・`rewrite` の不成立、`unsolved goals` など、モデルが書いた戦術が Mathlib に合わないもの。
- deviations-from-mean: 3 候補のうち 1 つは `Σx − (Σx)/n = 0`（偏差の和ではない偽の命題）で、ここでは閉じないのが正しい。他の 2 つは忠実だが閉じなかった。
- inverse-by-exhibiting: `∃ B, A * B = 1 ∧ B * A = 1` の `A` が定まっておらず、問題の行列を表していない（未忠実）。競走まで進んでいない。
- 補足（競走前に落ちた 2 題）: dependent-consecutive-triples は `Matrix.vecNotation`（`![…]`）を文チェックが拒否。image-of-intersection はモデルが「定理でない」と分類した。
- したがって、閉じない主因は文を書けないことではなく、1 回のモデル戦術＋固定ポートフォリオでは証明が足りないことにある。
