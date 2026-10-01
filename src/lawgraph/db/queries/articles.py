"""Article query helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    EDGE_STATUS_VOORGESTELD,
    RELATION_AMENDS,
    RELATION_EXPLAINS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_REPEALS,
)
from lawgraph.core.models import make_node_key
from lawgraph.core.qualifiers import Qualifier
from lawgraph.db import GraphStore
from lawgraph.db._rows import edge_doc, node_doc
from lawgraph.db.queries._helpers import (
    _coerce_float,
    _coerce_int,
    _coerce_text,
    _ensure_doc,
    _extract_confidence,
    _extract_qualifier,
    _extract_span,
    _find_instrument_for_article,
    _find_judgments_for_article,
    _resolve_target_from_entry,
    run_together,
)
from lawgraph.db.queries.dossiers import collect_dossier_numbers, get_dossier_titles


@dataclass
class ArticleDetailData:
    article: dict[str, Any]
    instrument: dict[str, Any] | None
    judgments: list[dict[str, Any]]
    metadata: dict[str, Any]


@dataclass
class ArticleHistoryData:
    article: dict[str, Any]
    versions: list[dict[str, Any]]
    dossier_titles: dict[str, str | None]


@dataclass
class ArticleCitationEntry:
    target: dict[str, Any]
    start: int | None
    end: int | None
    text: str | None
    confidence: float | None
    qualifier: Qualifier = field(default_factory=Qualifier)
    reference_kind: str | None = None


def _record_article_citation(
    citations: list[ArticleCitationEntry],
    seen: set[tuple[str, int | None, int | None, str | None]],
    target_doc: dict[str, Any],
    start: int | None,
    end: int | None,
    text: str | None,
    confidence: float | None,
    qualifier: Qualifier | None = None,
    reference_kind: str | None = None,
) -> None:
    target_id = target_doc.get("_id")
    if not target_id:
        return
    key = (target_id, start, end, text)
    if key in seen:
        return
    seen.add(key)
    citations.append(
        ArticleCitationEntry(
            target=target_doc,
            start=start,
            end=end,
            text=text,
            confidence=confidence,
            qualifier=qualifier or Qualifier(),
            reference_kind=reference_kind,
        )
    )


def get_article_with_relations(
    store: GraphStore,
    bwb_id: str,
    article_number: str,
) -> ArticleDetailData:
    """Fetch an article with its parent instrument and the judgments citing it."""
    article_key = make_node_key(bwb_id, article_number)
    article_doc = store.get_document(COLLECTION_ARTICLES, article_key)
    article_doc = _ensure_doc(article_doc)
    if article_doc is None:
        raise ValueError("article not found")

    article_id = article_doc["_id"]
    found = run_together(
        lambda: _find_instrument_for_article(store, article_id),
        lambda: _find_judgments_for_article(store, article_id),
    )
    instrument_doc = cast("dict[str, Any] | None", found[0])
    judgments = cast("list[dict[str, Any]]", found[1])

    metadata = {"judgment_count": len(judgments)}
    return ArticleDetailData(
        article=article_doc,
        instrument=instrument_doc,
        judgments=judgments,
        metadata=metadata,
    )


def _version_identity(
    article: dict[str, Any], bwb_id: str, article_number: str
) -> tuple[str, dict[str, Any]]:
    """The SQL condition on ``v`` (an ArticleVersion) that selects the versions of
    *article*, and its parameters.

    The identity of an article inside its regulation is ``(bwb_id, stam_id)``; an article
    without a ``stam_id`` is matched on ``(bwb_id, article_number)``. Both conditions are
    served by an index on ``article_versions``.
    """
    props = article.get("props") or {}
    bind: dict[str, Any] = {"bwb_id": props.get("bwb_id") or bwb_id.upper()}
    stam_id = props.get("stam_id")
    if stam_id:
        bind["identity"] = stam_id
        return "v.bwb_id = %(bwb_id)s AND v.stam_id = %(identity)s", bind
    bind["identity"] = props.get("article_number") or article_number
    return "v.bwb_id = %(bwb_id)s AND v.article_number = %(identity)s", bind


def get_article_history(
    store: GraphStore,
    bwb_id: str,
    article_number: str,
) -> ArticleHistoryData:
    """All versions of one article identity, oldest first, plus dossier titles.

    The current article is resolved by key (``ValueError`` when unknown). Its
    identity inside the regulation is ``(bwb_id, stam_id)``; an article without a
    ``stam_id`` is matched on ``(bwb_id, article_number)``. Query budget: one for
    the versions and, when the publications name dossiers, one for their titles —
    independent of the number of versions.
    """
    article_key = make_node_key(bwb_id, article_number)
    article = _ensure_doc(store.get_document(COLLECTION_ARTICLES, article_key))
    if article is None:
        raise ValueError("article not found")

    identity, bind = _version_identity(article, bwb_id, article_number)
    rows = store.query(
        f"""
        SELECT v.id, v.key, v.type, v.labels, v.props
        FROM {COLLECTION_ARTICLE_VERSIONS} v
        WHERE {identity}
        ORDER BY v.valid_from NULLS FIRST, v.key
        """,
        bind,
    )
    versions = [node_doc(row) for row in rows]

    publications = [
        (v.get("props") or {}).get(field)
        for v in versions
        for field in ("origin_publication", "commencement_publication")
    ]
    titles = get_dossier_titles(store, collect_dossier_numbers(publications))
    return ArticleHistoryData(article=article, versions=versions, dossier_titles=titles)


def _json_order(value: str) -> str:
    """ORDER BY terms that sort the json *value* as ArangoDB sorts any value: null (or
    missing), then booleans, numbers, strings, arrays and objects."""
    return (
        f"CASE json_typeof({value}) WHEN 'boolean' THEN 1 WHEN 'number' THEN 2"
        f" WHEN 'string' THEN 3 WHEN 'array' THEN 4 WHEN 'object' THEN 5 ELSE 0 END,"
        f" lg_bool({value}), lg_num({value}), lg_str({value})"
    )


def get_article_citations(
    store: GraphStore,
    article_doc: dict[str, Any],
) -> list[ArticleCitationEntry]:
    doc = _ensure_doc(article_doc)
    if not doc:
        return []
    article_id = doc.get("_id")
    if not article_id:
        return []

    citations: list[ArticleCitationEntry] = []
    seen: set[tuple[str, int | None, int | None, str | None]] = set()

    # In text order; the key settles which of two equal spans is kept. An edge to a node
    # that is not there is skipped.
    rows = store.query(
        f"""
        SELECT e.key, e.from_id, e.to_id, e.doc,
               n.id AS node_id, n.key AS node_key, n.type, n.labels, n.props
        FROM {COLLECTION_EDGES} e JOIN nodes n ON n.id = e.to_id
        WHERE e.from_id = %(article_id)s AND e.relation = %(relation)s
        ORDER BY {_json_order("e.doc -> 'meta' -> 'start'")}, e.key
        """,
        {"article_id": article_id, "relation": RELATION_REFERS_TO},
    )
    for row in rows:
        edge = edge_doc(row)
        target_doc = node_doc({**row, "id": row["node_id"], "key": row["node_key"]})
        start, end, text = _extract_span(edge)
        confidence = _extract_confidence(edge)
        qualifier, reference_kind = _extract_qualifier(edge)
        _record_article_citation(
            citations,
            seen,
            target_doc,
            start,
            end,
            text,
            confidence,
            qualifier,
            reference_kind,
        )

    props = doc.get("props") or {}
    raw_citations = props.get("citations")
    if isinstance(raw_citations, list):
        for entry in raw_citations:
            if not isinstance(entry, dict):
                continue
            target = _resolve_target_from_entry(store, entry)
            if not target:
                continue
            start = _coerce_int(entry.get("start"))
            end = _coerce_int(entry.get("end"))
            text = _coerce_text(entry.get("text"))
            confidence = _coerce_float(entry.get("confidence"))
            _record_article_citation(
                citations, seen, target, start, end, text, confidence
            )

    return citations


def _not_null(*values: str) -> str:
    """``NOT_NULL(a, b, ...)`` of json values: the first that is neither missing nor a
    json null."""
    cases = ", ".join(
        f"CASE WHEN json_typeof({v}) <> 'null' THEN {v} END" for v in values
    )
    return f"coalesce({cases})"


# The key of a dossier from its id (``PARSE_IDENTIFIER(id).key``).
_DOSSIER_KEY_FROM = len(COLLECTION_DOSSIERS) + 2

_CHANGES_SQL = f"""
SELECT
    ARRAY(
        SELECT k FROM (
            SELECT substr(e2.to_id, {_DOSSIER_KEY_FROM}) AS k
            FROM {COLLECTION_EDGES} e2
            WHERE e2.from_id = e.from_id
              AND e2.relation = ANY(%(direct)s)
              AND e2.to_collection = '{COLLECTION_DOSSIERS}'
            UNION
            SELECT substr(e3.to_id, {_DOSSIER_KEY_FROM})
            FROM {COLLECTION_EDGES} e2
            JOIN {COLLECTION_EDGES} e3
              ON e3.from_id = e2.to_id AND e3.relation = %(part_of)s
             AND e3.to_collection = '{COLLECTION_DOSSIERS}'
            WHERE e2.from_id = e.from_id
              AND e2.relation = %(part_of)s
              AND e2.to_collection = '{COLLECTION_CASES}'
        ) dossier_keys
        ORDER BY k
    ) AS dossier_keys,
    CASE WHEN s.collection = '{COLLECTION_INSTRUMENTS}'
        THEN s.props -> 'dossier_numbers' END AS numbers,
    {_not_null("s.props -> 'date'", "s.props -> 'date_published'", "s.props -> 'date_signed'")}
        AS date,
    {_not_null("s.props -> 'kind'", "s.props -> 'publication_kind'")} AS kind,
    lower(e.relation) AS change,
    e.doc -> 'status' AS status,
    s.props -> 'display_name' AS summary,
    s.id AS document_id
