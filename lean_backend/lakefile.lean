import Lake
open Lake DSL

/-!
# lean-checker-repl (v0.2.1 spike, Stage 1 = plumbing only)

Minimal Lean 4 REPL harness for rei-checker-mcp v0.2 LeanBackend.

**Stage 1 (this spike)**: proves the architecture
- Persistent stdin/stdout JSON IPC loop (no cold-start per request)
- Hardcoded truth table matching MockBackend semantics
- Zero external dependencies (only Lean.Data.Json stdlib)

**Stage 2 (v0.2.2 or later, NOT this spike)**: real elaboration
- Dynamic `Lean.Elab` API to try `decide` tactic on input
- Refutation via `Not <expr>` attempt (spec §1.2 double check)
- Axiom check via `#print axioms` post-elaboration

See ../docs/V02_PROTOCOL.md for the full v0.2 protocol.
-/

package «lean-checker-repl» where
  -- Keep default settings. No leanOptions / precompileModules / etc.
  -- Spike scope: minimum to build a runnable binary.

@[default_target]
lean_exe «lean_checker_repl» where
  root := `Main
  -- Support wide input on stdin (Lean.Data.Json handles UTF-8 by default).
  supportInterpreter := false
