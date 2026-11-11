# 常駐 Lean と高速レーン: 検証器の固定費を消し、残る秒数を測る (2026-11-12)

目標: 大学1年レベルの回答を 10 秒以内(判定条件は親リポジトリ #137)。ここでは Lean の固定費と、自動化だけで閉じる経路の実測を扱う。フラグはすべて既定 off。検証器サービス(`http_server.py`)と本番には触れていない。

## 結論

1. **Lean の固定費は消せた。** 1 回の検証(方針検査 + コンパイル + 信頼監査)は、本番検証器と同じ Linux イメージで約 6 秒(コンパイル約 3.0 秒 + 監査)から、**コンパイル 0.8 秒 + 監査 0.5 秒**になった。10 並行でも 1.1 秒以内に全部終わる。
2. **監査は弱めずに常駐プロセスで動く。** 監査プログラム(`TRUSTED_AUDIT_SOURCE`)は 2 か所の置換だけで、同じ `.olean` 受け渡しとコンパイル後に作る nonce を保つ。16 件(拒否 4 件を含む)で cold と warm の判定が一致した。
3. **それでも 10 秒には届かない。** 通常経路の中央値は 79 秒(説明まで 90 秒)で、その約 2/3 はモデル呼び出し(Draft→Sketch→Prove の逐次、題ごとの合計中央値 52 秒)。Lean を 0 にしても 50 秒台。高速レーン(自動化だけで閉じる経路)は、閉じる題なら Lean 部分が 1〜3 秒だが、**新入生 10 題のうち閉じたのは 3 題**で、閉じない題は 5〜12 秒を無駄に使ってから通常経路へ落ちる。
4. モデルが書いた命題を使う経路は、**形式化 4〜10 秒(中央値 5.5 秒)+ 忠実さの関所 5〜6 秒**が下限で、Lean をいくら速くしても 11 秒前後になる。10 秒に収めるには、モデル側の待ち(形式化と審査)を縮めるか並べ替える必要がある。

## 1. 現状の内訳(通常経路)

別途測定: 共有ノート `baseline-breakdown.md`(題 10、各 1 回、負荷平均 12〜53、費用 約 0.29 ドル)。

| 段階 | 中央値 / p90 |
|---|---|
| パイプライン全体(説明の前) | 79 s / 153 s(説明まで 90 s / 171 s) |
| モデル時間の題ごとの合計(Draft+Sketch+Prove、Terra/medium) | 52 s / 84 s(呼び出し 5.5 回) |
| 題ごとの Lean 合計 | 20 s / 33 s |
| Lean 1 回: コンパイル + 監査(素のプロセス) | 約 3.8 s + 約 4.9 s |
| `import Mathlib` のみ | 7.2 s |
| 意味レビュー + 説明(Luna/low、逐次) | 5.0 s + 10.3 s |
| 形式化 1 回(Luna/low、単独) | 5.0 s / 6.9 s |

## 2. 設計: 常駐 Lean(`pals_agent/lean_verifier/resident/`)

**fork する zygote 方式。** Mathlib を 1 回 import した Lean プロセスが待機し、依頼ごとに `fork` した子が環境を copy-on-write で共有して、その依頼だけを処理し、結果をファイルに書いて `_exit` する。

- 選択肢: (a) REPL 型の常駐ループ(`warm_worker.lean` の方式)は速いが、プロセス大域の状態(`IO.Ref`、`exact?` の索引)が依頼をまたいで残り、暴走した 1 依頼がプロセス全体を巻き込む(設計メモ `warm-portfolio-worker-design` の指摘どおり)。(b) `--server`、(c) olean の pickle/mmap は、4.32 で環境を import 済みのまま使い回す公開された方法を見つけられず、試していない(未実測)。**(d) fork は隔離(依頼ごとに別プロセス)と速さを両立し、実測できた。**
- 分離: zygote は依頼の文面を一度も elaborate しない(親の状態は依頼に依存しない)。子は別プロセス、別プロセスグループで、CPU 制限(全 OS)と private メモリ制限(Linux の `RLIMIT_DATA`: 子が既に持つ分 + 予算。読み取り専用に mmap された `.olean` は数えない)を持つ。依頼 A が宣言した定数は、直後の依頼 B から見えないことをテストで固定した。
- 実装上の落とし穴(いずれもテスト済み):
  - fork した子には親のタスク管理スレッドがなく、通常のフロントエンドは `Task.get` で永久に待つ。共有ライブラリの `l_palsChildSetup` が `lean_init_task_manager_using(1)` で新しい管理を差し替える(`--threads=1` 相当)。
  - 旧式の逐次 `Frontend.processCommands` は 4.32 で**メッセージを黙って捨てる**(誤受理の原因になる)。使っていない。
  - 拡張の C 部分は Lean のインタプリタが `l_<名前>` で探す。Linux では `-fvisibility=default` と、`RTLD_GLOBAL` への昇格(`dladdr`+`dlopen(RTLD_NOLOAD)`)が要る。検証器イメージには libc ヘッダがないので、Linux 側は libc 関数を手で宣言している。
- 失敗は判定にならない: 子の死亡、タイムアウト、zygote の死亡、満杯は `aborted` / `timed_out` / `unsupported` / `ResidentBusy` で、呼び出し側は cold の経路に落ちる。zygote が死んだら再起動(上限 5 回、バックオフ)。`LeanVerifier` は、常駐が提供できない依頼(import が `Mathlib` 以外、別のライブラリプロファイル、Recipe 受付の literal コマンド)では従来どおり動く。
- 監査: `warm_audit_source()` が `TRUSTED_AUDIT_SOURCE` から 2 行(エントリと import)だけを置換して `auditWarm` を作る。置換前の文字列が 1 回ずつ現れない場合は例外で、監査プログラムの変更に追従し損なえない。nonce は子が終わった後に作る。
- 文面検査の層 1(許可リスト)も zygote の子で動く(`STMT`)。`warm_worker.lean` と同一の断片をテストで固定している。
- `ResidentWorker`(adapter)は、段階 0 が使う `WarmWorker` の呼び出し(`check` / `check_statement`)を子で返す。「依頼ごとに新しい clean な worker」が、Mathlib の import なしで手に入る。
- 高速レーン(`pals_agent/fast_lane.py`)と `solve_warm` の並列化: 閉じ手の全てを同時に子へ出し、受理が 1 つ出たら残りを kill する。受理の判定は従来どおり宣言ごと(error の有無と公理)。**投機的な受理は検証済みを意味しない**: 勝った手で 1 つの clean な定理を作り、既存の `LeanVerifier.verify`(方針検査・コンパイル・監査)を通ったものだけを verified とする。

## 3. 計測

### 3.1 Linux(本番検証器と同じイメージ、aarch64、8 CPU、メモリ 24 GiB の一時コンテナ)

| 項目 | 値 |
|---|---|
| zygote の起動(Mathlib import 1 回) | 6.1 s(`exact?` の索引つきは 14 s) |
| コンパイル(`.olean` 出力あり) | 0.76〜0.82 s |
| コンパイル(出力なし、`exact?` 索引は zygote が保持) | 0.18〜0.22 s |
| 信頼監査 | 0.48 s |
| 10 並行の最大 | 1.09 s(全体 1.11 s) |
| 比較: 現行の cold コンパイル(`lake env lean`) | 2.9〜3.0 s(1 回目 5.5 s) |
| zygote の RSS | 8.3 GB(うち読み取り専用の `.olean` 6.3 GB、private 2.0 GB)。`exact?` 索引つき 10.1 GB |
| 子 1 つの private メモリ | 6〜14 MB(索引つき) / 200〜220 MB(索引なし) |
| `exact?` を子で初回実行 | 20.7 s・private 2.0 GB(索引つきなら 0.18 s・6 MB) |
| 10 並行の cgroup 使用量(ピーク) | 約 5.0 GB(zygote 込み) |
| 暴走した確保(300M 要素の `List`) | 子だけが約 6 秒で打ち切られ(`aborted`)、zygote と次の依頼は無事 |
| 暴走ループ | 3 秒の期限で kill、次の依頼は通る |

### 3.2 Mac(共有機、負荷平均 11〜21。ただし常駐と cold を同じ条件で比べた)

`scripts/eval/bench_resident.py`: 16 件(通る 12、拒否 4: 誤った主張、未解決のゴール、`variable`/`include` による命題の差し替え、記法の再定義)。各件を `LeanVerifier.verify`(方針検査 + コンパイル + 監査)に通す。

| | 単独 p50 / p90 | 10 並行 p50 / p90 |
|---|---|---|
| cold(現行) | 15.8 s / 17.0 s | 35.9 s / 36.8 s |
| 常駐 | 1.33 s / 1.41 s | 1.80 s / 2.04 s |

判定(成功の可否と error の診断コード)は **16 件すべて一致**。`variable`/`include` の件は両方で `lean.statement_mismatch`(常駐の監査が命題の結び付けを検出)、記法の再定義は方針検査が先に拒否。

### 3.3 高速レーンの end to end(段階 0 を常駐上で。Mac、負荷平均 12〜18)

`scripts/eval/run_fast_e2e.py`。tuning の題: easy 13 + medium 8(medium は 5 題で打ち切り: 題 id の短縮表記の不具合、修正済み)。計 18 題、各 1 回。モデルは形式化・審査・往復が Luna/low、費用 約 0.1 ドル未満。固定命題あり 5 題、なし 13 題。

| 結果 | 題数 | 内訳 |
|---|---|---|
| 答えた(Lean の閉じ手 + 忠実さの関所 + 既存の検証器の監査が成功) | 3 | 固定命題 2 題(`exact?`)、形式化 1 題(`positivity`) |
| 証明は閉じたが説明の雛形がない(`verified_needs_explanation`) | 1 | `norm_num` |
| 通常経路へ落ちた | 14 | 閉じ手なし 10、形式化が説明依頼/不成立 2、忠実さの関所が不合格 2 |

誤答(verified なのに誤り)は **0**。ただし n が小さく、関所が不合格にした 2 題の中身は別途確認していない。

時間(秒):

| | 値 |
|---|---|
| 固定命題で答えた 2 題: 閉じるまで / その後の既存検証器(コンパイル + 監査) / 表示まで | 2.3・2.9 / 1.1・1.2 / 3.4・4.1 |
| 形式化で答えた 1 題: 形式化 5.8 + 閉じ手 0.3 + 関所の追加 5.3 + 監査 0.6 | 12.2 |
| 形式化の呼び出し(2 回並行、待ちは遅い方): 中央値 | 5.5(2.6〜9.7) |
| 閉じなかった題が通常経路へ落ちるまでに使った時間 | 中央値 5.7、最大 12.5 |
| 参考: 常駐の子 + 逐次 + `exact?` 索引なしで先に行った run(9 題)の落ちるまで | 2.8〜12.6(閉じた題は `norm_num` の 1 題だけ、`budget_exhausted` が 7) |

参考(常駐の逐次、`exact?` の索引なし): 固定命題の 2 題が `budget_exhausted`(6 秒の予算で閉じ手を試し切れない)。**並列化と索引の保持で、同じ 2 題が 2〜3 秒で閉じた。**

## 4. 10 秒までに残る秒数と、それを消す手

| 段階 | 今 | 消す手 | 状態 |
|---|---|---|---|
| Lean の起動 + import(コンパイルと監査で 2 回) | 約 8 s | 常駐 zygote | **この PR** |
| 監査 | 約 5 s | 常駐の子で監査 | **この PR**(0.5 s) |
| 自動化の逐次試行 | 〜12 s | 並列 + 索引の保持 | **この PR** |
| 形式化(モデル、NL の依頼) | 中央値 5.5 s | 固定命題があるときは不要(カタログ)。モデルを速いものにする、または Draft の出力に形式命題を含めて 1 回で済ませる | 未 |
| 忠実さの関所(審査 + 往復) | 5〜6 s | 形式化の直後に審査を投機的に並べる(Lean と並行)のは済んでいるが、形式化→関所の直列が残る。形式化と同時に「依頼の言い換え」を先に作らせて並行にする | 未 |
| Draft→Sketch→Prove(通常経路) | 52 s | 別セッションの並列候補レーン(39.5 s)。**自動化で閉じない題の大半はここ** | 別 |
| 説明(モデル) | 10.3 s + 審査 5.0 s | 閉じ手の雛形があれば 0 s。なければ並列化/短縮 | 一部 |
| 検証器の HTTP・SQS・poll(固定 1 s の poll、ワーカーの 2 s アイドル) | 未測定 | — | 未測定 |

見立て: **自動化で閉じる題(固定命題あり)は、新入生レベルでも 4 秒前後で verified まで行ける(今回 2 題)。モデルが命題を書く題は、形式化 + 関所だけで 11〜12 秒**で、Lean を無限に速くしても 10 秒には入らない。自動化が閉じない題(今回 18 題中 14 題)は、通常経路の 50 秒以上が支配する。**10 秒目標を中央値で満たす見込みは、現状のモデル構成では無い。** 満たすには、(a) 自動化のカバレッジを上げる(Mathlib の補題検索が主力で、カタログ拡張は停止中)、(b) 形式化と関所を 1 回の呼び出しにまとめる/速いモデルにする、(c) 通常経路のモデル呼び出しを 1 回にする、のいずれかが要る。

## 5. 本番に載せるときの手(検証器サービス側)

`http_server.py` の変更は**不要**。`create_server` は `LeanVerifierPort`(`verify(lean_code)`)を受け取るだけで、常駐は `LeanVerifier(resident=...)` の内側で効く。必要なのは `http_runtime.py` の組み立て(担当と調整):

```python
# PALS_LEAN_RESIDENT=true のときだけ(既定 off)。
resident = ResidentLean(ResidentConfig(
    lean_binary=<固定 toolchain の lean>, lean_path=<LEAN_PATH を起動時に 1 回解決>,
    build_dir=<専用ディレクトリ>, max_children=settings.max_concurrent_compiles,
    project_dir=settings.project_dir,            # LeanVerifier がこれと一致するときだけ使う
    confine=True, request_root=Path("/run/pals-verifier-requests"),
    read_roots=default_read_roots(<lean>, <LEAN_PATH>), warm_exact=True,
    prebuilt_shim=<イメージのビルド時に作った .so>, allow_shim_compile=False,
))
resident.start()                     # 約 6 s。ready marker はこの後に作る
verifier = LeanVerifier(..., resident=resident)      # proof-job 用のみ。admission 用には付けない
```

- 同時実行: `MAX_CONCURRENT_COMPILES`(上限 2)は、cold の Mathlib 1 プロセスが約 7〜9 GiB で PID 64 に収まらなかった理由の上限。常駐では子 1 つが 200 MB 前後・数 PID なので、**10 並行は zygote 1 つ + 子 10 で足りる**(cgroup 約 5 GB)。ただし上限 2 の定数と `compile_slot` は `http_server.py` 側にあり、上げるには所有者の変更が要る(これが 10 並行の本番での唯一のブロッカー)。
- メモリ(`docker run --memory` 8g と 6g、swap なし、検証器イメージ): zygote が RSS 8.2 GB(読み取り専用の `.olean` 6.3 GB は page cache で回収可能、private 2.0 GB)、`exact?` の索引つきで RSS 10.1 GB(private 3.8 GB)。10 並行のコンテナ使用量のピークは、索引なしで 4.0〜4.3 GB、索引つきで 4.1〜4.5 GB で、**6 GiB でも 8 GiB でも OOM なく完走**した(子の private は 5〜220 MB)。`exact?` を索引なしの子で初回に動かすと 2.0 GB・20 秒なので、10 並行で `exact?` が走る運用では `warm_exact=True` にする(索引なしだと最悪 20 GB)。`child_memory_bytes` の既定は 3 GiB(`exact?` の冷実行 2.0 GB を許す上限)で、子が上限まで使う最悪の和ではなく、実測の典型(0.2 GB × 並行数 + zygote)でコンテナを決める。page cache が回収される分、cgroup が狭いと `.olean` の再読込で遅くなる可能性があるが、6 GiB では計測した時間(コンパイル 0.5〜0.6 秒)に差は出なかった。
- 隔離(`ResidentConfig(confine=True, request_root=..., read_roots=...)`、Linux、既定は off):
  - zygote は起動時に `no_new_privs`、Landlock(読み取りは toolchain・`LEAN_PATH`・システムライブラリ、書き込みは `request_root` と自分の scratch のみ)、seccomp(socket 系、`kill`/`tkill`/`tgkill`/`rt_sigqueueinfo`/`pidfd_send_signal`、`ptrace`、`process_vm_*`、`fcntl` の F_SETOWN 系)をかける。`libseccomp.so.2` を `dlopen` する(cold の `lean_child.py` と同じ依存)。**できなければ zygote は起動しない(fail closed)。**
  - 各子はさらに、Landlock で**自分の依頼ディレクトリだけに書き込み**(読み取りは runtime と自分の `/proc/self` のみ。他依頼のファイルや `/proc/<pid>` は読めない)、seccomp で `fork`/`vfork`/`clone`(スレッド以外)/`clone3`/`execve`/`execveat`/`setsid`/`setpgid` を拒否する。**子孫を作れない**ので、`setsid` した生き残りが reference・`.olean`・出力を後から書き換える経路はなく、プロセスグループ kill で足りる。cgroup や PID namespace は要らない。`RLIMIT_FSIZE`(16 MiB、cold と同じ)、`NOFILE` 1024、`CORE` 0、CPU 制限、private メモリ制限(`RLIMIT_DATA`)、`PR_SET_PDEATHSIG`(zygote が死ねば子も死ぬ)を設定する。zygote 自身も、マネージャが死ねば `PR_SET_PDEATHSIG` で死ぬ。
  - 検証(ローカルの検証器イメージ、Docker 既定の seccomp、`tests/unit/test_resident_confinement.py` の 9 件): 他依頼のファイルの読み取り・上書き、zygote への `kill`、プロセスの起動、`/proc/<zygote>/environ` の読み取りがすべて拒否される。自分のディレクトリへの書き込みは通る。2 つの攻撃と良い依頼を 10 並行で混ぜても、良い依頼は全部通り、攻撃は全部失敗し、他依頼のファイルは無傷で zygote は生きている。40 MB の出力は子が打ち切られ、次の依頼は通る。壊れた実行ファイルは有限回(5 回)の再起動のあと使用不可になる。
  - `lean_child.py` は使わない。zygote に必要なのは依頼ごとに新しいディレクトリへの書き込みで、`lean_child.py` は 1 つの `pals-lean-*` ディレクトリを起動時に固定する設計のため。
- 起動時の C コンパイル: `python -m pals_agent.lean_verifier.resident.build --lean <lean> --out <path>` をイメージのビルド時に実行し、`ResidentConfig(prebuilt_shim=<path>, allow_shim_compile=False)` で使うと、本番に C コンパイラも書き込み可能なディレクトリ(shim 用)も要らない。
- 監査を常駐でやる前提: 監査に渡す `.olean` は子が書く。常駐の子は `writeModule` で書くが、cold のコンパイルが書く `.olean` との同一性(imports の列、定数の列)は 16 件の判定一致で確認しただけで、バイト列の一致は見ていない。

**有効化の前に残る条件**(この PR は既定 off のまま):
1. 本番の実際の境界(ECS/Fargate の seccomp、x86_64)での確認。この PR の検証は aarch64 のローカルイメージと Mac。
2. 本番 `LeanVerifier` を通した攻撃の再現(ここでは常駐に直接ソースを渡した。本番では方針検査が先に拒否する)。
3. cold と常駐の判定比較を、より大きな集合で(いまは 16 件)と、fork の安全性の長時間の負荷試験。
4. `http_runtime.py` の接続(`confine=True`、`request_root` は `/run/pals-verifier-requests`、`read_roots`、`prebuilt_shim`)。起動時の `libseccomp`/Landlock の検査をヘルスチェックに含める。

## 6. 限界(正直に)

- 常駐の効果は 2 つの条件で測った: Linux の本番イメージ(負荷の低い Docker)と Mac(負荷が高い共有機)。**本番の実機(Fargate など)ではない。**
- Mac の cold は `lake env` の環境再利用なしで、本番の `PALS_LEAN_REUSE_LAKE_ENVIRONMENT` が有効なら cold は少し速い(1.2 s の `lake env` 起動分)。それでも 3 秒台の import と 5 秒の監査は残る。
- end to end は n=18、各 1 回、負荷あり、`pq` の日本語題で形式化が説明依頼になるなど、題の選び方の影響が大きい。**#137 の条件での判定ではなく、10 秒の達成を主張するものではない。**
- 通常経路との比較は、別セッションの測定(題 10、5 分野、1 回)と、同じ題・同じ条件ではない(高速レーンの 18 題のうち 9 題が、通常経路の 10 題と重なる)。
- 検証済みの誤答 0 は、閉じた 3〜4 題に対する数字。
- zygote の再起動中は cold に落ちる(その間は従来の遅さ)。起動 6〜14 s は、ready marker を待つ前提。
