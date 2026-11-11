# 段階0の本番接続設計(2026-11-11)

状態: 設計案。コードは変更していない。[確認]=読んだ事実(file:line)、[推測]=ここからの推論。
前段: [stage0-lane-2026-11-11.md](stage0-lane-2026-11-11.md)、[warm-portfolio-worker-design-2026-11-11.md](warm-portfolio-worker-design-2026-11-11.md)(常駐ワーカーの隔離設計は後者に既にある。本書は重複を避け、差分と source policy の突き合わせだけ書く)。

## 読んだリビジョン

- pals-agent: この worktree(HEAD 2deed7d + 未コミット差分)。
- pals-api: worktree 側は空ディレクトリ。メイン checkout `pals-api` は main@0f4b3cc(2026-10-05、origin/main に78遅れ)で、Recipe 系の証拠(`recipe_exact_input_correspondence` など)が入っていない。このため2つを読んだ。
  - 契約・DB・精算: 親が記録している 430aa19(`git show` で読み取り)。
  - instantiation 系: `origin/claude/seq27-response-language`@7a89ece(2026-11-08)。`recipe_instantiation_evidence.py` はここにしかない([確認] 430aa19 には無い)。**現行の本番 API がどちらかは未確認。**
- pals-webfront: メイン checkout は main@bb36ac3(2026-10-05、古い)。親の記録 c4593de(`git show`)を読んだ。

## 1. API の証拠契約

### 1.1 現状(確認)

- 回答の種類は閉じた4値。`evidence_kind: Literal["llm_assessed","reviewed_explanation","lean_catalog","lean_verified"]`(430aa19:`proof_request_contract.py:247`)。`lean_portfolio` は **スキーマで 422**。
- DB にも CHECK がある: `proof_request_lean/001_lean_flow.sql:6`(llm_assessed / lean_catalog / lean_verified)、`chat_experience/001_chat_experience.sql:42`。[推測] 新種別は migration が要る。
- `lean_catalog` は `LeanEvidence(source="catalog")` に Recipe の id・revision と、entry / answer / compiler_receipt / toolchain の4つの sha を全部束縛する(`:196-230`、`:289`)。`lean_verified` は `source="proof_job"` で proof job に束縛(DSP 経由で検証器が検証)。
- 精算 `POST /internal/proof-requests/{id}/settlements`(`proof_requests.py:279-299`)。`lean_catalog` で entry sha が無いと、API が自分の Recipe 読み取りで一致を探し、無ければ DSP の `formal` 計画に切り替える(`_verified_catalog_settlement` `:442-469`)。**worker の申告だけでは承認しない設計。**
- 固定プロファイル `recipe_exact_input`: API 側に ENTRY_SHA、LEAN_SHA、TOOLCHAIN_SHA が定数であり、依頼文もハードコード(`recipe_exact_input.py:120-239`)。利用者の言葉から作る形式命題には使えない。
- instantiation(seq27 ブランチ、`recipe_instantiation_evidence.py`):
  - worker は判断(どの Recipe、どのリテラル、その instance が依頼の命題か)だけを出す。API が自分の封印済み Recipe のバイトから instance の source、命題、表示文を**再導出**する(`:1-8`、`derive` `:96-110`、`validate` `:170-218`)。
  - Lean の compile は API 自身の `recipe_instance_compile` 記録だけが証明する。worker の証拠は使わず、`recipe_instance_verifier` で API が再検証して書く(`proof_requests.py:481-531`、`recipe_instantiation_evidence.py:221-231`)。検証器が無い、またはフラグ `recipe_instantiation_enabled` が off なら承認せず DSP へ落とす。
  - 回答の独立審査(`token_qa`/`answer_qa`)が、表示文の sha を承認していること。
- トークン精算: `lean_catalog` は「`token_answer_qa`(gpt-6-luna)の成功した呼び出しが 1 回以上」かつ `qa.call_id` が一致して初めて consume(`token_accounting.py:502-545`、430aa19)。例外は API 解決の exact_input 免除だけ。Lean の job は `settle_lean` が受領証付き呼び出しだけ課金する(`:548-585`)。**モデル呼び出しの id を持たない証拠は精算できない。**
- 他の分岐: `chat_routing.py:65` は `lean_catalog`/`lean_verified` に route=lean を要求。`guest_chat.py:259` は `lean_catalog` だけ通す。`chat_shares.py:108`、`guest_chat.py:203`、`proof_requests.py:774` も種別を列挙している。[推測] 新種別は全部の列挙箇所を探して足す必要がある。

### 1.2 段階0の現状の穴(確認)

