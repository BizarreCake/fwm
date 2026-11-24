"""The agent's tools: the same queries the pages use, shaped for a model to read.

Every function takes a read-only DuckDB connection and plain arguments and
returns a JSON-serialisable dict. Amounts are in billions of US dollars. Each
result carries the Z.1 series ids behind its numbers and a `link` to the page
that shows the same thing, so an answer can cite and point.

A ToolError carries a message meant for the model: what was wrong and what to do instead.
"""

from __future__ import annotations

import re
from typing import Any

import duckdb

from fwm import compare, context, countries, links, eacontext, economies, euroarea, euweekly, fedweekly, tic, instruments, overview, sectors, systemmap

GAP_CATEGORIES = {
    "counterparty": "Which holder holds which issuer's paper, or who lends to whom. Z.1 has each side's totals only.",
    "entity": "A specific institution, fund or security, or a country for anything other than securities holdings to and from "
              "the US. Apart from those, everything here is a sector aggregate.",
    "frequency": "Anything more recent than the latest quarter, or finer than quarterly. Exceptions: daily rates, and the "
                 "Federal Reserve's own balance sheet, which is weekly.",
    "causation": "Why something happened. The data shows what changed, not the reason.",
    "detail": "Maturity, yield, credit quality, currency or other attributes of holdings that Z.1 does not break out.",
    "forecast": "What will happen next.",
    "coverage": "Another economy's own accounts (its households, banks, government, or its dealings with third countries), or anything else outside the US financial accounts, the Fed's weekly balance sheet, rates, GDP and the Fed announcement calendar.",
}

PERIOD = re.compile(r"^(\d{4}):?Q([1-4])$", re.IGNORECASE)


class ToolError(Exception):
    pass


def _bn(millions: float | None) -> float | None:
    return None if millions is None else round(millions / 1000, 1)


def _pct(part: float | None, whole: float | None) -> float | None:
    if part is None or not whole:
        return None
    return round(100 * part / whole, 1)


def _index(periods: list[str], period: str | None, what: str = "period") -> int:
    if period is None:
        return len(periods) - 1
    match = PERIOD.match(period.strip().replace(" ", ""))
    if not match:
        raise ToolError(f"{what} must look like 2024:Q3, got {period!r}")
    label = f"{match.group(1)}:Q{match.group(2)}"
    if label not in periods:
        raise ToolError(f"{what} {label} is outside the data, which runs {periods[0]} to {periods[-1]}")
    return periods.index(label)


def _measures(item: dict, i: int, j: int | None, total: float | None) -> dict:
    """One position at quarter i; if j is given, also how it changed from quarter j to quarter i."""
    out = {
        "amount": _bn(item["level"][i]),
        "share_pct": _pct(item["level"][i], total),
        "net_transactions_in_quarter": _bn(item["transactions"][i]),
        "valuation_and_other_in_quarter": _bn(item["other_change"][i]),
    }
    if j is not None:
        start, end = item["level"][j], item["level"][i]
        flows = item["transactions"][j + 1:i + 1]
        complete = start is not None and end is not None and all(v is not None for v in flows)
        out["change"] = {
            "amount_at_start": _bn(start),
            "change_in_amount": _bn(end - start) if start is not None and end is not None else None,
            "net_transactions": _bn(sum(flows)) if complete else None,
            "valuation_and_other": _bn(end - start - sum(flows)) if complete else None,
        }
    return out


def _span(i: int, j: int | None, periods: list[str]) -> dict:
    out: dict[str, Any] = {"period": periods[i]}
    if j is not None:
        if j >= i:
            raise ToolError("compare_to must be earlier than period")
        out["compared_to"] = periods[j]
        out["change_covers"] = f"the {i - j} quarters after {periods[j]}, through {periods[i]}"
    return out


def _economy(con: duckdb.DuckDBPyConnection, economy: str) -> dict:
    """What differs between economies for the sector and instrument tools."""
    if economy not in economies.ECONOMIES:
        raise ToolError(f"Unknown economy {economy!r}. Use one of: {', '.join(economies.ECONOMIES)}.")
    if economy == "ea" and not euroarea.available(con):
        raise ToolError("The euro area accounts are not loaded in this installation.")
    sector_module, instrument_module = economies.accounts(economy)
    info = economies.ECONOMIES[economy]
    return {"id": economy, "name": info["name"], "unit": f"{info['currency']} billions", "sectors": sector_module,
            "instruments": instrument_module, "home": "#/" if economy == economies.DEFAULT else f"#/{economy}"}


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


def get_history(con: duckdb.DuckDBPyConnection, series: list[str], start: str | None = None, end: str | None = None,
                frequency: str = "auto", share_of_gdp: bool = False) -> dict:
    """Levels, flows and valuation changes of up to six series over time."""
    if not series or len(series) > 6:
        raise ToolError("Pass between one and six series ids, as returned by get_instrument or get_sector.")
    euro = [series_id.startswith("QSA.") for series_id in series]
    if any(euro):
        if not all(euro):
            raise ToolError("Pass series from one economy at a time: US and euro-area amounts are in different currencies.")
        if share_of_gdp:
            raise ToolError("GDP is loaded for the United States only, so share_of_gdp is not available for euro-area series.")
        if not euroarea.available(con):
            raise ToolError("The euro area accounts are not loaded in this installation.")
    periods = euroarea.periods(con) if any(euro) else context.periods(con)
    index = {label: k for k, label in enumerate(periods)}
    i = _index(periods, end, "end")
    j = _index(periods, start, "start") if start else max(0, i - 40)
    if j > i:
        raise ToolError("start must not be after end")
    if frequency not in ("auto", "quarterly", "annual"):
        raise ToolError("frequency must be auto, quarterly or annual")
    annual = frequency == "annual" or (frequency == "auto" and i - j > 48)
    picks = [k for k in range(j, i + 1) if not annual or periods[k].endswith("Q4") or k == i]
    gdp = context.gdp(con, periods) if share_of_gdp else None

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
                    "observations": _history_rows(periods, picks, level, flow, other, None)})
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
    symbol = "€" if economy == "ea" else "$"
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


