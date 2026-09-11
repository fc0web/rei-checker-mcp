"""Tests for v0.6.0a1 CoherenceMark emission (STEP 1989 defer arc (γ''')).

Standalone runnable:
    python tests/test_coherence_emission.py

Covers:
- CoherenceMark shape (5 optional fields, is_empty, camelCase emission)
- LedgerEntry integration (append + read back with coherence)
- Backward compat: pre-v0.6 rows without coherence remain readable
- Forward compat: unknown coherence keys silently ignored
- Interop with rei-aios consumer format (camelCase key contract)
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rei_checker import CoherenceMark, LedgerEntry, Verdict, __version__
from rei_checker.ledger import append_entry, read_all_entries, utc_now_iso


class TestCoherenceMarkShape(unittest.TestCase):
    """CoherenceMark dataclass behavior."""

    def test_all_fields_default_none(self):
        m = CoherenceMark()
        self.assertIsNone(m.ensemble_match)
        self.assertIsNone(m.recursive_match)
        self.assertIsNone(m.latest_match)
        self.assertIsNone(m.live_promoted)
        self.assertIsNone(m.reason_code)
        self.assertTrue(m.is_empty())

    def test_is_empty_transitions(self):
        self.assertTrue(CoherenceMark().is_empty())
        self.assertFalse(CoherenceMark(live_promoted=True).is_empty())
        self.assertFalse(CoherenceMark(reason_code="test").is_empty())
        self.assertFalse(CoherenceMark(ensemble_match=False).is_empty())

    def test_to_jsonl_dict_camelcase(self):
        m = CoherenceMark(
            ensemble_match=True,
            recursive_match=False,
            latest_match=True,
            live_promoted=True,
            reason_code="freshness_gate_fail",
        )
        d = m.to_jsonl_dict()
        # Must be camelCase to match rei-aios consumer interface
        self.assertIn("ensembleMatch", d)
        self.assertIn("recursiveMatch", d)
        self.assertIn("latestMatch", d)
        self.assertIn("livePromoted", d)
        self.assertIn("reasonCode", d)
        # Snake_case Python keys MUST NOT leak into JSONL
        self.assertNotIn("ensemble_match", d)
        self.assertNotIn("live_promoted", d)
        self.assertNotIn("reason_code", d)
        # Values preserved
        self.assertTrue(d["ensembleMatch"])
        self.assertFalse(d["recursiveMatch"])
        self.assertEqual(d["reasonCode"], "freshness_gate_fail")

    def test_to_jsonl_dict_omits_none(self):
        m = CoherenceMark(live_promoted=True)
        d = m.to_jsonl_dict()
        self.assertEqual(d, {"livePromoted": True})
        self.assertNotIn("ensembleMatch", d)

    def test_from_jsonl_dict_camelcase(self):
        raw = {
            "ensembleMatch": True,
            "recursiveMatch": False,
            "latestMatch": True,
            "livePromoted": False,
            "reasonCode": "gate_x_fail",
        }
        m = CoherenceMark.from_jsonl_dict(raw)
        self.assertTrue(m.ensemble_match)
        self.assertFalse(m.recursive_match)
        self.assertTrue(m.latest_match)
        self.assertFalse(m.live_promoted)
        self.assertEqual(m.reason_code, "gate_x_fail")

    def test_from_jsonl_dict_forward_compat_unknown_keys(self):
        raw = {"livePromoted": True, "futureUnknownField": 42}
        m = CoherenceMark.from_jsonl_dict(raw)
        self.assertTrue(m.live_promoted)
        # Unknown key silently ignored

    def test_from_jsonl_dict_wrong_types_produce_none(self):
        # Non-bool values for bool fields → None (v0.6 policy)
        raw = {"ensembleMatch": "yes", "reasonCode": 42}
        m = CoherenceMark.from_jsonl_dict(raw)
        self.assertIsNone(m.ensemble_match)
        self.assertIsNone(m.reason_code)


class TestLedgerEntryWithCoherence(unittest.TestCase):
    """LedgerEntry ↔ ledger.py round trip with coherence."""

    def _entry(self, coherence=None):
        return LedgerEntry(
            ts_utc=utc_now_iso(),
            expression_normalized="test expr",
            verdict=Verdict.VALID,
            checker_version=f"rei-checker-mcp/{__version__}+test",
            elapsed_ms=1,
            coherence=coherence,
        )

    def test_to_jsonl_dict_omits_coherence_when_none(self):
        d = self._entry(coherence=None).to_jsonl_dict()
        self.assertNotIn("coherence", d)

    def test_to_jsonl_dict_omits_coherence_when_empty(self):
        d = self._entry(coherence=CoherenceMark()).to_jsonl_dict()
        self.assertNotIn("coherence", d)  # is_empty() short-circuits

    def test_to_jsonl_dict_includes_coherence_when_set(self):
        d = self._entry(
            coherence=CoherenceMark(live_promoted=True, reason_code="ok")
        ).to_jsonl_dict()
        self.assertIn("coherence", d)
        self.assertEqual(d["coherence"], {"livePromoted": True, "reasonCode": "ok"})

    def test_round_trip_append_and_read(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = Path(f.name)
        try:
            entry = self._entry(
                coherence=CoherenceMark(ensemble_match=True, live_promoted=False)
            )
            append_entry(entry, path)
            rows = read_all_entries(path)
            self.assertEqual(len(rows), 1)
            self.assertIsNotNone(rows[0].coherence)
            self.assertTrue(rows[0].coherence.ensemble_match)
            self.assertFalse(rows[0].coherence.live_promoted)
            self.assertIsNone(rows[0].coherence.reason_code)
        finally:
            path.unlink(missing_ok=True)

    def test_backward_compat_pre_v06_row_reads_ok(self):
        """Pre-v0.6 rows have no 'coherence' key — must still parse."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            # Simulate a v0.5 ledger row (no coherence field)
            legacy_row = {
                "ts_utc": "2026-09-11T00:00:00Z",
                "expression_normalized": "old expr",
                "verdict": "VALID",
                "checker_version": "rei-checker-mcp/0.5.0a1+test",
                "elapsed_ms": 2,
            }
            f.write(json.dumps(legacy_row) + "\n")
            path = Path(f.name)
        try:
            rows = read_all_entries(path)
            self.assertEqual(len(rows), 1)
            self.assertIsNone(rows[0].coherence)  # No coherence, no error
        finally:
            path.unlink(missing_ok=True)

    def test_mixed_ledger_v05_and_v06_rows(self):
        """A ledger may contain both pre-v0.6 and v0.6+ rows."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            # v0.5 row (no coherence)
            f.write(
                json.dumps(
                    {
                        "ts_utc": "2026-09-11T00:00:00Z",
                        "expression_normalized": "legacy",
                        "verdict": "VALID",
                        "checker_version": "rei-checker-mcp/0.5.0a1",
                        "elapsed_ms": 1,
                    }
                )
                + "\n"
            )
            # v0.6 row (with coherence)
            f.write(
                json.dumps(
                    {
                        "ts_utc": "2026-09-12T09:00:00Z",
                        "expression_normalized": "new",
                        "verdict": "VALID",
                        "checker_version": "rei-checker-mcp/0.6.0a1",
                        "elapsed_ms": 2,
                        "coherence": {"livePromoted": True, "reasonCode": "ok"},
                    }
                )
                + "\n"
            )
            path = Path(f.name)
        try:
            rows = read_all_entries(path)
            self.assertEqual(len(rows), 2)
            self.assertIsNone(rows[0].coherence)
            self.assertIsNotNone(rows[1].coherence)
            self.assertTrue(rows[1].coherence.live_promoted)
            self.assertEqual(rows[1].coherence.reason_code, "ok")
        finally:
            path.unlink(missing_ok=True)


class TestInteropWithReiAios(unittest.TestCase):
    """The camelCase key contract MUST match rei-aios src/mcp/d8-ledger-query.ts.

    Interface (STEP 1973):
      interface CoherenceMark {
        ensembleMatch?: boolean;
        recursiveMatch?: boolean;
        latestMatch?: boolean;
        livePromoted?: boolean;
        reasonCode?: string;
      }
    """

    def test_all_expected_keys_present_when_set(self):
        m = CoherenceMark(
            ensemble_match=True,
            recursive_match=True,
            latest_match=True,
            live_promoted=True,
            reason_code="x",
        )
        d = m.to_jsonl_dict()
        expected_keys = {
            "ensembleMatch",
            "recursiveMatch",
            "latestMatch",
            "livePromoted",
            "reasonCode",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_serialization_matches_ts_shape(self):
        """A rei-aios reader casts JSON.parse(line).coherence directly to
        CoherenceMark. So the JSON MUST look like:
            {"ensembleMatch": true, "livePromoted": true, "reasonCode": "..."}
        """
        entry = LedgerEntry(
            ts_utc="2026-09-12T10:00:00Z",
            expression_normalized="test",
            verdict=Verdict.VALID,
            checker_version=f"rei-checker-mcp/{__version__}",
            elapsed_ms=1,
            coherence=CoherenceMark(live_promoted=True, reason_code="promoted"),
        )
        d = entry.to_jsonl_dict()
        # Simulate rei-aios JSON.parse then .coherence access
        raw_json = json.dumps(d)
        parsed = json.loads(raw_json)
        self.assertIn("coherence", parsed)
        self.assertEqual(parsed["coherence"]["livePromoted"], True)
        self.assertEqual(parsed["coherence"]["reasonCode"], "promoted")


if __name__ == "__main__":
    unittest.main(verbosity=2)
