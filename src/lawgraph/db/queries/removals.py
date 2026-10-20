"""The removals of nodes and edges: of records that went, and of what a step no longer
derives. A node never goes without its edges, except where a pipeline derives the nodes of
a collection in full (``remove_nodes_except``)."""

from __future__ import annotations

from typing import Literal

from psycopg import sql
from psycopg.types.json import Jsonb

from lawgraph.core.batching import chunked
from lawgraph.db.counting import Store
from lawgraph.db.queries._chunks import CHUNK, delete_keys

# The rows whose key is not in ``%(keep)s``: an anti-join, not a scan of the list per row
# (a pipeline keeps hundreds of thousands of keys).
_NOT_KEPT = "NOT EXISTS (SELECT 1 FROM unnest(%(keep)s::text[]) AS k WHERE k = {key})"

EdgeEnd = Literal["from_id", "to_id"]


def remove_edges_except(
    store: Store, relation: str, keep: list[str], *, source: str | None = None
) -> int:
    """Remove the edges of *relation* (made by *source*, or by any) whose key is not in
    *keep*; how many went. For edges one pipeline derives in full on every run, so an edge
    it no longer derives goes."""
    of_source = "" if source is None else "AND e.source = %(source)s"
    select = f"""
        SELECT e.key FROM edges e
        WHERE e.relation = %(relation)s {of_source}
          AND {_NOT_KEPT.format(key="e.key")}
    """
    bind = {"relation": relation, "source": source, "keep": keep}
    return delete_keys(store, "edges", select, bind)


def remove_edges_at(
    store: Store,
    end: EdgeEnd,
    relations: list[str],
    ids: list[str],
    keep: dict[str, set[str]],
    *,
    source: str,
    other_ends: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Remove the edges of *relations* made by *source* whose *end* is one of *ids* and
    whose key is not in *keep* (per node id): a pipeline that derives the edges from (or
    into) a node in full removes those it no longer derives. With *other_ends*, only the
    edges whose other end is in one of those collections (the step derives those alone).
    ``(from_id, to_id)`` of every edge that went."""
    # The edges at a node that *keep* (``{node id: [edge key, ...]}``, as jsonb) does not
    # name.
    other = "to_collection" if end == "from_id" else "from_collection"
    statement = f"""
        DELETE FROM edges e
        WHERE e.{end} = ANY(%(ids)s::text[])
          AND e.relation = ANY(%(relations)s::text[]) AND e.source = %(source)s
          AND NOT coalesce((%(keep)s::jsonb -> e.{end}) ? e.key, false)
          {"AND e." + other + " = ANY(%(other_ends)s::text[])" if other_ends else ""}
        RETURNING e.from_id, e.to_id
    """
    removed: list[tuple[str, str]] = []
    for chunk in chunked(ids, CHUNK):
        rows = store.execute(
            statement,
            {
                "ids": chunk,
                "relations": relations,
                "source": source,
                "keep": Jsonb({i: sorted(keep[i]) for i in chunk if i in keep}),
                "other_ends": other_ends,
            },
        )
        removed += [(row["from_id"], row["to_id"]) for row in rows]
    return removed


# The nodes whose other edges ``remove_edges_into_except`` removes in one statement.
INTO_CHUNK = 500


def remove_edges_into_except(
    store: Store, relation: str, written: dict[str, list[str]]
) -> int:
    """Remove the *relation* edges into each node of *written* whose key is not among the
    keys written into it; how many went. For the edges of a node one run derives in full
    (the votes on a decision)."""
    statement = f"""
        DELETE FROM edges e
        WHERE e.to_id = ANY(%(to_ids)s::text[]) AND e.relation = %(relation)s
          AND {_NOT_KEPT.format(key="e.key")}
        RETURNING 1
    """
    removed = 0
    for to_ids in chunked(sorted(written), INTO_CHUNK):
        keep = [key for to_id in to_ids for key in written[to_id]]
        bind = {"to_ids": to_ids, "relation": relation, "keep": keep}
        removed += len(store.execute(statement, bind))
    return removed


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
    return sum(
        len(store.execute(statement, {"ids": chunk, "all": record_ids}))
        for chunk in chunked(record_ids, CHUNK)
    )


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
    for chunk in chunked(keys, CHUNK):
        ids = [f"{collection}/{key}" for key in chunk]
        removed += len(store.execute(statement, {"keys": chunk, "ids": ids}))
    return removed


def remove_nodes_except(store: Store, collection: str, keep: list[str]) -> int:
    """Remove the nodes of *collection* whose key is not in *keep*, for a collection one
    pipeline derives in full; how many went. (The edges at them stay, as they did.)"""
    select = sql.SQL(
        "SELECT n.key FROM {} n WHERE " + _NOT_KEPT.format(key="n.key")
    ).format(sql.Identifier(collection))
    return delete_keys(store, collection, select, {"keep": keep})


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
