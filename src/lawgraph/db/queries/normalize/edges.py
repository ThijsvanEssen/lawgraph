"""The removals of the normalize phase: the nodes and edges of records that went or that a
step no longer derives."""

from __future__ import annotations

from psycopg import sql

from lawgraph.db.counting import Store
from lawgraph.db.queries._chunks import delete_keys

# The rows whose key is not in ``%(keep)s``: an anti-join, not a scan of the list per row
# (a pipeline keeps hundreds of thousands of keys).
_NOT_KEPT = "NOT EXISTS (SELECT 1 FROM unnest(%(keep)s::text[]) AS k WHERE k = {key})"


def remove_nodes_except(store: Store, collection: str, keep: list[str]) -> int:
    """Remove the nodes of *collection* whose key is not in *keep*, for a collection one
    pipeline derives in full; how many went. (The edges at them stay, as they did.)"""
    select = sql.SQL(
        "SELECT n.key FROM {} n WHERE " + _NOT_KEPT.format(key="n.key")
    ).format(sql.Identifier(collection))
    return delete_keys(store, collection, select, {"keep": keep})


# Keys removed in one statement.
_REMOVE_CHUNK = 5000


def remove_nodes(store: Store, collection: str, keys: list[str]) -> int:
    """Remove the nodes *keys* of *collection* with every edge at them; how many nodes went.
    A key without a node is passed over."""
    # The edges first, then the nodes, in one statement: a node never goes without its edges.
    # ``= ANY`` of a list on both ends: the indexes on from_id and to_id find the edges (an
    # ``IN`` of a subquery on either end read the whole edges table for every chunk).
    statement = sql.SQL(
        """
        WITH edges_gone AS (
            DELETE FROM edges e
            WHERE e.from_id = ANY(%(ids)s::text[]) OR e.to_id = ANY(%(ids)s::text[])
        )
        DELETE FROM {} n WHERE n.key = ANY(%(keys)s::text[])
        RETURNING 1
        """
    ).format(sql.Identifier(collection))
    removed = 0
    for start in range(0, len(keys), _REMOVE_CHUNK):
        chunk = keys[start : start + _REMOVE_CHUNK]
        ids = [f"{collection}/{key}" for key in chunk]
        removed += len(store.execute(statement, {"keys": chunk, "ids": ids}))
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
    # ``external_ids || [external_id]``: the list when there is one (an array is truthy even
    # when empty), else the one id; a value that is no string is no record id.
    statement = sql.SQL(
        """
        SELECT n.key FROM {} n
        WHERE (lg_str(n.props -> 'external_id') = ANY(%(ids)s::text[])
               OR lg_text_array(n.props -> 'external_ids') && %(ids)s::text[])
          AND NOT EXISTS (
            SELECT 1
            FROM json_array_elements(
                CASE WHEN json_typeof(n.props -> 'external_ids') = 'array'
                     THEN n.props -> 'external_ids'
                     ELSE json_build_array(n.props -> 'external_id') END
            ) AS x(v)
            WHERE lg_str(x.v) IS NULL OR NOT lg_str(x.v) = ANY(%(ids)s::text[])
          )
        ORDER BY n.key
        """
    ).format(sql.Identifier(collection))
    keys = list(store.query(statement, {"ids": record_ids}))
    return remove_nodes(store, collection, keys)


def remove_edges_of_records(store: Store, record_ids: list[str]) -> int:
    """Remove the edges made of the TK records *record_ids* alone (every id in
    ``meta.record_ids`` is one of them); how many went. For a record the Kamer deleted: a
    vote or a seat names nothing but its id then."""
    # ``record_ids`` holds the strings of ``meta.record_ids``: as many as the array has
    # elements, or one was something else, which no record id equals.
    statement = """
        DELETE FROM edges e
        WHERE e.record_ids && %(ids)s::text[]
          AND e.record_ids <@ %(all)s::text[]
          AND cardinality(e.record_ids)
              = json_array_length(e.doc -> 'meta' -> 'record_ids')
        RETURNING 1
    """
    removed = 0
    for start in range(0, len(record_ids), _REMOVE_CHUNK):
        chunk = record_ids[start : start + _REMOVE_CHUNK]
        removed += len(store.execute(statement, {"ids": chunk, "all": record_ids}))
    return removed


def remove_edges_into_except(
    store: Store, relation: str, to_ids: list[str], keep: list[str]
) -> int:
    """Remove the *relation* edges into *to_ids* whose key is not in *keep*; how many went.
    For the edges of a node one run derives in full (the votes on a decision)."""
    statement = f"""
        DELETE FROM edges e
        WHERE e.to_id = ANY(%(to_ids)s::text[]) AND e.relation = %(relation)s
          AND {_NOT_KEPT.format(key="e.key")}
        RETURNING 1
    """
    bind = {"to_ids": to_ids, "relation": relation, "keep": keep}
    return len(store.execute(statement, bind))


def remove_edges_except(store: Store, relation: str, keep: list[str]) -> int:
    """Remove the edges of *relation* whose key is not in *keep*; how many went. For edges
    one pipeline derives in full on every run, so an edge it no longer derives goes."""
    select = f"""
        SELECT e.key FROM edges e
        WHERE e.relation = %(relation)s AND {_NOT_KEPT.format(key="e.key")}
    """
    return delete_keys(store, "edges", select, {"relation": relation, "keep": keep})
