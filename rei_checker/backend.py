"""Checker backend abstraction.

Spec §5: 「Lean4 のみ」 for real judgments. But v0 spike keeps the interface
mockable so the schema (§2), ledger (§4), and MCP wrapper (§5) can be
validated without a Lean 4 install.

The Backend contract is intentionally narrow:
- Input:  expression string (already normalized upstream), optional context
- Output: (Verdict, Optional[ReasonCode], Optional[detail]) tuple
- Constraint (spec §1.1): the backend MUST NOT call any LLM. Failure to
  respect this makes the whole tool a lie.

MockBackend: hard-coded truth table for the tests + fallback UNDECIDED /
OUT_OF_SCOPE. Useful for CI where Lean 4 is not available.

LeanBackend: subprocess wrapper skeleton. v0.2 candidate — the actual
`lean --run` invocation and result parsing are deferred to a follow-up
spike once we have a Lean 4 harness written (see lean_backend/ dir).
"""

from __future__ import annotations

import subprocess
import time
from abc import ABC, abstractmethod
from typing import Optional, Tuple

from rei_checker.schema import Verdict, ReasonCode


BackendResult = Tuple[Verdict, Optional[ReasonCode], Optional[str]]


class CheckerBackend(ABC):
    """Contract for a decisive judgment engine.

    Spec §1.1: LLM MUST NOT appear anywhere on the path from input to
    Verdict. Implementations that violate this rule are not backends,
    they are guesses wearing a backend's clothes.
    """

    #: Short identifier for the backend, folded into checker_version.
    name: str = "abstract"

    @abstractmethod
    def check(
        self,
        expression: str,
        *,
        context: Optional[str] = None,
        timeout_ms: int = 5_000,
    ) -> BackendResult:
        """Judge one expression.

        MUST return within `timeout_ms` (or return UNDECIDED/TIMEOUT).
        MUST NOT raise on malformed input (return UNDECIDED/PARSE_FAILURE).
        MUST NOT call any LLM (spec §1.1).
        """
        raise NotImplementedError


class MockBackend(CheckerBackend):
    """Deterministic mock for interface validation and CI.

    Contains a small hard-coded truth table:
    - `1 + 1 = 2`               → VALID
    - `1 + 1 = 3`               → INVALID
    - `∀ n : ℕ, n + 0 = n`      → VALID
    - `∀ n : ℕ, n + 1 = n`      → INVALID
    - `True`                    → VALID
    - `False`                   → INVALID
    - empty / whitespace        → UNDECIDED/PARSE_FAILURE
    - `<timeout-test>`          → UNDECIDED/TIMEOUT (simulates hang)
    - `<syntax-test>`           → UNDECIDED/UNSUPPORTED_SYNTAX
    - `<axiom-test>`            → UNDECIDED/MISSING_AXIOM
    - `<depth-test>`            → UNDECIDED/DEPTH_LIMIT
    - anything else             → UNDECIDED/OUT_OF_SCOPE

    Spec §7 requires tests for every UNDECIDED reason_code, so each one
    has a deterministic trigger string.
    """

    name = "mock"

    _TRUE_TABLE = frozenset({
        "1 + 1 = 2",
        "∀ n : ℕ, n + 0 = n",
        "True",
    })

    _FALSE_TABLE = frozenset({
        "1 + 1 = 3",
        "∀ n : ℕ, n + 1 = n",
        "False",
    })

    _REASON_TRIGGERS = {
        "<timeout-test>": ReasonCode.TIMEOUT,
        "<syntax-test>": ReasonCode.UNSUPPORTED_SYNTAX,
        "<axiom-test>": ReasonCode.MISSING_AXIOM,
        "<depth-test>": ReasonCode.DEPTH_LIMIT,
    }

    def check(
        self,
        expression: str,
        *,
        context: Optional[str] = None,
        timeout_ms: int = 5_000,
    ) -> BackendResult:
        # Empty / whitespace → PARSE_FAILURE.
        if not expression or not expression.strip():
            return (
                Verdict.UNDECIDED,
                ReasonCode.PARSE_FAILURE,
                "expression is empty or whitespace-only",
            )

        expr = expression.strip()

        # Trigger strings for each reason_code (spec §7 test priority).
        if expr in self._REASON_TRIGGERS:
            code = self._REASON_TRIGGERS[expr]
            return (
                Verdict.UNDECIDED,
                code,
                f"mock trigger for {code.value}",
            )

        # Hard-coded truth table.
        if expr in self._TRUE_TABLE:
            return (Verdict.VALID, None, None)
        if expr in self._FALSE_TABLE:
            return (Verdict.INVALID, None, None)

        # Default: OUT_OF_SCOPE (spec §1.2 — return UNDECIDED, don't
        # guess, don't call an LLM).
        return (
            Verdict.UNDECIDED,
            ReasonCode.OUT_OF_SCOPE,
            "MockBackend has no rule for this expression",
        )


