"""The query behind the news feed (``GET /api/feed``): the dated events of the graph, newest
first, in one AQL.

Every kind of event is read from one collection (``_SOURCES``) as a light row: its date,
id, dossiers, ministry, the people who signed it and their factions. The rows of the kinds
are merged, sorted by date and id (both descending) and cut after the cursor; only the rows
of the page are then read in full.

With ``facets`` every row under the filters is read, since a facet counts all of them: the
facets (``kind``, ``ministry``, ``faction``, ``cabinet``) each without their own filter, the
total and the page are made from that one read. Without, each kind reads its rows in date
order from its index and stops after one page.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, cast

from lawgraph.config.constants import (
    CHAMBER_TK,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CABINETS,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_MEMBERS,
    RELATION_ABOUT,
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_PART_OF,
    RELATION_REPEALS,
)
from lawgraph.core.bwb_xml import KIND_PUBLICATION as INSTRUMENT_KIND_PUBLICATION
from lawgraph.core.feed import (
    DOCUMENT_KINDS,
    EVENT_BILL,
    EVENT_COMMENCEMENT,
    EVENT_COMMITMENT,
    EVENT_PUBLICATION,
    EVENT_VOTE,
    EXPLANATORY_MEMORANDUM,
    FEED_KINDS,
    FIRST_SIGNATORY,
    KIND_RANK,
    FeedCursor,
)
from lawgraph.core.tk_records import CAPACITY_GOVERNMENT, CAPACITY_MEMBER
from lawgraph.db import ArangoStore

# The instruments a publication names at most.
MAX_CHANGED_INSTRUMENTS = 10
# The end of every date range: after any ISO date.
_NO_END = "￿"
# The props of the page's nodes the items show; never the text of a paper.
_ITEM_PROPS = (
    "kind",
    "title",
    "subject",
    "display_name",
    "document_number",
    "status",
    "expected_resolution",
    "minister_name",
    "decision_text",
    "passed",
    "tally",
    "vote_kind",
    "citation_title",
    "publication_kind",
    "publication_year",
    "publication_number",
    "bwb_id",
    "valid_from",
)


@dataclass(frozen=True)
class FeedFilters:
    """What the feed keeps; None keeps everything.

    *dossier* is a prefix of a dossier label (``36600`` holds ``36600-VII``); *member* a
    member key, *faction* a faction key, *cabinet* a cabinet key (the events in its period),
    *q* words of the title or of the title of the event's dossier, in any case.
    """

    kinds: tuple[str, ...] | None = None
    since: str | None = None
    until: str | None = None
    cabinet: str | None = None
    ministry: str | None = None
    dossier: str | None = None
    member: str | None = None
    faction: str | None = None
    q: str | None = None


@dataclass(frozen=True)
class _Source:
    """How the events of one kind are read: from *collection*, dated by ``props.<date>``,
    kept by *where* (on ``n``). The other fields are AQL expressions on ``n``: its
    dossier labels, its signatures (``person_id``, ``member_key``, ``name``, ``role``,
    ``capacity``, ``faction_id``; None when nobody signs this kind), its title, and its own
    ministry (None: the ministry of its first dossier). A row looks its signatures up only
    when a filter or a facet needs them."""

    kind: str
    collection: str
    date: str
    where: str
    dossiers: str
    persons: str | None
    title: str
    ministry: str | None = None


_DOSSIER_NUMBERS = "n.props.dossier_numbers OR []"

_COMMITMENT_DOSSIERS = f"""(
            FOR e IN {COLLECTION_EDGES}
                FILTER e._from == n._id AND e.relation == "{RELATION_ABOUT}"
                FILTER STARTS_WITH(e._to, "{COLLECTION_DOSSIERS}/")
                LET d = DOCUMENT(e._to)
                FILTER d != null
                SORT d.props.label
                RETURN d.props.label
        )"""

_COMMITMENT_PERSONS = f"""[{{
            member_key: n.props.member_key,
            name: n.props.minister_name,
            function: n.props.minister_role,
            role: "{FIRST_SIGNATORY}",
            capacity: "{CAPACITY_GOVERNMENT}"
        }}]"""

# The signatures of the document a vote decided: a paper of the case it singled out, the
# newest that has signatures. A case key is its TK GUID made a node key (lower case, ``_``).
_DECIDED_PERSONS = f"""(FIRST(
            FOR e IN {COLLECTION_EDGES}
                FILTER {{guard}}
                FILTER e._to == CONCAT(
                    "{COLLECTION_CASES}/",
                    SUBSTITUTE(LOWER(n.props.primary_case_id), "-", "_")
                )
                FILTER e.relation == "{RELATION_PART_OF}"
                FILTER STARTS_WITH(e._from, "{COLLECTION_DOCUMENTS}/")
                LET paper = DOCUMENT(e._from)
                FILTER LENGTH(paper.props.actors) > 0
                SORT paper.props.date DESC, paper._key DESC
                LIMIT 1
                RETURN paper.props.actors
        ) OR [])"""


# The signatures of a bill: its own, else those of the first memorie van toelichting of its
# dossier, which the source signs where it leaves the voorstel itself unsigned. ``{label}``
# is the bill's first dossier label.
_BILL_PERSONS = f"""(LENGTH(n.props.actors) > 0 ? n.props.actors : (FIRST(
            FOR o IN {COLLECTION_DOCUMENTS}
                FILTER {{guard}}
                FILTER {{label}} != null AND {{label}} IN o.props.dossier_numbers[*]
                FILTER STARTS_WITH(o.props.kind, "{EXPLANATORY_MEMORANDUM}")
                FILTER LENGTH(o.props.actors) > 0
                SORT o.props.date, o._key
                LIMIT 1
                RETURN o.props.actors
        ) OR []))"""


def _document_source(kind: str, document_kinds: tuple[str, ...]) -> _Source:
    persons = "n.props.actors OR []"
    if kind == EVENT_BILL:
        persons = _BILL_PERSONS.replace("{guard}", "true").replace(
            "{label}", "labels[0]"
        )
    return _Source(
        kind=kind,
        collection=COLLECTION_DOCUMENTS,
        date="date",
        where=(
            f"n.props.kind IN {json.dumps(list(document_kinds))}"
            # not `IN n.labels`: the index on the labels holds nearly every paper, and
            # the one on the kind and the date is the one to read
            f' AND POSITION(n.labels, "{CHAMBER_TK}")'
        ),
        dossiers=_DOSSIER_NUMBERS,
        persons=persons,
        title="n.props.subject OR n.props.title",
    )


_SOURCES: dict[str, _Source] = {
    source.kind: source
    for source in (
        _Source(
            kind=EVENT_COMMITMENT,
            collection=COLLECTION_COMMITMENTS,
            date="made_on",
            where="true",
            dossiers=_COMMITMENT_DOSSIERS,
            persons=_COMMITMENT_PERSONS,
            title="n.props.text",
            ministry="n.props.ministry",
        ),
        *(_document_source(kind, kinds) for kind, kinds in DOCUMENT_KINDS.items()),
        _Source(
            kind=EVENT_VOTE,
            collection=COLLECTION_DECISIONS,
            date="date",
            where="IS_BOOL(n.props.passed)",  # read by date, not by the outcome
            dossiers=_DOSSIER_NUMBERS,
            persons=_DECIDED_PERSONS.replace("{guard}", "true"),
            title="n.props.subject",
        ),
        _Source(
            kind=EVENT_PUBLICATION,
            collection=COLLECTION_INSTRUMENTS,
            date="date_published",
            where=f'n.props.kind == "{INSTRUMENT_KIND_PUBLICATION}"',
            dossiers=_DOSSIER_NUMBERS,
            persons=None,
            title="n.props.citation_title",
        ),
        _Source(
            kind=EVENT_COMMENCEMENT,
            collection=COLLECTION_INSTRUMENT_VERSIONS,
            date="valid_from",
            where="true",
            dossiers="[]",
            persons=None,
            title=(
                f"FIRST(FOR i IN {COLLECTION_INSTRUMENTS}"
                " FILTER i._key == LOWER(n.props.bwb_id)"
                " RETURN i.props.citation_title OR i.props.title)"
            ),
        ),
    )
}

# The dimensions that are counted as facets; each is a filter on ``row`` too.
_DIMENSIONS = ("kind", "ministry", "faction", "cabinet")

# What every request reads first: factions by the ids of their Fractie records and the
# cabinets, newest first. (A map of every dossier would be copied for each row that reads
# it; a row looks its dossier up by the index on the label instead.)
_PREAMBLE = f"""
    LET faction_pairs = (
        FOR f IN {COLLECTION_FACTIONS}
            FOR id IN UNIQUE(APPEND(f.props.external_ids OR [], [f.props.external_id]))
                FILTER id != null
                RETURN [id, {{ key: f._key, short: f.props.abbreviation OR f.props.name }}]
    )
    LET faction_of = ZIP(faction_pairs[*][0], faction_pairs[*][1])
    LET cabinet_starts = (
        FOR c IN {COLLECTION_CABINETS}
            FILTER c.props.from_date != null
            SORT c.props.from_date DESC
            RETURN {{ key: c._key, from: c.props.from_date }}
    )
