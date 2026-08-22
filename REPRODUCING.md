# Reproducing rei-checker-mcp v0.2.0a1

> **Reproducibility guide** for the formal-verification checker MCP server.
> Version: `0.2.0a1` (alpha, 2026-08-23) · License: AGPL-3.0-or-later
> Repository: <https://github.com/fc0web/rei-checker-mcp>
> Source spec: [CHECKER_SPEC_v0.md](https://github.com/fc0web/rei-aios/blob/main/data/external-prior-art/checker-spec-v0-2026-08-22/CHECKER_SPEC_v0.md) (2026-08-22 archival)
> Design invariants: [CLAUDE.md](./CLAUDE.md)

This document describes how to reproduce every component of `rei-checker-mcp`
that a maintainer or independent evaluator would need to confirm before
depending on the tool. Reproduction is layered by the tooling required.

`decision_rate` (the only metric this project exposes, per spec §3) is not
the target of reproduction — the reproducibility target is **the ability to
observe that decision_rate at all, on your own machine, from the sources in
this repository.**

## Layer overview

| Layer | Required tooling | Cost | What you verify |
|---|---|---|---|
| **1. Python stdlib** | Python ≥ 3.9 | ¥0 | Schema + Mock backend + ledger + stats + CLI + MCP stdio server + **73 test PASS** |
| **2. Lean 4 REPL harness (optional)** | Layer 1 + Lean 4 `v4.29.0` (via elan) | ¥0 | Persistent REPL binary (`lean_checker_repl.exe`) + 13-pattern smoke parity with MockBackend |
| **3. MCP client integration** | Layer 1 + Claude Desktop (or any MCP-stdio client) | ¥0 | Live `verify` / `stats` tool calls from a real MCP host |

Layers are additive. Layer 1 alone is enough to confirm the discipline (three
values + reason codes + append-only ledger + no LLM in the judgment path);
Layers 2-3 add the harness and the wire.

**Honest scope up front** (before you spend time reproducing anything):

- `LeanBackend` in `rei_checker/backend.py` is **still a stub**. Real Lean 4
  elaboration is deferred to Stage 2 (v0.2.2+). Layer 2 in this guide
  reproduces the **REPL plumbing** and its behavioural parity with the Mock
  backend — not real Lean judgment. See `lean_backend/README.md` and
  `docs/V02_PROTOCOL.md` §5 (C7) for what Stage 2 will replace.
- MockBackend's truth table is a **testing fixture**. It is not a substitute
  for a mathematical checker. Real judgment is the goal of Stage 2.
- The "no LLM in the judgment path" invariant (spec §1.1, CLAUDE.md §1.1) is
  a **source-code discipline**. Reproduction confirms it by grep + read, not
  by a runtime check. See §4 of this document.

---

## Layer 1 — Python stdlib (¥0, 5 分)

### 1.1 Clone at a known revision

```bash
git clone https://github.com/fc0web/rei-checker-mcp.git
cd rei-checker-mcp
git log -1 --format='%H %s'
```

Expected: the top commit prefix `ba45b3a` (v0.2.0a1 utility modules landed),
or a later commit on `main`. Note the exact SHA you tested against — every
`verify` response carries `checker_version` so you can trace results back to
a source tree.

### 1.2 Confirm zero external dependencies

```bash
cat pyproject.toml | grep -A1 '^dependencies\|^\[project\.optional'
```

Expected:

```toml
dependencies = []

[project.optional-dependencies]
test = []
```

If either list is non-empty, the tree has drifted from spec §5 / CLAUDE.md §2
("複数バックエンド対応 非目標") and this reproduction guide no longer applies
as written.

### 1.3 Run the test suite

```bash
python -m unittest tests.test_all -v 2>&1 | tail -5
```

Expected:

```
----------------------------------------------------------------------
Ran 73 tests in 0.1XXs

OK
```

Test method count check:

```bash
grep -c "def test_" tests/test_all.py
```

Expected: `73`.

Test coverage (per spec §7 discipline — **UNDECIDED cases prioritised over
happy path**): schema (11) + MockBackend UNDECIDED paths (8) + happy paths
(5) + LeanBackend stub (1) + timeout enforcement (2) + ledger (8) + stats
(3) + verify E2E (5) + MCP handlers (8) + scope discipline (4) + v0.2.0a1
utility modules (§2 spawn error / §3 process kill / §4 axiom parse / §6
unclassified reason). If your grep count differs, note the delta.

### 1.4 CLI smoke — decisive + UNDECIDED + ledger + stats

```bash
python -m rei_checker verify "1 + 1 = 2"
```

Expected (exit code `0`, `verdict: VALID`):

```json
{
  "verdict": "VALID",
  "elapsed_ms": 0,
  "checker_version": "rei-checker-mcp/0.2.0a1+..."
}
```

```bash
python -m rei_checker verify "some unknown thing"
echo $?
```

Expected: `exit 2`, verdict `UNDECIDED`, `reason_code: OUT_OF_SCOPE`. Every
UNDECIDED carries a reason code — that is the spec §1.2 invariant.

Ledger persistence + stats aggregation:

```bash
python -m rei_checker verify "1 + 1 = 2"
python -m rei_checker verify "1 + 1 = 3"
python -m rei_checker verify "unknown thing"
python -m rei_checker stats
```

Expected: `total: 3, valid: 1, invalid: 1, undecided: 1, decision_rate:
0.666..., reason_breakdown: { OUT_OF_SCOPE: 1 }`.

Ledger location default is `./ledger.jsonl`; override with the env var
`REI_CHECKER_LEDGER=/absolute/path/ledger.jsonl`.

### 1.5 MCP stdio round-trip (Layer 1, no client needed)

Layer 1 exposes the MCP stdio server without any external MCP client. Send
JSON-RPC requests directly:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"verify","arguments":{"expression":"1 + 1 = 2"}}}' \
  '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"stats","arguments":{}}}' \
  | python -m rei_checker mcp
