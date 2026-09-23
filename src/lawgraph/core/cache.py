"""In-process cache with a time-to-live and least-recently-used eviction.

``get`` returns ``_MISSING`` for an absent or expired key, so ``None`` can be cached.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Generic, TypeVar

from lawgraph.config.settings import API_CACHE_MAXSIZE, API_CACHE_TTL

_K = TypeVar("_K")
_V = TypeVar("_V")

_MISSING = object()

_DEFAULT_TTL = API_CACHE_TTL
_DEFAULT_MAXSIZE = API_CACHE_MAXSIZE


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

    def get(self, key: _K) -> _V | object:
        entry = self._store.get(key)
        if entry is None:
            return _MISSING
        expires_at, value = entry
        if time.monotonic() > expires_at:
            self._store.pop(key, None)
            return _MISSING
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

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
