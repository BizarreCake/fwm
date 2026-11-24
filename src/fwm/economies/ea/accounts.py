"""The euro area's financial accounts, in the same shapes as the US views.

Sector balance sheets and instrument holders and issuers are built from the ECB's
quarterly sector accounts so that the pages and tools written for Z.1 can show them.

Differences from the US accounts that matter when reading them:

- Amounts are in euro. Nothing is converted.
- "Other changes" are published by the ECB, not derived, and equal the change in
  the amount outstanding less transactions.
- The rest of the world is not a sector of its own in the data. It is read from
  the euro area's positions against non-residents: what residents owe abroad is
  what the rest of the world holds, and the reverse.
- Banks, central banks and money market funds are one sector (monetary financial
  institutions). Central banks are published separately only from 2015.
"""

from __future__ import annotations

import duckdb

from fwm.loaders import ecb_accounts as ecb

FIRST_PERIOD = "1999:Q1"  # the euro's first quarter; a few series start earlier, most detail later
CURRENCY = "EUR"

# (id, name, shared sector group). Together they make up the whole economy (S1), without overlap, from 1999.
SECTORS = (
    ("S11", "Non-financial corporations", "gov_business"),
    ("S12K", "Banks, central banks and money market funds", "banks"),
    ("S124", "Investment funds other than money market funds", "funds"),
    ("S12O", "Other financial institutions", "other_financial"),
    ("S128", "Insurance corporations", "pensions_insurers"),
    ("S129", "Pension funds", "pensions_insurers"),
    ("S13", "General government", "gov_business"),
    ("S1M", "Households and non-profits", "households"),
)
# The two parts of S12K, published separately only from 2015. They have pages, and are listed under S12K,
# but totals are taken from S12K so that the history back to 1999 adds up.
PARTS = {"S12K": (("S121", "Central banks (Eurosystem)"), ("S12T", "Banks and money market funds, excluding central banks"))}
ROW = ("ROW", "Rest of the world", "row")
ECONOMY_TOTAL = "S1"
SECTOR_NAMES = {sector_id: name for sector_id, name, _ in (*SECTORS, ROW)}
PART_NAMES = {part: name for parts in PARTS.values() for part, name in parts}
PART_OF = {part: whole for whole, parts in PARTS.items() for part, _ in parts}
ALL_NAMES = {**SECTOR_NAMES, **PART_NAMES}
SECTOR_GROUP = {sector_id: group for sector_id, _, group in (*SECTORS, ROW)}
# Shared group ids (which fix the colours), with the names that fit the euro area.
GROUPS = (
    ("row", "Rest of the world"), ("banks", "Banks & central banks"), ("funds", "Investment funds"),
    ("pensions_insurers", "Pensions & insurers"), ("households", "Households & non-profits"),
    ("other_financial", "Other financial institutions"), ("gov_business", "Government & business"),
)

# (instrument, maturity) -> name. The top level is F1..F8; the rest are the breakdowns shown beneath them.
TOP = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8")
NAMES = {
    "F": "Total", "F1": "Monetary gold and SDRs", "F11": "Monetary gold", "F12": "Special drawing rights",
    "F2": "Currency and deposits", "F21": "Currency", "F2M": "Deposits",
    "F3": "Debt securities", "F3:S": "Short-term debt securities", "F3:L": "Long-term debt securities",
    "F4": "Loans", "F4:S": "Short-term loans", "F4:L": "Long-term loans",
    "F5": "Equity and investment fund shares", "F51": "Equity", "F511": "Listed shares", "F512": "Unlisted shares",
    "F519": "Other equity", "F52": "Investment fund shares", "F521": "Money market fund shares",
    "F522": "Other investment fund shares",
    "F6": "Insurance, pensions and guarantees", "F7": "Financial derivatives (net, recorded as liabilities)",
    "F8": "Other accounts", "F81": "Trade credits and advances", "F89": "Other accounts, excluding trade credits",
}
CHILDREN = {
    "F1": ("F11", "F12"), "F2": ("F21", "F2M"), "F3": ("F3:S", "F3:L"), "F4": ("F4:S", "F4:L"), "F5": ("F51", "F52"),
    "F51": ("F511", "F512", "F519"), "F52": ("F521", "F522"), "F8": ("F81", "F89"),
}
# Instruments with a page of their own: who holds and who owes.
INSTRUMENTS = ("F2", "F3", "F4", "F51", "F52", "F6", "F8")  # derivatives are published net, so have no holders
MARKET_VALUED = ("F3", "F5", "F7")
TOLERANCE = 2.5  # EUR millions: the ECB rounds each published line