```

Expected: 4 JSON-RPC responses. `tools/list` returns exactly **two tools**
(`verify` + `stats`) — no more, no less (spec §2, intentional minimum).

Layer 1 reproduction complete.

---

## Layer 2 — Lean 4 REPL harness (optional, ¥0)

Layer 2 is optional. It exists to reproduce the **REPL server plumbing** that
STEP 1367 (v0.2.1 spike Stage 1) landed, and to observe the ~100× startup
cost saving over `subprocess-per-request`. It does **not** run real Lean 4
elaboration — that is Stage 2 (v0.2.2+, deferred).

### 2.1 Install pinned Lean 4 toolchain

```bash
# elan (Lean version manager) — install once
# Linux/macOS:
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh
# Windows (PowerShell):
# Invoke-WebRequest -Uri https://raw.githubusercontent.com/leanprover/elan/master/elan-init.ps1 -OutFile elan-init.ps1; .\elan-init.ps1
```

Toolchain pin:

```bash
cat lean_backend/lean-toolchain
```

Expected: `leanprover/lean4:v4.29.0` (single line, no trailing content).

This version is **not arbitrary**. It matches the rei-aios convention (see
rei-aios `data/lean4-mathlib/lean-toolchain`) and the STEP 1367 spike build
context. Upgrading Lean before Stage 2 is deferred — Stage 2 metaprogramming
(`Lean.Parser.runParserCategory` + `Lean.Elab.Command.elabCommand`) has API
surface that shifts between minor Lean releases.

### 2.2 Build the REPL binary

```bash
cd lean_backend
lake build
```

Expected: `~4-5 sec` (first build downloads Lean 4 v4.29.0 via elan; that
step can take minutes on first-ever install). Deprecation warnings on
`String.trim` are expected and non-blocking (pinned to v4.29.0 for
reproducibility, so we don't chase later API renames yet).

Binary output:

```bash
ls -lh .lake/build/bin/lean_checker_repl.exe
```

Expected: file exists, ~141 MB (includes the Lean runtime).

### 2.3 Smoke test — MockBackend parity

```bash
echo '{"expression":"1 + 1 = 2"}' | ./.lake/build/bin/lean_checker_repl.exe
```

Expected:

```json
{"checker_version":"lean-checker-repl/0.2.1a1+spike-2026-08-22","verdict":"VALID"}
```

Batch smoke (13 patterns, matches MockBackend truth table):

```bash
printf '%s\n' \
  '{"expression":"1 + 1 = 2"}' \
  '{"expression":"1 + 1 = 3"}' \
  '{"expression":"True"}' \
  '{"expression":"False"}' \
  '{"expression":""}' \
  '{"expression":"unknown thing"}' \
  '{"expression":"<axiom-test>"}' \
  '{"expression":"<timeout-test>"}' \
  '__QUIT__' \
  | ./.lake/build/bin/lean_checker_repl.exe
