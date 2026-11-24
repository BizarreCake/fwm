"""Sector balance sheets from the Z.1 sector tables (S121 central bank, S123 money market funds, ...).

Each sector's assets and liabilities are returned as a tree whose parent/child
sums were verified against the full history by ``fwm.structure``. Lines the
inference could not place are not shown, so every number displayed rolls up
exactly to the published total above it.
"""

from __future__ import annotations

import duckdb

from fwm.structure import START

ASSET_TOTAL = "4090"
LIABILITY_TOTALS = ("4194", "4190")  # with equity preferred, else liabilities only


def _other_change(level: list, tx: list) -> list:
    """Change in level not explained by transactions (valuation + other volume changes)."""
    out: list = [None]
    for i in range(1, len(level)):
        if level[i] is None or level[i - 1] is None or tx[i] is None:
            out.append(None)
        else:
            out.append(level[i] - level[i - 1] - tx[i])
    return out


def _table(sector_id: str) -> str:
    return f"{sector_id}_s"


def _roots(con: duckdb.DuckDBPyConnection, table_id: str) -> tuple[str | None, str | None]:
    """Series ids of the assets root and the liabilities(+equity) root of a sector table."""
    rows = con.execute(
        """
        SELECT s.series_id, s.role,
               (SELECT count(*) FROM z1_structure c
                WHERE c.table_id = s.table_id AND c.parent_series_id = s.series_id AND c.role = 'component')
        FROM z1_structure s WHERE s.table_id = ? AND s.role <> 'memo' ORDER BY s.position
        """,
        [table_id],
    ).fetchall()
    assets = next((sid for sid, role, kids in rows if sid[4:8] == ASSET_TOTAL and role == "root" and kids), None)
    liabilities = None
    for code in LIABILITY_TOTALS:
        liabilities = next((sid for sid, role, _ in rows if sid[4:8] == code and role == "root"), None)
        if liabilities:
            break
    return assets, liabilities


def list_sectors(con: duckdb.DuckDBPyConnection) -> list[dict]:
    tables = con.execute(
        "SELECT table_id, any_value(table_name) FROM z1_series "
        "WHERE table_id LIKE 'S%\\_s' ESCAPE '\\' GROUP BY 1 ORDER BY 1"
    ).fetchall()
    latest = con.execute("SELECT latest_period FROM source_release WHERE source_id = 'fed_z1'").fetchone()[0]
    out = []
    for table_id, table_name in tables:
        assets, liabilities = _roots(con, table_id)
        if not assets:
            continue

        def value(series_id: str | None):
            if not series_id:
                return None
            row = con.execute(
                "SELECT value FROM z1_observations WHERE series_id = ? AND period = ?", [series_id, latest]
            ).fetchone()
            return row[0] if row else None

        out.append({
            "id": table_id.removesuffix("_s"),
            "name": table_name.split(" ", 1)[1],
            "sector_code": assets[2:4],
            "total_assets": value(assets),
            "total_liabilities": value(liabilities),
        })
    return out


