# 依頼文法の語彙を広げ、実数・有理数・整数パラメータを束縛する (2026-11-07)

## 目的

語彙が冪と連続性だけ、パラメータが自然数だけだった。語彙表(`request-grammar-v1.json`)の行の追加で広げ、Recipe の束縛を Nat/Int/Rat/Real に広げる。

## 追加した行

| 種類 | id | 受け付ける書き方(例) |
|---|---|---|
| 関数 | exp | `e^x` `e^{x}` `e^(x)` `exp(x)` `exp x` `eˣ` |
| 関数 | sin / cos | `sin x` `sin(x)` `sinx` `sine of x` `xの正弦`。`sinh` `arcsin` は読まない |
| 関数 | abs | `\|x\|` `abs(x)` `absolute value of x` `xの絶対値` |
| 関数 | sqrt | `√x` `sqrt(x)` `square root of x` `xの平方根` `ルートx` |
| 関数 | scaled | `3x` `3*x` `2.5·x` `5 times x` `xの2倍`(係数は decimal、0 は不可) |
| 関数 | affine | `2x+1` `1.5x + 2.5` `x + 2` `3 + 2x`(プラスのみ) |
| 性質 | uniformly_continuous | 連続より前に置く。`一様連続` `uniformly continuous` `一致连续` |
| 性質 | differentiable | `微分可能` `differentiable` `可导` |
| 性質 | strictly_increasing | `狭義単調増加` `strictly increasing` `严格单调递增` |
| 性質 | monotone | `広義単調増加` `nondecreasing` `weakly increasing` `单调不减` |
| 性質 | injective | `単射` `injective` `单射` |

冪の書き方も増やした(`x**2`、`x raised to the 4th power`、`The 5th power of x`、`xの立方`)。変数は `s t u v w x y` だけ。`e` `n` `k` `m` `z` と大文字は受理しない。

## 文法の仕組みの変更

- slot の種類 `decimal`(`0|[1-9]\d{0,8}` と、省略可の `.\d{1,6}`)。form ごとに `lean_body` を上書きできる。
- 異なる関数のマッチが部分的に重なるときは曖昧として miss。包含のときだけ長い方を採る(`2*x^3` の中の `x^3`)。
- 関数名だけの form(`name_only`)は、同じ関数で本体が一致する式の横でだけ消費する(`the fourth power function x⁴`)。名前だけで依頼になるのは `alone` が偽でない行だけ(`squaring function`、`平方関数`、`二乗関数`)。`the square function` は他の対象も指すため、名前だけでは受理しない。
- 提示・言語の指示は、既存の閉じた表(`presentation-instructions-v1.json`)で先に取り除く。語彙表の側にも「Keep it short」「箇条書きで」などを足した。
- 同じ性質を2回言っても1つの主張とする(`strictly increasing (strictly monotone increasing)`)。
- 領域の言い回し(`(x ∈ ℝ)`、`for x ∈ ℝ`、`(-∞, ∞)`、`where the domain is the reals`、写像記法 `x ↦ x^2`、Lean 直書き `Continuous (fun x : ℝ => x ^ 2)`、中国語の router 長文)を足した。
- `'` は区切りから外した。`(x^2)'` を `x^2` と読まないため。

## 束縛(`bind_recipe`)

- Nat/Int/Rat/Real のパラメータを扱う。整数リテラルは従来どおり hint として出す。
- 小数リテラルは hint を出さない(空の束縛。Lean の単一化が決める)。複数パラメータのうち1つでも小数なら、全ての hint を出さない(部分的な代入を主張しない)。
- 実数・有理数・整数のパラメータが `^` の直後にあるときは束縛しない。表は自然数の冪しか書かない。
- 複数パラメータ、同じパラメータの繰り返し、現れないパラメータは従来どおり。

## 意図して miss にしたもの

- 係数つきの冪 `3x^2`(表の追加で足せる。テストに追加例がある)。盲検コーパスは miss を期待している。
- 減算 `2x-1`(`2*x - 1` と `2*x + -1` の書式差)。
- 負の係数、`0x`、`x/2`、`(1/2)x`。
- 単独の `単調増加` `monotone increasing` `increasing` `one-to-one` `1対1`。
- 名前だけの `the sine function`、`exponential function`、`指数関数`。
- `exp is strictly increasing: e^x ...` のように、未適用の `exp` を含む文。

## 検証

- 盲検コーパス(487件)を `EVALUATED_SCOPES = ("current", "widened")` で評価: 誤った命題を返す件数 0、曖昧の受理 0、カバレッジ 217/218。
- 全組み合わせ(関数 x 性質 x 変数文字 x 数値)492 命題を、固定版 Lean 4.32.0-rc1 と Mathlib の1プロセスで `#check (p : Prop)`。拒否された命題は0。冪はすべて自然数の指数で elaborate される。拒否される対照行が検出されることも同じテストで確認。
- 注意: 命題が整形式であることと真であることは別。`|x|` の微分可能性、`√x` の微分可能性、`x^2` の狭義単調増加などは整形式だが偽で、Recipe に束縛されず Lean でも証明できない。
