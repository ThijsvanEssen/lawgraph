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

import datetime as dt
import time
from dataclasses import dataclass, replace
from typing import Any, cast

from lawgraph.config.constants import (
    CHAMBER_EK,
    CHAMBER_TK,
    CHANGE_RELATIONS,
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
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
    RELATION_ABOUT,
    RELATION_PART_OF,
)
from lawgraph.core.bwb_xml import KIND_PUBLICATION as INSTRUMENT_KIND_PUBLICATION
from lawgraph.core.dossier_stages import LEGISLATIVE_KINDS
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
from lawgraph.core.judgments import KIND_CONCLUSIE
from lawgraph.core.time import day_before
from lawgraph.core.tk_records import (
    CAPACITY_GOVERNMENT,
    CAPACITY_MEMBER,
    FIRST_SIGNATORY,
    KIND_EXPLANATORY_MEMORANDUM,
)
from lawgraph.core.votes import VOTE_AGAINST, VOTE_FOR
from lawgraph.db import GraphStore
from lawgraph.db.queries import _words
from lawgraph.db.queries._helpers import COUNTS_BUDGET
from lawgraph.db.queries._json_sql import (
    EMPTY_ARRAY,
    array_or_empty,
    as_text,
    has_length,
    is_present,
    truthy_or,
)
from lawgraph.db.queries.coalition_sql import coalition_factions, coalition_object
from lawgraph.db.queries.feed_relations import (
    CITATIONS_OF_LAW,
    CITES_LAW,
    COMMENCED,
    ENACTED,
    ENACTED_OF_REGULATION,
    FOLLOWS,
    PUBLICATION_IDENTIFIER,
    RELATIONS,
    followed_ctes,
    via,
)
from lawgraph.db.queries.judgment_light import OUTCOME_KEYS
from lawgraph.db.schema import (
    FEED_EVENTS_TABLE,
    INSTRUMENT_DOSSIER_NUMBERS,
    feed_title,
    search_words,
)
from lawgraph.db.store import read_budget, read_time_left
from lawgraph.db.version_cache import lasting

# The instruments a publication names at most.
MAX_CHANGED_INSTRUMENTS = 10
# The props of the page's nodes the items show; never the text of a paper.
_ITEM_PROPS = (
    "kind",
    "title",
    "subject",
    "display_name",
    "document_number",
    "sequence",
    # with ``sequence``, what the readable address of a paper or a commitment is made of
    # (``core.readable_paths.path_of``): its own dossier, and the letter of an Eerste Kamer
    # paper or the number of a commitment
    "dossier_number",
    "dossier_suffix",
    "number",
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
    "ecli",
    "court_code",
    "tier",
    "court_kind",
    "procedure",
    "date_eff",
    "published_on",
    "summary",
    "advocate_general",
    "advocate_general_role",
    # how a judgment ended, what a conclusion proposes, what the ECHR found
    # (``queries/judgment_light.OUTCOME_KEYS``)
    *OUTCOME_KEYS,
    "source",
)
# The name a bill gives itself: "Deze wet wordt aangehaald als: Wet sterkere archieven.",
# up to the full stop or the end of its line, without the spaces around it.
_CITED = r"wordt aangehaald als:?\s*([^.\s][^.\n]{1,148}[^.\s])"

_JSON_TEXT = "#>> '{}'"


def _lit(value: str) -> str:
    """SQL: *value* as a string literal."""
    return "'" + value.replace("'", "''") + "'"


def _kind_parts(field: str, kind: str) -> tuple[str, str]:
    """SQL: *field* is *kind* itself, and *field* is ``kind (…)``: a range, as the AQL had
    it, so the index on the kind and the date reads a page of it. The range holds under the
    ICU collation of the schema, which counts the space and the brackets (glibc ignores
    them); ``schema.check_collation`` refuses a database without it."""
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
    # what the coalition did on a vote (``FEED_COALITION``); keeps votes alone
    coalition: str | None = None
    # the tiers of the judgments; None: ``FEED_TIERS``. A tier keeps judgments alone.
    tiers: tuple[str, ...] | None = None
    instrument: str | None = None
    article: str | None = None


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
        them. *found* is SQL on ``n`` that an index serves and that holds for every row whose
        title holds ``q``, and *dossier_found* for every row whose first dossier is one of
        ``{titled}`` (the labels of the dossiers whose title holds it); None: no index.
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
    chamber: str = _lit(CHAMBER_TK)
    parts: tuple[str, ...] = ()
    found: str | None = None
    dossier_found: str | None = None
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
# newest that has signatures. A case key is its TK GUID made a node key.
_CASE_ID = as_text("n.props -> 'primary_case_id'")
_DECIDED_PERSONS = f"""coalesce((
            SELECT {truthy_or(_ACTORS_OF_PAPER, EMPTY_ARRAY)}
            FROM {COLLECTION_EDGES} e
            JOIN {COLLECTION_DOCUMENTS} paper ON paper.id = e.from_id
            WHERE e.to_id = {_lit(COLLECTION_CASES + "/")}
                            || lg_node_key({_CASE_ID})
              AND e.relation = {_lit(RELATION_PART_OF)}
              AND e.from_collection = {_lit(COLLECTION_DOCUMENTS)}
              AND {has_length(_ACTORS_OF_PAPER)}
            ORDER BY paper.date DESC NULLS LAST, paper.key DESC
            LIMIT 1
        ), {EMPTY_ARRAY})"""

# The signatures of a bill: its own, else those of the first memorie van toelichting of its
# dossier, which the source signs where it leaves the voorstel itself unsigned. ``{label}``
# is the bill's first dossier label.
_BILL_PERSONS = f"""CASE WHEN {has_length(_ACTORS_OF_N)} THEN {_ACTORS_OF_N}
        ELSE coalesce((
            SELECT {truthy_or(_ACTORS_OF_O, EMPTY_ARRAY)}
            FROM {COLLECTION_DOCUMENTS} o
            WHERE {{label}} IS NOT NULL AND o.dossier_numbers @> ARRAY[{{label}}]
              AND starts_with(o.kind, {_lit(KIND_EXPLANATORY_MEMORANDUM)})
              AND {has_length(_ACTORS_OF_O)}
            ORDER BY o.date ASC NULLS FIRST, o.key ASC
            LIMIT 1
        ), {EMPTY_ARRAY}) END"""

