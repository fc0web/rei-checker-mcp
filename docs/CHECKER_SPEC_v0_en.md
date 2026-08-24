# CHECKER_SPEC v0 — Independent Verifier for Machine-Emitted Formal Claims

> **Framing (2026-08-25)**: An **independent verification substrate for claims
> emitted by machines**. Anchored in Lean 4, verdict-neutral. Short name:
> `rei-verifier`. This framing is durable across generations of upstream
> generators (LLM agents, world models, neurosymbolic systems, continual-learning
> models) — the spec verifies the *claim*, not the *class of generator*.

- **Status**: Draft (v0 scope frozen; Post-v0 sections deferred)
- **Author of source spec**: Nobuki Fujimoto (`CHECKER_SPEC_v0.md`, Japanese original)
- **This document**: English distillation of the v0 scope only (§0–§8 of the source)
- **License**: AGPL-3.0 (implementation); CC BY-NC-SA 4.0 (spec text)
- **Audience**: Implementors placing this file at repository root as `CLAUDE.md` or `SPEC.md`
- **Short name**: `rei-verifier`
- **Spec identifier retained**: `CHECKER_SPEC v0` (do not break existing references)

---

## 1. Terminology

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** in this document are to be interpreted as described in RFC 2119.

Additional terms:

- **Verdict** — the single-symbol result of a verification call: `VALID`, `INVALID`, or `UNDECIDED`.
- **Decision path** — the code path that produces the verdict.
- **Refutation ledger** — the append-only log of every request and its verdict.
- **Checker** — the process that owns the decision path.

---

## 2. Purpose

The Checker accepts one expression at a time and returns whether it is true. Nothing more.

It is **not** a tutor, a learning platform, an explainer, or a chat surface. It is a single-function MCP server invoked by agents (including Claude Code) or humans that want a deterministic answer to a single formal claim.

Its reason for existing is the invariant in §3.1: **no LLM sits on the decision path**. If you remove that invariant, this project has no reason to exist.

---

## 3. Invariants

These three invariants are load-bearing. Any change to them requires a new major version, not a patch.

### 3.1 No LLM on the decision path

- Verdicts **MUST** be produced by Lean4 or another deterministic verification asset.
- An LLM **MAY** be used in preprocessing (e.g., natural-language → formal-syntax candidate generation), but its output **MUST** then pass through the checker.
- No code path **MAY** return "probably correct." That value does not exist in this system.

### 3.2 If we cannot decide, we say so

Every response **MUST** carry exactly one of three verdicts:

| Verdict | Meaning |
|---|---|
| `VALID` | The verification asset confirmed the expression is true. |
| `INVALID` | The verification asset confirmed the expression is false. |
| `UNDECIDED` | The verification asset could not decide within the constraints given. |

`UNDECIDED` is **not** an error. It is a first-class return value. Timeouts, unparseable input, missing axioms, and depth limits all resolve to `UNDECIDED` with a reason code, never to an exception that terminates the call.

Reason codes (initial registry — see Appendix A):
`TIMEOUT`, `PARSE_FAILURE`, `UNSUPPORTED_SYNTAX`, `MISSING_AXIOM`, `DEPTH_LIMIT`, `OUT_OF_SCOPE`.

### 3.3 The underlying logic does not leak into the API

The checker **MAY** use an 8-valued internal logic (D-FUMT₈) or any other representation. The **external interface MUST NOT** require the caller to understand it.

- The public verdict alphabet is `{VALID, INVALID, UNDECIDED}` and no other.
- Richer internal values (e.g., `NEITHER`) **MAY** be exposed later behind an explicit `verbose` option, but **MUST NOT** appear in the default response.

Rationale: designs that require the caller to learn a novel logic to use them are not used.

---

## 4. API Surface

The v0 server **MUST** expose exactly two tools.

```
verify(expression: str, context?: str, timeout_ms?: int)
  -> { verdict: VALID | INVALID | UNDECIDED,
       reason_code?: str,
       detail?: str,
       elapsed_ms: int,
       checker_version: str }

stats()
  -> { total: int,
       valid: int,
       invalid: int,
       undecided: int,
       decision_rate: float,
       reason_breakdown: { <code>: int } }
```

- `checker_version` **MUST** appear on every `verify` response so that any historical verdict is reproducible.
- `reason_code` **MUST** be present whenever `verdict = UNDECIDED`.
- `detail` **SHOULD** carry a short, machine-readable diagnostic string. It **MUST NOT** contain natural-language tutoring, hints, or corrections.

---

## 5. Non-Goals (v0)

The following are **out of scope** for v0. If an implementor finds themselves building one of these, they **MUST** stop and confirm before continuing.

- UI or web frontend
- User accounts, authentication, billing
- Gamification, progress tracking, learning history
- Natural-language dialog or explanation generation
- Multiple verification backends (Lean4 only in v0)
- Dependencies on Claude-specific behavior

---

## 6. The Sole Metric

```
decision_rate = (VALID + INVALID) / total
```

- `stats()` **MUST** return `decision_rate` on every call.
- The refutation ledger **MUST** be sufficient to recompute `decision_rate` for any past time window.
- User counts, star counts, and download counts **MUST NOT** be treated as success metrics.

The success condition for v0 is **not** "decision rate is high." It is **"decision rate is measurable."** An initial value of `0.1` is acceptable.

---

## 7. Refutation Ledger

`UNDECIDED` results **MUST NOT** be discarded. They are the primary input to the next iteration.

Each ledger entry **MUST** record:

- The normalized input expression
- The reason code
- Timestamp (UTC, ISO 8601)
- `checker_version`
- `elapsed_ms`

Additional rules:

