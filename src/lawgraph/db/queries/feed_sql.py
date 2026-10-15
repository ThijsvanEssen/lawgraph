"""How the events of the news feed are read (``GET /api/feed``, ``lg_feed_events``): per
kind of event its table (``SOURCES``) and the SQL of its light rows under a request's filters
(``Plan``, ``Kind``, ``rows_of``), and the facets counted on them.

Every kind of event is read from one table as a light row: its date, id, first dossier,
ministry, the factions of the people who signed it and, of a vote, its outcome. With
``facets`` every row under the filters is read, since a facet counts all of them: the facets
(``kind``, ``ministry``, ``faction``, ``cabinet``, ``chamber``, ``coalition``) each without
their own filter. Without, each kind reads its rows in date order and stops after one page.

``x OR y`` is the first of them that is truthy (``truthy_or``: not missing, null, false, 0 or
""), a value has a length (``has_length``) of any type, and a walk over a value that is no
array walks over ``[]``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from lawgraph.config.constants import (
    CHAMBER_EK,
    CHAMBER_TK,
    CHANGE_RELATIONS,
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
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
    RELATION_ABOUT,
    RELATION_PART_OF,
)
from lawgraph.core.bwb_xml import KIND_PUBLICATION as INSTRUMENT_KIND_PUBLICATION
from lawgraph.core.feed import (
    DEFAULT_KINDS,
    DOCUMENT_EVENTS,
    EVENT_BILL,
    EVENT_COMMENCEMENT,
    EVENT_COMMITMENT,
    EVENT_JUDGMENT,
    EVENT_PUBLICATION,
    EVENT_VOTE,
    FEED_KINDS,
    FEED_TIERS,
    KIND_RANK,
    FeedCursor,
)
from lawgraph.core.tk_records.actors import (
    CAPACITY_GOVERNMENT,
    CAPACITY_MEMBER,
    FIRST_SIGNATORY,
)
from lawgraph.core.tk_records.kinds import KIND_EXPLANATORY_MEMORANDUM
from lawgraph.core.votes import VOTE_AGAINST, VOTE_FOR
from lawgraph.db.queries import _words
from lawgraph.db.queries._json_sql import (
    EMPTY_ARRAY,
    array_or_empty,
    as_text,
    has_length,
    is_present,
    truthy_or,
)
from lawgraph.db.queries._lists import FacetFilters, facet, facet_of, where
from lawgraph.db.queries.feed_relations import (
    CITES_LAW,
    ENACTED,
    ENACTED_OF_REGULATION,
    FOLLOWS,
    PUBLICATION_IDENTIFIER,
    bwb_key,
    followed_ctes,
)
from lawgraph.db.schema import (
    FEED_EVENTS_TABLE,
    feed_title,
    instrument_dossier_numbers,
    search_words,
)

JSON_TEXT = "#>> '{}'"


def lit(value: str) -> str:
    """SQL: *value* as a string literal."""
    return "'" + value.replace("'", "''") + "'"


def _kind_parts(field: str, kind: str) -> tuple[str, str]:
    """SQL: *field* is *kind* itself, and *field* is ``kind (…)``: a range, so the index on
    the kind and the date reads a page of it. The range holds under the ICU collation of
    the schema, which counts the space and the brackets (glibc ignores them);
    ``schema.check_collation`` refuses a database without it."""
    return (
        f"{field} = {lit(kind)}",
        f"{field} >= {lit(kind + ' (')} AND {field} < {lit(kind + ' )')}",
    )


def of_kind(field: str, kind: str) -> str:
    """SQL: *field* is a ``Document.Soort`` of *kind*: *kind* itself or ``kind (…)``."""
    exact, ranged = _kind_parts(field, kind)
    return f"({exact} OR ({ranged}))"


def elements(value: str) -> str:
    """SQL: the elements ``x.v`` of the JSON *value* (none when it is no array)."""
    return f"json_array_elements({array_or_empty(value)}) AS x(v)"


@dataclass(frozen=True)
class FeedFilters:
    """What the feed keeps; None keeps everything.

    *dossier* is a prefix of a dossier label (``36600`` holds ``36600-VII``); *member* a
    member key, *faction* a faction key, *cabinet* a cabinet key (the events in its period),
    *q* words of the title or of the title of the event's dossier, in any case; of several,
    any of them (``_words``). *instrument* a BWB id: the events of that law
    (``feed_relations.followed_ctes``), with *article* (an article number) of that article.
    """

    kinds: tuple[str, ...] | None = None
    since: str | None = None
    until: str | None = None
    cabinet: str | None = None
    ministry: str | None = None
    dossier: str | None = None
    member: str | None = None
    faction: str | None = None
    q: tuple[str, ...] = ()
    chamber: str | None = None  # TK, EK
    # what the coalition did on a vote (``FeedCoalition``); keeps votes alone
    coalition: str | None = None
    # the tiers of the judgments; None: ``FEED_TIERS``. A tier keeps judgments alone.
    tiers: tuple[str, ...] | None = None
    instrument: str | None = None
    article: str | None = None


@dataclass(frozen=True)
class Source:
    """How the events of one kind are read: from the table *collection*, dated by its
        column *date*, kept by *where* (on ``n``) and by one of *parts* (none: by *where* alone;
    each part is read on its own index when a kind reads one page). The other fields are SQL on ``n`` (its
        ``id`` and ``props``): its dossier labels (JSON; None: none), its signatures (JSON
        objects with ``person_id``, ``member_key``, ``name``, ``role``, ``capacity``,
        ``faction_id``; None when nobody signs this kind), its title (JSON), its own ministry (text; None: that of its first dossier) and
        its chamber (text). A row looks its signatures up only when a filter or a facet needs
        them. *found* of a bind of a word is SQL on ``n`` that an index serves and that
        holds for every row whose title holds it, and *dossier_found* of the SQL of the
        labels of the dossiers whose title holds it, for every row whose first dossier is
        one of them; None: no index.
        *laws* is SQL on ``n`` of the names of the laws the event is about, which ``q``
        matches as its title (a publication: the laws it changes or enacts); read from the
        graph by ``lawgraph feed-events`` into the title it writes (``lg_feed_events``),
        and by the feed from that row."""

    kind: str
    collection: str
    date: str
    where: str
    dossiers: str | None
    persons: str | None
    title: str
    ministry: str | None = None
    chamber: str = lit(CHAMBER_TK)
    parts: tuple[str, ...] = ()
    found: Callable[[str], str] | None = None
    dossier_found: Callable[[str], str] | None = None
    laws: str | None = None

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

_DOSSIER_NUMBERS = truthy_or("n.props -> 'dossier_numbers'", EMPTY_ARRAY)
_PAPER_DOSSIER_NUMBERS = truthy_or("n.pj_dossier_numbers", EMPTY_ARRAY)

_COMMITMENT_DOSSIERS = f"""(
            SELECT coalesce(json_agg(d.props -> 'label' ORDER BY d.label ASC NULLS FIRST),
                            {EMPTY_ARRAY})
            FROM {COLLECTION_EDGES} e
            JOIN {COLLECTION_DOSSIERS} d ON d.id = e.to_id
            WHERE e.from_id = n.id AND e.relation = {lit(RELATION_ABOUT)}
              AND e.to_collection = {lit(COLLECTION_DOSSIERS)}
        )"""

COMMITMENT_PERSONS = f"""json_build_array(json_build_object(
            'member_key', n.props -> 'member_key',
            'name', n.props -> 'minister_name',
            'function', n.props -> 'minister_role',
            'role', {lit(FIRST_SIGNATORY)}::text,
            'capacity', {lit(CAPACITY_GOVERNMENT)}::text
        ))"""

# The signatures of the document a vote decided: a paper of the case it singled out, the
# newest that has signatures. A case key is its TK GUID made a node key.
_CASE_ID = as_text("n.props -> 'primary_case_id'")
DECIDED_PERSONS = f"""coalesce((
            SELECT {truthy_or(_ACTORS_OF_PAPER, EMPTY_ARRAY)}
            FROM {COLLECTION_EDGES} e
            JOIN {COLLECTION_DOCUMENTS} paper ON paper.id = e.from_id
            WHERE e.to_id = {lit(COLLECTION_CASES + "/")}
                            || lg_node_key({_CASE_ID})
              AND e.relation = {lit(RELATION_PART_OF)}
              AND e.from_collection = {lit(COLLECTION_DOCUMENTS)}
              AND {has_length(_ACTORS_OF_PAPER)}
            ORDER BY paper.date DESC NULLS LAST, paper.key DESC
            LIMIT 1
        ), {EMPTY_ARRAY})"""


def bill_persons(label: str) -> str:
    """SQL: the signatures of a bill whose first dossier label is *label*: its own, else
    those of the first memorie van toelichting of its dossier, which the source signs where
    it leaves the voorstel itself unsigned."""
    return f"""CASE WHEN {has_length(_ACTORS_OF_N)} THEN {_ACTORS_OF_N}
        ELSE coalesce((
            SELECT {truthy_or(_ACTORS_OF_O, EMPTY_ARRAY)}
            FROM {COLLECTION_DOCUMENTS} o
            WHERE {label} IS NOT NULL AND o.dossier_numbers @> ARRAY[{label}]
              AND starts_with(o.kind, {lit(KIND_EXPLANATORY_MEMORANDUM)})
              AND {has_length(_ACTORS_OF_O)}
            ORDER BY o.date ASC NULLS FIRST, o.key ASC
            LIMIT 1
        ), {EMPTY_ARRAY}) END"""


ACTORS = truthy_or(_ACTORS_OF_N, EMPTY_ARRAY)

# The first dossier label of a row (``labels[0]``), when it is a string.
_LABEL = "lg_str(CASE WHEN json_typeof(l.labels) = 'array' THEN l.labels -> 0 END)"

# The chamber of a vote: one of the Eerste Kamer carries ``chamber`` ``EK``.
_VOTE_CHAMBER = "lg_str(" + truthy_or("n.props -> 'chamber'", "'\"TK\"'::json") + ")"


def _number(value: str) -> str:
    """SQL: the JSON number *value*, 0 when it is missing."""
    return f"coalesce(({value} {JSON_TEXT})::float8, 0)"


# The difference in seats (in members on a roll-call) between for and against.
_VOOR = f"n.props -> 'tally' -> '{VOTE_FOR}'"
_TEGEN = f"n.props -> 'tally' -> '{VOTE_AGAINST}'"
_MARGIN = f"abs(({_number(_VOOR)}) - ({_number(_TEGEN)}))"


def _document_source(kind: str) -> Source:
    return Source(
        kind=kind,
        collection=COLLECTION_DOCUMENTS,
        date="date",
        where=f"{lit(CHAMBER_TK)} = ANY(n.labels)",
        parts=_kind_parts("n.kind", kind),
        dossiers=_PAPER_DOSSIER_NUMBERS,
        persons=bill_persons(_LABEL) if kind == EVENT_BILL else ACTORS,
        title=truthy_or("n.pj_subject", "n.pj_title"),
        found=lambda q: f"{feed_title('n')} LIKE {_words.folded_like(q)}",
        dossier_found=_paper_dossier_found,
    )


def _paper_dossier_found(titled: str) -> str:
    """SQL: a paper (or vote) ``n`` of one of the dossiers *titled* selects."""
    return f"n.dossier_numbers && ARRAY({titled})"


def _tier_part(tier: str) -> str:
    """SQL: a judgment of *tier*: a part of its own, read on the index of the tier and the
    date of publication."""
    return f"n.tier = {lit(tier)}"


_CHANGES = ", ".join(lit(r) for r in CHANGE_RELATIONS)

# The key of the instrument an edge of a paper changes: of an article, the instrument it is
# of by its BWB id, else the target's own key.
LAW_KEY = f"""CASE WHEN e.to_collection = {lit(COLLECTION_ARTICLES)}
                                THEN lg_node_key(a.bwb_id)
                            ELSE substr(e.to_id, length(e.to_collection) + 2) END"""


def law_edges(paper: str) -> str:
    """SQL: ``FROM`` the edges (``e``) by which the paper *paper* (its id) changes a law, and
    of each into an article that article (``a``)."""
    return f"""FROM {COLLECTION_EDGES} e
                        LEFT JOIN {COLLECTION_ARTICLES} a
                            ON e.to_collection = {lit(COLLECTION_ARTICLES)}
                           AND a.id = e.to_id
                        WHERE e.from_id = {paper} AND e.relation IN ({_CHANGES})"""


# The names of the laws a publication ``n`` is about, as ``q`` matches them: the citation
# title (else the title) of each law it changes, adds to or repeals articles of, and of each
# it enacted, with its official title ("Wet van 8 juli 2026, houdende regels ter
# implementatie …"): the title of the publication itself.
_PUBLICATION_LAWS = f"""(
            SELECT string_agg(DISTINCT x.name, ' | ') FROM (
                SELECT {as_text(truthy_or("i.props -> 'citation_title'", "i.props -> 'title'"))} AS name
                FROM {COLLECTION_INSTRUMENTS} i
                WHERE i.key IN (SELECT {LAW_KEY} {law_edges("n.id")})
                UNION ALL
                SELECT unnest(ARRAY[
                    {as_text(truthy_or("r.props -> 'citation_title'", "r.props -> 'title'"))},
                    lg_str(r.props -> 'official_title')])
                FROM {COLLECTION_INSTRUMENTS} r
                WHERE {ENACTED} = {PUBLICATION_IDENTIFIER} AND {ENACTED_OF_REGULATION}
            ) x
            WHERE x.name <> ''
        )"""

CITATION_TITLE = truthy_or("i.props -> 'citation_title'", "i.props -> 'title'")
_BWB_ID = as_text("n.props -> 'bwb_id'")
BWB_KEY = bwb_key(_BWB_ID)

SOURCES: dict[str, Source] = {
    source.kind: source
    for source in (
        Source(
            kind=EVENT_COMMITMENT,
            collection=COLLECTION_COMMITMENTS,
            date="made_on",
            where="true",
            dossiers=_COMMITMENT_DOSSIERS,
            persons=COMMITMENT_PERSONS,
            title="n.props -> 'text'",
            ministry="n.ministry",
            found=lambda q: (
                f"{search_words(COLLECTION_COMMITMENTS, 'n')} LIKE {_words.lower_like(q)}"
            ),
            dossier_found=lambda titled: (
                f"n.id IN (SELECT e.from_id FROM {COLLECTION_EDGES} e"
                f" JOIN {COLLECTION_DOSSIERS} d ON d.id = e.to_id"
                f" WHERE e.relation = {lit(RELATION_ABOUT)}"
                f" AND e.to_collection = {lit(COLLECTION_DOSSIERS)}"
                f" AND d.label IN ({titled}))"
            ),
        ),
        *(_document_source(kind) for kind in DOCUMENT_EVENTS),
        Source(
            kind=EVENT_VOTE,
            collection=COLLECTION_DECISIONS,
            date="date",
            # read by date, not by the outcome (the props, not the indexed ``passed``: a
            # page reads the index on the date newest first and stops); of the Eerste
            # Kamer only the vote that decided the bill (its list names a vote on a motion
            # by the bill too)
            where=(
                "lg_bool(n.props -> 'passed') IS NOT NULL"
                f" AND (lg_str(n.props -> 'chamber') IS DISTINCT FROM '{CHAMBER_EK}'"
                " OR lg_bool(n.props -> 'bill_decision') IS TRUE)"
            ),
            dossiers=_DOSSIER_NUMBERS,
            persons=DECIDED_PERSONS,
            title="n.props -> 'subject'",
            chamber=_VOTE_CHAMBER,
            found=lambda q: (
                f"{search_words(COLLECTION_DECISIONS, 'n')} LIKE {_words.lower_like(q)}"
            ),
            dossier_found=_paper_dossier_found,
        ),
        Source(
            kind=EVENT_PUBLICATION,
            collection=COLLECTION_INSTRUMENTS,
            date="date_published",
            where=f"n.kind = {lit(INSTRUMENT_KIND_PUBLICATION)}",
            dossiers=_DOSSIER_NUMBERS,
            persons=None,
            title="n.props -> 'citation_title'",
            chamber="NULL",
            found=lambda q: f"n.s_citation_title_g LIKE {_words.folded_like(q)}",
            dossier_found=lambda titled: (
                f"{instrument_dossier_numbers('n')} && ARRAY({titled})"
            ),
            laws=_PUBLICATION_LAWS,
        ),
        Source(
            kind=EVENT_JUDGMENT,
            collection=COLLECTION_JUDGMENTS,
            # the day it was published, not decided: a judgment is news when it appears
            date="published_on",
            where="n.stub IS NOT TRUE AND n.same_as IS NULL",
            parts=tuple(_tier_part(tier) for tier in FEED_TIERS),
            dossiers=None,
            persons=None,
            title="n.pj_display_name",
            chamber="NULL",
            found=lambda q: f"n.s_display_name_g LIKE {_words.folded_like(q)}",
        ),
        Source(
            kind=EVENT_COMMENCEMENT,
            collection=COLLECTION_INSTRUMENT_VERSIONS,
            date="valid_from",
            where="true",
            dossiers=None,
            persons=None,
            chamber="NULL",
            title=(
                f"(SELECT {CITATION_TITLE} FROM {COLLECTION_INSTRUMENTS} i"
                f" WHERE i.key = {BWB_KEY})"
            ),
            # the versions of the instruments whose title holds the words: by the index
            # on the citation title, or without one (its title then) every such instrument
            # but the publications (``instruments_list_title``)
            found=lambda q: (
                "n.bwb_id = ANY(ARRAY("
                "SELECT unnest(ARRAY[i.bwb_id, i.key, upper(i.key)])"
                f" FROM {COLLECTION_INSTRUMENTS} i"
                f" WHERE i.s_citation_title_g LIKE {_words.folded_like(q)}"
                " OR (coalesce(i.citation_title, '') = ''"
                f" AND i.kind IS DISTINCT FROM {lit(INSTRUMENT_KIND_PUBLICATION)})))"
            ),
        ),
    )
}

# The kinds that are no event of either chamber: a filter on the chamber leaves them out.
_NO_CHAMBER = (EVENT_PUBLICATION, EVENT_COMMENCEMENT, EVENT_JUDGMENT)

# The dimensions that are counted as facets; each is a filter on the rows too.
DIMENSIONS = ("kind", "ministry", "faction", "cabinet", "chamber", "coalition")

# What every request reads first: factions by the ids of their Fractie records (an id two
# factions claim goes to the first by key) and the cabinets with a start; each read once
# (MATERIALIZED), not again for every lookup in it.
_SHORT = truthy_or("f.props -> 'abbreviation'", "f.props -> 'name'")
_EXTERNAL_IDS = truthy_or("f.props -> 'external_ids'", EMPTY_ARRAY)
PREAMBLE = f"""
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

