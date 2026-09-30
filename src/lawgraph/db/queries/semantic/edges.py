"""The edge removals of the semantic phase: a step that derives the edges of a node in full
removes those it no longer derives."""

from __future__ import annotations

from lawgraph.config.constants import (
    COLLECTION_EDGES,
)
from lawgraph.db.counting import Store


def remove_edges_of_source_except(
    store: Store, relation: str, source: str, keep: list[str]
) -> int:
    """Remove the edges of *relation* made by *source* whose key is not in *keep*: for edges
    one pipeline derives in full on every run. How many went."""
    aql = f"""
    FOR e IN {COLLECTION_EDGES}
        FILTER e.relation == @relation AND e.source == @source
        FILTER e._key NOT IN @keep
        REMOVE e IN {COLLECTION_EDGES}
        RETURN 1
    """
    bind = {"relation": relation, "source": source, "keep": keep}
    return sum(store.query(aql, bind))


def remove_edges_from(
    store: Store,
    relation: str,
    source: str,
    from_ids: list[str],
    keep: dict[str, set[str]],
    *,
    chunk: int = 5000,
) -> int:
    """Remove the edges of *relation* made by *source* from any of *from_ids* whose key is
    not in *keep* (per node id): a pipeline that derives the edges of a node in full removes
    those it no longer derives. How many went."""
    aql = f"""
    FOR id IN @ids
        LET kept = @keep[id] OR []
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == id AND e.relation == @relation AND e.source == @source
            FILTER e._key NOT IN kept
            REMOVE e IN {COLLECTION_EDGES}
            RETURN 1
    """
    removed = 0
    for start in range(0, len(from_ids), chunk):
        ids = from_ids[start : start + chunk]
        removed += sum(
            store.query(
                aql,
                {
                    "ids": ids,
                    "relation": relation,
                    "source": source,
                    "keep": {i: sorted(keep[i]) for i in ids if i in keep},
                },
            )
        )
    return removed


def remove_edges_to(
    store: Store,
    relations: list[str],
    source: str,
    to_ids: list[str],
    keep: dict[str, set[str]],
    *,
    chunk: int = 5000,
) -> int:
    """Remove the edges of *relations* made by *source* into any of *to_ids* whose key is
    not in *keep* (per node id): the counterpart of ``remove_edges_from`` for a pipeline that
    derives the edges into a node in full. How many went."""
    aql = f"""
    FOR id IN @ids
        LET kept = @keep[id] OR []
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == id AND e.relation IN @relations AND e.source == @source
            FILTER e._key NOT IN kept
            REMOVE e IN {COLLECTION_EDGES}
            RETURN 1
    """
    removed = 0
    for start in range(0, len(to_ids), chunk):
        ids = to_ids[start : start + chunk]
        removed += sum(
            store.query(
                aql,
                {
                    "ids": ids,
                    "relations": relations,
                    "source": source,
                    "keep": {i: sorted(keep[i]) for i in ids if i in keep},
                },
            )
        )
    return removed
