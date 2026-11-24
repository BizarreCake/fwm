"""Who holds an instrument and who owes it, from the Z.1 instrument tables (F3.2 Treasuries, F4.1 repo, ...).

Each instrument table lists sector positions on one or both sides. Using the
hierarchy inferred by ``fwm.structure`` we find, per side, the published total
whose components are positions of several different sectors, and report those
positions grouped into the shared sector groups defined here. A side that has
no such total is reported as missing rather than guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from fwm.economies.us.structure import START

# Shared sector groups, used with the same identity (and colour) on every page.
GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("fed", "Federal Reserve", ("71",)),
    ("row", "Rest of the world", ("26",)),
    ("banks", "Banks & credit unions", ("70", "72", "74", "75", "76", "47", "27", "28")),
    ("mmf", "Money market funds", ("63",)),
    ("funds", "Investment funds", ("65", "56", "55", "62", "46", "44", "45")),
    ("pensions_insurers", "Pensions & insurers", ("57", "59", "22", "34", "54", "51")),
    ("households", "Households & nonprofits", ("15", "16")),
    ("other_financial", "Dealers & other financial", ("66", "40", "41", "42", "61", "67", "73", "64", "50", "79")),
    ("gov_business", "Government & business", ("31", "21", "10", "11", "12", "14", "18", "23", "38")),
)
MIXED_GROUPS = {"other_financial", "gov_business", "funds", "pensions_insurers"}
GROUP_OF = {code: group_id for group_id, _, codes in GROUPS for code in codes}
FALLBACK_GROUP = "gov_business"

AGGREGATE_SECTORS = {"89", "88", "79", "38", "14", "70", "59"}  # totals over other sectors
WHOLE_MARKET = {"89", "88"}  # all sectors / all domestic sectors
DISCREPANCY = "90"
ASSET, LIABILITY = "0", "1"


def sector_code(series_id: str) -> str:
    return series_id[2:4]


def side_of(series_id: str) -> str:
    """Z.1 mnemonics carry the side in the fourth digit: 0 = asset, 1 = liability."""
    return series_id[5]


@dataclass
class Line:
    series: str
    description: str
    children: list["Line"] = field(default_factory=list)
    memos: list["Line"] = field(default_factory=list)
    alt: list["Line"] = field(default_factory=list)


def _tree(con: duckdb.DuckDBPyConnection, table_id: str) -> list[Line]:
    rows = con.execute(
        """
        SELECT st.series_id, st.parent_series_id, st.role, se.description
        FROM z1_structure st JOIN z1_series se USING (table_id, series_id)
        WHERE st.table_id = ? ORDER BY st.position
        """,
        [table_id],
    ).fetchall()
    lines = {series: Line(series, description) for series, _, _, description in rows}
    roots = []
    for series, parent, role, _ in rows:
        if role == "root":
            roots.append(lines[series])
        elif role == "component":
            lines[parent].children.append(lines[series])
        elif role == "alt":
            lines[parent].alt.append(lines[series])
        else:
            lines[parent].memos.append(lines[series])
    return roots


def _positions(members: list[Line]) -> list[Line]:
    """Sector positions among a total's components: aggregates over several sectors are replaced by their members."""
    out: list[Line] = []
    for child in members:
        member_sectors = {sector_code(c.series) for c in child.children}
        if child.children and member_sectors != {sector_code(child.series)}:
            out.extend(_positions(child.children))
        else:
            out.append(child)
    return out


@dataclass
class Side:
    total: Line
    positions: list[Line]
    # Set when the published total also contains the instrument discrepancy, which is
    # then subtracted so that the side's total is the sum of its sector positions.
    less: Line | None = None


