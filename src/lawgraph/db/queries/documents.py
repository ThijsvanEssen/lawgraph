"""Queries behind the document endpoints."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
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
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from lawgraph.db.queries._helpers import chamber_sql
from lawgraph.db.version_cache import cached_rows


def get_document(store: GraphStore, key: str) -> dict[str, Any] | None:
    """One document by key (keys are lowercased at ingest)."""
    return store.get_document(COLLECTION_DOCUMENTS, key.lower())


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
    chambers write (an Eerste Kamer paper names its dossier in ``dossier_number``, a
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
    (the same ``bwb_id`` and ``stam_id``), each with the sections in ``meta.sections``. A
    section that several of those edges name is one row, with the highest confidence.
    Unsorted; an unknown article has none.
    """
    article = store.get_document(
        COLLECTION_ARTICLES, make_node_key(bwb_id, article_number)
    )
    if article is None:
        return []
    props = article.get("props") or {}
    bind: dict[str, Any] = {
        "document_id": document_id,
        "explains": RELATION_EXPLAINS,
        "article_id": article["_id"],
    }
    targets = "e.to_id = %(article_id)s"
    if props.get("stam_id"):
        # an article without a bwb_id matches the versions without one (null == null)
        same_law = "v.bwb_id = %(bwb_id)s"
        if props.get("bwb_id") is None:
            same_law = "v.bwb_id IS NULL"
        targets = f"""({targets} OR e.to_id IN (
            SELECT v.id FROM {COLLECTION_ARTICLE_VERSIONS} v
            WHERE {same_law} AND v.stam_id = %(stam_id)s
        ))"""
        bind.update(bwb_id=props.get("bwb_id"), stam_id=props["stam_id"])
    # Of equally confident sections the first edge's is kept.
    edges = store.query(
        f"""
        SELECT e.doc -> 'meta' -> 'sections'
        FROM {COLLECTION_EDGES} e
        WHERE e.from_id = %(document_id)s AND e.relation = %(explains)s
          AND {targets}
          AND json_typeof(e.doc -> 'meta' -> 'sections') = 'array'
        ORDER BY e.key
        """,
        bind,
    )
    best: dict[str, dict[str, Any]] = {}
    for sections in edges:
        for section in sections:
            known = best.get(section["section_anchor"])
            if known is None or section["confidence"] > known["confidence"]:
                best[section["section_anchor"]] = section
    return list(best.values())


# The chambers a paper can be of: its label (``TK``; ``EK`` with ``EersteKamer``).
_CHAMBERS = ("TK", "EK")
_CHAMBER_OF = chamber_sql("d")

# ``props.dossier_numbers OR []``: the value when AQL holds it true, else [].
_NUMBERS = "d.props -> 'dossier_numbers'"
_DOSSIER_NUMBERS = (
    f"CASE WHEN lg_truthy({_NUMBERS}) THEN {_NUMBERS} ELSE '[]'::json END"
)


def _not_null(*values: str) -> str:
    """``NOT_NULL(a, b, ...)`` of json values: the first that is neither missing nor a
    json null."""
    cases = ", ".join(
        f"CASE WHEN json_typeof({v}) <> 'null' THEN {v} END" for v in values
    )
    return f"coalesce({cases})"


# What the list shows of a paper, in the order of the answer.
_ITEM = f"""json_build_object(
        'id', d.id,
        'key', d.key,
        'chamber', {_CHAMBER_OF},
        'kind', d.props -> 'kind',
        'dossier_number', d.props -> 'dossier_number',
        'dossier_suffix', d.props -> 'dossier_suffix',
        'dossier_numbers', {_DOSSIER_NUMBERS},
        'sequence', d.props -> 'sequence',
        'number', d.props -> 'number',
        'date', d.props -> 'date',
        'title', {_not_null("d.props -> 'title'", "d.props -> 'display_name'")},
        'session_year', d.props -> 'session_year',
        'actors', d.props -> 'actors',
        'dictum', d.props -> 'dictum'
    )"""


def _facet(value: str, where: str) -> str:
    """The count per *value* of the papers of ``base`` under *where*, the largest first;
    the value settles equal counts."""
    return f"""(
        SELECT coalesce(json_agg(json_build_object('value', f.value, 'count', f.count)
                                 ORDER BY f.count DESC, f.value NULLS FIRST), '[]'::json)
        FROM (
            SELECT {value} AS value, count(*)::int AS count
            FROM base d
            WHERE {where}
            GROUP BY 1
        ) f
    )"""


