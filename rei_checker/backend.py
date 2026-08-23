"""Checker backend abstraction.

Spec §5: 「Lean4 のみ」 for real judgments. But v0 spike keeps the interface
mockable so the schema (§2), ledger (§4), and MCP wrapper (§5) can be
validated without a Lean 4 install.

The Backend contract is intentionally narrow:
- Input:  expression string (already normalized upstream), optional context
- Output: (Verdict, Optional[ReasonCode], Optional[detail]) tuple
- Constraint (spec §1.1): the backend MUST NOT call any LLM. Failure to
  respect this makes the whole tool a lie.

MockBackend: hard-coded truth table for the tests + fallback UNDECIDED /
OUT_OF_SCOPE. Useful for CI where Lean 4 is not available.

LeanBackend (v0.3): persistent JSON REPL client for lean_checker_repl.exe
built under lean_backend/.lake/build/bin/. Stage 1 semantics (mirrors
MockBackend truth table) wired end-to-end. Stage 2 (real elaboration) is
future work. See lean_backend/README.md for the harness architecture.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple

from rei_checker.schema import Verdict, ReasonCode


BackendResult = Tuple[Verdict, Optional[ReasonCode], Optional[str]]


class CheckerBackend(ABC):
    """Contract for a decisive judgment engine.

    Spec §1.1: LLM MUST NOT appear anywhere on the path from input to
    Verdict. Implementations that violate this rule are not backends,
    they are guesses wearing a backend's clothes.
    """

    #: Short identifier for the backend, folded into checker_version.
    name: str = "abstract"

    @abstractmethod
    def check(
        self,
        expression: str,
        *,
        context: Optional[str] = None,
        timeout_ms: int = 5_000,
    ) -> BackendResult:
        """Judge one expression.

        MUST return within `timeout_ms` (or return UNDECIDED/TIMEOUT).
        MUST NOT raise on malformed input (return UNDECIDED/PARSE_FAILURE).
        MUST NOT call any LLM (spec §1.1).
        """
        raise NotImplementedError


class MockBackend(CheckerBackend):
    """Deterministic mock for interface validation and CI.

    Contains a small hard-coded truth table:
    - `1 + 1 = 2`               → VALID
    - `1 + 1 = 3`               → INVALID
    - `∀ n : ℕ, n + 0 = n`      → VALID
    - `∀ n : ℕ, n + 1 = n`      → INVALID
    - `True`                    → VALID
    - `False`                   → INVALID
    - empty / whitespace        → UNDECIDED/PARSE_FAILURE
    - `<timeout-test>`          → UNDECIDED/TIMEOUT (simulates hang)
    - `<syntax-test>`           → UNDECIDED/UNSUPPORTED_SYNTAX
    - `<axiom-test>`            → UNDECIDED/MISSING_AXIOM
    - `<depth-test>`            → UNDECIDED/DEPTH_LIMIT
    - anything else             → UNDECIDED/OUT_OF_SCOPE

    Spec §7 requires tests for every UNDECIDED reason_code, so each one
    has a deterministic trigger string.
    """

    name = "mock"

    _TRUE_TABLE = frozenset({
        "1 + 1 = 2",
        "∀ n : ℕ, n + 0 = n",
        "True",
    })

    _FALSE_TABLE = frozenset({
        "1 + 1 = 3",
        "∀ n : ℕ, n + 1 = n",
        "False",
    })

    _REASON_TRIGGERS = {
        "<timeout-test>": ReasonCode.TIMEOUT,
        "<syntax-test>": ReasonCode.UNSUPPORTED_SYNTAX,
        "<axiom-test>": ReasonCode.MISSING_AXIOM,
        "<depth-test>": ReasonCode.DEPTH_LIMIT,
    }

    def check(
        self,
        expression: str,
        *,
        context: Optional[str] = None,
        timeout_ms: int = 5_000,
    ) -> BackendResult:
        # Empty / whitespace → PARSE_FAILURE.
        if not expression or not expression.strip():
            return (
                Verdict.UNDECIDED,
                ReasonCode.PARSE_FAILURE,
                "expression is empty or whitespace-only",
            )

        expr = expression.strip()

        # Trigger strings for each reason_code (spec §7 test priority).
        if expr in self._REASON_TRIGGERS:
            code = self._REASON_TRIGGERS[expr]
            return (
                Verdict.UNDECIDED,
                code,
                f"mock trigger for {code.value}",
            )

        # Hard-coded truth table.
        if expr in self._TRUE_TABLE:
            return (Verdict.VALID, None, None)
        if expr in self._FALSE_TABLE:
            return (Verdict.INVALID, None, None)

        # Default: OUT_OF_SCOPE (spec §1.2 — return UNDECIDED, don't
        # guess, don't call an LLM).
        return (
            Verdict.UNDECIDED,
            ReasonCode.OUT_OF_SCOPE,
            "MockBackend has no rule for this expression",
        )


class LeanBackend(CheckerBackend):
    """Lean 4 persistent REPL backend (v0.3, Stage 1 semantics wired).

    Spawns lean_checker_repl.exe on first check() call and reuses it for
    subsequent calls. Warm invocations ~1.5ms per STEP 1367 measurement.
    Cold spawn ~150ms (Lean 4 runtime init).

    JSON protocol per line (see lean_backend/Main.lean):
        Request:  {"expression": "..."}
        Response: {"verdict": "VALID"|"INVALID"|"UNDECIDED",
                   "reason_code"?: "...", "detail"?: "...",
                   "checker_version": "lean-checker-repl/..."}

    Timeout handling: reader runs in background thread, main check() uses
    Queue.get(timeout=). On timeout, subprocess is killed and next call
    respawns — never leaves a zombie hanging Lean process.

    Failure modes (all → UNDECIDED with appropriate reason_code):
        binary missing       → OUT_OF_SCOPE + detail path
        process crash        → PARSE_FAILURE + detail
        response timeout     → TIMEOUT + detail (process killed)
        malformed JSON       → PARSE_FAILURE + detail
        unknown verdict str  → UNCLASSIFIED (V02_PROTOCOL §6 D11)

    v0.3 scope: Stage 1 semantics (matches MockBackend truth table).
    Stage 2 (real Lean.Elab dispatch) is future work — the wire is
    already in place, only lean_backend/Main.lean's judge() needs to
    upgrade its logic. This backend does not need to change for Stage 2.

    Spec §1.1 preserved: no LLM anywhere in the path.
    """

    name = "lean-repl"

    def __init__(self, binary_path: Optional[str] = None) -> None:
        self.binary_path = binary_path or self._default_binary_path()
        self._proc: Optional[subprocess.Popen] = None
        self._stdout_queue: Optional["queue.Queue[str]"] = None
        self._stdout_thread: Optional[threading.Thread] = None

    @staticmethod
    def _default_binary_path() -> str:
        """Auto-detect lean_checker_repl.exe from repo layout.

        Priority:
        1. $REI_CHECKER_LEAN_BINARY env var (absolute path override)
        2. <repo_root>/lean_backend/.lake/build/bin/lean_checker_repl.exe
        3. <repo_root>/lean_backend/.lake/build/bin/lean_checker_repl (Unix)
        """
        env = os.environ.get("REI_CHECKER_LEAN_BINARY")
        if env:
            return env
        repo_root = Path(__file__).resolve().parent.parent
        bin_dir = repo_root / "lean_backend" / ".lake" / "build" / "bin"
        exe = bin_dir / "lean_checker_repl.exe"
        if exe.exists():
            return str(exe)
        return str(bin_dir / "lean_checker_repl")

    def is_available(self) -> bool:
        """Check whether the binary exists on disk (utility for tests)."""
        return Path(self.binary_path).exists()

    def _ensure_process(self) -> bool:
        """Spawn REPL process if not running. Returns True on success."""
        if self._proc is not None and self._proc.poll() is None:
            return True
        # Cleanup any stale state
        self._cleanup()
        if not self.is_available():
            return False
        try:
            self._proc = subprocess.Popen(
                [self.binary_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,  # line-buffered
            )
        except (OSError, FileNotFoundError):
            return False
        # Start stdout reader thread
        self._stdout_queue = queue.Queue()
        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            daemon=True,
            name="lean-repl-stdout-reader",
        )
        self._stdout_thread.start()
        return True

    def _read_stdout(self) -> None:
        """Read stdout lines into queue. Runs in background daemon thread."""
        if self._proc is None or self._proc.stdout is None:
            return
        try:
            for line in self._proc.stdout:
                if self._stdout_queue is not None:
                    self._stdout_queue.put(line)
                else:
                    return
        except (OSError, ValueError):
            # Process died mid-read; thread exits, next check() respawns.
            return

    def _cleanup(self) -> None:
        """Kill subprocess and reset state. Safe to call multiple times."""
        if self._proc is not None:
            try:
                if self._proc.poll() is None:
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()
                        try:
                            self._proc.wait(timeout=1.0)
                        except subprocess.TimeoutExpired:
                            pass
            except (OSError, ValueError):
                pass
            self._proc = None
        # Thread is daemon; will exit when queue is dropped.
        self._stdout_queue = None
        self._stdout_thread = None

    def check(
        self,
        expression: str,
        *,
        context: Optional[str] = None,
        timeout_ms: int = 5_000,
    ) -> BackendResult:
        # Ensure process is running.
        if not self._ensure_process():
            return (
                Verdict.UNDECIDED,
                ReasonCode.OUT_OF_SCOPE,
                f"LeanBackend binary not available at {self.binary_path}",
            )
        assert self._proc is not None and self._proc.stdin is not None
        assert self._stdout_queue is not None

        # Send JSON request (one line).
        request = json.dumps({"expression": expression}, ensure_ascii=False)
        try:
            self._proc.stdin.write(request + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError, BrokenPipeError) as e:
            self._cleanup()
            return (
                Verdict.UNDECIDED,
                ReasonCode.PARSE_FAILURE,
                f"LeanBackend write failed: {type(e).__name__}: {e}",
            )

        # Read response with timeout. On timeout, kill process so the
        # next call respawns — never leave a hanging Lean instance.
        timeout_s = max(0.001, timeout_ms / 1000.0)
        try:
            line = self._stdout_queue.get(timeout=timeout_s)
        except queue.Empty:
            self._cleanup()
            return (
                Verdict.UNDECIDED,
                ReasonCode.TIMEOUT,
                f"LeanBackend REPL timeout ({timeout_ms} ms, process killed)",
            )

        # Parse JSON response.
        try:
            resp = json.loads(line.strip())
        except json.JSONDecodeError as e:
            return (
                Verdict.UNDECIDED,
                ReasonCode.PARSE_FAILURE,
                f"LeanBackend returned invalid JSON: {e}",
            )

        # Extract verdict + reason_code + detail.
        v_str = resp.get("verdict")
        if v_str == "VALID":
            return (Verdict.VALID, None, None)
        if v_str == "INVALID":
            return (Verdict.INVALID, None, None)
        if v_str == "UNDECIDED":
            rc_str = resp.get("reason_code")
            detail = resp.get("detail")
            if rc_str is None:
                # V02_PROTOCOL §6 D11: silent-misclassification prevention.
                return (
                    Verdict.UNDECIDED,
                    ReasonCode.UNCLASSIFIED,
                    detail or "LeanBackend UNDECIDED without reason_code",
                )
            try:
                rc = ReasonCode(rc_str)
            except ValueError:
                # Unknown reason_code from Lean side → UNCLASSIFIED.
                return (
                    Verdict.UNDECIDED,
                    ReasonCode.UNCLASSIFIED,
                    f"LeanBackend returned unknown reason_code {rc_str!r}: {detail}",
                )
            return (Verdict.UNDECIDED, rc, detail)

        # Unknown verdict string (protocol drift).
        return (
            Verdict.UNDECIDED,
            ReasonCode.UNCLASSIFIED,
            f"LeanBackend returned unknown verdict: {v_str!r}",
        )

    def close(self) -> None:
        """Explicit shutdown: send __QUIT__ sentinel then cleanup.

        Idempotent — safe to call multiple times.
        """
        if self._proc is not None and self._proc.poll() is None:
            try:
                if self._proc.stdin is not None:
                    self._proc.stdin.write("__QUIT__\n")
                    self._proc.stdin.flush()
                try:
                    self._proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
            except (OSError, ValueError, BrokenPipeError):
                pass
        self._cleanup()

    def __del__(self) -> None:
        # Best-effort cleanup on GC.
        try:
            self.close()
        except Exception:
            pass


def enforce_timeout(
    backend: CheckerBackend,
    expression: str,
    *,
    context: Optional[str] = None,
    timeout_ms: int = 5_000,
) -> BackendResult:
    """Wrap a backend call with hard timeout enforcement (spec §7).

    If the backend takes longer than `timeout_ms`, return
    UNDECIDED/TIMEOUT rather than letting the caller hang.

    This is a soft-guard: v0 measures elapsed time and reports TIMEOUT
    if the backend already handled it internally. A stricter thread /
    process kill layer is a v0.2 candidate.
    """
    start_ns = time.monotonic_ns()
    try:
        result = backend.check(
            expression, context=context, timeout_ms=timeout_ms
        )
    except Exception as e:
        # Spec §7: "不正な入力でクラッシュしない". Any backend exception
        # is folded into UNDECIDED/PARSE_FAILURE.
        return (
            Verdict.UNDECIDED,
            ReasonCode.PARSE_FAILURE,
            f"backend raised {type(e).__name__}: {e}",
        )
    elapsed_ms = (time.monotonic_ns() - start_ns) // 1_000_000
    # If the backend took longer than the budget, upgrade to TIMEOUT
    # (whichever reason the backend returned is superseded).
    if elapsed_ms > timeout_ms:
        return (
            Verdict.UNDECIDED,
            ReasonCode.TIMEOUT,
            f"exceeded timeout_ms={timeout_ms} (actual {elapsed_ms} ms)",
        )
    return result
