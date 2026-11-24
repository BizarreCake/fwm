"""Countries as counterparties of the US, and the economy-scoped API."""

from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from fwm import api, countries, economies, tic, tools

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "fwm.duckdb"


@pytest.fixture(scope="module")
def con():
    if not DB_PATH.exists():
        pytest.skip("no ingested data; run `uv run fwm ingest`")
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    if not tic.available(connection):
        pytest.skip("no TIC data; run `uv run fwm ingest --only tic`")
    yield connection
    connection.close()


def test_listing_has_every_country_once_with_a_page(con):
    rows = countries.listing(con)
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)) and len(ids) >= 70
    assert {"japan", "united-kingdom", "china-mainland", "canada", "cayman-islands", "euro-area"} <= set(ids)
    assert {row["kind"] for row in rows} == {"country", "group"}
    for row in rows:
        assert countries.view(con, row["id"]) is not None, row["id"]
    assert countries.view(con, "atlantis") is None


def test_country_lines_match_the_ranking_pages(con):
    """A country's Treasury line is the same series as its row on the foreign-holders page."""
    for asset in tic.INWARD:
        ranking = {c["name"]: c for c in tic.view(con, asset)["countries"]}
        for country_id in ("japan", "united-kingdom", "canada"):
            view = countries.view(con, country_id)
            line = next(l for l in view["holds_us"]["lines"] if l["id"] == asset)
            assert line["total"] == ranking[view["name"]]["total"]
            assert line["total_net"] == ranking[view["name"]]["total_net"]
            assert line["page"] == f"#/us/foreign/{asset}"


def test_sides_add_up_from_their_lines_every_month(con):
    for country_id in ("japan", "cayman-islands", "euro-area", "greece"):
        view = countries.view(con, country_id)
        for side in (view["holds_us"], view["held_by_us"]):
            for i in range(len(view["periods"])):
                parts = [line["total"][i] for line in side["lines"] if line["total"][i] is not None]
                if parts:
                    assert side["total"][i] == pytest.approx(sum(parts), abs=1)
                else:
                    assert side["total"][i] is None


def test_ranks_are_consistent_with_amounts(con):
    japan = countries.view(con, "japan")
    treasuries = next(l for l in japan["holds_us"]["lines"] if l["id"] == "treasuries")
    ranking = sorted((c for c in tic.view(con, "treasuries")["countries"] if c["total"][-1] is not None), key=lambda c: -c["total"][-1])
    assert ranking[treasuries["rank"] - 1]["name"] == "Japan" and treasuries["ranked_among"] == len(ranking)
    assert all(line["rank"] is None for line in countries.view(con, "euro-area")["holds_us"]["lines"])  # a group is not ranked


def test_us_holdings_abroad_add_up_across_regions(con):
    for asset in tic.OUTWARD:
        view = tic.view(con, asset)
        assert view["direction"] == "outward" and view["official"] is None and view["quarterly"] is None
        for i in range(len(view["periods"])):
            assert sum(region["total"][i] for region in view["regions"]) == pytest.approx(view["total"]["total"][i], abs=1)


def test_country_tool_matches_the_country_page(con):
    view = countries.view(con, "china-mainland")
    result = tools.run(con, "get_country", {"country": "China"})
    assert result["country"] == "China, Mainland" and result["link"] == f"#/country/china-mainland?period={view['periods'][-1]}"
    inward = result["us_securities_held_in_this_country"]
    assert inward["total"]["amount"] == pytest.approx(view["holds_us"]["total"][-1] / 1000, abs=0.06)
    assert sum(line["amount"] for line in inward["by_kind_of_security"]) == pytest.approx(inward["total"]["amount"], abs=0.3)
    assert any("not the country's own balance sheet" in caveat for caveat in result["caveats"])
    with pytest.raises(tools.ToolError):
        tools.run(con, "get_country", {"country": "Atlantis"})


def test_api_is_scoped_by_economy_and_keeps_the_old_paths(con):
    client = TestClient(api.app)
    listed = client.get("/api/economies").json()
    assert [e["id"] for e in listed if e["loaded"]] == ["us", "ea", "jp"] and economies.DEFAULT == "us"
    scoped = client.get("/api/economy/us/sectors")
    assert scoped.status_code == 200 and scoped.json() == client.get("/api/sectors").json()
    assert client.get("/api/economy/us/foreign/equities").json()["id"] == "equities"
    assert client.get("/api/economy/us/foreign/us_foreign_equities").status_code == 404  # outward holdings have no ranking page
    assert client.get("/api/economy/japan/sectors").status_code == 404  # no accounts loaded for Japan
    assert client.get("/api/countries/japan").json()["name"] == "Japan"
    assert client.get("/api/countries/atlantis").status_code == 404
