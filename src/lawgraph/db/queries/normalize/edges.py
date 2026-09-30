"""The removals of the normalize phase: the nodes and edges of records that went or that a
step no longer derives."""

from __future__ import annotations

from lawgraph.config.constants import (
    COLLECTION_EDGES,
)
from lawgraph.db.counting import Store


def remove_nodes_except(store: Store, collection: str, keep: list[str]) -> int:
    """Remove the nodes of *collection* whose key is not in *keep*, for a collection one
    pipeline derives in full; how many went."""
    aql = f"""
    FOR n IN {collection}
        FILTER n._key NOT IN @keep
        REMOVE n IN {collection}
        RETURN 1
    """
    return sum(store.query(aql, {"keep": keep}))


# Keys removed in one query.
_REMOVE_CHUNK = 5000


def remove_nodes(store: Store, collection: str, keys: list[str]) -> int:
    """Remove the nodes *keys* of *collection* with every edge at them; how many nodes went.
    A key without a node is passed over."""
    removed = 0
    for start in range(0, len(keys), _REMOVE_CHUNK):
        chunk = keys[start : start + _REMOVE_CHUNK]
        edges = f"""
        FOR key IN @keys
            LET id = CONCAT(@collection, "/", key)
            FOR e IN UNION_DISTINCT(
                (FOR out IN {COLLECTION_EDGES} FILTER out._from == id RETURN out._key),
                (FOR inn IN {COLLECTION_EDGES} FILTER inn._to == id RETURN inn._key)
            )
                REMOVE e IN {COLLECTION_EDGES} OPTIONS {{ ignoreErrors: true }}
        """
        list(store.query(edges, {"keys": chunk, "collection": collection}))
        nodes = f"""
        FOR n IN {collection}
            FILTER n._key IN @keys
            REMOVE n IN {collection}
            RETURN 1
        """
        removed += sum(store.query(nodes, {"keys": chunk}))
    return removed


def remove_nodes_of_records(
    store: Store, collection: str, record_ids: list[str]
) -> int:
    """Remove the nodes of *collection* made of the TK records *record_ids* alone (every id
    in ``props.external_ids``, else ``props.external_id``, is one of them), with every edge
    at them; how many nodes went. For a record the Kamer deleted: a node keyed by a label
    (a dossier number, a faction abbreviation) cannot be found by the record's id."""
    if not record_ids:
        return 0
    aql = f"""
    FOR n IN {collection}
        FILTER n.props.external_id IN @ids
            OR LENGTH(INTERSECTION(n.props.external_ids || [], @ids)) > 0
        FILTER LENGTH(MINUS(n.props.external_ids || [n.props.external_id], @ids)) == 0
        RETURN n._key
    """
    keys = list(store.query(aql, {"ids": record_ids}))
    return remove_nodes(store, collection, keys)


def remove_edges_of_records(store: Store, record_ids: list[str]) -> int:
    """Remove the edges made of the TK records *record_ids* alone (every id in
    ``meta.record_ids`` is one of them); how many went. For a record the Kamer deleted: a
    vote or a seat names nothing but its id then."""
    removed = 0
    for start in range(0, len(record_ids), _REMOVE_CHUNK):
        aql = f"""
        LET keys = (
            FOR id IN @ids
                FOR e IN {COLLECTION_EDGES}
                    FILTER id IN e.meta.record_ids[*]
                    FILTER LENGTH(MINUS(e.meta.record_ids, @all)) == 0
                    RETURN DISTINCT e._key
        )
        FOR key IN keys
            REMOVE key IN {COLLECTION_EDGES} OPTIONS {{ ignoreErrors: true }}
            RETURN 1
        """
        chunk = record_ids[start : start + _REMOVE_CHUNK]
        removed += sum(store.query(aql, {"ids": chunk, "all": record_ids}))
    return removed


def remove_edges_into_except(
    store: Store, relation: str, to_ids: list[str], keep: list[str]
) -> int:
    """Remove the *relation* edges into *to_ids* whose key is not in *keep*; how many went.
    For the edges of a node one run derives in full (the votes on a decision)."""
    aql = f"""
    FOR id IN @to_ids
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == id AND e.relation == @relation
            FILTER e._key NOT IN @keep
            REMOVE e IN {COLLECTION_EDGES}
            RETURN 1
    """
    bind = {"to_ids": to_ids, "relation": relation, "keep": keep}
    return sum(store.query(aql, bind))


def remove_edges_except(store: Store, relation: str, keep: list[str]) -> int:
    """Remove the edges of *relation* whose key is not in *keep*; how many went. For edges
    one pipeline derives in full on every run, so an edge it no longer derives goes."""
    aql = f"""
    FOR e IN {COLLECTION_EDGES}
        FILTER e.relation == @relation AND e._key NOT IN @keep
        REMOVE e IN {COLLECTION_EDGES}
        RETURN 1
    """
    return sum(store.query(aql, {"relation": relation, "keep": keep}))
