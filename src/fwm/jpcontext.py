"""Context for Japan's accounts: interest rates, GDP, Bank of Japan announcements, and the yen exchange rate.

The Japanese counterpart of context.py and eacontext.py, in the same shape.

    jp_rate_series(series_id, name, short_name, source_series, shown)
    jp_rates_daily(series_id, date, value)
    jp_gdp(period, value)            -- nominal, JPY millions, per quarter, seasonally adjusted
    jp_fx_daily(date, value)         -- yen per euro, ECB reference rate

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

from fwm import context, ddp, eacontext, japan

SOURCE_ID = "jp_context"
SOURCE_NAME = "BIS policy rates, Ministry of Finance JGB yields, OECD quarterly national accounts, ECB reference exchange rates"
SOURCE_URL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm"
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
        con.execute("CREATE OR REPLACE TABLE jp_rate_series (series_id VARCHAR, name VARCHAR, short_name VARCHAR, source_series VARCHAR, shown BOOLEAN)")
        con.execute("CREATE OR REPLACE TABLE jp_rates_daily (series_id VARCHAR, date DATE, value DOUBLE)")
        con.execute("CREATE OR REPLACE TABLE jp_gdp (period VARCHAR, value DOUBLE)")
        con.execute("CREATE OR REPLACE TABLE jp_fx_daily (date DATE, value DOUBLE)")
        for series_id, (name, short_name, source_series, shown) in RATES.items():
            con.execute("INSERT INTO jp_rate_series VALUES (?, ?, ?, ?, ?)", [series_id, name, short_name, source_series, shown])
            con.executemany("INSERT INTO jp_rates_daily VALUES (?, ?, ?)",
                            [(series_id, date, value) for date, value in series[series_id] if date >= "1997-01-01"])
        con.executemany("INSERT INTO jp_gdp VALUES (?, ?)", gdp)
        con.executemany("INSERT INTO jp_fx_daily VALUES (?, ?)", fx)
        latest = max(rows[-1][0] for rows in series.values())
        fetched = dt.datetime.fromtimestamp((raw_dir / "gdp.csv").stat().st_mtime, dt.timezone.utc)
        ddp.record_release(con, SOURCE_ID, SOURCE_NAME, SOURCE_URL, fetched, latest)
    finally:
        con.close()
    return {"rates_latest": latest, "gdp_latest": gdp[-1][0], "fx_latest": fx[-1][0]}


def available(con: duckdb.DuckDBPyConnection) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'jp_gdp'").fetchone()[0])


def load_events() -> list[dict]:
    """The curated calendar. Every entry cites the Bank of Japan release it is named after."""
    with EVENTS_PATH.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    return [{"date": row["date"], "period": context.quarter_of(dt.date.fromisoformat(row["date"])), "kind": row["kind"],
             "title": row["title"], "detail": row["detail"], "url": RELEASE_URL.format(release=row["release"])} for row in rows]


def gdp(con: duckdb.DuckDBPyConnection, labels: list[str]) -> list[float | None]:
    """Nominal GDP over the four quarters ending in each quarter, JPY millions."""
    rows = dict(con.execute(
        "SELECT period, CASE WHEN count(*) OVER w = 4 THEN sum(value) OVER w END FROM jp_gdp "
        "WINDOW w AS (ORDER BY period ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)").fetchall())
    return [rows.get(label) for label in labels]


def yen_per_euro_quarter_end(con: duckdb.DuckDBPyConnection, labels: list[str]) -> list[float | None]:
    rows = dict(con.execute("SELECT year(date) || ':Q' || quarter(date), arg_max(value, date) FROM jp_fx_daily GROUP BY 1").fetchall())
    return [rows.get(label) for label in labels]


def usd_per_yen_quarter_end(con: duckdb.DuckDBPyConnection, labels: list[str]) -> list[float | None]:
    """US dollars per yen at each quarter end: the ECB's dollar rate over its yen rate."""
    if not eacontext.available(con):
        return [None] * len(labels)
    dollars, yen = eacontext.fx_quarter_end(con, labels), yen_per_euro_quarter_end(con, labels)
    return [None if None in (d, y) or not y else d / y for d, y in zip(dollars, yen)]


def policy_changes(con: duckdb.DuckDBPyConnection, last: int = 10) -> list[dict]:
    """The most recent days on which the policy rate took a new value, oldest first."""
    rows = con.execute(
        "SELECT date, value, previous FROM (SELECT date, value, lag(value) OVER (ORDER BY date) AS previous "
        "FROM jp_rates_daily WHERE series_id = 'policy') WHERE previous IS NOT NULL AND value <> previous ORDER BY date").fetchall()
    return [{"effective": date.isoformat(), "rate": value, "previous_rate": previous} for date, value, previous in rows[-last:]]


def view(con: duckdb.DuckDBPyConnection) -> dict:
    labels = japan.periods(con)
    index = {label: i for i, label in enumerate(labels)}
    n = len(labels)
    averages: dict[str, list] = {}
    for series_id, year, quarter, value in con.execute(
            "SELECT series_id, year(date), quarter(date), avg(value) FROM jp_rates_daily GROUP BY ALL").fetchall():
        i = index.get(f"{year}:Q{quarter}")
        if i is not None:
            averages.setdefault(series_id, [None] * n)[i] = round(value, 4)
    latest = {series_id: (date, value) for series_id, date, value in con.execute(
        "SELECT series_id, max(date), arg_max(value, date) FROM jp_rates_daily GROUP BY 1").fetchall()}
    rates = [{"id": series_id, "name": name, "short_name": short_name, "source_series": source_series, "shown": shown,
              "values": averages.get(series_id, [None] * n),
              "latest": {"date": latest[series_id][0].isoformat(), "value": latest[series_id][1]}}
             for series_id, name, short_name, source_series, shown in con.execute(
                 "SELECT series_id, name, short_name, source_series, shown FROM jp_rate_series").fetchall()]
    events = [dict(event, index=index[event["period"]]) for event in load_events() if event["period"] in index]
    sources = {source_id: {"name": name, "url": url, "latest": latest_period} for source_id, name, url, latest_period in
               con.execute("SELECT source_id, name, url, latest_period FROM source_release").fetchall()}
    return {
        "economy": "jp",
        "central_bank": "Bank of Japan",
        "periods": labels,
        "rates": rates,
        "gdp": {"series": GDP_SERIES, "unit": "JPY millions", "values": gdp(con, labels)},
        "fx": {"pair": "USD/JPY", "series": "ECB EXR D.USD.EUR.SP00.A / EXR D.JPY.EUR.SP00.A",
               "values": usd_per_yen_quarter_end(con, labels)},
        "events": events,
        "event_kinds": EVENT_KINDS,
        "sources": sources,
        "notes": {
            "rates": "Quarterly averages of daily rates, percent per year. The policy rate is the Bank of Japan's target for "
                     "the overnight call rate as recorded by the BIS (the midpoint where the target is a range); yields are "
                     "the Ministry of Finance's daily government bond yields.",
            "gdp": "Share of GDP divides by Japan's nominal GDP over the four quarters ending in that quarter (OECD "
                   "quarterly national accounts, seasonally adjusted, summed).",
            "events": "Events are Bank of Japan announcements, each named after its release and dated by it. They are shown "
                      "for reference; a marker next to a change does not show that one caused the other.",
        },
    }
