"""Database stats query helpers."""

from __future__ import annotations

from typing import Any

from lawgraph.config.settings import COLLECTION_EDGE_STATUS_LOG, COLLECTION_EDGES
from lawgraph.db import ArangoStore


def get_db_stats(store: ArangoStore) -> dict[str, Any]:
    """Return document counts per collection and edge counts per relation type."""
    node_collections = [
        "instruments",
        "instrument_articles",
        "judgments",
        "publications",
        "procedures",
        "topics",
        "kamerstukdossiers",
        "activiteiten",
        "stemmingen",
        "toezeggingen",
        "commissies",
        "leden",
    ]
    nodes: dict[str, int] = {}
    for name in node_collections:
        if store.db.has_collection(name):
            nodes[name] = store.db.collection(name).count()
        else:
            nodes[name] = 0

    edges_total = store.edges.count() if store.db.has_collection("edges") else 0

    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        COLLECT relation = edge.relation WITH COUNT INTO n
        RETURN {{ relation: relation, count: n }}
    """
    by_relation: dict[str, int] = {}
    for row in store.query(aql):
        key = row.get("relation") or "unknown"
        by_relation[key] = row.get("count", 0)

    # Source breakdown for judgments
    judgments_by_source: dict[str, int] = {}
    if store.db.has_collection("judgments"):
        for row in store.query(
            "FOR j IN judgments COLLECT src = j.props.source WITH COUNT INTO n RETURN {src, n}"
        ):
            judgments_by_source[row.get("src") or "unknown"] = row.get("n", 0)

    # Kind/jurisdiction breakdown for instruments
    instruments_by_kind: dict[str, int] = {}
    if store.db.has_collection("instruments"):
        for row in store.query(
            "FOR i IN instruments COLLECT k = i.props.kind WITH COUNT INTO n RETURN {k, n}"
        ):
            instruments_by_kind[row.get("k") or "unknown"] = row.get("n", 0)

    instruments_by_jurisdiction: dict[str, int] = {}
    if store.db.has_collection("instruments"):
        for row in store.query(
            "FOR i IN instruments COLLECT j = i.props.jurisdiction WITH COUNT INTO n RETURN {j, n}"
        ):
            instruments_by_jurisdiction[row.get("j") or "unknown"] = row.get("n", 0)

    # Source breakdown for publications
    publications_by_source: dict[str, int] = {}
    if store.db.has_collection("publications"):
        for row in store.query(
            "FOR p IN publications COLLECT src = p.props.source WITH COUNT INTO n RETURN {src, n}"
        ):
            publications_by_source[row.get("src") or "unknown"] = row.get("n", 0)

    return {
        "nodes": nodes,
        "edges": {"total": edges_total, "by_relation": by_relation},
        "by_source": {
            "judgments": judgments_by_source,
            "publications": publications_by_source,
        },
        "instruments": {
            "by_kind": instruments_by_kind,
            "by_jurisdiction": instruments_by_jurisdiction,
        },
    }


def get_edge_status_log(
    store: ArangoStore, *, limit: int = 200
) -> list[dict[str, Any]]:
    """Return recent edge-status flip audit entries, newest first."""
    aql = f"""
    FOR entry IN {COLLECTION_EDGE_STATUS_LOG}
        SORT entry.timestamp DESC
        LIMIT @limit
        RETURN entry
    """
    return list(store.query(aql, {"limit": limit}))