def _basis(code: str) -> str:
    return "market" if code.startswith(MARKET_VALUED) else "book"


def available(con: duckdb.DuckDBPyConnection) -> bool:
    return ecb.available(con)


def periods(con: duckdb.DuckDBPyConnection) -> list[str]:
    latest = con.execute("SELECT max(period) FROM qsa_observations").fetchone()[0]
    out = []
    year, quarter = int(FIRST_PERIOD[:4]), 1
    while f"{year}:Q{quarter}" <= latest:
        out.append(f"{year}:Q{quarter}")
        year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
    return out


class Accounts:
    """Every position's three measures, indexed for building views. One read of the database."""

    def __init__(self, con: duckdb.DuckDBPyConnection):
        self.periods = periods(con)
        index = {period: i for i, period in enumerate(self.periods)}
        n = len(self.periods)
        self.data: dict[tuple, dict] = {}
        rows = con.execute(
            "SELECT s.counterpart_area, s.sector, s.counterpart_sector, s.side, s.measure, s.instrument, s.maturity, "
            "s.key, o.period, o.value FROM qsa_series s JOIN qsa_observations o USING (key) "
            "WHERE (s.counterpart_area = 'W0' AND s.counterpart_sector = 'S1') OR (s.counterpart_area = 'W1' AND s.sector = 'S1')"
        ).fetchall()
        for area, sector, _, side, measure, instrument, maturity, key, period, value in rows:
            if period not in index:
                continue
            code = instrument if maturity in ("_Z", "T") else f"{instrument}:{maturity}"
            entry = self.data.setdefault((area, sector, side, code), {"keys": {}})
            entry.setdefault(measure, [None] * n)[index[period]] = value
            entry["keys"][measure] = key
        release = con.execute("SELECT name, url, published_at, latest_period FROM source_release WHERE source_id = ?", [ecb.SOURCE_ID]).fetchone()
        self.source = {"name": release[0], "url": release[1], "published_at": release[2].isoformat() if release[2] else None,
                       "latest_period": release[3]}

    def position(self, sector: str, side: str, code: str) -> dict | None:
        """One sector's holdings (assets) or debts (liabilities) of an instrument, or None if not published."""
        if sector == "ROW":
            # The rest of the world's assets are what euro-area residents owe to non-residents, and the reverse.
            entry = self.data.get(("W1", ECONOMY_TOTAL, "liabilities" if side == "assets" else "assets", code))
        else:
            entry = self.data.get(("W0", sector, side, code))
        if entry is None or "level" not in entry:
            return None
        n = len(self.periods)
        level = entry["level"]
        transactions = entry.get("transactions", [None] * n)
        published = entry.get("other_change", [None] * n)
        # Use the ECB's own other changes; where a quarter lacks them, the change in level less transactions.
        other = [
            published[i] if published[i] is not None
            else None if i == 0 or None in (level[i], level[i - 1], transactions[i]) else level[i] - level[i - 1] - transactions[i]
            for i in range(n)
        ]
        return {"series": entry["keys"]["level"], "level": level, "transactions": transactions, "other_change": other}

    def children(self, sector: str, side: str, code: str) -> list[str]:
        """The breakdown of a line, if every part is published and the parts add up to it in every quarter."""
        parts = CHILDREN.get(code, ())
        whole = self.position(sector, side, code)
        found = [(part, self.position(sector, side, part)) for part in parts]
        found = [(part, position) for part, position in found if position is not None]
        if whole is None or len(found) < 2:
            return []
        for i, total in enumerate(whole["level"]):
            values = [position["level"][i] for _, position in found]
            if total is None:
                continue
            if any(value is None for value in values) or abs(sum(values) - total) > TOLERANCE * len(values):
                return []
        return [part for part, _ in found]


