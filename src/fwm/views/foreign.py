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

import duckdb

from fwm.economies.us import instruments
from fwm.loaders.tic import (
    ALL_COUNTRIES,
    ASSETS,
    COLUMNS,
    FILES,
    GRAND_TOTAL,
    INWARD,
    MEMO,
    OFFICIAL,
    ORGANIZATIONS,
    OUTWARD,
    PRIVATE,
    SOURCES,
)

# The other direction: foreign securities held by US residents, by country (SLT Table 2).
CUSTODY_NOTE = (
    "Countries are where the securities are held in custody, not always where the owner lives. Financial centres "
    "(Belgium, Luxembourg, Ireland, the Cayman Islands, the United Kingdom) include holdings kept there for owners elsewhere."
)










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
