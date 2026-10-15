"""The names of the instruments: their abbreviations (``code_alias_rows``), and
``lg_instrument_names``, the title and short title of an instrument without its props
(``schema.instrument_names``).

The triggers on ``instruments`` keep ``lg_instrument_names`` with every write;
``fill_instrument_names`` adds the instruments written before them, a batch of ids at a time.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.counting import Store


# The abbreviations of the instruments: ``core.aliases.code_aliases`` reads them, for the
# search and for the semantic phase.
def code_alias_rows(store: Store) -> Iterator[dict[str, Any]]:
    """``{short_title, aliases, bwb_id, celex, citation_title, title}`` of the instruments
    with a BWB id or a CELEX number, in the order of their keys."""
    return store.query(
        """
        SELECT props -> 'short_title' AS short_title, props -> 'aliases' AS aliases,
               props -> 'bwb_id' AS bwb_id, props -> 'celex' AS celex,
               props -> 'citation_title' AS citation_title, props -> 'title' AS title
        FROM instruments
        WHERE bwb_id IS NOT NULL OR celex IS NOT NULL
        ORDER BY key
        """
    )


# The instruments of one statement: on the full graph a batch reads their props whole.
BATCH = 20_000

_FILL = """
WITH batch AS (
    SELECT i.id FROM instruments i
    WHERE i.id > %(after)s
      AND (%(every)s OR NOT EXISTS (SELECT 1 FROM lg_instrument_names n WHERE n.id = i.id))
    ORDER BY i.id
    LIMIT %(batch)s
),
kept AS (
    INSERT INTO lg_instrument_names (id, title, short_title)
    SELECT i.id, coalesce(i.props -> 'title' #>> '{}', ''),
           coalesce(i.props -> 'short_title' #>> '{}', '')
    FROM batch b JOIN instruments i ON i.id = b.id
    ON CONFLICT (id) DO UPDATE
        SET title = EXCLUDED.title, short_title = EXCLUDED.short_title
    RETURNING 1
)
SELECT (SELECT max(id) FROM batch) AS last, (SELECT count(*) FROM kept)::int AS n
"""


def fill_instrument_names(store: GraphStore, *, every: bool = False) -> int:
    """Keep the names of every instrument that has none (with *every*: of all of them);
    the instruments kept."""
    after, kept = "", 0
    while True:
        (row,) = store.execute(_FILL, {"after": after, "every": every, "batch": BATCH})
        if row["last"] is None:
            return kept
        after, kept = row["last"], kept + row["n"]