def compare_economies(con: duckdb.DuckDBPyConnection, period: str | None = None) -> dict:
    view = compare.view(con)
    if view is None:
        raise ToolError("Comparing economies needs the euro area accounts, which are not loaded in this installation.")
    periods = view["periods"]
    i = _index(periods, period)
    names = {economy["id"]: economy["name"] for economy in view["economies"]}

    def cell(measures: dict, economy: str) -> dict:
        usd, share = measures["usd"][i], measures["pct_of_gdp"][i]
        out = {"usd_billions": _bn(usd), "pct_of_own_gdp": None if share is None else round(share)}
        if economy == "ea":
            out["eur_billions"] = _bn(measures["native"][i])
        return out

    def rows(section: list[dict]) -> list[dict]:
        return [{"row": row["name"], **{names[e]: cell(row[e], e) for e in names}} for row in section]

    return {
        "period": periods[i],
        "usd_per_eur": view["usd_per_eur"][i],
        "gdp_over_four_quarters": {names[e]: {"usd_billions": _bn(view["gdp"][e]["usd"][i]),
                                             **({"eur_billions": _bn(view["gdp"][e]["native"][i])} if e == "ea" else {})} for e in names},
        "total_of_instruments_below": {names[e]: cell(view["total"][e], e) for e in names},
        "outstanding_by_instrument": rows(view["instruments"]),
        "held_by": rows(view["holders"]),
        "reading": "pct_of_own_gdp compares size without any exchange rate and is the better measure of how large "
                   "something is for its economy. usd_billions shows absolute scale and moves with the exchange rate.",
        "caveats": [view["notes"]["conversion"], view["notes"]["matching"], view["notes"]["what_it_is"]],
        "link": "#/",
    }


def _area(view: dict, given: str) -> str:
    wanted = given.strip().lower()
    aliases = {"usa": "us", "united states of america": "us", "eurozone": "ea", "euro zone": "ea", "britain": "uk",
               "gb": "uk", "cayman": "ky", "caymans": "ky"}
    for area in view["areas"]:
        if wanted in (area["id"], area["name"].lower()) or aliases.get(wanted) == area["id"]:
            return area["id"]
    raise ToolError(f"No economy {given!r} in the cross-border tables; known: " + ", ".join(f"{a['id']} ({a['name']})" for a in view["areas"])
                    + ". Other countries appear only inside 'everywhere else'.")


def get_cross_border_links(con: duckdb.DuckDBPyConnection, economy: str | None = None, other: str | None = None) -> dict:
    view = links.view(con)
    if view is None:
        raise ToolError("Links between economies are not loaded in this installation.")
    names = view["column_names"]
    caveats = [view["notes"]["reading"], view["notes"]["custody"], view["notes"]["not_included"], view["notes"]["euro_area"], view["notes"]["gaps"]]
    banks = view["all_banks"]

    def all_banks(area: str) -> dict:
        block = banks["areas"][area]
        return {side: {"total": _bn(block[side]["all"][-1]), "in_us_dollars": _bn(block[side]["usd"][-1]), "in_euro": _bn(block[side]["eur"][-1])}
                for side in ("claims", "liabilities")}

    if economy is None:
        if other is not None:
            raise ToolError("Give `economy` first; `other` narrows the answer to one pair.")
        tables = []
        for kind in view["kinds"]:
            rows = [{"row": names[holder], **{names[column]: _bn(kind["matrix"][holder][column]["level"][-1])
                                              for column in view["columns"] if column != holder}} for holder in kind["holders"]]
            tables.append({"what": kind["name"], "rows_are": kind["row_label"], "columns_are": kind["column_label"],
                           "source": kind["source"], "period": kind["periods"][-1], "rows": rows})
        return {
            "unit": "USD billions; null where the source publishes no country detail",
            "tables": tables,
            "all_reporting_banks_worldwide": {
                "period": banks["periods"][-1],
                "positions_with_residents_of": {names[area]: all_banks(area) for area in banks["areas"]},
                "note": view["notes"]["all_banks"] + " Dollar claims on residents outside the United States are the world "
                        "figure less the United States figure.",
            },
            "caveats": caveats,
            "link": "#/links",
        }

    a = _area(view, economy)
    if other is None:
        out = {"economy": names[a], "unit": "USD billions", "by_kind": []}
        for kind in view["kinds"]:
            entry = {"what": kind["name"], "source": kind["source"], "period": kind["periods"][-1]}
            if a in kind["matrix"]:
                entry[f"{kind['row_label']} {names[a]}, {kind['column_label'].lower()}"] = {
                    names[column]: _bn(kind["matrix"][a][column]["level"][-1]) for column in view["columns"] if column != a}
            entry[f"positions of other economies towards {names[a]}"] = {
                names[holder]: _bn(kind["matrix"][holder][a]["level"][-1]) for holder in kind["holders"] if holder != a}
            out["by_kind"].append(entry)
        out["all_reporting_banks_worldwide"] = {"period": banks["periods"][-1], **all_banks(a), "note": view["notes"]["all_banks"]}
        return {**out, "caveats": caveats, "link": "#/links"}

    b = _area(view, other)
    if a == b:
        raise ToolError("Give two different economies.")
    by_kind = []
    for kind in view["kinds"]:
        periods = kind["periods"]
        # Year ends, and the latest period if it is not one.
        at = [i for i, period in enumerate(periods) if period.endswith("Q4")][-12:]
        if at[-1] != len(periods) - 1:
            at.append(len(periods) - 1)
        entry = {"what": kind["name"], "source": kind["source"], "frequency": kind["frequency"], "latest_period": periods[-1], "directions": []}
        for holder, issuer in ((a, b), (b, a)):
            cell = kind["matrix"].get(holder, {}).get(issuer)
            if cell is None or all(value is None for value in cell["level"]):
                entry["directions"].append({"meaning": kind["sentence"].format(holder=names[holder], issuer=names[issuer], amount="an amount"),
                                            "amount": None, "why_missing": f"{names[holder]} does not publish this by country."})
                continue
            entry["directions"].append({
                "meaning": kind["sentence"].format(holder=names[holder], issuer=names[issuer], amount="this amount"),
                "amount": _bn(cell["level"][-1]),
                "share_of_all_such_positions_abroad_pct": _pct(cell["level"][-1], kind["matrix"][holder]["world"]["level"][-1]),
                "history": [{"period": periods[i], "amount": _bn(cell["level"][i])} for i in at if cell["level"][i] is not None],
                **({"latest_leaves_out": cell["missing"]} if cell["missing"] else {}),
            })
        by_kind.append(entry)
    return {"pair": [names[a], names[b]], "unit": "USD billions", "by_kind": by_kind, "caveats": caveats, "link": f"#/links?pair={a}-{b}"}


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


