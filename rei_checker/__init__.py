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
v0.4.0a1 (2026-08-26): stats() §7 by_decision timing diagnostic landed
    (opt-in via stats(include_by_decision=True), spec §1.3 preserved:
    verify() default surface unchanged; timing p50/p90/p99 grouped by
    verdict for hardware-substrate diagnostic).

    NOTE (2026-09-11, STEP 1945 refs): version drift discovered —
    pyproject was already 0.4.0a1 while __init__.__version__ +
    CHECKER_VERSION lagged at 0.3.0a1, causing every ledger row written
    under v0.4 code to be marked as v0.3. __init__ synced to pyproject
    (no version bump). Past ledger rows retain their 0.3.0a1 marker
    (append-only, no retroactive rewrite; the drift itself is preserved
    as a diagnostic artifact of the discovery window).
v0.5.0a1 (2026-09-11, STEP 1945 β-1 implementation): Citation stream adapter.
    4-band internal citation verdict (verified / casefold NEITHER / punct
    NEITHER / paraphrase NEITHER / not_found / unreachable) collapses to
    Body 3-value Verdict + 4 CITATION_* reason codes via citation_adapter.
    Spec §1.2 invariant preserved (reason_code only with UNDECIDED); spec
    §1.3 preserved (Verdict enum unchanged, no 4th value at API boundary).
    ReasonCode enum extended with 4 UNDECIDED-only citation codes:
    CITATION_CASE_DRIFT / CITATION_PUNCT_NORMALIZATION / CITATION_PARAPHRASE
    / CITATION_UNREACHABLE. Consumed by rei-aios sidecar
    data/tabs/rei-aios-ab/reflection-checker/skeleton/citation_verify.py
    (peer implementation). Central hypothesis (chat-Claude via 藤本さん relay):
    repair efficiency is bounded by information density of a single
    rejection; per-band reason codes make that density explicit.
"""

__version__ = "0.5.0a1"
CHECKER_VERSION = f"rei-checker-mcp/{__version__}+citation-stream-beta1-2026-09-11"

from rei_checker.schema import (
    Verdict,
    ReasonCode,
    VerifyResult,
    StatsResult,
    LedgerEntry,
)
from rei_checker.citation_adapter import (
    BodyVerdictWithReason,
    to_body_verdict,
    reason_code_to_repair_action,
    CITATION_VERIFIED,
    CITATION_CASEFOLD_NEITHER,
    CITATION_PUNCT_NEITHER,
    CITATION_PARAPHRASE_NEITHER,
    CITATION_NOT_FOUND,
    CITATION_UNREACHABLE,
    ALL_CITATION_VERDICTS,
)

__all__ = [
    "__version__",
    "CHECKER_VERSION",
    "Verdict",
    "ReasonCode",
    "VerifyResult",
    "StatsResult",
    "LedgerEntry",
    "BodyVerdictWithReason",
    "to_body_verdict",
    "reason_code_to_repair_action",
    "CITATION_VERIFIED",
    "CITATION_CASEFOLD_NEITHER",
    "CITATION_PUNCT_NEITHER",
    "CITATION_PARAPHRASE_NEITHER",
    "CITATION_NOT_FOUND",
    "CITATION_UNREACHABLE",
    "ALL_CITATION_VERDICTS",
]
