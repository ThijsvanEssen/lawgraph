"""Instrument query helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lawgraph.api.queries.search import build_search_clause, tokenize_search_query
from lawgraph.config.constants import RELATION_PART_OF_INSTRUMENT, RELATION_RAAKT
from lawgraph.config.settings import COLLECTION_EDGES
from lawgraph.core.models import parse_arango_id
from lawgraph.db import ArangoStore


@dataclass
class InstrumentStats:
    """Aggregate statistics for a single instrument (law/regulation)."""

    article_count: int = 0
    judgment_count: int = 0
    inbound_citation_count: int = 0
    outbound_citation_count: int = 0


INSTRUMENT_SORTS = ("title", "article_count")


def get_instrument_articles(
    store: ArangoStore,
    bwb_id: str,
    *,
    include_stubs: bool = False,
    limit: int = 2000,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """All articles belonging to an instrument, sorted by article_number.

    Sort is a natural numeric-aware order (so 'Artikel 9' precedes 'Artikel 10'
    and '24c' lands between '24' and '25') derived in AQL via a numeric/string
    split on the article_number. Returns ``(items, total)``.
    """
    bwb_uc = bwb_id.upper()
    stub_filter = "" if include_stubs else "FILTER doc.props.stub != true"
    aql = f"""
    LET filtered = (
        FOR doc IN instrument_articles
            FILTER doc.props.bwb_id == @bwb_id
            {stub_filter}
            RETURN doc
    )
    LET total = LENGTH(filtered)
    LET items = (
        FOR doc IN filtered
            // Natural sort: split article_number into leading int + suffix
            LET num_str = doc.props.article_number != null ? doc.props.article_number : ""
            LET digits = REGEX_MATCHES(num_str, "^([0-9]+)")
            LET num_int = LENGTH(digits) > 0 ? TO_NUMBER(digits[0]) : 999999
            LET suffix = LENGTH(digits) > 0 ? SUBSTRING(num_str, LENGTH(digits[0])) : num_str
            SORT num_int ASC, suffix ASC
            LIMIT @offset, @limit
            RETURN doc
    )
    RETURN {{ total: total, items: items }}
    """
    rows = list(store.query(aql, {"bwb_id": bwb_uc, "limit": limit, "offset": offset}))
    if not rows:
        return [], 0
    row = rows[0]
    return list(row.get("items") or []), int(row.get("total") or 0)


def get_instrument_edges_bundle(
    store: ArangoStore,
    bwb_id: str,
    *,
    relations: list[str] | None = None,
    include_part_of_instrument: bool = False,
    max_edges: int = 20000,
) -> dict[str, Any]:
    """Bulk: every edge incident to any article of this instrument.

    Returns a single payload the FE can use to render the legal-citation
    graph without N+1 round-trips:

      {bwb_id, article_count, total_edges,
       edges:[{from,to,relation,direction,meta}],
       nodes:{<collection>: [doc, ...]}}

    By default ``PART_OF_INSTRUMENT`` (article→instrument structural backbone)
    is excluded. Pass ``include_part_of_instrument=True`` to include it.

    ``relations`` is an explicit whitelist; when None, all relations except
    PART_OF_INSTRUMENT are returned.
    """
    bind: dict[str, Any] = {"bwb": bwb_id.upper(), "max_edges": max_edges}

    rel_filter = ""
    if relations:
        bind["relations"] = relations
        rel_filter = "FILTER e.relation IN @relations"
    elif not include_part_of_instrument:
        rel_filter = "FILTER e.relation != 'PART_OF_INSTRUMENT'"

    # Split the OR (e._from IN focal_ids OR e._to IN focal_ids) into two
    # index-friendly sub-queries so each can use the _from / _to B-tree index.
    # Intra-instrument edges (both ends in focal_ids) appear only in out_edges;
    # in_edges excludes them via FILTER e._from NOT IN focal_ids.
    aql = f"""
    LET focal_ids = (
        FOR a IN instrument_articles
            FILTER a.props.bwb_id == @bwb
            RETURN a._id
    )
    LET out_edges = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from IN focal_ids
            {rel_filter}
            RETURN {{
                from: e._from,
                to: e._to,
                relation: e.relation,
                direction: e._to IN focal_ids ? "intra" : "out",
                meta: e.meta
            }}
    )
    LET in_edges = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to IN focal_ids
            FILTER e._from NOT IN focal_ids
            {rel_filter}
            RETURN {{
                from: e._from,
                to: e._to,
                relation: e.relation,
                direction: "in",
                meta: e.meta
            }}
    )
    LET edges = SLICE(APPEND(out_edges, in_edges), 0, @max_edges)
    LET foreign_ids = UNIQUE(
        FOR e IN edges
            FOR id IN [e.from, e.to]
                FILTER id NOT IN focal_ids
                RETURN id
    )
    LET foreign_docs = (
        FOR id IN foreign_ids
            LET d = DOCUMENT(id)
            FILTER d != null
            RETURN d
    )
    RETURN {{
        article_count: LENGTH(focal_ids),
        edges: edges,
        foreign_docs: foreign_docs
    }}
    """
    rows = list(store.query(aql, bind))
    if not rows:
        return {
            "bwb_id": bwb_id,
            "article_count": 0,
            "total_edges": 0,
            "edges": [],
            "nodes": {},
        }
    row = rows[0]
    edges = list(row.get("edges") or [])
    nodes_by_coll: dict[str, list[dict[str, Any]]] = {}
    for doc in row.get("foreign_docs") or []:
        coll = parse_arango_id(doc.get("_id") or "")[0]
        if not coll:
            continue
        nodes_by_coll.setdefault(coll, []).append(doc)
    return {
        "bwb_id": bwb_id,
        "article_count": int(row.get("article_count") or 0),
        "total_edges": len(edges),
        "edges": edges,
        "nodes": nodes_by_coll,
    }


def get_instrument_judgments(
    store: ArangoStore, bwb_id: str, *, limit: int = 500
) -> tuple[list[dict[str, Any]], int]:
    """Judgments citing any article of this instrument, grouped by judgment.

    Returns ``(items, total)`` where ``total`` is the absolute count of
    distinct judgments (independent of ``limit``) so the FE can render a
    "+N more" badge accurately. Each item is ``{judgment, cited_articles}``.

    cited_articles entries expose ``id``/``key`` (the standard node-id
    naming used everywhere else in the API), not ``article_id``/
    ``article_key``.
    """
    aql = f"""
    LET focal_ids = (
        FOR a IN instrument_articles
            FILTER a.props.bwb_id == @bwb
            RETURN a._id
    )
    LET grouped = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == 'CITES_ARTICLE' AND e._to IN focal_ids
            FILTER STARTS_WITH(e._from, 'judgments/')
            COLLECT judgment_id = e._from INTO arts = e._to
            RETURN {{ judgment_id: judgment_id, arts: arts }}
    )
    LET total = LENGTH(grouped)
    LET items = (
        FOR row IN grouped
            LET judgment = DOCUMENT(row.judgment_id)
            FILTER judgment != null
            LET cited_count = LENGTH(UNIQUE(row.arts))
            SORT cited_count DESC, judgment.props.date_eff DESC
            LIMIT @limit
            RETURN {{
                judgment: judgment,
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
    rows = list(store.query(aql, {"bwb": bwb_id.upper(), "limit": limit}))
    if not rows:
        return [], 0
    row = rows[0]
    return list(row.get("items") or []), int(row.get("total") or 0)


def get_instrument_dossiers(
    store: ArangoStore, bwb_id: str, *, limit: int = 500
) -> tuple[list[dict[str, Any]], int]:
    """Kamerstukdossiers that touch this instrument.

    Combines two paths:
      * direct:  dossier -RAAKT-> instrument
      * derived: publication -(WIJZIGT|TREKT_IN|INTRODUCEERT|LICHT_TOE|MENTIONS_ARTICLE)->
                 article-of-this-instrument, and that publication is
                 -DEEL_VAN_DOSSIER-> dossier.
    """
    aql = f"""
    LET focal_article_ids = (
        FOR a IN instrument_articles
            FILTER a.props.bwb_id == @bwb
            RETURN a._id
    )
    LET instrument_id = FIRST(
        FOR i IN instruments
            FILTER i.props.bwb_id == @bwb
            LIMIT 1 RETURN i._id
    )
    LET direct = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == @raakt AND e._to == instrument_id
            LET d = DOCUMENT(e._from)
            FILTER d != null AND STARTS_WITH(d._id, 'kamerstukdossiers/')
            RETURN d
    )
    LET derived = (
        FOR e1 IN {COLLECTION_EDGES}
            FILTER e1._to IN focal_article_ids
            FILTER e1.relation IN ['WIJZIGT','TREKT_IN','INTRODUCEERT','LICHT_TOE','MENTIONS_ARTICLE']
            LET pub_id = e1._from
            FILTER STARTS_WITH(pub_id, 'publications/')
            FOR e2 IN {COLLECTION_EDGES}
                FILTER e2._from == pub_id AND e2.relation == 'DEEL_VAN_DOSSIER'
                LET d = DOCUMENT(e2._to)
                FILTER d != null AND STARTS_WITH(d._id, 'kamerstukdossiers/')
                RETURN d
    )
    LET dedup = UNIQUE(APPEND(direct, derived))
    LET total = LENGTH(dedup)
    LET items = (
        FOR d IN dedup
            SORT d.props.geopend_op DESC, d.props.kamerstuknummer ASC
            LIMIT @limit
            RETURN d
    )
    RETURN {{ total: total, items: items }}
    """
    rows = list(
        store.query(
            aql, {"bwb": bwb_id.upper(), "limit": limit, "raakt": RELATION_RAAKT}
        )
    )
    if not rows:
        return [], 0
    row = rows[0]
    return list(row.get("items") or []), int(row.get("total") or 0)


def get_instrument_related_instruments(
    store: ArangoStore, bwb_id: str, *, limit: int = 100
) -> tuple[list[dict[str, Any]], int]:
    """Other instruments related by cross-article REFERS_TO_ARTICLE links.

    Returns ``{instrument, outbound_count, inbound_count}`` per related
    instrument, sorted by total reference count descending.
    """
    # MERGE-based O(B) lookup replaces the previous O(B²) FIRST(FILTER) pattern.
    # COLLECT uses the raw (uppercase) bwb_id so the instrument lookup can use
    # the props.bwb_id B-tree index with a direct equality filter.
    aql = f"""
    LET focal_article_ids = (
        FOR a IN instrument_articles
            FILTER a.props.bwb_id == @bwb
            RETURN a._id
    )
    LET out_buckets = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == 'REFERS_TO_ARTICLE'
            FILTER e._from IN focal_article_ids AND e._to NOT IN focal_article_ids
            LET target = DOCUMENT(e._to)
            FILTER target != null AND STARTS_WITH(target._id, 'instrument_articles/')
            COLLECT bwb = target.props.bwb_id WITH COUNT INTO n
            FILTER bwb != null AND bwb != @bwb
            RETURN {{bwb: bwb, outbound_count: n}}
    )
    LET in_buckets = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == 'REFERS_TO_ARTICLE'
            FILTER e._to IN focal_article_ids AND e._from NOT IN focal_article_ids
            LET src = DOCUMENT(e._from)
            FILTER src != null AND STARTS_WITH(src._id, 'instrument_articles/')
            COLLECT bwb = src.props.bwb_id WITH COUNT INTO n
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
                FOR i IN instruments
                    FILTER i.props.bwb_id == b
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
    rows = list(store.query(aql, {"bwb": bwb_id.upper(), "limit": limit}))
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
        for ``article_count`` are read from precomputed props on the
        instrument document (back-filled by
        ``lawgraph-backfill-instrument-stats`` and kept current by the
        normalize pipelines). When the precomputed value is missing on a
        legacy doc, the loop derives it inline so the endpoint stays
        correct without the backfill.
      * ``total`` is exact when ``q``/filters are applied (cheap because the
        filtered base set is small); when the list is unfiltered we return
        the collection cardinality via ``COLLECTION_COUNT``. The frontend
        falls back to ``has_more`` for pagination either way.
      * ``article_count`` is read from the document; when missing, fetched
        per page row only (O(limit), not O(N)).
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
        "part_of": RELATION_PART_OF_INSTRUMENT,
        "jurisdiction": jurisdiction.lower() if jurisdiction else None,
        "kind": kind.lower() if kind else None,
        "article_count_min": article_count_min,
        **tok_bind,
    }

    # Source clause: SEARCH view when we have a free-text query (BM25-ranked,
    # uses the inverted index), otherwise the raw collection. `build_search_clause`
    # hardcodes ``doc.props.<field>``, so the loop variable must be ``doc``.
    source = (
        f'FOR doc IN search_instruments SEARCH ANALYZER({search_clause}, "text_en")'
        if use_search
        else "FOR doc IN instruments"
    )

    # Single FOR with SORT + LIMIT against indexed props — planner picks
    # IndexNode and never builds a SortNode. We project + run the
    # article_count fallback subquery only on the LIMITed page.
    aql = f"""
    LET items = (
        {source}
            FILTER @jurisdiction == null OR doc.props.jurisdiction == @jurisdiction
            FILTER @kind == null OR doc.props.kind == @kind
            FILTER @article_count_min == null
                OR (doc.props.article_count != null
                    AND doc.props.article_count >= @article_count_min)
            {sort_clause}
            LIMIT @offset, @limit
            LET props = doc.props
            LET jurisdiction = LOWER(
                props.jurisdiction != null ? props.jurisdiction :
                (props.celex != null ? 'eu' :
                 (props.bwb_id != null ? 'nl' : ''))
            )
            LET citation_title = (
                props.citation_title != null ? props.citation_title :
                (props.display_name != null ? props.display_name :
                 (props.title != null ? props.title : doc._key))
            )
            LET article_count = props.article_count != null ? props.article_count : LENGTH(
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._from == doc._id AND e.relation == @part_of
                    RETURN 1
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
                jurisdiction: jurisdiction,
                article_count: article_count
            }}
    )
    """

    if has_filter:
        count_source = (
            f'FOR doc IN search_instruments SEARCH ANALYZER({search_clause}, "text_en")'
            if use_search
            else "FOR doc IN instruments"
        )
        aql += f"""
    LET total = LENGTH(
        {count_source}
            FILTER @jurisdiction == null OR doc.props.jurisdiction == @jurisdiction
            FILTER @kind == null OR doc.props.kind == @kind
            FILTER @article_count_min == null
                OR (doc.props.article_count != null
                    AND doc.props.article_count >= @article_count_min)
            RETURN 1
    )
    """
    else:
        aql += "LET total = COLLECTION_COUNT('instruments')\n"

    aql += "RETURN { total: total, items: items }\n"

    rows = list(store.query(aql, bind_vars))
    return rows[0] if rows else {"total": 0, "items": []}


def get_instrument_versions(
    store: ArangoStore,
    bwb_id: str,
) -> list[dict[str, Any]]:
    """Return all historical versions for an instrument, newest first."""
    aql = """
    FOR doc IN instrument_versions
        FILTER doc.props.bwb_id == @bwb_id
        SORT doc.props.valid_from DESC
        RETURN doc
    """
    return list(store.query(aql, {"bwb_id": bwb_id.upper()}))


def get_instrument_articles_at(
    store: ArangoStore,
    bwb_id: str,
    at_date: str,
) -> list[dict[str, Any]]:
    """Return all article versions valid at the given date (YYYY-MM-DD), sorted naturally."""
    aql = """
    LET filtered = (
        FOR doc IN instrument_article_versions
            FILTER doc.props.bwb_id == @bwb_id
            FILTER doc.props.valid_from <= @at_date
            FILTER doc.props.valid_until > @at_date OR doc.props.valid_until == null
            RETURN doc
    )
    FOR doc IN filtered
        LET num_str = doc.props.article_number != null ? doc.props.article_number : ""
        LET digits = REGEX_MATCHES(num_str, "^([0-9]+)")
        LET num_int = LENGTH(digits) > 0 ? TO_NUMBER(digits[0]) : 999999
        LET suffix  = LENGTH(digits) > 0 ? SUBSTRING(num_str, LENGTH(digits[0])) : num_str
        SORT num_int ASC, suffix ASC
        RETURN doc
    """
    return list(store.query(aql, {"bwb_id": bwb_id.upper(), "at_date": at_date}))


def get_instrument_article_history(
    store: ArangoStore,
    bwb_id: str,
    article_number: str,
) -> list[dict[str, Any]]:
    """Return all versions of one article, newest first."""
    aql = """
    FOR doc IN instrument_article_versions
        FILTER doc.props.bwb_id == @bwb_id
        FILTER doc.props.article_number == @article_number
        SORT doc.props.valid_from DESC
        RETURN doc
    """
    return list(
        store.query(aql, {"bwb_id": bwb_id.upper(), "article_number": article_number})
    )
