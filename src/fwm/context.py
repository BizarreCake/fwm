"""Context for the accounts: interest rates, GDP, and dated policy events.

None of this explains a flow on its own. It lets a reader line up what a sector
did with what rates were doing and what the Federal Reserve had announced.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import duckdb

from fwm.structure import START

EVENTS_PATH = Path(__file__).with_name("events.csv")
RELEASE_URL = "https://www.federalreserve.gov/newsevents/pressreleases/{release}.htm"
GDP_SERIES = "FU086902005.Q"  # GDP, quarterly, not annualised, not seasonally adjusted
EVENT_KINDS = {"rate": "Policy rate", "balance_sheet": "Fed balance sheet", "facility": "Lending facility"}


def quarter_of(date: dt.date) -> str:
    return f"{date.year}:Q{(date.month - 1) // 3 + 1}"


def load_events() -> list[dict]:
    """The curated calendar. Every entry cites the Federal Reserve press release it summarises."""
    with EVENTS_PATH.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    return [
        {
            "date": row["date"],
            "period": quarter_of(dt.date.fromisoformat(row["date"])),
            "kind": row["kind"],
            "title": row["title"],
            "detail": row["detail"],
            "url": RELEASE_URL.format(release=row["release"]),
        }
        for row in rows
    ]


def periods(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [row[0] for row in con.execute(
        "SELECT DISTINCT period, period_end FROM z1_observations "
        "WHERE period LIKE '%:Q%' AND period_end >= CAST(? AS DATE) ORDER BY period_end", [START]
    ).fetchall()]


def gdp(con: duckdb.DuckDBPyConnection, labels: list[str]) -> list[float | None]:
    """Nominal GDP over the four quarters ending in each quarter, USD millions."""
    rows = dict(con.execute(
        """
        SELECT period, CASE WHEN count(*) OVER w = 4 THEN sum(value) OVER w END
        FROM z1_observations WHERE series_id = ?
        WINDOW w AS (ORDER BY period_end ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)
        """,
        [GDP_SERIES],
    ).fetchall())
    return [rows.get(label) for label in labels]


def view(con: duckdb.DuckDBPyConnection) -> dict:
    labels = periods(con)
    index = {label: i for i, label in enumerate(labels)}
    n = len(labels)

    rates = []
    has_rates = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'rates_daily'"
    ).fetchone()[0]
    if has_rates:
        averages: dict[str, list] = {}
        for series_id, year, quarter, value in con.execute(
            "SELECT series_id, year(date), quarter(date), avg(value) FROM rates_daily GROUP BY ALL"
        ).fetchall():
            i = index.get(f"{year}:Q{quarter}")
            if i is not None:
                averages.setdefault(series_id, [None] * n)[i] = round(value, 4)
        latest = {series_id: (date, value) for series_id, date, value in con.execute(
            "SELECT series_id, max(date), arg_max(value, date) FROM rates_daily GROUP BY 1"
        ).fetchall()}
        for series_id, name, short_name, source_series in con.execute(
            "SELECT series_id, name, short_name, source_series FROM rate_series"
        ).fetchall():
            rates.append({
                "id": series_id,
                "name": name,
                "short_name": short_name,
                "source_series": source_series,
                "values": averages.get(series_id, [None] * n),
                "latest": {"date": latest[series_id][0].isoformat(), "value": latest[series_id][1]},
            })

    events = [dict(event, index=index[event["period"]]) for event in load_events() if event["period"] in index]
    sources = {source_id: {"name": name, "url": url, "latest": latest_period} for source_id, name, url, latest_period in
               con.execute("SELECT source_id, name, url, latest_period FROM source_release").fetchall()}
    return {
        "periods": labels,
        "rates": rates,
        "gdp": {"series": GDP_SERIES, "unit": "USD millions", "values": gdp(con, labels)},
        "events": events,
        "event_kinds": EVENT_KINDS,
        "sources": sources,
        "notes": {
            "rates": "Quarterly averages of daily rates, percent per year. Source: Federal Reserve H.15.",
            "gdp": "Share of GDP divides by nominal GDP over the four quarters ending in that quarter (Z.1 series "
                   f"{GDP_SERIES}, summed).",
            "events": "Events are Federal Reserve announcements, dated by their press release. They are shown for "
                      "reference; a marker next to a change does not show that one caused the other.",
        },
    }
