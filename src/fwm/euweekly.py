"""The Eurosystem's consolidated balance sheet, weekly (the ECB's weekly financial statement).

The euro-area counterpart of fedweekly.py, in the same shape: two trees of lines whose
named lines and one computed "other" line add up to the published total. Amounts are
EUR millions, as at the Friday of each week, from January 1999.

    eurosystem_weekly(series_id, date, value)
"""

from __future__ import annotations

import csv
import datetime as dt
import urllib.request
from pathlib import Path

import duckdb

from fwm import ddp, eacontext, euroarea

SOURCE_ID = "ecb_weekly"
SOURCE_NAME = "ECB, Weekly financial statement of the Eurosystem (ILM)"
SOURCE_URL = "https://data.ecb.europa.eu/data/datasets/ILM"
API = "https://data-api.ecb.europa.eu/service/data/ILM/W.U2.C...?detail=dataonly&format=csvdata"
FILE_NAME = "ilm_weekly.csv"
TOTAL = "T000000"
# How the assistant's tool cites this statement.
CITE = {"prefix": "ECB weekly statement", "total": TOTAL, "currency": "EUR",
        "valuation": "securities held for monetary policy at amortised cost"}

Line = tuple[str, str, tuple[str, ...], tuple]
ASSETS: tuple[Line, ...] = (
    ("securities", "Securities of euro area residents", ("A070000",), (
        ("securities_policy", "Held for monetary policy purposes", ("A070100",), ()),
        ("securities_other", "Other securities", ("A070200",), ()),
    )),
    ("lending", "Lending to euro area banks (monetary policy operations)", ("A050000",), (
        ("lending_main", "Main refinancing operations", ("A050100",), ()),
        ("lending_longer", "Longer-term refinancing operations", ("A050200",), ()),
    )),
    ("gold", "Gold and gold receivables", ("A010000",), ()),
    ("foreign_currency", "Claims in foreign currency", ("A020000", "A030000"), ()),
    ("other_bank_claims", "Other claims on euro area banks", ("A060000",), ()),
    ("euro_claims_abroad", "Claims on non-euro area residents in euro", ("A040000",), ()),
    ("government_debt", "General government debt", ("A080000",), ()),
)
LIABILITIES: tuple[Line, ...] = (
    ("banknotes", "Banknotes in circulation", ("L010000",), ()),
    ("bank_deposits", "Deposits of euro area banks (monetary policy operations)", ("L020000",), (
        ("current_accounts", "Current accounts (including minimum reserves)", ("L020100",), ()),
        ("deposit_facility", "Deposit facility", ("L020200",), ()),
    )),
    ("government_deposits", "Deposits of euro area governments", ("L050100",), ()),
    ("non_resident_deposits", "Liabilities to non-euro area residents in euro", ("L060000",), ()),
    ("other_resident_deposits", "Other euro area residents' deposits", ("L050200", "L030000"), ()),
    ("revaluation", "Revaluation accounts", ("L140000",), ()),
    ("capital", "Capital and reserves", ("L150000",), ()),
)
OTHER = {"assets": ("other_assets", "Other assets"), "liabilities": ("other_liabilities", "Other liabilities")}


