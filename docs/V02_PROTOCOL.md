# V0.2 Protocol — Lean 4 backend implementation prerequisites

> **CRITICAL PREP DOC**: When implementing the real Lean 4 backend (replacing
> `LeanBackend` stub in `rei_checker/backend.py`), the 5 protocols below MUST
> be in place BEFORE writing any subprocess-touching code. Skipping them is
> not "we'll fix it later" — each one, if skipped, silently breaks the
> tool's discipline (spec §1.1-§1.2) or opens a security hole.

## Provenance of this document

This protocol was distilled from the chat-Claude critique of Gemini's
`lean-verify` TypeScript implementation, archived in rei-aios under
[`data/external-prior-art/gemini-lean-verify-2026-08-22/`](https://github.com/fc0web/rei-aios/tree/main/data/external-prior-art/gemini-lean-verify-2026-08-22).
The critique identified 13 findings (A1-A3 dangerous, B4-B6 broken, C7 most
impactful, D8-D13 spec-inconsistent, E minor). The 5 items below are the
subset that apply to **this repo's v0.2 Lean backend work**, cross-referenced
with rei-checker-mcp v0.1.0a1 (STEP 1365) source status.

STEP 1366 archived Gemini's spec + impl + chat-Claude critique verbatim
(immutable) and distilled this protocol as the B-part of that STEP.

## 5 protocols (order = chat-Claude recommended implementation order)

### §1. A1 — Sandbox layer (highest priority, environment-level, not code)

**Threat**: User-provided expression is embedded raw into Lean 4 source code.
A hostile expression like `sorry\n#eval IO.Process.run "rm -rf ~"` executes
shell commands on the host. String-level denylists CANNOT close this hole
(Unicode escapes, macros, `open`, `local instance` all bypass).

**Mitigation** (environment-level, not implementable in `rei_checker/`):

| Platform | Sandbox layer |
|---|---|
| Linux (production) | **nsjail** or **bubblewrap** with `--net none --read-only-bind / --proc /proc --die-with-parent`, non-root uid, rlimit (`RLIMIT_AS 2GB`, `RLIMIT_CPU 30s`) |
| Linux (CI) | **Docker container** with `--network none --read-only --cap-drop ALL --user 1000:1000 --memory 2g --cpus 1` |
| Windows (dev) | **Job Object** (Win32 API) with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE + JOB_OBJECT_LIMIT_ACTIVE_PROCESS + JOB_OBJECT_LIMIT_PROCESS_MEMORY`, or **AppContainer** for stricter isolation, or run under **low-integrity user account** |
| Windows (production) | Same as dev + WSL2 with Linux sandbox layer above (recommended) |
| macOS | **sandbox-exec** with restrictive profile (deprecated but functional), or Docker |

**Deploy discipline**:
- `LeanBackend.check()` MUST NOT be called from a process that has network
  access, filesystem write access outside a scratch dir, or any user
  credentials in env vars.
- The **caller's responsibility**, not the library's: `rei_checker/backend.py`
  documents this constraint but does not attempt to enforce it. Attempting
  in-process sandboxing (e.g. `seccomp` from Python) is fragile and gives
  false confidence — do the isolation at the container/nsjail layer where
  it's audited kernel-enforced.

**Auxiliary defense (defense in depth, NOT primary defense)**:
- Regex + tokenizer pre-scan for `#eval`, `#reduce`, `unsafe`, `initialize`,
  `native_decide` in the raw expression → reject with `UNDECIDED/UNSUPPORTED_SYNTAX`
  before Lean sees it. But this is **advisory only**, siren-family avoidance:
  never advertise "safe" purely from the pre-scan.

### §2. A2 — spawn error handling (permanent hang prevention)

**Threat**: If `lean` or `lake` binary is missing, `subprocess.Popen(...)`
raises `FileNotFoundError` in Python (or `spawn` `error` event in Node.js).
Without a try/except, the caller receives an unhandled exception, or worse,
the promise never resolves (Node.js case — Gemini impl bug A2).

**Python impl protocol** (for `rei_checker/backend.py::LeanBackend.check`):

```python
import subprocess
import threading
import time
from typing import Optional, Tuple

def _run_lean_safely(
    args: list[str],
    stdin_data: str,
    timeout_ms: int,
) -> Tuple[int, str, str, bool]:  # (returncode, stdout, stderr, timed_out)
    try:
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,  # §3 process group
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as e:
        # lean / lake not installed on this system.
        return (-1, "", f"binary not found: {e}", False)
    except OSError as e:
        # any other exec-level failure (permission denied, etc.)
        return (-1, "", f"exec failed: {type(e).__name__}: {e}", False)

    try:
        stdout, stderr = proc.communicate(
            input=stdin_data,
            timeout=timeout_ms / 1000.0,
        )
        return (proc.returncode, stdout, stderr, False)
    except subprocess.TimeoutExpired:
        # §3: kill the process group, not just the direct child.
        _kill_process_tree(proc.pid)
        try:
            stdout, stderr = proc.communicate(timeout=1.0)  # drain
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = "", ""
        return (-1, stdout, stderr, True)  # timed_out=True
```

**All 4 failure modes** MUST fold to `UNDECIDED` at the `check()` layer:
- FileNotFoundError → `UNDECIDED/OUT_OF_SCOPE` with detail "lean not installed"
- Other OSError → `UNDECIDED/PARSE_FAILURE` with detail
- TimeoutExpired → `UNDECIDED/TIMEOUT`
- Non-zero returncode with no diagnostics → `UNDECIDED/UNCLASSIFIED` (see §6)

### §3. A3 — Process group kill (orphan lean process prevention)

**Threat**: `lake env lean` spawns `lean` as grandchild. Killing `lake` with
`SIGKILL` leaves `lean` orphaned. Batch of 100 requests × 100 MB per lean =
10 GB memory leak.

**Cross-platform Python protocol**:

```python
import os
import signal
import sys

def _kill_process_tree(pid: int) -> None:
    """Kill the process and all its descendants. No-op if already dead."""
    if sys.platform == "win32":
        # Windows: use taskkill for tree kill.
        import subprocess
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=5.0,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
    else:
        # POSIX: kill process group.
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass  # already dead or race
```

**Prerequisite**: `subprocess.Popen(..., start_new_session=True)` on POSIX
so the child gets its own process group. Without this, `os.killpg` on the
child's pid kills the parent Python process too.

### §4. B4 — `--json` axiom parsing (through JSON message field, not raw stdout)

**Threat**: Lean 4 `--json` flag wraps all diagnostics — including `#print axioms X`
output — inside JSON `{severity, pos, endPos, message, ...}` objects. Naive
raw-stdout grep for `depends on axioms:` misses them. Axiom check silently
returns empty list, `all_axioms_authorized([])` returns True (vacuously),
axiom check effectively disabled.

**Correct parse protocol**:

```python
import json

def parse_axioms_from_lean_json_output(stdout: str) -> list[str]:
    """Parse #print axioms output from Lean --json stdout.

    Lean emits one JSON object per line. #print axioms output appears as
    an 'information'-severity diagnostic with message like:
        "'X' depends on axioms: [propext, Classical.choice]"
    """
    axioms = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        message_text = msg.get("data") or msg.get("message") or ""
        if isinstance(message_text, dict):
            message_text = json.dumps(message_text)  # fallback
        # Match both variants Lean has used across versions:
        for marker in ("depends on axioms:", "uses axioms:"):
            if marker in message_text:
                # Extract [ax1, ax2, ...] bracket content
                start = message_text.find("[")
                end = message_text.find("]", start)
                if start >= 0 and end > start:
                    raw = message_text[start + 1 : end]
                    axioms.extend(a.strip() for a in raw.split(",") if a.strip())
    return axioms
```

**Also detect `sorryAx`**: if the axiom list contains `sorryAx`, treat as
`ERR_SORRY_DETECTED` (backend-side sorry usage, distinct from user-side
sorry in expression — but if we only accept a single expression, both fold
to the same case; the distinction Gemini needs D10 doesn't apply here).

**Test discipline**: When adding LeanBackend real impl, write a unit test
that feeds actual `lean --json` output (captured as fixture) into this
parser and asserts axiom list. Do NOT accept parser code without a captured
fixture — Lean JSON schema can shift between versions.

### §5. C7 — REPL server, not subprocess-per-request

**Threat**: `import Mathlib.Tactic` cold start is 8-15 seconds and 2-4 GB
RAM. With default `timeout_ms: 5000`, most non-trivial requests hit
TIMEOUT. The ledger fills with `TIMEOUT` reason codes and no longer signals
what the checker actually can/can't do.

**Architectural decision**: v0.2 LeanBackend uses **persistent REPL** via
`leanprover-community/repl` or equivalent, not subprocess-per-request.

**Design**:
1. `lean_backend/` contains a Lean 4 project (lakefile.lean) that depends
   on `leanprover-community/repl` (or a minimal subset if Mathlib not
   required).
2. On first `LeanBackend.check()` call, Python spawns the REPL server as a
   long-lived subprocess (still inside the §1 sandbox).
3. Subsequent calls send JSON-encoded query to REPL stdin, read JSON
   response from REPL stdout. Latency drops from seconds to tens of ms.
4. REPL server death (crash / OOM / hang detected via read timeout) triggers
   auto-restart. Python side owns a thread that monitors health.

**Fallback**: If REPL fails to start (e.g. lakefile missing, Lean version
mismatch), `LeanBackend.check()` returns `UNDECIDED/OUT_OF_SCOPE` with
detail "REPL unavailable", NEVER falls back to subprocess-per-request
silently (that would resurrect the C7 problem).

**Prerequisite**: The `lean_backend/` directory needs its own lakefile.lean
+ REPL entry point. That's a separate work item (v0.2.1 candidate), not
covered by this protocol doc — this doc only enforces "when it's built, it
must be persistent REPL, not per-request subprocess".

### §6. D11 — `ERR_UNCLASSIFIED` reason code (silent misclassification prevention)

**Threat**: If `classifyFailure` defaults unknown failures to a specific
reason code (e.g. `PARSE_FAILURE`), the ledger can't distinguish "genuine
parse failure" from "classifier missed a new case". Ledger stops guiding
what to build next (spec §4 core violation).

**Protocol**: Add `ERR_UNCLASSIFIED` to `ReasonCode` enum. If Lean output
doesn't match any known error pattern, return `UNDECIDED/UNCLASSIFIED`
with the raw diagnostic in `detail`. When ledger shows UNCLASSIFIED
frequency rising, the fix is: **read the accumulated details, add new
classification rules to `classifyFailure`**, deploy, watch UNCLASSIFIED
frequency drop. Never assume the default classification is correct.

**Schema change**: `rei_checker/schema.py::ReasonCode` gets one more value.
Existing test `test_reason_code_has_six_initial_values` becomes
`test_reason_code_has_seven_values` (adjust). Existing ledger rows with
old 6-code set remain valid — enum widening is forward-compatible.

## What this protocol does NOT cover

- Ledger rotation, storage backend swap (JSONL → SQLite): separate scope, v0.3+
- Multi-request batch API, concurrency: separate scope, v0.3+
- MCP HTTP/SSE transport (currently stdio only): separate scope
- Auth / rate limiting: out of scope per CHECKER_SPEC_v0.md §2 ("作らないもの")
- UI, dashboards, education-layer tools (Phase 2 §12): explicit non-goal
  until v0 完了

## Implementation order (chat-Claude recommended)

Following the critique's recommended order:

1. **§1 sandbox** (environment prep, before any code)
2. **§2 spawn error handling** (`LeanBackend.check` guards)
3. **§3 process tree kill** (companion to §2)
4. **§4 JSON axiom parsing** (verify #print axioms actually works)
5. **§5 REPL server** (architectural, biggest win — do BEFORE ledger fills
   with false-TIMEOUT signals)
6. **§6 ERR_UNCLASSIFIED** (schema widen, forward-compat)

Steps 5, 6, 9-13 in the chat-Claude critique (some map to §6 here, others
are Gemini-spec-specific and don't apply to this repo) can wait one iteration.

## Test discipline (spec §7 継承)

Each protocol above MUST have a test in `tests/test_all.py` before the
protocol counts as "implemented":

- §1: cannot unit-test sandbox from inside the sandbox; use CI integration
  test that runs `LeanBackend.check("<hostile input>")` in a container
  and asserts no host file was created / no network call was made
- §2: unit test with `LeanBackend(lean_binary="does_not_exist")` → asserts
  `UNDECIDED/OUT_OF_SCOPE` with binary-not-found detail
- §3: unit test with a `sleep 60` mock backend that ignores SIGKILL on the
  direct child; assert grandchild also dies
- §4: unit test with captured Lean `--json` fixture; assert axiom list matches
- §5: integration test that verifies REPL warm-start latency < 100ms vs
  subprocess cold start ~8000ms
- §6: unit test that unknown diagnostic → `UNDECIDED/UNCLASSIFIED` (not
  `PARSE_FAILURE`)

## Related documents

- `../CLAUDE.md` — the source spec (§0-8 v0, §9-13 Phase 2)
- `../lean_backend/README.md` — Lean 4 harness placeholder + v0.2 plan
- rei-aios `data/external-prior-art/gemini-lean-verify-2026-08-22/` — source
  material archival (spec + impl + critique, immutable)
- rei-aios `data/external-prior-art/checker-spec-v0-2026-08-22/` — the
  original CHECKER_SPEC_v0.md source

## Implementation status (2026-08-22, v0.2.0a1)

Landed as isolated, testable utility modules — NOT yet wired into a real
running LeanBackend. LeanBackend real impl (Stage 2 of §5) will consume
these utilities as-is:

| Protocol | Status | Location | Tests |
|---|---|---|---|
| §1 A1 Sandbox | doc only (env-level, not code) | this file | n/a |
| §2 A2 spawn error | **landed** | `rei_checker/subprocess_util.py` `_run_lean_safely` | `TestSubprocessUtil` (4 cases) |
| §3 A3 process tree kill | **landed** | `rei_checker/subprocess_util.py` `_kill_process_tree` | `TestSubprocessUtil` (1 case, cross-platform) |
| §4 B4 axiom JSON parse | **landed** | `rei_checker/axiom_parser.py` | `TestAxiomParser` (10 cases with fixtures) |
| §5 C7 REPL server | Stage 1 plumbing done | `lean_backend/` (STEP 1367) | 13 smoke pass (Stage 1) |
| §6 D11 UNCLASSIFIED | **landed** | `rei_checker/schema.py::ReasonCode.UNCLASSIFIED` | `TestReasonCodeUnclassified` (3 cases) + updated `test_reason_code_has_seven_values` |

Total v0.2 tests: 18 new (73/73 pass on 2026-08-22). Real LeanBackend
wiring is a separate STEP.

## Version

- v1.0 (2026-08-22) — initial extraction from chat-Claude critique of
  Gemini's `lean-verify` TypeScript implementation. Author: Claude Code
  (rei-aios STEP 1366). No implementation code changed — this is a
  prep/planning document only.
- v1.1 (2026-08-22) — implementation-status table added after v0.2.0a1
  landed §2/§3/§4/§6 utility modules (rei-aios STEP 1370, Arc 3). §1
  still doc-only, §5 still Stage 1 plumbing.
