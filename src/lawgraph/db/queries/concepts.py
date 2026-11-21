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
from lawgraph.db.queries.judgment_sql import listed_judgment
from lawgraph.db.schema import CITED_BY_TABLE
from lawgraph.db.version_cache import cached

# The newest judgments and papers a block lists; the totals count them all.
CONCEPT_JUDGMENTS = 5
CONCEPT_DOCUMENTS = 2

# The judgments from the index of the citations (``lg_cited_by``); the papers from the edges
# between a paper and an article, either way (a memorandum that explains it, a paper that
# names it), as the neighbours of an article are read.
_CONCEPT_SQL = f"""
WITH cites AS (
    SELECT c.article_id, c.judgment_id, c.date_eff
    FROM {CITED_BY_TABLE} c
    WHERE c.article_id = ANY(%(ids)s)
),
latest AS (
    SELECT judgment_id, max(date_eff) AS date_eff,
           array_agg(DISTINCT article_id ORDER BY article_id) AS article_ids
    FROM cites
    GROUP BY judgment_id
    ORDER BY max(date_eff) DESC NULLS LAST, judgment_id
    LIMIT %(judgments)s
),
papers AS (
    SELECT e.from_id AS document_id, e.to_id AS article_id
    FROM {COLLECTION_EDGES} e
    WHERE e.to_id = ANY(%(ids)s) AND e.from_collection = '{COLLECTION_DOCUMENTS}'
    UNION
    SELECT e.to_id, e.from_id
    FROM {COLLECTION_EDGES} e
    WHERE e.from_id = ANY(%(ids)s) AND e.to_collection = '{COLLECTION_DOCUMENTS}'
),
paper_rows AS (
    SELECT d.id, d.key, d.kind, d.date, d.source, d.labels,
           d.props -> 'title' AS title,
           json_build_object(
               'dossier_number', d.props -> 'dossier_number',
               'dossier_suffix', d.props -> 'dossier_suffix',
               'sequence', d.props -> 'sequence') AS paper,
           p.article_ids
    FROM (
        SELECT document_id, array_agg(DISTINCT article_id ORDER BY article_id) AS article_ids
        FROM papers GROUP BY document_id
    ) p
    JOIN {COLLECTION_DOCUMENTS} d ON d.id = p.document_id
    ORDER BY d.date DESC NULLS LAST, d.id
    LIMIT %(documents)s
)
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
    (SELECT count(DISTINCT judgment_id)::int FROM cites) AS judgment_total,
    (
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
        ) ORDER BY l.date_eff DESC NULLS LAST, l.judgment_id), '[]'::json)
        FROM latest l
        JOIN {COLLECTION_JUDGMENTS} j ON j.id = l.judgment_id
        LEFT JOIN lg_judgment_light jl ON jl.id = j.id
    ) AS judgments,
    (SELECT count(DISTINCT document_id)::int FROM papers) AS document_total,
    (
        SELECT coalesce(json_agg(json_build_object(
            'document_id', r.id, 'key', r.key, 'kind', r.kind, 'title', r.title,
            'date', r.date, 'source', r.source, 'labels', r.labels, 'paper', r.paper,
            'article_ids', r.article_ids
        ) ORDER BY r.date DESC NULLS LAST, r.id), '[]'::json)
        FROM paper_rows r
    ) AS documents
"""


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
        lambda: _overview(store, article_ids),
        tables=(
            COLLECTION_ARTICLES,
            COLLECTION_EDGES,
            COLLECTION_JUDGMENTS,
            COLLECTION_DOCUMENTS,
        ),
    )


def _overview(store: GraphStore, article_ids: tuple[str, ...]) -> dict[str, Any]:
    row = next(
        iter(
            store.query(
                _CONCEPT_SQL,
                {
                    "ids": list(article_ids),
                    "judgments": CONCEPT_JUDGMENTS,
                    "documents": CONCEPT_DOCUMENTS,
                },
            )
        )
    )
    return dict(row)