def _context(con: duckdb.DuckDBPyConnection, economy: str):
    _economy(con, economy)
    if economy == "ea":
        if not eacontext.available(con):
            raise ToolError("Euro-area rates, GDP and announcements are not loaded in this installation.")
        return eacontext
    return context


def get_rates_and_gdp(con: duckdb.DuckDBPyConnection, start: str | None = None, end: str | None = None,
                      economy: str = economies.DEFAULT) -> dict:
    view = _context(con, economy).view(con)
    euro = economy == "ea"
    periods = view["periods"]
    i = _index(periods, end, "end")
    j = _index(periods, start, "start") if start else max(0, i - 12)
    if j > i:
        raise ToolError("start must not be after end")
    if i - j > 80:
        raise ToolError("Ask for at most 80 quarters at a time")
    return {
        "rates_unit": "percent per year, quarterly average of daily rates",
        "gdp_unit": f"{'EUR' if euro else 'USD'} billions, nominal, over the four quarters ending in that quarter",
        "rates": {rate["id"]: rate["name"] for rate in view["rates"]},
        "quarters": [
            {"period": periods[k], **{rate["id"]: rate["values"][k] for rate in view["rates"]},
             "gdp": _bn(view["gdp"]["values"][k]),
             **({"usd_per_eur_at_quarter_end": view["fx"]["values"][k]} if euro else {})}
            for k in range(j, i + 1)
        ],
        "latest_daily": {rate["id"]: rate["latest"] for rate in view["rates"]},
        **({"policy_rate_changes": eacontext.policy_changes(con),
            "policy_rate_changes_note": "The ten most recent changes in the deposit facility rate, by the day each took "
                                        "effect (a few days after the decision was announced)."} if euro else {}),
        "source": ("ECB: key interest rates, euro area AAA government yield curve, national accounts series "
                   + view["gdp"]["series"] + ", reference exchange rate") if euro
                  else "Federal Reserve H.15 (rates); Z.1 series " + view["gdp"]["series"] + " (GDP)",
    }


def get_fed_announcements(con: duckdb.DuckDBPyConnection, start: str | None = None, end: str | None = None,
                          economy: str = economies.DEFAULT) -> dict:
    source = _context(con, economy)
    periods = euroarea.periods(con) if economy == "ea" else context.periods(con)
    i = _index(periods, end, "end") if end else None
    j = _index(periods, start, "start") if start else None
    events = []
    for event in source.load_events():
        k = periods.index(event["period"]) if event["period"] in periods else None
        if k is None and (i is not None or j is not None):
            # After the latest quarter of accounts: include only if no end bound excludes it.
            if i is not None:
                continue
        if k is not None and ((i is not None and k > i) or (j is not None and k < j)):
            continue
        events.append({key: event[key] for key in ("date", "period", "kind", "title", "detail", "url")})
    if economy == "ea":
        return {
            "central_bank": "European Central Bank",
            "events": events,
            "coverage": "A hand-curated calendar of major ECB announcements from late 2008: rate turning points, asset "
                        "purchase and runoff decisions, and lending operations for banks. Not every Governing Council "
                        "meeting, and nothing from governments or other central banks.",
        }
    return {
        "central_bank": "Federal Reserve",
        "events": events,
        "coverage": "A hand-curated calendar of major Federal Reserve announcements from late 2008: rate turning points, "
                    "asset purchase and runoff decisions, and emergency facilities. Not every FOMC meeting, and nothing "
                    "from the Treasury, Congress or other central banks.",
    }


def _weekly(con: duckdb.DuckDBPyConnection, economy: str = economies.DEFAULT) -> dict:
    _economy(con, economy)
    view = (euweekly if economy == "ea" else fedweekly).view(con)
    if view is None:
        raise ToolError("The weekly central bank balance sheet is not loaded for this economy.")
    euro = economy == "ea"
    # What differs between the two central banks' weekly statements, for the tool output.
    view["_"] = {"prefix": "ECB weekly statement" if euro else "H.4.1", "total": euweekly.TOTAL if euro else "RESPPMA",
                 "currency": "EUR" if euro else "USD", "day": view["weekday"],
                 "valuation": "securities held for monetary policy at amortised cost" if euro else "securities at face value"}
    return view


