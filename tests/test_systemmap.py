"""Accounting checks on the system map."""

from pathlib import Path

import duckdb
import pytest

from fwm.economies.us import instruments
from fwm.views import systemmap

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "fwm.duckdb"


@pytest.fixture(scope="module")
def loaded():
    if not DB_PATH.exists():
        pytest.skip("no ingested data; run `uv run fwm ingest`")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        yield systemmap.compute(con), con
    finally:
        con.close()


def test_each_family_sums_to_its_published_totals(loaded):
    """Per family and side, the group amounts add up to the signed sum of the tables' published totals."""
    view, con = loaded
    signs = {family_id: dict(tables) for family_id, _, _, tables, _ in systemmap.FAMILIES}
    pages = {}
    for family in view["families"]:
        for table in family["tables"]:
            pages.setdefault(table, instruments.view(con, table))
        for side in ("holders", "issuers"):
            for i in range(len(view["periods"])):
                totals = [pages[t][side]["level"][i] for t in family["tables"]]
                if any(total is None for total in totals):
                    continue
                published = sum(signs[family["id"]][t] * total for t, total in zip(family["tables"], totals))
                summed = sum(values[i] for values in family[side].values())
                assert abs(published - summed) <= 60, (family["id"], side, view["periods"][i], published, summed)


def test_no_table_is_counted_in_two_families(loaded):
    view, _ = loaded
    positive = [t for _, _, _, tables, _ in systemmap.FAMILIES for t, sign in tables if sign > 0]
    assert len(positive) == len(set(positive))
    # "Other loans" is all loans less repo and mortgages, which have families of their own.
    loans = dict(next(tables for family_id, _, _, tables, _ in systemmap.FAMILIES if family_id == "loans"))
    assert loans == {"F4": 1, "F4_1": -1, "F4_5": -1}


def test_subtracted_family_is_never_materially_negative(loaded):
    view, _ = loaded
    loans = next(f for f in view["families"] if f["id"] == "loans")
    for side in ("holders", "issuers"):
        for group, values in loans[side].items():
            assert min(values) > -1_000, (side, group, min(values))


def test_sides_are_comparable(loaded):
    view, _ = loaded
    for family in view["families"]:
        held = sum(values[-1] for values in family["holders"].values())
        owed = sum(values[-1] for values in family["issuers"].values())
        assert min(held, owed) * 2 >= max(held, owed), family["id"]
