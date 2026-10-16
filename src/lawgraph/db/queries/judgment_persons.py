"""``lg_judgment_persons``: the persons a judgment names (``schema.judgment_persons``).

The trigger on ``judgments`` keeps it with every write of a judgment's props;
``fill_judgment_persons`` adds the judgments written before it, a batch of ids at a time,
by the same rows (``lg_judgment_person_rows``, ``lg_person_words``).
"""

from __future__ import annotations

from lawgraph.db import GraphStore

# The judgments of one statement: on the full graph a batch reads their props, text and all.
BATCH = 20_000

_BATCH = """
SELECT j.id FROM judgments j
WHERE j.id > %(after)s
  AND (%(every)s OR NOT EXISTS (SELECT 1 FROM lg_judgment_persons p WHERE p.id = j.id))
ORDER BY j.id
LIMIT %(batch)s
"""

_FILL = """
WITH kept AS (
    INSERT INTO lg_judgment_persons (id, n, name, role, party, date_eff, words)
    SELECT j.id, f.n, f.name, f.role, f.party, j.date_eff, lg_person_words(f.name)
    FROM judgments j, lg_judgment_person_rows(j.props) f
    WHERE j.id = ANY(%(ids)s::text[])
    ON CONFLICT (id, n) DO NOTHING
    RETURNING id
)
SELECT count(DISTINCT id)::int AS n FROM kept
"""


def fill_judgment_persons(store: GraphStore, *, every: bool = False) -> int:
    """Keep the persons of every judgment that has none (with *every*: of all of them,
    after ``lg_judgment_person_rows`` changed); the judgments that name one."""
    after, kept = "", 0
    while True:
        ids: list[str] = list(
            store.query(_BATCH, {"after": after, "every": every, "batch": BATCH})
        )
        if not ids:
            return kept
        if every:
            store.execute(
                "DELETE FROM lg_judgment_persons WHERE id = ANY(%(ids)s::text[])",
                {"ids": ids},
            )
        (n,) = store.execute(_FILL, {"ids": ids})
        after, kept = ids[-1], kept + n
