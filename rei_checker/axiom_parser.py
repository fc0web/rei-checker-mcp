"""Axiom parser for Lean 4 --json output.

V02_PROTOCOL.md §4 (B4). Pure function, no subprocess. The real LeanBackend
wires this into the check() path after subprocess wrapper (§2/§3).

Threat rationale (from V02_PROTOCOL.md):
    Lean 4 `--json` flag wraps all diagnostics — including `#print axioms X`
    output — inside JSON `{severity, pos, endPos, message, ...}` objects.
    Naive raw-stdout grep for `depends on axioms:` misses them. Axiom check
    silently returns empty list, `all_axioms_authorized([])` returns True
    (vacuously), axiom check effectively disabled.

Design:
    - Line-oriented parse (one JSON object per line, Lean --json convention).
    - Skip non-JSON lines silently (Lean sometimes emits build-status lines).
    - Match BOTH marker variants Lean has used across versions:
        "depends on axioms:" (post-v4.5)
        "uses axioms:"       (pre-v4.5)
    - Extract axiom names from the [a, b, c] bracket content.
    - Detect `sorryAx` presence separately (single flag, not a list item to
      hide inside a passing check).

Test discipline (spec §7): unit tests use captured Lean --json output as
fixtures (see tests/test_all.py). Do NOT change parser behavior without a
new fixture that reproduces the change — Lean JSON schema shifts between
versions and each shift needs its own captured evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable, List


_AXIOM_MARKERS = ("depends on axioms:", "uses axioms:")
_SORRY_AXIOM_NAME = "sorryAx"


@dataclass(frozen=True)
class AxiomScanResult:
    """Result of parsing a #print axioms diagnostic from Lean --json output.

    - `axioms`: list of axiom names in the order they appeared.
    - `has_sorry_ax`: True iff `sorryAx` appears in the axiom list. Distinct
      flag so callers cannot accidentally treat a sorry-tainted result as
      passing an unrelated allow-list check.
    - `saw_axiom_diagnostic`: True iff the parser matched at least one of
      the axiom markers. Distinguishes "checked and no axioms" (empty list,
      saw_axiom_diagnostic=True) from "did not check" (empty list,
      saw_axiom_diagnostic=False) — the latter must not be treated as
      passing vacuously.
    """

    axioms: List[str] = field(default_factory=list)
    has_sorry_ax: bool = False
    saw_axiom_diagnostic: bool = False


def parse_axioms_from_lean_json_output(stdout: str) -> AxiomScanResult:
    """Parse `#print axioms X` diagnostics from Lean 4 --json stdout.

    Returns AxiomScanResult with all axioms, sorryAx flag, and diagnostic-
    seen flag. Returns empty result (all defaults) if no axiom diagnostic
    is present — callers must check `saw_axiom_diagnostic` before treating
    an empty `axioms` list as "no unauthorized axioms".

    Robustness contract (V02_PROTOCOL.md §4):
        - Empty input → empty result, no exception.
        - Malformed JSON lines → skipped silently, do not abort parse.
        - Missing 'data' / 'message' field → skip that line.
        - Nested-dict message payload → serialize back to JSON for scanning
          (Lean occasionally wraps message in a structured MessageData tree).
        - Mismatched brackets (`depends on axioms: [foo, bar` with no
          closing `]`) → skip that occurrence, do not partial-return.
    """
    axioms: List[str] = []
    has_sorry_ax = False
    saw_axiom_diagnostic = False

    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        message_text = msg.get("data") or msg.get("message") or ""
        if isinstance(message_text, dict):
            # Lean sometimes emits structured MessageData; flatten by dumping.
            message_text = json.dumps(message_text)
        if not isinstance(message_text, str):
            continue

        for marker in _AXIOM_MARKERS:
            idx = message_text.find(marker)
            if idx < 0:
                continue
            saw_axiom_diagnostic = True
            # Find bracketed axiom list AFTER the marker.
            bracket_start = message_text.find("[", idx)
            bracket_end = message_text.find("]", bracket_start)
            if bracket_start < 0 or bracket_end <= bracket_start:
                continue
            raw = message_text[bracket_start + 1 : bracket_end]
            for name in raw.split(","):
                name = name.strip()
                if not name:
                    continue
                axioms.append(name)
                if name == _SORRY_AXIOM_NAME:
                    has_sorry_ax = True

    return AxiomScanResult(
        axioms=axioms,
        has_sorry_ax=has_sorry_ax,
        saw_axiom_diagnostic=saw_axiom_diagnostic,
    )


def all_axioms_authorized(
    axioms: Iterable[str],
    allow_list: Iterable[str],
) -> bool:
    """True iff every item in `axioms` is in `allow_list`.

    IMPORTANT: `axioms=[]` returns True vacuously — this is set-theoretic
    correctness, NOT a green light to treat "no axioms observed" as
    "verified". Callers must check `AxiomScanResult.saw_axiom_diagnostic`
    BEFORE calling this. V02_PROTOCOL.md §4 threat model.

    Set-based check; order and duplicates do not matter.
    """
    allow_set = set(allow_list)
    return all(a in allow_set for a in axioms)
