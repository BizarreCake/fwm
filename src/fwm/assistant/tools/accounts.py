"""Tools over one economy's accounts: sectors, instruments, series over time, the overview and the system map."""

from __future__ import annotations

import re

import duckdb

from fwm import economies
from fwm.assistant.tools.common import (
    ToolError,
    _bn,
    _context,
    _economy,
    _index,
    _measures,
    _pct,
    _span,
)
from fwm.economies.ea import accounts as euroarea
from fwm.economies.jp import accounts as japan
from fwm.economies.us import sectors
from fwm.views import overview, systemmap


def list_instruments(con: duckdb.DuckDBPyConnection, economy: str = economies.DEFAULT) -> dict:
    e = _economy(con, economy)
    rows = e["instruments"].list_instruments(con)
    return {
        "economy": e["name"],
        "unit": f"{e['unit']}, latest quarter",
        "instruments": [
            {"id": row["id"], "name": row["name"], "amount_held": _bn(row["holders_total"])} for row in rows
        ],
        "link": e["home"],
    }


def list_sectors(con: duckdb.DuckDBPyConnection, economy: str = economies.DEFAULT) -> dict:
    e = _economy(con, economy)
    return {
        "economy": e["name"],
        "unit": f"{e['unit']}, latest quarter",
        "sectors": [
            {"id": row["id"], "name": row["name"], "total_financial_assets": _bn(row["total_assets"]),
             "total_liabilities": _bn(row["total_liabilities"]),
             **({"part_of": row["part_of"]} if row.get("part_of") else {})}
            for row in e["sectors"].list_sectors(con)
        ],
        "link": e["home"],
    }


def get_instrument(con: duckdb.DuckDBPyConnection, instrument_id: str, period: str | None = None,
                   compare_to: str | None = None, economy: str = economies.DEFAULT) -> dict:
    e = _economy(con, economy)
    view = e["instruments"].view(con, instrument_id)
    if view is None:
        raise ToolError(f"No instrument page {instrument_id!r} for {e['name']}. Call list_instruments with this economy for valid ids.")
    periods = view["periods"]
    i = _index(periods, period)
    j = _index(periods, compare_to, "compare_to") if compare_to else None

    def side(data: dict | None) -> dict | None:
        if data is None:
            return None
        total = data["level"][i]
        groups = []
        for group in data["groups"]:
            entry = {"group": group["name"], "group_id": group["id"], **_measures(group, i, j, total), "sectors": [
                {"sector": sector["name"], "sector_id": sector["sector_id"], "series": sector["series"],
                 **({"part_of": sector["part_of"], "reading": "A part of that sector, already counted in it."}
                    if sector.get("part_of") else {}),
                 "basis": sector["basis"], **_measures(sector, i, j, total)}
                for sector in sorted(group["sectors"], key=lambda s: -(s["level"][i] or 0))
            ]}
            groups.append(entry)
        groups.sort(key=lambda g: -(g["amount"] or 0))
        return {"total": {"series": data["series"], **_measures(data, i, j, None)}, "groups": groups}

    discrepancy = view.get("discrepancy")
    return {
        "instrument": view["name"],
        "instrument_id": view["id"],
        "economy": e["name"],
        **_span(i, j, periods),
        "unit": e["unit"],
        "holders": side(view["holders"]),
        "issuers": side(view["issuers"]),
        "discrepancy": _bn(discrepancy["level"][i]) if discrepancy else None,
        "notes": [note for note in (view["notes"].get("sides"), view["notes"].get("issuers"), view.get("group_notes")) if note],
        "source": view["source"]["table"],
        "link": f"#/{economy}/instrument/{view['id']}?period={periods[i]}",
    }


