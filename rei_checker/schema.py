"""Schema definitions for rei-checker-mcp.

Spec §1.2: three-valued verdict + reason codes.
Spec §1.3: D-FUMT₈ internal 8-value logic is NOT exposed at the API surface.

All types are frozen dataclasses / str enums so that no LLM downstream can
mutate a returned verdict after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Dict, Any


class Verdict(str, Enum):
    """Three-valued verdict. Spec §1.2.

    Do NOT add a fourth value at this layer. If an internal engine needs
    finer distinctions (D-FUMT₈ NEITHER etc.), collapse to one of these
    three before crossing the API boundary. Spec §1.3.
    """

    VALID = "VALID"
    INVALID = "INVALID"
    UNDECIDED = "UNDECIDED"


class ReasonCode(str, Enum):
    """Reason codes for UNDECIDED verdicts. Spec §1.2.

    Initial set. Add new codes when the ledger (§4) shows a pattern of
    OUT_OF_SCOPE entries that cluster into a distinct category — never
    speculatively.
    """

    TIMEOUT = "TIMEOUT"
    PARSE_FAILURE = "PARSE_FAILURE"
    UNSUPPORTED_SYNTAX = "UNSUPPORTED_SYNTAX"
    MISSING_AXIOM = "MISSING_AXIOM"
    DEPTH_LIMIT = "DEPTH_LIMIT"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    # §6 D11 (V02_PROTOCOL.md): silent-misclassification prevention.
    # Return this when Lean output does not match any known error pattern,
    # with the raw diagnostic in `detail`. When ledger shows rising
    # UNCLASSIFIED frequency, the fix is to read accumulated details and
    # add new rules to classifyFailure — never assume default is correct.
    UNCLASSIFIED = "UNCLASSIFIED"


@dataclass(frozen=True)
class VerifyResult:
    """Return type of verify(). Spec §2.

    - `verdict` is always one of VALID / INVALID / UNDECIDED.
    - `reason_code` is present iff verdict == UNDECIDED (spec §1.2).
    - `detail` is a short free-text hint, optional.
    - `elapsed_ms` is measured wall-clock time inside verify() itself.
    - `checker_version` MUST be included in every response (spec §7).
    """

    verdict: Verdict
    elapsed_ms: int
    checker_version: str
    reason_code: Optional[ReasonCode] = None
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        # Invariant: reason_code iff UNDECIDED.
        if self.verdict == Verdict.UNDECIDED and self.reason_code is None:
            raise ValueError(
                "UNDECIDED verdict MUST include a reason_code (spec §1.2)"
            )
        if self.verdict != Verdict.UNDECIDED and self.reason_code is not None:
            raise ValueError(
                "reason_code is only permitted with UNDECIDED verdict (spec §1.2)"
            )
        if self.elapsed_ms < 0:
            raise ValueError("elapsed_ms must be non-negative")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to plain dict (for MCP responses)."""
        d: Dict[str, Any] = {
            "verdict": self.verdict.value,
            "elapsed_ms": self.elapsed_ms,
            "checker_version": self.checker_version,
        }
        if self.reason_code is not None:
            d["reason_code"] = self.reason_code.value
        if self.detail is not None:
            d["detail"] = self.detail
        return d


@dataclass(frozen=True)
class DecisionTiming:
    """Elapsed-time quantiles for one verdict class.

    v0.4 addition (CHECKER_SPEC v0.1 §7 論点「decision-stratified timing
    diagnostic」). Pure diagnostic — never enters `decision_rate`.
    Preserves Non-goal 0.2 (speed is not a goal) and I5 (no timing in metric).

    Rationale: a checker that returns UNDECIDED fast is different work from
    one that returns VALID slowly. The current marginal timing (absent from
    StatsResult altogether) hides that separation. Reporting by verdict
    surfaces it without promoting timing to a scored quantity.
    """

    p50_ms: int
    p90_ms: int
    p99_ms: int

    def __post_init__(self) -> None:
        if self.p50_ms < 0 or self.p90_ms < 0 or self.p99_ms < 0:
            raise ValueError("percentiles must be non-negative")
        if not (self.p50_ms <= self.p90_ms <= self.p99_ms):
            raise ValueError(
                f"percentiles must be non-decreasing (p50 <= p90 <= p99); "
                f"got p50={self.p50_ms}, p90={self.p90_ms}, p99={self.p99_ms}"
            )

    def to_dict(self) -> Dict[str, int]:
        return {
            "p50_ms": self.p50_ms,
            "p90_ms": self.p90_ms,
            "p99_ms": self.p99_ms,
        }