- `Stage0Result.evidence()`(`stage0.py:59-86`)は種別 `lean_portfolio`、`formal_statement_sha256`(形式命題そのものは入っていない)、`closed_by`、`cited_lemma`、ゲートの各判定、`model_calls`(**整数の回数だけで、call id が無い**)、`seconds` を出す。
- 回答に `lean`(束縛)が無い。Recipe の sha も、toolchain も、検証器の受領証も無い。`stage0_input`(`proof_reuse.py:979-997`)は `evidence_kind: "lean_portfolio"` で、`lean` を付けない。
- モデル呼び出しは `gate.ModelCall` 経由で、トークンメーター(`meter.last_call_id`、`proof_reuse.py:777,841`)を通っていない。**今のままでは精算できず、レート制限・予算の対象外になる。**
- ワーカーの `#print axioms` の出力を判定に使っている。これは**本番の検証器の受領証ではない**(試作のウォーム worker)。

### 1.3 段階0の回答が API に受理されるのに必要な項目(推測)

| 項目 | 内容 | 誰が決めるか |
|---|---|---|
| 種別 | 新 `lean_portfolio_instance`(または既存 `lean_verified` を再利用しない。下の注)。`lean.source` も新値 | API の契約 |
| 引用する一般定理 | Recipe 由来: `recipe_id`、`recipe_revision`、`entry_sha256`(封印済み)。Mathlib 由来: 補題名と、Mathlib/toolchain の固定 | Recipe は API の封印値と照合。補題名は API が**自分の検証器で**`#check` を行い、型が instance に使えることを確認 |
| instantiation / closer | Recipe なら bindings(既存契約を流用)。ポートフォリオなら「閉じた手」(tactic 名)と、`exact?` が返した項 | API が再導出または再 compile |
| 検査した形式命題とその sha | **命題の本文を証拠に含める**(今は sha だけ)。`formal_source` = `given` / `formalised` | API が文法で再検証し、sha を再計算 |
| 「未検証の形式化」ラベル | `formal_source=formalised` のとき必須。表示文の固定文言(`portfolio_explanation.py:154-156`)の有無を API が決定的に検査 | API |
| ゲートの判定 | 各検査(一致、意味審査、往復、構造語、自明性)の結果と、**モデル呼び出しごとの call id**(形式化2回、意味審査、往復2回) | API がトークン台帳の call と突き合わせ |
| toolchain 指紋 | Lean 版、Mathlib rev。`recipe_toolchain_sha256` と同じ形 | API の有効 toolchain と一致 |
| 検証器の受領証 | `lean_sha256`、`verification_succeeded`、リリース束縛(`http_server.py:440-448,372,404`) | 検証器が出し、API が保持 |

注: `lean_verified` を再利用すると、web が「Lean 検証済み」と読む(2節)。モデルが書いた命題を含む回答には使わない。種別を分けるほうが安全。[推測]

### 1.4 API は命題を自分の検証器で再検証すべきか

**する(必須)。** 根拠: 契約の思想は「worker を信用しない」(`proof_requests.py:445`、seq27 の docstring)。段階0は worker が(a)命題を書き、(b)ウォーム Lean で証明し、(c)ゲートの結果を申告する。どれも worker 内で完結するため、そのままでは申告にすぎない。[推測] 再検証の中身:

1. 命題は `statement_grammar`(許可リスト文法)で API が再検査。通らなければ DSP に落とす。
2. API が自分で `theorem … : <命題> := by <closer>` を組み立てて本番の検証器に送り、`recipe_instance_compile` と同じ形で API 所有の受領証を保存する。**worker が申告した source は使わない。** closer は閉じた表から選んだ決定的なものだけ(`exact?` の結果は、返された項そのものを固定して送る。探索を再実行させない)。
3. `#print axioms`(監査)は検証器の事後監査(olean 再生と `collectAxioms`、`lean_audit.py`)に任せる。
4. 忠実さ(命題が依頼の意味か)は Lean では確かめられない。ゲートは worker 申告のままなので、API は(a)モデル呼び出しが台帳に実在し成功していること、(b)判定が全部 pass で矛盾が無いこと、(c)ラベル付きで表示することまでしか保証できない。**これは検証済みの主張ではなく、「検証済みの命題に対する、未確認の形式化」と表示する。**
5. 検証器が使えない場合は承認せず通常のパイプライン(DSP)へ落とす(seq27 と同じ fail closed)。

## 2. 利用者への見せ方

読んだ事実(webfront c4593de):

