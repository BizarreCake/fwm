"""What the three context modules share: interest rates, GDP and exchange rates for every economy.

    rate_series(economy, series_id, name, short_name, source_series, shown)
    rates_daily(economy, series_id, date, value)      -- percent per year
    gdp_quarterly(economy, period, value)             -- nominal GDP per quarter, millions of the economy's currency
    fx_daily(pair, date, value)                       -- ECB reference rates: units of the first currency per euro

Each economy's loader replaces its own rows and leaves the others'. US GDP is not here:
it is read from the Z.1 accounts. context.py, eacontext.py and jpcontext.py say where each
economy's figures come from and give them through one interface (see economies.context).
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import duckdb

OLD_TABLES = ("ea_rate_series", "ea_rates_daily", "ea_gdp", "jp_rate_series", "jp_rates_daily", "jp_gdp", "jp_fx_daily")


def ensure(con: duckdb.DuckDBPyConnection) -> None:
    """Create the shared tables, and drop the per-economy tables that came before them."""
    columns = [row[0] for row in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'rates_daily'").fetchall()]
    if columns and "economy" not in columns:
        con.execute("DROP TABLE rates_daily")
        con.execute("DROP TABLE IF EXISTS rate_series")
    for table in OLD_TABLES:
        con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute("CREATE TABLE IF NOT EXISTS rate_series (economy VARCHAR, series_id VARCHAR, name VARCHAR, short_name VARCHAR, "
                "source_series VARCHAR, shown BOOLEAN)")
    con.execute("CREATE TABLE IF NOT EXISTS rates_daily (economy VARCHAR, series_id VARCHAR, date DATE, value DOUBLE)")
    con.execute("CREATE TABLE IF NOT EXISTS gdp_quarterly (economy VARCHAR, period VARCHAR, value DOUBLE)")
    con.execute("CREATE TABLE IF NOT EXISTS fx_daily (pair VARCHAR, date DATE, value DOUBLE)")


def replace_rates(con: duckdb.DuckDBPyConnection, economy: str, series: dict[str, tuple[str, str, str, bool]],
                  rows: dict[str, list[tuple]]) -> None:
    """series: id -> (name, short name, the source's own series, drawn on the rates chart); rows: id -> (date, value)."""
    ensure(con)
    con.execute("DELETE FROM rate_series WHERE economy = ?", [economy])
    con.execute("DELETE FROM rates_daily WHERE economy = ?", [economy])
    for series_id, (name, short_name, source_series, shown) in series.items():
        con.execute("INSERT INTO rate_series VALUES (?, ?, ?, ?, ?, ?)", [economy, series_id, name, short_name, source_series, shown])
        con.executemany("INSERT INTO rates_daily VALUES (?, ?, ?, ?)", [(economy, series_id, date, value) for date, value in rows[series_id]])


def replace_gdp(con: duckdb.DuckDBPyConnection, economy: str, rows: list[tuple[str, float]]) -> None:
    ensure(con)
    con.execute("DELETE FROM gdp_quarterly WHERE economy = ?", [economy])
    con.executemany("INSERT INTO gdp_quarterly VALUES (?, ?, ?)", [(economy, period, value) for period, value in rows])


def replace_fx(con: duckdb.DuckDBPyConnection, pair: str, rows: list[tuple[str, float]]) -> None:
    ensure(con)
    con.execute("DELETE FROM fx_daily WHERE pair = ?", [pair])
    con.executemany("INSERT INTO fx_daily VALUES (?, ?, ?)", [(pair, date, value) for date, value in rows])


def has_rates(con: duckdb.DuckDBPyConnection, economy: str) -> bool:
    columns = [row[0] for row in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'rates_daily'").fetchall()]
    return "economy" in columns and bool(con.execute("SELECT count(*) FROM rates_daily WHERE economy = ?", [economy]).fetchone()[0])


def has_gdp(con: duckdb.DuckDBPyConnection, economy: str) -> bool:
    exists = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'gdp_quarterly'").fetchone()[0]
    return bool(exists) and bool(con.execute("SELECT count(*) FROM gdp_quarterly WHERE economy = ?", [economy]).fetchone()[0])


def quarter_of(date: dt.date) -> str:
    return f"{date.year}:Q{(date.month - 1) // 3 + 1}"


def load_events(path: Path, release_url: str) -> list[dict]:
    """A curated calendar of announcements. Every entry cites the release it is taken from."""
    with path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    return [{"date": row["date"], "period": quarter_of(dt.date.fromisoformat(row["date"])), "kind": row["kind"],
             "title": row["title"], "detail": row["detail"], "url": release_url.format(release=row["release"])} for row in rows]


def gdp(con: duckdb.DuckDBPyConnection, economy: str, labels: list[str]) -> list[float | None]:
    """Nominal GDP over the four quarters ending in each quarter, in millions of the economy's currency."""
    rows = dict(con.execute(
        "SELECT period, CASE WHEN count(*) OVER w = 4 THEN sum(value) OVER w END FROM gdp_quarterly WHERE economy = ? "
        "WINDOW w AS (ORDER BY period ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)", [economy]).fetchall())
    return [rows.get(label) for label in labels]


def fx_quarter_end(con: duckdb.DuckDBPyConnection, pair: str, labels: list[str]) -> list[float | None]:
    """The rate on the last day of each quarter that has one."""
    exists = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'fx_daily'").fetchone()[0]
    rows = dict(con.execute(
        "SELECT year(date) || ':Q' || quarter(date), arg_max(value, date) FROM fx_daily WHERE pair = ? GROUP BY 1", [pair]).fetchall()) if exists else {}
    return [rows.get(label) for label in labels]


def policy_changes(con: duckdb.DuckDBPyConnection, economy: str, last: int = 10) -> list[dict]:
    """The most recent days on which the series called `policy` took a new value, oldest first."""
    rows = con.execute(
        "SELECT date, value, previous FROM (SELECT date, value, lag(value) OVER (ORDER BY date) AS previous "
        "FROM rates_daily WHERE economy = ? AND series_id = 'policy') WHERE previous IS NOT NULL AND value <> previous ORDER BY date",
        [economy]).fetchall()
    return [{"effective": date.isoformat(), "rate": value, "previous_rate": previous} for date, value, previous in rows[-last:]]


def rates(con: duckdb.DuckDBPyConnection, economy: str, labels: list[str]) -> list[dict]:
    """Each rate as quarterly averages on the given quarters, with its latest daily value."""
    if not has_rates(con, economy):
        return []
    index = {label: i for i, label in enumerate(labels)}
    n = len(labels)
    averages: dict[str, list] = {}
    for series_id, year, quarter, value in con.execute(
            "SELECT series_id, year(date), quarter(date), avg(value) FROM rates_daily WHERE economy = ? GROUP BY ALL", [economy]).fetchall():
        i = index.get(f"{year}:Q{quarter}")
        if i is not None:
            averages.setdefault(series_id, [None] * n)[i] = round(value, 4)
    latest = {series_id: (date, value) for series_id, date, value in con.execute(
        "SELECT series_id, max(date), arg_max(value, date) FROM rates_daily WHERE economy = ? GROUP BY 1", [economy]).fetchall()}
    return [{"id": series_id, "name": name, "short_name": short_name, "source_series": source_series, "shown": shown,
             "values": averages.get(series_id, [None] * n),
             "latest": {"date": latest[series_id][0].isoformat(), "value": latest[series_id][1]}}
            for series_id, name, short_name, source_series, shown in con.execute(
                "SELECT series_id, name, short_name, source_series, shown FROM rate_series WHERE economy = ?", [economy]).fetchall()]


def view(con: duckdb.DuckDBPyConnection, *, economy: str, central_bank: str, labels: list[str], gdp: dict, events: list[dict],
         event_kinds: dict, notes: dict, fx: dict | None = None) -> dict:
    """The context of one economy on its own quarters, in the shape the pages and tools read."""
    index = {label: i for i, label in enumerate(labels)}
    sources = {source_id: {"name": name, "url": url, "latest": latest_period} for source_id, name, url, latest_period in
               con.execute("SELECT source_id, name, url, latest_period FROM source_release").fetchall()}
    return {
        "economy": economy,
        "central_bank": central_bank,
        "periods": labels,
        "rates": rates(con, economy, labels),
        "gdp": gdp,
        **({"fx": fx} if fx else {}),
        "events": [dict(event, index=index[event["period"]]) for event in events if event["period"] in index],
        "event_kinds": event_kinds,
        "sources": sources,
        "notes": notes,
    }
