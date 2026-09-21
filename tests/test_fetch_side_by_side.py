"""Downloads of one source run side by side; the pacer of the host still spaces them."""

from __future__ import annotations

import threading
import time

import pytest

from lawgraph.pipelines.base import STOP
from lawgraph.pipelines.retrieve.base import fetched_side_by_side


def test_the_latency_of_one_request_is_not_the_limit() -> None:
    """At 0.2 s a request, 5 a second was the ceiling whatever the host allows."""

    def fetch(name: str) -> str:
        time.sleep(0.05)
        return name.upper()

    names = [f"ecli-{n}" for n in range(40)]
    started = time.monotonic()
    fetched = list(fetched_side_by_side(names, fetch, workers=8))
    assert time.monotonic() - started < 40 * 0.05 / 3  # one by one: 2.0 s
    assert fetched == [(name, name.upper()) for name in names]  # in the order asked


def test_a_failure_is_handed_over_with_its_id_and_the_rest_goes_on() -> None:
    def fetch(name: str) -> str:
        if name == "b":
            raise RuntimeError("no route")
        return name

    fetched = dict(fetched_side_by_side(["a", "b", "c"], fetch, workers=2))
    assert fetched["a"] == "a" and fetched["c"] == "c"
    assert isinstance(fetched["b"], RuntimeError)


def test_no_more_is_asked_for_than_is_being_used() -> None:
    """12,000 judgments are not downloaded ahead of the writer."""
    under_way = 0
    peak = 0
    lock = threading.Lock()

    def fetch(name: str) -> str:
        nonlocal under_way, peak
        with lock:
            under_way += 1
            peak = max(peak, under_way)
        time.sleep(0.01)
        with lock:
            under_way -= 1
        return name

    asked: list[str] = []

    def names():
        for n in range(200):
            asked.append(str(n))
            yield str(n)

    results = fetched_side_by_side(names(), fetch, workers=4)
    next(results)
    assert peak <= 4 and len(asked) <= 4 * 4  # a window, not the whole list
    assert len(list(results)) == 199


def test_an_interrupt_stops_asking() -> None:
    def fetch(name: str) -> str:
        time.sleep(0.01)
        return name

    results = fetched_side_by_side((str(n) for n in range(1000)), fetch, workers=2)
    next(results)
    STOP.set()
    try:
        with pytest.raises(KeyboardInterrupt):
            list(results)
    finally:
        STOP.clear()