"""

# The period of the cabinet asked for: from its beëdiging to that of the next one.
_CABINET_PERIOD = f"""
    LET cabinet_from = FIRST(
        FOR c IN {COLLECTION_CABINETS} FILTER c._key == @cabinet RETURN c.props.from_date
    )
    LET cabinet_until = FIRST(
        FOR c IN {COLLECTION_CABINETS}
            FILTER cabinet_from != null AND c.props.from_date > cabinet_from
            SORT c.props.from_date
            LIMIT 1
            RETURN c.props.from_date
    ) OR "{_NO_END}"
"""

_MEMBER_PERSON = f"""
    LET member_person = FIRST(
        FOR m IN {COLLECTION_MEMBERS} FILTER m._key == @member RETURN m.props.external_id
    )
"""

# The ministry and title of the first dossier of a row.
_FIRST_DOSSIER = f"""FIRST(
                FOR d IN {COLLECTION_DOSSIERS}
                    FILTER labels[0] != null AND d.props.label != null AND d.props.label == labels[0]
                    LIMIT 1
                    RETURN {{ ministry: d.props.ministry, title: d.props.title }}
            )"""


def _dimension_filters(filters: FeedFilters, bind: dict[str, Any]) -> dict[str, str]:
    """The filter of each facet dimension that is asked for, on ``row``."""
    clauses: dict[str, str] = {}
    if filters.kinds:
        clauses["kind"] = "row.kind IN @kinds"
        bind["kinds"] = list(filters.kinds)
    if filters.ministry:
        clauses["ministry"] = "row.ministry == @ministry"
        bind["ministry"] = filters.ministry
    if filters.faction:
        clauses["faction"] = "@faction IN row.factions"
        bind["faction"] = filters.faction
    if filters.cabinet:
        clauses["cabinet"] = (
            "cabinet_from != null AND row.date >= cabinet_from"
            " AND row.date < cabinet_until"
        )
        bind["cabinet"] = filters.cabinet
    return clauses


def _shared_filters(filters: FeedFilters, bind: dict[str, Any]) -> list[str]:
    """The filters that hold for every facet, on the variables of a kind's loop:
    ``labels`` (of its dossiers), ``persons``, ``title`` and ``first_dossier``."""
    clauses: list[str] = []
    if filters.dossier:
        clauses.append("LENGTH(labels[* FILTER STARTS_WITH(CURRENT, @dossier)]) > 0")
        bind["dossier"] = filters.dossier
    if filters.member:
        clauses.append(
            "@member IN persons[*].member_key"
            " OR (member_person != null AND member_person IN persons[*].person_id)"
        )
        bind["member"] = filters.member
    if filters.q:
        clauses.append(
            "CONTAINS(LOWER(title), @q) OR CONTAINS(LOWER(first_dossier.title), @q)"
        )
        bind["q"] = filters.q.strip().lower()
    return clauses


def _kinds_to_read(filters: FeedFilters, *, facets: bool) -> list[_Source]:
    """The kinds whose rows are read: those asked for (all of them for the facets, which
    count every kind), without those that cannot have the member or faction asked for."""
    chosen = FEED_KINDS if facets or not filters.kinds else filters.kinds
    sources = [_SOURCES[kind] for kind in FEED_KINDS if kind in chosen]
    if filters.member or filters.faction:
        sources = [s for s in sources if s.persons is not None]
    if filters.faction:
        sources = [s for s in sources if s.kind != EVENT_COMMITMENT]
    return sources


def _where(clauses: list[str] | tuple[str, ...], indent: str) -> str:
    return "".join(f"\n{indent}FILTER {clause}" for clause in clauses)


@dataclass(frozen=True)
class _Plan:
    """What the rows of one request are read under."""

    filters: FeedFilters
    facets: bool
    shared: list[str]
    dimensions: dict[str, str]
    cursor: FeedCursor | None

    @property
    def needs_factions(self) -> bool:
        return self.facets or bool(self.filters.faction)

    @property
    def needs_persons(self) -> bool:
        return self.needs_factions or bool(self.filters.member)


# The factions a row counts for: those its Kamerleden signed for.
_FACTIONS = f"""UNIQUE(
                FOR p IN persons
                    FILTER p.capacity == "{CAPACITY_MEMBER}"
                    LET faction = faction_of[p.faction_id]
                    FILTER faction != null
                    RETURN faction.key
            )"""


# The order of the feed: newest day first, within a day by the rank of the kind
# (``core.feed.DAY_ORDER``), then by id.
_ORDER = "row.date DESC, row.rank, row.id"


def _after_cursor(source: _Source, cursor: FeedCursor) -> str:
    """The events of *source* on the cursor's day that come after it: all when its kind
    ranks after the cursor's, none when before, those with a greater id when the same. A
    ternary, not an OR: ArangoDB 3.12 splits such an OR into two ranges of the index and
    loses events of the cursor's day."""
    rank = KIND_RANK[source.kind]
    later = (
        "true"
        if rank > cursor.rank
        else "false"
        if rank < cursor.rank
        else "n._id > @cursor_id"
    )
    return f"(n.props.{source.date} == @cursor_date ? {later} : true)"


