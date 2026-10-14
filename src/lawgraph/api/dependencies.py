"""What a route can ask for: the store. The API only reads."""

from __future__ import annotations

from lawgraph.db import GraphStore
from lawgraph.db.schema import CollationMismatch, SchemaOutdated

_store: GraphStore | None = None
# A database this version refuses stays refused until the API restarts: no request opens a
# pool to be told so again. One it cannot reach is tried again by the next request.
_refused: SchemaOutdated | CollationMismatch | None = None


def get_store() -> GraphStore:
    """Provide an GraphStore instance for FastAPI routes via Depends."""
    global _store, _refused
    if _refused is not None:
        raise _refused.with_traceback(None)
    if _store is None:
        try:
            _store = GraphStore()
        except (SchemaOutdated, CollationMismatch) as exc:
            _refused = exc
            raise
    return _store