_ACTORS = truthy_or(_ACTORS_OF_N, EMPTY_ARRAY)

# The chamber of a vote: one of the Eerste Kamer carries ``chamber`` ``EK``.
_VOTE_CHAMBER = "lg_str(" + truthy_or("n.props -> 'chamber'", "'\"TK\"'::json") + ")"


def _number(value: str) -> str:
    """SQL: AQL's TO_NUMBER of the JSON *value*: a number, 1 for true, else 0."""
    return (
        f"CASE json_typeof({value}) WHEN 'number' THEN ({value} {_JSON_TEXT})::float8"
        f" WHEN 'boolean' THEN ({value} {_JSON_TEXT})::boolean::int ELSE 0 END"
    )


# The difference in seats (in members on a roll-call) between for and against.
_VOOR = f"n.props -> 'tally' -> '{VOTE_FOR}'"
_TEGEN = f"n.props -> 'tally' -> '{VOTE_AGAINST}'"
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
        title=truthy_or("n.pj_subject", "n.pj_title"),
        found=f"{feed_title('n')} LIKE {_words.FOLDED_LIKE}",
        dossier_found="n.dossier_numbers && ARRAY({titled})",
    )


def _tier_part(tier: str) -> str:
    """SQL: a judgment of *tier*: a part of its own, read on the index of the tier and the
    date of publication."""
    return f"n.tier = {_lit(tier)}"


_CHANGES = ", ".join(_lit(r) for r in CHANGE_RELATIONS)

# The key of the instrument an edge of a paper changes: of an article, the instrument it is
# of by its BWB id, else the target's own key.
_LAW_KEY = f"""CASE WHEN e.to_collection = {_lit(COLLECTION_ARTICLES)}
                                THEN lg_node_key(a.bwb_id)
                            ELSE substr(e.to_id, length(e.to_collection) + 2) END"""
_LAW_EDGES = f"""FROM {COLLECTION_EDGES} e
                        LEFT JOIN {COLLECTION_ARTICLES} a
                            ON e.to_collection = {_lit(COLLECTION_ARTICLES)}
                           AND a.id = e.to_id
                        WHERE e.from_id = {{paper}} AND e.relation IN ({_CHANGES})"""

# The names of the laws a publication ``n`` is about, as ``q`` matches them: the citation
# title (else the title) of each law it changes, adds to or repeals articles of, and of each
# it enacted, with its official title ("Wet van 8 juli 2026, houdende regels ter
# implementatie …"): the title of the publication itself.
_PUBLICATION_LAWS = f"""(
            SELECT string_agg(DISTINCT x.name, ' | ') FROM (
                SELECT {as_text(truthy_or("i.props -> 'citation_title'", "i.props -> 'title'"))} AS name
                FROM {COLLECTION_INSTRUMENTS} i
                WHERE i.key IN (SELECT {_LAW_KEY} {_LAW_EDGES.replace("{paper}", "n.id")})
                UNION ALL
                SELECT unnest(ARRAY[
                    {as_text(truthy_or("r.props -> 'citation_title'", "r.props -> 'title'"))},
                    lg_str(r.props -> 'official_title')])
                FROM {COLLECTION_INSTRUMENTS} r
                WHERE {ENACTED} = {PUBLICATION_IDENTIFIER} AND {ENACTED_OF_REGULATION}
            ) x
            WHERE x.name <> ''
        )"""

_CITATION_TITLE = truthy_or("i.props -> 'citation_title'", "i.props -> 'title'")
_BWB_ID = as_text("n.props -> 'bwb_id'")
# The key of the instrument of that BWB id: the id in lower case (all letters and digits, so
# ``lg_node_key`` makes the same of it, but the planner prices that higher here and turns the
# join of the page; tests/pg/test_node_key_sql.py).
_BWB_KEY = f"lower({_BWB_ID})"

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
            found=f"{search_words(COLLECTION_COMMITMENTS, 'n')} LIKE {_words.LOWER_LIKE}",
            dossier_found=(
                f"n.id IN (SELECT e.from_id FROM {COLLECTION_EDGES} e"
                f" JOIN {COLLECTION_DOSSIERS} d ON d.id = e.to_id"
                f" WHERE e.relation = {_lit(RELATION_ABOUT)}"
                f" AND e.to_collection = {_lit(COLLECTION_DOSSIERS)}"
                " AND d.label IN ({titled}))"
            ),
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
                f" AND (lg_str(n.props -> 'chamber') IS DISTINCT FROM '{CHAMBER_EK}'"
                " OR lg_bool(n.props -> 'bill_decision') IS TRUE)"
            ),
            dossiers=_DOSSIER_NUMBERS,
            persons=_DECIDED_PERSONS,
            title="n.props -> 'subject'",
            chamber=_VOTE_CHAMBER,
            found=f"{search_words(COLLECTION_DECISIONS, 'n')} LIKE {_words.LOWER_LIKE}",
            dossier_found="n.dossier_numbers && ARRAY({titled})",
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
            found=f"n.s_citation_title_g LIKE {_words.FOLDED_LIKE}",
            dossier_found=(
                f"{INSTRUMENT_DOSSIER_NUMBERS.replace('props', 'n.props')}"
                " && ARRAY({titled})"
            ),
            laws=_PUBLICATION_LAWS,
        ),
        _Source(
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
            found=f"n.s_display_name_g LIKE {_words.FOLDED_LIKE}",
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
                f" WHERE i.key = {_BWB_KEY})"
            ),
            # the versions of the instruments whose title holds the words: by the index
            # on the citation title, or without one (its title then) every such instrument
            # but the publications (``instruments_list_title``)
            found=(
                "n.bwb_id = ANY(ARRAY("
                "SELECT unnest(ARRAY[i.bwb_id, i.key, upper(i.key)])"
                f" FROM {COLLECTION_INSTRUMENTS} i"
                f" WHERE i.s_citation_title_g LIKE {_words.FOLDED_LIKE}"
                " OR (coalesce(i.citation_title, '') = ''"
                f" AND i.kind IS DISTINCT FROM {_lit(INSTRUMENT_KIND_PUBLICATION)})))"
            ),
        ),
    )
}