def get_sector(con: duckdb.DuckDBPyConnection, sector_id: str, period: str | None = None,
               compare_to: str | None = None, economy: str = economies.DEFAULT) -> dict:
    e = _economy(con, economy)
    view = e["sectors"].balance_sheet(con, sector_id)
    if view is None:
        raise ToolError(f"No sector page {sector_id!r} for {e['name']}. Call list_sectors with this economy for valid ids.")
    periods = view["periods"]
    i = _index(periods, period)
    j = _index(periods, compare_to, "compare_to") if compare_to else None

    def lines(root: dict | None) -> dict | None:
        if root is None:
            return None
        total = root["level"][i]
        out = []

        def walk(node: dict, depth: int, memo: bool) -> None:
            if node["level"][i] is None and (j is None or node["level"][j] is None):
                return
            out.append({
                "line": node["name"], "depth": depth, **({"of_which": True} if memo else {}),
                "series": node["series"], "basis": node["basis"], "instrument_id": node["instrument"],
                **_measures(node, i, j, total),
            })
            for child in node["children"]:
                walk(child, depth + 1, False)
            for child in node["memos"]:
                walk(child, depth + 1, True)

        for child in root["children"]:
            walk(child, 0, False)
        return {"total": {"line": root["name"], "series": root["series"], **_measures(root, i, j, None)}, "lines": out}

    return {
        "sector": view["name"],
        "sector_id": view["id"],
        "economy": e["name"],
        **_span(i, j, periods),
        "unit": e["unit"],
        "reading": "Lines at depth 0 add up to the total; deeper lines add up to the line above them. "
                   "Lines marked of_which are subsets, not additional amounts. Financial assets only: no real estate or equipment.",
        "assets": lines(view["assets"]),
        "liabilities": lines(view["liabilities"]),
        "notes": [note for note in (view["notes"].get("liabilities"),) if note],
        "source": view["source"]["table"],
        "link": f"#/{economy}/sector/{view['id']}?period={periods[i]}",
    }


def _history_rows(periods: list[str], picks: list[int], level: list, flow: list, other: list, gdp: list | None) -> list[dict]:
    rows = []
    previous = None
    for k in picks:
        window = range((previous + 1) if previous is not None else k, k + 1)
        flows = [flow[q] for q in window]
        others = [other[q] for q in window]
        row = {
            "period": periods[k],
            "amount": _bn(level[k]),
            "net_transactions": _bn(sum(flows)) if all(v is not None for v in flows) else None,
            "valuation_and_other": _bn(sum(others)) if all(v is not None for v in others) else None,
        }
        if gdp is not None:
            row["amount_pct_of_gdp"] = _pct(level[k], gdp[k])
        rows.append(row)
        previous = k
    return rows


def _japan_history(con: duckdb.DuckDBPyConnection, series: list[str], start: str | None, end: str | None, frequency: str,
                   share_of_gdp: bool = False) -> dict:
    periods = japan.periods(con)
    i = _index(periods, end, "end")
    j = _index(periods, start, "start") if start else max(0, i - 40)
    if j > i:
        raise ToolError("start must not be after end")
    if frequency not in ("auto", "quarterly", "annual"):
        raise ToolError("frequency must be auto, quarterly or annual")
    annual = frequency == "annual" or (frequency == "auto" and i - j > 48)
    picks = [k for k in range(j, i + 1) if not annual or periods[k].endswith("Q4") or k == i]
    accounts = japan.Accounts(con)
    gdp = economies.context("jp").gdp(con, periods) if share_of_gdp else None
    out = []
    for series_id in series:
        match = re.fullmatch(r"FOF_FFAS(\d{3})([AL])(\d{3})", series_id)
        if not match or series_id not in accounts.data:
            raise ToolError(f"{series_id!r} is not a Japanese series id as returned by get_instrument or get_sector")
        sector, side = f"S{match.group(1)}", "assets" if match.group(2) == "A" else "liabilities"
        code = "F" if match.group(3) == "900" else f"I{match.group(3)}"
        position = accounts.position(sector, side, code)
        out.append({"series": series_id,
                    "description": f"{japan.ALL_NAMES.get(sector, sector)}: {japan.NAMES.get(code, code).lower()}, {side}",
                    "basis": japan._basis(code),
                    "observations": _history_rows(periods, picks, position["level"], position["transactions"], position["other_change"], gdp)})
    return {"unit": "JPY billions", "frequency": "annual (year-end amounts; flows summed over the year)" if annual else "quarterly",
            "series": out, "caveats": ["Amounts are in yen and are not converted.",
                                       "Valuation and other is the Bank of Japan's reconciliation between flows and stocks."]}


