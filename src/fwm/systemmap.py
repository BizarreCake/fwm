"""The whole system on one page: which sector groups owe, through which instruments, to which holders.

Instruments are gathered into a handful of families and sectors into the shared
groups, giving two matrices per quarter: amounts owed by group and family, and
amounts held by group and family. Both are sums of published sector positions.
Z.1 does not record which holder holds which issuer's paper, so the map joins
the two sides through the instrument and makes no holder-to-issuer claim.

A family is a signed combination of instrument tables. Subtraction is used where
a published total covers instruments whose own tables cannot be resolved: "other
loans" is all loans less repo and mortgages.
"""

from __future__ import annotations

import json

import duckdb

from fwm import economies, euroarea, instruments

# (id, name, page to open, tables with sign, counted as debt-like)
FAMILIES: tuple[tuple[str, str, str, tuple[tuple[str, int], ...], bool], ...] = (
    ("treasuries", "Treasury securities", "F3_2", (("F3_2", 1),), True),
    ("agency", "Agency & GSE securities", "F3_3", (("F3_3", 1),), True),
    ("other_debt", "Corporate, municipal & other debt", "F3_5", (("F3_1", 1), ("F3_4", 1), ("F3_5", 1)), True),
    ("repo", "Repo & federal funds", "F4_1", (("F4_1", 1),), True),
    ("mortgages", "Mortgages", "F4_5", (("F4_5", 1),), True),
    ("loans", "Other loans", "F4", (("F4", 1), ("F4_1", -1), ("F4_5", -1)), True),
    ("deposits", "Deposits & currency", "F2", (("F2", 1),), True),
    ("fund_shares", "Fund shares", "F522_1", (("F521", 1), ("F522_1", 1), ("F522_2", 1), ("F522_3", 1)), False),
    ("equities", "Corporate equities", "F51_1", (("F51_1", 1),), False),
    ("other_equity", "Other equity", "F519", (("F519", 1),), False),
    ("pensions_insurance", "Pensions & insurance", "F6_2", (("F6_1", 1), ("F6_2", 1)), False),
)
NOT_COVERED = "Trade credit, taxes payable, miscellaneous claims, and monetary gold and SDRs are not on the map."
# The euro area's accounts have fewer instrument tables, so its families are the instruments themselves.
EURO_FAMILIES: tuple[tuple[str, str, str, tuple[tuple[str, int], ...], bool], ...] = (
    ("debt_securities", "Debt securities", "F3", (("F3", 1),), True),
    ("loans", "Loans", "F4", (("F4", 1),), True),
    ("deposits", "Deposits & currency", "F2", (("F2", 1),), True),
    ("fund_shares", "Fund shares", "F52", (("F52", 1),), False),
    ("equities", "Equity", "F51", (("F51", 1),), False),
    ("pensions_insurance", "Insurance & pensions", "F6", (("F6", 1),), False),
)
EURO_NOT_COVERED = "Trade credit and other accounts, derivatives, and monetary gold and SDRs are not on the map."


def _key(economy: str) -> str:
    return "system_map" if economy == economies.DEFAULT else f"system_map:{economy}"


def compute(con: duckdb.DuckDBPyConnection, economy: str = economies.DEFAULT) -> dict:
    euro = economy == "ea"
    source = economies.accounts(economy)[1]
    family_list = EURO_FAMILIES if euro else FAMILIES
    groups = [(g[0], g[1]) for g in (euroarea.GROUPS if euro else instruments.GROUPS)]
    views: dict[str, dict] = {}
    for _, _, _, tables, _ in family_list:
        for table, _ in tables:
            if table not in views:
                view = source.view(con, table)
                if view is None or view["issuers"] is None:
                    raise RuntimeError(f"system map needs both sides of {table}, which did not resolve")
                views[table] = view
    periods = next(iter(views.values()))["periods"]
    n = len(periods)
    group_ids = [group_id for group_id, _ in groups]

    def matrix(tables: tuple[tuple[str, int], ...], side: str) -> dict[str, list[float]]:
        out = {group_id: [0.0] * n for group_id in group_ids}
        for table, sign in tables:
            for group in views[table][side]["groups"]:
                target = out[group["id"]]
                for i, value in enumerate(group["level"]):
                    target[i] += sign * (value or 0)
        return out

    families = []
    for family_id, name, page, tables, debt_like in family_list:
        families.append({
            "id": family_id,
            "name": name,
            "instrument_id": page,
            "debt_like": debt_like,
            "tables": [table for table, _ in tables],
            "issuers": matrix(tables, "issuers"),
            "holders": matrix(tables, "holders"),
        })
    return {
        "periods": periods,
        "unit": "EUR millions" if euro else "USD millions",
        "groups": [{"id": group_id, "name": name} for group_id, name in groups],
        "families": families,
        "notes": {
            "reading": "Left: what each sector group owes or has issued. Right: what each group holds. Band widths "
                       "are euro. The two sides meet at the instrument; the map does not say which holder holds "
                       "which issuer's paper.",
            "sides": "Both sides include the rest of the world, so amounts owed and held of each instrument match. "
                     "Banks & central banks includes money market funds.",
            "coverage": EURO_NOT_COVERED,
        } if euro else {
            "reading": "Left: what each sector group owes or has issued. Right: what each group holds. Band widths "
                       "are dollars. The two sides meet at the instrument; the map does not say which holder holds "
                       "which issuer's paper, because Z.1 does not record that.",
            "sides": "Amounts owed and held of the same instrument can differ: the sides are measured from different "
                     "sources and often on different bases (market vs. book value).",
            "coverage": NOT_COVERED,
        },
    }


def build(con: duckdb.DuckDBPyConnection, economy: str = economies.DEFAULT) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS computed (key VARCHAR PRIMARY KEY, value VARCHAR)")
    con.execute("DELETE FROM computed WHERE key = ?", [_key(economy)])
    con.execute("INSERT INTO computed VALUES (?, ?)", [_key(economy), json.dumps(compute(con, economy))])


def load(con: duckdb.DuckDBPyConnection, economy: str = economies.DEFAULT) -> dict | None:
    if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'computed'").fetchone()[0]:
        return None
    row = con.execute("SELECT value FROM computed WHERE key = ?", [_key(economy)]).fetchone()
    return json.loads(row[0]) if row else None
