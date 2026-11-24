"""Infer the line hierarchy of Z.1 tables from the data itself.

The bulk release lists each table's lines in order but does not say which lines
are totals of which. We recover that by testing accounting identities against
the full quarterly history: line P is the parent of lines C1..Cn if
P == C1 + ... + Cn in every quarter (within rounding). Because the identity must
hold in ~300 quarters, accidental matches are not a practical concern; lines we
cannot place are left unplaced rather than guessed.

Three patterns occur in the tables:

* a total followed by its components (most tables);
* components followed by their total (fund tables);
* "of which" memo lines sitting among the components, which must be skipped.
  A skipped line is attached to the preceding component as a memo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

START = "1952-03-31"
WINDOW = 40      # how many following items a parent may span
MAX_MEMOS = 2    # how many memo lines may be skipped inside one parent


@dataclass
class Node:
    index: int
    children: list["Node"] = field(default_factory=list)
    memos: list["Node"] = field(default_factory=list)


def _matches(target: list, total: list, n_terms: int) -> bool:
    tolerance = max(2, n_terms)  # values are rounded to whole millions
    seen = False
    for t, s in zip(target, total):
        if t is None:
            continue
        if abs(t - s) > tolerance:
            return False
        seen = seen or t != 0
    return seen


def _add(a: list, b: list, sign: int = 1) -> list:
    return [x + sign * (y or 0) for x, y in zip(a, b)]


def infer(values: list[list]) -> list[Node]:
    """Build the forest for one table. values[i] is line i's series over time (None = missing)."""
    n = len(values)
    n_periods = len(values[0]) if values else 0
    # Probe periods for cheap rejection before the full check: latest first.
    probes = [p for p in (n_periods - 1, n_periods // 2, n_periods // 4) if p >= 0]
    cache: dict[int, tuple[Node, int]] = {}

    def probe_ok(target: list, total: list, n_terms: int) -> bool:
        tolerance = max(2, n_terms)
        return all(target[p] is None or abs(target[p] - total[p]) <= tolerance for p in probes)

    def item(i: int) -> tuple[Node, int]:
        """Line i with the components that follow it. Returns (node, index after its subtree)."""
        if i in cache:
            return cache[i]
        target = values[i]
        result = (Node(i), i + 1)
        if any(v for v in target if v is not None):
            # Candidate components, each with its own subtree already resolved.
            candidates: list[tuple[Node, int]] = []
            k = i + 1
            while k < n and len(candidates) < WINDOW:
                node, k = item(k)
                candidates.append((node, k))
            prefix = [0.0] * n_periods
            found = None
            for j, (node, after) in enumerate(candidates):
                prefix = _add(prefix, values[node.index])
                for skipped in _memo_sets(j):
                    total = prefix
                    for s in skipped:
                        total = _add(total, values[candidates[s][0].index], -1)
                    terms = j + 1 - len(skipped)
                    if probe_ok(target, total, terms) and _matches(target, total, terms):
                        found = (j, skipped, after)
                        break
                if found:
                    break
            if found:
                j, skipped, after = found
                parent = Node(i)
                for c in range(j + 1):
                    node = candidates[c][0]
                    if c in skipped:
                        parent.children[-1].memos.append(node)
                    else:
                        parent.children.append(node)
                result = (parent, after)
        cache[i] = result
        return result

    def _memo_sets(j: int):
        """Sets of candidate positions to treat as memos, fewest first. The first candidate is never a memo."""
        yield ()
        if MAX_MEMOS >= 1:
            for a in range(1, j + 1):
                yield (a,)
        if MAX_MEMOS >= 2:
            for a in range(1, j + 1):
                for b in range(a + 1, j + 1):
                    yield (a, b)

    # Top level: walk the table; a line with no following components may instead
    # be the total of the loose lines before it.
    roots: list[Node] = []
    loose_from = 0
    i = 0
    while i < n:
        node, after = item(i)
        backward = _trailing_total(values, roots, loose_from, i)
        if backward is not None:
            start, skipped = backward
            parent = Node(i)
            for position, child in enumerate(roots[start:]):
                if position in skipped:
                    parent.children[-1].memos.append(child)
                else:
                    parent.children.append(child)
            del roots[start:]
            roots.append(parent)
            loose_from = len(roots)
            i += 1
            continue
        roots.append(node)
        i = after
    return roots


def _trailing_total(values: list[list], roots: list[Node], loose_from: int, i: int):
    """If line i equals the sum of the loose root lines before it, return (start, memo positions)."""
    target = values[i]
    loose = roots[loose_from:]
    if len(loose) < 2 or not any(v for v in target if v is not None):
        return None
    n_periods = len(target)
    for start in range(len(loose) - 1):
        run = loose[start:]
        total = [0.0] * n_periods
        for node in run:
            total = _add(total, values[node.index])
        if _matches(target, total, len(run)):
            return loose_from + start, ()
        for a in range(1, len(run)):
            without = _add(total, values[run[a].index], -1)
            if _matches(target, without, len(run) - 1):
                return loose_from + start, (a,)
            for b in range(a + 1, len(run)):
                if _matches(target, _add(without, values[run[b].index], -1), len(run) - 2):
                    return loose_from + start, (a, b)
    return None


def build(con: duckdb.DuckDBPyConnection) -> dict:
    """Infer and store the structure of every levels table. Returns a small summary."""
    periods = [r[0] for r in con.execute(
        "SELECT DISTINCT period FROM z1_observations "
        "WHERE period LIKE '%:Q%' AND period_end >= CAST(? AS DATE) ORDER BY 1", [START]).fetchall()]
    position = {p: i for i, p in enumerate(periods)}
    tables = [r[0] for r in con.execute(
        "SELECT DISTINCT table_id FROM z1_series WHERE table_id LIKE '%\\_s' ESCAPE '\\' ORDER BY 1").fetchall()]

    rows = []
    for table_id in tables:
        lines = con.execute(
            "SELECT series_id FROM z1_series WHERE table_id = ? ORDER BY coalesce(try_cast(line AS INT), 0)",
            [table_id]).fetchall()
        ids = [r[0] for r in lines]
        index = {series_id: i for i, series_id in enumerate(ids)}
        values = [[None] * len(periods) for _ in ids]
        for series_id, period, value in con.execute(
            "SELECT series_id, period, value FROM z1_observations "
            "WHERE series_id IN (SELECT series_id FROM z1_series WHERE table_id = ?) "
            "AND period LIKE '%:Q%' AND period_end >= CAST(? AS DATE)", [table_id, START]).fetchall():
            values[index[series_id]][position[period]] = value

        def emit(node: Node, parent: str | None, role: str) -> None:
            rows.append((table_id, ids[node.index], node.index, parent, role))
            for child in node.children:
                emit(child, ids[node.index], "component")
            for memo in node.memos:
                emit(memo, ids[node.index], "memo")

        for root in infer(values):
            emit(root, None, "root")

    con.execute(
        "CREATE OR REPLACE TABLE z1_structure ("
        "table_id VARCHAR, series_id VARCHAR, position INTEGER, parent_series_id VARCHAR, role VARCHAR)")
    con.executemany("INSERT INTO z1_structure VALUES (?, ?, ?, ?, ?)", rows)
    placed = sum(1 for r in rows if r[4] != "root")
    return {"tables": len(tables), "lines": len(rows), "placed": placed}
