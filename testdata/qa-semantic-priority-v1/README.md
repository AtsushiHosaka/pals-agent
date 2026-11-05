# QAの結論確認を優先する追加比較

#252の一度だけの追加修正を、事前登録した24QAで比較しました。固定した4出力では候補版が全件で期待された判定と妥当な理由を返しました。独立レビューでも全24件の採点が一致し、この範囲でのソース修正は限定受入PASSです。数学全般の精度向上や本番E2Eを示した結果ではありません。

前の24回では、結論欠落の負例を最初の変更案が3/3誤承認しました。その原本・採点・台帳値は保持します。今回の修正は、根拠の報告指示より後へoutput kind別の意味確認を置きます。説明ではconclusion自体、追加質問ではanswer自体が要求を満たすか確認し、両verdictで実在する短い引用と理由を求めます。入力の答えを許可する特例、判定後の成功書換、推論過程の開示要求はありません。

## 比較条件と結果

同じ4保存出力を各armで3回ずつ評価しました。これは2つの合成数学問題から作った4入力へのQA反復であり、24個の独立した問題ではありません。生成、retry、修復、fallback、途中のsource・入力・順番の変更は0です。実測はexplanationだけで、clarificationのモデル評価は行っていません。後者のfield分離と既存guardは局所回帰・独立ソースレビューで確認した範囲です。

| 固定入力 | baselineの厳格成功 | 候補の厳格成功 |
|---|---:|---:|
| coprime-positive | 3/3 | 3/3 |
| energy-positive | 3/3 | 3/3 |
| coprime-missing-result | 3/3 | 3/3 |
| energy-unsupported-bridge | 1/3 | 3/3 |

厳格成功には、期待する判定に加えて、入力にない欠陥を添えていないことを求めました。baselineもbridgeを3回とも拒否しましたが、2件は実際に引用された局所宣言の見出しを欠落と誤認したため除外しています。decompositionの18–20行は参照6–26行に、hzeroの30–31行は参照30–36行に含まれます。

各指摘のfield path・実在引用・要件に対応する理由は、拒否6件でbaselineが0/6、候補が6/6でした。正例の承認には指摘がないため、この分母へ加えていません。全verdictのconclusion確認は別に採点し、baselineが0/12、候補が12/12でした。形式の完全さを数学的正しさに置き換えていません。

結論欠落の候補は、保存された結論の実在文を引用し、求める同値条件が不足すると3回とも指摘しました。正しい下界から等号・達成・一意性を得る段階への誤った重複指摘は見つかりませんでした。未証明の確率対応も3回とも拒否し、その各理由で結論が正しくても別の未証明主張は承認できないことを区別しています。

## 計測単位と費用

UTCの2026-11-05 03:03:05.654940から03:06:00.313067まで実行しました。1行の単位は同じ固定説明への1QAで、generation＋reviewのpipelineではありません。modelはgpt-6-luna、low、出力上限6000token、timeout55秒、1attempt、standard/defaultです。

24回すべてでusageを取得し、受信raw bytes・解析後JSON・保存verdict/rationale・usage ID・provider ID・token数を照合しました。欠測0、provider IDとusage IDはそれぞれ24個の一意な値でした。入力96138、出力5141tokenで、出力にはreasoning2556を含みます。cached inputは64044、cache writeは32022tokenでした。

| 入力・arm | input / output token | 保守reserve USD | QA時間の合計 秒 |
|---|---:|---:|---:|
| coprime-positive / baseline | 10542 / 191 | 0.00273100 | 25.228184 |
| coprime-positive / candidate | 12633 / 271 | 0.00329375 | 28.910000 |
| energy-positive / baseline | 11676 / 1126 | 0.00348200 | 23.194951 |
| energy-positive / candidate | 13767 / 400 | 0.00364175 | 21.680536 |
| coprime-missing-result / baseline | 9678 / 1135 | 0.00298700 | 24.992360 |
| coprime-missing-result / candidate | 11769 / 442 | 0.00316325 | 11.626355 |
| energy-unsupported-bridge / baseline | 11991 / 432 | 0.00321375 | 11.527859 |
| energy-unsupported-bridge / candidate | 14082 / 1144 | 0.00409250 | 27.443520 |

QA時間はreview呼出しと原本保存を含む計測値の合計174.603765542秒です。HTTP部分は174.450932375秒でした。反復数が少なく、キャッシュやサービスの応答時間もあるため、時間差をプロンプト単独の効果とは判断しません。

全入力0.25USD/百万token、出力0.50USD/百万tokenの事前固定reserveは0.02660500USDです。前cohortの0.02553950USDと合わせて0.05214450USDで、今回turnの上限1USD以内でした。実行前の追加上限0.552USDも超えていません。[公式pricing](https://developers.openai.com/api/docs/pricing)を2026-11-05 02:51 UTCに確認し、standard短文contextの入力0.10・cached0.01・30m write0.125・12h write0.25・出力0.50を区別しました。responseは24/24でprompt_cache_retention=24h、service_tier=defaultを返しました。その保持時間表記と料金列の対応・実際の請求額は未照合です。

## 固定した証拠と限界

- baseline commit `23e903f682a5cfbd3cc21fd88b50ce6ffba0eccf`、module SHA256 `796d216eb5288e870bebf3b9520a8fccafdb45bf48d9fc67c790a7bbb7abe41b`
- candidate commit `fc7e58b5857921d5fbe3124fec04a547600024c9`、module SHA256 `82310b14357c55524edf70ec09cc68b0531dfb834f2f3308e9e83e12f244b8b6`
- prereg SHA256 `b8e892c09b1f38db9e4d40060a872e1d2047f9e6e8f2eeb243636f3da6f2b903`
- runner SHA256 `c640066f7ae59ffab1fd3eae846318a3885acc19d5c8a95e609d272e73fa6c60`
- outcomes SHA256 `1e9f80d5299bf4f33413c977a7abdff06f55a6d3561db6f3c12e21d8499b4a3a`
- adjudication SHA256 `bc91a484af46062c2961bf05bd681a2ab7d7441793eb9a4f574f272b90cebb5f`
- metrics SHA256 `e5f1d0f869617147e50d8f83676799db086be42d39ede1c986289ac9a8ad3bb1`
- private archive `qa-semantic-priority-20261105`は140ファイルを上書きせず保存。directory0700・files0600、manifest SHA256 `c337cc05dca339a3d9febe0dc264b7e495bc81fa5ff93e08e7a5078f5155acbf`

受信原本は解析より先に新規ファイルへ保存してfsyncしました。非JSON・不正UTF8・深いJSON・decoder例外・解析後保存失敗の境界8件もofflineで通過しています。入力の元出力・response・認証情報はGitへ保存していません。

今回の4入力と古い固定6題は別suiteです。元のdual/exp同値そのものを形式化した実験でもありません。数学全般の正確さ、他モデル、生成精度、clarificationのモデル判定、本番の利用者経路や配備は未検証です。以前の結果を新問題として重複計上せず、品質台帳にはこの8セルだけを引き継ぎます。関連は[親#252](https://github.com/AtsushiHosaka/pals/issues/252)と[説明#233](https://github.com/AtsushiHosaka/pals/issues/233)です。追加の有料呼出しは行いません。
