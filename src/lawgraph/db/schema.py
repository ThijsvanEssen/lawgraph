"""ArangoDB schema: collections, indexes, analyzers and search views."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypeVar, cast

from arango.exceptions import CollectionCreateError

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
    COLLECTION_RAW_SOURCES,
    DOCUMENT_COLLECTIONS,
    TEXT_ANALYZER,
)

if TYPE_CHECKING:
    from arango.database import StandardDatabase
    from arango.result import Result

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _at_once(answer: Result[T]) -> T:
    """The driver types every call as its answer or a job that will have it; a plain
    database connection, the only kind used here, answers at once."""
    return cast(T, answer)


_DUPLICATE_NAME = 1207  # ArangoDB: a collection of that name exists


def ensure_schema(db: StandardDatabase) -> None:
    """Ensure all collections, indexes, analyzers, and search views exist."""
    ensure_collections(db)
    _ensure_indexes(db)
    _ensure_analyzers(db)
    _ensure_search_views(db)


def ensure_collections(db: StandardDatabase) -> None:
    """Create missing document and edge collections."""
    for name in (*DOCUMENT_COLLECTIONS, COLLECTION_EDGES):
        if db.has_collection(name):
            continue
        try:
            db.create_collection(name, edge=name == COLLECTION_EDGES)
        except CollectionCreateError as exc:
            # Two processes that start on an empty database both find it missing; the one
            # that comes second must not die of "duplicate name".
            if exc.error_code != _DUPLICATE_NAME:
                raise
            continue
        logger.info("Created collection %s", name)


def _ensure_analyzers(db: StandardDatabase) -> None:
    """Ensure custom analyzers used by /api/search exist.

    * ``lawgraph_ngram_v2`` — 3..12 char ngrams over lowercased UTF-8, so
      substring queries like 'Vordering' resolve against compound words
      like 'Wetboek van Strafvordering' (which standard stemmers split
      on whitespace only).
    * ``lawgraph_norm`` — lowercased identity, so identifier fields like
      ``bwb_id='BWBR0001903'`` match a case-insensitive prefix query.
    """
    specs: list[dict[str, Any]] = [
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
    existing = {a["name"].split("::")[-1] for a in _at_once(db.analyzers())}
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


def _indexed_fields(links: dict[str, Any]) -> dict[str, dict[str, frozenset[str]]]:
    """collection -> field -> analyzers: the part of a view definition that we specify.

    The server returns links with its own defaults added and analyzers in its own order.
    """
    return {
        collection: {
            field: frozenset(spec.get("analyzers", ()))
            for field, spec in link["fields"]["props"]["fields"].items()
        }
        for collection, link in links.items()
    }


# view -> {collection: {field: analyzers}}; each view indexes one collection.
_VIEW_SPECS: dict[str, dict[str, dict[str, list[str]]]] = {
    "search_articles": {
        COLLECTION_ARTICLES: {
            "display_name": [TEXT_ANALYZER, "identity", "lawgraph_ngram_v2"],
            "text": [TEXT_ANALYZER],
            "article_number": [TEXT_ANALYZER, "identity", "lawgraph_norm"],
            "bwb_id": [TEXT_ANALYZER, "identity", "lawgraph_norm"],
        },
    },
    "search_instruments": {
        COLLECTION_INSTRUMENTS: {
            "title": [TEXT_ANALYZER, "lawgraph_ngram_v2"],
            "citation_title": [TEXT_ANALYZER, "identity", "lawgraph_ngram_v2"],
            "official_title": [TEXT_ANALYZER, "lawgraph_ngram_v2"],
            "display_name": [TEXT_ANALYZER, "identity", "lawgraph_ngram_v2"],
            "short_title": ["identity", "lawgraph_norm"],
            "bwb_id": ["identity", "lawgraph_norm"],
        },
    },
    "search_judgments": {
        COLLECTION_JUDGMENTS: {
            "display_name": [TEXT_ANALYZER, "identity", "lawgraph_ngram_v2"],
            # every element of the array: "Haviltex", "Lindenbaum/Cohen"
            "names": [TEXT_ANALYZER, "identity", "lawgraph_norm", "lawgraph_ngram_v2"],
            "summary": [TEXT_ANALYZER],
            "ecli": ["identity", "lawgraph_norm"],
            "appno": ["identity", "lawgraph_norm"],
        },
    },
    "search_dossiers": {
        COLLECTION_DOSSIERS: {
            "title": [TEXT_ANALYZER, "lawgraph_ngram_v2"],
            "display_name": [TEXT_ANALYZER, "lawgraph_ngram_v2"],
            "number": ["identity", "lawgraph_norm"],
        },
    },
    "search_documents": {
        COLLECTION_DOCUMENTS: {
            "title": [TEXT_ANALYZER, "lawgraph_ngram_v2"],
            "display_name": [TEXT_ANALYZER, "lawgraph_ngram_v2"],
            "external_id": ["identity", "lawgraph_norm"],
        },
    },
    "search_committees": {
        COLLECTION_COMMITTEES: {
            "name": [TEXT_ANALYZER, "lawgraph_ngram_v2"],
            "abbreviation": [TEXT_ANALYZER, "identity", "lawgraph_norm"],
        },
    },
}

# view -> the collection it indexes (``lawgraph check`` compares their sizes).
SEARCH_VIEWS: dict[str, str] = {
    view: next(iter(links)) for view, links in _VIEW_SPECS.items()
}


def _ensure_search_views(db: StandardDatabase) -> None:
    """Ensure ArangoSearch views back the /api/search text-search path.

    Each searchable collection gets its own view linking the relevant
    nested ``props`` fields with the right analyzers:
      * ``TEXT_ANALYZER`` (Dutch) — tokenises, lowercases and stems display_name,
        title, text, summary.
      * ``identity`` — keeps identifiers intact for exact-match queries.
      * ``lawgraph_norm`` — lowercased identifier match (bwb_id, ecli).
      * ``lawgraph_ngram_v2`` — substring match within compound words.

    Indexes are populated asynchronously by the engine; the first request
    after a fresh start may briefly miss recently inserted docs.
    """
    view_specs = _VIEW_SPECS
    existing_views = {v["name"] for v in _at_once(db.views())}
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
                current_links = _at_once(db.view(view_name)).get("links", {})
                if _indexed_fields(current_links) != _indexed_fields(view_links):
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
    # (collection, fields, unique) or (collection, fields, unique, sparse);
    # an omitted ``sparse`` defaults to True.
    index_specs: list[
        tuple[str, list[str], bool] | tuple[str, list[str], bool, bool]
    ] = [
        # Array indexes on labels
        (COLLECTION_ARTICLES, ["labels[*]"], False),
        (COLLECTION_DOCUMENTS, ["labels[*]"], False),
        (COLLECTION_JUDGMENTS, ["labels[*]"], False),
        (COLLECTION_CASES, ["labels[*]"], False),
        (COLLECTION_DOSSIERS, ["labels[*]"], False),
        # Node field indexes
        (COLLECTION_INSTRUMENTS, ["props.bwb_id"], True),
        (COLLECTION_INSTRUMENTS, ["props.celex"], True),
        (COLLECTION_ARTICLES, ["props.bwb_id", "props.article_number"], True),
        (COLLECTION_ARTICLES, ["props.celex", "props.article_number"], True),
        # the articles of one instrument: a sparse compound index holds only articles that
        # have both fields, so the optimiser cannot use it for `bwb_id == x` alone (a
        # historical article has no number) and read every article
        (COLLECTION_ARTICLES, ["props.bwb_id"], False, True),
        (COLLECTION_ARTICLES, ["props.celex"], False, True),
        # article identity across versions (BWB stam-id): the amendments pipeline
        # resolves (bwb_id, stam_id) pairs in bulk and streams versions sorted by them
        (COLLECTION_ARTICLES, ["props.bwb_id", "props.stam_id"], False, True),
        (
            COLLECTION_ARTICLE_VERSIONS,
            ["props.bwb_id", "props.stam_id"],
            False,
            False,
        ),
        # Law history version indexes
        (
            COLLECTION_INSTRUMENT_VERSIONS,
            ["props.bwb_id", "props.valid_from"],
            False,
            False,
        ),
        (
            COLLECTION_INSTRUMENT_VERSIONS,
            ["props.bwb_id", "props.current"],
            False,
            True,
        ),
        (
            COLLECTION_ARTICLE_VERSIONS,
            ["props.bwb_id", "props.article_number", "props.valid_from"],
            False,
            False,
        ),
        (
            COLLECTION_ARTICLE_VERSIONS,
            ["props.bwb_id", "props.valid_from"],
            False,
            False,
        ),
        (
            COLLECTION_ARTICLE_VERSIONS,
            ["props.bwb_id", "props.article_number", "props.current"],
            False,
            True,
        ),
        (COLLECTION_JUDGMENTS, ["props.ecli"], True),
        (COLLECTION_JUDGMENTS, ["props.appno"], False),
        # A conclusion and its judgment share a case number; a preliminary ruling names
        # the case number of the decision that asked its questions.
        # Not sparse: a sparse index is not used for a value that is a loop variable (`FOR
        # key IN @keys ... FILTER key IN j.props.case_number_keys[*]`), only for a constant.
        (COLLECTION_JUDGMENTS, ["props.case_number_keys[*]"], False, False),
        # the judgments of one series (``semantic rechtspraak-series``)
        (COLLECTION_JUDGMENTS, ["props.series_id"], False, True),
        # What `/api/stats` counts per value is not sparse, so the count walks the index
        # and sees the documents without a value too; sparse, each count read every document.
        # It ends in the tier and the date for the facets of `/api/judgments?source=`.
        (
            COLLECTION_JUDGMENTS,
            ["props.source", "props.date_eff", "props.tier"],
            False,
            False,
        ),
        # ``/api/stats/coverage`` counts per court from this index alone
        # (``queries/stats.py``): every field it reads is in it.
        (
            COLLECTION_JUDGMENTS,
            [
                "props.stub",
                "props.source",
                "props.tier",
                "props.court_code",
                "props.court",
                "props.date_eff",
            ],
            False,
            False,
        ),
        (COLLECTION_DOCUMENTS, ["props.source"], False, False),
        # Precomputed list-endpoint keys, written by ``graph-list-stats`` and the
        # normalize pipelines. Required for index-served filters and sorts on
        # /api/instruments and /api/judgments.
        # What is sorted on (article_count, date_eff) or counted per value (jurisdiction,
        # kind) is not sparse, so the optimiser can use the index for it; the rest stay
        # sparse since they only serve equality filters.
        (COLLECTION_INSTRUMENTS, ["props.jurisdiction"], False, False),
        (COLLECTION_INSTRUMENTS, ["props.kind"], False, False),
        (COLLECTION_INSTRUMENTS, ["props.article_count"], False, False),
        # `/api/judgments` counts per tier and per year of `date_eff` under the filters
        # (`queries/judgments.py`): each filter's index ends in both, so a count reads
        # the index alone, not the judgments.
        (COLLECTION_JUDGMENTS, ["props.tier", "props.date_eff"], False, False),
        (
            COLLECTION_JUDGMENTS,
            ["props.court_code", "props.date_eff", "props.tier"],
            False,
            False,
        ),
        (COLLECTION_JUDGMENTS, ["props.date_eff", "props.tier"], False, False),
        # `/api/judgments?subject=`: `@subject IN doc.props.subjects[*]`
        (COLLECTION_JUDGMENTS, ["props.subjects[*]"], False),
        (COLLECTION_JUDGMENTS, ["props.inbound_citation_count"], False, False),
        (COLLECTION_ARTICLES, ["props.inbound_citation_count"], False, False),
        # `/api/stats` counts the stubs (the judgments count them from the coverage index)
        (COLLECTION_ARTICLES, ["props.stub"], False, True),
        (COLLECTION_INSTRUMENTS, ["props.stub"], False, True),
        # Title-sort key for /api/instruments default list.
        (COLLECTION_INSTRUMENTS, ["props.citation_title"], False, False),
        (COLLECTION_DOCUMENTS, ["props.kind"], False),
        (COLLECTION_DOCUMENTS, ["props.date"], False),
        (COLLECTION_DOCUMENTS, ["props.dossier_number"], False),
        (COLLECTION_DOSSIERS, ["props.number"], False),
        (COLLECTION_DOSSIERS, ["props.closed"], False),
        (COLLECTION_DOSSIERS, ["props.closed_on"], False),
        (COLLECTION_ACTIVITIES, ["props.date"], False),
        (COLLECTION_DECISIONS, ["props.passed"], False),
        (COLLECTION_DECISIONS, ["props.date"], False),
        # `GET /api/decisions?dossier=`: `@number IN decision.props.dossier_numbers`
        (COLLECTION_DECISIONS, ["props.dossier_numbers[*]"], False),
        (COLLECTION_COMMITMENTS, ["props.dossier_id"], False),
        (COLLECTION_COMMITMENTS, ["props.status"], False),
        # who made it and under which cabinet (``semantic tk-government``)
        (COLLECTION_COMMITMENTS, ["props.member_key"], False),
        (COLLECTION_COMMITMENTS, ["props.cabinet"], False),
        (COLLECTION_COMMITMENTS, ["props.ministry"], False),
        (COLLECTION_DOSSIERS, ["props.cabinet"], False),
        (COLLECTION_DOSSIERS, ["props.ministry"], False),
        # `GET /api/members?cabinet=`: `@cabinet IN ...government_functions[*].cabinet_key`
        (COLLECTION_MEMBERS, ["props.government_functions[*].cabinet_key"], False),
        # raw_sources: the normalize pipelines read by source and kind. Not sparse, so a
        # count per kind walks the index and reads no document (an EU act is up to 1 MB).
        (COLLECTION_RAW_SOURCES, ["source", "kind"], False, False),
        # Edge indexes — critical for all traversal queries
        (COLLECTION_EDGES, ["relation"], False, False),  # counted per relation
        (COLLECTION_EDGES, ["_from", "relation"], False),
        (COLLECTION_EDGES, ["_to", "relation"], False),
        (COLLECTION_EDGES, ["status"], False),
        (COLLECTION_EDGES, ["status", "relation"], False),
        # edges confidence — for semantic filtering by confidence threshold
        (COLLECTION_EDGES, ["confidence"], False),
        # Semantic relationship type layer — equality filters only, so sparse
        # is fine and skips the (large) majority of unclassified edges.
        (COLLECTION_EDGES, ["semantic_type"], False),
        (COLLECTION_EDGES, ["_from", "semantic_type"], False),
        # annexes — lookups by parent law
        (COLLECTION_ANNEXES, ["props.bwb_id"], False),
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
            for idx in _at_once(coll.indexes())
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
            # In the background: a foreground build locks the collection for as long as it
            # takes to read it (minutes for raw_sources), and a load running in another
            # process would time out on its writes.
            coll.add_persistent_index(
                fields=fields, unique=unique, sparse=sparse, in_background=True
            )
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
