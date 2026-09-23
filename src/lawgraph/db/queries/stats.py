"""Database stats query helpers."""

from __future__ import annotations

from typing import Any, cast

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
    COLLECTION_TOPICS,
)
from lawgraph.db import ArangoStore

_NODE_COLLECTIONS = (
    COLLECTION_INSTRUMENTS,
    COLLECTION_ARTICLES,
    COLLECTION_JUDGMENTS,
    COLLECTION_DOCUMENTS,
    COLLECTION_CASES,
    COLLECTION_TOPICS,
    COLLECTION_DOSSIERS,
    COLLECTION_ACTIVITIES,
    COLLECTION_DECISIONS,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_MEMBERS,
)


def _count_by(store: ArangoStore, collection: str, field: str) -> dict[str, int]:
    """Number of documents in *collection* per value of *field* (``unknown`` when null)."""
    aql = f"""
    FOR doc IN {collection}
        COLLECT value = doc.{field} WITH COUNT INTO n
        RETURN [value, n]
    """
    return {value or "unknown": n for value, n in store.query(aql)}


def get_db_stats(store: ArangoStore) -> dict[str, Any]:
    """Document counts per collection, edge counts per relation, and source breakdowns."""
    return {
        "nodes": {
            name: cast(int, store.collection(name).count())
            for name in _NODE_COLLECTIONS
        },
        "edges": {
            "total": store.edges.count(),
            "by_relation": _count_by(store, COLLECTION_EDGES, "relation"),
        },
        "by_source": {
            "judgments": _count_by(store, COLLECTION_JUDGMENTS, "props.source"),
            "documents": _count_by(store, COLLECTION_DOCUMENTS, "props.source"),
        },
        "instruments": {
            "by_kind": _count_by(store, COLLECTION_INSTRUMENTS, "props.kind"),
            "by_jurisdiction": _count_by(
                store, COLLECTION_INSTRUMENTS, "props.jurisdiction"
            ),
        },
    }
