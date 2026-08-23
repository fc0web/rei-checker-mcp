"""Refutation ledger — append-only JSONL. Spec §4.

Every verify() call, including VALID and INVALID, writes one line. UNDECIDED
rows carry the reason_code — those are the ones that decide what the next
sprint implements. Spec §4: "UNSUPPORTED_SYNTAX が集中した構文が、次の
スプリントの対象。推測で機能を足さない。"

Storage:
- Default path: $REI_CHECKER_LEDGER (env var) or ./ledger.jsonl
- Format: one JSON object per line, UTF-8, no BOM, LF line ending
- No PII, no user identifier, no session id (spec §4)
- Append-only: never rewritten, never rotated in-place. Rotation is the
  operator's job (mv + touch + restart if needed).

Concurrency:
- Uses `open(path, "a", encoding="utf-8")` — atomic per-line on POSIX,
  effectively serialized on Windows because MCP stdio server is
  single-process. If multi-writer becomes necessary, add fcntl / msvcrt
  locking in v0.2.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional, List

from rei_checker.schema import LedgerEntry, Verdict, ReasonCode


DEFAULT_LEDGER_FILENAME = "ledger.jsonl"
ENV_VAR = "REI_CHECKER_LEDGER"


def default_ledger_path() -> Path:
    """Resolve ledger path from env var or fall back to CWD.

    Priority:
    1. $REI_CHECKER_LEDGER (absolute or relative to CWD)
    2. ./ledger.jsonl in current working directory
    """
    env_val = os.environ.get(ENV_VAR)
    if env_val:
        return Path(env_val)
    return Path.cwd() / DEFAULT_LEDGER_FILENAME


def utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 with 'Z' suffix."""
    # Truncate to seconds — ledger row identity is coarse-grained.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_expression(expression: str) -> str:
    """Normalize expression before ledger append.

    v0 spike: strip surrounding whitespace, collapse internal runs of
    whitespace to a single space. Nothing else — semantic normalization
    (α-conversion, De Morgan, etc.) is intentionally OUT of scope: the
    ledger records what the user actually typed, minus formatting noise.
    """
    return " ".join(expression.split())


def append_entry(
    entry: LedgerEntry,
    ledger_path: Optional[Path] = None,
) -> None:
    """Append one row to the ledger. Creates the file if absent.

    Directory creation is intentional (mkdir -p semantics) so first-run
    users don't have to pre-create anything.
    """
    path = ledger_path or default_ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry.to_jsonl_dict(), ensure_ascii=False)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


def read_all_entries(
    ledger_path: Optional[Path] = None,
) -> List[LedgerEntry]:
    """Read all rows from the ledger. Returns [] if file absent.

    v0: full-file read for stats() computation. For large ledgers (v0.2+
    scale), consider streaming iteration or a cached counter.
    """
    path = ledger_path or default_ledger_path()
    if not path.exists():
        return []
    entries: List[LedgerEntry] = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                d = json.loads(raw)
                verdict = Verdict(d["verdict"])
                reason_code = (
                    ReasonCode(d["reason_code"])
                    if d.get("reason_code") is not None
                    else None
                )
                entries.append(
                    LedgerEntry(
                        ts_utc=d["ts_utc"],
                        expression_normalized=d["expression_normalized"],
                        verdict=verdict,
                        checker_version=d["checker_version"],
                        elapsed_ms=int(d["elapsed_ms"]),
                        reason_code=reason_code,
                        # v0.3: d_fumt8 field optional (backward compat
                        # with pre-v0.3 rows that lack it).
                        d_fumt8=d.get("d_fumt8"),
                    )
                )
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                # Skip malformed rows silently — the ledger is
                # append-only; a bad row is likely from an old schema
                # version or a partial write. Do NOT abort stats().
                # A v0.2 candidate: emit a health-check warning.
                continue
    return entries


def iter_entries(
    ledger_path: Optional[Path] = None,
) -> Iterator[LedgerEntry]:
    """Streaming version of read_all_entries().

    Preferred for large ledgers; used by stats() when we add lazy
    aggregation in v0.2.
    """
    yield from read_all_entries(ledger_path)
