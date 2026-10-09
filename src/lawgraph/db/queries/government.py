"""Queries behind ``semantic tk-government``: who made a commitment, who brought a dossier
in, and the cabinet in office then."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    RELATION_AUTHORED,
    RELATION_PART_OF,
)
from lawgraph.core.tk_records import CAPACITY_GOVERNMENT, CAPACITY_MEMBER
from lawgraph.db.counting import Store

# The role of the one who signs a document first.
ROLE_FIRST_SIGNATORY = "Eerste ondertekenaar"


def _keep(props: str, *fields: str) -> str:
    """SQL: AQL ``KEEP(props, fields)``, the fields *props* has with their keys in byte
    order (probe P1)."""
    names = ", ".join(f"'{field}'" for field in fields)
    return f"""coalesce(
        (SELECT json_object_agg(k, v ORDER BY k COLLATE "C")
         FROM json_each({props}) AS p(k, v) WHERE k IN ({names})),
        '{{}}'::json
    )"""


# These read whole collections, and the step that reads them looks each row up on its own:
# their order does not matter. ArangoDB gave the documents in the order they were last
# written; these give them in ``_key`` byte order, the same every time.


def government_people(store: Store) -> Iterator[dict[str, Any]]:
    """Every member who held a post in a cabinet: ``{id, name, posts}``, ``id`` the member
    key, ``name`` the name Rijksoverheid gives (``H.G. Herbert``; a minister who never
    sat in parliament has no other), ``posts`` their ``government_functions``."""
    posts = "m.props -> 'government_functions'"
    government_name = "m.props -> 'government_name'"
    return store.query(
        f"""
        SELECT json_build_object(
            'id', m.key,
            'name', CASE WHEN lg_truthy({government_name}) THEN {government_name}
                         ELSE m.props -> 'name' END,
            'posts', {posts}
        )
        FROM members m
        -- LENGTH(posts) > 0: an array or object with something in it, a string that is
        -- not empty, any number, true
        WHERE CASE json_typeof({posts})
            WHEN 'array' THEN json_array_length({posts}) > 0
            WHEN 'object' THEN EXISTS (SELECT 1 FROM json_object_keys({posts}))
            WHEN 'string' THEN ({posts} #>> '{{}}') <> ''
            WHEN 'number' THEN true
            WHEN 'boolean' THEN ({posts} #>> '{{}}') = 'true'
            ELSE false END
        ORDER BY m.key COLLATE "C"
        """
    )


def cabinet_periods(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, from_date, to_date}`` of every cabinet."""
    return store.query(
        """
        SELECT json_build_object(
            'key', c.key,
            'from_date', c.props -> 'from_date',
            'to_date', c.props -> 'to_date'
        )
        FROM cabinets c
        ORDER BY c.key COLLATE "C"
        """
    )


def commitment_makers(
    store: Store, ids: list[str] | None = None
) -> Iterator[dict[str, Any]]:
    """``{key, name, role, ministry_name, text, date, props}`` of every commitment, or of
    those with an ``_id`` in *ids*: who made it as the source writes it, the ministry the
    source gives it, its text, and what is stored now of who made it."""
    return store.query(
        f"""
        SELECT json_build_object(
            'key', c.key,
            'name', c.props -> 'minister_name',
            'role', c.props -> 'minister_role',
            'ministry_name', c.props -> 'ministry_name',
            'text', c.props -> 'text',
            'date', c.props -> 'made_on',
            'props', {_keep("c.props", "member_key", "post", "ministry", "cabinet")}
        )
        FROM commitments c
        WHERE %(ids)s::text[] IS NULL OR c.id = ANY(%(ids)s::text[])
        ORDER BY c.key COLLATE "C"
        """,
        {"ids": ids},
    )


# The first signature of the earliest document of a dossier (directly or through a case)
# that a Kamerlid or a bewindspersoon signed first. The date of a paper is that of its
# document; an AUTHORED edge to a node of another collection reads it from that node.
_FIRST_SIGNATURES_SQL = f"""
WITH papers AS (
    SELECT p.to_id AS dossier_id, p.from_id AS paper_id
    FROM edges p
    WHERE p.relation = %(part_of)s AND p.to_collection = '{COLLECTION_DOSSIERS}'
      AND p.from_collection <> '{COLLECTION_CASES}' /* papers */
    UNION
    SELECT c.to_id, p.from_id
    FROM edges c
    JOIN edges p ON p.to_id = c.from_id AND p.relation = %(part_of)s
    WHERE c.relation = %(part_of)s AND c.to_collection = '{COLLECTION_DOSSIERS}'
      AND c.from_collection = '{COLLECTION_CASES}' /* cases */
),
signatures AS (
    SELECT papers.dossier_id, papers.paper_id, a.key, a.from_id, a.doc -> 'meta' AS meta,
           dated.date
    FROM papers
    JOIN edges a ON a.to_id = papers.paper_id AND a.relation = %(authored)s
    -- the date read once per signature, not once for each place that names it
    CROSS JOIN LATERAL (
        SELECT CASE WHEN a.to_collection = '{COLLECTION_DOCUMENTS}'
                    THEN (SELECT d.date FROM documents d WHERE d.id = a.to_id)
                    ELSE (SELECT lg_str(n.props -> 'date') FROM nodes n WHERE n.id = a.to_id)
               END AS date
        OFFSET 0
    ) dated
    WHERE lg_str(a.doc -> 'meta' -> 'role') = %(first_role)s
      AND lg_str(a.doc -> 'meta' -> 'capacity') = ANY(%(capacities)s)
),
firsts AS (
    SELECT DISTINCT ON (dossier_id) dossier_id, json_build_object(
        'date', date,
        'member', split_part(from_id, '/', 2),
        'capacity', meta -> 'capacity',
        'function', meta -> 'function',
        'paper', paper_id
    ) AS first
    FROM signatures
    WHERE date IS NOT NULL
    ORDER BY dossier_id, date ASC, paper_id ASC, key ASC
)
SELECT json_build_object(
    'key', dossier.key,
    'first', firsts.first,
    'props', {_keep("dossier.props", "ministry", "initiative", "cabinet", "first_signed")}
)
FROM dossiers dossier
LEFT JOIN firsts ON firsts.dossier_id = dossier.id /* dossiers */
ORDER BY dossier.key COLLATE "C"
"""
# The same for the dossiers of ``%(ids)s`` alone: their papers, by index.
_ONLY_SOME = {
    " /* papers */": " AND p.to_id = ANY(%(ids)s::text[])",
    " /* cases */": " AND c.to_id = ANY(%(ids)s::text[])",
    " /* dossiers */": " WHERE dossier.id = ANY(%(ids)s::text[])",
}


def dossier_first_signatures(
    store: Store, ids: list[str] | None = None
) -> Iterator[dict[str, Any]]:
    """``{key, first, props}`` of every dossier, or of those with an ``_id`` in *ids*:
    ``first`` the first signature of its earliest document signed first by a Kamerlid or
    a bewindspersoon (``{date, member, capacity, function}``, null when there is none),
    ``props`` what is stored now.

    With ``hash_joins``: the planner takes the first signatures (a condition on ``meta``)
    for a few dozen rows where there are a hundred thousand, and loops over them for every
    paper; on the server that ran for hours. A few dossiers are read by index instead."""
    some = ids is not None
    statement = _FIRST_SIGNATURES_SQL
    for marker, condition in _ONLY_SOME.items() if some else ():
        statement = statement.replace(marker, condition)
    return store.query(
        statement,
        {
            "part_of": RELATION_PART_OF,
            "authored": RELATION_AUTHORED,
            "first_role": ROLE_FIRST_SIGNATORY,
            "capacities": [CAPACITY_MEMBER, CAPACITY_GOVERNMENT],
            "ids": ids,
        },
        hash_joins=not some,
    )


# Of the dossiers *ids*, those whose first signature a window can have changed: the papers
# it touched (the nodes *seeds* of the records it fetched, and the papers of an AUTHORED edge
# written since *since*; a case is no paper, ``_FIRST_SIGNATURES_SQL``), walked up to their
# dossiers (directly or through a case), and of those the dossiers that keep no first
# signature yet, or whose touched paper is dated on or before the one kept, or is the one
# kept. A paper that comes later than the first, as almost every new one, changes nothing.
# The dossiers a touched paper may change are found once (``changed``), not again for each
# dossier: a window of tens of thousands of dossiers stays one pass.
_FIRST_MAY_CHANGE_SQL = f"""
WITH ids AS (
    SELECT DISTINCT unnest(%(ids)s::text[]) AS id
),
touched AS (
    SELECT unnest(%(seeds)s::text[]) AS paper_id
    UNION
    SELECT a.to_id FROM edges a
    WHERE a.relation = %(authored)s AND a.created_at >= %(since)s
      AND a.to_collection <> '{COLLECTION_CASES}'
),
up AS (
    SELECT e.to_id AS dossier_id, t.paper_id
    FROM touched t
    JOIN edges e ON e.from_id = t.paper_id AND e.relation = %(part_of)s
     AND e.to_collection = '{COLLECTION_DOSSIERS}'
    UNION
    SELECT c.to_id, t.paper_id
    FROM touched t
    JOIN edges e ON e.from_id = t.paper_id AND e.relation = %(part_of)s
     AND e.to_collection = '{COLLECTION_CASES}'
    JOIN edges c ON c.from_id = e.to_id AND c.relation = %(part_of)s
     AND c.to_collection = '{COLLECTION_DOSSIERS}'
),
dated AS (
    SELECT up.dossier_id, up.paper_id,
           CASE WHEN split_part(up.paper_id, '/', 1) = '{COLLECTION_DOCUMENTS}'
                THEN (SELECT d.date FROM documents d WHERE d.id = up.paper_id)
                ELSE (SELECT lg_str(n.props -> 'date') FROM nodes n WHERE n.id = up.paper_id)
           END AS date
    FROM up
    JOIN ids ON ids.id = up.dossier_id
),
changed AS (
    SELECT DISTINCT t.dossier_id
    FROM dated t
    JOIN {COLLECTION_DOSSIERS} ds ON ds.id = t.dossier_id
    WHERE t.paper_id = lg_str(ds.props -> 'first_signed' -> 'paper')
       OR t.date <= lg_str(ds.props -> 'first_signed' -> 'date')
)
SELECT ds.id
FROM {COLLECTION_DOSSIERS} ds
JOIN ids ON ids.id = ds.id
LEFT JOIN changed ON changed.dossier_id = ds.id
WHERE NOT lg_truthy(ds.props -> 'first_signed') OR changed.dossier_id IS NOT NULL
ORDER BY ds.key COLLATE "C"
"""


def dossiers_whose_first_may_change(
    store: Store, ids: list[str], seeds: list[str], since_iso: str
) -> list[str]:
    """The ``_id`` of the dossiers among *ids* whose first signature a window can have
    changed (see ``_FIRST_MAY_CHANGE_SQL``): the only ones ``semantic tk-government
    --touched-since`` reads the papers of; the others keep what they have."""
    return list(
        store.query(
            _FIRST_MAY_CHANGE_SQL, first_may_change_params(ids, seeds, since_iso)
        )
    )


def first_may_change_params(
    ids: list[str], seeds: list[str], since_iso: str
) -> dict[str, Any]:
    """The parameters of ``_FIRST_MAY_CHANGE_SQL``."""
    return {
        "ids": ids,
        "seeds": seeds,
        "since": since_iso,
        "authored": RELATION_AUTHORED,
        "part_of": RELATION_PART_OF,
    }
