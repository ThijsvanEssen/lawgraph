"""Copy a graph from ArangoDB into PostgreSQL as it is stored, for the parity of the API.

    python -m tests.parity.copy_graph --arango-db lawgraph_parity --pg-db lawgraph_parity

The API modules are ported before the pipelines are: with the same graph in both databases,
each module's routes can be replayed against the goldens (``replay.py --only``) without a
PostgreSQL build. Documents keep their key order (``json``); the edges keep their key, raw
records their payload references. Reads ArangoDB only; the PostgreSQL database is created
anew (with ``create_database_sql``).
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterator
from typing import Any

import psycopg
from arango.client import ArangoClient
from arango.database import StandardDatabase

from lawgraph.config import settings
from lawgraph.config.constants import (
    COLLECTION_EDGES,
    COLLECTION_PIPELINE_STATE,
    COLLECTION_RAW_SOURCES,
)
from lawgraph.db.schema import NODE_COLLECTIONS, create_database_sql, ensure_schema

SYSTEM = ("_key", "_id", "_rev", "_from", "_to")


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _documents(db: StandardDatabase, collection: str) -> Iterator[dict[str, Any]]:
    cursor = db.aql.execute(  # type: ignore[union-attr]
        f"FOR d IN {collection} RETURN d", stream=True, batch_size=2000, ttl=3600
    )
    yield from cursor  # type: ignore[misc]


def _rows(collection: str, doc: dict[str, Any]) -> tuple[Any, ...]:
    if collection in NODE_COLLECTIONS:
        return (
            doc["_id"],
            doc.get("type", ""),
            list(doc.get("labels") or []),
            _dumps(doc.get("props") or {}),
        )
    rest = {k: v for k, v in doc.items() if k not in SYSTEM}
    if collection == COLLECTION_EDGES:
        return (doc["_key"], doc["_from"], doc["_to"], _dumps(rest))
    return (doc["_key"], _dumps(rest))


_COLUMNS = {
    COLLECTION_EDGES: "key, from_id, to_id, doc",
    COLLECTION_RAW_SOURCES: "key, doc",
    COLLECTION_PIPELINE_STATE: "key, doc",
}


def copy(db: StandardDatabase, conn: psycopg.Connection) -> dict[str, int]:
    counts = {}
    tables = (
        *NODE_COLLECTIONS,
        COLLECTION_EDGES,
        COLLECTION_RAW_SOURCES,
        COLLECTION_PIPELINE_STATE,
    )
    with conn.transaction():
        conn.execute(f"TRUNCATE {', '.join(tables)}".encode())
        for collection in tables:
            columns = _COLUMNS.get(collection, "id, type, labels, props")
            n = 0
            with conn.cursor().copy(
                f"COPY {collection} ({columns}) FROM STDIN".encode()
            ) as out:
                for doc in _documents(db, collection):
                    out.write_row(_rows(collection, doc))
                    n += 1
            counts[collection] = n
            print(f"{collection}: {n:,}", flush=True)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--arango-url", default=settings.ARANGO_URL)
    parser.add_argument("--arango-db", required=True)
    parser.add_argument(
        "--pg-url", default=os.environ.get("LAWGRAPH_DB_URL", settings.DB_URL)
    )
    parser.add_argument("--pg-db", required=True)
    args = parser.parse_args()
    if args.arango_db in ("lawgraph", "lawgraph_small"):
        raise SystemExit(
            "copy from a parity database, never from lawgraph or lawgraph_small"
        )
    arango = ArangoClient(hosts=args.arango_url).db(
        args.arango_db, username=settings.ARANGO_USER, password=settings.ARANGO_PASSWORD
    )
    server = args.pg_url.rstrip("/")
    # The schema of the tables is created with them: a database made before it changed is
    # made again.
    with psycopg.connect(f"{server}/postgres", autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{args.pg_db}" WITH (FORCE)'.encode())
        admin.execute(create_database_sql(args.pg_db).encode())

    with psycopg.connect(f"{server}/{args.pg_db}", autocommit=True) as conn:
        ensure_schema(conn)
        copy(arango, conn)
        conn.execute("ANALYZE")


if __name__ == "__main__":
    main()
