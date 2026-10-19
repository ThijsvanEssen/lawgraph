"""``lg_faction_votes``: every vote of a faction with the date, key and kind of vote of its
decision (``schema.faction_votes``).

The triggers on ``edges`` and ``decisions`` keep it with every write; ``fill_faction_votes``
adds the votes written before them, a batch of decisions at a time.
"""

from __future__ import annotations

from lawgraph.config.constants import COLLECTION_FACTIONS, RELATION_VOTED
from lawgraph.db import GraphStore
from lawgraph.db.schema import faction_vote_columns

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
    SELECT {faction_vote_columns("e", "d")}
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


def fill_faction_votes(store: GraphStore, *, every: bool = False) -> int:
    """Keep every vote of a faction the table lacks (with *every*: all of them again); the
    votes kept."""
    after, kept = "", 0
    while True:
        (row,) = store.execute(_FILL, {"after": after, "every": every, "batch": BATCH})
        if row["last"] is None:
            return kept
        after, kept = row["last"], kept + row["n"]
