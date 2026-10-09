"""Queries behind the decision (vote) endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import (
    CHAMBER_EK,
    CHAMBER_TK,
    COLLECTION_CASES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    RELATION_ABOUT,
    RELATION_PART_OF,
    RELATION_VOTED,
)
from lawgraph.core.models import make_node_key
from lawgraph.core.tk_records import VOTE_AGAINST, VOTE_FOR
from lawgraph.db import GraphStore
from lawgraph.db._rows import node_doc
from lawgraph.db.queries import _words
from lawgraph.db.schema import search_words
from lawgraph.db.store import (
    ReadTimedOut,
    RequestCancelled,
    read_time_left,
    reset_read_deadline,
    set_read_deadline,
)
from lawgraph.db.version_cache import lasting


@dataclass(frozen=True)
class DecisionFilters:
    """What ``GET /api/decisions`` narrows the decisions to; None is no filter.

    *party* with *choice* keeps the decisions that party voted that way on (``Voor``,
    ``Tegen``: ``meta.choice`` of its VOTED edge); *party* alone the ones it voted on.
    *dossier* is a dossier number, matched against the numbers on the decision; *q* the
    words of the subject, any of them (``_words``: each from the start of a word, a short
    one whole, any case). *party_votes* asks how factions voted on the decisions, without
    keeping any out: the keys of factions, or ``("all",)`` for every faction that voted.
    *coalition* keeps the votes on which the coalition did that (``COALITION_VALUES``,
    ``lg_decision_coalition``): voted ``together``, ``split`` (no wisselmeerderheid),
    ``wissel``, or ``carried`` or ``decisive`` the vote.
    """

    kinds: tuple[str, ...] | None = None
    passed: bool | None = None
    party: str | None = None
    choice: str | None = None
    chamber: str | None = None
    dossier: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    q: tuple[str, ...] = ()
    party_votes: tuple[str, ...] = ()
    coalition: str | None = None


EMPTY_FACETS: dict[str, list[Any]] = {
    "kind": [],
    "passed": [],
    "days": [],
    "years": [],
    "party_votes": [],
    "coalition": [],
}

# What the coalition did on a vote, as ``coalition`` filters and counts it: a pattern of
# ``lg_decision_coalition`` (each vote has one), or a flag of it.
COALITION_PATTERNS = ("together", "split", "wissel")
COALITION_FLAGS = ("carried", "decisive")
COALITION_VALUES = COALITION_PATTERNS + COALITION_FLAGS


def _common_filters(filters: DecisionFilters, bind: dict[str, Any]) -> list[str]:
    """The conditions on the decision ``d`` but for kind and outcome."""
    clauses: list[str] = []
    if filters.chamber is not None:
        # TK decisions carry the label "TK", EK ones "EK".
        clauses.append("%(chamber)s = ANY(d.labels)")
        bind["chamber"] = filters.chamber.upper()
    if filters.dossier:
        # Served by the array index on ``dossier_numbers``.
        clauses.append("d.dossier_numbers @> ARRAY[%(dossier)s]::text[]")
        bind["dossier"] = filters.dossier
    if filters.date_from:
        clauses.append("d.date >= %(date_from)s")
        bind["date_from"] = filters.date_from
    if filters.date_to:
        clauses.append("d.date <= %(date_to)s")
        bind["date_to"] = filters.date_to
    clauses += _words_filters(filters, bind)
    if filters.party:
        # Start from the faction's own edges rather than scanning every vote.
        choice = ""
        if filters.choice:
            choice = "AND lg_str(e.doc -> 'meta' -> 'choice') = %(choice)s"
            bind["choice"] = filters.choice
        clauses.append(
            f"""d.id IN (
                SELECT e.to_id FROM edges e
                WHERE e.from_id = %(faction_id)s AND e.relation = %(voted)s {choice}
            )"""
        )
        bind["faction_id"] = (
            f"{COLLECTION_FACTIONS}/{make_node_key(filters.party.strip())}"
        )
        bind["voted"] = RELATION_VOTED
    return clauses


def _words_filters(filters: DecisionFilters, bind: dict[str, Any]) -> list[str]:
    """The decisions whose subject holds any of the words of *filters*: by the trigram
    index on the words of a decision when each has three letters or more, then tested."""
    words = [w for w in dict.fromkeys(_words.words(q) for q in filters.q) if w]
    if not words:
        return []
    found, holds = [], []
    for n, word in enumerate(words):
        bind[f"q_{n}"] = word
        bind[f"q_word_{n}"] = _words.word_pattern(word)
        found.append(
            f"{search_words(COLLECTION_DECISIONS, 'd')} LIKE {_words.lower_like(f'q_{n}')}"
        )
        # AQL LOWER of a missing subject is "", of a number its digits.
        holds.append(_words.holds("coalesce(d.props ->> 'subject', '')", f"q_word_{n}"))
    clauses = [f"({' OR '.join(holds)})"]
    if all(len(word) >= _words.TRIGRAM for word in words):
        clauses.insert(0, f"({' OR '.join(found)})")
    return clauses


def _kind_filter(filters: DecisionFilters, bind: dict[str, Any]) -> list[str]:
    if not filters.kinds:
        return []
    bind["kinds"] = list(filters.kinds)
    return ["r.kind = ANY(%(kinds)s)"]


def _passed_filter(filters: DecisionFilters, bind: dict[str, Any]) -> list[str]:
    if filters.passed is None:
        return []
    bind["passed"] = filters.passed
    return ["r.passed = %(passed)s"]


def _coalition_filter(filters: DecisionFilters, bind: dict[str, Any]) -> list[str]:
    if filters.coalition is None:
        return []
    if filters.coalition in COALITION_FLAGS:
        return [f"r.coalition_{filters.coalition} IS TRUE"]
    bind["coalition"] = filters.coalition
    return ["r.coalition_pattern = %(coalition)s"]


def _coalition_facet(where: list[str]) -> str:
    """SQL: ``[{value, count}]`` of the filtered decisions per thing the coalition did,
    in the order of ``COALITION_VALUES``, those with none left out."""
    counts = ", ".join(
        [
            f"count(*) FILTER (WHERE r.coalition_pattern = '{p}') AS {p}"
            for p in COALITION_PATTERNS
        ]
        + [
            f"count(*) FILTER (WHERE r.coalition_{f} IS TRUE) AS {f}"
            for f in COALITION_FLAGS
        ]
    )
    values = ", ".join(f"({n}, '{v}', c.{v})" for n, v in enumerate(COALITION_VALUES))
    return f"""(
        SELECT coalesce(json_agg(
            json_build_object('value', x.v, 'count', x.n) ORDER BY x.o
        ), '[]'::json)
        FROM (SELECT {counts} FROM filtered r {_where(where)}) c
        CROSS JOIN LATERAL (VALUES {values}) AS x(o, v, n)
        WHERE x.n > 0
    )"""


def _where(clauses: list[str]) -> str:
    return f"WHERE {' AND '.join(clauses)}" if clauses else ""


def _object_or_empty(value: str) -> str:
    """SQL: AQL ``value != null ? value : {}``."""
    return (
        f"CASE WHEN coalesce(json_typeof({value}), 'null') <> 'null'"
        f" THEN {value} ELSE '{{}}'::json END"
    )


# A row of the list, in the order of its keys. ``chamber`` is the stored one when it is
# set (AQL ``||``), else the first of the chambers whose label the decision carries.
_ITEM = f"""json_build_object(
    'id', d.id,
    'key', d.key,
    'date', d.props -> 'date',
    'subject', d.props -> 'subject',
    'display_name', d.props -> 'display_name',
    'external_id', d.props -> 'decision_id',
    'dossier_numbers', d.props -> 'dossier_numbers',
    'kind', d.props -> 'kind',
    'primary_case_kind', d.props -> 'primary_case_kind',
    'decision_kind', d.props -> 'decision_kind',
    'passed', d.props -> 'passed',
    'chamber', CASE
        WHEN lg_truthy(d.props -> 'chamber') THEN d.props -> 'chamber'
        ELSE to_json((
            SELECT c FROM unnest(%(chambers)s::text[]) WITH ORDINALITY AS u(c, n)
            WHERE c = ANY(d.labels) ORDER BY n LIMIT 1
        ))
    END,
    'result', d.props -> 'result',
    'method', d.props -> 'method',
    'bill_decision', d.props -> 'bill_decision',
    'vote_kind', d.props -> 'vote_kind',
    'tally', {_object_or_empty("d.props -> 'tally'")},
    'voters', {_object_or_empty("d.props -> 'voters'")},
    'primary_case_id', d.props -> 'primary_case_id',
    'coalition', CASE WHEN c.id IS NULL THEN NULL ELSE json_build_object(
        'cabinet', c.cabinet,
        'coalition_for', c.coalition_for,
        'coalition_against', c.coalition_against,
        'opposition_for', c.opposition_for,
        'opposition_against', c.opposition_against,
        'pattern', c.pattern,
        'carried', c.carried,
        'decisive', c.decisive
    ) END
)"""

# The order of the list: newest first, the key settling a day.
_ORDER = "r.date DESC NULLS LAST, r.key ASC"


def _facet(value: str, rows: str, where: list[str]) -> str:
    """SQL: the JSON array ``[{value, count}]`` of *rows* per *value*, most first, then
    by value."""
    return f"""(
        SELECT coalesce(json_agg(
            json_build_object('value', value, 'count', count)
            ORDER BY count DESC, value ASC NULLS FIRST
        ), '[]'::json)
        FROM (
            SELECT {value} AS value, count(*)::int AS count
            FROM {rows} r {_where(where)}
            GROUP BY 1
        ) facet
    )"""


# How many of the rows ``r`` there are, carried and did not.
_OUTCOMES = (
    "count(*)::int AS count,"
    " (count(*) FILTER (WHERE r.passed IS TRUE))::int AS passed,"
    " (count(*) FILTER (WHERE r.passed IS FALSE))::int AS rejected"
)


def _kind_facet(where: list[str]) -> str:
    """SQL: ``[{value, count, passed, rejected}]`` of the filtered decisions per kind,
    most first, then by kind."""
    return f"""(
        SELECT coalesce(json_agg(
            json_build_object(
                'value', value, 'count', count, 'passed', passed, 'rejected', rejected
            )
            ORDER BY count DESC, value ASC NULLS FIRST
        ), '[]'::json)
        FROM (
            SELECT r.kind AS value, {_OUTCOMES}
            FROM filtered r {_where(where)}
            GROUP BY 1
        ) facet
    )"""


# Per faction asked (``votes_of``: its id), how it voted on the decisions under every
# filter (``matching``), in all, per kind and per year: ``voor``, ``tegen`` and ``none``
# (any other choice, or no vote: a roll-call vote is one of members, not of their faction).
# Its votes are its VOTED edges into them, read from ``edges_to_cover``.
_PARTY_VOTES = f"""(
    WITH cast_votes AS (
        SELECT e.from_id AS party_id, m.kind, left(m.date, 4) AS year,
               lg_str(e.doc -> 'meta' -> 'choice') AS choice
        FROM matching m
        JOIN edges e ON e.to_id = m.id AND e.relation = %(voted)s
         AND e.from_collection = '{COLLECTION_FACTIONS}'
        WHERE {{parties}}
    ),
    asked AS (
        SELECT party_id FROM votes_of
    ),
    per_kind AS (
        SELECT a.party_id, t.value,
               count(v.*) FILTER (WHERE v.choice = %(voor)s)::int AS voor,
               count(v.*) FILTER (WHERE v.choice = %(tegen)s)::int AS tegen,
               t.count
        FROM asked a
        CROSS JOIN (SELECT r.kind AS value, count(*)::int AS count
                    FROM matching r GROUP BY 1) t
        LEFT JOIN cast_votes v ON v.party_id = a.party_id
         AND v.kind IS NOT DISTINCT FROM t.value
        GROUP BY a.party_id, t.value, t.count
    ),
    per_year AS (
        SELECT a.party_id, t.value,
               count(v.*) FILTER (WHERE v.choice = %(voor)s)::int AS voor,
               count(v.*) FILTER (WHERE v.choice = %(tegen)s)::int AS tegen,
               t.count
        FROM asked a
        CROSS JOIN (SELECT left(r.date, 4) AS value, count(*)::int AS count
                    FROM matching r GROUP BY 1) t
        LEFT JOIN cast_votes v ON v.party_id = a.party_id
         AND v.year IS NOT DISTINCT FROM t.value
        GROUP BY a.party_id, t.value, t.count
    )
    SELECT coalesce(json_agg(json_build_object(
        'party', f.key,
        'name', coalesce(lg_str(f.props -> 'abbreviation'), lg_str(f.props -> 'name')),
        'voor', coalesce(k.voor, 0),
        'tegen', coalesce(k.tegen, 0),
        'none', (SELECT count(*)::int FROM matching)
                - coalesce(k.voor, 0) - coalesce(k.tegen, 0),
        'kind', k.kinds,
        'years', y.years
    ) ORDER BY f.key ASC NULLS LAST), '[]'::json)
    FROM asked a
    JOIN {COLLECTION_FACTIONS} f ON f.id = a.party_id
    LEFT JOIN LATERAL (
        SELECT sum(p.voor)::int AS voor, sum(p.tegen)::int AS tegen,
               coalesce(json_agg(json_build_object(
                   'value', p.value, 'voor', p.voor, 'tegen', p.tegen,
                   'none', p.count - p.voor - p.tegen
               ) ORDER BY p.count DESC, p.value ASC NULLS FIRST), '[]'::json) AS kinds
        FROM per_kind p WHERE p.party_id = a.party_id
    ) k ON true
    LEFT JOIN LATERAL (
        SELECT coalesce(json_agg(json_build_object(
                   'year', p.value, 'voor', p.voor, 'tegen', p.tegen,
                   'none', p.count - p.voor - p.tegen
               ) ORDER BY p.value ASC NULLS FIRST), '[]'::json) AS years
        FROM per_year p WHERE p.party_id = a.party_id
    ) y ON true
)"""


def _party_votes(filters: DecisionFilters, bind: dict[str, Any]) -> str:
    """SQL: ``_PARTY_VOTES`` of the factions *filters* asks for; ``[]`` when it asks none."""
    if not filters.party_votes:
        return "'[]'::json"
    bind |= {"voted": RELATION_VOTED, "voor": VOTE_FOR, "tegen": VOTE_AGAINST}
    if filters.party_votes == ("all",):
        # every faction that voted on one of them
        votes_of = (
            "SELECT DISTINCT e.from_id AS party_id FROM matching m"
            " JOIN edges e ON e.to_id = m.id AND e.relation = %(voted)s"
            f" AND e.from_collection = '{COLLECTION_FACTIONS}'"
        )
        parties = "true"
    else:
        bind["vote_parties"] = [
            f"{COLLECTION_FACTIONS}/{make_node_key(party.strip())}"
            for party in filters.party_votes
        ]
        votes_of = "SELECT unnest(%(vote_parties)s::text[]) AS party_id"
        parties = "e.from_id = ANY(%(vote_parties)s)"
    return _PARTY_VOTES.replace("{parties}", parties).replace(
        "FROM votes_of", f"FROM ({votes_of}) votes_of"
    )


def get_decisions(
    store: GraphStore,
    filters: DecisionFilters | None = None,
    *,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """A page of decisions, newest first, with the seat tally per row, and the facets.

    The tally and the kind are stored on the decision, so a list page costs no
    traversal; filtering by party reads the VOTED edges of that party.

    ``facets`` counts the decisions under the filters: ``kind`` without the kind filter
    (and per kind how many carried and how many did not), ``passed`` without the outcome
    filter, ``days`` (per date, how many and how many passed) and ``years`` (per year, how
    many, carried, not) under all of them. There is one decision per Besluit, so the
    filtered ones are read once, three fields each, and every count is made from that.
    ``party_votes`` (with ``filters.party_votes``) reads the votes of factions on the
    decisions under all filters (``_PARTY_VOTES``).
    """
    filters = filters or DecisionFilters()
    bind: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "chambers": [CHAMBER_TK, CHAMBER_EK],
    }
    kind = _kind_filter(filters, bind)
    passed = _passed_filter(filters, bind)
    coalition = _coalition_filter(filters, bind)
    statement = f"""
    {_matching(filters, bind)}
    SELECT json_build_object(
        'total', (SELECT count(*)::int FROM matching),
        'items', (
            SELECT coalesce(json_agg({_ITEM} ORDER BY page.n), '[]'::json)
            FROM (
                SELECT r.id, row_number() OVER (ORDER BY {_ORDER}) AS n
                FROM matching r
                ORDER BY {_ORDER}
                LIMIT %(limit)s OFFSET %(offset)s
            ) page
            JOIN decisions d ON d.id = page.id
            LEFT JOIN lg_decision_coalition c ON c.id = d.id
        ),
        'facets', json_build_object(
            'kind', {_kind_facet(passed + coalition)},
            'passed', {_facet("r.passed", "filtered", kind + coalition)},
            'days', (
                SELECT coalesce(json_agg(
                    json_build_object('date', date, 'count', count, 'passed', passed)
                    ORDER BY date ASC NULLS FIRST
                ), '[]'::json)
                FROM (
                    SELECT r.date, count(*)::int AS count,
                           (count(*) FILTER (WHERE r.passed IS TRUE))::int AS passed
                    FROM matching r
                    GROUP BY r.date
                ) day
            ),
            'years', (
                SELECT coalesce(json_agg(
                    json_build_object(
                        'year', year, 'count', count, 'passed', passed,
                        'rejected', rejected
                    )
                    ORDER BY year ASC NULLS FIRST
                ), '[]'::json)
                FROM (
                    SELECT left(r.date, 4) AS year, {_OUTCOMES}
                    FROM matching r
                    GROUP BY 1
                ) year
            ),
            'party_votes', '[]'::json,
            'coalition', {_coalition_facet(kind + passed)}
        )
    )
    """
    rows = list(store.query(statement, bind))
    page: dict[str, Any] = (
        rows[0] if rows else {"total": 0, "items": [], "facets": dict(EMPTY_FACETS)}
    )
    _add_dictums(store, page["items"])
    if filters.party_votes:
        _add_party_votes(store, filters, page)
    return page


# The dictum of the motion of each case: of its oldest paper, as ``get_decision_document``
# picks the paper of a decision, read from ``lg_document_light`` (without the text).
_DICTUMS = f"""
SELECT DISTINCT ON (e.to_id) e.to_id AS case_id, l.props -> 'dictum' AS dictum
FROM {COLLECTION_EDGES} e
JOIN {COLLECTION_DOCUMENTS} doc ON doc.id = e.from_id
JOIN lg_document_light l ON l.id = e.from_id
WHERE e.to_id = ANY(%(case_ids)s::text[]) AND e.relation = %(part_of)s
  AND e.from_collection = '{COLLECTION_DOCUMENTS}'
