# #382 求値依頼の結論を検査する限定修正

この変更は作業中の実装であり、本番の精度改善や#382全体の完了を示さない。起点は現候補Agent `146ecf2b816ac6830940fac824bd9e8df90d80e4`。親#382と#385、PQ-016、CORE-002/003/004を参照する。main `32d20229aef8d1c71e38b98cdf48b9ce2a96dac3`とは106ファイルの差があるため、main全体は取り込んでいない。

## 変更した範囲

Agent#127の`6c495b1`、`05886f5`、`b0c7b1f`から、明示的な求値命令の判定と、新規生成時の結論検査だけを再利用した。v1では`LeanProofExplainer.explain`が検査を選ぶ。v2でも同じ判定を使い、生成指示とレビュー基準を揃えた。対象の求値依頼ではoverviewとconclusionの両方に結果を要求する。既存のanswer-first表示は保つ。

この検査は結論に`$...$`形式の数式があることを確認するだけで、式が最終的な答えか、数学的に正しいかを判定しない。これらの判断は既存の独立QAが行う。結果を明示せず「主張が確かめられた」とだけ書いた候補は、既存の生成試行回数と期限の中で修正する。試行回数は増やさない。

求値命令の判定は#127と同じ狭い範囲を保つ。日本語の「求めよ」「計算せよ」や英語のcomputeなどを対象とする。中文の求値命令や自由な言い回しを網羅せず、computeとproveが同居する依頼も対象から外れる。この判定を全言語の完全な分類とは扱わない。

保存済み説明を読む際は追加検査を既定で無効にし、以前の結論も読めるようにした。v1の生成プロンプト、worker、対象命題の抽出、verifier、設定、モデルは変更していない。生成者と別セッションによる意味審査、QA、同一sourceと参照の照合も維持する。未検証の昇格や未レビューの原稿へのfallbackは加えていない。

図の変換と審査、visualizationとvisualization_bindingsの返却は変更していない。不正な図の破棄、review_feedback後に図を落とす処理、本文の保持も既存どおりである。#318担当と編集範囲を確認した。

## 検証と限界

新規テストはscripted transportで生成器と構造検査だけを通す。正の実数$x$に対する$x+1/x$の最小値と達成条件、導関数、行列式などを入力に使う。共通fixtureでは平方の非負性から下界を導き、等号条件を確かめる。構造テスト自体はcompilerやQAを実行せず、本番の回答率を測らない。

| 検証 | 実結果 | 証拠の範囲 |
| --- | --- | --- |
| 起点sourceに新20件を適用 | 10件失敗、10件成功 | 結論欠落の構造回帰と既存挙動 |
| 修正後の新20件 | 20件成功 | v1/v2の修正、試行上限、保存可読性、未verified拒否、参照の一致 |
| 説明・図の関連5modules、locked環境 | 221件成功、skipなし | 既存の図・説明処理を含む回帰 |
| strict mypy、対象3ファイル | 成功 | 型検査 |
| Ruff | 追加変更は成功 | explanations.pyの既存E501だけを除外。既存プロンプトの101文字行は不変 |

最初のテスト作成時はpytestの予約名requestをparametrize引数に使い、collection errorになった。引数名を直してから起点sourceのREDを確認した。共有venvでの関連検証はPyYAML不足で220件成功・1件skipだったため、宣言済み依存を専用locked環境に用意し、221件成功・skipなしを確認した。最初のuv実行もsandboxのcache権限で失敗し、通常権限で実行し直した。途中の失敗を本番結果へ数えない。

広域58modulesの初回実行は1946件成功、47件失敗、9件error、4件skipだった。46件の失敗と9件のerrorはsandboxのloopback拒否、1件の失敗はstandalone worktreeに親compose fixtureがないことによる。skipはLinux Landlockの3件と、optional httpx不足の1件である。この結果は広域成功ではない。loopbackの影響を受けた5modulesだけを通常権限で再実行し、109件成功・1件skipを確認した。残ったskipはoptional httpx不足である。親fixture欠損とMacで実行できない境界は解消済みと扱わず、exact-source CIで別に確認する。

新規モデル呼出、設定変更、本番操作は0。v6/v8の旧測定、unit件数、CI結果を本番精度の証明や製品成功率へ流用しない。意味審査で不合格になった依頼の再形式化はAPI#108の別の経路であり、この変更では有効化しない。全工程と本番での検証、実際の最終答えの一致、全言語の網羅は未確認のままである。


## 題材の訂正と実compilerの別確認

初版136b42aでは数学題材の条件を見落とし、単純計算だけで終わる有限和を使っていた。親担当の確認後、tests-only commit04a156eで最小値と等号条件を求める題へ替えた。旧テストと測定の履歴は保持する。製品source2ファイルのbytesは136b42aから変えていない。訂正後も旧sourceでは10件失敗・10件成功、新sourceでは20件成功で、関連5modulesは221件成功・skipなしだった。

別の確認として、同じ既存Mathlib環境とLean4.32.0-rc1でtests/fixtures/reciprocal_minimum.leanを直接コンパイルした。初回のimport Mathlibは50秒でtimeoutになった。importをReal.Basicと使用するtacticに絞り、証明内容を変えずに実行し直すと9.597秒でexit0、構文上の冗長なtactic連結に関するwarning1件だった。fixtureのSHA256は8f533a306da1cc43ae634b9d7da6516cdf3e996994008a0faf41a8fa6824ea54。実環境のlake-manifest.jsonは候補146ecf2のbytesと一致し、SHA256は290f048c4a499d34a3b21f8db30ade48a2b8d05b0fe79709f1868fa6748944faだった。このローカルcompilerの受理は構造テストやQAの成功とは別の証拠で、本番verifierやsandboxとの同等性は示さない。

## CIの履歴

初回のexact-head CI44250860879はcandidate7767件成功・31件失敗・259件skipで、coreの再起動予算テスト1件によりblockedとなった。新20回帰はartifactでも全件成功だった。失敗はbirth-*件数の下限3に対し2件となったもので、anchorでは同じテストが成功した。worker_processes.pyはanchorと候補でbyte同一で、当該fresh subprocessは変更した説明moduleをimportしない。localの固定20反復は全件成功だったが、GitHub Linuxと同条件ではない。順序raceの原因は未確定のまま保持する。

手動job rerunは行わず、レビュー専用baseに作ったdraft PR149の自然なCI44251800913を同sourceの再試行1回として確認した。136b42aで7768件成功・30件失敗・259件skipとなり、既存基準とanchor比較を満たしてqualifiedだった。既存失敗やskipが解消したとは扱わない。題材訂正後の新headには改めてexact-source CIが必要で、この旧結果を継承しない。review-baseは146ecf2を指すだけで、main全体の統合や本番反映を意味しない。
