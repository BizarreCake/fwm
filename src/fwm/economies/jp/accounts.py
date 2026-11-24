"""Japan's financial accounts, in the same shapes as the US and euro-area views.

Built from the Bank of Japan's Flow of Funds. Differences that matter when reading them:

- Amounts are in yen. Nothing is converted.
- The Bank of Japan is a sector of its own for the whole history, as is the rest of the
  world ("Overseas"), so neither has to be derived.
- "Valuation & other" is the Bank's published reconciliation between flows and stocks.
- The published total on the liabilities side includes the difference between assets and
  liabilities, so total liabilities here are the sum of the instrument lines instead.
- The series change statistical basis at 2005:Q1. Levels step there; the step is in neither
  transactions nor the reconciliation, and it is left as published.
- Investment trusts are listed by the Bank among debt securities but counted with equity,
  as fund shares; here they are a line of their own beside equity.
"""

from __future__ import annotations

import duckdb

from fwm.loaders import boj_accounts as boj

FIRST_PERIOD = "1997:Q4"
CURRENCY = "JPY"

# (id, name, shared sector group). Together they make up the Bank's "Total" (domestic sectors and overseas).
SECTORS = (
    ("S110", "Bank of Japan", "fed"),
    ("S120", "Banks and other depository corporations", "banks"),
    ("S131", "Insurance", "pensions_insurers"),
    ("S140", "Pension funds", "pensions_insurers"),
    ("S160", "Investment trusts", "funds"),
    ("S170", "Nonbanks", "other_financial"),
    ("S180", "Public financial institutions", "other_financial"),
    ("S190", "Financial dealers and brokers", "other_financial"),
    ("S210", "Public captive financial institutions", "other_financial"),
    ("S300", "Financial auxiliaries", "other_financial"),
    ("S410", "Nonfinancial corporations", "gov_business"),
    ("S420", "General government", "gov_business"),
    ("S430", "Households", "households"),
    ("S440", "Private nonprofit institutions serving households", "households"),
)
ROW = ("S500", "Rest of the world", "row")
# Parts with pages of their own, listed under the whole and never added to totals.
PARTS = {
    "S120": (("S122", "Domestically licensed banks"), ("S123", "Foreign banks in Japan"),
             ("S124", "Financial institutions for agriculture, forestry and fisheries"),
             ("S125", "Financial institutions for small businesses"), ("S126", "Postal savings (Japan Post Bank)")),
    "S420": (("S421", "Central government"), ("S422", "Local governments"), ("S423", "Social security funds")),
    "S410": (("S411", "Private nonfinancial corporations"), ("S412", "Public nonfinancial corporations")),
}
SECTOR_NAMES = {sector_id: name for sector_id, name, _ in (*SECTORS, ROW)}
PART_NAMES = {part: name for parts in PARTS.values() for part, name in parts}
PART_OF = {part: whole for whole, parts in PARTS.items() for part, _ in parts}
ALL_NAMES = {**SECTOR_NAMES, **PART_NAMES}
SECTOR_GROUP = {sector_id: group for sector_id, _, group in (*SECTORS, ROW)}
GROUPS = (
    ("fed", "Bank of Japan"), ("row", "Rest of the world"), ("banks", "Banks"), ("funds", "Investment trusts"),
    ("pensions_insurers", "Pensions & insurers"), ("households", "Households & non-profits"),
    ("other_financial", "Other financial institutions"), ("gov_business", "Government & business"),
)

