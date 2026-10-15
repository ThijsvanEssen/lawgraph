"""The other query functions the unit tests patch, answered from an ``InMemoryStore``: the
edge removals, the alias rows and the pipeline state."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.db.queries import instrument_names, removals
from lawgraph.db.queries import state as state_queries
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from tests.fakes.store import InMemoryStore, PipelineStateFake


def _remove_edges_at(
    store: InMemoryStore,
    end: str,
    relations: list[str],
    ids: list[str],
    keep: dict[str, set[str]],
    *,
    source: str,
) -> list[tuple[str, str]]:
    side = {"from_id": "_from", "to_id": "_to"}[end]
    gone = [
        key
        for key, edge in store.edges.items()
        if edge[side] in ids
        and edge.get("relation") in relations
        and edge.get("source") == source
        and key not in keep.get(edge[side], set())
    ]
    return [(e["_from"], e["_to"]) for e in (store.edges.pop(key) for key in gone)]


def _remove_edges_except(
    store: InMemoryStore, relation: str, keep: list[str], *, source: str | None = None
) -> int:
    gone = [
        key
        for key, edge in store.edges.items()
        if edge.get("relation") == relation
        and source in (None, edge.get("source"))
        and key not in keep
    ]
    for key in gone:
        del store.edges[key]
    return len(gone)


def patch_edge_removals(monkeypatch: pytest.MonkeyPatch) -> None:
    """``remove_edges_at`` and ``remove_edges_except`` of ``db/queries/removals.py``, on the
    ``edges`` of an ``InMemoryStore``."""
    monkeypatch.setattr(removals, "remove_edges_at", _remove_edges_at)
    monkeypatch.setattr(removals, "remove_edges_except", _remove_edges_except)


_ALIAS_FIELDS = (
    "short_title",
    "aliases",
    "bwb_id",
    "celex",
    "title",
    "citation_title",
    "citation_titles",
)


def _alias_rows(store: InMemoryStore) -> Iterator[dict[str, Any]]:
    instruments = sorted(store.nodes.get("instruments", {}).items())
    return iter(
        [
            {field: doc.get("props", {}).get(field) for field in _ALIAS_FIELDS}
            for _, doc in instruments
            if doc.get("props", {}).get("bwb_id") or doc.get("props", {}).get("celex")
        ]
    )


def patch_alias_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """``code_alias_rows`` and ``instrument_alias_rows``, from the instruments of an
    ``InMemoryStore``."""
    monkeypatch.setattr(instrument_names, "code_alias_rows", _alias_rows)
    monkeypatch.setattr(semantic_bwb, "instrument_alias_rows", _alias_rows)


def patch_pipeline_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """The queries of ``db/queries/state.py``, answered from a ``PipelineStateFake``."""

    def covered_until(store: PipelineStateFake, phase: str) -> str | None:
        return store.state.get(phase)

    def set_covered_until(store: PipelineStateFake, phase: str, began_iso: str) -> None:
        store.state[phase] = began_iso

    monkeypatch.setattr(state_queries, "covered_until", covered_until)
    monkeypatch.setattr(state_queries, "set_covered_until", set_covered_until)
