"""Queries behind the faction endpoints: the factions of both Kamers, their seats on a
day and the votes of a faction of the Eerste Kamer."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    CHAMBER_EK,
    CHAMBER_TK,
    COLLECTION_DECISIONS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    COLLECTION_MEMBERS,
    RELATION_MEMBER_OF,
)
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore
from lawgraph.db._rows import node_doc
from lawgraph.db.queries._json_sql import (
    EMPTY_ARRAY,
    array_or_empty,
    period_holds,
    period_overlaps,
    truthy_or,
)
from lawgraph.db.queries._parliament_sql import (
    ASKED,
    NODE,
    asked_period,
    contains,
    of_chamber,
)

# What a faction is searched by.
_FACTION_NAME = "f.props ->> 'name'"
_FACTION_ABBREVIATION = "f.props ->> 'abbreviation'"


def get_factions(
    store: GraphStore,
    *,
    active: bool | None = None,
    q: str | None = None,
    chamber: str = CHAMBER_TK,
    active_from: str | None = None,
    active_to: str | None = None,
) -> list[dict[str, Any]]:
    """Every parliamentary party of *chamber* with its member count (the seats held today,
    ``lg_seated``), seated ones first; with a period (*active_from*, *active_to*) those
    active in it (``active_from`` to ``active_until``)."""
    bind: dict[str, Any] = {
        "member_of": RELATION_MEMBER_OF,
        "today": dutch_today().isoformat(),
    }
    filters = ["f.props ->> 'name' <> ''", of_chamber("f", chamber)]
    if asked_period(bind, active_from, active_to):
        filters.append(
            period_overlaps(
                "f.props -> 'active_from'", "f.props -> 'active_until'", *ASKED
            )
        )
    if active is not None:
        filters.append("f.active = %(active)s")
        bind["active"] = active
    if q:
        filters.append(
            f"{contains(_FACTION_NAME)} OR {contains(_FACTION_ABBREVIATION)}"
        )
        bind["q"] = q.strip().lower()
    rows = store.query(
        f"""
        SELECT {NODE.format(t="f")}, coalesce(counted.n, 0) AS member_count
        FROM {COLLECTION_FACTIONS} f
        LEFT JOIN (
            -- looked up per faction: its order does not reach the answer
            SELECT e.to_id, count(*)::int AS n
            FROM {COLLECTION_EDGES} e
            WHERE e.relation = %(member_of)s
              AND e.to_collection = '{COLLECTION_FACTIONS}'
              AND lg_seated(e.doc -> 'meta', %(today)s)
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
            {array_or_empty("m.pj_faction_memberships")}
        ) AS f(period)
        -- only a member with faction memberships has any (``in_parliament``); the list is
        -- a column of its own, read without the rest of the props
        WHERE m.in_parliament
          AND {period_holds("f.period -> 'from_date'", "f.period -> 'to_date'", "%(day)s")}
        GROUP BY 1
        ORDER BY 1 ASC NULLS FIRST
        """,
        {"day": day},
    )
    return {row["faction"]: row["seats"] for row in rows}


# The decision names the faction ``%(name)s`` in its list ``{}``.
_NAMES = "lg_text_array(d.props -> '{}') @> ARRAY[%(name)s]::text[]"


def get_ek_faction_votes(
    store: GraphStore,
    abbreviation: str,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """How a faction of the Eerste Kamer voted, by its name as the list of votes writes it
    (*abbreviation*): ``{total, counts, items}``, newest first. ``counts`` per choice
    (``voor``, ``tegen``, ``aantekening gevraagd``) over every vote that names it."""
    by_date = ""
    if from_date is not None:
        by_date += " AND d.date >= %(from)s"
    if to_date is not None:
        # a decision without a date is before every day
        by_date += " AND (d.date <= %(to)s OR d.date IS NULL)"
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
            -- the choices in their order (D11)
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
                    'dossier_numbers', {truthy_or("d.props -> 'dossier_numbers'", EMPTY_ARRAY)},
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
            "from": from_date,
            "to": to_date,
            "limit": limit,
            "offset": offset,
        },
    )
    row = next(rows, None)
    return row or {"total": 0, "counts": {}, "items": []}
