"""The Federal Reserve's balance sheet every Wednesday, from the H.4.1 release.

Z.1 shows the central bank once a quarter, months late. H.4.1 shows it weekly,
a day after the fact. This module keeps the system-wide Wednesday levels:

    weekly_series(series_id, source, description)
    weekly_observations(series_id, date, value)      -- USD millions

and arranges a chosen set of lines into a balance sheet. On each side, the
named lines plus one computed "other" line equal the published total, so the
sheet always adds up. Over history "other" holds the crisis facilities that
H.4.1 has since discontinued.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import duckdb

from fwm import context, ddp

SOURCE_ID = "fed_h41"
SOURCE_NAME = "Federal Reserve H.4.1, Factors Affecting Reserve Balances"
SOURCE_URL = "https://www.federalreserve.gov/releases/h41/"
TOTAL = "RESPPMA"  # total assets, consolidated; equal to total liabilities and capital
# How the assistant's tool cites this statement.
CITE = {"prefix": "H.4.1", "total": TOTAL, "currency": "USD", "valuation": "securities at face value"}

# (id, name, H.4.1 series added together, children). A leading "-" subtracts a series.
Line = tuple[str, str, tuple[str, ...], tuple]
ASSETS: tuple[Line, ...] = (
    ("treasuries", "Treasury securities", ("RESPPALGUO",), (
        ("treasury_bills", "Bills", ("RESPPALGUOB",), ()),
        ("treasury_notes_bonds", "Notes and bonds", ("RESPPALGUON",), ()),
    )),
    ("mbs", "Mortgage-backed securities", ("RESPPALGASMO",), ()),
    ("agency_debt", "Agency debt", ("RESPPALGAO",), ()),
    ("premiums", "Unamortized premiums and discounts", ("RESPPALSP", "RESPPALSD"), ()),
    ("repo", "Repurchase agreements", ("RESPPALGTR",), ()),
    ("loans", "Loans", ("RESPPALDN",), ()),
    ("swaps", "Central bank liquidity swaps", ("RESH4SCS",), ()),
)
LIABILITIES: tuple[Line, ...] = (
    ("currency", "Currency in circulation (Federal Reserve notes)", ("RESPPLLN",), ()),
    ("reserves", "Reserve balances of banks", ("RESPPLLDD",), ()),
    ("reverse_repo", "Reverse repurchase agreements", ("RESPPLLR",), (
        ("reverse_repo_foreign", "Foreign official accounts", ("RESPPLLRF",), ()),
        ("reverse_repo_other", "Other counterparties (includes the overnight facility)", ("RESPPLLRD",), ()),
    )),
    ("tga", "Treasury General Account", ("RESPPLLDT",), ()),
    ("other_deposits", "Other deposits", ("RESPPMLLD", "-RESPPLLDD", "-RESPPLLDT"), ()),
    # Negative when the Fed has run losses: it records them as a claim on its own future earnings.
    ("remittances", "Earnings remittances due to the Treasury", ("RESPPLLOP",), ()),
    ("capital", "Capital", ("RESPPLC",), ()),
)
OTHER = {"assets": ("other_assets", "Other assets"), "liabilities": ("other_liabilities", "Other liabilities")}

_SYSTEM_WIDE_LEVEL = re.compile(r"^RES[A-Z0-9]+_N\.WW$")  # not a district (_F01_), an average (_XAW_) or a change (_XCH)


def download(raw_dir: Path) -> None:
    ddp.download("H41", raw_dir / "h41.zip")


def ingest(raw_dir: Path, db_path: Path) -> dict:
    series, prepared = ddp.parse(raw_dir / "h41.zip", lambda name: bool(_SYSTEM_WIDE_LEVEL.match(name)))
    if f"{TOTAL}_N.WW" not in series:
        raise RuntimeError("H.4.1 download has no total assets series")
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE TABLE IF NOT EXISTS weekly_series (series_id VARCHAR, source VARCHAR, description VARCHAR)")
        con.execute("CREATE TABLE IF NOT EXISTS weekly_observations (series_id VARCHAR, date DATE, value DOUBLE)")
        con.execute("DELETE FROM weekly_observations WHERE series_id IN (SELECT series_id FROM weekly_series WHERE source = ?)", [SOURCE_ID])
        con.execute("DELETE FROM weekly_series WHERE source = ?", [SOURCE_ID])
        rows = []
        for name, entry in series.items():
            series_id = name.removesuffix("_N.WW")
            con.execute("INSERT INTO weekly_series VALUES (?, ?, ?)",
                        [series_id, SOURCE_ID, (entry["description"] or "").removesuffix(": Wednesday level")])
            # Published in millions of dollars (UNIT_MULT 1000000); stored in millions, like Z.1.
            rows += [(series_id, date, value * entry["multiplier"] / 1e6) for date, value in entry["observations"]]
        con.executemany("INSERT INTO weekly_observations VALUES (?, ?, ?)", rows)
        latest = con.execute("SELECT max(date) FROM weekly_observations WHERE series_id = ?", [TOTAL]).fetchone()[0]
        ddp.record_release(con, SOURCE_ID, SOURCE_NAME, SOURCE_URL, prepared, latest.isoformat())
    finally:
        con.close()
    return {"series": len(series), "observations": len(rows), "latest": latest.isoformat()}


def available(con: duckdb.DuckDBPyConnection) -> bool:
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'weekly_observations'").fetchone()[0])


def _load(con: duckdb.DuckDBPyConnection) -> tuple[list[dt.date], dict[str, list]]:
    dates = [row[0] for row in con.execute(
        "SELECT date FROM weekly_observations WHERE series_id = ? ORDER BY date", [TOTAL]).fetchall()]
    index = {date: i for i, date in enumerate(dates)}
    values: dict[str, list] = {}
    for series_id, date, value in con.execute(
        "SELECT o.series_id, o.date, o.value FROM weekly_observations o JOIN weekly_series s USING (series_id) WHERE s.source = ?",
        [SOURCE_ID],
    ).fetchall():
        if date in index:
            values.setdefault(series_id, [None] * len(dates))[index[date]] = value
    return dates, values


def view(con: duckdb.DuckDBPyConnection) -> dict | None:
    """The weekly balance sheet over its whole history, as two trees of lines."""
    if not available(con):
        return None
    dates, values = _load(con)
    n = len(dates)
    total = values[TOTAL]

    def combine(parts: tuple[str, ...]) -> list:
        out = [0.0] * n
        for part in parts:
            sign = -1 if part.startswith("-") else 1
            series = values.get(part.lstrip("-"), [None] * n)
            for i in range(n):
                # A line missing in a week is zero that week: H.4.1 omits items before they existed.
                out[i] += sign * (series[i] or 0.0)
        return out

    def node(line: Line) -> dict:
        line_id, name, parts, children = line
        return {"id": line_id, "name": name, "series": [part.lstrip("-") for part in parts], "computed": len(parts) > 1,
                "level": combine(parts), "children": [node(child) for child in children]}

    def side(lines: tuple[Line, ...], key: str) -> dict:
        nodes = [node(line) for line in lines]
        rest = [total[i] - sum(item["level"][i] for item in nodes) for i in range(n)]
        other_id, other_name = OTHER[key]
        nodes.append({"id": other_id, "name": other_name, "series": [], "computed": True, "level": rest, "children": []})
        return {"total": total, "lines": nodes}

    quarters = context.periods(con)
    latest_quarter = quarters[-1]
    year, quarter = latest_quarter.split(":Q")
    quarter_end = dt.date(int(year), int(quarter) * 3, 30 if quarter in ("2", "3") else 31)
    # The last Wednesday on or before the end of the latest quarter in the quarterly accounts.
    anchor = max((i for i, date in enumerate(dates) if date <= quarter_end), default=0)

    events = []
    for event in context.load_events():
        on = dt.date.fromisoformat(event["date"])
        week = next((i for i, date in enumerate(dates) if date >= on), None)
        if week is not None and on >= dates[0]:
            events.append({**event, "index": week})

    release = con.execute("SELECT name, url, published_at FROM source_release WHERE source_id = ?", [SOURCE_ID]).fetchone()
    return {
        "id": "fed",
        "name": "Federal Reserve, weekly",
        "central_bank": "Federal Reserve",
        "possessive": "the Fed's",
        "weekday": "Wednesday",
        "series_label": "H.4.1 series",
        "headline": ["reserves", "reverse_repo", "tga"],
        "default_line": "reserves",
        "page": "#/us/weekly/fed",
        "unit": "USD millions",
        "periods": [date.isoformat() for date in dates],
        "assets": side(ASSETS, "assets"),
        "liabilities": side(LIABILITIES, "liabilities"),
        "quarterly": {"period": latest_quarter, "index": anchor, "sector_id": "S121"},
        "events": events,
        "source": {"name": release[0], "url": release[1], "published_at": release[2].isoformat() if release[2] else None,
                   "latest": dates[-1].isoformat()},
        "notes": {
            "basis": "Levels each Wednesday. Securities are at face value, so these differ from the quarterly accounts, "
                     "which show Treasury and agency securities at market value.",
            "other": "On each side, the named lines and one computed \"other\" line add up to the published total. "
                     "\"Other\" is small today; in 2008 to 2010 and in 2020 it holds emergency facilities that H.4.1 has since discontinued.",
            "counterparties": "H.4.1 does not name counterparties. Reverse repos are split only into foreign official accounts and everyone else.",
        },
    }
