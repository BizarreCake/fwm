"""Accounting checks on the euro area's financial accounts (ECB quarterly sector accounts)."""

from pathlib import Path

import duckdb
import pytest

from fwm import euroarea

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "fwm.duckdb"


@pytest.fixture(scope="module")
def con():
    if not DB_PATH.exists():
        pytest.skip("no ingested data; run `uv run fwm ingest`")
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    if not euroarea.available(connection):
        pytest.skip("no euro-area data; run `uv run fwm ingest --only ecb`")
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def accounts(con):
    return euroarea.Accounts(con)


def test_quarters_run_from_the_start_of_the_euro_without_gaps(accounts):
    periods = accounts.periods
    assert periods[0] == "1999:Q1" and len(periods) >= 110
    for earlier, later in zip(periods, periods[1:]):
        year, quarter = int(earlier[:4]), int(earlier[-1])
        assert later == (f"{year + 1}:Q1" if quarter == 4 else f"{year}:Q{quarter + 1}")


def test_sectors_add_up_to_the_whole_economy_every_quarter(accounts):
    for side in ("assets", "liabilities"):
        whole = accounts.position("S1", side, "F")["level"]
        parts = [accounts.position(sector_id, side, "F")["level"] for sector_id, _, _ in euroarea.SECTORS]
        for i, period in enumerate(accounts.periods):
            assert all(part[i] is not None for part in parts), period
            assert sum(part[i] for part in parts) == pytest.approx(whole[i], abs=30), (side, period)


def test_the_two_parts_of_the_bank_sector_add_up_to_it_once_published(accounts):
    for side in ("assets", "liabilities"):
        whole = accounts.position("S12K", side, "F")["level"]
        parts = [accounts.position(part, side, "F")["level"] for part in ("S121", "S12T")]
        compared = [i for i in range(len(accounts.periods)) if all(part[i] is not None for part in parts)]
        assert accounts.periods[compared[0]] == "2015:Q1" and len(compared) >= 46
        for i in compared:
            assert sum(part[i] for part in parts) == pytest.approx(whole[i], abs=10)


def test_every_balance_sheet_line_equals_its_parts_every_quarter(con):
    def check(node, where):
        if node["children"]:
            for i, total in enumerate(node["level"]):
                values = [child["level"][i] for child in node["children"]]
                if total is not None:
                    assert sum(value or 0.0 for value in values) == pytest.approx(total, abs=20), (where, node["name"], i)
            for child in node["children"]:
                check(child, where)

    for sector in euroarea.list_sectors(con):
        sheet = euroarea.balance_sheet(con, sector["id"])
        check(sheet["assets"], sector["id"])
        check(sheet["liabilities"], sector["id"])
        assert sheet["assets"]["level"][-1] == sector["total_assets"]


def test_computed_remainders_are_small(con):
    for sector in euroarea.list_sectors(con):
        sheet = euroarea.balance_sheet(con, sector["id"])
        for side in (sheet["assets"], sheet["liabilities"]):
            for child in side["children"]:
                if child["series"] == "computed":
                    for i, value in enumerate(child["level"]):
                        if value is not None:
                            assert abs(value) <= 0.002 * abs(side["level"][i]) + 100, (sector["id"], i)


def test_change_in_amount_is_transactions_plus_other_changes(con):
    for sector_id in ("S1M", "S13", "S12K", "ROW"):
        sheet = euroarea.balance_sheet(con, sector_id)
        for node in (sheet["assets"], sheet["liabilities"], *sheet["assets"]["children"]):
            level, transactions, other = node["level"], node["transactions"], node["other_change"]
            checked = 0
            for i in range(1, len(level)):
                if None not in (level[i], level[i - 1], transactions[i], other[i]):
                    assert level[i] - level[i - 1] == pytest.approx(transactions[i] + other[i], abs=5), (sector_id, node["name"], i)
                    checked += 1
            assert checked >= 100, (sector_id, node["name"])


def test_what_is_held_equals_what_is_owed_for_every_instrument(con):
    """With the rest of the world on both sides, every instrument's holders and issuers match."""
    for instrument in euroarea.list_instruments(con):
        view = euroarea.view(con, instrument["id"])
        held, owed = view["holders"]["level"], view["issuers"]["level"]
        for i, period in enumerate(view["periods"]):
            assert held[i] == pytest.approx(owed[i], rel=0.002, abs=200), (instrument["id"], period)
        assert instrument["holders_total"] == held[-1]


