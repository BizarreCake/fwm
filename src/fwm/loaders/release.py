"""The record of what was loaded: one row per release in `source_release` (see sources.py for the list)."""

from __future__ import annotations

import datetime as dt


def record(con, source_id: str, name: str, url: str, prepared: dt.datetime | None, latest: str) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS source_release (
            source_id VARCHAR PRIMARY KEY, name VARCHAR, url VARCHAR,
            published_at TIMESTAMPTZ, ingested_at TIMESTAMPTZ, latest_period VARCHAR)
        """
    )
    con.execute("DELETE FROM source_release WHERE source_id = ?", [source_id])
    con.execute("INSERT INTO source_release VALUES (?, ?, ?, ?, now(), ?)", [source_id, name, url, prepared, latest])


def forget(con, source_id: str) -> None:
    """Drop a release row recorded under an id that is no longer used."""
    con.execute("DELETE FROM source_release WHERE source_id = ?", [source_id])