def _week(periods: list[str], date: str | None, what: str = "date") -> int:
    """The latest week on or before a date (YYYY-MM-DD), or the end of a quarter (2026:Q2)."""
    if date is None:
        return len(periods) - 1
    quarter = PERIOD.match(date.strip())
    if quarter:
        month = int(quarter.group(2)) * 3
        date = f"{quarter.group(1)}-{month:02d}-31"
    elif not re.match(r"^\d{4}-\d{2}-\d{2}$", date.strip()):
        raise ToolError(f"{what} must be a date such as 2026-11-18 or a quarter such as 2026:Q2")
    date = date.strip()
    if date < periods[0]:
        raise ToolError(f"The weekly data starts on {periods[0]}; {what} {date} is earlier")
    return max(i for i, period in enumerate(periods) if period <= date)


def _weekly_lines(view: dict):
    for side in ("assets", "liabilities"):
        for line in view[side]["lines"]:
            yield side, line, None
            for child in line["children"]:
                yield side, child, line["id"]


def get_fed_weekly(con: duckdb.DuckDBPyConnection, date: str | None = None, compare_to: str | None = None,
                   economy: str = economies.DEFAULT) -> dict:
    view = _weekly(con, economy)
    meta = view["_"]
    periods = view["periods"]
    i = _week(periods, date)
    anchor = view["quarterly"]["index"]
    j = _week(periods, compare_to, "compare_to") if compare_to else (anchor if i > anchor else max(0, i - 52))
    if j >= i:
        raise ToolError("compare_to must be earlier than date")
    out: dict = {"assets": [], "liabilities_and_capital": []}
    for side, line, parent in _weekly_lines(view):
        level = line["level"]
        row = {"line": line["id"], "name": line["name"], "amount": _bn(level[i]),
               "change_in_week": _bn(level[i] - level[i - 1]) if i else None,
               "change_since_compare_to": _bn(level[i] - level[j]),
               "series": [f"{meta['prefix']} {s}" for s in line["series"]] or None}
        if parent:
            row["part_of"] = parent
        if line["computed"] and not line["series"]:
            row["note"] = "Computed: the published total less the named lines."
        out["assets" if side == "assets" else "liabilities_and_capital"].append(row)
    total = view["assets"]["total"]
    return {
        "date": periods[i], "compare_to": periods[j], "latest_week_available": periods[-1],
        "central_bank": view["central_bank"],
        "unit": f"{meta['currency']} billions; {meta['day']} levels; {meta['valuation']}",
        "total_assets": {"amount": _bn(total[i]), "change_in_week": _bn(total[i] - total[i - 1]) if i else None,
                         "change_since_compare_to": _bn(total[i] - total[j]), "series": [f"{meta['prefix']} {meta['total']}"]},
        **out,
        "quarterly_accounts_end": {"quarter": view["quarterly"]["period"], "last_week_in_it": periods[anchor]},
        "caveats": [view["notes"]["basis"], view["notes"]["counterparties"],
                    *(["Earnings remittances due to the Treasury are negative when the Fed has accumulated losses."]
                      if economy == economies.DEFAULT else [])],
        "source": view["source"]["name"],
        "link": f"{view['page']}?period={periods[i]}",
    }


def get_fed_weekly_history(con: duckdb.DuckDBPyConnection, lines: list[str], start: str | None = None,
                           end: str | None = None, frequency: str = "auto", economy: str = economies.DEFAULT) -> dict:
    view = _weekly(con, economy)
    meta = view["_"]
    periods = view["periods"]
    known = {line["id"]: line for _, line, _ in _weekly_lines(view)}
    known["total_assets"] = {"id": "total_assets", "name": "Total assets", "level": view["assets"]["total"], "series": ["RESPPMA"]}
    if not 1 <= len(lines) <= 6:
        raise ToolError("lines must hold one to six line ids")
    unknown = [line for line in lines if line not in known]
    if unknown:
        raise ToolError(f"Unknown line ids {unknown}. Known: {sorted(known)}")
    i = _week(periods, end, "end")
    j = _week(periods, start, "start") if start else max(0, i - 26)
    if j > i:
        raise ToolError("start must not be after end")
    if frequency not in ("auto", "weekly", "monthly", "quarterly"):
        raise ToolError("frequency must be auto, weekly, monthly or quarterly")
    if frequency == "auto":
        frequency = "weekly" if i - j <= 60 else "monthly" if i - j <= 320 else "quarterly"

    def bucket(period: str) -> str:
        if frequency == "weekly":
            return period
        return period[:7] if frequency == "monthly" else f"{period[:4]}:Q{(int(period[5:7]) - 1) // 3 + 1}"

    # The last week of each month or quarter; the final point is the end week itself.
    chosen = [k for k in range(j, i + 1) if k == i or bucket(periods[k]) != bucket(periods[k + 1])]
    series = []
    for line_id in lines:
        level = known[line_id]["level"]
        window = range(j, i + 1)
        high = max(window, key=lambda k: level[k])
        low = min(window, key=lambda k: level[k])
        series.append({
            "line": line_id, "name": known[line_id]["name"],
            "series": [f"{meta['prefix']} {s}" for s in known[line_id]["series"]] or None,
            "amounts": [_bn(level[k]) for k in chosen],
            "change_over_window": _bn(level[i] - level[j]),
            "highest_week": {"date": periods[high], "amount": _bn(level[high])},
            "lowest_week": {"date": periods[low], "amount": _bn(level[low])},
        })
    return {
        "dates": [periods[k] for k in chosen], "frequency": frequency,
        "central_bank": view["central_bank"],
        "sampling": f"Each point is a {meta['day']} level; monthly and quarterly points are the last week of the period. "
                    "Highest and lowest weeks are searched over every week in the window.",
        "unit": f"{meta['currency']} billions; {meta['valuation']}",
        "lines": series,
        "source": view["source"]["name"],
        "link": f"{view['page']}?period={periods[i]}",
    }


def _foreign(con: duckdb.DuckDBPyConnection, asset: str = "treasuries") -> dict:
    if asset not in tic.INWARD:
        raise ToolError(f"asset must be one of {sorted(tic.INWARD)}; for what US residents hold abroad, use get_country")
    view = tic.view(con, asset)
    if view is None:
        raise ToolError("Foreign holdings by country are not loaded.")
    return view


