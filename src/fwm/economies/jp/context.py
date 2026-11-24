"""Context for Japan's accounts: interest rates, GDP, Bank of Japan announcements, and the yen exchange rate.

The Japanese counterpart of us/context.py and ea/context.py, with the same interface.
Rates, GDP and the yen rate go into the tables shared by all economies (see economies/base.py),
as economy `jp` and exchange-rate pair `JPY/EUR` (yen per euro).

Sources: the policy rate from the BIS's central bank policy rate series; government bond
yields from the Ministry of Finance's daily table; GDP from the OECD's quarterly national
accounts; the exchange rate from the ECB. Dollars per yen is the ECB's dollar rate
divided by its yen rate for the same day.
"""

from __future__ import annotations

import duckdb

from fwm.economies import base as contextbase
from fwm.economies.ea import context as eacontext
from fwm.economies.jp import accounts as japan
from fwm.loaders.jp_context import ECONOMY, FX_PAIR
from fwm.paths import CURATED

EVENTS_PATH = CURATED / "events_jp.csv"
RELEASE_URL = "https://www.boj.or.jp{release}"
EVENT_KINDS = {"rate": "Policy rate", "balance_sheet": "Bank of Japan balance sheet", "framework": "Policy framework"}
GDP_SERIES = "OECD QNA Q.Y.JPN.S1.B1GQ.XDC.V.N"
CENTRAL_BANK = CENTRAL_BANK_NAME = "Bank of Japan"
EVENTS_COVERAGE = ("A hand-curated calendar of major Bank of Japan announcements from 2010: its easing programmes, "
                   "changes of framework and rate changes. Each is named after the Bank's release; details beyond "
                   "the release title and the recorded policy rate are not included. Not every meeting.")
POLICY_NOTE = ("The ten most recent changes in the Bank of Japan's policy rate, by the day each "
               "took effect. Where the target was a range, the rate is its midpoint.")
FX_FIELD = ("yen_per_usd_at_quarter_end", True)  # name in the tool's answer, and whether to invert usd_per_unit










def available(con: duckdb.DuckDBPyConnection) -> bool:
    return contextbase.has_gdp(con, ECONOMY)


def load_events() -> list[dict]:
    """The curated calendar. Every entry cites the Bank of Japan release it is named after."""
    return contextbase.load_events(EVENTS_PATH, RELEASE_URL)


def gdp(con: duckdb.DuckDBPyConnection, labels: list[str]) -> list[float | None]:
    """Nominal GDP over the four quarters ending in each quarter, JPY millions."""
    return contextbase.gdp(con, ECONOMY, labels)


def usd_per_unit(con: duckdb.DuckDBPyConnection, labels: list[str]) -> list[float | None]:
    """US dollars per yen at each quarter end: the ECB's dollar rate over its yen rate."""
    dollars = contextbase.fx_quarter_end(con, eacontext.FX_PAIR, labels)
    yen = contextbase.fx_quarter_end(con, FX_PAIR, labels)
    return [None if None in (d, y) or not y else d / y for d, y in zip(dollars, yen)]


def policy_changes(con: duckdb.DuckDBPyConnection, last: int = 10) -> list[dict]:
    """The most recent days on which the policy rate took a new value, oldest first."""
    return contextbase.policy_changes(con, ECONOMY, last)


def view(con: duckdb.DuckDBPyConnection) -> dict:
    labels = japan.periods(con)
    return contextbase.view(
        con, economy=ECONOMY, central_bank=CENTRAL_BANK, labels=labels,
        gdp={"series": GDP_SERIES, "unit": "JPY millions", "values": gdp(con, labels)},
        fx={"pair": "USD/JPY", "series": "ECB EXR D.USD.EUR.SP00.A / EXR D.JPY.EUR.SP00.A", "values": usd_per_unit(con, labels)},
        events=load_events(), event_kinds=EVENT_KINDS,
        notes={
            "source": "BIS policy rate series; Ministry of Finance JGB yields; " + GDP_SERIES + " (GDP); ECB reference rates",
            "rates": "Quarterly averages of daily rates, percent per year. The policy rate is the Bank of Japan's target for "
                     "the overnight call rate as recorded by the BIS (the midpoint where the target is a range); yields are "
                     "the Ministry of Finance's daily government bond yields.",
            "gdp": "Share of GDP divides by Japan's nominal GDP over the four quarters ending in that quarter (OECD "
                   "quarterly national accounts, seasonally adjusted, summed).",
            "events": "Events are Bank of Japan announcements, each named after its release and dated by it. They are shown "
                      "for reference; a marker next to a change does not show that one caused the other.",
        })