def _node(accounts: Accounts, sector: str, side: str, code: str, name: str | None = None) -> dict | None:
    position = accounts.position(sector, side, code)
    if position is None:
        return None
    children = [_node(accounts, sector, side, part) for part in ((TOP if code == "F" else accounts.children(sector, side, code)))]
    children = [child for child in children if child is not None]
    if code == "F":
        # Where the published lines fall short of the published total, show the remainder rather than hide it.
        n = len(accounts.periods)

        def rest(key: str) -> list:
            return [None if position[key][i] is None else position[key][i] - sum(child[key][i] or 0.0 for child in children)
                    for i in range(n)]

        if any(value is not None and abs(value) > TOLERANCE * len(children) for value in rest("level")):
            children.append({"series": "computed", "name": "Not published separately (computed)", "basis": "book",
                             "instrument": None, "level": rest("level"), "transactions": rest("transactions"),
                             "other_change": rest("other_change"), "children": [], "memos": []})
    page = next((i for i in INSTRUMENTS if code == i or (code.split(":")[0] == i)), None)
    return {
        **position,
        "name": name or NAMES[code],
        "basis": _basis(code),
        "instrument": page if code != "F" else None,
        "children": children,
        "memos": [],
    }


def list_sectors(con: duckdb.DuckDBPyConnection) -> list[dict]:
    accounts = Accounts(con)
    out = []

    def row(sector_id: str, name: str, part_of: str | None = None) -> dict:
        assets, liabilities = accounts.position(sector_id, "assets", "F"), accounts.position(sector_id, "liabilities", "F")
        return {"id": sector_id, "name": name, "sector_code": sector_id, "part_of": part_of,
                "total_assets": assets["level"][-1] if assets else None,
                "total_liabilities": liabilities["level"][-1] if liabilities else None}

    for sector_id, name, _ in (*SECTORS, ROW):
        out.append(row(sector_id, name))
        out += [row(part, part_name, sector_id) for part, part_name in PARTS.get(sector_id, ())]
    return out


def balance_sheet(con: duckdb.DuckDBPyConnection, sector_id: str) -> dict | None:
    if sector_id not in ALL_NAMES:
        return None
    accounts = Accounts(con)
    assets = _node(accounts, sector_id, "assets", "F", "Total financial assets")
    liabilities = _node(accounts, sector_id, "liabilities", "F", "Total liabilities")
    if assets is None:
        return None
    return {
        "id": sector_id,
        "name": ALL_NAMES[sector_id],
        "economy": "ea",
        "part_of": PART_OF.get(sector_id),
        "unit": "EUR millions",
        "periods": accounts.periods,
        "assets": assets,
        "liabilities": liabilities,
        "source": {**accounts.source, "table": f"{sector_id} {ALL_NAMES[sector_id]}"},
        "notes": {
            "structure": "Lines are the ECB's instrument categories. A breakdown is shown only where its parts are all "
                         "published and add up to the line in every quarter. Amounts are in euro and are not consolidated: "
                         "claims between units of the same sector are included.",
            "liabilities": "The rest of the world is read from the euro area's positions against non-residents: its assets "
                           "are what residents owe abroad, its liabilities what residents hold abroad."
                           if sector_id == "ROW" else
                           f"Published separately from 2015. Before that it is part of {SECTOR_NAMES[PART_OF[sector_id]].lower()}."
                           if sector_id in PART_OF else None,
            "other_change": "Valuation & other is published by the ECB: price and exchange-rate changes, plus "
                            "reclassifications. It equals the change in the amount less transactions.",
        },
    }


def _total(positions: list[dict], n: int) -> dict:
    def add(key: str) -> list:
        return [None if all(p[key][i] is None for p in positions) else sum(p[key][i] or 0.0 for p in positions) for i in range(n)]
    return {"level": add("level"), "transactions": add("transactions"), "other_change": add("other_change")}


def list_instruments(con: duckdb.DuckDBPyConnection) -> list[dict]:
    accounts = Accounts(con)
    out = []
    for code in INSTRUMENTS:
        holders = [p for sector_id in SECTOR_NAMES if (p := accounts.position(sector_id, "assets", code))]
        out.append({"id": code, "name": NAMES[code], "has_issuers": True,
                    "holders_total": sum(p["level"][-1] or 0.0 for p in holders) if holders else None})
    return out


