"""Queries behind the committee, member and faction endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_CASES,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_MEMBERS,
    RELATION_ABOUT,
    RELATION_AMENDS,
    RELATION_AUTHORED,
    RELATION_INTRODUCES,
    RELATION_LED_BY,
    RELATION_MEMBER_OF,
    RELATION_PART_OF,
    RELATION_REPEALS,
    RELATION_VOTED,
)
from lawgraph.core.tk_records import VOTE_KIND_MEMBER
from lawgraph.db import GraphStore
from lawgraph.db._rows import node_doc

# A committee whose name is just a GUID carries no usable identity.
_GUID_NAME = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

# The chamber a faction, committee or member list is of: the Eerste Kamer's carry
# ``chamber`` ``EK`` (``normalize eerstekamer-composition``), the Tweede Kamer's none.
CHAMBER_EK = "EK"

# The columns of a node row (``node_doc``) of the table named ``{t}``.
_NODE = "{t}.id, {t}.key, {t}.type, {t}.labels, {t}.props"


def _is_null(value: str) -> str:
    """SQL: the JSON *value* is null or missing (AQL ``== null``)."""
    return f"coalesce(json_typeof({value}), 'null') = 'null'"


def _or_empty(value: str) -> str:
    """SQL: AQL ``value OR []``."""
    return f"CASE WHEN lg_truthy({value}) THEN {value} ELSE '[]'::json END"


def _array(value: str) -> str:
    """SQL: the JSON *value* when it is an array, else ``[]``: what a FOR walks."""
    return f"CASE WHEN json_typeof({value}) = 'array' THEN {value} ELSE '[]'::json END"


def _nonempty(value: str) -> str:
    """SQL: AQL ``LENGTH(value) > 0`` of a list."""
    return (
        f"(CASE WHEN json_typeof({value}) = 'array'"
        f" THEN json_array_length({value}) > 0 ELSE false END)"
    )


def _contains(text: str) -> str:
    """SQL: *text* holds ``%(q)s``, both folded as the search folds them (``lg_fold``: lower
    case, no accents: ``yesilgoz`` finds Yeşilgöz); null holds nothing, and nothing holds
    ``""``."""
    return (
        f"(%(q)s <> '' AND strpos(lg_fold(coalesce({text}, '')), lg_fold(%(q)s)) > 0)"
    )


def _chamber(table: str, chamber: str) -> str:
    """SQL: *table* (a faction or committee) is of *chamber* (``TK`` or ``EK``)."""
    test = "=" if chamber == CHAMBER_EK else "IS DISTINCT FROM"
    return f"lg_str({table}.props -> 'chamber') {test} '{CHAMBER_EK}'"


def _page(source: str, *order: str) -> str:
    """SQL: how many rows *source* has (``total``) beside a page of them (``page.*``) in
    *order*; one row with ``total`` alone when the page is empty."""
    return f"""
    SELECT counted.total, page.*
    FROM (SELECT count(*)::int AS total FROM {source}) counted
    LEFT JOIN LATERAL (
        SELECT * FROM {source} ORDER BY {", ".join(order)}
        LIMIT %(limit)s OFFSET %(offset)s
    ) page ON true
    ORDER BY {", ".join(f"page.{term}" for term in order)}
    """


def get_committees(store: GraphStore, *, chamber: str = "TK") -> list[dict[str, Any]]:
    """Every committee of *chamber* with a name, by name; of the Eerste Kamer only those
    the last snapshot shows. ``props.active_dossier_count`` is what ``semantic
    graph-list-stats`` counted."""
    rows = store.query(
        f"""
        SELECT {_NODE.format(t="c")}
        FROM {COLLECTION_COMMITTEES} c
        WHERE {_chamber("c", chamber)}
          AND {_is_null("c.props -> 'observed_until'")}
          AND c.props ->> 'name' <> ''
          AND c.props ->> 'name' !~* %(guid)s
        ORDER BY c.props ->> 'name' ASC NULLS FIRST, c.key ASC
        """,
        {"guid": _GUID_NAME},
    )
    return [node_doc(row) for row in rows]


def _committee(store: GraphStore, slug: str) -> dict[str, Any] | None:
    """The committee of the slug or the key *slug*. A slug that is also another
    committee's key: the key picks one every time."""
    rows = store.query(
        f"""
        SELECT {_NODE.format(t="c")}
        FROM {COLLECTION_COMMITTEES} c
        WHERE lg_str(c.props -> 'slug') = %(slug)s OR lower(c.key) = %(slug)s
        ORDER BY c.key ASC
        LIMIT 1
        """,
        {"slug": slug.lower()},
    )
    row = next(rows, None)
    return node_doc(row) if row else None


