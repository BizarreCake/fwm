"""Foreign holders of US securities by country, from the Treasury's TIC system.

Z.1 shows the rest of the world as one sector. The Treasury International Capital
(TIC) reports split its holdings by country every month:

    SLT Table 3: Treasury securities, bills as well as bonds and notes
    SLT Table 1: long-term securities by type: agency bonds, corporate bonds, equities
    SLT Table 2: the other direction, foreign long-term securities held by US residents

    tic_country(source, code, name, kind, region, position)   kind: country | region | organizations | total | split | memo
    tic_holdings(asset, code, month, total, total_net, long_term, long_term_net,
                 long_term_valuation, short_term, short_term_net)        -- USD millions

A country here is where the securities are held in custody, which is not always
where the owner lives. Holdings through Belgium, Luxembourg, Ireland, the Cayman
Islands or the United Kingdom include securities held there for owners elsewhere.
"""

from __future__ import annotations

import csv
import datetime as dt
import shutil
import urllib.request
from pathlib import Path

import duckdb

from fwm import ddp, instruments

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

# The other direction: foreign securities held by US residents, by country (SLT Table 2).
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

GRAND_TOTAL = "99996"
ALL_COUNTRIES = "69995"
ORGANIZATIONS = "79995"
OFFICIAL, PRIVATE = "99990", "99991"
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
CUSTODY_NOTE = (
    "Countries are where the securities are held in custody, not always where the owner lives. Financial centres "
    "(Belgium, Luxembourg, Ireland, the Cayman Islands, the United Kingdom) include holdings kept there for owners elsewhere."
)


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
            ddp.record_release(con, f"treasury_tic_{source}", SOURCES[source][1], SOURCE_URL,
                               dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc), f"{latest:%Y-%m}")
    finally:
        con.close()
    countries = parsed["slt1"][1]
    return {"countries": sum(c["kind"] == "country" for c in countries),
            "observations": sum(len(p[2]) for p in parsed.values()), "latest": f"{parsed['slt3'][3]:%Y-%m}"}


def available(con: duckdb.DuckDBPyConnection) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'tic_holdings'").fetchone()[0])


def _quarter(month: str) -> str:
    return f"{month[:4]}:Q{(int(month[5:7]) - 1) // 3 + 1}"