# The kinds that are no event of either chamber: a filter on the chamber leaves them out.
_NO_CHAMBER = (EVENT_PUBLICATION, EVENT_COMMENCEMENT, EVENT_JUDGMENT)

# The dimensions that are counted as facets; each is a filter on the rows too.
_DIMENSIONS = ("kind", "ministry", "faction", "cabinet", "chamber", "coalition")

# What every request reads first: factions by the ids of their Fractie records (an id two
# factions claim goes to the first by key) and the cabinets with a start; each read once
# (MATERIALIZED), not again for every lookup in it.
_SHORT = truthy_or("f.props -> 'abbreviation'", "f.props -> 'name'")
_EXTERNAL_IDS = truthy_or("f.props -> 'external_ids'", EMPTY_ARRAY)
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

# The period of the cabinet asked for: from its beëdiging to that of the next one; the
# cabinet in office has no end (NULL), not a bound that sorts after every date, which
# depends on the collation.
_CABINET_PERIOD = f""",
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

_IN_PERIOD = (
    "(SELECT cabinet_from FROM period) IS NOT NULL"
    " AND {date} >= (SELECT cabinet_from FROM period)"
    " AND ((SELECT cabinet_until FROM period) IS NULL"
    " OR {date} < (SELECT cabinet_until FROM period))"
)


def _cabinet_on(date: str) -> str:
    """SQL: the key of the cabinet in office on *date*: the last to start on or before it
    (of two that start on one day the later key), from its period in ``cabinet_periods``."""
    return (
        f"(SELECT cp.key FROM cabinet_periods cp WHERE cp.from_date <= {date}"
        f" AND (cp.until IS NULL OR {date} < cp.until))"
    )


def _kinds(filters: FeedFilters) -> tuple[str, ...] | None:
    """The kinds the feed keeps: those asked for; without, ``DEFAULT_KINDS``, unless a
    ``tier`` asks for judgments (None: every kind the other filters let through)."""
    if filters.kinds:
        return filters.kinds
    return None if filters.tiers else DEFAULT_KINDS


def _dimension_filters(filters: FeedFilters, bind: dict[str, Any]) -> dict[str, str]:
    """The filter of each facet dimension that is asked for, on the columns of ``events``."""
    clauses: dict[str, str] = {}
    kinds = _kinds(filters)
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
        clauses["cabinet"] = _IN_PERIOD.replace("{date}", "date")
        bind["cabinet"] = filters.cabinet
    if filters.coalition:
        clauses["coalition"] = "%(coalition)s = ANY(coalition)"
        bind["coalition"] = filters.coalition
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


def _contains(text: str, count: int) -> str:
    """SQL: the JSON *text* holds any of the *count* words of ``q`` (``_words``, the binds
    ``q_word_0`` …)."""
    return " OR ".join(_words.holds(as_text(text), f"q_word_{n}") for n in range(count))


def _words_of(filters: FeedFilters) -> list[str]:
    """The words of ``q`` as they are matched, each once."""
    return [w for w in dict.fromkeys(_words.words(q) for q in filters.q) if w]


def _each_word(sql: str, count: int) -> str:
    """SQL: *sql*, written for the binds ``q`` and ``q_whole``, for any of the *count*
    words."""
    return " OR ".join(
        sql.replace("%(q)s", f"%(q_{n})s").replace("%(q_whole)s", f"%(q_whole_{n})s")
        for n in range(count)
    )


def _shared_filters(filters: FeedFilters, bind: dict[str, Any]) -> list[str]:
    """The filters that hold for every facet, on the laterals of a kind's rows."""
    clauses: list[str] = []
    if filters.dossier:
        clauses.append(_DOSSIER_FILTER)
        bind["dossier"] = filters.dossier
    if filters.member:
        clauses.append(_MEMBER_FILTER)
        bind["member"] = filters.member
    words = _words_of(filters)
    for n, word in enumerate(words):
        if n == 0:
            clauses.append(_WORDS)
        bind[f"q_{n}"] = word
        bind[f"q_word_{n}"] = _words.word_pattern(word)
        bind[f"q_whole_{n}"] = _words.whole(word)
    if words:
        # what ``matched`` names per item: each word as it was asked, and its pattern
        asked = {_words.words(q): q.strip() for q in reversed(filters.q)}
        bind["q_terms"] = [asked.get(word, word) for word in words]
        bind["q_patterns"] = [_words.word_pattern(word) for word in words]
    return clauses


def _kinds_to_read(filters: FeedFilters, *, facets: bool) -> list[_Source]:
    """The kinds whose rows are read: those asked for (all of them for the facets, which
    count every kind), without those that cannot have the member or faction asked for."""
    chosen = FEED_KINDS if facets else (_kinds(filters) or FEED_KINDS)
    sources = [_SOURCES[kind] for kind in FEED_KINDS if kind in chosen]
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
    # the law followed is cited by many judgments: its judgments are read in date order
    # and tested one by one (``feed_relations.CITES_LAW``), not looked up all of them
    widely_cited: bool = False

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
    ("coalition", "text[]"),
)