def view(con: duckdb.DuckDBPyConnection, instrument_id: str) -> dict | None:
    """Who holds an instrument and who owes it, by sector group and sector."""
    if instrument_id not in INSTRUMENTS:
        return None
    accounts = Accounts(con)
    n = len(accounts.periods)

    def row(sector_id: str, side_name: str, group: str, **extra) -> dict | None:
        position = accounts.position(sector_id, side_name, instrument_id)
        if position is None:
            return None
        return {"code": sector_id, "name": ALL_NAMES[sector_id], "detail": NAMES[instrument_id].lower(), "group": group,
                "sector_id": sector_id, "basis": _basis(instrument_id), **extra, **position}

    def side(name: str) -> dict:
        rows = [r for sector_id in SECTOR_NAMES if (r := row(sector_id, name, SECTOR_GROUP[sector_id]))]
        groups = []
        for group_id, group_name in GROUPS:
            members = [r for r in rows if r["group"] == group_id]
            if not members:
                continue
            # Sectors published in two parts: list the parts beneath, marked so that they are not added to the total.
            listed = []
            for member in members:
                listed.append(member)
                listed += [r for part, _ in PARTS.get(member["code"], ()) if (r := row(part, name, group_id, part_of=member["code"]))]
            groups.append({"id": group_id, "name": group_name,
                           **_total(members, n), "sectors": listed})
        return {"series": f"sum of {len(rows)} sectors", "excludes_discrepancy": False, **_total(rows, n), "groups": groups}

    holders, issuers = side("assets"), side("liabilities")
    gap = [None if None in (h, i) else h - i for h, i in zip(holders["level"], issuers["level"])]
    return {
        "id": instrument_id,
        "name": NAMES[instrument_id],
        "economy": "ea",
        "unit": "EUR millions",
        "periods": accounts.periods,
        "group_order": [group_id for group_id, _ in GROUPS],
        "group_notes": "Banks & central banks includes money market funds. Investment funds excludes them.",
        "holders": holders,
        "issuers": issuers,
        "discrepancy": {"series": "holders less issuers (computed)", "level": gap},
        "who_to_whom": instrument_id in WHO_TO_WHOM,
        "source": {**accounts.source, "table": f"{instrument_id} {NAMES[instrument_id]}"},
        "notes": {
            "sides": "Holders report this instrument as an asset; issuers owe it as a liability. Both sides include the rest "
                     "of the world, read from the euro area's positions against non-residents, so the two totals should match.",
            "other_change": "Valuation & other is published by the ECB: price and exchange-rate changes, plus reclassifications.",
            "coverage": "Sector-level aggregates for the euro area as a whole, in euro; no individual institutions or "
                        "countries. Banks, central banks and money market funds are one sector; central banks are "
                        "published separately only from 2015.",
            "issuers": None,
        },
    }


# ---- who holds whose paper --------------------------------------------------------
#
# For some instruments the ECB publishes each resident sector's position against each
# resident sector. (instrument page, series code, side the series are reported on, what is covered)
WHO_TO_WHOM = {
    "F3": ("F3", "assets", "Debt securities"),
    "F4": ("F4", "assets", "Loans"),
    "F2": ("F2M", "liabilities", "Deposits (currency is not included)"),
    "F51": ("F511", "assets", "Listed shares only (unlisted shares and other equity are not published by counterpart)"),
    "F52": ("F52", "assets", "Investment fund shares"),
}


