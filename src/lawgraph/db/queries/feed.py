"""The query behind the news feed (``GET /api/feed``): the dated events of the graph, newest
first, in one SQL statement.

Every kind of event is read from one table (``_SOURCES``) as a light row: its date, id,
first dossier, ministry, the factions of the people who signed it and, of a vote, its
outcome. The rows of the kinds are put together, sorted by date (descending), the rank of
the kind and id, and cut after the cursor; only the rows of the page are then read in full.

With ``facets`` every row under the filters is read, since a facet counts all of them: the
facets (``kind``, ``ministry``, ``faction``, ``cabinet``, ``chamber``) each without their
own filter, the total and the page are made from that one read. Without, each kind reads
its rows in date order and stops after one page.

The SQL says what the AQL before it said: ``x OR y`` with AQL's truthiness (``lg_truthy``),
``LENGTH(x) > 0`` of a value of any type (``_has_length``), a FOR over a value that is no
array as a FOR over ``[]``.
"""

from __future__ import annotations

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
from lawgraph.core.dossier_stages import LEGISLATIVE_KINDS
from lawgraph.core.feed import (
    DOCUMENT_EVENTS,
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
    "method",
    "decision_kind",
    "chamber",
    "citation_title",
    "publication_kind",
    "publication_year",
    "publication_number",
    "bwb_id",
    "valid_from",
)
# The name a bill gives itself: "Deze wet wordt aangehaald als: Wet sterkere archieven."
# The AQL wrote ``\s`` and ``\.`` in a string literal, which made them ``s`` and ``.`` (any
# character but a line end); this is the pattern ArangoDB matched, in any case.
_CITED = "wordt aangehaald als:?s*([^.\n]{3,150})[^\n\r\u0085  ]"
# What AQL's TRIM takes off.
_TRIM = " \t\r\n"

_EMPTY = "'[]'::json"
_JSON_TEXT = "#>> '{}'"


def _lit(value: str) -> str:
    """SQL: *value* as a string literal."""
    return "'" + value.replace("'", "''") + "'"


def _or(value: str, other: str) -> str:
    """SQL: AQL ``value OR other`` of two JSON values."""
    return f"CASE WHEN lg_truthy({value}) THEN {value} ELSE {other} END"


def _not_null(value: str) -> str:
    """SQL: the JSON *value* is neither null nor missing (AQL ``value != null``)."""
    return f"coalesce(json_typeof({value}), 'null') <> 'null'"


def _array(value: str) -> str:
    """SQL: the JSON *value* when it is an array, else ``[]``: what a FOR walks."""
    return f"CASE WHEN json_typeof({value}) = 'array' THEN {value} ELSE {_EMPTY} END"


def _has_length(value: str) -> str:
    """SQL: AQL ``LENGTH(value) > 0``: an array or object that is not empty, a string that
    is not, any number, true."""
    return (
        f"CASE json_typeof({value})"
        f" WHEN 'array' THEN json_array_length({value}) > 0"
        f" WHEN 'object' THEN EXISTS (SELECT 1 FROM json_each({value}))"
        " WHEN 'number' THEN true"
        f" ELSE lg_truthy({value}) END"
    )


def _text(value: str) -> str:
    """SQL: the JSON *value* as AQL's LOWER reads it: a string as itself, a number or a
    boolean as written, null as ``""``."""
    return f"coalesce(({value}) {_JSON_TEXT}, '')"


def _kind_parts(field: str, kind: str) -> tuple[str, str]:
    """SQL: *field* is *kind* itself, and *field* is ``kind (…)``: a range, as the AQL had
    it (the collation is ArangoDB's)."""
    return (
        f"{field} = {_lit(kind)}",
        f"{field} >= {_lit(kind + ' (')} AND {field} < {_lit(kind + ' )')}",
    )


def _of_kind(field: str, kind: str) -> str:
    """SQL: *field* is a ``Document.Soort`` of *kind*: *kind* itself or ``kind (…)``."""
    exact, ranged = _kind_parts(field, kind)
    return f"({exact} OR ({ranged}))"


def _elements(value: str) -> str:
    """SQL: the elements ``x.v`` of the JSON *value* (none when it is no array)."""
    return f"json_array_elements({_array(value)}) AS x(v)"


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
    chamber: str | None = None  # TK, EK


@dataclass(frozen=True)
class _Source:
    """How the events of one kind are read: from the table *collection*, dated by its
        column *date*, kept by *where* (on ``n``) and by one of *parts* (none: by *where* alone;
    each part is read on its own index when a kind reads one page). The other fields are SQL on ``n`` (its
        ``id`` and ``props``): its dossier labels (JSON; None: none), its signatures (JSON
        objects with ``person_id``, ``member_key``, ``name``, ``role``, ``capacity``,
        ``faction_id``; None when nobody signs this kind; ``{label}`` is its first dossier
        label), its title (JSON), its own ministry (text; None: that of its first dossier) and
        its chamber (text). A row looks its signatures up only when a filter or a facet needs
        them."""

    kind: str
    collection: str
    date: str
    where: str
    dossiers: str | None
    persons: str | None
    title: str
    ministry: str | None = None
    chamber: str = _lit(CHAMBER_TK)
    parts: tuple[str, ...] = ()

    @property
    def condition(self) -> str:
        """*where*, and one of *parts*."""
        if not self.parts:
            return self.where
        return f"{self.where} AND ({' OR '.join(f'({p})' for p in self.parts)})"


# The signatures of a paper, from the column that holds them (``pj_actors``): its props
# hold the whole record of the source, which a read of one prop would parse.
_ACTORS_OF_N = "n.pj_actors"
_ACTORS_OF_PAPER = "paper.pj_actors"
_ACTORS_OF_O = "o.pj_actors"

_DOSSIER_NUMBERS = _or("n.props -> 'dossier_numbers'", _EMPTY)
_PAPER_DOSSIER_NUMBERS = _or("n.pj_dossier_numbers", _EMPTY)

