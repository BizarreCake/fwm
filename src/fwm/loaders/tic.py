"""Download and load the Treasury's TIC SLT tables: securities holdings by country, monthly.

    tic_country(source, code, name, kind, region, position)
    tic_holdings(asset, code, month, ...)      -- USD millions
"""

from __future__ import annotations

import csv
import datetime as dt
import shutil
import urllib.request
from pathlib import Path

import duckdb

from fwm.loaders import release

SOURCE_URL = "https://home.treasury.gov/data/treasury-international-capital-tic-system"


FILES = "https://ticdata.treasury.gov/resource-center/data-chart-center/tic/Documents/"


# source id -> (file, release name)
SOURCES = {
    "slt3": ("slt_table3.txt", "US Treasury, TIC SLT Table 3: Treasury securities held by foreign residents"),
    "slt1": ("slt_table1.txt", "US Treasury, TIC SLT Table 1: US long-term securities held by foreign residents"),
    "slt2": ("slt_table2.txt", "US Treasury, TIC SLT Table 2: foreign long-term securities held by US residents"),
}


# asset id -> what it is, which file and columns hold it, and the nearest instrument in the quarterly accounts.
ASSETS = {
    "treasuries": {
        "name": "Treasury securities", "source": "slt3", "instrument": "F3_2", "bills": True,
        "columns": {"total": "for_treas_pos", "total_net": "for_treas_net", "long_term": "for_lt_treas_pos",
                    "long_term_net": "for_lt_treas_net", "long_term_valuation": "for_lt_treas_valchg",
                    "short_term": "for_st_treas_pos", "short_term_net": "for_st_treas_net"},
        "scope": "Bills, notes and bonds.",
        "quarterly": "Z.1 takes its rest-of-the-world Treasury holdings from these reports, so the two totals agree at quarter ends.",
    },
    "agency": {
        "name": "Agency bonds", "source": "slt1", "instrument": "F3_3", "bills": False,
        "columns": {"total": "for_lt_agcy_pos", "total_net": "for_lt_agcy_net", "long_term_valuation": "for_lt_agcy_valchg"},
        "scope": "Long-term debt and mortgage-backed securities of US government agencies and sponsored enterprises "
                 "(original maturity over one year).",
        "quarterly": "Z.1's figure also counts short-term agency paper, so it is slightly larger.",
    },
    "corporate": {
        "name": "Corporate and other bonds", "source": "slt1", "instrument": "F3_5", "bills": False,
        "columns": {"total": "for_lt_corp_pos", "total_net": "for_lt_corp_net", "long_term_valuation": "for_lt_corp_valchg"},
        "scope": "Long-term bonds of US companies and other US issuers that are not the Treasury or an agency.",
        "quarterly": "Z.1's corporate and foreign bonds line is defined differently, so the totals are close but not equal.",
    },
    "equities": {
        "name": "Equities", "source": "slt1", "instrument": "F51_1", "bills": False,
        "columns": {"total": "for_lt_eqty_pos", "total_net": "for_lt_eqty_net", "long_term_valuation": "for_lt_eqty_valchg"},
        "scope": "US company shares and shares in US investment funds.",
        "quarterly": "This is larger than Z.1's corporate equities, which leaves out fund shares.",
    },
}


ASSETS.update({
    "us_foreign_government_bonds": {
        "name": "Foreign government bonds", "source": "slt2", "instrument": None, "bills": False, "direction": "outward",
        "columns": {"total": "us_lt_govt_bond_pos", "total_net": "us_lt_govt_bond_net", "long_term_valuation": "us_lt_govt_bond_valchg"},
        "scope": "Long-term bonds of foreign governments held by US residents.", "quarterly": "",
    },
    "us_foreign_corporate_bonds": {
        "name": "Foreign corporate bonds", "source": "slt2", "instrument": None, "bills": False, "direction": "outward",
        "columns": {"total": "us_lt_corp_bond_pos", "total_net": "us_lt_corp_bond_net", "long_term_valuation": "us_lt_corp_bond_valchg"},
        "scope": "Long-term bonds of foreign companies and other non-government issuers held by US residents.", "quarterly": "",
    },
    "us_foreign_equities": {
        "name": "Foreign equities", "source": "slt2", "instrument": None, "bills": False, "direction": "outward",
        "columns": {"total": "us_lt_eqty_pos", "total_net": "us_lt_eqty_net", "long_term_valuation": "us_lt_eqty_valchg"},
        "scope": "Shares of foreign companies and foreign investment funds held by US residents.", "quarterly": "",
    },
})
# US securities held by foreigners (inward) and foreign securities held by US residents (outward).
INWARD = [asset for asset, spec in ASSETS.items() if spec.get("direction") != "outward"]
OUTWARD = [asset for asset, spec in ASSETS.items() if spec.get("direction") == "outward"]

OFFICIAL, PRIVATE = "99990", "99991"
GRAND_TOTAL = "99996"


ALL_COUNTRIES = "69995"


ORGANIZATIONS = "79995"


# Region total rows, in the file's order. Each closes the block of countries above it.
REGIONS = {
    "19992": ("europe", "Europe"),
    "29998": ("canada", "Canada"),
    "39942": ("latin_america", "Latin America"),
    "34401": ("caribbean", "Caribbean"),
    "49999": ("asia", "Asia"),
    "59994": ("africa", "Africa"),
    "69906": ("oceania", "Australia and New Zealand"),
}


MEMO = {"16713": "Euro area", "16721": "European Union"}