# Transaction items. The top level adds up to total financial assets.
TOP = ("I100", "I190", "I200", "I300", "I330", "I318", "I340", "I400", "I500", "I510", "I520", "I530", "I540", "I550", "I600")
NAMES = {
    "F": "Total",
    "I100": "Currency and deposits", "I110": "Currency", "I120": "Deposits with the Bank of Japan", "I130": "Government deposits",
    "I140": "Transferable deposits", "I150": "Time and savings deposits", "I160": "Certificates of deposit",
    "I170": "Foreign currency deposits",
    "I190": "Deposits with the Fiscal Loan Fund",
    "I200": "Loans", "I210": "Bank of Japan loans", "I220": "Call loans and bills", "I240": "Loans by private financial institutions",
    "I241": "Housing loans", "I242": "Consumer credit", "I243": "Loans to companies and governments",
    "I250": "Loans by public financial institutions", "I260": "Loans by the nonfinancial sector", "I270": "Installment credit",
    "I280": "Repurchase agreements and securities lending",
    "I300": "Debt securities", "I310": "Treasury discount bills", "I311": "Government bonds (JGBs and FILP bonds)",
    "I312": "Local government securities", "I313": "Public corporation securities", "I314": "Bank debentures",
    "I315": "Industrial securities (corporate bonds)", "I316": "External securities issued by residents",
    "I317": "Commercial paper", "I319": "Trust beneficiary rights", "I320": "Structured-financing instruments",
    "I330": "Equity", "I331": "Listed shares", "I332": "Unlisted shares", "I333": "Other equity",
    "I318": "Investment trust shares",
    "I340": "Financial derivatives and employee stock options", "I341": "Forward-type instruments",
    "I342": "Option-type instruments", "I343": "Employee stock options",
    "I400": "Insurance, pensions and standardized guarantees", "I401": "Non-life insurance reserves",
    "I402": "Life insurance reserves", "I403": "Annuity entitlements", "I404": "Pension entitlements",
    "I405": "Claims of pension funds on pension managers", "I406": "Provisions for standardized guarantees",
    "I500": "Deposits money", "I510": "Trade credits", "I520": "Accounts receivable and payable",
    "I530": "Outward direct investment", "I540": "Outward investment in securities", "I550": "Other external claims and debts",
    "I600": "Other",
}
CHILDREN = {
    "I100": ("I110", "I120", "I130", "I140", "I150", "I160", "I170"),
    "I200": ("I210", "I220", "I240", "I250", "I260", "I270", "I280"),
    "I240": ("I241", "I242", "I243"),
    "I300": ("I310", "I311", "I312", "I313", "I314", "I315", "I316", "I317", "I319", "I320"),
    "I330": ("I331", "I332", "I333"),
    "I340": ("I341", "I342", "I343"),
    "I400": ("I401", "I402", "I403", "I404", "I405", "I406"),
}
# Instruments with a page of their own: who holds and who owes. Government bonds are part of debt securities.
INSTRUMENTS = ("I100", "I200", "I300", "I311", "I310", "I330", "I318", "I400", "I540")
COMPOSITE_PARTS = {"I311": "I300", "I310": "I300"}  # pages for a line that is also inside another page
MARKET_VALUED = ("I30", "I31", "I32", "I33", "I34", "I54")
BREAK = "2005:Q1"
BREAK_NOTE = ("The statistics change basis at 2005:Q1: amounts step in that quarter by more than its transactions and "
              "valuation changes explain, so comparisons across it are approximate.")
TOLERANCE = 250.0  # JPY millions: the Bank publishes in units of 100 million yen


def _basis(code: str) -> str:
    return "market" if code.startswith(MARKET_VALUED) else "book"


def available(con: duckdb.DuckDBPyConnection) -> bool:
    return boj.available(con)


def periods(con: duckdb.DuckDBPyConnection) -> list[str]:
    latest = con.execute("SELECT max(period) FROM jff_observations").fetchone()[0]
    out = []
    year, quarter = int(FIRST_PERIOD[:4]), int(FIRST_PERIOD[-1])
    while f"{year}:Q{quarter}" <= latest:
        out.append(f"{year}:Q{quarter}")
        year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
    return out


def series_id(measure: str, sector_id: str, side: str, code: str) -> str:
    letter = {"level": "S", "transactions": "F", "other_change": "R"}[measure]
    return f"FOF_FFA{letter}{sector_id[1:]}{'A' if side == 'assets' else 'L'}{'900' if code == 'F' else code[1:]}"


class Accounts:
    """Every position's three measures, indexed for building views. One read of the database."""

    def __init__(self, con: duckdb.DuckDBPyConnection):
        self.periods = periods(con)
        index = {period: i for i, period in enumerate(self.periods)}
        n = len(self.periods)
        self.data: dict[str, list] = {}
        for series, period, value in con.execute("SELECT series_id, period, value FROM jff_observations").fetchall():
            if period in index:
                self.data.setdefault(series, [None] * n)[index[period]] = value
        release = con.execute("SELECT name, url, published_at, latest_period FROM source_release WHERE source_id = ?", [boj.SOURCE_ID]).fetchone()
        self.source = {"name": release[0], "url": release[1], "published_at": release[2].isoformat() if release[2] else None,
                       "latest_period": release[3]}
        self._cache: dict[tuple, dict | None] = {}

    def position(self, sector: str, side: str, code: str) -> dict | None:
        """One sector's holdings (assets) or debts (liabilities) of an instrument, or None if not published."""
        key = (sector, side, code)
        if key not in self._cache:
            self._cache[key] = self._position(sector, side, code)
        return self._cache[key]

    def _position(self, sector: str, side: str, code: str) -> dict | None:
        n = len(self.periods)
        if code == "F" and side == "liabilities":
            # The published total includes the difference between assets and liabilities; add up the lines instead.
            parts = [p for item in TOP if (p := self.position(sector, side, item))]
            if not parts:
                return None
            return {"series": "computed", **{measure: [
                None if all(p[measure][i] is None for p in parts) else sum(p[measure][i] or 0.0 for p in parts) for i in range(n)]
                for measure in ("level", "transactions", "other_change")}}
        level = self.data.get(series_id("level", sector, side, code))
        if level is None or all(value is None for value in level):
            return None
        transactions = self.data.get(series_id("transactions", sector, side, code), [None] * n)
        published = self.data.get(series_id("other_change", sector, side, code), [None] * n)
        other = [
            published[i] if published[i] is not None
            else None if i == 0 or None in (level[i], level[i - 1], transactions[i]) else level[i] - level[i - 1] - transactions[i]
            for i in range(n)
        ]
        return {"series": series_id("level", sector, side, code), "level": level, "transactions": transactions, "other_change": other}

    def children(self, sector: str, side: str, code: str) -> list[str]:
        """The breakdown of a line: the published parts, if they add up to it in every quarter."""
        whole = self.position(sector, side, code)
        found = [(part, position) for part in CHILDREN.get(code, ()) if (position := self.position(sector, side, part))]
        if whole is None or len(found) < 2:
            return []
        for i, total in enumerate(whole["level"]):
            if total is None:
                continue
            if abs(sum(position["level"][i] or 0.0 for _, position in found) - total) > TOLERANCE * len(found):
                return []
        return [part for part, _ in found]


