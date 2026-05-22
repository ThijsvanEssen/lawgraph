"""LawGraph ArangoDB store — connection, collection handles, and CRUD operations."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterable
from typing import Any, cast
from uuid import uuid4

from arango.client import ArangoClient
from arango.exceptions import DocumentInsertError

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENT_ARTICLE_VERSIONS,
    COLLECTION_INSTRUMENT_VERSIONS,
    EDGE_STATUS_CANONIEK,
)
from lawgraph.config.settings import (
    ARANGO_DB_NAME,
    ARANGO_PASSWORD,
    ARANGO_REQUEST_TIMEOUT,
    ARANGO_URL,
    ARANGO_USER,
    COLLECTION_EDGES,
)
from lawgraph.config.settings import DOCUMENT_COLLECTIONS as _ALL_COLLECTION_NAMES
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node
from lawgraph.core.time import iso_timestamp

logger = get_logger(__name__)


def edge_key(from_id: str, relation: str, to_id: str) -> str:
    """Deterministic SHA-1 edge key — single scheme used everywhere."""
    return hashlib.sha1(f"{from_id}:{relation}:{to_id}".encode()).hexdigest()


# AQL templates shared between single-doc and batch upsert methods.
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


class ArangoStore:
    """Encapsulation of the ArangoDB client, collections, and CRUD helpers."""

    def __init__(self) -> None:
        client = ArangoClient(hosts=ARANGO_URL, request_timeout=ARANGO_REQUEST_TIMEOUT)
        try:
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

        from lawgraph.db.schema import ensure_schema

        ensure_schema(self.db)

        self._collections = {
            name: self.db.collection(name) for name in _ALL_COLLECTION_NAMES
        }
        self._collections[COLLECTION_EDGES] = self.db.collection(COLLECTION_EDGES)

        # Typed shorthand properties for the most frequently accessed collections.
        self.instruments = self._collections["instruments"]
        self.instrument_articles = self._collections["instrument_articles"]
        self.instrument_versions = self._collections[COLLECTION_INSTRUMENT_VERSIONS]
        self.instrument_article_versions = self._collections[
            COLLECTION_INSTRUMENT_ARTICLE_VERSIONS
        ]
        self.procedures = self._collections["procedures"]
        self.publications = self._collections["publications"]
        self.judgments = self._collections["judgments"]
        self.topics = self._collections["topics"]
        self.raw_sources = self._collections["raw_sources"]
        self.kamerstukdossiers = self._collections["kamerstukdossiers"]
        self.activiteiten = self._collections["activiteiten"]
        self.stemmingen = self._collections["stemmingen"]
        self.toezeggingen = self._collections["toezeggingen"]
        self.commissies = self._collections["commissies"]
        self.leden = self._collections["leden"]
        self.fracties = self._collections["fracties"]
        self.edge_status_log = self._collections["edge_status_log"]
        self.watches = self._collections["watches"]
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
        max_runtime: float = 600.0,
        batch_size: int = 1000,
    ) -> Iterable[dict[str, Any]]:
        """Execute an AQL query and stream results in batches.

        ``batch_size`` controls how many documents ArangoDB sends per HTTP
        response.  The default of 1000 keeps memory bounded for large result
        sets while reducing round-trips compared to the driver default of 100.
        Pipeline callers that do list() on the result see no difference;
        streaming callers benefit automatically.
        """
        cursor = self.db.aql.execute(
            aql,
            bind_vars=bind_vars or {},
            max_runtime=max_runtime,  # type: ignore[arg-type]
            batch_size=batch_size,
        )
        # python-arango <8.0 returns a cursor; >=8.0 returns a list directly
        result_attr = getattr(cursor, "result", None)
        if callable(result_attr):
            cursor = result_attr()
        return cast(Iterable[dict[str, Any]], cursor)

    # ── Raw sources ────────────────────────────────────────────────────────────

    def insert_raw_source(
        self,
        *,
        source: str,
        kind: str,
        external_id: str | None,
        payload_json: dict | list | None = None,
        payload_text: str | None = None,
        meta: dict | None = None,
    ) -> dict[str, Any]:
        """Upsert a raw source record keyed by (source, kind, external_id)."""
        fetched_at = iso_timestamp(
            dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        )

        if external_id is not None:
            record_key = hashlib.sha1(
                f"{source}:{kind}:{external_id}".encode()
            ).hexdigest()
        else:
            record_key = str(uuid4())

        doc: dict[str, Any] = {
            "_key": record_key,
            "source": source,
            "kind": kind,
            "external_id": external_id,
            "fetched_at": fetched_at,
            "payload_json": payload_json,
            "payload_text": payload_text,
            "meta": dict(meta or {}),
        }
        result = self.raw_sources.insert(doc, overwrite=True, overwrite_mode="replace")
        return cast(dict[str, Any], result)

    # ── Nodes ──────────────────────────────────────────────────────────────────

    def insert_node(self, node: Node) -> Node:
        """Insert a Node and return it with its resolved key."""
        if node.key is None:
            raise ValueError(
                f"insert_node requires a key; got node with type={node.type!r}"
            )
        collection = self.db.collection(node.collection)
        doc = node.to_document()
        inserted = cast(dict[str, Any], collection.insert(doc))
        new_key = inserted.get("_key") or node.key
        return node.with_key(str(new_key))

    def insert_or_update(self, node: Node) -> Node:
        """Upsert a Node using its deterministic key.

        On INSERT: stores the full document as-is.
        On UPDATE: merges props so neither pipeline overwrites the other's fields,
        and unions labels arrays so domain labels survive across pipeline runs.
        """
        if node.key is None:
            raise ValueError("Node must have a deterministic key.")

        if node.collection not in _ALL_COLLECTION_NAMES:
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
        IN {node.collection}
        RETURN NEW
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
            return Node.from_document(node.collection, rows[0])
        return node

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

        if collection not in _ALL_COLLECTION_NAMES and collection != COLLECTION_EDGES:
            raise ValueError(f"Unknown collection: {collection!r}")

        aql = f"""
        LET results = (
            FOR doc IN @docs
                UPSERT {{_key: doc._key}}
                INSERT doc
                UPDATE {{{update_clause}}}
                IN {collection}
                RETURN {{was_new: OLD == null}}
        )
        RETURN {{
            created: LENGTH(FOR r IN results FILTER r.was_new RETURN 1),
            updated: LENGTH(FOR r IN results FILTER NOT r.was_new RETURN 1)
        }}
        """
        rows = list(
            cast(
                Iterable[dict[str, Any]],
                self.db.aql.execute(aql, bind_vars={"docs": docs}),
            )
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

    def update_node(self, node: Node) -> Node:
        """Update an existing Node (must have key)."""
        if node.key is None:
            raise ValueError("Node must have a key to be updated.")
        collection = self.db.collection(node.collection)
        collection.update(node.to_document())
        return node

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

    def create_edge(
        self,
        *,
        from_id: str,
        to_id: str,
        relation: str,
        source: str = "",
        confidence: float | None = None,
        status: str = EDGE_STATUS_CANONIEK,
        meta: dict | None = None,
    ) -> dict[str, Any]:
        """Upsert an edge using a deterministic SHA-1 key. Never creates duplicates.

        The `status` parameter defaults to "canoniek" for structural/semantic edges.
        Parliamentary proposed-mutation edges should pass status="voorgesteld".

        ``created_at`` is set once on insert and never overwritten on update,
        consistent with the bulk upsert path (_EDGE_UPSERT_UPDATE).
        """
        if confidence is not None and not (0.0 <= confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {confidence}")
        e_key = edge_key(from_id, relation, to_id)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        doc: dict[str, Any] = {
            "_key": e_key,
            "_from": from_id,
            "_to": to_id,
            "relation": relation,
            "source": source,
            "status": status,
            "created_at": now,
            "meta": dict(meta or {}),
        }
        if confidence is not None:
            doc["confidence"] = confidence

        from lawgraph.config.settings import COLLECTION_EDGES

        update_fields = (
            "confidence: doc.confidence, source: doc.source, "
            "status: doc.status, meta: MERGE(OLD.meta, doc.meta)"
        )
        aql = f"""
        UPSERT {{_key: @key}}
        INSERT @doc
        UPDATE {{{update_fields}}}
        IN {COLLECTION_EDGES}
        RETURN NEW
        """
        rows = list(
            cast(
                Iterable[dict[str, Any]],
                self.db.aql.execute(aql, bind_vars={"key": e_key, "doc": doc}),
            )
        )
        return rows[0] if rows else doc

    def insert_or_update_edge(
        self,
        doc: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Upsert an edge in the unified edges collection. Returns (stored_doc, was_created)."""
        e_key = doc.get("_key")
        if not isinstance(e_key, str):
            raise ValueError("Edge document must include a `_key` string.")
        result = cast(
            dict[str, Any],
            self.edges.insert(doc, overwrite=True, return_new=True, return_old=True),
        )
        was_created = result.get("old") is None
        stored = result.get("new") or result
        return cast(dict[str, Any], stored), was_created

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
        triggering_stemming_id: str,
        source: str = "stemming-propagation",
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
            "triggering_stemming_id": triggering_stemming_id,
            "source": source,
            "timestamp": timestamp,
        }
        self.edge_status_log.insert(log_entry)
        logger.info(
            "Edge %s: %s → %s (triggered by stemming %s)",
            edge_key,
            old_status,
            new_status,
            triggering_stemming_id,
        )
        updated_doc = {**existing, "status": new_status, "updated_at": timestamp}
        return updated_doc
