"""Lightweight in-process TTL cache with LRU eviction.

Drop-in replacement for the bare-dict caches in individual route modules.
A single import replaces the 20-line boilerplate that was copy-pasted into
nodes.py and commissies.py.

Usage::

    from lawgraph.api.cache import TTLCache

    _cache: TTLCache[str, SomeType] = TTLCache(maxsize=256, ttl=60.0)

    value = _cache.get("key")
    if value is None:
        value = compute()
        _cache.set("key", value)
"""

from __future__ import annotations

import os
import time
from collections import OrderedDict
from typing import Generic, TypeVar

_K = TypeVar("_K")
_V = TypeVar("_V")

_DEFAULT_TTL = float(os.getenv("LAWGRAPH_CACHE_TTL", "60"))
_DEFAULT_MAXSIZE = int(os.getenv("LAWGRAPH_CACHE_MAXSIZE", "512"))


class TTLCache(Generic[_K, _V]):
    """LRU-evicting, TTL-expiring in-memory cache.

    Thread-safety: not guaranteed — designed for single-threaded async
    FastAPI workers where the GIL provides adequate protection for
    OrderedDict operations.

    Args:
        maxsize: Maximum number of entries before LRU eviction kicks in.
        ttl: Time-to-live in seconds for each entry.
    """

    def __init__(
        self,
        maxsize: int = _DEFAULT_MAXSIZE,
        ttl: float = _DEFAULT_TTL,
    ) -> None:
        self._maxsize = maxsize
        self._ttl = ttl
        self._store: OrderedDict[_K, tuple[float, _V]] = OrderedDict()

    def get(self, key: _K) -> _V | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            self._store.pop(key, None)
            return None
        # Move to end (most-recently used).
        self._store.move_to_end(key)
        return value

    def set(self, key: _K, value: _V) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (time.monotonic() + self._ttl, value)
        # Evict oldest entry when over capacity.
        while len(self._store) > self._maxsize:
            self._store.popitem(last=False)

    def invalidate(self, key: _K) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