def coalition_of(vote_id: str) -> str:
    """SQL: what the coalition did on the vote *vote_id*, as ``FEED_COALITION`` names it:
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
            persons = (self.source.persons or EMPTY_ARRAY).replace("{label}", _LABEL)
            joins.append(f"CROSS JOIN LATERAL (SELECT {persons} AS persons OFFSET 0) p")
        if self.plan.filters.q:
            joins.append(
                f"CROSS JOIN LATERAL (SELECT {self.source.title} AS title OFFSET 0) t"
            )
        return "".join(f"\n        {join}" for join in joins)

    @property
    def laws(self) -> str | None:
        """SQL: the names of the laws of the event as ``lawgraph feed-events`` last wrote
        them with its title (``_Source.laws``); None for a kind without."""
        if self.source.laws is None:
            return None
        return (
            f"(SELECT e.title FROM {FEED_EVENTS_TABLE} e"
            f" WHERE e.kind = {_lit(self.source.kind)} AND e.id = n.id)"
        )

    def words(self) -> str:
        """The filter on the words: in the title, in the title of the first dossier, or
        in the names of its laws."""
        count = len(_words_of(self.plan.filters))
        found = _contains("t.title", count)
        if self.first_dossier:
            found += f" OR {_contains('fd.title', count)}"
        if self.laws:
            found += f" OR {_contains(f'to_json({self.laws})', count)}"
        return f"({found})"

    def candidates(self) -> str | None:
        """The rows that may hold the words, found by index (``_Source.found``); None when
        the kind has no index for them or the words are too short for one."""
        words = _words_of(self.plan.filters)
        if self.source.found is None or not words:
            return None
        if any(len(word) < _words.TRIGRAM for word in words):
            return None
        count = len(words)
        found = _each_word(self.source.found, count)
        if self.laws:
            # the events whose written title may hold the words (``lg_feed_events``)
            found += " OR " + _each_word(
                f"n.id IN (SELECT e.id FROM {FEED_EVENTS_TABLE} e"
                f" WHERE e.kind = {_lit(self.source.kind)}"
                " AND e.words @@ lg_word_query(%(q)s, %(q_whole)s))",
                count,
            )
        if self.first_dossier:
            if self.source.dossier_found is None:
                return None
            titled = (
                f"SELECT d.label FROM {COLLECTION_DOSSIERS} d"
                f" WHERE ({_each_word(f'd.s_title_g LIKE {_words.FOLDED_LIKE}', count)})"
                f" AND ({_contains('d.pj_title', count)})"
            )
            found += " OR " + self.source.dossier_found.replace("{titled}", titled)
        return f"({found})"

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


def _rows_query(source: _Source, plan: _Plan) -> str:
    """The light rows of one kind (``_ROW_COLUMNS``). Without facets a kind reads one page,
    newest first: before anything else is looked up when no filter needs it."""
    kind = _Kind(source, plan)
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
    f" ORDER BY cnt DESC, value ASC NULLS FIRST), {EMPTY_ARRAY})"
)
_PER_FACTION = (
    "events CROSS JOIN LATERAL unnest(CASE WHEN cardinality(factions) > 0"
    " THEN factions ELSE ARRAY[NULL]::text[] END) AS fx(faction)"
)
_PER_COALITION = "events CROSS JOIN LATERAL unnest(coalition) AS cx(value)"


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
    if name == "coalition":
        # a vote counts for each that holds; an event without one counts for none
        return f"""({_FACET_AGG} FROM (
            SELECT value, count(*)::int AS cnt
            FROM {_PER_COALITION}{where}
            GROUP BY 1
        ) counted)"""
    return f"""({_FACET_AGG} FROM (
            SELECT {name} AS value, count(*)::int AS cnt
            FROM events{where}
            GROUP BY 1
        ) counted)"""


_OWN_ACTORS = "props -> 'actors'"

# The props of a judgment an item shows, from its columns: its own props hold its text and
# paragraphs, which a read of one prop would parse; the A-G of a conclusion alone.
_JUDGMENT_PROPS = f"""json_build_object(
                'display_name', pj_display_name, 'ecli', pj_ecli,
                'court_code', pj_court_code, 'tier', pj_tier,
                'court_kind', pj_court_kind, 'decision_kind', pj_decision_kind,
                'procedure', to_json(procedure), 'date_eff', pj_date_eff,
                'published_on', to_json(published_on), 'summary', pj_summary,
                'source', pj_source,
                'advocate_general', CASE WHEN pj_decision_kind {_JSON_TEXT} = {_lit(KIND_CONCLUSIE)}
                    THEN props -> 'advocate_general' END,
                'advocate_general_role', CASE WHEN pj_decision_kind {_JSON_TEXT} = {_lit(KIND_CONCLUSIE)}
                    THEN props -> 'advocate_general_role' END
            )"""


def _node_of(row: str) -> str:
    """SQL: ``n``, the node (``id``, ``props``, ``pj_actors``) of the page row *row*."""
    tables = sorted({s.collection for s in _SOURCES.values()})
    props = {COLLECTION_JUDGMENTS: _JUDGMENT_PROPS}
    # a paper's signatures from their column; a judgment has none
    actors = {COLLECTION_DOCUMENTS: "pj_actors", COLLECTION_JUDGMENTS: "NULL::json"}
    union = "\n            UNION ALL ".join(
        f"SELECT id, {props.get(table, 'props')} AS props, "
        f"{actors.get(table, _OWN_ACTORS)} AS pj_actors"
        f" FROM {table} WHERE id = {row}.id"
        for table in tables
    )
    return f"""CROSS JOIN LATERAL (
            {union}
        ) n"""


_PAPER_TEXT = (
    "CASE WHEN lg_truthy(paper.props -> 'text') THEN paper.props ->> 'text' ELSE '' END"
)
# ``case_ids OR []`` and ``signatures OR []`` walked: a value that is no array as ``[]``.
_CASE_IDS = array_or_empty("paper.props -> 'case_ids'")


def _official_short(label: str) -> str:
    """SQL: the name the bill of the dossier labelled *label* goes by, from official data
    only: the citation title its own text gives ("Deze wet wordt aangehaald als: …"), the
    citation title the Kamer gives its case, or the citation title of the one Dutch law it
    changes; ``{title, basis}`` with ``basis`` ``citation``, ``case`` or ``amended_law``,
    null when none of them is there."""
    return f"""(
            SELECT CASE
                WHEN os.cited IS NOT NULL THEN json_build_object(
                    'title', os.cited, 'basis', 'citation'::text)
                WHEN os.case_title IS NOT NULL THEN json_build_object(
                    'title', os.case_title, 'basis', 'case'::text)
                WHEN {is_present("law.props -> 'bwb_id'")}
                     AND {is_present("law.props -> 'citation_title'")}
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
                         || lg_node_key(ids.case_id {_JSON_TEXT})
                     WHERE {is_present("c.props -> 'citation_title'")}
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
# its TK GUID made a node key) and its faction. The keys MERGE adds come in the
# order ArangoDB gave them (that of its hash map, the same for these names every time).
# The member's name is the expression of ``members.list_name`` on its props: read as the
# column, the planner turns the join of the page.
_MEMBER_NAME = truthy_or(
    truthy_or("m.props -> 'name'", "m.props -> 'known_as'"),
    "m.props -> 'government_name'",
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
                ORDER BY s.o), {EMPTY_ARRAY}) AS value
            FROM json_array_elements({array_or_empty("sig.value")})
                WITH ORDINALITY AS s(p, o)
            CROSS JOIN LATERAL (SELECT CASE
                WHEN lg_truthy(s.p -> 'member_key') THEN s.p -> 'member_key'
                WHEN {is_present("s.p -> 'person_id'")}
                    THEN to_json(lg_node_key(s.p ->> 'person_id'))
            END AS key) who
            LEFT JOIN LATERAL (
                SELECT props FROM {COLLECTION_MEMBERS} WHERE key = (who.key {_JSON_TEXT})
            ) m ON true
        ) persons"""

_CHANGED_TITLE = truthy_or("c.props -> 'citation_title'", "c.props -> 'title'")
# The laws a publication enacts (``establishes``: the regulations that name it as the one
# that enacted them, with their articles) and those it changes, each once: ``amends``,
# ``introduces`` or ``repeals`` where every change it makes in the law is of that one kind,
# else ``amends``, with the articles it touches; the laws it enacts first, then by title.
_CHANGED_INSTRUMENTS = f"""CASE WHEN pg.kind = {_lit(EVENT_PUBLICATION)} THEN (
                SELECT coalesce(json_agg(json_build_object(
                    'key', c.key,
                    'title', {_CHANGED_TITLE},
                    'bwb_id', c.props -> 'bwb_id',
                    'effect', c.effect,
                    'article_count', c.articles
                ) ORDER BY c.rank, c.citation_title ASC NULLS FIRST, c.key ASC), {EMPTY_ARRAY})
                FROM (
                    SELECT c.*
                    FROM (
                        SELECT DISTINCT ON (i.key) i.key, i.props, i.citation_title,
                               changed.effect, changed.articles, changed.rank
                        FROM (
                            SELECT r.key, 'establishes' AS effect,
                                   r.article_count::int AS articles, 0 AS rank
                            FROM {COLLECTION_INSTRUMENTS} r
                            WHERE {ENACTED} = {PUBLICATION_IDENTIFIER}
                              AND {ENACTED_OF_REGULATION}
                            UNION ALL
                            SELECT law.key,
                                   CASE WHEN count(DISTINCT law.relation) = 1
                                        THEN lower(min(law.relation)) ELSE 'amends' END,
                                   count(DISTINCT law.article)::int, 1
                            FROM (
                                SELECT {_LAW_KEY} AS key, e.relation,
                                       CASE WHEN e.to_collection = {_lit(COLLECTION_ARTICLES)}
                                            THEN e.to_id END AS article
                                {_LAW_EDGES.replace("{paper}", "pg.id")}
                            ) law
                            GROUP BY law.key
                        ) changed
                        JOIN {COLLECTION_INSTRUMENTS} i ON i.key = changed.key
                        ORDER BY i.key, changed.rank
                    ) c
                    ORDER BY c.rank, c.citation_title ASC NULLS FIRST, c.key ASC
                    LIMIT {MAX_CHANGED_INSTRUMENTS}
                ) c
            ) ELSE {EMPTY_ARRAY} END"""

_CHANGED_ARTICLES = f"""CASE WHEN pg.kind = {_lit(EVENT_COMMENCEMENT)} THEN (
                SELECT count(*)::int FROM {COLLECTION_ARTICLE_VERSIONS} v
                WHERE lg_str(n.props -> 'bwb_id') IS NOT NULL
                  AND v.bwb_id = lg_str(n.props -> 'bwb_id')
                  AND v.valid_from = lg_str(n.props -> 'valid_from')
            ) ELSE 0 END"""

# The title of an item ``pg`` the words of ``q`` are matched in, as its kind's ``_Source.title``
# (on the full node ``n`` of the page), in lower case.
_MATCHED_TITLE = f"""lower(CASE pg.kind
                WHEN {_lit(EVENT_COMMITMENT)} THEN n.props ->> 'text'
                WHEN {_lit(EVENT_VOTE)} THEN n.props ->> 'subject'
                WHEN {_lit(EVENT_PUBLICATION)} THEN n.props ->> 'citation_title'
                WHEN {_lit(EVENT_JUDGMENT)} THEN n.props ->> 'display_name'
                WHEN {_lit(EVENT_COMMENCEMENT)} THEN instrument.value ->> 'title'
                ELSE {as_text(truthy_or("n.props -> 'subject'", "n.props -> 'title'"))} END)"""
# Per word of ``q`` that an item holds, where it holds it (``{term, field}``): its ``title``,
# else the ``dossier_title`` of its first dossier, else the names of its ``laws`` (of a
# publication, as ``lawgraph feed-events`` wrote them with its title); read for the items
# of the page alone.
_MATCHED = f"""(
                SELECT coalesce(json_agg(json_build_object('term', w.term, 'field', w.field)
                                         ORDER BY w.n), {EMPTY_ARRAY})
                FROM (
                    SELECT w.n, w.term, CASE
                        WHEN {_MATCHED_TITLE} ~ w.pattern THEN 'title'
                        WHEN lower(dossier.value ->> 'title') ~ w.pattern THEN 'dossier_title'
                        WHEN pg.kind = {_lit(EVENT_PUBLICATION)} AND (
                            SELECT e.title FROM {FEED_EVENTS_TABLE} e
                            WHERE e.kind = pg.kind AND e.id = pg.id) ~ w.pattern THEN 'laws'
                    END AS field
                    FROM unnest(%(q_terms)s::text[], %(q_patterns)s::text[])
                        WITH ORDINALITY AS w(term, pattern, n)
                ) w
                WHERE w.field IS NOT NULL
            )"""

_RELATIONS = ",\n            ".join(f"{_lit(name)}, {sql}" for name, sql in RELATIONS)

# The page (``page``), read in full: the node's props, its first dossier, the cabinet on its
# date, the signatures with their factions, of a paper whether it has its text and its
# dictum (``lg_document_light``), of a vote what the coalition did, and what a kind adds (who
# made a commitment, the laws a publication enacts or changes, the law, the articles and the
# publication of a new version and what it is issued under), the sources it is tied to
# (``feed_relations.RELATIONS``), where it holds the words of ``q`` (``matched``) and how it
# is tied to the law followed (``via``, ``{via}`` until ``_items``). The props as KEEP gave
# them: in the byte order of their names, as MERGE (``lg_merge``).
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
            'has_text', light.props -> 'has_text',
            'dictum', light.props -> 'dictum',
            'persons', persons.value,
            'instrument', instrument.value,
            'changed_articles', {_CHANGED_ARTICLES},
            'changed_instruments', {_CHANGED_INSTRUMENTS},
            'commenced', {COMMENCED},
            {_RELATIONS},
            'matched', {{matched}},
            'via', {{via}},
            'coalition', {coalition_object("co")},
            'coalition_factions', {coalition_factions("co")}
        ) ORDER BY {_PAGE_ORDER}), {EMPTY_ARRAY})
        FROM page pg
        {_node_of("pg")}
        -- of a paper: whether its text is in the data and a motion's dictum, kept light
        LEFT JOIN lg_document_light light ON light.id = pg.id
        -- of a vote of the Tweede Kamer: what the coalition did (``tk-coalition-votes``)
        LEFT JOIN LATERAL (
            SELECT c.* FROM lg_decision_coalition c
            WHERE pg.kind = {_lit(EVENT_VOTE)} AND c.id = pg.id
            OFFSET 0
        ) co ON true
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
                'article_count', i.props -> 'article_count',
                'date_in_force', i.props -> 'date_in_force',
                'kind', i.props -> 'kind'
            ) AS value
            FROM {COLLECTION_INSTRUMENTS} i
            WHERE pg.kind = {_lit(EVENT_COMMENCEMENT)} AND i.key = {_BWB_KEY}
        ) instrument ON true
    )"""


