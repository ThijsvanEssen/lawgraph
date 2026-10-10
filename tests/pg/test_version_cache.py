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


def test_while_typing_a_request_takes_the_last_answer_at_once(
    store: GraphStore,
) -> None:
    """A search while typing (``stale_wait``) does not wait ``STALE_WAIT`` (2 s) for the
    answer of a new data version (the parser of citations after a poll): it takes the last
    one at once, and the new one goes on computing for the next."""
    from lawgraph.db import store as store_module

    assert version_cache.cached(store, ("typing",), lambda: "old") == "old"
    store.bulk_insert_or_update_nodes("instruments", [_instrument("a")])

    def slow() -> str:
        time.sleep(1.0)
        return "new"

    token = store_module.set_read_deadline(30)
    try:
        started = time.monotonic()
        with version_cache.stale_wait(0.05):
            assert version_cache.cached(store, ("typing",), slow) == "old"
        assert time.monotonic() - started < 0.5
        # outside it a request waits STALE_WAIT, here long enough for the new answer
        assert version_cache.cached(store, ("typing",), slow) == "new"
    finally:
        store_module.reset_read_deadline(token)


def test_a_search_while_typing_takes_the_last_parser_of_citations(
    store: GraphStore, monkeypatch
) -> None:
    """The live search sets it: the parser of citations of a new version of the
    instruments, which reads every instrument, is not waited for (2 s per lane after every
    poll, measured on prod); the full search waits for it as before."""
    from lawgraph.db import store as store_module
    from lawgraph.db.queries import search as search_queries

    real = search_queries.code_alias_rows

    def slow_rows(store_: GraphStore) -> object:
        time.sleep(1.0)
        return real(store_)

    token = store_module.set_read_deadline(30)
    try:
        store.bulk_insert_or_update_nodes("instruments", [_instrument("a")])
        search_queries.search_live(store, q="wet", types=["articles"], limit=3)
        store.bulk_insert_or_update_nodes("instruments", [_instrument("b")])
        monkeypatch.setattr(search_queries, "code_alias_rows", slow_rows)
        started = time.monotonic()
        search_queries.search_live(store, q="wet", types=["articles"], limit=3)
        assert time.monotonic() - started < 0.6
    finally:
        store_module.reset_read_deadline(token)


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


def test_health_names_what_the_background_computes_but_never_what_was_asked(
    store: GraphStore,
) -> None:
    """A computation of the cache shows as its kind alone: the words of a search are a
    visitor's, and ``/api/health`` is public."""
    from lawgraph.api import warm

    started = threading.Event()
    release = threading.Event()

    def counting() -> int:
        started.set()
        release.wait(5)
        return 1

    key = ("bm25-df", "judgments", (("summary", "text", "geheim woord"),))
    waiter = threading.Thread(target=lambda: version_cache.cached(store, key, counting))
    waiter.start()
    started.wait(5)
    try:
        running = version_cache.busy()
    finally:
        release.set()
        waiter.join()
    assert [c["call"] for c in running] == ["cache: bm25-df"]
    assert running[0]["thread"].startswith("lawgraph-cache")
    assert "geheim" not in str(running)
    assert version_cache.busy() == []

    seen: list[list[dict]] = []
    warm._run("stats", lambda: seen.append(version_cache.busy()))
    assert [c["call"] for c in seen[0]] == ["warm-up: stats"]
    assert version_cache.busy() == []


def test_an_answer_computed_inside_another_gives_the_worker_back() -> None:
    """``doing`` within ``doing`` (an answer a computation asked for, computed in its own
    worker): afterwards the worker shows the computation that asked again."""
    with version_cache.doing("cache: outer"):
        with version_cache.doing("cache: inner"):
            assert [c["call"] for c in version_cache.busy()] == ["cache: inner"]
        assert [c["call"] for c in version_cache.busy()] == ["cache: outer"]
    assert version_cache.busy() == []


def _judgment(key: str) -> dict[str, object]:
    return {"_key": key, "type": "judgment", "labels": [], "props": {"title": key}}


def test_an_answer_kept_per_table_outlives_a_write_to_another(
    store: GraphStore,
) -> None:
    """A poll of judgments leaves what counts the instruments as it is; a write to the
    instruments has it counted again."""
    computed: list[int] = []

    def count() -> int:
        computed.append(1)
        return int(next(store.query("SELECT count(*)::int FROM instruments")))

    def kept() -> int:
        return version_cache.cached(store, ("n",), count, tables=("instruments",))

    assert kept() == 0
    store.bulk_insert_or_update_nodes("judgments", [_judgment("j")])
    assert kept() == 0
    assert computed == [1]

    store.bulk_insert_or_update_nodes("instruments", [_instrument("a")])
    assert kept() == 1
    assert computed == [1, 1]


def test_an_answer_kept_per_table_is_computed_again_after_its_age(
    store: GraphStore, monkeypatch
) -> None:
    """The safety net for a table its declaration lacks: ``MAX_AGE`` at most."""
    computed: list[int] = []

    def count() -> int:
        computed.append(1)
        return len(computed)

    assert version_cache.cached(store, ("age",), count, tables=("instruments",)) == 1
    monkeypatch.setattr(version_cache, "MAX_AGE", 0.0)
    time.sleep(0.01)
    assert version_cache.cached(store, ("age",), count, tables=("instruments",)) == 2


def test_a_stamp_of_tables_moves_with_them_alone(store: GraphStore) -> None:
    whole, instruments = store.data_version(), store.data_version(["instruments"])
    store.bulk_insert_or_update_nodes("judgments", [_judgment("j")])
    assert store.data_version() != whole
    assert store.data_version(["instruments"]) == instruments
    store.bulk_insert_or_update_nodes("instruments", [_instrument("a")])
    assert store.data_version(["instruments"]) != instruments


def test_a_lasting_answer_is_computed_again_before_it_expires(
    store: GraphStore,
) -> None:
    """From ``REFRESH_AHEAD`` of its age on, a request takes the kept answer at once and
    the new one computes in the background (the feed waited ``STALE_WAIT`` for its counts
    once they had expired: 3.7 s on 10 Oct); the warm-up waits for the new one."""
    from lawgraph.db import store as store_module

    max_age = 0.4
    assert version_cache.lasting(store, ("ahead",), lambda: 1, max_age) == 1
    time.sleep(max_age * version_cache.REFRESH_AHEAD)
    computed = threading.Event()

    def slow() -> int:
        time.sleep(0.3)
        computed.set()
        return 2

    token = store_module.set_read_deadline(5.0)
    try:
        started = time.monotonic()
        assert version_cache.lasting(store, ("ahead",), slow, max_age) == 1
        assert time.monotonic() - started < 0.1  # not waited for
        assert computed.wait(2)
        assert version_cache.lasting(store, ("ahead",), slow, max_age) == 2
    finally:
        store_module.reset_read_deadline(token)
    # without a deadline (the warm-up) the new answer is waited for
    time.sleep(max_age * version_cache.REFRESH_AHEAD)
    assert version_cache.lasting(store, ("ahead",), lambda: 3, max_age) == 3