def test_groups_cover_every_sector_once_and_parts_are_not_double_counted(con):
    view = euroarea.view(con, "F3")
    assert [group["id"] for group in view["holders"]["groups"]] == [g for g in view["group_order"]]
    for side in (view["holders"], view["issuers"]):
        whole = [sector["code"] for group in side["groups"] for sector in group["sectors"] if not sector.get("part_of")]
        assert sorted(whole) == sorted(euroarea.SECTOR_NAMES)
        for group in side["groups"]:
            counted = [sector for sector in group["sectors"] if not sector.get("part_of")]
            assert sum(sector["level"][-1] for sector in counted) == pytest.approx(group["level"][-1], abs=1)
        assert sum(group["level"][-1] for group in side["groups"]) == pytest.approx(side["level"][-1], abs=1)
    banks = next(group for group in view["holders"]["groups"] if group["id"] == "banks")
    assert [sector["code"] for sector in banks["sectors"]] == ["S12K", "S121", "S12T"]


def test_rest_of_the_world_mirrors_the_euro_areas_external_position(accounts):
    abroad = accounts.position("ROW", "assets", "F3")["level"][-1]
    owed_abroad = accounts.data[("W1", "S1", "liabilities", "F3")]["level"][-1]
    assert abroad == owed_abroad and abroad > 1_000_000


def test_api_serves_the_euro_area_beside_the_us_and_refuses_what_is_us_only(con):
    from fastapi.testclient import TestClient

    from fwm import api

    client = TestClient(api.app)
    listed = client.get("/api/economy/ea/sectors").json()
    assert [row["id"] for row in listed if not row["part_of"]] == list(euroarea.SECTOR_NAMES)
    assert client.get("/api/economy/ea/sectors/S1M").json()["unit"] == "EUR millions"
    assert client.get("/api/economy/ea/instruments/F3").json()["economy"] == "ea"
    assert client.get("/api/economy/ea/sectors/S2").status_code == 404  # a US sector id
    assert client.get("/api/economy/us/sectors/S12K").status_code == 404  # a euro-area sector id
    overview = client.get("/api/economy/ea/overview").json()
    assert overview["period"] == client.get("/api/economy/ea/sectors/S1M").json()["periods"][-1]
    assert overview["largest_flows"] and all(move["series"].startswith("QSA.") for move in overview["largest_flows"])
    assert not any(move["sector_id"] == "S12K" for move in overview["largest_flows"])  # ranked by its two parts instead
    system = client.get("/api/economy/ea/system-map").json()
    assert system["unit"] == "EUR millions"
    for family in system["families"]:
        owed, held = (sum(values[-1] for values in family[side].values()) for side in ("issuers", "holders"))
        assert owed == pytest.approx(held, rel=0.002), family["id"]
    assert client.get("/api/economy/ea/context").json()["central_bank"] == "ECB"
    assert client.get("/api/economy/ea/weekly/central-bank").json()["id"] == "eurosystem"
    assert client.get("/api/economy/us/weekly/central-bank").json()["id"] == "fed"
    for path in ("weekly/fed", "foreign/treasuries"):
        assert client.get(f"/api/economy/ea/{path}").status_code == 404, path


def test_assistant_tools_read_the_euro_area_in_euro(con):
    from fwm import tools

    listed = tools.run(con, "list_sectors", {"economy": "ea"})
    assert listed["unit"].startswith("EUR billions") and listed["link"] == "#/ea"
    view = euroarea.view(con, "F3")
    result = tools.run(con, "get_instrument", {"instrument_id": "F3", "economy": "ea", "compare_to": "2022:Q1"})
    assert result["unit"] == "EUR billions" and result["link"] == f"#/ea/instrument/F3?period={view['periods'][-1]}"
    assert result["holders"]["total"]["amount"] == pytest.approx(view["holders"]["level"][-1] / 1000, abs=0.06)
    change = result["holders"]["total"]["change"]
    assert change["change_in_amount"] == pytest.approx(change["net_transactions"] + change["valuation_and_other"], abs=0.3)
    banks = next(group for group in result["holders"]["groups"] if group["group_id"] == "banks")
    assert sum(s["amount"] for s in banks["sectors"] if "part_of" not in s) == pytest.approx(banks["amount"], abs=0.1)
    series = banks["sectors"][0]["series"]
    history = tools.run(con, "get_history", {"series": [series], "start": "2025:Q1"})
    assert history["unit"] == "EUR billions" and history["series"][0]["observations"][-1]["amount"] == banks["sectors"][0]["amount"]
    sheet = tools.run(con, "get_sector", {"sector_id": "S1M", "economy": "ea"})
    assert sheet["link"].startswith("#/ea/sector/S1M") and sheet["assets"]["total"]["amount"] > 30_000
    for bad in ({"series": [series], "share_of_gdp": True}, {"series": [series, "LM263061105.Q"]}):
        with pytest.raises(tools.ToolError):
            tools.run(con, "get_history", bad)
    with pytest.raises(tools.ToolError):
        tools.run(con, "get_sector", {"sector_id": "S12K"})  # without the economy, this is a US lookup
    assert tools.run(con, "get_sector", {"sector_id": "S121"})["unit"] == "USD billions"


