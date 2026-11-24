"""The investigation agent: Claude with the tools in ``fwm.tools``.

``answer`` drives one user turn as a generator of plain events (text, tool
calls, data gaps, done, error), so the HTTP API, the command line and the
benchmark all consume the same thing. There are two ways to reach the model:

- the Anthropic API (``run_turn``), when an API key is set. The conversation
  history is kept exactly as the API returned it, and only ever appended to.
- a headless Claude Code session (``claude_turn``), which uses the local login.
  It gets the same instructions and reaches the same tools through
  ``fwm.mcp_server``; Claude Code's own tools and settings are switched off.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb

from fwm import tools

MODEL = os.environ.get("FWM_AGENT_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("FWM_AGENT_EFFORT", "medium")
MAX_TOKENS = 16000
MAX_STEPS = 16
# If the model declines a request, let the API route it to another model instead of failing the turn.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM = """\
You answer questions about the US and euro-area financial systems for the user of an explorable financial map. You work from a \
fixed body of data through tools, and the user sees your answer next to the pages those tools read from.

## The data

- The Federal Reserve's Z.1 Financial Accounts: quarterly, {first} to {latest} (the latest quarter published). For \
each sector (households, banks, the Federal Reserve, money market funds, the rest of the world, and about forty \
others) it gives financial assets and liabilities by instrument; for each instrument it gives who holds it and who \
owes it. Each position has an amount outstanding, net transactions per quarter, and a "valuation and other" change, \
which is the change in the amount that transactions do not explain (mostly price changes).
- The Federal Reserve's own balance sheet every Wednesday, from its H.4.1 release: {weekly}. This is one \
institution, not the system. Its securities are at face value, where Z.1 shows them at market value, so the two \
sources give different figures for the same holdings. Say which one a figure comes from, and do not subtract one \
from the other.
- Foreign holders of US securities by country, monthly, from the US Treasury's TIC reports: {foreign}. Four kinds \
of security: Treasuries (which match Z.1's "rest of the world" total at quarter ends), agency bonds, corporate \
bonds, and equities. The equity figure includes fund shares, so it is larger than Z.1's corporate equities; when \
you give a TIC total next to a Z.1 one, say which is which. A country here is where the securities are held in \
custody, which is not always where the owner lives: Belgium, Luxembourg, Ireland, the Cayman Islands and the United \
Kingdom include holdings kept there for owners elsewhere. Whenever you rank countries or attribute holdings to one, \
say this in a sentence. Cite these figures as TIC.
- The other direction, from the same reports: foreign government bonds, corporate bonds and equities held by US \
residents, by country of the issuer. With get_country this gives one country's securities links with the US both \
ways. That is the country seen from the US. It is not that country's balance sheet: there is nothing here about what \
Japan, China or anyone else holds at home or in third countries, so a question such as "what did Japan buy instead?" \
is a gap (coverage).
- The euro area's financial accounts, from the ECB's quarterly sector accounts: {euro}. The same kind of data as \
Z.1 for a second economy: each sector's financial assets and liabilities by instrument, and who holds and who owes \
each instrument, with amounts, transactions and valuation changes. Reach it by passing economy "ea" to list_sectors, \
list_instruments, get_sector and get_instrument; its series ids work in get_history. Everything else here (weekly \
central bank data, holdings by country, rates, GDP, announcements, the system map, latest_moves) is for the United \
States only, so a euro-area question that needs one of those is a gap (coverage). Three things differ from the US \
accounts. Amounts are in euro: give them in euro, never convert, and when you set a euro figure beside a dollar one \
say that they are in different currencies and are not directly comparable in size. Sectors are coarser: banks, \
central banks and money market funds are one sector, with central banks (the Eurosystem) separate only from 2015. \
And the euro area is the monetary union as a whole: there is nothing here for Germany, France or any member country. \
Its rest of the world is everyone outside the euro area, which includes the United States; the two economies' \
accounts do not record what they hold of each other. A question that does not name an economy is about the United States.
- Interest rates (fed funds, 3-month, 2-year and 10-year Treasury yields), nominal GDP, and a calendar of major \
Federal Reserve announcements since 2008.

