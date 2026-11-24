"""The tables the answers of ``version_cache`` asked within ``reading`` name: the warm-up
leaves a part out while those of its answers stand still (``api/warm.py``)."""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator

# What the tables of a ``reading`` hold for an answer that names none (it may read any).
ANY = "*"
_reads: contextvars.ContextVar[set[str] | None] = contextvars.ContextVar(
    "lawgraph_table_reads", default=None
)


@contextlib.contextmanager
def reading() -> Iterator[set[str]]:
    """Within it, gather the tables each answer asked names, ``ANY`` for one naming none."""
    reads: set[str] = set()
    token = _reads.set(reads)
    try:
        yield reads
    finally:
        _reads.reset(token)


def note(tables: tuple[str, ...] | None) -> None:
    """An answer asked that reads *tables* (None: any)."""
    reads = _reads.get()
    if reads is not None:
        reads.update(tables or (ANY,))
