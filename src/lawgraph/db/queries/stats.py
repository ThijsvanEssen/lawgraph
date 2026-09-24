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


def get_judgment_coverage(store: ArangoStore) -> dict[str, Any]:
    """The judgments the graph holds (not the stubs of judgments it only knows as cited),
    per source, court tier and court, with the first and last date of each; and how many
    stubs there are. Every field it reads is in one index of ``db/schema.py``, so it
    counts without reading a judgment."""
    aql = f"""
    FOR j IN {COLLECTION_JUDGMENTS}
        FILTER j.props.stub == false
        COLLECT source = j.props.source, tier = j.props.tier,
                court_code = j.props.court_code
        AGGREGATE count = COUNT(1), first_date = MIN(j.props.date_eff),
                  last_date = MAX(j.props.date_eff), court = MAX(j.props.court)
        RETURN {{source, tier, court_code, court, count, first_date, last_date}}
    """
    stubs = f"""
    FOR j IN {COLLECTION_JUDGMENTS}
        FILTER j.props.stub == true
        COLLECT WITH COUNT INTO n
        RETURN n
    """
    return {
        "courts": list(store.query(aql)),
        "stubs": next(iter(store.query(stubs)), 0),
    }
