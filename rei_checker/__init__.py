"""rei-checker-mcp — formal-verification checker MCP server.

One expression, three-valued verdict (VALID / INVALID / UNDECIDED), no LLM
in judgment path. See CLAUDE.md for the full design spec.

v0.1.0a1 (2026-08-22): spike implementation of spec §0-8 (v0 core).
v0.2.0a1 (2026-08-22): V02_PROTOCOL.md §2/§3/§4/§6 utility modules landed
    (axiom_parser + subprocess_util + ReasonCode.UNCLASSIFIED). §5 REPL
    harness Stage 1 lives in lean_backend/. LeanBackend real impl (Stage 2)
    is a future STEP — v0.2.0a1 is "protocol utilities in place, not yet
    wired to a running Lean". Phase 2 (§9-13) still deferred.
v0.3.0a1 (2026-08-24, STEP 1401): pending-lean4-neither-mcp-connector
    (b) pickup. LeanBackend wired to lean_checker_repl.exe via persistent
    JSON REPL (Stage 1 semantics — matches MockBackend truth table).
    D-FUMT₈ internal projection added at ledger layer only (spec §1.3
    preserved: verify() / stats() default surface unchanged, opt-in
    d_fumt8_breakdown via stats(include_d_fumt8=True)).
"""

__version__ = "0.3.0a1"
CHECKER_VERSION = f"rei-checker-mcp/{__version__}+lean-repl-d8-2026-08-24"

from rei_checker.schema import (
    Verdict,
    ReasonCode,
    VerifyResult,
    StatsResult,
    LedgerEntry,
)

__all__ = [
    "__version__",
    "CHECKER_VERSION",
    "Verdict",
    "ReasonCode",
    "VerifyResult",
    "StatsResult",
    "LedgerEntry",
]
