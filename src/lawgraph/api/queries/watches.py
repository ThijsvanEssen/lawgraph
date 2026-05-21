"""Watch helpers."""

from __future__ import annotations

import datetime as dt
from typing import Any

from arango.exceptions import DocumentDeleteError

from lawgraph.db import ArangoStore


def list_watches(store: ArangoStore) -> list[dict[str, Any]]:
    """Return all watches, newest first."""
    aql = """
    FOR doc IN watches
        SORT doc.created_at DESC
        RETURN doc
    """
    return list(store.query(aql))


def create_watch(
    store: ArangoStore, *, node_id: str, label: str | None, collection: str | None
) -> dict[str, Any]:
    """Insert a new watch document and return it with its generated _key."""
    import uuid

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    doc = {
        "_key": str(uuid.uuid4()).replace("-", ""),
        "node_id": node_id,
        "label": label,
        "collection": collection,
        "created_at": now,
    }
    store.db.collection("watches").insert(doc)
    return doc


def delete_watch(store: ArangoStore, watch_id: str) -> bool:
    """Delete a watch by its _key. Returns True if found and deleted."""
    try:
        store.db.collection("watches").delete(watch_id)
        return True
    except DocumentDeleteError:
        return False
