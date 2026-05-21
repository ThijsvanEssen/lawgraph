"""Judgment query helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lawgraph.api.queries._helpers import _load_judgment
from lawgraph.config.constants import (
    RELATION_MENTIONS_ARTICLE,
    RELATION_PART_OF_INSTRUMENT,
)
from lawgraph.config.settings import COLLECTION_EDGES
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


JUDGMENT_SORTS = ("date_desc", "date_asc", "citation_count")

_TIER_BY_PREFIX = (
    ("HR", "hoge_raad"),
    ("GH", "gerechtshof"),
    ("RB", "rechtbank"),
    ("CRVB", "bijzonder"),
    ("CBB", "bijzonder"),
    ("RVS", "bijzonder"),
)


def get_judgment_with_relations(store: ArangoStore, ecli: str) -> JudgmentDetailData:
    """Fetch a judgment and its referenced articles in a single AQL pass.

    Previous implementation issued 2N+1 queries (edges list + per-article
    document fetch + per-article instrument lookup). This version collapses
    everything into one query: DOCUMENT() inline lookups and a nested
    FIRST(...) subquery for the PART_OF_INSTRUMENT edge, so ArangoDB resolves
    all joins server-side.
    """
    judgment_doc = _load_judgment(store, ecli)
    if judgment_doc is None:
        raise ValueError("judgment not found")

    aql = f"""
    FOR edge IN {COLLECTION_EDGES}
        FILTER edge._from == @jid AND edge.relation == @mentions
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
                "mentions": RELATION_MENTIONS_ARTICLE,
                "part_of": RELATION_PART_OF_INSTRUMENT,
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
      * ``tier``, ``court_code``, ``date`` read from precomputed props
        (back-filled by ``lawgraph-backfill-judgment-stats``); fall back to
        inline derivation when a doc predates the backfill.
      * ``inbound_citation_count`` is only computed when needed (sort by
        citation count or ``cited_by_min`` filter) — and only for the
        LIMITed page, not the whole base set.
      * ``total`` is exact when filtered, otherwise the collection
        cardinality. The frontend uses ``has_more`` for paging.
    """
    from lawgraph.api.queries.search import build_search_clause, tokenize_search_query

    # Precomputed inbound count lives on ``props.inbound_citation_count``,
    # back-filled and indexed. SORT/FILTER on citation count are served by
    # the persistent index — no per-row edge subquery on the list path.
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
        else "FOR doc IN judgments"
    )

    # Single FOR with SORT + LIMIT against the indexed props — the planner
    # turns this into an IndexNode (no SortNode), so only @limit rows are
    # ever materialised. The "LET base = (…) FOR row IN base SORT …"
    # two-stage shape we used before blocked the index optimisation and
    # forced a full-collection sort.
    # Source derivation from ECLI prefix — covers records where props.source
    # was never backfilled. Applied both in the FILTER (so ?source=echr works)
    # and in the RETURN projection.
    _source_expr = (
        "doc.props.source != null ? doc.props.source"
        " : (STARTS_WITH(_ecli, 'ECLI:NL:') ? 'rechtspraak'"
        "  : (STARTS_WITH(_ecli, 'ECLI:CE:ECHR:') ? 'echr'"
        "   : (STARTS_WITH(_ecli, 'ECLI:EU:') ? 'cjeu' : null)))"
    )

    aql = f"""
    LET items = (
        {from_clause}
            FILTER @court == null OR doc.props.court_code == @court
            FILTER @tier == null OR doc.props.tier == @tier
            LET _ecli = doc.props.ecli != null ? doc.props.ecli : doc._key
            LET _source = {_source_expr}
            FILTER @source == null OR _source == @source
            FILTER @from == null
                OR (doc.props.date_eff != null AND doc.props.date_eff >= @from)
            FILTER @to == null
                OR (doc.props.date_eff != null AND doc.props.date_eff <= @to)
            {cited_filter}
            {sort_clause}
            LIMIT @offset, @limit
            LET props = doc.props
            LET ecli = _ecli
            LET ecli_parts = SPLIT(ecli, ':')
            LET court_code = (
                props.court_code != null ? props.court_code :
                (LENGTH(ecli_parts) >= 3 ? UPPER(ecli_parts[2]) : null)
            )
            LET tier = (
                props.tier != null ? props.tier :
                (court_code == 'HR' ? 'hoge_raad' :
                 (court_code != null AND STARTS_WITH(court_code, 'GH') ? 'gerechtshof' :
                  (court_code != null AND STARTS_WITH(court_code, 'RB') ? 'rechtbank' :
                   (court_code == null ? null : 'bijzonder'))))
            )
            LET judgment_date = (
                props.date_eff != null ? props.date_eff :
                (props.judgment_metadata != null AND props.judgment_metadata.date != null
                    ? props.judgment_metadata.date :
                 (props.meta != null AND props.meta.date != null ? props.meta.date :
                  (props.date != null ? props.date : null)))
            )
            RETURN {{
                _id: doc._id,
                _key: doc._key,
                ecli: ecli,
                display_name: props.display_name,
                summary: props.summary,
                court_code: court_code,
                tier: tier,
                date: judgment_date,
                source: _source,
                inbound_citation_count: props.inbound_citation_count
            }}
    )
    """

    # Total: cheap when unfiltered (collection count); otherwise a separate
    # count-only pass that doesn't materialise rows. We accept the second
    # round-trip because it scans an indexed collection and never builds
    # docs.
    if has_filter:
        count_from_clause = (
            f'FOR doc IN search_judgments SEARCH ANALYZER({search_clause}, "text_en")'
            if use_search
            else "FOR doc IN judgments"
        )
        aql += f"""
    LET total = LENGTH(
        {count_from_clause}
            FILTER @court == null OR doc.props.court_code == @court
            FILTER @tier == null OR doc.props.tier == @tier
            LET _ecli = doc.props.ecli != null ? doc.props.ecli : doc._key
            LET _source = {_source_expr}
            FILTER @source == null OR _source == @source
            FILTER @from == null
                OR (doc.props.date_eff != null AND doc.props.date_eff >= @from)
            FILTER @to == null
                OR (doc.props.date_eff != null AND doc.props.date_eff <= @to)
            {cited_filter}
            RETURN 1
    )
    """
    else:
        aql += "LET total = COLLECTION_COUNT('judgments')\n"

    aql += "RETURN { total: total, items: items }\n"

    rows = list(store.query(aql, bind_vars))
    return rows[0] if rows else {"total": 0, "items": []}


def derive_judgment_tier(court_code: str | None) -> str | None:
    """Map an ECLI court code (e.g. 'HR', 'RBAMS') to a coarse tier label."""
    if not court_code:
        return None
    code = court_code.upper()
    for prefix, tier in _TIER_BY_PREFIX:
        if code.startswith(prefix):
            return tier
    return "bijzonder"
