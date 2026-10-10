"""Judgment query helpers."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_RELATED_TO,
    RELATION_SAME_AS,
)
from lawgraph.core.identifiers import find_eclis
from lawgraph.core.judgments import case_number_keys
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from lawgraph.db._rows import node_doc
from lawgraph.db.queries._helpers import _load_judgment, run_together
from lawgraph.db.version_cache import lasting_rows


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
    # the judgments it cites (REFERS_TO), as slim documents
    cited_judgments: list[dict[str, Any]] = field(default_factory=list)
    # the other publications of the same decision (SAME_AS, either way), as slim documents
    same_as: list[dict[str, Any]] = field(default_factory=list)
    related_to: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # the other judgments of its series (``props.series_id``), as slim documents
    series: list[dict[str, Any]] = field(default_factory=list)
    # its conclusions (``props.conclusion_eclis``): ``{ecli, author, role, date}`` each
    conclusions: list[dict[str, Any]] = field(default_factory=list)


def get_judgment_with_relations(store: GraphStore, ecli: str) -> JudgmentDetailData:
    """Fetch a judgment and the articles it refers to.

    One query reads the REFERS_TO edges to articles with each article and, through its
    first PART_OF edge by target id, its instrument (None when that instrument is gone).
    The articles come in id order, the edge key settling two edges to one article.
    """
    judgment_doc = _load_judgment(store, ecli)
    if judgment_doc is None:
        raise ValueError("judgment not found")

    rows = store.query(
        """
        SELECT a.id, a.key, a.type, a.labels, a.props,
               n.id AS i_id, n.key AS i_key, n.type AS i_type, n.labels AS i_labels,
               n.props AS i_props,
               e.doc -> 'confidence' AS confidence, e.doc -> 'meta' AS meta
        FROM edges e
        JOIN articles a ON a.id = e.to_id
        LEFT JOIN LATERAL (
            SELECT ie.to_id FROM edges ie
            WHERE ie.from_id = a.id AND ie.relation = %(part_of)s
            ORDER BY ie.to_id
            LIMIT 1
        ) ie ON true
        LEFT JOIN nodes n ON n.id = ie.to_id
        WHERE e.from_id = %(jid)s AND e.relation = %(refers_to)s
          AND e.to_collection = 'articles'
        ORDER BY e.to_id, e.key
        """,
        {
            "jid": judgment_doc["_id"],
            "refers_to": RELATION_REFERS_TO,
            "part_of": RELATION_PART_OF,
        },
    )
    article_relations = [
        JudgmentArticleRelation(
            article=node_doc(r),
            instrument=_instrument(r),
            confidence=r["confidence"],
            meta=r["meta"] or {},
        )
        for r in rows
    ]

    metadata = {"article_count": len(article_relations)}
    series_id = (judgment_doc.get("props") or {}).get("series_id")
    return JudgmentDetailData(
        judgment=judgment_doc,
        articles=article_relations,
        cited_judgments=_linked_judgments(
            store, judgment_doc["_id"], RELATION_REFERS_TO, both_ways=False
        ),
        same_as=_linked_judgments(
            store, judgment_doc["_id"], RELATION_SAME_AS, both_ways=True
        ),
        related_to=_related_judgments(store, judgment_doc["_id"]),
        metadata=metadata,
        series=[
            doc
            for doc in get_series_members(store, series_id)
            if doc["_id"] != judgment_doc["_id"]
        ]
        if series_id
        else [],
        conclusions=_conclusions(
            store, (judgment_doc.get("props") or {}).get("conclusion_eclis")
        ),
    )


def _conclusions(store: GraphStore, eclis: Any) -> list[dict[str, Any]]:
    """``{ecli, author, role, date}`` of each conclusion a judgment names, in its order: the
    A-G or P-G and the date its light node gives (``lg_judgment_light``, never its text);
    a conclusion the graph lacks is its ECLI alone."""
    named = [str(e) for e in eclis or [] if e]
    if not named:
        return []
    ids = {f"{COLLECTION_JUDGMENTS}/{make_node_key(ecli)}": ecli for ecli in named}
    light = {
        row["id"]: row["light"] or {}
        for row in store.query(
            "SELECT id, props AS light FROM lg_judgment_light"
            " WHERE id = ANY(%(ids)s::text[])",
            {"ids": list(ids)},
        )
    }
    found = {ecli: light.get(node_id, {}) for node_id, ecli in ids.items()}
    return [
        {
            "ecli": ecli,
            "author": found[ecli].get("advocate_general"),
            "role": found[ecli].get("advocate_general_role"),
            "date": found[ecli].get("date"),
        }
        for ecli in named
    ]


def _instrument(row: dict[str, Any]) -> dict[str, Any] | None:
    if row["i_id"] is None:
        return None
    return node_doc(
        {f: row[f"i_{f}"] for f in ("id", "key", "type", "labels", "props")}
    )


def _linked_judgments(
    store: GraphStore, judgment_id: str, relation: str, *, both_ways: bool
) -> list[dict[str, Any]]:
    """The judgments an edge of *relation* leads to from *judgment_id* (and, *both_ways*,
    leads from to it), each once with its ``_id``, ``_key`` and the ``display_name`` and
    ``ecli`` of its props, newest first. Only those columns are read: a judgment is its
    text."""
    rows = store.query(
        """
        SELECT json_build_object(
            '_id', j.id,
            '_key', j.key,
            'props', json_build_object(
                'display_name', j.pj_display_name, 'ecli', j.pj_ecli
            )
        )
        FROM judgments j
        WHERE j.id IN (
            SELECT e.to_id FROM edges e
            WHERE e.from_id = %(jid)s AND e.relation = %(relation)s
              AND e.to_collection = 'judgments'
            UNION
            SELECT e.from_id FROM edges e
            WHERE %(both_ways)s AND e.to_id = %(jid)s AND e.relation = %(relation)s
        )
        ORDER BY j.date_eff DESC NULLS LAST, j.ecli NULLS FIRST, j.key
        """,
        {"jid": judgment_id, "relation": relation, "both_ways": both_ways},
    )
    return list(rows)


def _related_judgments(store: GraphStore, judgment_id: str) -> list[dict[str, Any]]:
    """The connected cases (``RELATED_TO``) of *judgment_id*, both ways, as
    ``_linked_judgments`` gives them, each with its ``links``: per edge the ``direction``
    (``outbound``: this judgment's summary names it; ``inbound``: its summary names this
    one) and the ``basis`` and ``text`` of the edge's meta, the sentence that names it."""
    rows = store.query(
        """
        WITH l AS (
            SELECT e.to_id AS id, 'outbound' AS direction, e.doc -> 'meta' AS meta
            FROM edges e
            WHERE e.from_id = %(jid)s AND e.relation = %(relation)s
              AND e.to_collection = 'judgments'
            UNION ALL
            SELECT e.from_id, 'inbound', e.doc -> 'meta'
            FROM edges e
            WHERE e.to_id = %(jid)s AND e.relation = %(relation)s
              AND e.from_collection = 'judgments'
        )
        SELECT json_build_object(
            '_id', j.id,
            '_key', j.key,
            'props', json_build_object(
                'display_name', j.pj_display_name, 'ecli', j.pj_ecli
            ),
            'links', (
                SELECT json_agg(json_build_object(
                    'direction', l.direction,
                    'basis', l.meta -> 'basis',
                    'text', l.meta -> 'text'
                ) ORDER BY l.direction DESC NULLS LAST)
                FROM l WHERE l.id = j.id
            )
        )
        FROM judgments j
        WHERE j.id IN (SELECT id FROM l)
        ORDER BY j.date_eff DESC NULLS LAST, j.ecli NULLS FIRST, j.key
        """,
        {"jid": judgment_id, "relation": RELATION_RELATED_TO},
    )
    return list(rows)


