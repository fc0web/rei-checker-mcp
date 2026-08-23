"""stats() — aggregate the refutation ledger. Spec §2 + §3.

`decision_rate = (VALID + INVALID) / total` is the sole metric of
project success (spec §3). Everything else in the return is
diagnostic — the reason_breakdown tells you what to build next
(spec §4).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Optional

from rei_checker.ledger import read_all_entries
from rei_checker.schema import StatsResult, Verdict


def stats(
    ledger_path: Optional[Path] = None,
    *,
    include_d_fumt8: bool = False,
) -> StatsResult:
    """Read the ledger and return aggregate stats.

    Empty ledger → total=0, decision_rate=0.0, empty reason_breakdown.
    Malformed rows are silently skipped by read_all_entries (spec §4:
    never abort on a bad row).

    Spec §3: this MUST return decision_rate. Everything else exists to
    contextualize it.

    Args:
        ledger_path: optional override for tests.
        include_d_fumt8: v0.3 opt-in flag. When True, adds d_fumt8_breakdown
            to the result (ledger annotation aggregation). Default False
            preserves spec §1.3 (D-FUMT₈ not on default API surface).
            Rows without d_fumt8 field (pre-v0.3 ledger) are skipped in
            the breakdown, not counted as any D-FUMT₈ value.
    """
    entries = read_all_entries(ledger_path)
    total = len(entries)
    valid = sum(1 for e in entries if e.verdict == Verdict.VALID)
    invalid = sum(1 for e in entries if e.verdict == Verdict.INVALID)
    undecided = sum(1 for e in entries if e.verdict == Verdict.UNDECIDED)

    decision_rate = 0.0 if total == 0 else (valid + invalid) / total

    reason_breakdown = Counter(
        e.reason_code.value
        for e in entries
        if e.reason_code is not None
    )

    d_fumt8_breakdown: Optional[dict] = None
    if include_d_fumt8:
        # Only rows that carry d_fumt8 (i.e. v0.3+ writes). Pre-v0.3 rows
        # are silently skipped — do NOT infer d_fumt8 retroactively.
        d_fumt8_counter = Counter(
            e.d_fumt8 for e in entries if e.d_fumt8 is not None
        )
        d_fumt8_breakdown = dict(d_fumt8_counter)

    return StatsResult(
        total=total,
        valid=valid,
        invalid=invalid,
        undecided=undecided,
        decision_rate=decision_rate,
        reason_breakdown=dict(reason_breakdown),
        d_fumt8_breakdown=d_fumt8_breakdown,
    )
