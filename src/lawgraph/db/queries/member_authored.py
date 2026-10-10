"""``lg_authored``: every paper a member signed with what the edge says of the signature, the
dossiers of the paper and its date (``schema.member_authored``).

The triggers on ``edges``, ``documents`` and ``cases`` keep it with every write;
``fill_authored`` adds the signatures written before them, a batch of members at a time, and
notes in ``lg_authored_state`` that the table is whole, which ``get_actor_dossiers`` waits for;
``date_authored`` keeps the date and capacity of the signatures kept before those were, a
slice of members at a time, and notes in ``lg_authored_dated`` that every one has them, which
the counts of a cabinet wait for.
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

_FILLED = """
INSERT INTO lg_authored_state (id, filled_at) VALUES (true, now())
ON CONFLICT (id) DO UPDATE SET filled_at = EXCLUDED.filled_at
"""


def fill_authored(store: GraphStore, *, every: bool = False) -> int:
    """Keep every signature of a member the table lacks (with *every*: all of them again),
    then note that it is whole; the signatures kept."""
    after, kept = "", 0
    while True:
        (row,) = store.execute(_FILL, {"after": after, "every": every, "batch": BATCH})
        if row["last"] is None:
            store.execute(_FILLED)
            return kept
        after, kept = row["last"], kept + row["n"]


def is_filled(store: GraphStore) -> bool:
    """Whether the table holds every signature of a member (filled once since the
    triggers)."""
    found = store.query("SELECT 1 FROM lg_authored_state WHERE id")
    return next(iter(found), None) is not None


# The members of one slice of ``date_authored``: the dates and capacities of every signature
# they have, each date a probe of its paper or case.
_DATE = """
WITH slice AS (
    SELECT DISTINCT a.member_id FROM lg_authored a
    WHERE a.member_id > %(after)s
    ORDER BY a.member_id
    LIMIT %(limit)s
),
found AS (
    SELECT a.edge_key, lg_signed_date(a.document_id) AS date,
           lg_str(a.meta -> 'capacity') AS capacity
    FROM slice s JOIN lg_authored a ON a.member_id = s.member_id
),
dated AS (
    UPDATE lg_authored a SET date = f.date, capacity = f.capacity
    FROM found f
    WHERE a.edge_key = f.edge_key
      AND (a.date IS DISTINCT FROM f.date OR a.capacity IS DISTINCT FROM f.capacity)
    RETURNING 1
)
SELECT (SELECT max(member_id) FROM slice) AS last, (SELECT count(*) FROM dated)::int AS n
"""

_DATED = """
INSERT INTO lg_authored_dated (id, dated_at) VALUES (true, now())
ON CONFLICT (id) DO UPDATE SET dated_at = EXCLUDED.dated_at
"""


def date_authored(
    store: GraphStore, *, after: str = "", limit: int = BATCH
) -> tuple[str | None, int]:
    """Keep the date and capacity of the signatures of the next *limit* members past
    *after*: the last member of the slice (where the next goes on), None when none was
    left, and then note that every signature has them; and the signatures changed."""
    (row,) = store.execute(_DATE, {"after": after, "limit": limit})
    if row["last"] is None:
        store.execute(_DATED)
    return row["last"], row["n"]


def is_dated(store: GraphStore) -> bool:
    """Whether every signature has its date and capacity (dated once since the triggers)."""
    found = store.query("SELECT 1 FROM lg_authored_dated WHERE id")
    return next(iter(found), None) is not None
