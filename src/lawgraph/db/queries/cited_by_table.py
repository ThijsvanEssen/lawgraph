"""``lg_cited_by``: every edge from a judgment into an article, with its passages and what
the citing judgment is sorted and counted on (``schema.article_cited_by``).

The triggers on ``edges`` and ``judgments`` keep it with every write; ``fill_cited_by`` adds
the edges written before them, a batch of judgments at a time (the edges of a judgment are
written together, so a batch reads few pages of the edges).
"""

from __future__ import annotations

from lawgraph.db import GraphStore
from lawgraph.db.schema import (
    CITED_BY_COLUMNS,
    CITED_BY_TABLE,
    cited_by_edges,
    cited_by_values,
)

# The judgments of one statement, with every edge from them into an article.
BATCH = 5_000

_FILL = f"""
WITH batch AS (
    SELECT j.id FROM judgments j
    WHERE j.id > %(after)s
    ORDER BY j.id
    LIMIT %(batch)s
),
kept AS (
    INSERT INTO {CITED_BY_TABLE} ({CITED_BY_COLUMNS})
    SELECT {cited_by_values("e", "j")}
    FROM batch b
    JOIN judgments j ON j.id = b.id
    JOIN edges e ON e.from_id = b.id AND {cited_by_edges("e")}
    WHERE %(every)s OR NOT EXISTS (SELECT 1 FROM {CITED_BY_TABLE} x WHERE x.edge_key = e.key)
    ON CONFLICT (edge_key) DO UPDATE SET
        article_id = EXCLUDED.article_id, judgment_id = EXCLUDED.judgment_id,
        mentions = EXCLUDED.mentions, leden = EXCLUDED.leden,
        date_eff = EXCLUDED.date_eff, ecli = EXCLUDED.ecli,
        court_code = EXCLUDED.court_code, tier = EXCLUDED.tier, cited = EXCLUDED.cited,
        areas = EXCLUDED.areas
    RETURNING 1
)
SELECT (SELECT max(id) FROM batch) AS last, (SELECT count(*) FROM kept)::int AS n
"""


def fill_cited_by(store: GraphStore, *, every: bool = False) -> int:
    """Keep every edge from a judgment into an article that the table lacks (with *every*:
    all of them again); the edges kept."""
    after, kept = "", 0
    while True:
        (row,) = store.execute(_FILL, {"after": after, "every": every, "batch": BATCH})
        if row["last"] is None:
            return kept
        after, kept = row["last"], kept + row["n"]
