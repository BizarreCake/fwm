"""Ingest the Bank of Japan's Flow of Funds accounts (2008 SNA basis).

One flat file holds every series: FOF_FFA + S|F|R (stock, flow, reconciliation) + a
three-digit sector + A|L (assets, liabilities) + a three-digit transaction item, with a
value per quarter. Quarters are calendar quarters (202602 is April to June 2026). Values
are in units of 100 million yen and are stored here in JPY millions.

    jff_observations(series_id, period, value)

Each download is kept in `vintages/` under the date the Bank prepared the file.
"""

from __future__ import annotations

import datetime as dt
import shutil
import urllib.request
import zipfile
from pathlib import Path

import duckdb

from fwm import ddp

SOURCE_ID = "boj_fof"
SOURCE_NAME = "Bank of Japan, Flow of Funds Accounts"
SOURCE_URL = "https://www.boj.or.jp/en/statistics/sj/index.htm"
DOWNLOAD = "https://www.stat-search.boj.or.jp/info/fof.zip"
ZIP_NAME = "fof.zip"
MEMBER = "ff_value.csv"


def download(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(DOWNLOAD, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=300) as response:
        (raw_dir / ZIP_NAME).write_bytes(response.read())


def _extract(raw_dir: Path) -> tuple[Path, dt.datetime]:
    """Unpack the one file we use, and return it with the time the Bank wrote it."""
    with zipfile.ZipFile(raw_dir / ZIP_NAME) as archive:
        info = archive.getinfo(MEMBER)
        prepared = dt.datetime(*info.date_time, tzinfo=dt.timezone(dt.timedelta(hours=9)))
        target = raw_dir / MEMBER
        with archive.open(info) as source, target.open("wb") as out:
            shutil.copyfileobj(source, out)
    vintage = raw_dir / "vintages" / f"fof-{prepared:%Y%m%d}.zip"
    if not vintage.exists():
        vintage.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(raw_dir / ZIP_NAME, vintage)
    return target, prepared


def ingest(raw_dir: Path, db_path: Path) -> dict:
    path, prepared = _extract(raw_dir)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            "CREATE OR REPLACE TABLE jff_observations AS "
            "SELECT trim(code) AS series_id, substr(trim(period), 1, 4) || ':Q' || CAST(CAST(substr(trim(period), 5, 2) AS INTEGER) AS VARCHAR) AS period, "
            "100 * TRY_CAST(trim(value) AS DOUBLE) AS value "
            "FROM read_csv(?, header = false, all_varchar = true, columns = {'code': 'VARCHAR', 'frequency': 'VARCHAR', "
            "'period': 'VARCHAR', 'value': 'VARCHAR'}) "
            "WHERE trim(frequency) = 'Q' AND regexp_matches(trim(code), '^FOF_FFA[SFR][0-9]{3}[AL][0-9]{3}$') "
            "AND TRY_CAST(trim(value) AS DOUBLE) IS NOT NULL", [str(path)])
        observations, series, latest = con.execute(
            "SELECT count(*), count(DISTINCT series_id), max(period) FROM jff_observations").fetchone()
        if not observations:
            raise RuntimeError("Bank of Japan flow of funds file holds no quarterly values")
        ddp.record_release(con, SOURCE_ID, SOURCE_NAME, SOURCE_URL, prepared, latest)
        from fwm import overview, systemmap

        overview.build(con, "jp")
        systemmap.build(con, "jp")
    finally:
        con.close()
    return {"observations": observations, "series": series, "latest": latest}


def available(con: duckdb.DuckDBPyConnection) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'jff_observations'").fetchone()[0])
