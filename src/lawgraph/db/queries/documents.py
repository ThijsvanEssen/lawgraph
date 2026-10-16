"""Queries behind the document endpoints."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    CHAMBERS,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    RELATION_EXPLAINS,
    RELATION_PART_OF,
    RELATION_REVISES,
    RELATION_VERSION_OF,
)
from lawgraph.core.dossier_relations import RULE_REPLACEMENT
from lawgraph.core.models import key_of, make_node_key
from lawgraph.db import GraphStore
from lawgraph.db.queries._helpers import chamber_sql
from lawgraph.db.queries._json_sql import EMPTY_ARRAY, first_present, truthy_or
from lawgraph.db.queries._lists import FacetFilters, facet, where, without_page
from lawgraph.db.queries.articles import explained_targets, surest_per_anchor
from lawgraph.db.queries.members import with_member_slugs
from lawgraph.db.version_cache import cached_rows


def get_document(store: GraphStore, key: str) -> dict[str, Any] | None:
    """One document by key (keys are lowercased at ingest), with the slugs of the members
    that signed it (``with_member_slugs``)."""
    doc = store.get_document(COLLECTION_DOCUMENTS, key.lower())
    return with_member_slugs(store, doc) if doc is not None else None


# ``targets``: what each EXPLAINS edge of the document points at, a version of an article
# resolved to the first article it is a VERSION_OF (by id; NULL for a version without
# one); ``found``: those that are an article or an instrument, each once.
_LINKS_SQL = f"""
WITH targets AS (
    SELECT CASE WHEN e.to_collection = '{COLLECTION_ARTICLE_VERSIONS}' THEN (
        SELECT v.to_id
        FROM {COLLECTION_EDGES} v
        WHERE v.from_id = e.to_id AND v.relation = %(version_of)s
          AND v.to_collection = '{COLLECTION_ARTICLES}'
        ORDER BY v.to_id
        LIMIT 1
    ) ELSE e.to_id END AS id
    FROM {COLLECTION_EDGES} e
    WHERE e.from_id = %(document_id)s AND e.relation = %(explains)s
),
found AS (
    SELECT a.id, a.key, '{COLLECTION_ARTICLES}'::text AS collection,
           a.props -> 'bwb_id' AS bwb_id, a.props -> 'article_number' AS article_number
    FROM {COLLECTION_ARTICLES} a
    WHERE a.id IN (SELECT id FROM targets)
    UNION ALL
    SELECT i.id, i.key, '{COLLECTION_INSTRUMENTS}', i.props -> 'bwb_id', NULL::json
    FROM {COLLECTION_INSTRUMENTS} i
    WHERE i.id IN (SELECT id FROM targets)
)
SELECT
    ARRAY(
        SELECT DISTINCT ds.label
        FROM {COLLECTION_EDGES} e
        JOIN {COLLECTION_DOSSIERS} ds ON ds.id = e.to_id
        WHERE e.from_id = %(document_id)s AND e.relation = %(part_of)s
          AND e.to_collection = '{COLLECTION_DOSSIERS}'
          AND ds.label IS NOT NULL
        ORDER BY ds.label NULLS FIRST
    ) AS dossier_numbers,
    (
        SELECT coalesce(json_agg(json_build_object(
            'id', f.id,
            'key', f.key,
            'collection', f.collection,
            'bwb_id', f.bwb_id,
            'article_number', f.article_number
        ) ORDER BY f.id), '[]'::json)
        FROM found f
    ) AS explains