@pytest.mark.parametrize("instrument_id", list(euroarea.WHO_TO_WHOM))
def test_who_holds_whose_adds_up_to_each_sectors_totals(con, accounts, instrument_id):
    view = euroarea.who_to_whom(con, instrument_id)
    code = euroarea.WHO_TO_WHOM[instrument_id][0]
    first = view["periods"].index(view["first_period"])
    assert view["periods"] == accounts.periods and "ROW" in view["holders"] and "ROW" in view["issuers"]
    for holder in view["holders"]:
        if holder == "ROW":
            continue
        total = accounts.position(holder, "assets", code)["level"]
        for i in (first, len(total) - 1):
            held = sum(cell["level"][i] or 0.0 for cell in view["matrix"][holder].values())
            assert held == pytest.approx(total[i], abs=5), (holder, i)
    for row in view["matrix"].values():
        for issuer, cell in row.items():
            assert all(value is None for value in cell["level"][:first])
            # Nothing meaningfully negative: a remainder below zero would mean the parts exceed the whole.
            assert min(value for value in cell["level"][first:] if value is not None) > -500, issuer
            if not cell["computed"]:
                assert cell["series"].startswith("QSA.Q.N.I10.W2.")


def test_who_holds_whose_tool_and_api(con):
    from fastapi.testclient import TestClient

    from fwm import api, tools

    view = euroarea.who_to_whom(con, "F3")
    result = tools.run(con, "get_who_holds_whose", {"instrument_id": "F3", "compare_to": "2022:Q1"})
    top = result["pairs"][0]
    assert (top["holder_id"], top["issuer_id"]) == ("S12K", "S13")
    assert top["amount"] == pytest.approx(view["matrix"]["S12K"]["S13"]["level"][-1] / 1000, abs=0.06)
    assert result["total"] == pytest.approx(sum(row["amount"] for row in result["by_holder"]), abs=0.5)
    assert result["total"] == pytest.approx(sum(row["amount"] for row in result["by_issuer"]), abs=0.5)
    assert len(result["pairs"]) <= 30 and result["link"].startswith("#/ea/instrument/F3")
    history = tools.run(con, "get_history", {"series": [top["series"]], "start": "2025:Q1"})
    assert history["series"][0]["observations"][-1]["amount"] == top["amount"]
    assert "general government" in history["series"][0]["description"]
    with pytest.raises(tools.ToolError):
        tools.run(con, "get_who_holds_whose", {"instrument_id": "F3", "period": "2010:Q1"})  # before the detail starts
    client = TestClient(api.app)
    assert client.get("/api/economy/ea/who-to-whom/F3").json()["first_period"] == "2013:Q4"
    assert client.get("/api/economy/ea/who-to-whom/F6").status_code == 404
    assert client.get("/api/economy/us/who-to-whom/F3").status_code == 404


