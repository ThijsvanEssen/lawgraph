"""Queries behind the cabinet endpoints, and the posts and memberships the coalition reads."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOSSIERS,
    LABEL_RIJKSOVERHEID,
    RELATION_SERVED_IN,
)
from lawgraph.core.time import OPEN_END, OPEN_START, dutch_today
from lawgraph.core.tk_records.actors import CAPACITY_GOVERNMENT
from lawgraph.core.tk_records.commitments import COMMITMENT_OPEN
from lawgraph.db import GraphStore
from lawgraph.db._rows import node_doc
from lawgraph.db.counting import Store
from lawgraph.db.queries._json_sql import (
    EMPTY_ARRAY,
    array_or_empty,
    period_holds,
    truthy_or,
)
from lawgraph.db.version_cache import lasting

# The kind (Zaak.Soort) of a bill the government brings in.
KIND_BILL = "Wetgeving"


def person_object(member: str) -> str:
    """SQL: the member as a list and detail item name it, ``{key, name, slug}`` (the slug
    for its readable address)."""
    return (
        f"json_build_object('key', {member}.key, 'name', {member}.list_name,"
        f" 'slug', {member}.props -> 'slug')"
    )


# The government bills of a dossier ``d``: brought in under a cabinet, not an initiative.
_BILL = "d.initiative = false AND d.kind = %(bill)s"


def get_cabinets(store: GraphStore) -> list[dict[str, Any]]:
    """Every cabinet, newest first, with its prime minister and counts: ``members`` (who
    held a post in it), ``bills`` (government bills brought in under it) and
    ``commitments`` (made under it)."""
    rows = store.query(
        f"""
        SELECT c.id, c.key, c.type, c.labels, c.props,
               CASE WHEN pm.id IS NOT NULL THEN {person_object("pm")} END AS prime_minister,
               (SELECT count(*)::int FROM edges e
                WHERE e.to_id = c.id AND e.relation = %(served_in)s) AS members,
               coalesce(bills.n, 0) AS bills,
               coalesce(commitments.n, 0) AS commitments
        FROM cabinets c
        LEFT JOIN members pm ON pm.key = lg_str(c.props -> 'prime_minister')
        LEFT JOIN (
            SELECT d.cabinet, count(*)::int AS n FROM dossiers d
            WHERE d.cabinet IS NOT NULL AND {_BILL}
            GROUP BY d.cabinet
        ) bills ON bills.cabinet = c.key
        LEFT JOIN (
            SELECT k.cabinet, count(*)::int AS n FROM commitments k
            WHERE k.cabinet IS NOT NULL
            GROUP BY k.cabinet
        ) commitments ON commitments.cabinet = c.key
        ORDER BY lg_str(c.props -> 'from_date') DESC NULLS LAST, c.key ASC
        """,
        {"bill": KIND_BILL, "served_in": RELATION_SERVED_IN},
    )
    return [
        {
            "cabinet": node_doc(row),
            "prime_minister": row["prime_minister"],
            "members": row["members"],
            "bills": row["bills"],
            "commitments": row["commitments"],
        }
        for row in rows
    ]


# The dossiers a member ``m`` signed as a bewindspersoon within the period of the cabinet
# ``c`` (from its ``period_start``, or from any day when it has none, to its ``period_end``:
# its end or today), directly or through a case, each once, and how many of them are
# government bills: from ``lg_authored``, per member the range of its index by capacity and
# date within the period, each signature with its dossiers; no document or case read for its
# date (a minister of many cabinets signed tens of thousands).
_SIGNED = f"""
SELECT count(*)::int AS dossiers,
       (count(*) FILTER (WHERE d.id IS NOT NULL AND d.kind = %(bill)s))::int AS bills