def get_history(con: duckdb.DuckDBPyConnection, series: list[str], start: str | None = None, end: str | None = None,
                frequency: str = "auto", share_of_gdp: bool = False) -> dict:
    """Levels, flows and valuation changes of up to six series over time."""
    if not series or len(series) > 6:
        raise ToolError("Pass between one and six series ids, as returned by get_instrument or get_sector.")
    yen = [series_id.startswith("FOF_") for series_id in series]
    if any(yen):
        if not all(yen):
            raise ToolError("Pass series from one economy at a time: amounts are in different currencies.")
        _context(con, "jp") if share_of_gdp else _economy(con, "jp")
        return _japan_history(con, series, start, end, frequency, share_of_gdp)
    euro = [series_id.startswith("QSA.") for series_id in series]
    if any(euro):
        if not all(euro):
            raise ToolError("Pass series from one economy at a time: US and euro-area amounts are in different currencies.")
        _context(con, "ea") if share_of_gdp else _economy(con, "ea")
    economy = "ea" if any(euro) else "us"
    periods = economies.periods(con, economy)
    index = {label: k for k, label in enumerate(periods)}
    i = _index(periods, end, "end")
    j = _index(periods, start, "start") if start else max(0, i - 40)
    if j > i:
        raise ToolError("start must not be after end")
    if frequency not in ("auto", "quarterly", "annual"):
        raise ToolError("frequency must be auto, quarterly or annual")
    annual = frequency == "annual" or (frequency == "auto" and i - j > 48)
    picks = [k for k in range(j, i + 1) if not annual or periods[k].endswith("Q4") or k == i]
    gdp = economies.context(economy).gdp(con, periods) if share_of_gdp else None

    out = []
    for series_id in series if any(euro) else ():
        # An ECB key names its measure in the tenth position: LE amounts, F transactions, K other changes.
        parts = series_id.split(".")
        if len(parts) != 19 or parts[9] != "LE":
            raise ToolError(f"{series_id!r} is not a euro-area series id as returned by get_instrument or get_sector")
        keys = {measure: ".".join([*parts[:9], code, *parts[10:]]) for measure, code in (("level", "LE"), ("flow", "F"), ("other", "K"))}
        values = {measure: [None] * len(periods) for measure in keys}
        found = con.execute("SELECT key, period, value FROM qsa_observations WHERE key IN (?, ?, ?)", list(keys.values())).fetchall()
        if not any(key == series_id for key, _, _ in found):
            raise ToolError(f"Unknown series {series_id}")
        by_key = {key: measure for measure, key in keys.items()}
        for key, period, value in found:
            if period in index:
                values[by_key[key]][index[period]] = value
        level, flow = values["level"], values["flow"]
        # The ECB publishes other changes; where a quarter lacks them, they are the change that transactions do not explain.
        derived = sectors._other_change(level, flow)
        other = [values["other"][k] if values["other"][k] is not None else derived[k] for k in range(len(periods))]
        described = f"{euroarea.ALL_NAMES.get(parts[5], parts[5])}: {euroarea.NAMES.get(parts[10], parts[10]).lower()}, " \
                    f"{'assets' if parts[8] == 'A' else 'liabilities'}" + (", against the rest of the world" if parts[4] == "W1" else "") \
                    + (f", against {euroarea.ALL_NAMES.get(parts[6], parts[6]).lower()}" if parts[4] == "W2" else "")
        out.append({"series": series_id, "description": described,
                    "basis": "market" if parts[10].startswith(euroarea.MARKET_VALUED) else "book",
                    "observations": _history_rows(periods, picks, level, flow, other, gdp)})
    for series_id in () if any(euro) else series:
        if not re.fullmatch(r"[A-Z]{2}\d{9}\.Q", series_id):
            raise ToolError(f"{series_id!r} is not a Z.1 series id such as LM263061105.Q")
        described = con.execute("SELECT any_value(description) FROM z1_series WHERE series_id = ?", [series_id]).fetchone()[0]
        if described is None:
            raise ToolError(f"Unknown series {series_id}")
        level = [None] * len(periods)
        flow = [None] * len(periods)
        for sid, period, value in con.execute(
            "SELECT series_id, period, value FROM z1_observations WHERE series_id IN (?, ?) AND period LIKE '%:Q%'",
            [series_id, f"FU{series_id[2:]}"],
        ).fetchall():
            if period in index:
                (level if sid == series_id else flow)[index[period]] = value
        other = sectors._other_change(level, flow)
        out.append({"series": series_id, "description": described,
                    "basis": "market" if series_id.startswith("LM") else "book",
                    "observations": _history_rows(periods, picks, level, flow, other, gdp)})
    return {
        "unit": "EUR billions" if any(euro) else "USD billions",
        "frequency": "annual (fourth-quarter amounts; flows summed since the previous row)" if annual else "quarterly",
        "series": out,
    }


