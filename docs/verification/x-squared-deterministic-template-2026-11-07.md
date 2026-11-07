# x² の連続性: Lean の第1試行を決定論的テンプレートにする (2026-11-07)

## 原因

本番で「x² の連続性を説明して」を公開確認したところ、修復が1回入った(`repairs_used=1`、約1分44秒)。

- 修復の対象は Lean の第1試行だった。説明文の再生成は `repairs_used` に数えない(`pipeline.py` の `attempt - 1`)。
- 第1試行は compile で失敗した。診断は `lean.unknown_identifier`(Unknown identifier `abs_add`)で、修復は `route=prove` の1回で通った。`pals.proof_method_mismatch` は出ていない。
- 原因は、モデルが固定版の Mathlib に存在しない補題名を書いたこと。固定版では三角不等式は `abs_add_le`。
- 再現: 検証済みの証明で `abs_add_le _ _` を `abs_add _ _` に変えると、固定版の Lean が同じ `Unknown identifier abs_add` を返す(下の検証 4)。

モデルは毎回66行の証明を新しく書く。補題名の誤りは確率的に起き、修復の往復を毎回払う危険がある。ε-δ の骨格は固定なので、書き直す必要がない。

## 設計の選択肢

| 案 | 内容 | 長所 | 短所 |
|---|---|---|---|
| A | 補題名の別名表(`abs_add` → `abs_add_le`)でモデル出力を書き換える | 小さい | 載っていない誤名は直らない。表は Mathlib の更新で古くなる |
| B | コンパイル前の名前解決(Mathlib の宣言索引と照合) | 汎用 | 索引の構築と保守が要る。直すのは別の LLM 修復 |
| **C(採用)** | 検証済み証明をテンプレートにし、名前だけ置換して出す。モデルは呼ばない | 第1試行で通る。LLM 費用ゼロ。決定論的 | 対象はテンプレートのある命題だけ |
| D | 汎用の ε-δ 証明ジェネレーター(x^n、多項式) | 汎化する | 証明の正しさをテンプレートの検証済みという根拠で担保できない。別の設計が要る |

C を採用した。A は C の外側(モデルが書く他の証明)に効くが、効果が不確かなので今回は入れない。D は Recipe の一般形(`∀ n, ...` への代入)と組み合わせる次の段階とする。

## 実装

- `pals_agent/lean_templates.py`
  - `render_x_squared_epsilon_delta(bindings)`: 検証済みの証明に、関数の変数、固定点、動点、ε、δ、定理名を代入する。
  - 代入は閉じている。名前は Latin/Greek 文字で始まる8文字以内の識別子(定理名は64文字以内)に限る。キーワード、テンプレートが使う補題名と仮定名、互いに重複する名前は、書き換えずに拒否する(`TemplateBindingError`)。関数の変数と動点だけは別スコープなので同名でよい。
  - `template_proof_for_request(request)`: 次のどちらかなら出す。利用者が書いた形式命題があるときは使わない。
    - 検索が `continuous_square` の Draft を完全同値として返した。
    - 依頼文が x² の連続性だけを求めている(説明文の ε-δ 要件を決める既存の保守的な判定 `_is_x_squared_continuity` と同じ)。
- `ProofPipeline._generate_attempt`: 第1試行(`feedback is None`)で上のテンプレートがあれば、draft、sketch、prove の LLM 3段を飛ばしてテンプレートを返す。以降の preflight、ε-δ 方式検査、API 検証、意味審査、説明文の生成と QA は従来どおり。テンプレートが compile に落ちたときは、従来の修復(モデル)に落ちる。
- 切替: `PALS_DETERMINISTIC_TEMPLATES_ENABLED`(既定 `true`、`false` で従来動作)。`ProofPipeline.deterministic_templates` の既定は `False` で、`build_pipeline` が設定から渡す。

Lean が真偽の唯一の根拠である点は変えていない。テンプレートは「検証済みの候補」ではなく「LLM を通さない候補」であり、通常の候補と同じく API の compile を通らなければ公開されない。

## 検証

1. 固定版 Lean(4.32.0-rc1、固定 Mathlib のビルド済み olean)でテンプレートを3通りの名前で compile した。いずれも成功(exit 0、出力なし)。
   - 既定(`x2_continuous`、x、a、x、ε、δ)
   - 全て改名(`sq_cont`、t、p、s、e、d)
   - 検証済みフィクスチャの名前(y、x、y)
2. 空白を畳んで比較すると、フィクスチャの名前で描画した結果は `tests/fixtures/PalsX2Verified.lean` と一致する(`test_default_rendering_is_the_verified_fixture_up_to_names_and_layout`)。
3. 描画結果は ε-δ 方式の preflight(`validate_generated_lean`)を通る。目的の命題は `matches_x_squared_continuity` に一致する。
4. 反例: `abs_add_le` を `abs_add` に変えると、固定版 Lean が `Unknown identifier abs_add` を返す。これは本番の診断と同じ。
5. 単体テスト `tests/unit/test_lean_templates.py`(49件)。
   - 代入の安全性: キーワード、改行、`:=`、`--`、`.`、数字始まり、長すぎる名前、テンプレートの仮定名と補題名、重複する名前の拒否。改名が全単射であること。
   - 認識の反例: 別の性質(一様連続、導関数)、別の冪(x³)、合成(x²+1、(x-1)²)、2つの命題、x² を含まない依頼、完全同値でない Draft、別の Draft、利用者の形式命題。
   - パイプライン: テンプレートの要求ではモデルを呼ばずに verified まで進む。テンプレートが落ちたときは従来の修復に落ちる。フラグ off と、テンプレート外の依頼ではモデルが書く。

## 残るリスクと限界

- テンプレートは固定版の Mathlib に依存する。Mathlib の版を上げるときは、テンプレートを再検証する(上の検証 1 を再実行する)。
- 対象は x² の連続性だけ。一般形(x^n、他の関数)は、Recipe の全称変数への代入と組み合わせる別設計が要る。
- 説明文(日本語)はまだ LLM と2回の QA を通る。ここは今回の対象外で、説明文もテンプレート化できるが、言語ごとの本文と Lean 行範囲の引用が要る。
- 本番の実測(修復ゼロでの完了、所要時間の短縮)は、配備後でないと分からない。
- 依頼文の判定は日本語の語 `連続` と `x²`/`x^2` に依存する。英語の依頼は検索が完全同値を返したときだけテンプレートになる。

## 本番へ載せる手順(配備はしない)

1. この PR を、本番 worker の基点 `d313d9f`(`claude/release-seq24-worker-repair6`)の上でレビューしてマージする。`main`(adec962)は系統が違うので、PR の宛先を取り違えない。
2. 新しい worker の SHA を決め、API を含む次の更新(seq25)に載せる。API は署名窓(11/8 15:57 JST まで)を更新する。
3. 載せる前に、固定版 Lean でテンプレートを再 compile する(検証 1)。
4. 配備後に公開確認を1回行い、`repairs_used=0` と、verified までの時間を記録する。
5. 問題があれば `PALS_DETERMINISTIC_TEMPLATES_ENABLED=false` で従来動作に戻せる(環境変数の変更は infra の配備が要る)。