_COMMITMENT_DOSSIERS = f"""(
            SELECT coalesce(json_agg(d.props -> 'label' ORDER BY d.label ASC NULLS FIRST),
                            {_EMPTY})
            FROM {COLLECTION_EDGES} e
            JOIN {COLLECTION_DOSSIERS} d ON d.id = e.to_id
            WHERE e.from_id = n.id AND e.relation = {_lit(RELATION_ABOUT)}
              AND e.to_collection = {_lit(COLLECTION_DOSSIERS)}
        )"""

_COMMITMENT_PERSONS = f"""json_build_array(json_build_object(
            'member_key', n.props -> 'member_key',
            'name', n.props -> 'minister_name',
            'function', n.props -> 'minister_role',
            'role', {_lit(FIRST_SIGNATORY)}::text,
            'capacity', {_lit(CAPACITY_GOVERNMENT)}::text
        ))"""

# The signatures of the document a vote decided: a paper of the case it singled out, the
# newest that has signatures. A case key is its TK GUID made a node key (lower case, ``_``).
_CASE_ID = _text("n.props -> 'primary_case_id'")
_DECIDED_PERSONS = f"""coalesce((
            SELECT {_or(_ACTORS_OF_PAPER, _EMPTY)}
            FROM {COLLECTION_EDGES} e
            JOIN {COLLECTION_DOCUMENTS} paper ON paper.id = e.from_id
            WHERE e.to_id = {_lit(COLLECTION_CASES + "/")}
                            || replace(lower({_CASE_ID}), '-', '_')
              AND e.relation = {_lit(RELATION_PART_OF)}
              AND e.from_collection = {_lit(COLLECTION_DOCUMENTS)}
              AND {_has_length(_ACTORS_OF_PAPER)}
            ORDER BY paper.date DESC NULLS LAST, paper.key DESC
            LIMIT 1
        ), {_EMPTY})"""

# The signatures of a bill: its own, else those of the first memorie van toelichting of its
# dossier, which the source signs where it leaves the voorstel itself unsigned. ``{label}``
# is the bill's first dossier label.
_BILL_PERSONS = f"""CASE WHEN {_has_length(_ACTORS_OF_N)} THEN {_ACTORS_OF_N}
        ELSE coalesce((
            SELECT {_or(_ACTORS_OF_O, _EMPTY)}
            FROM {COLLECTION_DOCUMENTS} o
            WHERE {{label}} IS NOT NULL AND o.dossier_numbers @> ARRAY[{{label}}]
              AND starts_with(o.kind, {_lit(EXPLANATORY_MEMORANDUM)})
              AND {_has_length(_ACTORS_OF_O)}
            ORDER BY o.date ASC NULLS FIRST, o.key ASC
            LIMIT 1
        ), {_EMPTY}) END"""

_ACTORS = _or(_ACTORS_OF_N, _EMPTY)

# The chamber of a vote: one of the Eerste Kamer carries ``chamber`` ``EK``.
_VOTE_CHAMBER = "lg_str(" + _or("n.props -> 'chamber'", "'\"TK\"'::json") + ")"


def _number(value: str) -> str:
    """SQL: AQL's TO_NUMBER of the JSON *value*: a number, 1 for true, else 0."""
    return (
        f"CASE json_typeof({value}) WHEN 'number' THEN ({value} {_JSON_TEXT})::float8"
        f" WHEN 'boolean' THEN ({value} {_JSON_TEXT})::boolean::int ELSE 0 END"
    )


# The difference in seats (in members on a roll-call) between for and against.
_VOOR = "n.props -> 'tally' -> 'Voor'"
_TEGEN = "n.props -> 'tally' -> 'Tegen'"
_MARGIN = f"abs(({_number(_VOOR)}) - ({_number(_TEGEN)}))"


def _document_source(kind: str) -> _Source:
    return _Source(
        kind=kind,
        collection=COLLECTION_DOCUMENTS,
        date="date",
        where=f"{_lit(CHAMBER_TK)} = ANY(n.labels)",
        parts=_kind_parts("n.kind", kind),
        dossiers=_PAPER_DOSSIER_NUMBERS,
        persons=_BILL_PERSONS if kind == EVENT_BILL else _ACTORS,
        title=_or("n.pj_subject", "n.pj_title"),
    )


_CITATION_TITLE = _or("i.props -> 'citation_title'", "i.props -> 'title'")
_BWB_ID = _text("n.props -> 'bwb_id'")

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
            title="n.props -> 'text'",
            ministry="n.ministry",
        ),
        *(_document_source(kind) for kind in DOCUMENT_EVENTS),
        _Source(
            kind=EVENT_VOTE,
            collection=COLLECTION_DECISIONS,
            date="date",
            # read by date, not by the outcome (the props, not the indexed ``passed``: a
            # page reads the index on the date newest first and stops); of the Eerste
            # Kamer only the vote that decided the bill (its list names a vote on a motion
            # by the bill too)
            where=(
                "lg_bool(n.props -> 'passed') IS NOT NULL"
                " AND (lg_str(n.props -> 'chamber') IS DISTINCT FROM 'EK'"
                " OR lg_bool(n.props -> 'bill_decision') IS TRUE)"
            ),
            dossiers=_DOSSIER_NUMBERS,
            persons=_DECIDED_PERSONS,
            title="n.props -> 'subject'",
            chamber=_VOTE_CHAMBER,
        ),
        _Source(
            kind=EVENT_PUBLICATION,
            collection=COLLECTION_INSTRUMENTS,
            date="date_published",
            where=f"n.kind = {_lit(INSTRUMENT_KIND_PUBLICATION)}",
            dossiers=_DOSSIER_NUMBERS,
            persons=None,
            title="n.props -> 'citation_title'",
            chamber="NULL",
        ),
        _Source(
            kind=EVENT_COMMENCEMENT,
            collection=COLLECTION_INSTRUMENT_VERSIONS,
            date="valid_from",
            where="true",
            dossiers=None,
            persons=None,
            chamber="NULL",
            title=(
                f"(SELECT {_CITATION_TITLE} FROM {COLLECTION_INSTRUMENTS} i"
                f" WHERE i.key = lower({_BWB_ID}))"
            ),
        ),
    )
}

