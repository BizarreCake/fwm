"""Download and load Japan's policy rate (BIS), government bond yields (Ministry of Finance), GDP (OECD) and yen rate (ECB).

Rows go into the tables shared by all economies (economies/base.py) as economy `jp` and pair `JPY/EUR`.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
import urllib.request
from pathlib import Path

import duckdb

from fwm.economies import base as contextbase
from fwm.loaders import release

# release id -> (name, page), as recorded in source_release
RELEASES = {
    "jp_policy_rate": ("BIS central bank policy rates: Japan", "https://data.bis.org/topics/CBPOL"),
    "jp_yields": ("Ministry of Finance of Japan, JGB interest rates", "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm"),
    "jp_gdp": ("OECD quarterly national accounts: Japan", "https://data-explorer.oecd.org/"),
    "jp_fx": ("ECB euro foreign exchange reference rates: Japanese yen", "https://data.ecb.europa.eu/"),
}


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
        release.forget(con, "jp_context")
        yields_latest = max(series["yield_2y"][-1][0], series["yield_10y"][-1][0])
        for release_id, period in (("jp_policy_rate", series["policy"][-1][0]), ("jp_yields", yields_latest),
                                   ("jp_gdp", gdp[-1][0]), ("jp_fx", fx[-1][0])):
            release.record(con, release_id, *RELEASES[release_id], fetched, period)
    finally:
        con.close()
    return {"rates_latest": latest, "gdp_latest": gdp[-1][0], "fx_latest": fx[-1][0]}
