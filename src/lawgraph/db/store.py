"""LawGraph ArangoDB store — connection, collection handles, and CRUD operations."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import time
from collections.abc import Callable, Iterable, Iterator
from typing import Any, TypeVar, cast
from uuid import uuid4

import requests
from arango.client import ArangoClient
from arango.exceptions import ArangoServerError, DocumentInsertError

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_EDGE_STATUS_LOG,
    COLLECTION_EDGES,
    COLLECTION_JUDGMENTS,
    COLLECTION_RAW_SOURCES,
    DOCUMENT_COLLECTIONS,
    EDGE_STATUS_CANONIEK,
)
from lawgraph.config.settings import (
    ARANGO_DB_NAME,
    ARANGO_PASSWORD,
    ARANGO_REQUEST_TIMEOUT,
    ARANGO_URL,
    ARANGO_USER,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node
from lawgraph.core.time import iso_timestamp
from lawgraph.db.schema import ensure_schema

logger = get_logger(__name__)

T = TypeVar("T")


def edge_key(from_id: str, relation: str, to_id: str) -> str:
    """Deterministic SHA-1 edge key — single scheme used everywhere."""
    return hashlib.sha1(f"{from_id}:{relation}:{to_id}".encode()).hexdigest()


# AQL templates shared between single-doc and batch upsert methods. ``props`` and ``meta``
# are merged one level deep here, and the statements say ``mergeObjects: false``: an UPDATE
# merges nested objects by default, which kept every key a nested value ever had (a vote
# tally showed the choice nobody made any more next to the one they changed it to).
_NODE_UPSERT_UPDATE = """
    type: doc.type,
    labels: UNIQUE(APPEND(OLD.labels, doc.labels)),
    props: MERGE(OLD.props, doc.props)
"""

_EDGE_UPSERT_UPDATE = """
    confidence: doc.confidence,
    source: doc.source,
    status: doc.status,
    meta: MERGE(OLD.meta, doc.meta)
