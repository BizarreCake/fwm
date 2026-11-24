"""What moved in the latest quarter, across every instrument and sector.

For each sector position in each instrument we compare the latest quarter's net
transactions with that position's own history. A flow is "unusual" when it is
far from what that position normally does, not merely when it is large: its
distance from the position's ten-year mean must exceed a threshold, measured in
standard deviations. Among those, the largest come first, so that a small flow
in a normally dormant series does not outrank a large one.
Valuation changes are ranked separately, since a price move is a different kind
of event from a purchase.

The result is computed once per ingest and stored, because it reads every
instrument table.
"""

from __future__ import annotations

import json
import statistics

import duckdb

from fwm import economies

WINDOW = 40          # quarters of history a flow is compared with
MIN_HISTORY = 20     # quarters of history needed to score a flow at all
MIN_FLOW = 20_000    # millions of the economy's currency; smaller flows are not reported as notable
UNUSUAL = 2.5        # standard deviations from the position's own norm
TOP = 12


def _is_composite(instrument_id: str, all_ids: list[str]) -> bool:
    """A table that is the sum of other listed tables (F3 "Debt securities" over F3.1 to F3.5)."""
    return any(other != instrument_id and other.startswith(instrument_id) for other in all_ids)


def _since(series: list, i: int) -> str | None:
    """Index of the most recent earlier quarter with a move at least this large in the same direction."""
    now = series[i]
    for j in range(i - 1, -1, -1):
        past = series[j]
        if past is not None and (past >= now if now > 0 else past <= now):
            return j
    return None


def _score(series: list, i: int) -> float | None:
    history = [v for v in series[max(0, i - WINDOW):i] if v is not None]
    if len(history) < MIN_HISTORY:
        return None
    spread = statistics.pstdev(history)
    if spread == 0:
        return None
    return (series[i] - statistics.fmean(history)) / spread


def _key(economy: str) -> str:
    return "overview" if economy == economies.DEFAULT else f"overview:{economy}"


def compute(con: duckdb.DuckDBPyConnection, economy: str = economies.DEFAULT) -> dict:
    sectors, instruments = economies.accounts(economy)
    euro = economy == "ea"
    symbol = "€" if euro else "$"
    listed = instruments.list_instruments(con)
    ids = [instrument["id"] for instrument in listed]
    flows: list[dict] = []
    valuations: list[dict] = []
    index: list[dict] = []
    periods: list[str] = []

    for instrument in listed:
        view = instruments.view(con, instrument["id"])
        periods = view["periods"]
        last = len(periods) - 1
        composite = _is_composite(instrument["id"], ids)
        index.append({
            "id": instrument["id"],
            "name": instrument["name"],
            "composite": composite,
            "held": view["holders"]["level"][last],
            "transactions": view["holders"]["transactions"][last],
            "other_change": view["holders"]["other_change"][last],
        })
        if composite or "miscellaneous" in instrument["name"].lower() or instrument["name"].lower().startswith("other accounts"):
            continue  # sums of other tables, and residual categories that mostly carry measurement error
        for side_name in ("holders", "issuers"):
            side = view[side_name]
            if not side:
                continue
            for group in side["groups"]:
                # A sector published in parts is ranked by its parts, not also as a whole.
                split = {position.get("part_of") for position in group["sectors"]} - {None}
                for position in group["sectors"]:
                    if position["code"] in split:
                        continue
                    base = {
                        "instrument_id": instrument["id"],
                        "instrument": instrument["name"],
                        "side": side_name,
                        "sector": position["name"],
                        "sector_id": position["sector_id"],
                        "group": group["id"],
                        "series": position["series"],
                        "level": position["level"][last],
                    }
                    for measure, bucket in (("transactions", flows), ("other_change", valuations)):
                        if measure == "other_change" and side_name == "issuers":
                            continue
                        series = position[measure]
                        amount = series[last]
                        if amount is None or abs(amount) < MIN_FLOW:
                            continue
                        since = _since(series, last)
                        bucket.append({
                            **base,
                            "amount": amount,
                            "score": _score(series, last),
                            "largest_since": periods[since] if since is not None else None,
                            "history_from": periods[max(0, last - WINDOW)],
                            "history": series[max(0, last - WINDOW):],
                        })

    unusual = [flow for flow in flows if flow["score"] is not None and abs(flow["score"]) >= UNUSUAL]
    return {
        "period": periods[-1],
        "min_flow": MIN_FLOW,
        "window_quarters": WINDOW,
        "unusual_flows": sorted(unusual, key=lambda f: -abs(f["amount"]))[:TOP],
        "largest_flows": sorted(flows, key=lambda f: -abs(f["amount"]))[:TOP],
        "valuation_changes": sorted(valuations, key=lambda f: -abs(f["amount"]))[:TOP],
        "instruments": index,
        "sectors": sectors.list_sectors(con),
        "notes": {
            "unusual": f"Unusual means the quarter's net transactions are more than {UNUSUAL} standard deviations from "
                       f"that position's own average over the previous {WINDOW // 4} years. Largest first; flows "
                       f"under {symbol}{MIN_FLOW // 1000}B are left out.",
            "coverage": "Covers each sector's position in each instrument, from the ECB's quarterly sector accounts. "
                        "Left out of the rankings: other accounts, which are largely residuals. Central banks and "
                        "other banks are ranked separately, on their history from 2015. Amounts are in current "
                        "euro, so \"largest on record\" partly reflects growth in the size of the system."
                        if euro else
                        "Covers each sector's position in each instrument, from the Fed's Z.1 financial accounts. "
                        "Left out of the rankings: tables that are sums of other tables, which would count a flow "
                        "twice, and miscellaneous claims, which are largely residuals. Amounts are in current "
                        "dollars, so \"largest on record\" partly reflects growth in the size of the system.",
            "valuation": "Valuation & other is published by the ECB: mostly price and exchange-rate changes, plus "
                         "any reclassifications. Holders only."
                         if euro else
                         "Valuation & other is the change in level minus transactions: mostly price changes, plus "
                         "any reclassifications. Holders only.",
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
