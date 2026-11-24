"""Checks on the context data: rates, GDP and the event calendar."""

import datetime as dt
from pathlib import Path

import duckdb
import pytest

from fwm import context, instruments

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "fwm.duckdb"


@pytest.fixture(scope="module")
def loaded():
    if not DB_PATH.exists():
        pytest.skip("no ingested data; run `uv run fwm ingest`")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        yield context.view(con), con
    finally:
        con.close()


def test_events_are_dated_sourced_and_in_order():
    events = context.load_events()
    assert len(events) >= 20
    dates = [dt.date.fromisoformat(event["date"]) for event in events]
    assert dates == sorted(dates)
    for event, date in zip(events, dates):
        assert event["kind"] in context.EVENT_KINDS, event
        assert event["title"] and event["detail"], event
        # Each entry cites the Federal Reserve press release published on that date.
        assert event["url"].startswith("https://www.federalreserve.gov/newsevents/pressreleases/"), event
        assert f"{date:%Y%m%d}" in event["url"], event
        assert event["period"] == f"{date.year}:Q{(date.month - 1) // 3 + 1}"


def test_context_shares_the_quarters_of_the_account_pages(loaded):
    view, con = loaded
    assert view["periods"] == instruments.view(con, "F3_2")["periods"]
    for event in view["events"]:
        assert view["periods"][event["index"]] == event["period"]
    for rate in view["rates"]:
        assert len(rate["values"]) == len(view["periods"])
    assert len(view["gdp"]["values"]) == len(view["periods"])


def test_rates_agree_with_the_fed_funds_rate_published_in_z1(loaded):
    """Two independent Fed sources: H.15 daily rates averaged by quarter, and Z.1's quarterly figure.

    Z.1 does not say how it averages, so the two are compared loosely over the last twenty years.
    """
    view, con = loaded
    if not view["rates"]:
        pytest.skip("no rates; run `uv run fwm ingest --only rates`")
    fed_funds = next(rate for rate in view["rates"] if rate["id"] == "fed_funds")
    z1 = dict(con.execute("SELECT period, value FROM z1_observations WHERE series_id = 'FL072052006.Q'").fetchall())
    compared = 0
    for period, value in list(zip(view["periods"], fed_funds["values"]))[-80:]:
        if value is not None and period in z1:
            assert abs(value - z1[period]) <= 0.6, (period, value, z1[period])
            compared += 1
    assert compared >= 70


def test_rates_are_plausible(loaded):
    view, _ = loaded
    if not view["rates"]:
        pytest.skip("no rates")
    assert {rate["id"] for rate in view["rates"]} == {"fed_funds", "treasury_3m", "treasury_2y", "treasury_10y"}
    for rate in view["rates"]:
        values = [v for v in rate["values"] if v is not None]
        assert len(values) >= 150 and rate["values"][-1] is not None
        assert all(0 <= v <= 25 for v in values), rate["id"]


def test_gdp_is_a_four_quarter_sum_and_grows(loaded):
    view, con = loaded
    gdp = view["gdp"]["values"]
    assert all(v is not None for v in gdp)
    quarters = [row[0] for row in con.execute(
        "SELECT value FROM z1_observations WHERE series_id = ? ORDER BY period_end DESC LIMIT 4", [context.GDP_SERIES]
    ).fetchall()]
    assert gdp[-1] == pytest.approx(sum(quarters))
    assert 25e6 < gdp[-1] < 45e6  # tens of trillions of dollars
    assert gdp[-1] > gdp[-41] > gdp[-81]