def _rows_query(source: _Source, plan: _Plan, index: int) -> str:
    """``LET rows_<index> = (...)``: the light rows of one kind, ``{kind, id, date,
    dossier, ministry, factions}``. Without facets a kind reads one page, newest first,
    from the index on its date: before anything else is looked up when no filter needs
    it."""
    date = f"n.props.{source.date}"
    indent = " " * 12
    head = [f"{date} >= @since AND {date} <= @until", source.where]
    lets = [f"LET labels = {source.dossiers}"]
    if source.dossiers != "[]" and (source.ministry is None or plan.filters.q):
        lets.append(f"LET first_dossier = {_FIRST_DOSSIER}")
    else:
        lets.append("LET first_dossier = null")
    if plan.needs_persons:
        lets.append(f"LET persons = {source.persons or '[]'}")
    if plan.filters.q:
        lets.append(f"LET title = {source.title}")
    factions = _FACTIONS if plan.needs_factions and source.persons else "[]"
    tail = list(plan.shared)
    order = early = ""
    if not plan.facets:
        tail += [
            plan.dimensions[d] for d in ("ministry", "faction") if d in plan.dimensions
        ]
        if plan.filters.cabinet:
            head.append(
                f"cabinet_from != null AND {date} >= cabinet_from"
                f" AND {date} < cabinet_until"
            )
        if plan.cursor is not None:
            head.append(_after_cursor(source, plan.cursor))
        order = f"\n{indent}SORT {date} DESC, n._id\n{indent}LIMIT @page_size"
        if not tail:
            early, order = order, ""
    body = "".join(f"\n{indent}{let}" for let in lets)
    return f"""
    LET rows_{index} = (
        FOR n IN {source.collection}{_where(head, indent)}{early}{body}
            LET row = {{
                kind: "{source.kind}",
                rank: {KIND_RANK[source.kind]},
                id: n._id,
                date: {date},
                dossier: labels[0],
                ministry: {source.ministry or "first_dossier.ministry"},
                factions: {factions}
            }}{_where(tail, indent)}{order}
            RETURN row
    )"""


