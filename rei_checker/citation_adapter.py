"""citation_adapter — Citation stream (4-band internal) -> Body Verdict (3-value) 畳込み.

Spec §1.3 遵守: API 境界 で は Verdict 3 値 (VALID/INVALID/UNDECIDED) のみ、
citation stream 内部 4 帯 は reason_code 側 で 復元可能.

Spec §1.2 遵守: reason_code は UNDECIDED verdict のみ で 使用 (VerifyResult
invariant). Citation stream 4 band を Body に 畳込む と:
  - band 1 (verified)                 -> VALID     (reason_code=None)
  - band 2a (casefold NEITHER)        -> UNDECIDED + CITATION_CASE_DRIFT
  - band 2b (punct NEITHER)           -> UNDECIDED + CITATION_PUNCT_NORMALIZATION
  - band 2c (paraphrase NEITHER)      -> UNDECIDED + CITATION_PARAPHRASE
  - band 3 (not_found)                -> INVALID   (reason_code=None)
  - band 0 (unreachable, fetch fail)  -> UNDECIDED + CITATION_UNREACHABLE

STEP 1945 β-1 implementation. rei-aios sidecar
`data/tabs/rei-aios-ab/reflection-checker/` designed the 4-band verify tool
(citation_verify.py) whose 4-value output feeds this adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any

from rei_checker.schema import Verdict, ReasonCode


# Citation stream 内部 4 帯 constants (Body Verdict 3 値 とは 別 enum、 spec §1.3 遵守)
CITATION_VERIFIED = "verified"
CITATION_CASEFOLD_NEITHER = "casefold_neither"
CITATION_PUNCT_NEITHER = "punct_neither"
CITATION_PARAPHRASE_NEITHER = "paraphrase_neither"
CITATION_NOT_FOUND = "not_found"
CITATION_UNREACHABLE = "unreachable"


ALL_CITATION_VERDICTS = frozenset({
    CITATION_VERIFIED,
    CITATION_CASEFOLD_NEITHER,
    CITATION_PUNCT_NEITHER,
    CITATION_PARAPHRASE_NEITHER,
    CITATION_NOT_FOUND,
    CITATION_UNREACHABLE,
})


@dataclass(frozen=True)
class BodyVerdictWithReason:
    """Body 3-value verdict with optional reason_code (spec §1.2 invariant).

    Invariant: reason_code is not None iff verdict == UNDECIDED.
    """

    verdict: Verdict
    reason_code: Optional[ReasonCode] = None

    def __post_init__(self) -> None:
        if self.verdict == Verdict.UNDECIDED and self.reason_code is None:
            raise ValueError(
                "UNDECIDED verdict MUST include a reason_code (spec §1.2)"
            )
        if self.verdict != Verdict.UNDECIDED and self.reason_code is not None:
            raise ValueError(
                "reason_code is only permitted with UNDECIDED verdict (spec §1.2)"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "reason_code": self.reason_code.value if self.reason_code else None,
        }


# Mapping table: 6 citation values -> Body (Verdict, Optional[ReasonCode])
# Kept as a pure dict for auditability and to avoid conditional logic in
# to_body_verdict(). Every citation input has exactly one mapping.
_CITATION_TO_BODY: Dict[str, BodyVerdictWithReason] = {
    CITATION_VERIFIED:            BodyVerdictWithReason(Verdict.VALID,     None),
    CITATION_NOT_FOUND:           BodyVerdictWithReason(Verdict.INVALID,   None),
    CITATION_CASEFOLD_NEITHER:    BodyVerdictWithReason(Verdict.UNDECIDED, ReasonCode.CITATION_CASE_DRIFT),
    CITATION_PUNCT_NEITHER:       BodyVerdictWithReason(Verdict.UNDECIDED, ReasonCode.CITATION_PUNCT_NORMALIZATION),
    CITATION_PARAPHRASE_NEITHER:  BodyVerdictWithReason(Verdict.UNDECIDED, ReasonCode.CITATION_PARAPHRASE),
    CITATION_UNREACHABLE:         BodyVerdictWithReason(Verdict.UNDECIDED, ReasonCode.CITATION_UNREACHABLE),
}


def to_body_verdict(citation_verdict: str) -> BodyVerdictWithReason:
    """Citation stream 6 帯 verdict -> Body 3 値 + optional reason_code.

    Args:
        citation_verdict: One of CITATION_* constants defined in this module.

    Returns:
        BodyVerdictWithReason: verdict in {VALID/INVALID/UNDECIDED}. reason_code
        is set iff verdict == UNDECIDED (spec §1.2 invariant).

    Raises:
        ValueError: Unknown citation_verdict input.
    """
    if citation_verdict not in _CITATION_TO_BODY:
        raise ValueError(
            f"unknown citation_verdict: {citation_verdict!r}. "
            f"Expected one of: {sorted(ALL_CITATION_VERDICTS)}"
        )
    return _CITATION_TO_BODY[citation_verdict]


def reason_code_to_repair_action(reason_code: Optional[ReasonCode]) -> Optional[str]:
    """Map a citation-related reason_code to a repair_action hint.

    This layer is intentionally thin: it converts "why rejected" into
    "what to do next", matching peer rejection_coord.py repair_action set.
    Non-citation reason codes and None both return None.

    Central hypothesis (chat-Claude via 藤本さん relay): repair efficiency
    is bounded by the information density of a single rejection. Making
    the mapping explicit (rather than implicit in caller code) exposes
    that density directly.
    """
    if reason_code is None:
        return None
    mapping = {
        ReasonCode.CITATION_CASE_DRIFT: "REWRITE_QUOTE_TO_SOURCE_CASING",
        ReasonCode.CITATION_PUNCT_NORMALIZATION: "NORMALIZE_PUNCTUATION",
        ReasonCode.CITATION_PARAPHRASE: "QUOTE_VERBATIM_SPAN",
        ReasonCode.CITATION_UNREACHABLE: "REPLACE_SOURCE_URL",
    }
    return mapping.get(reason_code)