# Verdict names allowed as keys in StatsResult.by_decision.
# Kept as a module-level constant so the invariant check can reference it
# without importing Verdict enum values in every StatsResult construction.
_ALLOWED_BY_DECISION_KEYS = frozenset({"VALID", "INVALID", "UNDECIDED"})


@dataclass(frozen=True)
class StatsResult:
    """Return type of stats(). Spec §2 + §3.

    `decision_rate = (valid + invalid) / total` — the SOLE metric of
    project success. Spec §3.

    v0.3 addition: optional `d_fumt8_breakdown` field, populated only when
    stats() is called with `include_d_fumt8=True`. Spec §1.3 preserved:
    default off, ledger-only annotation is the primary surface. When
    absent, `to_dict()` omits the field (backward compat).

    v0.4 addition: `by_decision` field with per-verdict elapsed-time
    quantiles (CHECKER_SPEC v0.1 §7 論点). Diagnostic only — never enters
    `decision_rate` (I5). Empty verdict groups are omitted; when the whole
    dict is empty, `to_dict()` omits the field (backward compat).
    """

    total: int
    valid: int
    invalid: int
    undecided: int
    decision_rate: float
    reason_breakdown: Dict[str, int] = field(default_factory=dict)
    by_decision: Dict[str, DecisionTiming] = field(default_factory=dict)  # v0.4 §7
    d_fumt8_breakdown: Optional[Dict[str, int]] = None  # v0.3 opt-in

    def __post_init__(self) -> None:
        if self.total != self.valid + self.invalid + self.undecided:
            raise ValueError(
                "total must equal valid + invalid + undecided"
            )
        if self.total == 0:
            if self.decision_rate != 0.0:
                raise ValueError("decision_rate must be 0.0 when total == 0")
        else:
            expected = (self.valid + self.invalid) / self.total
            if abs(self.decision_rate - expected) > 1e-9:
                raise ValueError(
                    f"decision_rate must equal (valid+invalid)/total; "
                    f"got {self.decision_rate}, expected {expected}"
                )
        # v0.4 §7: by_decision keys must be a subset of the three verdicts.
        # Empty dict is fine (means no timing was aggregated).
        extra_keys = set(self.by_decision) - _ALLOWED_BY_DECISION_KEYS
        if extra_keys:
            raise ValueError(
                f"by_decision keys must be subset of "
                f"{sorted(_ALLOWED_BY_DECISION_KEYS)}; "
                f"got extra keys {sorted(extra_keys)}"
            )

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "total": self.total,
            "valid": self.valid,
            "invalid": self.invalid,
            "undecided": self.undecided,
            "decision_rate": self.decision_rate,
            "reason_breakdown": dict(self.reason_breakdown),
        }
        if self.by_decision:
            d["by_decision"] = {
                k: v.to_dict() for k, v in self.by_decision.items()
            }
        if self.d_fumt8_breakdown is not None:
            d["d_fumt8_breakdown"] = dict(self.d_fumt8_breakdown)
        return d


@dataclass(frozen=True)
class LedgerEntry:
    """One row of the refutation ledger. Spec §4.

    Append-only. No PII, no user identifier. The `expression_normalized`
    field is what the ledger stores — call sites are responsible for
    normalization before append.

    v0.3 addition: optional `d_fumt8` field stores the D-FUMT₈ projection
    (name only, e.g. "NEITHER") for downstream analysis. Spec §1.3 is
    preserved: this field is ledger-only, NOT exposed in VerifyResult /
    stats() decision_rate. See rei_checker/d_fumt8.py for the mapping.
    Old ledger rows without this field remain readable (backward compat).
    """

    ts_utc: str  # ISO 8601 UTC, e.g. "2026-08-22T10:15:30Z"
    expression_normalized: str
    verdict: Verdict
    checker_version: str
    elapsed_ms: int
    reason_code: Optional[ReasonCode] = None
    d_fumt8: Optional[str] = None  # v0.3: D-FUMT₈ name, ledger-only (spec §1.3)

    def to_jsonl_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSONL writing.

        Field order kept stable for grep-ability. reason_code omitted for
        VALID/INVALID rows. d_fumt8 emitted only when present (backward
        compat with pre-v0.3 rows).
        """
        d: Dict[str, Any] = {
            "ts_utc": self.ts_utc,
            "expression_normalized": self.expression_normalized,
            "verdict": self.verdict.value,
            "checker_version": self.checker_version,
            "elapsed_ms": self.elapsed_ms,
        }
        if self.reason_code is not None:
            d["reason_code"] = self.reason_code.value
        if self.d_fumt8 is not None:
            d["d_fumt8"] = self.d_fumt8
        return d
