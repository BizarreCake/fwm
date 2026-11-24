"""Context for the euro area's accounts: interest rates, GDP, ECB announcements, and the dollar exchange rate.

The euro-area counterpart of context.py and rates.py, with the same interface. Everything comes
from the ECB's data API, one small CSV per series, and goes into the tables shared by all
economies (see contextbase.py) as economy `ea` and exchange-rate pair `USD/EUR` (dollars per euro).
"""

from __future__ import annotations

import csv
import datetime as dt
import urllib.request
from pathlib import Path

import duckdb

from fwm import contextbase, ddp, euroarea

SOURCE_URL = "https://data.ecb.europa.eu/"
# release id -> name, as recorded in source_release
RELEASES = {
    "ecb_rates": "ECB key interest rates and euro area yield curve",
    "ecb_gdp": "ECB national accounts: euro area GDP",
    "ecb_fx": "ECB euro foreign exchange reference rates: US dollar",
}
API = "https://data-api.ecb.europa.eu/service/data/{key}?detail=dataonly&format=csvdata"
EVENTS_PATH = Path(__file__).with_name("events_ea.csv")
RELEASE_URL = "https://www.ecb.europa.eu/press/pr/date/{release}"
EVENT_KINDS = {"rate": "Policy rate", "balance_sheet": "Eurosystem balance sheet", "facility": "Lending to banks"}

# id -> (ECB series, name, short name, drawn on the rates chart)
RATES = {
    "policy": ("FM/D.U2.EUR.4F.KR.DFR.LEV", "ECB deposit facility rate", "Deposit rate", True),
    "yield_3m": ("YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_3M", "3-month euro area government yield (AAA)", "3-month", False),
    "yield_2y": ("YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y", "2-year euro area government yield (AAA)", "2-year", True),
    "yield_10y": ("YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y", "10-year euro area government yield (AAA)", "10-year", True),
}
GDP_KEY = "MNA/Q.N.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.V.N"
FX_KEY = "EXR/D.USD.EUR.SP00.A"
FX_PAIR = "USD/EUR"
ECONOMY = "ea"
CENTRAL_BANK = "ECB"
CENTRAL_BANK_NAME = "European Central Bank"
EVENTS_COVERAGE = ("A hand-curated calendar of major ECB announcements from late 2008: rate turning points, asset "
                   "purchase and runoff decisions, and lending operations for banks. Not every Governing Council "
                   "meeting, and nothing from governments or other central banks.")
POLICY_NOTE = ("The ten most recent changes in the deposit facility rate, by the day each took "
               "effect (a few days after the decision was announced).")
FX_FIELD = ("usd_per_eur_at_quarter_end", False)  # name in the tool's answer, and whether to invert usd_per_unit
FILES = {**{series_id: key for series_id, (key, _, _, _) in RATES.items()}, "gdp": GDP_KEY, "fx": FX_KEY}


def download(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name, key in FILES.items():
        request = urllib.request.Request(API.format(key=key), headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv"})
        with urllib.request.urlopen(request, timeout=120) as response:
            (raw_dir / f"{name}.csv").write_bytes(response.read())


def _read(path: Path) -> list[tuple[str, float]]:
    out = []
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            try:
                out.append((row["TIME_PERIOD"], float(row["OBS_VALUE"])))
            except ValueError:
                continue  # days without a value
    return out


def ingest(raw_dir: Path, db_path: Path) -> dict:
    con = duckdb.connect(str(db_path))
    try:
        rows = {series_id: _read(raw_dir / f"{series_id}.csv") for series_id in RATES}
        contextbase.replace_rates(con, ECONOMY, {series_id: (name, short_name, key.replace("/", "."), shown)
                                                 for series_id, (key, name, short_name, shown) in RATES.items()}, rows)
        latest = max(series[-1][0] for series in rows.values())
        gdp = [(period.replace("-Q", ":Q"), value) for period, value in _read(raw_dir / "gdp.csv")]
        contextbase.replace_gdp(con, ECONOMY, gdp)
        fx = _read(raw_dir / "fx.csv")
        contextbase.replace_fx(con, FX_PAIR, fx)
        fetched = dt.datetime.fromtimestamp((raw_dir / "gdp.csv").stat().st_mtime, dt.timezone.utc)
        ddp.forget_release(con, "ecb_context")
        for release_id, period in (("ecb_rates", latest), ("ecb_gdp", gdp[-1][0]), ("ecb_fx", fx[-1][0])):
            ddp.record_release(con, release_id, RELEASES[release_id], SOURCE_URL, fetched, period)
    finally:
        con.close()
    return {"rates_latest": latest, "gdp_latest": gdp[-1][0], "fx_latest": fx[-1][0]}


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
