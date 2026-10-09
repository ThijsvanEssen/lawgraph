"""``lg_document_light``: what the signals of a dossier read of a paper, without its text
(``schema.document_light``).

The triggers on ``documents`` keep it with every write; ``fill_document_light`` adds the
documents written before them, a batch of ids at a time.
"""

from __future__ import annotations

from lawgraph.db import GraphStore

# The documents of one statement: on the full graph a batch reads their props, text and all.
BATCH = 20_000

_FILL = """
WITH batch AS (
    SELECT d.id FROM documents d
    WHERE d.id > %(after)s
      AND (%(every)s OR NOT EXISTS (SELECT 1 FROM lg_document_light l WHERE l.id = d.id))
    ORDER BY d.id
    LIMIT %(batch)s
),
kept AS (
    INSERT INTO lg_document_light (id, props)
    SELECT d.id, coalesce(lg_document_light_props(d.props), '{}'::json)
    FROM batch b JOIN documents d ON d.id = b.id
    ON CONFLICT (id) DO UPDATE SET props = EXCLUDED.props
    RETURNING 1
)
SELECT (SELECT max(id) FROM batch) AS last, (SELECT count(*) FROM kept)::int AS n
"""


def fill_document_light(store: GraphStore, *, every: bool = False) -> int:
    """Keep the light props of every document that has none (with *every*: of all of them,
    after ``DOCUMENT_LIGHT_PROPS`` changed); the documents kept."""
    after, kept = "", 0
    while True:
        (row,) = store.execute(_FILL, {"after": after, "every": every, "batch": BATCH})
        if row["last"] is None:
            return kept
        after, kept = row["last"], kept + row["n"]
