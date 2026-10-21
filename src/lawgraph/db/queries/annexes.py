"""Annex queries: one annex, the annexes of a law and the articles referring to one."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    RELATION_SCOPED_BY,
)
from lawgraph.core.models import node_id
from lawgraph.db import GraphStore
from lawgraph.db._rows import edge_doc, node_doc
from lawgraph.db.schema import node_of


def get_annex(store: GraphStore, key: str) -> dict[str, Any] | None:
    """Return an annex document by key, or None when unknown."""
    doc = store.get_document(COLLECTION_ANNEXES, key)
    return doc if isinstance(doc, dict) else None


_LAW_ANNEXES = """
SELECT id, key, type, labels,
       json_build_object(
           'bwb_id', props -> 'bwb_id',
           'label', props -> 'label',
           'title', props -> 'title',
           'display_name', props -> 'display_name',
           'position', props -> 'position',
           'text', left(props ->> 'text', %(chars)s)
       ) AS props
FROM annexes
WHERE bwb_id = %(bwb_id)s AND (props ->> 'stub') IS DISTINCT FROM 'true'
ORDER BY (props ->> 'position')::int NULLS LAST, key
"""


def get_law_annexes(
    store: GraphStore, bwb_id: str, *, text_chars: int
) -> list[dict[str, Any]]:
    """The annexes of the law *bwb_id* its toestand holds (no stub), in the order of the
    toestand: light documents, their ``text`` cut to *text_chars*."""
    rows = store.query(_LAW_ANNEXES, {"bwb_id": bwb_id, "chars": text_chars})
    return [node_doc(row) for row in rows]


def get_annex_referenced_by(
    store: GraphStore,
    key: str,
) -> list[dict[str, Any]]:
    """Return articles (across all laws) linked to this annex via SCOPED_BY.

    Each row: {edge, article}, by the id of the article and then the edge key; an edge
    whose article is gone is left out.
    """
    rows = store.query(
        f"""
        SELECT e.key AS edge_key, e.from_id, e.to_id, e.doc,
               n.id, n.key, n.type, n.labels, n.props
        FROM edges e CROSS JOIN {node_of("e.from_id", "e.from_collection")} n
        WHERE e.to_id = %(annex_id)s AND e.relation = %(scoped_by)s
        ORDER BY e.from_id, e.key
        """,
        {"annex_id": node_id(COLLECTION_ANNEXES, key), "scoped_by": RELATION_SCOPED_BY},
    )
    return [
        {"edge": edge_doc({**row, "key": row["edge_key"]}), "article": node_doc(row)}
        for row in rows
    ]
