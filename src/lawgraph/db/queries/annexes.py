"""Annex queries: one annex and the articles referring to it."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    RELATION_SCOPED_BY,
)
from lawgraph.db import GraphStore
from lawgraph.db._rows import edge_doc, node_doc


def get_annex(store: GraphStore, key: str) -> dict[str, Any] | None:
    """Return an annex document by key, or None when unknown."""
    doc = store.get_document(COLLECTION_ANNEXES, key)
    return doc if isinstance(doc, dict) else None


def get_annex_referenced_by(
    store: GraphStore,
    key: str,
) -> list[dict[str, Any]]:
    """Return articles (across all laws) linked to this annex via SCOPED_BY.

    Each row: {edge, article}, by the id of the article and then the edge key; an edge
    whose article is gone is left out.
    """
    rows = store.query(
        """
        SELECT e.key AS edge_key, e.from_id, e.to_id, e.doc,
               n.id, n.key, n.type, n.labels, n.props
        FROM edges e JOIN nodes n ON n.id = e.from_id
        WHERE e.to_id = %(annex_id)s AND e.relation = %(scoped_by)s
        ORDER BY e.from_id, e.key
        """,
        {"annex_id": f"{COLLECTION_ANNEXES}/{key}", "scoped_by": RELATION_SCOPED_BY},
    )
    return [
        {"edge": edge_doc({**row, "key": row["edge_key"]}), "article": node_doc(row)}
        for row in rows
    ]
