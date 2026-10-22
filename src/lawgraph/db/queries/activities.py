"""Queries behind ``GET /api/activities/{key}`` and its records: one activity (a debate, a
hearing, a vote) and what was made in it or is on its agenda; and when the Tweede Kamer
meets and votes (``chamber_schedule`` of ``GET /api/feed/summary``).

The head reads the activity, its committee and the activities it continues; the records are
a route of their own (``records``), each list a probe of an index of the edges
(``edges_to_cover`` for what was ``MADE_IN`` it, ``edges_from_cover`` for its agenda), and
a document is read from ``lg_document_light``, without its text.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_EDGES,
    RELATION_ABOUT,
    RELATION_CONTINUES,
    RELATION_LED_BY,
    RELATION_MADE_IN,
)
from lawgraph.core.dossier_stages import ACTIVITY_HELD, ACTIVITY_PLANNED
from lawgraph.core.tk_links import PLENARY_KINDS, VOTES_KIND
from lawgraph.core.tk_records.kinds import KIND_MOTION
from lawgraph.db import GraphStore


def lead_committee(activity: str) -> str:
    """SQL: the committee that leads the activity *activity* (``LED_BY``) as ``{key, slug,
    name}``, the first by key when two lead it; null when none does (a plenary one)."""
    return f"""(
        SELECT json_build_object(
            'key', c.key, 'slug', c.props -> 'slug', 'name', c.props -> 'name'
        )
        FROM {COLLECTION_EDGES} led JOIN {COLLECTION_COMMITTEES} c ON c.id = led.to_id
        WHERE led.from_id = {activity}.id AND led.relation = '{RELATION_LED_BY}'
          AND led.to_collection = '{COLLECTION_COMMITTEES}'
        ORDER BY c.key
        LIMIT 1
    )"""


_HEAD_SQL = f"""
SELECT a.id, a.key, a.labels, a.props,
    {lead_committee("a")} AS committee,
    (
        SELECT coalesce(json_agg(json_build_object(
            'id', m.id, 'key', m.key, 'number', m.props -> 'number',
            'date', m.props -> 'date', 'status', m.props -> 'status'
        ) ORDER BY m.date ASC NULLS FIRST, m.key), '[]'::json)
        FROM {COLLECTION_EDGES} e JOIN {COLLECTION_ACTIVITIES} m ON m.id = e.to_id
        WHERE e.from_id = a.id AND e.relation = %(continues)s
          AND e.to_collection = '{COLLECTION_ACTIVITIES}'
    ) AS moved_from,
    (
        SELECT coalesce(json_agg(json_build_object(
            'id', m.id, 'key', m.key, 'number', m.props -> 'number',
            'date', m.props -> 'date', 'status', m.props -> 'status'
        ) ORDER BY m.date ASC NULLS FIRST, m.key), '[]'::json)
        FROM {COLLECTION_EDGES} e JOIN {COLLECTION_ACTIVITIES} m ON m.id = e.from_id
        WHERE e.to_id = a.id AND e.relation = %(continues)s
          AND e.from_collection = '{COLLECTION_ACTIVITIES}'
    ) AS moved_to
FROM {COLLECTION_ACTIVITIES} a
WHERE a.key = %(key)s
"""


def get_activity(store: GraphStore, key: str) -> dict[str, Any] | None:
    """The activity *key* with its lead committee (``LED_BY``), the activities it took the
    place of (``moved_from``: it ``CONTINUES`` them) and those that took its place
    (``moved_to``); None when unknown."""
    rows = store.query(
        _HEAD_SQL,
        {"key": key, "continues": RELATION_CONTINUES},
    )
    return next(iter(rows), None)


# A document made in the activity, as a list names it: its light props, without its text.
_DOCUMENT = """json_build_object(
    'id', p.id, 'key', split_part(p.id, '/', 2), 'kind', p.props -> 'kind',
    'date', p.props -> 'date', 'title', coalesce(
        CASE WHEN json_typeof(p.props -> 'title') = 'string' THEN p.props -> 'title' END,
        p.props -> 'display_name'),
    'dossier_number', p.props -> 'dossier_number',
    'dossier_suffix', p.props -> 'dossier_suffix',
    'sequence', p.props -> 'sequence', 'dictum', p.props -> 'dictum',
    'has_text', p.props -> 'has_text'
)"""

_RECORDS_SQL = f"""
WITH made AS MATERIALIZED (
    SELECT e.from_id AS id, e.from_collection AS collection
    FROM {COLLECTION_EDGES} e
    WHERE e.to_id = %(id)s AND e.relation = %(made_in)s
),
papers AS MATERIALIZED (
    SELECT m.id, l.props,
           starts_with(coalesce(lg_str(l.props -> 'kind'), ''), %(motion)s) AS motion
    FROM made m JOIN lg_document_light l ON l.id = m.id
    WHERE m.collection = '{COLLECTION_DOCUMENTS}'
)
SELECT
    (
        SELECT coalesce(json_agg({_DOCUMENT} ORDER BY
            lg_str(p.props -> 'date') ASC NULLS LAST, lg_str(p.props -> 'kind') NULLS LAST, p.id),
            '[]'::json)
        FROM papers p
        WHERE NOT p.motion
    ) AS documents,
    (
        SELECT coalesce(json_agg({_DOCUMENT} ORDER BY
            lg_num(p.props -> 'sequence') ASC NULLS LAST, p.id), '[]'::json)
        FROM papers p
        WHERE p.motion
    ) AS motions,
    (
        SELECT coalesce(json_agg(json_build_object(
            'id', c.id, 'key', c.key, 'number', c.number, 'text', c.props -> 'text',
            'status', c.status, 'registered_on', c.props -> 'registered_on',
            'expected_resolution', c.props -> 'expected_resolution',
            'minister_name', c.props -> 'minister_name',
            'minister_role', c.props -> 'minister_role'
        ) ORDER BY c.number ASC NULLS LAST, c.key), '[]'::json)
        FROM made m JOIN {COLLECTION_COMMITMENTS} c ON c.id = m.id
        WHERE m.collection = '{COLLECTION_COMMITMENTS}'
    ) AS commitments,
    (
        SELECT coalesce(json_agg(json_build_object(
            'id', x.id, 'key', x.key, 'date', x.date, 'passed', x.passed,
            'subject', x.props -> 'subject', 'kind', x.props -> 'kind',
            'decision_kind', x.props -> 'decision_kind',
            'decision_text', x.props -> 'decision_text',
            'tally', x.props -> 'tally'
        ) ORDER BY lg_num(x.props -> 'decision_order') ASC NULLS LAST, x.key),
        '[]'::json)
        FROM made m JOIN {COLLECTION_DECISIONS} x ON x.id = m.id
        WHERE m.collection = '{COLLECTION_DECISIONS}'
    ) AS decisions,
    (
        SELECT coalesce(json_agg(json_build_object(
            'id', c.id, 'key', c.key, 'number', c.props -> 'number',
            'kind', c.props -> 'kind', 'title', c.props -> 'title'
        ) ORDER BY lg_str(c.props -> 'number') ASC NULLS LAST, c.key), '[]'::json)
        FROM {COLLECTION_EDGES} e JOIN {COLLECTION_CASES} c ON c.id = e.to_id
        WHERE e.from_id = %(id)s AND e.relation = %(about)s
          AND e.to_collection = '{COLLECTION_CASES}'
    ) AS cases
