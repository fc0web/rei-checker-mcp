"""CLI entry point for rei-checker-mcp.

Subcommands:
    verify <expression> [--timeout-ms N] [--context TEXT]
    stats
    mcp                     — run MCP stdio server (equivalent to rei_checker.mcp_server)
    version

Windows note: stdio is forced to UTF-8 so 8-value glyphs and Japanese
detail strings print without mojibake.
"""

from __future__ import annotations

import argparse
import io
import json
import signal
import sys
from typing import List, Optional

from rei_checker import CHECKER_VERSION, __version__
from rei_checker.mcp_server import serve
from rei_checker.stats import stats as stats_fn
from rei_checker.verify import verify as verify_fn


def _configure_stdio_utf8() -> None:
    try:
        sys.stdin.reconfigure(encoding="utf-8", newline="\n")
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    except (AttributeError, io.UnsupportedOperation):
        pass


def _install_sigpipe_guard() -> None:
    """SIGPIPE guard for POSIX. No-op on Windows."""
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass


def _cmd_verify(args: argparse.Namespace) -> int:
    result = verify_fn(
        args.expression,
        context=args.context,
        timeout_ms=args.timeout_ms,
    )
    payload = result.to_dict()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    # Exit code mapping: 0 = decisive (VALID/INVALID), 2 = UNDECIDED.
    # Rationale: shell scripts want a distinguishable status for
    # "the tool ran fine, but the answer is UNDECIDED".
    if result.verdict.value == "UNDECIDED":
        return 2
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    result = stats_fn()
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _cmd_mcp(args: argparse.Namespace) -> int:
    serve()
    return 0


def _cmd_version(args: argparse.Namespace) -> int:
    print(json.dumps({
        "package_version": __version__,
        "checker_version": CHECKER_VERSION,
    }, indent=2, ensure_ascii=False))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rei-checker",
        description=(
            "Formal-verification checker MCP server. "
            "Three-valued verdict, no LLM in judgment path. "
            "See CLAUDE.md for spec."
        ),
    )
    subs = parser.add_subparsers(dest="command", required=True)

    p_verify = subs.add_parser(
        "verify",
        help="Verify one expression and print the VerifyResult as JSON.",
    )
    p_verify.add_argument(
        "expression",
        type=str,
        help="The expression to judge.",
    )
    p_verify.add_argument(
        "--timeout-ms",
        type=int,
        default=5000,
        help="Hard timeout in milliseconds (default: 5000).",
    )
    p_verify.add_argument(
        "--context",
        type=str,
        default=None,
        help="Optional context passed to the backend.",
    )
    p_verify.set_defaults(func=_cmd_verify)

    p_stats = subs.add_parser(
        "stats",
        help="Print aggregate ledger stats (decision_rate + reason_breakdown).",
    )
    p_stats.set_defaults(func=_cmd_stats)

    p_mcp = subs.add_parser(
        "mcp",
        help="Run the MCP stdio server. Reads JSON-RPC lines from stdin.",
    )
    p_mcp.set_defaults(func=_cmd_mcp)

    p_version = subs.add_parser(
        "version",
        help="Print package + checker version.",
    )
    p_version.set_defaults(func=_cmd_version)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    _configure_stdio_utf8()
    _install_sigpipe_guard()
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
