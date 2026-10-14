"""Bulk node overlay queries (in-flux and heat counts)."""

from __future__ import annotations

import datetime as dt

from lawgraph.config.constants import (
    CHANGE_RELATIONS,
    COLLECTION_ARTICLES,
    COLLECTION_EDGES,
    EDGE_STATUS_VOORGESTELD,
    RELATION_REFERS_TO,
)
from lawgraph.db import GraphStore, version_cache


def get_in_flux_counts(store: GraphStore) -> dict[str, int]:
    """Return a map of node_id → count of proposed edges pointing at it, by node id.

    The map is empty when the graph holds no proposed edges yet (e.g. before the
    amendment scanner has run) — that is the truth, not a bug.

    It reads every proposed edge (5.9 s on prod, 10 Oct): kept while the edges stand still
    and warmed after a change of them, so a request finds it computed.
    """

    def count() -> dict[str, int]:
        rows = store.query(
            """
            SELECT to_id AS id, count(*)::int AS count FROM edges
            WHERE status = %(proposed)s
            GROUP BY to_id
            ORDER BY to_id
            """,
            {"proposed": EDGE_STATUS_VOORGESTELD},
        )
        return {row["id"]: row["count"] for row in rows}

    return version_cache.cached(store, ("in flux",), count, tables=(COLLECTION_EDGES,))


# Every article-level signal, whatever its timestamp: references and amendments. Those
# edges may carry no created_at but are permanent signals of activity on an article.
_ARTICLE_CITATION_RELATIONS = [RELATION_REFERS_TO, *CHANGE_RELATIONS]
# The length of a month of the heat windows.
DAYS_PER_MONTH = 30
# The windows (months) the heat of the whole graph is counted for, all in one pass.
HEAT_WINDOWS = (3, 6, 12, 24)
# How many nodes of each window are counted and kept (``lg_heat``): the most a map asks.
HEAT_MAX_LIMIT = 50_000


def _counted_sql(
    windows: tuple[int, ...], *, named: bool
) -> tuple[str, dict[str, object]]:
    """The heat of each node per window of *windows* months: per node (``id``) the edges
    pointing at it created in each window (``m<months>``) and the citations of an article,
    whatever their timestamp (``cited``); the heat of a window is ``m<months> + cited``.
    *named* counts the nodes of ``%(ids)s`` alone (an index read each), otherwise every
    node with a signal in the widest window. The SQL and its parameters."""
    now = dt.datetime.now(dt.timezone.utc)
    params: dict[str, object] = {
        "relations": _ARTICLE_CITATION_RELATIONS,
        "articles": COLLECTION_ARTICLES,
    }
    for months in windows:
        params[f"c{months}"] = (
            now - dt.timedelta(days=DAYS_PER_MONTH * months)
        ).isoformat()
    cited = "relation = ANY(%(relations)s) AND to_collection = %(articles)s"
    counts = "".join(
        f"count(*) FILTER (WHERE created_at >= %(c{m})s)::int AS m{m}, "
        for m in windows
    )
    where = (
        "to_id = ANY(%(ids)s::text[])"
        if named
        else f"created_at >= %(c{max(windows)})s OR ({cited})"
    )
    statement = f"""
        SELECT to_id AS id, {counts}count(*) FILTER (WHERE {cited})::int AS cited
        FROM edges
        WHERE {where}
        GROUP BY to_id
        """
    return statement, params


def get_heat_counts(
    store: GraphStore, *, ids: list[str], months: int = 6, min_count: int = 1
) -> dict[str, int]:
    """Return a map of node_id → activity count of the nodes *ids*, by node id.

    Combines two signals:
    - Recent parliamentary activity: edges with created_at within the past
      *months* months (committees, dossiers, activities).
    - Citation activity: edges pointing at an article (they carry no created_at
      timestamp, so they always count as a supplemental article-layer signal).

    ``min_count`` (at least 1) filters the long tail. Only the nodes a view of the graph
    draws are counted, through the index on ``to_id``; the heat of the whole graph is
    kept by ``store_heat``.
    """
    statement, params = _counted_sql((months,), named=True)
    rows = store.query(statement, {**params, "ids": ids})
    heat = {row["id"]: row[f"m{months}"] + row["cited"] for row in rows}
    return {
        node: count
        for node, count in sorted(heat.items())
        if count >= max(min_count, 1)
    }


def _heat_tops_sql(top: int) -> tuple[str, dict[str, object]]:
    """Per window of ``HEAT_WINDOWS`` the *top* nodes with the highest heat
    (``_counted_sql``), the id settling ties, in one pass over the edges: the SQL
    (``months``, ``id``, ``count``) and its parameters."""
    counted, params = _counted_sql(HEAT_WINDOWS, named=False)
    tops = "\nUNION ALL\n".join(
        f"(SELECT {m} AS months, id, m{m} + cited AS count FROM counted"
        f" WHERE m{m} + cited > 0 ORDER BY count DESC, id LIMIT %(top)s)"
        for m in HEAT_WINDOWS
    )
    return f"WITH counted AS MATERIALIZED ({counted})\n{tops}", {**params, "top": top}


def store_heat(store: GraphStore, top: int) -> int:
    """Count the heat of every window (``_heat_tops_sql``) and keep it in ``lg_heat``, in
    place of what it held, in one transaction: a reader sees the old heat or the new. The
    rows it keeps."""
    statement, params = _heat_tops_sql(top)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    store.execute_together(
        [
            ("DELETE FROM lg_heat", None),
            (f"INSERT INTO lg_heat (months, id, count) {statement}", params),
            (
                "INSERT INTO lg_heat_state (one, computed_at, data_version)"
                " VALUES (true, %(now)s, %(version)s)"
                " ON CONFLICT (one) DO UPDATE SET computed_at = EXCLUDED.computed_at,"
                " data_version = EXCLUDED.data_version",
                {"now": now, "version": store.data_version()},
            ),
        ]
    )
    return int(next(store.query("SELECT count(*)::int FROM lg_heat")))


def stored_heat(
    store: GraphStore, months: int, min_count: int, limit: int
) -> dict[str, int] | None:
    """The kept heat (``store_heat``) of the window of ``HEAT_WINDOWS`` that holds *months*
    (5 counts as 6): the *limit* highest with at least *min_count*, by node id; None while
    none was kept."""
    months = next((w for w in HEAT_WINDOWS if w >= months), max(HEAT_WINDOWS))
    if next(store.query("SELECT count(*)::int FROM lg_heat_state")) == 0:
        return None
    rows = store.query(
        """
        SELECT id, count FROM lg_heat
        WHERE months = %(months)s AND count >= %(min_count)s
        ORDER BY count DESC, id
        LIMIT %(limit)s
        """,
        {"months": months, "min_count": max(min_count, 1), "limit": limit},
    )
    return dict(sorted((row["id"], row["count"]) for row in rows))
