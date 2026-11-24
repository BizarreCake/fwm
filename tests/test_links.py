"""Links between economies: IMF portfolio positions and BIS bank positions by pair."""

from pathlib import Path

import duckdb
import pytest

from fwm import links, tools

DB = Path(__file__).resolve().parents[1] / "data" / "fwm.duckdb"


@pytest.fixture(scope="module")
def con():
    if not DB.exists():
        pytest.skip("no database; run `uv run fwm ingest`")
    con = duckdb.connect(str(DB), read_only=True)
    if not links.available(con):
        con.close()
        pytest.skip("no cross-border data; run `uv run fwm ingest --only links`")
    yield con
    con.close()


@pytest.fixture(scope="module")
def view(con):
    return links.view(con)


def kind(view, kind_id):
    return next(k for k in view["kinds"] if k["id"] == kind_id)


def test_every_kind_has_all_reporting_economies_on_one_quarterly_axis(view):
    assert [k["id"] for k in view["kinds"]] == list(links.KIND_IDS)
    for k in view["kinds"]:
        assert k["periods"] == links._quarters(k["periods"][0], k["periods"][-1])
        assert k["holders"] == ["us", "ea", "jp", "uk", "cn", "ky"]
        for holder in k["holders"]:
            assert holder not in k["matrix"][holder] and set(k["matrix"][holder]) == set(view["columns"]) - {holder}
    assert kind(view, "equity")["periods"][0] == "2001:Q4" and kind(view, "bank_claims")["periods"][0] == "1999:Q1"
    assert kind(view, "bank_claims")["periods"][-1] >= kind(view, "equity")["periods"][-1] >= "2025:Q4"