# The kinds that are no event of either chamber: a filter on the chamber leaves them out.
_NO_CHAMBER = (EVENT_PUBLICATION, EVENT_COMMENCEMENT)
CHAMBER_EK = "EK"

# The dimensions that are counted as facets; each is a filter on the rows too.
_DIMENSIONS = ("kind", "ministry", "faction", "cabinet", "chamber")

# What every request reads first: factions by the ids of their Fractie records (an id two
# factions claim goes to the first by key) and the cabinets with a start; each read once
# (MATERIALIZED), not again for every lookup in it.
_SHORT = _or("f.props -> 'abbreviation'", "f.props -> 'name'")
_EXTERNAL_IDS = _or("f.props -> 'external_ids'", _EMPTY)
_PREAMBLE = f"""
    faction_of AS MATERIALIZED (
        SELECT DISTINCT ON (u.fid) u.fid, f.key, {_SHORT} AS short
        FROM {COLLECTION_FACTIONS} f
        CROSS JOIN LATERAL unnest(
            coalesce(lg_text_array({_EXTERNAL_IDS}), '{{}}')
            || ARRAY[lg_str(f.props -> 'external_id')]
        ) AS u(fid)
        WHERE u.fid IS NOT NULL
        ORDER BY u.fid, f.key ASC
    ),
    faction_map AS MATERIALIZED (
        -- a lookup only: its keys in no order (``jsonb``)
        SELECT jsonb_object_agg(fid, key) AS map FROM faction_of
    ),
    cabinet_starts AS MATERIALIZED (
        SELECT c.key, lg_str(c.props -> 'from_date') AS from_date
        FROM {COLLECTION_CABINETS} c
        WHERE lg_str(c.props -> 'from_date') IS NOT NULL
    ),
    cabinet_periods AS MATERIALIZED (
        SELECT key, from_date, lead(from_date) OVER (ORDER BY from_date) AS until
        FROM (
            SELECT DISTINCT ON (from_date) key, from_date FROM cabinet_starts
            ORDER BY from_date, key DESC
        ) firsts
    )"""

# The period of the cabinet asked for: from its beëdiging to that of the next one.
_UNTIL = _or("nx.v", "%(no_end)s::json")
_CABINET_PERIOD = f""",
    period AS (
        SELECT lg_str(cf.v) AS cabinet_from, lg_str({_UNTIL}) AS cabinet_until
        FROM (
            SELECT (SELECT c.props -> 'from_date' FROM {COLLECTION_CABINETS} c
                    WHERE c.key = %(cabinet)s) AS v
        ) cf
        CROSS JOIN LATERAL (
            SELECT (SELECT c.props -> 'from_date' FROM {COLLECTION_CABINETS} c
                    WHERE {_not_null("cf.v")}
                      AND lg_str(c.props -> 'from_date') > lg_str(cf.v)
                    ORDER BY lg_str(c.props -> 'from_date') ASC NULLS FIRST
                    LIMIT 1) AS v
        ) nx
    )"""

_MEMBER_PERSON = f""",
    member_person AS (
        SELECT lg_str(m.props -> 'external_id') AS person
        FROM {COLLECTION_MEMBERS} m WHERE m.key = %(member)s
    )"""

_IN_PERIOD = (
    "(SELECT cabinet_from FROM period) IS NOT NULL"
    " AND {date} >= (SELECT cabinet_from FROM period)"
    " AND {date} < (SELECT cabinet_until FROM period)"
)


def _cabinet_on(date: str) -> str:
    """SQL: the key of the cabinet in office on *date*: the last to start on or before it
    (of two that start on one day the later key), from its period in ``cabinet_periods``."""
    return (
        f"(SELECT cp.key FROM cabinet_periods cp WHERE cp.from_date <= {date}"
        f" AND (cp.until IS NULL OR {date} < cp.until))"
    )


def _dimension_filters(filters: FeedFilters, bind: dict[str, Any]) -> dict[str, str]:
    """The filter of each facet dimension that is asked for, on the columns of ``events``."""
    clauses: dict[str, str] = {}
    if filters.kinds:
        clauses["kind"] = "kind = ANY(%(kinds)s)"
        bind["kinds"] = list(filters.kinds)
    if filters.ministry:
        clauses["ministry"] = "ministry = %(ministry)s"
        bind["ministry"] = filters.ministry
    if filters.faction:
        clauses["faction"] = "%(faction)s = ANY(factions)"
        bind["faction"] = filters.faction
    if filters.chamber:
        clauses["chamber"] = "chamber = %(chamber)s"
        bind["chamber"] = filters.chamber
    if filters.cabinet:
        clauses["cabinet"] = _IN_PERIOD.replace("{date}", "date")
        bind["cabinet"] = filters.cabinet
    return clauses


# The filters that hold for every facet, on the laterals of a kind's rows: ``l.labels``
# (its dossiers), ``p.persons``, ``t.title`` and ``fd`` (its first dossier).
_DOSSIER_FILTER = (
    f"EXISTS (SELECT 1 FROM {_elements('l.labels')}"
    " WHERE json_typeof(x.v) IN ('string', 'number', 'boolean')"
    f" AND starts_with(x.v {_JSON_TEXT}, %(dossier)s))"
)
_MEMBER_FILTER = (
    f"EXISTS (SELECT 1 FROM {_elements('p.persons')}"
    " WHERE lg_str(x.v -> 'member_key') = %(member)s)"
    " OR ((SELECT person FROM member_person) IS NOT NULL"
    f" AND EXISTS (SELECT 1 FROM {_elements('p.persons')}"
    " WHERE lg_str(x.v -> 'person_id') = (SELECT person FROM member_person)))"
)
# Stands for the filter on the words, which reads ``fd`` only where a kind has dossiers.
_WORDS = "{words}"


