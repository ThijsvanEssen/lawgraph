"""What a route can ask for: the store. The API only reads."""

from __future__ import annotations

from lawgraph.db import GraphStore

_store: GraphStore | None = None


def get_store() -> GraphStore:
    """Provide an GraphStore instance for FastAPI routes via Depends."""
    global _store
    if _store is None:
        _store = GraphStore()
    return _store