def _resolve(roots: list[Line], latest: dict[str, float]) -> dict:
    """Pick the holders side, the issuers side and the discrepancy line of an instrument table.

    A side is a published total together with the sector positions that sum to it. Where
    several totals qualify (a table covering sub-instruments), the largest wins; and if the
    two sides then differ by more than a factor of two, the smaller is a partial subtotal
    and is dropped rather than presented as the whole market.
    """
    best: dict[str, Side | None] = {ASSET: None, LIABILITY: None}

    def value(line: Line) -> float:
        return abs(latest.get(line.series, 0))

    discrepancy = next((r for r in roots if sector_code(r.series) == DISCREPANCY), None)

    def consider(total: Line, members: list[Line]) -> None:
        nonlocal discrepancy
        positions = _positions(members)
        inside = next((p for p in positions if sector_code(p.series) == DISCREPANCY), None)
        discrepancy = discrepancy or inside
        positions = [p for p in positions if sector_code(p.series) != DISCREPANCY]
        if not positions or sector_code(total.series) not in AGGREGATE_SECTORS:
            return
        for side in (ASSET, LIABILITY):
            on_side = [p for p in positions if side_of(p.series) == side]
            sectors = {sector_code(p.series) for p in on_side} - WHOLE_MARKET
            if len(sectors) < 2 or len(on_side) * 2 <= len(positions):
                continue
            current = best[side]
            if current is None or value(total) > value(current.total):
                best[side] = Side(total, positions, inside)

    def walk(line: Line) -> None:
        if line.children:
            consider(line, line.children)
        if line.alt:
            consider(line, line.alt)
        for child in line.children + line.alt:
            walk(child)

    for root in roots:
        walk(root)

    holders, issuers = best[ASSET], best[LIABILITY]
    if holders and issuers:
        big, small = sorted((value(holders.total), value(issuers.total)), reverse=True)
        if small * 2 < big:
            if value(holders.total) < value(issuers.total):
                holders = issuers = None
            else:
                issuers = None
    largest = max(latest.values(), key=abs, default=0)
    if not holders:
        # Shares of one kind of fund: the holders sum to the fund sector's own total,
        # which is the largest line in the table.
        for root in roots:
            if value(root) < abs(largest):
                continue
            positions = _positions(root.children)
            assets = [p for p in positions if side_of(p.series) == ASSET]
            if (sector_code(root.series) not in AGGREGATE_SECTORS and len(assets) == len(positions)
                    and len({sector_code(p.series) for p in positions}) >= 2):
                holders = Side(root, positions)
                issuers = Side(root, [root])
                break
    elif not issuers:
        # One sector owes the whole instrument and has its own liability line (Treasury securities).
        single = next(
            (r for r in roots if side_of(r.series) == LIABILITY
             and sector_code(r.series) not in AGGREGATE_SECTORS | {DISCREPANCY}), None)
        if single:
            issuers = Side(single, [single])
    return {"holders": holders, "issuers": issuers, "discrepancy": discrepancy}


def _latest_values(con: duckdb.DuckDBPyConnection, table_id: str) -> dict[str, float]:
    return dict(con.execute(
        """
        SELECT series_id, value FROM z1_observations
        WHERE series_id IN (SELECT series_id FROM z1_series WHERE table_id = ?)
          AND period = (SELECT latest_period FROM source_release WHERE source_id = 'fed_z1')
        """,
        [table_id],
    ).fetchall())


def _table_name(con: duckdb.DuckDBPyConnection, table_id: str) -> str | None:
    row = con.execute("SELECT any_value(table_name) FROM z1_series WHERE table_id = ?", [table_id]).fetchone()
    return row[0].split(" ", 1)[1] if row and row[0] else None


def list_instruments(con: duckdb.DuckDBPyConnection) -> list[dict]:
    tables = [r[0] for r in con.execute(
        "SELECT DISTINCT table_id FROM z1_series WHERE table_id LIKE 'F%\\_s' ESCAPE '\\' ORDER BY 1").fetchall()]
    out = []
    for table_id in tables:
        latest = _latest_values(con, table_id)
        resolved = _resolve(_tree(con, table_id), latest)
        if not resolved["holders"]:
            continue
        out.append({
            "id": table_id.removesuffix("_s"),
            "name": _table_name(con, table_id),
            "holders_total": latest.get(resolved["holders"].total.series),
            "has_issuers": bool(resolved["issuers"]),
        })
    return out