FROM {COLLECTION_EDGES} e
JOIN nodes s ON s.id = e.from_id
WHERE e.to_id = %(article_id)s AND e.relation = ANY(%(changes)s)
-- The sorts in Python are stable: the edge key and the sorted dossier keys settle ties.
ORDER BY e.key
"""


def get_article_legislative_history(
    store: GraphStore,
    bwb_id: str,
    article_number: str,
    article_id: str | None = None,
) -> list[dict[str, Any]]:
    """The dossiers that introduced, amended or repealed an article, or propose to.

    A change is an ``AMENDS``, ``INTRODUCES`` or ``REPEALS`` edge to the article: from an
    amending publication (enacted, ``canoniek``), whose dossiers are those it is
    ``LEGISLATED_IN`` and those its ``dossier_numbers`` name (a dossier that is not in the
    graph has no ``dossier_id``), or from a bill (``voorgesteld``), whose dossier it is
    ``PART_OF``, directly or through its case. One entry per change and dossier; a change
    without a dossier is none, and what only cites the article (a judgment, another article)
    is no change.

    Each entry: {dossier_id, dossier_number, dossier_title, date, kind, change, status,
    summary, document_id}; proposed changes first, then newest first. The explanatory
    documents are found by ``get_article_explanations``.
    """
    if article_id is None:
        article_id = f"{COLLECTION_ARTICLES}/{make_node_key(bwb_id, article_number)}"

    changes = list(
        store.query(
            _CHANGES_SQL,
            {
                "article_id": article_id,
                "changes": [RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS],
                "direct": [RELATION_PART_OF, RELATION_LEGISLATED_IN],
                "part_of": RELATION_PART_OF,
            },
        )
    )
    # A number names the dossier whose key it makes; one lookup for every dossier.
    for change in changes:
        change["numbers"] = {make_node_key(n): n for n in change["numbers"] or []}
        change["dossier_keys"] += [
            key for key in change["numbers"] if key not in change["dossier_keys"]
        ]
    keys = sorted({k for change in changes for k in change["dossier_keys"]})
    dossiers = (
        {
            row["key"]: row
            for row in store.query(
                f"""
                SELECT key, id, props -> 'label' AS label, props -> 'title' AS title
                FROM {COLLECTION_DOSSIERS}
                WHERE key = ANY(%(keys)s)
                ORDER BY key
                """,
                {"keys": keys},
            )
        }
        if keys
        else {}
    )
    entries = []
    for change in changes:
        numbers = change.pop("numbers")
        for key in change.pop("dossier_keys"):
            dossier = dossiers.get(key)
            entries.append(
                {
                    **change,
                    "dossier_id": dossier["id"] if dossier else None,
                    "dossier_number": dossier["label"] if dossier else numbers[key],
                    "dossier_title": dossier["title"] if dossier else None,
                }
            )
    entries.sort(key=lambda e: e["dossier_number"] or "")
    entries.sort(key=lambda e: e["date"] or "", reverse=True)
    entries.sort(key=lambda e: e["status"] != EDGE_STATUS_VOORGESTELD)
    return entries


# The explanations of an article. ``found``: an EXPLAINS edge from a document to the
# article (rank 1) or one of its versions (rank 0); ``picked``: per document and section
# anchor the edge that says most (a version before the article, the newest version
# first); ``ranked``: the order of the answer, newest document first.
_EXPLANATIONS_SQL = f"""
WITH targets AS (
    SELECT %(article_id)s::text AS id, 1 AS rank, NULL::text AS valid_from
    UNION ALL
    SELECT v.id, 0, v.valid_from
    FROM {COLLECTION_ARTICLE_VERSIONS} v
    WHERE {{identity}}
),
found AS (
    SELECT d.id AS document_id, d.key, d.date, t.rank, t.valid_from,
           t.id AS target_id, e.doc -> 'confidence' AS confidence,
           -- a missing anchor and a json null are one group, as in a COLLECT
           nullif((e.doc -> 'meta' -> 'section_anchor')::jsonb, 'null'::jsonb)
               AS section_anchor
    FROM targets t
    JOIN {COLLECTION_EDGES} e
      ON e.to_id = t.id AND e.relation = %(explains)s
     AND e.from_collection = '{COLLECTION_DOCUMENTS}'
    JOIN {COLLECTION_DOCUMENTS} d ON d.id = e.from_id
),
picked AS (
    SELECT DISTINCT ON (document_id, section_anchor) *
    FROM found
    ORDER BY document_id, section_anchor, rank,
             valid_from DESC NULLS LAST, target_id
),
ranked AS (
    SELECT p.*, row_number() OVER (
        ORDER BY p.date DESC NULLS LAST, p.key NULLS FIRST,
                 lg_str(p.section_anchor::json) NULLS FIRST
    ) AS n
    FROM picked p
)
SELECT
    (SELECT count(*)::int FROM picked) AS total,
    (
        SELECT coalesce(json_agg(json_build_object(
            'document_id', r.document_id,
            'key', r.key,
            -- columns where there are, so the props (the whole text) are read once
            'kind', to_json(d.kind),
            'title', d.props -> 'title',
            'date', to_json(d.date),
            'source', to_json(d.source),
            'labels', to_json(d.labels),
            'dossier_number', (
                SELECT ds.label
                FROM {COLLECTION_EDGES} e
                JOIN {COLLECTION_DOSSIERS} ds ON ds.id = e.to_id
                WHERE e.from_id = r.document_id AND e.relation = %(part_of)s
                  AND e.to_collection = '{COLLECTION_DOSSIERS}'
                  AND ds.label IS NOT NULL
                ORDER BY ds.label
                LIMIT 1
            ),
            'target_id', r.target_id,
            'confidence', r.confidence,
            'section_anchor', r.section_anchor
        ) ORDER BY r.n), '[]'::json)
        FROM ranked r JOIN {COLLECTION_DOCUMENTS} d ON d.id = r.document_id
        WHERE r.n > %(offset)s AND r.n <= %(offset)s + %(limit)s
    ) AS items