def _contains(text: str) -> str:
    """SQL: AQL ``CONTAINS(LOWER(text), @q)`` of a JSON *text*."""
    return f"strpos(lower({_text(text)}), %(q)s) > 0"


def _shared_filters(filters: FeedFilters, bind: dict[str, Any]) -> list[str]:
    """The filters that hold for every facet, on the laterals of a kind's rows."""
    clauses: list[str] = []
    if filters.dossier:
        clauses.append(_DOSSIER_FILTER)
        bind["dossier"] = filters.dossier
    if filters.member:
        clauses.append(_MEMBER_FILTER)
        bind["member"] = filters.member
    if filters.q:
        clauses.append(_WORDS)
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
    if facets:  # every chamber is counted; ``chamber`` keeps the one asked for
        return sources
    if filters.chamber == CHAMBER_EK:
        sources = [s for s in sources if s.kind == EVENT_VOTE]
    elif filters.chamber:
        sources = [s for s in sources if s.kind not in _NO_CHAMBER]
    return sources


def _where(clauses: list[str], indent: str) -> str:
    if not clauses:
        return ""
    joined = f"\n{indent}  AND ".join(f"({clause})" for clause in clauses)
    return f"\n{indent}WHERE {joined}"


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


# The first dossier label of a row (``labels[0]``), when it is a string.
_LABEL = "lg_str(CASE WHEN json_typeof(l.labels) = 'array' THEN l.labels -> 0 END)"

# The factions a row counts for: those its Kamerleden signed for, a faction as often as
# they did (``= ANY`` filters on them; the faction facet counts a row once per faction).
# Looked up in ``faction_map``: a join per row would hash the factions for every row.
_FACTIONS = f"""array_remove(ARRAY(
                SELECT (SELECT map FROM faction_map) ->> lg_str(x.v -> 'faction_id')
                FROM {_elements("p.persons")}
                WHERE lg_str(x.v -> 'capacity') = {_lit(CAPACITY_MEMBER)}
            ), NULL)"""

# The columns of a light row, in the order of every kind's SELECT.
_ROW_COLUMNS = (
    ("kind", "text"),
    ("rank", "int"),
    ("id", "text"),
    ("date", "text"),
    ("dossier", "text"),
    ("ministry", "text"),
    ("factions", "text[]"),
    ("chamber", "text"),
    ("subkind", "text"),
    ("passed", "boolean"),
    ("margin", "float8"),
)

# The order of the feed: newest day first, within a day by the rank of the kind
# (``core.feed.DAY_ORDER``), then by id.
_ORDER = "date DESC NULLS LAST, rank ASC, id ASC"
_PAGE_ORDER = "pg.date DESC NULLS LAST, pg.rank ASC, pg.id ASC"


def _after_cursor(source: _Source, cursor: FeedCursor) -> str:
    """The events of *source* on the cursor's day that come after it: all when its kind
    ranks after the cursor's, none when before, those with a greater id when the same."""
    rank = KIND_RANK[source.kind]
    later = (
        "true"
        if rank > cursor.rank
        else "false"
        if rank < cursor.rank
        else "n.id > %(cursor_id)s"
    )
    return f"CASE WHEN n.{source.date} = %(cursor_date)s THEN {later} ELSE true END"


@dataclass(frozen=True)
class _Kind:
    """The SQL of one kind's rows under a plan: its laterals and its expressions."""

    source: _Source
    plan: _Plan

    @property
    def first_dossier(self) -> bool:
        """Whether a row looks up its first dossier: for the ministry, or the words."""
        return self.source.dossiers is not None and (
            self.source.ministry is None or bool(self.plan.filters.q)
        )

    @property
    def ministry(self) -> str:
        return self.source.ministry or ("fd.ministry" if self.first_dossier else "NULL")

    @property
    def factions(self) -> str:
        if self.plan.needs_factions and self.source.persons:
            return _FACTIONS
        return "'{}'::text[]"

    def laterals(self) -> str:
        """``l`` (the labels), ``fd`` (the first dossier), ``p`` (the signatures) and
        ``t`` (the title), those the plan needs."""
        joins = [
            f"CROSS JOIN LATERAL (SELECT {self.source.dossiers or _EMPTY}"
            " AS labels OFFSET 0) l"
        ]
        if self.first_dossier:
            joins.append(
                "LEFT JOIN LATERAL (SELECT d.ministry, d.props -> 'title' AS title"
                f" FROM {COLLECTION_DOSSIERS} d WHERE d.label = {_LABEL}"
                " ORDER BY d.key ASC LIMIT 1) fd ON true"
            )
        if self.plan.needs_persons:
            persons = (self.source.persons or _EMPTY).replace("{label}", _LABEL)
            joins.append(f"CROSS JOIN LATERAL (SELECT {persons} AS persons OFFSET 0) p")
        if self.plan.filters.q:
            joins.append(
                f"CROSS JOIN LATERAL (SELECT {self.source.title} AS title OFFSET 0) t"
            )
        return "".join(f"\n        {join}" for join in joins)

    def words(self) -> str:
        """The filter on the words: in the title, or in the title of the first dossier."""
        found = _contains("t.title")
        if self.first_dossier:
            found += f" OR {_contains('fd.title')}"
        return f"%(q)s <> '' AND ({found})"

    def select(self) -> str:
        """The columns of the light row (``_ROW_COLUMNS``)."""
        vote = self.source.kind == EVENT_VOTE
        values = (
            _lit(self.source.kind),
            str(KIND_RANK[self.source.kind]),
            "n.id",
            f"n.{self.source.date}",
            _LABEL,
            self.ministry,
            self.factions,
            self.source.chamber,
            "lg_str(n.props -> 'kind')" if vote else "NULL",
            "n.passed" if vote else "NULL",
            _MARGIN if vote else "NULL",
        )
        return ",\n            ".join(
            f"({value})::{sql_type} AS {name}"
            for value, (name, sql_type) in zip(values, _ROW_COLUMNS, strict=True)
        )

    def page_filters(self) -> list[str]:
        """Without facets, the filters on the ministry and the faction of a row."""
        clauses = []
        if self.plan.filters.ministry:
            clauses.append(f"({self.ministry}) = %(ministry)s")
        if self.plan.filters.faction:
            clauses.append(f"%(faction)s = ANY({self.factions})")
        return clauses


