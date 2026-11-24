"""Accounting checks on the who-holds / who-owes view of each instrument."""

from pathlib import Path

import duckdb
import pytest

from fwm.economies.us import instruments, sectors

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "fwm.duckdb"
GROUP_IDS = {group_id for group_id, _, _ in instruments.GROUPS}


@pytest.fixture(scope="module")
def con():
    if not DB_PATH.exists():
        pytest.skip("no ingested data; run `uv run fwm ingest`")
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    yield connection
    connection.close()


def check_side(instrument_id, name, side):
    """Sector positions, summed through their groups, equal the side's total in every quarter."""
    n_positions = sum(len(group["sectors"]) for group in side["groups"])
    tolerance = max(2, n_positions)
    for i, total in enumerate(side["level"]):
        if total is None:
            continue
        positions = [sector["level"][i] for group in side["groups"] for sector in group["sectors"]]
        if any(value is None for value in positions):
            continue  # a breakdown that starts later than its total cannot be checked before then
        summed = sum(group["level"][i] or 0 for group in side["groups"])
        assert abs(total - summed) <= tolerance, (instrument_id, name, i, total, summed)
    for group in side["groups"]:
        assert group["id"] in GROUP_IDS
        for i in range(len(side["level"])):
            members = sum(sector["level"][i] or 0 for sector in group["sectors"])
            assert abs((group["level"][i] or 0) - members) < 1e-6


def test_all_listed_instruments_reconcile(con):
    listed = instruments.list_instruments(con)
    assert len(listed) >= 30
    for instrument in listed:
        view = instruments.view(con, instrument["id"])
        check_side(instrument["id"], "holders", view["holders"])
        if view["issuers"]:
            check_side(instrument["id"], "issuers", view["issuers"])
            # Neither side may be a partial subtotal of the other.
            holders, issuers = abs(view["holders"]["level"][-1]), abs(view["issuers"]["level"][-1])
            assert min(holders, issuers) * 2 >= max(holders, issuers), instrument["id"]


@pytest.mark.parametrize("instrument_id, min_holder_sectors, min_issuer_sectors", [
    ("F3_2", 20, 1),   # Treasury securities: one issuer
    ("F3_3", 15, 2),   # agency- and GSE-backed securities
    ("F3_5", 20, 5),   # corporate and foreign bonds
    ("F4_1", 15, 10),  # federal funds and repo
    ("F4_5", 12, 3),   # mortgages
    ("F2_2", 15, 5),   # checkable deposits and currency
    ("F51_1", 15, 8),  # corporate equities
    ("F521", 10, 1),   # money market fund shares
])
def test_key_instruments_are_resolved(con, instrument_id, min_holder_sectors, min_issuer_sectors):
    view = instruments.view(con, instrument_id)
    assert sum(len(g["sectors"]) for g in view["holders"]["groups"]) >= min_holder_sectors
    assert sum(len(g["sectors"]) for g in view["issuers"]["groups"]) >= min_issuer_sectors


def test_treasury_holders_plus_valuation_gap_equal_amount_outstanding(con):
    """Holders are at market value, the federal liability at face value; Z.1 publishes the gap."""
    view = instruments.view(con, "F3_2")
    assert view["issuers"]["series"] == "FL313161105.Q"
    for i, face in enumerate(view["issuers"]["level"]):
        market, gap = view["holders"]["level"][i], view["discrepancy"]["level"][i]
        assert abs(market + gap - face) <= 2, (view["periods"][i], market, gap, face)


def test_level_change_decomposes(con):
    view = instruments.view(con, "F3_2")
    for group in view["holders"]["groups"]:
        for i in range(1, len(view["periods"])):
            other = group["other_change"][i]
            if other is not None:
                assert abs(group["level"][i] - group["level"][i - 1] - group["transactions"][i] - other) < 1e-6


def test_positions_link_to_sector_pages(con):
    listed = {sector["id"] for sector in sectors.list_sectors(con)}
    view = instruments.view(con, "F3_2")
    linked = [s for g in view["holders"]["groups"] for s in g["sectors"] if s["sector_id"]]
    assert len(linked) >= 20
    assert all(s["sector_id"] in listed for s in linked)


def test_sector_lines_link_only_to_resolved_instruments(con):
    listed = {instrument["id"] for instrument in instruments.list_instruments(con)}
    view = sectors.balance_sheet(con, "S123")

    def walk(node):
        yield node
        for child in node["children"] + node["memos"]:
            yield from walk(child)

    links = {node["instrument"] for node in walk(view["assets"]) if node["instrument"]}
    assert "F3_2" in links and "F4_1" in links
    assert links <= listed
