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
    COLLECTION_EDGE_STATUS_LOG,
    COLLECTION_INSTRUMENT_ARTICLE_VERSIONS,
    COLLECTION_INSTRUMENT_VERSIONS,
    EDGE_STATUS_CANONIEK,
)
from lawgraph.config.settings import (
    ARANGO_DB_NAME,
    ARANGO_PASSWORD,
    ARANGO_URL,
    ARANGO_USER,
    COLLECTION_EDGES,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node

logger = get_logger(__name__)


def _edge_key(from_id: str, relation: str, to_id: str) -> str:
    """Deterministic SHA-1 edge key — single scheme used everywhere."""
    return hashlib.sha1(f"{from_id}:{relation}:{to_id}".encode()).hexdigest()


class ArangoStore:
    """Encapsulation of the ArangoDB client, collections, and CRUD helpers."""

    def __init__(self) -> None:
        self.url = ARANGO_URL
        self.db_name = ARANGO_DB_NAME
        self.username = ARANGO_USER
        self.password = ARANGO_PASSWORD

        client = ArangoClient(hosts=self.url, request_timeout=620)
        try:
            self.db = client.db(
                self.db_name, username=self.username, password=self.password
            )
            self.db.version()
        except Exception as exc:
            raise ConnectionError(
                f"Cannot connect to ArangoDB at {self.url} "
                f"(db={self.db_name}, user={self.username}). "
                f"Original error: {exc}"
            ) from exc

        from lawgraph.db.schema import ensure_schema

        ensure_schema(self.db)

        self.instruments = self.db.collection("instruments")
        self.instrument_articles = self.db.collection("instrument_articles")
        self.instrument_versions = self.db.collection(COLLECTION_INSTRUMENT_VERSIONS)
        self.instrument_article_versions = self.db.collection(
            COLLECTION_INSTRUMENT_ARTICLE_VERSIONS
        )
        self.procedures = self.db.collection("procedures")
        self.publications = self.db.collection("publications")
        self.judgments = self.db.collection("judgments")
        self.topics = self.db.collection("topics")
        self.raw_sources = self.db.collection("raw_sources")
        self.kamerstukdossiers = self.db.collection("kamerstukdossiers")
        self.activiteiten = self.db.collection("activiteiten")
        self.stemmingen = self.db.collection("stemmingen")
        self.toezeggingen = self.db.collection("toezeggingen")
        self.commissies = self.db.collection("commissies")
        self.leden = self.db.collection("leden")
        self.fracties = self.db.collection("fracties")
        self.edge_status_log = self.db.collection(COLLECTION_EDGE_STATUS_LOG)
        self.watches = self.db.collection("watches")
        self.edges = self.db.collection(COLLECTION_EDGES)

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
        fetched_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        if fetched_at.endswith("+00:00"):
            fetched_at = fetched_at.replace("+00:00", "Z")

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
        collection = self.db.collection(node.collection)
        doc = node.to_document()
        inserted = cast(dict[str, Any], collection.insert(doc))
        new_key = inserted.get("_key") or node.key or str(uuid4())
        return node.with_key(str(new_key))

    def insert_or_update(self, node: Node) -> Node:
        """Upsert a Node using its deterministic key.

        On INSERT: stores the full document as-is.
        On UPDATE: merges props so neither pipeline overwrites the other's fields,
        and unions labels arrays so domain labels survive across pipeline runs.
        """
        if node.key is None:
            raise ValueError("Node must have a deterministic key.")

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

    def bulk_insert_or_update_nodes(
        self,
        collection: str,
        docs: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Batch-upsert multiple node documents. Returns (created_count, updated_count).

        Uses a single AQL UPSERT loop per collection — reduces N individual
        round-trips to 1 for high-throughput normalize pipelines.
        """
        if not docs:
            return 0, 0

        aql = f"""
        LET results = (
            FOR doc IN @docs
                UPSERT {{_key: doc._key}}
                INSERT doc
                UPDATE {{
                    type: doc.type,
                    labels: UNIQUE(APPEND(OLD.labels, doc.labels)),
                    props: MERGE(OLD.props, doc.props)
                }}
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
        existing = self.get_node(collection, key)
        if existing is not None:
            return existing

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
        """
        if confidence is not None and not (0.0 <= confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {confidence}")
        edge_key = _edge_key(from_id, relation, to_id)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        doc: dict[str, Any] = {
            "_key": edge_key,
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
        stored, _ = self.insert_or_update_edge(doc=doc)
        return stored

    def insert_or_update_edge(
        self,
        doc: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Upsert an edge in the unified edges collection. Returns (stored_doc, was_created)."""
        edge_key = doc.get("_key")
        if not isinstance(edge_key, str):
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
        if not docs:
            return 0, 0

        aql = f"""
        LET results = (
            FOR doc IN @docs
                UPSERT {{_key: doc._key}}
                INSERT doc
                UPDATE {{
                    confidence: doc.confidence,
                    source: doc.source,
                    status: doc.status,
                    meta: MERGE(OLD.meta, doc.meta)
                }}
                IN {COLLECTION_EDGES}
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

        self.edges.update({"_key": edge_key, "status": new_status})

        timestamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        if timestamp.endswith("+00:00"):
            timestamp = timestamp.replace("+00:00", "Z")

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
        return cast(dict[str, Any], self.edges.get(edge_key))
