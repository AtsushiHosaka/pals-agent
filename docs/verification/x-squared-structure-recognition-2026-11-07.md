# x² テンプレートの認識を、文面ではなく構造で行う (2026-11-07)

## 起きたこと(本番 job の statement、読み取りのみ)

seq25 のテンプレート(74f57780)は、日本語の statement だけで命中した。英語の statement 3件は不命中で、
モデルが draft/sketch/prove を実行し、`abs_add` の unknown identifier で第1試行が失敗した。うち2件は
修復後に `pals.proof_semantic_review_failed` で failed になった。

原因は2つあった。

1. テンプレートの認識が、日本語の文面を見る検査(`_is_x_squared_continuity`)に依存していた。
2. その検査は否定を見ない。「x² は連続でない理由」「x² は不連続ですか」も連続性の依頼として命中していた。

## 変更

- 認識は、語彙表の文法(`request-grammar-v1.json`)が依頼全体を `Continuous (fun v : ℝ => v ^ 2)` と
  読めたときだけ。文字が1つでも未消費なら不命中(否定、別の性質、区間、追加指示、2つの主張)。
- 文法が読む表現: 関数の定義(`f : ℝ → ℝ defined by f(x) = x²`、`f(x) = x² と定める`)、定義域の言い回し、
  出力言語の指示(閉じた語彙だけ。自由文は混ぜられない)、日本語・英語・簡体字・繁体字の語。
- 旧い日本語の文面検査は、テンプレートの判定から外した。
- 保険: Sketch の Lean 文が `Continuous (fun x : ℝ => x ^ 2)` と一致したら、prove 段をテンプレートに置き換える。
  言語に依存しない判定で、draft と sketch の2回だけモデルを呼ぶ。

## テスト

`tests/unit/test_lean_templates.py`: 本番の statement を回帰テストにした。表現ゆれ13件、否定例19件、
Sketch 文による置換(3件)と非置換(5件)、モデルを一度も呼ばない経路(本番3 statement)。
`ForbiddenGenerator` を使うので、モデルが呼ばれれば失敗する。

## 限界

- 文法は選択器で、未知の言い回しは不命中になり、従来のモデル経路(保険の Sketch 判定を含む)へ行く。
- 実モデルでの確認は未実施(この環境に API キーがない)。
