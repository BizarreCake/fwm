"""Ingest the Federal Reserve Z.1 (Financial Accounts of the United States) bulk CSV release.

The release is a zip of wide CSVs (one per table, one column per series) plus a
tab-separated data dictionary per table. We normalise it into two DuckDB tables:

    z1_series(series_id, description, unit, table_id, table_name, line)
    z1_observations(series_id, period, period_end, value)

plus a row in ``source_release`` recording which vintage of the release this is.
A series appears in several tables; observations are stored once per series.
"""

from __future__ import annotations

import csv
import datetime as dt
import email.utils
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import duckdb

Z1_URL = "https://www.federalreserve.gov/releases/z1/current/z1_csv_files.zip"
SOURCE_ID = "fed_z1"
MISSING = {"ND", ""}

QUARTER_END = {"Q1": (3, 31), "Q2": (6, 30), "Q3": (9, 30), "Q4": (12, 31)}


def period_end(label: str) -> dt.date:
    """'2026:Q2' -> 2026-06-30; '1946' (annual) -> 1946-12-31."""
    if ":" in label:
        year, quarter = label.split(":")
        month, day = QUARTER_END[quarter]
        return dt.date(int(year), month, day)
    return dt.date(int(label), 12, 31)


def download(raw_dir: Path) -> dt.datetime | None:
    """Fetch the current release zip into raw_dir. Returns its Last-Modified time."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(Z1_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request) as response:
        (raw_dir / "z1_csv_files.zip").write_bytes(response.read())
        last_modified = response.headers.get("Last-Modified")
    published = email.utils.parsedate_to_datetime(last_modified) if last_modified else None
    if published:
        (raw_dir / "published_at.txt").write_text(published.isoformat())
    archive(raw_dir)
    return published


def archive(raw_dir: Path) -> Path | None:
    """Keep a copy of the downloaded release under vintages/, named by its publication date.

    Each Z.1 release revises earlier quarters. Old releases cannot be downloaded later,
    so every one we see is kept, to make revisions visible in future.
    """
    published = _read_published(raw_dir)
    zip_path = raw_dir / "z1_csv_files.zip"
    if not published or not zip_path.exists():
        return None
    target = raw_dir / "vintages" / f"z1_{published:%Y-%m-%d}.zip"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(zip_path, target)
    return target


def _read_published(raw_dir: Path) -> dt.datetime | None:
    marker = raw_dir / "published_at.txt"
    return dt.datetime.fromisoformat(marker.read_text().strip()) if marker.exists() else None


def ingest(raw_dir: Path, db_path: Path) -> dict:
    """Load the downloaded zip into DuckDB, replacing any previous Z.1 data."""
    zip_path = raw_dir / "z1_csv_files.zip"
    series: dict[tuple[str, str], tuple] = {}

    with zipfile.ZipFile(zip_path) as archive, tempfile.TemporaryDirectory() as tmp:
        long_csv = Path(tmp) / "observations.csv"
        with long_csv.open("w", newline="") as out:
            writer = csv.writer(out)
            writer.writerow(["series_id", "period", "period_end", "value"])
            for name in sorted(archive.namelist()):
                if name.startswith("data_dictionary/") and name.endswith(".txt"):
                    table_id = Path(name).stem
                    text = archive.read(name).decode("latin-1")
                    for line in text.splitlines():
                        parts = line.split("\t")
                        if len(parts) < 5:
                            continue
                        series_id, description, line_no, table_name, unit = parts[:5]
                        series[(series_id, table_id)] = (
                            series_id,
                            description.strip(),
                            unit.strip(),
                            table_id,
                            table_name.strip(),
                            line_no.removeprefix("Line ").strip(),
                        )
                elif name.startswith("csv/") and name.endswith(".csv"):
                    rows = csv.reader(archive.read(name).decode("latin-1").splitlines())
                    header = next(rows)
                    for row in rows:
                        label = row[0]
                        end = period_end(label).isoformat()
                        for series_id, value in zip(header[1:], row[1:]):
                            if value not in MISSING:
                                writer.writerow([series_id, label, end, value])

        published = _read_published(raw_dir)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(db_path))
        try:
            con.execute(
                """
                CREATE OR REPLACE TABLE z1_observations AS
                SELECT DISTINCT series_id, period, period_end, value
                FROM read_csv(?, header = true, columns = {
                    'series_id': 'VARCHAR', 'period': 'VARCHAR',
                    'period_end': 'DATE', 'value': 'DOUBLE'})
                ORDER BY series_id, period_end
                """,
                [str(long_csv)],
            )
            con.execute(
                """
                CREATE OR REPLACE TABLE z1_series (
                    series_id VARCHAR, description VARCHAR, unit VARCHAR,
                    table_id VARCHAR, table_name VARCHAR, line VARCHAR)
                """
            )
            con.executemany("INSERT INTO z1_series VALUES (?, ?, ?, ?, ?, ?)", list(series.values()))
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS source_release (
                    source_id VARCHAR PRIMARY KEY, name VARCHAR, url VARCHAR,
                    published_at TIMESTAMPTZ, ingested_at TIMESTAMPTZ, latest_period VARCHAR)
                """
            )
            latest = con.execute(
                "SELECT arg_max(period, period_end) FROM z1_observations WHERE period LIKE '%:Q%'"
            ).fetchone()[0]
            con.execute("DELETE FROM source_release WHERE source_id = ?", [SOURCE_ID])
            con.execute(
                "INSERT INTO source_release VALUES (?, ?, ?, ?, now(), ?)",
                [
                    SOURCE_ID,
                    "Federal Reserve Z.1, Financial Accounts of the United States",
                    "https://www.federalreserve.gov/releases/z1/",
                    published,
                    latest,
                ],
            )
            n_obs = con.execute("SELECT count(*) FROM z1_observations").fetchone()[0]
            n_series = con.execute("SELECT count(DISTINCT series_id) FROM z1_observations").fetchone()[0]
            from fwm.economies.us import structure

            structure.build(con)
            conflicts = con.execute(
                """
                SELECT count(*) FROM (
                    SELECT series_id, period FROM z1_observations
                    GROUP BY ALL HAVING count(*) > 1)
                """
            ).fetchone()[0]
        finally:
            con.close()

    if conflicts:
        raise RuntimeError(f"{conflicts} series/period pairs have conflicting values across Z.1 tables")
    return {
        "observations": n_obs,
        "series": n_series,
        "latest_period": latest,
        "published_at": published.isoformat() if published else None,
    }
