"""Writes over a whole table in parts. A statement that writes runs for at most
``LAWGRAPH_WRITE_TIMEOUT_MS``; one that finds its rows across a whole table (the edges of a
relation not kept, the nodes whose list keys changed) can take longer on a full graph. It
reads those rows instead (a read has no time limit and streams) and writes them in chunks
of ``CHUNK``, each by its keys: the same rows, the same result."""

from __future__ import annotations

from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb

from lawgraph.core.batching import chunked
from lawgraph.db.counting import Store

# Rows written in one statement.
CHUNK = 5000


def delete_keys(
    store: Store, table: str, select_keys: Any, bind: dict[str, Any]
) -> int:
    """Remove the rows of *table* whose ``key`` the query *select_keys* gives; how many
    went."""
    statement = sql.SQL(
        "DELETE FROM {} WHERE key = ANY(%(keys)s::text[]) RETURNING 1"
    ).format(sql.Identifier(table))
    removed = 0
    # hash_joins: *select_keys* is an anti-join of a table with a list of keys, which the
    # planner takes for a row or two and tests the whole list against per row
    for keys in chunked(store.query(select_keys, bind, hash_joins=True), CHUNK):
        removed += len(store.execute(statement, {"keys": keys}))
    return removed


def update_props(store: Store, table: str, rows: Any, keys: list[str]) -> int:
    """Write *keys* of each row of *rows* (``id`` and a column per key) into the props of
    its node of *table* (``lg_update``, D11); how many were written."""
    statement = sql.SQL(
        """
        UPDATE {} t SET props = lg_update(t.props, v.value::json)
        FROM jsonb_each(%(values)s::jsonb) AS v(id, value)
        WHERE t.id = v.id
        RETURNING 1
        """
    ).format(sql.Identifier(table))
    written = 0
    for chunk in chunked(rows, CHUNK):
        values = {row["id"]: {k: row[k] for k in keys} for row in chunk}
        written += len(store.execute(statement, {"values": Jsonb(values)}))
    return written
