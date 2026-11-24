"""What every tool shares: the error type, units, period lookup, and the checks that an economy is loaded."""

from __future__ import annotations

import re
from typing import Any

import duckdb

from fwm import economies

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
    if not economies.available(con, economy):
        raise ToolError(f"The accounts of {economies.ECONOMIES[economy]['name']} are not loaded in this installation.")
    sector_module, instrument_module = economies.accounts(economy)
    info = economies.ECONOMIES[economy]
    return {"id": economy, "name": info["name"], "unit": f"{info['currency']} billions", "sectors": sector_module,
            "instruments": instrument_module, "home": "#/" if economy == economies.DEFAULT else f"#/{economy}"}


def _context(con: duckdb.DuckDBPyConnection, economy: str):
    """The economy's rates, GDP and announcements, or a ToolError saying they are not loaded."""
    _economy(con, economy)
    source = economies.context(economy)
    if not source.available(con):
        raise ToolError(f"Rates, GDP and announcements for {economies.ECONOMIES[economy]['name']} are not loaded in this installation.")
    return source