def who_to_whom(con: duckdb.DuckDBPyConnection, instrument_id: str) -> dict | None:
    """Amounts each sector holds of each sector's paper: a holder-by-issuer matrix per quarter.

    Positions between resident sectors are published. Positions with the rest of the world
    are the remainder: a holder's total less what it holds of residents, and an issuer's
    total less what residents hold of it.
    """
    if instrument_id not in WHO_TO_WHOM:
        return None
    code, reported_on, covers = WHO_TO_WHOM[instrument_id]
    accounts = Accounts(con)
    all_periods = accounts.periods
    index = {period: i for i, period in enumerate(all_periods)}
    n = len(all_periods)
    residents = [sector_id for sector_id, _, _ in SECTORS]
    rows = con.execute(
        "SELECT s.sector, s.counterpart_sector, s.measure, s.key, o.period, o.value FROM qsa_series s JOIN qsa_observations o USING (key) "
        "WHERE s.counterpart_area = 'W2' AND s.instrument = ? AND s.maturity IN ('_Z', 'T') AND s.side = ?", [code, reported_on]
    ).fetchall()
    cells: dict[tuple[str, str], dict] = {}
    for sector, counterpart, measure, key, period, value in rows:
        if sector not in residents or counterpart not in residents or period not in index:
            continue
        # Deposits are reported by the deposit-taker, so the counterpart is the holder.
        holder, issuer = (sector, counterpart) if reported_on == "assets" else (counterpart, sector)
        cell = cells.setdefault((holder, issuer), {"series": None, "level": [None] * n, "transactions": [None] * n, "other_change": [None] * n})
        cell[measure][index[period]] = value
        if measure == "level":
            cell["series"] = key
    if not cells:
        return None
    # Start where every published pair has an amount, so that rows and columns can be added up.
    start = max(next(i for i, value in enumerate(cell["level"]) if value is not None) for cell in cells.values())
    periods = all_periods
    m = n

    def cut(values: list) -> list:
        """Aligned with the instrument page's quarters; empty before the matrix is complete."""
        return [None] * start + values[start:]

    def remainder(total: dict | None, parts: list[dict], key: str) -> list:
        if total is None:
            return [None] * m
        whole = total[key]
        return [None if i < start or whole[i] is None else whole[i] - sum(part[key][i] or 0.0 for part in parts) for i in range(m)]

    matrix: dict[str, dict[str, dict]] = {}
    for (holder, issuer), cell in cells.items():
        matrix.setdefault(holder, {})[issuer] = {"series": cell["series"], "computed": False,
                                                 **{key: cut(cell[key]) for key in ("level", "transactions", "other_change")}}
    for sector_id in residents:
        held = [matrix.get(sector_id, {}).get(issuer) for issuer in residents]
        held = [cell for cell in held if cell]
        total = accounts.position(sector_id, "assets", code)
        if total is not None:
            matrix.setdefault(sector_id, {})["ROW"] = {"series": "computed", "computed": True, **{
                key: remainder(total, held, key) for key in ("level", "transactions", "other_change")}}
        owed = [matrix.get(holder, {}).get(sector_id) for holder in residents]
        owed = [cell for cell in owed if cell]
        total = accounts.position(sector_id, "liabilities", code)
        if total is not None and owed:
            matrix.setdefault("ROW", {})[sector_id] = {"series": "computed", "computed": True, **{
                key: remainder(total, owed, key) for key in ("level", "transactions", "other_change")}}
    order = [*residents, "ROW"]
    holders = [sector_id for sector_id in order if sector_id in matrix]
    # Leave out issuers that never owe anything in this instrument (households issue no securities).
    issuers = [sector_id for sector_id in order
               if any(abs(value or 0.0) >= 1 for holder in holders for value in matrix[holder].get(sector_id, {"level": []})["level"])]
    return {
        "id": instrument_id,
        "name": NAMES[instrument_id],
        "covers": covers,
        "economy": "ea",
        "unit": "EUR millions",
        "periods": periods,
        "first_period": periods[start],
        "sectors": {sector_id: {"name": SECTOR_NAMES[sector_id], "group": SECTOR_GROUP[sector_id]} for sector_id in order},
        "holders": holders,
        "issuers": issuers,
        "matrix": matrix,
        "source": {**accounts.source, "table": f"{code} by counterpart sector"},
        "notes": {
            "reading": "Each cell is what the sector in the row holds of what the sector in the column owes. Amounts between "
                       "resident sectors are published by the ECB.",
            "rest_of_world": "Rest of the world is the remainder: a holder's total less what it holds of residents, and an "
                             "issuer's total less what residents hold of it.",
            "coverage": f"{covers}. Banks, central banks and money market funds are one sector.",
        },
    }
