"""What the block of a concept shows (``core.concept_articles``): its articles, and the
judgments and papers that cite any of them, each counted once however many of the articles
it cites."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_EDGES,
    COLLECTION_JUDGMENTS,
)
from lawgraph.db import GraphStore
from lawgraph.db.queries.cited_by_table import (
    AREA_KEPT,
    TIERS_KEPT,
    YEAR_KEPT,
    cited_by_facets,
    court_kept,
)
from lawgraph.db.queries.judgment_sql import listed_judgment
from lawgraph.db.schema import CITED_BY_TABLE
from lawgraph.db.version_cache import cached

# The newest judgments and papers a block lists; the totals count them all.
CONCEPT_JUDGMENTS = 5
CONCEPT_DOCUMENTS = 2

# The orders of the judgments, as the passages of an article are ordered
# (``CITED_BY_SORTS``): the newest first, or the most cited (a standard judgment) first and
# then the newest.
JUDGMENT_SORTS: dict[str, str] = {
    "date_desc": "max(c.date_eff) DESC NULLS LAST, c.judgment_id",
    "citation_count": (
        "max(c.cited) DESC NULLS LAST, max(c.date_eff) DESC NULLS LAST, c.judgment_id"
    ),
}

# The judgments from the index of the citations (``lg_cited_by``), ``kept`` those under the
# filters (``court``, ``tiers``, ``year``, ``area``; each null for all); the papers from the edges
# between a paper and an article, either way (a memorandum that explains it, a paper that
# names it), as the neighbours of an article are read.
_CITES = f"""cites AS (
    SELECT c.article_id, c.judgment_id, c.date_eff, c.cited, c.tier, c.areas,
           substr(c.date_eff, 1, 4) AS year
    FROM {CITED_BY_TABLE} c
    WHERE c.article_id = ANY(%(ids)s) AND {court_kept("c")}
),
kept AS (
    SELECT h.* FROM cites h WHERE {TIERS_KEPT} AND {YEAR_KEPT} AND {AREA_KEPT}
)"""
_DOCUMENT_EDGES = f"""papers AS (
    SELECT e.from_id AS document_id, e.to_id AS article_id
    FROM {COLLECTION_EDGES} e
    WHERE e.to_id = ANY(%(ids)s) AND e.from_collection = '{COLLECTION_DOCUMENTS}'
    UNION
    SELECT e.to_id, e.from_id
    FROM {COLLECTION_EDGES} e
    WHERE e.from_id = ANY(%(ids)s) AND e.to_collection = '{COLLECTION_DOCUMENTS}'
)"""


def _latest(sort: str, limit: str = "limit") -> str:
    """SQL: the CTE ``latest``, the page of the judgments of ``kept``, in *sort*, each with
    the articles it cites."""
    return f"""latest AS (
    SELECT c.judgment_id, array_agg(DISTINCT c.article_id ORDER BY c.article_id) AS article_ids,
           row_number() OVER (ORDER BY {JUDGMENT_SORTS[sort]}) AS pos
    FROM kept c
    GROUP BY c.judgment_id
    ORDER BY pos NULLS LAST
    LIMIT %({limit})s OFFSET %(offset)s
)"""


# The papers of ``papers`` the documents hold, each once with the articles it is joined to,
# of the year ``%(year)s`` (of its date; null: any).
_DOCUMENTS_KEPT = f"""documents_kept AS (
    SELECT h.* FROM (
        SELECT d.id, d.key, d.kind, d.date, d.source, d.labels,
               d.props -> 'title' AS title,
               json_build_object(
                   'dossier_number', d.props -> 'dossier_number',
                   'dossier_suffix', d.props -> 'dossier_suffix',
                   'sequence', d.props -> 'sequence') AS paper,
               p.article_ids, substr(d.date, 1, 4) AS year
        FROM (
            SELECT document_id, array_agg(DISTINCT article_id ORDER BY article_id) AS article_ids
            FROM papers GROUP BY document_id
        ) p
        JOIN {COLLECTION_DOCUMENTS} d ON d.id = p.document_id
    ) h
    WHERE {YEAR_KEPT}
)"""


def _document_rows(limit: str = "limit") -> str:
    """SQL: the CTE ``paper_rows``, the page of ``documents_kept``, newest first."""
    return f"""paper_rows AS (
    SELECT * FROM documents_kept
    ORDER BY date DESC NULLS LAST, id
    LIMIT %({limit})s OFFSET %(offset)s
)"""


# The page of judgments as a json array of ``{judgment, article_ids}``, in the order of ``pos``.
_JUDGMENT_ROWS = f"""(
        SELECT coalesce(json_agg(json_build_object(
            'judgment', {
    listed_judgment(
        "j",
        "jl",
        "'inbound_citation_count', j.pj_inbound_citation_count",
        "'subjects', j.subjects",
    )
},
            'article_ids', l.article_ids
        ) ORDER BY l.pos NULLS LAST), '[]'::json)
        FROM latest l
        JOIN {COLLECTION_JUDGMENTS} j ON j.id = l.judgment_id
        LEFT JOIN lg_judgment_light jl ON jl.id = j.id
    )"""

# The page of papers as a json array, in the order of ``paper_rows``.
_DOCUMENT_ROWS = """(
        SELECT coalesce(json_agg(json_build_object(
            'document_id', r.id, 'key', r.key, 'kind', r.kind, 'title', r.title,
            'date', r.date, 'source', r.source, 'labels', r.labels, 'paper', r.paper,
            'article_ids', r.article_ids
        ) ORDER BY r.date DESC NULLS LAST, r.id), '[]'::json)
        FROM paper_rows r
    )"""

_TOTAL_JUDGMENTS = "(SELECT count(DISTINCT judgment_id)::int FROM kept)"
_TOTAL_DOCUMENTS = "(SELECT count(*)::int FROM documents_kept)"

_CONCEPT_SQL = f"""
WITH {_CITES}, {_latest("date_desc", "judgments")}, {_DOCUMENT_EDGES}, {_DOCUMENTS_KEPT},
     {_document_rows("documents")}
