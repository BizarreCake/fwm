"""A benchmark for the agent: questions with answers that can be checked against the data.

Expected figures are computed from the database when the benchmark runs, so the
questions stay valid across Z.1 releases. Grading is mechanical: the right
numbers appear in the answer, the right limits of the data were flagged, and
everything cited was actually looked up. It does not judge prose.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import duckdb

from fwm import agent, economies, euroarea, tools


@dataclass
class Transcript:
    """What one turn produced, gathered from the agent's events."""
    answer: str = ""
    calls: list[dict] = field(default_factory=list)   # {name, input, ok, result}
    gaps: list[dict] = field(default_factory=list)    # {category, explanation}
    error: str | None = None
    usage: dict = field(default_factory=dict)

    @classmethod
    def collect(cls, events) -> "Transcript":
        out = cls()
        for event in events:
            if event["type"] == "text":
                out.answer += event["text"]
            elif event["type"] == "break":
                out.answer += "\n\n" if out.answer and not out.answer.endswith("\n\n") else ""
            elif event["type"] == "tool":
                out.calls.append({k: event[k] for k in ("name", "input", "ok", "result")})
            elif event["type"] == "gap":
                out.gaps.append({"category": event["category"], "explanation": event["explanation"]})
            elif event["type"] == "error":
                out.error = event["message"]
            elif event["type"] == "done":
                out.usage = event["usage"]
        return out


# ---- reading numbers out of prose -------------------------------------------------

_SCALE = {"trillion": 1000.0, "tn": 1000.0, "t": 1000.0, "billion": 1.0, "bn": 1.0, "b": 1.0,
          "million": 0.001, "mn": 0.001, "m": 0.001}
_MONEY = re.compile(r"(?:\$|€|¥|EUR\s|JPY\s)\s?([\d,]+(?:\.\d+)?)\s?(trillion|billion|million|tn|bn|mn|t|b|m)\b", re.IGNORECASE)
_PERCENT = re.compile(r"([\d,]+(?:\.\d+)?)\s?(?:%|percent|percentage points?)", re.IGNORECASE)


def amounts(text: str) -> list[float]:
    """Dollar or euro amounts mentioned in the text, in billions of whichever currency they are in."""
    return [float(number.replace(",", "")) * _SCALE[unit.lower()] for number, unit in _MONEY.findall(text)]


def percents(text: str) -> list[float]:
    return [float(number.replace(",", "")) for number in _PERCENT.findall(text)]


# ---- checks ------------------------------------------------------------------------

Check = Callable[[Transcript, duckdb.DuckDBPyConnection], str | None]


def amount(what: str, *references: Callable[[duckdb.DuckDBPyConnection], float], tolerance: float = 0.03) -> Check:
    """The answer states this dollar amount (billions), within a tolerance that allows for rounding.

    With several references, any one will do: some questions have a correct answer in each of two sources.
    """
    def check(transcript: Transcript, con: duckdb.DuckDBPyConnection) -> str | None:
        expected = [abs(reference(con)) for reference in references]
        found = amounts(transcript.answer)
        if any(abs(value - e) <= max(tolerance * e, 0.6) for value in found for e in expected):
            return None
        wanted = " or ".join(f"${e:,.1f}B" for e in expected)
        return f"{what}: expected about {wanted}, answer mentions {[round(v, 1) for v in found] or 'no dollar amounts'}"
    return check


def percent(what: str, reference: Callable[[duckdb.DuckDBPyConnection], float], tolerance: float = 0.35) -> Check:
    def check(transcript: Transcript, con: duckdb.DuckDBPyConnection) -> str | None:
        expected = abs(reference(con))
        found = percents(transcript.answer)
        if any(abs(value - expected) <= tolerance for value in found):
            return None
        return f"{what}: expected about {expected:.1f}%, answer mentions {found or 'no percentages'}"
    return check


def mentions(*any_of: str) -> Check:
    def check(transcript: Transcript, con: duckdb.DuckDBPyConnection) -> str | None:
        text = transcript.answer.lower()
        return None if any(term.lower() in text for term in any_of) else f"answer does not mention any of {list(any_of)}"
    return check


def gap(*categories: str) -> Check:
    def check(transcript: Transcript, con: duckdb.DuckDBPyConnection) -> str | None:
        flagged = [g["category"] for g in transcript.gaps]
        return None if any(c in flagged for c in categories) else f"expected a data gap of kind {list(categories)}, flagged {flagged}"
    return check


