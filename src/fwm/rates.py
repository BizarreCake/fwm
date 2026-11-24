"""Daily interest rates from the Federal Reserve's H.15 release.

The download is one zip holding an SDMX XML file with every H.15 series. We keep
the business-day series for a handful of benchmark rates:

    rate_series(series_id, name, short_name, description)
    rates_daily(series_id, date, value)       -- percent per year
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import duckdb

from fwm import ddp

SOURCE_ID = "fed_h15"

# H.15 series name -> (id used in this project, name, short name)
SERIES = {
    "RIFSPFF_N.B": ("fed_funds", "Federal funds effective rate", "Fed funds"),
    "RIFLGFCM03_N.B": ("treasury_3m", "3-month Treasury yield", "3-month"),
    "RIFLGFCY02_N.B": ("treasury_2y", "2-year Treasury yield", "2-year"),
    "RIFLGFCY10_N.B": ("treasury_10y", "10-year Treasury yield", "10-year"),
}


def download(raw_dir: Path) -> None:
    ddp.download("H15", raw_dir / "h15.zip")


def parse(zip_path: Path) -> tuple[dict[str, list[tuple[dt.date, float]]], dt.datetime | None]:
    """Observations per H.15 series name, and the time the file was prepared."""
    series, prepared = ddp.parse(zip_path, lambda name: name in SERIES)
    return {name: series.get(name, {"observations": []})["observations"] for name in SERIES}, prepared


def ingest(raw_dir: Path, db_path: Path) -> dict:
    observations, prepared = parse(raw_dir / "h15.zip")
    missing = [name for name, rows in observations.items() if not rows]
    if missing:
        raise RuntimeError(f"H.15 download has no observations for {missing}")
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE OR REPLACE TABLE rate_series (series_id VARCHAR, name VARCHAR, short_name VARCHAR, source_series VARCHAR)")
        con.execute("CREATE OR REPLACE TABLE rates_daily (series_id VARCHAR, date DATE, value DOUBLE)")
        for source_series, (series_id, name, short_name) in SERIES.items():
            con.execute("INSERT INTO rate_series VALUES (?, ?, ?, ?)", [series_id, name, short_name, source_series])
            con.executemany(
                "INSERT INTO rates_daily VALUES (?, ?, ?)",
                [(series_id, date, value) for date, value in observations[source_series]],
            )
        latest = con.execute("SELECT max(date) FROM rates_daily").fetchone()[0]
        ddp.record_release(con, SOURCE_ID, "Federal Reserve H.15, Selected Interest Rates",
                           "https://www.federalreserve.gov/releases/h15/", prepared, latest.isoformat())
        count = con.execute("SELECT count(*) FROM rates_daily").fetchone()[0]
    finally:
        con.close()
    return {"observations": count, "latest": latest.isoformat()}