"""


def get_article_explanations(
    store: GraphStore,
    bwb_id: str,
    article_number: str,
    *,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """A page of the documents that EXPLAIN an article, and how many there are in all.

    An explanation is an EXPLAINS edge whose target is the article or one of its versions
    (found as ``get_article_history`` finds them); the edge of an explanatory memorandum
    usually points at a version. An edge to the article's law is no explanation of the
    article: it is written for a law that changed no articles, and says nothing about this
    one. Per document one edge is kept, the one that says most (a version before the
    article, the newest version first); edges that carry a ``meta.section_anchor`` are kept
    apart from those that do not.

    An unknown article has no explanations: the answer is empty. Query budget: one
    lookup of the article and one query, driven by the ``(to_id, relation)`` index of
    the edges, that reads the documents of the page only.
    """
    article = _ensure_doc(
        store.get_document(COLLECTION_ARTICLES, make_node_key(bwb_id, article_number))
    )
    if article is None:
        return {"total": 0, "items": []}

    identity, bind = _version_identity(article, bwb_id, article_number)
    bind.update(
        {
            "article_id": article["_id"],
            "part_of": RELATION_PART_OF,
            "explains": RELATION_EXPLAINS,
            "limit": limit,
            "offset": offset,
        }
    )
    rows = list(store.query(_EXPLANATIONS_SQL.replace("{identity}", identity), bind))
    return rows[0] if rows else {"total": 0, "items": []}


@dataclass(frozen=True)
class CitedBy:
    """A page of the passages that cite an article: ``{judgment, mention}`` rows, the
    passages that match the filters and the judgments they are in."""

    rows: list[dict[str, Any]]
    total: int
    judgment_total: int


# ``hits``: per edge of a judgment to the article, one row per mention that passes the
# filters, with only what sorts it; ``ranked``: their order, newest first; the mentions of
# the page are read whole after the cut.
_CITED_BY_SQL = f"""
WITH hits AS (
    SELECT e.key AS edge, m.position - 1 AS position, j.date_eff AS date, j.ecli
    FROM {COLLECTION_EDGES} e
    JOIN {COLLECTION_JUDGMENTS} j ON j.id = e.from_id
    CROSS JOIN LATERAL json_array_elements(
        CASE WHEN json_typeof(e.doc -> 'meta' -> 'mentions') = 'array'
            THEN e.doc -> 'meta' -> 'mentions' END
    ) WITH ORDINALITY AS m(mention, position)
    WHERE e.to_id = %(article_id)s AND e.relation = %(relation)s
      AND e.from_collection = '{COLLECTION_JUDGMENTS}'
      AND (%(court)s::text IS NULL OR j.court_code = %(court)s::text)
      AND (%(tier)s::text IS NULL OR j.tier = %(tier)s::text)
      AND (
          %(lid)s::text IS NULL
          OR %(lid)s::text = ANY(lg_text_array(m.mention -> 'leden'))
      )
),
ranked AS (
    SELECT h.*, row_number() OVER (
        ORDER BY h.date DESC NULLS LAST, h.ecli NULLS FIRST, h.edge, h.position
    ) AS n
    FROM hits h
)
SELECT
    (SELECT count(*)::int FROM hits) AS total,
    -- one edge per judgment and article
    (SELECT count(DISTINCT edge)::int FROM hits) AS judgment_total,
    (
        SELECT coalesce(json_agg(json_build_object(
            'judgment', json_build_object(
                '_id', j.id,
                '_key', j.key,
                'props', json_build_object(
                    'ecli', j.pj_ecli,
                    'display_name', j.pj_display_name,
                    'court_code', j.pj_court_code,
                    'tier', j.pj_tier,
                    'court_kind', j.pj_court_kind,
                    'date_eff', j.pj_date_eff
                )
            ),
            'mention', (e.doc -> 'meta' -> 'mentions') -> r.position::int
        ) ORDER BY r.n), '[]'::json)
        FROM ranked r
        JOIN {COLLECTION_EDGES} e ON e.key = r.edge
        JOIN {COLLECTION_JUDGMENTS} j ON j.id = e.from_id
        WHERE r.n > %(offset)s AND r.n <= %(offset)s + %(limit)s
    ) AS items