- 種別は閉集合で、**未知の種別はスキーマ検証で例外**。`lib/api/proofRequests.ts:47`(`evidenceKinds`)、`:142`(`Invalid proof answer`)、`:9`(型)。API が新種別を返すだけでは画面が壊れる。
- `validLean` は `lean_catalog` なら `source==="catalog"` と Recipe 束縛を、それ以外は `proof_job` 束縛を要求(`:52-62`)。新 `lean.source` も拒否される。
- バッジの出し方は2つだけ。`llm_assessed` →「AIの回答・Lean未検証」(`GuestChat.tsx:125`、`guestMessages.ts:25`)。`verdict==="refuted"` → `leanRefuted`(`ProofRequestThread.tsx:~154`、`GuestChat.tsx:126`)。`lean_catalog`/`lean_verified` の回答には、**「Lean 検証済み」を明示するバッジは現状ほぼ無く**、Lean ソースの参照パネル(`hasProofRequestLeanSource`、`ReferencedLeanSourcePanel.tsx`)の有無で暗黙に表される。ただし `guestMessages.ts:27` に `leanVerified` 文言はある(使用箇所は未確認)。
- 参照パネルは proof_job / catalog の Lean ソースだけを引ける(`proofRequests.ts:68-77`)。

見せ方の案(推測):

- 回答本文の上または直下に、固定の注記枠を出す。内容は(1)「この命題は自動で作った形式化で、依頼との一致は人が確認していません」(2)Lean が証明したのは**この命題**であって、あなたの文章ではない、(3)引用した一般定理(Recipe 名、または Mathlib 補題名)(4)形式命題の本文(コード表示、コピー可)。
- 与えられた命題(カードや文法由来、`formal_source=given`)は(1)を出さず、現行の `lean_catalog` と同じ見せ方にそろえる。
- **主張してはいけないこと**: 「Lean で検証済みの証明」「証明済み」とだけ書くこと。モデルが書いた命題では、検証済みなのは形式命題であり、依頼の意図への一致ではない。バッジは「形式命題は Lean が検証、依頼との対応は未確認」と分ける。

## 3. 本番の検証器が温存 portfolio worker に提供すべきこと

隔離方式の骨格(Landlock・seccomp・subreaper・503・mTLS)は warm-portfolio-worker 設計メモ 1〜5 節にある。ここでは source policy との突き合わせ([確認]、実際に `find_source_violation` を呼んで確認した)と差分だけ。

| 段階0が使うもの | 現行 `lean_source_policy.py` | 判定 |
|---|---|---|
| `#print axioms`(`automation_portfolio.py:187,568`) | `_NUMBER_SIGN_COMMAND`(`:20`、`:172`)で `lean.disallowed_interactive_command` | **拒否される** |
| `set_option maxHeartbeats N in` | 許可(`_ALLOWED_OPTIONS`、`:105-115`)。値の上限なし。`0`(無制限)も通る | 通るが**上限が無い**。worker 側で `withHeartbeats` 等の上限を被せる |
| `exact?` | 拒否規則なし(通る)。検索は ~6 コアと索引構築(数秒) | 通る。専用 worker に分ける(メモ 4 節) |
| `grind`、`aesop`、`nlinarith`、`decide`、`omega`、`norm_num`、`bound` | すべて通る。`aesop` は規則追加だけ制限(`_aesop_violation`)。`polyrith` は拒否 | 通る |
| `native_decide` | `_NATIVE_EVALUATION` で拒否 | 使わないので問題なし |

要件(推測):

1. **判定の方法を変える**: 受領証を `#print axioms` の出力にしない。検証器の方式(`lean_audit.py` の olean 再生、`collectAxioms`)に合わせるか、worker 内で `#print axioms` を許可した別の信頼経路にする。source policy の `#` 禁止は緩めない(ユーザー由来の source には必要)。worker が自分で組み立てた固定のテンプレートだけを、policy の外側で扱う案がある。ただし**そのとき、命題部分にだけ policy をかけること**が必須(命題は `statement_grammar` で済む)。
2. **リクエストごとの隔離**: 同じ import 済み環境から、`Command.mkState env` で毎回新規の状態を作る。名前空間・属性・`instance`・`open` の漏れを防ぐ(メモ 4 節)。命題と closer は別の宣言で、先頭を `_` にした試行用の名前とする(`stage0-lane` の `_pals_ref` の方式)。
3. **時間の制限**: wall(supervisor が SIGKILL)と heartbeat の2本立て。worker の CPU rlimit は累積するので使えない(メモ 3 節)。heartbeat は worker 側で全体に上限を被せる(`lean.py` / `lean_child.py` / `lean_supervisor.py` / `sandbox.py` に heartbeat の上限の設定は無い。`sandbox.py:126` は `RLIMIT_CPU` のみ)。
4. **error の拒否権**: 重大度が error のメッセージが1つでもあれば不採用(ハートビート超過では `sorryAx` が出ないことがある)。現行は `lean.py:455-478` の `success = returncode==0 and not any(error)`、`declaration uses sorry` も別に見る。ウォーム worker の `check` は文字列だけを返すので、重大度を構造化して返す。
5. **kill と再起動**: wall 超過、出力上限、応答なし、RSS 超過で worker ごと kill、境界で再起動。`exact?` の索引は再起動のたびに数秒(`prewarm_search` が必要)。再起動中は 503 を返し、判定にしない。N リクエストごとの再起動値は実測してから決める。
6. **同時実行**: 現行の枠は `MAX_CONCURRENT_COMPILES = 2`(`http_server.py:57`)、満杯なら待たせず 503(`:412-414`)。段階0の1 worker = 同時1。プール数を増やす前にこの上限と cgroup の memory を見直す。
7. **http_server.py の変更点**(別の担当者が所有。**編集しない**):
   - `POST /v1/verify` は `lean_code` と `proof_job_id` を要求し、1リクエスト=1プロセス(`:391,418`)。ウォーム worker には、`/v1/portfolio/verify` のような別経路(`statement`、固定 closer の表の ID、timeout)が要る。
   - 応答は `lean_sha256`、`verification_succeeded` のみ(`:440-448`)。段階0用に、closer 名、引用した補題名、`toolchain_fingerprint_sha256`、worker の世代を足す。
   - リリース束縛(`Pals-Release-Id`、`:372,404`)と mTLS は新経路にも同じに適用する。
   - ウォーム worker のプロセス管理(起動、prewarm、準備完了 `ready`)は `http_runtime.py` に足す。

