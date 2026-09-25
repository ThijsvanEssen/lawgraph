"""Judgment query helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_EDGES,
    COLLECTION_JUDGMENTS,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    TEXT_ANALYZER,
)
from lawgraph.db import ArangoStore
from lawgraph.db.queries._helpers import _load_judgment


@dataclass
class JudgmentArticleRelation:
    article: dict[str, Any]
    instrument: dict[str, Any] | None
    confidence: float | None = None
    # ``meta`` of the REFERS_TO edge: ``mentions`` and ``mention_count`` (core.mentions)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class JudgmentDetailData:
    judgment: dict[str, Any]
    articles: list[JudgmentArticleRelation]
    cited_judgments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # the other judgments of its series (``props.series_id``), as slim documents
    series: list[dict[str, Any]] = field(default_factory=list)


def get_judgment_with_relations(store: ArangoStore, ecli: str) -> JudgmentDetailData:
    """Fetch a judgment and the articles it refers to in a single AQL pass.

    DOCUMENT() inline lookups and a nested FIRST(...) subquery for the PART_OF
    edge let ArangoDB resolve every join server-side.
    """
    judgment_doc = _load_judgment(store, ecli)
    if judgment_doc is None:
        raise ValueError("judgment not found")

    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._from == @jid AND edge.relation == @refers_to
        FILTER STARTS_WITH(edge._to, '{COLLECTION_ARTICLES}/')
        LET article = DOCUMENT(edge._to)
        FILTER article != null
        LET instrument = FIRST(
            FOR ie IN {COLLECTION_EDGES}
                FILTER ie._from == article._id AND ie.relation == @part_of
                LIMIT 1
                RETURN DOCUMENT(ie._to)
        )
        RETURN {{
            article: article,
            instrument: instrument,
            confidence: edge.confidence,
            meta: edge.meta
        }}
    """
    rows = list(
        store.query(
            aql,
            {
                "jid": judgment_doc["_id"],
                "refers_to": RELATION_REFERS_TO,
                "part_of": RELATION_PART_OF,
            },
        )
    )
    article_relations = [
        JudgmentArticleRelation(
            article=r["article"],
            instrument=r.get("instrument"),
            confidence=r.get("confidence"),
            meta=r.get("meta") or {},
        )
        for r in rows
    ]

    metadata = {"article_count": len(article_relations)}
    series_id = (judgment_doc.get("props") or {}).get("series_id")
    return JudgmentDetailData(
        judgment=judgment_doc,
        articles=article_relations,
        metadata=metadata,
        series=[
            doc
            for doc in get_series_members(store, series_id)
            if doc["_id"] != judgment_doc["_id"]
        ]
        if series_id
        else [],
    )


def get_series_members(store: ArangoStore, series_id: str) -> list[dict[str, Any]]:
    """The judgments of a series (``semantic rechtspraak-series``), each with its ``_id``,
    ``_key`` and the ``display_name`` and ``ecli`` of its props, in the order of their ECLI
    numbers (one court, one year: a shorter ECLI is a lower number)."""
    aql = f"""
    FOR j IN {COLLECTION_JUDGMENTS}
        FILTER j.props.series_id == @series_id
        SORT LENGTH(j.props.ecli), j.props.ecli
        RETURN {{
            _id: j._id,
            _key: j._key,
            props: KEEP(j.props, "display_name", "ecli")
        }}
    """
    return list(store.query(aql, {"series_id": series_id}))


@dataclass(frozen=True)
class JudgmentFilters:
    """What ``GET /api/judgments`` narrows the judgments to; None is no filter.

    *subject* is one of ``props.subjects`` as the source writes it: ``Strafrecht``,
    ``Bestuursrecht; Belastingrecht``.
    """

    q: str | None = None
    court: str | None = None
    tier: str | None = None
    source: str | None = None
    subject: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    cited_by_min: int | None = None


# The filter a facet leaves out: each facet counts what choosing another value would give.
_TIER_FILTERS = frozenset({"tier"})
_YEAR_FILTERS = frozenset({"from", "to"})


def _judgment_filters(filters: JudgmentFilters, bind: dict[str, Any]) -> dict[str, str]:
    """The FILTER per filter set, on ``doc``; each served by an index on its prop."""
    clauses: dict[str, str] = {}
    if filters.court:
        clauses["court"] = "FILTER doc.props.court_code == @court"
        bind["court"] = filters.court.upper()
    if filters.tier:
        clauses["tier"] = "FILTER doc.props.tier == @tier"
        bind["tier"] = filters.tier
    if filters.source:
        clauses["source"] = "FILTER doc.props.source == @source"
        bind["source"] = filters.source
    if filters.subject:
        clauses["subject"] = "FILTER @subject IN doc.props.subjects[*]"
        bind["subject"] = filters.subject
    if filters.date_from:
        clauses["from"] = (
            "FILTER doc.props.date_eff != null AND doc.props.date_eff >= @from"
        )
        bind["from"] = filters.date_from
    if filters.date_to:
        clauses["to"] = (
            "FILTER doc.props.date_eff != null AND doc.props.date_eff <= @to"
        )
        bind["to"] = filters.date_to
    if filters.cited_by_min is not None:
        clauses["cited_by_min"] = (
            "FILTER doc.props.inbound_citation_count >= @cited_by_min"
        )
        bind["cited_by_min"] = filters.cited_by_min
    return clauses