OTHER_KINDS = {
    GRAND_TOTAL: "total", ALL_COUNTRIES: "total", ORGANIZATIONS: "organizations",
    "72907": "memo", "76929": "memo", OFFICIAL: "split", PRIVATE: "split",
}


COLUMNS = ("total", "total_net", "long_term", "long_term_net", "long_term_valuation", "short_term", "short_term_net")


def download(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for file_name, _ in SOURCES.values():
        request = urllib.request.Request(FILES + file_name, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request) as response:
            (raw_dir / file_name).write_bytes(response.read())


def _number(text: str) -> float | None:
    text = text.strip().replace(",", "")
    if text in ("", "n.a."):
        return None
    return float(text)


def parse(path: Path, source: str) -> tuple[list[dict], list[tuple]]:
    """Countries (in file order, each with its kind and region) and one row of figures per asset, country and month."""
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    header_at = next(i for i, row in enumerate(rows) if row and row[0] == "country")
    header = [cell.strip() for cell in rows[header_at]]
    if header[:3] != ["country", "country_code", "date"]:
        raise RuntimeError(f"{path.name} has unexpected columns: {header[:3]}")
    assets = {asset: spec for asset, spec in ASSETS.items() if spec["source"] == source}
    missing = sorted({name for spec in assets.values() for name in spec["columns"].values()} - set(header))
    if missing:
        raise RuntimeError(f"{path.name} lacks columns {missing}")

    order: list[str] = []
    names: dict[str, str] = {}
    figures = []
    for row in rows[header_at + 1:]:
        if len(row) < len(header) or len(row[2]) != 7 or row[2][4] != "-":
            continue
        code, name = row[1].strip(), row[0].strip()
        if name.startswith("Of Which:") and code not in (OFFICIAL, PRIVATE):
            continue  # breakdowns by type of issuer, not by holder
        if code not in names:
            names[code] = name
            order.append(code)
        year, month = row[2].split("-")
        cells = dict(zip(header, row))
        for asset, spec in assets.items():
            value = {key: _number(cells[column]) for key, column in spec["columns"].items()}
            if not spec["bills"]:
                # A table of long-term securities: the whole position is long-term.
                value.update(long_term=value["total"], long_term_net=value["total_net"], short_term=None, short_term_net=None)
            figures.append((asset, code, dt.date(int(year), int(month), 1), *[value[column] for column in COLUMNS]))

    countries = []
    block: list[dict] = []
    for code in order:
        if code in REGIONS:
            region_id, region_name = REGIONS[code]
            for country in block:
                country["region"] = region_id
            block = []
            countries.append({"code": code, "name": region_name, "kind": "region", "region": region_id})
        elif code in MEMO:
            countries.append({"code": code, "name": MEMO[code], "kind": "memo", "region": None})
        elif code in OTHER_KINDS:
            countries.append({"code": code, "name": names[code], "kind": OTHER_KINDS[code], "region": None})
        else:
            country = {"code": code, "name": names[code], "kind": "country", "region": None}
            block.append(country)
            countries.append(country)
    if block:
        raise RuntimeError(f"{path.name}: countries outside any region: {[c['name'] for c in block]}")
    # Table 2 has no split of holders into official and private: its holders are US residents.
    splits = () if source == "slt2" else (OFFICIAL, PRIVATE)
    absent = [code for code in (*REGIONS, GRAND_TOTAL, ALL_COUNTRIES, ORGANIZATIONS, *splits) if code not in names]
    if absent:
        raise RuntimeError(f"{path.name} lacks expected total rows: {absent}")
    return countries, figures


def ingest(raw_dir: Path, db_path: Path) -> dict:
    parsed = {}
    for source, (file_name, _) in SOURCES.items():
        path = raw_dir / file_name
        countries, figures = parse(path, source)
        latest = max(row[2] for row in figures)
        # Each monthly release revises earlier months and the files are small: keep every one we see.
        vintage = raw_dir / "vintages" / f"{path.stem}_{latest:%Y-%m}.txt"
        if not vintage.exists():
            vintage.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, vintage)
        parsed[source] = (path, countries, figures, latest)
    con = duckdb.connect(str(db_path))
    try:
        con.execute("DROP TABLE IF EXISTS tic_treasury")
        con.execute("CREATE OR REPLACE TABLE tic_country (source VARCHAR, code VARCHAR, name VARCHAR, kind VARCHAR, region VARCHAR, position INTEGER)")
        con.execute(
            "CREATE OR REPLACE TABLE tic_holdings (asset VARCHAR, code VARCHAR, month DATE, total DOUBLE, total_net DOUBLE, "
            "long_term DOUBLE, long_term_net DOUBLE, long_term_valuation DOUBLE, short_term DOUBLE, short_term_net DOUBLE)")
        con.execute("DELETE FROM source_release WHERE source_id = 'treasury_tic_slt3'")
        for source, (path, countries, figures, latest) in parsed.items():
            con.executemany("INSERT INTO tic_country VALUES (?, ?, ?, ?, ?, ?)",
                            [(source, c["code"], c["name"], c["kind"], c["region"], i) for i, c in enumerate(countries)])
            con.executemany("INSERT INTO tic_holdings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", figures)
            release.record(con, f"treasury_tic_{source}", SOURCES[source][1], SOURCE_URL,
                               dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc), f"{latest:%Y-%m}")
    finally:
        con.close()
    countries = parsed["slt1"][1]
    return {"countries": sum(c["kind"] == "country" for c in countries),
            "observations": sum(len(p[2]) for p in parsed.values()), "latest": f"{parsed['slt3'][3]:%Y-%m}"}