def _rows_query(source: _Source, plan: _Plan) -> str:
    """The light rows of one kind (``_ROW_COLUMNS``). Without facets a kind reads one page,
    newest first: before anything else is looked up when no filter needs it."""
    kind = _Kind(source, plan)
    date = f"n.{source.date}"
    head = [f"{date} >= %(since)s AND {date} <= %(until)s", source.condition]
    if plan.filters.chamber and source.kind == EVENT_VOTE and not plan.facets:
        head.append(f"{_VOTE_CHAMBER} = %(chamber)s")
    tail = [clause.replace(_WORDS, kind.words()) for clause in plan.shared]
    table, order = f"{source.collection} n", ""
    if not plan.facets:
        tail += kind.page_filters()
        if plan.filters.cabinet:
            head.append(_IN_PERIOD.replace("{date}", date))
        if plan.cursor is not None:
            head.append(_after_cursor(source, plan.cursor))
        # NULLS FIRST, not LAST: no row of the date range is null, and so the order is
        # that of the index on the date (or the kind and the date) read backwards
        order = (
            f"\n        ORDER BY {date} DESC NULLS FIRST, n.id ASC"
            "\n        LIMIT %(page_size)s"
        )
        if not tail:
            # one page of the kind first, then what its rows look up
            table = f"({_first_page(source, head, order)}) n"
            head, order = [], ""
    return f"""(
        SELECT {kind.select()}
        FROM {table}{kind.laterals()}{_where(head + tail, "        ")}{order}
    )"""


def _first_page(source: _Source, head: list[str], order: str) -> str:
    """SQL: the first page of *source* under *head*, newest first. Of a kind in parts
    (a ``Document.Soort`` and its ``kind (…)``) each part is read in the order of its own
    index, a page at most, and the pages are merged: no part is read whole for a page."""
    indent = "            "
    if not source.parts:
        return f"\n{indent}SELECT * FROM {source.collection} n{_where(head, indent)}{order}\n"
    where = [source.where if clause == source.condition else clause for clause in head]
    pages = "\n        UNION ALL ".join(
        f"(SELECT * FROM {source.collection} n{_where([*where, part], indent)}{order})"
        for part in source.parts
    )
    merged = order.replace("n.", "")
    return f"\n        SELECT * FROM (\n        {pages}\n        ) n{merged}\n"


_FACET_AGG = (
    "SELECT coalesce(json_agg(json_build_object('value', value, 'count', cnt)"
    f" ORDER BY cnt DESC, value ASC NULLS FIRST), {_EMPTY})"
)
_PER_FACTION = (
    "events CROSS JOIN LATERAL unnest(CASE WHEN cardinality(factions) > 0"
    " THEN factions ELSE ARRAY[NULL]::text[] END) AS fx(faction)"
)


def _facet(plan: _Plan, name: str) -> str:
    """A facet: the rows under every filter but its own, counted per value."""
    others = [clause for dim, clause in plan.dimensions.items() if dim != name]
    where = _where(others, "                ")
    if name == "cabinet":
        return f"""({_FACET_AGG} FROM (
            SELECT value, sum(n)::int AS cnt
            FROM (
                SELECT {_cabinet_on("per_day.date")} AS value, per_day.n
                FROM (SELECT date, count(*) AS n FROM events{where}
                      GROUP BY date) per_day
            ) dated
            GROUP BY value
        ) counted)"""
    if name == "faction":
        # a row counts once for a faction, however many of its signers signed for it
        return f"""({_FACET_AGG} FROM (
            SELECT value, count(*)::int AS cnt
            FROM (SELECT DISTINCT fx.faction AS value, id FROM {_PER_FACTION}{where}) once
            GROUP BY 1
        ) counted)"""
    return f"""({_FACET_AGG} FROM (
            SELECT {name} AS value, count(*)::int AS cnt
            FROM events{where}
            GROUP BY 1
        ) counted)"""


def _node_of(row: str) -> str:
    """SQL: ``n``, the node (``id``, ``props``, ``pj_actors``) of the page row *row*."""
    tables = sorted({s.collection for s in _SOURCES.values()})
    union = "\n            UNION ALL ".join(
        "SELECT id, props, "
        + ("pj_actors" if table == COLLECTION_DOCUMENTS else "props -> 'actors'")
        + f" AS pj_actors FROM {table} WHERE id = {row}.id"
        for table in tables
    )
    return f"""CROSS JOIN LATERAL (
            {union}
        ) n"""


_CHANGES = ", ".join(
    _lit(r) for r in (RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS)
)

# The key of the instrument an edge of a paper changes: of an article, the instrument it is
# of by its BWB id (``LOWER(null)`` is ``""``), else the target's own key.
_LAW_KEY = f"""CASE WHEN e.to_collection = {_lit(COLLECTION_ARTICLES)}
                                THEN lower({_text("a.props -> 'bwb_id'")})
                            ELSE substr(e.to_id, length(e.to_collection) + 2) END"""
_LAW_EDGES = f"""FROM {COLLECTION_EDGES} e
                        LEFT JOIN {COLLECTION_ARTICLES} a
                            ON e.to_collection = {_lit(COLLECTION_ARTICLES)}
                           AND a.id = e.to_id
                        WHERE e.from_id = {{paper}} AND e.relation IN ({_CHANGES})"""