def _facet(plan: _Plan, name: str) -> str:
    """A facet: the rows under every filter but its own, counted per value."""
    others = [clause for dim, clause in plan.dimensions.items() if dim != name]
    where = _where(others, " " * 12)
    if name == "cabinet":
        return f"""(
        FOR row IN rows{where}
            COLLECT date = row.date WITH COUNT INTO n
            LET cabinet = FIRST(
                FOR c IN cabinet_starts FILTER c.from <= date LIMIT 1 RETURN c.key
            )
            COLLECT value = cabinet AGGREGATE count = SUM(n)
            SORT count DESC, value
            RETURN {{ value, count }}
    )"""
    value = {
        "kind": "row.kind",
        "ministry": "row.ministry",
        "faction": "LENGTH(row.factions) > 0 ? row.factions : [null]",
    }[name]
    loop = f"\n            FOR faction IN {value}" if name == "faction" else ""
    collect = "value = faction" if name == "faction" else f"value = {value}"
    return f"""(
        FOR row IN rows{where}{loop}
            COLLECT {collect} WITH COUNT INTO count
            SORT count DESC, value
            RETURN {{ value, count }}
    )"""


def _page_query(plan: _Plan) -> str:
    """``LET page``, and with facets ``total`` and ``facets``."""
    if not plan.facets:
        return f"""
    LET page = (FOR row IN rows SORT {_ORDER} LIMIT @page_size RETURN row)
    LET total = null
    LET facets = null"""
    after = ""
    if plan.cursor is not None:
        after = (
            "\n            FILTER row.date < @cursor_date OR (row.date == @cursor_date"
            " AND (row.rank > @cursor_rank"
            " OR (row.rank == @cursor_rank AND row.id > @cursor_id)))"
        )
    facets = ",\n        ".join(f"{name}: {_facet(plan, name)}" for name in _DIMENSIONS)
    return f"""
    LET matching = (
        FOR row IN rows{_where(list(plan.dimensions.values()), " " * 12)}
            RETURN row
    )
    LET page = (
        FOR row IN matching{after}
            SORT {_ORDER}
            LIMIT @page_size
            RETURN row
    )
    LET total = LENGTH(matching)
    LET facets = {{
        {facets}
    }}"""


