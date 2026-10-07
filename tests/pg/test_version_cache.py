"""Answers kept per data version on a real PostgreSQL: computed once, kept until a write
to the graph raises the version, and computed once when many ask at the same moment."""

from __future__ import annotations

import threading
import time

from lawgraph.db import GraphStore, version_cache


def _instrument(key: str) -> dict[str, object]:
    return {"_key": key, "type": "instrument", "labels": [], "props": {"title": key}}


def test_an_answer_is_kept_until_the_data_changes(store: GraphStore) -> None:
    computed: list[int] = []

    def count() -> int:
        computed.append(1)
        return int(next(store.query("SELECT count(*)::int FROM instruments")))

    assert version_cache.cached(store, ("count",), count) == 0
    assert version_cache.cached(store, ("count",), count) == 0
    assert computed == [1]

    store.bulk_insert_or_update_nodes("instruments", [_instrument("a")])
    assert version_cache.cached(store, ("count",), count) == 1
    assert computed == [1, 1]


def test_rows_are_kept_per_statement_and_parameters(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments", [_instrument("a"), _instrument("b")]
    )
    statement = "SELECT key FROM instruments WHERE key = ANY(%(keys)s) ORDER BY key"
    assert version_cache.cached_rows(store, statement, {"keys": ["a"]}) == ["a"]
    assert version_cache.cached_rows(store, statement, {"keys": ["a", "b"]}) == [
        "a",
        "b",
    ]


def test_many_at_once_compute_it_once(store: GraphStore) -> None:
    computed: list[int] = []

    def slow() -> str:
        computed.append(1)
        time.sleep(0.3)
        return "answer"

    answers: list[str] = []
    threads = [
        threading.Thread(
            target=lambda: answers.append(version_cache.cached(store, ("slow",), slow))
        )
        for _ in range(6)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert answers == ["answer"] * 6
    assert computed == [1]
