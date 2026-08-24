# `rei-checker-mcp` (CHECKER) — Positioning (2026-Q3)

**Framing (2026-08-25).** **Independent Verifier for Machine-Emitted Formal Claims.** An independent verification substrate for claims emitted by machines. Anchored in Lean 4, verdict-neutral. Durable across generations of upstream generators (LLM agents, world models, neurosymbolic systems, continual-learning models) — the verifier judges the *claim*, not the *class of generator*.

**One line.** A single-purpose MCP server that returns `VALID / INVALID / UNDECIDED` for a formal claim, with **no LLM on the decision path**.

**Author**: Nobuki Fujimoto (藤本 伸樹).
**Spec**: [`CHECKER_SPEC_v0_en.md`](./CHECKER_SPEC_v0_en.md) (English distillation) · [`CHECKER_SPEC_v0.md`](./CHECKER_SPEC_v0.md) (JP, authoritative for intent).
**Reference implementation**: [`rei_checker/`](../rei_checker/) in this repository.
**Verification corpus**: `https://fc0web.github.io/lean-d-fumt8/` (Lean 4, zero-sorry, no-Mathlib) and its error database at `docs/errors/`.
**Package name**: `rei-checker-mcp` on GitHub. Spec identifier `CHECKER_SPEC v0` retained for continuity.

---

## 1. Why this, why now

Three signals from mid-2026 converge on the same missing piece.

**Hugging Face — trending #1 paper (August 2026)**: *"Demystifying Agent Skills: Why They Work — Until They Don't."* The paper is a taxonomy of the ways agent-authored artifacts silently fail. It names the failure modes. It does not ship a way to catch them.

**GitHub — the MCP-audit gap**: several projects have appeared to audit installed MCP servers against known-bad registries. They are metadata checks. None of them verify that an MCP server's answer is *true*.

**GitHub — the 1-file success shape**: Matt Pocock's `skills` sits at trending #1 (~11k stars/week) as a taxonomy of what to build. Karpathy's 4-principle CLAUDE.md distilled to a single file has crossed 156k stars. In this window, a well-written specification beats a large codebase.

CHECKER is what the first two signals ask for, shaped like the third.

---

## 2. What CHECKER is

The v0 contract, verbatim from spec §4:

```
verify(expression, context?, timeout_ms?)
  -> { verdict: VALID | INVALID | UNDECIDED,
       reason_code?, detail?,
       elapsed_ms, checker_version }

stats()
  -> { total, valid, invalid, undecided,
       decision_rate, reason_breakdown }
```

Three invariants (spec §3):

1. **No LLM on the decision path.** Verdicts come from Lean 4 (or another deterministic backend). An LLM may pre-process; its output must then pass through the checker.
2. **When we cannot decide, we say so.** `UNDECIDED` is a first-class return value, not an exception. Timeouts, unparseable input, missing axioms — all resolve to `UNDECIDED` + a reason code.
3. **The internal logic does not leak.** The public verdict alphabet is exactly three symbols. Richer internal representations (e.g. an 8-valued logic) may exist behind an explicit `verbose` option; they do not appear in the default response.

The sole success metric is `decision_rate = (VALID + INVALID) / total`. The v0 target is not "high decision rate" — it is **"decision rate is measurable."** An initial value of `0.1` is acceptable (spec §6).

---

## 3. What CHECKER is not

- **Not a tutor.** It returns verdicts, not explanations. Explanation is human territory (spec §12).
- **Not a benchmark.** It measures `decision_rate` on inputs, not a ranking of models.
- **Not a rating agency.** Post-v0 harnesses measure `overconfidence_rate`; they never composite scores into a single number, and they never build a leaderboard (spec §13, principle 4).
- **Not another agent framework.** It is one MCP server with two tools.
- **Not a Claude-specific tool.** The MCP spec is the target. Claude Desktop / claude.ai quirks are not depended on (spec §8).

---

## 4. Relation to adjacent projects

| Project | What it does | Where CHECKER fits |
|---|---|---|
| Matt Pocock — `skills` | Taxonomy of *what* an agent should be able to do. | Complementary. A skill is a description; a verdict is confirmation. `skills` says "here is what a Lean-proof-writer skill looks like." CHECKER says "here is whether the proof it wrote is true." |
| *"Demystifying Agent Skills"* (HF trending #1, 2026-08) | Diagnosis of the failure modes of agent-authored artifacts. | CHECKER is a countermeasure for one of those failure modes — the one where the agent's artifact looks correct and is not. It does not address planning, tool-selection, or hallucinated APIs. |
| MCP-audit tools | Check MCP server *metadata* against known-bad registries. | Different layer. Those tools ask "is this server installed from a safe source?" CHECKER answers "is this server's answer true?" Both are needed. |
| Karpathy CLAUDE.md (156k stars) | Distills 4 behavioral principles for coding agents into one file. | Same shape at the specification layer. CHECKER's spec is deliberately a single file for the same reason: in this window, a precise specification propagates faster than a codebase. |

CHECKER does **not** compete with any of these. It occupies the seat none of them fills: *deterministic verification of a single formal claim*.

---

## 5. Five-minute proof

The full path from claim to verdict:

```
python -m rei_checker verify path/to/asset.lean --timeout-ms 5000
```

Output is JSON. Exit code is `0` for any well-formed response, including `UNDECIDED` — per spec §3.2, `UNDECIDED` is not an error.

The Lean-side contract: the asset ends with a line that prints `VERDICT VALID` or `VERDICT INVALID` on stdout. Anything else resolves to `UNDECIDED / UNSUPPORTED_SYNTAX`. The checker never guesses.

The verification corpus this ships against — the `lean-d-fumt8` library — is Apache-2.0, 29 theorems, all `decide`-proved, zero `sorry`, no `Mathlib`. Its error database at `docs/errors/` documents fifteen recurring Lean 4 failure modes and, on each page, exactly how they surface through `verify()` + `reason_code` today, and through the planned Layer 2 tools tomorrow.

---

## 6. Roadmap

**v0 (this)**: `verify` + `stats`, Lean 4 backend, refutation ledger, decision-rate measurable.

**Post-v0 Layer 3 — Harnesses**:

- `calibrate(model_id, dataset_id)` — measure `overconfidence_rate`, `silent_failure_rate`, `abstention_accuracy`, `decisive_correct_rate`. **The failure-mode instrument that "Demystifying Agent Skills" describes but does not build.**
- `regression(baseline_id, current_id)` — detect drift in `decision_rate` between checker builds.
- Transfer harness — design only; not implemented without institutional partners.

**Post-v0 Layer 2 — Education-facing**: `locate_first_error`, `boundary_report`, `escalate`. Thin wrappers over Layer 1; no independent decision logic; no explanation generation.

Implementation order after v0 is deliberately **Layer 3② (calibration) → Layer 3① (regression) → Layer 2**. Layer 3② lands first because it stands alone — a working calibration instrument does not require a learner cohort, an institutional partner, or a large user base. It is the piece a paper can be written from.

---

## 7. Non-solicitation

This document is a positioning artifact, not a call for contributors, sponsors, or partnerships. If a reader wants to run it, the spec and the reference implementation are enough. If a reader wants to file a defect, the refutation ledger — once it exists — is the interface.

*Do not hurry. Slowly.* (spec §12)
