"""Full test suite for rei-checker-mcp v0.1.0a1.

stdlib only (no pytest dependency). Run with:
    python -m tests.test_all
or
    python tests/test_all.py

Spec §7: 「UNDECIDED を返すべきケースのテストを優先」. Reason_code paths
are tested first, then VALID/INVALID happy paths, then schema/ledger/
stats/MCP integration.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List

# Allow running as `python tests/test_all.py` from repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rei_checker import CHECKER_VERSION, __version__
from rei_checker.schema import (
    Verdict,
    ReasonCode,
    VerifyResult,
    StatsResult,
    LedgerEntry,
)
from rei_checker.backend import (
    MockBackend,
    LeanBackend,
    enforce_timeout,
)
from rei_checker.ledger import (
    append_entry,
    read_all_entries,
    normalize_expression,
    utc_now_iso,
    default_ledger_path,
    DEFAULT_LEDGER_FILENAME,
    ENV_VAR,
)
from rei_checker.stats import stats
from rei_checker.verify import verify
from rei_checker.mcp_server import (
    handle_request,
    TOOL_DEFINITIONS,
    PROTOCOL_VERSION,
    SERVER_NAME,
)


# ==========================================================================
# §1. Schema — spec §1.2 three-value + reason_code invariants
# ==========================================================================

class TestSchema(unittest.TestCase):

    def test_verdict_has_exactly_three_values(self):
        # Spec §1.2: three-valued verdict, no fourth.
        self.assertEqual(len(list(Verdict)), 3)
        self.assertEqual(Verdict.VALID.value, "VALID")
        self.assertEqual(Verdict.INVALID.value, "INVALID")
        self.assertEqual(Verdict.UNDECIDED.value, "UNDECIDED")

    def test_reason_code_has_seven_values(self):
        # Spec §1.2 initial set + §6 D11 (V02_PROTOCOL.md, v0.2) widen with
        # UNCLASSIFIED. Enum widening is forward-compatible — existing
        # ledger rows with old 6-code set remain valid.
        expected = {
            "TIMEOUT", "PARSE_FAILURE", "UNSUPPORTED_SYNTAX",
            "MISSING_AXIOM", "DEPTH_LIMIT", "OUT_OF_SCOPE",
            "UNCLASSIFIED",
        }
        self.assertEqual(
            {r.value for r in ReasonCode},
            expected,
        )

    def test_verify_result_undecided_requires_reason_code(self):
        # Spec §1.2 invariant.
        with self.assertRaises(ValueError):
            VerifyResult(
                verdict=Verdict.UNDECIDED,
                elapsed_ms=1,
                checker_version="test",
                reason_code=None,
            )

    def test_verify_result_valid_rejects_reason_code(self):
        # Symmetric invariant.
        with self.assertRaises(ValueError):
            VerifyResult(
                verdict=Verdict.VALID,
                elapsed_ms=1,
                checker_version="test",
                reason_code=ReasonCode.OUT_OF_SCOPE,
            )

    def test_verify_result_to_dict_valid(self):
        r = VerifyResult(
            verdict=Verdict.VALID,
            elapsed_ms=42,
            checker_version="test-v",
        )
        d = r.to_dict()
        self.assertEqual(d["verdict"], "VALID")
        self.assertEqual(d["elapsed_ms"], 42)
        self.assertEqual(d["checker_version"], "test-v")
        self.assertNotIn("reason_code", d)  # elided for VALID
        self.assertNotIn("detail", d)  # elided when None

    def test_verify_result_to_dict_undecided(self):
        r = VerifyResult(
            verdict=Verdict.UNDECIDED,
            elapsed_ms=100,
            checker_version="test-v",
            reason_code=ReasonCode.MISSING_AXIOM,
            detail="need Choice",
        )
        d = r.to_dict()
        self.assertEqual(d["verdict"], "UNDECIDED")
        self.assertEqual(d["reason_code"], "MISSING_AXIOM")
        self.assertEqual(d["detail"], "need Choice")

    def test_stats_result_decision_rate_invariant(self):
        # Spec §3: decision_rate = (VALID + INVALID) / total
        r = StatsResult(
            total=10, valid=3, invalid=2, undecided=5,
            decision_rate=0.5,
        )
        self.assertEqual(r.total, 10)
        self.assertAlmostEqual(r.decision_rate, 0.5)

    def test_stats_result_empty_ledger(self):
        r = StatsResult(
            total=0, valid=0, invalid=0, undecided=0,
            decision_rate=0.0,
        )
        self.assertEqual(r.total, 0)
        self.assertEqual(r.decision_rate, 0.0)

    def test_stats_result_rejects_mismatched_totals(self):
        with self.assertRaises(ValueError):
            StatsResult(
                total=5, valid=3, invalid=1, undecided=0,  # 4 != 5
                decision_rate=0.8,
            )

    def test_stats_result_rejects_wrong_decision_rate(self):
        with self.assertRaises(ValueError):
            StatsResult(
                total=10, valid=5, invalid=0, undecided=5,
                decision_rate=0.9,  # actual is 0.5
            )

    def test_elapsed_ms_rejects_negative(self):
        with self.assertRaises(ValueError):
            VerifyResult(
                verdict=Verdict.VALID,
                elapsed_ms=-1,
                checker_version="test",
            )


# ==========================================================================
# §2. Backend — spec §7 prioritizes UNDECIDED test cases
# ==========================================================================

class TestMockBackendUndecidedPaths(unittest.TestCase):
    """Every reason_code has a dedicated trigger. Spec §7."""

    def setUp(self):
        self.backend = MockBackend()

    def test_empty_expression_returns_parse_failure(self):
        v, code, _ = self.backend.check("")
        self.assertEqual(v, Verdict.UNDECIDED)
        self.assertEqual(code, ReasonCode.PARSE_FAILURE)

    def test_whitespace_only_returns_parse_failure(self):
        v, code, _ = self.backend.check("   \n\t")
        self.assertEqual(v, Verdict.UNDECIDED)
        self.assertEqual(code, ReasonCode.PARSE_FAILURE)

    def test_timeout_trigger_returns_timeout(self):
        v, code, _ = self.backend.check("<timeout-test>")
        self.assertEqual(v, Verdict.UNDECIDED)
        self.assertEqual(code, ReasonCode.TIMEOUT)

    def test_syntax_trigger_returns_unsupported_syntax(self):
        v, code, _ = self.backend.check("<syntax-test>")
        self.assertEqual(v, Verdict.UNDECIDED)
        self.assertEqual(code, ReasonCode.UNSUPPORTED_SYNTAX)

    def test_axiom_trigger_returns_missing_axiom(self):
        v, code, _ = self.backend.check("<axiom-test>")
        self.assertEqual(v, Verdict.UNDECIDED)
        self.assertEqual(code, ReasonCode.MISSING_AXIOM)

    def test_depth_trigger_returns_depth_limit(self):
        v, code, _ = self.backend.check("<depth-test>")
        self.assertEqual(v, Verdict.UNDECIDED)
        self.assertEqual(code, ReasonCode.DEPTH_LIMIT)

    def test_unknown_expression_returns_out_of_scope(self):
        v, code, detail = self.backend.check("some random thing")
        self.assertEqual(v, Verdict.UNDECIDED)
        self.assertEqual(code, ReasonCode.OUT_OF_SCOPE)
        self.assertIn("MockBackend", detail)


class TestMockBackendHappyPaths(unittest.TestCase):
    """Happy paths — after all UNDECIDED cases are covered."""

    def setUp(self):
        self.backend = MockBackend()

    def test_one_plus_one_equals_two_returns_valid(self):
        v, code, _ = self.backend.check("1 + 1 = 2")
        self.assertEqual(v, Verdict.VALID)
        self.assertIsNone(code)

    def test_one_plus_one_equals_three_returns_invalid(self):
        v, code, _ = self.backend.check("1 + 1 = 3")
        self.assertEqual(v, Verdict.INVALID)
        self.assertIsNone(code)

    def test_nat_zero_identity_returns_valid(self):
        v, code, _ = self.backend.check("∀ n : ℕ, n + 0 = n")
        self.assertEqual(v, Verdict.VALID)

    def test_true_returns_valid(self):
        v, _, _ = self.backend.check("True")
        self.assertEqual(v, Verdict.VALID)

    def test_false_returns_invalid(self):
        v, _, _ = self.backend.check("False")
        self.assertEqual(v, Verdict.INVALID)


class TestLeanBackendStub(unittest.TestCase):
    """Spec §5: Lean 4 is the sole intended real backend. v0 stub only."""

    def test_stub_always_returns_undecided_out_of_scope(self):
        backend = LeanBackend()
        v, code, detail = backend.check("1 + 1 = 2")
        self.assertEqual(v, Verdict.UNDECIDED)
        self.assertEqual(code, ReasonCode.OUT_OF_SCOPE)
        self.assertIn("stub", detail)


class TestEnforceTimeout(unittest.TestCase):
    """Spec §7: 「タイムアウトは必ず効く。ハングしたら UNDECIDED/TIMEOUT」"""

    def test_normal_call_passes_through(self):
        backend = MockBackend()
        v, code, _ = enforce_timeout(backend, "1 + 1 = 2", timeout_ms=5000)
        self.assertEqual(v, Verdict.VALID)

    def test_backend_exception_becomes_parse_failure(self):
        # A backend that raises should not crash the caller.
        class BadBackend(MockBackend):
            def check(self, expression, *, context=None, timeout_ms=5000):
                raise RuntimeError("oops")
        v, code, detail = enforce_timeout(BadBackend(), "anything", timeout_ms=5000)
        self.assertEqual(v, Verdict.UNDECIDED)
        self.assertEqual(code, ReasonCode.PARSE_FAILURE)
        self.assertIn("RuntimeError", detail)


# ==========================================================================
# §3. Ledger — spec §4 append-only, no PII
# ==========================================================================

class TestLedger(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ledger_path = Path(self.tmpdir) / "test_ledger.jsonl"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_normalize_expression_collapses_whitespace(self):
        self.assertEqual(normalize_expression("  1 + 1  =   2 "), "1 + 1 = 2")
        self.assertEqual(normalize_expression("a\n\tb"), "a b")

    def test_utc_now_iso_format(self):
        ts = utc_now_iso()
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_append_and_read_roundtrip_valid(self):
        entry = LedgerEntry(
            ts_utc="2026-08-22T10:00:00Z",
            expression_normalized="1 + 1 = 2",
            verdict=Verdict.VALID,
            checker_version="test-v",
            elapsed_ms=5,
        )
        append_entry(entry, ledger_path=self.ledger_path)
        entries = read_all_entries(self.ledger_path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].verdict, Verdict.VALID)
        self.assertEqual(entries[0].expression_normalized, "1 + 1 = 2")
        self.assertIsNone(entries[0].reason_code)

    def test_append_undecided_preserves_reason_code(self):
        entry = LedgerEntry(
            ts_utc="2026-08-22T10:00:00Z",
            expression_normalized="unknown",
            verdict=Verdict.UNDECIDED,
            checker_version="test-v",
            elapsed_ms=3,
            reason_code=ReasonCode.OUT_OF_SCOPE,
        )
        append_entry(entry, ledger_path=self.ledger_path)
        entries = read_all_entries(self.ledger_path)
        self.assertEqual(entries[0].reason_code, ReasonCode.OUT_OF_SCOPE)

    def test_read_all_entries_empty_file_returns_empty(self):
        # File doesn't exist yet.
        self.assertEqual(read_all_entries(self.ledger_path), [])

    def test_read_all_entries_skips_malformed_rows(self):
        # Spec §4: never abort on a bad row.
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        good = {
            "ts_utc": "2026-08-22T10:00:00Z",
            "expression_normalized": "x",
            "verdict": "VALID",
            "checker_version": "test",
            "elapsed_ms": 1,
        }
        with open(self.ledger_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(good) + "\n")
            f.write("not json\n")  # malformed
            f.write("{}\n")  # missing required fields
            f.write(json.dumps(good) + "\n")
        entries = read_all_entries(self.ledger_path)
        self.assertEqual(len(entries), 2)  # skipped 2 bad rows

    def test_default_ledger_path_respects_env_var(self):
        try:
            os.environ[ENV_VAR] = str(self.ledger_path)
            self.assertEqual(default_ledger_path(), self.ledger_path)
        finally:
            del os.environ[ENV_VAR]

    def test_default_ledger_path_falls_back_to_cwd(self):
        if ENV_VAR in os.environ:
            del os.environ[ENV_VAR]
        expected = Path.cwd() / DEFAULT_LEDGER_FILENAME
        self.assertEqual(default_ledger_path(), expected)

    def test_append_creates_parent_directory(self):
        deep_path = Path(self.tmpdir) / "a" / "b" / "c" / "ledger.jsonl"
        entry = LedgerEntry(
            ts_utc="2026-08-22T10:00:00Z",
            expression_normalized="x",
            verdict=Verdict.VALID,
            checker_version="test",
            elapsed_ms=1,
        )
        append_entry(entry, ledger_path=deep_path)
        self.assertTrue(deep_path.exists())


# ==========================================================================
# §4. Stats — spec §3 decision_rate + §4 reason_breakdown
# ==========================================================================

class TestStats(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ledger_path = Path(self.tmpdir) / "test_ledger.jsonl"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_entries(self, entries: List[LedgerEntry]):
        for e in entries:
            append_entry(e, ledger_path=self.ledger_path)

    def test_empty_ledger_returns_zero_stats(self):
        r = stats(self.ledger_path)
        self.assertEqual(r.total, 0)
        self.assertEqual(r.decision_rate, 0.0)
        self.assertEqual(r.reason_breakdown, {})

    def test_decision_rate_computed_correctly(self):
        # 2 VALID + 1 INVALID + 2 UNDECIDED = 5, decision_rate = 3/5 = 0.6
        self._write_entries([
            LedgerEntry("2026-08-22T10:00:00Z", "a", Verdict.VALID, "v", 1),
            LedgerEntry("2026-08-22T10:00:01Z", "b", Verdict.VALID, "v", 1),
            LedgerEntry("2026-08-22T10:00:02Z", "c", Verdict.INVALID, "v", 1),
            LedgerEntry("2026-08-22T10:00:03Z", "d", Verdict.UNDECIDED, "v", 1,
                        reason_code=ReasonCode.OUT_OF_SCOPE),
            LedgerEntry("2026-08-22T10:00:04Z", "e", Verdict.UNDECIDED, "v", 1,
                        reason_code=ReasonCode.TIMEOUT),
        ])
        r = stats(self.ledger_path)
        self.assertEqual(r.total, 5)
        self.assertEqual(r.valid, 2)
        self.assertEqual(r.invalid, 1)
        self.assertEqual(r.undecided, 2)
        self.assertAlmostEqual(r.decision_rate, 0.6)
        self.assertEqual(r.reason_breakdown["OUT_OF_SCOPE"], 1)
        self.assertEqual(r.reason_breakdown["TIMEOUT"], 1)

    def test_all_undecided_gives_zero_decision_rate(self):
        self._write_entries([
            LedgerEntry("2026-08-22T10:00:00Z", "a", Verdict.UNDECIDED, "v", 1,
                        reason_code=ReasonCode.OUT_OF_SCOPE),
            LedgerEntry("2026-08-22T10:00:01Z", "b", Verdict.UNDECIDED, "v", 1,
                        reason_code=ReasonCode.OUT_OF_SCOPE),
        ])
        r = stats(self.ledger_path)
        self.assertEqual(r.decision_rate, 0.0)
        self.assertEqual(r.reason_breakdown["OUT_OF_SCOPE"], 2)


# ==========================================================================
# §5. verify() end-to-end
# ==========================================================================

class TestVerifyE2E(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ledger_path = Path(self.tmpdir) / "e2e_ledger.jsonl"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_verify_valid_expression_writes_ledger(self):
        result = verify("1 + 1 = 2", ledger_path=self.ledger_path)
        self.assertEqual(result.verdict, Verdict.VALID)
        self.assertIn(CHECKER_VERSION, result.checker_version)
        entries = read_all_entries(self.ledger_path)
        self.assertEqual(len(entries), 1)

    def test_verify_undecided_expression_writes_reason_code(self):
        result = verify("some unknown thing", ledger_path=self.ledger_path)
        self.assertEqual(result.verdict, Verdict.UNDECIDED)
        self.assertEqual(result.reason_code, ReasonCode.OUT_OF_SCOPE)
        entries = read_all_entries(self.ledger_path)
        self.assertEqual(entries[0].reason_code, ReasonCode.OUT_OF_SCOPE)

    def test_verify_normalizes_expression_before_ledger(self):
        verify("  1  +  1  =  2  ", ledger_path=self.ledger_path)
        entries = read_all_entries(self.ledger_path)
        self.assertEqual(entries[0].expression_normalized, "1 + 1 = 2")

    def test_verify_record_false_skips_ledger(self):
        result = verify("1 + 1 = 2", ledger_path=self.ledger_path, record=False)
        self.assertEqual(result.verdict, Verdict.VALID)
        # No ledger file created.
        self.assertFalse(self.ledger_path.exists())

    def test_verify_empty_string_returns_parse_failure(self):
        result = verify("", ledger_path=self.ledger_path)
        self.assertEqual(result.verdict, Verdict.UNDECIDED)
        self.assertEqual(result.reason_code, ReasonCode.PARSE_FAILURE)


# ==========================================================================
# §6. MCP protocol handlers — spec §5
# ==========================================================================

class TestMCPHandlers(unittest.TestCase):

    def test_initialize_returns_protocol_version(self):
        req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        resp = handle_request(req)
        self.assertIsNotNone(resp)
        self.assertEqual(resp["result"]["protocolVersion"], PROTOCOL_VERSION)
        self.assertEqual(resp["result"]["serverInfo"]["name"], SERVER_NAME)
        self.assertEqual(resp["result"]["serverInfo"]["version"], __version__)

    def test_tools_list_returns_two_tools(self):
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        resp = handle_request(req)
        tools = resp["result"]["tools"]
        self.assertEqual(len(tools), 2)  # spec §2: exactly two tools
        names = {t["name"] for t in tools}
        self.assertEqual(names, {"verify", "stats"})

    def test_tools_call_verify_valid(self):
        req = {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "verify", "arguments": {"expression": "1 + 1 = 2"}},
        }
        resp = handle_request(req)
        self.assertFalse(resp["result"]["isError"])
        payload = resp["result"]["structuredContent"]
        self.assertEqual(payload["verdict"], "VALID")

    def test_tools_call_verify_undecided(self):
        req = {
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "verify", "arguments": {"expression": "<timeout-test>"}},
        }
        resp = handle_request(req)
        payload = resp["result"]["structuredContent"]
        self.assertEqual(payload["verdict"], "UNDECIDED")
        self.assertEqual(payload["reason_code"], "TIMEOUT")

    def test_tools_call_stats_smoke(self):
        req = {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
               "params": {"name": "stats"}}
        resp = handle_request(req)
        self.assertFalse(resp["result"]["isError"])
        # Structured content includes decision_rate.
        payload = resp["result"]["structuredContent"]
        self.assertIn("decision_rate", payload)
        self.assertIn("reason_breakdown", payload)

    def test_tools_call_missing_expression_returns_error(self):
        req = {
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "verify", "arguments": {}},
        }
        resp = handle_request(req)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32602)

    def test_tools_call_unknown_tool_returns_error(self):
        req = {
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "does_not_exist", "arguments": {}},
        }
        resp = handle_request(req)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32601)

    def test_notification_no_response(self):
        # No "id" field = notification, no reply expected.
        req = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        resp = handle_request(req)
        self.assertIsNone(resp)


# ==========================================================================
# §7. Tool definition sanity — no accidental Phase 2 leakage
# ==========================================================================

class TestScopeDiscipline(unittest.TestCase):
    """Spec §2: v0 has EXACTLY two tools. No third-tool creep."""

    def test_exactly_two_tools_defined(self):
        self.assertEqual(len(TOOL_DEFINITIONS), 2)

    def test_no_phase2_tools_present(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        # Phase 2 tool names — must NOT appear in v0.
        phase2 = {
            "calibrate", "regression", "transfer",
            "locate_first_error", "boundary_report", "escalate",
        }
        overlap = names & phase2
        self.assertEqual(overlap, set(), f"Phase 2 leakage detected: {overlap}")

    def test_verify_tool_schema_has_expression_required(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "verify")
        self.assertIn("expression", tool["inputSchema"]["required"])

    def test_stats_tool_schema_takes_no_arguments(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "stats")
        # Empty required list or absent — either is fine.
        required = tool["inputSchema"].get("required", [])
        self.assertEqual(required, [])


# -------------------------------------------------------------------------
# V0.2 protocol tests (V02_PROTOCOL.md §2, §3, §4, §6).
# §1 is environment-level (sandbox), not code-testable from inside the
# sandbox. §5 REPL server has its own harness in lean_backend/ (STEP 1367).
# -------------------------------------------------------------------------


class TestAxiomParser(unittest.TestCase):
    """V02_PROTOCOL.md §4 (B4): parse #print axioms from Lean --json stdout."""

    def _parse(self, stdout):
        from rei_checker.axiom_parser import parse_axioms_from_lean_json_output
        return parse_axioms_from_lean_json_output(stdout)

    def test_empty_stdout_returns_no_diagnostic(self):
        r = self._parse("")
        self.assertEqual(r.axioms, [])
        self.assertFalse(r.has_sorry_ax)
        self.assertFalse(r.saw_axiom_diagnostic)

    def test_extracts_axioms_from_depends_on_marker(self):
        # Canonical post-v4.5 shape.
        stdout = (
            '{"severity":"information","pos":{"line":1,"column":0},'
            '"data":"\'foo\' depends on axioms: [propext, Classical.choice]"}'
        )
        r = self._parse(stdout)
        self.assertEqual(r.axioms, ["propext", "Classical.choice"])
        self.assertFalse(r.has_sorry_ax)
        self.assertTrue(r.saw_axiom_diagnostic)

    def test_extracts_axioms_from_uses_axioms_marker(self):
        # Pre-v4.5 shape variant.
        stdout = (
            '{"severity":"information",'
            '"data":"\'bar\' uses axioms: [Quot.sound]"}'
        )
        r = self._parse(stdout)
        self.assertEqual(r.axioms, ["Quot.sound"])
        self.assertTrue(r.saw_axiom_diagnostic)

    def test_detects_sorry_ax(self):
        stdout = (
            '{"severity":"information",'
            '"data":"\'baz\' depends on axioms: [sorryAx, propext]"}'
        )
        r = self._parse(stdout)
        self.assertTrue(r.has_sorry_ax)
        self.assertIn("sorryAx", r.axioms)
        self.assertIn("propext", r.axioms)

    def test_message_field_fallback_when_no_data(self):
        # Older Lean JSON put text under `message` not `data`.
        stdout = (
            '{"severity":"info",'
            '"message":"\'q\' depends on axioms: [ax1]"}'
        )
        r = self._parse(stdout)
        self.assertEqual(r.axioms, ["ax1"])
        self.assertTrue(r.saw_axiom_diagnostic)

    def test_structured_message_dict_flattened_via_json_dump(self):
        # Lean sometimes wraps message as MessageData tree (dict).
        stdout = (
            '{"severity":"info",'
            '"data":{"tag":"appendField","content":"depends on axioms: [x]"}}'
        )
        r = self._parse(stdout)
        # After json.dumps flattening the "depends on axioms: [x]" substring
        # is still findable.
        self.assertTrue(r.saw_axiom_diagnostic)
        self.assertIn("x", r.axioms)

    def test_malformed_json_line_skipped_silently(self):
        stdout = (
            "Compiling ...\n"  # non-JSON line, must skip
            "{not json}\n"     # malformed JSON, must skip
            '{"severity":"info","data":"\'y\' depends on axioms: [ax1]"}'
        )
        r = self._parse(stdout)
        self.assertEqual(r.axioms, ["ax1"])

    def test_mismatched_bracket_skipped_no_partial_return(self):
        # Missing closing bracket → occurrence skipped entirely, no partial.
        stdout = (
            '{"severity":"info","data":"depends on axioms: [ax1, ax2"}'
        )
        r = self._parse(stdout)
        self.assertTrue(r.saw_axiom_diagnostic)
        self.assertEqual(r.axioms, [])  # nothing extracted

    def test_multiple_diagnostics_accumulate(self):
        stdout = (
            '{"severity":"info","data":"\'a\' depends on axioms: [x, y]"}\n'
            '{"severity":"info","data":"\'b\' depends on axioms: [z]"}'
        )
        r = self._parse(stdout)
        self.assertEqual(r.axioms, ["x", "y", "z"])

    def test_all_axioms_authorized_vacuous_true_but_flagged(self):
        # V02_PROTOCOL.md §4 threat: empty list returns True vacuously.
        # This is set-theoretically correct — the fix is that callers must
        # check saw_axiom_diagnostic BEFORE trusting the vacuous True.
        from rei_checker.axiom_parser import all_axioms_authorized
        self.assertTrue(all_axioms_authorized([], ["propext"]))
        self.assertTrue(all_axioms_authorized(["propext"], ["propext"]))
        self.assertFalse(
            all_axioms_authorized(["Classical.choice"], ["propext"])
        )


