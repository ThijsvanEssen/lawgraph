from __future__ import annotations

from functools import lru_cache

from lawgraph.db import ArangoStore


@lru_cache(maxsize=1)
def _get_store_instance() -> ArangoStore:
    """Singleton-like container for the shared Arango store."""
    return ArangoStore()


def get_store() -> ArangoStore:
    """Provide an ArangoStore instance for FastAPI routes via Depends."""
    return _get_store_instance()
