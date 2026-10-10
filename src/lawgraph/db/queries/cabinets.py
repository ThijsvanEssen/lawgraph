"""Queries behind the cabinet and commitment endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Any, cast

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_CASES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    LABEL_RIJKSOVERHEID,
    RELATION_ABOUT,
    RELATION_AUTHORED,
    RELATION_MADE_IN,
    RELATION_PART_OF,
    RELATION_SERVED_IN,
)
from lawgraph.core.tk_records import CAPACITY_GOVERNMENT, COMMITMENT_OPEN, NO_DUE_DATE
from lawgraph.db import GraphStore
from lawgraph.db._rows import node_doc
from lawgraph.db.counting import Store
from lawgraph.db.queries import member_authored
from lawgraph.db.version_cache import lasting

# The kind (Zaak.Soort) of a bill the government brings in.
KIND_BILL = "Wetgeving"


def _name(member: str) -> str:
    """SQL: the name *member* goes by (AQL ``name OR known_as OR government_name``); for a
    TK person without one, the name Rijksoverheid gives (``David van Weel``, else
    ``D.M. van Weel``)."""
    name, known_as = f"{member}.props -> 'name'", f"{member}.props -> 'known_as'"
    return (
        f"CASE WHEN lg_truthy({name}) THEN {name}"
        f" WHEN lg_truthy({known_as}) THEN {known_as}"
        f" ELSE {member}.props -> 'government_name' END"
    )


def _person(member: str) -> str:
    """SQL: the member as a list and detail item name it, ``{key, name}``."""
    return f"json_build_object('key', {member}.key, 'name', {_name(member)})"


# The government bills of a dossier ``d``: brought in under a cabinet, not an initiative.
_BILL = "d.initiative = false AND d.kind = %(bill)s"


def get_cabinets(store: GraphStore) -> list[dict[str, Any]]:
    """Every cabinet, newest first, with its prime minister and counts: ``members`` (who
    held a post in it), ``bills`` (government bills brought in under it) and
    ``commitments`` (made under it)."""
    rows = store.query(
        f"""
        SELECT c.id, c.key, c.type, c.labels, c.props,
               CASE WHEN pm.id IS NOT NULL THEN {_person("pm")} END AS prime_minister,
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
# its end or today; computed once per cabinet, as reading them from ``props`` parses the
# whole json again on every comparison), directly
# or through a case, each once; and how many of them are government bills. The date of a
# paper is that of its document; an AUTHORED edge to a node of another collection reads
# it from that node.
_SIGNED = f"""
SELECT count(*)::int AS dossiers,
       (count(*) FILTER (WHERE d.id IS NOT NULL AND d.kind = %(bill)s)
       )::int AS bills
FROM (
    SELECT DISTINCT CASE WHEN p.to_collection = '{COLLECTION_CASES}'
                         THEN q.to_id ELSE p.to_id END AS target
    FROM (
        -- each date read once: OFFSET 0 keeps the subquery from being inlined into every
        -- comparison of the date below, where it would be read again per comparison; a
        -- case's from its own table by key, not through the view of every node
        SELECT a.to_id,
               CASE WHEN a.to_collection = '{COLLECTION_DOCUMENTS}' THEN doc.date
                    WHEN a.to_collection = '{COLLECTION_CASES}' THEN (
                        SELECT lg_str(k.props -> 'date') FROM {COLLECTION_CASES} k
                        WHERE k.id = a.to_id)
                    ELSE (SELECT lg_str(n.props -> 'date') FROM nodes n WHERE n.id = a.to_id)
               END AS date
        FROM edges a
        LEFT JOIN {COLLECTION_DOCUMENTS} doc
            ON a.to_collection = '{COLLECTION_DOCUMENTS}' AND doc.id = a.to_id
        WHERE a.from_id = m.id AND a.relation = %(authored)s
          AND lg_str(a.doc -> 'meta' -> 'capacity') = %(government)s
        OFFSET 0
    ) a
    JOIN edges p ON p.from_id = a.to_id AND p.relation = %(part_of)s
    LEFT JOIN edges q ON p.to_collection = '{COLLECTION_CASES}' AND q.from_id = p.to_id
        AND q.relation = %(part_of)s AND q.to_collection = '{COLLECTION_DOSSIERS}'
    WHERE a.date IS NOT NULL
      AND (c.period_start IS NULL OR a.date >= c.period_start)
      AND a.date <= c.period_end
) signed
LEFT JOIN dossiers d ON d.id = signed.target
WHERE starts_with(signed.target, '{COLLECTION_DOSSIERS}/')
"""