def latest_moves(con: duckdb.DuckDBPyConnection, kind: str = "unusual_flows", economy: str = economies.DEFAULT) -> dict:
    if kind not in ("unusual_flows", "largest_flows", "valuation_changes"):
        raise ToolError("kind must be unusual_flows, largest_flows or valuation_changes")
    e = _economy(con, economy)
    view = overview.load(con, economy) or overview.compute(con, economy)
    symbol = economies.ECONOMIES[economy]["symbol"]
    return {
        "economy": e["name"],
        "period": view["period"],
        "kind": kind,
        "unit": e["unit"],
        "definition": {
            "unusual_flows": "Net transactions more than 2.5 standard deviations from that position's own average "
                             f"over the previous ten years and at least {symbol}20B, largest first. Current prices.",
            "largest_flows": "Largest net transactions by absolute size.",
            "valuation_changes": "Largest changes in holdings that were not transactions (mostly price changes).",
        }[kind],
        "moves": [
            {"sector": move["sector"], "sector_id": move["sector_id"], "side": move["side"],
             "instrument": move["instrument"], "instrument_id": move["instrument_id"], "series": move["series"],
             "amount": _bn(move["amount"]), "amount_outstanding": _bn(move["level"]),
             "standard_deviations_from_norm": None if move["score"] is None else round(move["score"], 1),
             "largest_since": move["largest_since"]}
            for move in view[kind]
        ],
        "only_available_for": "the latest quarter",
        "link": e["home"],
    }


def get_system_map(con: duckdb.DuckDBPyConnection, period: str | None = None, economy: str = economies.DEFAULT) -> dict:
    e = _economy(con, economy)
    view = systemmap.load(con, economy) or systemmap.compute(con, economy)
    i = _index(view["periods"], period)
    names = {group["id"]: group["name"] for group in view["groups"]}

    def row(values: dict) -> dict:
        return {names[g]: _bn(v[i]) for g, v in values.items() if abs(v[i]) >= 50}

    return {
        "economy": e["name"],
        "period": view["periods"][i],
        "unit": e["unit"],
        "families": [
            {"family": family["name"], "instrument_id": family["instrument_id"],
             "owed_by": row(family["issuers"]), "held_by": row(family["holders"])}
            for family in view["families"]
        ],
        "reading": view["notes"]["reading"],
        "not_covered": view["notes"]["coverage"],
        "link": e["home"],
    }


def get_who_holds_whose(con: duckdb.DuckDBPyConnection, instrument_id: str, period: str | None = None,
                        compare_to: str | None = None) -> dict:
    """Euro area only: what each sector holds of each sector's paper."""
    _economy(con, "ea")
    view = euroarea.who_to_whom(con, instrument_id)
    if view is None:
        raise ToolError(f"No counterpart detail for {instrument_id!r}. Available: {', '.join(euroarea.WHO_TO_WHOM)}.")
    periods = view["periods"]
    i = _index(periods, period)
    j = _index(periods, compare_to, "compare_to") if compare_to else None
    first = periods.index(view["first_period"])
    if min(i, j if j is not None else i) < first:
        raise ToolError(f"Counterpart detail for this instrument starts in {view['first_period']}.")
    names = {sector_id: info["name"] for sector_id, info in view["sectors"].items()}
    cells = [(holder, issuer, cell) for holder, row in view["matrix"].items() for issuer, cell in row.items()
             if cell["level"][i] is not None]
    total = sum(cell["level"][i] for _, _, cell in cells)
    pairs = [
        {"holder": names[holder], "holder_id": holder, "issuer": names[issuer], "issuer_id": issuer,
         "series": cell["series"], **({"computed_as_remainder": True} if cell["computed"] else {}), **_measures(cell, i, j, total)}
        for holder, issuer, cell in sorted(cells, key=lambda c: -abs(c[2]["level"][i]))
        if abs(cell["level"][i]) >= 1000
    ][:30]

    def totals(position: int) -> list[dict]:
        sums: dict[str, float] = {}
        for cell in cells:
            sums[cell[position]] = sums.get(cell[position], 0.0) + cell[2]["level"][i]
        return [{"sector": names[s], "sector_id": s, "amount": _bn(v), "share_pct": _pct(v, total)}
                for s, v in sorted(sums.items(), key=lambda kv: -kv[1])]

    return {
        "instrument": view["name"],
        "instrument_id": view["id"],
        "covers": view["covers"],
        "economy": "Euro area",
        **_span(i, j, periods),
        "unit": "EUR billions",
        "reading": "Each pair is what the holder holds of what the issuer owes. share_pct is of the whole instrument. "
                   "The 30 largest pairs are listed; by_holder and by_issuer cover everything.",
        "total": _bn(total),
        "by_holder": totals(0),
        "by_issuer": totals(1),
        "pairs": pairs,
        "notes": [view["notes"]["rest_of_world"], view["notes"]["coverage"]],
        "source": view["source"]["table"],
        "link": f"#/ea/instrument/{view['id']}?period={periods[i]}",
    }