def _month(periods: list[str], month: str | None, what: str = "month") -> int:
    if month is None:
        return len(periods) - 1
    text = month.strip()
    quarter = PERIOD.match(text)
    if quarter:
        text = f"{quarter.group(1)}-{int(quarter.group(2)) * 3:02d}"
    text = text[:7]
    if text not in periods:
        raise ToolError(f"{what} must be a month from {periods[0]} to {periods[-1]} (YYYY-MM) or a quarter; got {month}")
    return periods.index(text)


def _net(values: list, j: int, i: int) -> float | None:
    """Flows summed over the months after j up to i, or None where any month is not reported."""
    window = values[j + 1:i + 1]
    return None if not window or any(v is None for v in window) else _bn(sum(window))


def _holder_row(holder: dict, i: int, j: int, total: float | None) -> dict:
    level, before = holder["total"][i], holder["total"][j]
    return {
        "name": holder["name"], "amount": _bn(level), "share_pct": _pct(level, total),
        **({"bills": _bn(holder["short_term"][i]), "bonds_and_notes": _bn(holder["long_term"][i])}
           if holder["short_term"][i] is not None else {}),
        "change_since_compare_to": None if level is None or before is None else _bn(level - before),
        "net_purchases_since_compare_to": _net(holder["total_net"], j, i),
    }


def _quarterly_note(view: dict, i: int) -> dict | None:
    quarterly = view["quarterly"]
    if not quarterly:
        return None
    level = quarterly["level"][i]
    return {"nearest_instrument": quarterly["instrument_name"], "instrument_id": quarterly["instrument_id"],
            "rest_of_world_amount_that_quarter": _bn(level), "how_they_compare": quarterly["note"]}


def get_foreign_holders(con: duckdb.DuckDBPyConnection, asset: str = "treasuries", month: str | None = None,
                        compare_to: str | None = None, top: int = 15) -> dict:
    view = _foreign(con, asset)
    periods = view["periods"]
    i = _month(periods, month)
    j = _month(periods, compare_to, "compare_to") if compare_to else max(0, i - 12)
    if j >= i:
        raise ToolError("compare_to must be earlier than month")
    if not 1 <= top <= 80:
        raise ToolError("top must be between 1 and 80")
    total = view["total"]["total"][i]
    ranked = sorted((c for c in view["countries"] if c["total"][i] is not None), key=lambda c: -c["total"][i])
    return {
        "asset": view["name"], "scope": view["notes"]["scope"],
        "month": periods[i], "compare_to": periods[j], "latest_month_available": periods[-1],
        "unit": "USD billions, market value, end of month",
        "all_foreign_holders": _holder_row(view["total"], i, j, total),
        "official": _holder_row(view["official"], i, j, total),
        "private": _holder_row(view["private"], i, j, total),
        "regions": [_holder_row(region, i, j, total) for region in view["regions"]],
        "countries": [{"rank": k + 1, **_holder_row(c, i, j, total)} for k, c in enumerate(ranked[:top])],
        "countries_listed": len(ranked),
        "memo": [_holder_row(m, i, j, total) for m in view["memo"]],
        "quarterly_accounts": _quarterly_note(view, i),
        "caveats": [view["notes"]["custody"], view["notes"]["valuation"], view["notes"]["history"]],
        "source": view["source"]["name"],
        "link": f"#/us/foreign/{view['id']}?period={periods[i]}",
    }


def get_foreign_holder_history(con: duckdb.DuckDBPyConnection, countries: list[str], asset: str = "treasuries",
                               start: str | None = None, end: str | None = None) -> dict:
    view = _foreign(con, asset)
    periods = view["periods"]
    known = {h["name"].lower(): h for h in [*view["countries"], *view["regions"], *view["memo"], view["official"], view["private"]]}
    known.update({"all": view["total"], "total": view["total"], "official": view["official"], "private": view["private"],
                  "china": known["china, mainland"], "south korea": known["korea, south"], "uk": known["united kingdom"]})
    if not 1 <= len(countries) <= 6:
        raise ToolError("countries must hold one to six names")
    unknown = [name for name in countries if name.strip().lower() not in known]
    if unknown:
        raise ToolError(f"Unknown holders {unknown}. Use names from get_foreign_treasury_holders, a region name, 'official', 'private' or 'total'.")
    i = _month(periods, end, "end")
    j = _month(periods, start, "start") if start else max(0, i - 24)
    if j > i:
        raise ToolError("start must not be after end")
    chosen = list(range(j, i + 1))
    sampling = "monthly"
    if len(chosen) > 37:
        chosen = [k for k in chosen if k == i or k == j or periods[k][5:] in ("03", "06", "09", "12")]
        sampling = "quarter-end months, plus the first and last month"
    out = []
    for name in countries:
        holder = known[name.strip().lower()]
        present = [k for k in range(j, i + 1) if holder["total"][k] is not None]
        high = max(present, key=lambda k: holder["total"][k]) if present else None
        low = min(present, key=lambda k: holder["total"][k]) if present else None
        out.append({
            "name": holder["name"],
            "amounts": [_bn(holder["total"][k]) for k in chosen],
            **({"bills": [_bn(holder["short_term"][k]) for k in chosen]} if view["has_bills"] else {}),
            "change_over_window": None if None in (holder["total"][i], holder["total"][j]) else _bn(holder["total"][i] - holder["total"][j]),
            "net_purchases_over_window": _net(holder["total_net"], j, i),
            "valuation_change_over_window_excluding_bills": _net(holder["long_term_valuation"], j, i),
            "highest_month": None if high is None else {"month": periods[high], "amount": _bn(holder["total"][high])},
            "lowest_month": None if low is None else {"month": periods[low], "amount": _bn(holder["total"][low])},
        })
    return {
        "months": [periods[k] for k in chosen], "sampling": sampling,
        "unit": "USD billions, market value, end of month",
        "holders": out,
        "asset": view["name"],
        "caveats": [view["notes"]["custody"], view["notes"]["history"]],
        "source": view["source"]["name"],
        "link": f"#/us/foreign/{view['id']}?period={periods[i]}",
    }