SELECT
    (
        SELECT coalesce(json_agg(json_build_object(
            'id', a.id, 'key', a.key, 'props', a.props)), '[]'::json)
        FROM {COLLECTION_ARTICLES} a
        WHERE a.id = ANY(%(ids)s)
    ) AS articles,
    (
        SELECT coalesce(json_object_agg(article_id, n), '{{}}'::json)
        FROM (
            SELECT article_id, count(DISTINCT judgment_id)::int AS n
            FROM cites GROUP BY article_id
        ) x
    ) AS judgment_counts,
    {_TOTAL_JUDGMENTS} AS judgment_total,
    {_JUDGMENT_ROWS} AS judgments,
    {_TOTAL_DOCUMENTS} AS document_total,
    {_DOCUMENT_ROWS} AS documents
"""

_JUDGMENT_PAGE_SQL = {
    sort: f"""
WITH {_CITES}, {_latest(sort)}
SELECT {_TOTAL_JUDGMENTS} AS total, {cited_by_facets("cites", "judgment_id")} AS facets,
       {_JUDGMENT_ROWS} AS items
"""
    for sort in JUDGMENT_SORTS
}

_DOCUMENT_PAGE_SQL = f"""
WITH {_DOCUMENT_EDGES}, {_DOCUMENTS_KEPT}, {_document_rows()}
SELECT {_TOTAL_DOCUMENTS} AS total, {_DOCUMENT_ROWS} AS items
"""

_TABLES = (
    COLLECTION_ARTICLES,
    COLLECTION_EDGES,
    COLLECTION_JUDGMENTS,
    COLLECTION_DOCUMENTS,
)


def concept_overview(store: GraphStore, article_ids: tuple[str, ...]) -> dict[str, Any]:
    """Of the articles *article_ids* (the articles of one concept): their nodes
    (``articles``, an id that is not there left out), per article the judgments that cite
    it (``judgment_counts``), the judgments that cite any (``judgment_total``) and the
    newest ``CONCEPT_JUDGMENTS`` of them with the articles each cites (``judgments``), and
    the same of the papers an edge joins to any of them (``document_total``,
    ``documents``). Kept per data version of the tables it reads."""
    return cached(
        store,
        ("concept overview", article_ids),
        lambda: _row(
            store,
            _CONCEPT_SQL,
            article_ids,
            judgments=CONCEPT_JUDGMENTS,
            documents=CONCEPT_DOCUMENTS,
            offset=0,
        ),
        tables=_TABLES,
    )


# The filters of the lists, none: every judgment and paper.
_NO_FILTERS: dict[str, Any] = {"court": None, "tiers": None, "year": None, "area": None}


def concept_judgments(
    store: GraphStore,
    article_ids: tuple[str, ...],
    *,
    limit: int,
    offset: int,
    sort: str,
    court: str | None = None,
    tiers: tuple[str, ...] = (),
    year: str | None = None,
    area: str | None = None,
) -> dict[str, Any]:
    """A page of the judgments that cite any of *article_ids*, each once, of the ECLI
    *court* code, of any of the *tiers*, of the *year* (of its date) and of the main *area*
    of law (the part of a subject of the source before its first ';'), each empty for all,
    in *sort* (``JUDGMENT_SORTS``): ``total`` (``judgment_total`` of the overview without
    filters), ``facets`` (per ``year``, ``tier`` and ``subject_area`` the judgments, each
    under the other filters, as the passages of an article count them) and ``items``,
    ``{judgment, article_ids}`` as ``judgments`` of the overview."""
    return _row(
        store,
        _JUDGMENT_PAGE_SQL[sort],
        article_ids,
        limit=limit,
        offset=offset,
        court=court.upper() if court else None,
        tiers=list(dict.fromkeys(tiers)) or None,
        year=year,
        area=area,
    )


def concept_documents(
    store: GraphStore,
    article_ids: tuple[str, ...],
    *,
    limit: int,
    offset: int,
    year: str | None = None,
) -> dict[str, Any]:
    """A page of the papers an edge joins to any of *article_ids*, each once, newest first,
    of the *year* (of their date) alone when given: ``total`` (``document_total`` of the
    overview without it) and ``items`` as ``documents`` of the overview."""
    return _row(
        store,
        _DOCUMENT_PAGE_SQL,
        article_ids,
        limit=limit,
        offset=offset,
        year=year,
    )


def _row(
    store: GraphStore, sql: str, article_ids: tuple[str, ...], **params: object
) -> dict[str, Any]:
    """The one row of *sql* for *article_ids*, a filter not in *params* null."""
    bind = {**_NO_FILTERS, **params, "ids": list(article_ids)}
    return dict(next(iter(store.query(sql, bind))))