# The same, from ``lg_authored`` once it is filled: per member a range of its index, each
# paper with its dossiers (directly and through its cases) kept with it, instead of the walk
# over every paper the member signed and its cases.
_SIGNED_LIGHT = f"""
SELECT count(*)::int AS dossiers,
       (count(*) FILTER (WHERE d.id IS NOT NULL AND d.kind = %(bill)s))::int AS bills
FROM (
    SELECT DISTINCT x.dossier_id
    FROM (
        SELECT a.dossiers,
               CASE WHEN starts_with(a.document_id, '{COLLECTION_DOCUMENTS}/') THEN doc.date
                    WHEN starts_with(a.document_id, '{COLLECTION_CASES}/') THEN (
                        SELECT lg_str(k.props -> 'date') FROM {COLLECTION_CASES} k
                        WHERE k.id = a.document_id)
                    ELSE (SELECT lg_str(n.props -> 'date') FROM nodes n
                          WHERE n.id = a.document_id)
               END AS date
        FROM lg_authored a
        LEFT JOIN {COLLECTION_DOCUMENTS} doc ON doc.id = a.document_id
        WHERE a.member_id = m.id
          AND lg_str(a.meta -> 'capacity') = %(government)s
        OFFSET 0
    ) a
    CROSS JOIN LATERAL unnest(a.dossiers) AS x(dossier_id)
    WHERE a.date IS NOT NULL
      AND (c.period_start IS NULL OR a.date >= c.period_start)
      AND a.date <= c.period_end
) signed
LEFT JOIN dossiers d ON d.id = signed.dossier_id
"""


# How long the page of a cabinet is kept (seconds), whatever the data does: its counts read
# every paper its members signed (a minute for the newest cabinets together, from disk), and a
# poll of other sources (an hour of judgments) changes none of them; a newly signed paper
# counts within the hour.
CABINET_MAX_AGE = 3600.0


def get_cabinet(store: GraphStore, key: str) -> dict[str, Any] | None:
    """One cabinet with every member and their posts in it, and per member the counts
    ``dossiers`` (signed first or with others as a bewindspersoon within the cabinet's
    period, directly or through a case), ``bills`` (of those, government bills) and
    ``open_commitments`` (made under it and still open); None when unknown. Kept
    ``CABINET_MAX_AGE`` and a day, whatever the data does: the counts read every paper a
    member ever signed, for a long-serving minister thousands, a minute from disk."""
    today = dt.date.today().isoformat()
    return lasting(
        store,
        ("cabinet", key, today),
        lambda: _cabinet(store, key, today),
        CABINET_MAX_AGE,
    )