# The period of the cabinet asked for: from its beëdiging to that of the next one; the
# cabinet in office has no end (NULL), not a bound that sorts after every date, which
# depends on the collation.
CABINET_PERIOD = f""",
    period AS (
        SELECT lg_str(cf.v) AS cabinet_from, NULLIF(lg_str(nx.v), '') AS cabinet_until
        FROM (
            SELECT (SELECT c.props -> 'from_date' FROM {COLLECTION_CABINETS} c
                    WHERE c.key = %(cabinet)s) AS v
        ) cf
        CROSS JOIN LATERAL (
            SELECT (SELECT c.props -> 'from_date' FROM {COLLECTION_CABINETS} c
                    WHERE {is_present("cf.v")}
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


def in_period(date: str) -> str:
    """SQL: *date* is in the period of the cabinet asked for (``period``)."""
    return (
        "(SELECT cabinet_from FROM period) IS NOT NULL"
        f" AND {date} >= (SELECT cabinet_from FROM period)"
        " AND ((SELECT cabinet_until FROM period) IS NULL"
        f" OR {date} < (SELECT cabinet_until FROM period))"
    )


def cabinet_on(date: str) -> str:
    """SQL: the key of the cabinet in office on *date*: the last to start on or before it
    (of two that start on one day the later key), from its period in ``cabinet_periods``."""
    return (
        f"(SELECT cp.key FROM cabinet_periods cp WHERE cp.from_date <= {date}"
        f" AND (cp.until IS NULL OR {date} < cp.until))"
    )


def kinds_of(filters: FeedFilters) -> tuple[str, ...] | None:
    """The kinds the feed keeps: those asked for; without, ``DEFAULT_KINDS``, unless a
    ``tier`` asks for judgments (None: every kind the other filters let through)."""
    if filters.kinds:
        return filters.kinds
    return None if filters.tiers else DEFAULT_KINDS


def dimension_filters(filters: FeedFilters, bind: dict[str, Any]) -> FacetFilters:
    """The filter of each facet dimension that is asked for, on the columns of ``events``."""
    clauses: dict[str, str] = {}
    kinds = kinds_of(filters)
    if kinds:
        clauses["kind"] = "kind = ANY(%(kinds)s)"
        bind["kinds"] = list(kinds)
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
        clauses["cabinet"] = in_period("date")
        bind["cabinet"] = filters.cabinet
    if filters.coalition:
        clauses["coalition"] = "%(coalition)s = ANY(coalition)"
        bind["coalition"] = filters.coalition
    return FacetFilters(own=clauses)


# The filters that hold for every facet, on the laterals of a kind's rows: ``l.labels``
# (its dossiers), ``p.persons``, ``t.title`` and ``fd`` (its first dossier).
_DOSSIER_FILTER = (
    f"EXISTS (SELECT 1 FROM {elements('l.labels')}"
    " WHERE json_typeof(x.v) IN ('string', 'number', 'boolean')"
    f" AND starts_with(x.v {JSON_TEXT}, %(dossier)s))"
)
_MEMBER_FILTER = (
    f"EXISTS (SELECT 1 FROM {elements('p.persons')}"
    " WHERE lg_str(x.v -> 'member_key') = %(member)s)"
    " OR ((SELECT person FROM member_person) IS NOT NULL"
    f" AND EXISTS (SELECT 1 FROM {elements('p.persons')}"
    " WHERE lg_str(x.v -> 'person_id') = (SELECT person FROM member_person)))"
)


def _contains(text: str, count: int) -> str:
    """SQL: the JSON *text* holds any of the *count* words of ``q`` (``_words``, the binds
    ``q_word_0`` …)."""
    return " OR ".join(_words.holds(as_text(text), f"q_word_{n}") for n in range(count))


def words_of(filters: FeedFilters) -> list[str]:
    """The words of ``q`` as they are matched, each once."""
    return [w for w in dict.fromkeys(_words.words(q) for q in filters.q) if w]


def _each_word(sql: Callable[[int], str], count: int) -> str:
    """SQL: *sql* of the number of a word (of its binds ``q_{n}``, ``q_whole_{n}``), for
    any of the *count* words."""
    return " OR ".join(sql(n) for n in range(count))


def shared_filters(filters: FeedFilters, bind: dict[str, Any]) -> list[str]:
    """The filters that hold for every facet, on the laterals of a kind's rows, but the
    filter on the words (``Kind.words``, which reads ``fd`` only where a kind has
    dossiers)."""
    clauses: list[str] = []
    if filters.dossier:
        clauses.append(_DOSSIER_FILTER)
        bind["dossier"] = filters.dossier
    if filters.member:
        clauses.append(_MEMBER_FILTER)
        bind["member"] = filters.member
    words = words_of(filters)
    for n, word in enumerate(words):
        bind[f"q_{n}"] = word
        bind[f"q_word_{n}"] = _words.word_pattern(word)
        bind[f"q_whole_{n}"] = _words.whole(word)
    if words:
        # what ``matched`` names per item: each word as it was asked, and its pattern
        asked = {_words.words(q): q.strip() for q in reversed(filters.q)}
        bind["q_terms"] = [asked.get(word, word) for word in words]
        bind["q_patterns"] = [_words.word_pattern(word) for word in words]
    return clauses


def kinds_to_read(filters: FeedFilters, *, facets: bool) -> list[Source]:
    """The kinds whose rows are read: those asked for (all of them for the facets, which
    count every kind), without those that cannot have the member or faction asked for."""
    chosen = FEED_KINDS if facets else (kinds_of(filters) or FEED_KINDS)
    sources = [SOURCES[kind] for kind in FEED_KINDS if kind in chosen]
    if filters.tiers:  # only a judgment has a tier
        judgments = [s for s in sources if s.kind == EVENT_JUDGMENT]
        parts = tuple(_tier_part(tier) for tier in filters.tiers)
        sources = [replace(s, parts=parts) for s in judgments]
    if filters.member or filters.faction:
        sources = [s for s in sources if s.persons is not None]
    if filters.faction:
        sources = [s for s in sources if s.kind != EVENT_COMMITMENT]
    if facets:  # every chamber is counted; ``chamber`` keeps the one asked for
        return sources
    if filters.coalition:  # only a vote has a coalition
        sources = [s for s in sources if s.kind == EVENT_VOTE]
    if filters.chamber == CHAMBER_EK:
        sources = [s for s in sources if s.kind == EVENT_VOTE]
    elif filters.chamber:
        sources = [s for s in sources if s.kind not in _NO_CHAMBER]
    return sources


@dataclass(frozen=True)
class Plan:
    """What the rows of one request are read under."""

    filters: FeedFilters
    facets: bool
    shared: list[str]
    dimensions: FacetFilters
    cursor: FeedCursor | None
    # the law followed is cited by many judgments: its judgments are read in date order
    # and tested one by one (``feed_relations.CITES_LAW``), not looked up all of them
    widely_cited: bool = False
    # a row reads its title and that of its first dossier without words of ``q`` too
    # (``lawgraph feed-events`` writes them)
    read_titles: bool = False

    @property
    def titles(self) -> bool:
        """Whether a row reads its title and that of its first dossier: for the words of
        ``q``, or when the plan asks for them."""
        return self.read_titles or bool(self.filters.q)

    @property
    def until(self) -> str | None:
        """The last day a kind reads: ``until``, and without facets no later than the
        cursor's day; None is no end (no bound after every date: that would depend on the
        collation of the database)."""
        days = [self.filters.until]
        if self.cursor is not None and not self.facets:
            days.append(self.cursor.date)
        return min((day for day in days if day), default=None)

    @property
    def needs_factions(self) -> bool:
        return self.facets or bool(self.filters.faction)

    @property
    def needs_coalition(self) -> bool:
        return self.facets or bool(self.filters.coalition)

    @property
    def needs_persons(self) -> bool:
        return self.needs_factions or bool(self.filters.member)


# The factions a row counts for: those its Kamerleden signed for, a faction as often as
# they did (``= ANY`` filters on them; the faction facet counts a row once per faction).
# Looked up in ``faction_map``: a join per row would hash the factions for every row.
_FACTIONS = f"""array_remove(ARRAY(
                SELECT (SELECT map FROM faction_map) ->> lg_str(x.v -> 'faction_id')
                FROM {elements("p.persons")}
                WHERE lg_str(x.v -> 'capacity') = {lit(CAPACITY_MEMBER)}
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
    ("coalition", "text[]"),
)


def coalition_of(vote_id: str) -> str:
    """SQL: what the coalition did on the vote *vote_id*, as ``FeedCoalition`` names it:
    its pattern, ``split`` for a ``wissel`` too, and ``decisive``; ``{}`` without a row of
    ``lg_decision_coalition``. Read when asked, never kept with the events."""
    return f"""ARRAY(
                SELECT v FROM lg_decision_coalition c
                CROSS JOIN LATERAL unnest(ARRAY[
                    c.pattern,
                    CASE WHEN c.pattern = 'wissel' THEN 'split' END,
                    CASE WHEN c.decisive THEN 'decisive' END
                ]) AS v
                WHERE c.id = {vote_id} AND v IS NOT NULL
            )"""


def _after_cursor(source: Source, cursor: FeedCursor) -> str:
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
class Kind:
    """The SQL of one kind's rows under a plan: its laterals and its expressions."""

    source: Source
    plan: Plan

    @property
    def first_dossier(self) -> bool:
        """Whether a row looks up its first dossier: for the ministry, or the titles."""
        return self.source.dossiers is not None and (
            self.source.ministry is None or self.plan.titles
        )

    @property
    def ministry(self) -> str:
        return self.source.ministry or ("fd.ministry" if self.first_dossier else "NULL")

    @property
    def factions(self) -> str:
        if self.plan.needs_factions and self.source.persons:
            return _FACTIONS
        return "'{}'::text[]"

    @property
    def coalition(self) -> str:
        if self.plan.needs_coalition and self.source.kind == EVENT_VOTE:
            return coalition_of("n.id")
        return "'{}'::text[]"

    def laterals(self) -> str:
        """``l`` (the labels), ``fd`` (the first dossier), ``p`` (the signatures) and
        ``t`` (the title), those the plan needs."""
        joins = [
            f"CROSS JOIN LATERAL (SELECT {self.source.dossiers or EMPTY_ARRAY}"
            " AS labels OFFSET 0) l"
        ]
        if self.first_dossier:
            joins.append(
                "LEFT JOIN LATERAL (SELECT d.ministry, d.props -> 'title' AS title"
                f" FROM {COLLECTION_DOSSIERS} d WHERE d.label = {_LABEL}"
                " ORDER BY d.key ASC LIMIT 1) fd ON true"
            )
        if self.plan.needs_persons:
            persons = self.source.persons or EMPTY_ARRAY
            joins.append(f"CROSS JOIN LATERAL (SELECT {persons} AS persons OFFSET 0) p")
        if self.plan.titles:
            joins.append(
                f"CROSS JOIN LATERAL (SELECT {self.source.title} AS title OFFSET 0) t"
            )
        return "".join(f"\n        {join}" for join in joins)

    @property
    def laws(self) -> str | None:
        """SQL: the names of the laws of the event as ``lawgraph feed-events`` last wrote
        them with its title (``Source.laws``); None for a kind without."""
        if self.source.laws is None:
            return None
        return (
            f"(SELECT e.title FROM {FEED_EVENTS_TABLE} e"
            f" WHERE e.kind = {lit(self.source.kind)} AND e.id = n.id)"
        )

    def words(self) -> str:
        """The filter on the words: in the title, in the title of the first dossier, or
        in the names of its laws."""
        count = len(words_of(self.plan.filters))
        found = _contains("t.title", count)
        if self.first_dossier:
            found += f" OR {_contains('fd.title', count)}"
        if self.laws:
            found += f" OR {_contains(f'to_json({self.laws})', count)}"
        return f"({found})"

    def candidates(self) -> str | None:
        """The rows that may hold the words, found by index (``Source.found``); None when
        the kind has no index for them or the words are too short for one."""
        words = words_of(self.plan.filters)
        own = self.source.found
        if own is None or not words:
            return None
        if any(len(word) < _words.TRIGRAM for word in words):
            return None
        count = len(words)
        found = _each_word(lambda n: own(f"q_{n}"), count)
        if self.laws:
            # the events whose written title may hold the words (``lg_feed_events``)
            found += " OR " + _each_word(
                lambda n: (
                    f"n.id IN (SELECT e.id FROM {FEED_EVENTS_TABLE} e"
                    f" WHERE e.kind = {lit(self.source.kind)}"
                    f" AND e.words @@ lg_word_query(%(q_{n})s, %(q_whole_{n})s))"
                ),
                count,
            )
        if self.first_dossier:
            of_dossiers = self.source.dossier_found
            if of_dossiers is None:
                return None
            titled = _each_word(
                lambda n: f"d.s_title_g LIKE {_words.folded_like(f'q_{n}')}", count
            )
            found += " OR " + of_dossiers(
                f"SELECT d.label FROM {COLLECTION_DOSSIERS} d"
                f" WHERE ({titled}) AND ({_contains('d.pj_title', count)})"
            )
        return f"({found})"

    def select(self) -> str:
        """The columns of the light row (``_ROW_COLUMNS``)."""
        vote = self.source.kind == EVENT_VOTE
        values = (
            lit(self.source.kind),
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
            self.coalition,
        )
        return ",\n            ".join(
            f"({value})::{sql_type} AS {name}"
            for value, (name, sql_type) in zip(values, _ROW_COLUMNS, strict=True)
        )

    def page_filters(self) -> list[str]:
        """Without facets, the filters on the ministry, the faction and the coalition of a
        row."""
        clauses = []
        if self.plan.filters.ministry:
            clauses.append(f"({self.ministry}) = %(ministry)s")
        if self.plan.filters.faction:
            clauses.append(f"%(faction)s = ANY({self.factions})")
        if self.plan.filters.coalition:
            clauses.append(f"%(coalition)s = ANY({self.coalition})")
        return clauses


def _rows_query(source: Source, plan: Plan) -> str:
    """The light rows of one kind (``_ROW_COLUMNS``). Without facets a kind reads one page,
    newest first: before anything else is looked up when no filter needs it."""
    kind = Kind(source, plan)
    date = f"n.{source.date}"
    head = [f"{date} >= %(since)s", source.condition]
    if plan.until is not None:
        head.insert(1, f"{date} <= %(until)s")
    if plan.filters.chamber and source.kind == EVENT_VOTE and not plan.facets:
        head.append(f"{_VOTE_CHAMBER} = %(chamber)s")
    candidates = kind.candidates()
    if candidates:
        head.append(candidates)
    if plan.filters.instrument:
        walked = plan.widely_cited and source.kind == EVENT_JUDGMENT
        head.append(CITES_LAW if walked else FOLLOWS[source.kind])
    tail = list(plan.shared)
    if words_of(plan.filters):
        tail.append(kind.words())
    table, order = f"{source.collection} n", ""
    if not plan.facets:
        tail += kind.page_filters()
        if plan.filters.cabinet:
            head.append(in_period(date))
        if plan.cursor is not None:
            head.append(_after_cursor(source, plan.cursor))
        order = _newest_first(source, "n.")
        if not tail:
            # one page of the kind first, then what its rows look up
            table = f"({_first_page(source, head)}) n"
            head, order = [], ""
    return f"""(
        SELECT {kind.select()}
        FROM {table}{kind.laterals()}
        {where(head + tail)}{order}
    )"""


def _newest_first(source: Source, row: str) -> str:
    """SQL: a page of the rows of *source*, newest first, its columns prefixed by *row*.
    NULLS FIRST, not LAST: no row of the date range is null, and so the order is that of
    the index on the date (or the kind and the date) read backwards."""
    return (
        f"\n        ORDER BY {row}{source.date} DESC NULLS FIRST, {row}id ASC"
        "\n        LIMIT %(page_size)s"
    )


def _first_page(source: Source, head: list[str]) -> str:
    """SQL: the first page of *source* under *head*, newest first. Of a kind in parts
    (a ``Document.Soort`` and its ``kind (…)``) each part is read in the order of its own
    index, a page at most, and the pages are merged: no part is read whole for a page."""
    indent = "            "
    order = _newest_first(source, "n.")
    if not source.parts:
        return f"\n{indent}SELECT * FROM {source.collection} n {where(head)}{order}\n"
    kept = [source.where if clause == source.condition else clause for clause in head]
    pages = "\n        UNION ALL ".join(
        f"(SELECT * FROM {source.collection} n {where([*kept, part])}{order})"
        for part in source.parts
    )
    merged = _newest_first(source, "")
    return f"\n        SELECT * FROM (\n        {pages}\n        ) n{merged}\n"


def per_faction(rows: str) -> str:
    """SQL: the rows *rows* once per faction (``fx.faction``), a row without one once."""
    return (
        f"{rows} CROSS JOIN LATERAL unnest(CASE WHEN cardinality(factions) > 0"
        " THEN factions ELSE ARRAY[NULL]::text[] END) AS fx(faction)"
    )


def per_coalition(rows: str) -> str:
    """SQL: the rows *rows* once per value of their ``coalition`` (``cx.value``)."""
    return f"{rows} CROSS JOIN LATERAL unnest(coalition) AS cx(value)"


def dimension_facet(plan: Plan, name: str) -> str:
    """A facet: the rows under every filter but its own, counted per value."""
    others = plan.dimensions.where(name)
    if name == "cabinet":
        return facet_of(f"""
            SELECT value, sum(n)::int AS count
            FROM (
                SELECT {cabinet_on("per_day.date")} AS value, per_day.n
                FROM (SELECT date, count(*) AS n FROM events {others}
                      GROUP BY date) per_day
            ) dated
            GROUP BY value""")
    if name == "faction":
        # a row counts once for a faction, however many of its signers signed for it
        once = f"""(
                SELECT DISTINCT fx.faction AS value, id FROM {per_faction("events")} {others}
            ) once"""
        return facet("value", once)
    if name == "coalition":
        # a vote counts for each that holds; an event without one counts for none
        return facet("value", per_coalition("events"), others)
    return facet(name, "events", others)


def rows_of(filters: FeedFilters, plan: Plan, *, facets: bool) -> str:
    """The CTEs that read ``events``: the preamble and the light rows of every kind read."""
    ctes = PREAMBLE
    if filters.cabinet:
        ctes += CABINET_PERIOD
    if filters.member:
        ctes += _MEMBER_PERSON
    if filters.instrument:
        ctes += followed_ctes(article=bool(filters.article))
    sources = kinds_to_read(filters, facets=facets)
    union = "\n    UNION ALL ".join(_rows_query(s, plan) for s in sources)
    if not union:
        columns = ", ".join(f"NULL::{t} AS {name}" for name, t in _ROW_COLUMNS)
        union = f"SELECT {columns} WHERE false"
    return f"WITH {ctes},\n    events AS ({union}\n    )"