def in_euro(transcript: Transcript, con: duckdb.DuckDBPyConnection) -> str | None:
    """Euro-area amounts are given in euro, never as dollars."""
    if "€" not in transcript.answer and "EUR" not in transcript.answer and "euro" not in transcript.answer.lower():
        return "answer does not give amounts in euro"
    return "answer gives a dollar amount for the euro area" if "$" in transcript.answer else None


def no_gap(transcript: Transcript, con: duckdb.DuckDBPyConnection) -> str | None:
    return f"flagged a data gap for an answerable question: {transcript.gaps}" if transcript.gaps else None


def no_amounts(transcript: Transcript, con: duckdb.DuckDBPyConnection) -> str | None:
    """For questions with nothing to look up: the answer must not produce figures from memory."""
    looked_up = any(call["ok"] and call["name"] not in ("list_instruments", "list_sectors") for call in transcript.calls)
    found = amounts(transcript.answer)
    return f"states dollar amounts without looking anything up: {found}" if found and not looked_up else None


def used(name: str, **arguments: Any) -> Check:
    def check(transcript: Transcript, con: duckdb.DuckDBPyConnection) -> str | None:
        for call in transcript.calls:
            if call["name"] == name and call["ok"] and all(call["input"].get(k) == v for k, v in arguments.items()):
                return None
        return f"expected a call to {name} with {arguments}"
    return check


_SERIES = re.compile(r"\b[A-Z]{2}\d{9}\.Q\b|\bQSA(?:\.[A-Z0-9_]+){18}|\bFOF_FFA[SFR]\d{3}[AL]\d{3}\b")
_LINK = re.compile(r"\]\((#/[^)\s]*)\)")
_ROUTE = re.compile(r"^#/(?:$|country/[\w-]+(?:\?[\w=:&%.-]*)?$|us/(?:weekly/fed|foreign/(?:treasuries|agency|corporate|equities))(?:\?[\w=:&%.-]*)?$|ea$|jp$|links(?:\?pair=(?:us|ea|jp|uk|cn|ky)-(?:us|ea|jp|uk|cn|ky))?$|ea/weekly/eurosystem(?:\?[\w=:&%.-]*)?$|(us|ea|jp)/(instrument|sector)/(\w+)(?:\?[\w=:&%.-]*)?$)")
_WEEKLY_SERIES = re.compile(r"H\.4\.1 (RES[A-Z0-9]+)")


def grounded(transcript: Transcript, con: duckdb.DuckDBPyConnection) -> str | None:
    """Applied to every question: cited series were looked up, links lead to real pages, and the turn completed."""
    if transcript.error:
        return f"turn failed: {transcript.error}"
    if not transcript.answer.strip():
        return "no answer"
    seen = json.dumps([call["result"] for call in transcript.calls]) + json.dumps([call["input"] for call in transcript.calls])
    invented = sorted({s for s in _SERIES.findall(transcript.answer) + _WEEKLY_SERIES.findall(transcript.answer) if s not in seen})
    if invented:
        return f"cites series that no tool returned: {invented}"
    valid = {}
    for economy in economies.ECONOMIES:
        try:
            valid[economy, "instrument"] = {row["id"] for row in tools.list_instruments(con, economy)["instruments"]}
            valid[economy, "sector"] = {row["id"] for row in tools.list_sectors(con, economy)["sectors"]}
        except tools.ToolError:
            valid[economy, "instrument"] = valid[economy, "sector"] = set()
    for link in _LINK.findall(transcript.answer):
        match = _ROUTE.match(link)
        if not match or (match.group(1) and match.group(3) not in valid[match.group(1), match.group(2)]):
            return f"links to a page that does not exist: {link}"
    if amounts(transcript.answer) and not any(call["ok"] for call in transcript.calls):
        return "states dollar amounts without any successful lookup"
    return None


# ---- reference values --------------------------------------------------------------

def _group(con, instrument_id: str, side: str, group_id: str, period: str | None = None, compare_to: str | None = None) -> dict:
    view = tools.get_instrument(con, instrument_id, period, compare_to)
    return next(g for g in view[side]["groups"] if g["group_id"] == group_id)


def _country(con, name: str | None, asset: str = "treasuries") -> dict:
    """One country's row in the ranking; with no name, the largest holder."""
    rows = tools.get_foreign_holders(con, asset, top=80)["countries"]
    return next(row for row in rows if name is None or row["name"] == name)


