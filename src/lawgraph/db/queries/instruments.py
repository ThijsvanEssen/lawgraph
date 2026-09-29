"""Instrument query helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_REFERS_TO,
    RELATION_REPEALS,
    TEXT_ANALYZER,
)
from lawgraph.core.bwb_xml import KIND_PUBLICATION
from lawgraph.db import ArangoStore
from lawgraph.db.queries.dossiers import collect_dossier_numbers, get_dossier_titles
from lawgraph.db.queries.instrument_scope import scope_of
from lawgraph.db.queries.search import build_search_clause, tokenize_search_query

# Edges from an amending instrument to the articles it changes.
_MUTATION_RELATIONS = [RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS]


@dataclass
class AmendedByData:
    """Amending instruments of a regulation plus the titles of their dossiers."""

    items: list[dict[str, Any]]
    total: int
    dossier_titles: dict[str, str | None]


@dataclass
class InstrumentStats:
    """Aggregate statistics for a single instrument (law/regulation)."""

    article_count: int = 0
    judgment_count: int = 0
    inbound_citation_count: int = 0
    outbound_citation_count: int = 0


INSTRUMENT_SORTS = ("title", "article_count")


def get_articles(
    store: ArangoStore,
    identifier: str,
    *,
    include_stubs: bool = False,
    include_repealed: bool = False,
    limit: int = 2000,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """The articles of an instrument (BWB id or CELEX) and how many there are.

    In the order of the document (``props.position``): an article with only a heading
    where it stands, an annex after the regulation; historical articles and stubs last.
    Without *include_repealed* only the articles in force: no historical identity and no
    article whose current version repeals it.
    """
    scope = scope_of(identifier)
    stub_filter = "" if include_stubs else "FILTER doc.props.stub != true"
    if not include_repealed:
        stub_filter += " FILTER doc.props.repealed != true"
    aql = f"""
    LET filtered = (
        FOR doc IN {COLLECTION_ARTICLES}
            FILTER doc.props.{scope.prop} == @bwb_id
            {stub_filter}
            RETURN doc
    )
    LET total = LENGTH(filtered)
    LET items = (
        FOR doc IN filtered
            // the order of the document; a historical article or a stub has none: last
            SORT doc.props.position == null, doc.props.position, doc._key
            LIMIT @offset, @limit
            RETURN doc
    )
    RETURN {{ total: total, items: items }}
    """
    rows = list(
        store.query(aql, {"bwb_id": scope.value, "limit": limit, "offset": offset})
    )
    if not rows:
        return [], 0
    row = rows[0]
    return list(row.get("items") or []), int(row.get("total") or 0)


def get_instrument_judgments(
    store: ArangoStore, identifier: str, *, limit: int = 500
) -> tuple[list[dict[str, Any]], int]:
    """Judgments referring to any article of this instrument, grouped by judgment.

    Returns ``(items, total)`` where ``total`` is the absolute count of
    distinct judgments (independent of ``limit``) so the FE can render a
    "+N more" badge accurately. Each item is ``{judgment, cited_articles}``.

    cited_articles entries expose ``id``/``key`` (the standard node-id
    naming used everywhere else in the API), not ``article_id``/
    ``article_key``.
    """
    scope = scope_of(identifier)
    aql = f"""
    LET focal_ids = (
        FOR a IN {COLLECTION_ARTICLES}
            FILTER a.props.{scope.prop} == @bwb
            RETURN a._id
    )
    LET grouped = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == '{RELATION_REFERS_TO}' AND e._to IN focal_ids
            FILTER STARTS_WITH(e._from, '{COLLECTION_JUDGMENTS}/')
            COLLECT judgment_id = e._from INTO arts = e._to
            RETURN {{ judgment_id: judgment_id, arts: arts }}
    )
    LET total = LENGTH(grouped)
    LET items = (
        FOR row IN grouped
            // Only the date is read before the LIMIT: whole judgments in the sort are
            // every citing judgment of the law in memory at once.
            LET found = DOCUMENT(row.judgment_id)
            FILTER found != null
            LET date_eff = found.props.date_eff
            LET cited_count = LENGTH(UNIQUE(row.arts))
            SORT cited_count DESC, date_eff DESC
            LIMIT @limit
            RETURN {{
                judgment: {{
                    _id: found._id,
                    _key: found._key,
                    props: {{ecli: found.props.ecli, display_name: found.props.display_name}}
                }},
                cited_articles: (
                    FOR aid IN UNIQUE(row.arts)
                        LET a = DOCUMENT(aid)
                        FILTER a != null
                        RETURN {{
                            id: a._id,
                            key: a._key,
                            article_number: a.props.article_number,
                            display_name: a.props.display_name
                        }}
                )
            }}
    )
    RETURN {{ total: total, items: items }}
    """
    rows = list(store.query(aql, {"bwb": scope.value, "limit": limit}))
    if not rows:
        return [], 0
    row = rows[0]
    return list(row.get("items") or []), int(row.get("total") or 0)


def get_instrument_dossiers(
    store: ArangoStore, identifier: str, *, limit: int = 500
) -> tuple[list[dict[str, Any]], int]:
    """Parliamentary dossiers linked to this regulation, one query.

    Dossiers are reached through ``LEGISLATED_IN`` edges from two kinds of source:
      * the regulation itself (BWB ``dossierref``) -> ``via = "instrument"``;
      * the amending publications that AMEND / INTRODUCE / REPEAL one of its
        articles -> ``via = "amending_publication"`` (``publication`` names the
        newest such publication).
    A dossier linked both ways is reported as ``instrument``.

    Returns ``(items, total)``; each item is ``{dossier, via, publication}``.
    """
    scope = scope_of(identifier)
    instrument_id = f"{COLLECTION_INSTRUMENTS}/{scope.node_key}"
    aql = f"""
    LET article_ids = (
        FOR a IN {COLLECTION_ARTICLES}
            FILTER a.props.{scope.prop} == @bwb
            RETURN a._id
    )
    LET publication_ids = UNIQUE(
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to IN article_ids
            FILTER e.relation IN @mutations
            RETURN e._from
    )
    LET sources = APPEND([@instrument_id], publication_ids)
    LET grouped = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from IN sources
            FILTER e.relation == @legislated_in
            FILTER STARTS_WITH(e._to, 'dossiers/')
            COLLECT dossier_id = e._to INTO srcs = e._from
            LET d = DOCUMENT(dossier_id)
            FILTER d != null
            RETURN {{
                dossier: d,
                direct: @instrument_id IN srcs,
                publications: (
                    FOR s IN UNIQUE(srcs)
                        FILTER s != @instrument_id
                        LET p = DOCUMENT(s)
                        FILTER p != null
                        RETURN {{
                            key: p._key,
                            identifier: p.props.identifier,
                            published: p.props.date_published
                        }}
                )
            }}
    )
    LET total = LENGTH(grouped)
    LET items = (
        FOR g IN grouped
            SORT g.dossier.props.opened_on DESC, g.dossier.props.number ASC
            LIMIT @limit
            RETURN g
    )
    RETURN {{ total: total, items: items }}
    """
    rows = list(
        store.query(
            aql,
            {
                "bwb": scope.value,
                "instrument_id": instrument_id,
                "mutations": _MUTATION_RELATIONS,
                "legislated_in": RELATION_LEGISLATED_IN,
                "limit": limit,
            },
        )
    )
    if not rows:
        return [], 0
    row = rows[0]
    return [_dossier_link(g) for g in row.get("items") or []], int(
        row.get("total") or 0
    )


def _dossier_link(group: dict[str, Any]) -> dict[str, Any]:
    """Shape one grouped dossier row as ``{dossier, via, publication}``."""
    if group.get("direct"):
        return {"dossier": group["dossier"], "via": "instrument", "publication": None}
    publications = sorted(
        group.get("publications") or [],
        key=lambda p: (p.get("published") or "", p.get("key") or ""),
        reverse=True,
    )
    newest = publications[0] if publications else None
    return {
        "dossier": group["dossier"],
        "via": "amending_publication",
        "publication": (
            (newest.get("identifier") or newest.get("key")) if newest else None
        ),
    }


def get_instrument_amended_by(
    store: ArangoStore, identifier: str, *, limit: int = 50, offset: int = 0
) -> AmendedByData:
    """Amending instruments of a regulation, newest first (2 queries at most).

    One aggregating query over the AMENDS / INTRODUCES / REPEALS edges whose
    ``_to`` is an article of the regulation (the ``_to`` edge index is used with
    the collected article ids), grouped per amending instrument; a second bulk
    query resolves the titles of every dossier the page mentions.
    """
    scope = scope_of(identifier)
    aql = f"""
    LET article_ids = (
        FOR a IN {COLLECTION_ARTICLES}
            FILTER a.props.{scope.prop} == @bwb
            RETURN a._id
    )
    LET grouped = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to IN article_ids
            FILTER e.relation IN @mutations
            COLLECT source_id = e._from INTO hits = {{
                relation: e.relation,
                article: e._to,
                effective: e.meta.effective_date
            }}
            LET d = DOCUMENT(source_id)
            FILTER d != null
            RETURN {{
                instrument: d,
                amends: LENGTH(FOR h IN hits FILTER h.relation == @amends RETURN 1),
                introduces: LENGTH(
                    FOR h IN hits FILTER h.relation == @introduces RETURN 1
                ),
                repeals: LENGTH(FOR h IN hits FILTER h.relation == @repeals RETURN 1),
                articles_affected: LENGTH(UNIQUE(hits[*].article)),
                first_effective_date: MIN(hits[*].effective)
            }}
    )
    LET total = LENGTH(grouped)
    LET items = (
        FOR g IN grouped
            SORT g.instrument.props.date_published DESC,
                 g.instrument.props.date_signed DESC,
                 g.instrument._key DESC
            LIMIT @offset, @limit
            RETURN g
    )
    RETURN {{ total: total, items: items }}
    """
    rows = list(
        store.query(
            aql,
            {
                "bwb": scope.value,
                "mutations": _MUTATION_RELATIONS,
                "amends": RELATION_AMENDS,
                "introduces": RELATION_INTRODUCES,
                "repeals": RELATION_REPEALS,
                "limit": limit,
                "offset": offset,
            },
        )
    )
    if not rows:
        return AmendedByData(items=[], total=0, dossier_titles={})
    row = rows[0]
    items = list(row.get("items") or [])
    numbers = collect_dossier_numbers(
        {
            "dossiers": (i.get("instrument", {}).get("props") or {}).get(
                "dossier_numbers"
            )
        }
        for i in items
    )
    return AmendedByData(
        items=items,
        total=int(row.get("total") or 0),
        dossier_titles=get_dossier_titles(store, numbers),
    )


def get_instrument_related_instruments(
    store: ArangoStore, identifier: str, *, limit: int = 100
) -> tuple[list[dict[str, Any]], int]:
    """Other instruments related by cross-article REFERS_TO links.

    Returns ``{instrument, outbound_count, inbound_count}`` per related
    instrument, sorted by total reference count descending. The counterpart of a
    BWB regulation is a BWB regulation; the counterpart of an EU act is a BWB
    regulation or another EU act.
    """
    scope = scope_of(identifier)
    # The identity of the counterpart of an edge, and how it is found again.
    if scope.prop == "bwb_id":

        def identity(var: str) -> str:
            return f"{var}.props.bwb_id"

        find = "FILTER i.props.bwb_id != null AND i.props.bwb_id == b"
    else:

        def identity(var: str) -> str:
            return (
                f"({var}.props.bwb_id != null ? {var}.props.bwb_id : {var}.props.celex)"
            )

        find = (
            "FILTER (i.props.bwb_id != null AND i.props.bwb_id == b)"
            " OR (i.props.celex != null AND i.props.celex == b)"
        )
    # MERGE-based O(B) lookup replaces the previous O(B²) FIRST(FILTER) pattern.
    # COLLECT uses the raw (uppercase) identifier so the instrument lookup can use
    # the props.bwb_id / props.celex B-tree index with a direct equality filter.
    aql = f"""
    LET focal_article_ids = (
        FOR a IN {COLLECTION_ARTICLES}
            FILTER a.props.{scope.prop} == @bwb
            RETURN a._id
    )
    LET out_buckets = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == '{RELATION_REFERS_TO}'
            FILTER e._from IN focal_article_ids AND e._to NOT IN focal_article_ids
            LET target = DOCUMENT(e._to)
            FILTER target != null AND STARTS_WITH(target._id, 'articles/')
            COLLECT bwb = {identity("target")} WITH COUNT INTO n
            FILTER bwb != null AND bwb != @bwb
            RETURN {{bwb: bwb, outbound_count: n}}
    )
    LET in_buckets = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == '{RELATION_REFERS_TO}'
            FILTER e._to IN focal_article_ids AND e._from NOT IN focal_article_ids
            LET src = DOCUMENT(e._from)
            FILTER src != null AND STARTS_WITH(src._id, 'articles/')
            COLLECT bwb = {identity("src")} WITH COUNT INTO n
            FILTER bwb != null AND bwb != @bwb
            RETURN {{bwb: bwb, inbound_count: n}}
    )
    LET out_map = MERGE(FOR o IN out_buckets RETURN {{[o.bwb]: o.outbound_count}})
    LET in_map  = MERGE(FOR i IN in_buckets  RETURN {{[i.bwb]: i.inbound_count}})
    LET all_bwbs = UNIQUE(APPEND(out_buckets[*].bwb, in_buckets[*].bwb))
    LET resolved = (
        FOR b IN all_bwbs
            LET out_n = out_map[b] != null ? out_map[b] : 0
            LET in_n  = in_map[b]  != null ? in_map[b]  : 0
            LET inst = FIRST(
                FOR i IN {COLLECTION_INSTRUMENTS}
                    {find}
                    LIMIT 1 RETURN i
            )
            FILTER inst != null
            RETURN {{ instrument: inst, outbound_count: out_n, inbound_count: in_n }}
    )
    LET total = LENGTH(resolved)
    LET items = (
        FOR r IN resolved
            SORT (r.outbound_count + r.inbound_count) DESC
            LIMIT @limit
            RETURN r
    )
    RETURN {{ total: total, items: items }}
    """
    rows = list(store.query(aql, {"bwb": scope.value, "limit": limit}))
    if not rows:
        return [], 0
    row = rows[0]
    return list(row.get("items") or []), int(row.get("total") or 0)


def get_instruments_list(
    store: ArangoStore,
    *,
    q: str | None = None,
    jurisdiction: str | None = None,
    kind: str | None = None,
    article_count_min: int | None = None,
    sort: str = "title",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Paginated, filterable list of instruments with cheap aggregate stats.

    Performance strategy:
      * Free-text (`q`) is served by the ``search_instruments`` ArangoSearch
        view with BM25 ranking — orders of magnitude cheaper than a per-row
        ``CONTAINS(LOWER(...))`` scan.
      * Filter fields (jurisdiction, kind, article_count) and the sort key
        for ``article_count`` are read from the props ``graph-list-stats``
        precomputes on the instrument document.
      * ``total`` is exact when ``q``/filters are applied (cheap because the
        filtered base set is small); an unfiltered list returns the collection
        cardinality via ``COLLECTION_COUNT``. The frontend falls back to
        ``has_more`` for pagination either way.
    """
    tokens = tokenize_search_query(q) if q else []
    use_search = bool(tokens)
    # When q tokenises to nothing (single-char query, only punctuation), the
    # query degrades to "no filter" — keep the cheap COLLECTION_COUNT path
    # instead of paying for LENGTH(base) on the whole collection.
    has_filter = bool(
        use_search or jurisdiction or kind or article_count_min is not None
    )

    search_clause, tok_bind = (
        build_search_clause(
            tokens,
            [
                "title",
                "citation_title",
                "official_title",
                "display_name",
                "short_title",
                "bwb_id",
            ],
        )
        if tokens
        else ("true", {})
    )

    # Single-key SORT against indexed props — keeps LIMIT before
    # materialise. citation_title is indexed (non-sparse) so the title sort
    # plan is now IndexNode → Limit → Materialise.
    sort_clause = {
        "title": "SORT doc.props.citation_title ASC",
        "article_count": "SORT doc.props.article_count DESC",
    }[sort]

    bind_vars: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "jurisdiction": jurisdiction.lower() if jurisdiction else None,
        "kind": kind.lower() if kind else None,
        "article_count_min": article_count_min,
        "publication": KIND_PUBLICATION,
        **tok_bind,
    }

    # Source clause: SEARCH view when we have a free-text query (BM25-ranked,
    # uses the inverted index), otherwise the raw collection. `build_search_clause`
    # hardcodes ``doc.props.<field>``, so the loop variable must be ``doc``.
    source = (
        f'FOR doc IN search_instruments SEARCH ANALYZER({search_clause}, "{TEXT_ANALYZER}")'
        if use_search
        else f"FOR doc IN {COLLECTION_INSTRUMENTS}"
    )

    # Single FOR with SORT + LIMIT against indexed props — planner picks
    # IndexNode and never builds a SortNode, so only @limit rows materialise.
    aql = f"""
    LET items = (
        {source}
            FILTER @jurisdiction == null OR doc.props.jurisdiction == @jurisdiction
            FILTER @kind == null
                ? doc.props.kind != @publication : doc.props.kind == @kind
            FILTER @article_count_min == null
                OR (doc.props.article_count != null
                    AND doc.props.article_count >= @article_count_min)
            {sort_clause}
            LIMIT @offset, @limit
            LET props = doc.props
            LET citation_title = (
                props.citation_title != null ? props.citation_title :
                (props.title != null ? props.title :
                 (props.display_name != null ? props.display_name : doc._key))
            )
            RETURN {{
                _id: doc._id,
                _key: doc._key,
                bwb_id: props.bwb_id,
                celex: props.celex,
                title: props.title,
                short_title: props.short_title,
                kind: props.kind,
                citation_title: citation_title,
                jurisdiction: props.jurisdiction,
                article_count: props.article_count,
                uri: props.uri,
                publication_kind: props.publication_kind,
                publication_year: props.publication_year,
                publication_number: props.publication_number
            }}
    )
    """

    if has_filter:
        count_source = (
            f'FOR doc IN search_instruments SEARCH ANALYZER({search_clause}, "{TEXT_ANALYZER}")'
            if use_search
            else f"FOR doc IN {COLLECTION_INSTRUMENTS}"
        )
        aql += f"""
    LET total = LENGTH(
        {count_source}
            FILTER @jurisdiction == null OR doc.props.jurisdiction == @jurisdiction
            FILTER @kind == null
                ? doc.props.kind != @publication : doc.props.kind == @kind
            FILTER @article_count_min == null
                OR (doc.props.article_count != null
                    AND doc.props.article_count >= @article_count_min)
            RETURN 1
    )
    """
    else:
        # the collection less its publications, counted on the index of the kind
        aql += f"""
    LET total = COLLECTION_COUNT('{COLLECTION_INSTRUMENTS}') - LENGTH(
        FOR doc IN {COLLECTION_INSTRUMENTS} FILTER doc.props.kind == @publication RETURN 1
    )
    """

    aql += "RETURN { total: total, items: items }\n"

    rows = list(store.query(aql, bind_vars))
    return rows[0] if rows else {"total": 0, "items": []}