def get_judgments_list(
    store: ArangoStore,
    filters: JudgmentFilters | None = None,
    *,
    sort: str = "date_desc",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Paginated, filterable list of judgments, with facets.

    Performance strategy mirrors ``get_instruments_list``:
      * Free-text via ``search_judgments`` ArangoSearch view (BM25). Without
        the view, ``CONTAINS(LOWER(props.summary), @q)`` dominates wall time
        because summaries are multi-KB.
      * ``tier``, ``court_code``, ``date_eff``, ``source`` and ``subjects`` are
        read from the props the normalize pipelines write, each indexed.
      * ``total`` is exact when filtered, otherwise the collection
        cardinality. The frontend uses ``has_more`` for paging.
      * ``facets`` counts per ``tier`` (without the tier filter) and per year
        of ``date_eff`` (without ``from`` and ``to``). Unfiltered, each count
        walks one index and reads no judgment (``db/schema.py``).
    """
    from lawgraph.db.queries.search import build_search_clause, tokenize_search_query

    filters = filters or JudgmentFilters()
    tokens = tokenize_search_query(filters.q) if filters.q else []
    search_clause, tok_bind = (
        build_search_clause(tokens, ["display_name", "summary", "ecli"])
        if tokens
        else ("true", {})
    )

    # Single-key SORT so the planner places LIMIT *before* the materialise
    # step. Adding a secondary tiebreak (e.g. ``ecli ASC``) forces a
    # SortNode because the single-field index can't serve both keys.
    # The trade-off — non-deterministic order among rows with identical
    # sort keys — is acceptable for a catalogue list.
    # The inbound count lives on the indexed ``props.inbound_citation_count``,
    # so SORT/FILTER on citation count are served by the persistent index —
    # no per-row edge subquery on the list path.
    sort_clause = {
        "date_desc": "SORT doc.props.date_eff DESC",
        "date_asc": "SORT doc.props.date_eff ASC",
        "citation_count": "SORT doc.props.inbound_citation_count DESC",
    }[sort]

    bind_vars: dict[str, Any] = {"limit": limit, "offset": offset, **tok_bind}
    clauses = _judgment_filters(filters, bind_vars)

    def where(leave_out: frozenset[str] = frozenset()) -> str:
        return "\n            ".join(
            clause for name, clause in clauses.items() if name not in leave_out
        )

    from_clause = (
        f'FOR doc IN search_judgments SEARCH ANALYZER({search_clause}, "{TEXT_ANALYZER}")'
        if tokens
        else f"FOR doc IN {COLLECTION_JUDGMENTS}"
    )
    # Single FOR with SORT + LIMIT against the indexed props — the planner
    # turns this into an IndexNode (no SortNode), so only @limit rows are
    # ever materialised.
    aql = f"""
    LET items = (
        {from_clause}
            {where()}
            {sort_clause}
            LIMIT @offset, @limit
            LET props = doc.props
            RETURN {{
                _id: doc._id,
                _key: doc._key,
                ecli: props.ecli != null ? props.ecli : doc._key,
                display_name: props.display_name,
                summary: props.summary,
                court_code: props.court_code,
                tier: props.tier,
                date: props.date_eff,
                source: props.source,
                subjects: props.subjects,
                inbound_citation_count: props.inbound_citation_count,
                series_id: props.series_id,
                series_size: props.series_size
            }}
    )
    LET by_tier = (
        {from_clause}
            {where(_TIER_FILTERS)}
            COLLECT value = doc.props.tier WITH COUNT INTO count
            SORT count DESC, value
            RETURN {{ value, count }}
    )
    LET by_year = (
        {from_clause}
            {where(_YEAR_FILTERS)}
            COLLECT value = doc.props.date_eff != null
                ? SUBSTRING(doc.props.date_eff, 0, 4) : null
            WITH COUNT INTO count
            SORT value
            RETURN {{ value, count }}
    )
    """

    # Total: cheap when unfiltered (collection count); otherwise a separate
    # count-only pass that never materialises documents.
    if tokens or clauses:
        aql += f"""
    LET total = LENGTH(
        {from_clause}
            {where()}
            RETURN 1
    )
    """
    else:
        aql += f"LET total = COLLECTION_COUNT('{COLLECTION_JUDGMENTS}')\n"

    aql += (
        "RETURN { total: total, items: items, "
        "facets: { tier: by_tier, year: by_year } }\n"
    )

    rows = list(store.query(aql, bind_vars))
    return rows[0] if rows else {"total": 0, "items": [], "facets": {}}