def get_series_members(store: GraphStore, series_id: str) -> list[dict[str, Any]]:
    """The judgments of a series (``semantic rechtspraak-series``), each with its ``_id``,
    ``_key`` and the ``display_name`` and ``ecli`` of its props (those it has, in the order
    of its props), in the order of their ECLI numbers (one court, one year: a shorter ECLI
    is a lower number)."""
    rows = store.query(
        """
        SELECT json_build_object(
            '_id', j.id,
            '_key', j.key,
            'props', coalesce(
                (SELECT json_object_agg(p.k, p.v ORDER BY p.n)
                 FROM json_each(j.props) WITH ORDINALITY AS p(k, v, n)
                 WHERE p.k IN ('display_name', 'ecli')),
                '{}'::json
            )
        )
        FROM judgments j
        WHERE j.series_id = %(series_id)s
        ORDER BY coalesce(char_length(j.ecli), 0), j.ecli NULLS FIRST, j.key
        """,
        {"series_id": series_id},
    )
    return list(rows)


@dataclass(frozen=True)
class JudgmentFilters:
    """What ``GET /api/judgments`` narrows the judgments to; None is no filter.

    *subject* is one of ``props.subjects`` as the source writes it: ``Strafrecht``,
    ``Bestuursrecht; Belastingrecht``. *procedure* is the procedure (psi:procedure) as the
    source writes it: ``Hoger beroep``, ``Cassatie``.
    """

    q: str | None = None
    court: str | None = None
    tier: str | None = None
    court_kind: str | None = None
    source: str | None = None
    subject: str | None = None
    # the main area of law: a subject up to its first ';' (``Bestuursrecht``)
    subject_area: str | None = None
    procedure: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    cited_by_min: int | None = None
    include_stubs: bool = False
    # an exact match of the whole of ``q``: its ECLI, or a key of its case number
    ecli: str | None = None
    case_number_key: str | None = None


