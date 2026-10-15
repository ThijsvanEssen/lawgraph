"""The one error a query or a route raises for something that is not there; the API
answers it with a 404 (``api/app.py``). Any other error is a 500."""

from __future__ import annotations

from typing import Any

from lawgraph.db import GraphStore


class NotFound(LookupError):
    """``what`` with ``key`` does not exist."""

    def __init__(self, what: str, key: str) -> None:
        super().__init__(f"{what} '{key}' not found.")


def require[T](value: T | None, what: str, key: str) -> T:
    """*value*, or ``NotFound`` when it is ``None``."""
    if value is None:
        raise NotFound(what, key)
    return value


def require_node(
    store: GraphStore, collection: str, key: str, what: str
) -> dict[str, Any]:
    """The document of *key* in *collection*, or ``NotFound``."""
    return require(store.get_document(collection, key), what, key)
