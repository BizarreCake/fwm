"""The agent's tools: the same queries the pages use, shaped for a model to read.

Every function takes a read-only DuckDB connection and plain arguments and
returns a JSON-serialisable dict. Amounts are in billions of the economy's currency. Each
result carries the series ids behind its numbers and a `link` to the page
that shows the same thing, so an answer can cite and point.

A ToolError carries a message meant for the model: what was wrong and what to do instead.

The tools are grouped by subject in the modules of this package; this file holds the
registry of names, descriptions and argument schemas, and runs a tool by name.
"""

from __future__ import annotations

from typing import Any

import duckdb

from fwm import economies
from fwm.assistant.tools.accounts import (
    get_history,
    get_instrument,
    get_sector,
    get_system_map,
    get_who_holds_whose,
    latest_moves,
    list_instruments,
    list_sectors,
)
from fwm.assistant.tools.between import compare_economies, get_cross_border_links
from fwm.assistant.tools.common import GAP_CATEGORIES, PERIOD, ToolError  # noqa: F401
from fwm.assistant.tools.context import get_fed_announcements, get_rates_and_gdp
from fwm.assistant.tools.foreign import (
    get_country,
    get_foreign_holder_history,
    get_foreign_holders,
)
from fwm.assistant.tools.weekly import get_fed_weekly, get_fed_weekly_history
from fwm.views import foreign as tic


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
            "description": "us (default; amounts in USD), ea for the euro area (amounts in EUR, quarterly from 1999:Q1) or "
                           "jp for Japan (amounts in JPY, quarterly from 1997:Q4). Sector and instrument ids differ "
                           "between them: list them for the economy you want."}

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
        "economy; one economy per call): amount "
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
        "The United States, the euro area and Japan side by side in one quarter: amounts outstanding of each kind of instrument "
        "(debt securities, loans, deposits, fund shares, equity, pensions and insurance) and what each sector group holds, "
        "in US dollars at that quarter's exchange rate and as a percent of each economy's own GDP, with GDP itself. Use it "
        "for any question that sets these economies against each other in size or structure. This is the only place "
        "euro and yen amounts are converted. From 1999:Q1.",
        _schema({"period": _PERIOD}, [])),
    "get_cross_border_links": (get_cross_border_links,
        "Positions between economies, in US dollars: holdings of each other's equity and fund shares and debt securities "
        "(IMF portfolio survey, end of June and December, to end-2025), and what banks located in one are owed by and owe to "
        "residents of the other (BIS, quarterly from 1999). Economies: us, ea (euro area), jp (Japan), uk, cn (China), "
        "ky (Cayman Islands). Any other country can also be given by name (Germany, Switzerland, Korea): alone, for its "
        "largest counterparts in each direction from its own report and from what other countries report about it; or as "
        "one of a pair. With no arguments: every pair of the six economies, latest, plus all reporting banks' positions with each economy "
        "split into US dollars and euro (the measure of dollars outside the United States). With `economy`: that economy "
        "against all the others. With `economy` and `other`: both directions for that pair with year-end history. This is "
        "the only tool with euro-area or Japanese holdings by counterparty country; it has no sectors, maturities or flows.",
        _schema({"economy": {"type": "string", "description": "us, ea, jp, uk, cn or ky, or a country name. Omit for all pairs."},
                 "other": {"type": "string", "description": "A second economy or country, for both directions of one pair with history."}}, [])),
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