# The filter a facet leaves out: each facet counts what choosing another value would give.
# Another tier drops the kind of court chosen within one.
_TIER_FILTERS = frozenset({"tier", "court_kind"})
_COURT_KIND_FILTERS = frozenset({"court_kind"})
_SOURCE_FILTERS = frozenset({"source"})
_YEAR_FILTERS = frozenset({"from", "to"})
_SUBJECT_FILTERS = frozenset({"subject"})
_SUBJECT_AREA_FILTERS = frozenset({"subject_area"})
_PROCEDURE_FILTERS = frozenset({"procedure"})

# filter -> its condition on the judgment ``j``. Each is served by an index on its column;
# a value of another type than the column holds (a date that is not a string) matches
# nothing.
_CLAUSES: dict[str, str] = {
    # a judgment known only because something cites it: no date, court or text
    "stubs": "j.stub IS NOT TRUE",
    # a publication of a decision that another one replaces: the decision is listed once
    "duplicates": "j.same_as IS NULL",
    "ecli": "j.ecli = %(ecli)s",
    "case_number": "j.case_number_keys @> ARRAY[%(case_number_key)s]::text[]",
    "court": "j.court_code = %(court)s",
    "tier": "j.tier = %(tier)s",
    "court_kind": "j.court_kind = %(court_kind)s",
    "source": "j.source = %(source)s",
    "subject": "j.subjects @> ARRAY[%(subject)s]::text[]",
    "subject_area": "lg_subject_areas(j.subjects) @> ARRAY[%(subject_area)s]::text[]",
    "procedure": "j.procedure = %(procedure)s",
    "from": "j.date_eff >= %(from)s",
    "to": "j.date_eff <= %(to)s",
    "cited_by_min": "j.inbound_citation_count >= %(cited_by_min)s",
}


def _judgment_filters(filters: JudgmentFilters, bind: dict[str, Any]) -> list[str]:
    """The filters (names in ``_CLAUSES``) *filters* sets, their values put in *bind*."""
    values: dict[str, tuple[str, Any]] = {
        "ecli": ("ecli", filters.ecli),
        "case_number": ("case_number_key", filters.case_number_key),
        "court": ("court", filters.court.upper() if filters.court else None),
        "tier": ("tier", filters.tier),
        "court_kind": ("court_kind", filters.court_kind),
        "source": ("source", filters.source),
        "subject": ("subject", filters.subject),
        "subject_area": ("subject_area", filters.subject_area),
        "procedure": ("procedure", filters.procedure),
        "from": ("from", filters.date_from),
        "to": ("to", filters.date_to),
    }
    names: list[str] = []
    if not filters.include_stubs:
        names.append("stubs")
    if not filters.ecli:
        names.append("duplicates")
    for name, (param, value) in values.items():
        if value:
            names.append(name)
            bind[param] = value
    if filters.cited_by_min is not None:
        names.append("cited_by_min")
        bind["cited_by_min"] = filters.cited_by_min
    return names


