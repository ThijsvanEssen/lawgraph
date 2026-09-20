"""ArangoStore.existing_keys: bulk existence check, chunked."""

from __future__ import annotations

import pytest

from lawgraph.db.store import ArangoStore


def _store(existing: set[str]) -> tuple[ArangoStore, list[list[str]]]:
    calls: list[list[str]] = []
    store = ArangoStore.__new__(ArangoStore)  # no database connection needed

    def fake_query(aql, bind_vars=None, **_kw):
        calls.append(bind_vars["keys"])
        return [k for k in bind_vars["keys"] if k in existing]

    store.query = fake_query  # type: ignore[method-assign]
    return store, calls


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