def _rows_of(filters: FeedFilters, plan: _Plan, *, facets: bool) -> str:
    """The CTEs that read ``events``: the preamble and the light rows of every kind read."""
    ctes = _PREAMBLE
    if filters.cabinet:
        ctes += _CABINET_PERIOD
    if filters.member:
        ctes += _MEMBER_PERSON
    if filters.instrument:
        ctes += followed_ctes(article=bool(filters.article))
    sources = _kinds_to_read(filters, facets=facets)
    union = "\n    UNION ALL ".join(_rows_query(s, plan) for s in sources)
    if not union:
        columns = ", ".join(f"NULL::{t} AS {name}" for name, t in _ROW_COLUMNS)
        union = f"SELECT {columns} WHERE false"
    return f"WITH {ctes},\n    events AS ({union}\n    )"


def _base_bind(filters: FeedFilters, limit: int) -> dict[str, Any]:
    bind: dict[str, Any] = {
        "since": filters.since or "0",
        "page_size": limit + 1,
        "cited": _CITED,
        "item_props": list(_ITEM_PROPS),
    }
    if filters.instrument:
        bind["instrument"] = filters.instrument
        bind["article"] = filters.article
    return bind


def _items(filters: FeedFilters) -> str:
    """``_ITEMS``, with ``matched`` of each item under words and ``via`` when *filters*
    follow a law."""
    tie = via(article=bool(filters.article)) if filters.instrument else "NULL::json"
    matched = _MATCHED if filters.q else "NULL::json"
    return _ITEMS.replace("{via}", tie).replace("{matched}", matched)


