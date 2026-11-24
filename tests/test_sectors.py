"""Accounting checks on sector balance sheets."""

from pathlib import Path

import duckdb
import pytest

from fwm.economies.us import sectors

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "fwm.duckdb"


@pytest.fixture(scope="module")
def con():
    if not DB_PATH.exists():
        pytest.skip("no ingested data; run `uv run fwm ingest`")
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    yield connection
    connection.close()


def check_rollup(node, path=""):
    """Every parent equals the sum of its components in every quarter (memos excluded)."""
    if node["children"]:
        tolerance = max(2, len(node["children"]))
        for i, parent in enumerate(node["level"]):
            if parent is None:
                continue
            if any(child["level"][i] is None for child in node["children"]):
                continue  # a breakdown that starts later than its total cannot be checked before then
            total = sum(child["level"][i] or 0 for child in node["children"])
            assert abs(parent - total) <= tolerance, (path + node["name"], i, parent, total)
        for child in node["children"]:
            check_rollup(child, path + node["name"] + " > ")


def test_all_listed_sectors_roll_up(con):
    listed = sectors.list_sectors(con)
    assert len(listed) >= 40
    for sector in listed:
        view = sectors.balance_sheet(con, sector["id"])
        assert len(view["assets"]["children"]) >= 2, sector["id"]
        check_rollup(view["assets"])
        if view["liabilities"]:
            check_rollup(view["liabilities"])


@pytest.mark.parametrize("sector_id, min_assets, min_liabilities", [
    ("S121", 6, 2),    # central bank
    ("S122", 10, 2),   # private depository institutions
    ("S123", 5, 0),    # money market funds (assets only in Z.1)
    ("S1M", 12, 3),    # households and nonprofits
    ("S2", 12, 2),     # rest of the world
    ("S125s3", 6, 2),  # brokers and dealers
])
def test_key_sectors_are_resolved(con, sector_id, min_assets, min_liabilities):
    view = sectors.balance_sheet(con, sector_id)
    assert len(view["assets"]["children"]) >= min_assets
    if min_liabilities:
        assert len(view["liabilities"]["children"]) >= min_liabilities
