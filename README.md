# rei-checker-mcp

**形式検証チェッカー MCP v0.1.0a1** — 一行を受け取り、真偽を返す。 それ以上でも それ以下でもない。

Three-valued verdict (`VALID` / `INVALID` / `UNDECIDED`). No LLM in the judgment path. Every UNDECIDED carries a reason code and lands in an append-only refutation ledger.

**License**: AGPL-3.0-or-later
**Spec**: [CHECKER_SPEC_v0.md](https://github.com/fc0web/rei-aios/blob/main/data/external-prior-art/checker-spec-v0-2026-08-22/CHECKER_SPEC_v0.md)
**Design invariants**: [CLAUDE.md](./CLAUDE.md)

## 5 分で 動かす

Python 3.9+ が あれば 十分。 外部 dependency なし (stdlib only)。

```bash
git clone https://github.com/fc0web/rei-checker-mcp.git
cd rei-checker-mcp
python -m rei_checker verify "1 + 1 = 2"
```

期待出力:

```json
{
  "verdict": "VALID",
  "elapsed_ms": 0,
  "checker_version": "rei-checker-mcp/0.1.0a1+spike-2026-08-22"
}
```

判定不能な入力は 「判定できない」 を 返す (spec §1.2):

```bash
python -m rei_checker verify "some unknown thing"
```

```json
{
  "verdict": "UNDECIDED",
  "elapsed_ms": 0,
  "checker_version": "rei-checker-mcp/0.1.0a1+spike-2026-08-22",
  "reason_code": "OUT_OF_SCOPE",
  "detail": "MockBackend has no rule for this expression"
}
```

exit code: `0` = decisive (VALID/INVALID), `2` = UNDECIDED。 shell script で 「判定できたか」 を 直接分岐可。

## Ledger 蓄積 と stats

すべての `verify` 呼び出しは `ledger.jsonl` に一行追記される (spec §4)。

```bash
python -m rei_checker verify "1 + 1 = 2"
python -m rei_checker verify "1 + 1 = 3"
python -m rei_checker verify "<axiom-test>"
python -m rei_checker stats
```

```json
{
  "total": 3,
  "valid": 1,
  "invalid": 1,
  "undecided": 1,
  "decision_rate": 0.6666666666666666,
  "reason_breakdown": {
    "MISSING_AXIOM": 1
  }
}
```

**`decision_rate` が 唯一の 指標** (spec §3)。 初期値が 0.1 でも構わない — **測れる状態に なる** ことが 成功条件。

Ledger の 場所は `$REI_CHECKER_LEDGER` env var で 上書き可能。 default = カレントディレクトリの `ledger.jsonl`。

## MCP server として 使う

Claude Desktop に 登録:

```json
{
  "mcpServers": {
    "rei-checker": {
      "command": "python",
      "args": ["-m", "rei_checker", "mcp"],
      "cwd": "C:/path/to/rei-checker-mcp",
      "env": {
        "REI_CHECKER_LEDGER": "C:/path/to/ledger.jsonl"
      }
    }
  }
}
```

MCP tool は **2 つだけ** (spec §2、 意図的最小):

- `verify(expression, context?, timeout_ms?)` → `{ verdict, reason_code?, detail?, elapsed_ms, checker_version }`
- `stats()` → `{ total, valid, invalid, undecided, decision_rate, reason_breakdown }`

## 何が 「作られていない」 か (spec §2 明示)

以下は **v0 の 非目標**。 実装しようとしたら **手を止めて 確認する**:

- UI / Web フロントエンド
- ユーザー登録・認証・課金
- ゲーミフィケーション、 進捗管理、 学習履歴
- 自然言語での 対話・解説生成
- 複数バックエンド対応 (Lean 4 のみ、 v0 spike は Mock backend で 動作)
- Claude 固有の 機能への 依存

## v0 の 状態 (honest scope、 2026-08-22 spike)

- ✅ Schema (3 値 + reason code 6 種) 完全実装
- ✅ Mock backend (test 用 truth table + 全 reason code trigger)
- ✅ Ledger (append-only JSONL、 UTF-8、 malformed row skip)
- ✅ stats() aggregate (decision_rate + reason_breakdown)
- ✅ MCP stdio server (initialize + tools/list + tools/call)
- ✅ CLI (verify / stats / mcp / version subcommand)
- ⚠ **Lean 4 backend は stub** (v0.2 candidate、 lean_backend/ dir で 実装予定)
- ⚠ Timeout enforcement は soft (elapsed 監視、 hard process kill は v0.2)

**「まず 使われる」 が 優先** (spec §1.3、 §6.6)。 Lean 4 harness 完成後、 backend を 差し替えれば 実 判定 稼働。 API surface は 変わらない。

## Phase 2 (v0 完了までは 着手しない)

spec §9-13 で 定義された 三層構造:

- 第 1 層 checker (verify / stats) ← **v0、 これ**
- 第 2 層 education (locate_first_error / boundary_report / escalate)
- 第 3 層 harness (calibration / regression / transfer)

**実装順序**: 第 1 層 → 第 3 層② calibration harness → 第 2 層。 詳細は spec §9-13。

## テスト

```bash
python -m unittest tests.test_all -v
```

Spec §7 に従い、 **UNDECIDED を 返すべき ケースの テスト を 優先** (全 reason_code 個別 test + VALID/INVALID happy path)。

## Rei stack との 関係 (混同回避)

本 repo は 意図的に 独立。 隣接 tool との 区別:

- **rei-verify** (PyPI 0.1.0a1) = 反証機械 4-value verdict、 refutation-first 主軸。 本 repo は 3-value verification-first で **設計哲学が 別**。
- **grounded-check** = LLM 出力の 引用 grounding check、 別 domain。
- **rei-preregister** = 予測 SHA256 seal、 事前登録 tool。
- **discovery-worker** = 反例 hunter、 別 layer。

統合は spec §5 「複数バックエンド対応 非目標」 に反するため 現時点 なし。

## 貢献 / 報告

spec §8 の 4 原則を 遵守してください:

1. 機能を 足すか 迷ったら、 足さない
2. 「たぶん 正しい」 を 返すか 迷ったら、 UNDECIDED を 返す
3. 理論を API に 出すか 迷ったら、 出さない
4. 急がず、 ゆっくりと

Issues: https://github.com/fc0web/rei-checker-mcp/issues