class LeanBackend(CheckerBackend):
    """Lean 4 subprocess backend (spike stub, spec §6 step 1).

    v0 spike scope: interface defined, timeout enforcement present, but
    the actual Lean 4 elaboration pipeline is a placeholder. Currently
    returns UNDECIDED/OUT_OF_SCOPE for every input, with a detail line
    identifying itself as the stub.

    v0.2+ work: write a small Lean 4 harness under lean_backend/ that
    accepts one expression via stdin, runs it through Lean's elaborator,
    and prints VALID / INVALID / UNDECIDED + reason on stdout. Then this
    class becomes a subprocess wrapper around that harness.

    Spec §5 says Lean 4 is the ONLY intended real backend. This stub
    exists so the interface can be exercised end-to-end today.
    """

    name = "lean-stub"

    def __init__(self, lean_binary: str = "lean") -> None:
        self.lean_binary = lean_binary

    def check(
        self,
        expression: str,
        *,
        context: Optional[str] = None,
        timeout_ms: int = 5_000,
    ) -> BackendResult:
        # v0 stub: always UNDECIDED/OUT_OF_SCOPE. Enforcing the
        # interface contract without pretending to check.
        return (
            Verdict.UNDECIDED,
            ReasonCode.OUT_OF_SCOPE,
            "LeanBackend v0 stub: real Lean 4 elaboration not yet wired "
            "(see lean_backend/ dir + v0.2 candidate)",
        )

    def _is_lean_available(self) -> bool:
        """Check whether `lean --version` runs. Utility for future spike."""
        try:
            result = subprocess.run(
                [self.lean_binary, "--version"],
                capture_output=True,
                timeout=5.0,
                text=True,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False


def enforce_timeout(
    backend: CheckerBackend,
    expression: str,
    *,
    context: Optional[str] = None,
    timeout_ms: int = 5_000,
) -> BackendResult:
    """Wrap a backend call with hard timeout enforcement (spec §7).

    If the backend takes longer than `timeout_ms`, return
    UNDECIDED/TIMEOUT rather than letting the caller hang.

    This is a soft-guard: v0 measures elapsed time and reports TIMEOUT
    if the backend already handled it internally. A stricter thread /
    process kill layer is a v0.2 candidate.
    """
    start_ns = time.monotonic_ns()
    try:
        result = backend.check(
            expression, context=context, timeout_ms=timeout_ms
        )
    except Exception as e:
        # Spec §7: "不正な入力でクラッシュしない". Any backend exception
        # is folded into UNDECIDED/PARSE_FAILURE.
        return (
            Verdict.UNDECIDED,
            ReasonCode.PARSE_FAILURE,
            f"backend raised {type(e).__name__}: {e}",
        )
    elapsed_ms = (time.monotonic_ns() - start_ns) // 1_000_000
    # If the backend took longer than the budget, upgrade to TIMEOUT
    # (whichever reason the backend returned is superseded).
    if elapsed_ms > timeout_ms:
        return (
            Verdict.UNDECIDED,
            ReasonCode.TIMEOUT,
            f"exceeded timeout_ms={timeout_ms} (actual {elapsed_ms} ms)",
        )
    return result
