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


def stats(ledger_path: Optional[Path] = None) -> StatsResult:
    """Read the ledger and return aggregate stats.

    Empty ledger → total=0, decision_rate=0.0, empty reason_breakdown.
    Malformed rows are silently skipped by read_all_entries (spec §4:
    never abort on a bad row).

    Spec §3: this MUST return decision_rate. Everything else exists to
    contextualize it.
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

    return StatsResult(
        total=total,
        valid=valid,
        invalid=invalid,
        undecided=undecided,
        decision_rate=decision_rate,
        reason_breakdown=dict(reason_breakdown),
    )
