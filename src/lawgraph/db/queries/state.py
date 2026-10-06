"""``pipeline_state``: until when each phase has worked through its sources."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Json

from lawgraph.config.constants import COLLECTION_PIPELINE_STATE


def covered_until(store: Any, phase: str) -> str | None:
    """The moment (ISO) the last complete run of *phase* began, or None."""
    doc = next(
        store.query(
            f"SELECT doc FROM {COLLECTION_PIPELINE_STATE} WHERE key = %(phase)s",
            {"phase": phase},
        ),
        None,
    )
    return str(doc["covered_until"]) if doc else None


def set_covered_until(store: Any, phase: str, began_iso: str) -> None:
    """Record that *phase* is complete until *began_iso*."""
    store.execute(
        f"""
        INSERT INTO {COLLECTION_PIPELINE_STATE} (key, doc) VALUES (%(phase)s, %(doc)s)
        ON CONFLICT (key) DO UPDATE SET doc = EXCLUDED.doc
        """,
        {"phase": phase, "doc": Json({"covered_until": began_iso})},
    )


def get_state(store: Any, key: str) -> dict[str, Any] | None:
    """The document a pipeline keeps under *key* (where a long run is), or None."""
    doc = next(
        store.query(
            f"SELECT doc FROM {COLLECTION_PIPELINE_STATE} WHERE key = %(key)s",
            {"key": key},
        ),
        None,
    )
    return dict(doc) if doc else None


def set_state(store: Any, key: str, doc: dict[str, Any] | None) -> None:
    """Keep *doc* under *key*; None removes it."""
    if doc is None:
        store.execute(
            f"DELETE FROM {COLLECTION_PIPELINE_STATE} WHERE key = %(key)s", {"key": key}
        )
        return
    store.execute(
        f"""
        INSERT INTO {COLLECTION_PIPELINE_STATE} (key, doc) VALUES (%(key)s, %(doc)s)
        ON CONFLICT (key) DO UPDATE SET doc = EXCLUDED.doc
        """,
        {"key": key, "doc": Json(doc)},
    )


def states_starting_with(store: Any, prefix: str) -> dict[str, dict[str, Any]]:
    """Every document kept under a key that starts with *prefix*, by key."""
    rows = store.query(
        f"SELECT key, doc FROM {COLLECTION_PIPELINE_STATE} "
        "WHERE starts_with(key, %(prefix)s)",
        {"prefix": prefix},
    )
    return {row["key"]: dict(row["doc"]) for row in rows}
