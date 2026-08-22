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
class StatsResult:
    """Return type of stats(). Spec §2 + §3.

    `decision_rate = (valid + invalid) / total` — the SOLE metric of
    project success. Spec §3.
    """

    total: int
    valid: int
    invalid: int
    undecided: int
    decision_rate: float
    reason_breakdown: Dict[str, int] = field(default_factory=dict)

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "valid": self.valid,
            "invalid": self.invalid,
            "undecided": self.undecided,
            "decision_rate": self.decision_rate,
            "reason_breakdown": dict(self.reason_breakdown),
        }


@dataclass(frozen=True)
class LedgerEntry:
    """One row of the refutation ledger. Spec §4.

    Append-only. No PII, no user identifier. The `expression_normalized`
    field is what the ledger stores — call sites are responsible for
    normalization before append.
    """

    ts_utc: str  # ISO 8601 UTC, e.g. "2026-08-22T10:15:30Z"
    expression_normalized: str
    verdict: Verdict
    checker_version: str
    elapsed_ms: int
    reason_code: Optional[ReasonCode] = None

    def to_jsonl_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSONL writing.

        Field order kept stable for grep-ability. reason_code omitted for
        VALID/INVALID rows.
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
        return d
