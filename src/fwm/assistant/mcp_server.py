"""The agent's tools as a Model Context Protocol server over stdio.

This is how a Claude Code session reaches the data: it starts this module as a
subprocess and calls the same functions in ``fwm.tools`` that the API backend
calls directly. The database is opened read-only.

    python -m fwm.assistant.mcp_server            # reads FWM_DB, or data/fwm.duckdb
"""

from __future__ import annotations

import json
import sys

import duckdb

from fwm.assistant import tools
from fwm.paths import DB_PATH

SERVER_NAME = "fwm"
DEFAULT_PROTOCOL = "2025-06-18"


def handle(con: duckdb.DuckDBPyConnection, request: dict) -> dict | None:
    """Answer one JSON-RPC message. Notifications get no reply."""
    method, request_id = request.get("method"), request.get("id")
    if request_id is None:
        return None

    def reply(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    if method == "initialize":
        return reply({
            "protocolVersion": request.get("params", {}).get("protocolVersion", DEFAULT_PROTOCOL),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
        })
    if method == "ping":
        return reply({})
    if method == "tools/list":
        return reply({"tools": [
            {"name": name, "description": description, "inputSchema": schema}
            for name, (_, description, schema) in tools.REGISTRY.items()
        ]})
    if method == "tools/call":
        params = request.get("params", {})
        try:
            result = tools.run(con, params.get("name"), params.get("arguments") or {})
            failed = False
        except tools.ToolError as error:
            result, failed = {"error": str(error)}, True
        return reply({"content": [{"type": "text", "text": json.dumps(result, separators=(",", ":"))}], "isError": failed})
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> None:
    db_path = str(DB_PATH)
    con = duckdb.connect(db_path, read_only=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            response = handle(con, request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
