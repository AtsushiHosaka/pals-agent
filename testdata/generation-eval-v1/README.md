# generation-eval-v1: 生成側の固定評価セット

Lean 生成（初回コンパイル、最終成功、修復回数、時間、費用）の対比較に使う、100題の固定集合です。設計は親リポジトリの `specs/generation-eval/`（requirements・design・inventory）にあります。

| ファイル | 内容 |
|---|---|
| `manifest.json` | 100題。`id`、`source`、`field`、`tier`（easy/medium/hard）と `tier_basis`（observed/declared/assigned）、`split`（tuning 70 / held_out 30）、`language`、`statement`、`fixed_lean_statement`（任意）、`expected_answer`（判定・計算の題）、`tags`、`history`、`shared`（Codex の題との結合キー） |
| `SPLIT.sha256` | (id, split, 文面ハッシュ) の SHA-256。**変更しない。** 分割や文面を変えるなら `generation-eval-v2` を作る |
| `codex_shared_problems.json` | Codex の説明品質評価の20題の問い文と `fixture_sha256`（pals-observability#2、ef6065d）。参考解答は含めない |

## 使い方

```sh
python3 scripts/eval/run_eval.py validate                       # 検証（テストと同じ検査）
python3 scripts/eval/run_eval.py schedule --arms base,new --repeats 2 --split tuning
python3 scripts/eval/build_manifest.py --parent <親リポジトリ> --out testdata/generation-eval-v1   # 再生成
```

保留（held_out）は最終比較でだけ使います。`schedule --split held_out` は `--open-held-out` を付けない限り拒否します。開けたら、理由を改善ジャーナルに書き、その題を調整に使いません。

## 注意

- 文面は既存の記録（型付きカタログのカード、要求シード、Codex の登録、スキーム論の測定カード、高校・大学の候補カード）から取った**問い**です。カタログにカードは追加していません。
- `(x+y)^2` の展開は使いません（検証テストが検査します）。
- 候補カード（20題）には Lean の証明がありません。命題が Lean で成立するかは未確認で、失敗が生成の失敗か命題の問題かを `history` だけでは区別できません。
- 難度の `assigned` は手動の割り当てです。`observed` 以外の難度は、分析で別に扱えるよう `tier_basis` を残しています。
