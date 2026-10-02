"""Instrument query helpers."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, cast

from lawgraph.config.constants import (
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_REFERS_TO,
    RELATION_REPEALS,
)
from lawgraph.core.bwb_xml import KIND_PUBLICATION
from lawgraph.core.judgments import KIND_CONCLUSIE
from lawgraph.db import GraphStore
from lawgraph.db._rows import node_doc
from lawgraph.db.queries._helpers import run_together
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


def _document_order(table: str) -> str:
    """The order of the document (``props.position``, a number); a historical article or
    a stub has none: last. The key settles ties. ``position`` is a column, so the props of
    a law's articles are not read for it."""
    position = f"{table}.position"
    return f"{position} IS NULL, {position} NULLS FIRST, {table}.key"


def _paged(counted: str, page: str) -> str:
    """A page and the total in one statement: every row carries ``total`` (the rows of
    *counted*), the rows of *page* their place ``n``; a page past the end is one row with
    the total alone (``n`` null). *page* selects ``row_number() OVER (...) AS n``, orders
    by it and pages."""
    return f"""
        SELECT t.total, p.*
        FROM (SELECT count(*)::int AS total FROM {counted}) t
        LEFT JOIN ({page}) p ON true
        ORDER BY p.n
    """


def _split_page(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """The rows of a ``_paged`` statement as (the rows of the page, the total)."""
    found = list(rows)
    total = int(found[0]["total"]) if found else 0
    return [row for row in found if row["n"] is not None], total


def _articles_of(prop: str) -> str:
    """The ids of the articles whose *prop* (``bwb_id`` or ``celex``) is ``%(bwb)s``."""
    return f"SELECT id FROM articles WHERE {prop} = %(bwb)s"


def get_articles(
    store: GraphStore,
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
    conditions = [f"a.{scope.prop} = %(bwb)s"]
    if not include_stubs:
        conditions.append("a.stub IS NOT TRUE")
    if not include_repealed:
        conditions.append("a.repealed IS NOT TRUE")
    matched = f"articles a WHERE {' AND '.join(conditions)}"
    page = f"""
        SELECT a.id, a.key, a.type, a.labels, a.props,
               row_number() OVER (ORDER BY {_document_order("a")}) AS n
        FROM {matched}
        ORDER BY n
        LIMIT %(limit)s OFFSET %(offset)s
    """
    rows = store.query(
        _paged(matched, page),
        {"bwb": scope.value, "limit": limit, "offset": offset},
    )
    items, total = _split_page(rows)
    return [node_doc(row) for row in items], total


# The orders of the judgments that cite a law: the newest first, or the most cited articles
# of the law first (then the newest); the id settles ties.
INSTRUMENT_JUDGMENT_SORTS = {
    "date": "j.date_eff DESC NULLS LAST, g.judgment_id",
    "cited": "g.cited_count DESC, j.date_eff DESC NULLS LAST, g.judgment_id",
}


def _citing_judgments(prop: str) -> str:
    """``cites`` (judgment, article) and ``grouped`` (judgment, how many of the articles of
    the law it cites): the judgments that cite the law of ``%(bwb)s``."""
    return f"""
        WITH cites AS (
            SELECT DISTINCT e.from_id AS judgment_id, e.to_id AS article_id
            FROM edges e
            WHERE e.relation = %(refers_to)s
              AND e.to_id IN ({_articles_of(prop)})
              AND e.from_collection = %(judgments)s
        ),
        grouped AS (
            SELECT judgment_id, count(*)::int AS cited_count
            FROM cites GROUP BY judgment_id
        )
    """


def get_instrument_judgments(
    store: GraphStore,
    identifier: str,
    *,
    sort: str = "date",
    limit: int = 500,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Judgments referring to any article of this instrument, grouped by judgment, in the
    order of *sort* (``INSTRUMENT_JUDGMENT_SORTS``).

    Returns ``(items, total)`` where ``total`` is the absolute count of
    distinct judgments (independent of ``limit``) so the FE can render a
    "+N more" badge accurately. Each item is ``{judgment, cited_articles}``.

    cited_articles entries expose ``id``/``key`` (the standard node-id
    naming used everywhere else in the API), not ``article_id``/
    ``article_key``.
    """
    scope = scope_of(identifier)
    order = INSTRUMENT_JUDGMENT_SORTS[sort]
    # ``total`` counts every citing judgment id, one that is missing too; the page only the
    # judgments that exist. Only the date is read before the LIMIT: whole judgments in the
    # sort are every citing judgment of the law in memory at once.
    ctes = (
        _citing_judgments(scope.prop)
        + f""",
        top AS (
            SELECT g.judgment_id, row_number() OVER (ORDER BY {order}) AS n
            FROM grouped g JOIN judgments j ON j.id = g.judgment_id
            ORDER BY n
            LIMIT %(limit)s OFFSET %(offset)s
        )
    """
    )
    # The page is cut from the judgments first (``top``); the cited articles are gathered
    # for those alone, in one pass (a scan of ``cites`` per row of the page would be 500
    # scans, and the props of every cited article of the law parsed).
    page = f"""
        SELECT json_build_object(
            'judgment', json_build_object(
                '_id', j.id,
                '_key', j.key,
                'props', json_build_object(
                    'ecli', j.pj_ecli, 'display_name', j.pj_display_name,
                    'court_code', j.pj_court_code, 'tier', j.pj_tier,
                    'court_kind', j.pj_court_kind, 'date_eff', j.pj_date_eff,
                    'advocate_general', {_OF_A_CONCLUSION.format(prop="advocate_general")},
                    'advocate_general_role',
                    {_OF_A_CONCLUSION.format(prop="advocate_general_role")}
                )
            ),
            'cited_articles', coalesce(cited.articles, '[]')
        ) AS item,
        top.n
        FROM top
        JOIN judgments j ON j.id = top.judgment_id
        LEFT JOIN (
            SELECT c.judgment_id, json_agg(json_build_object(
                'id', a.id,
                'key', a.key,
                'article_number', a.props -> 'article_number',
                'display_name', a.props -> 'display_name'
            ) ORDER BY {_document_order("a")}) AS articles
            FROM cites c JOIN articles a ON a.id = c.article_id
            WHERE c.judgment_id IN (SELECT judgment_id FROM top)
            GROUP BY c.judgment_id
        ) cited ON cited.judgment_id = top.judgment_id
        ORDER BY top.n
    """
    rows = store.query(
        ctes + _paged("grouped", page),
        {
            "bwb": scope.value,
            "refers_to": RELATION_REFERS_TO,
            "judgments": COLLECTION_JUDGMENTS,
            "conclusion": KIND_CONCLUSIE,
            "limit": limit,
            "offset": offset,
        },
    )
    items, total = _split_page(rows)
    return [row["item"] for row in items], total


@dataclass(frozen=True)
class CitingJudgments:
    """A page of the judgments that cite a law, how many there are, and per year."""

    items: list[dict[str, Any]]
    total: int
    years: list[dict[str, Any]]


def get_citing_judgments(
    store: GraphStore,
    identifier: str,
    *,
    sort: str = "date",
    limit: int = 500,
    offset: int = 0,
) -> CitingJudgments:
    """``get_instrument_judgments`` and ``get_instrument_judgment_years`` at once."""
    page, years = run_together(
        lambda: get_instrument_judgments(
            store, identifier, sort=sort, limit=limit, offset=offset
        ),
        lambda: get_instrument_judgment_years(store, identifier),
    )
    items, total = cast("tuple[list[dict[str, Any]], int]", page)
    return CitingJudgments(items, total, cast("list[dict[str, Any]]", years))


# A prop only a conclusion has, read from its props for a conclusion alone: the props of a
# judgment hold its text, and are parsed whole for one value.
_OF_A_CONCLUSION = (
    "CASE WHEN j.pj_decision_kind #>> '{{}}' = %(conclusion)s "
    "THEN j.props -> '{prop}' END"
)


def get_instrument_judgment_years(
    store: GraphStore, identifier: str
) -> list[dict[str, Any]]:
    """``[{value, count}]``: the judgments that cite the law per year (of ``date_eff``),
    every one of them, not a page; the oldest first, those without a date first of all."""
    scope = scope_of(identifier)
    rows = store.query(
        _citing_judgments(scope.prop)
        + """
        SELECT substr(j.date_eff, 1, 4) AS value, count(*)::int AS count
        FROM grouped g JOIN judgments j ON j.id = g.judgment_id
        GROUP BY 1
        ORDER BY value NULLS FIRST
        """,
        {
            "bwb": scope.value,
            "refers_to": RELATION_REFERS_TO,
            "judgments": COLLECTION_JUDGMENTS,
        },
    )
    return [{"value": row["value"], "count": row["count"]} for row in rows]


def get_instrument_dossiers(
    store: GraphStore, identifier: str, *, limit: int = 500
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
    ctes = f"""
        WITH sources AS (
            SELECT %(instrument_id)s::text AS id
            UNION
            SELECT e.from_id FROM edges e
            WHERE e.to_id IN ({_articles_of(scope.prop)})
              AND e.relation = ANY(%(mutations)s)
        ),
        links AS (
            SELECT DISTINCT e.to_id AS dossier_id, e.from_id AS source_id
            FROM edges e
            WHERE e.from_id IN (SELECT id FROM sources)
              AND e.relation = %(legislated_in)s
              AND e.to_collection = %(dossiers)s
        ),
        grouped AS (
            SELECT d.id, d.key, d.type, d.labels, d.props, d.opened_on, d.number,
                   bool_or(l.source_id = %(instrument_id)s) AS direct
            FROM links l JOIN dossiers d ON d.id = l.dossier_id
            GROUP BY d.id
        )
    """
    # The publications of a dossier in the order of their id: ``_dossier_link`` picks the
    # newest of them.
    page = """
        SELECT g.id, g.key, g.type, g.labels, g.props, g.direct,
               (
                   SELECT coalesce(json_agg(json_build_object(
                       'key', s.key,
                       'identifier', s.props -> 'identifier',
                       'published', s.props -> 'date_published'
                   ) ORDER BY s.id), '[]')
                   FROM links l JOIN nodes s ON s.id = l.source_id
                   WHERE l.dossier_id = g.id AND l.source_id <> %(instrument_id)s
               ) AS publications,
               row_number() OVER (
                   ORDER BY g.opened_on DESC NULLS LAST, g.number NULLS FIRST, g.key
               ) AS n
        FROM grouped g
        ORDER BY n
        LIMIT %(limit)s
    """
    rows = store.query(
        ctes + _paged("grouped", page),
        {
            "bwb": scope.value,
            "instrument_id": instrument_id,
            "mutations": _MUTATION_RELATIONS,
            "legislated_in": RELATION_LEGISLATED_IN,
            "dossiers": COLLECTION_DOSSIERS,
            "limit": limit,
        },
    )
    items, total = _split_page(rows)
    groups = [
        {
            "dossier": node_doc(row),
            "direct": row["direct"],
            "publications": row["publications"],
        }
        for row in items
    ]
    return [_dossier_link(g) for g in groups], total


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
    store: GraphStore, identifier: str, *, limit: int = 50, offset: int = 0
) -> AmendedByData:
    """Amending instruments of a regulation, newest first (2 queries at most).

    One aggregating query over the AMENDS / INTRODUCES / REPEALS edges whose
    ``_to`` is an article of the regulation (the ``edges_to`` index is used with
    the article ids), grouped per amending instrument; a second bulk
    query resolves the titles of every dossier the page mentions.
    """
    scope = scope_of(identifier)
    ctes = f"""
        WITH hits AS (
            SELECT e.from_id,
                   (count(*) FILTER (WHERE e.relation = %(amends)s))::int AS amends,
                   (count(*) FILTER (WHERE e.relation = %(introduces)s))::int AS introduces,
                   (count(*) FILTER (WHERE e.relation = %(repeals)s))::int AS repeals,
                   count(DISTINCT e.to_id)::int AS articles_affected,
                   min(lg_str(e.doc -> 'meta' -> 'effective_date')) AS first_effective_date
            FROM edges e
            WHERE e.to_id IN ({_articles_of(scope.prop)})
              AND e.relation = ANY(%(mutations)s)
            GROUP BY e.from_id
        ),
        grouped AS (
            -- each amending node looked up by its id (a join with the view would read
            -- every table whole; LIMIT keeps the planner from turning it into one)
            SELECT d.id, d.key, d.type, d.labels, d.props,
                   h.amends, h.introduces, h.repeals, h.articles_affected,
                   h.first_effective_date
            FROM hits h
            CROSS JOIN LATERAL (
                SELECT n.id, n.key, n.type, n.labels, n.props FROM nodes n
                WHERE n.id = h.from_id
                LIMIT 1
            ) d
        )
    """
    page = """
        SELECT g.*, row_number() OVER (
            ORDER BY lg_str(g.props -> 'date_published') DESC NULLS LAST,
                     lg_str(g.props -> 'date_signed') DESC NULLS LAST,
                     g.key DESC
        ) AS n
        FROM grouped g
        ORDER BY n
        LIMIT %(limit)s OFFSET %(offset)s
    """
    rows = store.query(
        ctes + _paged("grouped", page),
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
    page_rows, total = _split_page(rows)
    items = [
        {
            "instrument": node_doc(row),
            "amends": row["amends"],
            "introduces": row["introduces"],
            "repeals": row["repeals"],
            "articles_affected": row["articles_affected"],
            "first_effective_date": row["first_effective_date"],
        }
        for row in page_rows
    ]
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
        total=total,
        dossier_titles=get_dossier_titles(store, numbers),
    )


def _reference_bucket(identity: str, own: str, other: str) -> str:
    """REFERS_TO edges between an article of the focal instrument (*own* end) and an
    article outside it (*other* end), counted per *identity* of the other article."""
    return f"""
        SELECT {identity} AS b, count(*)::int AS n
        FROM edges e JOIN articles x ON x.id = e.{other}
        WHERE e.relation = %(refers_to)s
          AND e.{own} IN (SELECT id FROM focal)
          AND e.{other} NOT IN (SELECT id FROM focal)
        GROUP BY 1
    """


def get_instrument_related_instruments(
    store: GraphStore, identifier: str, *, limit: int = 100
) -> tuple[list[dict[str, Any]], int]:
    """Other instruments related by cross-article REFERS_TO links.

    Returns ``{instrument, outbound_count, inbound_count}`` per related
    instrument, sorted by total reference count descending. The counterpart of a
    BWB regulation is a BWB regulation; the counterpart of an EU act is a BWB
    regulation or another EU act.
    """
    scope = scope_of(identifier)
    # The identity of the counterpart article of an edge, and how its instrument is found
    # again: by the indexed bwb_id / celex of the instruments, the first by key.
    if scope.prop == "bwb_id":
        identity = "x.bwb_id"
        find = "i.bwb_id = c.b"
    else:
        identity = "coalesce(x.bwb_id, x.celex)"
        find = "i.bwb_id = c.b OR i.celex = c.b"
    ctes = f"""
        WITH focal AS ({_articles_of(scope.prop)}),
        outbound AS ({_reference_bucket(identity, "from_id", "to_id")}),
        inbound AS ({_reference_bucket(identity, "to_id", "from_id")}),
        counts AS (
            SELECT b, coalesce(o.n, 0) AS outbound_count, coalesce(i.n, 0) AS inbound_count
            FROM outbound o FULL JOIN inbound i USING (b)
            WHERE b IS NOT NULL AND b <> %(bwb)s
        ),
        resolved AS (
            SELECT c.b, c.outbound_count, c.inbound_count,
                   inst.id, inst.key, inst.type, inst.labels, inst.props
            FROM counts c
            JOIN LATERAL (
                SELECT i.id, i.key, i.type, i.labels, i.props FROM instruments i
                WHERE {find}
                ORDER BY i.key
                LIMIT 1
            ) inst ON true
        )
    """
    # Two identities can find the same instrument (its bwb_id and its celex): the identity
    # settles that tie.
    page = """
        SELECT r.*, row_number() OVER (
            ORDER BY r.outbound_count + r.inbound_count DESC, r.key, r.b
        ) AS n
        FROM resolved r
        ORDER BY n
        LIMIT %(limit)s
    """
    rows = store.query(
        ctes + _paged("resolved", page),
        {"bwb": scope.value, "refers_to": RELATION_REFERS_TO, "limit": limit},
    )
    page_rows, total = _split_page(rows)
    items = [
        {
            "instrument": node_doc(row),
            "outbound_count": row["outbound_count"],
            "inbound_count": row["inbound_count"],
        }
        for row in page_rows
    ]
    return items, total


# The fields of the free-text search over the ``search_instruments`` view.
_SEARCH_FIELDS = [
    "title",
    "citation_title",
    "official_title",
    "display_name",
    "short_title",
    "bwb_id",
]


def get_instruments_list(
    store: GraphStore,
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
      * Free text (`q`) narrows the list by the search of ``queries/search.py``; the
        order stays the one asked for.
      * Filter fields (jurisdiction, kind, article_count) and the sort key
        for ``article_count`` are read from the props ``graph-list-stats``
        precomputes on the instrument document, each an indexed column.
      * ``total`` is exact: the instruments the filters let through (without
        filters every instrument but the publications).
    """
    # When q tokenises to nothing (single-char query, only punctuation), the
    # query degrades to "no filter".
    tokens = tokenize_search_query(q) if q else []
    search, words = build_search_clause(
        "instruments", tokens, _SEARCH_FIELDS, "instruments"
    )

    # The key settles ties. Each sort is one index in its order (``db/schema.py``), so a
    # page of the whole list is read from it without sorting the list.
    order = {
        "title": "citation_title NULLS FIRST, key",
        "article_count": "article_count DESC NULLS LAST, key DESC",
    }[sort]
    # Without a kind, every instrument but the publications (one without a kind too): the
    # condition of the list's indexes, written out so that every plan can use them.
    conditions = [
        "kind = %(kind)s" if kind else f"kind IS DISTINCT FROM '{KIND_PUBLICATION}'"
    ]
    if jurisdiction:
        conditions.append("jurisdiction = %(jurisdiction)s")
    if article_count_min is not None:
        conditions.append("article_count >= %(article_count_min)s")
    if tokens:
        conditions.append(f"({search})")
    matched = f"instruments WHERE {' AND '.join(conditions)}"
    page = f"""
        SELECT key, props, row_number() OVER (ORDER BY {order}) AS n
        FROM {matched}
        ORDER BY {order}
        LIMIT %(limit)s OFFSET %(offset)s
    """
    rows = store.query(
        _paged(matched, page),
        {
            "limit": limit,
            "offset": offset,
            "jurisdiction": jurisdiction.lower() if jurisdiction else None,
            "kind": kind.lower() if kind else None,
            "article_count_min": article_count_min,
            **words,
        },
    )
    items, total = _split_page(rows)
    listed = [_list_item(row) for row in items]
    coming = _next_versions(store, [i["bwb_id"] for i in listed if i["bwb_id"]])
    for item in listed:
        item["next_version_from"] = coming.get(item["bwb_id"] or "")
    return {"total": total, "items": listed}


_NEXT_VERSIONS = """
SELECT bwb_id, min(valid_from) AS valid_from FROM instrument_versions
WHERE bwb_id = ANY(%(bwb_ids)s) AND valid_from > %(today)s
GROUP BY bwb_id
"""


def _next_versions(store: GraphStore, bwb_ids: list[str]) -> dict[str, str]:
    """``bwb_id -> `` the start of its first toestand still to come, for the laws that
    have one: the date of the first coming change, as the BWB lists it."""
    if not bwb_ids:
        return {}
    rows = store.query(
        _NEXT_VERSIONS,
        {"bwb_ids": bwb_ids, "today": dt.date.today().isoformat()},
    )
    return {row["bwb_id"]: row["valid_from"] for row in rows}


def _list_item(row: dict[str, Any]) -> dict[str, Any]:
    """One instrument of the list, from its key and props."""
    props = row["props"] or {}
    key = row["key"]
    citation_title = next(
        (
            props[field]
            for field in ("citation_title", "title", "display_name")
            if props.get(field) is not None
        ),
        key,
    )
    display_name = props.get("display_name")
    return {
        "_id": f"{COLLECTION_INSTRUMENTS}/{key}",
        "_key": key,
        "bwb_id": props.get("bwb_id"),
        "celex": props.get("celex"),
        "title": props.get("title"),
        "short_title": props.get("short_title"),
        "kind": props.get("kind"),
        "citation_title": citation_title,
        "display_name": display_name if display_name is not None else citation_title,
        "jurisdiction": props.get("jurisdiction"),
        "article_count": props.get("article_count"),
        "inbound_citation_count": props.get("inbound_citation_count"),
        "uri": props.get("uri"),
        "publication_kind": props.get("publication_kind"),
        "publication_year": props.get("publication_year"),
        "publication_number": props.get("publication_number"),
    }


def get_instrument_versions(
    store: GraphStore,
    bwb_id: str,
) -> list[dict[str, Any]]:
    """Return all historical versions for an instrument, newest first."""
    rows = store.query(
        """
        SELECT id, key, type, labels, props FROM instrument_versions
        WHERE bwb_id = %(bwb_id)s
        ORDER BY valid_from DESC NULLS LAST, key DESC
        """,
        {"bwb_id": bwb_id.upper()},
    )
    return [node_doc(row) for row in rows]


@dataclass(frozen=True)
class LawOnADate:
    """The articles of a law in force on a date (a page of them), how many there are, and
    the start of the first toestand of the law."""

    items: list[dict[str, Any]]
    total: int
    first_version_from: str | None


def get_articles_at(
    store: GraphStore,
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
    # The start of the first toestand is the smallest valid_from, null first: a toestand
    # without a start, or none at all, leaves no law on any date. An article version
    # without a start began before any date; one without an end is in force still.
    matched = """
        article_versions v
        WHERE v.bwb_id = %(bwb_id)s
          AND EXISTS (SELECT 1 FROM earliest WHERE earliest.valid_from <= %(at_date)s)
          AND (v.valid_from <= %(at_date)s OR v.valid_from IS NULL)
          AND (v.valid_until > %(at_date)s
               OR v.valid_until_set IS NOT TRUE)
          AND coalesce(v.article_number, '') NOT LIKE 'bijlage %%'
    """
    page = f"""
        SELECT v.id, v.key, v.type, v.labels, v.props,
               row_number() OVER (ORDER BY {_document_order("v")}) AS n
        FROM {matched}
        ORDER BY n
        LIMIT %(limit)s OFFSET %(offset)s
    """
    statement = f"""
        WITH earliest AS (
            SELECT valid_from FROM instrument_versions
            WHERE bwb_id = %(bwb_id)s
            ORDER BY valid_from NULLS FIRST
            LIMIT 1
        )
        SELECT (SELECT valid_from FROM earliest) AS first_from, paged.*
        FROM ({_paged(matched, page)}) paged
        ORDER BY paged.n
    """
    bind = {
        "bwb_id": bwb_id.upper(),
        "at_date": at_date,
        "limit": limit,
        "offset": offset,
    }
    found = list(store.query(statement, bind))
    items, total = _split_page(found)
    return LawOnADate(
        items=[node_doc(row) for row in items],
        total=total,
        first_version_from=found[0]["first_from"] if found else None,
    )
