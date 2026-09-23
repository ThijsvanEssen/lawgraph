"""``pipeline_state``: until when each phase has worked through its sources."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_PIPELINE_STATE


def covered_until(store: Any, phase: str) -> str | None:
    """The moment (ISO) the last complete run of *phase* began, or None."""
    doc = store.collection(COLLECTION_PIPELINE_STATE).get(phase)
    return str(doc["covered_until"]) if doc else None


def set_covered_until(store: Any, phase: str, began_iso: str) -> None:
    """Record that *phase* is complete until *began_iso*."""
    store.collection(COLLECTION_PIPELINE_STATE).insert(
        {"_key": phase, "covered_until": began_iso}, overwrite=True
    )
