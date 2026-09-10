"""Tests for citation_adapter (v0.5.0a1 β-1).

Verifies:
1. Every citation input maps to a valid Body verdict.
2. Spec §1.2 invariant: reason_code iff UNDECIDED.
3. Spec §1.3 invariant: verdict always in {VALID, INVALID, UNDECIDED} (no 4th value).
4. repair_action mapping matches peer rejection_coord.py 4-action design.
5. Unknown citation input raises ValueError with expected sorted set.
"""

from __future__ import annotations

import pytest

from rei_checker import (
    to_body_verdict,
    reason_code_to_repair_action,
    BodyVerdictWithReason,
    Verdict,
    ReasonCode,
    CITATION_VERIFIED,
    CITATION_CASEFOLD_NEITHER,
    CITATION_PUNCT_NEITHER,
    CITATION_PARAPHRASE_NEITHER,
    CITATION_NOT_FOUND,
    CITATION_UNREACHABLE,
    ALL_CITATION_VERDICTS,
)


# (citation_input, expected_verdict, expected_reason_code, expected_repair_action)
CASES = [
    (CITATION_VERIFIED,            Verdict.VALID,     None,                                   None),
    (CITATION_NOT_FOUND,           Verdict.INVALID,   None,                                   None),
    (CITATION_CASEFOLD_NEITHER,    Verdict.UNDECIDED, ReasonCode.CITATION_CASE_DRIFT,          "REWRITE_QUOTE_TO_SOURCE_CASING"),
    (CITATION_PUNCT_NEITHER,       Verdict.UNDECIDED, ReasonCode.CITATION_PUNCT_NORMALIZATION, "NORMALIZE_PUNCTUATION"),
    (CITATION_PARAPHRASE_NEITHER,  Verdict.UNDECIDED, ReasonCode.CITATION_PARAPHRASE,          "QUOTE_VERBATIM_SPAN"),
    (CITATION_UNREACHABLE,         Verdict.UNDECIDED, ReasonCode.CITATION_UNREACHABLE,         "REPLACE_SOURCE_URL"),
]


@pytest.mark.parametrize("citation,expected_verdict,expected_reason,expected_repair", CASES)
def test_citation_to_body_verdict(citation, expected_verdict, expected_reason, expected_repair):
    body = to_body_verdict(citation)
    assert body.verdict == expected_verdict, f"{citation} verdict mismatch"
    assert body.reason_code == expected_reason, f"{citation} reason_code mismatch"
    assert reason_code_to_repair_action(body.reason_code) == expected_repair, \
        f"{citation} repair_action mismatch"


def test_all_citation_verdicts_frozen_set_matches_cases():
    """Every constant in ALL_CITATION_VERDICTS is covered by CASES exactly once."""
    covered = {c[0] for c in CASES}
    assert covered == set(ALL_CITATION_VERDICTS), \
        f"Coverage mismatch: covered={sorted(covered)} vs constants={sorted(ALL_CITATION_VERDICTS)}"


def test_spec_1_2_invariant_reason_code_iff_undecided():
    """Spec §1.2 invariant: reason_code is not None iff verdict == UNDECIDED."""
    for citation, expected_verdict, expected_reason, _ in CASES:
        body = to_body_verdict(citation)
        if body.verdict == Verdict.UNDECIDED:
            assert body.reason_code is not None, \
                f"{citation}: UNDECIDED must have reason_code"
        else:
            assert body.reason_code is None, \
                f"{citation}: {body.verdict} must not have reason_code"


def test_spec_1_3_invariant_verdict_three_values_only():
    """Spec §1.3 invariant: verdict is always in {VALID, INVALID, UNDECIDED}."""
    allowed = {Verdict.VALID, Verdict.INVALID, Verdict.UNDECIDED}
    for citation, _, _, _ in CASES:
        body = to_body_verdict(citation)
        assert body.verdict in allowed, \
            f"{citation}: verdict {body.verdict} outside {allowed}"


def test_unknown_citation_raises_with_sorted_expected():
    with pytest.raises(ValueError, match="unknown citation_verdict"):
        to_body_verdict("no_such_band")


def test_none_reason_code_returns_none_repair_action():
    assert reason_code_to_repair_action(None) is None


def test_non_citation_reason_code_returns_none_repair_action():
    """Existing (non-citation) reason codes have no citation repair mapping."""
    assert reason_code_to_repair_action(ReasonCode.TIMEOUT) is None
    assert reason_code_to_repair_action(ReasonCode.MISSING_AXIOM) is None
    assert reason_code_to_repair_action(ReasonCode.OUT_OF_SCOPE) is None


def test_body_verdict_with_reason_invariant_valid_plus_reason_raises():
    """BodyVerdictWithReason enforces spec §1.2 invariant at construction."""
    with pytest.raises(ValueError, match="only permitted with UNDECIDED"):
        BodyVerdictWithReason(Verdict.VALID, ReasonCode.CITATION_CASE_DRIFT)


def test_body_verdict_with_reason_invariant_undecided_without_reason_raises():
    with pytest.raises(ValueError, match="MUST include a reason_code"):
        BodyVerdictWithReason(Verdict.UNDECIDED, None)


def test_body_verdict_to_dict():
    body = to_body_verdict(CITATION_CASEFOLD_NEITHER)
    d = body.to_dict()
    assert d == {"verdict": "UNDECIDED", "reason_code": "CITATION_CASE_DRIFT"}

    body_valid = to_body_verdict(CITATION_VERIFIED)
    d_valid = body_valid.to_dict()
    assert d_valid == {"verdict": "VALID", "reason_code": None}