COUNTRY_ALIASES = {"china": "china-mainland", "south-korea": "korea-south", "korea": "korea-south", "uk": "united-kingdom",
                   "britain": "united-kingdom", "uae": "united-arab-emirates", "eurozone": "euro-area", "eu": "european-union"}


def get_country(con: duckdb.DuckDBPyConnection, country: str, month: str | None = None, compare_to: str | None = None) -> dict:
    key = countries.slug(country)
    view = countries.view(con, COUNTRY_ALIASES.get(key, key))
    if view is None:
        known = [row["name"] for row in countries.listing(con)]
        raise ToolError(f"No country {country!r}. Known: {', '.join(sorted(known))}")
    periods = view["periods"]
    i = _month(periods, month)
    j = _month(periods, compare_to, "compare_to") if compare_to else max(0, i - 12)
    if j >= i:
        raise ToolError("compare_to must be earlier than month")

    def row(line: dict) -> dict:
        level, before, everyone = line["total"][i], line["total"][j], line.get("all_countries", [None] * len(periods))[i]
        return {
            "name": line.get("name", "Total published"), "amount": _bn(level),
            **({"share_of_all_countries_pct": _pct(level, everyone)} if everyone else {}),
            "change_since_compare_to": None if level is None or before is None else _bn(level - before),
            "net_purchases_since_compare_to": _net(line["total_net"], j, i),
            "valuation_change_since_compare_to": _net(line["long_term_valuation"], j, i),
            **({"rank_among_countries_latest_month": line["rank"]} if line.get("rank") else {}),
        }

    def side(data: dict) -> dict:
        return {"total": row(data), "by_kind_of_security": [row(line) for line in data["lines"]]} if data["lines"] else None

    return {
        "country": view["name"], "month": periods[i], "compare_to": periods[j], "latest_month_available": periods[-1],
        "unit": "USD billions, market value, end of month",
        "us_securities_held_in_this_country": side(view["holds_us"]),
        "this_countrys_securities_held_by_us_residents": side(view["held_by_us"]),
        "caveats": [view["notes"][key] for key in ("scope", "custody", "outward", "coverage", "history")],
        "source": view["source"]["name"],
        "link": f"#/country/{view['id']}?period={periods[i]}",
    }


def flag_data_gap(con: duckdb.DuckDBPyConnection, category: str, explanation: str) -> dict:
    if category not in GAP_CATEGORIES:
        raise ToolError(f"category must be one of {sorted(GAP_CATEGORIES)}")
    return {"recorded": True, "category": category, "shown_to_user": explanation}


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


_PERIOD = {"type": "string", "description": "A quarter such as 2024:Q3. Omit for the latest quarter."}
_COMPARE = {"type": "string", "description": "An earlier quarter such as 2022:Q1. If given, each position also reports "
                                              "its change since then, split into net transactions and valuation."}
_ECONOMY = {"type": "string", "enum": sorted(economies.ECONOMIES),
            "description": "us (default; amounts in USD) or ea for the euro area (amounts in EUR, quarterly from 1999:Q1). "
                           "Sector and instrument ids differ between the two: list them for the economy you want."}

