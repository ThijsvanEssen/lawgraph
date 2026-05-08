"""LawGraph ArangoDB store."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterable
from typing import Any, cast
from uuid import uuid4

from arango.client import ArangoClient

from lawgraph.config.settings import (
    ARANGO_DB_NAME,
    ARANGO_PASSWORD,
    ARANGO_URL,
    ARANGO_USER,
    COLLECTION_EDGE_STATUS_LOG,
    COLLECTION_EDGES,
    DOCUMENT_COLLECTIONS,
    EDGE_STATUS_CANONIEK,
)
from lawgraph.logging import get_logger
from lawgraph.models import Node

logger = get_logger(__name__)


def _edge_key(from_id: str, relation: str, to_id: str) -> str:
    """Deterministic SHA-1 edge key — single scheme used everywhere."""
    return hashlib.sha1(f"{from_id}:{relation}:{to_id}".encode()).hexdigest()


class ArangoStore:
    """Encapsulation of the ArangoDB client, collections, and helpers."""

    def __init__(self) -> None:
        self.url = ARANGO_URL
        self.db_name = ARANGO_DB_NAME
        self.username = ARANGO_USER
        self.password = ARANGO_PASSWORD

        client = ArangoClient(hosts=self.url)
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

        self._ensure_collections()

        self.instruments = self.db.collection("instruments")
        self.instrument_articles = self.db.collection("instrument_articles")
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
        self.edge_status_log = self.db.collection(COLLECTION_EDGE_STATUS_LOG)
        self.watches = self.db.collection("watches")
        self.edges = self.db.collection(COLLECTION_EDGES)

    def _ensure_collections(self) -> None:
        """Create missing document and edge collections, then ensure indexes."""
        for name in DOCUMENT_COLLECTIONS:
            if not self.db.has_collection(name):
                self.db.create_collection(name)
                logger.info("Created document collection %s", name)

        if not self.db.has_collection(COLLECTION_EDGES):
            self.db.create_collection(COLLECTION_EDGES, edge=True)
            logger.info("Created edge collection %s", COLLECTION_EDGES)

        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Ensure performance-critical persistent indexes exist."""
        index_specs: list[tuple[str, list[str], bool]] = [
            # Array indexes on labels
            ("instrument_articles", ["labels[*]"], False),
            ("publications", ["labels[*]"], False),
            ("judgments", ["labels[*]"], False),
            ("procedures", ["labels[*]"], False),
            ("kamerstukdossiers", ["labels[*]"], False),
            # Node field indexes
            ("instruments", ["props.bwb_id"], True),
            ("instruments", ["props.celex"], True),
            ("instrument_articles", ["props.bwb_id", "props.article_number"], True),
            ("instrument_articles", ["props.celex", "props.article_number"], True),
            ("judgments", ["props.ecli"], True),
            ("publications", ["props.soort"], False),
            ("publications", ["props.datum"], False),
            ("publications", ["props.dossier_nummer"], False),
            ("kamerstukdossiers", ["props.nummer"], False),
            ("kamerstukdossiers", ["props.afgedaan"], False),
            ("kamerstukdossiers", ["props.gesloten_op"], False),
            ("activiteiten", ["props.dossier_id"], False),
            ("activiteiten", ["props.datum"], False),
            ("stemmingen", ["props.dossier_id"], False),
            ("stemmingen", ["props.aangenomen"], False),
            ("toezeggingen", ["props.dossier_id"], False),
            ("toezeggingen", ["props.status"], False),
            ("watches", ["node_id"], False),
            # Edge indexes — critical for all traversal queries
            (COLLECTION_EDGES, ["relation"], False),
            (COLLECTION_EDGES, ["_from", "relation"], False),
            (COLLECTION_EDGES, ["_to", "relation"], False),
            (COLLECTION_EDGES, ["status"], False),
            (COLLECTION_EDGES, ["status", "relation"], False),
        ]
        for coll_name, fields, unique in index_specs:
            if not self.db.has_collection(coll_name):
                continue
            coll = self.db.collection(coll_name)
            existing_by_fields = {
                tuple(idx["fields"]): idx
                for idx in coll.indexes()
                if idx.get("type") == "persistent"
            }
            key = tuple(fields)
            if key in existing_by_fields:
                existing_idx = existing_by_fields[key]
                existing_unique = existing_idx.get("unique", False)
                if existing_unique == unique:
                    continue
                try:
                    coll.delete_index(existing_idx["id"])
                except Exception:
                    continue
            try:
                coll.add_persistent_index(fields=fields, unique=unique, sparse=True)
                logger.info(
                    "Created index on %s %s (unique=%s)", coll_name, fields, unique
                )
            except Exception as exc:
                logger.warning(
                    "Could not create index on %s %s: %s", coll_name, fields, exc
                )

    # ── Query ──────────────────────────────────────────────────────────────────

    def query(
        self,
        aql: str,
        bind_vars: dict | None = None,
    ) -> Iterable[dict[str, Any]]:
        """Execute an AQL query and return results."""
        cursor = self.db.aql.execute(aql, bind_vars=bind_vars or {})
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
        rows = list(self.db.aql.execute(aql, bind_vars=bind_vars))
        if rows:
            return Node.from_document(node.collection, cast(dict[str, Any], rows[0]))
        return node

    def update_node(self, node: Node) -> Node:
        """Update an existing Node (must have key)."""
        if node.key is None:
            raise ValueError("Node must have a key to be updated.")
        collection = self.db.collection(node.collection)
        collection.update(node.to_document())
        return node

    def get_node(self, collection: str, key: str) -> Node | None:
        """Fetch a Node by collection and key. Returns None if not found."""
        coll = self.db.collection(collection)
        if not coll.has(key):
            return None
        raw = coll.get(key)
        if raw is None:
            return None
        return Node.from_document(collection, cast(dict[str, Any], raw))

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
        existing = self.edges.get(edge_key)
        if existing is None:
            logger.warning("flip_edge_status: edge %s not found", edge_key)
            return None

        old_status = existing.get("status", EDGE_STATUS_CANONIEK)
        if old_status == new_status:
            return cast(dict[str, Any], existing)

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