## 4. 後続 PR の順序(すべてフラグ既定 off)

| # | リポジトリ | タイトル | 範囲 | 依存 | フラグ |
|---|---|---|---|---|---|
| 1 | pals-agent | stage0 の証拠を精算可能にする | モデル呼び出しをトークンメーター経由にし、call id を証拠に入れる。命題本文、toolchain、closer、引用定理を `evidence()` と回答 `lean` に足す。受領証は API が出すまで空 | なし | `PALS_STAGE0_PORTFOLIO`(既存) |
| 2 | pals-agent | 検証器へのウォーム portfolio 経路 | 3節の1〜6。`#print axioms` を使わない判定、リクエストごとの状態、heartbeat 上限、error 拒否権、kill と再起動、構造化した結果。`lean_verifier/` は別担当と調整してから | 1 | `PALS_LEAN_PORTFOLIO_VERIFIER` |
| 3 | pals-api | 新種別 `lean_portfolio` の契約と migration | `AssessedAnswer` と `LeanEvidence` に新種別・新 source、DB CHECK、種別の列挙箇所(chat_routing、chat_shares、guest_chat、proof_requests)。承認は未実装のまま常に DSP に落とす | なし | `PALS_API_STAGE0_ENABLED` |
| 4 | pals-api | 精算での再導出と再検証 | 命題の文法再検査、API 所有の検証器での closer 再 compile、`recipe_instance_compile` と同形の記録、call id と台帳の突き合わせ、ラベルの決定的検査。検証器が無ければ DSP | 2、3 | 同上 |
| 5 | pals-webfront | 新種別の受け入れと注記枠 | `evidenceKinds`、`validLean`、型、注記枠(形式命題、ラベル、引用定理)、4言語の文言。未知の種別でも画面を壊さない(縮退表示)ようにする | 3(契約) | `NEXT_PUBLIC_STAGE0_EVIDENCE`(構想) |
| 6 | pals-agent | `stage0_input` の本番接続 | API の新契約で精算、失敗は常に通常パイプラインへ。段階0の予算(形式化する場合 12 秒)と `deadline` の関係を維持 | 1〜4 | `PALS_STAGE0_PORTFOLIO` + `PALS_GENERAL_RECIPE_LANE` |

注: 5 は 3 の契約が決まれば 4 と並行できる([推測])。web の「未知種別で壊れない」修正(5 の一部)は、API を出す**前**に出す必要がある(順序を逆にすると、既存画面が例外になる)。

### ロールアウトの順序

1. PR 5 の縮退部分(web が未知種別を許容)を先にデプロイする。
2. PR 3 → PR 4(API。フラグ off で承認しない)。API 側の台帳との突き合わせは、先にテスト環境で検証する(AWS staging は作らない。ローカルとモックの境界を明示)。
3. PR 1 → PR 2(agent と検証器。検証器のリリース束縛を更新)。
4. 内部のみ・ごく一部でフラグ on。有料の実評価は 1 回 1 ドル以下の方針に従い、通常のリリース手順(`make release-local-qualify`、cutover の時間制約)に載せる。
5. 以降は日次の誤答率を見る。誤答(依頼と違う命題を答えた)が1件でも出たら、`formal_source=formalised` の経路だけを止める(`given` は残せる)。

## 未確認

- 現行の本番 API がどのリビジョンか(seq27 の instantiation が入っているか)。
- 配備済みの webfront に `lean_*` の明示バッジがあるか(c4593de には無い)。
- 精算時に API が検証器へ新経路を呼べる権限・ネットワークの設計(別担当の `http_server.py` と同時に決める必要がある)。
