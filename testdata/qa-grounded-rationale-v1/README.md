# QA指摘の根拠を確認する比較

[pals#252](https://github.com/AtsushiHosaka/pals/issues/252)の実装と検証記録です。前の[固定出力QA反復](https://github.com/AtsushiHosaka/pals-agent/pull/52)で、正しい下界から等号条件を導く段階まで「重複」とする理由が見つかりました。過去の原本・採点・品質台帳は変更しません。

## 実装した条件

QAが否定する各箇所について、候補JSONのfield path、実在する短いexact span、数学的な問題または違反要件を理由に含めるよう指示しました。結論の欠落では、実際の結論の語句と不足する答えを示し、存在しない文章を引用しないよう求めます。重複の指摘には2箇所の実際の文章と、同じ導出・最終計算を再実行している根拠が必要です。既に示した事実を別の推論の前提に使うことと区別します。

QAのclosedな`approved`/`rationale`応答形式は維持しています。否定を承認へ書き換える処理、fixture文字列のwhitelist、未証明の同一視や具体的結論欠落の拒否を外す処理はありません。数学的な理由が正しいかを決定的に判定するcheckerではなく、既存のモデルQAへの指示を具体化する変更です。

別commitで、保存済み説明のloaderに限り、元separatorのexcerptと旧版のLF正規化excerptを受理する明示的なlegacy modeを設けました。返すreferenceは元sourceのseparatorへ正規化し、保存payloadは変更しません。新規生成とQAは元sourceの引用を厳密に検査し、見出しguardと品質Schemaも保持します。

比較のbaselineはAgent51の`23e903f682a5cfbd3cc21fd88b50ce6ffba0eccf`、module SHA256は`796d216eb5288e870bebf3b9520a8fccafdb45bf48d9fc67c790a7bbb7abe41b`です。変更版は`781cc883db7bb6ca766c7ad4109d4ee194c4c709`、module SHA256は`601a9979187e6dc8c18bf32e3f420ae62195c2d96175facd8c31e5a132999e91`です。比較入力は元からLFであり、legacy読込の差は両版へ渡す説明本文に影響しません。

## 別cohortの事前登録

既存のLeanコンパイル・axiom監査済み合成2題から、次の4保存入力を固定しました。新規のモデル生成はありません。Energy正例は、保存済み負例の未証明の同一視を述べる最初の1文だけを取り除いたもので、他の文章・結論・引用は同一です。

| 入力ID | 期待する判定と理由 |
|---|---|
| `coprime-positive` | 自然数の0を含むEuclidの議論と積の整除条件を承認 |
| `energy-positive` | 大域的下界から等号条件・達成・一意性へ進む説明を承認 |
| `coprime-missing-result` | 実際の結論が証明完了だけであり、要求された特徴付けを欠くことを理由に拒否 |
| `energy-unsupported-bridge` | 仮定にも証明にもない正規化済み確率対象との同一視を理由に拒否し、正しい下界・等号段階への欠陥を捏造しない |

各入力を各版へ3回ずつ、4入力×3反復×2版で最大24QA呼出しです。1題につき3回なので、版の先行は2対1または1対2になります。各roundでは両版が2題ずつ先行し、全体の先行回数は同数です。入力の順番は循環させ、全24の順番を事前登録しました。異なる12題や、生成精度の測定とは扱いません。

成功は、期待する承認・拒否と、実際の欠陥だけに基づく理由を両方満たす場合です。正例の拒否、負例の誤承認、正しい欠陥に余計な誤理由を加えた拒否は分けて残します。指摘のfield path・実在する引用・理由の対応は別の列で採点し、説明の数学的な正しさと新しい理由の書式を混ぜて改善率を作りません。承認された正例には否定指摘の根拠という分母を置きません。形式不正・通信失敗・未完了・usage欠測はゼロで補いません。

モデルは同じ`gpt-6-luna`、reasoningは`low`、最大出力6,000 token、55秒、1attemptです。追加予算は1 USD、生成・再試行・修復・fallbackは行いません。全入力0.25、出力0.50 USD/百万tokenを使う固定reserveの事前上限は0.552 USDです。入力0.25は[公式Standard short context価格](https://developers.openai.com/api/docs/pricing)の12h cache write列を使った保守値であり、uncached入力0.10や実請求額とは異なります。前のresponseは`24h`/`default`を返しましたが、保持時間表記と12h・30m価格列の課金上の対応は未照合です。

事前登録のSHA256は`24dfb0c62f501c10c2083a78c10f0ab006f6725161397d4117bcbf04265f2ff8`、harnessは`464e53da3fb60305fff2feb29ee4a0ceb31a5e3f89d3a649e67c3e1179f33066`です。実装差分と事前登録を独立に確認してから実行します。有料呼出しはまだ0で、モデルの改善を確認した記録ではありません。

## 局所検証と原本保存

説明・claim・semantic review・worker・proof request workerの対象346件、strict mypy、Ruff、diff検査がPASSしました。CRLF/CR/NEL/LS/PSごとに、元excerptまたは旧LF保存値からloaderを通してclarification promptを組み立てる10件と、新規生成・QAでのLF正規化引用と改変引用を拒否する5件を含みます。このunit件数をモデル精度の分母へ足しません。

harnessはHTTP受信後、解析前に状態・所要時間・base64本文だけのflat envelopeを排他的作成し、flush/fsync後に解析と派生保存へ進みます。原本自体の保存失敗を成功とは扱いません。非JSON、不正UTF8、過深JSON、ValueError/RecursionError、parsed保存失敗と既存artifact競合、通常JSONを含むoffline8件で、後続処理が失敗しても原本を保持する境界を確認しました。前の測定原本は上書きしません。

```bash
python -m pytest -o addopts='' -q testdata/qa-grounded-rationale-v1/test_recording.py
```

生応答・保存説明・provider ID・認証情報はGitへ保存しません。原本はGit外の0700ディレクトリ・0600ファイルへ保存します。SSM・保護設定・AWS・本番DB・worker queueは使用しません。親リポジトリの品質台帳とグラフは親担当が更新します。本番の症状が解消したことや、他の入力で根拠の誤判定が起きないことは、この局所検証だけでは判断できません。
