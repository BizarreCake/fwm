"""Tools for an economy's rates, GDP and central bank announcements."""

from __future__ import annotations

import duckdb

from fwm import economies
from fwm.assistant.tools.common import ToolError, _bn, _context, _index


def get_rates_and_gdp(con: duckdb.DuckDBPyConnection, start: str | None = None, end: str | None = None,
                      economy: str = economies.DEFAULT) -> dict:
    source = _context(con, economy)
    view = source.view(con)

    def fx(k: int) -> dict:
        if source.FX_FIELD is None:
            return {}
        name, invert = source.FX_FIELD
        value = view["fx"]["values"][k]
        return {name: (round(1 / value, 2) if value else None) if invert else value}

    changes = source.policy_changes(con)
    periods = view["periods"]
    i = _index(periods, end, "end")
    j = _index(periods, start, "start") if start else max(0, i - 12)
    if j > i:
        raise ToolError("start must not be after end")
    if i - j > 80:
        raise ToolError("Ask for at most 80 quarters at a time")
    return {
        "rates_unit": "percent per year, quarterly average of daily rates",
        "gdp_unit": f"{economies.ECONOMIES[economy]['currency']} billions, nominal, over the four quarters ending in that quarter",
        "rates": {rate["id"]: rate["name"] for rate in view["rates"]},
        "quarters": [
            {"period": periods[k], **{rate["id"]: rate["values"][k] for rate in view["rates"]},
             "gdp": _bn(view["gdp"]["values"][k]),
             **fx(k)}
            for k in range(j, i + 1)
        ],
        "latest_daily": {rate["id"]: rate["latest"] for rate in view["rates"]},
        **({"policy_rate_changes": changes, "policy_rate_changes_note": source.POLICY_NOTE} if changes else {}),
        "source": view["notes"]["source"],
    }


def get_fed_announcements(con: duckdb.DuckDBPyConnection, start: str | None = None, end: str | None = None,
                          economy: str = economies.DEFAULT) -> dict:
    source = _context(con, economy)
    periods = economies.periods(con, economy)
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
    if source.EVENTS_COVERAGE:
        return {"central_bank": source.CENTRAL_BANK_NAME, "events": events, "coverage": source.EVENTS_COVERAGE}
    return {
        "central_bank": "Federal Reserve",
        "events": events,
        "coverage": "A hand-curated calendar of major Federal Reserve announcements from late 2008: rate turning points, "
                    "asset purchase and runoff decisions, and emergency facilities. Not every FOMC meeting, and nothing "
                    "from the Treasury, Congress or other central banks.",
    }