"""


def get_article_cited_by(
    store: GraphStore,
    article_id: str,
    *,
    court: str | None = None,
    tier: str | None = None,
    lid: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> CitedBy:
    """The passages of judgments that cite an article: one row per mention, newest first.

    ``total`` counts every mention that passes the filters, whatever the page, and
    ``judgment_total`` the judgments they are in. Filters: the ``court`` (ECLI court code) and
    ``tier`` of the judgment, and a ``lid`` number that the mention names.

    A much cited article has thousands of judgments (Sr 287, Awb 6:2) and a judgment is
    its text and its paragraphs. The first pass reads the edges of the article by
    ``(to_id, relation)`` and keeps only what filters and sorts a mention (the edge, its
    position, the date and the ECLI, from the generated columns of the judgment); the
    mentions of the page, with their snippets, are read after the cut, for ``limit`` rows
    and not for all of them.
    """
    bind = {
        "article_id": article_id,
        "relation": RELATION_REFERS_TO,
        "court": court.upper() if court else None,
        "tier": tier,
        "lid": lid.lower() if lid else None,
        "limit": limit,
        "offset": offset,
    }
    answer = next(iter(store.query(_CITED_BY_SQL, bind)), None) or {}
    return CitedBy(
        rows=list(answer.get("items") or []),
        total=int(answer.get("total") or 0),
        judgment_total=int(answer.get("judgment_total") or 0),
    )
