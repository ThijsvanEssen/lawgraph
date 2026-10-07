"""Semantic relationship queries.

Back the /api/relationships endpoints and the article relationships view. The semantic
layer of an article-to-article REFERS_TO edge lives on the edge document: ``semantic_type``
and ``explanation``, written by ``semantic bwb-relation-types``.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLES,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_SCOPED_BY,
)
from lawgraph.db import GraphStore
from lawgraph.db._rows import edge_doc, node_doc
from lawgraph.db.queries._helpers import run_together

# Relations that participate in the semantic relationship layer between articles.
ARTICLE_RELATIONS: tuple[str, ...] = (RELATION_REFERS_TO,)

# The columns of an edge, and of the nodes joined to it as ``t`` (target) and ``i``
# (instrument), under names that do not clash.
_EDGE = "e.key AS edge_key, e.from_id, e.to_id, e.doc"
_TARGET = "t.id, t.key, t.type, t.labels, t.props"
_NODE_FIELDS = ("id", "key", "type", "labels", "props")

# The parent instrument of the article ``t`` (edges go article → instrument): the first
# PART_OF edge by target id whose instrument exists. Its edges first, then each node by its
# id (as ``_helpers._find_instrument_for_article``): never ``nodes`` in the order of its ids.
_INSTRUMENT_FOR = f"""
    LEFT JOIN LATERAL (
        SELECT n.id, n.key, n.type, n.labels, n.props
        FROM (
            SELECT pe.to_id FROM edges pe
            WHERE pe.from_id = t.id AND pe.relation = '{RELATION_PART_OF}'
            ORDER BY pe.to_id
            OFFSET 0
        ) pe
        CROSS JOIN LATERAL (
            SELECT n.id, n.key, n.type, n.labels, n.props FROM nodes n WHERE n.id = pe.to_id
        ) n
        ORDER BY pe.to_id
        LIMIT 1
    ) i ON true
"""
_INSTRUMENT = (
    "i.id AS i_id, i.key AS i_key, i.type AS i_type, i.labels AS i_labels,"
    " i.props AS i_props"
)


def _edge(row: dict[str, Any]) -> dict[str, Any]:
    return edge_doc({**row, "key": row["edge_key"]})


def _instrument(row: dict[str, Any]) -> dict[str, Any] | None:
    if row["i_id"] is None:
        return None
    return node_doc({f: row[f"i_{f}"] for f in _NODE_FIELDS})


def _article_links(
    store: GraphStore, article_id: str, own: str, other: str
) -> list[dict[str, Any]]:
    """The REFERS_TO edges between *article_id* (the edge's *own* end) and another article
    (its *other* end), by edge key; each ``{edge, target, instrument}``."""
    rows = store.query(
        f"""
        SELECT {_EDGE}, {_TARGET}, {_INSTRUMENT}
        FROM edges e
        JOIN articles t ON t.id = e.{other}_id
        {_INSTRUMENT_FOR}
        WHERE e.{own}_id = %(article_id)s AND e.relation = ANY(%(relations)s)
          AND e.{other}_collection = '{COLLECTION_ARTICLES}'
        ORDER BY e.key
        """,
        {"article_id": article_id, "relations": list(ARTICLE_RELATIONS)},
    )
    return [
        {"edge": _edge(row), "target": node_doc(row), "instrument": _instrument(row)}
        for row in rows
    ]


def get_article_relationship_data(
    store: GraphStore,
    article_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """Return upstream/downstream article relationships plus annex scope links.

    * upstream — outgoing article references (this article depends on the target)
    * downstream — incoming article references (other articles rely on this one)
    * scope — outgoing SCOPED_BY edges to annex nodes

    REFERS_TO also carries references from judgments and documents, so both
    directions are restricted to article endpoints. Each list is in edge key order; an
    edge whose other end is gone is left out.
    """
    upstream, downstream, scope = run_together(
        lambda: _article_links(store, article_id, "from", "to"),
        lambda: _article_links(store, article_id, "to", "from"),
        lambda: _scope_links(store, article_id),
    )
    return {"upstream": upstream, "downstream": downstream, "scope": scope}


def _scope_links(store: GraphStore, article_id: str) -> list[dict[str, Any]]:
    """The SCOPED_BY edges from *article_id* to an annex, by edge key; each
    ``{edge, annex}``."""
    rows = store.query(
        f"""
        SELECT {_EDGE}, {_TARGET}
        FROM edges e JOIN annexes t ON t.id = e.to_id
        WHERE e.from_id = %(article_id)s AND e.relation = %(scoped_by)s
          AND e.to_collection = '{COLLECTION_ANNEXES}'
        ORDER BY e.key
        """,
        {"article_id": article_id, "scoped_by": RELATION_SCOPED_BY},
    )
    return [{"edge": _edge(row), "annex": node_doc(row)} for row in rows]


def search_relationships(
    store: GraphStore,
    *,
    semantic_types: Collection[str] | None = None,
    exclude_types: Collection[str] | None = None,
    bwb_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Classified edges, filtered by semantic type and by the law of the source article.

    *semantic_types* keeps the edges of any of those types, *exclude_types* drops the edges
    of those; both may be given. Returns ``(rows, total)``, each row
    ``{edge, source_article, target}``, by edge key. The page is cut from the matching
    edges before their ends are read: an edge with an end that is gone leaves its page one
    short, and still counts in the total.
    """
    conditions = ["e.semantic_type IS NOT NULL"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if semantic_types:
        conditions.append("e.semantic_type = ANY(%(semantic_types)s)")
        params["semantic_types"] = sorted(semantic_types)
    if exclude_types:
        conditions.append("NOT e.semantic_type = ANY(%(exclude_types)s)")
        params["exclude_types"] = sorted(exclude_types)
    if bwb_id:
        # Only the edges that leave an article of the law (driven from its index).
        conditions.append(
            "e.from_id = ANY(ARRAY(SELECT id FROM articles WHERE bwb_id = %(bwb_id)s))"
        )
        params["bwb_id"] = bwb_id
    where = " AND ".join(conditions)

    total = next(
        store.query(f"SELECT count(*)::int FROM edges e WHERE {where}", params)
    )
    # The matches are cut to the page first: every classified edge of a law with its
    # article (text included) is hundreds of MB to count them and show fifty.
    rows = store.query(
        f"""
        SELECT {_EDGE},
               s.id AS s_id, s.key AS s_key, s.type AS s_type, s.labels AS s_labels,
               s.props AS s_props, {_TARGET}
        FROM (
            SELECT * FROM edges e WHERE {where}
            ORDER BY e.key
            LIMIT %(limit)s OFFSET %(offset)s
        ) e
        -- per edge an id lookup in each table of the view, not a join of the view
        CROSS JOIN LATERAL (SELECT * FROM nodes WHERE nodes.id = e.from_id) s
        CROSS JOIN LATERAL (SELECT * FROM nodes WHERE nodes.id = e.to_id) t
        ORDER BY e.key
        """,
        params,
    )
    page = [
        {
            "edge": _edge(row),
            "source_article": node_doc({f: row[f"s_{f}"] for f in _NODE_FIELDS}),
            "target": node_doc(row),
        }
        for row in rows
    ]
    return page, int(total)
