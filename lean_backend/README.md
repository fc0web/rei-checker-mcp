# lean_backend/ — Lean 4 harness (v0.2 candidate、 not yet implemented)

This directory is reserved for the real Lean 4 backend harness. Spec §5:
「Lean4 のみ」 is the intended sole real backend. v0 spike leaves this
empty on purpose — the `LeanBackend` class in `rei_checker/backend.py`
is currently a stub that always returns `UNDECIDED/OUT_OF_SCOPE`.

## Prerequisite (2026-08-22 追加): READ [`../docs/V02_PROTOCOL.md`](../docs/V02_PROTOCOL.md) FIRST

Before writing any code in this directory, read the v0.2 protocol document.
It captures 5 non-negotiable prerequisites distilled from the chat-Claude
critique of Gemini's `lean-verify` TypeScript implementation (rei-aios
STEP 1366 archival). Skipping any of them silently breaks the tool's
discipline (spec §1.1-§1.2) or opens a security hole:

- §1 A1 — **Sandbox** (environment, not code): nsjail / Docker / Job Object
- §2 A2 — spawn error handling (FileNotFoundError / OSError)
- §3 A3 — process tree kill (POSIX process group, Windows taskkill /T)
- §4 B4 — `--json` axiom parsing through JSON message field
- §5 C7 — **REPL server**, not subprocess-per-request (architectural)
- §6 D11 — `ERR_UNCLASSIFIED` reason code (silent misclassification prevent)

## v0.2 plan (not scheduled, per protocol §5)

Write a small Lean 4 project here that:

1. Accepts one expression via stdin (or a temp file path via argv).
2. Wraps it as a Lean 4 statement in a scratch buffer with a preamble
   that imports Mathlib subset (or a pinned axiom-free core).
3. **Uses `leanprover-community/repl` (or equivalent persistent REPL) —
   NOT subprocess-per-request.** Cold-start cost of `import Mathlib.Tactic`
   is 8-15 seconds; per-request subprocess makes the tool unusable
   (protocol §5).
4. Prints one of `VALID` / `INVALID` / `UNDECIDED` + reason to stdout.
5. Exits within a strict wall-clock budget passed via `--timeout-ms N`.
6. Runs inside the sandbox layer (protocol §1) — the Python-side
   `LeanBackend` documents this constraint, does not try to enforce it
   in-process (that would give false confidence).

## Why not now?

Spec §6 実装順序 step 1 is 「Lean4 を 叩いて 真偽を返す 最小の関数」.
The v0 spike deferred this to lower the first-run friction: users can
`git clone && python -m rei_checker verify "1 + 1 = 2"` without installing
Lean 4 or elan. The Mock backend covers the interface contract; the
Lean backend covers real judgment. Both share the same 3-value +
reason_code output shape, so swapping in the real one is a single-file
change once this harness exists.

## Not going to be

- A general-purpose theorem prover
- A tactic library
- A Mathlib fork
- A Lean 4 plugin / VS Code extension

It's the smallest possible bridge that lets Python call Lean 4 to get
one three-valued answer for one expression. Nothing more.