def test_context_has_rates_gdp_exchange_rate_and_ecb_announcements(con):
    from fwm import eacontext

    if not eacontext.available(con):
        pytest.skip("no euro-area context; run `uv run fwm ingest --only ecb`")
    view = eacontext.view(con)
    assert view["periods"] == euroarea.periods(con) and view["central_bank"] == "ECB"
    rates = {rate["id"]: rate for rate in view["rates"]}
    assert [rate["id"] for rate in view["rates"] if rate["shown"]] == ["policy", "yield_2y", "yield_10y"]
    at = view["periods"].index
    # The deposit rate was negative from mid-2014 to mid-2022 and 4% at its peak.
    assert rates["policy"]["values"][at("2016:Q4")] == pytest.approx(-0.40) and rates["policy"]["values"][at("2023:Q4")] == pytest.approx(4.0)
    assert rates["yield_10y"]["values"][at("2004:Q1")] is None and rates["yield_10y"]["values"][-1] is not None
    gdp = view["gdp"]["values"]
    assert all(value is not None for value in gdp) and 14e6 < gdp[-1] < 20e6  # EUR millions over four quarters
    assert 0.8 < view["fx"]["values"][-1] < 1.6 and view["fx"]["values"][0] is not None
    assert len(view["events"]) >= 15 and all(event["url"].startswith("https://www.ecb.europa.eu/press/pr/date/") for event in view["events"])
    assert [event["date"] for event in view["events"]] == sorted(event["date"] for event in view["events"])


def test_weekly_eurosystem_adds_up_and_reaches_past_the_quarterly_accounts(con):
    from fwm import euweekly, tools

    if not euweekly.available(con):
        pytest.skip("no weekly Eurosystem data; run `uv run fwm ingest --only ecb`")
    view = euweekly.view(con)
    periods = view["periods"]
    assert periods[0] == "1999-01-01" and periods == sorted(periods) and len(set(periods)) == len(periods)
    assert periods[-1] > f"{view['quarterly']['period'][:4]}-{int(view['quarterly']['period'][-1]) * 3:02d}-30"
    for side in ("assets", "liabilities"):
        lines = view[side]["lines"]
        for i in (0, len(periods) // 2, len(periods) - 1):
            assert sum(line["level"][i] for line in lines) == pytest.approx(view[side]["total"][i], abs=1)
        other = lines[-1]
        assert other["computed"] and min(other["level"]) >= 0
    assert view["assets"]["total"] == view["liabilities"]["total"]
    sheet = tools.run(con, "get_fed_weekly", {"economy": "ea"})
    assert sheet["central_bank"] == "Eurosystem" and sheet["unit"].startswith("EUR billions; Friday")
    assert sheet["total_assets"]["amount"] == pytest.approx(view["assets"]["total"][-1] / 1000, abs=0.06)
    assert sheet["link"].startswith("#/ea/weekly/eurosystem") and not any("Fed" in caveat for caveat in sheet["caveats"])
    history = tools.run(con, "get_fed_weekly_history", {"lines": ["total_assets"], "economy": "ea", "start": "2008-01-04"})
    assert history["lines"][0]["highest_week"]["date"].startswith("2022")
    assert tools.run(con, "get_fed_weekly", {})["central_bank"] == "Federal Reserve"


def test_economies_side_by_side_convert_at_the_quarters_rate_and_add_up(con):
    from fastapi.testclient import TestClient

    from fwm import api, compare, context, eacontext, systemmap, tools

    if not compare.available(con):
        pytest.skip("comparison needs the euro area and its context loaded")
    view = compare.view(con)
    assert view["periods"][0] == "1999:Q1" and view["periods"][-1] == euroarea.periods(con)[-1]
    rate = view["usd_per_eur"][-1]
    for economy in ("us", "ea"):
        total = view["total"][economy]
        for section in ("instruments", "holders"):
            assert sum(row[economy]["native"][-1] for row in view[section]) == pytest.approx(total["native"][-1], rel=1e-9)
        own = systemmap.load(con, economy)
        assert total["native"][-1] == pytest.approx(sum(v[-1] for family in own["families"] for v in family["holders"].values()), rel=1e-9)
    euro = view["instruments"][0]["ea"]
    assert euro["usd"][-1] == pytest.approx(euro["native"][-1] * rate) and view["instruments"][0]["us"]["usd"] == view["instruments"][0]["us"]["native"]
    assert euro["pct_of_gdp"][-1] == pytest.approx(100 * euro["native"][-1] / eacontext.gdp(con, view["periods"])[-1])
    assert view["gdp"]["us"]["native"][-1] == pytest.approx(context.gdp(con, view["periods"])[-1])
    result = tools.run(con, "compare_economies", {})
    first = result["outstanding_by_instrument"][0]
    assert first["Euro area"]["usd_billions"] == pytest.approx(first["Euro area"]["eur_billions"] * rate, rel=1e-3)
    assert "eur_billions" not in first["United States"] and result["usd_per_eur"] == rate
    assert TestClient(api.app).get("/api/compare").json()["periods"] == view["periods"]