- The ledger **MUST NOT** record personal data or user identifiers.
- The storage format **SHOULD** be append-only (JSONL recommended).
- The ledger is the **only** legitimate basis for deciding what to implement next. Speculative feature additions **MUST NOT** be prioritized over ledger evidence.

If `UNSUPPORTED_SYNTAX` concentrates on a particular construct, that construct is the next sprint. Nothing else.

---

## 8. Protocol

- The server **MUST** implement the MCP specification. It **MUST NOT** depend on quirks of Claude Desktop or claude.ai.
- Both `stdio` and `HTTP/SSE` transports are anticipated. v0 **MAY** ship `stdio` only, but the I/O layer **MUST** be separated so that adding `HTTP/SSE` does not require rewriting the core.
- The tool category is **`checker`** (returns a verdict). Harness features (see §14) **MUST NOT** be mixed into the checker.
- License: AGPL-3.0, matching the parent repository.

---

## 9. Implementation Order

Implement in this order. Do not polish step N until step N−1 runs.

1. A minimal function that shells out to Lean4 and returns a truth value. CLI-only, no MCP.
2. Fix the three-valued verdict schema and reason codes.
3. Append every request to the refutation ledger.
4. Implement `stats()` over the ledger.
5. Wrap the whole thing as an MCP server.
6. Write a `README` such that **a reader who has never heard of D-FUMT₈ can run the server in five minutes.**

Each step **MUST** leave a working artifact. `README` polish before step 5 is a scope violation.

---

## 10. Quality Bar

- **Timeouts MUST always fire.** A hang **MUST** resolve to `UNDECIDED` + `TIMEOUT`.
- **Malformed input MUST NOT crash the server.** It **MUST** resolve to `UNDECIDED` + `PARSE_FAILURE`.
- `checker_version` **MUST** appear in every response. This is what makes past verdicts reproducible.
- Tests **MUST** cover the decision logic. Tests for cases that **should** return `UNDECIDED` **SHOULD** be written before tests for `VALID`/`INVALID` cases — the `UNDECIDED` path is the one that regresses silently.

---

## 11. Verification Assets

The v0 checker delegates to Lean4. The initial verification asset shipped alongside this spec is:

- `AmalaFixpoint.lean` — a self-contained Lean4 module (core Lean4, no `mathlib` dependency) providing a small three-state fixed-point model. This is a **seed asset**, not the whole surface; additional Lean modules will be added ledger-driven.

Implementors **MUST**:

- Pin the Lean4 toolchain version and record it as part of `checker_version`.
- Refuse to load a verification asset that does not compile under the pinned toolchain, and surface this as `UNDECIDED` + `MISSING_AXIOM` for calls that would have depended on it.

Implementors **MUST NOT**:

- Modify verification assets to make failing tests pass.
- Inline interpretive commentary from an asset (e.g., the doctrinal notes at the top of `AmalaFixpoint.lean`) into API responses.

---

## 12. When In Doubt

- Unsure whether to add a feature? **Do not add it.**
- Unsure whether to return "probably correct"? **Return `UNDECIDED`.**
- Unsure whether to expose the underlying theory? **Do not expose it.**
- Do not hurry. Slowly.

---

## 13. Post-v0 (Deferred)

The Japanese source spec (§9–§13) defines two additional layers that are **explicitly out of scope for v0** and **MUST NOT** be implemented until `decision_rate` is measurable in production:

- **Layer 3 — Harnesses.** Calibration harness (`overconfidence_rate`, `silent_failure_rate`, `abstention_accuracy`, `decisive_correct_rate`), regression harness, and (design-only) transfer harness. Implementation order after v0 is **Layer 3② (calibration) → Layer 3① (regression) → Layer 2**.
- **Layer 2 — Education-facing tools.** `locate_first_error`, `boundary_report`, `escalate`. These are thin wrappers over Layer 1; they **MUST NOT** contain independent decision logic and **MUST NOT** generate explanations, corrections, or alternative solutions.

The v0 design **MUST** leave room for these extensions but **MUST NOT** stub, mock, or partially ship them.

Cross-cutting principles carried into Post-v0 (from the source spec, §13):

1. No LLM on the decision path — this **also** applies to decisive/hedged labeling inside the calibration harness.
2. Do not hide exclusions. `exclusion_rate` **MUST** be reported alongside every calibration output.
3. Do not generate explanations. Layer 2 returns positions, not prose.
4. Do not build a ranking table. This is an instrument, not a referee.
5. Build Layer 3② before Layer 2.
6. Do not hurry. Slowly.

---

## Appendix A — Reason Code Registry (v0)

| Code | When to return |
|---|---|
| `TIMEOUT` | The verification asset did not return within `timeout_ms`. |
| `PARSE_FAILURE` | The input could not be parsed into a form the checker can pass to the verification asset. |
| `UNSUPPORTED_SYNTAX` | The input parsed, but uses a construct the current verification asset does not accept. |
| `MISSING_AXIOM` | The verification asset ran but could not close the goal because a required axiom or lemma is not present. |
| `DEPTH_LIMIT` | A search or unfolding depth cap was reached. |
| `OUT_OF_SCOPE` | The input is well-formed but falls outside the domain the checker claims to cover. |

New reason codes **MAY** be added in minor versions. Existing codes **MUST NOT** change meaning across versions — a code's semantics are part of the ledger's long-term interpretability.

---

## Appendix B — Source

This document is a scope-narrowed English distillation of `CHECKER_SPEC_v0.md` (Japanese, 306 lines). Where the two disagree, the Japanese source is authoritative for intent; this document is authoritative for the exact wording an English-language implementor is expected to follow.
