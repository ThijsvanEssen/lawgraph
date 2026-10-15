"""Small batching helpers."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Iterator
from itertools import batched


def chunked[T](items: Iterable[T], size: int) -> Iterator[list[T]]:
    """Yield lists of up to *size* items, preserving order."""
    for batch in batched(items, size, strict=False):
        yield list(batch)


def chunked_aligned[T](
    items: Iterable[T], size: int, key: Callable[[T], Hashable]
) -> Iterator[list[T]]:
    """Like :func:`chunked`, but never split a run of consecutive items with the same *key*.

    A chunk is closed once it holds at least *size* items **and** the next item has
    a different key, so a chunk can exceed *size* by the length of one run. Use it
    on a stream sorted by *key* when everything belonging to one key must be
    processed together (e.g. all versions of one article).
    """
    chunk: list[T] = []
    last: Hashable = None
    for item in items:
        item_key = key(item)
        if len(chunk) >= size and item_key != last:
            yield chunk
            chunk = []
        chunk.append(item)
        last = item_key
    if chunk:
        yield chunk
