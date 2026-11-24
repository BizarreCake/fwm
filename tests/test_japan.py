"""Japan's accounts from the Bank of Japan's flow of funds: accounting identities and the shared interfaces."""

from pathlib import Path

import duckdb
import pytest

from fwm import japan, overview, systemmap, tools

DB = Path(__file__).resolve().parents[1] / "data" / "fwm.duckdb"


@pytest.fixture(scope="module")
def con():
    if not DB.exists():
        pytest.skip("no database; run `uv run fwm ingest`")
    con = duckdb.connect(str(DB), read_only=True)
    if not japan.available(con):
        con.close()
        pytest.skip("no Japanese data; run `uv run fwm ingest --only boj`")
    yield con
    con.close()


@pytest.fixture(scope="module")
def accounts(con):
    return japan.Accounts(con)


def test_sectors_add_up_to_the_published_total_in_every_quarter(accounts):
    n = len(accounts.periods)
    assert accounts.periods[0] == "1997:Q4" and accounts.periods[-1] >= "2026:Q2"
    for item in ("900", "100", "200", "300", "311", "330", "318", "400"):
        for side, letter in (("assets", "A"), ("liabilities", "L")):
            if item == "900" and side == "liabilities":
                continue  # the published liabilities total includes net worth
            total = accounts.data[f"FOF_FFAS700{letter}{item}"]
            code = "F" if item == "900" else f"I{item}"
            parts = [p for sector_id in japan.SECTOR_NAMES if (p := accounts.position(sector_id, side, code))]
            for i in range(n):
                assert sum(p["level"][i] or 0.0 for p in parts) == pytest.approx(total[i], abs=japan.TOLERANCE * len(parts)), (item, side, accounts.periods[i])


