"""rei-checker-mcp — formal-verification checker MCP server.

One expression, three-valued verdict (VALID / INVALID / UNDECIDED), no LLM
in judgment path. See CLAUDE.md for the full design spec.

v0.1.0a1 (2026-08-22): spike implementation of spec §0-8 (v0 core).
v0.2.0a1 (2026-08-22): V02_PROTOCOL.md §2/§3/§4/§6 utility modules landed
    (axiom_parser + subprocess_util + ReasonCode.UNCLASSIFIED). §5 REPL
    harness Stage 1 lives in lean_backend/. LeanBackend real impl (Stage 2)
    is a future STEP — v0.2.0a1 is "protocol utilities in place, not yet
    wired to a running Lean". Phase 2 (§9-13) still deferred.
"""

__version__ = "0.2.0a1"
CHECKER_VERSION = f"rei-checker-mcp/{__version__}+utils-2026-08-22"

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
