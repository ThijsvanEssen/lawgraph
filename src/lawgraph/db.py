"""LawGraph Arango helpers and store abstractions."""

# Structural changes:
# - Delegate collection and credential constants to lawgraph.config.settings.
# - Replace stdout collection notes with structured logging.

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any, cast
from uuid import uuid4

from arango.client import ArangoClient

from lawgraph.config.settings import (
    ARANGO_DB_NAME,
    ARANGO_PASSWORD,
    ARANGO_URL,
    ARANGO_USER,
    DOCUMENT_COLLECTIONS,
    EDGE_COLLECTIONS,
)
from lawgraph.logging import get_logger
from lawgraph.models import Node

logger = get_logger(__name__)


class ArangoStore:
    """Encapsulatie van de ArangoDB client, collecties en helpers."""

    def __init__(self) -> None:
        """Initialize the store using LAWGRAPH-specific environment settings."""
        self.url = ARANGO_URL
        self.db_name = ARANGO_DB_NAME
        self.username = ARANGO_USER
        self.password = ARANGO_PASSWORD

        client = ArangoClient(hosts=self.url)
        self.db = client.db(
            self.db_name, username=self.username, password=self.password)

        self._ensure_collections()

        self.instruments = self.db.collection("instruments")
        self.instrument_articles = self.db.collection("instrument_articles")
        self.procedures = self.db.collection("procedures")
        self.publications = self.db.collection("publications")
        self.judgments = self.db.collection("judgments")
        self.topics = self.db.collection("topics")
        self.raw_sources = self.db.collection("raw_sources")

        self.edges_strict = self.db.collection("edges_strict")
        self.edges_semantic = self.db.collection("edges_semantic")

    def _ensure_collections(self) -> None:
        """Ensure every expected collection exists, creating it when necessary."""
        for name in DOCUMENT_COLLECTIONS:
            if not self.db.has_collection(name):
                self.db.create_collection(name)
                logger.info("Created document collection %s", name)

        for name in EDGE_COLLECTIONS:
            if not self.db.has_collection(name):
                self.db.create_collection(name, edge=True)
                logger.info("Created edge collection %s", name)

    def query(
        self,
        aql: str,
        bind_vars: dict | None = None,
    ) -> Iterable[dict[str, Any]]:
        """Execute an AQL query and unwrap possible async cursor wrappers."""
        cursor = self.db.aql.execute(aql, bind_vars=bind_vars or {})

        result_attr = getattr(cursor, "result", None)
        if callable(result_attr):
            cursor = result_attr()

        return cast(Iterable[dict[str, Any]], cursor)

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
        """Unified helper to store raw dumps in the raw_sources collection."""
        fetched_at = dt.datetime.now(dt.timezone.utc).replace(
            microsecond=0).isoformat()
        if fetched_at.endswith("+00:00"):
            fetched_at = fetched_at.replace("+00:00", "Z")

        doc: dict[str, Any] = {
            "_key": str(uuid4()),
            "source": source,
            "kind": kind,
            "external_id": external_id,
            "fetched_at": fetched_at,
            "payload_json": payload_json,
            "payload_text": payload_text,
            "meta": dict(meta or {}),
        }
        inserted = cast(dict[str, Any], self.raw_sources.insert(doc))
        return inserted

    def create_edge(
        self,
        *,
        from_id: str,
        to_id: str,
        relation: str,
        strict: bool = True,
        meta: dict | None = None,
    ) -> dict[str, Any]:
        """Unified helper to create edges between nodes."""
        collection = self.edges_strict if strict else self.edges_semantic
        doc: dict[str, Any] = {
            "_key": str(uuid4()),
            "_from": from_id,
            "_to": to_id,
            "relation": relation,
            "strict": strict,
            "meta": dict(meta or {}),
        }
        inserted = cast(dict[str, Any], collection.insert(doc))
        return inserted

    def insert_node(self, node: Node) -> Node:
        """
        Insert a Node into its collection and return a Node with its resolved key.
        """
        collection = self.db.collection(node.collection)
        doc = node.to_document()

        inserted = cast(dict[str, Any], collection.insert(doc))

        new_key = inserted.get("_key") or node.key
        if new_key is None:
            new_key = str(uuid4())

        return node.with_key(str(new_key))

    def insert_or_update(self, node: Node) -> Node:
        """Insert or update the given Node using its deterministic key."""
        if node.key is None:
            raise ValueError("Node must have a deterministic key.")

        collection = self.db.collection(node.collection)
        doc = node.to_document()

        if collection.has(node.key):
            collection.update(doc)
        else:
            collection.insert(doc)

        updated = collection.get(node.key)
        if updated is None:
            raise RuntimeError("Failed to retrieve node after insert/update.")

        return Node.from_document(node.collection, cast(dict[str, Any], updated))

    def update_node(self, node: Node) -> Node:
        """Update an existing Node (must already have a key set)."""
        if node.key is None:
            raise ValueError("Node must have a key to be updated.")

        collection = self.db.collection(node.collection)
        collection.update(node.to_document())
        return node

    def get_node(self, collection: str, key: str) -> Node | None:
        """Fetch a Node from Arango by collection and key."""
        coll = self.db.collection(collection)
        if not coll.has(key):
            return None

        raw = coll.get(key)
        if raw is None:
            return None

        doc = cast(dict[str, Any], raw)
        return Node.from_document(collection, doc)