def view(con: duckdb.DuckDBPyConnection, asset: str = "treasuries") -> dict | None:
    """Every holder's monthly series, with region totals, the official and private split, and Z.1's figure alongside."""
    if asset not in ASSETS or not available(con):
        return None
    spec = ASSETS[asset]
    months = [f"{row[0]:%Y-%m}" for row in con.execute(
        "SELECT DISTINCT month FROM tic_holdings WHERE asset = ? ORDER BY month", [asset]).fetchall()]
    index = {month: i for i, month in enumerate(months)}
    n = len(months)
    series: dict[str, dict[str, list]] = {}
    for code, month, *values in con.execute(
        "SELECT code, month, total, total_net, long_term, long_term_net, long_term_valuation, short_term, short_term_net "
        "FROM tic_holdings WHERE asset = ?", [asset]).fetchall():
        entry = series.setdefault(code, {column: [None] * n for column in COLUMNS})
        for column, value in zip(COLUMNS, values):
            entry[column][index[f"{month:%Y-%m}"]] = value

    rows = con.execute("SELECT code, name, kind, region FROM tic_country WHERE source = ? ORDER BY position", [spec["source"]]).fetchall()

    def holder(code: str, name: str, **extra) -> dict:
        data = series[code]
        level, net, valuation = data["long_term"], data["long_term_net"], data["long_term_valuation"]
        # Derived: the part of the change in bonds and notes that reported purchases and valuation do not explain.
        other = [
            None if i == 0 or None in (level[i], level[i - 1], net[i], valuation[i]) else level[i] - level[i - 1] - net[i] - valuation[i]
            for i in range(n)
        ]
        return {"id": code, "name": name, **extra, **data, "long_term_other": other}

    # A country the Treasury never publishes separately stays inside its region's unlisted remainder.
    withheld = [name for code, name, kind, _ in rows if kind == "country" and all(v is None for v in series[code]["total"])]
    countries = [holder(code, name, region=region) for code, name, kind, region in rows
                 if kind == "country" and name not in withheld]
    regions = []
    for code, name, kind, region in rows:
        if kind != "region":
            continue
        members = [c for c in countries if c["region"] == region]
        # What the region total holds beyond the countries the Treasury lists separately.
        unlisted = [
            None if series[code]["total"][i] is None else series[code]["total"][i] - sum(c["total"][i] or 0.0 for c in members)
            for i in range(n)
        ]
        if not members:
            # Canada is a region of one: list it as a country too.
            countries.append(holder(code, name, region=region))
            members, unlisted = [countries[-1]], [0.0] * n
        regions.append(holder(code, name, region=region, unlisted=unlisted, countries=[c["id"] for c in members]))
    organizations = holder(ORGANIZATIONS, "International and regional organizations", region="organizations",
                           unlisted=series[ORGANIZATIONS]["total"], countries=[])

    # Table 1's regions fall slightly short of its "All Countries" total. Show the difference rather than hide it.
    gap = [series[ALL_COUNTRIES]["total"][i] - sum(region["total"][i] for region in regions) for i in range(n)]
    unallocated = None
    if any(abs(value) > 0.5 for value in gap):
        blank = [None] * n
        unallocated = {"id": "unallocated", "name": "Not allocated to a region", "region": "unallocated", "total": gap,
                       "total_net": blank, "long_term": gap, "long_term_net": blank, "long_term_valuation": blank,
                       "long_term_other": blank, "short_term": blank, "short_term_net": blank, "unlisted": gap, "countries": []}

    # The rest of the world's holdings of the nearest Z.1 instrument at each quarter end, for comparison.
    quarterly = None
    try:
        instrument = instruments.view(con, spec["instrument"]) if spec["instrument"] else None
    except Exception:  # the quarterly accounts are not loaded
        instrument = None
    if instrument:
        group = next((g for g in instrument["holders"]["groups"] if g["id"] == "row"), None)
        periods = instrument["periods"]
        if group:
            at = {period: group["level"][i] for i, period in enumerate(periods)}
            quarterly = {
                "instrument_id": spec["instrument"], "instrument_name": instrument["name"], "sector_id": "S2",
                "latest": periods[-1], "note": spec["quarterly"],
                "level": [at.get(_quarter(month)) if int(month[5:7]) % 3 == 0 else None for month in months],
            }

    release = con.execute("SELECT name, url, latest_period FROM source_release WHERE source_id = ?",
                          [f"treasury_tic_{spec['source']}"]).fetchone()
    return {
        "id": asset,
        "name": spec["name"],
        "direction": spec.get("direction", "inward"),
        "assets": [{"id": key, "name": ASSETS[key]["name"]} for key in (OUTWARD if asset in OUTWARD else INWARD)],
        "has_bills": spec["bills"],
        "unit": "USD millions",
        "periods": months,
        "total": holder(GRAND_TOTAL, "All foreign holders"),
        "official": holder(OFFICIAL, "Official holders (central banks and governments)") if OFFICIAL in series else None,
        "private": holder(PRIVATE, "Private holders") if PRIVATE in series else None,
        "regions": [*regions, organizations, *([unallocated] if unallocated else [])],
        "countries": countries,
        "memo": [holder(code, name) for code, name, kind, _ in rows if kind == "memo" and code in MEMO],
        "quarterly": quarterly,
        "source": {"name": release[0], "url": release[1], "file": FILES + SOURCES[spec["source"]][0], "latest": release[2]},
        "notes": {
            "custody": CUSTODY_NOTE,
            "scope": spec["scope"],
            "valuation": "Holdings are at market value. Net purchases and valuation change are as reported"
                         + ("; for bills, purchases are estimated as the change in holdings and no valuation change is reported." if spec["bills"] else "."),
            **({"unallocated": "The Treasury's region totals fall slightly short of its total for all countries in this "
                               "table; the difference is shown as \"Not allocated to a region\"."} if unallocated else {}),
            "history": "This table covers January 2020 onward. Net purchases and valuation are reported from February 2023.",
            "other": "\"Other change\" is computed here: the change in long-term holdings that reported net purchases and valuation "
                     "do not explain. The Treasury does not say what it contains.",
            "missing": "Not published separately, and counted in their region's total: " + ", ".join(withheld) + ".",
        },
    }
