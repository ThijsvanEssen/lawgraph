"""``lg_authored``: every paper a member signed with what the edge says of the signature, the
dossiers of the paper, its date and the capacity signed in (``schema.member_authored``).

The triggers on ``edges``, ``documents`` and ``cases`` keep it with every write;
``fill_authored`` adds the signatures written before them, a batch of members at a time.
"""

from __future__ import annotations

from lawgraph.config.constants import COLLECTION_MEMBERS, RELATION_AUTHORED
from lawgraph.db import GraphStore

# The members of one statement, with every paper they signed.
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