_PAPER_TEXT = (
    "CASE WHEN lg_truthy(paper.props -> 'text') THEN paper.props ->> 'text' ELSE '' END"
)
# ``case_ids OR []`` and ``signatures OR []`` walked: a value that is no array as ``[]``.
_CASE_IDS = _array("paper.props -> 'case_ids'")


def _official_short(label: str) -> str:
    """SQL: the name the bill of the dossier labelled *label* goes by, from official data
    only: the citation title its own text gives ("Deze wet wordt aangehaald als: …"), the
    citation title the Kamer gives its case, or the citation title of the one Dutch law it
    changes; ``{title, basis}`` with ``basis`` ``citation``, ``case`` or ``amended_law``,
    null when none of them is there."""
    return f"""(
            SELECT CASE
                WHEN os.cited IS NOT NULL THEN json_build_object(
                    'title', btrim(os.cited, %(trim)s), 'basis', 'citation'::text)
                WHEN os.case_title IS NOT NULL THEN json_build_object(
                    'title', os.case_title, 'basis', 'case'::text)
                WHEN {_not_null("law.props -> 'bwb_id'")}
                     AND {_not_null("law.props -> 'citation_title'")}
                    THEN json_build_object(
                        'title', law.props -> 'citation_title',
                        'basis', 'amended_law'::text)
            END
            FROM (
                SELECT paper.id, paper.props FROM {COLLECTION_DOCUMENTS} paper
                WHERE {label} IS NOT NULL AND paper.dossier_numbers @> ARRAY[{label}]
                  AND {_of_kind("paper.kind", EVENT_BILL)}
                ORDER BY paper.date ASC NULLS FIRST, paper.key ASC
                LIMIT 1
            ) paper
            CROSS JOIN LATERAL (
                SELECT
                    (regexp_match({_PAPER_TEXT}, %(cited)s, 'i'))[1] AS cited,
                    (SELECT c.props -> 'citation_title'
                     FROM json_array_elements({_CASE_IDS})
                         WITH ORDINALITY AS ids(case_id, ord)
                     JOIN {COLLECTION_CASES} c ON c.id = {_lit(COLLECTION_CASES + "/")}
                         || replace(lower(ids.case_id {_JSON_TEXT}), '-', '_')
                     WHERE {_not_null("c.props -> 'citation_title'")}
                     ORDER BY ids.ord
                     LIMIT 1) AS case_title,
                    ARRAY(
                        SELECT DISTINCT {_LAW_KEY}
                        {_LAW_EDGES.replace("{paper}", "paper.id")}
                    ) AS laws
                OFFSET 0
            ) os
            LEFT JOIN {COLLECTION_INSTRUMENTS} law
                ON cardinality(os.laws) = 1 AND law.key = os.laws[1]
        )"""


# The signatures of an event on the page, by its kind.
_SIGNATURES = f"""CASE pg.kind
                WHEN {_lit(EVENT_COMMITMENT)} THEN {_COMMITMENT_PERSONS}
                WHEN {_lit(EVENT_VOTE)} THEN {_DECIDED_PERSONS}
                WHEN {_lit(EVENT_BILL)} THEN {_BILL_PERSONS.replace("{label}", "pg.dossier")}
                ELSE {_ACTORS} END"""

# A signature as an item shows it: with the key and name of its member (a member's key is
# its TK GUID made a node key: lower case, ``_``) and its faction. The keys MERGE adds come in the
# order ArangoDB gave them (that of its hash map, the same for these names every time).
_MEMBER_NAME = _or(
    _or("m.props -> 'name'", "m.props -> 'known_as'"), "m.props -> 'government_name'"
)
_PERSONS = f"""CROSS JOIN LATERAL (
            SELECT coalesce(json_agg(
                CASE WHEN json_typeof(s.p) = 'object' THEN lg_merge(s.p, json_build_object(
                    'faction', (SELECT json_build_object('key', fo.key, 'short', fo.short)
                                FROM faction_of fo
                                WHERE fo.fid = lg_str(s.p -> 'faction_id')),
                    'member_name', {_MEMBER_NAME},
                    'member_key', who.key
                )) END
                ORDER BY s.o), {_EMPTY}) AS value
            FROM json_array_elements({_array("sig.value")})
                WITH ORDINALITY AS s(p, o)
            CROSS JOIN LATERAL (SELECT CASE
                WHEN lg_truthy(s.p -> 'member_key') THEN s.p -> 'member_key'
                WHEN {_not_null("s.p -> 'person_id'")}
                    THEN to_json(replace(lower(s.p ->> 'person_id'), '-', '_'))
            END AS key) who
            LEFT JOIN LATERAL (
                SELECT props FROM {COLLECTION_MEMBERS} WHERE key = (who.key {_JSON_TEXT})
            ) m ON true
        ) persons"""

_CHANGED_TITLE = _or("c.props -> 'citation_title'", "c.props -> 'title'")
_CHANGED_INSTRUMENTS = f"""CASE WHEN pg.kind = {_lit(EVENT_PUBLICATION)} THEN (
                SELECT coalesce(json_agg(json_build_object(
                    'key', c.key,
                    'title', {_CHANGED_TITLE},
                    'bwb_id', c.props -> 'bwb_id'
                ) ORDER BY c.citation_title ASC NULLS FIRST, c.key ASC), {_EMPTY})
                FROM (
                    SELECT i.key, i.props, i.citation_title
                    FROM (
                        SELECT DISTINCT {_LAW_KEY} AS key
                        {_LAW_EDGES.replace("{paper}", "pg.id")}
                    ) changed
                    JOIN {COLLECTION_INSTRUMENTS} i ON i.key = changed.key
                    ORDER BY i.citation_title ASC NULLS FIRST, i.key ASC
                    LIMIT {MAX_CHANGED_INSTRUMENTS}
                ) c
            ) ELSE {_EMPTY} END"""