```

Expected: 8 JSON responses whose verdicts match MockBackend for the same
expressions (VALID / INVALID / VALID / INVALID / UNDECIDED[PARSE_FAILURE] /
UNDECIDED[OUT_OF_SCOPE] / UNDECIDED[MISSING_AXIOM] / UNDECIDED[TIMEOUT]).

### 2.4 Startup cost observation (informational, not asserted)

STEP 1367 measured cold subprocess-per-request ≈ **146 ms/req** vs a single
warm REPL invocation ≈ **1.5 ms/req** across 100 requests (~**100×**). Your
number will vary by hardware; the point is that the ratio should be
substantial (order of magnitude), which is the C7 architectural evidence
that `docs/V02_PROTOCOL.md` §5 preserves for Stage 2.

Stage 2 will change these numbers: importing `Mathlib.Tactic` in Stage 2 is
expected to raise cold cost to 8-15 sec and preserve the warm-REPL benefit
(300-1000× projected, **not yet verified**).

### 2.5 What Layer 2 does *not* verify

- **Real Lean 4 elaboration** is not run. Stage 1 pattern-matches expression
  strings against a hardcoded table (see `lean_backend/Main.lean`).
- The `LeanBackend` class in `rei_checker/backend.py` is a stub that returns
  `UNDECIDED/UNSUPPORTED_SYNTAX` for every input. Layer 1's 73 tests include
  1 test asserting this stub behaviour.
- Sandbox enforcement (`docs/V02_PROTOCOL.md` §1) is **not in place**.
  Running the Layer 2 binary against attacker-controlled expressions is
  unsafe until Stage 2 lands the environment-level sandbox. For
  reproduction, use only trusted inputs.

Layer 2 reproduction complete.

---

## Layer 3 — MCP client integration (¥0)

Layer 3 wires Layer 1 into a real MCP host. Any MCP-stdio-compatible client
works; the concrete example is Claude Desktop.

### 3.1 Claude Desktop config

Add to `claude_desktop_config.json` (path varies by OS):

```json
{
  "mcpServers": {
    "rei-checker": {
      "command": "python",
      "args": ["-m", "rei_checker", "mcp"],
      "cwd": "/absolute/path/to/rei-checker-mcp",
      "env": {
        "REI_CHECKER_LEDGER": "/absolute/path/to/ledger.jsonl"
      }
    }
  }
}
```

Both `cwd` and `REI_CHECKER_LEDGER` should be absolute paths. Absolute paths
in reproducibility material are otherwise flagged as environment leakage;
here they are the *contract* the MCP host requires.

### 3.2 Verify the two tools are exposed

In Claude Desktop (or via any MCP client), the `rei-checker` server should
list **exactly two tools**: `verify` and `stats`. Any additional tool means
the tree has drifted from spec §2 / CLAUDE.md §2 (intentional minimum).

### 3.3 Round-trip a decisive + UNDECIDED call

From the client, call `rei-checker.verify` with `expression = "1 + 1 = 2"`
and confirm `VALID`. Then call it with an unknown expression and confirm
`UNDECIDED` + `reason_code`. Then call `stats` and confirm the counters
incremented.

Layer 3 reproduction complete.

---

## Version pinning (for reproducibility across time)

| Component | Pin | Where to check |
|---|---|---|
| Python | ≥ 3.9 (tested through 3.13) | `pyproject.toml` `requires-python` |
| Package version | `0.2.0a1` | `pyproject.toml` + `rei_checker/__init__.py` `__version__` |
| Lean 4 toolchain | `leanprover/lean4:v4.29.0` | `lean_backend/lean-toolchain` |
| License | AGPL-3.0-or-later | `LICENSE` + `pyproject.toml` |
| Runtime dependencies | (none — stdlib only) | `pyproject.toml` `dependencies = []` |
| Test dependencies | (none — `unittest` only) | `pyproject.toml` `optional-dependencies.test = []` |

Every `verify` response carries `checker_version` (format:
`rei-checker-mcp/<version>+<build-tag>`). Record that string alongside any
result you rely on — it is the reproducibility handle back to a source tree.

---

## §4 — Confirming "no LLM in the judgment path" (source-inspection)

This invariant (spec §1.1, CLAUDE.md §1.1) is the reason the project exists.
There is no runtime check for it — a checker cannot check itself for this
property without begging the question. Instead:

```bash
grep -rn "openai\|anthropic\|langchain\|litellm\|claude\|gpt\|llm" rei_checker/ tests/
```

Expected: **zero matches** in imports, calls, or logic. String literals
mentioning these names in comments or docstrings are acceptable (this
document itself contains them). Non-zero matches in source paths are a
signal to read `docs/V02_PROTOCOL.md` before trusting any judgment.

`rei_checker/backend.py` defines a single abstract `Backend` class with two
concrete subclasses (`MockBackend`, `LeanBackend`). Neither imports any LLM
library. Confirm by reading the file.

---

## Honest scope (v0.2.0a1, alpha)

1. **v0.2.0a1 is alpha**. Not stable. API surface (`verify` + `stats` +
   3-value verdict + 6 reason codes) is frozen at spec §2 / §1.2, but
   internals (backend abstraction, ledger format, MCP protocol version)
   may shift before v0.2.0 stable.
2. **Real Lean 4 elaboration is not yet available**. Layers 1-3 in this
   guide are reproducible today; the judgment they produce is bounded by
   MockBackend's truth table (Layer 1) or Layer 2's hardcoded parity table.
   Stage 2 (real elaboration) is deferred — see `docs/V02_PROTOCOL.md`.
3. **Sandbox is not enforced yet** (`docs/V02_PROTOCOL.md` §1). Do not run
   Layer 2 against attacker-controlled expressions. Layer 1's Mock backend
   is safe (no subprocess), Layer 2's Lean binary is not.
4. **`decision_rate` is the metric, not the target**. Reproducing v0.2.0a1
   means confirming you can *observe* decision_rate on your machine.
   Whether that number is 0.1 or 0.9 is a follow-up question for Stage 2,
   when the LeanBackend stub is replaced with real elaboration.
5. **This document is the first REPRODUCING.md for a Rei stack tool other
   than Paper 145** (silicon domain, rei-aios REPRODUCING.md, 4-layer guide
   for Tang Console 138K + Aer + IBM Heron r2). It is deliberately shorter
   and simpler because the tooling surface is smaller (Python + Lean 4 vs
   FPGA + quantum hardware). Cross-domain reproducibility patterns are not
   yet abstracted — that is a candidate follow-up after 2-3 domain pilots
   are in place.
6. **No DOI**. This is a source repository, not a published artifact. If you
   need a citable reference, cite the source spec (`CHECKER_SPEC_v0.md`)
   archived in rei-aios or the STEP arc that produced this repository (STEP
   1365 spike + STEP 1366 protocol + STEP 1367 REPL Stage 1).

---

## Related resources

- **Source spec (archival, immutable)**: [CHECKER_SPEC_v0.md](https://github.com/fc0web/rei-aios/blob/main/data/external-prior-art/checker-spec-v0-2026-08-22/CHECKER_SPEC_v0.md) — rei-aios STEP 1364.
- **v0.2 pre-cautions**: [`docs/V02_PROTOCOL.md`](./docs/V02_PROTOCOL.md) — required reading before any Stage 2 Lean backend work.
- **Lean 4 REPL Stage 1 detail**: [`lean_backend/README.md`](./lean_backend/README.md).
- **Design invariants**: [`CLAUDE.md`](./CLAUDE.md) — §1.1-1.3 non-negotiables + §8 four principles.
- **Rei stack position** (deliberate independence from `rei-verify`, `grounded-check`, `rei-preregister`, `discovery-worker`, and the 8 MCP systems): `CLAUDE.md` "Rei stack 内 位置付け" section.
- **Precedent for this document**: [Paper 145 REPRODUCING.md](https://github.com/fc0web/rei-aios/blob/main/REPRODUCING.md) — silicon-domain 4-layer guide.

## Discipline

急がず、 ゆっくりと。 (CLAUDE.md §8.4)

If this guide fails to reproduce on your machine, that is a signal to file
an issue — not to patch around the failure. Reproducibility that only works
when the reader guesses right is not reproducibility.

<https://github.com/fc0web/rei-checker-mcp/issues>
