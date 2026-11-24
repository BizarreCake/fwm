"""Context for the euro area's accounts: interest rates, GDP, ECB announcements, and the dollar exchange rate.

The euro-area counterpart of us/context.py, with the same interface. Everything comes
from the ECB's data API, one small CSV per series, and goes into the tables shared by all
economies (see economies/base.py) as economy `ea` and exchange-rate pair `USD/EUR` (dollars per euro).
"""

from __future__ import annotations

import duckdb

from fwm.economies import base as contextbase
from fwm.economies.ea import accounts as euroarea
from fwm.loaders.ecb_context import ECONOMY, FX_KEY, FX_PAIR, GDP_KEY
from fwm.paths import CURATED

EVENTS_PATH = CURATED / "events_ea.csv"
RELEASE_URL = "https://www.ecb.europa.eu/press/pr/date/{release}"
EVENT_KINDS = {"rate": "Policy rate", "balance_sheet": "Eurosystem balance sheet", "facility": "Lending to banks"}

CENTRAL_BANK = "ECB"
CENTRAL_BANK_NAME = "European Central Bank"
EVENTS_COVERAGE = ("A hand-curated calendar of major ECB announcements from late 2008: rate turning points, asset "
                   "purchase and runoff decisions, and lending operations for banks. Not every Governing Council "
                   "meeting, and nothing from governments or other central banks.")
POLICY_NOTE = ("The ten most recent changes in the deposit facility rate, by the day each took "
               "effect (a few days after the decision was announced).")
FX_FIELD = ("usd_per_eur_at_quarter_end", False)  # name in the tool's answer, and whether to invert usd_per_unit








def available(con: duckdb.DuckDBPyConnection) -> bool:
    return contextbase.has_gdp(con, ECONOMY)


def load_events() -> list[dict]:
    """The curated calendar. Every entry cites the ECB press release it summarises."""
    return contextbase.load_events(EVENTS_PATH, RELEASE_URL)


def gdp(con: duckdb.DuckDBPyConnection, labels: list[str]) -> list[float | None]:
    """Nominal GDP over the four quarters ending in each quarter, EUR millions."""
    return contextbase.gdp(con, ECONOMY, labels)


def usd_per_unit(con: duckdb.DuckDBPyConnection, labels: list[str]) -> list[float | None]:
    """US dollars per euro on the last day of each quarter that has a rate."""
    return contextbase.fx_quarter_end(con, FX_PAIR, labels)


def policy_changes(con: duckdb.DuckDBPyConnection, last: int = 10) -> list[dict]:
    """The most recent days on which the deposit facility rate took a new value, oldest first."""
    return contextbase.policy_changes(con, ECONOMY, last)


def view(con: duckdb.DuckDBPyConnection) -> dict:
    labels = euroarea.periods(con)
    return contextbase.view(
        con, economy=ECONOMY, central_bank=CENTRAL_BANK, labels=labels,
        gdp={"series": GDP_KEY.replace("/", "."), "unit": "EUR millions", "values": gdp(con, labels)},
        fx={"pair": FX_PAIR, "series": FX_KEY.replace("/", "."), "values": usd_per_unit(con, labels)},
        events=load_events(), event_kinds=EVENT_KINDS,
        notes={
            "source": "ECB: key interest rates, euro area AAA government yield curve, national accounts series "
                      + GDP_KEY.replace("/", ".") + ", reference exchange rate",
            "rates": "Quarterly averages of daily rates, percent per year. The deposit facility rate is the ECB's policy "
                     "rate; yields are the ECB's curve for AAA-rated euro area government bonds, from September 2004. "
                     "Source: ECB.",
            "gdp": "Share of GDP divides by the euro area's nominal GDP over the four quarters ending in that quarter "
                   "(ECB national accounts, not seasonally adjusted, summed).",
            "events": "Events are ECB announcements, dated by their press release. They are shown for reference; a marker "
                      "next to a change does not show that one caused the other.",
        })