def _node(accounts: Accounts, sector: str, side: str, code: str, name: str | None = None) -> dict | None:
    position = accounts.position(sector, side, code)
    if position is None:
        return None
    children = [_node(accounts, sector, side, part) for part in (TOP if code == "F" else accounts.children(sector, side, code))]
    children = [child for child in children if child is not None]
    return {
        **position,
        "name": name or NAMES[code],
        "basis": _basis(code),
        "instrument": code if code in INSTRUMENTS else None,
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
        "economy": "jp",
        "part_of": PART_OF.get(sector_id),
        "unit": "JPY millions",
        "periods": accounts.periods,
        "assets": assets,
        "liabilities": liabilities,
        "source": {**accounts.source, "table": f"sector {sector_id[1:]} {ALL_NAMES[sector_id]}"},
        "notes": {
            "structure": "Lines are the Bank of Japan's transaction items. A breakdown is shown only where its parts add up "
                         "to the line in every quarter. Amounts are in yen. Investment trust shares are shown beside "
                         "equity rather than inside debt securities.",
            "liabilities": "Total liabilities are the sum of the lines. The Bank's own total for this side also includes "
                           "the difference between financial assets and liabilities, which is not a debt."
                           + (" The rest of the world's assets are claims on Japan; its liabilities are Japan's claims abroad."
                              if sector_id == ROW[0] else ""),
            "other_change": "Valuation & other is the Bank of Japan's reconciliation between flows and stocks: price and "
                            "exchange-rate changes, plus reclassifications. " + BREAK_NOTE,
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
        out.append({"id": code, "name": NAMES[code], "has_issuers": True, "part_of": COMPOSITE_PARTS.get(code),
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
        if position is None or not any(position["level"]):
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
            listed = []
            for member in members:
                listed.append(member)
                listed += [r for part, _ in PARTS.get(member["code"], ()) if (r := row(part, name, group_id, part_of=member["code"]))]
            groups.append({"id": group_id, "name": group_name, **_total(members, n), "sectors": listed})
        return {"series": f"sum of {len(rows)} sectors", "excludes_discrepancy": False, **_total(rows, n), "groups": groups}

    holders, issuers = side("assets"), side("liabilities")
    gap = [None if None in (h, i) else h - i for h, i in zip(holders["level"], issuers["level"])]
    return {
        "id": instrument_id,
        "name": NAMES[instrument_id],
        "economy": "jp",
        "unit": "JPY millions",
        "periods": accounts.periods,
        "group_order": [group_id for group_id, _ in GROUPS],
        "group_notes": "Banks includes Japan Post Bank and cooperative banks. Other financial institutions includes public "
                       "lenders such as the Fiscal Loan Fund.",
        "holders": holders,
        "issuers": issuers,
        "discrepancy": {"series": "holders less issuers (computed)", "level": gap},
        "who_to_whom": False,
        "source": {**accounts.source, "table": f"item {instrument_id[1:]} {NAMES[instrument_id]}"},
        "notes": {
            "sides": "Holders report this instrument as an asset; issuers owe it as a liability. Both sides include the "
                     "rest of the world, so the two totals match.",
            "other_change": "Valuation & other is the Bank of Japan's reconciliation between flows and stocks: price and "
                            "exchange-rate changes, plus reclassifications. " + BREAK_NOTE + " A negative holding is a net "
                            "short position, as securities dealers often have in government bonds, or, for pension "
                            "funds' claims on their sponsors, a plan with more assets than obligations.",
            "coverage": "Sector-level aggregates for Japan, in yen; no individual institutions. Which holder holds which "
                        "issuer's paper is not recorded.",
            "issuers": None,
        },
    }