# name -> (function, description, input schema)
REGISTRY: dict[str, tuple[Any, str, dict]] = {
    "list_instruments": (list_instruments,
        "List every financial instrument that has a page (Treasuries, repo, mortgages, deposits, equities, ...) with its id "
        "and amount outstanding. Call this to find an instrument_id.",
        _schema({"economy": _ECONOMY}, [])),
    "list_sectors": (list_sectors,
        "List every sector that has a balance sheet (households, the Federal Reserve, banks, money market funds, rest of "
        "the world, ...) with its id and size. Call this to find a sector_id.",
        _schema({"economy": _ECONOMY}, [])),
    "get_instrument": (get_instrument,
        "Who holds an instrument and who owes it, by sector group and by sector, in one quarter: amount, share, and that "
        "quarter's net transactions and valuation change. With compare_to, also the change between two quarters split into "
        "transactions and valuation. Use this for 'who holds', 'who absorbed', 'who issued' and for decomposing a change.",
        _schema({"instrument_id": {"type": "string", "description": "From list_instruments, e.g. F3_2 for Treasury securities."},
                 "period": _PERIOD, "compare_to": _COMPARE, "economy": _ECONOMY}, ["instrument_id"])),
    "get_sector": (get_sector,
        "One sector's financial balance sheet in one quarter: every asset and liability line with amount, share of the total, "
        "and that quarter's transactions and valuation change. With compare_to, also each line's change between two quarters.",
        _schema({"sector_id": {"type": "string", "description": "From list_sectors, e.g. S121 for the Federal Reserve."},
                 "period": _PERIOD, "compare_to": _COMPARE, "economy": _ECONOMY}, ["sector_id"])),
    "get_history": (get_history,
        "Time series for up to six positions, by series id (taken from get_instrument or get_sector results, for either "
        "economy; one economy per call, and no share of GDP for the euro area): amount "
        "outstanding, net transactions and valuation change per period, optionally as a share of GDP. Defaults to the last "
        "ten years, quarterly. Use this for trends, peaks and turning points.",
        _schema({"series": {"type": "array", "items": {"type": "string"}, "description": "One to six series ids such as LM263061105.Q."},
                 "start": {"type": "string", "description": "First quarter, e.g. 2008:Q1. Data starts 1952:Q1."},
                 "end": {"type": "string", "description": "Last quarter. Omit for the latest."},
                 "frequency": {"type": "string", "enum": ["auto", "quarterly", "annual"]},
                 "share_of_gdp": {"type": "boolean", "description": "Also report each amount as a percent of GDP."}}, ["series"])),
    "latest_moves": (latest_moves,
        "What stood out in the latest quarter: flows that were unusual against each position's own ten-year history, the "
        "largest flows outright, or the largest valuation changes.",
        _schema({"kind": {"type": "string", "enum": ["unusual_flows", "largest_flows", "valuation_changes"]},
                 "economy": _ECONOMY}, ["kind"])),
    "get_system_map": (get_system_map,
        "The whole system in one quarter: for each instrument family (Treasuries, other debt, repo, mortgages, loans, "
        "deposits, fund shares, equities, pensions and insurance), how much each sector group owes and holds. Use this for "
        "questions about the overall shape of the system or one group's role across instruments.",
        _schema({"period": _PERIOD, "economy": _ECONOMY}, [])),
    "compare_economies": (compare_economies,
        "The United States and the euro area side by side in one quarter: amounts outstanding of each kind of instrument "
        "(debt securities, loans, deposits, fund shares, equity, pensions and insurance) and what each sector group holds, "
        "in US dollars at that quarter's exchange rate and as a percent of each economy's own GDP, with GDP itself. Use it "
        "for any question that sets the two economies against each other in size or structure. This is the only place "
        "euro amounts are converted. From 1999:Q1.",
        _schema({"period": _PERIOD}, [])),
    "get_cross_border_links": (get_cross_border_links,
        "Positions between economies, in US dollars: holdings of each other's equity and fund shares and debt securities "
        "(IMF portfolio survey, end of June and December, to end-2025), and what banks located in one are owed by and owe to "
        "residents of the other (BIS, quarterly from 1999). Economies: us, ea (euro area), jp (Japan), uk, cn (China), "
        "ky (Cayman Islands). With no arguments: every pair, latest, plus all reporting banks' positions with each economy "
        "split into US dollars and euro (the measure of dollars outside the United States). With `economy`: that economy "
        "against all the others. With `economy` and `other`: both directions for that pair with year-end history. This is "
        "the only tool with euro-area or Japanese holdings by counterparty country; it has no sectors, maturities or flows.",
        _schema({"economy": {"type": "string", "description": "us, ea, jp, uk, cn or ky. Omit for all pairs."},
                 "other": {"type": "string", "description": "A second economy, for both directions of one pair with history."}}, [])),
    "get_who_holds_whose": (get_who_holds_whose,
        "Euro area only: what each sector holds of each sector's paper, for one instrument in one quarter, as holder and "
        "issuer pairs with amount, share, and that quarter's transactions and valuation change (and the change since "
        "compare_to). Instruments: F3 debt securities, F4 loans (lender and borrower), F2 deposits (depositor and "
        "deposit-taker), F51 listed shares, F52 investment fund shares. Use it for questions such as who holds "
        "government debt, whom banks lend to, or how much of something is held abroad. Debt securities, listed shares "
        "and fund shares start in 2013:Q4. The US accounts have nothing like this: there, who holds whose paper is a gap.",
        _schema({"instrument_id": {"type": "string", "enum": ["F2", "F3", "F4", "F51", "F52"]},
                 "period": _PERIOD, "compare_to": _COMPARE}, ["instrument_id"])),
    "get_rates_and_gdp": (get_rates_and_gdp,
        "Quarterly averages of the federal funds rate and 3-month, 2-year and 10-year Treasury yields, nominal GDP, and the "
        "latest daily rates. Defaults to the last three years. With economy ea: the ECB deposit facility rate, euro area "
        "AAA government yields (from late 2004), euro area GDP in euro, US dollars per euro at each quarter end, and the "
        "dates of the ten most recent changes in the deposit rate.",
        _schema({"start": {"type": "string", "description": "First quarter, e.g. 2019:Q1."},
                 "end": {"type": "string", "description": "Last quarter. Omit for the latest."}, "economy": _ECONOMY}, [])),
    "get_fed_announcements": (get_fed_announcements,
        "Major Federal Reserve announcements since 2008 (rate turning points, asset purchases and runoff, emergency "
        "facilities), each with its date and press release. Context only: an announcement near a change is not evidence of cause. "
        "With economy ea: major European Central Bank announcements instead.",
        _schema({"start": {"type": "string", "description": "First quarter, e.g. 2020:Q1."},
                 "end": {"type": "string", "description": "Last quarter."}, "economy": _ECONOMY}, [])),
    "get_fed_weekly": (get_fed_weekly,
        "The Federal Reserve's own balance sheet on one Wednesday, from its weekly H.4.1 release: Treasury securities "
        "(bills, notes and bonds), mortgage-backed securities, loans, and on the other side currency, bank reserve balances, "
        "reverse repurchase agreements, the Treasury General Account and capital. Each line has its change in that week and "
        "since compare_to. This is the only data here newer than the latest quarter; use it for anything about the Fed's "
        "balance sheet, reserves, the Treasury's cash balance or the reverse repo facility recently or week by week. It "
        "covers the Federal Reserve only, from December 2002. With economy ea it is the Eurosystem's weekly statement "
        "instead (the ECB and the euro area's national central banks together), every Friday from January 1999, in euro: "
        "securities (those held for monetary policy shown separately), lending to banks, gold, and on the other side "
        "banknotes, banks' deposits (current accounts and the deposit facility), government deposits and capital.",
        _schema({"date": {"type": "string", "description": "A date such as 2026-11-18 (the latest week on or before it is used), or a quarter such as 2026:Q2 for its last week. Omit for the latest week."},
                 "compare_to": {"type": "string", "description": "An earlier date or quarter. Defaults to the last week of the latest quarter in the quarterly accounts, or a year earlier for older dates."}, "economy": _ECONOMY}, [])),
    "get_fed_weekly_history": (get_fed_weekly_history,
        "Weekly history of up to six lines of the Federal Reserve's balance sheet, with the highest and lowest week in the "
        "window. Line ids come from get_fed_weekly (for example reserves, reverse_repo, tga, treasuries, mbs), plus total_assets. "
        "With economy ea the lines are the Eurosystem's (for example securities_policy, lending, bank_deposits, deposit_facility, banknotes). "
        "Defaults to the last six months, weekly.",
        _schema({"lines": {"type": "array", "items": {"type": "string"}, "description": "One to six line ids."},
                 "start": {"type": "string", "description": "First date or quarter. Data starts 2002-12-18."},
                 "end": {"type": "string", "description": "Last date or quarter. Omit for the latest week."},
                 "frequency": {"type": "string", "enum": ["auto", "weekly", "monthly", "quarterly"]}, "economy": _ECONOMY}, ["lines"])),
    "get_foreign_holders": (get_foreign_holders,
        "Foreign holders of one kind of US security by country in one month, ranked, from the Treasury's TIC reports: amount, "
        "share of foreign holdings, and change and net purchases since compare_to. Assets: treasuries (bills, notes and bonds), "
        "agency (agency bonds), corporate (corporate and other bonds), equities (shares, including fund shares). Also region "
        "totals, the euro area, and official (central banks and governments) against private holders. Use it for any question "
        "about which countries hold these securities or how a country's holdings moved. Monthly, from January 2020.",
        _schema({"asset": {"type": "string", "enum": sorted(tic.INWARD), "description": "Default treasuries."},
                 "month": {"type": "string", "description": "A month such as 2026-09, or a quarter such as 2026:Q2 for its last month. Omit for the latest month."},
                 "compare_to": {"type": "string", "description": "An earlier month or quarter. Defaults to twelve months earlier."},
                 "top": {"type": "integer", "description": "How many countries to list, largest first. Default 15."}}, [])),
    "get_foreign_holder_history": (get_foreign_holder_history,
        "Monthly history of one kind of US security held by up to six foreign holders: country names as returned by "
        "get_foreign_holders (for example Japan, China, United Kingdom), a region, 'official', 'private' or 'total'. "
        "Defaults to Treasuries over the last two years.",
        _schema({"countries": {"type": "array", "items": {"type": "string"}, "description": "One to six holder names."},
                 "asset": {"type": "string", "enum": sorted(tic.INWARD), "description": "Default treasuries."},
                 "start": {"type": "string", "description": "First month or quarter. Data starts 2020-01."},
                 "end": {"type": "string", "description": "Last month or quarter. Omit for the latest."}}, ["countries"])),
    "get_country": (get_country,
        "One country (or the euro area or European Union) as a counterparty of the United States, in one month: the US "
        "securities held there by kind (Treasuries, agency bonds, corporate bonds, equities), and that country's securities "
        "held by US residents (government bonds, corporate bonds, equities), each with change, net purchases and valuation "
        "since compare_to. Use it for questions about one country's links with the US in both directions. It is not the "
        "country's own balance sheet: nothing about what it holds at home or in third countries.",
        _schema({"country": {"type": "string", "description": "A country name such as Japan, China, United Kingdom, Cayman Islands, or Euro area."},
                 "month": {"type": "string", "description": "A month such as 2026-09 or a quarter such as 2026:Q2. Omit for the latest month."},
                 "compare_to": {"type": "string", "description": "An earlier month or quarter. Defaults to twelve months earlier."}}, ["country"])),
    "flag_data_gap": (flag_data_gap,
        "Record that something the user asked for cannot be answered from this data. The user sees your explanation as a "
        "highlighted note. Call it when answering what was asked would otherwise mean guessing, inferring a link the data "
        "does not record, or drawing on general knowledge. Do not call it for limits the user did not ask about. Categories: " + " ".join(f"{k}: {v}" for k, v in GAP_CATEGORIES.items()),
        _schema({"category": {"type": "string", "enum": sorted(GAP_CATEGORIES)},
                 "explanation": {"type": "string", "description": "One or two sentences for the user: what is missing, and what the data can say instead."}},
                ["category", "explanation"])),
}