"""


def get_activity_records(store: GraphStore, node_id: str) -> dict[str, Any]:
    """What was made in the activity *node_id* (``MADE_IN``): its documents (a stenogram, a
    verslag, a convocatie) apart from the motions submitted in it, the commitments made
    and the decisions taken in it; and the cases on its agenda (``ABOUT``)."""
    rows = store.query(
        _RECORDS_SQL,
        {
            "id": node_id,
            "made_in": RELATION_MADE_IN,
            "about": RELATION_ABOUT,
            "motion": KIND_MOTION,
        },
    )
    return dict(next(iter(rows)))


# The day-precise one first within a week: a vote planned for the week of a Monday
# (``Weeknummer``) is that week, after one planned for a day of it.
_WEEK_ORDER = (
    "date_trunc('week', a.date::date) ASC NULLS LAST, "
    "lg_str(a.props -> 'precision') IS DISTINCT FROM 'Dag' ASC NULLS LAST"
)


def _schedule_part(kinds: str, *, held: bool) -> str:
    """SQL: the activity of *kinds* (a ``LIKE ANY`` parameter) last held on or before
    ``today``, or first planned on or after it."""
    if held:
        where, order = "a.date <= %(today)s", "a.date DESC NULLS LAST, a.key DESC"
    else:
        where, order = (
            "a.date >= %(today)s",
            f"{_WEEK_ORDER}, a.date ASC NULLS LAST, a.key",
        )
    status = "%(held)s" if held else "%(planned)s"
    return f"""(
        SELECT json_build_object('id', a.id, 'key', a.key, 'props', a.props)
        FROM {COLLECTION_ACTIVITIES} a
        WHERE {where} AND lg_str(a.props -> 'status') = {status}
          AND lower(lg_str(a.props -> 'kind')) LIKE ANY({kinds})
        ORDER BY {order}
        LIMIT 1
    )"""


_SCHEDULE_SQL = f"""
SELECT
    {_schedule_part("%(sitting)s", held=True)} AS last_sitting,
    {_schedule_part("%(votes)s", held=True)} AS last_votes,
    {_schedule_part("%(sitting)s", held=False)} AS next_sitting,
    {_schedule_part("%(votes)s", held=False)} AS next_votes
"""


def get_chamber_schedule(store: GraphStore, today: str) -> dict[str, Any]:
    """When the Tweede Kamer last met and voted in the plenary hall, and when it meets and
    votes next, from its activities: ``last_sitting`` and ``last_votes`` the latest held
    (``Uitgevoerd``) on or before *today*, ``next_sitting`` and ``next_votes`` the first
    planned (``Gepland``) on or after it, of a week the one planned for a day before one
    planned for the week; a sitting any plenary kind (``PLENARY_KINDS``), the votes
    ``Stemmingen``. Each ``{id, key, props}``, or None."""
    rows = store.query(
        _SCHEDULE_SQL,
        {
            "today": today,
            "held": ACTIVITY_HELD,
            "planned": ACTIVITY_PLANNED,
            "sitting": [f"{kind}%" for kind in PLENARY_KINDS],
            "votes": [f"{VOTES_KIND}%"],
        },
    )
    return dict(next(iter(rows)))