def list_documents(
    store: GraphStore,
    *,
    chambers: tuple[str, ...] = _CHAMBERS,
    kinds: tuple[str, ...] | None = None,
    dossier: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
    facets: bool = True,
) -> dict[str, Any]:
    """The papers of the chambers, newest first: ``{total, items, facets}``.

    *dossier* is a dossier label (``36791``, ``37020-XV``): the papers ``PART_OF`` it
    (its own and those of its cases). ``facets`` counts per ``kind`` (under the other
    filters) and per ``chamber`` (under the other filters); ``facets=False`` gives
    ``null`` for ``total`` and ``facets``. One statement either way.
    """
    bind: dict[str, Any] = {
        "chambers": list(chambers),
        "all_chambers": list(_CHAMBERS),
        "from": date_from or "0",
        "to": date_to or "9",
        "limit": limit,
        "offset": offset,
    }
    # always a range on the date: the index on it then reads a page newest first (a paper
    # without a date is not listed)
    shared = [
        "d.date >= %(from)s AND d.date <= %(to)s",
        "d.labels && %(all_chambers)s::text[]",
    ]
    if dossier:
        shared.append("d.dossier_numbers @> ARRAY[%(dossier)s::text]")
        bind["dossier"] = dossier
    by_chamber = "d.labels && %(chambers)s::text[]"
    by_kind = "TRUE"
    if kinds:
        by_kind = "d.kind = ANY(%(kinds)s::text[])"
        bind["kinds"] = list(kinds)
    where = " AND ".join(f"({c})" for c in shared)
    # The page is chosen by id first: an item is built (and the props read) only for the
    # papers on it, not for every paper a deep offset skips.
    items = f"""(
        SELECT coalesce(json_agg({_ITEM} ORDER BY d.date DESC NULLS LAST, d.key),
                        '[]'::json)
        FROM (
            SELECT d.id
            FROM {COLLECTION_DOCUMENTS} d
            WHERE {where} AND {by_chamber} AND {by_kind}
            ORDER BY d.date DESC NULLS LAST, d.key
            LIMIT %(limit)s OFFSET %(offset)s
        ) page
        JOIN {COLLECTION_DOCUMENTS} d ON d.id = page.id
    )"""
    page = list(store.query(f"SELECT {items} AS items", bind))[0]
    if not facets:
        return {"items": page, "total": None, "facets": None}
    # The counts are the same on every page and for every visitor: kept per data version
    # under the filters alone (on the full graph they read 650,000 papers).
    counted = {k: v for k, v in bind.items() if k not in ("limit", "offset")}
    row = cached_rows(
        store,
        f"""
        WITH base AS (
            SELECT d.kind, d.labels, {_CHAMBER_OF} AS chamber
            FROM {COLLECTION_DOCUMENTS} d
            WHERE {where}
        )
        SELECT
            (SELECT count(*)::int FROM base d WHERE {by_chamber} AND {by_kind}) AS total,
            {_facet("d.kind", by_chamber)} AS kind,
            {_facet("d.chamber", by_kind)} AS chamber
        """,
        counted,
        tables=(COLLECTION_DOCUMENTS,),
    )[0]
    return {
        "items": page,
        "total": row["total"],
        "facets": {"kind": row["kind"], "chamber": row["chamber"]},
    }


# The papers an amended amendment or motion replaces, and those that replace it: ``REVISES``
# with the rule ``vervanging`` (``Zaak.VervangenVanuit``, ``semantic tk-dossier-relations``),
# each other paper with its number (``sequence``) from ``lg_document_light``, never its props.
_REPLACEMENTS_SQL = """
SELECT 'replaces' AS side, e.from_id AS paper, e.to_id AS other,
       lg_num(l.props -> 'sequence') AS sequence
FROM edges e LEFT JOIN lg_document_light l ON l.id = e.to_id
WHERE e.from_id = ANY(%(ids)s::text[]) AND e.relation = %(revises)s
  AND e.to_collection = 'documents' AND e.doc -> 'meta' ->> 'rule' = 'vervanging'
UNION ALL
SELECT 'replaced_by', e.to_id, e.from_id, lg_num(l.props -> 'sequence')
FROM edges e LEFT JOIN lg_document_light l ON l.id = e.from_id
WHERE e.to_id = ANY(%(ids)s::text[]) AND e.relation = %(revises)s
  AND e.from_collection = 'documents' AND e.doc -> 'meta' ->> 'rule' = 'vervanging'
ORDER BY 1, 2, 4 NULLS LAST, 3
"""


def get_replacements(
    store: GraphStore, document_ids: list[str]
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Per paper of *document_ids* that has one: ``replaces`` (the papers it replaces, "ter
    vervanging van nr. 8") and ``replaced_by`` (the papers that replace it), each
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
                "key": row["other"].split("/", 1)[1],
                "sequence": int(sequence) if sequence is not None else None,
            }
        )
    return found
