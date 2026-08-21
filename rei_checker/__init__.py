"""rei-checker-mcp — formal-verification checker MCP server.

One expression, three-valued verdict (VALID / INVALID / UNDECIDED), no LLM
in judgment path. See CLAUDE.md for the full design spec.

v0.1.0a1 (2026-08-22): spike implementation of spec §0-8 (v0 core).
Phase 2 (§9-13 calibration/education/regression harness) deferred.
"""

__version__ = "0.1.0a1"
CHECKER_VERSION = f"rei-checker-mcp/{__version__}+spike-2026-08-22"

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
