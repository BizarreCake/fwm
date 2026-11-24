"""Accounting checks on the Treasury holders view, run against the ingested Z.1 release."""

from pathlib import Path

import duckdb
import pytest

from fwm import treasury

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "fwm.duckdb"
TOLERANCE = 2  # USD millions; Z.1 publishes whole millions, so sums can be off by rounding.


@pytest.fixture(scope="module")
def con():
    if not DB_PATH.exists():
        pytest.skip("no ingested data; run `uv run fwm ingest`")
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def view(con):
    return treasury.holders(con)


def test_holders_sum_to_published_total(view):
    for measure in ("level", "transactions"):
        published = view["totals"]["holders_market"][measure]
        for i, period in enumerate(view["periods"]):
            summed = sum(group[measure][i] for group in view["groups"])
            assert abs(summed - published[i]) <= TOLERANCE, (measure, period, summed, published[i])


def test_holders_plus_valuation_gap_equals_liability(view):
    totals = view["totals"]
    for i, period in enumerate(view["periods"]):
        market = totals["holders_market"]["level"][i]
        gap = totals["valuation_gap"]["level"][i]
        face = totals["liability_face"]["level"][i]
        assert abs(market + gap - face) <= TOLERANCE, (period, market, gap, face)


def test_sectors_sum_to_group(view):
    for group in view["groups"]:
        for measure in ("level", "transactions"):
            for i in range(len(view["periods"])):
                assert abs(sum(s[measure][i] for s in group["sectors"]) - group[measure][i]) < 1e-6


def test_level_change_decomposes(view):
    """Δlevel == transactions + other_change, by construction, wherever all three exist."""
    for group in view["groups"]:
        for i in range(1, len(view["periods"])):
            other = group["other_change"][i]
            if other is None:
                continue
            delta = group["level"][i] - group["level"][i - 1]
            assert abs(delta - group["transactions"][i] - other) < 1e-6


def test_quarterly_and_contiguous(view):
    ends = view["period_ends"]
    assert view["periods"][0] == "1952:Q1"
    assert len(ends) == len(set(ends))
    years = int(ends[-1][:4]) - int(ends[0][:4])
    assert len(ends) in range(years * 4, years * 4 + 5)