# The signatures of an event on the page, by its kind.
_VOTE_SIGNATURES = _DECIDED_PERSONS.replace("{guard}", f'row.kind == "{EVENT_VOTE}"')
_BILL_SIGNATURES = _BILL_PERSONS.replace(
    "{guard}", f'row.kind == "{EVENT_BILL}"'
).replace("{label}", "row.dossier")
_SIGNATURES = f"""row.kind == "{EVENT_COMMITMENT}" ? {_COMMITMENT_PERSONS}
                : row.kind == "{EVENT_VOTE}" ? {_VOTE_SIGNATURES}
                : row.kind == "{EVENT_BILL}" ? {_BILL_SIGNATURES}
                : (n.props.actors OR [])"""

# The page, read in full: the node's props, its first dossier, the cabinet on its date, the
# signatures with their factions, and what a kind adds (who made a commitment, the laws a
# publication changes, the law and the articles a new version puts in force).
_ITEMS = f"""
    LET items = (
        FOR row IN page
            LET n = DOCUMENT(row.id)
            LET dossier = FIRST(
                FOR d IN {COLLECTION_DOSSIERS}
                    FILTER d.props.label != null AND d.props.label == row.dossier
                    LIMIT 1
                    RETURN {{ key: d._key, number: d.props.label, title: d.props.title }}
            )
            LET signatures = {_SIGNATURES}
            LET instrument = row.kind == "{EVENT_COMMENCEMENT}"
                ? DOCUMENT({COLLECTION_INSTRUMENTS}, LOWER(n.props.bwb_id)) : null
            LET changed_articles = LENGTH(
                FOR v IN {COLLECTION_ARTICLE_VERSIONS}
                    FILTER row.kind == "{EVENT_COMMENCEMENT}"
                    FILTER n.props.bwb_id != null AND v.props.bwb_id == n.props.bwb_id
                    FILTER v.props.valid_from == n.props.valid_from
                    RETURN 1
            )
            LET changed_instruments = (
                FOR e IN {COLLECTION_EDGES}
                    FILTER row.kind == "{EVENT_PUBLICATION}"
                    FILTER e._from == row.id
                    FILTER e.relation IN [
                        "{RELATION_AMENDS}", "{RELATION_INTRODUCES}", "{RELATION_REPEALS}"
                    ]
                    LET target = PARSE_IDENTIFIER(e._to)
                    LET key = target.collection == "{COLLECTION_ARTICLES}"
                        ? LOWER(DOCUMENT(e._to).props.bwb_id) : target.key
                    COLLECT instrument_key = key
                    LET changed = DOCUMENT({COLLECTION_INSTRUMENTS}, instrument_key)
                    FILTER changed != null
                    SORT changed.props.citation_title, instrument_key
                    LIMIT {MAX_CHANGED_INSTRUMENTS}
                    RETURN {{
                        key: changed._key,
                        title: changed.props.citation_title OR changed.props.title,
                        bwb_id: changed.props.bwb_id
                    }}
            )
            RETURN {{
                kind: row.kind,
                id: row.id,
                date: row.date,
                ministry: row.ministry,
                cabinet: FIRST(
                    FOR c IN cabinet_starts FILTER c.from <= row.date LIMIT 1 RETURN c.key
                ),
                dossier: dossier,
                props: KEEP(n.props, {json.dumps(list(_ITEM_PROPS))}),
                text: row.kind == "{EVENT_COMMITMENT}" ? n.props.text : null,
                persons: (
                    FOR p IN signatures OR []
                        // a member's key is its TK GUID made a node key (lower case, _)
                        LET key = p.member_key OR (p.person_id != null
                            ? SUBSTITUTE(LOWER(p.person_id), "-", "_") : null)
                        LET person = key != null
                            ? DOCUMENT({COLLECTION_MEMBERS}, key) : null
                        RETURN MERGE(p, {{
                            member_key: key,
                            member_name: person.props.name OR person.props.known_as
                                OR person.props.government_name,
                            faction: faction_of[p.faction_id]
                        }})
                ),
                instrument: instrument != null ? {{
                    key: instrument._key,
                    title: instrument.props.citation_title OR instrument.props.title,
                    bwb_id: instrument.props.bwb_id,
                    article_count: instrument.props.article_count
                }} : null,
                changed_articles: changed_articles,
                changed_instruments: changed_instruments
            }}
    )
    RETURN {{ items: items, total: total, facets: facets }}
"""


