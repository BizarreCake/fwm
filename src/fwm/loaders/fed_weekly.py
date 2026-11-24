"""Download and load the Federal Reserve's H.4.1 release: system-wide Wednesday levels.

    weekly_series(series_id, source, description)
    weekly_observations(series_id, date, value)      -- USD millions
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

from fwm.loaders import ddp, release

SOURCE_ID = "fed_h41"


SOURCE_NAME = "Federal Reserve H.4.1, Factors Affecting Reserve Balances"


SOURCE_URL = "https://www.federalreserve.gov/releases/h41/"


TOTAL = "RESPPMA"  # total assets, consolidated; equal to total liabilities and capital


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
        release.record(con, SOURCE_ID, SOURCE_NAME, SOURCE_URL, prepared, latest.isoformat())
    finally:
        con.close()
    return {"series": len(series), "observations": len(rows), "latest": latest.isoformat()}
