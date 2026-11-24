"""Tools for the weekly central bank balance sheets."""

from __future__ import annotations

import re

import duckdb

from fwm import economies
from fwm.assistant.tools.common import PERIOD, ToolError, _bn, _economy


def _weekly(con: duckdb.DuckDBPyConnection, economy: str = economies.DEFAULT) -> dict:
    _economy(con, economy)
    module = economies.weekly(economy)
    if module is None:
        raise ToolError(f"No weekly central bank balance sheet is loaded for {economies.ECONOMIES[economy]['name']}; its central bank "
                        "is in the quarterly accounts only (for Japan, get_sector S110 with economy jp).")
    view = module.view(con)
    if view is None:
        raise ToolError("The weekly central bank balance sheet is not loaded for this economy.")
    # What differs between the central banks' weekly statements, for the tool output.
    view["_"] = {**module.CITE, "day": view["weekday"]}
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
