"""A data version that cannot be read: before one was read nothing is kept and every request
computes its answer, after it the version read before holds; the log says so once, not on
every request. One thread reads it at a time, within ``VERSION_READ``."""

from __future__ import annotations

import threading

import pytest

from lawgraph.db import version_cache
from lawgraph.db.request_context import (
    ReadTimedOut,
    read_time_left,
    reset_read_deadline,
    set_read_deadline,
)


class _Broken:
    """A database whose versions cannot be read (``lg_data_version`` gone)."""

    name = "unread"

    def __init__(self) -> None:
        self.failure: Exception | None = RuntimeError(
            "relation lg_data_version is gone"
        )

    def data_version(self) -> str:
        return "1"

    def table_versions(self) -> dict[str, int]:
        if self.failure is not None:
            raise self.failure
        return {"judgments": 1}


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]


def test_a_version_that_cannot_be_read_is_computed_and_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _Broken()
    computed: list[int] = []

    def compute() -> int:
        computed.append(1)
        return len(computed)

    with caplog.at_level("WARNING"):
        answers = [version_cache.cached(store, "count", compute) for _ in range(3)]
    assert answers == [1, 2, 3]  # nothing kept
    assert _warnings(caplog) == [
        "The data version cannot be read; every answer is computed anew:"
        " RuntimeError: relation lg_data_version is gone"
    ]


def test_another_failure_and_one_after_a_read_are_logged_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _Broken()
    with caplog.at_level("WARNING"):
        version_cache.cached(store, "count", lambda: 0)
        store.failure = OSError("connection refused")
        version_cache.cached(store, "count", lambda: 0)
        store.failure = None
        version_cache.cached(store, "count", lambda: 0)  # read: kept from now on
        store.failure = OSError("connection refused")
        version_cache.cached(store, "count", lambda: 0)
    assert [w.rsplit(": ", 1)[1] for w in _warnings(caplog)] == [
        "relation lg_data_version is gone",
        "connection refused",
        "connection refused",
    ]


def test_a_store_without_a_version_keeps_nothing_and_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = object()
    with caplog.at_level("WARNING"):
        assert version_cache.cached(store, "count", lambda: 1) == 1
    assert not isinstance(store, version_cache.VersionedStore)
    assert _warnings(caplog) == []


def test_a_failed_read_after_a_read_keeps_the_version_and_its_answers() -> None:
    store = _Broken()
    store.failure = None
    computed: list[int] = []

    def compute() -> int:
        computed.append(1)
        return len(computed)

    assert version_cache.cached(store, "count", compute) == 1
    store.failure = OSError("connection refused")
    assert version_cache.cached(store, "count", compute) == 1  # kept, not computed anew
    assert computed == [1]


def test_a_read_that_finds_no_free_connection_is_no_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _Broken()
    store.failure = None
    version_cache.cached(store, "count", lambda: 1)
    store.failure = ReadTimedOut("No connection of the pool came free.")
    with caplog.at_level("WARNING"):
        assert version_cache.cached(store, "count", lambda: 2) == 1
    assert _warnings(caplog) == []


def test_the_read_waits_for_a_connection_no_longer_than_version_read() -> None:
    left: list[float | None] = []

    class _Timed(_Broken):
        def table_versions(self) -> dict[str, int]:
            left.append(read_time_left())
            return {"judgments": 1}

    token = set_read_deadline(30.0)  # a request with time to spare
    try:
        version_cache.cached(_Timed(), "count", lambda: 1)
        assert read_time_left() == pytest.approx(30.0, abs=1.0)  # its own deadline back
    finally:
        reset_read_deadline(token)
    version_cache.cached(_Timed(), "count", lambda: 1)  # the warm-up: no deadline
    assert [x is not None and x <= version_cache.VERSION_READ for x in left] == [
        True,
        True,
    ]


def test_one_thread_reads_the_version_while_the_others_take_the_known_one() -> None:
    reading = threading.Event()
    release = threading.Event()
    reads: list[int] = []

    class _Slow(_Broken):
        def table_versions(self) -> dict[str, int]:
            reads.append(1)
            if len(reads) == 2:
                reading.set()
                release.wait(5)
            return {"judgments": 1}

    store = _Slow()
    version_cache.cached(store, "count", lambda: 1)  # a version known
    slow = threading.Thread(target=version_cache.cached, args=(store, "count", int))
    slow.start()
    assert reading.wait(5)
    try:
        assert (
            version_cache.cached(store, "count", lambda: 2) == 1
        )  # no read of its own
        assert len(reads) == 2
    finally:
        release.set()
        slow.join(5)