def _ea_government_debt(con) -> dict:
    side = tools.get_instrument(con, "F3", compare_to="2019:Q4", economy="ea")["issuers"]
    group = next(g for g in side["groups"] if g["group_id"] == "gov_business")
    return next(s for s in group["sectors"] if s["sector_id"] == "S13")


def _country_pair(con: duckdb.DuckDBPyConnection, kind_id: str, holder: str, issuer: str) -> float:
    from fwm import links
    kind = next(kind for kind in links.pair(con, (holder,), (issuer,)) if kind["id"] == kind_id)
    return kind["directions"][0]["history"][-1]["value"] / 1000


def _jp(con: duckdb.DuckDBPyConnection, sector_id: str, side: str, code: str) -> float:
    from fwm import japan
    return japan.Accounts(con).position(sector_id, side, code)["level"][-1] / 1000


def _link(con: duckdb.DuckDBPyConnection, kind_id: str, holder: str, issuer: str) -> float:
    from fwm import links
    kind = next(kind for kind in links.view(con)["kinds"] if kind["id"] == kind_id)
    return kind["matrix"][holder][issuer]["level"][-1] / 1000


def _ea_pair(con, holder: str, issuer: str, instrument_id: str = "F3") -> float:
    return euroarea.who_to_whom(con, instrument_id)["matrix"][holder][issuer]["level"][-1] / 1000


def _fed_week(con, line_id: str, date: str | None = None, compare_to: str | None = None) -> dict:
    sheet = tools.get_fed_weekly(con, date, compare_to)
    return next(row for row in sheet["assets"] + sheet["liabilities_and_capital"] if row["line"] == line_id)


def _line(con, sector_id: str, side: str, starts_with: str, period: str | None = None) -> dict:
    view = tools.get_sector(con, sector_id, period)
    return next(l for l in view[side]["lines"] if l["line"].lower().startswith(starts_with.lower()))


def _total(con, sector_id: str, side: str = "assets", period: str | None = None) -> float:
    return tools.get_sector(con, sector_id, period)[side]["total"]["amount"]


def _gdp(con, period: str) -> float:
    return tools.get_rates_and_gdp(con, period, period)["quarters"][0]["gdp"]


def _rate(con, period: str, rate: str) -> float:
    return tools.get_rates_and_gdp(con, period, period)["quarters"][0][rate]


@dataclass
class Question:
    id: str
    text: str
    checks: list[Check]
    kind: str = "answerable"   # answerable | partial | out_of_scope