def test_lines_add_up_to_total_assets_and_change_is_flow_plus_reconciliation(accounts):
    n = len(accounts.periods)
    for sector_id in ("S430", "S120", "S110", "S500", "S420"):
        total = accounts.position(sector_id, "assets", "F")
        lines = [p for item in japan.TOP if (p := accounts.position(sector_id, "assets", item))]
        for i in (0, n // 2, n - 1):
            assert sum(p["level"][i] or 0.0 for p in lines) == pytest.approx(total["level"][i], abs=japan.TOLERANCE * len(lines))
        for position in (total, accounts.position(sector_id, "assets", "I100"), accounts.position(sector_id, "liabilities", "F")):
            if position is None:
                continue
            for i in range(1, n):
                if None in (position["level"][i], position["level"][i - 1], position["transactions"][i], position["other_change"][i]):
                    continue
                if accounts.periods[i] == japan.BREAK:
                    continue  # the one quarter where the statistics change basis
                change = position["level"][i] - position["level"][i - 1]
                assert change == pytest.approx(position["transactions"][i] + position["other_change"][i], abs=japan.TOLERANCE * 20), (sector_id, accounts.periods[i])


def test_holders_equal_issuers_for_every_instrument_page(con):
    for instrument in japan.list_instruments(con):
        view = japan.view(con, instrument["id"])
        assert view["economy"] == "jp" and view["unit"] == "JPY millions"
        for i in (0, len(view["periods"]) // 2, -1):
            assert view["holders"]["level"][i] == pytest.approx(view["issuers"]["level"][i], rel=1e-6, abs=japan.TOLERANCE * 30), instrument["id"]


def test_known_facts(con):
    sectors = {s["id"]: s for s in japan.list_sectors(con)}
    assert 2.0e9 < sectors["S430"]["total_assets"] < 3.2e9         # households: over two thousand trillion yen
    assert sectors["S430"]["total_liabilities"] < 0.25 * sectors["S430"]["total_assets"]
    assert sectors["S421"]["part_of"] == "S420" and sectors["S500"]["name"] == "Rest of the world"
    bonds = japan.view(con, "I311")
    groups = {g["id"]: g for g in bonds["holders"]["groups"]}
    share = groups["fed"]["level"][-1] / bonds["holders"]["level"][-1]
    assert 0.35 < share < 0.6                                       # the Bank of Japan holds close to half of government bonds
    at = bonds["periods"].index("2012:Q4")
    assert groups["fed"]["level"][at] / bonds["holders"]["level"][at] < 0.15
    assert [g["id"] for g in bonds["issuers"]["groups"] if g["level"][-1] > 0.9 * bonds["issuers"]["level"][-1]] == ["gov_business"]
    sheet = japan.balance_sheet(con, "S110")
    assert sheet["liabilities"]["series"] == "computed" and sheet["assets"]["series"] == "FOF_FFAS110A900"
    deposits = next(c for c in japan.balance_sheet(con, "S430")["assets"]["children"] if c["name"] == "Currency and deposits")
    assert deposits["instrument"] == "I100" and len(deposits["children"]) >= 4
    assert deposits["level"][-1] > 0.4 * sectors["S430"]["total_assets"]   # over half of household assets are cash and deposits


def test_overview_and_system_map(con):
    system = systemmap.load(con, "jp") or systemmap.compute(con, "jp")
    assert system["unit"] == "JPY millions" and [g["id"] for g in system["groups"]][0] == "fed"
    for family in system["families"]:
        assert sum(v[-1] for v in family["holders"].values()) == pytest.approx(sum(v[-1] for v in family["issuers"].values()), rel=1e-6)
    # Three holdings are negative at times, and are real: securities dealers net short of government bonds and of
    # foreign securities, and pension funds that are over-funded and so owe their sponsors. Nothing else is.
    negative = {(family["id"], group) for family in system["families"] for group, v in family["holders"].items() if min(v) < -1e5}
    assert negative <= {("government_bonds", "other_financial"), ("foreign_securities", "other_financial"),
                        ("pensions_insurance", "pensions_insurers")}
    view = overview.load(con, "jp") or overview.compute(con, "jp")
    assert view["period"] == japan.periods(con)[-1] and view["min_flow"] >= 1_000_000
    ranked = {flow["instrument_id"] for flow in view["largest_flows"] + view["unusual_flows"] + view["valuation_changes"]}
    assert "I300" not in ranked and view["largest_flows"]
    assert next(i for i in view["instruments"] if i["id"] == "I300")["composite"]


def test_tools_and_api(con):
    from fastapi.testclient import TestClient

    from fwm import api

    listed = tools.run(con, "list_sectors", {"economy": "jp"})
    assert listed["economy"] == "Japan" and "JPY billions" in listed["unit"]
    bonds = tools.run(con, "get_instrument", {"instrument_id": "I311", "economy": "jp"})
    assert bonds["link"].startswith("#/jp/instrument/I311")
    sector = tools.run(con, "get_sector", {"sector_id": "S110", "economy": "jp"})
    assert sector["link"].startswith("#/jp/sector/S110")
    history = tools.run(con, "get_history", {"series": ["FOF_FFAS110A311"], "start": "2012:Q4"})
    rows = history["series"][0]["observations"]
    assert history["unit"] == "JPY billions" and rows[-1]["amount"] > 3 * rows[0]["amount"] and "Bank of Japan" in history["series"][0]["description"]
    rates = tools.run(con, "get_rates_and_gdp", {"economy": "jp"})
    assert rates["quarters"][-1]["gdp"] > 500_000 and 100 < rates["quarters"][-1]["yen_per_usd_at_quarter_end"] < 250
    assert rates["policy_rate_changes"][-1]["rate"] == rates["latest_daily"]["policy"]["value"]
    events = tools.run(con, "get_fed_announcements", {"economy": "jp"})
    assert events["central_bank"] == "Bank of Japan" and len(events["events"]) >= 12
    assert all(event["url"].startswith("https://www.boj.or.jp/en/mopo/mpmdeci/") for event in events["events"])
    shared = tools.run(con, "get_history", {"series": ["FOF_FFAS420L311"], "share_of_gdp": True, "start": "2024:Q4"})
    assert 100 < shared["series"][0]["observations"][-1]["amount_pct_of_gdp"] < 250
    for name, arguments in (("get_fed_weekly", {"economy": "jp"}),
                            ("get_history", {"series": ["FOF_FFAS110A311", "LM263061105.Q"]}), ("get_history", {"series": ["FOF_FFAS999A311"]})):
        with pytest.raises(tools.ToolError):
            getattr(tools, name)(con, **arguments)
    assert tools.run(con, "get_system_map", {"economy": "jp"}) and tools.run(con, "latest_moves", {"kind": "largest_flows", "economy": "jp"})
    client = TestClient(api.app)
    assert client.get("/api/economy/jp/sectors/S430").json()["unit"] == "JPY millions"
    assert client.get("/api/economy/jp/instruments/I311").json()["name"].startswith("Government bonds")
    assert client.get("/api/economy/jp/overview").status_code == 200 and client.get("/api/economy/jp/system-map").status_code == 200
    assert client.get("/api/economy/jp/context").json()["central_bank"] == "Bank of Japan"
    assert client.get("/api/economy/jp/weekly/central-bank").status_code == 404
    compared = client.get("/api/compare").json()
    assert [e["id"] for e in compared["economies"]] == ["us", "ea", "jp"]
    debt = compared["instruments"][0]["jp"]
    assert debt["usd"][-1] == pytest.approx(debt["native"][-1] / compared["yen_per_usd"][-1]) and 150 < debt["pct_of_gdp"][-1] < 400
    assert client.get("/api/economy/jp/sectors/S1M").status_code == 404


def test_the_break_in_2005_is_the_only_unexplained_step(accounts):
    n = len(accounts.periods)
    unexplained = set()
    for sector_id in japan.SECTOR_NAMES:
        for item in japan.TOP:
            position = accounts.position(sector_id, "assets", item)
            if position is None:
                continue
            for i in range(1, n):
                values = (position["level"][i], position["level"][i - 1], position["transactions"][i], position["other_change"][i])
                if None not in values and abs(values[0] - values[1] - values[2] - values[3]) > japan.TOLERANCE * 20:
                    unexplained.add(accounts.periods[i])
    assert unexplained == {japan.BREAK}
