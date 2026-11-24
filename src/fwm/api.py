"""HTTP API. The UI and (later) the agent's tools read the same endpoints."""

from __future__ import annotations

import json
import os
import threading
from collections import OrderedDict
from pathlib import Path

import duckdb
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles

from fwm import agent, context, countries, economies, fedweekly, instruments, tic, overview, sectors, systemmap

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("FWM_DB", ROOT / "data" / "fwm.duckdb"))
WEB_DIST = ROOT / "web" / "dist"

app = FastAPI(title="fwm")


def known_economy(economy: str = economies.DEFAULT) -> str:
    if economy not in economies.ECONOMIES:
        raise HTTPException(404, f"No accounts for economy {economy!r}; known: {sorted(economies.ECONOMIES)}")
    return economy


# Everything that describes one economy's own accounts. Served under /api/economy/{economy}/..., and, for links
# made before there was more than one economy, under /api/... for the default economy.
economy_api = APIRouter(dependencies=[Depends(known_economy)])


def us_only(economy: str = economies.DEFAULT) -> None:
    if economy != "us":
        raise HTTPException(404, f"Not available for {economies.ECONOMIES[economy]['name']}: built from US sources only.")


def connect() -> duckdb.DuckDBPyConnection:
    if not DB_PATH.exists():
        raise HTTPException(503, "No data yet. Run `uv run fwm ingest` first.")
    return duckdb.connect(str(DB_PATH), read_only=True)


@economy_api.get("/overview", dependencies=[Depends(us_only)])
def overview_view() -> dict:
    con = connect()
    try:
        view = overview.load(con)
    finally:
        con.close()
    if view is None:
        raise HTTPException(503, "Overview not built yet. Run `uv run fwm ingest --no-download`.")
    return view


@economy_api.get("/system-map", dependencies=[Depends(us_only)])
def system_map() -> dict:
    con = connect()
    try:
        view = systemmap.load(con)
    finally:
        con.close()
    if view is None:
        raise HTTPException(503, "System map not built yet. Run `uv run fwm ingest --no-download`.")
    return view


@economy_api.get("/context", dependencies=[Depends(us_only)])
def context_view() -> dict:
    con = connect()
    try:
        return context.view(con)
    finally:
        con.close()


# Each conversation's state lives in memory for as long as the server runs.
SESSIONS: OrderedDict[str, dict] = OrderedDict()
SESSION_LOCKS: dict[str, threading.Lock] = {}
MAX_SESSIONS = 100
_client = None  # set by tests to script the model


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[\w-]+$")
    message: str = Field(min_length=1, max_length=4000)


@app.get("/api/chat/status")
def chat_status() -> dict:
    ready = _client is not None or agent.configured()
    return {
        "configured": ready,
        "model": agent.MODEL,
        "model_name": agent.model_name(agent.MODEL),
        "via": {"api": "Anthropic API", "claude-code": "Claude Code"}.get(agent.backend()),
        "hint": None if ready else agent.SETUP_HINT,
    }


@app.post("/api/chat")
def chat(request: ChatRequest) -> StreamingResponse:
    """One user turn, streamed as server-sent events: text, tool, gap, break, done, error."""
    state = SESSIONS.setdefault(request.session_id, {})
    SESSIONS.move_to_end(request.session_id)
    while len(SESSIONS) > MAX_SESSIONS:
        dropped, _ = SESSIONS.popitem(last=False)
        SESSION_LOCKS.pop(dropped, None)
    lock = SESSION_LOCKS.setdefault(request.session_id, threading.Lock())

    def events():
        if not lock.acquire(blocking=False):
            yield {"type": "error", "message": "Still answering the previous question in this conversation."}
            return
        try:
            con = connect()
            try:
                for event in agent.answer(con, state, request.message, _client):
                    # Tool results stay server-side; the browser gets the label and link.
                    yield {k: v for k, v in event.items() if k != "result"}
            finally:
                con.close()
        finally:
            lock.release()

    def stream():
        for event in events():
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@economy_api.get("/weekly/fed", dependencies=[Depends(us_only)])
def fed_weekly() -> dict:
    con = connect()
    try:
        view = fedweekly.view(con)
    finally:
        con.close()
    if view is None:
        raise HTTPException(503, "Weekly Fed data not loaded yet. Run `uv run fwm ingest --only fed-weekly`.")
    return view


@economy_api.get("/foreign/{asset}", dependencies=[Depends(us_only)])
def foreign_holders(asset: str) -> dict:
    if asset not in tic.INWARD:
        raise HTTPException(404, f"No foreign holdings for {asset!r}; known: {tic.INWARD}")
    con = connect()
    try:
        view = tic.view(con, asset)
    finally:
        con.close()
    if view is None:
        raise HTTPException(503, "Foreign holdings by country not loaded yet. Run `uv run fwm ingest --only tic`.")
    return view


@economy_api.get("/instruments")
def instrument_list(economy: str = economies.DEFAULT) -> list[dict]:
    con = connect()
    try:
        return economies.accounts(economy)[1].list_instruments(con)
    finally:
        con.close()


@economy_api.get("/instruments/{instrument_id}")
def instrument_view(instrument_id: str, economy: str = economies.DEFAULT) -> dict:
    con = connect()
    try:
        view = economies.accounts(economy)[1].view(con, instrument_id)
    finally:
        con.close()
    if view is None:
        raise HTTPException(404, f"No holder data for instrument {instrument_id!r}")
    return view


@economy_api.get("/sectors")
def sector_list(economy: str = economies.DEFAULT) -> list[dict]:
    con = connect()
    try:
        return economies.accounts(economy)[0].list_sectors(con)
    finally:
        con.close()


@economy_api.get("/sectors/{sector_id}")
def sector_balance_sheet(sector_id: str, economy: str = economies.DEFAULT) -> dict:
    con = connect()
    try:
        view = economies.accounts(economy)[0].balance_sheet(con, sector_id)
    finally:
        con.close()
    if view is None:
        raise HTTPException(404, f"No balance sheet for sector {sector_id!r}")
    return view


@app.get("/api/economies")
def economy_list() -> list[dict]:
    return economies.listing()


@app.get("/api/countries")
def country_list() -> list[dict]:
    con = connect()
    try:
        return countries.listing(con)
    finally:
        con.close()


@app.get("/api/countries/{country_id}")
def country_view(country_id: str) -> dict:
    con = connect()
    try:
        view = countries.view(con, country_id)
    finally:
        con.close()
    if view is None:
        raise HTTPException(404, f"No country {country_id!r}")
    return view


app.include_router(economy_api, prefix="/api/economy/{economy}")
app.include_router(economy_api, prefix="/api")

if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
