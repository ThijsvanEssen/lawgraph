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
    store: GraphStore, *, months: int = 6, min_count: int = 1
) -> dict[str, int]:
    """Return a map of node_id → activity count.

    Combines two signals:
    - Recent parliamentary activity: edges with created_at within the past
      *months* months (committees, dossiers, activities).
    - Citation activity: edges pointing at an article (they carry no created_at
      timestamp, so they always count as a supplemental article-layer signal).

    ``min_count`` filters the long tail server-side. The corpus has ~46K
    nodes with count ≥ 1 but only ~20K with count ≥ 5 — bumping the
    threshold halves response size without affecting the visible heat
    overlay (low-count halos are barely perceptible anyway).
    """
    cutoff = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30 * months)
    ).isoformat()
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
        return {k: v for k, v in result.items() if v >= min_count}
    return result