QUESTIONS: list[Question] = [
    # -- answerable from the data --
    Question("treasury-largest-holder", "Who is the largest holder of US Treasuries right now, and what share do they hold?", [
        mentions("rest of the world", "foreign"),
        percent("foreign share of Treasuries", lambda con: _group(con, "F3_2", "holders", "row")["share_pct"]),
        used("get_instrument", instrument_id="F3_2"), no_gap]),
    Question("fed-treasury-level", "How much in Treasury securities does the Federal Reserve hold?", [
        amount("Fed Treasury holdings", lambda con: _group(con, "F3_2", "holders", "fed")["amount"],
               lambda con: _fed_week(con, "treasuries")["amount"]), no_gap]),
    Question("fed-treasury-since-2022", "How have the Fed's Treasury holdings changed since the first quarter of 2022?", [
        amount("change in Fed Treasury holdings", lambda con: _group(con, "F3_2", "holders", "fed", None, "2022:Q1")["change"]["change_in_amount"]),
        no_gap]),
    Question("household-equities-decomposition",
             "Last quarter, how much of the change in households' corporate equity holdings came from buying versus prices?", [
        amount("household equity purchases", lambda con: _group(con, "F51_1", "holders", "households")["net_transactions_in_quarter"], tolerance=0.05),
        amount("household equity valuation change", lambda con: _group(con, "F51_1", "holders", "households")["valuation_and_other_in_quarter"]),
        no_gap]),
    Question("mmf-assets", "How big are money market funds in total?", [
        amount("money market fund assets", lambda con: _total(con, "S123")), no_gap]),
    Question("fed-largest-asset", "In the latest quarterly accounts, what is the Fed's largest asset and how much of its balance sheet is it?", [
        mentions("treasur"),
        percent("Treasury share of Fed assets", lambda con: _line(con, "S121", "assets", "total treasury")["share_pct"], 1.0),
        used("get_sector", sector_id="S121"), no_gap]),
    Question("mortgage-debtors", "Who owes the most mortgage debt, and how much?", [
        mentions("household"),
        amount("household mortgage debt", lambda con: _group(con, "F4_5", "issuers", "households")["amount"]), no_gap]),
    Question("unusual-flows", "What was the most unusual flow in the latest quarter?", [
        mentions("exchange-traded", "etf"),
        amount("largest unusual flow", lambda con: tools.latest_moves(con, "unusual_flows")["moves"][0]["amount"]),
        used("latest_moves", kind="unusual_flows"), no_gap]),
    Question("mmf-treasuries-2020", "How much did money market funds' Treasury holdings change between Q4 2019 and Q2 2020?", [
        amount("change in money fund Treasuries", lambda con: _group(con, "F3_2", "holders", "mmf", "2020:Q2", "2019:Q4")["change"]["change_in_amount"]),
        no_gap]),
    Question("fed-funds-2023", "What did the federal funds rate average in the second quarter of 2023?", [
        percent("fed funds, 2023:Q2", lambda con: _rate(con, "2023:Q2", "fed_funds"), 0.06), used("get_rates_and_gdp"), no_gap]),
    Question("march-2020-announcements", "What did the Fed announce in March 2020?", [
        mentions("0 to 1/4", "0–0.25", "0-0.25", "0 to 0.25", "zero", "near zero"), mentions("purchas"),
        used("get_fed_announcements"), no_gap]),
    Question("fed-assets-gdp", "How large was the Fed's balance sheet relative to GDP in the first quarter of 2022?", [
        percent("Fed assets as % of GDP, 2022:Q1", lambda con: 100 * _total(con, "S121", "assets", "2022:Q1") / _gdp(con, "2022:Q1"), 0.6),
        no_gap]),
    Question("mmf-repo", "How much do money market funds lend through repo?", [
        amount("money fund repo lending", lambda con: _group(con, "F4_1", "holders", "mmf")["amount"]), no_gap]),
    Question("agency-holders", "Which group holds the most agency and GSE-backed securities?", [
        mentions("bank"),
        amount("bank agency holdings", lambda con: _group(con, "F3_3", "holders", "banks")["amount"]), no_gap]),
    Question("treasury-absorption", "The Treasury borrowed last quarter. Which sectors bought the most of that debt?", [
        mentions("household"),
        amount("household Treasury purchases", lambda con: _group(con, "F3_2", "holders", "households")["net_transactions_in_quarter"], tolerance=0.05),
        no_gap]),
    # -- partly answerable: give the aggregate and flag what is missing --
    Question("deposits-by-country", "Which countries hold the most deposits in US banks?", [
        gap("entity"), no_amounts], "partial"),
    Question("mmf-to-dealers", "How much do money market funds lend to broker-dealers in repo?", [
        gap("counterparty"),
        amount("money fund repo lending in total", lambda con: _group(con, "F4_1", "holders", "mmf")["amount"])], "partial"),
    Question("why-foreign-equities", "Why did foreign investors buy so much US equity last quarter?", [
        gap("causation"),
        amount("foreign equity purchases", lambda con: _group(con, "F51_1", "holders", "row")["net_transactions_in_quarter"], tolerance=0.05)], "partial"),
    Question("named-bank", "How many Treasuries does JPMorgan hold?", [gap("entity"), no_amounts], "partial"),
    # -- foreign Treasury holdings by country --
    Question("treasury-by-country", "Which countries hold the most US Treasuries?", [
        mentions("Japan"), mentions("custod"),
        amount("Japan's holdings", lambda con: _country(con, "Japan")["amount"]),
        used("get_foreign_holders"), no_gap]),
    Question("equities-by-country", "Which countries hold the most US equities?", [
        mentions("custod"),
        amount("the largest holder's equities", lambda con: _country(con, None, "equities")["amount"]),
        used("get_foreign_holders", asset="equities"), no_gap]),
    Question("japan-corporate-bonds", "How much in US corporate bonds do Japanese investors hold?", [
        amount("Japan's corporate bonds", lambda con: _country(con, "Japan", "corporate")["amount"]), no_gap]),
    Question("china-treasuries-year", "How have China's Treasury holdings changed over the past year?", [
        amount("change in China's holdings", lambda con: _country(con, "China, Mainland")["change_since_compare_to"], tolerance=0.06),
        no_gap]),
    Question("official-share", "How much of foreign Treasury holdings belongs to central banks and governments?", [
        amount("official holdings", lambda con: tools.get_foreign_holders(con)["official"]["amount"]), no_gap]),
    Question("us-holdings-in-japan", "How much do US investors hold in Japanese securities, and how much does Japan hold in US securities?", [
        amount("US holdings of Japanese securities", lambda con: tools.get_country(con, "Japan")["this_countrys_securities_held_by_us_residents"]["total"]["amount"]),
        amount("Japan's holdings of US securities", lambda con: tools.get_country(con, "Japan")["us_securities_held_in_this_country"]["total"]["amount"]),
        used("get_country"), no_gap]),
    Question("japan-bought-instead", "Japan has been selling Treasuries. What has it been buying instead?", [
        gap("coverage", "entity")], "partial"),
    # -- the euro area --
    Question("ea-household-assets", "How large are euro area households' financial assets, and what is the biggest part?", [
        amount("household financial assets", lambda con: tools.get_sector(con, "S1M", economy="ea")["assets"]["total"]["amount"]),
        used("get_sector", economy="ea"), mentions("equity", "shares"), in_euro, no_gap]),
    Question("ea-debt-holders", "Who holds euro area debt securities?", [
        amount("debt securities held", lambda con: tools.get_instrument(con, "F3", economy="ea")["holders"]["total"]["amount"]),
        used("get_instrument", economy="ea"), mentions("rest of the world", "non-resident", "foreign", "abroad"), in_euro, no_gap]),
    Question("ea-government-debt-since-2020", "How much have euro area governments' debt securities grown since the end of 2019?", [
        amount("change in government debt securities", lambda con: _ea_government_debt(con)["change"]["change_in_amount"], tolerance=0.05),
        in_euro, no_gap]),
    Question("ea-who-holds-government-debt", "How much euro area government debt do banks hold, and how much is held abroad?", [
        amount("banks' holdings of government debt securities", lambda con: _ea_pair(con, "S12K", "S13")),
        amount("rest of the world's holdings of government debt securities", lambda con: _ea_pair(con, "ROW", "S13")),
        used("get_who_holds_whose"), in_euro, no_gap]),
    Question("us-who-holds-whose", "How much of US corporate bonds issued by banks is held by pension funds?", [
        gap("counterparty")], "partial"),
    Question("jp-jgb-holders", "Who holds Japanese government bonds, and how much does the Bank of Japan have?", [
        used("get_instrument", instrument_id="I311", economy="jp"), mentions("Bank of Japan"),
        amount("Bank of Japan holdings of government bonds", lambda con: _jp(con, "S110", "assets", "I311")),
        mentions("¥", "yen", "JPY"), no_gap]),
    Question("jp-household-assets", "What do Japanese households keep their money in?", [
        used("get_sector", sector_id="S430", economy="jp"), mentions("deposit"),
        amount("household currency and deposits", lambda con: _jp(con, "S430", "assets", "I100")), no_gap]),
    Question("jp-boj-since-2012", "How has the Bank of Japan's balance sheet changed since 2012?", [
        mentions("government bond", "JGB"), amount("Bank of Japan total assets", lambda con: _jp(con, "S110", "assets", "F")), no_gap]),
    Question("jp-rates", "What is the Bank of Japan's policy rate, and when did it last change?", [
        used("get_rates_and_gdp", economy="jp"), mentions("1.25"), mentions("2026"), no_gap]),
    Question("jp-debt-to-gdp", "How big is Japanese government debt next to the economy, compared with the US and euro area?", [
        mentions("gdp"), mentions("Japan"), no_gap]),
    Question("jp-boj-weekly", "What is on the Bank of Japan's balance sheet this week?", [gap("frequency", "coverage")], "partial"),
    Question("links-us-ea", "How much do euro area investors hold of US securities, and how much do Americans hold of euro area ones?", [
        used("get_cross_border_links"),
        amount("euro area holdings of US equity", lambda con: _link(con, "equity", "ea", "us")),
        amount("US holdings of euro area equity", lambda con: _link(con, "equity", "us", "ea")), no_gap]),
    Question("links-japan-us", "How exposed are banks in Japan to the United States?", [
        used("get_cross_border_links"), amount("claims of banks in Japan on US residents", lambda con: _link(con, "bank_claims", "jp", "us")), no_gap]),
    Question("links-offshore-dollars", "How many dollars do banks lend to borrowers outside the United States?", [
        used("get_cross_border_links"), mentions("trillion", "T"), no_gap]),
    Question("links-germany-japan", "How much do German investors hold of Japanese bonds?", [
        used("get_cross_border_links"), amount("German holdings of Japanese debt securities", lambda con: _country_pair(con, "debt", "DE", "JP")), no_gap]),
    Question("links-switzerland", "Which countries do Swiss banks lend to most?", [
        used("get_cross_border_links"), mentions("United States", "US"), mentions("United Kingdom", "UK"), no_gap]),
    Question("links-germany-sectors", "Which German sectors hold US Treasuries: banks, insurers or households?", [
        gap("entity", "coverage", "instrument")], "partial"),
    Question("ea-us-size", "How big is the euro area's bond market next to the US one?", [
        used("compare_economies"), mentions("gdp"), mentions("exchange rate", "per euro", "converted"), no_gap]),
    Question("ea-ecb-balance-sheet-now", "How large is the ECB's balance sheet right now, and how much has it shrunk from its peak?", [
        amount("Eurosystem total assets, latest week", lambda con: tools.get_fed_weekly(con, economy="ea")["total_assets"]["amount"]),
        amount("peak total assets", lambda con: tools.get_fed_weekly_history(con, ["total_assets"], "2008-01-04", economy="ea")["lines"][0]["highest_week"]["amount"]),
        in_euro, no_gap]),
    Question("ea-rates", "What is the ECB's deposit rate now, and when did it last change?", [
        mentions("2.5"), mentions("2026"), used("get_rates_and_gdp", economy="ea"), no_gap]),
    Question("ea-germany", "How much do German households hold in deposits?", [
        gap("entity", "coverage")], "partial"),
    Question("ea-countries", "Which countries hold the most euro area government debt?", [
        gap("entity", "coverage")], "partial"),
    Question("ea-us-compare", "Do households hold more of their financial wealth in deposits in the euro area or in the US?", [
        used("get_sector", economy="ea"), mentions("%", "percent", "share"), no_gap]),
    # -- the weekly Federal Reserve balance sheet --
    Question("reserves-now", "How large are bank reserves at the Fed right now?", [
        amount("reserve balances, latest week", lambda con: _fed_week(con, "reserves")["amount"]),
        used("get_fed_weekly"), no_gap]),
    Question("tga-since-quarter", "How has the Treasury's cash balance at the Fed changed since the end of June?", [
        amount("change in the Treasury General Account", lambda con: _fed_week(con, "tga", None, "2026-06-30")["change_since_compare_to"], tolerance=0.08),
        no_gap]),
    Question("fed-assets-peak", "When did the Fed's balance sheet peak, and how big was it?", [
        amount("peak total assets", lambda con: tools.get_fed_weekly_history(con, ["total_assets"], "2008-01-02")["lines"][0]["highest_week"]["amount"]),
        mentions("2022"), no_gap]),
    Question("who-uses-rrp", "Which money market funds are using the Fed's reverse repo facility this week?", [
        gap("entity", "counterparty")], "partial"),
    # -- outside the data --
    Question("last-week", "What happened to money market fund assets last week?", [gap("frequency")], "out_of_scope"),
    Question("forecast", "Will the Fed start buying Treasuries again next year?", [gap("forecast")], "out_of_scope"),
    Question("maturity", "What is the average maturity of the Treasuries held by foreign investors?", [gap("detail")], "out_of_scope"),
    Question("off-topic", "What is the market capitalisation of the Tokyo Stock Exchange?", [gap("coverage", "entity"), no_amounts], "out_of_scope"),
]


