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

from fwm import instruments

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


def compute(con: duckdb.DuckDBPyConnection) -> dict:
    views: dict[str, dict] = {}
    for _, _, _, tables, _ in FAMILIES:
        for table, _ in tables:
            if table not in views:
                view = instruments.view(con, table)
                if view is None or view["issuers"] is None:
                    raise RuntimeError(f"system map needs both sides of {table}, which did not resolve")
                views[table] = view
    periods = next(iter(views.values()))["periods"]
    n = len(periods)
    group_ids = [group_id for group_id, _, _ in instruments.GROUPS]

    def matrix(tables: tuple[tuple[str, int], ...], side: str) -> dict[str, list[float]]:
        out = {group_id: [0.0] * n for group_id in group_ids}
        for table, sign in tables:
            for group in views[table][side]["groups"]:
                target = out[group["id"]]
                for i, value in enumerate(group["level"]):
                    target[i] += sign * (value or 0)
        return out

    families = []
    for family_id, name, page, tables, debt_like in FAMILIES:
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
        "unit": "USD millions",
        "groups": [{"id": group_id, "name": name} for group_id, name, _ in instruments.GROUPS],
        "families": families,
        "notes": {
            "reading": "Left: what each sector group owes or has issued. Right: what each group holds. Band widths "
                       "are dollars. The two sides meet at the instrument; the map does not say which holder holds "
                       "which issuer's paper, because Z.1 does not record that.",
            "sides": "Amounts owed and held of the same instrument can differ: the sides are measured from different "
                     "sources and often on different bases (market vs. book value).",
            "coverage": NOT_COVERED,
        },
    }


def build(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS computed (key VARCHAR PRIMARY KEY, value VARCHAR)")
    con.execute("DELETE FROM computed WHERE key = 'system_map'")
    con.execute("INSERT INTO computed VALUES ('system_map', ?)", [json.dumps(compute(con))])


def load(con: duckdb.DuckDBPyConnection) -> dict | None:
    row = con.execute("SELECT value FROM computed WHERE key = 'system_map'").fetchone()
    return json.loads(row[0]) if row else None
