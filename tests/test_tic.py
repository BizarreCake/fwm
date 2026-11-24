"""Accounting checks on foreign Treasury holdings by country (Treasury TIC, SLT Table 3)."""

from pathlib import Path

import duckdb
import pytest

from fwm.views import foreign as tic

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "fwm.duckdb"


@pytest.fixture(scope="module", params=tic.INWARD)
def view(request):
    if not DB_PATH.exists():
        pytest.skip("no ingested data; run `uv run fwm ingest`")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        loaded = tic.view(con, request.param)
    finally:
        con.close()
    if loaded is None:
        pytest.skip("no TIC data; run `uv run fwm ingest --only tic`")
    return loaded


def months(view):
    return range(len(view["periods"]))


def test_months_are_consecutive(view):
    periods = view["periods"]
    assert periods[0] == "2020-01" and len(periods) >= 81
    for earlier, later in zip(periods, periods[1:]):
        year, month = int(earlier[:4]), int(earlier[5:])
        assert later == (f"{year + 1}-01" if month == 12 else f"{year}-{month + 1:02d}")


def test_regions_and_organizations_add_up_to_the_grand_total_every_month(view):
    for i in months(view):
        assert sum(region["total"][i] for region in view["regions"]) == pytest.approx(view["total"]["total"][i], abs=1)


def test_amount_not_allocated_to_a_region_is_tiny(view):
    extra = [region for region in view["regions"] if region["id"] == "unallocated"]
    assert (view["id"] == "treasuries") == (not extra)
    for region in extra:
        for i in months(view):
            assert abs(region["total"][i]) <= 0.005 * view["total"]["total"][i], view["periods"][i]


def test_official_and_private_add_up_to_the_grand_total_every_month(view):
    for i in months(view):
        assert view["official"]["total"][i] + view["private"]["total"][i] == pytest.approx(view["total"]["total"][i], abs=1)


def test_bills_plus_bonds_equal_total_for_every_holder_every_month(view):
    for holder in [view["total"], view["official"], view["private"], *view["regions"], *view["countries"]]:
        for i in months(view):
            parts = (holder["total"][i], holder["long_term"][i], holder["short_term"][i])
            if None not in parts:
                assert parts[1] + parts[2] == pytest.approx(parts[0], abs=2), (holder["name"], view["periods"][i])


def test_listed_countries_never_exceed_their_region(view):
    """The remainder of each region (countries not published separately) is never negative."""
    by_id = {country["id"]: country for country in view["countries"]}
    listed = set()
    for region in view["regions"]:
        listed |= set(region["countries"])
        for i in months(view):
            if region["id"] != "unallocated":
                assert region["unlisted"][i] >= -1, (region["name"], view["periods"][i])
            members = sum(by_id[c]["total"][i] or 0 for c in region["countries"])
            assert members + region["unlisted"][i] == pytest.approx(region["total"][i], abs=1)
    assert listed == set(by_id)


def test_every_listed_country_has_figures(view):
    assert len(view["countries"]) >= 50
    for country in view["countries"]:
        assert any(value is not None for value in country["total"]), country["name"]
    assert {"Japan", "United Kingdom", "China, Mainland", "Canada"} <= {c["name"] for c in view["countries"]}


def test_changes_split_into_purchases_valuation_and_a_derived_remainder(view):
    for holder in [view["total"], *view["countries"]]:
        for i in months(view):
            parts = [holder[key][i] for key in ("long_term_net", "long_term_valuation", "long_term_other")]
            if i and None not in parts and None not in (holder["long_term"][i], holder["long_term"][i - 1]):
                assert sum(parts) == pytest.approx(holder["long_term"][i] - holder["long_term"][i - 1], abs=1)
            if i and None not in (holder["short_term_net"][i], holder["short_term"][i], holder["short_term"][i - 1]):
                # Bill purchases are estimated by the Treasury as the change in holdings.
                assert holder["short_term_net"][i] == pytest.approx(holder["short_term"][i] - holder["short_term"][i - 1], abs=2)


def test_only_treasuries_have_bills(view):
    has_any = any(value is not None for value in view["total"]["short_term"])
    assert has_any == view["has_bills"] == (view["id"] == "treasuries")


def test_agrees_with_the_quarterly_accounts(view):
    """Treasuries match Z.1's rest of the world (Z.1 takes them from these reports); the others are close, for stated reasons."""
    quarterly = view["quarterly"]["level"]
    pairs = [(view["periods"][i], quarterly[i], view["total"]["total"][i]) for i in months(view) if quarterly[i] is not None]
    assert len(pairs) >= 24 and all(period[5:] in ("03", "06", "09", "12") for period, _, _ in pairs)
    recent = [(period, z1 / reported) for period, z1, reported in pairs if period >= "2022"]
    low, high = {"treasuries": (0.995, 1.005), "agency": (1.0, 1.06), "corporate": (0.9, 1.05), "equities": (0.85, 1.0)}[view["id"]]
    assert all(low <= ratio <= high for _, ratio in recent), recent