def definitions() -> list[dict]:
    """Tool definitions for the Messages API, in a fixed order so the prompt prefix stays cacheable."""
    return [{"name": name, "description": description, "input_schema": schema, "strict": True}
            for name, (_, description, schema) in REGISTRY.items()]


def validate(name: str, arguments: Any) -> None:
    """Check arguments against the tool's schema before running it."""
    if name not in REGISTRY:
        raise ToolError(f"Unknown tool {name!r}")
    schema = REGISTRY[name][2]
    if not isinstance(arguments, dict):
        raise ToolError("Tool input must be a JSON object")
    types = {"string": str, "boolean": bool, "array": list, "integer": int}
    for key in schema["required"]:
        if key not in arguments:
            raise ToolError(f"Missing required argument {key!r}")
    for key, value in arguments.items():
        spec = schema["properties"].get(key)
        if spec is None:
            raise ToolError(f"Unexpected argument {key!r}; allowed: {sorted(schema['properties'])}")
        if not isinstance(value, types[spec["type"]]) or (spec["type"] == "integer" and isinstance(value, bool)):
            raise ToolError(f"Argument {key!r} must be a {spec['type']}")
        if "enum" in spec and value not in spec["enum"]:
            raise ToolError(f"Argument {key!r} must be one of {spec['enum']}")
        if spec["type"] == "array" and not all(isinstance(item, str) for item in value):
            raise ToolError(f"Argument {key!r} must be a list of strings")


def run(con: duckdb.DuckDBPyConnection, name: str, arguments: Any) -> dict:
    validate(name, arguments)
    return REGISTRY[name][0](con, **arguments)
