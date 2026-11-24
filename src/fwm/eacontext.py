"""Context for the euro area's accounts: interest rates, GDP, ECB announcements, and the dollar exchange rate.

The euro-area counterpart of context.py and rates.py, in the same shape, so that the
same charts can show it. Everything comes from the ECB's data API, one small CSV per series.

    ea_rate_series(series_id, name, short_name, source_series, shown)
    ea_rates_daily(series_id, date, value)
    ea_gdp(period, value)            -- nominal, EUR millions, per quarter, not seasonally adjusted
    fx_daily(pair, date, value)      -- 'USD/EUR': US dollars per euro, ECB reference rate
"""

from __future__ import annotations

import csv
import datetime as dt
import urllib.request
from pathlib import Path

import duckdb

from fwm import context, ddp, euroarea

SOURCE_ID = "ecb_context"
SOURCE_NAME = "ECB Data Portal: key interest rates, euro area yield curve, national accounts, reference exchange rates"
SOURCE_URL = "https://data.ecb.europa.eu/"
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
        con.execute("CREATE OR REPLACE TABLE ea_rate_series (series_id VARCHAR, name VARCHAR, short_name VARCHAR, source_series VARCHAR, shown BOOLEAN)")
        con.execute("CREATE OR REPLACE TABLE ea_rates_daily (series_id VARCHAR, date DATE, value DOUBLE)")
        con.execute("CREATE OR REPLACE TABLE ea_gdp (period VARCHAR, value DOUBLE)")
        con.execute("CREATE OR REPLACE TABLE fx_daily (pair VARCHAR, date DATE, value DOUBLE)")
        latest = None
        for series_id, (key, name, short_name, shown) in RATES.items():
            rows = _read(raw_dir / f"{series_id}.csv")
            con.execute("INSERT INTO ea_rate_series VALUES (?, ?, ?, ?, ?)", [series_id, name, short_name, key.replace("/", "."), shown])
            con.executemany("INSERT INTO ea_rates_daily VALUES (?, ?, ?)", [(series_id, date, value) for date, value in rows])
            latest = max(latest or rows[-1][0], rows[-1][0])
        gdp = [(period.replace("-Q", ":Q"), value) for period, value in _read(raw_dir / "gdp.csv")]
        con.executemany("INSERT INTO ea_gdp VALUES (?, ?)", gdp)
        fx = _read(raw_dir / "fx.csv")
        con.executemany("INSERT INTO fx_daily VALUES (?, ?, ?)", [(FX_PAIR, date, value) for date, value in fx])
        fetched = dt.datetime.fromtimestamp((raw_dir / "gdp.csv").stat().st_mtime, dt.timezone.utc)
        ddp.record_release(con, SOURCE_ID, SOURCE_NAME, SOURCE_URL, fetched, latest)
    finally:
        con.close()
    return {"rates_latest": latest, "gdp_latest": gdp[-1][0], "fx_latest": fx[-1][0]}


def available(con: duckdb.DuckDBPyConnection) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'ea_gdp'").fetchone()[0])


def load_events() -> list[dict]:
    """The curated calendar. Every entry cites the ECB press release it summarises."""
    with EVENTS_PATH.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    return [{"date": row["date"], "period": context.quarter_of(dt.date.fromisoformat(row["date"])), "kind": row["kind"],
             "title": row["title"], "detail": row["detail"], "url": RELEASE_URL.format(release=row["release"])} for row in rows]


def gdp(con: duckdb.DuckDBPyConnection, labels: list[str]) -> list[float | None]:
    """Nominal GDP over the four quarters ending in each quarter, EUR millions."""
    rows = dict(con.execute(
        "SELECT period, CASE WHEN count(*) OVER w = 4 THEN sum(value) OVER w END FROM ea_gdp "
        "WINDOW w AS (ORDER BY period ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)").fetchall())
    return [rows.get(label) for label in labels]


def fx_quarter_end(con: duckdb.DuckDBPyConnection, labels: list[str]) -> list[float | None]:
    """US dollars per euro on the last day of each quarter that has a rate."""
    rows = dict(con.execute(
        "SELECT year(date) || ':Q' || quarter(date), arg_max(value, date) FROM fx_daily WHERE pair = ? GROUP BY 1", [FX_PAIR]).fetchall())
    return [rows.get(label) for label in labels]


def policy_changes(con: duckdb.DuckDBPyConnection, last: int = 10) -> list[dict]:
    """The most recent days on which the deposit facility rate took a new value, oldest first."""
    rows = con.execute(
        "SELECT date, value, previous FROM (SELECT date, value, lag(value) OVER (ORDER BY date) AS previous "
        "FROM ea_rates_daily WHERE series_id = 'policy') WHERE previous IS NOT NULL AND value <> previous ORDER BY date").fetchall()
    return [{"effective": date.isoformat(), "rate": value, "previous_rate": previous} for date, value, previous in rows[-last:]]


def view(con: duckdb.DuckDBPyConnection) -> dict:
    labels = euroarea.periods(con)
    index = {label: i for i, label in enumerate(labels)}
    n = len(labels)
    averages: dict[str, list] = {}
    for series_id, year, quarter, value in con.execute(
            "SELECT series_id, year(date), quarter(date), avg(value) FROM ea_rates_daily GROUP BY ALL").fetchall():
        i = index.get(f"{year}:Q{quarter}")
        if i is not None:
            averages.setdefault(series_id, [None] * n)[i] = round(value, 4)
    latest = {series_id: (date, value) for series_id, date, value in con.execute(
        "SELECT series_id, max(date), arg_max(value, date) FROM ea_rates_daily GROUP BY 1").fetchall()}
    rates = [{"id": series_id, "name": name, "short_name": short_name, "source_series": source_series, "shown": shown,
              "values": averages.get(series_id, [None] * n),
              "latest": {"date": latest[series_id][0].isoformat(), "value": latest[series_id][1]}}
             for series_id, name, short_name, source_series, shown in con.execute(
                 "SELECT series_id, name, short_name, source_series, shown FROM ea_rate_series").fetchall()]
    events = [dict(event, index=index[event["period"]]) for event in load_events() if event["period"] in index]
    sources = {source_id: {"name": name, "url": url, "latest": latest_period} for source_id, name, url, latest_period in
               con.execute("SELECT source_id, name, url, latest_period FROM source_release").fetchall()}
    return {
        "economy": "ea",
        "central_bank": "ECB",
        "periods": labels,
        "rates": rates,
        "gdp": {"series": GDP_KEY.replace("/", "."), "unit": "EUR millions", "values": gdp(con, labels)},
        "fx": {"pair": FX_PAIR, "series": FX_KEY.replace("/", "."), "values": fx_quarter_end(con, labels)},
        "events": events,
        "event_kinds": EVENT_KINDS,
        "sources": sources,
        "notes": {
            "rates": "Quarterly averages of daily rates, percent per year. The deposit facility rate is the ECB's policy "
                     "rate; yields are the ECB's curve for AAA-rated euro area government bonds, from September 2004. "
                     "Source: ECB.",
            "gdp": "Share of GDP divides by the euro area's nominal GDP over the four quarters ending in that quarter "
                   "(ECB national accounts, not seasonally adjusted, summed).",
            "events": "Events are ECB announcements, dated by their press release. They are shown for reference; a marker "
                      "next to a change does not show that one caused the other.",
        },
    }
