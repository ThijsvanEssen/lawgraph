"""The children a group starts a path from (``GET /api/paths?expand=members``).

A law is its articles and annexes, a faction or a committee its members, a cabinet its
bewindspersonen, a dossier its cases and papers and the papers of its cases: each with the
edge that makes it a child (``PART_OF``, ``MEMBER_OF``, ``SERVED_IN``). Of each group the
most telling first, up to a cap; the total says how many there are.
"""

from __future__ import annotations

from dataclasses import dataclass

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLES,
    COLLECTION_CABINETS,
    COLLECTION_CASES,
    COLLECTION_COMMITTEES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_MEMBERS,
    RELATION_MEMBER_OF,
    RELATION_PART_OF,
    RELATION_SERVED_IN,
)
from lawgraph.db import GraphStore


@dataclass(frozen=True)
class Child:
    """A child of a group: its id, the node it is a child of (the group, or a case of a
    dossier) and the edge between them."""

    id: str
    parent: str
    edge: str


@dataclass(frozen=True)
class Children:
    """The children of a group a path starts from, and how many it has."""

    kept: tuple[Child, ...]
    total: int


# Per kind of group: its children (``child``, ``parent``, ``edge``), each numbered ``n`` in
# the order of the most telling first.
_MEMBERS = f"""
    SELECT m.child, m.parent, m.edge,
           row_number() OVER (
               ORDER BY m.seated DESC NULLS LAST, m.since DESC NULLS LAST,
                        m.child NULLS LAST
           ) AS n
    FROM (
        -- each member once, by the membership seated now, else the latest
        SELECT DISTINCT ON (e.from_id) e.from_id AS child, e.to_id AS parent,
               e.key AS edge,
               coalesce(json_typeof(e.doc -> 'meta' -> 'to_date'), 'null') = 'null'
                   AS seated,
               lg_str(e.doc -> 'meta' -> 'from_date') AS since
        FROM edges e
        WHERE e.to_id = %(id)s AND e.relation = '{RELATION_MEMBER_OF}'
          AND e.from_collection = '{COLLECTION_MEMBERS}'
        ORDER BY e.from_id NULLS LAST, seated DESC NULLS LAST, since DESC NULLS LAST,
                 e.key NULLS LAST
    ) m
"""
_GROUPS: dict[str, str] = {
    # a law: its articles, the most cited first, and its annexes
    COLLECTION_INSTRUMENTS: f"""
        SELECT e.from_id AS child, e.to_id AS parent, e.key AS edge,
               row_number() OVER (
                   ORDER BY a.inbound_citation_count DESC NULLS LAST, e.from_id NULLS LAST
               ) AS n
        FROM edges e
        LEFT JOIN {COLLECTION_ARTICLES} a ON a.id = e.from_id
        WHERE e.to_id = %(id)s AND e.relation = '{RELATION_PART_OF}'
          AND e.from_collection IN ('{COLLECTION_ARTICLES}', '{COLLECTION_ANNEXES}')
    """,
    # a faction, a committee: its members, those seated now first, then the latest
    COLLECTION_FACTIONS: _MEMBERS,
    COLLECTION_COMMITTEES: _MEMBERS,
    # a cabinet: its bewindspersonen
    COLLECTION_CABINETS: f"""
        SELECT e.from_id AS child, e.to_id AS parent, e.key AS edge,
               row_number() OVER (ORDER BY e.from_id NULLS LAST) AS n
        FROM edges e
        WHERE e.to_id = %(id)s AND e.relation = '{RELATION_SERVED_IN}'
          AND e.from_collection = '{COLLECTION_MEMBERS}'
    """,
    # a dossier: its own cases and papers, the newest first, then the papers of its cases
    COLLECTION_DOSSIERS: f"""
        WITH own AS (
            SELECT e.from_id AS child, e.to_id AS parent, e.key AS edge, 0 AS tier
            FROM edges e
            WHERE e.to_id = %(id)s AND e.relation = '{RELATION_PART_OF}'
              AND e.from_collection IN ('{COLLECTION_DOCUMENTS}', '{COLLECTION_CASES}')
        ),
        every AS (
            SELECT * FROM own
            UNION ALL
            SELECT d.from_id, d.to_id, d.key, 1
            FROM own o
            JOIN edges d ON d.to_id = o.child AND d.relation = '{RELATION_PART_OF}'
                AND d.from_collection = '{COLLECTION_DOCUMENTS}'
            WHERE starts_with(o.child, '{COLLECTION_CASES}/')
        )
        SELECT every.child, every.parent, every.edge,
               row_number() OVER (
                   ORDER BY every.tier NULLS LAST, doc.date DESC NULLS LAST,
                            every.child NULLS LAST
               ) AS n
        FROM every
        LEFT JOIN {COLLECTION_DOCUMENTS} doc ON doc.id = every.child
    """,
}

_KEPT = """
WITH c AS MATERIALIZED ({children})
SELECT (SELECT count(*)::int FROM c) AS total,
       coalesce((
           SELECT json_agg(json_build_array(c.child, c.parent, c.edge) ORDER BY c.n)
           FROM c WHERE c.n <= %(cap)s
       ), '[]'::json) AS kept
"""


def is_group(node_id: str) -> bool:
    """Whether *node_id* is a group whose children a path may start from."""
    return node_id.split("/", 1)[0] in _GROUPS


def children_of(store: GraphStore, group: str, cap: int) -> Children:
    """The children of *group*, the *cap* most telling, and how many it has. A paper of a
    case of a dossier is kept only with its case."""
    statement = _KEPT.format(children=_GROUPS[group.split("/", 1)[0]])
    (row,) = store.query(statement, {"id": group, "cap": cap})
    kept: list[Child] = []
    reached = {group}
    for child, parent, edge in row["kept"]:
        if parent in reached and child not in reached:
            kept.append(Child(child, parent, edge))
            reached.add(child)
    return Children(tuple(kept), row["total"])