def sector_tables_by_code(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Two-digit Z.1 sector code -> id of the sector page that best represents it (the largest, where sub-sector tables share a code)."""
    best: dict[str, dict] = {}
    for sector in list_sectors(con):
        current = best.get(sector["sector_code"])
        if current is None or (sector["total_assets"] or 0) > (current["total_assets"] or 0):
            best[sector["sector_code"]] = sector
    return {code: sector["id"] for code, sector in best.items()}


def _label(description: str, owner: str) -> str:
    parts = [p.strip() for p in description.split(";")]
    if len(parts) == 1:
        return parts[0]
    item = parts[1]
    for suffix in (" (market value)", " (IMA)", " (SBS)"):
        item = item.removesuffix(suffix)
    item = item[:1].upper() + item[1:]
    return item if parts[0] == owner else f"{item} ({parts[0]})"


def balance_sheet(con: duckdb.DuckDBPyConnection, sector_id: str) -> dict | None:
    table_id = _table(sector_id)
    meta = con.execute("SELECT any_value(table_name) FROM z1_series WHERE table_id = ?", [table_id]).fetchone()
    if not meta or not meta[0]:
        return None
    assets_root, liabilities_root = _roots(con, table_id)
    if not assets_root:
        return None

    periods = con.execute(
        "SELECT DISTINCT period, period_end FROM z1_observations "
        "WHERE period LIKE '%:Q%' AND period_end >= CAST(? AS DATE) ORDER BY period_end", [START]
    ).fetchall()
    index = {label: i for i, (label, _) in enumerate(periods)}
    n = len(periods)

    lines = con.execute(
        """
        SELECT st.series_id, st.parent_series_id, st.role, se.description
        FROM z1_structure st JOIN z1_series se USING (table_id, series_id)
        WHERE st.table_id = ? ORDER BY st.position
        """,
        [table_id],
    ).fetchall()
    ids = [line[0] for line in lines]
    owner = next(line[3] for line in lines if line[0] == assets_root).split(";")[0].strip()

    wanted = ids + [f"FU{sid[2:]}" for sid in ids]
    series: dict[str, list] = {}
    for series_id, period, value in con.execute(
        "SELECT series_id, period, value FROM z1_observations "
        "WHERE series_id IN (SELECT unnest(?)) AND period LIKE '%:Q%' AND period_end >= CAST(? AS DATE)",
        [wanted, START],
    ).fetchall():
        series.setdefault(series_id, [None] * n)[index[period]] = value

    from fwm.instruments import list_instruments

    resolved = {f"{instrument['id']}_s" for instrument in list_instruments(con)}
    instrument_tables = dict(con.execute(
        """
        SELECT series_id, arg_max(table_id, length(table_id)) FROM z1_series
        WHERE series_id IN (SELECT unnest(?)) AND table_id IN (SELECT unnest(?)) GROUP BY 1
        """,
        [ids, sorted(resolved)],
    ).fetchall())

    children: dict[str, list] = {}
    for series_id, parent, role, description in lines:
        if parent:
            children.setdefault(parent, []).append((series_id, role, description))
    described = {line[0]: line[3] for line in lines}

    def node(series_id: str) -> dict:
        level = series.get(series_id, [None] * n)
        tx = series.get(f"FU{series_id[2:]}", [None] * n)
        kids = children.get(series_id, [])
        instrument = instrument_tables.get(series_id)
        return {
            "series": series_id,
            "name": _label(described[series_id], owner),
            "basis": "market" if series_id.startswith("LM") else "book",
            "instrument": instrument.removesuffix("_s") if instrument else None,
            "level": level,
            "transactions": tx,
            "other_change": _other_change(level, tx),
            "children": [node(sid) for sid, role, _ in kids if role == "component"],
            "memos": [node(sid) for sid, role, _ in kids if role == "memo"],
        }

    release = con.execute(
        "SELECT name, url, published_at, latest_period FROM source_release WHERE source_id = 'fed_z1'"
    ).fetchone()
    return {
        "id": sector_id,
        "name": meta[0].split(" ", 1)[1],
        "unit": "USD millions",
        "periods": [label for label, _ in periods],
        "assets": node(assets_root),
        "liabilities": node(liabilities_root) if liabilities_root else None,
        "source": {
            "name": release[0],
            "url": release[1],
            "table": meta[0].replace(".s ", " ", 1),
            "published_at": release[2].isoformat() if release[2] else None,
            "latest_period": release[3],
        },
        "notes": {
            "structure": "Z.1 does not publish which lines add up to which totals. The hierarchy shown is inferred: "
                         "a line is treated as a total only if it equals the sum of its components in every quarter.",
            "liabilities": None if liabilities_root else
                           "This Z.1 table publishes the sector's assets only.",
            "other_change": "Valuation & other is the change in level minus transactions: mostly price changes, "
                            "plus any reclassifications.",
        },
    }
