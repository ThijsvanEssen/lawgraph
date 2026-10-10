"""Bulk node overlay queries (in-flux and heat counts)."""

from __future__ import annotations

import datetime as dt

from lawgraph.config.constants import (
    COLLECTION_EDGES,
    EDGE_STATUS_VOORGESTELD,
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_REFERS_TO,
    RELATION_REPEALS,
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
_ARTICLE_CITATION_RELATIONS = [
    RELATION_REFERS_TO,
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_REPEALS,
]


def get_heat_counts(
    store: GraphStore,
    *,
    months: int = 6,
    min_count: int = 1,
    ids: list[str] | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Return a map of node_id → activity count.

    Combines two signals:
    - Recent parliamentary activity: edges with created_at within the past
      *months* months (committees, dossiers, activities).
    - Citation activity: edges pointing at an article (they carry no created_at
      timestamp, so they always count as a supplemental article-layer signal).

    ``min_count`` filters the long tail server-side. With *ids* only those nodes are
    counted, through the index on ``to_id``: what a view of the graph draws (the whole
    graph holds 1.85 million nodes with a count). Without, *limit* keeps the nodes with
    the highest counts (the key settles ties).
    """
    cutoff = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30 * months)
    ).isoformat()
    if ids is not None:
        rows = store.query(
            """
            SELECT e.to_id AS id,
                   (count(*) FILTER (WHERE e.created_at >= %(cutoff)s)
                    + count(*) FILTER (WHERE e.relation = ANY(%(relations)s)
                                         AND e.to_collection = 'articles'))::int AS count
            FROM edges e
            WHERE e.to_id = ANY(%(ids)s::text[])
            GROUP BY e.to_id
            ORDER BY e.to_id
            """,
            {"cutoff": cutoff, "relations": _ARTICLE_CITATION_RELATIONS, "ids": ids},
        )
        return {
            row["id"]: row["count"] for row in rows if row["count"] >= max(min_count, 1)
        }
    # One statement: both signals counted in one pass over the edges, and only the *limit*
    # highest leave the database (the whole graph has 1.85 million nodes with a count).
    rows = store.query(
        f"""
        SELECT id, count FROM (
            SELECT to_id AS id,
                   (count(*) FILTER (WHERE created_at >= %(cutoff)s)
                    + count(*) FILTER (WHERE relation = ANY(%(relations)s)
                                         AND to_collection = 'articles'))::int AS count
            FROM edges
            WHERE created_at >= %(cutoff)s
               OR (relation = ANY(%(relations)s) AND to_collection = 'articles')
            GROUP BY to_id
        ) counted
        WHERE count >= %(min_count)s
        ORDER BY count DESC, id
        {"LIMIT %(limit)s" if limit is not None else ""}
        """,
        {
            "cutoff": cutoff,
            "relations": _ARTICLE_CITATION_RELATIONS,
            "min_count": max(min_count, 1),
            "limit": limit,
        },
    )
    return dict(sorted((row["id"], row["count"]) for row in rows))


# The windows (months) the heat of the whole graph is counted for, all in one pass.
HEAT_WINDOWS = (3, 6, 12, 24)
# How many nodes of each window are counted and kept (``lg_heat``): the most a map asks.
HEAT_MAX_LIMIT = 50_000


def _heat_tops_sql(top: int) -> tuple[str, dict[str, object]]:
    """Per window of ``HEAT_WINDOWS`` the *top* nodes with the highest heat (as
    ``get_heat_counts``), the id settling ties, in one pass over the edges: the SQL
    (``months``, ``id``, ``count``) and its parameters."""
    now = dt.datetime.now(dt.timezone.utc)
    params: dict[str, object] = {"relations": _ARTICLE_CITATION_RELATIONS, "top": top}
    for months in HEAT_WINDOWS:
        params[f"c{months}"] = (now - dt.timedelta(days=30 * months)).isoformat()
    windows = ",\n".join(
        f"count(*) FILTER (WHERE created_at >= %(c{m})s)::int AS m{m}"
        for m in HEAT_WINDOWS
    )
    tops = "\nUNION ALL\n".join(
        f"(SELECT {m} AS months, id, m{m} + cited AS count FROM counted"
        f" WHERE m{m} + cited > 0 ORDER BY count DESC, id LIMIT %(top)s)"
        for m in HEAT_WINDOWS
    )
    statement = f"""
        WITH counted AS MATERIALIZED (
            SELECT to_id AS id,
                   {windows},
                   count(*) FILTER (WHERE relation = ANY(%(relations)s)
                                      AND to_collection = 'articles')::int AS cited
            FROM edges
            WHERE created_at >= %(c{max(HEAT_WINDOWS)})s
               OR (relation = ANY(%(relations)s) AND to_collection = 'articles')
            GROUP BY to_id
        )
        {tops}
        """
    return statement, params


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
