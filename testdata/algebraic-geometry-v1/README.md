# algebraic-geometry-v1

スキーム論（学部上級から修士初年）の評価題 10 題。`generation-eval-v1` の `held_out` とは文面が重ならない独立した区分で、すべて `split: tuning`（調整・測定用）。命題の固定（`fixed_lean_statement`）は付けていない。

- 分野: アフィンスキーム、構造層、射の性質、層のコホモロジー（1 題。Mathlib に概念が無く、現状は通らない想定）。
- 実行: `scripts/eval/run_stages.py tier2 --manifest testdata/algebraic-geometry-v1/manifest.json --ids ... --answer`（有料。1 回の実行は 1 ドル以下にする）。
- 注意: 「Lean が通った」は依頼どおりの証明を意味しない。依頼どおりかは、意味レビューの承認と、定理文がスキームの命題であることで確かめる。
- 測定結果: 親リポジトリの `docs/algebraic-geometry-e2e-2026-11-14.md`。
