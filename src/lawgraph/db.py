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
    COLLECTION_INSTRUMENT_ARTICLE_VERSIONS,
    COLLECTION_INSTRUMENT_VERSIONS,
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

        self._ensure_collections()

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
        self._ensure_analyzers()
        self._ensure_search_views()

    def _ensure_analyzers(self) -> None:
        """Ensure custom analyzers used by /api/search exist.

        * ``lawgraph_ngram_v2`` — 3..12 char ngrams over lowercased UTF-8, so
          substring queries like 'Vordering' resolve against compound words
          like 'Wetboek van Strafvordering' (which standard stemmers split
          on whitespace only).
        * ``lawgraph_norm`` — lowercased identity, so identifier fields like
          ``bwb_id='BWBR0001903'`` match a case-insensitive prefix query.
        """
        specs = [
            {
                # Pipeline: lowercase → ngram. The bare ngram analyzer is
                # case-preserving, which would cause 'Vordering' (capital V)
                # to miss 'Strafvordering' (lowercase v mid-word).
                "name": "lawgraph_ngram_v2",
                "type": "pipeline",
                "properties": {
                    "pipeline": [
                        {
                            "type": "norm",
                            "properties": {
                                "locale": "en",
                                "case": "lower",
                                "accent": False,
                            },
                        },
                        {
                            "type": "ngram",
                            "properties": {
                                "min": 3,
                                "max": 12,
                                "preserveOriginal": False,
                                "streamType": "utf8",
                            },
                        },
                    ],
                },
                "features": ["position", "frequency", "norm"],
            },
            {
                "name": "lawgraph_norm",
                "type": "norm",
                "properties": {"locale": "en", "case": "lower", "accent": False},
                "features": ["frequency", "norm"],
            },
        ]
        # Analyzers are immutable in ArangoDB — to change properties, bump the
        # name (e.g. _v2 → _v3) rather than trying to drop-and-recreate, since
        # any view referencing the analyzer would block the drop. Stored
        # properties are also normalised on read (defaults injected,
        # field ordering changes), so comparing them is unreliable.
        existing = {a["name"].split("::")[-1] for a in self.db.analyzers()}
        for spec in specs:
            if spec["name"] in existing:
                continue
            try:
                self.db.create_analyzer(
                    name=spec["name"],
                    analyzer_type=spec["type"],
                    properties=spec["properties"],
                    features=spec["features"],
                )
                logger.info("Created analyzer %s", spec["name"])
            except Exception as exc:
                logger.warning("Failed to create analyzer %s: %s", spec["name"], exc)

    def _ensure_search_views(self) -> None:
        """Ensure ArangoSearch views back the /api/search text-search path.

        Each searchable collection gets its own view linking the relevant
        nested ``props`` fields with the right analyzers:
          * ``text_en`` — tokenises and lowercases display_name, title,
            text, summary, etc. Used for "every token must appear" queries.
          * ``identity`` — keeps article_number, bwb_id, ecli, slug intact
            so exact-match short queries hit the inverted index.

        Indexes are populated asynchronously by the engine; the first
        request after a fresh start may briefly miss recent docs.
        """
        # Conventions:
        #   * text_en       — token+stem matches across whitespace
        #   * identity      — exact case-sensitive (legacy, keep for back-compat)
        #   * lawgraph_norm — lowercased identifier match (e.g. bwb_id, ecli)
        #   * lawgraph_ngram_v2 — substring match within compound words
        view_specs: dict[str, dict[str, Any]] = {
            "search_articles": {
                "instrument_articles": {
                    "display_name": ["text_en", "identity", "lawgraph_ngram_v2"],
                    "text": ["text_en"],
                    "article_number": ["text_en", "identity", "lawgraph_norm"],
                    "bwb_id": ["text_en", "identity", "lawgraph_norm"],
                },
            },
            "search_instruments": {
                "instruments": {
                    "title": ["text_en", "lawgraph_ngram_v2"],
                    "citation_title": ["text_en", "identity", "lawgraph_ngram_v2"],
                    "official_title": ["text_en", "lawgraph_ngram_v2"],
                    "display_name": ["text_en", "identity", "lawgraph_ngram_v2"],
                    "short_title": ["identity", "lawgraph_norm"],
                    "bwb_id": ["identity", "lawgraph_norm"],
                },
            },
            "search_judgments": {
                "judgments": {
                    "display_name": ["text_en", "identity", "lawgraph_ngram_v2"],
                    "summary": ["text_en"],
                    "ecli": ["identity", "lawgraph_norm"],
                    "appno": ["identity", "lawgraph_norm"],
                },
            },
            "search_dossiers": {
                "kamerstukdossiers": {
                    "titel": ["text_en", "lawgraph_ngram_v2"],
                    "display_name": ["text_en", "lawgraph_ngram_v2"],
                    "kamerstuknummer": ["identity", "lawgraph_norm"],
                },
            },
            "search_publications": {
                "publications": {
                    "title": ["text_en", "lawgraph_ngram_v2"],
                    "titel": ["text_en", "lawgraph_ngram_v2"],
                    "display_name": ["text_en", "lawgraph_ngram_v2"],
                    "external_id": ["identity", "lawgraph_norm"],
                },
            },
            "search_commissies": {
                "commissies": {
                    "naam": ["text_en", "lawgraph_ngram_v2"],
                    "afkorting": ["text_en", "identity", "lawgraph_norm"],
                },
            },
        }
        existing_views = {v["name"] for v in self.db.views()}
        for view_name, links in view_specs.items():
            view_links: dict[str, Any] = {}
            for coll, fields in links.items():
                view_links[coll] = {
                    "includeAllFields": False,
                    "storeValues": "id",
                    "analyzers": ["identity"],
                    "fields": {
                        "props": {
                            "fields": {
                                fname: {"analyzers": list(analyzers)}
                                for fname, analyzers in fields.items()
                            }
                        }
                    },
                }
            properties = {"links": view_links}
            try:
                if view_name not in existing_views:
                    self.db.create_arangosearch_view(view_name, properties=properties)
                    logger.info("Created ArangoSearch view %s", view_name)
                else:
                    # Idempotent reconcile: keep links in sync with the spec.
                    self.db.update_arangosearch_view(view_name, properties=properties)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to ensure ArangoSearch view %s: %s", view_name, exc
                )

    def _ensure_indexes(self) -> None:
        """Ensure performance-critical persistent indexes exist.

        Each spec is ``(collection, fields, unique, sparse)``. Use
        ``sparse=False`` whenever the field is a sort key for a list
        endpoint — sparse indexes drop null entries, which forces the
        optimiser back to a collection scan for ``SORT field DESC LIMIT n``
        because the result must include nulls. Equality filters are fine
        with sparse indexes (the filter inherently excludes nulls).
        """
        # 4-tuple: (collection, fields, unique, sparse). Default sparse for
        # backwards-compat with the historical 3-tuple shape.
        index_specs: list[
            tuple[str, list[str], bool] | tuple[str, list[str], bool, bool]
        ] = [
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
            # Law history version indexes
            ("instrument_versions", ["props.bwb_id", "props.valid_from"], False, False),
            ("instrument_versions", ["props.bwb_id", "props.current"], False, True),
            (
                "instrument_article_versions",
                ["props.bwb_id", "props.article_number", "props.valid_from"],
                False,
                False,
            ),
            (
                "instrument_article_versions",
                ["props.bwb_id", "props.valid_from"],
                False,
                False,
            ),
            (
                "instrument_article_versions",
                ["props.bwb_id", "props.article_number", "props.current"],
                False,
                True,
            ),
            ("judgments", ["props.ecli"], True),
            ("judgments", ["props.source"], False, True),
            ("publications", ["props.source"], False, True),
            # Precomputed list-endpoint indexes — back-filled by the
            # backfill-stats migrations and maintained by the normalize
            # pipelines. Required for index-served filters/sorts on
            # /api/instruments and /api/judgments. The sort-key indexes
            # (article_count, date_eff) are non-sparse so the optimiser
            # uses them for ``SORT field DESC LIMIT n``; the rest stay
            # sparse since they only serve equality filters.
            ("instruments", ["props.jurisdiction"], False, True),
            ("instruments", ["props.kind"], False, True),
            ("instruments", ["props.article_count"], False, False),
            ("judgments", ["props.tier"], False, True),
            ("judgments", ["props.court_code"], False, True),
            ("judgments", ["props.date_eff"], False, False),
            ("judgments", ["props.inbound_citation_count"], False, False),
            # Title-sort key for /api/instruments default list.
            ("instruments", ["props.citation_title"], False, False),
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
            # raw_sources — needed for normalize pipelines scanning by source+kind
            ("raw_sources", ["source", "kind"], False),
            # Edge indexes — critical for all traversal queries
            (COLLECTION_EDGES, ["relation"], False),
            (COLLECTION_EDGES, ["_from", "relation"], False),
            (COLLECTION_EDGES, ["_to", "relation"], False),
            (COLLECTION_EDGES, ["status"], False),
            (COLLECTION_EDGES, ["status", "relation"], False),
            # edge_status_log indexes — for audit log time-range and key lookups
            ("edge_status_log", ["timestamp"], False),
            ("edge_status_log", ["edge_key"], False),
            # edges confidence — for semantic filtering by confidence threshold
            (COLLECTION_EDGES, ["confidence"], False),
            # NOTE: we deliberately *don't* index ``edges.created_at``. The
            # planner picks it up for the heat-window scan, but the index
            # range covers 25% of the collection so it triggers a
            # MaterializeNode (load full doc per match) — about 2× slower
            # than the bare collection scan, which already has the doc in
            # memory. A covering index with storedValues=["_to"] would help,
            # but the gain is small (~100 ms) for the added write cost.
        ]
        for spec in index_specs:
            coll_name, fields, unique = spec[0], spec[1], spec[2]
            sparse = spec[3] if len(spec) > 3 else True
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
                existing_sparse = existing_idx.get("sparse", False)
                if existing_unique == unique and existing_sparse == sparse:
                    continue
                try:
                    coll.delete_index(existing_idx["id"])
                except Exception:
                    continue
            try:
                coll.add_persistent_index(fields=fields, unique=unique, sparse=sparse)
                logger.info(
                    "Created index on %s %s (unique=%s, sparse=%s)",
                    coll_name,
                    fields,
                    unique,
                    sparse,
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
            max_runtime=max_runtime,
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
        """Fetch a Node by collection and key. Returns None if not found.

        Uses a single get() call rather than has() + get() to avoid two
        round-trips per lookup.
        """
        coll = self.db.collection(collection)
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
        rows = list(self.db.aql.execute(aql, bind_vars={"docs": docs}))
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
