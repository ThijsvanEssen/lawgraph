"""GraphStore.existing_keys: bulk existence check, chunked."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.db.store import GraphStore, Params, Statement


class _KeysStore(GraphStore):
    """The real ``existing_keys`` on a query that answers from *existing*: no database."""

    def __init__(self, existing: set[str]) -> None:
        self.existing = existing
        self.calls: list[list[str]] = []

    def query(
        self, statement: Statement, params: Params = None, **_kw: Any
    ) -> Iterator[Any]:
        assert isinstance(params, dict)
        self.calls.append(params["keys"])
        return iter([k for k in params["keys"] if k in self.existing])


def _store(existing: set[str]) -> tuple[GraphStore, list[list[str]]]:
    store = _KeysStore(existing)
    return store, store.calls


def test_returns_only_existing_keys_in_one_call() -> None:
    store, calls = _store({"a", "c"})

    assert store.existing_keys("dossiers", ["a", "b", "c", "a"]) == {"a", "c"}
    assert len(calls) == 1 and sorted(calls[0]) == ["a", "b", "c"]  # de-duplicated


def test_chunks_large_key_sets() -> None:
    keys = [f"k{i}" for i in range(12)]
    store, calls = _store(set(keys))

    assert store.existing_keys("dossiers", keys, chunk_size=5) == set(keys)
    assert [len(c) for c in calls] == [5, 5, 2]


def test_empty_input_does_not_query() -> None:
    store, calls = _store(set())
    assert store.existing_keys("dossiers", []) == set()
    assert calls == []


def test_unknown_collection_is_rejected() -> None:
    store, _ = _store(set())
    with pytest.raises(ValueError):
        store.existing_keys("nope", ["a"])
