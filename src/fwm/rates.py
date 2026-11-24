"""Daily interest rates from the Federal Reserve's H.15 release.

The download is one zip holding an SDMX XML file with every H.15 series. We keep
the business-day series for a handful of benchmark rates:

    rate_series(series_id, name, short_name, description)
    rates_daily(series_id, date, value)       -- percent per year
"""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import duckdb

H15_URL = "https://www.federalreserve.gov/datadownload/Output.aspx?rel=H15&filetype=zip"
SOURCE_ID = "fed_h15"

# H.15 series name -> (id used in this project, name, short name)
SERIES = {
    "RIFSPFF_N.B": ("fed_funds", "Federal funds effective rate", "Fed funds"),
    "RIFLGFCM03_N.B": ("treasury_3m", "3-month Treasury yield", "3-month"),
    "RIFLGFCY02_N.B": ("treasury_2y", "2-year Treasury yield", "2-year"),
    "RIFLGFCY10_N.B": ("treasury_10y", "10-year Treasury yield", "10-year"),
}


def download(raw_dir: Path) -> None:
    import urllib.request

    raw_dir.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(H15_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request) as response:
        (raw_dir / "h15.zip").write_bytes(response.read())


def parse(zip_path: Path) -> tuple[dict[str, list[tuple[dt.date, float]]], dt.datetime | None]:
    """Observations per H.15 series name, and the time the file was prepared."""
    out: dict[str, list[tuple[dt.date, float]]] = {name: [] for name in SERIES}
    prepared = None
    current = None
    with zipfile.ZipFile(zip_path) as archive, archive.open("H15_data.xml") as source:
        for event, element in ET.iterparse(source, events=("start", "end")):
            tag = element.tag.rsplit("}", 1)[-1]
            if event == "start" and tag == "Series":
                name = element.attrib.get("SERIES_NAME")
                current = name if name in SERIES else None
            elif event == "end" and tag == "Obs":
                # Status "A" is a normal observation; holidays and missing days carry other codes.
                if current and element.attrib.get("OBS_STATUS") == "A":
                    out[current].append((
                        dt.date.fromisoformat(element.attrib["TIME_PERIOD"]),
                        float(element.attrib["OBS_VALUE"]),
                    ))
                element.clear()
            elif event == "end" and tag == "Prepared" and element.text:
                prepared = dt.datetime.fromisoformat(element.text.strip())
    return out, prepared


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
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS source_release (
                source_id VARCHAR PRIMARY KEY, name VARCHAR, url VARCHAR,
                published_at TIMESTAMPTZ, ingested_at TIMESTAMPTZ, latest_period VARCHAR)
            """
        )
        con.execute("DELETE FROM source_release WHERE source_id = ?", [SOURCE_ID])
        con.execute(
            "INSERT INTO source_release VALUES (?, ?, ?, ?, now(), ?)",
            [SOURCE_ID, "Federal Reserve H.15, Selected Interest Rates",
             "https://www.federalreserve.gov/releases/h15/", prepared, latest.isoformat()],
        )
        count = con.execute("SELECT count(*) FROM rates_daily").fetchone()[0]
    finally:
        con.close()
    return {"observations": count, "latest": latest.isoformat()}
