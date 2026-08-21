"""MCP stdio server for rei-checker-mcp. Spec §5.

Two tools exposed (spec §2):
- verify(expression, context?, timeout_ms?) → VerifyResult
- stats() → StatsResult

Protocol:
- JSON-RPC 2.0 over stdio
- MCP methods handled: initialize, tools/list, tools/call
- One request per line, one response per line (line-delimited JSON)

Spec §5: MCP 仕様に対して 実装する — Claude Desktop 固有の 挙動に 依存しない。
The line-delimited JSON transport matches Anthropic's MCP stdio spec; a
lightweight implementation without the official Python SDK dep so the
whole tool stays stdlib-only.

Windows note: stdout is set to UTF-8, line-buffered.
"""

from __future__ import annotations

import io
import json
import sys
from typing import Any, Dict, Optional

from rei_checker import CHECKER_VERSION, __version__
from rei_checker.stats import stats as stats_fn
from rei_checker.verify import verify as verify_fn


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "rei-checker-mcp"


TOOL_DEFINITIONS = [
    {
        "name": "verify",
        "description": (
            "Verify one expression. Returns a three-valued verdict "
            "(VALID / INVALID / UNDECIDED) with a reason_code when "
            "UNDECIDED. No LLM anywhere on the judgment path (spec §1.1). "
            "The expression is normalized and recorded in the append-only "
            "refutation ledger (spec §4)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The expression to judge.",
                },
                "context": {
                    "type": "string",
                    "description": (
                        "Optional context (axioms, imports, prior "
                        "definitions). Backend-defined semantics."
                    ),
                },
                "timeout_ms": {
                    "type": "integer",
                    "description": (
                        "Hard timeout in milliseconds. Overrun → "
                        "UNDECIDED/TIMEOUT. Default: 5000."
                    ),
                    "default": 5000,
                    "minimum": 1,
                },
            },
            "required": ["expression"],
        },
    },
    {
        "name": "stats",
        "description": (
            "Return aggregate stats from the refutation ledger. Includes "
            "decision_rate = (VALID + INVALID) / total, the sole metric "
            "of project success (spec §3), plus reason_breakdown that "
            "drives what the next sprint implements (spec §4)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def _make_response(id_: Any, result: Optional[Dict[str, Any]] = None,
                   error: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    resp: Dict[str, Any] = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        resp["error"] = error
    else:
        resp["result"] = result if result is not None else {}
    return resp


def _handle_initialize(req_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return _make_response(
        req_id,
        result={
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": SERVER_NAME,
                "version": __version__,
                "checker_version": CHECKER_VERSION,
            },
        },
    )


def _handle_tools_list(req_id: Any) -> Dict[str, Any]:
    return _make_response(req_id, result={"tools": TOOL_DEFINITIONS})


def _handle_tools_call(req_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    tool_name = params.get("name")
    arguments = params.get("arguments") or {}

    if tool_name == "verify":
        expression = arguments.get("expression")
        if not isinstance(expression, str):
            return _make_response(
                req_id,
                error={
                    "code": -32602,
                    "message": "verify requires string 'expression' argument",
                },
            )
        context = arguments.get("context")
        timeout_ms = int(arguments.get("timeout_ms", 5000))
        result = verify_fn(
            expression,
            context=context if isinstance(context, str) else None,
            timeout_ms=timeout_ms,
        )
        return _make_response(
            req_id,
            result={
                "content": [
                    {"type": "text", "text": json.dumps(result.to_dict(), ensure_ascii=False)}
                ],
                "structuredContent": result.to_dict(),
                "isError": False,
            },
        )

    if tool_name == "stats":
        result = stats_fn()
        return _make_response(
            req_id,
            result={
                "content": [
                    {"type": "text", "text": json.dumps(result.to_dict(), ensure_ascii=False)}
                ],
                "structuredContent": result.to_dict(),
                "isError": False,
            },
        )

    return _make_response(
        req_id,
        error={
            "code": -32601,
            "message": f"tool not found: {tool_name!r}",
        },
    )


def handle_request(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Dispatch one MCP request to its handler.

    Returns the response dict, or None if the request is a notification
    (no id field — no response expected).
    """
    req_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    # Notifications (no id) get no reply.
    is_notification = "id" not in request

    if method == "initialize":
        return None if is_notification else _handle_initialize(req_id, params)
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return None if is_notification else _handle_tools_list(req_id)
    if method == "tools/call":
        return None if is_notification else _handle_tools_call(req_id, params)

    if is_notification:
        return None
    return _make_response(
        req_id,
        error={
            "code": -32601,
            "message": f"method not found: {method!r}",
        },
    )


def _configure_stdio_utf8() -> None:
    """Force UTF-8 on stdin/stdout/stderr (Windows fix)."""
    try:
        sys.stdin.reconfigure(encoding="utf-8", newline="\n")
        sys.stdout.reconfigure(encoding="utf-8", newline="\n", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", newline="\n")
    except (AttributeError, io.UnsupportedOperation):
        pass


def serve() -> None:
    """Run the MCP stdio loop. Blocks until stdin closes."""
    _configure_stdio_utf8()
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            request = json.loads(raw)
        except json.JSONDecodeError as e:
            err_resp = _make_response(
                None,
                error={"code": -32700, "message": f"parse error: {e}"},
            )
            print(json.dumps(err_resp, ensure_ascii=False), flush=True)
            continue

        response = handle_request(request)
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    serve()
