"""Context for Japan's accounts: interest rates, GDP, Bank of Japan announcements, and the yen exchange rate.

The Japanese counterpart of context.py and eacontext.py, with the same interface.
Rates, GDP and the yen rate go into the tables shared by all economies (see contextbase.py),
as economy `jp` and exchange-rate pair `JPY/EUR` (yen per euro).

Sources: the policy rate from the BIS's central bank policy rate series; government bond
yields from the Ministry of Finance's daily table; GDP from the OECD's quarterly national
accounts; the exchange rate from the ECB. Dollars per yen is the ECB's dollar rate
divided by its yen rate for the same day.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
import urllib.request
from pathlib import Path

import duckdb

from fwm import contextbase, ddp, eacontext, japan

# release id -> (name, page), as recorded in source_release
RELEASES = {
    "jp_policy_rate": ("BIS central bank policy rates: Japan", "https://data.bis.org/topics/CBPOL"),
    "jp_yields": ("Ministry of Finance of Japan, JGB interest rates", "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm"),
    "jp_gdp": ("OECD quarterly national accounts: Japan", "https://data-explorer.oecd.org/"),
    "jp_fx": ("ECB euro foreign exchange reference rates: Japanese yen", "https://data.ecb.europa.eu/"),
}
EVENTS_PATH = Path(__file__).with_name("events_jp.csv")
RELEASE_URL = "https://www.boj.or.jp{release}"
EVENT_KINDS = {"rate": "Policy rate", "balance_sheet": "Bank of Japan balance sheet", "framework": "Policy framework"}
GDP_SERIES = "OECD QNA Q.Y.JPN.S1.B1GQ.XDC.V.N"
FILES = {
    "policy": ("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.JP?startPeriod=1997-01-01",
               "application/vnd.sdmx.data+csv;version=1.0.0"),
    "yields_history": ("https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv", "text/csv"),
    "yields_month": ("https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv", "text/csv"),
    "gdp": ("https://sdmx.oecd.org/public/rest/data/OECD.SDD.NAD,DSD_NAMAIN1@DF_QNA_EXPENDITURE_NATIO_CURR,/"
            "Q.Y.JPN.S1..B1GQ.....V..?startPeriod=1994-Q1&dimensionAtObservation=AllDimensions",
            "application/vnd.sdmx.data+csv; charset=utf-8"),
    "fx": ("https://data-api.ecb.europa.eu/service/data/EXR/D.JPY.EUR.SP00.A?detail=dataonly&format=csvdata&startPeriod=1999-01-01",
           "text/csv"),
}
FX_PAIR = "JPY/EUR"
ECONOMY = "jp"
CENTRAL_BANK = CENTRAL_BANK_NAME = "Bank of Japan"
EVENTS_COVERAGE = ("A hand-curated calendar of major Bank of Japan announcements from 2010: its easing programmes, "
                   "changes of framework and rate changes. Each is named after the Bank's release; details beyond "
                   "the release title and the recorded policy rate are not included. Not every meeting.")
POLICY_NOTE = ("The ten most recent changes in the Bank of Japan's policy rate, by the day each "
               "took effect. Where the target was a range, the rate is its midpoint.")
FX_FIELD = ("yen_per_usd_at_quarter_end", True)  # name in the tool's answer, and whether to invert usd_per_unit
# id -> (name, short name, source series, drawn on the rates chart)
RATES = {
    "policy": ("Bank of Japan policy rate (uncollateralized overnight call rate target)", "Policy rate", "BIS WS_CBPOL D.JP", True),
    "yield_2y": ("2-year Japanese government bond yield", "2-year", "MOF JGB 2Y", True),
    "yield_10y": ("10-year Japanese government bond yield", "10-year", "MOF JGB 10Y", True),
}


def download(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name, (url, accept) in FILES.items():
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": accept})
        with urllib.request.urlopen(request, timeout=300) as response:
            (raw_dir / f"{name}.csv").write_bytes(response.read())


def _sdmx(path: Path) -> list[tuple[str, float]]:
    out = []
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            try:
                out.append((row["TIME_PERIOD"], float(row["OBS_VALUE"])))
            except ValueError:
                continue
    return sorted(out)


def _yields(paths: list[Path]) -> dict[str, dict[str, float]]:
    """{maturity: {date: yield}} from the Ministry of Finance's tables, which carry notes in Japanese around the data."""
    out: dict[str, dict[str, float]] = {}
    for path in paths:
        header: list[str] = []
        for row in csv.reader(path.read_text(encoding="shift_jis", errors="replace").splitlines()):
            if row and row[0] == "Date":
                header = row
            match = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", row[0].strip()) if row else None
            if not match or not header:
                continue
            date = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
            for maturity, value in zip(header[1:], row[1:]):
                try:
                    out.setdefault(maturity, {})[date] = float(value)
                except ValueError:
                    continue  # '-' where a maturity was not issued
    return out


def ingest(raw_dir: Path, db_path: Path) -> dict:
    yields = _yields([raw_dir / "yields_history.csv", raw_dir / "yields_month.csv"])
    series = {
        "policy": _sdmx(raw_dir / "policy.csv"),
        "yield_2y": sorted(yields["2Y"].items()),
        "yield_10y": sorted(yields["10Y"].items()),
    }
    gdp = [(period.replace("-Q", ":Q"), value) for period, value in _sdmx(raw_dir / "gdp.csv")]
    fx = _sdmx(raw_dir / "fx.csv")
    if not all(series.values()) or not gdp or not fx:
        raise RuntimeError("A Japanese context download holds no values")
    con = duckdb.connect(str(db_path))
    try:
        contextbase.replace_rates(con, ECONOMY, RATES, {series_id: [row for row in rows if row[0] >= "1997-01-01"]
                                                        for series_id, rows in series.items()})
        contextbase.replace_gdp(con, ECONOMY, gdp)
        contextbase.replace_fx(con, FX_PAIR, fx)
        latest = max(rows[-1][0] for rows in series.values())
        fetched = dt.datetime.fromtimestamp((raw_dir / "gdp.csv").stat().st_mtime, dt.timezone.utc)
        ddp.forget_release(con, "jp_context")
        yields_latest = max(series["yield_2y"][-1][0], series["yield_10y"][-1][0])
        for release_id, period in (("jp_policy_rate", series["policy"][-1][0]), ("jp_yields", yields_latest),
                                   ("jp_gdp", gdp[-1][0]), ("jp_fx", fx[-1][0])):
            ddp.record_release(con, release_id, *RELEASES[release_id], fetched, period)
    finally:
        con.close()
    return {"rates_latest": latest, "gdp_latest": gdp[-1][0], "fx_latest": fx[-1][0]}


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
