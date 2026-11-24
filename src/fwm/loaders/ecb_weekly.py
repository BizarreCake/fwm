"""Download and load the ECB's weekly financial statement of the Eurosystem.

    eurosystem_weekly(series_id, date, value)      -- EUR millions, as at the Friday of each week
"""

from __future__ import annotations

import csv
import datetime as dt
import urllib.request
from pathlib import Path

import duckdb

from fwm.loaders import release

SOURCE_ID = "ecb_weekly"


SOURCE_NAME = "ECB, Weekly financial statement of the Eurosystem (ILM)"


SOURCE_URL = "https://data.ecb.europa.eu/data/datasets/ILM"


API = "https://data-api.ecb.europa.eu/service/data/ILM/W.U2.C...?detail=dataonly&format=csvdata"


FILE_NAME = "ilm_weekly.csv"


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
        release.record(con, SOURCE_ID, SOURCE_NAME, SOURCE_URL, fetched, latest.isoformat())
    finally:
        con.close()
    return {"weeks": len({date for _, date, _ in rows}), "latest": latest.isoformat()}
