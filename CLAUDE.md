# 設計方針書 — 形式検証チェッカー MCP v0

このファイルは Claude Code に渡す設計指示書。 このリポジトリで 作業する際は 必ず 最初に読むこと。

## 0. このプロジェクトが作るもの

**一行を受け取り、真偽を返す検証器。** それ以上でもそれ以下でもない。

チューターではない。学習プラットフォームでもない。エージェント (Claude Code を含む) や人間が生成した式・証明の一行を受け取り、Lean4 で判定して結果を返す、単機能の MCP サーバ。

**Source spec**: [CHECKER_SPEC_v0.md](https://github.com/fc0web/rei-aios/blob/main/data/external-prior-art/checker-spec-v0-2026-08-22/CHECKER_SPEC_v0.md) (2026-08-22 archival、 chat-Claude session output)

## 1. 絶対に守る原則

### 1.1 判定経路に LLM を入れない

これがこのプロジェクトの存在理由。判定は決定的でなければならない。

- Lean4 / 既存の検証資産のみが判定を下す
- LLM は前処理 (自然言語→形式表現の変換候補生成) にのみ使ってよいが、**その出力は必ず検証器を通す**
- 「たぶん正しい」を返す経路を一切作らない

### 1.2 判定できない時は、判定できないと返す

出力は必ず三値のいずれか。例外を投げて終わらない。

| 値 | 意味 |
|---|---|
| `VALID` | 検証器が真であることを確認した |
| `INVALID` | 検証器が偽であることを確認した |
| `UNDECIDED` | 検証器が判定を下せなかった |

`UNDECIDED` はエラーではなく、**正当な戻り値**。 タイムアウト、構文非対応、公理不足、深さ制限——すべて `UNDECIDED` + 理由コードとして返す。

理由コード:
`TIMEOUT` / `PARSE_FAILURE` / `UNSUPPORTED_SYNTAX` / `MISSING_AXIOM` / `DEPTH_LIMIT` / `OUT_OF_SCOPE`

### 1.3 D-FUMT₈ を API 表面に出さない

内部で 8 値論理を使うのは自由だが、**v0 の外部インタフェースは上記三値のみ**。

理由: 利用者が D-FUMT₈ を理解しなければ使えない設計にすると、誰も使わない。まず使われること。

## 2. v0 のスコープ

MCP サーバ 1 本。ツールは **2 つだけ**。

- `verify(expression, context?, timeout_ms?) → { verdict, reason_code?, detail?, elapsed_ms, checker_version }`
- `stats() → { total, valid, invalid, undecided, decision_rate, reason_breakdown }`

### 作らないもの (v0 で 明示的に 非目標)

- UI / Web フロントエンド
- ユーザー登録・認証・課金
- ゲーミフィケーション、進捗管理、学習履歴
- 自然言語での対話・解説生成
- 複数バックエンド対応 (Lean4 のみ)
- Claude 固有の機能への依存

非目標を実装しようとした場合、**手を止めて確認を取ること。**

## 3. 唯一の指標

```
decision_rate = (VALID + INVALID) / total
```

v0 の成功条件は 「判定率が 高いこと」 ではない。 **判定率が 測れる状態に なること。** 初期値が 0.1 でも構わない。

## 4. 反証台帳

`UNDECIDED` は 捨てない。 全て記録する。

- 個人情報・利用者識別子は 記録しない
- 保存形式は 追記専用 (JSONL)
- これが 次に実装すべき機能を 決める 唯一の根拠
- `UNSUPPORTED_SYNTAX` が 集中した 構文が、 次のスプリントの 対象。 推測で 機能を 足さない。

## 5. プロトコル方針

- **MCP 仕様に対して 実装する。** Claude Desktop / claude.ai 固有の 挙動に依存しない
- stdio と HTTP/SSE の 両トランスポートを 想定。 v0 は stdio のみ 実装可、 但し I/O 層を 分離しておく
- ライセンス AGPL-3.0

## 6. 実装順序

1. Lean4 を叩いて 真偽を返す 最小の関数 (MCP なし、 CLI で 動くこと)
2. 三値 + 理由コードの 戻り値スキーマを 固定
3. 反証台帳への 追記
4. `stats()` の 算出
5. MCP サーバとして 包む
6. README (**D-FUMT₈ を 知らない人が 5 分で 動かせること**)

各段階で 動くものを 残す。 5 まで 到達しないうちに 6 の 体裁を 整えない。

## 7. 品質基準

- タイムアウトは 必ず効く。 ハングしたら `UNDECIDED/TIMEOUT`
- 不正な入力で クラッシュしない。 `UNDECIDED/PARSE_FAILURE`
- `checker_version` を 全レスポンスに含める (過去の判定の 再現性のため)
- 判定ロジックに テストを書く。 特に **`UNDECIDED` を 返すべき ケースの テスト** を 優先

## 8. 判断に迷った時

- 機能を 足すか 迷ったら、 足さない
- 「たぶん 正しい」 を 返すか 迷ったら、 `UNDECIDED` を 返す
- 理論を API に 出すか 迷ったら、 出さない
- 急がず、 ゆっくりと。

---

# v0.3.0a1 (2026-08-24、 STEP 1401) landed

- **LeanBackend Stage 1 wired** (persistent JSON REPL、 `lean_backend/.lake/build/bin/lean_checker_repl.exe`)
- **D-FUMT₈ 内部 projection** (`rei_checker/d_fumt8.py`)、 **ledger 層のみ** (spec §1.3 preserve: verify() 応答 に 出さない)
- **stats(include_d_fumt8=True) opt-in**、 default off で backward compat
- **Timeout hard-kill** (background thread + Queue、 hanging Lean process kill)
- test 105/105 PASS (v0.2.0a1 73 + v0.3 32 追加)

## v0.3 D-FUMT₈ mapping (spec §1.3 preservation の operational form)

pending-lean4-neither-mcp-connector (b) pickup。 chat-Claude 2-turn arc 「Lean4 sorry-zero 実在 + NEITHER 意味論完成 + 接続 gap」 を **ledger 経由で 埋める** approach (rei-aios STEP 1349/1350/1371/1376/1377/1379/1397 D-FUMT₈ surface と 独立、 単方向 flow)。

**spec §1.3 保護 の 3 条件**:
1. `VerifyResult` (MCP response) には `d_fumt8` field を **出さない**
2. `StatsResult` の default output も 変えない (`include_d_fumt8=True` opt-in のみ で 表示)
3. `LedgerEntry` にのみ `d_fumt8` optional field 追加 (backward compat: pre-v0.3 rows 読み込み OK)

mapping table は `rei_checker/d_fumt8.py` の docstring + `spec_table()` で 参照可能。 downstream (rei-aios MCP、 cross-project 分析) は ledger.jsonl grep で D-FUMT₈ 分布を 取得。

---

# v0.2 事前対策 (LeanBackend 実装前に 必須読み込み)

**LeanBackend stub を 実 Lean 4 backend に 差し替える前に**、 [`docs/V02_PROTOCOL.md`](./docs/V02_PROTOCOL.md) を **必ず** 読むこと。 5 protocol (A1 sandbox / A2 spawn error / A3 process tree kill / B4 --json axiom parse / C7 REPL server + D11 ERR_UNCLASSIFIED) の 事前対策を skip すると:

- A1 skip → 生徒 input による 任意コード実行 (`#eval IO.Process.run` で shell)
- A2 skip → `lean` 不在時 永久ハング (spec §7 直接違反)
- A3 skip → `lean` 孤児プロセス メモリリーク
- B4 skip → 公理検査 事実上無効化 (`#print axioms` output が JSON message 内で 未 parse)
- C7 skip → `import Mathlib.Tactic` cold start 8-15 秒 → 全 request TIMEOUT → 台帳 「TIMEOUT ばかり」 で spec §4 signal 崩壊
- D11 skip → 分類器 網羅性不足 の silent 化 (原典 §4 「推測で 機能を 足さない」 の 信号腐敗)

**source**: rei-aios `data/external-prior-art/gemini-lean-verify-2026-08-22/chat_claude_critique_2026-08-22.md` (STEP 1366 archival)、 Gemini `lean-verify` TypeScript impl への chat-Claude critique から Python 移植 + 私 rei-checker-mcp 適用 protocol 化。

---

# Phase 2 以降 (v0 完了までは 着手しない)

以下は 将来の 設計方針で、 **v0 のスコープ外**。 `decision_rate` が 算出できる 状態に なるまで、 このセクションの 実装に 着手しない。 但し v0 の 設計時に、 ここへの 拡張余地だけは 潰さない。

構成は 三層:

```
第1層  checker    verify / stats                      ← v0
第2層  education  locate_first_error / boundary_report / escalate
第3層  harness    calibration / regression / transfer
```

**実装順序は 第 1 層 → 第 3 層② → 第 2 層。** 第 2 層より 先に 較正ハーネスを 作る。

詳細は source spec `CHECKER_SPEC_v0.md` §9-13 を 参照。

## Phase 2 で 守る原則 (再掲)

1. **判定経路に LLM を 入れない。** 較正ハーネスの ラベル付けにも 適用する (§9.4)
2. **除外したものを 隠さない。** `exclusion_rate` を 常に 併記する
3. **説明を 生成しない。** 第 2 層は 位置を 返すのみ
4. **順位表を 作らない。** 計器であって 審判ではない
5. 第 2 層より 先に 第 3 層② を 作る
6. 急がず、 ゆっくりと。

---

# Rei stack 内 位置付け (混同回避)

- **`rei-verify`** (PyPI 0.1.0a1、 別 repo) = 反証機械 (refutation machine)、 4-value verdict (CONFIRMED/REFUTED/HOLDING/...)、 refutation-first 主軸。 本 repo とは 設計哲学 明示的に 別 (反証 first vs 検証 first、 4 値 vs 3 値)。 混同禁止。
- **`grounded-check`** (PyPI live) = 引用 grounding check、 別 domain。
- **`rei-preregister`** (rei-aios/tools/) = 予測 sha256 seal、 事前登録 tool、 事後検証と 別目的。
- **`discovery-worker`** (別 repo、 2026-08-22 spike) = 反例探索 hunter、 別 layer。
- **Rei stack MCP 8 systems** (rei-aios v2.8.1 tool 38 + benchtop v0.6 tool 17 + mcp-lens + rei-automator-mcp + lab-notebook-mcp + rei-verify + rei-memory-mcp + rei-meta-mcp) = 全て 別 domain、 本 repo は 9th system として parallel 配置予定 (実運用で 硬化後、 藤本さん judgment)。

本 repo は **spec CHECKER_SPEC_v0.md** に **strictly** 従い、 上記 8 system と **意図的に 独立**。 統合は spec §5 「複数バックエンド対応 非目標」 に反するため 現時点 なし。
