"""What the search reads, read into memory after the nightly run (``pg_prewarm``).

The first searches after the nightly run read their pages from disk: an article search
of two words 2.7 s cold against 0.3 s warm (prod, 29 Oct). Here the search indexes of
``TABLES``, then the heap and TOAST of the tables asked for, are read into the cache of the
operating system (``pg_prewarm`` ``read``), within ``BUDGET_MB``: a page there costs
PostgreSQL no disk read, and ``shared_buffers`` (1 GB, which the search indexes alone
outgrow: 1.9 GB on prod) keeps what the rest of the API reads. A relation that does not
fit in what is left is skipped, the next one is still read.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOSSIERS,
    COLLECTION_JUDGMENTS,
)
from lawgraph.db import GraphStore
from lawgraph.db.schema import search_indexes

# The tables whose search indexes are read, in the order they are searched by most.
TABLES = (COLLECTION_ARTICLES, COLLECTION_DOSSIERS, COLLECTION_JUDGMENTS)
# The most read (MB): the search indexes on prod (1.9 GB) with room to grow, some 40 %
# of the cache of web-1 (8 GB, 5 GB of it cache). The heap and TOAST of the articles
# (4.3 GB) would push out most of the rest.
BUDGET_MB = 2560


@dataclass(frozen=True)
class Warmed:
    """A relation and its blocks read, or none when it did not fit (``skipped``)."""

    relation: str
    blocks: int
    seconds: float
    skipped: bool = False


def relations(store: GraphStore, heaps: tuple[str, ...] = ()) -> list[str]:
    """The relations to read, in order: the search indexes of ``TABLES`` that exist,
    then the heap and TOAST of each of *heaps*."""
    wanted = [name for table in TABLES for name in search_indexes(table)]
    existing = set(
        store.execute(
            "SELECT relname FROM pg_class WHERE relkind = 'i' AND relname = ANY(%s)",
            (wanted,),
        )
    )
    found = [name for name in wanted if name in existing]
    for table in heaps:
        found.append(table)
        found += store.execute(
            "SELECT reltoastrelid::regclass::text FROM pg_class"
            " WHERE oid = %s::regclass AND reltoastrelid <> 0",
            (table,),
        )
    return found


def prewarm(
    store: GraphStore, heaps: tuple[str, ...] = (), budget_mb: int = BUDGET_MB
) -> list[Warmed]:
    """Read ``relations`` into the cache of the operating system, each while it fits in
    what is left of *budget_mb*."""
    left = budget_mb * 1024 * 1024
    warmed = []
    for relation in relations(store, heaps):
        (size,) = store.execute("SELECT pg_relation_size(%s::regclass)", (relation,))
        if size > left:
            warmed.append(Warmed(relation, 0, 0.0, skipped=True))
            continue
        started = time.monotonic()
        (blocks,) = store.execute(
            "SELECT pg_prewarm(%s::regclass, 'read')", (relation,)
        )
        left -= size
        warmed.append(Warmed(relation, blocks, time.monotonic() - started))
    return warmed
