"""``lg_judgment_light``: a judgment as a neighbour, without its text (``schema.judgment_light``).

The triggers on ``judgments`` keep it with every write; ``fill_judgment_light`` adds the
judgments written before them, a batch of ids at a time.
"""

from __future__ import annotations

from lawgraph.db import GraphStore

# The judgments of one statement: on the full graph a batch reads their props, text and all.
BATCH = 20_000

_FILL = """
WITH batch AS (
    SELECT j.id FROM judgments j
    WHERE j.id > %(after)s
      AND (%(every)s OR NOT EXISTS (SELECT 1 FROM lg_judgment_light l WHERE l.id = j.id))
    ORDER BY j.id
    LIMIT %(batch)s
),
kept AS (
    INSERT INTO lg_judgment_light (id, props)
    SELECT j.id, lg_judgment_light_props(j.props)
    FROM batch b JOIN judgments j ON j.id = b.id
    ON CONFLICT (id) DO UPDATE SET props = EXCLUDED.props
    RETURNING 1
)
SELECT (SELECT max(id) FROM batch) AS last, (SELECT count(*) FROM kept)::int AS n
"""


def fill_judgment_light(store: GraphStore, *, every: bool = False) -> int:
    """Keep the light props of every judgment that has none (with *every*: of all of them,
    after ``JUDGMENT_LIGHT_PROPS`` changed); the judgments kept."""
    after, kept = "", 0
    while True:
        (row,) = store.execute(_FILL, {"after": after, "every": every, "batch": BATCH})
        if row["last"] is None:
            return kept
        after, kept = row["last"], kept + row["n"]


# How a judgment ended, what a conclusion proposes and what the ECHR found per article
# (``core/judgment_outcome.py``, ``core/echr_findings.py``), as a row of a list shows them.
OUTCOME_KEYS = (
    "outcome",
    "outcome_text",
    "conclusion_outcome",
    "conclusion_outcome_text",
    "echr_findings",
)


def outcome_pairs(light: str) -> str:
    """SQL: the ``OUTCOME_KEYS`` as pairs of a ``json_build_object``, read from the props
    *light* of the row of ``lg_judgment_light`` of a judgment (null without one)."""
    return ", ".join(f"'{key}', {light} -> '{key}'" for key in OUTCOME_KEYS)