def view(con: duckdb.DuckDBPyConnection, instrument_id: str) -> dict | None:
    from fwm.economies.us.sectors import _other_change, sector_tables_by_code

    table_id = f"{instrument_id}_s"
    name = _table_name(con, table_id)
    if not name:
        return None
    resolved = _resolve(_tree(con, table_id), _latest_values(con, table_id))
    if not resolved["holders"]:
        return None

    periods = con.execute(
        "SELECT DISTINCT period, period_end FROM z1_observations "
        "WHERE period LIKE '%:Q%' AND period_end >= CAST(? AS DATE) ORDER BY period_end", [START]
    ).fetchall()
    index = {label: i for i, (label, _) in enumerate(periods)}
    n = len(periods)

    ids = [r[0] for r in con.execute("SELECT series_id FROM z1_series WHERE table_id = ?", [table_id]).fetchall()]
    wanted = ids + [f"FU{series[2:]}" for series in ids]
    data: dict[str, list] = {}
    for series, period, value in con.execute(
        "SELECT series_id, period, value FROM z1_observations "
        "WHERE series_id IN (SELECT unnest(?)) AND period LIKE '%:Q%' AND period_end >= CAST(? AS DATE)",
        [wanted, START],
    ).fetchall():
        data.setdefault(series, [None] * n)[index[period]] = value

    def measures(series: str) -> dict:
        level = data.get(series, [None] * n)
        tx = data.get(f"FU{series[2:]}", [None] * n)
        return {"level": level, "transactions": tx, "other_change": _other_change(level, tx)}

    sector_pages = sector_tables_by_code(con)

    def position(line: Line) -> dict:
        code = sector_code(line.series)
        parts = [p.strip() for p in line.description.split(";")]
        return {
            "code": code,
            "name": parts[0],
            "detail": parts[1] if len(parts) > 1 else "",
            "group": GROUP_OF.get(code, FALLBACK_GROUP),
            "sector_id": sector_pages.get(code),
            "series": line.series,
            "basis": "market" if line.series.startswith("LM") else "book",
            **measures(line.series),
        }

    def total_of(columns: list[list]) -> list:
        return [None if all(v is None for v in column) else sum(v or 0 for v in column) for column in zip(*columns)]

    def side(chosen: Side | None) -> dict | None:
        if chosen is None:
            return None
        total = chosen.total
        rows = [position(line) for line in chosen.positions]
        published = measures(total.series)
        if chosen.less:
            removed = measures(chosen.less.series)
            for key in ("level", "transactions"):
                published[key] = [None if t is None else t - (d or 0) for t, d in zip(published[key], removed[key])]
            published["other_change"] = _other_change(published["level"], published["transactions"])
        groups = []
        for group_id, group_name, _ in GROUPS:
            members = [row for row in rows if row["group"] == group_id]
            if not members:
                continue
            level = total_of([m["level"] for m in members])
            tx = total_of([m["transactions"] for m in members])
            groups.append({
                "id": group_id,
                # A catch-all group with a single member is clearer under that member's own name.
                "name": members[0]["name"] if len(members) == 1 and group_id in MIXED_GROUPS else group_name,
                "level": level,
                "transactions": tx,
                "other_change": _other_change(level, tx),
                "sectors": members,
            })
        return {
            "series": total.series,
            "excludes_discrepancy": bool(chosen.less),
            **published,
            "groups": groups,
        }

    holders = side(resolved["holders"])
    issuers = side(resolved["issuers"])

    release = con.execute(
        "SELECT name, url, published_at, latest_period FROM source_release WHERE source_id = 'fed_z1'"
    ).fetchone()
    discrepancy = resolved["discrepancy"]
    return {
        "id": instrument_id,
        "name": name,
        "unit": "USD millions",
        "periods": [label for label, _ in periods],
        "group_order": [group_id for group_id, _, _ in GROUPS],
        "holders": holders,
        "issuers": issuers,
        "discrepancy": {"series": discrepancy.series, "level": data.get(discrepancy.series, [None] * n)}
        if discrepancy else None,
        "source": {
            "name": release[0],
            "url": release[1],
            "table": f"{instrument_id.replace('_', '.')} {name}",
            "published_at": release[2].isoformat() if release[2] else None,
            "latest_period": release[3],
        },
        "notes": {
            "sides": "Holders report this instrument as an asset; issuers owe it as a liability. The two sides are "
                     "measured from different sources and often on different bases (market vs. book value), so "
                     "their totals need not match. Z.1 publishes the difference as an instrument discrepancy.",
            "other_change": "Valuation & other is the change in level minus transactions: mostly price changes, "
                            "plus any reclassifications.",
            "coverage": "Sector-level aggregates; no individual institutions. Z.1 does not say which holder "
                        "holds which issuer's paper, only each side's totals.",
            "issuers": None if issuers else "This Z.1 table does not break the instrument down by issuing sector.",
        },
    }