def feed_query(
    filters: FeedFilters,
    *,
    cursor: FeedCursor | None = None,
    limit: int = 50,
    facets: bool = True,
) -> tuple[str, dict[str, Any]]:
    """The AQL of one page of the feed and its bind variables. It reads ``limit + 1`` rows,
    so the caller knows whether a next page exists."""
    bind: dict[str, Any] = {
        "since": filters.since or "0",
        "until": filters.until or _NO_END,
        "page_size": limit + 1,
    }
    plan = _Plan(
        filters=filters,
        facets=facets,
        shared=_shared_filters(filters, bind),
        dimensions=_dimension_filters(filters, bind),
        cursor=cursor,
    )
    if not facets:
        # the kinds asked for are the kinds read
        bind.pop("kinds", None)
    if cursor is not None:
        bind["cursor_date"] = cursor.date
        bind["cursor_id"] = cursor.id
        bind["cursor_rank"] = cursor.rank
        if not facets:
            # A kind reads no row after the cursor's date from its index.
            bind["until"] = min(bind["until"], cursor.date)
    preamble = _PREAMBLE
    if filters.cabinet:
        preamble += _CABINET_PERIOD
    if filters.member:
        preamble += _MEMBER_PERSON
    sources = _kinds_to_read(filters, facets=facets)
    rows = "".join(_rows_query(s, plan, i) for i, s in enumerate(sources))
    union = ", ".join(f"rows_{i}" for i in range(len(sources)))
    aql = (
        preamble
        + rows
        + f"\n    LET rows = FLATTEN([{union}], 1)"
        + _page_query(plan)
        + _ITEMS
    )
    # ArangoDB refuses a bind variable the query does not use: the cursor's rank and id
    # are only read by the kinds and the page that need them.
    used = set(re.findall(r"@(\w+)", aql))
    return aql, {name: value for name, value in bind.items() if name in used}


def get_feed(
    store: ArangoStore,
    filters: FeedFilters,
    *,
    cursor: FeedCursor | None = None,
    limit: int = 50,
    facets: bool = True,
) -> dict[str, Any]:
    """One page of the feed: ``items`` (up to ``limit + 1``: one more than the page when
    there is a next page), and with *facets* ``total`` and ``facets`` (null without)."""
    aql, bind = feed_query(filters, cursor=cursor, limit=limit, facets=facets)
    rows = list(store.query(aql, bind))
    if not rows:
        return {"items": [], "total": None, "facets": None}
    return cast(dict[str, Any], rows[0])
