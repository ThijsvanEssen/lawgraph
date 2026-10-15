"""What a member and a faction answer alike: the laws they change most and the dossiers they
authored in."""

from __future__ import annotations

from typing import Any, get_args

from lawgraph.config.constants import (
    CHANGE_RELATIONS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_MEMBERS,
    RELATION_AUTHORED,
    RELATION_MEMBER_OF,
    RELATION_PART_OF,
)
from lawgraph.core.models import parse_node_id
from lawgraph.core.tk_records.actors import SigningCapacity
from lawgraph.db import GraphStore
from lawgraph.db._rows import node_doc
from lawgraph.db.queries._json_sql import array_or_empty
from lawgraph.db.queries._lists import page_of, paged
from lawgraph.db.queries._parliament_sql import IN_MEMBERSHIP, NODE


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
            "changes": list(CHANGE_RELATIONS),
        },
    )
    return list(rows)


def _distinct(field: str, condition: str) -> str:
    """SQL: the distinct values of *field* of the meta of the rows ``r`` that meet
    *condition*, in order."""
    value = f"r.meta ->> '{field}'"
    return (
        f"coalesce(array_agg(DISTINCT {value} ORDER BY {value} ASC NULLS FIRST)"
        f" FILTER (WHERE {value} {condition}), '{{}}')"
    )


# The dossiers of the papers a faction's members signed, from ``lg_authored``: of each member
# who sat in it its periods in it, read once, and the papers it signed within one of them,
# by the day of the paper, each with its dossiers.
_FACTION_FOUND = f"""
        seats AS (
            SELECT seat.from_id AS member_id, array_agg(f.period) AS periods
            FROM {COLLECTION_EDGES} seat
            JOIN {COLLECTION_MEMBERS} m ON m.id = seat.from_id
            CROSS JOIN LATERAL json_array_elements(
                {array_or_empty("m.props -> 'faction_memberships'")}
            ) AS f(period)
            WHERE seat.to_id = %(actor_id)s AND seat.relation = %(member_of)s
              AND f.period ->> 'faction_id' = %(actor_id)s
            GROUP BY seat.from_id
        ),
        found AS (
            SELECT k.dossier_id, a.document_id, a.meta
            FROM seats s
            JOIN lg_authored a ON a.member_id = s.member_id
            CROSS JOIN LATERAL (SELECT a.date) d
            CROSS JOIN LATERAL unnest(a.dossiers) AS k(dossier_id)
            WHERE d.date IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM unnest(s.periods) AS f(period) WHERE {IN_MEMBERSHIP}
              )
        ),
"""
# The dossiers of the papers a member signed, from ``lg_authored``: a range of its index.
_AUTHORED_FOUND = """
        found AS (
            SELECT d.dossier_id, a.document_id, a.meta
            FROM lg_authored a
            CROSS JOIN LATERAL unnest(a.dossiers) AS d(dossier_id)
            WHERE a.member_id = %(actor_id)s
        ),
"""


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
    is_faction = parse_node_id(actor_id)[0] == COLLECTION_FACTIONS
    found = _FACTION_FOUND if is_faction else _AUTHORED_FOUND
    rows = store.query(
        f"""
        WITH
{found}        grouped AS (
            SELECT {NODE.format(t="d")}, d.opened_on,
                   {_distinct("role", "<> ''")} AS roles,
                   {_distinct("function", "<> ''")} AS functions,
                   {_distinct("capacity", "= ANY(%(capacities)s)")} AS capacities,
                   count(DISTINCT r.document_id)::int AS document_count
            FROM found r JOIN {COLLECTION_DOSSIERS} d ON d.id = r.dossier_id
            GROUP BY d.id
        )
        {paged("grouped", page_of("grouped", "opened_on DESC NULLS LAST, key ASC"))}
        """,
        {
            "actor_id": actor_id,
            "limit": limit,
            "offset": offset,
            "member_of": RELATION_MEMBER_OF,
            # a capacity the source leaves empty or names otherwise is none of them
            "capacities": list(get_args(SigningCapacity)),
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
