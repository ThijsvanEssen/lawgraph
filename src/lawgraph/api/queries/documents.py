"""Queries behind the document endpoints."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    RELATION_EXPLAINS,
    RELATION_REFERS_TO,
)
from lawgraph.config.settings import COLLECTION_EDGES
from lawgraph.db import ArangoStore


def get_document(store: ArangoStore, key: str) -> dict[str, Any] | None:
    """One document by key (keys are lowercased at ingest)."""
    doc = store.collection(COLLECTION_DOCUMENTS).get(key.lower())
    return doc if isinstance(doc, dict) else None


def list_documents(
    store: ArangoStore,
    *,
    q: str | None,
    kind: str | None,
    chamber: str | None,
    source: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Document rows with the number of articles each one links to.

    The count is computed for the limited page only, so the whole list is one
    round trip.
    """
    filters: list[str] = []
    bind: dict[str, Any] = {
        "limit": limit,
        "linking": [RELATION_REFERS_TO, RELATION_EXPLAINS],
    }

    if chamber:
        filters.append("FILTER @chamber IN document.labels")
        bind["chamber"] = chamber.upper()
    if source:
        filters.append("FILTER document.props.source == @source")
        bind["source"] = source
    if kind:
        filters.append("FILTER document.props.kind == @kind")
        bind["kind"] = kind
    if q:
        filters.append(
            "FILTER CONTAINS(LOWER(document.props.title), LOWER(@q))"
            " OR CONTAINS(LOWER(document.props.kind), LOWER(@q))"
        )
        bind["q"] = q

    aql = f"""
FOR document IN {COLLECTION_DOCUMENTS}
    {chr(10).join(f"    {f}" for f in filters)}
    SORT document.props.date DESC, document.props.title ASC
    LIMIT @limit
    LET linked = LENGTH(
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == document._id
            FILTER e.relation IN @linking
            RETURN 1
    )
    RETURN {{
        key: document._key,
        title: document.props.title,
        kind: document.props.kind,
        date: document.props.date,
        external_id: document.props.external_id,
        source: document.props.source,
        has_text: document.props.text != null,
        linked_articles: linked
    }}
"""
    return list(store.query(aql, bind_vars=bind))
