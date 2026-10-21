"""``lg_unlinked_references``: per node a step read the references of, how many its text
makes that the step recognized and could not link (of a judgment with the LJNs it cites that
no judgment in the graph has, ``ljns``); with the ``REFERS_TO`` edges of the node that go to a
stub, what ``core.completeness.references_part`` says of its references. Of a
law of the Staatsblad and its articles the same, the count a prop of each
(``law_reference_counts``).
"""

from __future__ import annotations

import json

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    RELATION_REFERS_TO,
)
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


_KEEP_LJNS_SQL = f"""
UPDATE {UNLINKED_TABLE} u SET ljns = r.ljns
FROM json_to_recordset(%(rows)s::json) AS r(id text, ljns integer)
WHERE u.id = r.id AND u.ljns IS DISTINCT FROM r.ljns
RETURNING 1
"""


def keep_unlinked_ljns(store: Store, counts: dict[str, int]) -> int:
    """Keep *counts* (judgment id -> how many LJNs its text cites that no one judgment in the
    graph has) on the row of each judgment ``semantic rechtspraak`` read, null for none; a
    judgment without a row is left. How many rows changed."""
    written = 0
    for chunk in chunked(sorted(counts.items()), CHUNK):
        rows = [{"id": node, "ljns": count or None} for node, count in chunk]
        written += len(store.execute(_KEEP_LJNS_SQL, {"rows": json.dumps(rows)}))
    return written


def _stub(collection: str) -> str:
    """Whether a row ``t`` of *collection* is a stub: by its column where it has one, so
    the props (a judgment's whole text) are not read."""
    if any(column.name == "stub" for column in COLUMNS.get(collection, ())):
        return "t.stub"
    return "lg_bool(t.props -> 'stub')"


def _to_stubs(source: str) -> str:
    """SQL: how many ``REFERS_TO`` edges from the node *source* (an SQL expression of its
    id, or ``ANY`` of an array of ids) go to a stub: per collection that takes stubs, by
    the index of the edges from a node (from_id, relation, to_collection) and the key of
    the target."""
    return " + ".join(
        f"""(SELECT count(*) FROM {COLLECTION_EDGES} e JOIN {name} t ON t.id = e.to_id
      WHERE e.from_id = {source} AND e.relation = '{RELATION_REFERS_TO}'
        AND e.to_collection = '{name}' AND {_stub(name)})"""
        for name in sorted(STUB_COLLECTIONS)
    )


_COUNT_SQL = f"""
SELECT u.count + coalesce(u.ljns, 0) AS unlinked, {_to_stubs("u.id")} AS unloaded
FROM {UNLINKED_TABLE} u WHERE u.id = %(id)s
"""


def reference_counts(store: Store, node: str) -> ReferenceCounts | None:
    """Of the references the text of *node* makes: how many its step could not link, and
    how many of its ``REFERS_TO`` edges go to a stub; None when no step read it."""
    rows = store.query(_COUNT_SQL, {"id": node})
    row = next(iter(rows), None)
    return None if row is None else ReferenceCounts(row["unlinked"], row["unloaded"])


# Of a law of the Staatsblad (``semantic staatsblad-law-references``) or an article of one:
# what the step could not link is a prop of it (of the law: the sum over its articles); the
# edges to a stub are those of the article, or of every article of the law (by the column
# that names its law).
_LAW_ARTICLE_COUNT_SQL = f"""
SELECT (n.props ->> 'unlinked_references')::int AS unlinked, {_to_stubs("n.id")} AS unloaded
FROM {COLLECTION_ARTICLES} n WHERE n.id = %(id)s
"""
_LAW_ARTICLES = f"""ANY(ARRAY(
    SELECT a.id FROM {COLLECTION_ARTICLES} a
    WHERE a.official_id = lg_str(n.props -> 'official_id') AND a.stub IS NOT TRUE))"""
_LAW_COUNT_SQL = f"""
SELECT (n.props ->> 'unlinked_references')::int AS unlinked,
       {_to_stubs(_LAW_ARTICLES)} AS unloaded
FROM {COLLECTION_INSTRUMENTS} n WHERE n.id = %(id)s
"""


def law_reference_counts(store: Store, node: str) -> ReferenceCounts | None:
    """Of the references a law of the Staatsblad (*node*, of all its articles) or an article
    of one makes: how many ``semantic staatsblad-law-references`` could not link
    (``unlinked_references``), and how many of their ``REFERS_TO`` edges go to a stub; None
    when the step has not read it."""
    law = node.startswith(f"{COLLECTION_INSTRUMENTS}/")
    rows = store.query(_LAW_COUNT_SQL if law else _LAW_ARTICLE_COUNT_SQL, {"id": node})
    row = next(iter(rows), None)
    if row is None or row["unlinked"] is None:
        return None
    return ReferenceCounts(row["unlinked"], row["unloaded"])