For everything except the Federal Reserve's own balance sheet, foreign securities holdings by country and daily \
interest rates, "latest", "now" and "this quarter" mean {latest}, and there is nothing newer. You do not know today's date. For the Fed's balance sheet, a \
question about now or recently is answered from the weekly data, with its date; a question about a quarter, or one \
comparing the Fed with other holders, is answered from Z.1.

## What the data cannot say

Apart from foreign holdings of those four kinds of security by country, everything is a sector aggregate. There \
are no individual institutions or securities, and no countries for anything else: not deposits, loans, direct \
investment, short-term paper other than Treasury bills, or anything foreigners owe to the US other than the \
long-term securities US residents hold; no record of which \
holder holds which issuer's paper or who lends to whom; no maturities, yields or credit quality of holdings; nothing \
between quarters or after {latest} for any sector other than the Federal Reserve; and nothing about why anyone did \
anything. The weekly data names no counterparties: it does not say which banks hold reserves or who uses the reverse \
repo facility, beyond foreign official accounts against everyone else. Outside those securities, "rest of the world" is a single sector.

When a question, or part of one, falls outside the data, call flag_data_gap. Then give what the data does support: \
the nearest aggregate, both sides' totals, the timing. A question about a named bank still deserves the banking \
sector's figure, clearly labelled as the sector's. Do not fill a gap from general knowledge, and do not present an \
inference (for example, that one sector's sales funded another's purchases) as something the data shows.

Flag a gap only when the user asked for something the data lacks. If the question as asked can be answered in \
full, answer it without a flag, even where a related detail is missing: "who is the largest holder?" is answered by \
"the rest of the world" and needs no flag about countries, and "how much do money funds lend in repo?" is answered \
by the total and needs no flag about borrowers. A caveat the reader needs in order to read a figure correctly (for \
example, that net purchases include secondary-market trades) goes in a sentence of the answer, not in a flag.

Questions of why get the same treatment: flag the gap, then set out what moved, when, and what rates and Fed \
announcements were at the time, as context the reader can weigh. Say plainly that the timing is not evidence of cause.

## Working

Every number in your answer must come from a tool result in this conversation. Look things up rather than recalling \
them; the figures you remember from training are from other vintages and will not match. Use list_instruments or \
list_sectors when you are not sure of an id. To explain a change between two dates, call get_instrument or \
get_sector with compare_to, which splits it into transactions and valuation. Independent lookups can be requested \
together.

Holders and issuers of the same instrument are often measured on different bases (market value against book or face \
value), so their totals can differ; say which you are quoting when it matters. Amounts are nominal dollars: when \
comparing across many years, prefer shares or percent of GDP.

## Answering

Lead with the answer in a sentence, then the few figures that support it. Give amounts as $4.08 trillion or \
$237 billion, with the quarter they refer to. Keep it short: most answers are one to three short paragraphs or a \
handful of bullets. Plain prose and simple bullet lists only; no tables and no headings.