_CHANGED_ARTICLES = f"""CASE WHEN pg.kind = {_lit(EVENT_COMMENCEMENT)} THEN (
                SELECT count(*)::int FROM {COLLECTION_ARTICLE_VERSIONS} v
                WHERE lg_str(n.props -> 'bwb_id') IS NOT NULL
                  AND v.bwb_id = lg_str(n.props -> 'bwb_id')
                  AND v.valid_from = lg_str(n.props -> 'valid_from')
            ) ELSE 0 END"""

# The page (``page``), read in full: the node's props, its first dossier, the cabinet on its
# date, the signatures with their factions, and what a kind adds (who made a commitment, the
# laws a publication changes, the law and the articles a new version puts in force). The
# props as KEEP gave them: in the byte order of their names, as MERGE (``lg_merge``).
_ITEMS = f"""(
        SELECT coalesce(json_agg(json_build_object(
            'kind', pg.kind,
            'id', pg.id,
            'date', pg.date,
            'ministry', pg.ministry,
            'cabinet', {_cabinet_on("pg.date")},
            'dossier', dossier.value,
            'props', (
                SELECT coalesce(json_object_agg(k.key, k.value ORDER BY k.key COLLATE "C"), '{{}}'::json)
                FROM json_each(n.props) AS k(key, value)
                WHERE k.key = ANY(%(item_props)s)
            ),
            'text', CASE WHEN pg.kind = {_lit(EVENT_COMMITMENT)} THEN n.props -> 'text' END,
            'persons', persons.value,
            'instrument', instrument.value,
            'changed_articles', {_CHANGED_ARTICLES},
            'changed_instruments', {_CHANGED_INSTRUMENTS}
        ) ORDER BY {_PAGE_ORDER}), {_EMPTY})
        FROM page pg
        {_node_of("pg")}
        LEFT JOIN LATERAL (
            SELECT json_build_object(
                'key', d.key,
                'number', d.props -> 'label',
                'title', d.props -> 'title',
                'official_short', {_official_short("pg.dossier")}
            ) AS value
            FROM {COLLECTION_DOSSIERS} d
            WHERE d.label = pg.dossier
            ORDER BY d.key ASC
            LIMIT 1
        ) dossier ON true
        CROSS JOIN LATERAL (SELECT {_SIGNATURES} AS value OFFSET 0) sig
        {_PERSONS}
        LEFT JOIN LATERAL (
            SELECT json_build_object(
                'key', i.key,
                'title', {_CITATION_TITLE},
                'bwb_id', i.props -> 'bwb_id',
                'article_count', i.props -> 'article_count'
            ) AS value
            FROM {COLLECTION_INSTRUMENTS} i
            WHERE pg.kind = {_lit(EVENT_COMMENCEMENT)} AND i.key = lower({_BWB_ID})
        ) instrument ON true
    )"""


def _rows_of(filters: FeedFilters, plan: _Plan, *, facets: bool) -> str:
    """The CTEs that read ``events``: the preamble and the light rows of every kind read."""
    ctes = _PREAMBLE
    if filters.cabinet:
        ctes += _CABINET_PERIOD
    if filters.member:
        ctes += _MEMBER_PERSON
    sources = _kinds_to_read(filters, facets=facets)
    union = "\n    UNION ALL ".join(_rows_query(s, plan) for s in sources)
    if not union:
        columns = ", ".join(f"NULL::{t} AS {name}" for name, t in _ROW_COLUMNS)
        union = f"SELECT {columns} WHERE false"
    return f"WITH {ctes},\n    events AS ({union}\n    )"


def _base_bind(filters: FeedFilters, limit: int) -> dict[str, Any]:
    return {
        "since": filters.since or "0",
        "until": filters.until or _NO_END,
        "page_size": limit + 1,
        "no_end": f'"{_NO_END}"',
        "cited": _CITED,
        "trim": _TRIM,
        "item_props": list(_ITEM_PROPS),
    }


def _page_query(plan: _Plan) -> str:
    """The page, with facets the total and the facets too, and the answer."""
    if not plan.facets:
        return f""",
    page AS (SELECT * FROM events ORDER BY {_ORDER} LIMIT %(page_size)s)
    SELECT json_build_object('items', {_ITEMS}, 'total', NULL, 'facets', NULL)"""
    after = ""
    if plan.cursor is not None:
        after = (
            "\n        WHERE date < %(cursor_date)s OR (date = %(cursor_date)s"
            " AND (rank > %(cursor_rank)s"
            " OR (rank = %(cursor_rank)s AND id > %(cursor_id)s)))"
        )
    facets = ",\n            ".join(
        f"{_lit(name)}, {_facet(plan, name)}" for name in _DIMENSIONS
    )
    matching = _where(list(plan.dimensions.values()), "        ")
    return f""",
    matching AS (SELECT * FROM events{matching}),
    page AS (
        SELECT * FROM matching{after}
        ORDER BY {_ORDER}
        LIMIT %(page_size)s
    )
    SELECT json_build_object(
        'items', {_ITEMS},
        'total', (SELECT count(*)::int FROM matching),
        'facets', json_build_object(
            {facets}
        )
    )"""


def feed_query(
    filters: FeedFilters,
    *,
    cursor: FeedCursor | None = None,
    limit: int = 50,
    facets: bool = True,
) -> tuple[str, dict[str, Any]]:
    """The SQL of one page of the feed and its parameters. It reads ``limit + 1`` rows,
    so the caller knows whether a next page exists."""
    bind = _base_bind(filters, limit)
    plan = _Plan(
        filters=filters,
        facets=facets,
        shared=_shared_filters(filters, bind),
        dimensions=_dimension_filters(filters, bind),
        cursor=cursor,
    )
    if cursor is not None:
        bind["cursor_date"] = cursor.date
        bind["cursor_id"] = cursor.id
        bind["cursor_rank"] = cursor.rank
        if not facets:
            # A kind reads no row after the cursor's date.
            bind["until"] = min(bind["until"], cursor.date)
    return _rows_of(filters, plan, facets=facets) + _page_query(plan), bind