# The order of the list. The key settles ties; each sort is one index read in one
# direction. The inbound count lives on the indexed ``props.inbound_citation_count``, so
# no edge is counted on the list path.
_SORTS: dict[str, str] = {
    "date_desc": "j.date_eff DESC NULLS LAST, j.key DESC",
    "date_asc": "j.date_eff ASC NULLS FIRST, j.key ASC",
    "citation_count": "j.inbound_citation_count DESC NULLS LAST, j.key DESC",
}

# The fields words to find are looked for in.
_SEARCH_FIELDS = ["display_name", "names", "summary", "ecli"]

# A row of the list, in the order of its keys; ``ecli`` is the key when it has none.
_ITEM = """json_build_object(
    '_id', j.id,
    '_key', j.key,
    'ecli', CASE WHEN coalesce(json_typeof(j.pj_ecli), 'null') = 'null'
                 THEN to_json(j.key) ELSE j.pj_ecli END,
    'display_name', j.pj_display_name,
    'summary', j.pj_summary,
    'names', j.pj_names,
    'decision_kind', j.pj_decision_kind,
    'court_code', j.pj_court_code,
    'tier', j.pj_tier,
    'court_kind', j.pj_court_kind,
    'date', j.pj_date_eff,
    'source', j.pj_source,
    'subjects', j.pj_subjects,
    'inbound_citation_count', j.pj_inbound_citation_count,
    'outbound_citation_count', j.pj_outbound_citation_count,
    'series_id', j.pj_series_id,
    'series_size', j.pj_series_size
)"""


# facet -> the value it counts and the filters it leaves out. A judgment counts once for
# each of its areas of law (``subjects``).
# How long the facets and the total of a list are kept (seconds), whatever the data does:
# under a filter that holds a few hundred thousand judgments each reads them all, and a run
# of the pipelines hardly moves them. The page itself is read fresh.
FACETS_MAX_AGE = 3600.0

_FACETS: dict[str, tuple[str, frozenset[str]]] = {
    "tier": ("j.tier", _TIER_FILTERS),
    "court_kind": ("j.court_kind", _COURT_KIND_FILTERS),
    "source": ("j.source", _SOURCE_FILTERS),
    "year": ("substr(j.date_eff, 1, 4)", _YEAR_FILTERS),
    "subjects": ("s.value", _SUBJECT_FILTERS),
    # the tree of the areas of law: main areas and the subjects under them (``narrower``),
    # counted alike, without the ``subject_area`` and ``subject`` filters
    "subject_area": ("a.value", _SUBJECT_AREA_FILTERS | _SUBJECT_FILTERS),
    "procedure": ("j.procedure", _PROCEDURE_FILTERS),
}
# what a facet reads besides the judgment; a judgment counts once per area of law
_FACET_JOINS = {
    "subjects": "CROSS JOIN LATERAL unnest(j.subjects) AS s(value)",
    "subject_area": "CROSS JOIN LATERAL unnest(lg_subject_areas(j.subjects)) AS a(value)",
}


