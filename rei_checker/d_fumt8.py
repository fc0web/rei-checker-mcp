"""D-FUMT₈ 8-value logic mapping — INTERNAL projection layer only.

Spec §1.3 preserved: this module maps (Verdict, ReasonCode) → D-FUMT₈ value
for **ledger annotation only**. The MCP API surface (verify() response,
StatsResult.reason_breakdown) does NOT expose D-FUMT₈ values by design.

Why annotate ledger with D-FUMT₈?
    chat-Claude 2026-08-23 2-turn arc identified a "接続 gap": Lean 4
    sorry-zero evidence + NEITHER 意味論 (rei-aios STEP 1349/1350/1371/1376/
    1377/1379/1397) are both present in the Rei stack, but the checker's
    3-value verdict at the API boundary drops the finer-grained "why
    undecidable" information from downstream analysis. Recording D-FUMT₈
    at the ledger layer restores analytical access without violating spec
    §1.3 (which prohibits exposing the finer values at the API surface).

    Downstream consumers (rei-aios MCP, stats aggregation, cross-project
    analysis) can grep ledger.jsonl for `d_fumt8` field distribution.
    The API caller still receives clean 3-value verdicts.

Mapping table:
    VALID                        → TRUE (⊤)
    INVALID                      → FALSE (⊥)
    UNDECIDED / TIMEOUT          → NEITHER (〜)   [chat-Claude 「便りが来ない」]
    UNDECIDED / PARSE_FAILURE    → ZERO (〇)      [「まだ問われていない」 = 無効入力]
    UNDECIDED / UNSUPPORTED_SYNTAX → NEITHER (〜) [判定不能 = 表現不能]
    UNDECIDED / MISSING_AXIOM    → NEITHER (〜)   [判定不能 = 前提不足]
    UNDECIDED / DEPTH_LIMIT      → INFINITY (∞)  [評価不能 = 上限 hit]
    UNDECIDED / OUT_OF_SCOPE     → NEITHER (〜)   [判定不能 = 対象外]
    UNDECIDED / UNCLASSIFIED     → NEITHER (〜)   [判定不能 = 未分類]

D-FUMT₈ value definitions (rei-aios src/axiom-os/seven-logic.ts, STEP 406):
    TRUE     = "⊤"  = 1.0   (真)
    FALSE    = "⊥"  = 0.0   (偽)
    BOTH     = "B"  = 2.0   (両立)
    NEITHER  = "〜" = -1.0  (判定不能)
    INFINITY = "∞"  = 3.0   (評価不能 上限)
    ZERO     = "〇" = 4.0   (まだ問われていない、 校正原点)
    FLOWING  = "〜→" = 5.0  (流動)
    SELF     = "⟲"  = 6.0   (自己参照)

Non-emitted values in this mapping (v0.3 spike scope):
    BOTH    — reserved for multi-backend cross-check (未実装)
    FLOWING — reserved for iterative / streaming semantics (該当なし)
    SELF    — reserved for self-referential expressions (該当なし)

Source discipline (STEP 1349/1350 pattern):
    Every mapping call returns a `source: "rei-checker-d-fumt8-mapping"` marker
    so downstream analysis can distinguish this projection from other
    D-FUMT₈ producers (rei-aios connectors, benchtop measurements, etc.).
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from rei_checker.schema import Verdict, ReasonCode


D_FUMT8_MAPPING_SOURCE = "rei-checker-d-fumt8-mapping"


class D8Value(str, Enum):
    """D-FUMT₈ 8-value enumeration. Names match rei-aios seven-logic.ts.

    Values are Enum for ledger serialization (str) and type safety.
    See module docstring for full definitions + numeric encoding.
    """

    TRUE = "TRUE"
    FALSE = "FALSE"
    BOTH = "BOTH"
    NEITHER = "NEITHER"
    INFINITY = "INFINITY"
    ZERO = "ZERO"
    FLOWING = "FLOWING"
    SELF = "SELF"


D8_SYMBOL: Dict[D8Value, str] = {
    D8Value.TRUE:     "⊤",
    D8Value.FALSE:    "⊥",
    D8Value.BOTH:     "B",
    D8Value.NEITHER:  "〜",
    D8Value.INFINITY: "∞",
    D8Value.ZERO:     "〇",
    D8Value.FLOWING:  "〜→",
    D8Value.SELF:     "⟲",
}

D8_NUMERIC: Dict[D8Value, float] = {
    D8Value.TRUE:     1.0,
    D8Value.FALSE:    0.0,
    D8Value.BOTH:     2.0,
    D8Value.NEITHER: -1.0,
    D8Value.INFINITY: 3.0,
    D8Value.ZERO:     4.0,
    D8Value.FLOWING:  5.0,
    D8Value.SELF:     6.0,
}


def map_verdict_to_d8(
    verdict: "Verdict",
    reason_code: Optional["ReasonCode"] = None,
) -> D8Value:
    """Map a 3-value verdict + optional reason_code to D-FUMT₈.

    See module docstring for the mapping table + design justification.

    Deterministic: no randomness, no cache, no external state. Same input
    → same output, forever.

    Args:
        verdict: the 3-value Verdict enum instance.
        reason_code: required if verdict == UNDECIDED, ignored otherwise.

    Returns:
        D8Value corresponding to the mapping table.

    Raises:
        ValueError: if UNDECIDED verdict is passed without reason_code
                    (spec §1.2 invariant — matches VerifyResult.__post_init__).
        TypeError:  if unknown verdict or reason_code enum value slipped
                    through (defensive; upstream types prevent this).
    """
    # Deferred import to avoid circular dependency.
    from rei_checker.schema import Verdict, ReasonCode

    if verdict == Verdict.VALID:
        return D8Value.TRUE
    if verdict == Verdict.INVALID:
        return D8Value.FALSE
    if verdict == Verdict.UNDECIDED:
        if reason_code is None:
            raise ValueError(
                "UNDECIDED verdict requires reason_code for D-FUMT₈ mapping"
            )
        # UNDECIDED verdict — dispatch by reason_code.
        if reason_code == ReasonCode.PARSE_FAILURE:
            return D8Value.ZERO
        if reason_code == ReasonCode.DEPTH_LIMIT:
            return D8Value.INFINITY
        # TIMEOUT / UNSUPPORTED_SYNTAX / MISSING_AXIOM / OUT_OF_SCOPE /
        # UNCLASSIFIED all collapse to NEITHER: chat-Claude 「便りが来ない
        # = 判定不能」 principle. Each is a distinct "cannot decide" mode,
        # but the D-FUMT₈ projection at the ledger layer merges them under
        # NEITHER; reason_code stays in the ledger row for finer analysis.
        return D8Value.NEITHER
    # Defensive: unknown Verdict enum member.
    raise TypeError(f"unknown verdict: {verdict!r}")


def d8_payload(d8: D8Value) -> Dict[str, object]:
    """Build a payload dict with name + symbol + numeric + source marker.

    Matches STEP 1349/1350 pattern (rei-aios): every D-FUMT₈ emission
    carries a source field so downstream consumers can distinguish this
    projection from other D-FUMT₈ producers.
    """
    return {
        "name": d8.value,
        "symbol": D8_SYMBOL[d8],
        "numeric": D8_NUMERIC[d8],
        "source": D_FUMT8_MAPPING_SOURCE,
    }


def spec_table() -> Tuple[Dict[str, object], ...]:
    """Return the mapping table as data (for docs / drift-check / audit).

    STEP 1380 pattern (rei-aios): spec-as-data export so external tools
    can verify the mapping without importing this module. Each entry is
    a plain dict with verdict/reason_code/d8_name/d8_symbol/rationale.
    """
    return (
        {
            "verdict": "VALID",
            "reason_code": None,
            "d8_name": "TRUE",
            "d8_symbol": "⊤",
            "rationale": "証明済 = 真値",
        },
        {
            "verdict": "INVALID",
            "reason_code": None,
            "d8_name": "FALSE",
            "d8_symbol": "⊥",
            "rationale": "反証済 = 偽値",
        },
        {
            "verdict": "UNDECIDED",
            "reason_code": "TIMEOUT",
            "d8_name": "NEITHER",
            "d8_symbol": "〜",
            "rationale": "chat-Claude 「便りが来ない」 = 判定不能",
        },
        {
            "verdict": "UNDECIDED",
            "reason_code": "PARSE_FAILURE",
            "d8_name": "ZERO",
            "d8_symbol": "〇",
            "rationale": "まだ問われていない = 無効入力 (校正原点)",
        },
        {
            "verdict": "UNDECIDED",
            "reason_code": "UNSUPPORTED_SYNTAX",
            "d8_name": "NEITHER",
            "d8_symbol": "〜",
            "rationale": "判定不能 = 表現不能",
        },
        {
            "verdict": "UNDECIDED",
            "reason_code": "MISSING_AXIOM",
            "d8_name": "NEITHER",
            "d8_symbol": "〜",
            "rationale": "判定不能 = 前提不足",
        },
        {
            "verdict": "UNDECIDED",
            "reason_code": "DEPTH_LIMIT",
            "d8_name": "INFINITY",
            "d8_symbol": "∞",
            "rationale": "評価不能 = 上限 hit",
        },
        {
            "verdict": "UNDECIDED",
            "reason_code": "OUT_OF_SCOPE",
            "d8_name": "NEITHER",
            "d8_symbol": "〜",
            "rationale": "判定不能 = 対象外",
        },
        {
            "verdict": "UNDECIDED",
            "reason_code": "UNCLASSIFIED",
            "d8_name": "NEITHER",
            "d8_symbol": "〜",
            "rationale": "判定不能 = 未分類 (V02_PROTOCOL §6 D11)",
        },
    )
