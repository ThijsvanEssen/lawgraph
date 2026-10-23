"""A read its caller leaves before its last row (``next(iter(store.query(...)))``, a
``for`` left by an exception) gives its connection back to the pool without a transaction,
whichever thread drops it: also the garbage collector, at any point of any thread, holding
whatever lock that thread holds (``store._abandon``)."""

from __future__ import annotations

import gc
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.db import GraphStore, request_context
from lawgraph.db import store as store_module

ROWS = "SELECT n FROM generate_series(1, 5000) AS n"


@pytest.fixture()
def no_gc() -> Iterator[None]:
    """No collection but the one the test makes."""
    gc.disable()
    try:
        yield
    finally:
        gc.enable()


def _in_transaction() -> list[dict[str, Any]]:
    return [
        row
        for row in store_module.own_activity(0.0)
        if row["state"].startswith("idle in transaction")
    ]


def _free(store: GraphStore) -> int:
    usage = store.pool_usage()["requests"]
    assert usage is not None
    return usage["free"]


def _all_free(store: GraphStore) -> bool:
    size = store.pool.get_stats().get("pool_size", 0)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if _free(store) == size:
            return True
        time.sleep(0.05)
    return False


def _abandon_in_a_cycle(store: GraphStore) -> None:
    """A read left after its first row, kept alive by a reference cycle: only the garbage
    collector frees it."""
    rows = store.query(ROWS, batch_size=10)
    assert next(rows) == 1
    cycle: dict[str, Any] = {"rows": rows}
    cycle["self"] = cycle


def test_a_read_left_after_its_first_row_gives_its_connection_back(
    store: GraphStore,
) -> None:
    first = next(iter(store.query(ROWS, batch_size=10)))
    assert first == 1
    assert _all_free(store)
    assert _in_transaction() == []


def test_a_read_the_collector_frees_under_its_requests_lock_does_not_hang(
    store: GraphStore, no_gc: None
) -> None:
    """The collector runs in the thread that allocates, wherever it is: here in the
    ``Cancellation.cancel`` of the read's own request, under its lock (the server sends a
    disconnect at the end of every request). A read that gave its connection back there
    took that lock again and waited for ever: the thread, and with it every collection of
    the process after it, so every read left in a cycle kept its connection idle in a
    transaction (23 Oct 00:55 UTC)."""
    cancellation = request_context.Cancellation()
    token = request_context.set_cancellation(cancellation)
    try:
        _abandon_in_a_cycle(store)
    finally:
        request_context.reset_cancellation(token)

    def collect_under_the_lock() -> None:
        with cancellation._lock:
            gc.collect()

    collector = threading.Thread(target=collect_under_the_lock, daemon=True)
    collector.start()
    collector.join(timeout=5)
    assert not collector.is_alive(), "the collector waited for the lock it held"
    assert _all_free(store)
    assert _in_transaction() == []


def test_a_cancel_reaches_no_connection_given_back(store: GraphStore) -> None:
    """A read that ended took its connection out of its request's ``Cancellation``: a
    cancel after it does not reach that connection when another request reads on it."""
    cancellation = request_context.Cancellation()
    token = request_context.set_cancellation(cancellation)
    try:
        assert list(store.query("SELECT 1 AS one")) == [1]
        next(iter(store.query(ROWS, batch_size=10)))
    finally:
        request_context.reset_cancellation(token)
    assert _all_free(store)
    assert cancellation._connections == set()
