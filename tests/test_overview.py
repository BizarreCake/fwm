"""Checks on the latest-quarter overview."""

from pathlib import Path

import duckdb
import pytest

from fwm.economies.us import instruments
from fwm.views import overview

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "fwm.duckdb"


@pytest.fixture(scope="module")
def view():
    if not DB_PATH.exists():
        pytest.skip("no ingested data; run `uv run fwm ingest`")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        yield overview.compute(con), con
    finally:
        con.close()


def test_flows_match_the_instrument_pages(view):
    """Every reported flow is the same number the instrument page shows for that position."""
    data, con = view
    for flow in data["unusual_flows"] + data["largest_flows"]:
        page = instruments.view(con, flow["instrument_id"])
        positions = [s for g in page[flow["side"]]["groups"] for s in g["sectors"] if s["series"] == flow["series"]]
        assert len(positions) == 1
        assert positions[0]["transactions"][-1] == flow["amount"]
        assert flow["history"][-1] == flow["amount"]


def test_rankings_respect_their_rules(view):
    data, _ = view
    assert data["unusual_flows"] and data["largest_flows"] and data["valuation_changes"]
    for flow in data["unusual_flows"]:
        assert abs(flow["score"]) >= overview.UNUSUAL
        assert abs(flow["amount"]) >= overview.MIN_FLOW
    for key in ("unusual_flows", "largest_flows", "valuation_changes"):
        amounts = [abs(f["amount"]) for f in data[key]]
        assert amounts == sorted(amounts, reverse=True)
    composites = {i["id"] for i in data["instruments"] if i["composite"]}
    assert composites and not any(f["instrument_id"] in composites for f in data["largest_flows"])


def test_largest_since_is_correct(view):
    data, _ = view
    for flow in data["largest_flows"]:
        history, now = flow["history"][:-1], flow["amount"]
        bigger = [v for v in history if v is not None and (v >= now if now > 0 else v <= now)]
        if flow["largest_since"] is None or flow["largest_since"] < flow["history_from"]:
            assert not bigger  # nothing as large within the window we carry
        else:
            assert bigger