class TestSubprocessUtil(unittest.TestCase):
    """V02_PROTOCOL.md §2 (A2 spawn error) + §3 (A3 process tree kill)."""

    def test_binary_not_found_folds_to_error_tuple(self):
        from rei_checker.subprocess_util import _run_lean_safely
        rc, out, err, timed_out = _run_lean_safely(
            args=["nonexistent_binary_xyz_9999"],
            stdin_data="",
            timeout_ms=1000,
        )
        self.assertEqual(rc, -1)
        self.assertEqual(out, "")
        self.assertIn("binary not found", err)
        self.assertFalse(timed_out)

    def test_normal_exit_zero_stdout_captured(self):
        import sys as _sys
        from rei_checker.subprocess_util import _run_lean_safely
        rc, out, err, timed_out = _run_lean_safely(
            args=[_sys.executable, "-c", "print('hello')"],
            stdin_data="",
            timeout_ms=5000,
        )
        self.assertEqual(rc, 0)
        self.assertIn("hello", out)
        self.assertFalse(timed_out)

    def test_timeout_kills_and_returns_timed_out_true(self):
        import sys as _sys
        from rei_checker.subprocess_util import _run_lean_safely
        # Sleep for 30 seconds; timeout at 500ms.
        rc, out, err, timed_out = _run_lean_safely(
            args=[_sys.executable, "-c", "import time; time.sleep(30)"],
            stdin_data="",
            timeout_ms=500,
        )
        self.assertEqual(rc, -1)
        self.assertTrue(timed_out)

    def test_stdin_delivered_to_child(self):
        import sys as _sys
        from rei_checker.subprocess_util import _run_lean_safely
        rc, out, err, timed_out = _run_lean_safely(
            args=[_sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
            stdin_data="ping",
            timeout_ms=5000,
        )
        self.assertEqual(rc, 0)
        self.assertIn("PING", out)

    def test_kill_process_tree_noop_on_dead_pid(self):
        # PID 0 / 1 / 2 are system pids; passing something guaranteed-dead is
        # tricky cross-platform. Use a real short-lived process and then
        # try to kill after it's already exited — must not raise.
        import sys as _sys
        import subprocess as _sp
        from rei_checker.subprocess_util import _kill_process_tree
        p = _sp.Popen(
            [_sys.executable, "-c", "pass"],
            stdout=_sp.PIPE,
            stderr=_sp.PIPE,
        )
        p.wait(timeout=5)
        # p.pid is now dead. Must not raise.
        _kill_process_tree(p.pid)  # succeeds silently


class TestReasonCodeUnclassified(unittest.TestCase):
    """V02_PROTOCOL.md §6 (D11): UNCLASSIFIED enum value + invariant."""

    def test_unclassified_is_a_valid_reason_code(self):
        self.assertEqual(ReasonCode.UNCLASSIFIED.value, "UNCLASSIFIED")

    def test_unclassified_paired_with_undecided_verdict_ok(self):
        r = VerifyResult(
            verdict=Verdict.UNDECIDED,
            elapsed_ms=1,
            checker_version="test",
            reason_code=ReasonCode.UNCLASSIFIED,
            detail="some raw diagnostic",
        )
        self.assertEqual(r.reason_code, ReasonCode.UNCLASSIFIED)
        self.assertEqual(r.detail, "some raw diagnostic")

    def test_unclassified_forbidden_with_valid_verdict(self):
        with self.assertRaises(ValueError):
            VerifyResult(
                verdict=Verdict.VALID,
                elapsed_ms=1,
                checker_version="test",
                reason_code=ReasonCode.UNCLASSIFIED,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