def grade(question: Question, transcript: Transcript, con: duckdb.DuckDBPyConnection) -> list[str]:
    """Reasons this answer fails; empty if it passes."""
    return [failure for check in [grounded, *question.checks] if (failure := check(transcript, con))]


def run(con: duckdb.DuckDBPyConnection, only: list[str] | None = None, client: Any = None, report=print) -> dict:
    results = []
    for question in QUESTIONS:
        if only and question.id not in only:
            continue
        transcript = Transcript.collect(agent.answer(con, {}, question.text, client))
        failures = grade(question, transcript, con)
        report(f"{'PASS' if not failures else 'FAIL'}  {question.id}")
        for failure in failures:
            report(f"      {failure}")
        results.append({"id": question.id, "kind": question.kind, "question": question.text, "passed": not failures,
                        "failures": failures, "answer": transcript.answer, "gaps": transcript.gaps,
                        "calls": [{"name": c["name"], "input": c["input"], "ok": c["ok"]} for c in transcript.calls],
                        "usage": transcript.usage, "error": transcript.error})
        if transcript.error == agent.SETUP_HINT:
            break
    passed = sum(r["passed"] for r in results)
    return {"backend": agent.describe(), "effort": agent.EFFORT, "passed": passed, "total": len(results), "results": results}
