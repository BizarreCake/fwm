"""The Claude Code backend: the MCP server for the tools, and the reading of Claude Code's output.

Claude Code itself is replaced by a small script that prints a recorded-style stream.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from fwm import agent, bench, mcp_server, tools

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "fwm.duckdb"


@pytest.fixture(scope="module")
def con():
    if not DB_PATH.exists():
        pytest.skip("no ingested data; run `uv run fwm ingest`")
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        yield connection
    finally:
        connection.close()


def rpc(method, request_id=1, **params):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def test_mcp_server_lists_and_calls_the_same_tools(con):
    listed = mcp_server.handle(con, rpc("tools/list"))["result"]["tools"]
    assert [tool["name"] for tool in listed] == list(tools.REGISTRY)
    assert all(tool["inputSchema"]["type"] == "object" for tool in listed)

    reply = mcp_server.handle(con, rpc("tools/call", name="get_instrument", arguments={"instrument_id": "F3_2"}))["result"]
    assert reply["isError"] is False
    assert json.loads(reply["content"][0]["text"]) == tools.get_instrument(con, "F3_2")

    failed = mcp_server.handle(con, rpc("tools/call", name="get_instrument", arguments={"instrument_id": "NOPE"}))["result"]
    assert failed["isError"] is True and "list_instruments" in failed["content"][0]["text"]

    assert mcp_server.handle(con, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert mcp_server.handle(con, rpc("resources/list"))["error"]["code"] == -32601


def test_mcp_server_speaks_over_stdio():
    if not DB_PATH.exists():
        pytest.skip("no ingested data")
    requests = [rpc("initialize", 1, protocolVersion="2025-06-18"), {"jsonrpc": "2.0", "method": "notifications/initialized"},
                rpc("tools/call", 2, name="flag_data_gap", arguments={"category": "entity", "explanation": "x"})]
    done = subprocess.run([sys.executable, "-m", "fwm.mcp_server"], input="\n".join(map(json.dumps, requests)) + "\n",
                          capture_output=True, text=True, timeout=30, env={**os.environ, "FWM_DB": str(DB_PATH)})
    replies = [json.loads(line) for line in done.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2]
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    assert json.loads(replies[1]["result"]["content"][0]["text"])["recorded"] is True


def stream(con, answer="The Fed holds $4.08 trillion.", final=None):
    """Lines in the shape Claude Code prints with --output-format stream-json."""
    result = tools.get_instrument(con, "F3_2")
    gap = tools.flag_data_gap(con, "entity", "No single banks.")

    def delta(text):
        return {"type": "stream_event", "session_id": "s-1",
                "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}}

    def tool_result(tool_id, payload, is_error=False):
        return {"type": "user", "session_id": "s-1", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_id, "is_error": is_error, "content": [{"type": "text", "text": json.dumps(payload)}]}]}}

    return [json.dumps(line) for line in [
        {"type": "system", "subtype": "init", "session_id": "s-1", "model": "claude-opus-5-5", "tools": ["mcp__fwm__get_instrument"]},
        {"type": "stream_event", "session_id": "s-1", "event": {"type": "content_block_delta", "index": 0,
                                                                "delta": {"type": "input_json_delta", "partial_json": "{"}}},
        {"type": "assistant", "session_id": "s-1", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "mcp__fwm__get_instrument", "input": {"instrument_id": "F3_2"}},
            {"type": "tool_use", "id": "t2", "name": "mcp__fwm__flag_data_gap", "input": {"category": "entity", "explanation": "No single banks."}},
            {"type": "tool_use", "id": "t3", "name": "mcp__fwm__get_sector", "input": {"sector_id": "NOPE"}}]}},
        tool_result("t1", result), tool_result("t2", gap), tool_result("t3", {"error": "No sector page 'NOPE'."}, True),
        delta(answer[:9]), delta(answer[9:]),
        {"type": "assistant", "session_id": "s-1", "message": {"role": "assistant", "content": [{"type": "text", "text": answer}]}},
        final or {"type": "result", "subtype": "success", "is_error": False, "session_id": "s-1", "result": answer,
                  "usage": {"input_tokens": 4, "output_tokens": 146, "cache_read_input_tokens": 3470}, "modelUsage": {"some-model": {}}},
    ]] + ["", "not json"]


def test_claude_stream_becomes_the_same_events_as_the_api_backend(con):
    state: dict = {}
    events = list(agent.parse_claude_stream(iter(stream(con)), state))
    assert [event["type"] for event in events] == ["tool", "break", "gap", "break", "tool", "break", "text", "text", "done"]
    assert state == {"claude_session": "s-1"}

    lookup, gap, failed = events[0], events[2], events[4]
    assert lookup["name"] == "get_instrument" and lookup["ok"] and lookup["link"].startswith("#/us/instrument/F3_2")
    assert lookup["label"].startswith("Treasury securities") and lookup["result"]["instrument_id"] == "F3_2"
    assert gap == {"type": "gap", "category": "entity", "explanation": "No single banks."}
    assert failed["name"] == "get_sector" and not failed["ok"] and failed["link"] is None
    assert events[-1]["usage"]["output_tokens"] == 146 and events[-1]["model"] == "claude-opus-5-5" and events[-1]["model_name"] == "Claude Opus 5.5"

    # The benchmark reads these events exactly as it reads the API backend's.
    transcript = bench.Transcript.collect(events)
    assert transcript.answer == "The Fed holds $4.08 trillion." and len(transcript.calls) == 2 and len(transcript.gaps) == 1


def test_claude_errors_and_cut_off_streams_are_reported(con):
    failed = {"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "Usage limit reached"}
    assert list(agent.parse_claude_stream(iter(stream(con, final=failed)), {}))[-1] == {"type": "error", "message": "Usage limit reached"}
    cut = list(agent.parse_claude_stream(iter(stream(con)[:-3]), {}))
    assert cut[-1]["type"] == "error" and "without finishing" in cut[-1]["message"]


def test_command_gives_claude_code_only_our_tools_and_resumes_follow_ups(con):
    command = agent.claude_command(con, {}, "Who holds Treasuries?")
    option = lambda name: command[command.index(name) + 1]
    assert command[:3] == [agent.CLAUDE_BIN, "-p", "Who holds Treasuries?"]
    assert option("--tools") == "" and "--strict-mcp-config" in command and option("--setting-sources") == ""
    assert option("--allowedTools") == "mcp__fwm" and option("--system-prompt") == agent.system_prompt(con)
    server = json.loads(option("--mcp-config"))["mcpServers"]["fwm"]
    assert server["args"] == ["-m", "fwm.mcp_server"] and Path(server["env"]["FWM_DB"]) == DB_PATH
    # The model is always named, so it does not depend on Claude Code's own default.
    assert option("--model") == agent.MODEL == "claude-opus-5-5"
    assert "--resume" not in command and "--dangerously-skip-permissions" not in command

    follow_up = agent.claude_command(con, {"claude_session": "s-1"}, "And now?")
    assert follow_up[follow_up.index("--resume") + 1] == "s-1"


def test_model_names():
    assert agent.model_name("claude-opus-5-5") == "Claude Opus 5.5"
    assert agent.model_name("claude-opus-5") == "Claude Opus 5"
    assert agent.model_name("claude-haiku-4-5-20251001") == "Claude Haiku 4.5"
    assert agent.model_name("scripted") == "scripted"


def test_turn_runs_the_claude_binary_and_continues_the_session(con, tmp_path, monkeypatch):
    recorded = tmp_path / "stream.jsonl"
    recorded.write_text("\n".join(stream(con)) + "\n")
    arguments = tmp_path / "arguments.txt"
    fake = tmp_path / "claude"
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >> "{arguments}"\necho ---- >> "{arguments}"\ncat "{recorded}"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(agent, "CLAUDE_BIN", str(fake))
    monkeypatch.setattr(agent, "SESSION_DIR", tmp_path / "sessions")
    monkeypatch.setenv("FWM_AGENT_BACKEND", "claude-code")

    state: dict = {}
    first = bench.Transcript.collect(agent.answer(con, state, "How much does the Fed hold?"))
    assert first.error is None and first.answer == "The Fed holds $4.08 trillion." and state["claude_session"] == "s-1"
    list(agent.answer(con, state, "And a year ago?"))
    calls = arguments.read_text().split("----\n")
    assert "--resume" not in calls[0].splitlines() and "s-1" in calls[1].splitlines()


def test_backend_choice(monkeypatch, tmp_path):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "FWM_AGENT_BACKEND"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(agent, "CLAUDE_BIN", str(tmp_path / "missing"))
    assert agent.backend() is None and not agent.configured()
    monkeypatch.setattr(agent, "CLAUDE_BIN", sys.executable)
    assert agent.backend() == "claude-code"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert agent.backend() == "api"
    monkeypatch.setenv("FWM_AGENT_BACKEND", "claude-code")
    assert agent.backend() == "claude-code"
