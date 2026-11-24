"""The economies side by side, in a common currency and as a share of each one's GDP.

Amounts come from each economy's system map (what is outstanding of each instrument
family, and what each sector group holds). Euro amounts are converted at the ECB's
reference rate on the last day of the quarter. Share of GDP needs no conversion, and
is the better comparison of size; dollars show absolute scale.

The two sets of accounts are not built to the same rulebook, so rows are matched as
closely as the published categories allow and the differences are stated in the notes.
"""

from __future__ import annotations

import duckdb

from fwm import context, eacontext, economies, euroarea, systemmap

# Row -> the system-map families that make it up in each economy.
INSTRUMENTS = (
    ("debt_securities", "Debt securities", {"us": ("treasuries", "agency", "other_debt"), "ea": ("debt_securities",)}),
    ("loans", "Loans", {"us": ("repo", "mortgages", "loans"), "ea": ("loans",)}),
    ("deposits", "Deposits & currency", {"us": ("deposits",), "ea": ("deposits",)}),
    ("fund_shares", "Fund shares", {"us": ("fund_shares",), "ea": ("fund_shares",)}),
    ("equity", "Equity", {"us": ("equities", "other_equity"), "ea": ("equities",)}),
    ("pensions_insurance", "Pensions & insurance", {"us": ("pensions_insurance",), "ea": ("pensions_insurance",)}),
)
# Row -> the sector groups that make it up in each economy. The euro area publishes banks,
# central banks and money market funds as one sector, so the US groups are merged to match.
HOLDERS = (
    ("banks", "Banks, central bank & money market funds", {"us": ("banks", "fed", "mmf"), "ea": ("banks",)}),
    ("funds", "Investment funds", {"us": ("funds",), "ea": ("funds",)}),
    ("pensions_insurers", "Pensions & insurers", {"us": ("pensions_insurers",), "ea": ("pensions_insurers",)}),
    ("other_financial", "Other financial institutions", {"us": ("other_financial",), "ea": ("other_financial",)}),
    ("households", "Households & non-profits", {"us": ("households",), "ea": ("households",)}),
    ("gov_business", "Government & business", {"us": ("gov_business",), "ea": ("gov_business",)}),
    ("row", "Rest of the world", {"us": ("row",), "ea": ("row",)}),
)
ORDER = ("us", "ea")


def available(con: duckdb.DuckDBPyConnection) -> bool:
    return euroarea.available(con) and eacontext.available(con) and systemmap.load(con, "ea") is not None


def view(con: duckdb.DuckDBPyConnection) -> dict | None:
    if not available(con):
        return None
    maps = {economy: systemmap.load(con, economy) or systemmap.compute(con, economy) for economy in ORDER}
    periods = [period for period in maps["ea"]["periods"] if period in set(maps["us"]["periods"])]
    at = {economy: [maps[economy]["periods"].index(period) for period in periods] for economy in ORDER}
    gdp = {"us": context.gdp(con, periods), "ea": eacontext.gdp(con, periods)}
    rate = eacontext.fx_quarter_end(con, periods)  # US dollars per euro
    to_usd = {"us": [1.0] * len(periods), "ea": rate}

    def measures(economy: str, native: list[float]) -> dict:
        return {
            "native": native,
            "usd": [None if to_usd[economy][i] is None else value * to_usd[economy][i] for i, value in enumerate(native)],
            "pct_of_gdp": [None if not gdp[economy][i] else 100 * value / gdp[economy][i] for i, value in enumerate(native)],
        }

    def outstanding(economy: str, family_ids: tuple[str, ...], group_ids: tuple[str, ...] | None = None) -> list[float]:
        out = [0.0] * len(periods)
        for family in maps[economy]["families"]:
            if family["id"] not in family_ids:
                continue
            for group_id, values in family["holders"].items():
                if group_ids is None or group_id in group_ids:
                    for k, i in enumerate(at[economy]):
                        out[k] += values[i]
        return out

    everything = {economy: tuple(family["id"] for family in maps[economy]["families"]) for economy in ORDER}
    instruments = [{"id": row_id, "name": name,
                    **{economy: measures(economy, outstanding(economy, families[economy])) for economy in ORDER}}
                   for row_id, name, families in INSTRUMENTS]
    holders = [{"id": row_id, "name": name,
                **{economy: measures(economy, outstanding(economy, everything[economy], groups[economy])) for economy in ORDER}}
               for row_id, name, groups in HOLDERS]
    return {
        "periods": periods,
        "economies": [{"id": economy, "name": economies.ECONOMIES[economy]["name"], "currency": economies.ECONOMIES[economy]["currency"]}
                      for economy in ORDER],
        "gdp": {economy: measures(economy, [value or 0.0 for value in gdp[economy]]) for economy in ORDER},
        "total": {economy: measures(economy, outstanding(economy, everything[economy])) for economy in ORDER},
        "usd_per_eur": rate,
        "instruments": instruments,
        "holders": holders,
        "notes": {
            "conversion": "Euro amounts are converted to US dollars at the ECB's reference exchange rate on the last day of "
                          "each quarter, so the dollar size of the euro area moves with the exchange rate as well as with "
                          "the amounts themselves. Share of GDP uses each economy's own GDP over the four quarters ending "
                          "then, and needs no conversion.",
            "matching": "The two sets of accounts follow different rulebooks, so rows are matched as closely as their "
                        "categories allow. Loans include US repo and mortgages. Equity is all equity in both, listed or "
                        "not; unlisted equity has no market price, and the two need not value it alike. The euro area's banks cannot be "
                        "separated from its central banks before 2015, so the three are one row for both. Trade credit, "
                        "derivatives and other accounts are left out of both. Euro-area amounts are unconsolidated: they "
                        "include claims between units of the same sector, such as deposits banks hold with each other.",
            "what_it_is": "Amounts outstanding of each instrument, and what each sector group holds across those "
                          "instruments. Each economy's rest of the world includes the other economy.",
        },
    }
