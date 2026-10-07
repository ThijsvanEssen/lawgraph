"""Queries run side by side keep the deadline of the request: in their threads, and in how
long the request waits for them; and a pool shared by every request cannot wait for itself."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from lawgraph.db import store as store_module
from lawgraph.db.queries._helpers import side_by_side


def test_the_deadline_of_the_request_holds_in_the_threads() -> None:
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-side")
    token = store_module.set_read_deadline(5.0)
    try:
        left = side_by_side(pool, [store_module.read_time_left] * 3)
    finally:
        store_module.reset_read_deadline(token)
    assert all(t is not None and 0 < t <= 5.0 for t in left)
    # outside a request: no deadline in the threads either
    assert side_by_side(pool, [store_module.read_time_left]) == [None]


def test_the_request_waits_no_longer_than_its_deadline() -> None:
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-slow")
    token = store_module.set_read_deadline(0.2)
    started = time.monotonic()
    try:
        with pytest.raises(store_module.ReadTimedOut):
            side_by_side(pool, [lambda: time.sleep(1.0)])
    finally:
        store_module.reset_read_deadline(token)
    assert time.monotonic() - started < 0.6


def test_a_call_from_the_pool_itself_runs_its_calls_there() -> None:
    """With every thread of the pool waiting for calls queued behind them, it would hang."""
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-nest")

    def outer() -> list[int]:
        return side_by_side(pool, [lambda: 1, lambda: 2])

    assert side_by_side(pool, [outer]) == [[1, 2]]


def test_a_request_does_not_queue_behind_the_calls_of_others() -> None:
    """Every thread of the shared pool busy with a slow call of another request: the calls
    of this one run in its own thread, at once."""
    import threading

    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-busy")
    release = threading.Event()
    others = [
        pool.submit(release.wait, 5) for _ in range(2)
    ]  # not through side_by_side
    busy = threading.Thread(
        target=lambda: side_by_side(pool, [lambda: release.wait(5)] * 2)
    )
    busy.start()
    time.sleep(0.1)
    started = time.monotonic()
    try:
        assert side_by_side(pool, [lambda: 1, lambda: 2]) == [1, 2]
    finally:
        release.set()
        busy.join()
    assert time.monotonic() - started < 0.5
    assert all(f.result() for f in others)


def test_health_names_the_calls_the_shared_threads_run() -> None:
    import threading

    from lawgraph.db.queries._helpers import busy_calls

    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-named")
    release = threading.Event()

    def slow_count() -> bool:
        return release.wait(5)

    runner = threading.Thread(target=lambda: side_by_side(pool, [slow_count]))
    runner.start()
    time.sleep(0.2)
    try:
        running = [c for c in busy_calls() if c["thread"].startswith("test-named")]
    finally:
        release.set()
        runner.join()
    assert len(running) == 1
    assert running[0]["call"].endswith("slow_count")
    assert running[0]["seconds"] >= 0.1
    assert not [c for c in busy_calls() if c["thread"].startswith("test-named")]
