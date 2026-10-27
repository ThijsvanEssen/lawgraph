"""The steps between sources (``source_steps``), built whole from the edges by ``semantic
graph-steps``; ``/api/chains`` searches them (``queries/chains.py``).

A step joins two sources (``STEP_COLLECTIONS``: laws and articles): by an edge between them
(``direct``), or by a node with an edge to both, of any collection (a paper that names both,
a judgment that cites both). A node with an edge to more than ``THROUGH_CAP`` sources (an
omnibus paper, a large dossier) joins none: it says little of any two of them. The
``PART_OF`` of an article or an annex and its law is no edge here: else every two articles of
a law would be one step apart.

``source_steps`` holds one row per pair of sources (``a < b``, compared by byte): ``ways``
the nodes they share, ``direct`` whether an edge joins them, and ``weight`` how strong the
step is: over the nodes they share the sum of 1 / ln k, k the sources of the node
(Adamic-Adar: a node of two sources adds 1.44, one of fifty 0.26), plus ``DIRECT_WEIGHT`` for
the edge, as much as a node that touches those two alone; ``via`` the node they share with
the fewest sources, then the lowest id (null when they share none), the way ``/api/chains``
shows. ``source_step_nodes`` holds per node with an edge to two sources or more their number
(``sources``), over the cap too: the search reads what a step goes through there.

Both are built beside the tables (``_new``), their indexes and visibility made, and then put
in their place in one short transaction: a reader sees the old steps or the new, never half.
"""

from __future__ import annotations

import datetime as dt
import math

import psycopg
from psycopg.types.json import Json

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_PIPELINE_STATE,
    RELATION_PART_OF,
)
from lawgraph.db import GraphStore
from lawgraph.db._sql import sql_text_list
from lawgraph.db.schema import (
    SOURCE_STEP_NODES_TABLE,
    SOURCE_STEPS_COLUMNS,
    SOURCE_STEPS_INDEXES,
    SOURCE_STEPS_TABLE,
)

# The collections of the sources a step joins.
STEP_COLLECTIONS = (COLLECTION_INSTRUMENTS, COLLECTION_ARTICLES)
# A node with an edge to more sources than this joins none of them.
THROUGH_CAP = 50
# The weight of the edge between two sources: that of a node of those two alone.
DIRECT_WEIGHT = 1 / math.log(2)
# When the steps were built (``pipeline_state``): until then ``/api/chains`` has none.
BUILT_STATE = "source_steps"
# The digits of the sources of a node through which a step goes: ``via`` is the least of
# them and its id together.
_DIGITS = len(str(THROUGH_CAP))
# How long one statement of the build may run, and the memory of its sorts and hashes.
BUILD_TIMEOUT = "30min"
BUILD_WORK_MEM = "256MB"

_NEW = "_new"
_SOURCES = sql_text_list(STEP_COLLECTIONS)
# An edge a step reads: not to itself, and not the ``PART_OF`` of a law.
KEPT = f"""e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM '{RELATION_PART_OF}'
         OR e.from_collection <> '{COLLECTION_INSTRUMENTS}'
            AND e.to_collection <> '{COLLECTION_INSTRUMENTS}')"""

# Every node and source with an edge between them, once.
_TOUCH = f"""
CREATE TEMP TABLE lg_step_touch ON COMMIT DROP AS
SELECT DISTINCT t.x COLLATE "C" AS x, t.s COLLATE "C" AS s FROM (
    SELECT e.from_id AS x, e.to_id AS s FROM edges e
    WHERE e.to_collection IN ({_SOURCES}) AND {KEPT}
    UNION ALL
    SELECT e.to_id, e.from_id FROM edges e
    WHERE e.from_collection IN ({_SOURCES}) AND {KEPT}
) t
"""

_NODES = f"""
INSERT INTO {SOURCE_STEP_NODES_TABLE}{_NEW} (id, sources)
SELECT x, count(*) FROM lg_step_touch GROUP BY x HAVING count(*) >= 2 ORDER BY x
"""

# Every node a step goes through, with its source and what it adds to the weight.
_THROUGH = f"""
CREATE TEMP TABLE lg_step_through ON COMMIT DROP AS
SELECT t.x, t.s, 1 / ln(n.sources) AS weight,
       lpad(n.sources::text, {_DIGITS}, '0') || t.x COLLATE "C" AS rank
FROM lg_step_touch t JOIN {SOURCE_STEP_NODES_TABLE}{_NEW} n ON n.id = t.x
WHERE n.sources <= {THROUGH_CAP}
"""

