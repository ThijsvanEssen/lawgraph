"""Queries behind the committee endpoints."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    CHAMBER_TK,
    COLLECTION_ACTIVITIES,
    COLLECTION_COMMITTEES,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_MEMBERS,
    RELATION_MEMBER_OF,
)
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore
from lawgraph.db._rows import node_doc
from lawgraph.db.queries._json_sql import (
    array_or_empty,
    is_absent,
    period_overlaps,
)
from lawgraph.db.queries._lists import page_of, paged
from lawgraph.db.queries._parliament_sql import ASKED, NODE, asked_period, of_chamber
from lawgraph.db.version_cache import cached

# A committee whose name is just a GUID carries no usable identity.
_GUID_NAME = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def get_committees(
    store: GraphStore,
    *,
    chamber: str = CHAMBER_TK,
    active_from: str | None = None,
    active_to: str | None = None,
) -> list[dict[str, Any]]:
    """Every committee of *chamber* with a name, by name; of the Eerste Kamer only those
    the last snapshot shows. ``props.active_dossier_count`` is what ``semantic
    graph-list-stats`` counted. With a period (*active_from*, *active_to*) those that
    existed in it (``started_on`` to ``ended_on``), also the ones that ended since."""
    bind: dict[str, Any] = {"guid": _GUID_NAME}
    existing = (
        period_overlaps("c.props -> 'started_on'", "c.props -> 'ended_on'", *ASKED)
        if asked_period(bind, active_from, active_to)
        else is_absent("c.props -> 'observed_until'")
    )
    rows = store.query(
        f"""
        SELECT {NODE.format(t="c")}
        FROM {COLLECTION_COMMITTEES} c
        WHERE {of_chamber("c", chamber)}
          AND {existing}
          AND c.props ->> 'name' <> ''
          AND c.props ->> 'name' !~* %(guid)s
        ORDER BY c.props ->> 'name' ASC NULLS FIRST, c.key ASC
        """,
        bind,
    )
    return [node_doc(row) for row in rows]


def find_committee(store: GraphStore, slug: str) -> dict[str, Any] | None:
    """The committee of the slug or the key *slug*. A slug that is also another
    committee's key: the key picks one every time."""
    rows = store.query(
        f"""
        SELECT {NODE.format(t="c")}
        FROM {COLLECTION_COMMITTEES} c
        WHERE lg_str(c.props -> 'slug') = %(slug)s OR lower(c.key) = %(slug)s
        ORDER BY c.key ASC
        LIMIT 1
        """,
        {"slug": slug.lower()},
    )
    row = next(rows, None)
    return node_doc(row) if row else None


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
        bind["today"] = dutch_today().isoformat()
    rows = store.query(
        f"""
        SELECT {NODE.format(t="m")}, e.doc -> 'meta' AS meta
        FROM {COLLECTION_EDGES} e
        JOIN {COLLECTION_MEMBERS} m ON m.id = e.from_id
        WHERE e.to_id = %(committee_id)s AND e.relation = %(member_of)s
          AND e.from_collection = '{COLLECTION_MEMBERS}'
          {"AND lg_seated(e.doc -> 'meta', %(today)s)" if current_only else ""}
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

    Accepts the committee's ``slug`` or its ``key``. With *current_only* the
    members are those whose seat has no end date, or an end date still ahead.
    *status* (``open`` or ``closed``) keeps the dossiers of that state, newest
    first; ``dossier_total`` counts them all.
    """
    committee = find_committee(store, slug)
    if committee is None:
        return None
    total, dossiers = cached(
        store,
        ("committee-dossiers", committee["id"], status, limit, offset),
        lambda: _led_dossiers(store, committee["id"], status, limit, offset),
        tables=(COLLECTION_EDGES, COLLECTION_DOSSIERS),
    )
    return {
        **committee,
        "members": _committee_members(
            store, committee["id"], current_only=current_only
        ),
        "dossiers": dossiers,
        "dossier_total": total,
    }


# The dossiers the items a committee leads are about: those kept with its items in
# ``lg_led``, a range of its index.
_LED_DOSSIERS = """
    SELECT x.dossier_id
    FROM lg_led l CROSS JOIN LATERAL unnest(l.dossiers) AS x(dossier_id)
    WHERE l.committee_id = %(committee_id)s
"""


def _led_dossiers(
    store: GraphStore,
    committee_id: str,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[int, list[dict[str, Any]]]:
    """The dossiers the activities and cases of a committee are about: how many, and a
    page of them, newest opened first; kept per data version."""
    # A dossier is open until ``semantic tk-dossier-outcomes`` closed it (as
    # ``/dossiers?status=open``).
    by_status = {
        None: "",
        "closed": "AND d.closed IS TRUE",
    }.get(status, "AND d.closed IS NOT TRUE")
    rows = store.query(
        f"""
        WITH matching AS (
            SELECT {NODE.format(t="d")}, d.opened_on
            FROM {COLLECTION_DOSSIERS} d
            WHERE d.id IN ({_LED_DOSSIERS}) {by_status}
        )
        {paged("matching", page_of("matching", "opened_on DESC NULLS LAST, key ASC"))}
        """,
        {"committee_id": committee_id, "limit": limit, "offset": offset},
    )
    total, dossiers = 0, []
    for row in rows:
        total = row["total"]
        if row["id"] is not None:
            dossiers.append(node_doc(row))
    return total, dossiers


def get_committee_activities(
    store: GraphStore, slug: str, *, limit: int = 100, offset: int = 0
) -> dict[str, Any] | None:
    """A page of the activities a committee leads, newest first; None when unknown.

    Accepts the committee's ``slug`` or its ``key``. Returns ``{total, items}``.
    """
    committee = find_committee(store, slug)
    if committee is None:
        return None
    return cached(
        store,
        ("committee-activities", committee["id"], limit, offset),
        lambda: _led_activities(store, committee["id"], limit, offset),
        tables=(COLLECTION_EDGES, COLLECTION_ACTIVITIES),
    )


# The activities a committee leads with their dates: a range of the index of ``lg_led`` in
# the order of their dates; the page's rows alone are read.
_LED_ACTIVITIES = f"""
    SELECT l.item_id AS id, split_part(l.item_id, '/', 2) AS key, l.date
    FROM lg_led l
    WHERE l.committee_id = %(committee_id)s
      AND l.item_collection = '{COLLECTION_ACTIVITIES}'
"""


def _led_activities(
    store: GraphStore, committee_id: str, limit: int, offset: int
) -> dict[str, Any]:
    """``{total, items}``: a page of the activities a committee leads, newest first; kept
    per data version."""
    rows = store.query(
        f"""
        WITH led AS ({_LED_ACTIVITIES}),
        listed AS ({paged("led", page_of("led", "date DESC NULLS LAST, id ASC"))})
        SELECT listed.total, a.id, json_build_object(
            'id', a.id,
            'key', a.key,
            'date', a.props -> 'date',
            'kind', a.props -> 'kind',
            'agenda_title', a.props -> 'agenda_title',
            'status', a.props -> 'status',
            'dossier_numbers', {array_or_empty("a.props -> 'dossier_numbers'")}
        ) AS item
        FROM listed
        LEFT JOIN {COLLECTION_ACTIVITIES} a ON a.id = listed.id
        ORDER BY listed.date DESC NULLS LAST, listed.key ASC
        """,
        {"committee_id": committee_id, "limit": limit, "offset": offset},
    )
    total, items = 0, []
    for row in rows:
        total = row["total"]
        if row["id"] is not None:
            items.append(row["item"])
    return {"total": total, "items": items}