# The events a summary shows one by one: a bill submitted, a commitment, a commencement, a
# vote on a bill, a vote whose margin is at most ``margin``, and every vote of a quiet day.
_HIGHLIGHT = (
    f"kind IN ({_lit(EVENT_BILL)}, {_lit(EVENT_COMMITMENT)}, {_lit(EVENT_COMMENCEMENT)})"
    f" OR (kind = {_lit(EVENT_VOTE)} AND (chamber = {_lit(CHAMBER_EK)}"
    " OR subkind = ANY(%(legislative)s) OR margin <= %(margin)s"
    " OR date IN (SELECT date FROM quiet_days)))"
)

# Per day of the window: the events per kind, per kind and dossier and, of the votes, per
# subkind and outcome; the title of every dossier counted; the days with at most ``few``
# votes on anything but a bill (each of their votes is shown); and the events shown one by
# one.
_SUMMARY = f""",
    matching AS (SELECT * FROM events{{dimensions}}),
    day_kinds AS (
        SELECT date, json_agg(json_build_object('value', kind, 'count', cnt)
                              ORDER BY cnt DESC, kind ASC NULLS FIRST) AS value
        FROM (SELECT date, kind, count(*)::int AS cnt FROM matching GROUP BY date, kind) x
        GROUP BY date
    ),
    day_dossiers AS (
        SELECT date, json_agg(json_build_object('kind', kind, 'number', dossier, 'count', cnt)
                              ORDER BY rank ASC, cnt DESC, dossier ASC NULLS FIRST) AS value
        FROM (
            SELECT date, kind, rank, dossier, count(*)::int AS cnt
            FROM matching WHERE dossier IS NOT NULL
            GROUP BY date, kind, rank, dossier
        ) x
        GROUP BY date
    ),
    day_votes AS (
        SELECT date, json_agg(json_build_object(
                   'chamber', chamber, 'subkind', subkind, 'passed', passed, 'count', cnt)
                   ORDER BY cnt DESC, chamber ASC NULLS FIRST, subkind ASC NULLS FIRST,
                            passed ASC NULLS FIRST) AS value
        FROM (
            SELECT date, chamber, subkind, passed, count(*)::int AS cnt
            FROM matching WHERE kind = {_lit(EVENT_VOTE)}
            GROUP BY date, chamber, subkind, passed
        ) x
        GROUP BY date
    ),
    days AS (
        SELECT coalesce(json_agg(json_build_object(
            'date', d.date,
            'total', d.total,
            'kinds', k.value,
            'dossiers', coalesce(ds.value, {_EMPTY}),
            'votes', coalesce(v.value, {_EMPTY})
        ) ORDER BY d.date DESC NULLS LAST), {_EMPTY}) AS value
        FROM (SELECT date, count(*)::int AS total FROM matching GROUP BY date) d
        JOIN day_kinds k ON k.date = d.date
        LEFT JOIN day_dossiers ds ON ds.date = d.date
        LEFT JOIN day_votes v ON v.date = d.date
    ),
    dossier_titles AS (
        SELECT coalesce(json_agg(json_build_object(
            'number', nums.number,
            'key', d.key,
            'title', d.props -> 'title',
            'official_short', {_official_short("nums.number")}
        ) ORDER BY nums.number ASC), {_EMPTY}) AS value
        FROM (SELECT DISTINCT dossier AS number FROM matching WHERE dossier IS NOT NULL) nums
        CROSS JOIN LATERAL (
            SELECT d.key, d.props FROM {COLLECTION_DOSSIERS} d
            WHERE d.label = nums.number
            ORDER BY d.key ASC
            LIMIT 1
        ) d
    ),
    quiet_days AS (
        SELECT date FROM matching
        WHERE kind = {_lit(EVENT_VOTE)} AND chamber IS DISTINCT FROM {_lit(CHAMBER_EK)}
          AND (subkind IS NULL OR subkind <> ALL(%(legislative)s))
        GROUP BY date
        HAVING count(*) <= %(few)s
    ),
    page AS (
        SELECT * FROM matching
        WHERE {_HIGHLIGHT}
        ORDER BY {_ORDER}
        LIMIT %(page_size)s
    )
    SELECT json_build_object(
        'days', (SELECT value FROM days),
        'dossiers', (SELECT value FROM dossier_titles),
        'items', {_ITEMS}
    )"""


def summary_query(
    filters: FeedFilters, *, margin: int = 10, few: int = 2, limit: int = 100
) -> tuple[str, dict[str, Any]]:
    """The SQL of a summary of the days from ``filters.since`` to ``filters.until`` and its
    parameters: per day the counts (``days``), the titles of the dossiers counted, and up to
    ``limit + 1`` events shown one by one (``items``)."""
    bind = _base_bind(filters, limit)
    bind |= {"margin": margin, "few": few, "legislative": list(LEGISLATIVE_KINDS)}
    plan = _Plan(
        filters=filters,
        facets=True,  # every row of the window is counted
        shared=_shared_filters(filters, bind),
        dimensions=_dimension_filters(filters, bind),
        cursor=None,
    )
    dimensions = _where(list(plan.dimensions.values()), "        ")
    summary = _SUMMARY.replace("{dimensions}", dimensions)
    return _rows_of(filters, plan, facets=True) + summary, bind


def get_feed_summary(
    store: ArangoStore,
    filters: FeedFilters,
    *,
    margin: int = 10,
    few: int = 2,
    limit: int = 100,
) -> dict[str, Any]:
    """``days``, ``dossiers`` and ``items`` of ``summary_query``."""
    sql, bind = summary_query(filters, margin=margin, few=few, limit=limit)
    rows = list(store.query(sql, bind))
    return (
        cast(dict[str, Any], rows[0])
        if rows
        else {"days": [], "dossiers": [], "items": []}
    )


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
    sql, bind = feed_query(filters, cursor=cursor, limit=limit, facets=facets)
    rows = list(store.query(sql, bind))
    if not rows:
        return {"items": [], "total": None, "facets": None}
    return cast(dict[str, Any], rows[0])
