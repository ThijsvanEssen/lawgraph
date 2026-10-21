"""``lg_unlinked_references``: per node a step read the references of, how many its text
makes that the step recognized and could not link; with the ``REFERS_TO`` edges of the node
that go to a stub, what ``core.completeness.references_part`` says of its references.
"""

from __future__ import annotations

import json

from lawgraph.config.constants import COLLECTION_EDGES, RELATION_REFERS_TO
from lawgraph.core.batching import chunked
from lawgraph.core.completeness import ReferenceCounts
from lawgraph.core.models import STUB_COLLECTIONS
from lawgraph.db.counting import Store
from lawgraph.db.queries._chunks import CHUNK
from lawgraph.db.schema import COLUMNS, UNLINKED_TABLE

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


def _stub(collection: str) -> str:
    """Whether a row ``t`` of *collection* is a stub: by its column where it has one, so
    the props (a judgment's whole text) are not read."""
    if any(column.name == "stub" for column in COLUMNS.get(collection, ())):
        return "t.stub"
    return "lg_bool(t.props -> 'stub')"


# per collection that takes stubs, the edges of the node that go to one: by the index of
# the edges from a node (from_id, relation, to_collection) and the key of the target
_TO_STUBS = " + ".join(
    f"""(SELECT count(*) FROM {COLLECTION_EDGES} e JOIN {name} t ON t.id = e.to_id
      WHERE e.from_id = u.id AND e.relation = '{RELATION_REFERS_TO}'
        AND e.to_collection = '{name}' AND {_stub(name)})"""
    for name in sorted(STUB_COLLECTIONS)
)
_COUNT_SQL = f"""
SELECT u.count AS unlinked, {_TO_STUBS} AS unloaded
FROM {UNLINKED_TABLE} u WHERE u.id = %(id)s
"""


def reference_counts(store: Store, node: str) -> ReferenceCounts | None:
    """Of the references the text of *node* makes: how many its step could not link, and
    how many of its ``REFERS_TO`` edges go to a stub; None when no step read it."""
    rows = store.query(_COUNT_SQL, {"id": node})
    row = next(iter(rows), None)
    return None if row is None else ReferenceCounts(row["unlinked"], row["unloaded"])
