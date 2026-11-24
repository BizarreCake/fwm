"""Download and load positions between countries: IMF portfolio investment positions and BIS locational banking statistics.

    xb_positions(kind, denom, period, reporter, counterpart, value)      -- USD millions

`reporter` is an ISO two-letter code (or 5A, all BIS reporting countries); `counterpart` keeps the source's own code:
three letters in IMF rows, two in BIS rows. Every country in the code table is kept as a reporter.
"""

from __future__ import annotations

import datetime as dt
import urllib.request
from pathlib import Path

import duckdb

from fwm.codes import load_codes
from fwm.loaders import release

# release id -> (name, page, the kinds it covers), as recorded in source_release
RELEASES = {
    "imf_pip": ("IMF, Portfolio Investment Positions by Counterpart Economy", "https://data.imf.org/en/datasets/IMF.STA:PIP", ("equity", "debt")),
    "bis_lbs": ("BIS, Locational Banking Statistics", "https://data.bis.org/topics/LBS", ("bank_claims", "bank_liabilities")),
}


IMF_API = ("https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA/PIP/+/"
           "*.A.{indicator}.S1.S1.*.S?c%5BTIME_PERIOD%5D=ge:2001")


BIS_API = ("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_LBS_D_PUB/1.0/"
           "Q.S.{position}.A.TO1+USD+EUR.A.5J.A..A..N?startPeriod=1999-Q1")


BIS_ACCEPT = "application/vnd.sdmx.data+csv;version=1.0.0"


# kind -> source, file, name, what a row is, what a column is, and the sentence for one cell.
KINDS = (
    ("equity", "imf", "P_F51_P_USD", "Equity & fund shares", "Held by residents of", "Issued in",
     "Residents of {holder} hold {amount} of equity and fund shares issued in {issuer}"),
    ("debt", "imf", "P_F3_P_USD", "Debt securities", "Held by residents of", "Issued in",
     "Residents of {holder} hold {amount} of debt securities issued in {issuer}"),
    ("bank_claims", "bis", "C", "Bank claims", "Banks located in", "Claims on residents of",
     "Banks located in {holder} have {amount} of claims on residents of {issuer}"),
    ("bank_liabilities", "bis", "L", "Bank liabilities", "Banks located in", "Owe to residents of",
     "Banks located in {holder} owe {amount} to residents of {issuer}"),
)


def _file(kind_id: str) -> str:
    return f"{kind_id}.csv"


def download(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for kind_id, source, code, *_ in KINDS:
        url = IMF_API.format(indicator=code) if source == "imf" else BIS_API.format(position=code)
        accept = "text/csv" if source == "imf" else BIS_ACCEPT
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": accept})
        with urllib.request.urlopen(request, timeout=600) as response, (raw_dir / _file(kind_id)).open("wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)


def ingest(raw_dir: Path, db_path: Path) -> dict:
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE OR REPLACE TABLE xb_positions (kind VARCHAR, denom VARCHAR, period VARCHAR, reporter VARCHAR, "
                    "counterpart VARCHAR, value DOUBLE)")
        con.execute("CREATE OR REPLACE TEMP TABLE xb_codes (iso2 VARCHAR, iso3 VARCHAR)")
        con.executemany("INSERT INTO xb_codes VALUES (?, ?)", [(row["iso2"], row["iso3"]) for row in load_codes()])
        for kind_id, source, *_ in KINDS:
            path = str(raw_dir / _file(kind_id))
            if source == "imf":
                # Positions are in US dollars. 2025-S1 is the end of June, 2025-S2 the end of December.
                con.execute(
                    "INSERT INTO xb_positions SELECT ?, 'all', "
                    "substr(TIME_PERIOD, 1, 4) || CASE WHEN TIME_PERIOD LIKE '%S1' THEN ':Q2' ELSE ':Q4' END, "
                    "c.iso2, COUNTERPART_COUNTRY, CAST(OBS_VALUE AS DOUBLE) / 1e6 "
                    "FROM read_csv(?, all_varchar = true) JOIN xb_codes c ON c.iso3 = COUNTRY "
                    "WHERE FREQUENCY = 'S' AND OBS_VALUE IS NOT NULL AND OBS_VALUE <> ''", [kind_id, path])
            else:
                con.execute(
                    "INSERT INTO xb_positions SELECT ?, CASE L_DENOM WHEN 'TO1' THEN 'all' WHEN 'USD' THEN 'usd' ELSE 'eur' END, "
                    "replace(TIME_PERIOD, '-', ':'), L_REP_CTY, L_CP_COUNTRY, CAST(OBS_VALUE AS DOUBLE) "
                    "FROM read_csv(?, all_varchar = true) "
                    "WHERE (L_REP_CTY = '5A' OR L_REP_CTY IN (SELECT iso2 FROM xb_codes)) AND OBS_VALUE IS NOT NULL AND OBS_VALUE NOT IN ('', 'NaN')", [kind_id, path])
        con.execute("DELETE FROM xb_positions WHERE isnan(value)")
        rows, latest = con.execute("SELECT count(*), max(period) FROM xb_positions").fetchone()
        if not rows:
            raise RuntimeError("Cross-border downloads hold no values")
        fetched = dt.datetime.fromtimestamp((raw_dir / _file("equity")).stat().st_mtime, dt.timezone.utc)
        by_kind = dict(con.execute("SELECT kind, max(period) FROM xb_positions GROUP BY kind").fetchall())
        release.forget(con, "links")
        for release_id, (name, url, kind_ids) in RELEASES.items():
            release.record(con, release_id, name, url, fetched, max(by_kind[kind_id] for kind_id in kind_ids))
    finally:
        con.close()
    return {"observations": rows, "latest": by_kind}
