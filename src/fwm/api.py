"""HTTP API. The UI and (later) the agent's tools read the same endpoints."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from fwm import instruments, sectors

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("FWM_DB", ROOT / "data" / "fwm.duckdb"))
WEB_DIST = ROOT / "web" / "dist"

app = FastAPI(title="fwm")


def connect() -> duckdb.DuckDBPyConnection:
    if not DB_PATH.exists():
        raise HTTPException(503, "No data yet. Run `uv run fwm ingest` first.")
    return duckdb.connect(str(DB_PATH), read_only=True)


@app.get("/api/instruments")
def instrument_list() -> list[dict]:
    con = connect()
    try:
        return instruments.list_instruments(con)
    finally:
        con.close()


@app.get("/api/instruments/{instrument_id}")
def instrument_view(instrument_id: str) -> dict:
    con = connect()
    try:
        view = instruments.view(con, instrument_id)
    finally:
        con.close()
    if view is None:
        raise HTTPException(404, f"No holder data for instrument {instrument_id!r}")
    return view


@app.get("/api/sectors")
def sector_list() -> list[dict]:
    con = connect()
    try:
        return sectors.list_sectors(con)
    finally:
        con.close()


@app.get("/api/sectors/{sector_id}")
def sector_balance_sheet(sector_id: str) -> dict:
    con = connect()
    try:
        view = sectors.balance_sheet(con, sector_id)
    finally:
        con.close()
    if view is None:
        raise HTTPException(404, f"No balance sheet for sector {sector_id!r}")
    return view


if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
