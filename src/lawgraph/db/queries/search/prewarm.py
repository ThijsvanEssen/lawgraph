"""What the search reads, read into memory after the nightly run (``pg_prewarm``).

The first searches after the nightly run read their pages from disk: an article search
of two words 2.7 s cold, 2.0 s of it its heap, against 0.3 s warm (prod, 29 Oct). Here the
search indexes of ``TABLES`` are read into the buffers of PostgreSQL (``buffer``), within
``INDEX_SHARE`` of ``shared_buffers``, so they do not push out what the rest of the API
reads; the heap and TOAST of ``HEAPS`` into the cache of the operating system (``read``),
within ``HEAP_MB``, which takes nothing from those buffers. A relation that does not fit
in what is left is skipped, the next one is still read.
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
# The share of ``shared_buffers`` the indexes may take.
INDEX_SHARE = 0.5
# The tables whose heap and TOAST are read into the cache of the operating system.
HEAPS = (COLLECTION_ARTICLES,)
# The most of those heaps read (MB).
HEAP_MB = 2048


@dataclass(frozen=True)
class Warmed:
    """A relation, how it was read (``buffer``, ``read``) and its blocks read, or none
    when it did not fit (``skipped``)."""

    relation: str
    mode: str
    blocks: int
    seconds: float
    skipped: bool = False


def relations(
    store: GraphStore, heaps: tuple[str, ...] = HEAPS
) -> list[tuple[str, str]]:
    """The relations to read and how: the search indexes of ``TABLES`` that exist
    (``buffer``), then the heap and TOAST of each of *heaps* (``read``)."""
    wanted = [name for table in TABLES for name in search_indexes(table)]
    existing = set(
        store.execute(
            "SELECT relname FROM pg_class WHERE relkind = 'i' AND relname = ANY(%s)",
            (wanted,),
        )
    )
    found = [(name, "buffer") for name in wanted if name in existing]
    for table in heaps:
        found.append((table, "read"))
        found += [
            (toast, "read")
            for toast in store.execute(
                "SELECT reltoastrelid::regclass::text FROM pg_class"
                " WHERE oid = %s::regclass AND reltoastrelid <> 0",
                (table,),
            )
        ]
    return found


def prewarm(
    store: GraphStore,
    heaps: tuple[str, ...] = HEAPS,
    heap_mb: int = HEAP_MB,
) -> list[Warmed]:
    """Read ``relations`` into memory, each within what is left of its budget."""
    (shared,) = store.execute("SELECT pg_size_bytes(current_setting('shared_buffers'))")
    left = {"buffer": int(shared * INDEX_SHARE), "read": heap_mb * 1024 * 1024}
    warmed = []
    for relation, mode in relations(store, heaps):
        (size,) = store.execute("SELECT pg_relation_size(%s::regclass)", (relation,))
        if size > left[mode]:
            warmed.append(Warmed(relation, mode, 0, 0.0, skipped=True))
            continue
        started = time.monotonic()
        (blocks,) = store.execute(
            "SELECT pg_prewarm(%s::regclass, %s)", (relation, mode)
        )
        left[mode] -= size
        warmed.append(Warmed(relation, mode, blocks, time.monotonic() - started))
    return warmed
