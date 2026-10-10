"""``lg_led``: every activity and case a committee leads with its date and the dossiers it is
about (``schema.committee_led``).

The triggers on ``edges``, ``activities`` and ``cases`` keep it with every write;
``fill_led`` adds what was led before them, a batch of committees at a time, and notes in
``lg_led_state`` that the table is whole, which the pages of a committee wait for.
"""

from __future__ import annotations

from lawgraph.config.constants import COLLECTION_COMMITTEES, RELATION_LED_BY
from lawgraph.db import GraphStore
from lawgraph.db.version_cache import once_true

# The committees of one statement, with everything they lead.
BATCH = 20

_FILL = f"""
WITH batch AS (
    SELECT c.id FROM {COLLECTION_COMMITTEES} c
    WHERE c.id > %(after)s
    ORDER BY c.id
    LIMIT %(batch)s
),
kept AS (
    INSERT INTO lg_led (edge_key, committee_id, item_id, item_collection, date, dossiers)
    SELECT e.key, e.to_id, e.from_id, e.from_collection,
           lg_led_date(e.from_id), lg_led_dossiers(e.from_id)
    FROM batch b
    JOIN edges e ON e.to_id = b.id AND e.relation = '{RELATION_LED_BY}'
    WHERE %(every)s OR NOT EXISTS (SELECT 1 FROM lg_led x WHERE x.edge_key = e.key)
    ON CONFLICT (edge_key) DO UPDATE SET
        committee_id = EXCLUDED.committee_id, item_id = EXCLUDED.item_id,
        item_collection = EXCLUDED.item_collection, date = EXCLUDED.date,
        dossiers = EXCLUDED.dossiers
    RETURNING 1
)
SELECT (SELECT max(id) FROM batch) AS last, (SELECT count(*) FROM kept)::int AS n
"""

_FILLED = """
INSERT INTO lg_led_state (id, filled_at) VALUES (true, now())
ON CONFLICT (id) DO UPDATE SET filled_at = EXCLUDED.filled_at
"""


def fill_led(store: GraphStore, *, every: bool = False) -> int:
    """Keep every item a committee leads that the table lacks (with *every*: all of them
    again), then note that it is whole; the items kept."""
    after, kept = "", 0
    while True:
        (row,) = store.execute(_FILL, {"after": after, "every": every, "batch": BATCH})
        if row["last"] is None:
            store.execute(_FILLED)
            return kept
        after, kept = row["last"], kept + row["n"]


def is_filled(store: GraphStore) -> bool:
    """Whether the table holds every item a committee leads (filled once since the
    triggers); once it does, known without asking (``once_true``)."""

    def check() -> bool:
        found = store.query("SELECT 1 FROM lg_led_state WHERE id")
        return next(iter(found), None) is not None

    return once_true(store, "lg_led filled", check)
