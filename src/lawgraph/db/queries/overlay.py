"""Bulk node overlay queries (in-flux and heat counts)."""

from __future__ import annotations

import datetime as dt

from lawgraph.config.constants import (
    EDGE_STATUS_VOORGESTELD,
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_REFERS_TO,
    RELATION_REPEALS,
)
from lawgraph.db import GraphStore


def get_in_flux_counts(store: GraphStore) -> dict[str, int]:
    """Return a map of node_id → count of proposed edges pointing at it, by node id.

    The map is empty when the graph holds no proposed edges yet (e.g. before the
    amendment scanner has run) — that is the truth, not a bug.
    """
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


def get_heat_tops(store: GraphStore, top: int) -> dict[int, list[tuple[str, int]]]:
    """Per window of ``HEAT_WINDOWS`` the *top* nodes with the highest heat (as
    ``get_heat_counts``), highest first, the id settling ties: one pass over the edges for
    every window, from which each ``months``, ``min_count`` and ``limit`` up to *top* is
    read without another (``heat_top``)."""
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
    rows = store.query(
        f"""
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
        """,
        params,
    )
    found: dict[int, list[tuple[str, int]]] = {months: [] for months in HEAT_WINDOWS}
    for row in rows:
        found[row["months"]].append((row["id"], row["count"]))
    for listed in found.values():
        listed.sort(key=lambda item: (-item[1], item[0]))
    return found


def heat_top(
    tops: dict[int, list[tuple[str, int]]], months: int, min_count: int, limit: int
) -> dict[str, int]:
    """The *limit* highest of window *months* with at least *min_count*, by node id."""
    kept = [item for item in tops[months] if item[1] >= max(min_count, 1)][:limit]
    return dict(sorted(kept))
