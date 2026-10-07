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


def test_a_request_past_its_deadline_gives_up_and_the_computation_goes_on(
    store: GraphStore,
) -> None:
    import pytest

    from lawgraph.db import store as store_module

    computed: list[int] = []

    def slow() -> str:
        computed.append(1)
        time.sleep(0.5)
        return "answer"

    token = store_module.set_read_deadline(0.1)
    try:
        with pytest.raises(store_module.ReadTimedOut):
            version_cache.cached(store, ("slow-deadline",), slow)
    finally:
        store_module.reset_read_deadline(token)
    time.sleep(0.6)
    # computed on, kept for the next request
    assert version_cache.cached(store, ("slow-deadline",), slow) == "answer"
    assert computed == [1]


def test_a_failed_computation_is_not_kept(store: GraphStore) -> None:
    import pytest

    attempts: list[int] = []

    def flaky() -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("the database went away")
        return "answer"

    with pytest.raises(RuntimeError):
        version_cache.cached(store, ("flaky",), flaky)
    assert version_cache.cached(store, ("flaky",), flaky) == "answer"
    assert attempts == [1, 1]


def test_a_new_data_version_warms_up_in_the_background(
    store: GraphStore, monkeypatch
) -> None:
    warmed: list[str] = []
    monkeypatch.setattr(version_cache, "_warmers", [lambda s: warmed.append(s.name)])
    # it starts once the version has stood still this long (90 s on a server)
    monkeypatch.setattr(version_cache, "WARM_UP_SETTLE", 0.2)

    version_cache.cached(store, ("x",), lambda: 1)  # the first version: no warm-up
    time.sleep(0.2)
    assert warmed == []

    store.bulk_insert_or_update_nodes("instruments", [_instrument("a")])
    version_cache.cached(store, ("x",), lambda: 2)  # a version it did not know
    for _ in range(60):
        if warmed:
            break
        time.sleep(0.05)
    assert warmed == [store.name]


def test_after_a_change_a_request_takes_the_last_answer_while_the_new_one_computes(
    store: GraphStore, monkeypatch
) -> None:
    from lawgraph.db import store as store_module

    monkeypatch.setattr(version_cache, "STALE_WAIT", 0.1)
    assert version_cache.cached(store, ("stale",), lambda: "old") == "old"
    store.bulk_insert_or_update_nodes("instruments", [_instrument("a")])

    def slow() -> str:
        time.sleep(0.5)
        return "new"

    token = store_module.set_read_deadline(30)
    try:
        started = time.monotonic()
        assert version_cache.cached(store, ("stale",), slow) == "old"
        assert time.monotonic() - started < 0.4
    finally:
        store_module.reset_read_deadline(token)
    time.sleep(0.6)
    assert version_cache.cached(store, ("stale",), slow) == "new"


def test_outside_a_request_the_new_answer_is_waited_for(
    store: GraphStore, monkeypatch
) -> None:
    """The warm-up has no deadline: it waits for the answer of the new version."""
    monkeypatch.setattr(version_cache, "STALE_WAIT", 0.1)
    assert version_cache.cached(store, ("warm",), lambda: "old") == "old"
    store.bulk_insert_or_update_nodes("instruments", [_instrument("a")])

    def slow() -> str:
        time.sleep(0.3)
        return "new"

    assert version_cache.cached(store, ("warm",), slow) == "new"


def test_computing_says_whether_an_answer_is_on_its_way(store: GraphStore) -> None:
    started = threading.Event()
    release = threading.Event()

    def slow() -> str:
        started.set()
        release.wait(5)
        return "answer"

    assert not version_cache.computing(store)
    waiter = threading.Thread(
        target=lambda: version_cache.cached(store, ("busy",), slow)
    )
    waiter.start()
    started.wait(5)
    assert version_cache.computing(store)
    release.set()
    waiter.join()
    assert not version_cache.computing(store)


def test_lasting_rows_are_kept_when_the_data_changes(store: GraphStore) -> None:
    """A facet of a filter: kept its ``max_age``, not per data version."""
    statement = "SELECT count(*)::int FROM instruments"
    assert version_cache.lasting_rows(store, statement, max_age=3600) == [0]
    store.bulk_insert_or_update_nodes("instruments", [_instrument("a")])
    assert version_cache.lasting_rows(store, statement, max_age=3600) == [0]
    assert version_cache.lasting_rows(store, statement, max_age=0) == [1]


def test_a_computation_that_asks_for_another_one_does_not_wait_for_the_pool(
    store: GraphStore, monkeypatch, caplog
) -> None:
    """With every worker of the pool busy, an answer a computation asks for would wait in
    the queue behind it for ever: it is computed in the worker that asks, with a warning
    whose stack names the caller."""
    import concurrent.futures

    monkeypatch.setattr(
        version_cache,
        "_pool",
        concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="lawgraph-cache"),
    )
    done: list[str] = []

    def outer() -> str:
        inner = version_cache.lasting(store, ("inner",), lambda: "inner", 3600)
        also = version_cache.cached(store, ("also",), lambda: "also")
        return f"{inner} {also}"

    with caplog.at_level("WARNING"):
        asking = threading.Thread(
            target=lambda: done.append(version_cache.cached(store, ("outer",), outer)),
            daemon=True,
        )
        asking.start()
        asking.join(timeout=10)
    assert done == ["inner also"], "the computation waited for the pool"
    nested = [
        r for r in caplog.records if "A computation of the cache asked" in r.message
    ]
    assert len(nested) == 2 and nested[0].stack_info
