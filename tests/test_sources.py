"""The registry of sources agrees with the database, the loaders and the written description."""

import datetime as dt
from pathlib import Path

import duckdb
import pytest

from fwm import sources

DB = Path(__file__).resolve().parents[1] / "data" / "fwm.duckdb"


@pytest.fixture(scope="module")
def con():
    if not DB.exists():
        pytest.skip("no database; run `uv run fwm ingest`")
    con = duckdb.connect(str(DB), read_only=True)
    yield con
    con.close()


def test_every_table_belongs_to_one_source_with_the_columns_it_says(con):
    described = {**sources.SHARED_TABLES}
    for source in sources.SOURCES:
        assert not set(source.tables) & set(described), f"{source.id} repeats a table"
        assert set(source.shares) <= set(sources.SHARED_TABLES)
        described.update(source.tables)
    actual = {row[0] for row in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
    assert actual == set(described)
    for table, text in described.items():
        columns = [row[0] for row in con.execute(f"DESCRIBE {table}").fetchall()]
        assert [c.strip() for c in text.split(":")[0].split(",")] == columns, table


def test_every_release_is_recorded_and_nothing_else_is(con):
    recorded = {row[0] for row in con.execute("SELECT source_id FROM source_release").fetchall()}
    assert recorded == {release.id for source in sources.SOURCES for release in source.releases}
    assert sources.unregistered(con) == []
    computed = {row[0] for row in con.execute("SELECT key FROM computed").fetchall()}
    assert computed == set(sources.COMPUTED) == {key for source in sources.SOURCES for key in source.rebuilds}


def test_every_source_has_a_loader_module_and_known_neighbours():
    import importlib

    ids = [source.id for source in sources.SOURCES]
    assert len(set(ids)) == len(ids) and set(sources.DESCRIBE) == set(ids)
    for source in sources.SOURCES:
        module = importlib.import_module(source.module)
        assert module.__name__.startswith("fwm.loaders.")
        assert callable(module.download) and callable(module.ingest)
        assert set(source.needs) <= set(ids)
    assert [s.id for s in sources.selected("ecb")] == ["ecb-weekly", "ecb-context", "ecb-accounts"]
    assert [s.id for s in sources.selected("jp-context")] == ["jp-context"] and len(sources.selected(None)) == len(ids)
    with pytest.raises(ValueError):
        sources.selected("nothing")
    for path in sources.CURATED:
        assert (sources.ROOT / path).exists(), path


def test_periods_and_due_dates():
    assert sources.period_end("2026:Q2") == dt.date(2026, 6, 30) and sources.period_end("2025:Q4") == dt.date(2025, 12, 31)
    assert sources.period_end("2026-09") == dt.date(2026, 9, 30) and sources.period_end("2026-12") == dt.date(2026, 12, 31)
    assert sources.next_period_end("2026:Q2", "quarter") == dt.date(2026, 9, 30)
    assert sources.next_period_end("2025:Q4", "half-year") == dt.date(2026, 6, 30)
    assert sources.next_period_end("2026-12", "month") == dt.date(2027, 1, 31)
    assert sources.next_period_end("2026-11-18", "week") == dt.date(2026, 11, 25)


def test_status_says_when_newer_data_is_probably_out(con):
    loaded = dict(con.execute("SELECT source_id, ingested_at FROM source_release").fetchall())
    day = loaded["fed_z1"].date()
    now = {row["release"]: row for row in sources.status(con, day)}
    assert now["fed_z1"]["state"] == "current" and now["fed_z1"]["latest"] and now["fed_z1"]["refresh"] == "uv run fwm ingest --only z1"
    later = {row["release"]: row for row in sources.status(con, day + dt.timedelta(days=200))}
    assert all(row["state"] == "newer data probably published" for row in later.values())
    due = dt.date.fromisoformat(now["fed_z1"]["next_due"])
    assert {r["release"]: r for r in sources.status(con, due - dt.timedelta(days=1))}["fed_z1"]["state"] == "current"
    assert {r["release"]: r for r in sources.status(con, due)}["fed_z1"]["state"] == "newer data probably published"


def test_written_description_is_up_to_date():
    assert sources.DOC_PATH.read_text(encoding="utf-8") == sources.render(), "run `uv run fwm sources --write`"


def test_every_economy_gives_its_context_through_one_interface(con):
    from fwm import economies

    for economy, info in economies.ECONOMIES.items():
        assert economies.available(con, economy) and info["refresh"] in sources.GROUPS
        periods = economies.periods(con, economy)
        source = economies.context(economy)
        assert source.available(con) and source.ECONOMY == economy
        view = source.view(con)
        assert view["periods"] == periods and view["economy"] == economy and view["notes"]["source"]
        assert all(len(rate["values"]) == len(periods) for rate in view["rates"]) and len(view["rates"]) >= 3
        assert source.gdp(con, periods)[-1] > 0 and source.usd_per_unit(con, periods)[-1] > 0
        assert isinstance(source.policy_changes(con), list) and source.load_events()
    assert economies.weekly("jp") is None and economies.weekly("us").CITE["currency"] == "USD"
