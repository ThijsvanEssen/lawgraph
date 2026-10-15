"""``lg_authored``: every document a member signed with what the edge says of the signature, the
dossiers of the document, its date and the capacity signed in (``schema.member_authored``).

The triggers on ``edges``, ``documents`` and ``cases`` keep it with every write;
``fill_authored`` adds the signatures written before them, a batch of members at a time;
``get_signed`` reads the newest a member signed.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_MEMBERS, RELATION_AUTHORED
from lawgraph.db import GraphStore
from lawgraph.db._rows import canvas_edge_doc, canvas_props, light_node_doc
from lawgraph.db.queries.nodes import NeighborEntry
from lawgraph.db.schema import node_of

# The members of one statement, with every document they signed.
BATCH = 200

_FILL = f"""
WITH batch AS (
    SELECT m.id FROM {COLLECTION_MEMBERS} m
    WHERE m.id > %(after)s
    ORDER BY m.id
    LIMIT %(batch)s
),
kept AS (
    INSERT INTO lg_authored
        (edge_key, member_id, document_id, meta, dossiers, date, capacity)
    SELECT a.key, a.from_id, a.to_id,
           json_build_object('role', a.doc -> 'meta' -> 'role',
                             'function', a.doc -> 'meta' -> 'function',
                             'capacity', a.doc -> 'meta' -> 'capacity'),
           lg_dossiers_of(a.to_id), lg_signed_date(a.to_id),
           lg_str(a.doc -> 'meta' -> 'capacity')
    FROM batch b
    JOIN edges a ON a.from_id = b.id AND a.relation = '{RELATION_AUTHORED}'
    WHERE %(every)s OR NOT EXISTS (SELECT 1 FROM lg_authored x WHERE x.edge_key = a.key)
    ON CONFLICT (edge_key) DO UPDATE SET
        member_id = EXCLUDED.member_id, document_id = EXCLUDED.document_id,
        meta = EXCLUDED.meta, dossiers = EXCLUDED.dossiers, date = EXCLUDED.date,
        capacity = EXCLUDED.capacity
    RETURNING 1
)
SELECT (SELECT max(id) FROM batch) AS last, (SELECT count(*) FROM kept)::int AS n
"""


def fill_authored(store: GraphStore, *, every: bool = False) -> int:
    """Keep every signature of a member the table lacks (with *every*: all of them again);
    the signatures kept."""
    after, kept = "", 0
    while True:
        (row,) = store.execute(_FILL, {"after": after, "every": every, "batch": BATCH})
        if row["last"] is None:
            return kept
        after, kept = row["last"], kept + row["n"]


_SIGNED = f"""
SELECT a.edge_key, e.from_id, e.to_id, e.doc,
       n.id, n.key, n.type, n.labels, {canvas_props("n")} AS props
FROM (
    SELECT edge_key, date FROM lg_authored
    WHERE member_id = %(member)s
    ORDER BY date DESC NULLS LAST, edge_key
    LIMIT %(limit)s OFFSET %(offset)s
) a
JOIN edges e ON e.key = a.edge_key
CROSS JOIN {node_of("e.to_id", "e.to_collection")} n
ORDER BY a.date DESC NULLS LAST, a.edge_key
"""


def get_signed(
    store: GraphStore, member_id: str, limit: int, offset: int
) -> tuple[int, list[NeighborEntry]]:
    """Every paper *member_id* signed (``total``) and a page of them, the newest first by
    the date of the paper (``lg_authored.date``; an undated one last): each with its
    ``AUTHORED`` edge, as the canvas of the explorer reads a neighbour
    (``_rows.CANVAS_PROPS``). From ``lg_authored`` through its index of members: a few
    thousand rows of a minister sorted, not the edges and dates of every paper."""
    bind: dict[str, Any] = {"member": member_id, "limit": limit, "offset": offset}
    total = next(
        iter(
            store.query(
                "SELECT count(*)::int FROM lg_authored WHERE member_id = %(member)s",
                bind,
            )
        ),
        0,
    )
    entries = [
        NeighborEntry(
            doc=light_node_doc(row),
            edge=canvas_edge_doc({**row, "key": row["edge_key"]}, False),
            direction="outbound",
        )
        for row in store.query(_SIGNED, bind)
    ]
    return int(total), entries