FROM (
    SELECT DISTINCT x.dossier_id
    FROM lg_authored a
    CROSS JOIN LATERAL unnest(a.dossiers) AS x(dossier_id)
    WHERE a.member_id = m.id AND a.capacity = %(government)s
      AND a.date >= coalesce(c.period_start, '') AND a.date <= c.period_end
) signed
LEFT JOIN {COLLECTION_DOSSIERS} d ON d.id = signed.dossier_id
"""


# How long the page of a cabinet is kept (seconds), whatever the data does: its counts read
# every document its members signed (a minute for the newest cabinets together, from disk), and a
# poll of other sources (an hour of judgments) changes none of them; a newly signed document
# counts within the hour.
CABINET_MAX_AGE = 3600.0


def get_cabinet(store: GraphStore, key: str) -> dict[str, Any] | None:
    """One cabinet with every member and their posts in it, and per member the counts
    ``dossiers`` (signed first or with others as a bewindspersoon within the cabinet's
    period, directly or through a case), ``bills`` (of those, government bills) and
    ``open_commitments`` (made under it and still open); None when unknown. Kept
    ``CABINET_MAX_AGE`` and a day, whatever the data does: the counts read every document a
    member ever signed, for a long-serving minister thousands, a minute from disk."""
    today = dutch_today().isoformat()
    return lasting(
        store,
        ("cabinet", key, today),
        lambda: _cabinet(store, key, today),
        CABINET_MAX_AGE,
    )


def _cabinet(store: GraphStore, key: str, today: str) -> dict[str, Any] | None:
    rows = store.query(
        f"""
        SELECT c.id, c.key, c.type, c.labels, c.props,
               CASE WHEN pm.id IS NOT NULL THEN {person_object("pm")} END AS prime_minister,
               (
                   SELECT coalesce(json_agg(json_build_object(
                       'member', {person_object("m")},
                       'posts', {truthy_or("e.doc -> 'meta' -> 'posts'", EMPTY_ARRAY)},
                       'dossiers', signed.dossiers,
                       'bills', signed.bills,
                       'open_commitments', (
                           SELECT count(*)::int FROM commitments k
                           WHERE k.member_key = m.key AND k.cabinet = c.key
                             AND k.status = %(open)s
                       )
                   ) ORDER BY e.key ASC), '[]'::json)
                   FROM edges e
                   JOIN members m ON m.id = e.from_id
                   CROSS JOIN LATERAL ({_SIGNED}) signed
                   WHERE e.to_id = c.id AND e.relation = %(served_in)s
               ) AS members,
               (SELECT count(*)::int FROM dossiers d
                WHERE d.cabinet = c.key AND {_BILL}) AS bills,
               (SELECT count(*)::int FROM commitments k
                WHERE k.cabinet = c.key) AS commitments
        FROM (
            SELECT c.*, lg_str(c.props -> 'from_date') AS period_start,
                   CASE WHEN lg_truthy(c.props -> 'to_date')
                        THEN lg_str(c.props -> 'to_date') ELSE %(today)s END AS period_end
            FROM cabinets c
            WHERE c.key = %(key)s
            OFFSET 0
        ) c
        LEFT JOIN members pm ON pm.key = lg_str(c.props -> 'prime_minister')
        """,
        {
            "key": key,
            "today": today,
            "served_in": RELATION_SERVED_IN,
            "government": CAPACITY_GOVERNMENT,
            "bill": KIND_BILL,
            "open": COMMITMENT_OPEN,
        },
    )
    row = next(rows, None)
    if row is None:
        return None
    return {
        "cabinet": node_doc(row),
        "prime_minister": row["prime_minister"],
        "members": row["members"],
        "bills": row["bills"],
        "commitments": row["commitments"],
    }


def cabinets_with_posts(store: GraphStore) -> list[dict[str, Any]]:
    """Every cabinet, oldest first, with every post held in it (``lawgraph verify
    cabinets``): ``{key, props, posts}``, each post with ``member`` (its key) and ``own``
    (a member only Rijksoverheid knows)."""
    # each post with ``own`` and ``member`` set (``lg_update``: they win over the post's own)
    rows = store.query(
        f"""
        SELECT json_build_object(
            'key', c.key,
            'props', c.props,
            'posts', (
                SELECT coalesce(json_agg(
                    lg_update(post, json_build_object(
                        'own', coalesce(%(own)s = ANY(m.labels), false),
                        'member', split_part(e.from_id, '/', 2)
                    ))
                    ORDER BY e.key ASC, p.n
                ), '[]'::json)
                FROM edges e
                LEFT JOIN members m ON m.id = e.from_id
                CROSS JOIN LATERAL json_array_elements(
                    {array_or_empty("e.doc -> 'meta' -> 'posts'")}
                ) WITH ORDINALITY AS p(post, n)
                WHERE e.to_id = c.id AND e.relation = %(served_in)s
            )
        )
        FROM cabinets c
        ORDER BY lg_str(c.props -> 'from_date') ASC NULLS FIRST, c.key ASC
        """,
        {"served_in": RELATION_SERVED_IN, "own": LABEL_RIJKSOVERHEID},
    )
    return list(rows)


# ── coalition seats (``core.coalition``) ─────────────────────────────────────


def cabinet_posts(store: GraphStore, key: str) -> list[dict[str, Any]]:
    """Every post held in the cabinet *key* (``meta.posts`` of its ``SERVED_IN`` edges):
    ``{party: {short, faction}, from_date, to_date, …}``, in the order of the edges."""
    rows = store.query(
        f"""
        SELECT p.post
        FROM cabinets c
        JOIN edges e ON e.to_id = c.id AND e.relation = %(served_in)s
        CROSS JOIN LATERAL json_array_elements(
            {array_or_empty("e.doc -> 'meta' -> 'posts'")}
        ) WITH ORDINALITY AS p(post, n)
        WHERE c.key = %(key)s
        ORDER BY e.key ASC, p.n ASC
        """,
        {"key": key, "served_in": RELATION_SERVED_IN},
    )
    return [dict(post) for post in rows if isinstance(post, dict)]


def memberships_between(store: Store, start: str, end: str) -> list[dict[str, Any]]:
    """``{member, faction_key, from_date, to_date}`` of every faction membership of the
    Tweede Kamer that overlaps *start*..*end* (inclusive), from the members'
    ``faction_memberships`` (a column of its own, read without the rest of the props)."""
    rows = store.query(
        f"""
        SELECT m.key AS member, lg_str(f.period -> 'faction_key') AS faction_key,
               lg_str(f.period -> 'from_date') AS from_date,
               lg_str(f.period -> 'to_date') AS to_date
        FROM members m
        CROSS JOIN LATERAL json_array_elements(
            {array_or_empty("m.pj_faction_memberships")}
        ) AS f(period)
        WHERE m.in_parliament
          AND lg_str(f.period -> 'from_date') <= %(end)s
          AND (lg_str(f.period -> 'to_date') IS NULL
               OR lg_str(f.period -> 'to_date') >= %(start)s)
        ORDER BY 1 ASC NULLS FIRST, 3 ASC NULLS FIRST
        """,
        {"start": start, "end": end},
    )
    return list(rows)


def all_memberships(store: Store) -> list[dict[str, Any]]:
    """Every faction membership of the Tweede Kamer (``memberships_between`` over all time)."""
    return memberships_between(store, OPEN_START, OPEN_END)


def cabinet_on(store: GraphStore, day: str) -> dict[str, Any] | None:
    """``{key, name, from_date, to_date}`` of the cabinet in office on *day*: the newest that had
    begun by then and had not ended before it; None before 1945 or between two."""
    rows = store.query(
        f"""
        SELECT c.key, lg_str(c.props -> 'name') AS name,
               lg_str(c.props -> 'from_date') AS from_date,
               lg_str(c.props -> 'to_date') AS to_date
        FROM cabinets c
        WHERE {period_holds("c.props -> 'from_date'", "c.props -> 'to_date'", "%(day)s")}
        ORDER BY lg_str(c.props -> 'from_date') DESC NULLS LAST, c.key ASC
        LIMIT 1
        """,
        {"day": day},
    )
    return next(iter(rows), None)
