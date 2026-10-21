"""Nodes written straight into the graph and what the integration tests read back of it,
shared by more than one test module."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RELATION_REFERS_TO,
)
from lawgraph.db import GraphStore

# The tables a run of the whole chain fills.
CHAIN_COLLECTIONS = (
    "cases",
    "documents",
    "dossiers",
    "decisions",
    "activities",
    "commitments",
    "members",
    "factions",
    "committees",
    "instruments",
    "articles",
    "judgments",
    "edges",
)


def node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": node_type, "labels": [], "props": props}


def cabinet_post(faction: str, short: str, start: str, end: str | None = None) -> dict:
    return {
        "party": {"short": short, "faction": faction},
        "from_date": start,
        "to_date": end,
    }


def member_node(key: str, *periods: tuple[str, str, str | None]) -> dict[str, Any]:
    return node(
        key,
        "member",
        name=key,
        faction_memberships=[
            {"faction_key": f, "from_date": start, "to_date": end}
            for f, start, end in periods
        ],
    )


def put_node(store: GraphStore, collection: str, key: str, **props: Any) -> None:
    doc = {"key": key, "type": collection.rstrip("s"), "labels": [], "props": props}
    store.bulk_insert_or_update_nodes(collection, [doc])


def cited_articles(store: GraphStore, judgment_key: str) -> dict[str, dict[str, Any]]:
    rows = store.query(
        "SELECT a.key, coalesce(a.stub, false) AS stub, e.doc -> 'meta' AS meta "
        "FROM edges e LEFT JOIN articles a ON a.id = e.to_id "
        "WHERE e.from_id = %(j)s AND e.relation = %(r)s",
        {"j": f"judgments/{judgment_key}", "r": RELATION_REFERS_TO},
    )
    return {row["key"]: row for row in rows}


def cited_judgments(store: GraphStore) -> set[tuple[str, str]]:
    sql = """
    SELECT f.ecli AS from_ecli, t.ecli AS to_ecli
    FROM edges e
    LEFT JOIN judgments f ON f.id = e.from_id
    LEFT JOIN judgments t ON t.id = e.to_id
    WHERE e.relation = %(relation)s
        AND e.from_collection = 'judgments' AND e.to_collection = 'judgments'
    """
    return {
        (row["from_ecli"], row["to_ecli"])
        for row in store.query(sql, {"relation": RELATION_REFERS_TO})
    }


def collection_counts(store: GraphStore) -> dict[str, int]:
    return {name: store.count(name) for name in CHAIN_COLLECTIONS}


def edge_keys(store: GraphStore) -> set[str]:
    return set(store.query("SELECT key FROM edges"))


def revisions(
    store: GraphStore, collection: str, where: str = "true"
) -> dict[str, str]:
    """The key of every row of *collection* with its ``xmin``: the transaction that wrote it
    last."""
    statement = f"SELECT key, xmin::text AS rev FROM {collection} WHERE {where}"
    return {row["key"]: row["rev"] for row in store.query(statement)}


def write_evrm(store: GraphStore) -> None:
    """The ECHR Convention as ``normalize bwb`` writes BWBV0001000: EVRM from its WTI."""
    store.bulk_insert_or_update_nodes(
        COLLECTION_INSTRUMENTS,
        [
            {
                "key": "bwbv0001000",
                "type": "instrument",
                "labels": [],
                "props": {
                    "bwb_id": "BWBV0001000",
                    "title": "Verdrag tot bescherming van de rechten van de mens en de "
                    "fundamentele vrijheden",
                    "short_title": "EVRM",
                    "aliases": ["EVRM"],
                },
            }
        ],
    )
    store.bulk_insert_or_update_nodes(
        COLLECTION_ARTICLES,
        [
            {
                "key": "bwbv0001000_8",
                "type": "article",
                "labels": [],
                "props": {"bwb_id": "BWBV0001000", "article_number": "8"},
            }
        ],
    )