"""


def _create_database_if_missing(client: ArangoClient) -> None:
    """Create ``ARANGO_DB_NAME`` when the user may administer the server and it is absent."""
    system = client.db("_system", username=ARANGO_USER, password=ARANGO_PASSWORD)
    try:
        exists = system.has_database(ARANGO_DB_NAME)
    except ArangoServerError:
        return  # no access to _system: the database must already exist
    if not exists:
        system.create_database(ARANGO_DB_NAME)
        logger.info("Created database %s.", ARANGO_DB_NAME)


def raw_source_doc(
    *,
    source: str,
    kind: str,
    external_id: str | None,
    payload_json: dict | list | None = None,
    payload_text: str | None = None,
    meta: dict | None = None,
) -> dict[str, Any]:
    """The raw_sources document of one record, keyed by (source, kind, external_id).

    ``fetched_at`` is the moment of this call: when the record was fetched, not when a
    buffered write stores it.
    """
    if external_id is not None:
        key = hashlib.sha1(f"{source}:{kind}:{external_id}".encode()).hexdigest()
    else:
        key = str(uuid4())
    return {
        "_key": key,
        "source": source,
        "kind": kind,
        "external_id": external_id,
        "fetched_at": iso_timestamp(
            dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        ),
        "payload_json": payload_json,
        "payload_text": payload_text,
        "meta": dict(meta or {}),
    }


# A bulk write is an upsert, so it can be sent again: a database that restarts (a second or
# two) or is still starting up must not cost a run of hours its buffer. After these waits the
# failure is real and is raised.
WRITE_RETRY_WAITS = (2.0, 10.0, 30.0)


def _is_unreachable(exc: Exception) -> bool:
    """The server cannot be reached or is starting up; not: it refused what we sent."""
    if isinstance(exc, ArangoServerError):
        return exc.http_code == 503
    return isinstance(
        exc, (ConnectionError, requests.ConnectionError, requests.Timeout)
    )


def _retry_write(what: str, write: Callable[[], T]) -> T:
    for wait in WRITE_RETRY_WAITS:
        try:
            return write()
        except Exception as exc:
            if not _is_unreachable(exc):
                raise
            logger.warning(
                "The database is unreachable (%s); writing %s again in %.0fs.",
                type(exc).__name__,
                what,
                wait,
            )
            _sleep(wait)
    return write()


def _closing(cursor: Any) -> Iterator[dict[str, Any]]:
    """The rows of *cursor*; the cursor is closed when the reader stops, however it stops.

    A reader that raises halfway would leave its query (and the snapshot it holds) open on
    the server until the ttl of an hour has passed.
    """
    try:
        yield from cursor
    finally:
        try:
            cursor.close(ignore_missing=True)
        except Exception as exc:  # the server is gone, or the cursor already is
            logger.debug("Closing a cursor failed: %s", exc)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


# A query with one of these operations changes data (AQL keywords are written in capitals
# throughout the code; ``updated_at`` and the like do not match).
_WRITES = re.compile(r"\b(INSERT|UPDATE|REPLACE|REMOVE|UPSERT)\b")
WRITE_MAX_RUNTIME = 600.0

# How long the server keeps an AQL cursor that is not read (its default is 30 seconds).
CURSOR_TTL_SECONDS = 3600.0


class ArangoStore:
    """Encapsulation of the ArangoDB client, collections, and CRUD helpers."""

    def __init__(self) -> None:
        client = ArangoClient(hosts=ARANGO_URL, request_timeout=ARANGO_REQUEST_TIMEOUT)
        try:
            _create_database_if_missing(client)
            self.db = client.db(
                ARANGO_DB_NAME, username=ARANGO_USER, password=ARANGO_PASSWORD
            )
            self.db.version()
        except Exception as exc:
            raise ConnectionError(
                f"Cannot connect to ArangoDB at {ARANGO_URL} "
                f"(db={ARANGO_DB_NAME}, user={ARANGO_USER}). "
                f"Original error: {exc}"
            ) from exc

        ensure_schema(self.db)

        self._collections = {
            name: self.db.collection(name) for name in DOCUMENT_COLLECTIONS
        }
        self._collections[COLLECTION_EDGES] = self.db.collection(COLLECTION_EDGES)

        # Shorthands for the collections this class and its callers reach for
        # by name; everything else goes through ``collection()``.
        self.articles = self._collections[COLLECTION_ARTICLES]
        self.judgments = self._collections[COLLECTION_JUDGMENTS]
        self.raw_sources = self._collections[COLLECTION_RAW_SOURCES]
        self.edge_status_log = self._collections[COLLECTION_EDGE_STATUS_LOG]
        self.edges = self._collections[COLLECTION_EDGES]

    def collection(self, name: str) -> Any:
        """Return the collection handle for *name*. Raises KeyError if unknown."""
        return self._collections[name]

    # ── Query ──────────────────────────────────────────────────────────────────

    def query(
        self,
        aql: str,
        bind_vars: dict | None = None,
        *,
        batch_size: int = 1000,
        ttl: float = CURSOR_TTL_SECONDS,
    ) -> Iterable[dict[str, Any]]:
        """Execute an AQL query; a query that only reads streams its result.

        Without a streaming cursor the server builds the whole result in its memory before
        it sends the first batch: 41,000 BWB toestanden of 80 KB are 3 GB, and that query
        killed the server. A streaming cursor computes the result while it is read, so
        ``batch_size`` documents are in flight, whatever the size of the result.

        A streamed query lives as long as its reader takes, so it gets no ``max_runtime``
        (the server would kill a pipeline that works on every batch); ``ttl`` is how long the
        server keeps the cursor between two batches (its default of 30 seconds answers
        ``cursor not found`` to such a reader).

        A query that writes is not streamed: streamed, it would only write as far as its
        cursor is read. It runs to the end at once, within ``WRITE_MAX_RUNTIME`` seconds.
        """
        writes = _WRITES.search(aql) is not None
        cursor = self.db.aql.execute(
            aql,
            bind_vars=bind_vars or {},
            stream=not writes,
            max_runtime=WRITE_MAX_RUNTIME if writes else None,  # type: ignore[arg-type]
            batch_size=batch_size,
            ttl=ttl,  # type: ignore[arg-type]
        )
        return _closing(cast(Any, cursor))

    # ── Raw sources ────────────────────────────────────────────────────────────

    def insert_raw_sources(
        self, docs: list[dict[str, Any]]
    ) -> list[tuple[dict[str, Any], str]]:
        """Upsert raw source documents (see ``raw_source_doc``) in one request.

        A stored document with the same key is replaced. Returns the documents the server
        refused, each with the reason; a failure of the request itself raises.
        """
        if not docs:
            return []
        outcome = _retry_write(
            f"{len(docs)} raw records",
            lambda: self.raw_sources.insert_many(
                docs,
                overwrite=True,
                overwrite_mode="replace",
                return_new=False,
                raise_on_document_error=False,
            ),
        )
        return [
            (doc, str(answer))
            for doc, answer in zip(docs, cast(list[Any], outcome), strict=True)
            if isinstance(answer, Exception)
        ]

    # ── Nodes ──────────────────────────────────────────────────────────────────

    def insert_or_update(self, node: Node) -> tuple[Node, bool]:
        """Upsert a Node using its deterministic key; returns (stored node, created).

        On INSERT: stores the full document as-is.
        On UPDATE: merges props so neither pipeline overwrites the other's fields,
        and unions labels arrays so domain labels survive across pipeline runs.
        """
        if node.key is None:
            raise ValueError("Node must have a deterministic key.")

        if node.collection not in DOCUMENT_COLLECTIONS:
            raise ValueError(f"Unknown collection: {node.collection!r}")

        doc = node.to_document()
        props = doc.get("props") or {}
        labels = doc.get("labels") or []
        node_type = doc.get("type", "")

        aql = f"""
        UPSERT {{ _key: @key }}
        INSERT @insert_doc
        UPDATE {{
            type: @type,
            labels: UNIQUE(APPEND(OLD.labels, @labels)),
            props: MERGE(OLD.props, @props)
        }}
        IN {node.collection} OPTIONS {{ mergeObjects: false }}
        RETURN {{doc: NEW, was_new: OLD == null}}
        """
        bind_vars: dict[str, Any] = {
            "key": node.key,
            "insert_doc": doc,
            "type": node_type,
            "labels": labels,
            "props": props,
        }
        rows = list(
            cast(
                Iterable[dict[str, Any]], self.db.aql.execute(aql, bind_vars=bind_vars)
            )
        )
        if rows:
            row = rows[0]
            return Node.from_document(node.collection, row["doc"]), bool(row["was_new"])
        return node, False

    def _bulk_upsert(
        self,
        collection: str,
        docs: list[dict[str, Any]],
        update_clause: str,
    ) -> tuple[int, int]:
        """Execute a single AQL UPSERT loop for *docs* into *collection*.

        Returns (created_count, updated_count). The *update_clause* string is
        interpolated verbatim — callers must pass one of the module-level
        ``_NODE_UPSERT_UPDATE`` or ``_EDGE_UPSERT_UPDATE`` constants.
        """
        if not docs:
            return 0, 0

        if collection not in DOCUMENT_COLLECTIONS and collection != COLLECTION_EDGES:
            raise ValueError(f"Unknown collection: {collection!r}")

        aql = f"""
        LET results = (
            FOR doc IN @docs
                UPSERT {{_key: doc._key}}
                INSERT doc
                UPDATE {{{update_clause}}}
                IN {collection} OPTIONS {{ mergeObjects: false }}
                RETURN {{was_new: OLD == null}}
        )
        RETURN {{
            created: LENGTH(FOR r IN results FILTER r.was_new RETURN 1),
            updated: LENGTH(FOR r IN results FILTER NOT r.was_new RETURN 1)
        }}
        """
        rows = _retry_write(
            f"{len(docs)} documents of {collection}",
            lambda: list(
                cast(
                    Iterable[dict[str, Any]],
                    self.db.aql.execute(aql, bind_vars={"docs": docs}),
                )
            ),
        )
        if rows:
            row = rows[0]
            return int(row.get("created", 0)), int(row.get("updated", 0))
        return 0, 0

    def bulk_insert_or_update_nodes(
        self,
        collection: str,
        docs: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Batch-upsert multiple node documents. Returns (created_count, updated_count).

        Uses a single AQL UPSERT loop per collection — reduces N individual
        round-trips to 1 for high-throughput normalize pipelines.
        """
        return self._bulk_upsert(collection, docs, _NODE_UPSERT_UPDATE)

    def existing_keys(
        self,
        collection: str,
        keys: Iterable[str],
        *,
        chunk_size: int = 5000,
    ) -> set[str]:
        """Return the subset of *keys* that exist in *collection*.

        One primary-index lookup per ``chunk_size`` keys — use this instead of
        ``get_node`` in a loop when you only need to know whether nodes exist.
        """
        if collection not in DOCUMENT_COLLECTIONS:
            raise ValueError(f"Unknown collection: {collection!r}")
        wanted = list(set(keys))
        found: set[str] = set()
        aql = f"FOR d IN {collection} FILTER d._key IN @keys RETURN d._key"
        for start in range(0, len(wanted), chunk_size):
            chunk = wanted[start : start + chunk_size]
            found.update(self.query(aql, {"keys": chunk}))
        return found

    def ensure_stub_node(
        self,
        collection: str,
        key: str,
        node_type: Any,
        props: dict[str, Any],
    ) -> Node | None:
        """Return the node if it exists, otherwise insert a minimal stub.

        Used by semantic pipelines to keep the graph connected when a
        referenced node hasn't been fully imported yet (e.g., a cited ECLI
        that isn't in the corpus). The stub carries ``props.stub=True`` so
        the frontend can surface it as a pending import.
        """
        stub_props = dict(props)
        stub_props["stub"] = True
        node_type_val = (
            node_type.value if hasattr(node_type, "value") else str(node_type)
        )
        doc: dict[str, Any] = {
            "_key": key,
            "type": node_type_val,
            "labels": [],
            "props": stub_props,
        }
        try:
            coll = self.db.collection(collection)
            result = cast(
                dict[str, Any],
                coll.insert(doc, overwrite=False, return_new=True),
            )
            raw = result.get("new") or doc
            return Node.from_document(collection, cast(dict[str, Any], raw))
        except DocumentInsertError:
            # Race: another worker inserted the stub between get and insert.
            existing = self.get_node(collection, key)
            return existing

    def get_node(self, collection: str, key: str) -> Node | None:
        """Fetch a Node by collection and key. Returns None if not found.

        Uses a single get() call rather than has() + get() to avoid two
        round-trips per lookup.
        """
        coll = self.db.collection(collection)
        raw = coll.get(key)
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise TypeError(
                f"ArangoDB returned {type(raw).__name__} for {collection}/{key}; expected dict"
            )
        return Node.from_document(collection, raw)

    # ── Edges ──────────────────────────────────────────────────────────────────

    def bulk_insert_or_update_edges(
        self,
        docs: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Batch-upsert multiple edges. Returns (created_count, updated_count).

        Uses a single AQL UPSERT loop rather than N individual insert() calls,
        giving ArangoDB the chance to optimise the batch as a transaction.
        For semantic pipelines writing hundreds of edges per run, this reduces
        HTTP round-trips from O(N) to 1.
        """
        return self._bulk_upsert(COLLECTION_EDGES, docs, _EDGE_UPSERT_UPDATE)

    def flip_edge_status(
        self,
        *,
        edge_key: str,
        new_status: str,
        triggering_decision_id: str,
        source: str = "decision-propagation",
    ) -> dict[str, Any] | None:
        """Flip an edge's status and write an immutable audit log entry.

        Every call is logged to `edge_status_log` so researchers can answer
        'why did the graph change at this point in time'.
        """
        raw_existing = self.edges.get(edge_key)
        if raw_existing is None:
            raise ValueError(f"flip_edge_status: edge {edge_key!r} not found")

        existing = cast(dict[str, Any], raw_existing)
        old_status = existing.get("status", EDGE_STATUS_CANONIEK)
        if old_status == new_status:
            return existing

        timestamp = iso_timestamp(
            dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        )

        self.edges.update(
            {"_key": edge_key, "status": new_status, "updated_at": timestamp}
        )

        log_entry: dict[str, Any] = {
            "_key": str(uuid4()),
            "edge_key": edge_key,
            "edge_from": existing.get("_from"),
            "edge_to": existing.get("_to"),
            "relation": existing.get("relation"),
            "old_status": old_status,
            "new_status": new_status,
            "triggering_decision_id": triggering_decision_id,
            "source": source,
            "timestamp": timestamp,
        }
        self.edge_status_log.insert(log_entry)
        logger.info(
            "Edge %s: %s → %s (triggered by decision %s)",
            edge_key,
            old_status,
            new_status,
            triggering_decision_id,
        )
        updated_doc = {**existing, "status": new_status, "updated_at": timestamp}
        return updated_doc
