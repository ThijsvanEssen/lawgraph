"""``lg_unlinked_references``: per node a step read the references of, how many its text
makes that the step recognized and could not link (``core.completeness.references_part``).
"""

from __future__ import annotations

import json

from lawgraph.core.batching import chunked
from lawgraph.db.counting import Store
from lawgraph.db.queries._chunks import CHUNK
from lawgraph.db.schema import UNLINKED_TABLE

_KEEP_SQL = f"""
INSERT INTO {UNLINKED_TABLE} (id, step, count)
SELECT r.id, %(step)s, r.count
FROM json_to_recordset(%(rows)s::json) AS r(id text, count integer)
ON CONFLICT (id) DO UPDATE SET step = EXCLUDED.step, count = EXCLUDED.count
WHERE ({UNLINKED_TABLE}.step, {UNLINKED_TABLE}.count)
      IS DISTINCT FROM (EXCLUDED.step, EXCLUDED.count)
RETURNING 1
"""


def keep_unlinked(
    store: Store, step: str, counts: dict[str, int], *, whole: bool
) -> int:
    """Keep *counts* (node id -> how many references it could not link) of *step*; a row
    that holds its count already is left, so a run that finds what the last one found
    leaves the data version. *whole*: the run read every node of the step, so a row of the
    step for a node it did not read (gone, or without references now) goes. How many rows
    were written or removed."""
    written = 0
    for chunk in chunked(sorted(counts.items()), CHUNK):
        rows = [{"id": node, "count": count} for node, count in chunk]
        written += len(
            store.execute(_KEEP_SQL, {"step": step, "rows": json.dumps(rows)})
        )
    if whole:
        kept = store.query(
            f"SELECT id FROM {UNLINKED_TABLE} WHERE step = %(step)s", {"step": step}
        )
        gone = [node for node in kept if node not in counts]
        for ids in chunked(gone, CHUNK):
            written += len(
                store.execute(
                    f"DELETE FROM {UNLINKED_TABLE} WHERE id = ANY(%(ids)s::text[])"
                    " RETURNING 1",
                    {"ids": ids},
                )
            )
    return written


_COUNT_SQL = f"SELECT count FROM {UNLINKED_TABLE} WHERE id = %(id)s"


def unlinked_count(store: Store, node: str) -> int | None:
    """How many references the text of *node* makes that its step could not link; None
    when no step read it."""
    rows = store.query(_COUNT_SQL, {"id": node})
    return next(iter(rows), None)