def get_instrument_versions(
    store: ArangoStore,
    bwb_id: str,
) -> list[dict[str, Any]]:
    """Return all historical versions for an instrument, newest first."""
    aql = f"""
    FOR doc IN {COLLECTION_INSTRUMENT_VERSIONS}
        FILTER doc.props.bwb_id == @bwb_id
        SORT doc.props.valid_from DESC
        RETURN doc
    """
    return list(store.query(aql, {"bwb_id": bwb_id.upper()}))


@dataclass(frozen=True)
class LawOnADate:
    """The articles of a law in force on a date (a page of them), how many there are, and
    the start of the first toestand of the law."""

    items: list[dict[str, Any]]
    total: int
    first_version_from: str | None


def get_articles_at(
    store: ArangoStore,
    bwb_id: str,
    at_date: str,
    *,
    limit: int = 2000,
    offset: int = 0,
) -> LawOnADate:
    """The articles of the law in force on *at_date* (YYYY-MM-DD): the article versions
    whose half-open period holds it, in the order of the document. A bijlage is part of the
    law, not an article of it: the articles of a bijlage are left out.

    None before the first toestand of the law: the source gives the law from there, and an
    article's own start before it (``inwerking``) says nothing of the articles that were
    replaced or lapsed before it."""
    aql = f"""
    LET first = FIRST(
        FOR v IN {COLLECTION_INSTRUMENT_VERSIONS}
            FILTER v.props.bwb_id == @bwb_id
            SORT v.props.valid_from
            LIMIT 1
            RETURN v.props.valid_from
    )
    LET filtered = first == null OR @at_date < first ? [] : (
        FOR doc IN {COLLECTION_ARTICLE_VERSIONS}
            FILTER doc.props.bwb_id == @bwb_id
            FILTER doc.props.valid_from <= @at_date
            FILTER doc.props.valid_until > @at_date OR doc.props.valid_until == null
            FILTER NOT LIKE(doc.props.article_number OR "", "bijlage %")
            RETURN doc
    )
    LET items = (
        FOR doc IN filtered
            SORT doc.props.position == null, doc.props.position, doc._key
            LIMIT @offset, @limit
            RETURN doc
    )
    RETURN {{ total: LENGTH(filtered), items: items, first: first }}
    """
    bind = {
        "bwb_id": bwb_id.upper(),
        "at_date": at_date,
        "limit": limit,
        "offset": offset,
    }
    rows = list(store.query(aql, bind))
    row = rows[0] if rows else {}
    return LawOnADate(
        items=list(row.get("items") or []),
        total=int(row.get("total") or 0),
        first_version_from=row.get("first"),
    )