_STEPS = f"""
INSERT INTO {SOURCE_STEPS_TABLE}{_NEW} (a, b, ways, direct, weight, via)
SELECT c.a, c.b, sum(c.ways)::int, bool_or(c.direct), sum(c.weight)::real,
       substr(min(c.rank), {_DIGITS + 1}) FROM (
    SELECT p.s AS a, q.s AS b, 1 AS ways, false AS direct, p.weight, p.rank
    FROM lg_step_through p JOIN lg_step_through q ON q.x = p.x AND p.s < q.s
    UNION ALL
    SELECT DISTINCT least(e.from_id COLLATE "C", e.to_id COLLATE "C"),
           greatest(e.from_id COLLATE "C", e.to_id COLLATE "C"), 0, true, {DIRECT_WEIGHT},
           NULL
    FROM edges e
    WHERE e.from_collection IN ({_SOURCES}) AND e.to_collection IN ({_SOURCES}) AND {KEPT}
) c
GROUP BY c.a, c.b
ORDER BY c.a, c.b
"""


def _build(conn: psycopg.Connection) -> None:
    """Build both tables beside the ones there, with their indexes, in one transaction."""
    conn.execute(f"SET LOCAL statement_timeout = '{BUILD_TIMEOUT}'")
    conn.execute(f"SET LOCAL work_mem = '{BUILD_WORK_MEM}'")
    for table, columns in SOURCE_STEPS_COLUMNS.items():
        conn.execute(f"DROP TABLE IF EXISTS {table}{_NEW}")
        conn.execute(f"CREATE TABLE {table}{_NEW} ({columns})")
    conn.execute(_TOUCH)
    conn.execute(_NODES)
    conn.execute(_THROUGH)
    conn.execute("CREATE INDEX ON lg_step_through (x)")
    conn.execute("ANALYZE lg_step_through")
    conn.execute(_STEPS)
    for name, definition in SOURCE_STEPS_INDEXES.items():
        conn.execute(
            definition.format(name=f"{name}{_NEW}", table=f"{SOURCE_STEPS_TABLE}{_NEW}")
        )


def _swap(conn: psycopg.Connection) -> int:
    """Put the tables built beside them in their place, and note when; the steps."""
    for table in SOURCE_STEPS_COLUMNS:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute(f"ALTER TABLE {table}{_NEW} RENAME TO {table}")
    conn.execute(
        f"ALTER INDEX {SOURCE_STEP_NODES_TABLE}{_NEW}_pkey"
        f" RENAME TO {SOURCE_STEP_NODES_TABLE}_pkey"
    )
    for name in SOURCE_STEPS_INDEXES:
        conn.execute(f"ALTER INDEX {name}{_NEW} RENAME TO {name}")
    row = conn.execute(f"SELECT count(*) FROM {SOURCE_STEPS_TABLE}").fetchone()
    steps = int(row[0]) if row else 0
    conn.execute(
        f"INSERT INTO {COLLECTION_PIPELINE_STATE} (key, doc) VALUES (%s, %s)"
        " ON CONFLICT (key) DO UPDATE SET doc = EXCLUDED.doc",
        (
            BUILT_STATE,
            Json({"built_at": dt.datetime.now(dt.UTC).isoformat(), "steps": steps}),
        ),
    )
    return steps


def build_source_steps(store: GraphStore) -> int:
    """Build the steps between the sources again, whole, and put them in place of the
    ones there; the steps (rows of ``source_steps``)."""
    with store.pool.connection() as conn:
        with conn.transaction():
            _build(conn)
        # the visibility of every row, so that a read of the indexes reads no row
        conn.autocommit = True
        try:
            for table in SOURCE_STEPS_COLUMNS:
                conn.execute(f"VACUUM (ANALYZE) {table}{_NEW}")
        finally:
            conn.autocommit = False
        with conn.transaction():
            return _swap(conn)


def steps_built(store: GraphStore) -> bool:
    """Whether the steps were built (``build_source_steps``) on this database."""
    found = store.query(
        f"SELECT count(*)::int FROM {COLLECTION_PIPELINE_STATE} WHERE key = %(key)s",
        {"key": BUILT_STATE},
    )
    return bool(next(found))
