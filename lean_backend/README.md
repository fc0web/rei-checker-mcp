# lean_backend/ — Lean 4 REPL harness

**v0.2.1 spike Stage 1** (2026-08-22, STEP 1367): plumbing only.
Persistent Lean 4 process with JSON stdin/stdout IPC. Hardcoded truth
table (mirrors MockBackend semantics). Real Lean 4 elaboration is Stage 2
(v0.2.2 or later, not this spike).

## What's here

- `lakefile.lean` — Lake build config (no external deps, minimal)
- `lean-toolchain` — pinned to `leanprover/lean4:v4.29.0` (matches rei-aios convention)
- `Main.lean` — REPL loop + JSON IPC + hardcoded truth table
- After `lake build`: `.lake/build/bin/lean_checker_repl.exe` (~141 MB, includes Lean runtime)

## Prerequisite: READ [`../docs/V02_PROTOCOL.md`](../docs/V02_PROTOCOL.md) FIRST (before any Stage 2 work)

Before writing any Stage 2 code in this directory, read the v0.2 protocol
document. It captures 6 non-negotiable prerequisites distilled from the
chat-Claude critique of Gemini's `lean-verify` TypeScript implementation
(rei-aios STEP 1366 archival). Skipping any of them silently breaks the
tool's discipline (spec §1.1-§1.2) or opens a security hole:

- §1 A1 — **Sandbox** (environment, not code): nsjail / Docker / Job Object
- §2 A2 — spawn error handling (FileNotFoundError / OSError)
- §3 A3 — process tree kill (POSIX process group, Windows taskkill /T)
- §4 B4 — `--json` axiom parsing through JSON message field
- §5 C7 — **REPL server**, not subprocess-per-request (architectural) ✅ Stage 1 で 完了 (100x speedup 実測)
- §6 D11 — `ERR_UNCLASSIFIED` reason code (silent misclassification prevent)

## Build

```bash
cd lean_backend
lake build
```

First build downloads/verifies Lean 4 v4.29.0 via elan, then compiles.
Subsequent builds are incremental (~1-2 sec).

## Run (standalone smoke test)

```bash
echo '{"expression":"1 + 1 = 2"}' | ./.lake/build/bin/lean_checker_repl.exe
# → {"checker_version":"lean-checker-repl/0.2.1a1+spike-2026-08-22","verdict":"VALID"}
```

Batch smoke:
```bash
printf '{"expression":"1 + 1 = 2"}\n{"expression":"1 + 1 = 3"}\n__QUIT__\n' \
  | ./.lake/build/bin/lean_checker_repl.exe
# → {"...verdict":"VALID"}
# → {"...verdict":"INVALID"}
```

Sentinel `__QUIT__` line ends the loop cleanly. Otherwise EOF (stdin close)
also ends it.

## Protocol (Stage 1)

**Request** (one JSON object per line, UTF-8):
```json
{"expression": "<string>"}
```

**Response** (one JSON object per line, UTF-8):

| Verdict | Fields |
|---|---|
| VALID / INVALID | `verdict`, `checker_version` |
| UNDECIDED | `verdict`, `reason_code`, `detail`, `checker_version` |

Reason codes match the Python `rei_checker/schema.py::ReasonCode` enum:
`TIMEOUT`, `PARSE_FAILURE`, `UNSUPPORTED_SYNTAX`, `MISSING_AXIOM`,
`DEPTH_LIMIT`, `OUT_OF_SCOPE`.

## Truth table (Stage 1, matches Python MockBackend exactly)

| Input | Response |
|---|---|
| `1 + 1 = 2` | VALID |
| `1 + 1 = 3` | INVALID |
| `∀ n : ℕ, n + 0 = n` | VALID |
| `∀ n : ℕ, n + 1 = n` | INVALID |
| `True` | VALID |
| `False` | INVALID |
| `` (empty/whitespace) | UNDECIDED/PARSE_FAILURE |
| `<timeout-test>` | UNDECIDED/TIMEOUT |
| `<syntax-test>` | UNDECIDED/UNSUPPORTED_SYNTAX |
| `<axiom-test>` | UNDECIDED/MISSING_AXIOM |
| `<depth-test>` | UNDECIDED/DEPTH_LIMIT |
| anything else | UNDECIDED/OUT_OF_SCOPE |

Invalid JSON or missing `expression` field → UNDECIDED/PARSE_FAILURE
(never crashes the REPL).

## Measured performance (2026-08-22 spike verify)

- **Cold start** (subprocess-per-request): ~146 ms/req (Lean binary load)
- **Warm REPL** (100 req in one invocation): ~1.5 ms/req
- **Speedup**: ~100x

This validates the C7 architecture (V02_PROTOCOL.md §5). With Mathlib
import added in Stage 2, cold start jumps to 8-15 sec (chat-Claude C7
finding); warm REPL stays close to constant. The speedup ratio grows
proportionally to whatever preamble Stage 2 needs.

## Stage 2 (v0.2.2 or later, NOT this spike): real elaboration

Replace the `truthTable` function in `Main.lean` with:

1. Parse `expression` string as a Lean `Term` via `Lean.Parser.runParserCategory`
2. Try elaborating `example : <term> := by decide` via `Lean.Elab.Command.elabCommand`
3. If elaboration succeeds → VALID
4. Else try `example : Not <term> := by decide`; success → INVALID
5. Else → UNDECIDED with appropriate reason code from elaborator diagnostics

Stage 2 also needs Python-side integration in `rei_checker/backend.py`:
- Spawn this REPL binary as a persistent subprocess (protocol §2 spawn
  error handling)
- Maintain stdin/stdout pipes across multiple `verify()` calls
- Enforce timeout via write-with-timeout on stdin + read-with-timeout on
  stdout (NOT process kill per request — kill only on health check failure)
- Send `__QUIT__` on shutdown; if REPL dies unexpectedly, spawn a new one
  (auto-restart, protocol §5)
- Run the REPL binary inside the sandbox layer (protocol §1) — the
  Python-side `LeanBackend` documents this constraint, does not try to
  enforce it in-process (that would give false confidence)

## Not going to be

- A general-purpose theorem prover
- A tactic library
- A Mathlib fork
- A Lean 4 plugin / VS Code extension

It's the smallest possible bridge that lets Python call Lean 4 to get one
three-valued answer for one expression. Nothing more.