def test_rows_add_up_to_the_reported_total(view):
    for k in view["kinds"]:
        for holder in k["holders"]:
            row = k["matrix"][holder]
            for i in (-1, -9, len(k["periods"]) // 2):
                listed = [row[c]["level"][i] for c in view["columns"] if c not in (holder, "world")]
                if any(value is None for value in listed) or row["world"]["level"][i] is None:
                    continue
                assert sum(listed) == pytest.approx(row["world"]["level"][i], rel=1e-9)
                assert row["other"]["level"][i] >= -0.02 * row["world"]["level"][i]


def test_single_countries_match_the_source_rows(con, view):
    for kind_id, counterpart in (("equity", "JPN"), ("bank_claims", "JP")):
        k = kind(view, kind_id)
        value = con.execute("SELECT value FROM xb_positions WHERE kind = ? AND denom = 'all' AND reporter = 'US' AND counterpart = ? "
                            "AND period = ?", [kind_id, counterpart, k["periods"][-1]]).fetchone()[0]
        assert k["matrix"]["us"]["jp"]["level"][-1] == pytest.approx(value)


def test_euro_area_is_its_members_without_positions_between_them(con, view):
    k = kind(view, "debt")
    period = k["periods"][-1]
    members3 = [iso3 for iso3, _ in links.EURO_MEMBERS.values()]
    marks = ", ".join("?" for _ in members3)
    on_world, on_members, on_us = (con.execute(
        f"SELECT sum(value) FROM xb_positions WHERE kind = 'debt' AND period = ? AND reporter IN ({', '.join('?' for _ in links.EURO_MEMBERS)}) "
        f"AND counterpart IN ({which})", [period, *links.EURO_MEMBERS, *codes]).fetchone()[0]
        for which, codes in (("?", ["G001"]), (marks, members3), ("?", ["USA"])))
    row = k["matrix"]["ea"]
    assert row["world"]["level"][-1] == pytest.approx(on_world - on_members)
    assert row["us"]["level"][-1] == pytest.approx(on_us)
    assert on_members > 0.3 * on_world  # a large part of members' foreign holdings is of each other
    assert "Finland" in row["us"]["missing"] or row["us"]["missing"] == []
    assert len(k["reporting"]["ea"]) >= 19 and len(kind(view, "bank_claims")["reporting"]["ea"]) >= 12


def test_partial_periods_are_left_empty_not_shown_as_falls(view):
    # Some members reported portfolio holdings only at year ends before 2013; a sum of the rest is not published.
    k = kind(view, "equity")
    level = dict(zip(k["periods"], k["matrix"]["ea"]["us"]["level"]))
    assert level["2010:Q2"] is None and level["2010:Q4"] is not None and level["2011:Q4"] is not None
    published = [value for value in k["matrix"]["ea"]["us"]["level"] if value is not None]
    # The largest fall between published dates is the 2008 crash (about 40%), not a missing reporter.
    assert all(later > 0.5 * earlier for earlier, later in zip(published, published[1:]))


def test_economies_without_country_detail_have_totals_only(view):
    for kind_id in ("bank_claims", "bank_liabilities"):
        row = kind(view, kind_id)["matrix"]["cn"]
        assert row["world"]["level"][-1] > 1e6 and row["us"]["level"][-1] is None and row["other"]["level"][-1] is None
    assert kind(view, "equity")["matrix"]["cn"]["us"]["level"][-1] > 0


def test_all_banks_by_currency(view):
    banks = view["all_banks"]
    world, us = banks["areas"]["world"]["claims"], banks["areas"]["us"]["claims"]
    assert banks["periods"][0] == "1999:Q1"
    for i in (0, -1):
        assert world["usd"][i] + world["eur"][i] < world["all"][i] and us["usd"][i] < world["usd"][i]
    assert us["usd"][-1] > 0.7 * us["all"][-1]              # claims on US residents are mostly in dollars
    assert world["usd"][-1] - us["usd"][-1] > 10e6           # more than $10T of dollar claims on residents elsewhere
    ea = banks["areas"]["ea"]["claims"]
    assert ea["eur"][-1] > ea["usd"][-1]


def test_tool_answers_overall_one_economy_and_one_pair(con, view):
    overall = tools.run(con, "get_cross_border_links", {})
    assert [table["what"] for table in overall["tables"]] == [k["name"] for k in view["kinds"]] and overall["link"] == "#/links"
    equity = overall["tables"][0]
    us = next(row for row in equity["rows"] if row["row"] == "United States")
    assert us["Euro area"] == pytest.approx(kind(view, "equity")["matrix"]["us"]["ea"]["level"][-1] / 1000, abs=0.06)
    assert next(row for row in overall["tables"][2]["rows"] if row["row"] == "China")["United States"] is None
    one = tools.run(con, "get_cross_border_links", {"economy": "Japan"})
    assert one["economy"] == "Japan" and len(one["by_kind"]) == 4
    pair = tools.run(con, "get_cross_border_links", {"economy": "eurozone", "other": "US"})
    assert pair["pair"] == ["Euro area", "United States"] and pair["link"] == "#/links?pair=ea-us"
    debt = pair["by_kind"][1]["directions"]
    assert debt[0]["amount"] == pytest.approx(kind(view, "debt")["matrix"]["ea"]["us"]["level"][-1] / 1000, abs=0.06)
    assert debt[0]["history"][-1]["period"] == "2025:Q4" and all(point["amount"] is not None for point in debt[0]["history"])
    china = tools.run(con, "get_cross_border_links", {"economy": "cn", "other": "us"})
    assert china["by_kind"][2]["directions"][0]["amount"] is None and "does not publish" in china["by_kind"][2]["directions"][0]["why_missing"]
    for bad in ({"economy": "Germany"}, {"economy": "us", "other": "us"}, {"other": "us"}):
        with pytest.raises(tools.ToolError):
            tools.get_cross_border_links(con, **bad)


def test_api_serves_the_view(view):
    from fastapi.testclient import TestClient

    from fwm import api

    body = TestClient(api.app).get("/api/links").json()
    assert [area["id"] for area in body["areas"]] == ["us", "ea", "jp", "uk", "cn", "ky"] and body["kinds"][0]["periods"] == view["kinds"][0]["periods"]
