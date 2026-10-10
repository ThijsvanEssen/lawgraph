"""``lg_faction_votes``: every vote of a faction with the date, key and kind of vote of its
decision (``schema.faction_votes``).

The triggers on ``edges`` and ``decisions`` keep it with every write; ``fill_faction_votes``
adds the votes written before them, a batch of decisions at a time, and notes in
``lg_faction_votes_state`` that the table is whole, which ``get_member_votes`` waits for.
"""

from __future__ import annotations

from lawgraph.config.constants import COLLECTION_FACTIONS, RELATION_VOTED
from lawgraph.db import GraphStore

# The decisions of one statement, each with the votes of its factions.
BATCH = 5_000

_FILL = f"""
WITH batch AS (
    SELECT d.id FROM decisions d
    WHERE d.id > %(after)s
    ORDER BY d.id
    LIMIT %(batch)s
),
kept AS (
    INSERT INTO lg_faction_votes (edge_key, faction_id, decision_id, date, decision_key, vote_kind)
    SELECT e.key, e.from_id, e.to_id, d.date, d.key, lg_str(d.props -> 'vote_kind')
    FROM batch b
    JOIN decisions d ON d.id = b.id
    JOIN edges e ON e.to_id = d.id AND e.relation = '{RELATION_VOTED}'
     AND e.from_collection = '{COLLECTION_FACTIONS}'
    WHERE %(every)s OR NOT EXISTS (SELECT 1 FROM lg_faction_votes v WHERE v.edge_key = e.key)
    ON CONFLICT (edge_key) DO UPDATE SET
        faction_id = EXCLUDED.faction_id, decision_id = EXCLUDED.decision_id,
        date = EXCLUDED.date, decision_key = EXCLUDED.decision_key,
        vote_kind = EXCLUDED.vote_kind
    RETURNING 1
)
SELECT (SELECT max(id) FROM batch) AS last, (SELECT count(*) FROM kept)::int AS n
"""

_FILLED = """
INSERT INTO lg_faction_votes_state (id, filled_at) VALUES (true, now())
ON CONFLICT (id) DO UPDATE SET filled_at = EXCLUDED.filled_at
"""


def fill_faction_votes(store: GraphStore, *, every: bool = False) -> int:
    """Keep every vote of a faction the table lacks (with *every*: all of them again), then
    note that it is whole; the votes kept."""
    after, kept = "", 0
    while True:
        (row,) = store.execute(_FILL, {"after": after, "every": every, "batch": BATCH})
        if row["last"] is None:
            store.execute(_FILLED)
            return kept
        after, kept = row["last"], kept + row["n"]


def is_filled(store: GraphStore) -> bool:
    """Whether the table holds every vote of a faction (filled once since the triggers)."""
    return (
        next(iter(store.query("SELECT 1 FROM lg_faction_votes_state WHERE id")), None)
        is not None
    )
