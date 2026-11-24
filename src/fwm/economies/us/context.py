"""Context for the accounts: interest rates, GDP, and dated policy events.

None of this explains a flow on its own. It lets a reader line up what a sector
did with what rates were doing and what the Federal Reserve had announced.
"""

from __future__ import annotations

import duckdb

from fwm.economies import base as contextbase
from fwm.economies.base import quarter_of  # noqa: F401  (used across the project under this name)
from fwm.economies.us.structure import START
from fwm.paths import CURATED

EVENTS_PATH = CURATED / "events.csv"
RELEASE_URL = "https://www.federalreserve.gov/newsevents/pressreleases/{release}.htm"
GDP_SERIES = "FU086902005.Q"  # GDP, quarterly, not annualised, not seasonally adjusted
EVENT_KINDS = {"rate": "Policy rate", "balance_sheet": "Fed balance sheet", "facility": "Lending facility"}


ECONOMY = "us"
CENTRAL_BANK = "Fed"
CENTRAL_BANK_NAME = "Federal Reserve"
EVENTS_COVERAGE = None  # the tool describes the Fed calendar itself
POLICY_NOTE = None
FX_FIELD = None  # amounts are already in US dollars


def available(con: duckdb.DuckDBPyConnection) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'z1_observations'").fetchone()[0])


def load_events() -> list[dict]:
    """The curated calendar. Every entry cites the Federal Reserve press release it summarises."""
    return contextbase.load_events(EVENTS_PATH, RELEASE_URL)


def policy_changes(con: duckdb.DuckDBPyConnection, last: int = 10) -> list[dict]:
    """None: the fed funds rate loaded is the daily effective rate, not the target, so it has no clean change dates."""
    return []


def usd_per_unit(con: duckdb.DuckDBPyConnection, labels: list[str]) -> list[float | None]:
    return [1.0] * len(labels)


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
    return contextbase.view(
        con, economy=ECONOMY, central_bank=CENTRAL_BANK, labels=labels,
        gdp={"series": GDP_SERIES, "unit": "USD millions", "values": gdp(con, labels)},
        events=load_events(), event_kinds=EVENT_KINDS,
        notes={
            "source": "Federal Reserve H.15 (rates); Z.1 series " + GDP_SERIES + " (GDP)",
            "rates": "Quarterly averages of daily rates, percent per year. Source: Federal Reserve H.15.",
            "gdp": "Share of GDP divides by nominal GDP over the four quarters ending in that quarter (Z.1 series "
                   f"{GDP_SERIES}, summed).",
            "events": "Events are Federal Reserve announcements, dated by their press release. They are shown for "
                      "reference; a marker next to a change does not show that one caused the other.",
        })