def _page_query(plan: _Plan) -> str:
    """The page, with facets the total and the facets too, and the answer."""
    if not plan.facets:
        return f""",
    page AS (SELECT * FROM events ORDER BY {_ORDER} LIMIT %(page_size)s)
    SELECT json_build_object('items', {_items(plan.filters)}, 'total', NULL, 'facets', NULL)"""
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
        'items', {_items(plan.filters)},
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
    widely_cited: bool = False,
) -> tuple[str, dict[str, Any]]:
    """The SQL of one page of the feed and its parameters. It reads ``limit + 1`` rows,
    so the caller knows whether a next page exists. *widely_cited*: the law followed is
    (``widely_cited``)."""
    bind = _base_bind(filters, limit)
    plan = _Plan(
        filters=filters,
        facets=facets,
        shared=_shared_filters(filters, bind),
        dimensions=_dimension_filters(filters, bind),
        cursor=cursor,
        widely_cited=widely_cited,
    )
    if cursor is not None:
        bind["cursor_date"] = cursor.date
        bind["cursor_id"] = cursor.id
        bind["cursor_rank"] = cursor.rank
    bind["until"] = plan.until  # a kind reads no row after the cursor's date
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
            'dossiers', coalesce(ds.value, {EMPTY_ARRAY}),
            'votes', coalesce(v.value, {EMPTY_ARRAY})
        ) ORDER BY d.date DESC NULLS LAST), {EMPTY_ARRAY}) AS value
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
        ) ORDER BY nums.number ASC), {EMPTY_ARRAY}) AS value
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
    bind["until"] = plan.until
    dimensions = _where(list(plan.dimensions.values()), "        ")
    summary = _SUMMARY.replace("{dimensions}", dimensions).replace(
        _ITEMS, _items(filters)
    )
    return _rows_of(filters, plan, facets=True) + summary, bind