ORDER BY e.to_id NULLS LAST, doc.date ASC NULLS FIRST, doc.key ASC
"""


def motion_dictums(store: GraphStore, decisions: list[dict[str, Any]]) -> list[Any]:
    """Per decision of *decisions* (``{primary_case_kind, primary_case_id}``) the dictum of
    the motion it decided on (``core/motion_dictum.py``): None for a decision on anything
    else, or on a motion without text."""
    cases = [
        f"{COLLECTION_CASES}/{make_node_key(str(d['primary_case_id']))}"
        if d.get("primary_case_kind") == "Motie" and d.get("primary_case_id")
        else None
        for d in decisions
    ]
    wanted = sorted({c for c in cases if c})
    found: dict[str, Any] = {}
    if wanted:
        found = {
            row["case_id"]: row["dictum"]
            for row in store.query(
                _DICTUMS, {"case_ids": wanted, "part_of": RELATION_PART_OF}
            )
        }
    return [found.get(case) if case else None for case in cases]


def _add_dictums(store: GraphStore, items: list[dict[str, Any]]) -> None:
    """``dictum`` on each row of a page of decisions, in place of ``primary_case_id``."""
    for item, dictum in zip(items, motion_dictums(store, items), strict=True):
        item.pop("primary_case_id", None)
        item["dictum"] = dictum


def _matching(filters: DecisionFilters, bind: dict[str, Any]) -> str:
    """SQL: ``WITH`` the decisions under every filter but kind and outcome (``filtered``:
    id, key, kind, passed, date) and under all of them (``matching``)."""
    common = _common_filters(filters, bind)
    rest = (
        _kind_filter(filters, bind)
        + _passed_filter(filters, bind)
        + _coalition_filter(filters, bind)
    )
    return f"""WITH filtered AS MATERIALIZED (
        SELECT d.id, d.key, lg_str(d.props -> 'kind') AS kind, d.passed, d.date,
               c.pattern AS coalition_pattern, c.carried AS coalition_carried,
               c.decisive AS coalition_decisive
        FROM decisions d
        LEFT JOIN lg_decision_coalition c ON c.id = d.id {_where(common)}
    ),
    matching AS MATERIALIZED (
        SELECT * FROM filtered r {_where(rest)}
    )"""


# The seconds a request waits for ``party_votes`` (every vote of a faction on 69,000
# decisions without a filter): past them the page comes without it, ``partial``, and it is
# counted on for a later request (``party_votes``).
PARTY_VOTES_BUDGET = 3.0


def _add_party_votes(
    store: GraphStore, filters: DecisionFilters, page: dict[str, Any]
) -> None:
    """``facets.party_votes`` of *page*, or ``partial`` when they take longer than
    ``PARTY_VOTES_BUDGET``."""
    left = read_time_left()
    token = set_read_deadline(
        PARTY_VOTES_BUDGET if left is None else min(PARTY_VOTES_BUDGET, left)
    )
    try:
        page["facets"]["party_votes"] = party_votes(store, filters)
    except RequestCancelled:
        raise
    except ReadTimedOut:
        page["partial"] = True
    finally:
        reset_read_deadline(token)


# How long ``party_votes`` under a filter are kept (seconds), whatever the data does: every
# faction on every decision reads every VOTED edge (minutes on the full graph), every write
# of a run of the pipelines changes the version of the edges, and a vote hardly moves
# the counts. Computed on demand only, never in the warm-up.
PARTY_VOTES_MAX_AGE = 3600.0


def party_votes(store: GraphStore, filters: DecisionFilters) -> list[dict[str, Any]]:
    """``_PARTY_VOTES`` under *filters*, kept ``PARTY_VOTES_MAX_AGE`` (``lasting``): one
    computation per filter at a time, in the background, the same for every visitor."""
    return lasting(
        store,
        ("decisions party votes", filters),
        lambda: _read_party_votes(store, filters),
        PARTY_VOTES_MAX_AGE,
    )


def _read_party_votes(
    store: GraphStore, filters: DecisionFilters
) -> list[dict[str, Any]]:
    bind: dict[str, Any] = {}
    statement = (
        f"{_matching(filters, bind)}\nSELECT {_party_votes(filters, bind)} AS votes"
    )
    rows = list(store.query(statement, bind))
    return list(rows[0]) if rows else []


def get_decision_detail(store: GraphStore, key: str) -> dict[str, Any] | None:
    """One decision with every vote cast on it.

    Each vote is a VOTED edge — from a member on a roll-call, from a faction
    otherwise — so the voter's node carries the name to show. The most seats first, then
    by the voter's name and key.
    """
    rows = store.query(
        """
        SELECT d.id, d.key, d.type, d.labels, d.props, (
            SELECT coalesce(json_agg(
                json_build_object(
                    'voter_id', v.id,
                    'voter_key', v.key,
                    'name', CASE
                        WHEN coalesce(json_typeof(v.props -> 'abbreviation'), 'null')
                             <> 'null'
                        THEN v.props -> 'abbreviation' ELSE v.props -> 'name' END,
                    'choice', e.doc -> 'meta' -> 'choice',
                    'seats', e.doc -> 'meta' -> 'seats'
                )
                ORDER BY lg_num(e.doc -> 'meta' -> 'seats') DESC NULLS LAST,
                         v.name ASC NULLS FIRST, v.key ASC
            ), '[]'::json)
            FROM edges e
            JOIN LATERAL (
                SELECT id, key, props, name FROM members WHERE id = e.from_id
                UNION ALL
                SELECT id, key, props, name FROM factions WHERE id = e.from_id
            ) v ON true
            WHERE e.to_id = d.id AND e.relation = %(voted)s
        ) AS votes,
        (
            SELECT json_build_object(
                'cabinet', c.cabinet,
                'coalition_for', c.coalition_for,
                'coalition_against', c.coalition_against,
                'opposition_for', c.opposition_for,
                'opposition_against', c.opposition_against,
                'pattern', c.pattern,
                'carried', c.carried,
                'decisive', c.decisive
            )
            FROM lg_decision_coalition c WHERE c.id = d.id
        ) AS coalition
        FROM decisions d
        WHERE d.key = %(key)s
        """,
        {"key": key, "voted": RELATION_VOTED},
    )
    row = next(rows, None)
    if row is None:
        return None
    # MERGE(decision, {votes}): the keys of the document in byte order, then ``votes``.
    doc = node_doc(row)
    return {
        "_id": doc["_id"],
        "_key": doc["_key"],
        "labels": doc["labels"],
        "props": doc["props"],
        "type": doc["type"],
        "votes": row["votes"],
        "coalition": row["coalition"],
    }


def get_decision_document(
    store: GraphStore, decision: dict[str, Any]
) -> dict[str, Any] | None:
    """The document (motion, amendment, bill) the decision was about.

    A decision is ABOUT a case; a document is PART_OF that case. The case the
    decision singled out — ``primary_case_id`` — is tried before the others
    on the same agenda item, and the first document found wins.
    """
    props = decision.get("props") or {}
    primary = props.get("primary_case_id")
    candidates = [primary] if primary else []
    candidates += [c for c in props.get("case_ids") or [] if c != primary]
    if not candidates:
        return None

    # The candidates in their order; within a case the oldest document, as
    # ``_documents_by_case`` picks it (the key settles a tie).
    rows = store.query(
        f"""
        SELECT d.id, d.key, d.type, d.labels, d.props
        FROM edges e
        JOIN documents d ON d.id = e.from_id
        WHERE e.to_id = ANY(%(case_ids)s) AND e.relation = %(part_of)s
          AND e.from_collection = '{COLLECTION_DOCUMENTS}'
        ORDER BY array_position(%(case_ids)s::text[], e.to_id),
                 d.date ASC NULLS FIRST, d.key ASC
        LIMIT 1
        """,
        {
            "case_ids": [
                f"{COLLECTION_CASES}/{make_node_key(str(c))}" for c in candidates
            ],
            "part_of": RELATION_PART_OF,
        },
    )
    row = next(rows, None)
    return node_doc(row) if row else None


def get_document_decisions(store: GraphStore, document_id: str) -> list[dict[str, Any]]:
    """The decisions taken on a document (the votes on a motion, an amendment, a bill),
    oldest first, each with its votes as ``get_decision_detail`` gives them.

    The reverse of ``get_decision_document``: a decision is ABOUT the cases of an agenda
    item and names one of them (``primary_case_id``); the document it was taken on is the
    oldest document PART_OF that case (the key settles a tie). So a paper of a bill that is
    not the bill itself carries none of the votes on the bill. A decision whose named case
    has no document takes the first document of its other cases, as
    ``get_decision_document`` finds it: such a decision is asked that.
    """
    # the decisions about a case of which this document is the oldest
    rows = list(
        store.query(
            f"""
            WITH own AS (
                SELECT d.id, d.date, d.key
                FROM {COLLECTION_DOCUMENTS} d
                WHERE d.id = %(id)s
            ),
            own_cases AS (
                SELECT p.to_id AS id
                FROM edges p
                CROSS JOIN own
                WHERE p.from_id = own.id AND p.relation = %(part_of)s
                  AND p.to_collection = '{COLLECTION_CASES}'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM edges o
                      JOIN {COLLECTION_DOCUMENTS} od ON od.id = o.from_id
                      WHERE o.to_id = p.to_id AND o.relation = %(part_of)s
                        AND od.id <> own.id
                        AND (
                            (od.date IS NULL AND own.date IS NOT NULL)
                            OR od.date < own.date
                            OR (od.date IS NOT DISTINCT FROM own.date
                                AND od.key < own.key)
                        )
                  )
            )
            SELECT dec.key, any_value(dec.props) AS props,
                   array_agg(a.to_id ORDER BY a.to_id) AS cases
            FROM own_cases
            JOIN edges a ON a.to_id = own_cases.id AND a.relation = %(about)s
            JOIN decisions dec ON dec.id = a.from_id
            GROUP BY dec.id, dec.key, dec.date
            ORDER BY dec.date ASC NULLS FIRST, dec.key ASC
            """,
            {"id": document_id, "part_of": RELATION_PART_OF, "about": RELATION_ABOUT},
        )
    )
    named = {
        row["key"]: f"{COLLECTION_CASES}/{make_node_key(str(primary))}"
        for row in rows
        if (primary := (row["props"] or {}).get("primary_case_id"))
    }
    # the named cases that have a document: a decision naming one of them was taken on
    # that document, here when it is one of this document's cases
    with_document = set(
        store.query(
            f"""
            SELECT DISTINCT e.to_id
            FROM edges e
            JOIN {COLLECTION_DOCUMENTS} d ON d.id = e.from_id
            WHERE e.to_id = ANY(%(cases)s) AND e.relation = %(part_of)s
            """,
            {"cases": sorted(set(named.values())), "part_of": RELATION_PART_OF},
        )
    )
    keys = [
        row["key"]
        for row in rows
        if (
            named.get(row["key"]) in row["cases"]
            if named.get(row["key"]) in with_document
            else (get_decision_document(store, {"props": row["props"]}) or {}).get(
                "_id"
            )
            == document_id
        )
    ]
    return [d for key in keys if (d := get_decision_detail(store, key)) is not None]
