"""Tools for the Treasury's country data: foreign holders of US securities, and one country as a counterparty of the US."""

from __future__ import annotations

import duckdb

from fwm.assistant.tools.common import PERIOD, ToolError, _bn, _pct
from fwm.views import countries
from fwm.views import foreign as tic


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