def _cabinet(store: GraphStore, key: str, today: str) -> dict[str, Any] | None:
    signed_sql = _SIGNED_LIGHT if member_authored.is_filled(store) else _SIGNED
    rows = store.query(
        f"""
        SELECT c.id, c.key, c.type, c.labels, c.props,
               CASE WHEN pm.id IS NOT NULL THEN {_person("pm")} END AS prime_minister,
               (
                   SELECT coalesce(json_agg(json_build_object(
                       'member', {_person("m")},
                       'posts', CASE WHEN lg_truthy(e.doc -> 'meta' -> 'posts')
                                     THEN e.doc -> 'meta' -> 'posts' ELSE '[]'::json END,
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
                   CROSS JOIN LATERAL ({signed_sql}) signed
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
            "authored": RELATION_AUTHORED,
            "government": CAPACITY_GOVERNMENT,
            "part_of": RELATION_PART_OF,
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


# What a commitment item shows beside its own props: who made it, its dossiers and the
# activity it was made in.
_COMMITMENT_ITEM = f"""json_build_object(
    'commitment', json_build_object(
        '_key', c.key, '_id', c.id, 'type', c.type, 'labels', to_json(c.labels),
        'props', c.props
    ),
    'member', (
        SELECT {_person("m")} FROM members m WHERE m.key = c.member_key
    ),
    'dossiers', (
        SELECT coalesce(json_agg(json_build_object(
            'key', d.key, 'number', d.props -> 'label', 'title', d.props -> 'title'
        ) ORDER BY d.label ASC NULLS FIRST, d.key ASC), '[]'::json)
        FROM edges e JOIN dossiers d ON d.id = e.to_id
        WHERE e.from_id = c.id AND e.relation = %(about)s
          AND e.to_collection = '{COLLECTION_DOSSIERS}'
    ),
    'activity', (
        SELECT json_build_object(
            'key', a.key, 'date', a.props -> 'date', 'number', a.props -> 'number'
        )
        FROM edges e JOIN activities a ON a.id = e.to_id
        WHERE e.from_id = c.id AND e.relation = %(made_in)s
          AND e.to_collection = '{COLLECTION_ACTIVITIES}'
        ORDER BY e.to_id ASC
        LIMIT 1
    )
)"""


# The dimensions a commitment list counts as facets, and the column each counts.
_COMMITMENT_FACETS = {
    "status": "c.status",
    "cabinet": "c.cabinet",
    "ministry": "c.ministry",
}

# AQL on ``props.expected_resolution``: ``!= @no_date`` (a value of another type is
# unequal), and ``< @day`` (null, a boolean and a number sort below a string, an array and
# an object above it).
_EXPECTED = "c.props -> 'expected_resolution'"
_DATED = f"lg_str({_EXPECTED}) IS DISTINCT FROM %(no_date)s"


def _expected_before(day: str) -> str:
    return (
        f"CASE json_typeof({_EXPECTED})"
        f" WHEN 'string' THEN ({_EXPECTED} #>> '{{}}') < %({day})s"
        f" WHEN 'array' THEN false WHEN 'object' THEN false ELSE true END"
    )


# The orders of the list; the key settles ties. Soonest due puts those without a date (or
# with the placeholder of none) last.
_COMMITMENT_SORTS = {
    "date": "c.made_on DESC NULLS LAST, c.key ASC",
    "expected_resolution": (
        f"(coalesce(json_typeof({_EXPECTED}), 'null') = 'null'"
        f" OR coalesce(lg_str({_EXPECTED}) = %(no_date)s, false)) ASC,"
        f" lg_str({_EXPECTED}) ASC NULLS FIRST, c.made_on DESC NULLS LAST, c.key ASC"
    ),
}


def _commitment_filters(
    bind: dict[str, Any],
    *,
    member: str | None,
    dossier: str | None,
    due_before: str | None,
    overdue: bool,
    q: str | None,
    made_from: str | None = None,
    made_to: str | None = None,
) -> list[str]:
    """The conditions on the commitment ``c`` of every count, their values in *bind*."""
    shared: list[str] = []
    # the day it was made, inclusive (``commitments_made_on``)
    if made_from:
        shared.append("c.made_on >= %(made_from)s")
        bind["made_from"] = made_from
    if made_to:
        shared.append("c.made_on <= %(made_to)s")
        bind["made_to"] = made_to
    if member:
        shared.append("c.member_key = %(member)s")
        bind["member"] = member
    if due_before:
        shared.append(f"{_DATED} AND {_expected_before('due_before')}")
        bind["due_before"] = due_before
        bind["no_date"] = NO_DUE_DATE
    if overdue:
        shared.append(
            f"c.status = %(open)s AND {_DATED} AND {_expected_before('today')}"
        )
        bind["open"] = COMMITMENT_OPEN
        bind["no_date"] = NO_DUE_DATE
        bind["today"] = dt.date.today().isoformat()
    if q:
        # nothing holds "" (*q* of spaces alone); a missing text is ""; both folded as the
        # search folds them (lg_fold: lower case, no accents)
        shared.append(
            "%(q)s <> '' AND strpos(lg_fold(coalesce(c.props ->> 'text', '')),"
            " lg_fold(%(q)s)) > 0"
        )
        bind["q"] = q.strip().lower()
    if dossier:
        shared.append(
            """EXISTS (
                SELECT 1 FROM edges e JOIN dossiers d ON d.id = e.to_id
                WHERE e.from_id = c.id AND e.relation = %(about)s
                  AND (d.label = %(dossier)s OR d.number = %(dossier)s)
            )"""
        )
        bind["dossier"] = dossier
    return shared


def get_commitments(
    store: GraphStore,
    *,
    status: str | None = None,
    member: str | None = None,
    cabinet: str | None = None,
    ministry: str | None = None,
    dossier: str | None = None,
    due_before: str | None = None,
    overdue: bool = False,
    q: str | None = None,
    sort: str = "date",
    limit: int = 100,
    offset: int = 0,
    made_from: str | None = None,
    made_to: str | None = None,
    facets: bool = True,
) -> dict[str, Any]:
    """A page of commitments, the total and ``facets``: per ``status``, ``cabinet`` and
    ``ministry`` the number of commitments per value under the other filters, each
    dimension counted without its own filter (``facets=False``: the page and the total
    alone, ``facets`` None). *dossier* is a number (``36600``) or the
    label of a dossier (``36600-VII``); *overdue* keeps the open ones whose expected date
    has passed; *made_from* and *made_to* the first and last day it was made on; *sort* is ``date`` (newest made first) or ``expected_resolution`` (soonest
    first, those without one last)."""
    own: dict[str, str] = {}
    bind: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "about": RELATION_ABOUT,
        "made_in": RELATION_MADE_IN,
    }
    for name, value in (
        ("status", status),
        ("cabinet", cabinet),
        ("ministry", ministry),
    ):
        if value:
            own[name] = f"{_COMMITMENT_FACETS[name]} = %({name})s"
            bind[name] = value
    shared = _commitment_filters(
        bind,
        member=member,
        dossier=dossier,
        due_before=due_before,
        overdue=overdue,
        q=q,
        made_from=made_from,
        made_to=made_to,
    )
    if sort == "expected_resolution":
        bind["no_date"] = NO_DUE_DATE
    order = _COMMITMENT_SORTS.get(sort, _COMMITMENT_SORTS["date"])

    def where(*clauses: str) -> str:
        return f"WHERE {' AND '.join(clauses)}" if clauses else ""

    per_facet = ",\n".join(
        f"""'{name}', (
            SELECT coalesce(json_agg(
                json_build_object('value', value, 'count', count)
                ORDER BY count DESC, value ASC NULLS FIRST
            ), '[]'::json)
            FROM (
                SELECT {column} AS value, count(*)::int AS count
                FROM commitments c
                {where(*shared, *(c for n, c in own.items() if n != name))}
                GROUP BY 1
            ) facet
        )"""
        for name, column in _COMMITMENT_FACETS.items()
    )
    statement = f"""
    WITH matching AS MATERIALIZED (
        SELECT c.id FROM commitments c {where(*shared, *own.values())}
    )
    SELECT json_build_object(
        'total', (SELECT count(*)::int FROM matching),
        'items', (
            SELECT coalesce(json_agg({_COMMITMENT_ITEM} ORDER BY page.n), '[]'::json)
            FROM (
                SELECT c.id, row_number() OVER (ORDER BY {order}) AS n
                FROM matching JOIN commitments c ON c.id = matching.id
                ORDER BY {order}
                LIMIT %(limit)s OFFSET %(offset)s
            ) page
            JOIN commitments c ON c.id = page.id
        ),
        'facets', {f"json_build_object({per_facet})" if facets else "NULL::json"}
    )
    """
    rows = list(store.query(statement, bind))
    return (
        cast(dict[str, Any], rows[0])
        if rows
        else {"total": 0, "items": [], "facets": {}}
    )


def get_commitment(store: GraphStore, key: str) -> dict[str, Any] | None:
    """One commitment as a list item; None when unknown."""
    rows = store.query(
        f"SELECT {_COMMITMENT_ITEM} FROM commitments c WHERE c.key = %(key)s",
        {"key": key, "about": RELATION_ABOUT, "made_in": RELATION_MADE_IN},
    )
    return cast(dict[str, Any] | None, next(rows, None))


def cabinets_with_posts(store: GraphStore) -> list[dict[str, Any]]:
    """Every cabinet, oldest first, with every post held in it (``lawgraph verify
    cabinets``): ``{key, props, posts}``, each post with ``member`` (its key) and ``own``
    (a member only Rijksoverheid knows)."""
    # MERGE(post, {member, own}): the keys of the post in byte order, then the new ones in
    # the order ArangoDB gave them (``own`` before ``member``).
    rows = store.query(
        """
        SELECT json_build_object(
            'key', c.key,
            'props', c.props,
            'posts', (
                SELECT coalesce(json_agg(
                    lg_merge(post, json_build_object(
                        'own', coalesce(%(own)s = ANY(m.labels), false),
                        'member', split_part(e.from_id, '/', 2)
                    ))
                    ORDER BY e.key ASC, p.n
                ), '[]'::json)
                FROM edges e
                LEFT JOIN members m ON m.id = e.from_id
                CROSS JOIN LATERAL json_array_elements(
                    CASE WHEN json_typeof(e.doc -> 'meta' -> 'posts') = 'array'
                         THEN e.doc -> 'meta' -> 'posts' ELSE '[]'::json END
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
        """
        SELECT p.post
        FROM cabinets c
        JOIN edges e ON e.to_id = c.id AND e.relation = %(served_in)s
        CROSS JOIN LATERAL json_array_elements(
            CASE WHEN json_typeof(e.doc -> 'meta' -> 'posts') = 'array'
                 THEN e.doc -> 'meta' -> 'posts' ELSE '[]'::json END
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
        """
        SELECT m.key AS member, lg_str(f.period -> 'faction_key') AS faction_key,
               lg_str(f.period -> 'from_date') AS from_date,
               lg_str(f.period -> 'to_date') AS to_date
        FROM members m
        CROSS JOIN LATERAL json_array_elements(
            CASE WHEN json_typeof(m.pj_faction_memberships) = 'array'
                 THEN m.pj_faction_memberships ELSE '[]'::json END
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


def cabinet_on(store: GraphStore, day: str) -> dict[str, Any] | None:
    """``{key, name, from_date, to_date}`` of the cabinet in office on *day*: the newest that had
    begun by then and had not ended before it; None before 1945 or between two."""
    rows = store.query(
        """
        SELECT c.key, lg_str(c.props -> 'name') AS name,
               lg_str(c.props -> 'from_date') AS from_date,
               lg_str(c.props -> 'to_date') AS to_date
        FROM cabinets c
        WHERE lg_str(c.props -> 'from_date') <= %(day)s
          AND (lg_str(c.props -> 'to_date') IS NULL
               OR lg_str(c.props -> 'to_date') >= %(day)s)
        ORDER BY lg_str(c.props -> 'from_date') DESC NULLS LAST, c.key ASC
        LIMIT 1
        """,
        {"day": day},
    )
    return next(iter(rows), None)