def get_judgments_list(
    store: GraphStore,
    filters: JudgmentFilters | None = None,
    *,
    sort: str = "date_desc",
    limit: int = 50,
    offset: int = 0,
    facets: bool = True,
) -> dict[str, Any]:
    """Paginated, filterable list of judgments, with facets (``facets=False``: the page and
    the total alone, ``facets`` None).

    Performance strategy mirrors ``get_instruments_list``:
      * Free text (``q``) narrows the list and every count by the search of
        ``queries/search.py``; the order stays the one asked for.
      * ``tier``, ``court_kind``, ``court_code``, ``date_eff``, ``source`` and ``subjects`` are
        read from the props the normalize pipelines write, each a column with an index.
      * ``total`` is exact when filtered, otherwise the table count less the stubs and the
        replaced publications. The frontend uses ``has_more`` for paging.
      * ``facets`` counts per ``tier`` (without the tier and court_kind filters), per
        ``court_kind`` (without the court_kind filter), per ``source`` (without the
        source filter), per year of ``date_eff`` (without ``from`` and ``to``), per area of
        law (``subjects``, without the ``subject`` filter; a judgment counts for each of
        its areas), per main area of law (``subject_area``, the part of a subject before
        its first ';', without the ``subject_area`` and ``subject`` filters, as its ``narrower``
        subjects; a judgment counts once for each)
        and per ``procedure`` (without its filter); the values by count, most
        first, then by value; the years by year.
    """
    from lawgraph.db.queries.search import build_search_clause, tokenize_search_query

    filters = filters or JudgmentFilters()
    exact = _exact_filters(filters)
    if exact is not None:
        found = get_judgments_list(
            store, exact, sort=sort, limit=limit, offset=offset, facets=facets
        )
        if found["total"]:
            return found
    tokens = tokenize_search_query(filters.q) if filters.q else []

    order = _SORTS[sort]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    names = _judgment_filters(filters, params)
    # Words to find narrow every count as they narrow the list.
    search: list[str] = []
    if tokens:
        clause, words = build_search_clause("judgments", tokens, _SEARCH_FIELDS, "j")
        search = [clause]
        params.update(words)

    def where(leave_out: frozenset[str] = frozenset()) -> str:
        conditions = [_CLAUSES[n] for n in names if n not in leave_out] + search
        return f"WHERE {' AND '.join(conditions)}" if conditions else ""

    def facet(name: str) -> Callable[[], list[Any]]:
        value, leave_out = _FACETS[name]
        by_count = "" if name == "year" else "count DESC, "
        join = _FACET_JOINS.get(name, "")
        return lambda: lasting_rows(
            store,
            f"""
            SELECT {value} AS value, count(*)::int AS count
            FROM judgments j {join} {where(leave_out)}
            GROUP BY 1
            ORDER BY {by_count}value NULLS FIRST
            """,
            _without_page(params),
            max_age=FACETS_MAX_AGE,
        )

    def narrower() -> list[Any]:
        leave_out = _SUBJECT_AREA_FILTERS | _SUBJECT_FILTERS
        return lasting_rows(
            store,
            f"""
            SELECT value, count(*)::int AS count
            FROM (
                SELECT s.value FROM judgments j
                CROSS JOIN LATERAL unnest(j.subjects) AS s(value) {where(leave_out)}
            ) subjects
            WHERE strpos(value, ';') > 0
            GROUP BY 1
            ORDER BY count DESC, value NULLS FIRST
            """,
            _without_page(params),
            max_age=FACETS_MAX_AGE,
        )

    filtered = [*names, *(["search"] if search else [])]
    # A search that finds few judgments sorts its hits; one that finds many reads the
    # list in the order of an index (``_page``). The total (kept) tells which.
    hits_first = bool(search) and (
        _total(store, filtered, where(), params) <= SORTED_HITS_MAX
    )

    def items() -> list[Any]:
        return _page(store, order, where(), params, hits_first=hits_first)

    if not facets:
        page, total = run_together(
            items, lambda: _total(store, filtered, where(), params)
        )
        return {"total": total, "items": page, "facets": None}
    answers: list[Any] = run_together(
        items,
        *(facet(name) for name in _FACETS),
        narrower,
        lambda: _total(store, filtered, where(), params),
    )
    counted = dict(zip(_FACETS, answers[1:-2], strict=True))
    counted["subject_area"] = _with_narrower(counted["subject_area"], answers[-2])
    result: dict[str, Any] = {
        "total": answers[-1],
        "items": answers[0],
        "facets": counted,
    }
    return result


# The most hits of a search that are found first and then sorted (``_page``). Past them
# they are at least one in twenty judgments, and a page in the order of an index finds
# its rows by testing twenty for each.
SORTED_HITS_MAX = 50_000


