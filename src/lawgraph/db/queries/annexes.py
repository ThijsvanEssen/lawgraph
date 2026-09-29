"""Annex queries: one annex and the articles referring to it."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_EDGES,
    RELATION_SCOPED_BY,
)
from lawgraph.db import ArangoStore


def get_annex(store: ArangoStore, key: str) -> dict[str, Any] | None:
    """Return an annex document by key, or None when unknown."""
    doc = store.collection(COLLECTION_ANNEXES).get(key)
    return doc if isinstance(doc, dict) else None


def get_annex_referenced_by(
    store: ArangoStore,
    key: str,
) -> list[dict[str, Any]]:
    """Return articles (across all laws) linked to this annex via SCOPED_BY.

    Each row: {edge, article}.
    """
    annex_id = f"{COLLECTION_ANNEXES}/{key}"
    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._to == @annex_id
        FILTER edge.relation == '{RELATION_SCOPED_BY}'
        LET article = DOCUMENT(edge._from)
        FILTER article != null
        RETURN {{ edge: edge, article: article }}
    """
    return list(store.query(aql, {"annex_id": annex_id}))
