"""Queries behind the member endpoints: the lists of members of both Kamers, the
committees of a member and the slugs of the members."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    CHAMBER_TK,
    COLLECTION_COMMITTEES,
    COLLECTION_EDGES,
    COLLECTION_MEMBERS,
    RELATION_MEMBER_OF,
)
from lawgraph.core.models import make_node_key
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore
from lawgraph.db._rows import node_doc
from lawgraph.db.queries._json_sql import array_or_empty, is_absent, period_overlaps
from lawgraph.db.queries._parliament_sql import ASKED, NODE, asked_period, contains
from lawgraph.db.version_cache import cached

# The start and end of a period ``p.v`` of a list, and the posts a member held.
_FROM_DATE = "p.v -> 'from_date'"
_TO_DATE = "p.v -> 'to_date'"
_GOVERNMENT_FUNCTIONS = "m.props -> 'government_functions'"


def _a_period_overlaps(periods: str) -> str:
    """SQL: one of the periods of the JSON list *periods* (``from_date``, ``to_date``)
    overlaps the one asked."""
    return (
        f"EXISTS (SELECT 1 FROM json_array_elements({array_or_empty(periods)}) AS p(v)"
        f" WHERE {period_overlaps(_FROM_DATE, _TO_DATE, *ASKED)})"
    )


def get_member_committees(store: GraphStore, member_id: str) -> list[dict[str, Any]]:
    """The committees a member sat on, of either chamber, each with its seat (the edge's
    ``meta``): those they sit on now first, then by name and key."""
    rows = store.query(
        f"""
        SELECT c.key, c.props -> 'slug' AS slug, c.props -> 'name' AS name,
               c.props -> 'abbreviation' AS abbreviation,
               coalesce(lg_str(c.props -> 'chamber'), '{CHAMBER_TK}') AS chamber,
               e.doc -> 'meta' AS meta
        FROM {COLLECTION_EDGES} e
        JOIN {COLLECTION_COMMITTEES} c ON c.id = e.to_id
        WHERE e.from_id = %(member_id)s AND e.relation = %(member_of)s
          AND e.to_collection = '{COLLECTION_COMMITTEES}'
        ORDER BY lg_seated(e.doc -> 'meta', %(today)s) DESC NULLS LAST,
                 c.props ->> 'name' ASC NULLS FIRST, c.key ASC
        """,
        {
            "member_id": member_id,
            "member_of": RELATION_MEMBER_OF,
            "today": dutch_today().isoformat(),
        },
    )
    return list(rows)


# The member's party, or an abbreviation, name or alias in their faction timeline (a
# missing one is ``""``).
# A faction period of the member's timeline names the party: its abbreviation, name or an
# alias.
_PERIOD_OF_PARTY = f"""(
            lower(coalesce(f.period ->> 'abbreviation', '')) = %(party)s
            OR lower(coalesce(f.period ->> 'name', '')) = %(party)s
            OR EXISTS (
                SELECT 1 FROM json_array_elements({array_or_empty("f.period -> 'aliases'")}) AS a(alias)
                WHERE lower(coalesce(a.alias #>> '{{}}', '')) = %(party)s
            )
        )"""
_TIMELINE = array_or_empty("m.props -> 'faction_memberships'")
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
        WHERE {is_absent("f.period -> 'to_date'")}
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
        SELECT {NODE.format(t="m")}
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
    active_from: str | None = None,
    active_to: str | None = None,
) -> list[dict[str, Any]]:
    """Members of parliament, in name order (or *sort*); never a record without a name.
    *slug* keeps the one member of that slug, whoever they are.

    Restricted to people who ever held a seat; *include_all* also returns the
    ministers and other people the TK Persoon endpoint exposes. *government* keeps
    those who held a post in a cabinet, *cabinet* those who held one in that cabinet
    (both whether they sat in parliament or not). *party* matches the current party or
    any abbreviation, name or alias in the member's faction timeline; with *active* only a
    period without an end, so a member who left the party for another is not counted.
    With a period (*active_from*, *active_to*) those who held a seat or a post in a cabinet
    in it.
    """
    filters, bind = _member_filters(
        party=party,
        active=active,
        q=q,
        include_all=include_all,
        government=government,
        cabinet=cabinet,
        slug=slug,
        active_from=active_from,
        active_to=active_to,
    )
    bind.update(limit=limit, offset=offset)
    return _members_page(store, filters, bind, "m.seated", sort)


def count_members(
    store: GraphStore, *, include_all: bool = False, government: bool = False
) -> int:
    """How many members ``get_members`` lists with these filters, over every page: the
    count of the list (``/api/stats`` ``lists``), by the same conditions."""
    filters, bind = _member_filters(include_all=include_all, government=government)
    rows = store.query(
        f"""
        SELECT count(*)::int
        FROM {COLLECTION_MEMBERS} m
        CROSS JOIN LATERAL (SELECT m.list_name AS name) n
        WHERE {" AND ".join(f"({f})" for f in filters)}
          AND (%(active)s::boolean IS NULL OR (m.seated) = %(active)s::boolean)
        """,
        bind,
    )
    return int(next(iter(rows), 0) or 0)


def _member_filters(
    *,
    party: str | None = None,
    active: bool | None = None,
    q: str | None = None,
    include_all: bool = False,
    government: bool = False,
    cabinet: str | None = None,
    slug: str | None = None,
    active_from: str | None = None,
    active_to: str | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """The conditions on ``m`` (and its name ``n.name``) of a list of members, and their
    parameters (``get_members``)."""
    # ``list_name``, ``in_parliament`` and ``seated`` are columns of the members table:
    # with them a page of the list is read from an index in name order
    filters: list[str] = ["m.list_name <> ''"]
    bind: dict[str, Any] = {"active": active}

    if government:
        filters.append(
            f"json_array_length({array_or_empty(_GOVERNMENT_FUNCTIONS)}) > 0"
        )
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
        filters.append(contains("n.name"))
        bind["q"] = q.strip().lower()
    if asked_period(bind, active_from, active_to):
        filters.append(
            f"{_a_period_overlaps('m.pj_faction_memberships')}"
            f" OR {_a_period_overlaps(_GOVERNMENT_FUNCTIONS)}"
        )
    return filters, bind


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
    active_from: str | None = None,
    active_to: str | None = None,
) -> list[dict[str, Any]]:
    """The members of the Eerste Kamer (``props.ek``), in name order (or *sort*): those the last
    snapshot shows (*active*), those it no longer does, or both. *party* matches the
    abbreviation of their faction. With a period (*active_from*, *active_to*) those the
    snapshots showed in it (``observed_from`` to ``observed_until``)."""
    filters = ["m.in_ek"]
    bind: dict[str, Any] = {"limit": limit, "offset": offset, "active": active}
    if party:
        filters.append(
            "lower(coalesce(m.props -> 'ek' ->> 'abbreviation', '')) = %(party)s"
        )
        bind["party"] = party.strip().lower()
    if q:
        filters.append(f"{contains('n.name')} OR {contains(_EK_NAME)}")
        bind["q"] = q.strip().lower()
    if asked_period(bind, active_from, active_to):
        filters.append(
            period_overlaps(
                "m.props -> 'ek' -> 'observed_from'",
                "m.props -> 'ek' -> 'observed_until'",
                *ASKED,
            )
        )
    seated = is_absent("m.props -> 'ek' -> 'observed_until'")
    return _members_page(store, filters, bind, seated, sort)


def _read_member_slugs(store: GraphStore) -> dict[str, str]:
    return {
        row["key"]: row["slug"]
        for row in store.query(
            f"SELECT key, lg_str(props -> 'slug') AS slug FROM {COLLECTION_MEMBERS}"
            " WHERE lg_str(props -> 'slug') IS NOT NULL"
        )
    }


def get_member_brief(store: GraphStore, key: str) -> dict[str, Any] | None:
    """``{name, slug}`` of the member with *key*; None for none."""
    member = store.get_document(COLLECTION_MEMBERS, key)
    props = (member or {}).get("props") or {}
    return {"name": props.get("name"), "slug": props.get("slug")} if member else None


def load_member_slugs(store: GraphStore) -> dict[str, str]:
    """The slug of every member by its key (the readable address of a member named by
    its key alone, ``/leden/<slug>``), kept while the members stand still: computed on
    first use, and in the warm-up (``api/warm.py``)."""
    return cached(
        store,
        ("member-slugs",),
        lambda: _read_member_slugs(store),
        tables=(COLLECTION_MEMBERS,),
    )


def with_member_slugs(store: GraphStore, doc: dict[str, Any]) -> dict[str, Any]:
    """A document with the slug of each member that signed it (``member_slugs``: key ->
    slug), for their readable addresses."""
    slugs = load_member_slugs(store)
    keys = {
        make_node_key(str(actor["person_id"]))
        for actor in (doc.get("props") or {}).get("actors") or []
        if actor.get("person_id")
    }
    return {**doc, "member_slugs": {k: slugs[k] for k in sorted(keys) if k in slugs}}
