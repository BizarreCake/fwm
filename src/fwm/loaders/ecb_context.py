"""Download and load the euro area's rates, GDP and dollar exchange rate from the ECB's data API.

Rows go into the tables shared by all economies (economies/base.py) as economy `ea` and pair `USD/EUR`.
"""

from __future__ import annotations

import csv
import datetime as dt
import urllib.request
from pathlib import Path

import duckdb

from fwm.economies import base as contextbase
from fwm.loaders import release

SOURCE_URL = "https://data.ecb.europa.eu/"


# release id -> name, as recorded in source_release
RELEASES = {
    "ecb_rates": "ECB key interest rates and euro area yield curve",
    "ecb_gdp": "ECB national accounts: euro area GDP",
    "ecb_fx": "ECB euro foreign exchange reference rates: US dollar",
}


API = "https://data-api.ecb.europa.eu/service/data/{key}?detail=dataonly&format=csvdata"


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
        release.forget(con, "ecb_context")
        for release_id, period in (("ecb_rates", latest), ("ecb_gdp", gdp[-1][0]), ("ecb_fx", fx[-1][0])):
            release.record(con, release_id, RELEASES[release_id], SOURCE_URL, fetched, period)
    finally:
        con.close()
    return {"rates_latest": latest, "gdp_latest": gdp[-1][0], "fx_latest": fx[-1][0]}