"""


def get_document_links(store: GraphStore, document_id: str) -> dict[str, Any]:
    """The dossiers a document is PART_OF and the articles or laws it EXPLAINS.

    ``dossier_numbers`` come from the PART_OF edges to dossier nodes, which both
    chambers write (an Eerste Kamer document names its dossier in ``dossier_number``, a
    Tweede Kamer one in ``dossier_numbers``), so it is the number the ``dossier``
    filters use, with its suffix for a chapter (``37020-XV``). ``explains`` resolves
    each EXPLAINS target to what a reader cites: an article version to its article
    (through VERSION_OF; a version without an article is left out), an article as it
    is, an instrument as ``instruments``.
    """
    bind = {
        "document_id": document_id,
        "part_of": RELATION_PART_OF,
        "explains": RELATION_EXPLAINS,
        "version_of": RELATION_VERSION_OF,
    }
    row = list(store.query(_LINKS_SQL, bind))[0]
    return {
        "dossier_numbers": list(row["dossier_numbers"]),
        "explains": row["explains"],
    }


def get_document_passages(
    store: GraphStore, document_id: str, bwb_id: str, article_number: str
) -> list[dict[str, Any]]:
    """The sections of a document that explain an article, one row per section.

    The edges are ``EXPLAINS`` from the document to the article or to one of its versions
    (``explained_targets``), each with the sections in ``meta.sections``. A section that
    several of those edges name is one row, with the highest confidence (of equally
    confident ones the first edge's by key). Unsorted; an unknown article has none.
    """
    article = store.get_document(
        COLLECTION_ARTICLES, make_node_key(bwb_id, article_number)
    )
    if article is None:
        return []
    targets, bind = explained_targets(article, bwb_id, article_number)
    bind.update(document_id=document_id, explains=RELATION_EXPLAINS)
    edges = store.query(
        f"""
        SELECT e.doc -> 'meta' -> 'sections'
        FROM {COLLECTION_EDGES} e
        WHERE e.from_id = %(document_id)s AND e.relation = %(explains)s
          AND e.to_id IN (SELECT t.id FROM ({targets}) t)
          AND json_typeof(e.doc -> 'meta' -> 'sections') = 'array'
        ORDER BY e.key
        """,
        bind,
    )
    return surest_per_anchor([section for sections in edges for section in sections])


_CHAMBER_OF = chamber_sql("d")


# What the list shows of a document, in the order of the answer; how a motion or an amendment
# ended and what an amendment is for from its light row (``lg_document_light``).
_ITEM = f"""json_build_object(
        'id', d.id,
        'key', d.key,
        'chamber', {_CHAMBER_OF},
        'kind', d.props -> 'kind',
        'dossier_number', d.props -> 'dossier_number',
        'dossier_suffix', d.props -> 'dossier_suffix',
        'dossier_numbers', {truthy_or("d.props -> 'dossier_numbers'", EMPTY_ARRAY)},
        'sequence', d.props -> 'sequence',
        'number', d.props -> 'number',
        'date', d.props -> 'date',
        'title', {first_present("d.props -> 'title'", "d.props -> 'display_name'")},
        'session_year', d.props -> 'session_year',
        'actors', d.props -> 'actors',
        'dictum', d.props -> 'dictum',
        'explanation', l.props -> 'explanation',
        'outcome', l.props -> 'outcome',
        'decided_on', l.props -> 'decided_on',
        'tally', l.props -> 'tally',
        'decision', l.props -> 'decision'
    )"""


def list_documents(
    store: GraphStore,
    *,
    chambers: tuple[str, ...] = CHAMBERS,
    kinds: tuple[str, ...] | None = None,
    dossier: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
    facets: bool = True,
) -> dict[str, Any]:
    """The documents of the chambers, newest first: ``{total, items, facets}``.

    *dossier* is a dossier label (``36791``, ``37020-XV``): the documents ``PART_OF`` it
    (its own and those of its cases). ``facets`` counts per ``kind`` (under the other
    filters) and per ``chamber`` (under the other filters); ``facets=False`` gives
    ``null`` for ``total`` and ``facets``. One statement either way.
    """
    bind: dict[str, Any] = {
        "chambers": list(chambers),
        "all_chambers": list(CHAMBERS),
        "from": from_date or "0",
        "to": to_date or "9",
        "limit": limit,
        "offset": offset,
    }
    # always a range on the date: the index on it then reads a page newest first (a document
    # without a date is not listed)
    shared = [
        "d.date >= %(from)s AND d.date <= %(to)s",
        "d.labels && %(all_chambers)s::text[]",
    ]
    if dossier:
        shared.append("d.dossier_numbers @> ARRAY[%(dossier)s::text]")
        bind["dossier"] = dossier
    own = {"chamber": "d.labels && %(chambers)s::text[]"}
    if kinds:
        own["kind"] = "d.kind = ANY(%(kinds)s::text[])"
        bind["kinds"] = list(kinds)
    filters = FacetFilters(shared, own)
    # The page is chosen by id first: an item is built (and the props read) only for the
    # documents on it, not for every document a deep offset skips. Each is read by its id
    # (OFFSET 0 keeps the read apart): a join let the planner read the table whole for a
    # page of 100 where it was small.
    items = f"""(
        SELECT coalesce(json_agg({_ITEM} ORDER BY d.date DESC NULLS LAST, d.key),
                        '[]'::json)
        FROM (
            SELECT d.id
            FROM {COLLECTION_DOCUMENTS} d
            {filters.where()}
            ORDER BY d.date DESC NULLS LAST, d.key
            LIMIT %(limit)s OFFSET %(offset)s
        ) page
        CROSS JOIN LATERAL (
            SELECT * FROM {COLLECTION_DOCUMENTS} d WHERE d.id = page.id OFFSET 0
        ) d
        LEFT JOIN lg_document_light l ON l.id = d.id
    )"""
    page = list(store.query(f"SELECT {items} AS items", bind))[0]
    if not facets:
        return {"items": page, "total": None, "facets": None}
    # The counts are the same on every page and for every visitor: kept per data version
    # under the filters alone (on the full graph they read 650,000 documents).
    counted = without_page(bind)
    facet_filters = FacetFilters(own=own)
    row = cached_rows(
        store,
        f"""
        WITH base AS (
            SELECT d.kind, d.labels, {_CHAMBER_OF} AS chamber
            FROM {COLLECTION_DOCUMENTS} d
            {where(shared)}
        )
        SELECT
            (SELECT count(*)::int FROM base d {facet_filters.where()}) AS total,
            {facet("d.kind", "base d", facet_filters.where("kind"))} AS kind,
            {facet("d.chamber", "base d", facet_filters.where("chamber"))} AS chamber
        """,
        counted,
        tables=(COLLECTION_DOCUMENTS,),
    )[0]
    return {
        "items": page,
        "total": row["total"],
        "facets": {"kind": row["kind"], "chamber": row["chamber"]},
    }


# The documents an amended amendment or motion replaces, and those that replace it: ``REVISES``
# with the rule ``vervanging`` (``Zaak.VervangenVanuit``, ``semantic tk-dossier-relations``),
# each other document with its number (``sequence``) from ``lg_document_light``, never its props.
_REPLACEMENTS_SQL = f"""
SELECT 'replaces' AS side, e.from_id AS paper, e.to_id AS other,
       lg_num(l.props -> 'sequence') AS sequence
FROM edges e LEFT JOIN lg_document_light l ON l.id = e.to_id
WHERE e.from_id = ANY(%(ids)s::text[]) AND e.relation = %(revises)s
  AND e.to_collection = 'documents' AND e.doc -> 'meta' ->> 'rule' = '{RULE_REPLACEMENT}'
UNION ALL
SELECT 'replaced_by', e.to_id, e.from_id, lg_num(l.props -> 'sequence')
FROM edges e LEFT JOIN lg_document_light l ON l.id = e.from_id
WHERE e.to_id = ANY(%(ids)s::text[]) AND e.relation = %(revises)s
  AND e.from_collection = 'documents' AND e.doc -> 'meta' ->> 'rule' = '{RULE_REPLACEMENT}'
ORDER BY 1, 2, 4 NULLS LAST, 3
"""


def get_replacements(
    store: GraphStore, document_ids: list[str]
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Per document of *document_ids* that has one: ``replaces`` (the documents it replaces, "ter
    vervanging van nr. 8") and ``replaced_by`` (the documents that replace it), each
    ``{id, key, sequence}``, by number."""
    found: dict[str, dict[str, list[dict[str, Any]]]] = {}
    if not document_ids:
        return found
    for row in store.query(
        _REPLACEMENTS_SQL, {"ids": document_ids, "revises": RELATION_REVISES}
    ):
        sides = found.setdefault(row["paper"], {"replaces": [], "replaced_by": []})
        sequence = row["sequence"]
        sides[row["side"]].append(
            {
                "id": row["other"],
                "key": key_of(row["other"]),
                "sequence": int(sequence) if sequence is not None else None,
            }
        )
    return found
