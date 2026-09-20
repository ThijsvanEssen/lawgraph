"""Judgment query helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lawgraph.api.queries._helpers import _load_judgment
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_EDGES,
    COLLECTION_JUDGMENTS,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
)
from lawgraph.db import ArangoStore


@dataclass
class JudgmentArticleRelation:
    article: dict[str, Any]
    instrument: dict[str, Any] | None


@dataclass
class JudgmentDetailData:
    judgment: dict[str, Any]
    articles: list[JudgmentArticleRelation]
    cited_judgments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


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
        RETURN {{ article: article, instrument: instrument }}
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
        JudgmentArticleRelation(article=r["article"], instrument=r.get("instrument"))
        for r in rows
    ]

    metadata = {"article_count": len(article_relations)}
    return JudgmentDetailData(
        judgment=judgment_doc, articles=article_relations, metadata=metadata
    )


def get_judgments_list(
    store: ArangoStore,
    *,
    q: str | None = None,
    court: str | None = None,
    tier: str | None = None,
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    cited_by_min: int | None = None,
    sort: str = "date_desc",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Paginated, filterable list of judgments.

    Performance strategy mirrors ``get_instruments_list``:
      * Free-text via ``search_judgments`` ArangoSearch view (BM25). Without
        the view, ``CONTAINS(LOWER(props.summary), @q)`` dominates wall time
        because summaries are multi-KB.
      * ``tier``, ``court_code``, ``date_eff`` and ``source`` are read from
        the props the normalize pipelines write.
      * ``inbound_citation_count`` is only computed when needed (sort by
        citation count or ``cited_by_min`` filter) — and only for the
        LIMITed page, not the whole base set.
      * ``total`` is exact when filtered, otherwise the collection
        cardinality. The frontend uses ``has_more`` for paging.
    """
    from lawgraph.api.queries.search import build_search_clause, tokenize_search_query

    # The inbound count lives on the indexed ``props.inbound_citation_count``,
    # so SORT/FILTER on citation count are served by the persistent index —
    # no per-row edge subquery on the list path.
    tokens = tokenize_search_query(q) if q else []
    use_search = bool(tokens)
    has_filter = bool(
        use_search
        or court
        or tier
        or source
        or date_from
        or date_to
        or cited_by_min is not None
    )
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
    sort_clause = {
        "date_desc": "SORT doc.props.date_eff DESC",
        "date_asc": "SORT doc.props.date_eff ASC",
        "citation_count": "SORT doc.props.inbound_citation_count DESC",
    }[sort]

    cited_filter = (
        "FILTER doc.props.inbound_citation_count >= @cited_by_min"
        if cited_by_min is not None
        else ""
    )

    bind_vars: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "court": court.upper() if court else None,
        "tier": tier,
        "source": source,
        "from": date_from,
        "to": date_to,
        **tok_bind,
    }
    if cited_by_min is not None:
        bind_vars["cited_by_min"] = cited_by_min

    from_clause = (
        f'FOR doc IN search_judgments SEARCH ANALYZER({search_clause}, "text_en")'
        if use_search
        else f"FOR doc IN {COLLECTION_JUDGMENTS}"
    )
    # Single FOR with SORT + LIMIT against the indexed props — the planner
    # turns this into an IndexNode (no SortNode), so only @limit rows are
    # ever materialised.
    filters = f"""
            FILTER @court == null OR doc.props.court_code == @court
            FILTER @tier == null OR doc.props.tier == @tier
            FILTER @source == null OR doc.props.source == @source
            FILTER @from == null
                OR (doc.props.date_eff != null AND doc.props.date_eff >= @from)
            FILTER @to == null
                OR (doc.props.date_eff != null AND doc.props.date_eff <= @to)
            {cited_filter}
    """

    aql = f"""
    LET items = (
        {from_clause}
            {filters}
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
                inbound_citation_count: props.inbound_citation_count
            }}
    )
    """

    # Total: cheap when unfiltered (collection count); otherwise a separate
    # count-only pass that never materialises documents.
    if has_filter:
        aql += f"""
    LET total = LENGTH(
        {from_clause}
            {filters}
            RETURN 1
    )
    """
    else:
        aql += f"LET total = COLLECTION_COUNT('{COLLECTION_JUDGMENTS}')\n"

    aql += "RETURN { total: total, items: items }\n"

    rows = list(store.query(aql, bind_vars))
    return rows[0] if rows else {"total": 0, "items": []}
