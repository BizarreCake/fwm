"""Accounting checks on the weekly Federal Reserve balance sheet (H.4.1)."""

import datetime as dt
from pathlib import Path

import duckdb
import pytest

from fwm import fedweekly, sectors

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "fwm.duckdb"


@pytest.fixture(scope="module")
def loaded():
    if not DB_PATH.exists():
        pytest.skip("no ingested data; run `uv run fwm ingest`")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        view = fedweekly.view(con)
        if view is None:
            pytest.skip("no weekly Fed data; run `uv run fwm ingest --only fed-weekly`")
        yield view, con
    finally:
        con.close()


def test_weeks_are_wednesdays_in_order_and_recent(loaded):
    view, _ = loaded
    dates = [dt.date.fromisoformat(period) for period in view["periods"]]
    assert dates == sorted(set(dates)) and len(dates) > 1200
    # Wednesday, or Tuesday/Thursday when the Wednesday was a holiday.
    assert all(date.weekday() in (1, 2, 3) for date in dates)
    assert all(5 <= (later - earlier).days <= 9 for earlier, later in zip(dates, dates[1:]))


def test_each_side_adds_up_to_total_assets_every_week(loaded):
    view, _ = loaded
    for side in ("assets", "liabilities"):
        total = view[side]["total"]
        for i in range(len(view["periods"])):
            assert sum(line["level"][i] for line in view[side]["lines"]) == pytest.approx(total[i], abs=0.01)
    assert view["assets"]["total"] == view["liabilities"]["total"]


def test_sub_lines_add_up_to_their_parent_every_week(loaded):
    view, _ = loaded
    parents = [line for side in ("assets", "liabilities") for line in view[side]["lines"] if line["children"]]
    assert {line["id"] for line in parents} == {"treasuries", "reverse_repo"}
    for line in parents:
        for i in range(len(view["periods"])):
            assert sum(child["level"][i] for child in line["children"]) == pytest.approx(line["level"][i], abs=2), (line["id"], view["periods"][i])


def test_the_computed_other_lines_are_small_in_recent_years(loaded):
    """The named lines explain almost all of today's balance sheet; "other" is not hiding anything large."""
    view, _ = loaded
    for side, limit in (("assets", 0.02), ("liabilities", 0.005)):
        other = view[side]["lines"][-1]
        assert other["computed"] and other["id"].startswith("other_")
        for i in range(len(view["periods"]) - 104, len(view["periods"])):
            assert abs(other["level"][i]) <= limit * view[side]["total"][i], (side, view["periods"][i])


def test_no_line_is_negative_except_deferred_remittances(loaded):
    view, _ = loaded
    for side in ("assets", "liabilities"):
        for line in view[side]["lines"]:
            if line["id"] != "remittances":
                assert min(line["level"]) > -1_000, line["id"]


def test_anchor_is_the_last_week_of_the_latest_quarter_in_the_accounts(loaded):
    view, _ = loaded
    year, quarter = view["quarterly"]["period"].split(":Q")
    anchor = dt.date.fromisoformat(view["periods"][view["quarterly"]["index"]])
    assert (anchor.year, (anchor.month - 1) // 3 + 1) == (int(year), int(quarter))
    following = dt.date.fromisoformat(view["periods"][view["quarterly"]["index"] + 1])
    assert (following.year, (following.month - 1) // 3 + 1) != (int(year), int(quarter))


def test_agrees_with_the_quarterly_accounts_within_valuation_differences(loaded):
    """Z.1 values the Fed's securities at market, H.4.1 at face, so they differ, but not wildly, and move together."""
    view, con = loaded
    sheet = sectors.balance_sheet(con, "S121")
    index = {period: i for i, period in enumerate(sheet["periods"])}
    dates = [dt.date.fromisoformat(period) for period in view["periods"]]
    ratios = []
    for year in range(2004, 2027):
        quarter_end = dt.date(year, 6, 30)
        week = max(i for i, date in enumerate(dates) if date <= quarter_end)
        quarterly = sheet["assets"]["level"][index[f"{year}:Q2"]]
        ratios.append(quarterly / view["assets"]["total"][week])
    assert all(0.8 <= ratio <= 1.1 for ratio in ratios), ratios
    # Before large-scale purchases the two were nearly identical.
    assert all(0.97 <= ratio <= 1.03 for ratio in ratios[:4]), ratios[:4]


def test_events_point_at_the_week_of_the_announcement(loaded):
    view, _ = loaded
    assert len(view["events"]) >= 20
    for event in view["events"]:
        week = dt.date.fromisoformat(view["periods"][event["index"]])
        assert 0 <= (week - dt.date.fromisoformat(event["date"])).days <= 8
