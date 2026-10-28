"""Queries behind the committee endpoints."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    CHAMBER_EK,
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


def _sitting(t: str) -> str:
    """SQL: committee *t* sits on ``%(today)s``: it has not ended and, of the Eerste Kamer,
    its last snapshot shows it; of the Tweede Kamer, a member is seated on it that day. The
    Kamer closes few committees it stopped (``DatumInactief`` is mostly empty): a committee
    whose every seat ended, or that never had one in the source, sits no longer."""
    return f"""(
        NOT coalesce(lg_str({t}.props -> 'ended_on') <= %(today)s, false)
        AND {is_absent(f"{t}.props -> 'observed_until'")}
        AND ({of_chamber(t, CHAMBER_EK)} OR EXISTS (
            SELECT 1 FROM {COLLECTION_EDGES} s
            WHERE s.to_id = {t}.id AND s.relation = %(member_of)s
              AND s.from_collection = '{COLLECTION_MEMBERS}'
              AND lg_seated(s.doc -> 'meta', %(today)s)
        ))
    )"""


def _committee_doc(row: dict[str, Any]) -> dict[str, Any]:
    return {**node_doc(row), "sitting": bool(row["sitting"])}


def get_committees(
    store: GraphStore,
    *,
    chamber: str = CHAMBER_TK,
    include_ended: bool = False,
    active_from: str | None = None,
    active_to: str | None = None,
) -> list[dict[str, Any]]:
    """The committees of *chamber* with a name, by name, each with whether it sits
    (``_sitting``): those sitting, or with *include_ended* every one. With a period
    (*active_from*, *active_to*) those that existed in it (``started_on`` to
    ``ended_on``), also the ones that ended since. ``props.active_dossier_count`` is what
    ``semantic graph-list-stats`` counted."""
    bind: dict[str, Any] = {
        "guid": _GUID_NAME,
        "member_of": RELATION_MEMBER_OF,
        "today": dutch_today().isoformat(),
    }
    if asked_period(bind, active_from, active_to):
        existing = period_overlaps(
            "c.props -> 'started_on'", "c.props -> 'ended_on'", *ASKED
        )
    else:
        existing = "true" if include_ended else _sitting("c")
    rows = store.query(
        f"""
        SELECT {NODE.format(t="c")}, {_sitting("c")} AS sitting
        FROM {COLLECTION_COMMITTEES} c
        WHERE {of_chamber("c", chamber)}
          AND {existing}
          AND c.props ->> 'name' <> ''
          AND c.props ->> 'name' !~* %(guid)s
        ORDER BY c.props ->> 'name' ASC NULLS FIRST, c.key ASC
        """,
        bind,
    )
    return [_committee_doc(row) for row in rows]


def find_committee(store: GraphStore, slug: str) -> dict[str, Any] | None:
    """The committee of the slug or the key *slug*, with whether it sits (``_sitting``). A
    slug that is also another committee's key: the key picks one every time."""
    rows = store.query(
        f"""
        SELECT {NODE.format(t="c")}, {_sitting("c")} AS sitting
        FROM {COLLECTION_COMMITTEES} c
        WHERE lg_str(c.props -> 'slug') = %(slug)s OR lower(c.key) = %(slug)s
        ORDER BY c.key ASC
        LIMIT 1
        """,
        {
            "slug": slug.lower(),
            "member_of": RELATION_MEMBER_OF,
            "today": dutch_today().isoformat(),
        },
    )
    row = next(rows, None)
    return _committee_doc(row) if row else None


# What a seat on a committee adds to its member.
_SEAT_FIELDS = ("from_date", "to_date", "role", "observed_from", "observed_until")


def _committee_members(
    store: GraphStore, committee_id: str, *, current_only: bool
) -> list[dict[str, Any]] | None:
    """The members of a committee by name, each with its seat (``_SEAT_FIELDS``); None
    when the data has no seat on it at all (not known: the source gives none)."""
    bind: dict[str, Any] = {
        "committee_id": committee_id,
        "member_of": RELATION_MEMBER_OF,
    }
    if current_only:
        bind["today"] = dutch_today().isoformat()
    rows = store.query(
        f"""
        SELECT {NODE.format(t="m")}, e.doc -> 'meta' AS meta,
               {"lg_seated(e.doc -> 'meta', %(today)s)" if current_only else "true"}
                   AS seated
        FROM {COLLECTION_EDGES} e
        JOIN {COLLECTION_MEMBERS} m ON m.id = e.from_id
        WHERE e.to_id = %(committee_id)s AND e.relation = %(member_of)s
          AND e.from_collection = '{COLLECTION_MEMBERS}'
        ORDER BY m.name ASC NULLS FIRST, m.key ASC, e.key ASC
        """,
        bind,
    )
    seats = list(rows)
    if not seats:
        return None
    return [
        {**node_doc(row), **{field: _meta(row).get(field) for field in _SEAT_FIELDS}}
        for row in seats
        if row["seated"]
    ]