# A seat with no end date or one still ahead; a seat of the Eerste Kamer ends where a
# snapshot no longer shows it.
_CURRENT_MEMBERSHIP = f"""
    AND ({_is_null("e.doc -> 'meta' -> 'to_date'")}
         OR lg_str(e.doc -> 'meta' -> 'to_date') >= %(today)s)
    AND {_is_null("e.doc -> 'meta' -> 'observed_until'")}
"""


def get_member_committees(store: GraphStore, member_id: str) -> list[dict[str, Any]]:
    """The committees a member sat on, of either chamber, each with its seat (the edge's
    ``meta``): those they sit on now first, then by name and key."""
    rows = store.query(
        f"""
        SELECT c.key, c.props -> 'slug' AS slug, c.props -> 'name' AS name,
               c.props -> 'abbreviation' AS abbreviation,
               coalesce(lg_str(c.props -> 'chamber'), 'TK') AS chamber,
               e.doc -> 'meta' AS meta
        FROM {COLLECTION_EDGES} e
        JOIN {COLLECTION_COMMITTEES} c ON c.id = e.to_id
        WHERE e.from_id = %(member_id)s AND e.relation = %(member_of)s
          AND e.to_collection = '{COLLECTION_COMMITTEES}'
        ORDER BY ({_is_null("e.doc -> 'meta' -> 'to_date'")}
                  AND {_is_null("e.doc -> 'meta' -> 'observed_until'")}) DESC,
                 c.props ->> 'name' ASC NULLS FIRST, c.key ASC
        """,
        {"member_id": member_id, "member_of": RELATION_MEMBER_OF},
    )
    return list(rows)


# What a seat on a committee adds to its member.
_SEAT_FIELDS = ("from_date", "to_date", "role", "observed_from", "observed_until")


def _committee_members(
    store: GraphStore, committee_id: str, *, current_only: bool
) -> list[dict[str, Any]]:
    """The members of a committee by name, each with its seat (``_SEAT_FIELDS``)."""
    bind: dict[str, Any] = {
        "committee_id": committee_id,
        "member_of": RELATION_MEMBER_OF,
    }
    if current_only:
        bind["today"] = dt.date.today().isoformat()
    rows = store.query(
        f"""
        SELECT {_NODE.format(t="m")}, e.doc -> 'meta' AS meta
        FROM {COLLECTION_EDGES} e
        JOIN {COLLECTION_MEMBERS} m ON m.id = e.from_id
        WHERE e.to_id = %(committee_id)s AND e.relation = %(member_of)s
          AND e.from_collection = '{COLLECTION_MEMBERS}'
          {_CURRENT_MEMBERSHIP if current_only else ""}
        ORDER BY m.name ASC NULLS FIRST, m.key ASC, e.key ASC
        """,
        bind,
    )
    members = []
    for row in rows:
        meta = row["meta"] if isinstance(row["meta"], dict) else {}
        members.append(
            {**node_doc(row), **{field: meta.get(field) for field in _SEAT_FIELDS}}
        )
    return members


def get_committee_detail(
    store: GraphStore,
    slug: str,
    *,
    current_only: bool = True,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any] | None:
    """One committee with its members and a page of the dossiers it leads.

    Accepts the committee's ``slug`` or its ``_key``. With *current_only* the
    members are those whose seat has no end date, or an end date still ahead.
    *status* (``open`` or ``closed``) keeps the dossiers of that state, newest
    first; ``dossier_total`` counts them all.
    """
    committee = _committee(store, slug)
    if committee is None:
        return None
    # A dossier is open until ``semantic tk-dossier-outcomes`` closed it (as
    # ``/dossiers?status=open``).
    by_status = {
        None: "",
        "closed": "AND d.closed IS TRUE",
    }.get(status, "AND d.closed IS NOT TRUE")
    rows = store.query(
        f"""
        WITH matching AS (
            SELECT {_NODE.format(t="d")}, d.opened_on
            FROM {COLLECTION_DOSSIERS} d
            WHERE d.id IN (
                SELECT subject.to_id
                FROM {COLLECTION_EDGES} led
                JOIN {COLLECTION_EDGES} subject ON subject.from_id = led.from_id
                WHERE led.to_id = %(committee_id)s AND led.relation = %(led_by)s
                  AND subject.relation = %(about)s
                  AND subject.to_collection = '{COLLECTION_DOSSIERS}'
            ) {by_status}
        )
        {_page("matching", "opened_on DESC NULLS LAST", "key ASC")}
        """,
        {
            "committee_id": committee["_id"],
            "led_by": RELATION_LED_BY,
            "about": RELATION_ABOUT,
            "limit": limit,
            "offset": offset,
        },
    )
    total, dossiers = 0, []
    for row in rows:
        total = row["total"]
        if row["id"] is not None:
            dossiers.append(node_doc(row))
    return {
        **committee,
        "members": _committee_members(
            store, committee["_id"], current_only=current_only
        ),
        "dossiers": dossiers,
        "dossier_total": total,
    }


