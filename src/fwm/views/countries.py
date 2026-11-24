"""Countries as counterparties of the United States.

For one country: the US securities held there, and the foreign securities of
that country held by US residents, both monthly from the Treasury's TIC reports.

This is the country seen from the US, not the country's own balance sheet. It
says nothing about what the country holds at home or in third countries, and
the two directions are counted differently: US securities are attributed to the
country where they are held in custody; foreign securities to the country of
the issuer.
"""

from __future__ import annotations

import re

import duckdb

from fwm import codes
from fwm.views import foreign as tic
from fwm.views import links

MEASURES = ("total", "total_net", "long_term_valuation")
NOTES = {
    "scope": "This is the country seen from the United States: US securities held there, and its securities held by US "
             "residents. It is not the country's own balance sheet, and says nothing about what it holds at home or elsewhere.",
    "custody": tic.CUSTODY_NOTE,
    "outward": "Foreign securities held by US residents are attributed to the country of the issuer. Funds and companies "
               "incorporated in financial centres (the Cayman Islands, Ireland, Luxembourg) count as issuers there.",
    "coverage": "Long-term securities and Treasury bills only. No bank deposits, loans, direct investment or derivatives.",
    "history": "Monthly from January 2020. Net purchases and valuation are reported from February 2023.",
}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _entities(con: duckdb.DuckDBPyConnection) -> dict[str, dict]:
    """Every country and country group in any TIC table, keyed by slug, with its code in each table."""
    out: dict[str, dict] = {}
    rows = con.execute("SELECT source, code, name, kind, region FROM tic_country ORDER BY source, position").fetchall()
    for source, code, name, kind, region in rows:
        if kind == "country" or (kind == "region" and region == "canada"):
            entity_kind = "country"
        elif kind == "memo" and code in tic.MEMO:
            entity_kind = "group"
        else:
            continue
        entity = out.setdefault(slug(name), {"id": slug(name), "name": name, "kind": entity_kind, "region": region, "codes": {}})
        entity["codes"][source] = code
        entity["region"] = entity["region"] or region
    return out


def code_of(entity: dict) -> str | None:
    """The ISO two-letter code of a country that has a page, for the cross-border data."""
    row = codes.find_country(entity["name"]) if entity["kind"] == "country" else None
    return row["iso2"] if row else None


def page_of(con: duckdb.DuckDBPyConnection, iso2: str) -> str | None:
    """The id of the country page for an ISO code, if the country has one."""
    if not tic.available(con):
        return None
    return next((key for key, entity in _entities(con).items() if code_of(entity) == iso2), None)


def cross_border(con: duckdb.DuckDBPyConnection, country_id: str) -> dict | None:
    """The country's positions with every other country, with links to their pages."""
    entity = _entities(con).get(country_id) if tic.available(con) else None
    code = code_of(entity) if entity else None
    view = links.country(con, code) if code else None
    if view is None:
        return None
    pages = {code_of(e): key for key, e in _entities(con).items()}
    for kind in view["kinds"]:
        for side in ("own", "mirror"):
            for row in (kind[side] or {}).get("top", []):
                row["page"] = pages.get(row["iso2"])
    return view


def _series(con: duckdb.DuckDBPyConnection, asset: str, months: list[str]) -> dict[str, dict[str, list]]:
    index = {month: i for i, month in enumerate(months)}
    out: dict[str, dict[str, list]] = {}
    for code, month, *values in con.execute(
        "SELECT code, month, total, total_net, long_term_valuation FROM tic_holdings WHERE asset = ?", [asset]).fetchall():
        entry = out.setdefault(code, {measure: [None] * len(months) for measure in MEASURES})
        for measure, value in zip(MEASURES, values):
            entry[measure][index[f"{month:%Y-%m}"]] = value
    return out


def _months(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [f"{row[0]:%Y-%m}" for row in con.execute("SELECT DISTINCT month FROM tic_holdings ORDER BY month").fetchall()]


def _sum(lists: list[list]) -> list:
    """Month by month, the sum of the values that are published; None where none is."""
    return [None if all(v is None for v in column) else sum(v or 0.0 for v in column) for column in zip(*lists)]


def listing(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Every country with the latest totals in each direction, largest first."""
    if not tic.available(con):
        return []
    months = _months(con)
    entities = _entities(con)
    latest: dict[str, dict[str, float]] = {key: {"holds_us": 0.0, "held_by_us": 0.0} for key in entities}
    published: dict[str, set] = {key: set() for key in entities}
    for asset, spec in tic.ASSETS.items():
        direction = "held_by_us" if asset in tic.OUTWARD else "holds_us"
        series = _series(con, asset, months)
        for key, entity in entities.items():
            code = entity["codes"].get(spec["source"])
            value = series.get(code, {}).get("total", [None])[-1] if code else None
            if value is not None:
                latest[key][direction] += value
                published[key].add(direction)
    rows = [
        {"id": key, "name": entity["name"], "kind": entity["kind"], "region": entity["region"],
         "holds_us": latest[key]["holds_us"] if "holds_us" in published[key] else None,
         "held_by_us": latest[key]["held_by_us"] if "held_by_us" in published[key] else None}
        for key, entity in entities.items() if published[key]
    ]
    return sorted(rows, key=lambda row: -((row["holds_us"] or 0) + (row["held_by_us"] or 0)))


def view(con: duckdb.DuckDBPyConnection, country_id: str) -> dict | None:
    if not tic.available(con):
        return None
    entity = _entities(con).get(country_id)
    if entity is None:
        return None
    months = _months(con)
    n = len(months)
    peers = [e for e in _entities(con).values() if e["kind"] == "country"]

    def lines(assets: list[str]) -> list[dict]:
        out = []
        for asset in assets:
            spec = tic.ASSETS[asset]
            series = _series(con, asset, months)
            code = entity["codes"].get(spec["source"])
            own = series.get(code) if code else None
            if own is None or all(v is None for v in own["total"]):
                continue
            everyone = series[tic.GRAND_TOTAL]["total"]
            latest = own["total"][-1]
            # Rank among countries with a published figure in the latest month.
            others = [series[c]["total"][-1] for e in peers if (c := e["codes"].get(spec["source"])) in series]
            rank = None if latest is None or entity["kind"] != "country" else 1 + sum(1 for v in others if v is not None and v > latest)
            out.append({
                "id": asset, "name": spec["name"], "scope": spec["scope"],
                "page": f"#/us/foreign/{asset}" if asset in tic.INWARD else None,
                **own,
                "all_countries": everyone,
                "rank": rank,
                "ranked_among": sum(1 for v in others if v is not None),
            })
        return out

    def side(assets: list[str]) -> dict:
        rows = lines(assets)
        return {
            "lines": rows,
            **{measure: _sum([row[measure] for row in rows]) if rows else [None] * n for measure in MEASURES},
        }

    holds_us, held_by_us = side(tic.INWARD), side(tic.OUTWARD)
    if not holds_us["lines"] and not held_by_us["lines"]:
        return None
    release = con.execute("SELECT url, latest_period FROM source_release WHERE source_id = 'treasury_tic_slt1'").fetchone()
    return {
        "id": entity["id"], "name": entity["name"], "kind": entity["kind"], "region": entity["region"],
        "has_links": bool(links.available(con) and code_of(entity)),
        "unit": "USD millions",
        "periods": months,
        "holds_us": holds_us,
        "held_by_us": held_by_us,
        "source": {"name": "US Treasury, TIC SLT Tables 1, 2 and 3", "url": release[0], "latest": release[1]},
        "notes": NOTES,
    }