def get_feed_summary(
    store: GraphStore,
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
    store: GraphStore,
    filters: FeedFilters,
    *,
    cursor: FeedCursor | None = None,
    limit: int = 50,
    facets: bool = True,
) -> dict[str, Any]:
    """One page of the feed: ``items`` (up to ``limit + 1``: one more than the page when
    there is a next page), and with *facets* ``total`` and ``facets`` (null without), or,
    while those are counted longer than ``COUNTS_BUDGET``, null and ``partial``. Words or a
    faction without a first day are searched back in windows (``_page_items``): when the
    budget ends that search, ``partial`` and ``searched_from``.

    The page is read without the facets: each kind reads its rows in date order and stops
    after one page. The total and the facets read every row under the filters (20 s on the
    full graph), whatever the cursor: they are kept per data version under the filters
    (``version_cache``)."""
    items, searched_from = _page_items(store, filters, cursor, limit)
    shown: dict[str, Any] = {"items": items}
    if searched_from:
        shown.update(partial=True, searched_from=searched_from)
    if not facets:
        return {**shown, "total": None, "facets": None}
    with read_budget(COUNTS_BUDGET, "The counts of the feed"):
        return {
            **shown,
            **(_counts_of_events(store, filters) or feed_counts(store, filters)),
        }
    # counted on for the next request (``lasting``); this one shows the page now
    return {**shown, "total": None, "facets": None, "partial": True}


# Words, a faction or a law without a first day (``q``, ``faction`` or ``instrument``, and no
# ``since``): a word that few events hold, a faction that signs few events of a kind (a
# letter of the government: none) or a law few events are tied to, has every event of every
# kind tested for it, the whole history (over 30 s for ``faction=vvd`` on prod, 11 Oct). The page is read back in windows,
# newest first, each of these many days further back from where it starts, then the rest,
# until it is full or ``WORDS_BUDGET`` seconds are spent: then what was found is answered,
# ``partial``, with the first day searched (``searched_from``), and a request with ``until``
# the day before goes on from there.
WORDS_WINDOWS = (90, 365, 3 * 365)
WORDS_BUDGET = 8.0


def _page_items(
    store: GraphStore, filters: FeedFilters, cursor: FeedCursor | None, limit: int
) -> tuple[list[dict[str, Any]], str | None]:
    """The rows of one page (up to ``limit + 1``) and, when the budget ended the search
    before the first event, the first day it searched."""
    if filters.since or not (filters.q or filters.faction or filters.instrument):
        return _rows(store, filters, cursor, limit), None
    bounded = _bounded_page(store, filters, cursor, limit)
    if bounded is not None:
        return bounded, None
    start = cursor.date[:10] if cursor else filters.until or dt.date.today().isoformat()
    end = dt.date.fromisoformat(start)
    left = read_time_left()
    deadline = time.monotonic() + (
        WORDS_BUDGET if left is None else min(WORDS_BUDGET, left)
    )
    items: list[dict[str, Any]] = []
    until = filters.until
    searched_from = (end + dt.timedelta(days=1)).isoformat()  # nothing searched yet
    for days in (*WORDS_WINDOWS, None):
        since = (end - dt.timedelta(days=days)).isoformat() if days else None
        window = replace(filters, since=since, until=until)
        with read_budget(
            deadline - time.monotonic(), "The words of the feed"
        ) as budget:
            items += _rows(store, window, cursor, limit - len(items))
        if budget.ran_out:
            return items, searched_from
        if len(items) > limit or since is None:
            return items[: limit + 1], None
        searched_from = since
        until = day_before(since)
    return items, None


def _bounded_page(
    store: GraphStore, filters: FeedFilters, cursor: FeedCursor | None, limit: int
) -> list[dict[str, Any]] | None:
    """The page under words or a faction without a first day, read once from the first
    day it reaches back to (``feed_events.first_day_of_page``: by the index on the words of the events,
    not window after window); None where that table cannot tell, or the page read from that
    day is short of what it counted (an event gone since it was written): then the
    windows."""
    # it reads the events as this module does
    from lawgraph.db.queries import feed_events

    before = cursor.date[:10] if cursor else None
    found = feed_events.first_day_of_page(
        store, replace(filters, kinds=_kinds(filters)), limit, before
    )
    if found is None:
        return None
    first, whole_page = found
    items = _rows(store, replace(filters, since=first), cursor, limit)
    if len(items) > limit:
        return items[: limit + 1]
    # fewer than a page: the rest of the history, unless the table held a page the feed
    # did not find
    return None if whole_page else items


def _rows(
    store: GraphStore, filters: FeedFilters, cursor: FeedCursor | None, limit: int
) -> list[dict[str, Any]]:
    """Up to ``limit + 1`` rows of the feed under *filters*, from *cursor* on."""
    sql, bind = feed_query(
        filters,
        cursor=cursor,
        limit=limit,
        facets=False,
        widely_cited=_widely_cited(store, filters),
    )
    rows = list(store.query(sql, bind))
    page = cast(dict[str, Any], rows[0]) if rows else {"items": []}
    return page.get("items") or []


# From this many citations by judgments a law followed is ``widely_cited``.
WIDELY_CITED = 5000


def _widely_cited(store: GraphStore, filters: FeedFilters) -> bool:
    """Whether the page under *filters* reads the judgments of a law (or article) cited by
    ``WIDELY_CITED`` judgments or more: its newest judgments are then found soonest in date
    order, while those of a law cited a few times are found soonest from its citations.
    Counted up to that many, by the index of the edges into its articles."""
    if not filters.instrument:
        return False
    kinds = _kinds(filters) or FEED_KINDS
    if EVENT_JUDGMENT not in kinds:
        return False
    rows = store.query(CITATIONS_OF_LAW, {**_base_bind(filters, 0), "n": WIDELY_CITED})
    # one column: each row is its value
    return bool(next(iter(rows), False))


# How long the total and the facets of the feed under a filter are kept (seconds), whatever
# the data does: each reads every event of every kind (a minute on the full graph), and a
# run of the pipelines hardly moves them. The page itself is read fresh.
COUNTS_MAX_AGE = 3600.0


def _counts_of_events(store: GraphStore, filters: FeedFilters) -> dict[str, Any] | None:
    """Under words, a faction or a coalition, ``total`` and ``facets`` from
    ``lg_feed_events`` (by the index on their words or factions, not a read of every event,
    which takes a minute and more on prod for each such filter); None without them or where
    that table cannot tell: then ``feed_counts``."""
    if not (filters.q or filters.faction or filters.coalition):
        return None
    # it reads the events as this module does
    from lawgraph.db.queries import feed_events

    return feed_events.get_counts(store, filters, COUNTS_MAX_AGE)