def download(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(API, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv"})
    with urllib.request.urlopen(request, timeout=300) as response:
        (raw_dir / FILE_NAME).write_bytes(response.read())


def week_end(period: str) -> dt.date:
    """'2026-W47' -> the Friday of that week, the day the statement is drawn up for."""
    year, week = period.split("-W")
    return dt.date.fromisocalendar(int(year), int(week), 5)


def ingest(raw_dir: Path, db_path: Path) -> dict:
    path = raw_dir / FILE_NAME
    rows = []
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            try:
                rows.append((row["BS_ITEM"], week_end(row["TIME_PERIOD"]), float(row["OBS_VALUE"])))
            except ValueError:
                continue
    if not rows:
        raise RuntimeError("ECB weekly statement download holds no values")
    latest = max(date for _, date, _ in rows)
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE OR REPLACE TABLE eurosystem_weekly (series_id VARCHAR, date DATE, value DOUBLE)")
        con.executemany("INSERT INTO eurosystem_weekly VALUES (?, ?, ?)", rows)
        fetched = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)
        ddp.record_release(con, SOURCE_ID, SOURCE_NAME, SOURCE_URL, fetched, latest.isoformat())
    finally:
        con.close()
    return {"weeks": len({date for _, date, _ in rows}), "latest": latest.isoformat()}


def available(con: duckdb.DuckDBPyConnection) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'eurosystem_weekly'").fetchone()[0])


def view(con: duckdb.DuckDBPyConnection) -> dict | None:
    if not available(con):
        return None
    dates = [row[0] for row in con.execute("SELECT date FROM eurosystem_weekly WHERE series_id = ? ORDER BY date", [TOTAL]).fetchall()]
    index = {date: i for i, date in enumerate(dates)}
    n = len(dates)
    values: dict[str, list] = {}
    for series_id, date, value in con.execute("SELECT series_id, date, value FROM eurosystem_weekly").fetchall():
        if date in index:
            values.setdefault(series_id, [None] * n)[index[date]] = value
    total = values[TOTAL]

    def combine(parts: tuple[str, ...]) -> list:
        # A line missing in a week is zero that week: items are not reported before they existed.
        return [sum((values.get(part, [None] * n)[i] or 0.0) for part in parts) for i in range(n)]

    def node(line: Line) -> dict:
        line_id, name, parts, children = line
        return {"id": line_id, "name": name, "series": list(parts), "computed": len(parts) > 1,
                "level": combine(parts), "children": [node(child) for child in children]}

    def side(lines: tuple[Line, ...], key: str) -> dict:
        nodes = [node(line) for line in lines]
        rest = [total[i] - sum(item["level"][i] for item in nodes) for i in range(n)]
        other_id, other_name = OTHER[key]
        nodes.append({"id": other_id, "name": other_name, "series": [], "computed": True, "level": rest, "children": []})
        return {"total": total, "lines": nodes}

    latest_quarter = euroarea.periods(con)[-1]
    year, quarter = latest_quarter.split(":Q")
    quarter_end = dt.date(int(year), int(quarter) * 3, 30 if quarter in ("2", "3") else 31)
    anchor = max((i for i, date in enumerate(dates) if date <= quarter_end), default=0)
    events = []
    for event in eacontext.load_events():
        on = dt.date.fromisoformat(event["date"])
        week = next((i for i, date in enumerate(dates) if date >= on), None)
        if week is not None and on >= dates[0]:
            events.append({**event, "index": week})
    release = con.execute("SELECT name, url, published_at FROM source_release WHERE source_id = ?", [SOURCE_ID]).fetchone()
    return {
        "id": "eurosystem",
        "name": "Eurosystem, weekly",
        "central_bank": "Eurosystem",
        "possessive": "the Eurosystem's",
        "weekday": "Friday",
        "series_label": "ECB weekly financial statement item",
        "headline": ["bank_deposits", "government_deposits", "banknotes"],
        "default_line": "bank_deposits",
        "page": "#/ea/weekly/eurosystem",
        "unit": "EUR millions",
        "periods": [date.isoformat() for date in dates],
        "assets": side(ASSETS, "assets"),
        "liabilities": side(LIABILITIES, "liabilities"),
        "quarterly": {"period": latest_quarter, "index": anchor, "sector_id": "S121"},
        "events": events,
        "source": {"name": release[0], "url": release[1], "published_at": release[2].isoformat() if release[2] else None,
                   "latest": dates[-1].isoformat()},
        "notes": {
            "basis": "Levels each Friday, for the ECB and the national central banks of the euro area together. Securities "
                     "held for monetary policy are at amortised cost, so these differ from the quarterly accounts, which "
                     "show securities at market value. Gold and foreign currency are revalued at the end of each quarter.",
            "other": "On each side, the named lines and one computed \"other\" line add up to the published total.",
            "counterparties": "The statement does not name counterparties: banks, governments and non-residents appear only as groups.",
        },
    }
