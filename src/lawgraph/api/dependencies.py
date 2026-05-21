from __future__ import annotations

from lawgraph.db import ArangoStore

_store: ArangoStore | None = None


def get_store() -> ArangoStore:
    """Provide an ArangoStore instance for FastAPI routes via Depends."""
    global _store
    if _store is None:
        _store = ArangoStore()
    return _store
