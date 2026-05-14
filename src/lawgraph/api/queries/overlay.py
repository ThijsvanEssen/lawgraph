"""Bulk node overlay queries (in-flux and heat counts)."""

from __future__ import annotations

import datetime as dt

from lawgraph.config.settings import (
    COLLECTION_EDGES,
    EDGE_STATUS_VOORGESTELD,
    RELATION_CITES_ARTICLE,
    RELATION_INTRODUCEERT,
    RELATION_REFERS_TO_ARTICLE,
    RELATION_TREKT_IN,
    RELATION_WIJZIGT,
)
from lawgraph.db import ArangoStore


def get_in_flux_counts(store: ArangoStore) -> dict[str, int]:
    """Return a map of node_id → count of VOORGESTELD edges pointing at it.

    Mirrors the definition used by ``get_article_in_flux`` exactly so the bulk
    overlay and per-article endpoints can never disagree. Returns an empty
    map when the graph contains no VOORGESTELD edges yet (e.g. before the
    amendment-scanner pipeline has run) — that's the truth, not a bug.
    """
    aql = f"""
    FOR e IN {COLLECTION_EDGES}
        FILTER e.status == '{EDGE_STATUS_VOORGESTELD}'
        COLLECT target = e._to WITH COUNT INTO cnt
        RETURN {{ id: target, count: cnt }}
    """
    return {row["id"]: row["count"] for row in store.query(aql)}


def get_heat_counts(
    store: ArangoStore, *, months: int = 6, min_count: int = 1
) -> dict[str, int]:
    """Return a map of node_id → activity count.

    Combines two signals:
    - Recent parliamentary activity: edges with created_at within the past
      *months* months (commissies, dossiers, activiteiten).
    - Judicial citation activity: CITES_ARTICLE edges from judgments targeting
      instrument_articles (citation edges have no created_at timestamps so they
      are always included as a supplemental article-layer signal).

    ``min_count`` filters the long tail server-side. The corpus has ~46K
    nodes with count ≥ 1 but only ~20K with count ≥ 5 — bumping the
    threshold halves response size without affecting the visible heat
    overlay (low-count halos are barely perceptible anyway).
    """
    cutoff = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30 * months)
    ).isoformat()
    aql_parliament = f"""
    FOR e IN {COLLECTION_EDGES}
        FILTER e.created_at >= @cutoff
        COLLECT target = e._to WITH COUNT INTO cnt
        RETURN {{ id: target, count: cnt }}
    """
    result = {
        row["id"]: row["count"]
        for row in store.query(aql_parliament, {"cutoff": cutoff})
    }

    # Always supplement with all article-citation signals regardless of timestamp.
    # Covers judicial citations (CITES_ARTICLE), TK/EU semantic links
    # (REFERS_TO_ARTICLE), and amendment-scanner edges (WIJZIGT, INTRODUCEERT,
    # TREKT_IN).  These edges may be old (no created_at) but are permanent
    # signals of legislative activity on an article.
    _ARTICLE_CITATION_RELATIONS = [
        RELATION_CITES_ARTICLE,
        RELATION_REFERS_TO_ARTICLE,
        RELATION_WIJZIGT,
        RELATION_INTRODUCEERT,
        RELATION_TREKT_IN,
    ]
    aql_article_citations = f"""
    FOR e IN {COLLECTION_EDGES}
        FILTER e.relation IN @relations
        FILTER STARTS_WITH(e._to, "instrument_articles/")
        COLLECT target = e._to WITH COUNT INTO cnt
        RETURN {{ id: target, count: cnt }}
    """
    for row in store.query(
        aql_article_citations, {"relations": _ARTICLE_CITATION_RELATIONS}
    ):
        node_id = row["id"]
        result[node_id] = result.get(node_id, 0) + row["count"]

    if min_count > 1:
        return {k: v for k, v in result.items() if v >= min_count}
    return result
