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