def feed_counts(store: GraphStore, filters: FeedFilters) -> dict[str, Any]:
    """``total`` and ``facets`` of the feed under *filters*, of every page alike, kept
    ``COUNTS_MAX_AGE``. The feed without filters and that of each single kind come from
    one reading of the events for all of them (``_counts_per_kind``)."""
    kinds = _shared_kinds(filters)
    if kinds is None:
        return lasting(
            store, ("feed", filters), lambda: _counts(store, filters), COUNTS_MAX_AGE
        )
    shared = replace(filters, kinds=None)
    per_kind = lasting(
        store,
        ("feed per kind", shared),
        lambda: _counts_per_kind(store, shared),
        COUNTS_MAX_AGE,
    )
    return per_kind[kinds]


def _counts(store: GraphStore, filters: FeedFilters) -> dict[str, Any]:
    """``total`` and ``facets`` of the feed under *filters*, of every page alike."""
    sql, bind = feed_query(filters, limit=1, facets=True)
    rows = list(store.query(sql, bind))
    row = cast(dict[str, Any], rows[0]) if rows else {}
    return {"total": row.get("total"), "facets": row.get("facets")}


# The sets of kinds counted in one reading of the events: the feed without a kind (its
# ``DEFAULT_KINDS``) and every kind on its own.
_KIND_SETS: tuple[tuple[str, ...], ...] = (
    DEFAULT_KINDS,
    *((kind,) for kind in FEED_KINDS),
)


def _shared_kinds(filters: FeedFilters) -> tuple[str, ...] | None:
    """The set of ``_KIND_SETS`` *filters* asks for when it filters on nothing but the
    kind (and the dates); None when it filters on more."""
    if replace(filters, kinds=None, since=None, until=None) != FeedFilters():
        return None
    kinds = filters.kinds or DEFAULT_KINDS
    return kinds if kinds in _KIND_SETS else None


def _counts_per_kind(
    store: GraphStore, filters: FeedFilters
) -> dict[tuple[str, ...], dict[str, Any]]:
    """Per set of ``_KIND_SETS`` the ``total`` and ``facets`` of the feed under *filters*
    (which keeps no kind), from one reading of the events: what ``_counts`` gives for each,
    in the same order (a facet by count, then by value)."""
    sql, bind = counts_per_kind_query(filters)
    rows = list(store.query(sql, bind))
    found = cast(dict[str, Any], rows[0]) if rows else {}
    totals = found.get("total") or {}
    facets = {name: found.get(name) or {} for name in _DIMENSIONS if name != "kind"}
    answers: dict[tuple[str, ...], dict[str, Any]] = {}
    for n, kinds in enumerate(_KIND_SETS):
        set_id = str(n)
        answers[kinds] = {
            "total": totals.get(set_id, 0),
            "facets": {
                name: (
                    (found.get("kind") or [])
                    if name == "kind"
                    else facets[name].get(set_id, [])
                )
                for name in _DIMENSIONS
            },
        }
    return answers


def counts_per_kind_query(filters: FeedFilters) -> tuple[str, dict[str, Any]]:
    """The SQL of ``_counts_per_kind`` and its parameters: the events of every kind read
    once (``events``), each counted for every set of ``_KIND_SETS`` that holds its kind."""
    bind = _base_bind(filters, 1)
    plan = _Plan(
        filters=filters,
        facets=True,
        shared=_shared_filters(filters, bind),
        dimensions={},
        cursor=None,
    )
    bind["until"] = plan.until
    bind["set_ids"] = [str(n) for n, kinds in enumerate(_KIND_SETS) for _ in kinds]
    bind["set_kinds"] = [kind for kinds in _KIND_SETS for kind in kinds]
    per_set = ",\n        ".join(
        f"{_lit(name)}, {_facet_per_set(name)}"
        for name in _DIMENSIONS
        if name != "kind"
    )
    return (
        _rows_of(filters, plan, facets=True)
        + f""",
    in_set AS (
        SELECT s.set_id, e.*
        FROM events e
        JOIN unnest(%(set_ids)s::text[], %(set_kinds)s::text[]) AS s(set_id, kind)
            ON s.kind = e.kind
    )
    SELECT json_build_object(
        'total', (SELECT json_object_agg(set_id, n) FROM (
            SELECT set_id, count(*)::int AS n FROM in_set GROUP BY set_id) t),
        'kind', ({_FACET_AGG} FROM (
            SELECT kind AS value, count(*)::int AS cnt FROM events GROUP BY 1) counted),
        {per_set}
    )""",
        bind,
    )


def _facet_per_set(name: str) -> str:
    """SQL: per set of ``in_set`` the facet *name*, as ``_facet`` counts it (no other
    filter than the set's kinds), by set id."""
    if name == "cabinet":
        counted = f"""SELECT set_id, value, sum(n)::int AS cnt FROM (
                SELECT set_id, {_cabinet_on("per_day.date")} AS value, per_day.n
                FROM (SELECT set_id, date, count(*) AS n FROM in_set
                      GROUP BY set_id, date) per_day
            ) dated GROUP BY set_id, value"""
    elif name == "faction":
        counted = f"""SELECT set_id, value, count(*)::int AS cnt FROM (
                SELECT DISTINCT set_id, fx.faction AS value, id
                FROM {_PER_FACTION.replace("events", "in_set")}
            ) once GROUP BY set_id, value"""
    elif name == "coalition":
        counted = f"""SELECT set_id, value, count(*)::int AS cnt
            FROM {_PER_COALITION.replace("events", "in_set")}
            GROUP BY set_id, value"""
    else:
        counted = f"""SELECT set_id, {name} AS value, count(*)::int AS cnt
            FROM in_set GROUP BY set_id, value"""
    return f"""(SELECT json_object_agg(set_id, facet) FROM (
            SELECT set_id, coalesce(json_agg(json_build_object('value', value, 'count', cnt)
                ORDER BY cnt DESC, value ASC NULLS FIRST), {EMPTY_ARRAY}) AS facet
            FROM ({counted}) counted
            GROUP BY set_id
        ) per_set)"""
