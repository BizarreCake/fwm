"""Who holds US Treasury securities: sector-level positions and transactions from Z.1.

Source table: F3.2 "Treasury securities" (levels in F3.2.s, unadjusted quarterly
transactions in F3.2.t_tu). Three things about this table shape everything below:

* The issuer side (federal government liability) is at face value; holder
  positions are at market value. The gap is published as an explicit
  "instrument discrepancy" line, so holders + discrepancy == liability exactly.
* Transactions are published; revaluations are not. We derive
  ``other_change = Δlevel - transactions``, which is mostly price change but
  also includes any reclassifications / other volume changes.
* Only marketable securities are allocated to holders. Nonmarketable debt
  (savings bonds, state and local series, etc.) is a separate memo line.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

INSTRUMENT = "us_treasury_marketable"
START = "1952-03-31"  # Z.1 is annual before 1952; quarterly changes need quarterly data.

# 9-digit Z.1 codes (sector + instrument); the two-letter prefix selects the measure.
LIABILITY = "313161105"
BILLS_LIABILITY = "313161110"
ALL_HOLDERS = "893061105"
DISCREPANCY = "903061103"
NONMARKETABLE = "313169205"


@dataclass(frozen=True)
class Sector:
    code: str
    name: str


@dataclass(frozen=True)
class Group:
    id: str
    name: str
    note: str
    sectors: tuple[Sector, ...]


# Display groups. Every holder line of F3.2 belongs to exactly one group; the
# reconciliation test fails if the Fed adds a holder line we have not mapped.
GROUPS: tuple[Group, ...] = (
    Group("fed", "Federal Reserve", "System Open Market Account holdings.", (
        Sector("713061103", "Federal Reserve"),
    )),
    Group("row", "Rest of the world", "Foreign official and private holders.", (
        Sector("263061105", "Rest of the world"),
    )),
    Group("banks", "Banks & credit unions", "Depository institutions.", (
        Sector("763061100", "U.S.-chartered depository institutions"),
        Sector("753061103", "Foreign banking offices in the U.S."),
        Sector("743061103", "Banks in U.S.-affiliated areas"),
        Sector("473061105", "Credit unions"),
    )),
    Group("mmf", "Money market funds", "Reported at amortised cost, not market value.", (
        Sector("633061105", "Money market funds"),
    )),
    Group("funds", "Mutual funds & ETFs", "Long-term investment funds.", (
        Sector("653061105", "Mutual funds"),
        Sector("563061103", "Exchange-traded funds"),
        Sector("553061103", "Closed-end funds"),
    )),
    Group("pensions_insurers", "Pensions & insurers", "Retirement funds and insurance companies.", (
        Sector("573061105", "Private pension funds"),
        Sector("223061143", "State & local government pension funds"),
        Sector("343061105", "Federal government pension funds"),
        Sector("543061105", "Life insurers"),
        Sector("513061105", "Property-casualty insurers"),
    )),
    Group("households", "Households & nonprofits",
          "Largely a residual in Z.1, so it absorbs measurement error from other sectors.", (
        Sector("153061105", "Households & nonprofit organizations"),
    )),
    Group("other", "Other domestic", "Governments, businesses, dealers and other financial firms.", (
        Sector("213061103", "State & local governments"),
        Sector("663061105", "Security brokers & dealers"),
        Sector("403061105", "Government-sponsored enterprises"),
        Sector("103061103", "Nonfinancial corporate business"),
        Sector("733061103", "Holding companies"),
        Sector("623061103", "Hedge funds (domestic, net of shorts)"),
        Sector("503061123", "Central clearing counterparties"),
        Sector("113061003", "Nonfinancial noncorporate business"),
        Sector("673061103", "Issuers of asset-backed securities"),
    )),
)


def _load(con: duckdb.DuckDBPyConnection) -> tuple[list[tuple], dict[str, dict]]:
    """Return (periods, {code: {'level': [...], 'tx': [...], 'level_id':..., 'basis':...}})."""
    periods = con.execute(
        """
        SELECT DISTINCT period, period_end FROM z1_observations
        WHERE series_id = ? AND period_end >= CAST(? AS DATE) ORDER BY period_end
        """,
        [f"FL{LIABILITY}.Q", START],
    ).fetchall()
    index = {label: i for i, (label, _) in enumerate(periods)}

    rows = con.execute(
        """
        SELECT s.series_id, s.unit, o.period, o.value
        FROM z1_series s JOIN z1_observations o USING (series_id)
        WHERE s.table_id IN ('F3_2_s', 'F3_2_t_tu') AND o.period_end >= CAST(? AS DATE)
        """,
        [START],
    ).fetchall()

    data: dict[str, dict] = {}
    for series_id, unit, period, value in rows:
        prefix, code = series_id[:2], series_id[2:11]
        entry = data.setdefault(code, {"level": [None] * len(periods), "tx": [None] * len(periods)})
        if prefix in ("FL", "LM"):
            entry["level"][index[period]] = value
            entry["level_series"] = series_id
            entry["basis"] = "market" if prefix == "LM" else "book"
        elif prefix == "FU":
            entry["tx"][index[period]] = value
            entry["tx_series"] = series_id
    return periods, data


def _other_change(level: list, tx: list) -> list:
    """Change in level not explained by transactions (valuation + other volume changes)."""
    out: list = [None]
    for i in range(1, len(level)):
        if level[i] is None or level[i - 1] is None or tx[i] is None:
            out.append(None)
        else:
            out.append(level[i] - level[i - 1] - tx[i])
    return out


def _sum(series: list[list]) -> list:
    return [sum(v or 0 for v in column) for column in zip(*series)]


def _measures(level: list, tx: list) -> dict:
    return {"level": level, "transactions": tx, "other_change": _other_change(level, tx)}


def holders(con: duckdb.DuckDBPyConnection) -> dict:
    """Treasury holdings by holder group over time, with provenance."""
    from fwm.sectors import sector_for_series

    periods, data = _load(con)

    def series(code: str) -> dict:
        return data[code]

    groups = []
    for group in GROUPS:
        sectors = []
        for sector in group.sectors:
            entry = series(sector.code)
            level = [v or 0 for v in entry["level"]]
            tx = [v or 0 for v in entry["tx"]]
            sectors.append({
                "sector_id": sector_for_series(con, entry["level_series"]),
                "code": sector.code,
                "name": sector.name,
                "basis": entry["basis"],
                "level_series": entry["level_series"],
                "transactions_series": entry["tx_series"],
                **_measures(level, tx),
            })
        level = _sum([s["level"] for s in sectors])
        tx = _sum([s["transactions"] for s in sectors])
        groups.append({
            "id": group.id,
            "name": group.name,
            "note": group.note,
            **_measures(level, tx),
            "sectors": sectors,
        })

    release = con.execute(
        "SELECT name, url, published_at, ingested_at, latest_period FROM source_release WHERE source_id = 'fed_z1'"
    ).fetchone()

    def totals(code: str) -> dict:
        entry = series(code)
        return {"series": entry["level_series"], **_measures(entry["level"], entry["tx"])}

    return {
        "instrument": INSTRUMENT,
        "unit": "USD millions",
        "periods": [label for label, _ in periods],
        "period_ends": [end.isoformat() for _, end in periods],
        "groups": groups,
        "totals": {
            "liability_face": totals(LIABILITY),
            "bills_face": totals(BILLS_LIABILITY),
            "holders_market": totals(ALL_HOLDERS),
            "valuation_gap": totals(DISCREPANCY),
            "nonmarketable_face": {"series": series(NONMARKETABLE)["level_series"],
                                   "level": series(NONMARKETABLE)["level"]},
        },
        "source": {
            "name": release[0],
            "url": release[1],
            "table": "F3.2 Treasury securities",
            "published_at": release[2].isoformat() if release[2] else None,
            "ingested_at": release[3].isoformat(),
            "latest_period": release[4],
        },
        "notes": {
            "valuation": "Holder positions are at market value; the amount outstanding is at face value. "
                         "The difference is the valuation gap.",
            "other_change": "Change in holdings not explained by transactions: mostly price changes, "
                            "plus any reclassifications. Derived as change in level minus transactions.",
            "coverage": "Marketable Treasury securities only. Sector-level; no individual institutions.",
        },
    }


def mapped_codes() -> set[str]:
    return {sector.code for group in GROUPS for sector in group.sectors}
