"""Subprocess helpers for the (future) real Lean 4 backend.

V02_PROTOCOL.md §2 (A2 spawn error handling) and §3 (A3 process tree kill).

Wired-in-code prerequisites for `LeanBackend.check()` real impl. Kept as a
separate module so unit tests can exercise the helpers with a benign
subprocess (e.g. `python -c "..."`) without needing a Lean install.

Design contract:
    - `_run_lean_safely` NEVER raises: all subprocess-related exceptions
      collapse to (-1, "", err_msg, timed_out) tuple. Callers (i.e.
      LeanBackend.check) map the tuple into a Verdict/ReasonCode. This is
      the "all 4 failure modes fold to UNDECIDED" pattern from V02_PROTOCOL.
    - `_kill_process_tree` is cross-platform (Windows taskkill, POSIX
      killpg). No-op on already-dead processes.

Not covered here (deferred, per V02_PROTOCOL "What this protocol does NOT
cover"): concurrency, batching, sandbox (§1 = environment-level).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import List, Tuple


RunResult = Tuple[int, str, str, bool]
"""(returncode, stdout, stderr, timed_out).

- returncode == -1 signals a wrapper-level failure (spawn error, kill).
  The Lean process itself may return any non-negative integer.
- timed_out is True only on subprocess.TimeoutExpired path; do not infer
  from returncode alone.
"""


def _kill_process_tree(pid: int) -> None:
    """Kill the process and all its descendants. No-op if already dead.

    Cross-platform: Windows uses `taskkill /F /T /PID`, POSIX uses
    `os.killpg(os.getpgid(pid), SIGKILL)`. See V02_PROTOCOL.md §3 for the
    orphan-lean-process rationale.

    POSIX prerequisite: the child must have been spawned with
    `start_new_session=True` so it has its own process group. Otherwise
    `killpg` on the child's pid would kill the parent Python interpreter.

    All expected exceptions (already-dead race, permission, missing
    taskkill.exe) are swallowed silently — the guarantee is "best-effort
    cleanup", not "no-op on all system states".
    """
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=5.0,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def _run_lean_safely(
    args: List[str],
    stdin_data: str,
    timeout_ms: int,
) -> RunResult:
    """Run a subprocess with hardened error handling and timeout.

    V02_PROTOCOL.md §2 (spawn error handling) + §3 (process tree kill on
    timeout). This function NEVER raises: every failure mode returns a
    RunResult tuple that the caller maps into a Verdict/ReasonCode.

    Failure-mode map (caller's responsibility to translate):
        FileNotFoundError → (-1, "", "binary not found: ...", False)
            → LeanBackend.check → UNDECIDED/OUT_OF_SCOPE
        Other OSError     → (-1, "", "exec failed: ...", False)
            → LeanBackend.check → UNDECIDED/PARSE_FAILURE
        TimeoutExpired    → (-1, drained_stdout, drained_stderr, True)
            → LeanBackend.check → UNDECIDED/TIMEOUT
        Non-zero rc, no diagnostics → (rc, "", "", False)
            → LeanBackend.check → UNDECIDED/UNCLASSIFIED (§6)

    POSIX spawn uses start_new_session=True (=setsid). This is REQUIRED
    for `_kill_process_tree` to work correctly. Windows equivalent is
    creating a new console group; taskkill /T handles the child tree
    without a special spawn flag, so we do not set CREATE_NEW_PROCESS_GROUP.
    """
    popen_kwargs: dict = dict(
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",  # tolerate non-UTF8 bytes from Lean crashes
    )
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(args, **popen_kwargs)
    except FileNotFoundError as e:
        return (-1, "", f"binary not found: {e}", False)
    except OSError as e:
        return (-1, "", f"exec failed: {type(e).__name__}: {e}", False)

    try:
        stdout, stderr = proc.communicate(
            input=stdin_data,
            timeout=timeout_ms / 1000.0,
        )
        return (proc.returncode, stdout, stderr, False)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc.pid)
        try:
            stdout, stderr = proc.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = "", ""
        except (OSError, ValueError):
            # ValueError: I/O on closed pipe after kill on some platforms.
            stdout, stderr = "", ""
        return (-1, stdout, stderr, True)
