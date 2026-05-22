"""ArangoDB schema management — collections, indexes, analyzers, search views.

Extracted from ArangoStore so the store class focuses on data operations.
Called once from ArangoStore.__init__; also callable standalone (e.g. in tests
or tooling that needs a schema without a full store instance).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from arango.database import StandardDatabase

logger = logging.getLogger(__name__)


def ensure_schema(db: StandardDatabase) -> None:
    """Ensure all collections, indexes, analyzers, and search views exist."""
    ensure_collections(db)
    _ensure_indexes(db)
    _ensure_analyzers(db)
    _ensure_search_views(db)


def ensure_collections(db: StandardDatabase) -> None:
    """Create missing document and edge collections."""
    from lawgraph.config.settings import COLLECTION_EDGES, DOCUMENT_COLLECTIONS

    for name in DOCUMENT_COLLECTIONS:
        if not db.has_collection(name):
            db.create_collection(name)
            logger.info("Created document collection %s", name)

    if not db.has_collection(COLLECTION_EDGES):
        db.create_collection(COLLECTION_EDGES, edge=True)
        logger.info("Created edge collection %s", COLLECTION_EDGES)


def _ensure_analyzers(db: StandardDatabase) -> None:
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
    existing = {a["name"].split("::")[-1] for a in db.analyzers()}
    for spec in specs:
        if spec["name"] in existing:
            continue
        try:
            db.create_analyzer(
                name=spec["name"],
                analyzer_type=spec["type"],
                properties=spec["properties"],
                features=spec["features"],
            )
            logger.info("Created analyzer %s", spec["name"])
        except Exception as exc:
            logger.warning("Failed to create analyzer %s: %s", spec["name"], exc)


def _ensure_search_views(db: StandardDatabase) -> None:
    """Ensure ArangoSearch views back the /api/search text-search path.

    Each searchable collection gets its own view linking the relevant
    nested ``props`` fields with the right analyzers:
      * ``text_en`` — tokenises and lowercases display_name, title, text, summary.
      * ``identity`` — keeps identifiers intact for exact-match queries.
      * ``lawgraph_norm`` — lowercased identifier match (bwb_id, ecli).
      * ``lawgraph_ngram_v2`` — substring match within compound words.

    Indexes are populated asynchronously by the engine; the first request
    after a fresh start may briefly miss recently inserted docs.
    """
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
    existing_views = {v["name"] for v in db.views()}
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
                db.create_arangosearch_view(view_name, properties=properties)
                logger.info("Created ArangoSearch view %s", view_name)
            else:
                current = db.view(view_name)
                current_links = current.get("links", {})
                if current_links != view_links:
                    db.update_arangosearch_view(view_name, properties=properties)
                    logger.info("Updated ArangoSearch view %s", view_name)
        except Exception as exc:
            logger.warning("Failed to ensure ArangoSearch view %s: %s", view_name, exc)


def _ensure_indexes(db: StandardDatabase) -> None:
    """Ensure performance-critical persistent indexes exist.

    Each spec is ``(collection, fields, unique, sparse)``. Use
    ``sparse=False`` whenever the field is a sort key for a list
    endpoint — sparse indexes drop null entries, which forces the
    optimiser back to a collection scan for ``SORT field DESC LIMIT n``
    because the result must include nulls. Equality filters are fine
    with sparse indexes (the filter inherently excludes nulls).
    """
    from lawgraph.config.settings import COLLECTION_EDGES

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
        # Precomputed list-endpoint indexes — back-filled by the maintenance
        # pipelines and maintained by the normalize pipelines. Required for
        # index-served filters/sorts on /api/instruments and /api/judgments.
        # The sort-key indexes (article_count, date_eff) are non-sparse so the
        # optimiser uses them for ``SORT field DESC LIMIT n``; the rest stay
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
        ("kamerstukdossiers", ["props.kamerstuknummer"], False),
        ("kamerstukdossiers", ["props.afgedaan"], False),
        ("kamerstukdossiers", ["props.gesloten_op"], False),
        ("activiteiten", ["props.datum"], False),
        ("stemmingen", ["props.aangenomen"], False),
        ("stemmingen", ["props.datum"], False),
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
        # NOTE: we deliberately *don't* index ``edges.created_at``. The planner
        # picks it up for the heat-window scan, but the index range covers 25%
        # of the collection so it triggers a MaterializeNode (load full doc per
        # match) — about 2× slower than the bare collection scan, which already
        # has the doc in memory. A covering index with storedValues=["_to"] would
        # help, but the gain is small (~100 ms) for the added write cost.
    ]
    for spec in index_specs:
        coll_name, fields, unique = spec[0], spec[1], spec[2]
        sparse = spec[3] if len(spec) > 3 else True
        if not db.has_collection(coll_name):
            continue
        coll = db.collection(coll_name)
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
            except Exception as exc:
                logger.warning(
                    "Failed to drop outdated index on %s %s: %s", coll_name, fields, exc
                )
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
