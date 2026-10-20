"""The other query functions the unit tests patch, answered from an ``InMemoryStore``: the
edge removals, the alias rows, the kinds of Documents, the pipeline state and the references a
step could not link."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.db.queries import instrument_names, removals, unlinked_references
from lawgraph.db.queries import state as state_queries
from lawgraph.db.queries.normalize import tk as normalize_tk
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
    other_ends: list[str] | None = None,
) -> list[tuple[str, str]]:
    other = "to_id" if end == "from_id" else "from_id"
    gone = [
        key
        for key, edge in store.edges.items()
        if edge[end] in ids
        and edge.get("relation") in relations
        and edge.get("source") == source
        and key not in keep.get(edge[end], set())
        and (other_ends is None or edge[other].split("/", 1)[0] in other_ends)
    ]
    return [(e["from_id"], e["to_id"]) for e in (store.edges.pop(key) for key in gone)]


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


def patch_document_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    """``document_kinds``, from the ``props.kind`` of the Documents of an ``InMemoryStore``."""

    def document_kinds(store: InMemoryStore, keys: list[str]) -> dict[str, str | None]:
        documents = store.nodes.get("documents", {})
        return {
            key: (documents[key].get("props") or {}).get("kind")
            for key in keys
            if key in documents
        }

    monkeypatch.setattr(normalize_tk, "document_kinds", document_kinds)


def patch_kept_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_state`` and ``set_state``, on the ``kept`` of an ``InMemoryStore``."""

    def get_state(store: InMemoryStore, key: str) -> dict[str, Any] | None:
        return store.kept.get(key)

    def set_state(store: InMemoryStore, key: str, doc: dict[str, Any] | None) -> None:
        store.kept.pop(key, None)
        if doc is not None:
            store.kept[key] = doc

    monkeypatch.setattr(state_queries, "get_state", get_state)
    monkeypatch.setattr(state_queries, "set_state", set_state)


def patch_pipeline_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """The queries of ``db/queries/state.py``, answered from a ``PipelineStateFake``: the
    watermarks from its ``state``, any other document from its ``kept``."""
    patch_kept_state(monkeypatch)

    def covered_until(store: PipelineStateFake, phase: str) -> str | None:
        return store.state.get(phase)

    def set_covered_until(store: PipelineStateFake, phase: str, began_iso: str) -> None:
        store.state[phase] = began_iso

    monkeypatch.setattr(state_queries, "covered_until", covered_until)
    monkeypatch.setattr(state_queries, "set_covered_until", set_covered_until)


def patch_unlinked(monkeypatch: pytest.MonkeyPatch) -> None:
    """``keep_unlinked`` of ``db/queries/unlinked_references.py``, into ``unlinked`` of an
    ``InMemoryStore`` (node id -> ``(step, count)``)."""

    def keep_unlinked(
        store: InMemoryStore, step: str, counts: dict[str, int], *, whole: bool
    ) -> int:
        kept = store.unlinked
        if whole:
            for node in [n for n, (s, _) in kept.items() if s == step]:
                if node not in counts:
                    del kept[node]
        kept.update({node: (step, count) for node, count in counts.items()})
        return len(counts)

    monkeypatch.setattr(unlinked_references, "keep_unlinked", keep_unlinked)
