"""Ingest the ECB's quarterly sector accounts for the euro area (dataset QSA).

The euro-area counterpart of the Fed's Z.1: for each sector, financial assets and
liabilities by instrument, as amounts outstanding (LE), transactions (F) and other
changes in volume and price (K). Amounts are in millions of euro.

    qsa_series(key, counterpart_area, sector, counterpart_sector, side, measure, instrument, maturity)
    qsa_observations(key, period, value)

One request returns every series for the area as CSV. The response is kept
compressed under data/raw/ecb/, with a dated copy of each release we see.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import shutil
import urllib.request
from pathlib import Path

import duckdb

from fwm.loaders import release

SOURCE_ID = "ecb_qsa"
SOURCE_NAME = "ECB, Quarterly Sector Accounts for the euro area (QSA)"
SOURCE_URL = "https://data.ecb.europa.eu/data/datasets/QSA"
# The euro area in its current composition. I9 is the previous composition and stops in 2025.
AREA = "I10"
API = "https://data-api.ecb.europa.eu/service/data/QSA/{key}?detail=dataonly&format=csvdata"
DIMENSIONS = ("FREQ", "ADJUSTMENT", "REF_AREA", "COUNTERPART_AREA", "REF_SECTOR", "COUNTERPART_SECTOR", "CONSOLIDATION",
              "ACCOUNTING_ENTRY", "STO", "INSTR_ASSET", "MATURITY", "EXPENDITURE", "UNIT_MEASURE", "CURRENCY_DENOM",
              "VALUATION", "PRICES", "TRANSFORMATION", "CUST_BREAKDOWN")
FILE_NAME = f"qsa_{AREA}.csv.gz"
MEASURES = {"LE": "level", "F": "transactions", "K": "other_change"}


def download(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    wanted = {"FREQ": "Q", "ADJUSTMENT": "N", "REF_AREA": AREA, "UNIT_MEASURE": "XDC"}
    key = ".".join(wanted.get(dimension, "") for dimension in DIMENSIONS)
    request = urllib.request.Request(API.format(key=key), headers={
        "User-Agent": "Mozilla/5.0", "Accept": "text/csv", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request, timeout=600) as response:
        body = response.read()
        if response.headers.get("Content-Encoding") != "gzip":
            body = gzip.compress(body)
    (raw_dir / FILE_NAME).write_bytes(body)


def parse(path: Path) -> tuple[list[tuple], list[tuple]]:
    """Series and observations for financial positions: unconsolidated, not transformed, no special breakdown."""
    series: dict[str, tuple] = {}
    observations = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            if (row["STO"] not in MEASURES or not row["INSTR_ASSET"].startswith("F") or row["TRANSFORMATION"] != "N"
                    or row["CUST_BREAKDOWN"] != "_T" or row["CONSOLIDATION"] != "N" or row["ACCOUNTING_ENTRY"] not in ("A", "L")):
                continue
            try:
                value = float(row["OBS_VALUE"])
            except ValueError:
                continue
            key = row["KEY"]
            if key not in series:
                series[key] = (key, row["COUNTERPART_AREA"], row["REF_SECTOR"], row["COUNTERPART_SECTOR"],
                               "assets" if row["ACCOUNTING_ENTRY"] == "A" else "liabilities", MEASURES[row["STO"]],
                               row["INSTR_ASSET"], row["MATURITY"])
            year, quarter = row["TIME_PERIOD"].split("-Q")
            observations.append((key, f"{year}:Q{quarter}", value))
    return list(series.values()), observations


def ingest(raw_dir: Path, db_path: Path) -> dict:
    path = raw_dir / FILE_NAME
    series, observations = parse(path)
    if not series:
        raise RuntimeError("ECB download holds no financial series")
    latest = max(period for _, period, _ in observations)
    # Each release revises earlier quarters: keep every one we see, named by the day it was fetched.
    fetched = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)
    vintage = raw_dir / "vintages" / f"qsa_{AREA}_{latest.replace(':', '')}_{fetched:%Y-%m-%d}.csv.gz"
    if not vintage.exists():
        vintage.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, vintage)
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE OR REPLACE TABLE qsa_series (key VARCHAR PRIMARY KEY, counterpart_area VARCHAR, sector VARCHAR, "
                    "counterpart_sector VARCHAR, side VARCHAR, measure VARCHAR, instrument VARCHAR, maturity VARCHAR)")
        con.execute("CREATE OR REPLACE TABLE qsa_observations (key VARCHAR, period VARCHAR, value DOUBLE)")
        con.executemany("INSERT INTO qsa_series VALUES (?, ?, ?, ?, ?, ?, ?, ?)", series)
        # Bulk load through CSV: far faster than row-by-row inserts for half a million values.
        buffer = io.StringIO()
        csv.writer(buffer).writerows(observations)
        staging = raw_dir / "_observations.csv"
        staging.write_text(buffer.getvalue())
        try:
            con.execute(f"INSERT INTO qsa_observations SELECT * FROM read_csv('{staging}', header=false, "
                        "columns={'key': 'VARCHAR', 'period': 'VARCHAR', 'value': 'DOUBLE'})")
        finally:
            staging.unlink()
        release.record(con, SOURCE_ID, SOURCE_NAME, SOURCE_URL, fetched, latest)

    finally:
        con.close()
    return {"series": len(series), "observations": len(observations), "latest": latest}


def available(con: duckdb.DuckDBPyConnection) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'qsa_observations'").fetchone()[0])