Cite the Z.1 series id in backticks after a figure the reader may want to check, like `LM263061105.Q`. For weekly \
Fed figures cite the H.4.1 series the same way, like `H.4.1 RESPPLLDD`. Link the page \
that shows what you describe using the link values from tool results, written as a Markdown link with a short label, \
like [Treasury holders](#/us/instrument/F3_2?period=2026:Q2). The reader can click it to see the same numbers on the map.
"""


def system_prompt(con: duckdb.DuckDBPyConnection) -> str:
    from fwm import context

    from fwm import fedweekly

    periods = context.periods(con)
    weekly = "not loaded in this installation"
    if fedweekly.available(con):
        first, last = con.execute("SELECT min(date), max(date) FROM weekly_observations WHERE series_id = ?", [fedweekly.TOTAL]).fetchone()
        weekly = f"{first} to {last}"
    from fwm import tic

    foreign = "not loaded in this installation"
    if tic.available(con):
        first, last = con.execute("SELECT min(month), max(month) FROM tic_holdings WHERE asset = 'treasuries'").fetchone()
        foreign = f"{first:%Y-%m} to {last:%Y-%m}"
    from fwm import euroarea

    euro = "not loaded in this installation"
    if euroarea.available(con):
        quarters = euroarea.periods(con)
        euro = f"quarterly, {quarters[0]} to {quarters[-1]}"
    return SYSTEM.format(first=periods[0], latest=periods[-1], weekly=weekly, foreign=foreign, euro=euro)


def label(name: str, arguments: dict, result: dict | None) -> str:
    """A short description of a tool call for the user."""
    result = result or {}
    def quarter(value: str | None) -> str:
        return " ".join(reversed(value.split(":"))) if value else ""

    period = quarter(result.get("period"))
    since = f", change since {quarter(result['compared_to'])}" if result.get("compared_to") else ""
    if name == "get_instrument":
        return f"{result.get('instrument', arguments.get('instrument_id'))}: holders and issuers, {period}{since}"
    if name == "get_sector":
        return f"{result.get('sector', arguments.get('sector_id'))}: balance sheet, {period}{since}"
    if name == "get_history":
        count = len(arguments.get("series", []))
        return f"History of {count} position{'s' if count != 1 else ''}"
    if name == "latest_moves":
        return {"unusual_flows": "Unusual flows", "largest_flows": "Largest flows",
                "valuation_changes": "Largest valuation changes"}.get(arguments.get("kind"), "Moves") + f", {period}"
    return {
        "list_instruments": "List of instruments",
        "list_sectors": "List of sectors",
        "get_system_map": f"System map, {period}",
        "get_rates_and_gdp": "Interest rates and GDP",
        "get_fed_announcements": "Fed announcements",
        "get_fed_weekly": f"Federal Reserve weekly balance sheet, {result.get('date', 'latest week')}",
        "get_fed_weekly_history": "Federal Reserve weekly history",
        "get_foreign_holders": f"Foreign holders of {str(result.get('asset', 'US securities')).lower()} by country, {result.get('month', 'latest month')}",
        "get_foreign_holder_history": "Foreign holders' history",
        "get_country": f"{result.get('country', arguments.get('country', 'Country'))} and the US, {result.get('month', 'latest month')}",
        "flag_data_gap": "Noted a limit of the data",
    }.get(name, name)


def _block(block: Any, key: str, default: Any = None) -> Any:
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


def run_turn(con: duckdb.DuckDBPyConnection, client: Any, messages: list, user_text: str) -> Iterator[dict]:
    """Run one user turn. Appends to `messages` and yields events until the answer is complete."""
    messages.append({"role": "user", "content": user_text})
    system = [{"type": "text", "text": system_prompt(con)}]
    definitions = tools.definitions()
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}

    for _ in range(MAX_STEPS):
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=definitions,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            cache_control={"type": "ephemeral"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            for event in stream:
                if event.type == "text":
                    yield {"type": "text", "text": event.text}
            response = stream.get_final_message()

        for key in usage:
            usage[key] += getattr(response.usage, key, 0) or 0
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "pause_turn":
            continue
        if response.stop_reason == "refusal":
            yield {"type": "error", "message": "The model declined to answer this request."}
            return
        if response.stop_reason == "max_tokens":
            yield {"type": "error", "message": "The answer was cut off because it ran too long. Try a narrower question."}
            return
        if response.stop_reason != "tool_use":
            yield {"type": "done", "usage": usage, "model": response.model, "model_name": model_name(response.model)}
            return

        results = []
        for block in response.content:
            if _block(block, "type") != "tool_use":
                continue
            name, arguments = _block(block, "name"), _block(block, "input")
            try:
                result = tools.run(con, name, arguments)
                failed = False
            except tools.ToolError as error:
                result, failed = {"error": str(error)}, True
            event = {"type": "tool", "name": name, "input": arguments, "ok": not failed,
                     "label": label(name, arguments if isinstance(arguments, dict) else {}, None if failed else result),
                     "link": None if failed else result.get("link"), "result": result}
            if name == "flag_data_gap" and not failed:
                event = {"type": "gap", "category": result["category"], "explanation": result["shown_to_user"]}
            yield event
            results.append({
                "type": "tool_result",
                "tool_use_id": _block(block, "id"),
                "content": json.dumps(result, separators=(",", ":")),
                **({"is_error": True} if failed else {}),
            })
            yield {"type": "break"}
        messages.append({"role": "user", "content": results})

    yield {"type": "error", "message": "Stopped after too many lookups without reaching an answer."}


SETUP_HINT = ("The assistant needs a model to talk to. Either install Claude Code and log in (`claude`), which uses "
              "your subscription, or set ANTHROPIC_API_KEY. Then restart `fwm serve`.")
CLAUDE_BIN = os.environ.get("FWM_CLAUDE_BIN", "claude")
MCP_PREFIX = "mcp__fwm__"
SESSION_DIR = Path(__file__).resolve().parents[2] / "data" / "agent-sessions"


def backend() -> str | None:
    """Which model backend to use: 'api' (Anthropic API key), 'claude-code' (local login), or None.

    FWM_AGENT_BACKEND forces one. Otherwise an API key wins if present, since it was set on purpose.
    """
    forced = os.environ.get("FWM_AGENT_BACKEND")
    if forced in ("api", "claude-code"):
        return forced
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "api"
    if shutil.which(CLAUDE_BIN):
        return "claude-code"
    return None


def configured() -> bool:
    return backend() is not None


def model_name(model_id: str | None) -> str:
    """'claude-opus-5-5' -> 'Claude Opus 5.5'. Unrecognised ids are shown as they are."""
    match = re.fullmatch(r"claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?", model_id or "")
    if not match:
        return model_id or "unknown model"
    family, major, minor = match.groups()
    return f"Claude {family.capitalize()} {major}" + (f".{minor}" if minor else "")


def describe() -> str:
    """The model and how it is reached, in words, for status displays and benchmark records."""
    chosen = backend()
    if chosen is None:
        return "not configured"
    return f"{model_name(MODEL)} via {'the Anthropic API' if chosen == 'api' else 'Claude Code'}"


def _database_path(con: duckdb.DuckDBPyConnection) -> str:
    return con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()[0]


def claude_command(con: duckdb.DuckDBPyConnection, state: dict, user_text: str) -> list[str]:
    """The headless Claude Code invocation for one turn: our prompt, our tools, and nothing else."""
    servers = {"mcpServers": {"fwm": {
        "command": sys.executable, "args": ["-m", "fwm.mcp_server"], "env": {"FWM_DB": _database_path(con)},
    }}}
    command = [
        CLAUDE_BIN, "-p", user_text,
        "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--system-prompt", system_prompt(con),
        "--tools", "",                       # no file, shell or web tools
        "--strict-mcp-config", "--mcp-config", json.dumps(servers),
        "--allowedTools", "mcp__fwm",        # our tools run without permission prompts
        "--setting-sources", "",             # ignore the user's and project's Claude Code settings, hooks and memory
        "--disable-slash-commands",
        "--model", MODEL,                    # not whatever Claude Code happens to default to
        "--effort", EFFORT,
    ]
    # Follow-up questions continue the Claude Code session that the first one created.
    command += ["--resume", state["claude_session"]] if state.get("claude_session") else []
    return command


def parse_claude_stream(lines: Iterator[str], state: dict) -> Iterator[dict]:
    """Turn Claude Code's stream-json output into this module's events."""
    pending: dict[str, tuple[str, dict]] = {}
    finished = False
    model = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = message.get("type")
        if message.get("session_id"):
            state["claude_session"] = message["session_id"]
        if kind == "system" and message.get("subtype") == "init":
            model = message.get("model")
        elif kind == "stream_event":
            event = message.get("event", {})
            delta = event.get("delta", {})
            if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                yield {"type": "text", "text": delta.get("text", "")}
        elif kind == "assistant":
            for block in message.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    pending[block["id"]] = (block.get("name", "").removeprefix(MCP_PREFIX), block.get("input") or {})
        elif kind == "user":
            content = message.get("message", {}).get("content", [])
            for block in content if isinstance(content, list) else []:
                if block.get("type") != "tool_result" or block.get("tool_use_id") not in pending:
                    continue
                name, arguments = pending.pop(block["tool_use_id"])
                body = block.get("content")
                text = body if isinstance(body, str) else "".join(part.get("text", "") for part in body or [])
                try:
                    result = json.loads(text)
                except json.JSONDecodeError:
                    result = {"error": text}
                failed = bool(block.get("is_error")) or not isinstance(result, dict) or "error" in result
                if name == "flag_data_gap" and not failed:
                    yield {"type": "gap", "category": result["category"], "explanation": result["shown_to_user"]}
                else:
                    yield {"type": "tool", "name": name, "input": arguments, "ok": not failed,
                           "label": label(name, arguments, None if failed else result),
                           "link": None if failed else result.get("link"), "result": result}
                yield {"type": "break"}
        elif kind == "result":
            finished = True
            if message.get("is_error") or message.get("subtype") != "success":
                yield {"type": "error", "message": str(message.get("result") or message.get("subtype") or "Claude Code reported an error.")}
            else:
                usage = message.get("usage", {})
                yield {"type": "done", "model": model, "model_name": model_name(model),
                       "usage": {key: usage.get(key, 0) for key in ("input_tokens", "output_tokens", "cache_read_input_tokens")}}
    if not finished:
        yield {"type": "error", "message": "Claude Code stopped without finishing the answer."}


def claude_turn(con: duckdb.DuckDBPyConnection, state: dict, user_text: str) -> Iterator[dict]:
    """One user turn through a headless Claude Code session, using the local login."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    try:
        process = subprocess.Popen(
            claude_command(con, state, user_text), cwd=SESSION_DIR, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except FileNotFoundError:
        yield {"type": "error", "message": SETUP_HINT}
        return
    try:
        failed = False
        for event in parse_claude_stream(process.stdout, state):
            failed = failed or event["type"] == "error"
            if event["type"] == "error" and process.poll() not in (None, 0):
                detail = process.stderr.read().strip().splitlines()
                event = {"type": "error", "message": (detail[-1] if detail else event["message"])[:500]}
            yield event
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()


def answer(con: duckdb.DuckDBPyConnection, state: dict, user_text: str, client: Any = None) -> Iterator[dict]:
    """One user turn on whichever backend is configured. `state` is the conversation's memory; start with {}.

    Passing `client` forces the Anthropic API path with that client.
    """
    chosen = "api" if client is not None else backend()
    if chosen == "claude-code":
        yield from claude_turn(con, state, user_text)
        return
    if chosen is None:
        yield {"type": "error", "message": SETUP_HINT}
        return
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    messages = state.setdefault("messages", [])
    checkpoint = len(messages)
    failed = False
    for event in safe_turn(con, client, messages, user_text):
        failed = failed or event["type"] == "error"
        yield event
    if failed:
        # Leave the history as it was, so a failed turn cannot poison the conversation.
        del messages[checkpoint:]


def safe_turn(con: duckdb.DuckDBPyConnection, client: Any, messages: list, user_text: str) -> Iterator[dict]:
    """run_turn, with API failures turned into a single error event."""
    import anthropic

    try:
        yield from run_turn(con, client, messages, user_text)
    except anthropic.AuthenticationError:
        yield {"type": "error", "message": "Anthropic rejected the API credentials. " + SETUP_HINT}
    except anthropic.RateLimitError:
        yield {"type": "error", "message": "Rate limited by the Anthropic API. Wait a moment and try again."}
    except anthropic.APIStatusError as error:
        yield {"type": "error", "message": f"The Anthropic API returned an error ({error.status_code}): {error.message}"}
    except anthropic.APIConnectionError:
        yield {"type": "error", "message": "Could not reach the Anthropic API. Check the network connection."}
    except TypeError as error:
        # The SDK raises TypeError when it finds no credentials at all.
        if "auth" not in str(error).lower() and "api_key" not in str(error).lower():
            raise
        yield {"type": "error", "message": SETUP_HINT}
