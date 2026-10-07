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
    recent = store.query(
        """
        SELECT to_id AS id, count(*)::int AS count FROM edges
        WHERE created_at >= %(cutoff)s
        GROUP BY to_id
        ORDER BY to_id
        """,
        {"cutoff": cutoff},
    )
    result = {row["id"]: row["count"] for row in recent}
    citations = store.query(
        """
        SELECT to_id AS id, count(*)::int AS count FROM edges
        WHERE relation = ANY(%(relations)s) AND to_collection = 'articles'
        GROUP BY to_id
        ORDER BY to_id
        """,
        {"relations": _ARTICLE_CITATION_RELATIONS},
    )
    for row in citations:
        result[row["id"]] = result.get(row["id"], 0) + row["count"]

    if min_count > 1:
        result = {k: v for k, v in result.items() if v >= min_count}
    if limit is not None and len(result) > limit:
        kept = sorted(result.items(), key=lambda item: (-item[1], item[0]))[:limit]
        result = dict(sorted(kept))
    return result
