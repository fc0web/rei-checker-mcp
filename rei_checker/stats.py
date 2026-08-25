"""stats() — aggregate the refutation ledger. Spec §2 + §3.

`decision_rate = (VALID + INVALID) / total` is the sole metric of
project success (spec §3). Everything else in the return is
diagnostic — the reason_breakdown tells you what to build next
(spec §4), and by_decision (v0.4) surfaces per-verdict timing
without promoting it to a metric (CHECKER_SPEC v0.1 §7 論点).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from statistics import quantiles
from typing import Dict, List, Optional

from rei_checker.ledger import read_all_entries
from rei_checker.schema import DecisionTiming, StatsResult, Verdict


def _quantiles_p50_p90_p99(times_ms: List[int]) -> DecisionTiming:
    """Compute p50 / p90 / p99 from a list of elapsed_ms values.

    Handles small samples: 1 element → all quantiles collapse to that value.
    Uses `statistics.quantiles(..., method='inclusive')` so p99 of a small
    sample stays close to the observed max (more intuitive here than the
    default exclusive method which extrapolates past the range).
    """
    if len(times_ms) == 0:
        raise ValueError("_quantiles_p50_p90_p99 requires non-empty input")
    if len(times_ms) == 1:
        v = int(times_ms[0])
        return DecisionTiming(p50_ms=v, p90_ms=v, p99_ms=v)

    # n=100 → 99 cut points at 1%, 2%, ..., 99%. Indices are 0-based:
    # 50th percentile = qs[49], 90th = qs[89], 99th = qs[98].
    qs = quantiles(times_ms, n=100, method="inclusive")
    return DecisionTiming(
        p50_ms=int(qs[49]),
        p90_ms=int(qs[89]),
        p99_ms=int(qs[98]),
    )


def _compute_by_decision(entries) -> Dict[str, DecisionTiming]:
    """Group entries by verdict, compute per-verdict elapsed_ms quantiles.

    Empty verdict groups are omitted from the result (same pattern as
    reason_breakdown). Never enters decision_rate (I5).
    """
    by_verdict: Dict[str, List[int]] = defaultdict(list)
    for e in entries:
        by_verdict[e.verdict.value].append(int(e.elapsed_ms))

    result: Dict[str, DecisionTiming] = {}
    for verdict_name, times in by_verdict.items():
        if not times:
            continue
        result[verdict_name] = _quantiles_p50_p90_p99(times)
    return result


def stats(
    ledger_path: Optional[Path] = None,
    *,
    include_d_fumt8: bool = False,
) -> StatsResult:
    """Read the ledger and return aggregate stats.

    Empty ledger → total=0, decision_rate=0.0, empty reason_breakdown,
    empty by_decision. Malformed rows are silently skipped by
    read_all_entries (spec §4: never abort on a bad row).

    Spec §3: this MUST return decision_rate. Everything else exists to
    contextualize it.

    Args:
        ledger_path: optional override for tests.
        include_d_fumt8: v0.3 opt-in flag. When True, adds d_fumt8_breakdown
            to the result (ledger annotation aggregation). Default False
            preserves spec §1.3 (D-FUMT₈ not on default API surface).
            Rows without d_fumt8 field (pre-v0.3 ledger) are skipped in
            the breakdown, not counted as any D-FUMT₈ value.

    v0.4 addition: `by_decision` is always computed when at least one
    entry exists (no opt-in). Empty verdict groups are omitted so a
    ledger with only VALID rows yields `by_decision = {"VALID": ...}`.
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

    by_decision = _compute_by_decision(entries)

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
        by_decision=by_decision,
        d_fumt8_breakdown=d_fumt8_breakdown,
    )