def get_committee_activities(
    store: GraphStore, slug: str, *, limit: int = 100, offset: int = 0
) -> dict[str, Any] | None:
    """A page of the activities a committee leads, newest first; None when unknown.

    Accepts the committee's ``slug`` or its ``_key``. Returns ``{total, items}``.
    """
    committee = _committee(store, slug)
    if committee is None:
        return None
    rows = store.query(
        f"""
        WITH led AS (
            SELECT a.id, a.key, a.date
            FROM {COLLECTION_EDGES} e
            JOIN {COLLECTION_ACTIVITIES} a ON a.id = e.from_id
            WHERE e.to_id = %(committee_id)s AND e.relation = %(led_by)s
              AND e.from_collection = '{COLLECTION_ACTIVITIES}'
        ),
        listed AS ({_page("led", "date DESC NULLS LAST", "key ASC")})
        SELECT listed.total, a.id, json_build_object(
            'id', a.id,
            'key', a.key,
            'date', a.props -> 'date',
            'kind', a.props -> 'kind',
            'agenda_title', a.props -> 'agenda_title',
            'status', a.props -> 'status',
            'dossier_numbers', {_or_empty("a.props -> 'dossier_numbers'")}
        ) AS item
        FROM listed
        LEFT JOIN {COLLECTION_ACTIVITIES} a ON a.id = listed.id
        ORDER BY listed.date DESC NULLS LAST, listed.key ASC
        """,
        {
            "committee_id": committee["_id"],
            "led_by": RELATION_LED_BY,
            "limit": limit,
            "offset": offset,
        },
    )
    total, items = 0, []
    for row in rows:
        total = row["total"]
        if row["id"] is not None:
            items.append(row["item"])
    return {"total": total, "items": items}


def _member_name(table: str) -> str:
    """SQL: the name a member goes by (AQL ``name OR known_as OR government_name``); a TK
    person without one: the name Rijksoverheid gives."""
    name, known_as = (f"{table}.props -> '{f}'" for f in ("name", "known_as"))
    return (
        f"CASE WHEN lg_truthy({name}) THEN {table}.props ->> 'name'"
        f" WHEN lg_truthy({known_as}) THEN {table}.props ->> 'known_as'"
        f" ELSE {table}.props ->> 'government_name' END"
    )


# A member who is seated: one of their faction memberships has no end date.
_SEATED = f"""EXISTS (
    SELECT 1 FROM json_array_elements({_array("m.props -> 'faction_memberships'")}) AS f(period)
    WHERE {_is_null("f.period -> 'to_date'")}
)"""

# The member's party, or an abbreviation, name or alias in their faction timeline (AQL
# ``LOWER(null)`` is ``""``).
# A faction period of the member's timeline names the party: its abbreviation, name or an
# alias.
_PERIOD_OF_PARTY = f"""(
            lower(coalesce(f.period ->> 'abbreviation', '')) = %(party)s
            OR lower(coalesce(f.period ->> 'name', '')) = %(party)s
            OR EXISTS (
                SELECT 1 FROM json_array_elements({_array("f.period -> 'aliases'")}) AS a(alias)
                WHERE lower(coalesce(a.alias #>> '{{}}', '')) = %(party)s
            )
        )"""
_TIMELINE = _array("m.props -> 'faction_memberships'")
_PERIODS = f"json_array_elements({_TIMELINE}) AS f(period)"

# The member is or was of the party: its current party, or any period of its timeline.
_PARTY = f"""
    lower(coalesce(m.props ->> 'party', '')) = %(party)s
    OR EXISTS (SELECT 1 FROM {_PERIODS} WHERE {_PERIOD_OF_PARTY})
"""

# The member sits for the party now: a period of it without an end (what ``seated`` reads).
# A member who left the party for another is seated, but not for it.
_SEATED_FOR_PARTY = f"""
    EXISTS (
        SELECT 1 FROM {_PERIODS}
        WHERE coalesce(json_typeof(f.period -> 'to_date'), 'null') = 'null'
          AND {_PERIOD_OF_PARTY}
    )
"""


