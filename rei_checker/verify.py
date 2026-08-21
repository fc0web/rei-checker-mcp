"""Top-level verify() orchestration.

Spec §2: verify(expression, context?, timeout_ms?) → VerifyResult.

Pipeline:
1. Normalize expression (ledger §4 wants normalized text).
2. Call the backend (spec §1.1: no LLM anywhere in this call).
3. Wrap with timeout enforcement (spec §7).
4. Append one ledger row (spec §4: never drop UNDECIDED).
5. Return VerifyResult with checker_version stamped (spec §7).

The default backend is MockBackend so `python -m rei_checker verify "1 + 1 = 2"`
works with zero configuration. LeanBackend can be selected via env var
$REI_CHECKER_BACKEND=lean (v0.2+ when the Lean harness is wired).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from rei_checker import CHECKER_VERSION
from rei_checker.backend import (
    CheckerBackend,
    MockBackend,
    LeanBackend,
    enforce_timeout,
)
from rei_checker.ledger import (
    append_entry,
    normalize_expression,
    utc_now_iso,
)
from rei_checker.schema import (
    LedgerEntry,
    VerifyResult,
    Verdict,
)


DEFAULT_TIMEOUT_MS = 5_000
ENV_BACKEND = "REI_CHECKER_BACKEND"


def _resolve_backend() -> CheckerBackend:
    """Pick backend from env var. Default: MockBackend."""
    name = os.environ.get(ENV_BACKEND, "mock").strip().lower()
    if name == "lean":
        return LeanBackend()
    if name == "mock":
        return MockBackend()
    # Unknown backend name: fall back to Mock and let the caller notice
    # via the verdict detail — better than crashing (spec §7).
    return MockBackend()


def verify(
    expression: str,
    *,
    context: Optional[str] = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    backend: Optional[CheckerBackend] = None,
    ledger_path: Optional[Path] = None,
    record: bool = True,
) -> VerifyResult:
    """Verify one expression. Spec §2.

    Args:
        expression: the string to judge. Normalized before ledger append.
        context: optional context (v0 pass-through; backends may use it).
        timeout_ms: hard budget in milliseconds. Overrun → UNDECIDED/TIMEOUT.
        backend: injected backend (default: env-var-resolved or MockBackend).
        ledger_path: override ledger location (mainly for tests).
        record: append to ledger. Set False only in tests that need isolation.

    Returns:
        VerifyResult with checker_version stamped (spec §7 re-run reproducibility).
    """
    if backend is None:
        backend = _resolve_backend()

    # Timing includes the whole pipeline (backend + ledger write), matching
    # what a client caller experiences.
    start_ns = time.monotonic_ns()

    normalized = normalize_expression(expression)
    verdict, reason_code, detail = enforce_timeout(
        backend,
        normalized,
        context=context,
        timeout_ms=timeout_ms,
    )

    elapsed_ms = (time.monotonic_ns() - start_ns) // 1_000_000

    result = VerifyResult(
        verdict=verdict,
        elapsed_ms=int(elapsed_ms),
        checker_version=CHECKER_VERSION,
        reason_code=reason_code,
        detail=detail,
    )

    if record:
        entry = LedgerEntry(
            ts_utc=utc_now_iso(),
            expression_normalized=normalized,
            verdict=verdict,
            checker_version=CHECKER_VERSION,
            elapsed_ms=int(elapsed_ms),
            reason_code=reason_code,
        )
        append_entry(entry, ledger_path=ledger_path)

    return result