def _meta(row: dict[str, Any]) -> dict[str, Any]:
    return row["meta"] if isinstance(row["meta"], dict) else {}


def get_committee_detail(
    store: GraphStore,
    slug: str,
    *,
    current_only: bool = True,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    sort: str = "opened",
) -> dict[str, Any] | None:
    """One committee with its members and a page of the dossiers it leads.

    Accepts the committee's ``slug`` or its ``key``. With *current_only* the
    members are those whose seat has no end date, or an end date still ahead; None
    when the data has no seat on it at all.
    *status* (``open`` or ``closed``) keeps the dossiers of that state, newest
    first, or with *sort* ``importance`` the open ones first, then those with the most
    items the committee led (activities and cases), then the newest opened;
    ``dossier_total`` counts them all.
    """
    committee = find_committee(store, slug)
    if committee is None:
        return None
    total, dossiers = cached(
        store,
        ("committee-dossiers", committee["id"], status, limit, offset, sort),
        lambda: _led_dossiers(store, committee["id"], status, limit, offset, sort),
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


# The orders of the dossiers of a committee: newest opened, or the open ones first, with the
# most items led, then newest opened.
_DOSSIER_ORDER = {
    "opened": "opened_on DESC NULLS LAST, key ASC",
    "importance": "is_closed ASC NULLS LAST, led DESC NULLS LAST, opened_on DESC NULLS LAST, key ASC",
}


def _led_dossiers(
    store: GraphStore,
    committee_id: str,
    status: str | None,
    limit: int,
    offset: int,
    sort: str,
) -> tuple[int, list[dict[str, Any]]]:
    """The dossiers the activities and cases of a committee are about: how many, and a
    page of them in the order of *sort*; kept per data version."""
    # A dossier is open until ``semantic tk-dossier-outcomes`` closed it (as
    # ``/dossiers?status=open``).
    by_status = {
        None: "",
        "closed": "AND d.closed IS TRUE",
    }.get(status, "AND d.closed IS NOT TRUE")
    rows = store.query(
        f"""
        WITH led AS (
            SELECT x.dossier_id, count(*)::int AS led
            FROM ({_LED_DOSSIERS}) x GROUP BY x.dossier_id
        ),
        matching AS (
            SELECT {NODE.format(t="d")}, d.opened_on, l.led,
                   d.closed IS TRUE AS is_closed
            FROM led l JOIN {COLLECTION_DOSSIERS} d ON d.id = l.dossier_id
            WHERE true {by_status}
        )
        {paged("matching", page_of("matching", _DOSSIER_ORDER[sort]))}
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
    store: GraphStore,
    slug: str,
    *,
    limit: int = 100,
    offset: int = 0,
    sort: str = "date",
    today: str = "",
) -> dict[str, Any] | None:
    """A page of the activities a committee leads, newest first; None when unknown.

    With *sort* ``importance`` those held (dated on or before *today*) come first, the
    latest first, then those planned, the soonest first, then those without a date.

    Accepts the committee's ``slug`` or its ``key``. Returns ``{total, items}``.
    """
    committee = find_committee(store, slug)
    if committee is None:
        return None
    return cached(
        store,
        ("committee-activities", committee["id"], limit, offset, sort, today),
        lambda: _led_activities(store, committee["id"], limit, offset, sort, today),
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


# The orders of the activities of a committee: the newest date first, or the held ones from
# the latest, then the planned from the soonest, then the undated.
_ACTIVITY_ORDER = {
    "date": "date DESC NULLS LAST, id ASC",
    "importance": (
        "(date IS NULL) ASC NULLS LAST, (date > %(today)s) ASC NULLS LAST,"
        " CASE WHEN date <= %(today)s THEN date END DESC NULLS LAST,"
        " CASE WHEN date > %(today)s THEN date END ASC NULLS LAST, id ASC"
    ),
}


def _led_activities(
    store: GraphStore,
    committee_id: str,
    limit: int,
    offset: int,
    sort: str,
    today: str,
) -> dict[str, Any]:
    """``{total, items}``: a page of the activities a committee leads, in the order of
    *sort*; kept per data version."""
    rows = store.query(
        f"""
        WITH led AS ({_LED_ACTIVITIES}),
        listed AS ({paged("led", page_of("led", _ACTIVITY_ORDER[sort]))})
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
        ORDER BY listed.n
        """,
        {
            "committee_id": committee_id,
            "limit": limit,
            "offset": offset,
            "today": today,
        },
    )
    total, items = 0, []
    for row in rows:
        total = row["total"]
        if row["id"] is not None:
            items.append(row["item"])
    return {"total": total, "items": items}