# The orders of a list of members: by the name they go by, or by surname as the Kamer lists
# its members (Steur, van der), those without one last.
MEMBER_ORDERS = {
    "name": "n.name ASC NULLS FIRST, m.key ASC",
    "family_name": "lg_str(m.props -> 'family_name') ASC NULLS LAST,"
    " lg_str(m.props -> 'name_prefix') ASC NULLS FIRST,"
    " n.name ASC NULLS FIRST, m.key ASC",
}


def _members_page(
    store: GraphStore,
    filters: list[str],
    bind: dict[str, Any],
    seated: str,
    sort: str,
) -> list[dict[str, Any]]:
    """A page of the members *filters* keep (on ``m`` and its name ``n.name``), with
    ``%(active)s`` only those *seated* (or not), in the order *sort* (``MEMBER_ORDERS``)."""
    rows = store.query(
        f"""
        SELECT {_NODE.format(t="m")}
        FROM {COLLECTION_MEMBERS} m
        CROSS JOIN LATERAL (SELECT m.list_name AS name) n
        WHERE {" AND ".join(f"({f})" for f in filters)}
          AND (%(active)s::boolean IS NULL OR ({seated}) = %(active)s::boolean)
        ORDER BY {MEMBER_ORDERS[sort]}
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        bind,
    )
    return [node_doc(row) for row in rows]


def get_members(
    store: GraphStore,
    *,
    party: str | None = None,
    active: bool | None = None,
    q: str | None = None,
    include_all: bool = False,
    government: bool = False,
    cabinet: str | None = None,
    slug: str | None = None,
    sort: str = "name",
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Members of parliament, in name order (or *sort*); never a record without a name.
    *slug* keeps the one member of that slug, whoever they are.

    Restricted to people who ever held a seat; *include_all* also returns the
    ministers and other people the TK Persoon endpoint exposes. *government* keeps
    those who held a post in a cabinet, *cabinet* those who held one in that cabinet
    (both whether they sat in parliament or not). *party* matches the current party or
    any abbreviation, name or alias in the member's faction timeline; with *active* only a
    period without an end, so a member who left the party for another is not counted.
    """
    # ``list_name``, ``in_parliament`` and ``seated`` are columns of the members table:
    # with them a page of the list is read from an index in name order
    filters: list[str] = ["m.list_name <> ''"]
    bind: dict[str, Any] = {"limit": limit, "offset": offset, "active": active}

    if government:
        filters.append(_nonempty("m.props -> 'government_functions'"))
    if cabinet:
        filters.append("m.cabinet_keys @> ARRAY[%(cabinet)s]::text[]")
        bind["cabinet"] = cabinet
    if slug:
        filters.append("lg_str(m.props -> 'slug') = %(slug)s")
        bind["slug"] = slug.strip().lower()
    elif not (include_all or government or cabinet):
        filters.append("m.in_parliament")
    if party:
        # seated (*active*) and of a party: seated for it, not for another one since
        filters.append(_SEATED_FOR_PARTY if active else _PARTY)
        bind["party"] = party.strip().lower()
    if q:
        filters.append(_contains("n.name"))
        bind["q"] = q.strip().lower()
    return _members_page(store, filters, bind, "m.seated", sort)


# The name a member has in the Eerste Kamer.
_EK_NAME = "m.props -> 'ek' ->> 'name'"


def get_ek_members(
    store: GraphStore,
    *,
    party: str | None = None,
    active: bool | None = None,
    q: str | None = None,
    sort: str = "name",
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """The members of the Eerste Kamer (``props.ek``), in name order (or *sort*): those the last
    snapshot shows (*active*), those it no longer does, or both. *party* matches the
    abbreviation of their faction."""
    filters = ["m.in_ek"]
    bind: dict[str, Any] = {"limit": limit, "offset": offset, "active": active}
    if party:
        filters.append(
            "lower(coalesce(m.props -> 'ek' ->> 'abbreviation', '')) = %(party)s"
        )
        bind["party"] = party.strip().lower()
    if q:
        filters.append(f"{_contains('n.name')} OR {_contains(_EK_NAME)}")
        bind["q"] = q.strip().lower()
    seated = _is_null("m.props -> 'ek' -> 'observed_until'")
    return _members_page(store, filters, bind, seated, sort)


# What a faction is searched by.
_FACTION_NAME = "f.props ->> 'name'"
_FACTION_ABBREVIATION = "f.props ->> 'abbreviation'"


def get_factions(
    store: GraphStore,
    *,
    active: bool | None = None,
    q: str | None = None,
    chamber: str = "TK",
) -> list[dict[str, Any]]:
    """Every parliamentary party of *chamber* with its member count (of the Eerste Kamer:
    the members the last snapshot shows), seated ones first."""
    bind: dict[str, Any] = {"member_of": RELATION_MEMBER_OF}
    filters = ["f.props ->> 'name' <> ''", _chamber("f", chamber)]
    if active is not None:
        filters.append("f.active = %(active)s")
        bind["active"] = active
    if q:
        filters.append(
            f"{_contains(_FACTION_NAME)} OR {_contains(_FACTION_ABBREVIATION)}"
        )
        bind["q"] = q.strip().lower()
    rows = store.query(
        f"""
        SELECT {_NODE.format(t="f")}, coalesce(counted.n, 0) AS member_count
        FROM {COLLECTION_FACTIONS} f
        LEFT JOIN (
            -- looked up per faction: its order does not reach the answer
            SELECT e.to_id, count(*)::int AS n
            FROM {COLLECTION_EDGES} e
            WHERE e.relation = %(member_of)s
              AND e.to_collection = '{COLLECTION_FACTIONS}'
              AND {_is_null("e.doc -> 'meta' -> 'observed_until'")}
            GROUP BY e.to_id
        ) counted ON counted.to_id = f.id
        WHERE {" AND ".join(f"({f})" for f in filters)}
        ORDER BY f.active DESC NULLS LAST,
                 lg_str(f.props -> 'abbreviation') ASC NULLS FIRST,
                 f.name ASC NULLS FIRST, f.key ASC
        """,
        bind,
    )
    return [{**node_doc(row), "member_count": row["member_count"]} for row in rows]


def get_seats_on(store: GraphStore, day: str) -> dict[str, int]:
    """Faction key -> the seats its members held on *day* (YYYY-MM-DD), from their
    ``faction_memberships``: a member is one seat of a faction, whatever their role."""
    rows = store.query(
        f"""
        SELECT f.period ->> 'faction_key' AS faction, count(DISTINCT m.key)::int AS seats
        FROM {COLLECTION_MEMBERS} m
        CROSS JOIN LATERAL json_array_elements(
            {_array("m.pj_faction_memberships")}
        ) AS f(period)
        -- only a member with faction memberships has any (``in_parliament``); the list is
        -- a column of its own, read without the rest of the props
        WHERE m.in_parliament
          AND lg_str(f.period -> 'from_date') <= %(day)s
          AND ({_is_null("f.period -> 'to_date'")} OR lg_str(f.period -> 'to_date') >= %(day)s)
        GROUP BY 1
        ORDER BY 1 ASC NULLS FIRST
        """,
        {"day": day},
    )
    return {row["faction"]: row["seats"] for row in rows}


# The membership ``f.period`` held on the day ``d.date``.
_IN_MEMBERSHIP = f"""
    ({_is_null("f.period -> 'from_date'")} OR lg_str(f.period -> 'from_date') <= d.date)
    AND ({_is_null("f.period -> 'to_date'")} OR lg_str(f.period -> 'to_date') >= d.date)
"""


# The faction votes of a period read first, the newest by date, before which of them were
# roll-calls is known (``_member_votes_page``): a multiple of the page, as roll-calls are few.
VOTE_CANDIDATES = 2


def get_member_votes(
    store: GraphStore, member_id: str, *, limit: int = 100
) -> list[dict[str, Any]]:
    """How a member voted, newest first.

    Two kinds of vote reach a member. A roll-call names every member, so the
    VOTED edge starts at the member. Any other vote is cast by the faction,
    and counts for the member only while they belonged to it — which is what
    ``faction_memberships`` dates. ``party`` is the party they sat for at the
    time, so historic votes keep their colour after a switch.

    Whether a vote of the faction was a roll-call is in the props of its decision: of each
    period only the newest ``VOTE_CANDIDATES`` times the page are read for it (a large
    party votes tens of thousands of times), and more when the roll-calls among those
    leave less than a page.
    """
    candidates = max(limit, 1) * VOTE_CANDIDATES
    while True:
        (row,) = store.query(
            _MEMBER_VOTES, _member_votes_params(member_id, limit, candidates)
        )
        if row["complete"]:
            return list(row["votes"])
        candidates *= 4


def _member_votes_params(member_id: str, limit: int, candidates: int) -> dict[str, Any]:
    return {
        "member_id": member_id,
        "limit": limit,
        "candidates": candidates,
        "voted": RELATION_VOTED,
        "roll_call": VOTE_KIND_MEMBER,
    }


_MEMBER_VOTES = f"""
    WITH member AS (
        SELECT props FROM {COLLECTION_MEMBERS} WHERE id = %(member_id)s
    ),
    periods AS (
        SELECT f.period, f.n
        FROM member
        CROSS JOIN LATERAL json_array_elements(
            {_array("member.props -> 'faction_memberships'")}
        ) WITH ORDINALITY AS f(period, n)
    ),
    -- per period the newest votes of the faction: the decisions of the period newest first
    -- (their index of the dates), each with the faction's vote on it; a faction votes on
    -- nearly every decision while it is seated, so few are read past the page (from the
    -- faction's side every vote it ever cast was read, a decision each: 441,000 for one
    -- member of seven periods)
    candidates AS (
        SELECT p.n, p.period, c.edge_key, c.decision_id, c.date, c.key
        FROM periods p
        CROSS JOIN LATERAL (
            SELECT v.key AS edge_key, d.id AS decision_id, d.date, d.key
            FROM {COLLECTION_DECISIONS} d
            CROSS JOIN LATERAL (SELECT p.period) AS f(period)
            -- per decision (never joined whole: that reads every vote of the faction)
            CROSS JOIN LATERAL (
                SELECT v.key FROM {COLLECTION_EDGES} v
                WHERE v.to_id = d.id AND v.relation = %(voted)s
                  AND v.from_collection = '{COLLECTION_FACTIONS}'
                  AND v.from_id = p.period ->> 'faction_id'
                OFFSET 0
            ) v
            WHERE d.date IS NOT NULL
              AND {_IN_MEMBERSHIP}
            -- NULLS FIRST as the index of the dates walked backward gives it (no date is
            -- null here): the walk stops after the candidates instead of a sort of them all
            ORDER BY d.date DESC NULLS FIRST, d.key ASC
            LIMIT %(candidates)s
        ) c
    ),
    -- of those, the votes no roll-call made
    kept AS (
        SELECT c.* FROM candidates c
        JOIN {COLLECTION_DECISIONS} d ON d.id = c.decision_id
        WHERE lg_str(d.props -> 'vote_kind') IS DISTINCT FROM %(roll_call)s
    ),
    voted AS (
        SELECT e.to_id AS decision_id, e.doc -> 'meta' AS meta,
               member.props -> 'party' AS party,
               NULL::json AS faction_key, NULL::text AS faction_order,
               'member'::text AS vote_source
        FROM member
        JOIN {COLLECTION_EDGES} e
          ON e.from_id = %(member_id)s AND e.relation = %(voted)s
        UNION ALL
        SELECT k.decision_id, e.doc -> 'meta',
               CASE WHEN {_is_null("k.period -> 'abbreviation'")}
                    THEN k.period -> 'name' ELSE k.period -> 'abbreviation' END,
               k.period -> 'faction_key', k.period ->> 'faction_key',
               'faction'::text
        FROM kept k JOIN {COLLECTION_EDGES} e ON e.key = k.edge_key
    ),
    page AS (
        SELECT v.*, d.key, d.date
        FROM voted v JOIN {COLLECTION_DECISIONS} d ON d.id = v.decision_id
        ORDER BY d.date DESC NULLS LAST, d.key ASC, v.faction_order ASC NULLS FIRST
        LIMIT %(limit)s
    )
    SELECT
        -- a period cut at its candidates whose roll-calls left less than a page may lack
        -- votes of the page: read again with more
        NOT EXISTS (
            SELECT 1 FROM periods p
            WHERE (SELECT count(*) FROM candidates c WHERE c.n = p.n) = %(candidates)s
              AND (SELECT count(*) FROM kept k WHERE k.n = p.n) < %(limit)s
        ) AS complete,
        coalesce((
            SELECT json_agg(json_build_object(
                'decision_id', d.id,
                'decision_key', d.key,
                'external_id', d.props -> 'decision_id',
                'date', d.props -> 'date',
                'subject', d.props -> 'subject',
                'passed', d.props -> 'passed',
                'choice', page.meta -> 'choice',
                'seats', page.meta -> 'seats',
                'party', page.party,
                'faction_key', page.faction_key,
                'vote_source', page.vote_source
            ) ORDER BY page.date DESC NULLS LAST, page.key ASC,
                       page.faction_order ASC NULLS FIRST)
            FROM page JOIN {COLLECTION_DECISIONS} d ON d.id = page.decision_id
        ), '[]'::json) AS votes
"""


def get_actor_touched_instruments(
    store: GraphStore, actor_id: str, *, limit: int = 10
) -> list[dict[str, Any]]:
    """The laws a member most often proposes changes to.

    Walks member → AUTHORED → document → AMENDS/INTRODUCES/REPEALS → article
    → PART_OF → instrument, and counts the distinct documents per instrument.
    The instrument document is only fetched for the rows that survive the
    limit.
    """
    rows = store.query(
        f"""
        SELECT json_build_object(
            'id', top.instrument_id,
            'key', i.key,
            'display_name', i.props -> 'display_name',
            'title', i.props -> 'title',
            'short_title', i.props -> 'short_title',
            'citation_title', i.props -> 'citation_title',
            'bwb_id', i.props -> 'bwb_id',
            'celex', i.props -> 'celex',
            'count', top.document_count
        )
        FROM (
            SELECT part.to_id AS instrument_id,
                   count(DISTINCT authored.to_id)::int AS document_count
            FROM {COLLECTION_EDGES} authored
            JOIN {COLLECTION_EDGES} change
              ON change.from_id = authored.to_id AND change.relation = ANY(%(changes)s)
            JOIN {COLLECTION_EDGES} part
              ON part.from_id = change.to_id AND part.relation = %(part_of)s
             AND part.to_collection = '{COLLECTION_INSTRUMENTS}'
            WHERE authored.from_id = %(actor_id)s AND authored.relation = %(authored)s
            GROUP BY part.to_id
            ORDER BY document_count DESC NULLS LAST, part.to_id ASC
            LIMIT %(limit)s
        ) top
        JOIN {COLLECTION_INSTRUMENTS} i ON i.id = top.instrument_id
        ORDER BY top.document_count DESC NULLS LAST, top.instrument_id ASC
        """,
        {
            "actor_id": actor_id,
            "limit": limit,
            "authored": RELATION_AUTHORED,
            "part_of": RELATION_PART_OF,
            "changes": [RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS],
        },
    )
    return list(rows)


# The AUTHORED edges of a member: the document (or case) each is of, and its meta.
_MEMBER_AUTHORED = f"""
    SELECT a.to_id AS document_id, a.doc -> 'meta' AS meta
    FROM {COLLECTION_EDGES} a
    WHERE a.from_id = %(actor_id)s AND a.relation = %(authored)s
"""

# The AUTHORED edges of a faction's members, each signed while the member belonged to it
# (``faction_memberships``, as for their votes): on the day of the document (or case).
_FACTION_AUTHORED = f"""
    SELECT a.to_id AS document_id, a.doc -> 'meta' AS meta
    FROM {COLLECTION_EDGES} seat
    JOIN {COLLECTION_MEMBERS} m ON m.id = seat.from_id
    JOIN {COLLECTION_EDGES} a ON a.from_id = m.id AND a.relation = %(authored)s
    CROSS JOIN LATERAL (
        SELECT CASE WHEN a.to_collection = '{COLLECTION_DOCUMENTS}'
            THEN (SELECT x.date FROM {COLLECTION_DOCUMENTS} x WHERE x.id = a.to_id)
            ELSE (SELECT lg_str(x.props -> 'date') FROM nodes x WHERE x.id = a.to_id)
        END AS date
    ) d
    WHERE seat.to_id = %(actor_id)s AND seat.relation = %(member_of)s
      AND d.date IS NOT NULL
      AND EXISTS (
          SELECT 1
          FROM json_array_elements({_array("m.props -> 'faction_memberships'")}) AS f(period)
          WHERE f.period ->> 'faction_id' = %(actor_id)s AND {_IN_MEMBERSHIP}
      )
"""


def _distinct(field: str, condition: str) -> str:
    """SQL: the distinct values of *field* of the meta of the rows ``r`` that meet
    *condition*, in order."""
    value = f"r.meta ->> '{field}'"
    return (
        f"coalesce(array_agg(DISTINCT {value} ORDER BY {value} ASC NULLS FIRST)"
        f" FILTER (WHERE {value} {condition}), '{{}}')"
    )


def get_actor_dossiers(
    store: GraphStore,
    actor_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """A page of the dossiers a member or a faction authored documents in.

    Walks member -> ``AUTHORED`` -> document (or case) -> ``PART_OF`` -> dossier, directly
    or through a case. A faction has no ``AUTHORED`` edges of its own: it counts the
    documents its members signed while they belonged to it (``faction_memberships``, as
    for their votes). Each dossier carries the distinct ``AUTHORED`` roles and the number
    of documents; newest opened first. Returns ``{total, items}``.
    """
    is_faction = actor_id.startswith(f"{COLLECTION_FACTIONS}/")
    rows = store.query(
        f"""
        WITH authored AS ({_FACTION_AUTHORED if is_faction else _MEMBER_AUTHORED}),
        found AS (
            SELECT ids.dossier_id, a.document_id, a.meta
            FROM authored a
            CROSS JOIN LATERAL (
                SELECT p.to_id AS dossier_id
                FROM {COLLECTION_EDGES} p
                WHERE p.from_id = a.document_id AND p.relation = %(part_of)s
                  AND p.to_collection = '{COLLECTION_DOSSIERS}'
                UNION
                SELECT p2.to_id
                FROM {COLLECTION_EDGES} p1
                JOIN {COLLECTION_EDGES} p2
                  ON p2.from_id = p1.to_id AND p2.relation = %(part_of)s
                 AND p2.to_collection = '{COLLECTION_DOSSIERS}'
                WHERE p1.from_id = a.document_id AND p1.relation = %(part_of)s
                  AND p1.to_collection = '{COLLECTION_CASES}'
            ) ids
        ),
        grouped AS (
            SELECT {_NODE.format(t="d")}, d.opened_on,
                   {_distinct("role", "<> ''")} AS roles,
                   {_distinct("function", "<> ''")} AS functions,
                   {_distinct("capacity", "IS NOT NULL")} AS capacities,
                   count(DISTINCT r.document_id)::int AS document_count
            FROM found r JOIN {COLLECTION_DOSSIERS} d ON d.id = r.dossier_id
            GROUP BY d.id
        )
        {_page("grouped", "opened_on DESC NULLS LAST", "key ASC")}
        """,
        {
            "actor_id": actor_id,
            "limit": limit,
            "offset": offset,
            "authored": RELATION_AUTHORED,
            "part_of": RELATION_PART_OF,
            "member_of": RELATION_MEMBER_OF,
        },
    )
    total, items = 0, []
    for row in rows:
        total = row["total"]
        if row["id"] is None:
            continue
        items.append(
            {
                "dossier": node_doc(row),
                "roles": list(row["roles"]),
                "functions": list(row["functions"]),
                "capacities": list(row["capacities"]),
                "document_count": row["document_count"],
            }
        )
    return {"total": total, "items": items}


# The decision names the faction ``%(name)s`` in its list ``{}``.
_NAMES = "lg_text_array(d.props -> '{}') @> ARRAY[%(name)s]::text[]"


def get_ek_faction_votes(
    store: GraphStore,
    abbreviation: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """How a faction of the Eerste Kamer voted, by its name as the list of votes writes it
    (*abbreviation*): ``{total, counts, items}``, newest first. ``counts`` per choice
    (``voor``, ``tegen``, ``aantekening gevraagd``) over every vote that names it."""
    by_date = ""
    if date_from is not None:
        by_date += " AND d.date >= %(from)s"
    if date_to is not None:
        # a decision without a date is before every day, as AQL compares null
        by_date += (
            " AND (d.date <= %(to)s OR coalesce(json_typeof(d.props -> 'date'), 'null')"
            " IN ('null', 'number', 'boolean'))"
        )
    rows = store.query(
        f"""
        WITH named AS (
            SELECT * FROM (
                SELECT d.id, d.key, d.date, CASE
                    WHEN {_NAMES.format("factions_for")} THEN 'voor'
                    WHEN {_NAMES.format("factions_against")} THEN 'tegen'
                    WHEN {_NAMES.format("factions_noted")} THEN 'aantekening gevraagd'
                END AS choice
                FROM {COLLECTION_DECISIONS} d
                WHERE lg_str(d.props -> 'chamber') = %(ek)s {by_date}
            ) voted
            WHERE choice IS NOT NULL
        ),
        page AS (
            SELECT * FROM named
            ORDER BY date DESC NULLS LAST, key ASC
            LIMIT %(limit)s OFFSET %(offset)s
        )
        SELECT json_build_object(
            'total', (SELECT count(*)::int FROM named),
            -- the choices in their order, as AQL's COLLECT gives them (D11)
            'counts', (
                SELECT coalesce(
                    json_object_agg(choice, n ORDER BY choice ASC NULLS FIRST),
                    '{{}}'::json
                )
                FROM (SELECT choice, count(*)::int AS n FROM named GROUP BY choice) c
            ),
            'items', (
                SELECT coalesce(json_agg(json_build_object(
                    'decision_id', d.id,
                    'decision_key', d.key,
                    'date', d.props -> 'date',
                    'subject', d.props -> 'subject',
                    'dossier_numbers', {_or_empty("d.props -> 'dossier_numbers'")},
                    'result', d.props -> 'result',
                    'method', d.props -> 'method',
                    'bill_decision', d.props -> 'bill_decision',
                    'choice', page.choice
                ) ORDER BY page.date DESC NULLS LAST, page.key ASC), '[]'::json)
                FROM page JOIN {COLLECTION_DECISIONS} d ON d.id = page.id
            )
        )
        """,
        {
            "ek": CHAMBER_EK,
            "name": abbreviation,
            "from": date_from,
            "to": date_to,
            "limit": limit,
            "offset": offset,
        },
    )
    row = next(rows, None)
    return row or {"total": 0, "counts": {}, "items": []}
