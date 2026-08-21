# lean_backend/ — Lean 4 harness (v0.2 candidate、 not yet implemented)

This directory is reserved for the real Lean 4 backend harness. Spec §5:
「Lean4 のみ」 is the intended sole real backend. v0 spike leaves this
empty on purpose — the `LeanBackend` class in `rei_checker/backend.py`
is currently a stub that always returns `UNDECIDED/OUT_OF_SCOPE`.

## v0.2 plan (not scheduled)

Write a small Lean 4 project here that:

1. Accepts one expression via stdin (or a temp file path via argv).
2. Wraps it as a Lean 4 statement in a scratch buffer with a preamble
   that imports Mathlib subset (or a pinned axiom-free core).
3. Runs `lean --run` or elaborates programmatically.
4. Prints one of `VALID` / `INVALID` / `UNDECIDED` + reason to stdout.
5. Exits within a strict wall-clock budget passed via `--timeout-ms N`.

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