def _page(
    store: GraphStore,
    order: str,
    where: str,
    params: dict[str, Any],
    *,
    hits_first: bool,
) -> list[Any]:
    """A page of the judgments *where* lets through, in *order*: the rows of the page are
    chosen first, and only theirs are built into items, read again by their place
    (``ctid``): one read of a page the choosing read already, where a lookup by id walked
    the primary key for each row (four times the reads of the choosing itself, the most of a
    cold page). With *hits_first* the rows are found by the indexes of *where* (the words of
    a search) and then sorted: in the order of an index the planner would test every
    judgment of the list for the words of a rare one, and finds the page only after reading
    nearly the whole table (``pacht``: 317 of a million)."""
    hits = ""
    rows = f"judgments j {where}"
    if hits_first:
        hits = f"""WITH hits AS MATERIALIZED (
            SELECT j.ctid AS row_id, j.key, j.date_eff, j.inbound_citation_count
            FROM judgments j {where}
        )"""
        rows = "hits j"
    row_id = "j.row_id" if hits_first else "j.ctid"
    return list(
        store.query(
            f"""
            -- a ctid is the place of a row in this snapshot: the rows chosen and the join
            -- that reads them are one statement, so no row has moved between the two
            {hits}
            SELECT {_ITEM}
            FROM (
                SELECT {row_id} AS row_id, row_number() OVER (ORDER BY {order}) AS n
                FROM {rows}
                ORDER BY {order}
                LIMIT %(limit)s OFFSET %(offset)s
            ) page
            JOIN judgments j ON j.ctid = page.row_id
            ORDER BY page.n
            """,
            params,
        )
    )


def _with_narrower(
    areas: list[dict[str, Any]], subjects: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The main areas of law, each with the subjects of the source under it (``value``
    the subject as written, ``label`` the part after its first ';')."""
    under: dict[str, list[dict[str, Any]]] = {}
    for row in subjects:
        main, _, rest = str(row["value"]).partition(";")
        under.setdefault(main.strip(), []).append(
            {"value": row["value"], "label": rest.strip(), "count": row["count"]}
        )
    return [{**area, "narrower": under.get(str(area["value"]), [])} for area in areas]


def _total(
    store: GraphStore, names: list[str], where: str, params: dict[str, Any]
) -> int:
    """How many judgments the filters let through. Unfiltered it is the table count less
    the stubs and less the replaced publications, each by its index (a stub that is also
    replaced is taken off twice, as before)."""
    if set(names) == {"stubs", "duplicates"}:
        statement = """
            SELECT (SELECT count(*) FROM judgments)
                 - (SELECT count(*) FROM judgments WHERE stub IS TRUE)
                 - (SELECT count(*) FROM judgments WHERE same_as IS NOT NULL)
            """
    else:
        statement = f"SELECT count(*) FROM judgments j {where}"
    return int(
        lasting_rows(store, statement, _without_page(params), max_age=FACETS_MAX_AGE)[0]
    )


def _without_page(params: dict[str, Any]) -> dict[str, Any]:
    """*params* without the page: the counts are the same on every page, and are kept per
    data version (``version_cache``) under the filters alone."""
    return {k: v for k, v in params.items() if k not in ("limit", "offset")}


# A case number as a query: a token with a digit and a slash or dash, as courts write them
# ("18/04298", "C/19/117301 / HA ZA 16-256", "200.335.407/01").
_CASE_NUMBER_QUERY = re.compile(r"^(?=.*\d)(?=.*[/-])[\w./ -]{3,60}$")


def _exact_filters(filters: JudgmentFilters) -> JudgmentFilters | None:
    """*filters* with ``q`` read as the whole of an ECLI or a case number, or None when
    ``q`` is neither. An exact match is the answer; words are searched when none is."""
    q = (filters.q or "").strip()
    if not q:
        return None
    eclis = find_eclis(q)
    if len(eclis) == 1 and eclis[0] == q.upper():
        return replace(filters, q=None, ecli=eclis[0])
    keys = case_number_keys(q)
    if len(keys) == 1 and _CASE_NUMBER_QUERY.match(q):
        return replace(filters, q=None, case_number_key=keys[0])
    return None
