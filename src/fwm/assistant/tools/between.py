"""Tools that set economies against each other: the side-by-side comparison and cross-border positions."""

from __future__ import annotations

import duckdb

from fwm import codes, economies
from fwm.assistant.tools.common import ToolError, _bn, _index, _pct
from fwm.views import compare, countries, links


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
        if economy != "us":
            out[f"{economies.ECONOMIES[economy]['currency'].lower()}_billions"] = _bn(measures["native"][i])
        return out

    def rows(section: list[dict]) -> list[dict]:
        return [{"row": row["name"], **{names[e]: cell(row[e], e) for e in names}} for row in section]

    return {
        "period": periods[i],
        "usd_per_eur": view["usd_per_eur"][i],
        "gdp_over_four_quarters": {names[e]: {"usd_billions": _bn(view["gdp"][e]["usd"][i]),
                                             **({f"{economies.ECONOMIES[e]['currency'].lower()}_billions": _bn(view["gdp"][e]["native"][i])}
                                                if e != "us" else {})} for e in names},
        **({"yen_per_usd": round(view["yen_per_usd"][i], 2)} if view.get("yen_per_usd") and view["yen_per_usd"][i] else {}),
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


def _country_links(con: duckdb.DuckDBPyConnection, iso2: str, caveats: list[str]) -> dict:
    """One country against every other, from its own report and from everyone else's."""
    view = links.country(con, iso2, top=8)
    if view is None:
        raise ToolError("Nothing is published for this country in the cross-border data.")
    by_kind = []
    for kind in view["kinds"]:
        entry: dict = {"what": kind["name"], "source": kind["source"], "frequency": kind["frequency"]}
        for side, key in (("own", "reported_by_this_country"), ("mirror", "reported_by_other_countries")):
            block = kind[side]
            if block is None:
                entry[key] = None
                continue
            entry[key] = {
                "meaning": block["label"], "period": block["period"], "total": _bn(block["total"]),
                "largest": {row["name"]: _bn(row["value"]) for row in block["top"]} or "not published by country",
                **({"everywhere_else": _bn(block["everywhere_else"])} if block["top"] else {}),
                **({"countries_reporting": block["reporters"]} if side == "mirror" and kind["source"] == "IMF" else {}),
                **({"in_us_dollars": _bn(block["in_us_dollars"]), "in_euro": _bn(block["in_euro"])} if block.get("in_us_dollars") is not None else {}),
                "year_ends": [{"period": p, "total": _bn(v)} for p, v in zip(kind["periods"], block["series"])
                              if v is not None and p.endswith("Q4")][-6:],
            }
        by_kind.append(entry)
    page = countries.page_of(con, iso2)
    return {"country": view["name"], "unit": "USD billions", "by_kind": by_kind,
            "caveats": [view["notes"]["mirror"], view["notes"]["custody"], *caveats[:3]],
            "link": f"#/country/{page}" if page else "#/links"}


def _country_pair(con: duckdb.DuckDBPyConnection, view: dict, a: tuple[str, tuple], b: tuple[str, tuple], caveats: list[str]) -> dict:
    """Both directions between two countries, or a country and one of the economies."""
    if set(a[1]) & set(b[1]):
        raise ToolError(f"{a[0]} and {b[0]} overlap; give two separate countries or economies.")
    name_of = {a[1]: a[0], b[1]: b[0]}
    sentences = {kind["id"]: kind["sentence"] for kind in view["kinds"]}
    by_kind = []
    for kind in links.pair(con, a[1], b[1]):
        directions = []
        for direction in kind["directions"]:
            holder, issuer = name_of[direction["holders"]], name_of[direction["issuers"]]
            history = direction["history"]
            if not history:
                directions.append({"meaning": sentences[kind["id"]].format(holder=holder, issuer=issuer, amount="an amount"),
                                   "amount": None, "why_missing": f"{holder} does not publish this by country."})
                continue
            directions.append({
                "meaning": sentences[kind["id"]].format(holder=holder, issuer=issuer, amount="this amount"),
                "period": history[-1]["period"], "amount": _bn(history[-1]["value"]),
                "history": [{"period": h["period"], "amount": _bn(h["value"])} for h in history],
                **({"members_reporting": len(direction["reporting"])} if len(direction["holders"]) > 1 else {}),
            })
        by_kind.append({"what": kind["name"], "source": kind["source"], "directions": directions})
    page = next((p for members in (a[1], b[1]) if len(members) == 1 and (p := countries.page_of(con, members[0]))
                 and members[0] not in ("US", "JP")), None)
    return {"pair": [a[0], b[0]], "unit": "USD billions", "by_kind": by_kind,
            "note": "Debt securities are all issuers together: government, banks and companies are not separated.",
            "caveats": caveats[:3], "link": f"#/country/{page}" if page else "#/links"}


def get_cross_border_links(con: duckdb.DuckDBPyConnection, economy: str | None = None, other: str | None = None) -> dict:
    view = links.view(con)
    if view is None:
        raise ToolError("Links between economies are not loaded in this installation.")
    names = view["column_names"]
    caveats = [view["notes"]["reading"], view["notes"]["custody"], view["notes"]["not_included"], view["notes"]["euro_area"], view["notes"]["gaps"],
               view["notes"]["against_us_data"]]
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

    def resolve(given: str) -> tuple[str | None, str, tuple[str, ...]]:
        try:
            area = _area(view, given)
            return area, names[area], tuple(links.MEMBERS[area])
        except ToolError:
            row = codes.find_country(given)
            if row is None:
                raise ToolError(f"No economy or country {given!r} in the cross-border data.") from None
            return None, row["name"], (row["iso2"],)

    a, a_name, a_members = resolve(economy)
    if a is None and other is None:
        return _country_links(con, a_members[0], caveats)
    if other is not None:
        b, b_name, b_members = resolve(other)
        if a is None or b is None:
            return _country_pair(con, view, (a_name, a_members), (b_name, b_members), caveats)
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
